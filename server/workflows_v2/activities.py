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


@activity.defn
async def persist_node_run(payload: dict) -> None:
    """PoC: log only. Epic #2 writes to ``workflow_node_runs`` (RLS-scoped)."""
    activity.logger.info(
        "[PoC persist_node_run] node=%s status=%s",
        payload.get("node_id"), payload.get("status"),
    )
    return None
