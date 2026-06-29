"""
ServiceNow tools for Aurora agents.

Uses the ServiceNow connector (Vault credentials per user) with .env fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def is_servicenow_connected(user_id: str | None = None) -> bool:
    """True when per-user connector credentials or legacy SNOW_* env vars are configured."""
    try:
        from routes.servicenow.snow_client import load_client_for_user, load_client_from_env

        if user_id and load_client_for_user(user_id):
            return True
        return load_client_from_env() is not None
    except Exception as exc:
        logger.debug("[ServiceNowTool] Connection check failed: %s", exc)
        return False


class ResolveServiceNowTicketArgs(BaseModel):
    incident_id: str = Field(description="Aurora incident UUID")
    resolution_notes: str = Field(
        default="",
        description="Brief resolution summary (root cause + remediation). Optional but recommended.",
    )


class GetServiceNowTicketArgs(BaseModel):
    incident_id: str = Field(description="Aurora incident UUID")


class GetServiceNowTicketByNumberArgs(BaseModel):
    ticket_number: str = Field(
        description="ServiceNow ticket number, e.g. IT#0011459406 or INC0012345",
    )


def _load_snow_link(incident_id: str, user_id: str | None) -> dict[str, Any]:
    from utils.auth.stateless_auth import set_rls_context
    from utils.db.connection_pool import db_pool

    with db_pool.get_admin_connection() as conn:
        with conn.cursor() as cursor:
            if user_id:
                set_rls_context(cursor, conn, user_id, log_prefix="[ServiceNowTool]")
            cursor.execute(
                "SELECT alert_metadata FROM incidents WHERE id = %s::uuid",
                (incident_id,),
            )
            row = cursor.fetchone()
    if not row:
        return {"error": f"Incident {incident_id} not found."}
    metadata = row[0] if isinstance(row[0], dict) else {}
    sys_id = (
        metadata.get("snow_sys_id")
        or metadata.get("servicenow_sys_id")
        or metadata.get("service_now_sys_id")
    )
    if not sys_id:
        return {
            "error": "No ServiceNow ticket linked to this incident (missing snow_sys_id in alert_metadata).",
            "alert_metadata_keys": sorted(metadata.keys()),
        }
    return {
        "snow_sys_id": str(sys_id),
        "snow_number": metadata.get("snow_number"),
        "snow_table": metadata.get("snow_table"),
        "snow_url": metadata.get("snow_url"),
    }


def get_servicenow_ticket_by_number(
    ticket_number: str,
    user_id: str | None = None,
    **kwargs,
) -> str:
    """Fetch a ServiceNow ticket by its number (read-only)."""
    from routes.servicenow.connector_service import get_ticket_context

    result = get_ticket_context(ticket_number=ticket_number, user_id=user_id)
    return json.dumps(result)


def get_servicenow_ticket_for_incident(
    incident_id: str,
    user_id: str | None = None,
    **kwargs,
) -> str:
    """Load the linked ServiceNow ticket metadata and current state."""
    if not incident_id:
        return json.dumps({"error": "incident_id is required."})

    link = _load_snow_link(incident_id, user_id)
    if link.get("error"):
        return json.dumps(link)

    from routes.servicenow.connector_service import get_ticket_context

    result = get_ticket_context(
        sys_id=link["snow_sys_id"],
        table=link.get("snow_table"),
        user_id=user_id,
    )
    if result.get("error"):
        return json.dumps(result)
    result["incident_id"] = incident_id
    result["snow_number"] = result.get("ticket_number") or link.get("snow_number")
    result["current_state"] = result.pop("state", None)
    return json.dumps(result)


def resolve_servicenow_ticket(
    incident_id: str,
    resolution_notes: str = "",
    user_id: str | None = None,
    **kwargs,
) -> str:
    """Resolve the ServiceNow ticket linked to an Aurora incident."""
    from routes.servicenow.connector_service import resolve_ticket_for_incident

    if not incident_id:
        return json.dumps({"error": "incident_id is required."})
    result = resolve_ticket_for_incident(
        incident_id=incident_id,
        resolution_notes=resolution_notes,
        user_id=user_id,
    )
    if result.get("status") == "resolved":
        logger.info(
            "[ServiceNowTool] Resolved ticket %s (%s) for incident %s",
            result.get("snow_number"),
            result.get("snow_sys_id"),
            incident_id,
        )
    return json.dumps(result)
