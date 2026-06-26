"""Tests for the risk-based policy engine."""

from __future__ import annotations

from services.policy.policy_engine import PolicyAction, decide


def test_foreground_always_allows():
    # Foreground HITL is handled interactively; policy engine allows.
    assert decide("github_commit", is_background=False).action is PolicyAction.ALLOW
    assert decide("cloud_exec", is_background=False).action is PolicyAction.ALLOW


def test_background_read_allowed():
    d = decide("query_datadog", is_background=True)
    assert d.action is PolicyAction.ALLOW
    assert d.risk == "read"


def test_background_write_requires_approval():
    d = decide("github_fix", is_background=True)
    assert d.action is PolicyAction.REQUIRE_APPROVAL
    assert d.risk == "write"


def test_background_destructive_requires_approval():
    d = decide("cloud_exec", is_background=True)
    assert d.action is PolicyAction.REQUIRE_APPROVAL
    assert d.risk == "destructive"


def test_background_unknown_tool_requires_approval():
    # Action keys / MCP tools aren't in the catalog -> fail safe to approval.
    d = decide("gitlab:create_merge_request", is_background=True)
    assert d.action is PolicyAction.REQUIRE_APPROVAL
    assert d.risk is None


def test_action_hash_is_stable_and_action_specific():
    from services.policy.approvals import action_hash
    h1 = action_hash("iac_tool", "apply plan X")
    h2 = action_hash("iac_tool", "apply plan X")
    h3 = action_hash("iac_tool", "apply plan Y")
    assert h1 == h2           # stable
    assert h1 != h3           # different action -> different hash
    assert len(h1) == 32


def test_decision_never_denies_by_default():
    # Default policy queues for approval rather than hard-denying; deny is
    # reserved for explicit org policy (future).
    for name in ("github_commit", "iac_tool", "notion_delete_view", "totally_unknown"):
        assert decide(name, is_background=True).action is not PolicyAction.DENY
