"""Zabbix connector routes: connect / status / disconnect + read-only queries.

Credentials (base URL + API token, or username/password) are validated against the live
Zabbix server, then stored via the central token helpers (Vault-backed). Read-only — Zabbix
is a monitoring source.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from connectors.zabbix_connector.client import ZabbixClient, ZabbixAPIError
from routes.zabbix.config import MAX_RESULTS_CAP
from utils.auth.rbac_decorators import require_permission
from utils.auth.token_management import get_token_data, store_tokens_in_db
from utils.log_sanitizer import sanitize, hash_for_log
from utils.net.ssrf import is_safe_public_url
from utils.secrets.secret_ref_utils import delete_user_secret

logger = logging.getLogger(__name__)

zabbix_bp = Blueprint("zabbix", __name__)


def _client_from_stored(user_id: str) -> Optional[ZabbixClient]:
    data = get_token_data(user_id, "zabbix")
    if not data or not data.get("base_url"):
        return None
    if not data.get("api_token") and not (data.get("username") and data.get("password")):
        return None
    return ZabbixClient(
        base_url=data["base_url"],
        api_token=data.get("api_token"),
        username=data.get("username"),
        password=data.get("password"),
        verify_ssl=bool(data.get("verify_ssl", True)),
    )


@zabbix_bp.route("/connect", methods=["POST"])
@require_permission("connectors", "write")
def connect(user_id):
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    base_url = (payload.get("baseUrl") or "").strip().rstrip("/")
    api_token = (payload.get("apiToken") or "").strip() or None
    username = (payload.get("username") or "").strip() or None
    password = payload.get("password") or None
    verify_ssl = bool(payload.get("verifySsl", True))

    if not base_url:
        return jsonify({"error": "Zabbix base URL is required (e.g. https://zabbix.example.com)"}), 400
    if not api_token and not (username and password):
        return jsonify({"error": "Provide either an API token or a username and password"}), 400

    ok, reason = is_safe_public_url(base_url)
    if not ok:
        logger.warning("[ZABBIX] connect blocked by SSRF guard for user %s: %s", sanitize(user_id), reason)
        return jsonify({
            "error": "This Zabbix address is not permitted. If it is on a private management "
                     "network, add its range to AURORA_SSRF_ALLOWED_CIDRS."
        }), 400

    client = ZabbixClient(base_url=base_url, api_token=api_token, username=username,
                          password=password, verify_ssl=verify_ssl)
    logger.info("[ZABBIX] Connecting user %s host=%s auth=%s", sanitize(user_id), sanitize(base_url),
                "token" if api_token else "userpass")
    try:
        client.validate()
    except ZabbixAPIError as exc:
        logger.warning("[ZABBIX] Validation failed for user %s: %s", sanitize(user_id), exc)
        return jsonify({"error": f"Failed to validate Zabbix: {exc}"}), 502

    token_payload = {
        "base_url": base_url,
        "api_token": api_token,
        "username": username,
        "password": password,
        "verify_ssl": verify_ssl,
        "zabbix_version": client.detected_version,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        store_tokens_in_db(user_id, token_payload, "zabbix")
    except Exception as exc:
        logger.exception("[ZABBIX] Failed to store credentials: %s", exc)
        return jsonify({"error": "Failed to store Zabbix credentials"}), 500

    return jsonify({
        "success": True,
        "baseUrl": base_url,
        "zabbixVersion": client.detected_version,
        "validated": True,
    })


@zabbix_bp.route("/status", methods=["GET"])
@require_permission("connectors", "read")
def status(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"connected": False})
    try:
        client.validate()
    except ZabbixAPIError as exc:
        return jsonify({"connected": False, "error": str(exc)})
    return jsonify({
        "connected": True,
        "baseUrl": client.base_url,
        "zabbixVersion": client.detected_version,
    })


@zabbix_bp.route("/disconnect", methods=["DELETE", "POST"])
@require_permission("connectors", "write")
def disconnect(user_id):
    try:
        success, _ = delete_user_secret(user_id, "zabbix")
    except Exception as exc:
        logger.exception("[ZABBIX] Failed to disconnect: %s", exc)
        return jsonify({"error": "Failed to disconnect Zabbix"}), 500
    return jsonify({"success": bool(success)})


def _clamp(value: Any, default: int) -> int:
    try:
        return max(1, min(int(value), MAX_RESULTS_CAP))
    except (TypeError, ValueError):
        return default


@zabbix_bp.route("/hosts", methods=["GET"])
@require_permission("connectors", "read")
def list_hosts(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "Zabbix is not connected"}), 400
    try:
        return jsonify({"hosts": client.get_hosts(limit=_clamp(request.args.get("limit"), 100))})
    except ZabbixAPIError as exc:
        return jsonify({"error": str(exc)}), 502


@zabbix_bp.route("/problems", methods=["GET"])
@require_permission("connectors", "read")
def list_problems(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "Zabbix is not connected"}), 400
    try:
        return jsonify({"problems": client.get_problems(limit=_clamp(request.args.get("limit"), 100))})
    except ZabbixAPIError as exc:
        return jsonify({"error": str(exc)}), 502


@zabbix_bp.route("/triggers", methods=["GET"])
@require_permission("connectors", "read")
def list_triggers(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "Zabbix is not connected"}), 400
    try:
        return jsonify({"triggers": client.get_triggers(limit=_clamp(request.args.get("limit"), 100))})
    except ZabbixAPIError as exc:
        return jsonify({"error": str(exc)}), 502
