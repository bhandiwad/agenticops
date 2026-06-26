"""Tests for unified MCP tool risk classification."""

from __future__ import annotations

from chat.backend.agent.tools.mcp_risk import is_destructive_mcp_tool, mcp_tool_risk
from chat.backend.agent.tools.tool_registry import Risk


def test_destructive_heuristic_exact_and_prefix():
    assert is_destructive_mcp_tool("merge_pull_request") is True   # exact
    assert is_destructive_mcp_tool("delete_something") is True     # prefix
    assert is_destructive_mcp_tool("get_file_contents") is False
    assert is_destructive_mcp_tool("search_code") is False


def test_mcp_tool_risk_catalog_first():
    # A native catalog tool keeps its catalog risk even via the MCP classifier.
    assert mcp_tool_risk("query_datadog") is Risk.READ
    assert mcp_tool_risk("cloud_exec") is Risk.DESTRUCTIVE


def test_mcp_tool_risk_falls_back_to_heuristic():
    assert mcp_tool_risk("create_pull_request") is Risk.DESTRUCTIVE
    assert mcp_tool_risk("get_file_contents") is Risk.READ


def test_mcp_tools_reexports_stay_consistent():
    # mcp_tools re-exports the unified heuristic.
    from chat.backend.agent.tools import mcp_risk
    assert mcp_risk.is_destructive_mcp_tool("create_branch") is True


def test_enforce_read_only_drops_destructive():
    from chat.backend.agent.tools.mcp_risk import enforce_read_only
    tools = [
        {"name": "get_file_contents"},   # read
        {"name": "search_code"},          # read
        {"name": "create_pull_request"},  # destructive
        {"name": "delete_file"},          # destructive
    ]
    kept = {t["name"] for t in enforce_read_only(tools, read_only=True)}
    assert kept == {"get_file_contents", "search_code"}
    # read_only=False keeps everything.
    assert len(enforce_read_only(tools, read_only=False)) == 4
