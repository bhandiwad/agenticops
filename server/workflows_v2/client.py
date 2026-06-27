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


def start_run(graph: dict, context: dict) -> dict:
    """Start a WorkflowRunner execution for ``graph``. Returns
    ``{ok, workflow_id}`` or ``{ok: False, error}``."""
    addr = os.getenv("TEMPORAL_ADDRESS")
    if not addr:
        return {"ok": False, "error": "Temporal is not configured (TEMPORAL_ADDRESS unset)"}
    workflow_id = f"wf2-{(graph.get('key') or 'run')}-{uuid.uuid4().hex[:10]}"
    try:
        wfid = asyncio.run(_start(
            graph, context, workflow_id,
            os.getenv("TEMPORAL_TASK_QUEUE", "aurora-workflows-v2"),
            addr,
            os.getenv("TEMPORAL_NAMESPACE", "default"),
        ))
        return {"ok": True, "workflow_id": wfid}
    except Exception as e:  # noqa: BLE001 - surfaced to the caller
        logger.exception("wf-v2: start_run failed")
        return {"ok": False, "error": str(e)[:200]}
