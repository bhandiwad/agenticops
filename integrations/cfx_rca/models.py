"""Canonical data models for the enrichment join.

These dataclasses define the stable contract that Aurora agents will consume.
The same structures are produced whether data arrives via polling (now) or via
webhooks (later), so downstream agents never need to change.

Schema is versioned (SCHEMA_VERSION) so future additive changes remain
backward-compatible.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

SCHEMA_VERSION = "1.0"


def _clean(value: Any) -> Any:
    """Treat CFX placeholders / empties as None."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() in ("not available", "none", "null", "n/a"):
        return None
    if s.startswith("{$") and s.endswith("}"):  # unresolved template placeholder
        return None
    return value


@dataclass
class IngestMeta:
    source: str                  # cfx_poll | cfx_webhook | snow_webhook | ...
    source_stream: str = ""      # originating pstream / endpoint
    ingested_at: str = ""
    schema_version: str = SCHEMA_VERSION


@dataclass
class SnowTicket:
    ticket_number: str | None = None     # e.g. IT#0011459621
    ticket_sys_id: str | None = None
    ticket_status: str | None = None
    company_sys_id: str | None = None
    ci_sys_id: str | None = None
    service_request_type: str | None = None
    url: str | None = None
    source_stream: str | None = None

    @property
    def linked(self) -> bool:
        return bool(self.ticket_number or self.ticket_sys_id)


@dataclass
class AffectedAsset:
    ip: str | None = None
    name: str | None = None
    ci_name: str | None = None
    ci_sys_id: str | None = None
    node_type: str | None = None
    layer: str | None = None
    shortname: str | None = None
    alert_source: str | None = None


@dataclass
class TopologyNodeRef:
    node_key: str | None = None
    node_id: str | None = None
    node_type: str | None = None
    layer: str | None = None
    label: str | None = None
    matched_by: str | None = None        # ip | ci_name | name


@dataclass
class TopologyDependent:
    node_id: str | None = None
    label: str | None = None
    node_type: str | None = None
    layer: str | None = None
    relation_type: str | None = None
    direction: str | None = None         # inbound | outbound
    depth: int = 1


@dataclass
class TopologyView:
    resolved: bool = False
    graph_name: str | None = None
    db_name: str | None = None
    matched_nodes: list[TopologyNodeRef] = field(default_factory=list)
    dependents: list[TopologyDependent] = field(default_factory=list)
    impacted_layers: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class Correlation:
    correlation_batch_id: str | None = None
    parent_incident_id: str | None = None
    member_alert_ids: list[str] = field(default_factory=list)
    related_incident_ids: list[str] = field(default_factory=list)


@dataclass
class JoinKeys:
    """The heart of the cross-system join. Stable keys agents query by."""
    cfx_incident_id: str | None = None
    snow_ticket_number: str | None = None
    snow_ticket_sys_id: str | None = None
    asset_ips: list[str] = field(default_factory=list)
    ci_sys_ids: list[str] = field(default_factory=list)
    ci_names: list[str] = field(default_factory=list)


@dataclass
class IncidentCore:
    cfx_incident_id: str | None = None
    project_id: str | None = None
    customer_id: str | None = None
    org_name: str | None = None
    summary: str | None = None
    description: str | None = None
    incident_type: str | None = None
    severity: str | None = None
    status: str | None = None
    alert_count: int | None = None
    alert_sources: list[str] = field(default_factory=list)
    created_ts: str | None = None
    occurred_ts: str | None = None
    updated_ts: str | None = None
    resolved_ts: str | None = None
    closed_ts: str | None = None


@dataclass
class AgentContext:
    """Pre-baked natural-language seeds so Aurora LLM agents can act directly."""
    rca_seed: str = ""
    postmortem_seed: str = ""
    snow_seed: str = ""


@dataclass
class EnrichedIncident:
    ingest: IngestMeta
    incident: IncidentCore
    snow: SnowTicket
    affected_assets: list[AffectedAsset]
    topology: TopologyView
    correlation: Correlation
    join_keys: JoinKeys
    agent_context: AgentContext
    raw_sample: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
