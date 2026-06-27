"""Unit tests for the Workflow V2 expression resolver + topo sort (pure)."""

from workflows_v2.expressions import resolve, topo_order, eval_condition, truthy


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


def test_truthy_string_falsies():
    assert truthy("hello") is True
    for v in ("", "false", "0", "none", "null", "no", "  False  "):
        assert truthy(v) is False
    assert truthy([1]) is True and truthy([]) is False


def test_eval_condition_equality():
    assert eval_condition({"left": "summarizer_agent", "op": "==", "right": "summarizer_agent"}) is True
    assert eval_condition({"left": "a", "op": "!=", "right": "b"}) is True


def test_eval_condition_numeric_and_contains():
    assert eval_condition({"left": "5", "op": ">", "right": "3"}) is True
    assert eval_condition({"left": "3", "op": ">", "right": "5"}) is False
    assert eval_condition({"left": "abcdef", "op": "contains", "right": "cde"}) is True


def test_eval_condition_truthiness_fallback():
    assert eval_condition({"condition": "yes"}) is True
    assert eval_condition({"condition": ""}) is False


def test_topo_order_diamond_is_deterministic():
    nodes = {"a": {}, "b": {}, "c": {}, "d": {}}
    edges = [{"source": "a", "target": "b"}, {"source": "a", "target": "c"},
             {"source": "b", "target": "d"}, {"source": "c", "target": "d"}]
    order = topo_order(nodes, edges)
    assert order[0] == "a" and order[-1] == "d"
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")
