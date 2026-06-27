"""Start Workflow V2 runs from the app (aurora-server) via the Temporal client.

Used by the "Run" action in the Flow Builder. Synchronous wrapper so it is callable
from the Flask route. Requires TEMPORAL_ADDRESS (set once aurora-server is wired to
Temporal); returns a structured result instead of raising.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

logger = logging.getLogger("workflows_v2.client")


async def _start(graph: dict, context: dict, workflow_id: str, task_queue: str, addr: str, ns: str) -> str:
    from temporalio.client import Client
    client = await Client.connect(addr, namespace=ns)
    handle = await client.start_workflow(
        "WorkflowRunner",
        {"graph": graph, "context": context},
        id=workflow_id,
        task_queue=task_queue,
    )
    return handle.id


def start_run(graph: dict, context: dict, workflow_id: str | None = None) -> dict:
    """Start a WorkflowRunner execution for ``graph``. Returns
    ``{ok, workflow_id}`` or ``{ok: False, error}``. A caller-supplied
    ``workflow_id`` makes the start idempotent (Temporal rejects a duplicate id —
    treated as already-running, not an error)."""
    addr = os.getenv("TEMPORAL_ADDRESS")
    if not addr:
        return {"ok": False, "error": "Temporal is not configured (TEMPORAL_ADDRESS unset)"}
    wid = workflow_id or f"wf2-{(graph.get('key') or 'run')}-{uuid.uuid4().hex[:10]}"
    try:
        wfid = asyncio.run(_start(
            graph, context, wid,
            os.getenv("TEMPORAL_TASK_QUEUE", "aurora-workflows-v2"),
            addr,
            os.getenv("TEMPORAL_NAMESPACE", "default"),
        ))
        return {"ok": True, "workflow_id": wfid}
    except Exception as e:  # noqa: BLE001 - surfaced to the caller
        # A duplicate workflow_id (idempotent re-fire) is fine, not a failure.
        if "already" in str(e).lower():
            return {"ok": True, "workflow_id": wid, "already_running": True}
        logger.exception("wf-v2: start_run failed")
        return {"ok": False, "error": str(e)[:200]}


def dispatch_rca_enrichment(user_id: str, org_id: str, incident_id: str | None) -> list:
    """Fire the org's RCA-enrichment workflows (read-only, graph.rca_enrichment +
    enabled) for an incident. Idempotent per (incident, workflow) so it's safe to
    call on every RCA dispatch wave. Best-effort; returns the keys started."""
    if not (user_id and org_id):
        return []
    try:
        from services.workflows.defs import list_defs
        defs = [d for d in list_defs(user_id, org_id)
                if d.get("enabled") and (d.get("graph") or {}).get("rca_enrichment")]
    except Exception:
        return []
    started = []
    inc = incident_id or "adhoc"
    for d in defs:
        wid = f"wf2-rcaenrich-{inc}-{d['key']}"
        res = start_run(d["graph"], {"user_id": user_id, "org_id": org_id, "incident_id": incident_id}, workflow_id=wid)
        if res.get("ok"):
            started.append(d["key"])
    return started
