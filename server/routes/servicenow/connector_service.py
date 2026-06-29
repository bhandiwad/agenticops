"""High-level ServiceNow connector operations for agents and routes.

Agents should call these functions (or the agent tools that wrap them) instead
of making raw Table API calls directly.
"""
from __future__ import annotations

import logging
from typing import Any

from .snow_client import ServiceNowAPIError, ServiceNowClient, get_client

logger = logging.getLogger(__name__)


def get_ticket_context(
    *,
    ticket_number: str | None = None,
    sys_id: str | None = None,
    table: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Fetch a normalized ticket document (single connector entrypoint)."""
    client = get_client(user_id)
    try:
        if ticket_number:
            doc = client.get_ticket_by_number(ticket_number)
        elif sys_id:
            doc = client.get_ticket_by_sys_id(sys_id, table=table)
        else:
            return {"error": "ticket_number or sys_id is required"}
        return {"status": "ok", **doc}
    except ServiceNowAPIError as exc:
        return {"error": str(exc)}
    except ValueError as exc:
        return {"error": str(exc)}


def resolve_ticket_for_incident(
    *,
    incident_id: str,
    resolution_notes: str = "",
    user_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the SNOW ticket linked to an Aurora incident."""
    from chat.backend.agent.tools.servicenow_tool import _load_snow_link

    client = get_client(user_id)
    link = _load_snow_link(incident_id, user_id)
    if link.get("error"):
        return link
    try:
        result = client.resolve_ticket(
            link["snow_sys_id"],
            table=link.get("snow_table"),
            close_notes=resolution_notes,
        )
        result["incident_id"] = incident_id
        result["snow_table"] = link.get("snow_table") or client.table
        result["snow_url"] = link.get("snow_url")
        if not result.get("snow_number"):
            result["snow_number"] = link.get("snow_number")
        return result
    except ServiceNowAPIError as exc:
        return {"error": str(exc), "incident_id": incident_id}


def validate_credentials(client: ServiceNowClient) -> dict[str, Any]:
    """Connectivity probe used by /connect and /status."""
    try:
        info = client.validate_connection()
        return {"ok": True, "table": info.get("table"), "instance": client.instance}
    except ServiceNowAPIError as exc:
        return {"ok": False, "error": str(exc)}
