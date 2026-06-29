"""ServiceNow connector routes — connect, status, disconnect, ticket lookup."""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from routes.servicenow.connector_service import get_ticket_context, validate_credentials
from routes.servicenow.snow_client import ServiceNowClient
from utils.auth.rbac_decorators import require_permission
from utils.auth.token_management import get_token_data, store_tokens_in_db
from utils.log_sanitizer import sanitize
from utils.secrets.secret_ref_utils import delete_user_secret

logger = logging.getLogger(__name__)

servicenow_bp = Blueprint("servicenow", __name__)


def _get_stored_credentials(user_id: str) -> dict[str, Any] | None:
    try:
        return get_token_data(user_id, "servicenow")
    except Exception as exc:
        logger.error("[ServiceNow] Failed to load credentials for %s: %s", sanitize(user_id), exc)
        return None


@servicenow_bp.route("/connect", methods=["POST"])
@require_permission("connectors", "write")
def connect(user_id: str):
    data = request.get_json(force=True, silent=True) or {}
    instance = ServiceNowClient.normalize_instance_url(data.get("instanceUrl") or data.get("instance"))
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    table = (data.get("table") or "").strip() or None
    verify_ssl = data.get("verifySsl", True)
    if isinstance(verify_ssl, str):
        verify_ssl = verify_ssl.strip().lower() not in ("0", "false", "no")

    if not instance:
        return jsonify({"error": "A valid ServiceNow instance URL is required"}), 400
    if not username:
        return jsonify({"error": "username is required"}), 400
    if not password:
        return jsonify({"error": "password is required"}), 400

    client = ServiceNowClient(
        instance=instance,
        username=username,
        password=password,
        table=table or "incident",
        verify_ssl=verify_ssl,
        resolve_state=(data.get("resolveState") or "4"),
        resolve_active=str(data.get("resolveActive") or "false").lower(),
    )

    probe = validate_credentials(client)
    if not probe.get("ok"):
        logger.warning("[ServiceNow] Connect validation failed for %s: %s", sanitize(user_id), probe.get("error"))
        return jsonify({"error": probe.get("error") or "Failed to validate ServiceNow credentials"}), 502

    token_payload = client.to_token_payload()
    try:
        store_tokens_in_db(user_id, token_payload, "servicenow")
        logger.info("[ServiceNow] Stored credentials for user %s (table=%s)", sanitize(user_id), client.table)
    except Exception as exc:
        logger.exception("[ServiceNow] Failed to store credentials: %s", exc)
        return jsonify({"error": "Failed to store ServiceNow credentials"}), 500

    return jsonify({
        "success": True,
        "connected": True,
        "instanceUrl": client.instance,
        "table": client.table,
        "username": client.username,
    })


@servicenow_bp.route("/status", methods=["GET"])
@require_permission("connectors", "read")
def status(user_id: str):
    creds = _get_stored_credentials(user_id)
    if not creds:
        return jsonify({"connected": False})

    try:
        client = ServiceNowClient.from_token_data(creds)
    except Exception:
        return jsonify({"connected": False, "error": "Invalid stored credentials"})

    probe = validate_credentials(client)
    if not probe.get("ok"):
        return jsonify({
            "connected": False,
            "error": probe.get("error") or "Failed to validate stored credentials",
        })

    return jsonify({
        "connected": True,
        "instanceUrl": client.instance,
        "table": client.table,
        "username": client.username,
    })


@servicenow_bp.route("/disconnect", methods=["POST", "DELETE"])
@require_permission("connectors", "write")
def disconnect(user_id: str):
    try:
        success, deleted_count = delete_user_secret(user_id, "servicenow")
        if not success:
            return jsonify({"success": False, "error": "Failed to delete stored credentials"}), 500
        logger.info("[ServiceNow] Disconnected provider (deleted %s token entries)", deleted_count)
        return jsonify({
            "success": True,
            "message": "ServiceNow disconnected successfully",
            "deleted": deleted_count,
        })
    except Exception:
        logger.exception("[ServiceNow] Failed to disconnect")
        return jsonify({"error": "Failed to disconnect ServiceNow"}), 500


@servicenow_bp.route("/tickets/<ticket_number>", methods=["GET"])
@require_permission("connectors", "read")
def get_ticket(user_id: str, ticket_number: str):
    result = get_ticket_context(ticket_number=ticket_number, user_id=user_id)
    if result.get("error"):
        return jsonify(result), 404
    return jsonify(result)
