"""The generic node-graph interpreter as a Temporal workflow.

``WorkflowRunner`` takes a graph definition (data) and walks it deterministically.
Side-effecting nodes (agent/action/set) run as activities referenced by *name*
(string), so this module never imports activity implementations into the workflow
sandbox. Control-flow nodes (if/switch/merge/foreach) are evaluated inline because
they are pure + deterministic.

Branching model: a node executes only if it has an *active* incoming edge (roots
are active). Normal nodes activate all outgoing edges; ``if``/``switch`` activate
only the edge(s) whose ``port`` matches the decision, so untaken branches are
skipped.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows_v2.expressions import resolve, topo_order, eval_condition

# node type -> activity name registered on the worker
_ACTIVITY_FOR = {
    "agent": "run_agent",
    "action": "run_action",
    "set": "run_set",
    "http": "run_http",
}
# node types evaluated inline (pure, no activity)
_INLINE = {"if", "switch", "merge", "foreach"}
# human-in-the-loop / wait nodes that pause until a signal (or timer)
_HITL = {"approval", "form", "wait_webhook"}


@workflow.defn(name="WorkflowRunner")
class WorkflowRunner:
    def __init__(self) -> None:
        # node_id -> resume payload, set by the resume_node signal.
        self._signals: dict = {}

    @workflow.signal
    def resume_node(self, node_id: str, data: dict) -> None:
        """Resume a waiting HITL node (approval decision / form inputs / webhook)."""
        self._signals[node_id] = data or {}

    @workflow.run
    async def run(self, payload: dict) -> dict:
        graph = payload.get("graph", {}) or {}
        context = payload.get("context", {}) or {}
        workflow_key = graph.get("key", "adhoc")
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        edges = graph.get("edges", []) or []

        node_outputs: dict = {}
        scope = {"$node": node_outputs, "$context": context}

        # Activation state for branching. Roots (no incoming edge) start active.
        indeg = {nid: 0 for nid in nodes}
        for e in edges:
            if e.get("target") in indeg and e.get("source") in nodes:
                indeg[e["target"]] += 1
        node_active = {nid: (indeg[nid] == 0) for nid in nodes}
        activated_edges: set = set()

        def activate_outgoing(src: str, port=None) -> None:
            for e in edges:
                if e.get("source") != src:
                    continue
                ep = e.get("port")
                take = (port is None) or (ep == port) or (ep == "*")
                if take:
                    activated_edges.add((src, e.get("target")))
                    if e.get("target") in node_active:
                        node_active[e["target"]] = True

        run_id = None
        try:
            created = await workflow.execute_activity(
                "create_run",
                {"workflow_key": workflow_key, "context": context,
                 "temporal_run_id": workflow.info().run_id},
                start_to_close_timeout=timedelta(seconds=15),
            )
            run_id = (created or {}).get("run_id")
        except Exception:
            workflow.logger.warning("create_run failed (non-fatal); continuing without persistence")

        for nid in topo_order(nodes, edges):
            node = nodes[nid]
            ntype = node.get("type")

            if not node_active.get(nid, False):
                node_outputs[nid] = {"output": None, "status": "skipped"}
                await self._persist(run_id, nid, ntype, "skipped", {}, None, context)
                continue

            cfg = resolve(node.get("config", {}) or {}, scope)

            # ---- inline control-flow / data nodes ----
            if ntype == "if":
                result = eval_condition(cfg)
                node_outputs[nid] = {"output": {"result": result}, "status": "completed"}
                activate_outgoing(nid, port=("true" if result else "false"))
                await self._persist(run_id, nid, ntype, "completed", cfg, {"result": result}, context)
                continue
            if ntype == "switch":
                value = cfg.get("value")
                ports = {e.get("port") for e in edges if e.get("source") == nid}
                chosen = str(value) if str(value) in ports else "default"
                node_outputs[nid] = {"output": {"value": value, "port": chosen}, "status": "completed"}
                activate_outgoing(nid, port=chosen)
                await self._persist(run_id, nid, ntype, "completed", cfg, {"port": chosen}, context)
                continue
            if ntype == "merge":
                merged = [node_outputs.get(s, {}).get("output")
                          for (s, t) in activated_edges if t == nid]
                out = {"merged": merged}
                node_outputs[nid] = {"output": out, "status": "completed"}
                activate_outgoing(nid)
                await self._persist(run_id, nid, ntype, "completed", {}, out, context)
                continue
            if ntype == "foreach":
                items = cfg.get("items") or []
                if not isinstance(items, list):
                    items = []
                template = node.get("config", {}).get("template", {})
                results = [
                    resolve(template, {"$node": node_outputs, "$context": context,
                                       "$item": item, "$index": i})
                    for i, item in enumerate(items)
                ]
                out = {"count": len(results), "results": results}
                node_outputs[nid] = {"output": out, "status": "completed"}
                activate_outgoing(nid)
                await self._persist(run_id, nid, ntype, "completed", {"count": len(results)}, out, context)
                continue

            # ---- HITL nodes: pause until a resume_node signal ----
            if ntype in _HITL:
                await self._persist(run_id, nid, ntype, "waiting", cfg, None, context)
                try:
                    await workflow.execute_activity(
                        "create_hitl",
                        {"node_id": nid, "node_type": ntype, "config": cfg, "context": context,
                         "temporal_workflow_id": workflow.info().workflow_id},
                        start_to_close_timeout=timedelta(seconds=15),
                    )
                except Exception:
                    workflow.logger.warning("create_hitl failed (non-fatal); awaiting direct signal")
                workflow.logger.info("WorkflowRunner: node %s (%s) waiting for signal", nid, ntype)
                await workflow.wait_condition(lambda n=nid: n in self._signals)
                data = self._signals.get(nid, {})
                node_outputs[nid] = {"output": data, "status": "completed"}
                activate_outgoing(nid)
                await self._persist(run_id, nid, ntype, "completed", cfg, data, context)
                continue

            # ---- wait_timer: durable sleep ----
            if ntype == "wait_timer":
                secs = int(cfg.get("seconds", 0) or 0)
                if secs > 0:
                    await workflow.sleep(timedelta(seconds=secs))
                out = {"waited": secs}
                node_outputs[nid] = {"output": out, "status": "completed"}
                activate_outgoing(nid)
                await self._persist(run_id, nid, ntype, "completed", cfg, out, context)
                continue

            # ---- sub-workflow node: run another def as a Temporal child workflow ----
            if ntype == "sub_workflow":
                child_key = node.get("ref") or cfg.get("workflow_key") or ""
                child_graph = await workflow.execute_activity(
                    "load_def_graph", {"key": child_key, "context": context},
                    start_to_close_timeout=timedelta(seconds=15),
                )
                if not child_graph:
                    node_outputs[nid] = {"output": None, "status": "error",
                                         "error": f"sub-workflow {child_key!r} not found"}
                    await self._persist(run_id, nid, ntype, "error", cfg, None, context)
                else:
                    child_out = await workflow.execute_child_workflow(
                        "WorkflowRunner", {"graph": child_graph, "context": context},
                        id=f"{workflow.info().workflow_id}-sub-{nid}",
                    )
                    node_outputs[nid] = {"output": child_out, "status": "completed"}
                    await self._persist(run_id, nid, ntype, "completed", cfg, child_out, context)
                activate_outgoing(nid)
                continue

            # ---- activity-backed nodes (agent/action/set/http/...) ----
            activity_name = _ACTIVITY_FOR.get(ntype)
            if not activity_name:
                node_outputs[nid] = {"output": None, "status": "skipped",
                                     "note": f"no handler for type {ntype!r}"}
                activate_outgoing(nid)
                continue

            workflow.logger.info("WorkflowRunner: node %s (%s)", nid, ntype)
            default_timeout = 600 if ntype == "agent" else 120
            retry = RetryPolicy(maximum_attempts=int(node.get("retries", 3)))
            try:
                out = await workflow.execute_activity(
                    activity_name,
                    {"node_id": nid, "type": ntype, "ref": node.get("ref", ""),
                     "config": cfg, "context": context},
                    start_to_close_timeout=timedelta(seconds=int(node.get("timeout_s", default_timeout))),
                    retry_policy=retry,
                )
                node_outputs[nid] = {"output": out, "status": "completed"}
                activate_outgoing(nid)
                await self._persist(run_id, nid, ntype, "completed",
                                    {"ref": node.get("ref", ""), "config": cfg}, out, context)
            except Exception as e:  # node failed after retries
                err = str(e)[:300]
                node_outputs[nid] = {"output": None, "status": "error", "error": err}
                await self._persist(run_id, nid, ntype, "error",
                                    {"ref": node.get("ref", ""), "config": cfg}, {"error": err}, context)
                if node.get("continue_on_error"):
                    # route via the 'error' port if wired, and continue the flow
                    activate_outgoing(nid, port="error")
                    activate_outgoing(nid)
                    workflow.logger.warning("node %s errored; continuing (continue_on_error)", nid)
                    continue
                # otherwise fail the whole run
                workflow.logger.error("node %s errored; failing run: %s", nid, err)
                # Error-handler hook: start the graph's on_error workflow (fire-and-forget).
                on_error = graph.get("on_error")
                if on_error:
                    try:
                        await workflow.execute_activity(
                            "start_workflow_by_key",
                            {"key": on_error, "context": {**context, "error": err, "failed_node": nid}},
                            start_to_close_timeout=timedelta(seconds=15),
                        )
                    except Exception:
                        workflow.logger.warning("on_error handler %s failed to start", on_error)
                try:
                    await workflow.execute_activity(
                        "finish_run", {"run_id": run_id, "status": "failed", "context": context},
                        start_to_close_timeout=timedelta(seconds=15),
                    )
                except Exception:
                    pass
                return {"status": "failed", "run_id": run_id, "failed_node": nid,
                        "error": err, "node_outputs": node_outputs}

        try:
            await workflow.execute_activity(
                "finish_run", {"run_id": run_id, "status": "completed", "context": context},
                start_to_close_timeout=timedelta(seconds=15),
            )
        except Exception:
            workflow.logger.warning("finish_run failed (non-fatal)")

        return {"status": "completed", "run_id": run_id, "node_outputs": node_outputs}

    async def _persist(self, run_id, node_id, node_type, status, input_, output, context) -> None:
        try:
            await workflow.execute_activity(
                "persist_node_run",
                {"run_id": run_id, "node_id": node_id, "node_type": node_type,
                 "status": status, "input": input_, "output": output, "context": context},
                start_to_close_timeout=timedelta(seconds=15),
            )
        except Exception:  # noqa: BLE001 - persistence is non-fatal
            workflow.logger.warning("persist_node_run failed for %s (non-fatal)", node_id)
