"""Risk classification for MCP tools, unified with the native tool catalog.

The MCP client historically classified tools with a name-pattern heuristic
(``is_destructive_mcp_tool``). This module extracts that heuristic into a light,
import-cheap location and layers the catalog on top, so MCP and native tools are
classified through one ``Risk`` vocabulary.

Kept dependency-light (only imports the pure tool_registry) so the policy engine
and registry can use it without pulling the heavy MCP client module.
"""

from __future__ import annotations

from chat.backend.agent.tools.tool_registry import Risk, tool_risk

# Tools that create, modify, or delete resources (exact names).
_DESTRUCTIVE_MCP_TOOLS = {
    "create_or_update_file", "push_files", "create_branch", "create_repository",
    "create_issue", "create_pull_request", "create_pull_request_review",
    "merge_pull_request", "update_pull_request_branch", "fork_repository",
    "add_issue_comment", "add_comment_to_pending_review", "add_project_item",
    "delete_file", "delete_pending_review", "cancel_workflow_run",
    "rerun_workflow_run", "rerun_failed_jobs", "assign_copilot_to_issue",
    "request_copilot_review", "update_issue", "update_project_item_field_value",
    "close_pull_request_review", "manage_pull_request_review",
}

_DESTRUCTIVE_MCP_PREFIXES = {
    "create_", "delete_", "update_", "push_", "merge_", "close_",
    "add_", "remove_", "cancel_", "rerun_", "fork_", "assign_",
    "request_", "submit_", "approve_", "dismiss_", "resolve_",
}


def is_destructive_mcp_tool(tool_name: str) -> bool:
    """Name-heuristic: does this MCP tool create/modify/delete resources?"""
    if tool_name in _DESTRUCTIVE_MCP_TOOLS:
        return True
    return any(tool_name.startswith(p) for p in _DESTRUCTIVE_MCP_PREFIXES)


def enforce_read_only(tool_dicts, read_only: bool):
    """Drop write/destructive tools from a list of MCP tool dicts when the
    server is registered read-only. Pure. Each dict must have a ``name`` key.

    A read-only MCP server must never expose tools that mutate state, regardless
    of what the server advertises — this is the per-server read/write boundary.
    """
    if not read_only:
        return list(tool_dicts)
    return [t for t in tool_dicts if mcp_tool_risk(t.get("name", "")) is Risk.READ]


def mcp_tool_risk(tool_name: str) -> Risk:
    """Classify an MCP (or native) tool's risk.

    Catalog-first: if the name is a classified native tool, use its risk.
    Otherwise fall back to the MCP name-heuristic (destructive -> DESTRUCTIVE,
    else READ). This is for display/classification; the command gate keeps its
    own conservative policy for unknown structured actions.
    """
    native = tool_risk(tool_name)
    if native is not None:
        return native
    return Risk.DESTRUCTIVE if is_destructive_mcp_tool(tool_name) else Risk.READ


__all__ = [
    "is_destructive_mcp_tool",
    "mcp_tool_risk",
    "enforce_read_only",
    "_DESTRUCTIVE_MCP_TOOLS",
    "_DESTRUCTIVE_MCP_PREFIXES",
]
