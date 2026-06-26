"""Tests for the pure trigger-executor plan builder + fail-safe dispatch gate."""

from __future__ import annotations

from services.routing.events import RCA_COMPLETED, LifecycleEvent
from services.routing.executor import build_dispatch_plan, dispatch_lifecycle_event


def _ev(**kw) -> LifecycleEvent:
    return LifecycleEvent(event_type=RCA_COMPLETED, org_id="org1", incident_id="inc1", **kw)


def test_plan_maps_agents_to_roles_with_modes():
    plan = build_dispatch_plan(
        ["summarizer_agent", "notification_agent", "postmortem_agent"], _ev()
    )
    by_name = {p.agent_name: p for p in plan}
    assert set(by_name) == {"summarizer_agent", "notification_agent", "postmortem_agent"}
    # read-only lifecycle agent runs in ask mode; writers in agent mode.
    assert by_name["summarizer_agent"].mode == "ask"
    assert by_name["notification_agent"].mode == "agent"
    assert by_name["postmortem_agent"].mode == "agent"
    # limits come from the role definitions.
    assert by_name["summarizer_agent"].max_turns > 0
    assert by_name["summarizer_agent"].max_seconds > 0


def test_plan_preserves_order():
    names = ["summarizer_agent", "notification_agent", "postmortem_agent"]
    plan = build_dispatch_plan(names, _ev())
    assert [p.agent_name for p in plan] == names


def test_plan_prompt_includes_role_body_and_context():
    plan = build_dispatch_plan(["summarizer_agent"], _ev(service="api", severity="high"))
    p = plan[0]
    assert "summariz" in p.prompt.lower()          # role body present
    assert "rca_completed" in p.prompt              # event context
    assert "inc1" in p.prompt                        # incident id
    assert "api" in p.prompt and "high" in p.prompt  # service/severity


def test_plan_sets_capability_scoped_tool_allowlist():
    plan = build_dispatch_plan(["notification_agent"], _ev())
    allow = set(plan[0].tool_allowlist)
    # notification_agent has the `chat` tag -> slack tools + safe core
    assert "list_slack_channels" in allow
    assert "web_search" in allow
    # not granted execution/cloud tools outside its domain
    assert "terminal_exec" not in allow
    assert "cloud_exec" not in allow


def test_plan_uses_prompt_override_when_present():
    plan = build_dispatch_plan(
        ["summarizer_agent"], _ev(),
        prompt_overrides={"summarizer_agent": "CUSTOM ORG PROMPT BODY"},
    )
    assert "CUSTOM ORG PROMPT BODY" in plan[0].prompt
    # Falls back to the role body when no override is supplied.
    plan2 = build_dispatch_plan(["summarizer_agent"], _ev())
    assert "CUSTOM ORG PROMPT BODY" not in plan2[0].prompt


def test_plan_applies_overrides():
    plan = build_dispatch_plan(
        ["summarizer_agent"],
        _ev(),
        overrides={"summarizer_agent": {"enabled": True, "max_turns": 3, "model": "claude-x"}},
    )
    assert plan[0].max_turns == 3
    assert plan[0].model == "claude-x"


def test_plan_skips_unknown_agents():
    plan = build_dispatch_plan(["summarizer_agent", "not_an_agent"], _ev())
    assert [p.agent_name for p in plan] == ["summarizer_agent"]


def test_dispatch_is_noop_when_flag_disabled(monkeypatch):
    # Flag unset/off -> returns [] without touching DB or Celery.
    monkeypatch.delenv("AURORA_TRIGGER_ROUTER_ENABLED", raising=False)
    assert dispatch_lifecycle_event("user1", _ev()) == []
