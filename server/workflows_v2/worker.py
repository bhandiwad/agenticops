"""aurora-temporal-worker: hosts the WorkflowRunner interpreter + activities.

Run with: ``python -m workflows_v2.worker``
Env: TEMPORAL_ADDRESS (default temporal:7233), TEMPORAL_NAMESPACE (default),
     TEMPORAL_TASK_QUEUE (default aurora-workflows-v2).
"""

from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from workflows_v2 import activities
from workflows_v2.interpreter import WorkflowRunner

logger = logging.getLogger("workflows_v2.worker")

TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "aurora-workflows-v2")


async def _connect_with_retry(addr: str, namespace: str, attempts: int = 40, delay: float = 3.0) -> Client:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await Client.connect(addr, namespace=namespace)
        except Exception as e:  # noqa: BLE001 - retry until the server is up
            last = e
            logger.warning("temporal connect retry %d/%d: %s", i + 1, attempts, e)
            await asyncio.sleep(delay)
    raise RuntimeError(f"could not connect to temporal at {addr}: {last}")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    addr = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")

    client = await _connect_with_retry(addr, namespace)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[WorkflowRunner],
        activities=[
            activities.run_agent,
            activities.run_action,
            activities.run_set,
            activities.run_http,
            activities.load_def_graph,
            activities.start_workflow_by_key,
            activities.create_run,
            activities.finish_run,
            activities.create_hitl,
            activities.persist_node_run,
        ],
    )
    logger.info("aurora-temporal-worker started addr=%s ns=%s queue=%s", addr, namespace, TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
