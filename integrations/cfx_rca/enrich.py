"""The join/enrichment step.

Takes a single raw CFX incident record (poll or webhook), normalizes it, resolves
its affected asset(s) against the topology index, and produces a fully-joined
EnrichedIncident with cross-system keys and LLM-ready context seeds.

Optionally merges a SNOW ticket detail dict (e.g. fetched live from ServiceNow
or arriving via a SNOW webhook) to override/augment the ticket section.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import (
    AgentContext,
    EnrichedIncident,
    IngestMeta,
    JoinKeys,
    SnowTicket,
)
from .normalize import (
    normalize_affected_assets,
    normalize_correlation,
    normalize_incident_core,
    normalize_snow_ticket,
)
from .topology import TopologyIndex

ORG_NAME_DEFAULT = "Sify_IT_Services"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def build_join_keys(core, snow: SnowTicket, assets) -> JoinKeys:
    return JoinKeys(
        cfx_incident_id=core.cfx_incident_id,
        snow_ticket_number=snow.ticket_number,
        snow_ticket_sys_id=snow.ticket_sys_id,
        asset_ips=sorted({a.ip for a in assets if a.ip}),
        ci_sys_ids=sorted({a.ci_sys_id for a in assets if a.ci_sys_id}
                          | ({snow.ci_sys_id} if snow.ci_sys_id else set())),
        ci_names=sorted({a.ci_name for a in assets if a.ci_name}
                        | {a.name for a in assets if a.name}),
    )


def build_agent_context(core, snow, assets, topo) -> AgentContext:
    asset_str = ", ".join(
        filter(None, [a.name or a.ci_name or a.ip for a in assets])
    ) or "unknown asset"
    snow_str = (
        f"ServiceNow ticket {snow.ticket_number}"
        + (f" (status {snow.ticket_status})" if snow.ticket_status else "")
        if snow.ticket_number else "no linked ServiceNow ticket"
    )
    dependents = len(topo.dependents)
    matched = len(topo.matched_nodes)
    layers = ", ".join(topo.impacted_layers) or "n/a"

    rca = (
        f"CFX incident {core.cfx_incident_id} ({core.incident_type or 'incident'}, "
        f"severity {core.severity or 'n/a'}, status {core.status or 'n/a'}) affecting "
        f"{asset_str}. Linked to {snow_str}. Topology resolution: {matched} matched "
        f"node(s), {dependents} dependent component(s) across layers [{layers}]. "
        f"Use the topology.dependents list to trace downstream impact and the "
        f"correlation block to group related alerts when determining root cause."
    )
    postmortem = (
        f"Postmortem seed for {core.cfx_incident_id}: impact began "
        f"{core.occurred_ts or core.created_ts or 'unknown'}, affected primary asset "
        f"{asset_str} with {dependents} dependent component(s) potentially impacted "
        f"(layers: {layers}). Reference {snow_str} for remediation/closure notes. "
        f"Alert volume: {core.alert_count if core.alert_count is not None else 'n/a'} "
        f"from sources {', '.join(core.alert_sources) or 'n/a'}."
    )
    snow_seed = (
        f"{snow_str}. Company sys_id {snow.company_sys_id or 'n/a'}, CI sys_id "
        f"{snow.ci_sys_id or 'n/a'}. URL: {snow.url or 'n/a'}."
    )
    return AgentContext(rca_seed=rca, postmortem_seed=postmortem, snow_seed=snow_seed)


def enrich_record(
    record: dict[str, Any],
    topo: TopologyIndex | None,
    source: str = "cfx_poll",
    source_stream: str = "",
    snow_detail: dict[str, Any] | None = None,
    max_depth: int = 2,
) -> EnrichedIncident:
    core = normalize_incident_core(record)
    core.org_name = core.org_name or ORG_NAME_DEFAULT

    snow = normalize_snow_ticket(record)
    if snow_detail:
        merged = normalize_snow_ticket(snow_detail)
        snow = SnowTicket(
            ticket_number=merged.ticket_number or snow.ticket_number,
            ticket_sys_id=merged.ticket_sys_id or snow.ticket_sys_id,
            ticket_status=merged.ticket_status or snow.ticket_status,
            company_sys_id=merged.company_sys_id or snow.company_sys_id,
            ci_sys_id=merged.ci_sys_id or snow.ci_sys_id,
            service_request_type=merged.service_request_type or snow.service_request_type,
            url=merged.url or snow.url,
            source_stream="snow_detail",
        )
    else:
        snow.source_stream = source_stream

    assets = normalize_affected_assets(record)
    correlation = normalize_correlation(record)

    if topo is not None:
        topo_view = topo.build_view(assets, max_depth=max_depth)
    else:
        from .models import TopologyView
        topo_view = TopologyView(note="Topology index unavailable for this run.")

    join_keys = build_join_keys(core, snow, assets)
    agent_ctx = build_agent_context(core, snow, assets, topo_view)

    return EnrichedIncident(
        ingest=IngestMeta(source=source, source_stream=source_stream, ingested_at=_now_iso()),
        incident=core,
        snow=snow,
        affected_assets=assets,
        topology=topo_view,
        correlation=correlation,
        join_keys=join_keys,
        agent_context=agent_ctx,
        raw_sample={k: record[k] for k in list(record)[:60]},
    )
