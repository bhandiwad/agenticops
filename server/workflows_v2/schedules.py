"""Schedule (cron) triggers for Workflow V2, backed by Temporal Schedules.

Embeds a snapshot of the def's graph + the creating user's context into the
schedule action, so each fire starts a WorkflowRunner run. Re-create the schedule
after editing a def to refresh the snapshot. Sync wrappers for the Flask route.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("workflows_v2.schedules")


def _sid(org_id: str, key: str) -> str:
    return f"wf2-sched-{(org_id or '')[:8]}-{key}"


async def _connect():
    from temporalio.client import Client
    return await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", ""),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
    )


async def _upsert(schedule_id: str, graph: dict, context: dict, cron: str, task_queue: str):
    from temporalio.client import (
        Schedule, ScheduleActionStartWorkflow, ScheduleSpec,
    )
    client = await _connect()
    action = ScheduleActionStartWorkflow(
        "WorkflowRunner", {"graph": graph, "context": context},
        id=f"{schedule_id}-run", task_queue=task_queue,
    )
    sched = Schedule(action=action, spec=ScheduleSpec(cron_expressions=[cron]))
    try:
        await client.create_schedule(schedule_id, sched)
    except Exception:
        # Already exists -> replace it with the new snapshot/cron.
        handle = client.get_schedule_handle(schedule_id)
        try:
            await handle.delete()
        except Exception:
            pass
        await client.create_schedule(schedule_id, sched)


def upsert_schedule(key: str, graph: dict, context: dict, cron: str) -> dict:
    if not os.getenv("TEMPORAL_ADDRESS"):
        return {"ok": False, "error": "Temporal is not configured"}
    sid = _sid(context.get("org_id", ""), key)
    try:
        asyncio.run(_upsert(sid, graph, context, cron,
                            os.getenv("TEMPORAL_TASK_QUEUE", "aurora-workflows-v2")))
        return {"ok": True, "schedule_id": sid, "cron": cron}
    except Exception as e:  # noqa: BLE001
        logger.exception("wf-v2: upsert_schedule failed")
        return {"ok": False, "error": str(e)[:200]}


def delete_schedule(key: str, org_id: str) -> dict:
    if not os.getenv("TEMPORAL_ADDRESS"):
        return {"ok": False, "error": "Temporal is not configured"}
    sid = _sid(org_id, key)

    async def _del():
        client = await _connect()
        await client.get_schedule_handle(sid).delete()

    try:
        asyncio.run(_del())
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


def set_paused(key: str, org_id: str, paused: bool) -> dict:
    """Pause/unpause the def's Temporal schedule if one exists. Best-effort."""
    if not os.getenv("TEMPORAL_ADDRESS"):
        return {"ok": True, "note": "no temporal"}
    sid = _sid(org_id, key)

    async def _do():
        client = await _connect()
        handle = client.get_schedule_handle(sid)
        if paused:
            await handle.pause()
        else:
            await handle.unpause()

    try:
        asyncio.run(_do())
        return {"ok": True}
    except Exception as e:  # noqa: BLE001 - schedule may not exist
        return {"ok": False, "error": str(e)[:120]}


def trigger_now(key: str, org_id: str) -> dict:
    """Fire the schedule immediately (manual run / validation)."""
    if not os.getenv("TEMPORAL_ADDRESS"):
        return {"ok": False, "error": "Temporal is not configured"}
    sid = _sid(org_id, key)

    async def _trig():
        client = await _connect()
        await client.get_schedule_handle(sid).trigger()

    try:
        asyncio.run(_trig())
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}
