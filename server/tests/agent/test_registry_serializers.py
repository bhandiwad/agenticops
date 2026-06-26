"""Tests for the registry serializers backing the read-only registry API."""

from __future__ import annotations

from chat.backend.agent.tools.tool_registry import (
    TOOL_CATALOG,
    allowed_tools_for_capabilities,
    disabled_tool_names,
    merge_availability,
    serialize_catalog,
)
from chat.backend.agent.orchestrator.role_registry import RoleRegistry, apply_agent_override

_RISKS = {"read", "write", "destructive"}


def test_serialize_catalog_shape_and_coverage():
    rows = serialize_catalog()
    assert len(rows) == len(TOOL_CATALOG)
    for r in rows:
        assert set(r) == {"name", "risk", "capabilities", "connector_id", "notes"}
        assert r["risk"] in _RISKS
        assert isinstance(r["capabilities"], list) and r["capabilities"]
        # JSON-able: connector_id is str or None.
        assert r["connector_id"] is None or isinstance(r["connector_id"], str)


def test_serialize_catalog_sorted_by_connector_then_name():
    rows = serialize_catalog()
    keys = [(r["connector_id"] or "", r["name"]) for r in rows]
    assert keys == sorted(keys)


def test_serialize_agents_shape_and_kinds():
    agents = RoleRegistry().serialize()
    assert len(agents) >= 13
    required = {
        "name", "kind", "description", "capability_tags",
        "max_turns", "max_seconds", "rca_priority", "model", "prompt",
    }
    for a in agents:
        assert required <= set(a)
        assert a["prompt"]
    kinds = {a["kind"] for a in agents}
    assert "investigator" in kinds
    assert {"summarizer", "notification", "postmortem"} <= kinds


def test_serialize_agents_ordered_by_kind_then_priority():
    agents = RoleRegistry().serialize()
    keys = [(a["kind"], a["rca_priority"], a["name"]) for a in agents]
    assert keys == sorted(keys)


# --------------------------------------------------------------------------- #
# Per-org overlay helpers (tool availability + agent overrides)
# --------------------------------------------------------------------------- #
def test_merge_availability_defaults_to_enabled():
    rows = serialize_catalog()
    merged = merge_availability(rows, {"query_datadog": False})
    by_name = {r["name"]: r for r in merged}
    assert by_name["query_datadog"]["enabled"] is False
    # Any tool without a row defaults to enabled.
    assert by_name["web_search"]["enabled"] is True
    assert len(merged) == len(rows)


def test_disabled_tool_names_only_real_disabled_catalog_tools():
    avail = {"query_datadog": False, "web_search": True, "not_a_tool": False}
    disabled = disabled_tool_names(avail)
    assert "query_datadog" in disabled
    assert "web_search" not in disabled   # enabled
    assert "not_a_tool" not in disabled    # not in catalog


def test_apply_agent_override_none_keeps_defaults_enabled():
    agent = {"name": "x", "max_turns": 10, "max_seconds": 100, "model": None}
    out = apply_agent_override(agent, None)
    assert out["enabled"] is True
    assert out["max_turns"] == 10 and out["max_seconds"] == 100


def test_allowed_tools_for_capabilities_includes_domain_plus_core():
    chat = allowed_tools_for_capabilities({"chat"})
    # chat-tagged tools (slack) present
    assert "list_slack_channels" in chat
    # safe core present
    assert "web_search" in chat and "read_artifact" in chat
    # execution tools NOT granted by an unrelated capability
    assert "terminal_exec" not in chat
    assert "cloud_exec" not in chat


def test_allowed_tools_for_capabilities_postmortem():
    pm = allowed_tools_for_capabilities({"postmortem"})
    assert {"get_postmortem", "save_postmortem"} <= pm
    assert "notion_export_postmortem" in pm


def test_allowed_tools_for_capabilities_empty_is_core_only():
    core = allowed_tools_for_capabilities(set())
    assert "web_search" in core
    assert "query_datadog" not in core


def test_apply_agent_override_applies_set_fields_only():
    agent = {"name": "x", "max_turns": 10, "max_seconds": 100, "model": None}
    out = apply_agent_override(
        agent, {"enabled": False, "max_turns": 5, "max_seconds": None, "model": "claude-x"}
    )
    assert out["enabled"] is False
    assert out["max_turns"] == 5            # overridden
    assert out["max_seconds"] == 100        # None override ignored → default kept
    assert out["model"] == "claude-x"
