"""FortiGate connector routes: connect / status / disconnect + read-only queries.

Credentials (base URL + API token + options) are validated against the live device, then
stored via the central token helpers (Vault-backed). Write operations that change firewall
config are NOT exposed here directly — they run through the approval-gated open-firewall-port
workflow so every change is reviewed before it is applied.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from connectors.fortigate_connector.client import FortiGateClient, FortiGateAPIError
from routes.fortigate.config import MAX_RESULTS_CAP
from utils.auth.rbac_decorators import require_permission
from utils.auth.token_management import get_token_data, store_tokens_in_db
from utils.log_sanitizer import sanitize, hash_for_log
from utils.net.ssrf import is_safe_public_url
from utils.secrets.secret_ref_utils import delete_user_secret

logger = logging.getLogger(__name__)

fortigate_bp = Blueprint("fortigate", __name__)


def _client_from_stored(user_id: str) -> Optional[FortiGateClient]:
    data = get_token_data(user_id, "fortigate")
    if not data or not data.get("base_url") or not data.get("api_token"):
        return None
    return FortiGateClient(
        base_url=data["base_url"],
        api_token=data["api_token"],
        vdom=data.get("vdom"),
        verify_ssl=bool(data.get("verify_ssl", True)),
        auth_in_query=bool(data.get("auth_in_query", False)),
    )


@fortigate_bp.route("/connect", methods=["POST"])
@require_permission("connectors", "write")
def connect(user_id):
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    base_url = (payload.get("baseUrl") or "").strip().rstrip("/")
    api_token = payload.get("apiToken")
    vdom = (payload.get("vdom") or "").strip() or None
    verify_ssl = bool(payload.get("verifySsl", True))
    auth_in_query = bool(payload.get("authInQuery", False))

    if not base_url:
        return jsonify({"error": "FortiGate base URL is required (e.g. https://10.0.0.1)"}), 400
    if not api_token or not isinstance(api_token, str):
        return jsonify({"error": "FortiGate API token is required"}), 400

    ok, reason = is_safe_public_url(base_url)
    if not ok:
        logger.warning("[FORTIGATE] connect blocked by SSRF guard for user %s: %s", sanitize(user_id), reason)
        return jsonify({
            "error": "This FortiGate address is not permitted. If it is on a private "
                     "management network, add its range to AURORA_SSRF_ALLOWED_CIDRS."
        }), 400

    client = FortiGateClient(base_url=base_url, api_token=api_token, vdom=vdom,
                             verify_ssl=verify_ssl, auth_in_query=auth_in_query)
    logger.info("[FORTIGATE] Connecting user %s host=%s token=%s", sanitize(user_id), sanitize(base_url), hash_for_log(api_token))
    try:
        client.get_system_status()
    except FortiGateAPIError as exc:
        logger.warning("[FORTIGATE] Validation failed for user %s: %s", sanitize(user_id), exc)
        return jsonify({"error": f"Failed to validate FortiGate: {exc}"}), 502

    token_payload = {
        "base_url": base_url,
        "api_token": api_token,
        "vdom": vdom,
        "verify_ssl": verify_ssl,
        "auth_in_query": auth_in_query,
        "fortios_version": client.detected_version,
        "serial": client.serial,
        "hostname": client.hostname,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        store_tokens_in_db(user_id, token_payload, "fortigate")
    except Exception as exc:
        logger.exception("[FORTIGATE] Failed to store credentials: %s", exc)
        return jsonify({"error": "Failed to store FortiGate credentials"}), 500

    return jsonify({
        "success": True,
        "baseUrl": base_url,
        "vdom": vdom,
        "fortiosVersion": client.detected_version,
        "hostname": client.hostname,
        "validated": True,
    })


@fortigate_bp.route("/status", methods=["GET"])
@require_permission("connectors", "read")
def status(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"connected": False})
    try:
        client.get_system_status()
    except FortiGateAPIError as exc:
        return jsonify({"connected": False, "error": str(exc)})
    return jsonify({
        "connected": True,
        "baseUrl": client.base_url,
        "vdom": client.vdom,
        "fortiosVersion": client.detected_version,
        "hostname": client.hostname,
    })


@fortigate_bp.route("/disconnect", methods=["DELETE", "POST"])
@require_permission("connectors", "write")
def disconnect(user_id):
    try:
        success, _ = delete_user_secret(user_id, "fortigate")
    except Exception as exc:
        logger.exception("[FORTIGATE] Failed to disconnect: %s", exc)
        return jsonify({"error": "Failed to disconnect FortiGate"}), 500
    return jsonify({"success": bool(success)})


def _clamp(value: Any, default: int) -> int:
    try:
        return max(1, min(int(value), MAX_RESULTS_CAP))
    except (TypeError, ValueError):
        return default


@fortigate_bp.route("/policies", methods=["GET"])
@require_permission("connectors", "read")
def list_policies(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "FortiGate is not connected"}), 400
    try:
        return jsonify({"policies": client.list_firewall_policies(limit=_clamp(request.args.get("limit"), 100))})
    except FortiGateAPIError as exc:
        return jsonify({"error": str(exc)}), 502


@fortigate_bp.route("/addresses", methods=["GET"])
@require_permission("connectors", "read")
def list_addresses(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "FortiGate is not connected"}), 400
    try:
        return jsonify({"addresses": client.list_addresses(limit=_clamp(request.args.get("limit"), 200))})
    except FortiGateAPIError as exc:
        return jsonify({"error": str(exc)}), 502


@fortigate_bp.route("/services", methods=["GET"])
@require_permission("connectors", "read")
def list_services(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "FortiGate is not connected"}), 400
    try:
        return jsonify({"services": client.list_services(limit=_clamp(request.args.get("limit"), 200))})
    except FortiGateAPIError as exc:
        return jsonify({"error": str(exc)}), 502


@fortigate_bp.route("/interfaces", methods=["GET"])
@require_permission("connectors", "read")
def list_interfaces(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "FortiGate is not connected"}), 400
    try:
        return jsonify({"interfaces": client.list_interfaces(limit=_clamp(request.args.get("limit"), 200))})
    except FortiGateAPIError as exc:
        return jsonify({"error": str(exc)}), 502
