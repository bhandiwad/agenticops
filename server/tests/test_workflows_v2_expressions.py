"""Unit tests for the Workflow V2 expression resolver + topo sort (pure)."""

from workflows_v2.expressions import resolve, topo_order


def _scope():
    return {
        "$node": {"a1": {"output": {"summary": "hello", "agent": "summarizer_agent",
                                     "items": [{"finding": "x"}]}}},
        "$context": {"incident_id": "inc-1"},
    }


def test_whole_string_expression_returns_raw_value():
    assert resolve("{{ $node.a1.output.summary }}", _scope()) == "hello"


def test_interpolation_into_string():
    assert resolve("Summary: {{ $node.a1.output.summary }}", _scope()) == "Summary: hello"


def test_context_reference():
    assert resolve("{{ $context.incident_id }}", _scope()) == "inc-1"


def test_list_index_path():
    assert resolve("{{ $node.a1.output.items.0.finding }}", _scope()) == "x"


def test_missing_path_is_empty_in_interpolation():
    assert resolve("v={{ $node.a1.output.nope }}", _scope()) == "v="


def test_nested_dict_and_list_resolution():
    cfg = {"h": "{{ $node.a1.output.agent }}", "list": ["{{ $context.incident_id }}", "lit"]}
    assert resolve(cfg, _scope()) == {"h": "summarizer_agent", "list": ["inc-1", "lit"]}


def test_non_expression_passthrough():
    assert resolve(42, _scope()) == 42
    assert resolve("plain", _scope()) == "plain"


def test_topo_order_linear():
    nodes = {"a1": {}, "s1": {}}
    edges = [{"source": "a1", "target": "s1"}]
    assert topo_order(nodes, edges) == ["a1", "s1"]


def test_topo_order_diamond_is_deterministic():
    nodes = {"a": {}, "b": {}, "c": {}, "d": {}}
    edges = [{"source": "a", "target": "b"}, {"source": "a", "target": "c"},
             {"source": "b", "target": "d"}, {"source": "c", "target": "d"}]
    order = topo_order(nodes, edges)
    assert order[0] == "a" and order[-1] == "d"
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")
