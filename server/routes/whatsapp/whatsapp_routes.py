"""WhatsApp (Meta Cloud API) connector routes: connect / status / disconnect + test send.

Credentials (access token + phone number id + API version) are validated against the Meta
Graph API, then stored via the central token helpers (Vault-backed). Automated message sending
happens through the send_whatsapp agent tool (used as a workflow notification step).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from connectors.whatsapp_connector.client import WhatsAppClient, WhatsAppAPIError
from routes.whatsapp.config import DEFAULT_API_VERSION
from utils.auth.rbac_decorators import require_permission
from utils.auth.token_management import get_token_data, store_tokens_in_db
from utils.log_sanitizer import sanitize, hash_for_log
from utils.secrets.secret_ref_utils import delete_user_secret

logger = logging.getLogger(__name__)

whatsapp_bp = Blueprint("whatsapp", __name__)


def _client_from_stored(user_id: str) -> Optional[WhatsAppClient]:
    data = get_token_data(user_id, "whatsapp")
    if not data or not data.get("access_token") or not data.get("phone_number_id"):
        return None
    return WhatsAppClient(
        access_token=data["access_token"],
        phone_number_id=data["phone_number_id"],
        api_version=data.get("api_version") or DEFAULT_API_VERSION,
    )


@whatsapp_bp.route("/connect", methods=["POST"])
@require_permission("connectors", "write")
def connect(user_id):
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    access_token = payload.get("accessToken")
    phone_number_id = (payload.get("phoneNumberId") or "").strip()
    api_version = (payload.get("apiVersion") or DEFAULT_API_VERSION).strip()

    if not access_token or not isinstance(access_token, str):
        return jsonify({"error": "WhatsApp access token is required"}), 400
    if not phone_number_id:
        return jsonify({"error": "WhatsApp phone number ID is required"}), 400

    client = WhatsAppClient(access_token=access_token, phone_number_id=phone_number_id, api_version=api_version)
    logger.info("[WHATSAPP] Connecting user %s phone_id=%s token=%s", sanitize(user_id), sanitize(phone_number_id), hash_for_log(access_token))
    try:
        info = client.validate()
    except WhatsAppAPIError as exc:
        logger.warning("[WHATSAPP] Validation failed for user %s: %s", sanitize(user_id), exc)
        return jsonify({"error": f"Failed to validate WhatsApp: {exc}"}), 502

    token_payload = {
        "access_token": access_token,
        "phone_number_id": phone_number_id,
        "api_version": api_version,
        "display_phone_number": info.get("display_phone_number"),
        "verified_name": info.get("verified_name"),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        store_tokens_in_db(user_id, token_payload, "whatsapp")
    except Exception as exc:
        logger.exception("[WHATSAPP] Failed to store credentials: %s", exc)
        return jsonify({"error": "Failed to store WhatsApp credentials"}), 500

    return jsonify({
        "success": True,
        "displayPhoneNumber": info.get("display_phone_number"),
        "verifiedName": info.get("verified_name"),
        "validated": True,
    })


@whatsapp_bp.route("/status", methods=["GET"])
@require_permission("connectors", "read")
def status(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"connected": False})
    try:
        info = client.validate()
    except WhatsAppAPIError as exc:
        return jsonify({"connected": False, "error": str(exc)})
    return jsonify({
        "connected": True,
        "displayPhoneNumber": info.get("display_phone_number"),
        "verifiedName": info.get("verified_name"),
    })


@whatsapp_bp.route("/disconnect", methods=["DELETE", "POST"])
@require_permission("connectors", "write")
def disconnect(user_id):
    try:
        success, _ = delete_user_secret(user_id, "whatsapp")
    except Exception as exc:
        logger.exception("[WHATSAPP] Failed to disconnect: %s", exc)
        return jsonify({"error": "Failed to disconnect WhatsApp"}), 500
    return jsonify({"success": bool(success)})


@whatsapp_bp.route("/send-test", methods=["POST"])
@require_permission("connectors", "write")
def send_test(user_id):
    """Send a test text message to verify delivery end-to-end."""
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "WhatsApp is not connected"}), 400
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    to = (payload.get("to") or "").strip()
    body = (payload.get("message") or "").strip()
    if not to or not body:
        return jsonify({"error": "'to' and 'message' are required"}), 400
    try:
        result = client.send_text(to, body)
    except WhatsAppAPIError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({"success": True, "result": result})
