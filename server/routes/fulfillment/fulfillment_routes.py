"""Fulfillment routes: ticket intake + catalog listing + per-org auto-policy management.

- GET  /fulfillment/catalog  — list catalog entries (for the Service Catalog UI).
- GET  /fulfillment/policy   — per-entry auto|approval decision + the org auto-allowlist.
- POST /fulfillment/policy   — toggle an entry into/out of the org auto-allowlist.
- POST /fulfillment/intake   — classify a ticket and (for a service request) plan+dispatch.
"""

import logging
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from services.fulfillment import catalog as cat
from services.fulfillment import policy as pol
from services.fulfillment import intake as intk
from utils.auth.rbac_decorators import require_auth_only, require_permission
from utils.auth.stateless_auth import get_org_id_from_request

logger = logging.getLogger(__name__)

fulfillment_bp = Blueprint("fulfillment", __name__)


def _serialize(entry: cat.FulfillmentEntry, org_id: str) -> Dict[str, Any]:
    return {
        "key": entry.key, "title": entry.title, "intent": entry.intent,
        "targetType": entry.target_type, "targetRef": entry.target_ref,
        "riskClass": entry.risk_class, "readOnly": entry.read_only,
        "categories": list(entry.categories), "params": list(entry.params),
        "description": entry.description,
        "decision": pol.decide(entry, org_id),
    }


@fulfillment_bp.route("/fulfillment/catalog", methods=["GET"])
@require_auth_only
def list_catalog(user_id):
    org_id = get_org_id_from_request() or ""
    entries = cat.get_catalog(user_id, org_id)
    return jsonify({"entries": [_serialize(e, org_id) for e in entries]})


@fulfillment_bp.route("/fulfillment/policy", methods=["GET"])
@require_auth_only
def get_policy(user_id):
    org_id = get_org_id_from_request() or ""
    entries = cat.get_catalog(user_id, org_id)
    return jsonify({
        "allowlist": sorted(pol.allowlist(org_id)),
        "orgAllowlist": sorted(pol._org_allowlist(org_id)),
        "entries": [{"key": e.key, "riskClass": e.risk_class, "readOnly": e.read_only,
                     "decision": pol.decide(e, org_id)} for e in entries],
    })


@fulfillment_bp.route("/fulfillment/policy", methods=["POST"])
@require_permission("connectors", "write")
def set_policy(user_id):
    org_id = get_org_id_from_request() or ""
    payload = request.get_json(force=True, silent=True) or {}
    key = (payload.get("key") or "").strip()
    enabled = bool(payload.get("auto"))
    if not key or cat.get_entry(key) is None:
        return jsonify({"error": "unknown catalog entry key"}), 400
    entry = cat.get_entry(key)
    if enabled and entry.risk_class == cat.RISK_PRIVILEGED:
        return jsonify({"error": "privileged entries cannot be set to auto"}), 400
    ok = pol.set_org_auto(org_id, key, enabled)
    return jsonify({"success": ok, "key": key, "auto": enabled})


@fulfillment_bp.route("/fulfillment/intake", methods=["POST"])
@require_permission("connectors", "write")
def intake(user_id):
    org_id = get_org_id_from_request() or ""
    ticket = request.get_json(force=True, silent=True) or {}
    if not ticket:
        return jsonify({"error": "ticket payload required"}), 400
    result = intk.handle_ticket(ticket, user_id, org_id)
    return jsonify(result)
