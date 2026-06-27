"""Sample node-graph definitions used by the Epic #1 vertical-slice PoC."""

# agent -> set, with the `set` node consuming the `agent` node's output via an
# expression. Proves Temporal wiring + the interpreter + data passing.
SAMPLE_AGENT_TO_SET = {
    "key": "poc_agent_to_set",
    "name": "PoC: agent -> set",
    "nodes": [
        {"id": "a1", "type": "agent", "ref": "summarizer_agent", "config": {}},
        {
            "id": "s1",
            "type": "set",
            "config": {
                "headline": "Summary: {{ $node.a1.output.summary }}",
                "agent_ran": "{{ $node.a1.output.agent }}",
                "incident": "{{ $context.incident_id }}",
            },
        },
    ],
    "edges": [{"source": "a1", "target": "s1"}],
}

# Expected s1 output after a run:
#   {"headline": "Summary: [PoC] summarizer_agent executed",
#    "agent_ran": "summarizer_agent",
#    "incident": "poc-demo"}
