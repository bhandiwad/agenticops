"""Workflow V2 — native node-graph engine executed on Temporal.

PoC (Epic #1): a single generic ``WorkflowRunner`` Temporal workflow interprets a
node-graph definition (graph = data, not code). All non-determinism lives in
activities. Flag-gated by AURORA_WORKFLOWS_V2; additive and isolated from the V1
linear engine in services/workflows/.
"""
