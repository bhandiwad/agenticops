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
    """PoC STUB. Real synchronous agent execution is Epic #3.

    Returns a structured output so downstream nodes can consume it via
    expressions (this is what proves the data plane end-to-end).
    """
    ref = payload.get("ref") or "agent"
    activity.logger.info("[PoC run_agent] %s", ref)
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
