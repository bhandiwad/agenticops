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
import uuid

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

    # Resolve a real org/user so persistence (RLS) is exercised. Best-effort:
    # falls back to no DB context (log-only persistence) if the DB isn't reachable.
    real_agent = os.getenv("POC_REAL_AGENT", "").strip().lower() in ("1", "true", "yes")
    incident_id = os.getenv("POC_INCIDENT_ID") or str(uuid.uuid4())
    ctx = {"incident_id": incident_id, "real_agent": real_agent}
    try:
        from utils.db.connection_pool import db_pool
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, org_id FROM users ORDER BY created_at LIMIT 1")
                row = cur.fetchone()
        if row:
            ctx["user_id"], ctx["org_id"] = row[0], row[1]
            print(f"using org={row[1]} for RLS persistence")
    except Exception as e:
        print(f"(no DB context: {e}); persistence will be log-only")

    client = await Client.connect(addr, namespace=namespace)
    handle = await client.start_workflow(
        WorkflowRunner.run,
        {"graph": SAMPLE_AGENT_TO_SET, "context": ctx},
        id=f"poc-agent-to-set-{os.getpid()}",
        task_queue=task_queue,
    )
    print(f"started workflow id={handle.id}")
    result = await handle.result()
    print("RESULT:")
    print(json.dumps(result, indent=2))

    node_outputs = result.get("node_outputs", {})
    a1 = (node_outputs.get("a1", {}) or {}).get("output", {}) or {}
    s1 = (node_outputs.get("s1", {}) or {}).get("output", {}) or {}

    if real_agent:
        # Real agent ran: output must be non-empty, completed, and NOT the stub.
        summary = a1.get("summary") or ""
        ok = bool(summary) and "[PoC]" not in summary and a1.get("status") == "completed"
        print(f"a1.status={a1.get('status')} summary_len={len(summary)}")
        print("REAL_AGENT_OK" if ok else "REAL_AGENT_FAILED")
    else:
        # Stub path: s1 consumed a1's stub output via expression.
        ok = s1.get("headline") == "Summary: [PoC] summarizer_agent executed" and s1.get("agent_ran") == "summarizer_agent"
        print("DATA_PASSING_OK" if ok else "DATA_PASSING_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
