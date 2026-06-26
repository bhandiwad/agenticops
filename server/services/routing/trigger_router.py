"""Pure trigger-routing engine: lifecycle event -> ordered typed agents.

The router maps a :class:`LifecycleEvent` to an ordered list of agent names
(roles from the agent registry) that should run for that event. Routing is:

  1. DEFAULT_ROUTES — the built-in mapping (this module),
  2. minus any event types an org has disabled (org trigger-rule overlay),
  3. minus any agents the org has disabled (agent_overrides),
  4. plus per-step ``match`` conditions evaluated against the event.

This module is pure (no DB / no agent execution). Callers pass the org's
disabled sets in; execution of the resulting agents is a separate concern
(the executor + lifecycle-hook wiring, dispatched via Celery).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional

from services.routing.events import (
    ALERT_CREATED,
    INCIDENT_CREATED,
    INCIDENT_RESOLVED,
    RCA_COMPLETED,
    LifecycleEvent,
)


@dataclass(frozen=True)
class RouteStep:
    """One dispatch target for an event, optionally gated by ``match``.

    ``ref`` is an agent name (``target_type='agent'``) or a workflow key
    (``target_type='workflow'``). ``match`` is a dict of
    ``event field -> required value``; the step applies only when every
    condition matches the event (top-level field or label).
    """

    ref: str
    target_type: str = "agent"
    match: Optional[Dict[str, str]] = None

    @property
    def agent(self) -> str:
        """Backward-compatible alias for ``ref`` (agent targets)."""
        return self.ref


# Built-in routing. Order within a list is the dispatch order. Mirrors the
# AgenticOps lifecycle examples:
#   alert created      -> dedup, then correlation
#   incident created   -> summarize
#   RCA completed      -> summarize -> notify -> postmortem
#   incident resolved  -> postmortem
# Remediation (planner -> approval -> executor) is intentionally NOT auto-routed
# yet; it requires the HITL approval gate (Phase 4).
DEFAULT_ROUTES: Dict[str, List[RouteStep]] = {
    ALERT_CREATED: [
        RouteStep("dedup_agent"),
        RouteStep("correlation_agent"),
    ],
    INCIDENT_CREATED: [
        RouteStep("summarizer_agent"),
    ],
    RCA_COMPLETED: [
        RouteStep("summarizer_agent"),
        RouteStep("notification_agent"),
        RouteStep("postmortem_agent"),
    ],
    INCIDENT_RESOLVED: [
        RouteStep("postmortem_agent"),
    ],
}


def _step_matches(step: RouteStep, event: LifecycleEvent) -> bool:
    if not step.match:
        return True
    return all(event.field_value(k) == v for k, v in step.match.items())


@dataclass(frozen=True)
class RoutingDecision:
    event_type: str
    agents: List[str]            # agent refs only, ordered/de-duped (compat)
    suppressed: List[str]        # agents dropped because disabled (org/agent)
    targets: List[dict]          # ordered [{target_type, ref}] — agents + workflows


def route_event(
    event: LifecycleEvent,
    *,
    disabled_event_types: FrozenSet[str] = frozenset(),
    disabled_agents: FrozenSet[str] = frozenset(),
    extra_routes: Optional[Dict[str, List[RouteStep]]] = None,
) -> RoutingDecision:
    """Return the ordered targets (agents and/or workflows) to dispatch for ``event``.

    * ``disabled_event_types`` — event types the org has turned off (no targets).
    * ``disabled_agents`` — agents disabled for the org (agent_overrides); removed
      from the result and reported in ``suppressed``.
    * ``extra_routes`` — optional org-defined custom routes merged after defaults.
    """
    if event.event_type in disabled_event_types:
        return RoutingDecision(event.event_type, [], [], [])

    steps: List[RouteStep] = list(DEFAULT_ROUTES.get(event.event_type, []))
    if extra_routes:
        steps += extra_routes.get(event.event_type, [])

    agents: List[str] = []
    suppressed: List[str] = []
    targets: List[dict] = []
    seen = set()
    for step in steps:
        if not _step_matches(step, event):
            continue
        key = (step.target_type, step.ref)
        if key in seen:
            continue
        seen.add(key)
        if step.target_type == "agent":
            if step.ref in disabled_agents:
                suppressed.append(step.ref)
                continue
            agents.append(step.ref)
        targets.append({"target_type": step.target_type, "ref": step.ref})
    return RoutingDecision(event.event_type, agents, suppressed, targets)


def default_routing_table() -> Dict[str, List[dict]]:
    """JSON-able view of the built-in routes (for the API/UI)."""
    return {
        et: [{"target_type": s.target_type, "ref": s.ref, "match": s.match} for s in steps]
        for et, steps in DEFAULT_ROUTES.items()
    }


__all__ = [
    "RouteStep",
    "RoutingDecision",
    "DEFAULT_ROUTES",
    "route_event",
    "default_routing_table",
]
