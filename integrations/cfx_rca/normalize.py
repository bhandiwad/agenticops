"""Source-agnostic normalizer.

Converts a raw CFX incident record (from a pstream poll OR a future webhook
payload) into the canonical IncidentCore + SnowTicket + AffectedAsset parts.

Field name handling is deliberately permissive: CFX uses several shapes across
streams (`i_*`, `attrs_*`, alert `a_*`, external-ticket fields). All known
variants map to the same canonical fields, so the poller and webhook produce
identical output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import (
    AffectedAsset,
    Correlation,
    IncidentCore,
    SnowTicket,
    _clean,
)

SNOW_INSTANCE_DEFAULT = "https://sifytest.service-now.com"
SNOW_TABLE_DEFAULT = "x_sitl_goinfinit_sify_task"


def _first(record: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in record:
            v = _clean(record.get(k))
            if v is not None:
                return v
    return None


def _ms_to_iso(value: Any) -> str | None:
    v = _clean(value)
    if v is None:
        return None
    try:
        # Epoch millis (int or numeric string)
        ms = int(float(v))
        if ms > 10_000_000_000:  # treat as millis
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
        if ms > 1_000_000_000:   # seconds
            return datetime.fromtimestamp(ms, tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        pass
    return str(v)  # already an ISO string


def normalize_incident_core(record: dict[str, Any]) -> IncidentCore:
    return IncidentCore(
        cfx_incident_id=_first(record, "incident_id", "i_incident_id", "incidentid"),
        project_id=_first(record, "project_id", "projectid"),
        customer_id=_first(record, "customer_id", "customerid"),
        summary=_first(record, "i_summary", "summary", "subject"),
        description=_first(record, "i_description", "description"),
        incident_type=_first(record, "i_cfx_incident_type", "incident_type", "attrs_alert_type"),
        severity=_first(record, "attrs_alert_severity", "i_severity", "severity"),
        status=_first(record, "i_status", "status", "attrs_Alert_Status"),
        alert_count=_to_int(_first(record, "attrs_incidentAnalytics_alerts", "attrs_i_alert_count")),
        alert_sources=_split(_first(record, "attrs_incidentAnalytics_alert_sources",
                                    "attrs_i_alert_sources", "attrs_Alert_Source", "Alert_Source")),
        created_ts=_ms_to_iso(_first(record, "i_created_ts", "created_ts", "a_created_ts")),
        occurred_ts=_ms_to_iso(_first(record, "i_cfx_incident_occurred", "occurred_ts")),
        updated_ts=_ms_to_iso(_first(record, "i_updated_ts", "updated_ts")),
        resolved_ts=_ms_to_iso(_first(record, "i_resolved_at_ts", "resolved_ts")),
        closed_ts=_ms_to_iso(_first(record, "i_closed_at_ts", "closed_ts")),
    )


def normalize_snow_ticket(record: dict[str, Any]) -> SnowTicket:
    number = _first(
        record,
        "i_itsm_ticket_number", "ticket_number", "external_ticket_number",
        "itsm_ticket_number", "snow_number",
    )
    sys_id = _first(
        record,
        "ticket_id", "external_ticket_id", "attrs_snow_task_sysid", "snow_sys_id",
    )
    status = _first(record, "external_ticket_status", "i_itsm_ticket_status", "ticket_status")
    url = _first(record, "externalUrl", "external_url", "link", "snow_url")
    if not url and sys_id:
        url = f"{SNOW_INSTANCE_DEFAULT}/{SNOW_TABLE_DEFAULT}.do?sys_id={sys_id}"
    return SnowTicket(
        ticket_number=number,
        ticket_sys_id=sys_id,
        ticket_status=status,
        company_sys_id=_first(record, "attrs_snow_company_sysid", "company_sys_id"),
        ci_sys_id=_first(record, "attrs_snow_ci_sysid", "ci_sys_id"),
        service_request_type=_first(record, "attrs_snow_service_request_type", "service_request_type"),
        url=url,
    )


def normalize_affected_assets(record: dict[str, Any]) -> list[AffectedAsset]:
    ip = _first(record, "attrs_alert_asset_ip", "attrs_alert-asset-name",
                "a_asset_ip_address", "a_en_alert_asset_ip", "asset_ip")
    name = _first(record, "attrs_alert_assetname", "a_asset_name",
                  "a_en_alert_assetname", "asset_name")
    ci_name = _first(record, "attrs_ci_name", "ci_name")
    asset = AffectedAsset(
        ip=ip,
        name=name,
        ci_name=ci_name,
        ci_sys_id=_first(record, "attrs_snow_ci_sysid", "ci_sys_id"),
        node_type=_first(record, "attrs_node_type", "a_en_node_type", "node_type"),
        layer=_first(record, "attrs_layer_id", "layer_id", "layer"),
        shortname=_first(record, "attrs_asset_shortname", "a_en_asset_shortname"),
        alert_source=_first(record, "attrs_Alert_Source", "a_en_Alert_Source", "Alert_Source"),
    )
    # Only return if it carries at least one identifying field
    if any([asset.ip, asset.name, asset.ci_name, asset.ci_sys_id]):
        return [asset]
    return []


def normalize_correlation(record: dict[str, Any]) -> Correlation:
    members: list[str] = []
    for k, v in record.items():
        if k.startswith("attrs_sibling_correlation_parents"):
            cv = _clean(v)
            if cv:
                members.append(str(cv))
    parent = _first(record, "a_correlation_parent", "correlation_parent")
    return Correlation(
        correlation_batch_id=_first(record, "correlation_batch_id", "a_correlation_batch_id"),
        parent_incident_id=parent,
        member_alert_ids=members,
    )


def _to_int(value: Any) -> int | None:
    v = _clean(value)
    if v is None:
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _split(value: Any) -> list[str]:
    v = _clean(value)
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [s.strip() for s in str(v).replace("|", ",").split(",") if s.strip()]
