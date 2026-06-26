"""Characterization + consistency tests for the native tool registry.

These lock the tool metadata catalog introduced in AgenticOps Phase 1 so that:
  * every entry is internally consistent (valid risk, known capabilities/connector),
  * the safety-critical risk classifications are pinned (a regression that
    silently downgrades cloud_exec / kubectl / delete tools to "read" fails here),
  * the accessors behave,
  * the catalog stays in sync with the one tool block that lives in a separate,
    importable module (Notion) — a real drift guard, not a copy of the catalog.

The catalog itself is pure data (no LangChain / DB), so these run in the
lightweight CI env. A full ``get_cloud_tools()`` parity test (which needs the
whole agent stack + a mocked connectivity oracle) is intentionally deferred to
the integration harness in Phase 1b.
"""

from __future__ import annotations

import re

import pytest

from chat.backend.agent.tools.tool_registry import (
    KNOWN_CAPABILITIES,
    KNOWN_CONNECTORS,
    TOOL_CATALOG,
    Risk,
    ToolSpec,
    all_tool_names,
    get_tool_spec,
    is_destructive,
    is_read_only,
    requires_connector,
    tool_risk,
    tools_by_capability,
    tools_for_connector,
)

_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


# --------------------------------------------------------------------------- #
# Internal consistency
# --------------------------------------------------------------------------- #
def test_catalog_is_non_empty():
    assert len(TOOL_CATALOG) > 100, "expected the full native tool catalog"


@pytest.mark.parametrize("name", sorted(TOOL_CATALOG))
def test_every_spec_is_consistent(name: str):
    spec = TOOL_CATALOG[name]
    assert isinstance(spec, ToolSpec)
    # Name shape + index integrity.
    assert spec.name == name
    assert _SNAKE_CASE.match(name), f"{name!r} is not snake_case"
    # Risk is a real enum member.
    assert isinstance(spec.risk, Risk)
    # Capabilities are non-empty and drawn from the known vocabulary.
    assert spec.capabilities, f"{name} has no capability tags"
    unknown = spec.capabilities - KNOWN_CAPABILITIES
    assert not unknown, f"{name} has unknown capabilities {sorted(unknown)}"
    # Connector is either unset or a known connector id.
    if spec.connector_id is not None:
        assert spec.connector_id in KNOWN_CONNECTORS, (
            f"{name} references unknown connector {spec.connector_id!r}"
        )


def test_no_duplicate_names():
    # TOOL_CATALOG is a dict, but assert the source list had no dupes by
    # confirming the count matches a set of names.
    assert len(TOOL_CATALOG) == len({s.name for s in TOOL_CATALOG.values()})


def test_capability_vocabulary_has_no_dead_entries():
    """Every declared capability tag is actually used by at least one tool.

    Keeps KNOWN_CAPABILITIES honest — a tag nobody uses is either a typo or
    dead vocabulary that should be removed.
    """
    used = set().union(*(s.capabilities for s in TOOL_CATALOG.values()))
    dead = KNOWN_CAPABILITIES - used
    assert not dead, f"unused capability tags: {sorted(dead)}"


# --------------------------------------------------------------------------- #
# Safety-critical risk classifications (the reason the catalog exists)
# --------------------------------------------------------------------------- #
_EXPECTED_DESTRUCTIVE = {
    "terminal_exec",
    "cloud_exec",
    "iac_tool",
    "on_prem_kubectl",
    "tailscale_ssh",
    "github_commit",
    "gitlab",
    "bitbucket_repos",
    "bitbucket_branches",
    "cloudflare_action",
    "notion_delete_view",
    "notion_update_database_properties",
}

_EXPECTED_WRITE = {
    "write_artifact",
    "save_postmortem",
    "trigger_rca",
    "trigger_action",
    "github_fix",
    "bitbucket_fix",
    "spinnaker_rca",
    "sharepoint_create_page",
    "jira_create_issue",
    "jira_update_issue",
    "jira_add_comment",
    "notion_create_pages",
    "notion_export_postmortem",
    "rag_index_zip",
}

_EXPECTED_READ = {
    "query_datadog",
    "query_newrelic",
    "query_sentry",
    "query_dynatrace",
    "github_rca",
    "get_connected_repos",
    "search_splunk",
    "web_search",
    "knowledge_base_search",
    "get_postmortem",
    "read_artifact",
    "list_artifacts",
    "coroot_get_traces",
    "notion_search",
    "notion_query_database",
}


@pytest.mark.parametrize("name", sorted(_EXPECTED_DESTRUCTIVE))
def test_destructive_tools_classified_destructive(name: str):
    assert name in TOOL_CATALOG, f"{name} missing from catalog"
    assert tool_risk(name) is Risk.DESTRUCTIVE
    assert is_destructive(name) is True


@pytest.mark.parametrize("name", sorted(_EXPECTED_WRITE))
def test_write_tools_classified_write(name: str):
    assert name in TOOL_CATALOG, f"{name} missing from catalog"
    assert tool_risk(name) is Risk.WRITE
    assert is_destructive(name) is False
    assert is_read_only(name) is False


@pytest.mark.parametrize("name", sorted(_EXPECTED_READ))
def test_read_tools_classified_read(name: str):
    assert name in TOOL_CATALOG, f"{name} missing from catalog"
    assert tool_risk(name) is Risk.READ
    assert is_read_only(name) is True
    assert is_destructive(name) is False


# --------------------------------------------------------------------------- #
# Accessors
# --------------------------------------------------------------------------- #
def test_get_tool_spec_unknown_returns_none():
    assert get_tool_spec("definitely_not_a_tool") is None
    assert tool_risk("definitely_not_a_tool") is None
    assert is_destructive("definitely_not_a_tool") is False
    assert is_read_only("definitely_not_a_tool") is False
    assert requires_connector("definitely_not_a_tool") is None


def test_requires_connector():
    assert requires_connector("query_datadog") == "datadog"
    assert requires_connector("iac_tool") == "cloud"
    assert requires_connector("terminal_exec") is None  # always-available


def test_tools_by_capability_source_control():
    scm = set(tools_by_capability("source_control_read")) | set(
        tools_by_capability("source_control_write")
    )
    assert {"github_rca", "github_commit", "gitlab", "bitbucket_repos"} <= scm
    # Pure read tools from other domains should not appear.
    assert "query_datadog" not in scm


def test_tools_for_connector_datadog():
    assert tools_for_connector("datadog") == ["query_datadog"]


def test_always_available_tools_have_no_connector():
    for name in ("terminal_exec", "web_search", "load_skill", "write_artifact"):
        assert requires_connector(name) is None


def test_all_tool_names_matches_catalog():
    assert all_tool_names() == frozenset(TOOL_CATALOG.keys())


# --------------------------------------------------------------------------- #
# Drift guard: cross-check against the one tool block defined in an importable
# module. If a Notion tool is added/removed there, this fails until the catalog
# is updated.
# --------------------------------------------------------------------------- #
def test_notion_specs_in_sync_with_catalog():
    registry = pytest.importorskip(
        "chat.backend.agent.tools.notion.registry",
        reason="Notion tool module not importable in this environment",
    )
    specs = registry.NOTION_TOOL_SPECS
    source_names = {name for (_func, name, _schema, _desc) in specs}
    catalog_notion = set(tools_for_connector("notion"))

    missing_from_catalog = source_names - catalog_notion
    stale_in_catalog = catalog_notion - source_names
    assert not missing_from_catalog, (
        f"Notion tools registered in get_cloud_tools but unclassified: "
        f"{sorted(missing_from_catalog)}"
    )
    assert not stale_in_catalog, (
        f"Notion tools in catalog no longer registered: {sorted(stale_in_catalog)}"
    )
