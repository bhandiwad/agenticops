"""Tests for the pure trigger-routing engine."""

from __future__ import annotations

from services.routing.events import (
    ALERT_CREATED,
    INCIDENT_CREATED,
    INCIDENT_RESOLVED,
    RCA_COMPLETED,
    LifecycleEvent,
)
from services.routing.trigger_router import (
    DEFAULT_ROUTES,
    RouteStep,
    route_event,
    default_routing_table,
)
from chat.backend.agent.orchestrator.role_registry import RoleRegistry, INVESTIGATOR_KIND


def _ev(event_type: str, **kw) -> LifecycleEvent:
    return LifecycleEvent(event_type=event_type, org_id="org1", **kw)


def test_default_routes_per_event_type():
    assert route_event(_ev(ALERT_CREATED)).agents == ["dedup_agent", "correlation_agent"]
    assert route_event(_ev(INCIDENT_CREATED)).agents == ["summarizer_agent"]
    assert route_event(_ev(RCA_COMPLETED)).agents == [
        "summarizer_agent", "notification_agent", "postmortem_agent",
    ]
    assert route_event(_ev(INCIDENT_RESOLVED)).agents == ["postmortem_agent"]


def test_unknown_event_type_routes_to_nothing():
    assert route_event(_ev("nonsense")).agents == []


def test_disabled_event_type_suppresses_whole_route():
    d = route_event(_ev(RCA_COMPLETED), disabled_event_types=frozenset({RCA_COMPLETED}))
    assert d.agents == []


def test_disabled_agent_is_removed_and_reported():
    d = route_event(_ev(RCA_COMPLETED), disabled_agents=frozenset({"notification_agent"}))
    assert d.agents == ["summarizer_agent", "postmortem_agent"]
    assert d.suppressed == ["notification_agent"]


def test_match_condition_gates_extra_route_step():
    extra = {ALERT_CREATED: [RouteStep("summarizer_agent", match={"severity": "critical"})]}
    # Non-critical: extra step does not apply.
    low = route_event(_ev(ALERT_CREATED, severity="low"), extra_routes=extra)
    assert "summarizer_agent" not in low.agents
    # Critical: extra step applies and is appended.
    crit = route_event(_ev(ALERT_CREATED, severity="critical"), extra_routes=extra)
    assert crit.agents == ["dedup_agent", "correlation_agent", "summarizer_agent"]


def test_match_against_label():
    extra = {INCIDENT_CREATED: [RouteStep("notification_agent", match={"alert_kind": "crashloop"})]}
    ev = _ev(INCIDENT_CREATED, labels={"alert_kind": "crashloop"})
    assert "notification_agent" in route_event(ev, extra_routes=extra).agents


def test_duplicate_agents_collapse_preserving_first_order():
    extra = {INCIDENT_CREATED: [RouteStep("summarizer_agent")]}  # already in default
    d = route_event(_ev(INCIDENT_CREATED), extra_routes=extra)
    assert d.agents == ["summarizer_agent"]


def test_default_routing_table_is_json_able():
    table = default_routing_table()
    assert set(table) == set(DEFAULT_ROUTES)
    for steps in table.values():
        for s in steps:
            assert set(s) == {"agent", "match"}


# --------------------------------------------------------------------------- #
# Cross-check: every routed agent is a real, non-investigator (lifecycle) agent
# --------------------------------------------------------------------------- #
def test_routed_agents_exist_and_are_lifecycle_agents():
    reg = RoleRegistry()
    routed = {s.agent for steps in DEFAULT_ROUTES.values() for s in steps}
    for name in routed:
        role = reg.get(name)
        assert role is not None, f"routed agent {name} is not in the agent registry"
        assert role.kind != INVESTIGATOR_KIND, (
            f"{name} is an RCA investigator; the trigger router should only "
            f"dispatch lifecycle agents"
        )
