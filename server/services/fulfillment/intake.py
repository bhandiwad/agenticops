"""Ticket intake: classify an inbound ticket's intent and route it to the fulfillment engine.

Generic SNOW-ticket model (per product decision): a ticket carries a table/type, a category,
and short_description/description. We classify intent = incident | service_request | change,
then service requests are fulfilled via the generic engine (same catalog/policy as remediation).
Incidents defer to the existing RCA path (which drives remediation on completion).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from services.fulfillment import catalog as cat
from services.fulfillment import engine

logger = logging.getLogger(__name__)

INCIDENT = "incident"
SERVICE_REQUEST = "service_request"
CHANGE = "change"
UNKNOWN = "unknown"

# SNOW tables → intent.
_TABLE_INTENT = {
    "incident": INCIDENT,
    "sc_req_item": SERVICE_REQUEST, "sc_task": SERVICE_REQUEST, "sc_request": SERVICE_REQUEST,
    "change_request": CHANGE,
}
_SR_HINTS = ("request", "provision", "create", "add ", "onboard", "grant", "access",
             "new user", "report", "install", "enable", "open port", "backup")
_INC_HINTS = ("down", "outage", "error", "failure", "failed", "unreachable", "breach",
              "not working", "degraded", "high cpu", "disk full", "crash")


def classify_intent(ticket: Dict[str, Any]) -> str:
    """Best-effort intent from table, then category/keywords."""
    table = str(ticket.get("table") or ticket.get("type") or "").strip().lower()
    if table in _TABLE_INTENT:
        return _TABLE_INTENT[table]

    text = " ".join(str(ticket.get(f, "")) for f in ("short_description", "description", "category")).lower()
    sr = sum(1 for h in _SR_HINTS if h in text)
    inc = sum(1 for h in _INC_HINTS if h in text)
    if sr > inc and sr > 0:
        return SERVICE_REQUEST
    if inc > 0:
        return INCIDENT
    return UNKNOWN


def handle_ticket(ticket: Dict[str, Any], user_id: str, org_id: str) -> Dict[str, Any]:
    """Classify a ticket and, for a service request, plan+dispatch via the fulfillment engine.

    Incidents are acknowledged and left to the RCA path (which triggers remediation on
    completion). Fail-safe: always returns a status dict.
    """
    intent = classify_intent(ticket)
    number = ticket.get("number") or ticket.get("ticket_number")
    text = " ".join(str(ticket.get(f, "")) for f in ("short_description", "description")).strip()
    category = ticket.get("category")

    if intent == SERVICE_REQUEST:
        result = engine.plan_and_dispatch(
            intent=cat.SERVICE_REQUEST, text=text, user_id=user_id, org_id=org_id,
            category=category, ticket_number=number,
        )
        result["classified_intent"] = intent
        return result

    if intent == INCIDENT:
        return {"status": "deferred_to_rca", "classified_intent": intent, "ticket_number": number}

    return {"status": "unclassified", "classified_intent": intent, "ticket_number": number}
