"""Temporal activities for the node-graph interpreter (PoC).

Activities do the side-effecting work and run outside the workflow sandbox, so
they may import freely. In the PoC ``run_agent``/``run_action`` are clearly
labelled stubs; Epic #3 replaces ``run_agent`` with a synchronous invocation of
the real agent run path (returning findings), and Epic #2 makes
``persist_node_run`` write to ``workflow_node_runs`` with RLS context.
"""

from __future__ import annotations

from temporalio import activity


@activity.defn
async def run_agent(payload: dict) -> dict:
    """Run an agent node.

    When the run context opts in (``context.real_agent`` truthy + a ``user_id``),
    invoke the real agent synchronously (Epic #3) in a worker thread and return
    its findings. Otherwise return the lightweight stub (fast default for demos).
    """
    ref = payload.get("ref") or "agent"
    ctx = payload.get("context", {}) or {}

    if ctx.get("user_id") and ctx.get("real_agent", True):
        import asyncio
        from workflows_v2.agent_runner import run_agent_node
        purpose = (payload.get("config") or {}).get("purpose")
        activity.logger.info("[run_agent REAL] %s", ref)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, run_agent_node, ctx["user_id"], ref, ctx.get("incident_id"), ctx, None, purpose,
        )

    activity.logger.info("[run_agent stub] %s", ref)
    return {
        "agent": ref,
        "summary": f"[PoC] {ref} executed",
        "items": [{"finding": "stub-finding", "severity": "info"}],
    }


@activity.defn
async def run_action(payload: dict) -> dict:
    """Execute an Aurora Action (by id in ``ref``) synchronously and return its
    output. Runs in a worker thread so the blocking background-chat path is safe."""
    ref = payload.get("ref") or ""
    ctx = payload.get("context", {}) or {}
    if not (ref and ctx.get("user_id")):
        return {"action": ref, "status": "error", "error": "missing action ref or user context"}
    import asyncio
    from workflows_v2.agent_runner import run_action_node
    activity.logger.info("[run_action] %s", ref)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_action_node, ctx["user_id"], ref, ctx.get("incident_id"), ctx)


@activity.defn
async def run_http(payload: dict) -> dict:
    """HTTP Request node — call any API/runbook/automation endpoint. No implicit
    server credentials (only the headers the node provides). Blocks the metadata
    endpoint; caps response size."""
    import asyncio as _asyncio
    cfg = payload.get("config", {}) or {}

    def _do() -> dict:
        import json as _json
        import socket
        import ipaddress
        from urllib.parse import urlparse
        import requests

        method = (cfg.get("method") or "GET").upper()
        url = cfg.get("url") or ""
        if not url:
            return {"ok": False, "error": "url is required"}
        headers = cfg.get("headers") or {}
        if isinstance(headers, str):
            try:
                headers = _json.loads(headers)
            except Exception:
                headers = {}
        # SSRF guard: refuse cloud-metadata / link-local targets.
        try:
            host = urlparse(url).hostname or ""
            ip = socket.gethostbyname(host) if host else ""
            if ip and (ipaddress.ip_address(ip).is_link_local or ip == "169.254.169.254"):
                return {"ok": False, "error": "blocked host (metadata/link-local)"}
        except Exception:
            pass
        kw: dict = {"headers": headers, "timeout": int(cfg.get("timeout_s", 30))}
        body = cfg.get("body")
        if isinstance(body, (dict, list)):
            kw["json"] = body
        elif body:
            kw["data"] = str(body)
        try:
            resp = requests.request(method, url, **kw)
            out: dict = {"ok": resp.ok, "status": resp.status_code, "body": resp.text[:8000]}
            try:
                out["json"] = resp.json()
            except Exception:
                pass
            return out
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:200]}

    return await _asyncio.get_event_loop().run_in_executor(None, _do)


@activity.defn
async def load_def_graph(payload: dict) -> dict:
    """Load a workflow def's graph by key (for the sub-workflow + error-handler nodes)."""
    ctx = payload.get("context", {}) or {}
    user_id, org_id, key = ctx.get("user_id"), ctx.get("org_id"), payload.get("key")
    if not (user_id and org_id and key):
        return {}
    try:
        from services.workflows.defs import get_def
        d = get_def(user_id, org_id, key)
        return (d or {}).get("graph", {}) or {}
    except Exception:
        activity.logger.warning("load_def_graph failed for %s", key)
        return {}


@activity.defn
async def start_workflow_by_key(payload: dict) -> dict:
    """Fire-and-forget start of another workflow by key (error-handler hook)."""
    ctx = payload.get("context", {}) or {}
    user_id, org_id, key = ctx.get("user_id"), ctx.get("org_id"), payload.get("key")
    if not (user_id and org_id and key):
        return {"ok": False}
    try:
        from services.workflows.defs import get_def
        from workflows_v2.client import start_run
        d = get_def(user_id, org_id, key)
        if not d:
            return {"ok": False, "error": "not found"}
        return start_run(d["graph"], ctx)
    except Exception:
        activity.logger.warning("start_workflow_by_key failed for %s", key)
        return {"ok": False}


@activity.defn
async def run_set(payload: dict) -> dict:
    """Data-shaping node. ``config`` arrives with expressions already resolved by
    the interpreter, so this simply returns it as the node output."""
    return dict(payload.get("config", {}) or {})


def _ids(payload: dict):
    ctx = payload.get("context", {}) or {}
    return ctx.get("user_id"), ctx.get("org_id")


@activity.defn
async def create_run(payload: dict) -> dict:
    """Create a workflow_runs row; returns {run_id}. Non-fatal: returns {} on miss."""
    from workflows_v2 import store
    user_id, org_id = _ids(payload)
    if not (user_id and org_id):
        return {}
    run_id = store.create_run(
        user_id, org_id,
        workflow_key=payload.get("workflow_key", "adhoc"),
        temporal_run_id=payload.get("temporal_run_id"),
        incident_id=(payload.get("context", {}) or {}).get("incident_id"),
    )
    return {"run_id": run_id}


@activity.defn
async def finish_run(payload: dict) -> None:
    from workflows_v2 import store
    user_id, org_id = _ids(payload)
    if user_id and org_id:
        store.finish_run(user_id, org_id, payload.get("run_id"), payload.get("status", "completed"))
    return None


@activity.defn
async def create_hitl(payload: dict) -> dict:
    """Register a pending HITL record so the approvals API can resume the run via a
    Temporal signal (resume_payload carries the workflow id + node id). Best-effort:
    needs user/org context; otherwise the node is resumable only by direct signal."""
    ctx = payload.get("context", {}) or {}
    user_id, org_id = ctx.get("user_id"), ctx.get("org_id")
    if not (user_id and org_id):
        activity.logger.info("[create_hitl] node=%s has no DB context; direct-signal only",
                             payload.get("node_id"))
        return {}
    try:
        from services.policy.approvals import create_approval_safe
        cfg = payload.get("config", {}) or {}
        approval_id = create_approval_safe(
            user_id,
            tool_name=f"wf_v2:{payload.get('node_type')}",
            summary=cfg.get("summary") or f"Workflow waiting at node {payload.get('node_id')}",
            incident_id=ctx.get("incident_id"),
            resume_payload={
                "kind": "wf_v2_signal",
                "temporal_workflow_id": payload.get("temporal_workflow_id"),
                "node_id": payload.get("node_id"),
            },
        )
        return {"approval_id": approval_id}
    except Exception:
        activity.logger.warning("[create_hitl] failed (non-fatal)")
        return {}


@activity.defn
async def persist_node_run(payload: dict) -> None:
    """Mirror a node's input/output/status to workflow_node_runs (RLS-scoped).
    Non-fatal: logs only if user/org context is absent (e.g. the bare PoC run)."""
    from workflows_v2 import store
    user_id, org_id = _ids(payload)
    if not (user_id and org_id and payload.get("run_id")):
        activity.logger.info("[persist_node_run] node=%s status=%s (no DB context)",
                             payload.get("node_id"), payload.get("status"))
        return None
    store.persist_node_run(
        user_id, org_id, payload.get("run_id"), payload.get("node_id"),
        payload.get("node_type", ""), payload.get("status", ""),
        payload.get("input", {}) or {}, payload.get("output"),
    )
    return None
