"""Lifecycle event schema for the trigger router.

A :class:`LifecycleEvent` is the normalized shape emitted at incident lifecycle
transitions (alert ingested, incident created, RCA completed, incident
resolved). The trigger router maps an event to an ordered list of typed agents
to dispatch. Pure data — no DB or agent imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

# Canonical event types. These align with the existing inline trigger points:
#   alert_created      — webhook ingestion (routes/<provider>/tasks.py)
#   incident_created   — INSERT INTO incidents
#   rca_completed      — background RCA finishes (chat/background/task.py)
#   incident_resolved  — incident status -> resolved (incidents_routes.py)
ALERT_CREATED = "alert_created"
INCIDENT_CREATED = "incident_created"
RCA_COMPLETED = "rca_completed"
INCIDENT_RESOLVED = "incident_resolved"

EVENT_TYPES = (
    ALERT_CREATED,
    INCIDENT_CREATED,
    RCA_COMPLETED,
    INCIDENT_RESOLVED,
)


@dataclass(frozen=True)
class LifecycleEvent:
    """A normalized incident lifecycle event.

    ``labels`` carries free-form metadata (e.g. ``{"alert_kind": "crashloop"}``)
    that custom routing rules can match on. ``severity``/``source``/``service``
    are promoted to top-level fields because routing commonly keys on them.
    """

    event_type: str
    org_id: str
    incident_id: Optional[str] = None
    source: Optional[str] = None        # pagerduty | datadog | grafana | ...
    severity: Optional[str] = None      # critical | high | medium | low
    service: Optional[str] = None
    labels: Dict[str, str] = field(default_factory=dict)

    def field_value(self, key: str) -> Optional[str]:
        """Resolve a match key against top-level fields, then labels."""
        if key in ("event_type", "org_id", "incident_id", "source", "severity", "service"):
            return getattr(self, key)
        return self.labels.get(key)
