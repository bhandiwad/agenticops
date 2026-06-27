"""Send a resume signal to a running WorkflowRunner (HITL resume).

Used by the approvals API when a workflow-gated approval is decided, and by the
PoC runner to validate the pause→signal→resume mechanism. Synchronous wrapper so
it is callable from the (sync) Flask approvals path.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("workflows_v2.signal")


async def _signal(workflow_id: str, node_id: str, data: dict) -> None:
    from temporalio.client import Client
    client = await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "temporal:7233"),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
    )
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("resume_node", args=[node_id, data])


def signal_resume(workflow_id: str, node_id: str, data: dict) -> bool:
    """Signal a running run to resume ``node_id`` with ``data``. Returns success.
    Never raises (returns False if Temporal is unreachable / not configured)."""
    if not (workflow_id and node_id):
        return False
    try:
        asyncio.run(_signal(workflow_id, node_id, data or {}))
        return True
    except Exception:
        logger.warning("wf-v2: signal_resume failed (temporal unreachable?)", exc_info=True)
        return False
