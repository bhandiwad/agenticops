"""Agent tools for reading CFX enriched incident join documents.

These tools expose the RCA/postmortem foundation built by the cfx_rca ingest
pipeline. They are read-only against the local enriched store (JSON by default).
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .cfx_rca_context import (
    is_cfx_rca_store_available,
    load_enriched_doc,
    normalize_ticket_number,
    output_dir,
    resolve_incident_id,
)


def _load_index() -> dict[str, Any]:
    path = output_dir() / "index.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


class GetCfxEnrichedIncidentArgs(BaseModel):
    cfx_incident_id: str = Field(
        default="",
        description="CloudFabrix incident id, e.g. CFX20260626264027f973",
    )
    ticket_number: str = Field(
        default="",
        description="ServiceNow ticket number, e.g. IT#0011459657",
    )


class ListCfxEnrichedIncidentsArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=50, description="Max incidents to return")
    severity: str = Field(default="", description="Optional filter: High, Critical, etc.")
    has_snow_ticket: bool = Field(
        default=False,
        description="If true, only return incidents linked to a ServiceNow ticket",
    )


class CfxLiveEnrichIncidentArgs(BaseModel):
    cfx_incident_id: str = Field(
        default="",
        description="CloudFabrix incident id, e.g. CFX20260626264027f973",
    )
    ticket_number: str = Field(
        default="",
        description="ServiceNow ticket number, e.g. IT#0011459657",
    )
    max_depth: int = Field(
        default=1,
        ge=0,
        le=2,
        description="Topology traversal depth for dependents (default 1)",
    )


def get_cfx_enriched_incident(
    cfx_incident_id: str = "",
    ticket_number: str = "",
    user_id: str | None = None,
    **kwargs,
) -> str:
    """Load a CFX enriched incident join document (CFX + SNOW + topology)."""
    ticket_number = normalize_ticket_number(ticket_number)
    inc_id = resolve_incident_id(
        cfx_incident_id=cfx_incident_id, ticket_number=ticket_number
    )
    if not inc_id:
        return json.dumps({
            "error": "Provide cfx_incident_id or ticket_number.",
            "cfx_incident_id": cfx_incident_id or None,
            "ticket_number": ticket_number or None,
            "store": str(output_dir()),
            "store_available": is_cfx_rca_store_available(),
        })
    doc = load_enriched_doc(cfx_incident_id=inc_id)
    if not doc:
        return json.dumps({
            "error": f"No enriched document found for {inc_id}. "
                     "Run the CFX RCA Poll Agent or manual ingest first.",
            "cfx_incident_id": inc_id,
            "ticket_number": ticket_number or None,
            "store": str(output_dir()),
        })
    return json.dumps({
        "status": "ok",
        "cfx_incident_id": inc_id,
        "incident": doc.get("incident"),
        "snow": doc.get("snow"),
        "affected_assets": doc.get("affected_assets"),
        "topology": doc.get("topology"),
        "correlation": doc.get("correlation"),
        "join_keys": doc.get("join_keys"),
        "agent_context": doc.get("agent_context"),
    })


def cfx_live_enrich_incident(
    cfx_incident_id: str = "",
    ticket_number: str = "",
    max_depth: int = 1,
    user_id: str | None = None,
    **kwargs,
) -> str:
    """Live-fetch one CFX incident with SNOW linkage and topology (connector-backed)."""
    from routes.cloudfabrix.connector_service import live_enrich_incident

    ticket_number = normalize_ticket_number(ticket_number)
    if not (cfx_incident_id or "").strip() and not ticket_number:
        return json.dumps({
            "error": "Provide cfx_incident_id or ticket_number for live CFX enrichment.",
        })
    result = live_enrich_incident(
        cfx_incident_id=cfx_incident_id,
        ticket_number=ticket_number,
        user_id=user_id,
        max_depth=max_depth,
    )
    return json.dumps(result)


def list_cfx_enriched_incidents(
    limit: int = 10,
    severity: str = "",
    has_snow_ticket: bool = False,
    user_id: str | None = None,
    **kwargs,
) -> str:
    """List recent CFX enriched incidents from the local join store."""
    index = _load_index()
    if not index:
        return json.dumps({
            "error": "Enriched incident store is empty. Run CFX RCA Poll Agent first.",
            "store": str(output_dir()),
        })
    items: list[dict[str, Any]] = []
    sev_filter = (severity or "").strip().lower()
    for inc_id, meta in index.items():
        if sev_filter and (meta.get("severity") or "").lower() != sev_filter:
            continue
        if has_snow_ticket and not meta.get("snow_ticket_number"):
            continue
        items.append({
            "cfx_incident_id": inc_id,
            "snow_ticket_number": meta.get("snow_ticket_number"),
            "severity": meta.get("severity"),
            "status": meta.get("status"),
            "asset_ips": meta.get("asset_ips"),
            "matched_nodes": meta.get("matched_nodes"),
            "dependents": meta.get("dependents"),
        })
    items.sort(key=lambda x: x["cfx_incident_id"], reverse=True)
    return json.dumps({
        "status": "ok",
        "count": len(items[:limit]),
        "total_indexed": len(index),
        "incidents": items[:limit],
        "store": str(output_dir()),
    })
