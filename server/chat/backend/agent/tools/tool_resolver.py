"""Pure resolution of *which* native tools apply to a given agent context.

This extracts the inclusion logic embedded in ``get_cloud_tools()`` (the long
sequence of ``if connected: tools.append(...)`` blocks) into a single, pure,
testable function. It deliberately produces only tool *names* in the exact
order ``get_cloud_tools`` produces them — it does NOT build LangChain tools,
touch the DB/Vault, or call connectivity checks. The caller resolves
connectivity + feature flags once and passes them in via :class:`ToolContext`.

Why this exists: it lets us characterize and lock the inclusion behavior in the
lightweight CI env, so that ``get_cloud_tools`` can later be rewritten to call
this resolver for inclusion (keeping its per-tool LangChain construction) with a
parity test as the safety net — rather than rewriting a 1600-line function
blind.

Fidelity notes (mirrors cloud_tools.get_cloud_tools as of this commit):
  * ``cloud`` in ``connected`` means "any cloud provider connected".
  * Connector ids in ``connected`` are assumed to already account for feature
    flags (e.g. ``jira`` present == ``is_jira_enabled() and creds present``;
    ``sharepoint`` present == ``is_sharepoint_enabled() and creds``;
    ``confluence`` present == ``get_token_data(confluence)`` truthy).
  * Ask mode drops ONLY ``iac_tool`` and ``github_commit`` from native tools
    (this matches ModeAccessController.filter_tools — it is intentionally
    documented here because "ask == read-only" is weaker than it sounds; making
    it risk-driven from the catalog is a later step).
  * MCP tools are dynamic and out of scope for this resolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, List

# Notion tool ordering, mirrored from notion/registry.py NOTION_TOOL_SPECS so
# the resolver can reproduce get_cloud_tools' ordering without importing the
# heavy Notion modules. Kept in sync by a drift test.
_NOTION_TOOLS_ORDERED = (
    "notion_search",
    "notion_fetch",
    "notion_create_pages",
    "notion_update_page",
    "notion_append_to_page",
    "notion_move_pages",
    "notion_duplicate_page",
    "notion_trash_page",
    "notion_get_block_children",
    "notion_update_block",
    "notion_delete_block",
    "notion_create_database",
    "notion_update_database",
    "notion_update_database_properties",
    "notion_query_database",
    "notion_create_data_source",
    "notion_get_data_source",
    "notion_update_data_source",
    "notion_update_data_source_properties",
    "notion_query_data_source",
    "notion_list_data_source_templates",
    "notion_create_view",
    "notion_update_view",
    "notion_delete_view",
    "notion_list_database_views",
    "notion_query_view",
    "notion_create_comment",
    "notion_get_comments",
    "notion_list_users",
    "notion_get_user",
    "notion_get_self",
    "notion_find_person",
    "notion_list_teamspaces",
    "notion_upload_file",
    "notion_list_file_uploads",
    "notion_list_custom_emojis",
    "notion_export_postmortem",
    "notion_create_action_items",
)

# Subset loaded during background RCA (mirrors _NOTION_RCA_TOOLS in cloud_tools),
# preserving spec order.
_NOTION_RCA_TOOLS = {
    "notion_search",
    "notion_fetch",
    "notion_query_database",
    "notion_export_postmortem",
    "notion_create_action_items",
}

# Native tools dropped by ModeAccessController.filter_tools in ask (read-only)
# mode. MCP tools are also dropped there but are out of scope for this resolver.
_ASK_MODE_DROPPED = ("iac_tool", "github_commit")


@dataclass(frozen=True)
class ToolContext:
    """Resolved context that decides native tool inclusion.

    ``connected`` holds connector ids that resolved truthy (already accounting
    for feature flags). Recognized ids match
    ``tool_registry.KNOWN_CONNECTORS`` plus the ``"cloud"`` meta-connector.
    """

    mode: str = "agent"
    is_pr_review: bool = False
    is_background: bool = False
    is_rca_context: bool = False
    is_postmortem_action: bool = False
    trigger_rca_requested: bool = False
    has_action_id: bool = False
    has_incident: bool = False
    jira_comment_only: bool = True
    connected: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def _mode(self) -> str:
        return (self.mode or "agent").strip().lower()

    @property
    def is_ask_mode(self) -> bool:
        return self._mode == "ask"

    @property
    def is_prediscovery(self) -> bool:
        return self._mode == "prediscovery"


def resolve_native_tool_names(ctx: ToolContext) -> List[str]:
    """Return the ordered, de-duplicated native tool names for ``ctx``.

    Order matches ``get_cloud_tools`` so this can later drive inclusion without
    reordering the tool surface the LLM sees.
    """
    pr = ctx.is_pr_review
    c = ctx.connected
    names: List[str] = []
    add = names.append

    # --- tool_functions list (processed first, in this order) ------------- #
    add("terminal_exec")
    add("analyze_zip_file")

    if "cloud" in c and not pr:
        add("iac_tool")
        add("cloud_exec")

    if ctx.trigger_rca_requested:
        add("trigger_rca")
    if ctx.has_action_id:
        add("trigger_action")

    if "github" in c:
        if not pr:
            add("github_commit")
        add("get_connected_repos")
        add("github_rca")
        if ctx.is_rca_context:
            add("github_fix")

    if "tailscale" in c and not pr:
        add("tailscale_ssh")

    if "kubectl_onprem" in c and not pr:
        add("get_connected_clusters")
        add("on_prem_kubectl")

    if "slack" in c:
        add("list_slack_channels")
        add("get_channel_history")
        add("get_thread_replies")

    if "jenkins" in c:
        add("jenkins_rca")
    if "cloudbees" in c:
        add("cloudbees_rca")
    if "spinnaker" in c:
        add("spinnaker_rca")

    add("get_postmortem")
    if ctx.is_postmortem_action:
        add("save_postmortem")

    add("list_artifacts")
    add("read_artifact")
    add("write_artifact")

    # --- standalone appends (after the loop) ------------------------------ #
    add("analyze_zip_file")  # re-appended in get_cloud_tools; dedup collapses it
    add("rag_index_zip")
    add("load_skill")
    add("knowledge_base_search")
    add("get_infrastructure_context")

    if ctx.is_prediscovery:
        add("save_discovery_finding")
        add("save_infrastructure_context")

    if "splunk" in c:
        add("search_splunk")
        add("list_splunk_indexes")
        add("list_splunk_sourcetypes")

    if "incidentio" in c:
        add("list_incidentio_incidents")
        add("get_incidentio_incident")
        add("get_incidentio_timeline")

    if "dynatrace" in c:
        add("query_dynatrace")
    if "datadog" in c:
        add("query_datadog")
    if "newrelic" in c:
        add("query_newrelic")
    if "sentry" in c:
        add("query_sentry")
    if "gitlab" in c:
        add("gitlab")
    if "opsgenie" in c:
        add("query_opsgenie")

    if "bitbucket" in c:
        add("bitbucket_repos")
        add("bitbucket_branches")
        add("bitbucket_pull_requests")
        if not ctx.is_background:
            add("bitbucket_issues")  # excluded from the read-only RCA subset
        add("bitbucket_pipelines")
        add("bitbucket_fix")

    if "confluence" in c:
        add("confluence_search_similar")
        add("confluence_search_runbooks")
        add("confluence_fetch_page")
        add("confluence_runbook_parse")

    if "notion" in c:
        if ctx.is_background:
            for n in _NOTION_TOOLS_ORDERED:
                if n in _NOTION_RCA_TOOLS:
                    add(n)
        else:
            for n in _NOTION_TOOLS_ORDERED:
                add(n)

    if "jira" in c:
        add("jira_search_issues")
        add("jira_get_issue")
        add("jira_add_comment")
        if not ctx.jira_comment_only:
            add("jira_create_issue")
            add("jira_update_issue")
            add("jira_link_issues")

    if "sharepoint" in c:
        add("sharepoint_search")
        add("sharepoint_fetch_page")
        add("sharepoint_fetch_document")
        add("sharepoint_create_page")

    if "coroot" in c:
        for n in (
            "coroot_get_incidents", "coroot_get_incident_detail",
            "coroot_get_applications", "coroot_get_app_detail",
            "coroot_get_app_logs", "coroot_get_traces",
            "coroot_get_service_map", "coroot_query_metrics",
            "coroot_get_deployments", "coroot_get_nodes",
            "coroot_get_overview_logs", "coroot_get_node_detail",
            "coroot_get_costs", "coroot_get_risks",
        ):
            add(n)

    if "thousandeyes" in c:
        for n in (
            "thousandeyes_list_tests", "thousandeyes_get_test_detail",
            "thousandeyes_get_test_results", "thousandeyes_get_alerts",
            "thousandeyes_get_alert_rules", "thousandeyes_get_agents",
            "thousandeyes_get_endpoint_agents", "thousandeyes_get_internet_insights",
            "thousandeyes_get_dashboards", "thousandeyes_get_dashboard_widget",
            "thousandeyes_get_bgp_monitors",
        ):
            add(n)

    if "cloudflare" in c:
        add("query_cloudflare")
        add("cloudflare_list_zones")
        add("cloudflare_action")

    if "flyio" in c:
        add("query_flyio_metrics")

    if ctx.has_incident and ctx.is_background:
        add("get_alert_field")

    add("web_search")

    # --- ModeAccessController.filter_tools (ask mode) --------------------- #
    if ctx.is_ask_mode:
        names = [n for n in names if n not in _ASK_MODE_DROPPED]

    # --- dedup, preserving first occurrence ------------------------------- #
    seen = set()
    deduped: List[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def reconcile_tool_lists(expected: List[str], actual: List[str]) -> dict:
    """Compare a resolver-produced ``expected`` list against an ``actual`` list
    of constructed native tool names.

    Returns a dict with:
      * ``missing``     — names the resolver expected but ``actual`` lacks,
      * ``unexpected``  — names present in ``actual`` the resolver didn't expect,
      * ``order_ok``    — whether the common names appear in the same relative order.

    Used by the optional drift validator wired into ``get_cloud_tools`` so the
    declarative resolver can be checked against the live imperative inclusion
    logic in a real environment before it is promoted to drive inclusion.
    """
    expected_set = set(expected)
    actual_set = set(actual)
    missing = [n for n in expected if n not in actual_set]
    unexpected = [n for n in actual if n not in expected_set]
    # Relative order of the names common to both lists.
    common_expected = [n for n in expected if n in actual_set]
    common_actual = [n for n in actual if n in expected_set]
    return {
        "missing": missing,
        "unexpected": unexpected,
        "order_ok": common_expected == common_actual,
    }


__all__ = ["ToolContext", "resolve_native_tool_names", "reconcile_tool_lists"]
