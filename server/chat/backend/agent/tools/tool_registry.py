"""Declarative metadata registry for Aurora's native agent tools.

Today the only source of truth for which tools exist is the ~1600-line
imperative ``get_cloud_tools()`` in :mod:`chat.backend.agent.tools.cloud_tools`.
That function interleaves *inclusion* decisions (the ``if connected:`` gates)
with LangChain *construction* (``StructuredTool.from_function`` with bespoke
descriptions/schemas/wrapping), and carries no machine-readable risk or
capability metadata — the closest thing is a name-pattern heuristic for MCP
tools in ``mcp_tools.is_destructive_mcp_tool``.

This module is the first, deliberately non-invasive step toward a data-driven
tool layer (AgenticOps Phase 1). It declares, for every native tool, its:

* ``risk`` — read / write / destructive classification (for the policy engine
  and Ask-mode read-only enforcement),
* ``capabilities`` — coarse capability tags (for per-agent tool allowlists and
  the Tools UI),
* ``connector_id`` — the connector that gates the tool (``None`` for
  always-available or context-gated tools).

It is intentionally pure: no LangChain, no DB, no Vault, no imports of the tool
implementations. That keeps it unit-testable in the lightweight CI env and lets
other layers (PolicyEngine, ModeAccessController, the Tools API) consume tool
metadata without paying the cost of building the LangChain tools.

NOTE: this registry does NOT yet drive ``get_cloud_tools()``. Wiring the factory
to consume it (so inclusion + metadata share one source of truth) is the next
step and needs an integration harness that can run the full agent stack with a
mocked connectivity oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional


class Risk(str, Enum):
    """Impact classification used by the policy/approval layer.

    Ordering (READ < WRITE < DESTRUCTIVE) reflects increasing blast radius and
    is what an Ask-mode / approval gate should key off. A tool is classified by
    the *maximum* impact any of its actions can have — e.g. a multi-action tool
    that can both read and delete is ``DESTRUCTIVE``.
    """

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


# Canonical capability vocabulary. These tag *what domain a tool operates on*,
# for per-agent allowlists (a role's `tools:` list intersects these) and for
# grouping in the Tools UI. The first block is the established vocabulary that
# orchestrator roles already use (orchestrator/select_skills._TOOL_METADATA);
# the second block extends it for non-RCA tools the orchestrator metadata does
# not yet cover. Kept as the single source of truth: a reconciliation test
# asserts _TOOL_METADATA's tags are a subset of this vocabulary, and another
# asserts every tag here is used by at least one tool (no dead entries).
KNOWN_CAPABILITIES: FrozenSet[str] = frozenset({
    # --- established (shared with orchestrator role tags) --- #
    "runtime_state", "metrics", "logs", "observability", "error_tracking",
    "on_call", "ticket_history", "ci_cd", "source_control_read",
    "source_control_write", "iac", "runbooks", "knowledge_base",
    # --- extensions for non-RCA tool domains --- #
    "artifacts", "postmortem", "chat", "infra", "alert", "incident_ops",
    "discovery", "files", "network", "security", "cost", "database", "users",
    "comments", "meta",
})

# Connector ids that gate tools. These mirror the connector identifiers used by
# the backend connectivity checks (``is_<x>_connected``). ``"cloud"`` is the
# meta-connector meaning "any cloud provider connected" (AWS/GCP/Azure/...).
KNOWN_CONNECTORS: FrozenSet[str] = frozenset({
    "cloud", "github", "gitlab", "bitbucket", "tailscale", "kubectl_onprem",
    "slack", "jenkins", "cloudbees", "spinnaker", "splunk", "incidentio",
    "dynatrace", "datadog", "newrelic", "sentry", "opsgenie", "confluence",
    "sharepoint", "coroot", "thousandeyes", "cloudflare", "flyio", "jira",
    "notion", "fortigate", "zabbix", "servicenow",
})


@dataclass(frozen=True)
class ToolSpec:
    """Static metadata for one native agent tool.

    This describes the tool, not a per-invocation grant. Tenant/user/project
    scoping is still enforced at runtime by connector connection state + RLS;
    ``connector_id`` only records *which* connector gates the tool.
    """

    name: str
    risk: Risk
    capabilities: FrozenSet[str]
    connector_id: Optional[str] = None
    notes: str = ""

    @property
    def is_destructive(self) -> bool:
        return self.risk is Risk.DESTRUCTIVE

    @property
    def is_read_only(self) -> bool:
        return self.risk is Risk.READ


def _spec(
    name: str,
    risk: Risk,
    capabilities: "set[str] | frozenset[str]",
    connector_id: Optional[str] = None,
    notes: str = "",
) -> ToolSpec:
    return ToolSpec(
        name=name,
        risk=risk,
        capabilities=frozenset(capabilities),
        connector_id=connector_id,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# The catalog. Grouped by connector for readability. Risk reflects the maximum
# impact the tool can have; capabilities are the domains it touches.
# --------------------------------------------------------------------------- #
_CATALOG: List[ToolSpec] = [
    # --- Always-available (no connector gating) --------------------------- #
    _spec("terminal_exec", Risk.DESTRUCTIVE, {"runtime_state"},
          notes="Executes arbitrary shell commands in a sandbox pod."),
    _spec("analyze_zip_file", Risk.READ, {"files"}),
    _spec("rag_index_zip", Risk.WRITE, {"files", "knowledge_base"},
          notes="Indexes uploaded files into the Weaviate RAG store."),
    _spec("load_skill", Risk.READ, {"meta"}),
    _spec("knowledge_base_search", Risk.READ, {"knowledge_base", "runbooks"}),
    _spec("get_infrastructure_context", Risk.READ, {"infra"}),
    _spec("web_search", Risk.READ, {"knowledge_base"}),
    _spec("list_artifacts", Risk.READ, {"artifacts"}),
    _spec("read_artifact", Risk.READ, {"artifacts"}),
    _spec("write_artifact", Risk.WRITE, {"artifacts"}),
    _spec("get_postmortem", Risk.READ, {"postmortem"}),

    # --- Context-gated (flags, not connectors) ---------------------------- #
    _spec("save_postmortem", Risk.WRITE, {"postmortem"},
          notes="Only registered for the dedicated postmortem-generation action."),
    _spec("trigger_rca", Risk.WRITE, {"incident_ops"},
          notes="Creates an incident and dispatches a background RCA."),
    _spec("trigger_action", Risk.WRITE, {"incident_ops"},
          notes="Runs an Aurora Action as a background task."),
    _spec("list_workflows", Risk.READ, {"incident_ops"},
          notes="List automation workflows available to run."),
    _spec("run_workflow", Risk.WRITE, {"incident_ops"},
          notes="Start a V2 automation workflow; destructive steps inside self-gate via HITL."),
    _spec("list_quick_actions", Risk.READ, {"incident_ops"},
          notes="List one-click Quick Actions."),
    _spec("run_quick_action", Risk.WRITE, {"incident_ops"},
          notes="Run a Quick Action (Aurora Action) by id or name."),
    _spec("get_operations_stats", Risk.READ, {"incident_ops"},
          notes="Workflow/action/agent run stats + pending approvals for a period."),
    _spec("get_incident_stats", Risk.READ, {"incident_ops"},
          notes="Incident counts, MTTD/MTTA/MTTR, and top services for a period."),
    _spec("save_discovery_finding", Risk.WRITE, {"discovery"},
          notes="Prediscovery mode only."),
    _spec("save_infrastructure_context", Risk.WRITE, {"infra", "discovery"},
          notes="Prediscovery mode only."),
    _spec("get_alert_field", Risk.READ, {"alert"},
          notes="Background RCA with an incident only."),

    # --- Cloud (gated by any connected provider) -------------------------- #
    _spec("iac_tool", Risk.DESTRUCTIVE, {"iac"}, "cloud",
          notes="Terraform plan/apply. Apply is destructive."),
    _spec("cloud_exec", Risk.DESTRUCTIVE, {"runtime_state", "metrics", "logs", "observability"}, "cloud",
          notes="Runs cloud CLI commands that can mutate infrastructure (write-gated per-command)."),

    # --- GitHub ----------------------------------------------------------- #
    _spec("github_commit", Risk.DESTRUCTIVE, {"source_control_write"}, "github",
          notes="Commits and pushes to a repository."),
    _spec("get_connected_repos", Risk.READ, {"source_control_read"}, "github"),
    _spec("github_rca", Risk.READ, {"source_control_read", "ci_cd"}, "github"),
    _spec("github_fix", Risk.WRITE, {"source_control_write"}, "github",
          notes="Stores a fix suggestion for user review; not applied directly."),

    # --- Tailscale -------------------------------------------------------- #
    _spec("tailscale_ssh", Risk.DESTRUCTIVE, {"runtime_state", "network"}, "tailscale",
          notes="SSH command execution over Tailscale."),

    # --- On-prem kubectl -------------------------------------------------- #
    _spec("get_connected_clusters", Risk.READ, {"runtime_state"}, "kubectl_onprem"),
    _spec("on_prem_kubectl", Risk.DESTRUCTIVE, {"runtime_state", "observability"}, "kubectl_onprem",
          notes="kubectl can apply/delete cluster resources (write-gated per-command)."),

    # --- Slack ------------------------------------------------------------ #
    _spec("list_slack_channels", Risk.READ, {"chat"}, "slack"),
    _spec("get_channel_history", Risk.READ, {"chat"}, "slack"),
    _spec("get_thread_replies", Risk.READ, {"chat"}, "slack"),

    # --- CI/CD ------------------------------------------------------------ #
    _spec("jenkins_rca", Risk.READ, {"ci_cd"}, "jenkins"),
    _spec("cloudbees_rca", Risk.READ, {"ci_cd"}, "cloudbees"),
    _spec("spinnaker_rca", Risk.WRITE, {"ci_cd"}, "spinnaker",
          notes="Can trigger pipelines (e.g. rollback)."),

    # --- Splunk ----------------------------------------------------------- #
    _spec("search_splunk", Risk.READ, {"logs", "observability"}, "splunk"),
    _spec("list_splunk_indexes", Risk.READ, {"logs"}, "splunk"),
    _spec("list_splunk_sourcetypes", Risk.READ, {"logs"}, "splunk"),

    # --- incident.io ------------------------------------------------------ #
    _spec("list_incidentio_incidents", Risk.READ, {"ticket_history", "on_call"}, "incidentio"),
    _spec("get_incidentio_incident", Risk.READ, {"ticket_history", "on_call"}, "incidentio"),
    _spec("get_incidentio_timeline", Risk.READ, {"ticket_history", "on_call"}, "incidentio"),

    # --- Observability (read-only query tools) ---------------------------- #
    _spec("query_dynatrace", Risk.READ, {"metrics", "observability", "error_tracking"}, "dynatrace"),
    _spec("query_datadog", Risk.READ, {"metrics", "observability", "error_tracking", "logs"}, "datadog"),
    _spec("query_newrelic", Risk.READ, {"metrics", "observability", "error_tracking"}, "newrelic"),
    _spec("query_sentry", Risk.READ, {"error_tracking", "observability"}, "sentry"),
    _spec("query_flyio_metrics", Risk.READ, {"metrics", "observability", "network"}, "flyio"),

    # --- GitLab ----------------------------------------------------------- #
    _spec("gitlab", Risk.DESTRUCTIVE, {"source_control_read", "source_control_write", "ci_cd"}, "gitlab",
          notes="Multi-action; can push files, create/merge MRs, delete branches."),

    # --- OpsGenie / JSM --------------------------------------------------- #
    _spec("query_opsgenie", Risk.READ, {"on_call", "ticket_history"}, "opsgenie"),

    # --- Bitbucket -------------------------------------------------------- #
    _spec("bitbucket_repos", Risk.DESTRUCTIVE, {"source_control_read"}, "bitbucket",
          notes="Can create/update/delete files (read-only subset during RCA)."),
    _spec("bitbucket_branches", Risk.DESTRUCTIVE, {"source_control_read"}, "bitbucket",
          notes="Can create/delete branches (read-only subset during RCA)."),
    _spec("bitbucket_pull_requests", Risk.WRITE, {"source_control_read", "ci_cd"}, "bitbucket",
          notes="Can create/merge/decline PRs."),
    _spec("bitbucket_issues", Risk.WRITE, {"ticket_history"}, "bitbucket"),
    _spec("bitbucket_pipelines", Risk.WRITE, {"ci_cd"}, "bitbucket",
          notes="Can trigger/stop pipelines."),
    _spec("bitbucket_fix", Risk.WRITE, {"source_control_write"}, "bitbucket",
          notes="Stores a fix suggestion for user review."),

    # --- Confluence ------------------------------------------------------- #
    _spec("confluence_search_similar", Risk.READ, {"runbooks", "knowledge_base"}, "confluence"),
    _spec("confluence_search_runbooks", Risk.READ, {"runbooks", "knowledge_base"}, "confluence"),
    _spec("confluence_fetch_page", Risk.READ, {"runbooks", "knowledge_base"}, "confluence"),
    _spec("confluence_runbook_parse", Risk.READ, {"runbooks", "knowledge_base"}, "confluence"),

    # --- SharePoint ------------------------------------------------------- #
    _spec("sharepoint_search", Risk.READ, {"runbooks", "knowledge_base"}, "sharepoint"),
    _spec("sharepoint_fetch_page", Risk.READ, {"runbooks", "knowledge_base"}, "sharepoint"),
    _spec("sharepoint_fetch_document", Risk.READ, {"runbooks", "knowledge_base"}, "sharepoint"),
    _spec("sharepoint_create_page", Risk.WRITE, {"knowledge_base"}, "sharepoint"),

    # --- Coroot (eBPF observability, all read-only) ----------------------- #
    _spec("coroot_get_incidents", Risk.READ, {"ticket_history", "observability"}, "coroot"),
    _spec("coroot_get_incident_detail", Risk.READ, {"ticket_history", "observability"}, "coroot"),
    _spec("coroot_get_applications", Risk.READ, {"runtime_state", "observability"}, "coroot"),
    _spec("coroot_get_app_detail", Risk.READ, {"runtime_state", "observability"}, "coroot"),
    _spec("coroot_get_app_logs", Risk.READ, {"logs", "observability"}, "coroot"),
    _spec("coroot_get_traces", Risk.READ, {"metrics", "observability"}, "coroot"),
    _spec("coroot_get_service_map", Risk.READ, {"runtime_state", "observability", "network"}, "coroot"),
    _spec("coroot_query_metrics", Risk.READ, {"metrics", "observability"}, "coroot"),
    _spec("coroot_get_deployments", Risk.READ, {"ci_cd"}, "coroot"),
    _spec("coroot_get_nodes", Risk.READ, {"runtime_state", "infra"}, "coroot"),
    _spec("coroot_get_overview_logs", Risk.READ, {"logs", "observability"}, "coroot"),
    _spec("coroot_get_node_detail", Risk.READ, {"runtime_state", "infra"}, "coroot"),
    _spec("coroot_get_costs", Risk.READ, {"cost"}, "coroot"),
    _spec("coroot_get_risks", Risk.READ, {"observability", "security"}, "coroot"),

    # --- ThousandEyes (network intelligence, all read-only) --------------- #
    _spec("thousandeyes_list_tests", Risk.READ, {"metrics", "observability", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_test_detail", Risk.READ, {"metrics", "observability", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_test_results", Risk.READ, {"metrics", "observability", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_alerts", Risk.READ, {"ticket_history", "observability", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_alert_rules", Risk.READ, {"observability", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_agents", Risk.READ, {"runtime_state", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_endpoint_agents", Risk.READ, {"runtime_state", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_internet_insights", Risk.READ, {"metrics", "observability", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_dashboards", Risk.READ, {"metrics", "observability", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_dashboard_widget", Risk.READ, {"metrics", "observability", "network"}, "thousandeyes"),
    _spec("thousandeyes_get_bgp_monitors", Risk.READ, {"observability", "network"}, "thousandeyes"),

    # --- Cloudflare ------------------------------------------------------- #
    _spec("query_cloudflare", Risk.READ, {"metrics", "observability", "logs", "network"}, "cloudflare"),
    _spec("cloudflare_list_zones", Risk.READ, {"observability", "network"}, "cloudflare"),
    _spec("cloudflare_action", Risk.DESTRUCTIVE, {"network", "security"}, "cloudflare",
          notes="Purge cache, change security level, update DNS, toggle firewall rules."),

    # --- Jira ------------------------------------------------------------- #
    _spec("jira_search_issues", Risk.READ, {"ticket_history"}, "jira"),
    _spec("jira_get_issue", Risk.READ, {"ticket_history"}, "jira"),
    _spec("jira_add_comment", Risk.WRITE, {"ticket_history", "comments"}, "jira"),
    _spec("jira_create_issue", Risk.WRITE, {"ticket_history"}, "jira"),
    _spec("jira_update_issue", Risk.WRITE, {"ticket_history"}, "jira"),
    _spec("jira_link_issues", Risk.WRITE, {"ticket_history"}, "jira"),

    # --- Notion (38 tools) ------------------------------------------------ #
    _spec("notion_search", Risk.READ, {"runbooks", "knowledge_base"}, "notion"),
    _spec("notion_fetch", Risk.READ, {"runbooks", "knowledge_base"}, "notion"),
    _spec("notion_create_pages", Risk.WRITE, {"knowledge_base"}, "notion"),
    _spec("notion_update_page", Risk.WRITE, {"knowledge_base"}, "notion"),
    _spec("notion_append_to_page", Risk.WRITE, {"knowledge_base"}, "notion"),
    _spec("notion_move_pages", Risk.WRITE, {"knowledge_base"}, "notion"),
    _spec("notion_duplicate_page", Risk.WRITE, {"knowledge_base"}, "notion"),
    _spec("notion_trash_page", Risk.WRITE, {"knowledge_base"}, "notion",
          notes="Soft-delete (recoverable from Notion trash)."),
    _spec("notion_get_block_children", Risk.READ, {"knowledge_base"}, "notion"),
    _spec("notion_update_block", Risk.WRITE, {"knowledge_base"}, "notion"),
    _spec("notion_delete_block", Risk.WRITE, {"knowledge_base"}, "notion",
          notes="Archives a single block (recoverable)."),
    _spec("notion_create_database", Risk.WRITE, {"knowledge_base", "database"}, "notion"),
    _spec("notion_update_database", Risk.WRITE, {"knowledge_base", "database"}, "notion"),
    _spec("notion_update_database_properties", Risk.DESTRUCTIVE, {"database"}, "notion",
          notes="Setting a property to null removes the column and its data."),
    _spec("notion_query_database", Risk.READ, {"knowledge_base", "database"}, "notion"),
    _spec("notion_create_data_source", Risk.WRITE, {"database"}, "notion"),
    _spec("notion_get_data_source", Risk.READ, {"database"}, "notion"),
    _spec("notion_update_data_source", Risk.WRITE, {"database"}, "notion"),
    _spec("notion_update_data_source_properties", Risk.WRITE, {"database"}, "notion"),
    _spec("notion_query_data_source", Risk.READ, {"knowledge_base", "database"}, "notion"),
    _spec("notion_list_data_source_templates", Risk.READ, {"database"}, "notion"),
    _spec("notion_create_view", Risk.WRITE, {"database"}, "notion"),
    _spec("notion_update_view", Risk.WRITE, {"database"}, "notion"),
    _spec("notion_delete_view", Risk.DESTRUCTIVE, {"database"}, "notion",
          notes="Irreversible."),
    _spec("notion_list_database_views", Risk.READ, {"database"}, "notion"),
    _spec("notion_query_view", Risk.READ, {"database"}, "notion"),
    _spec("notion_create_comment", Risk.WRITE, {"comments"}, "notion"),
    _spec("notion_get_comments", Risk.READ, {"comments"}, "notion"),
    _spec("notion_list_users", Risk.READ, {"users"}, "notion"),
    _spec("notion_get_user", Risk.READ, {"users"}, "notion"),
    _spec("notion_get_self", Risk.READ, {"users", "meta"}, "notion"),
    _spec("notion_find_person", Risk.READ, {"users"}, "notion"),
    _spec("notion_list_teamspaces", Risk.READ, {"meta"}, "notion"),
    _spec("notion_upload_file", Risk.WRITE, {"files"}, "notion"),
    _spec("notion_list_file_uploads", Risk.READ, {"files"}, "notion"),
    _spec("notion_list_custom_emojis", Risk.READ, {"meta"}, "notion"),
    _spec("notion_export_postmortem", Risk.WRITE, {"postmortem", "knowledge_base"}, "notion"),
    _spec("notion_create_action_items", Risk.WRITE, {"postmortem", "knowledge_base"}, "notion"),

    # --- FortiGate firewall ---------------------------------------------- #
    _spec("query_fortigate", Risk.READ, {"network", "security"}, "fortigate"),
    _spec("fortigate_open_port", Risk.DESTRUCTIVE, {"network", "security"}, "fortigate",
          notes="Creates a firewall service/address object and allow policy. Background/workflow only."),

    # --- Zabbix monitoring ----------------------------------------------- #
    _spec("query_zabbix", Risk.READ, {"observability", "metrics", "infra"}, "zabbix"),

    # --- ServiceNow ITSM writes (automation ticket updates) -------------- #
    _spec("update_servicenow_ticket", Risk.WRITE, {"incident_ops", "comments"}, "servicenow",
          notes="Appends a work note (optionally resolves) to a ServiceNow ticket."),
]


# Indexed by name for O(1) lookup. Building this also asserts uniqueness so a
# duplicate registration fails loudly at import time rather than silently
# shadowing.
def _build_catalog(specs: List[ToolSpec]) -> Dict[str, ToolSpec]:
    catalog: Dict[str, ToolSpec] = {}
    for spec in specs:
        if spec.name in catalog:
            raise ValueError(f"Duplicate ToolSpec for tool '{spec.name}'")
        catalog[spec.name] = spec
    return catalog


TOOL_CATALOG: Dict[str, ToolSpec] = _build_catalog(_CATALOG)


# --------------------------------------------------------------------------- #
# Accessors
# --------------------------------------------------------------------------- #
def get_tool_spec(name: str) -> Optional[ToolSpec]:
    """Return the :class:`ToolSpec` for ``name``, or ``None`` if not a known
    native tool (e.g. a dynamically-discovered MCP tool)."""
    return TOOL_CATALOG.get(name)


def tool_risk(name: str) -> Optional[Risk]:
    """Return the declared :class:`Risk` for ``name``, or ``None`` if unknown."""
    spec = TOOL_CATALOG.get(name)
    return spec.risk if spec else None


def is_destructive(name: str) -> bool:
    """True only for tools explicitly classified ``DESTRUCTIVE`` in the catalog.

    Returns ``False`` for unknown tools — callers that must fail closed for
    unclassified (e.g. MCP) tools should combine this with their own heuristic.
    """
    spec = TOOL_CATALOG.get(name)
    return bool(spec and spec.risk is Risk.DESTRUCTIVE)


def is_read_only(name: str) -> bool:
    """True only for tools explicitly classified ``READ`` in the catalog."""
    spec = TOOL_CATALOG.get(name)
    return bool(spec and spec.risk is Risk.READ)


def requires_connector(name: str) -> Optional[str]:
    """Return the connector id that gates ``name``, or ``None`` if the tool is
    always-available / context-gated / unknown."""
    spec = TOOL_CATALOG.get(name)
    return spec.connector_id if spec else None


def tools_by_capability(capability: str) -> List[str]:
    """Return the sorted names of tools tagged with ``capability``."""
    return sorted(n for n, s in TOOL_CATALOG.items() if capability in s.capabilities)


def tools_for_connector(connector_id: Optional[str]) -> List[str]:
    """Return the sorted names of tools gated by ``connector_id``."""
    return sorted(n for n, s in TOOL_CATALOG.items() if s.connector_id == connector_id)


def all_tool_names() -> FrozenSet[str]:
    return frozenset(TOOL_CATALOG.keys())


# A small safe core every lifecycle agent may use regardless of its capability
# tags (research + its own working documents). Deliberately excludes execution
# tools (terminal_exec/cloud_exec/iac_tool) and connector write tools.
_LIFECYCLE_CORE_TOOLS: FrozenSet[str] = frozenset({
    "web_search",
    "load_skill",
    "knowledge_base_search",
    "list_artifacts",
    "read_artifact",
    "write_artifact",
    "get_postmortem",
})


def allowed_tools_for_capabilities(capability_tags) -> FrozenSet[str]:
    """Return the catalog tool names a capability-tagged agent may use.

    This is the restrictive allowlist for trigger-routed lifecycle agents: the
    union of tools whose capabilities intersect the agent's tags, plus the safe
    core. It mirrors the orchestrator's capability-tag tool selection
    (``select_tools_for_role``) but on the static catalog, so it is pure and
    testable. It only *restricts* a tool surface; it never grants context-gated
    tools that were not built.
    """
    tags = set(capability_tags or ())
    allowed = set(_LIFECYCLE_CORE_TOOLS)
    for tag in tags:
        allowed.update(tools_by_capability(tag))
    return frozenset(allowed)


def merge_availability(rows: List[dict], availability: Dict[str, bool]) -> List[dict]:
    """Annotate serialized catalog rows with per-org ``enabled`` state.

    ``availability`` maps tool name -> enabled. A tool with no row defaults to
    enabled (tools are available unless explicitly disabled for the org). Pure.
    """
    out = []
    for r in rows:
        rr = dict(r)
        rr["enabled"] = availability.get(r["name"], True)
        out.append(rr)
    return out


def disabled_tool_names(availability: Dict[str, bool]) -> FrozenSet[str]:
    """Return the set of catalog tool names explicitly disabled for an org."""
    return frozenset(
        name for name, enabled in availability.items()
        if enabled is False and name in TOOL_CATALOG
    )


def serialize_catalog() -> List[dict]:
    """Return the catalog as JSON-able dicts for the Tools API/UI, sorted by
    (connector, name). Pure — no LangChain or DB."""
    rows = [
        {
            "name": s.name,
            "risk": s.risk.value,
            "capabilities": sorted(s.capabilities),
            "connector_id": s.connector_id,
            "notes": s.notes,
        }
        for s in TOOL_CATALOG.values()
    ]
    rows.sort(key=lambda r: (r["connector_id"] or "", r["name"]))
    return rows


__all__ = [
    "Risk",
    "ToolSpec",
    "TOOL_CATALOG",
    "KNOWN_CAPABILITIES",
    "KNOWN_CONNECTORS",
    "get_tool_spec",
    "tool_risk",
    "is_destructive",
    "is_read_only",
    "requires_connector",
    "tools_by_capability",
    "tools_for_connector",
    "all_tool_names",
    "serialize_catalog",
    "merge_availability",
    "disabled_tool_names",
    "allowed_tools_for_capabilities",
]
