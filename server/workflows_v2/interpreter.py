"""The generic node-graph interpreter as a Temporal workflow.

``WorkflowRunner`` takes a graph definition (data) and walks it deterministically:
for each node it resolves config expressions against prior node outputs, then
executes a typed activity and stores the result. Activities are referenced by
*name* (string) so this module never imports the activity implementations into
the workflow sandbox.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from workflows_v2.expressions import resolve, topo_order

# node type -> activity name registered on the worker
_ACTIVITY_FOR = {
    "agent": "run_agent",
    "action": "run_action",
    "set": "run_set",
}


@workflow.defn(name="WorkflowRunner")
class WorkflowRunner:
    @workflow.run
    async def run(self, payload: dict) -> dict:
        graph = payload.get("graph", {}) or {}
        context = payload.get("context", {}) or {}
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges = graph.get("edges", []) or []

        node_outputs: dict = {}
        scope = {"$node": node_outputs, "$context": context}

        for nid in topo_order(nodes, edges):
            node = nodes[nid]
            ntype = node.get("type")
            activity_name = _ACTIVITY_FOR.get(ntype)
            cfg = resolve(node.get("config", {}) or {}, scope)

            if not activity_name:
                node_outputs[nid] = {"output": None, "status": "skipped",
                                     "note": f"no handler for type {ntype!r}"}
                continue

            workflow.logger.info("WorkflowRunner: node %s (%s)", nid, ntype)
            out = await workflow.execute_activity(
                activity_name,
                {"node_id": nid, "type": ntype, "ref": node.get("ref", ""),
                 "config": cfg, "context": context},
                start_to_close_timeout=timedelta(seconds=int(node.get("timeout_s", 120))),
            )
            node_outputs[nid] = {"output": out, "status": "completed"}

            # Best-effort mirror to Postgres for the UI/history (Epic #2 fills this in).
            try:
                await workflow.execute_activity(
                    "persist_node_run",
                    {"node_id": nid, "type": ntype, "status": "completed", "output": out},
                    start_to_close_timeout=timedelta(seconds=15),
                )
            except Exception:  # noqa: BLE001 - persistence is non-fatal in the PoC
                workflow.logger.warning("persist_node_run failed for %s (non-fatal)", nid)

        return {"status": "completed", "node_outputs": node_outputs}
