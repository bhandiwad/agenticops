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

    if ctx.get("real_agent") and ctx.get("user_id"):
        import asyncio
        from workflows_v2.agent_runner import run_agent_node
        activity.logger.info("[run_agent REAL] %s", ref)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, run_agent_node, ctx["user_id"], ref, ctx.get("incident_id"), ctx, None,
        )

    activity.logger.info("[run_agent stub] %s", ref)
    return {
        "agent": ref,
        "summary": f"[PoC] {ref} executed",
        "items": [{"finding": "stub-finding", "severity": "info"}],
    }


@activity.defn
async def run_action(payload: dict) -> dict:
    """PoC STUB for an Aurora Action node (Epic #3 returns real action output)."""
    ref = payload.get("ref") or "action"
    activity.logger.info("[PoC run_action] %s", ref)
    return {"action": ref, "status": "stub"}


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
