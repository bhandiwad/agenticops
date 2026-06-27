"""Trigger the Epic #1 vertical-slice PoC run and print the result.

Run with: ``python -m workflows_v2.poc_run`` (requires AURORA_WORKFLOWS_V2=true).
Starts the generic WorkflowRunner on the sample agent->set graph and prints the
resolved node outputs, proving Temporal + interpreter + data passing end-to-end.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from temporalio.client import Client

from workflows_v2.interpreter import WorkflowRunner
from workflows_v2.sample_graphs import SAMPLE_AGENT_TO_SET


async def main() -> int:
    if os.getenv("AURORA_WORKFLOWS_V2", "").strip().lower() not in ("1", "true", "yes"):
        print("AURORA_WORKFLOWS_V2 not enabled; refusing to run PoC")
        return 2

    addr = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("TEMPORAL_TASK_QUEUE", "aurora-workflows-v2")

    client = await Client.connect(addr, namespace=namespace)
    handle = await client.start_workflow(
        WorkflowRunner.run,
        {"graph": SAMPLE_AGENT_TO_SET, "context": {"incident_id": "poc-demo"}},
        id="poc-agent-to-set",
        task_queue=task_queue,
    )
    print(f"started workflow id={handle.id}")
    result = await handle.result()
    print("RESULT:")
    print(json.dumps(result, indent=2))

    # Assert the data plane worked: s1 consumed a1's output.
    s1 = (result.get("node_outputs", {}).get("s1", {}) or {}).get("output", {}) or {}
    ok = s1.get("headline") == "Summary: [PoC] summarizer_agent executed" and s1.get("agent_ran") == "summarizer_agent"
    print("DATA_PASSING_OK" if ok else "DATA_PASSING_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
