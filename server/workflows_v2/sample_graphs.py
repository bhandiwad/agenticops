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


# agent -> if -> (true: s_true | false: s_false) -> merge. Exercises branching:
# the untaken branch must be skipped, and merge joins the taken branch.
SAMPLE_BRANCHING = {
    "key": "poc_branching",
    "name": "PoC: if branching + merge",
    "nodes": [
        {"id": "a1", "type": "agent", "ref": "summarizer_agent", "config": {}},
        {"id": "c1", "type": "if",
         "config": {"left": "{{ $node.a1.output.agent }}", "op": "==", "right": "summarizer_agent"}},
        {"id": "s_true", "type": "set", "config": {"branch": "taken-true"}},
        {"id": "s_false", "type": "set", "config": {"branch": "taken-false"}},
        {"id": "m1", "type": "merge", "config": {}},
    ],
    "edges": [
        {"source": "a1", "target": "c1"},
        {"source": "c1", "target": "s_true", "port": "true"},
        {"source": "c1", "target": "s_false", "port": "false"},
        {"source": "s_true", "target": "m1"},
        {"source": "s_false", "target": "m1"},
    ],
}


# approval (HITL) -> set. The run pauses at ap1 until a resume_node signal arrives
# (from the approvals API or a direct client signal); the signal data flows into s1.
SAMPLE_HITL = {
    "key": "poc_hitl",
    "name": "PoC: approval (HITL signal)",
    "nodes": [
        {"id": "ap1", "type": "approval", "config": {"summary": "Approve to continue the PoC"}},
        {"id": "s1", "type": "set",
         "config": {"decision": "{{ $node.ap1.output.decision }}",
                    "note": "{{ $node.ap1.output.note }}"}},
    ],
    "edges": [{"source": "ap1", "target": "s1"}],
}
