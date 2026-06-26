"""Characterization tests for native tool inclusion (resolve_native_tool_names).

These lock the inclusion logic extracted from get_cloud_tools so that a later
rewrite of get_cloud_tools to consume the resolver is provably behavior-
preserving. Pure data — runs in the lightweight CI env.
"""

from __future__ import annotations

import pytest

from chat.backend.agent.tools.tool_registry import all_tool_names, tools_for_connector
from chat.backend.agent.tools.tool_resolver import (
    _NOTION_TOOLS_ORDERED,
    ToolContext,
    reconcile_tool_lists,
    resolve_native_tool_names,
)

ALL_CONNECTORS = frozenset({
    "cloud", "github", "gitlab", "bitbucket", "tailscale", "kubectl_onprem",
    "slack", "jenkins", "cloudbees", "spinnaker", "splunk", "incidentio",
    "dynatrace", "datadog", "newrelic", "sentry", "opsgenie", "confluence",
    "sharepoint", "coroot", "thousandeyes", "cloudflare", "flyio", "jira",
    "notion",
})

# The always-available set, in resolver order, for an empty agent-mode context.
_BASE_EXPECTED = [
    "terminal_exec",
    "analyze_zip_file",
    "get_postmortem",
    "list_artifacts",
    "read_artifact",
    "write_artifact",
    "rag_index_zip",
    "load_skill",
    "knowledge_base_search",
    "get_infrastructure_context",
    "web_search",
]


# --------------------------------------------------------------------------- #
# Baseline / structural invariants
# --------------------------------------------------------------------------- #
def test_empty_context_returns_exact_base_set():
    assert resolve_native_tool_names(ToolContext()) == _BASE_EXPECTED


def test_output_has_no_duplicates_even_when_fully_connected():
    ctx = ToolContext(connected=ALL_CONNECTORS)
    out = resolve_native_tool_names(ctx)
    assert len(out) == len(set(out))


def test_analyze_zip_file_appears_exactly_once():
    # It is appended twice inside get_cloud_tools; dedup must collapse it.
    out = resolve_native_tool_names(ToolContext(connected=ALL_CONNECTORS))
    assert out.count("analyze_zip_file") == 1


def test_resolver_never_emits_a_non_catalog_tool():
    """Every name the resolver can emit must be a classified native tool."""
    catalog = all_tool_names()
    # Union over a spread of contexts that exercises every branch.
    contexts = [
        ToolContext(connected=ALL_CONNECTORS, is_background=True,
                    is_rca_context=True, is_postmortem_action=True,
                    trigger_rca_requested=True, has_action_id=True,
                    has_incident=True, jira_comment_only=False),
        ToolContext(connected=ALL_CONNECTORS, is_background=False,
                    jira_comment_only=False),
        ToolContext(connected=ALL_CONNECTORS, mode="prediscovery"),
        ToolContext(connected=ALL_CONNECTORS, is_pr_review=True),
        ToolContext(connected=ALL_CONNECTORS, mode="ask"),
    ]
    emitted = set()
    for ctx in contexts:
        emitted.update(resolve_native_tool_names(ctx))
    extra = emitted - catalog
    assert not extra, f"resolver emitted unclassified tools: {sorted(extra)}"


def test_resolver_can_emit_every_catalog_tool():
    """Coverage: the union over representative contexts equals the full catalog.

    Proves the resolver reaches every native tool (no orphan in the catalog
    that no context can ever produce) and emits nothing outside it.
    """
    catalog = all_tool_names()
    union = set()
    # background RCA: bitbucket/notion read-only subsets, get_alert_field, fixes
    union |= set(resolve_native_tool_names(ToolContext(
        connected=ALL_CONNECTORS, is_background=True, is_rca_context=True,
        is_postmortem_action=True, trigger_rca_requested=True,
        has_action_id=True, has_incident=True, jira_comment_only=False)))
    # foreground agent: bitbucket_issues + full Notion + iac/cloud_exec
    union |= set(resolve_native_tool_names(ToolContext(
        connected=ALL_CONNECTORS, is_background=False, jira_comment_only=False)))
    # prediscovery: the two save_* discovery tools
    union |= set(resolve_native_tool_names(ToolContext(
        connected=ALL_CONNECTORS, mode="prediscovery")))
    assert union == catalog, (
        f"not reachable: {sorted(catalog - union)}; "
        f"unexpected: {sorted(union - catalog)}"
    )


# --------------------------------------------------------------------------- #
# Per-connector gating
# --------------------------------------------------------------------------- #
def test_cloud_tools_gated_on_cloud():
    out = resolve_native_tool_names(ToolContext(connected=frozenset({"cloud"})))
    assert "iac_tool" in out and "cloud_exec" in out
    assert "iac_tool" not in resolve_native_tool_names(ToolContext())


def test_datadog_and_github_combo():
    out = resolve_native_tool_names(
        ToolContext(connected=frozenset({"datadog", "github"}))
    )
    assert "query_datadog" in out
    assert {"github_commit", "get_connected_repos", "github_rca"} <= set(out)
    assert "query_newrelic" not in out  # not connected


# --------------------------------------------------------------------------- #
# Flag-driven gating
# --------------------------------------------------------------------------- #
def test_github_fix_only_in_rca_context():
    base = ToolContext(connected=frozenset({"github"}))
    assert "github_fix" not in resolve_native_tool_names(base)
    rca = ToolContext(connected=frozenset({"github"}), is_rca_context=True)
    assert "github_fix" in resolve_native_tool_names(rca)


def test_pr_review_excludes_write_and_exec_tools():
    ctx = ToolContext(
        connected=frozenset({"cloud", "github", "tailscale", "kubectl_onprem"}),
        is_pr_review=True,
    )
    out = resolve_native_tool_names(ctx)
    # write/exec excluded under PR review
    for n in ("iac_tool", "cloud_exec", "github_commit", "tailscale_ssh",
              "on_prem_kubectl", "get_connected_clusters"):
        assert n not in out, f"{n} should be excluded in PR review"
    # read tools remain
    assert {"get_connected_repos", "github_rca"} <= set(out)


def test_trigger_tools_require_their_flags():
    assert "trigger_rca" in resolve_native_tool_names(
        ToolContext(trigger_rca_requested=True))
    assert "trigger_action" in resolve_native_tool_names(
        ToolContext(has_action_id=True))
    assert "trigger_rca" not in resolve_native_tool_names(ToolContext())


def test_postmortem_and_discovery_flags():
    assert "save_postmortem" in resolve_native_tool_names(
        ToolContext(is_postmortem_action=True))
    pre = resolve_native_tool_names(ToolContext(mode="prediscovery"))
    assert {"save_discovery_finding", "save_infrastructure_context"} <= set(pre)
    assert "save_discovery_finding" not in resolve_native_tool_names(ToolContext())


def test_get_alert_field_requires_incident_and_background():
    assert "get_alert_field" in resolve_native_tool_names(
        ToolContext(has_incident=True, is_background=True))
    assert "get_alert_field" not in resolve_native_tool_names(
        ToolContext(has_incident=True, is_background=False))


# --------------------------------------------------------------------------- #
# Bitbucket / Notion background subsets
# --------------------------------------------------------------------------- #
def test_bitbucket_issues_only_outside_background():
    bg = resolve_native_tool_names(
        ToolContext(connected=frozenset({"bitbucket"}), is_background=True))
    fg = resolve_native_tool_names(
        ToolContext(connected=frozenset({"bitbucket"}), is_background=False))
    assert "bitbucket_issues" not in bg
    assert "bitbucket_issues" in fg
    # bitbucket_fix present in both
    assert "bitbucket_fix" in bg and "bitbucket_fix" in fg


def test_notion_background_subset_vs_full():
    bg = set(resolve_native_tool_names(
        ToolContext(connected=frozenset({"notion"}), is_background=True)))
    fg = set(resolve_native_tool_names(
        ToolContext(connected=frozenset({"notion"}), is_background=False)))
    notion_catalog = set(tools_for_connector("notion"))
    assert bg & notion_catalog == {
        "notion_search", "notion_fetch", "notion_query_database",
        "notion_export_postmortem", "notion_create_action_items",
    }
    assert fg & notion_catalog == notion_catalog  # all 38


def test_jira_comment_only_vs_full():
    co = set(resolve_native_tool_names(
        ToolContext(connected=frozenset({"jira"}), jira_comment_only=True)))
    full = set(resolve_native_tool_names(
        ToolContext(connected=frozenset({"jira"}), jira_comment_only=False)))
    assert {"jira_search_issues", "jira_get_issue", "jira_add_comment"} <= co
    assert "jira_create_issue" not in co
    assert {"jira_create_issue", "jira_update_issue", "jira_link_issues"} <= full


# --------------------------------------------------------------------------- #
# Ask mode (documents that it only drops iac_tool + github_commit)
# --------------------------------------------------------------------------- #
def test_ask_mode_only_drops_iac_and_github_commit():
    connected = frozenset({"cloud", "github"})
    agent_out = set(resolve_native_tool_names(ToolContext(connected=connected)))
    ask_out = set(resolve_native_tool_names(
        ToolContext(connected=connected, mode="ask")))
    assert agent_out - ask_out == {"iac_tool", "github_commit"}
    # Notably cloud_exec is NOT dropped by ask mode today.
    assert "cloud_exec" in ask_out


# --------------------------------------------------------------------------- #
# Ordering drift guard for the mirrored Notion list
# --------------------------------------------------------------------------- #
def test_reconcile_identical_lists():
    out = reconcile_tool_lists(["a", "b", "c"], ["a", "b", "c"])
    assert out == {"missing": [], "unexpected": [], "order_ok": True}


def test_reconcile_detects_missing_and_unexpected():
    out = reconcile_tool_lists(["a", "b", "c"], ["a", "c", "d"])
    assert out["missing"] == ["b"]
    assert out["unexpected"] == ["d"]


def test_reconcile_detects_order_mismatch():
    # Same membership, different relative order of common names.
    out = reconcile_tool_lists(["a", "b", "c"], ["a", "c", "b"])
    assert out["missing"] == [] and out["unexpected"] == []
    assert out["order_ok"] is False


def test_reconcile_resolver_against_itself_is_clean():
    names = resolve_native_tool_names(ToolContext(connected=ALL_CONNECTORS))
    out = reconcile_tool_lists(names, list(names))
    assert out == {"missing": [], "unexpected": [], "order_ok": True}


def test_notion_ordered_list_matches_source_specs():
    registry = pytest.importorskip(
        "chat.backend.agent.tools.notion.registry",
        reason="Notion tool module not importable in this environment",
    )
    source_order = tuple(name for (_f, name, _s, _d) in registry.NOTION_TOOL_SPECS)
    assert _NOTION_TOOLS_ORDERED == source_order
