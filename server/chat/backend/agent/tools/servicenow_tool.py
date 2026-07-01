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

    if not user_id:
        return {"error": "User context required to look up incident."}
    with db_pool.get_admin_connection() as conn:
        with conn.cursor() as cursor:
            # RLS-protected `incidents` — always scope by org (never query without context).
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


class UpdateServiceNowTicketArgs(BaseModel):
    note: str = Field(description="Work note to append to the ticket — what the workflow did and its outcome.")
    ticket_number: str = Field(default="", description="ServiceNow ticket number (e.g. INC0012345). Provide this OR incident_id.")
    incident_id: str = Field(default="", description="Aurora incident UUID whose linked ticket to update. Provide this OR ticket_number.")
    resolve: bool = Field(default=False, description="Also move the ticket to its resolved state.")


def update_servicenow_ticket(
    note: str,
    ticket_number: str = "",
    incident_id: str = "",
    resolve: bool = False,
    user_id: str | None = None,
    **kwargs,
) -> str:
    """Append a work note to a ServiceNow ticket (optionally resolving it) so an automation
    workflow records what it did on the associated ticket. Identify the ticket by
    ``incident_id`` (uses the incident's linked ticket) or by ``ticket_number``."""
    from routes.servicenow.snow_client import load_client_for_user, load_client_from_env

    if not (note or "").strip():
        return json.dumps({"error": "note is required"})

    client = (load_client_for_user(user_id) if user_id else None) or load_client_from_env()
    if client is None:
        return json.dumps({"error": "ServiceNow is not connected"})

    sys_id: str | None = None
    table: str | None = None
    if incident_id:
        link = _load_snow_link(incident_id, user_id)
        if link.get("error"):
            return json.dumps(link)
        sys_id, table = link["snow_sys_id"], link.get("snow_table")
    elif ticket_number:
        try:
            t = client.get_ticket_by_number(ticket_number)
            sys_id, table = t.get("snow_sys_id"), t.get("snow_table")
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"Ticket lookup failed: {exc}"})
    else:
        return json.dumps({"error": "Provide either ticket_number or incident_id"})

    if not sys_id:
        return json.dumps({"error": "Could not resolve the ticket sys_id"})

    try:
        result = client.add_work_note(sys_id, note, table=table)
        if resolve:
            result["resolve"] = client.resolve_ticket(sys_id, table=table, close_notes=note)
        logger.info("[ServiceNowTool] Updated ticket %s (resolve=%s)", result.get("snow_number"), resolve)
        return json.dumps({"ok": True, **result})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})
