"""Commvault connector routes: connect / status / disconnect + read-only queries.

Credentials (Web Service base URL + username/password) are validated against the live
CommServe, then stored via the central token helpers (Vault-backed). Backup *triggering*
is not exposed here directly — it runs through the approval-gated VM-backup workflow so every
backup job is reviewed, executed, validated (job polled to completion), and recorded on the
ServiceNow ticket.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from connectors.commvault_connector.client import CommvaultClient, CommvaultAPIError
from routes.commvault.config import MAX_RESULTS_CAP
from utils.auth.rbac_decorators import require_permission
from utils.auth.token_management import get_token_data, store_tokens_in_db
from utils.log_sanitizer import sanitize, hash_for_log
from utils.net.ssrf import is_safe_public_url
from utils.secrets.secret_ref_utils import delete_user_secret

logger = logging.getLogger(__name__)

commvault_bp = Blueprint("commvault", __name__)


def _client_from_stored(user_id: str) -> Optional[CommvaultClient]:
    data = get_token_data(user_id, "commvault")
    if not data or not data.get("base_url") or not data.get("username") or not data.get("password"):
        return None
    return CommvaultClient(
        base_url=data["base_url"],
        username=data["username"],
        password=data["password"],
        verify_ssl=bool(data.get("verify_ssl", True)),
    )


@commvault_bp.route("/connect", methods=["POST"])
@require_permission("connectors", "write")
def connect(user_id):
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    base_url = (payload.get("baseUrl") or "").strip().rstrip("/")
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    verify_ssl = bool(payload.get("verifySsl", True))

    if not base_url:
        return jsonify({"error": "Commvault Web Service URL is required (e.g. https://commserve/webconsole/api)"}), 400
    if not username or not password:
        return jsonify({"error": "Commvault username and password are required"}), 400

    ok, reason = is_safe_public_url(base_url)
    if not ok:
        logger.warning("[COMMVAULT] connect blocked by SSRF guard for user %s: %s", sanitize(user_id), reason)
        return jsonify({
            "error": "This Commvault address is not permitted. If it is on a private management "
                     "network, add its range to AURORA_SSRF_ALLOWED_CIDRS."
        }), 400

    client = CommvaultClient(base_url=base_url, username=username, password=password, verify_ssl=verify_ssl)
    logger.info("[COMMVAULT] Connecting user %s host=%s user=%s", sanitize(user_id), sanitize(base_url), hash_for_log(username))
    try:
        client.validate()
    except CommvaultAPIError as exc:
        logger.warning("[COMMVAULT] Validation failed for user %s: %s", sanitize(user_id), exc)
        return jsonify({"error": f"Failed to validate Commvault: {exc}"}), 502

    token_payload = {
        "base_url": base_url,
        "username": username,
        "password": password,
        "verify_ssl": verify_ssl,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        store_tokens_in_db(user_id, token_payload, "commvault")
    except Exception as exc:
        logger.exception("[COMMVAULT] Failed to store credentials: %s", exc)
        return jsonify({"error": "Failed to store Commvault credentials"}), 500

    return jsonify({"success": True, "baseUrl": base_url, "validated": True})


@commvault_bp.route("/status", methods=["GET"])
@require_permission("connectors", "read")
def status(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"connected": False})
    try:
        client.validate()
    except CommvaultAPIError as exc:
        return jsonify({"connected": False, "error": str(exc)})
    return jsonify({"connected": True, "baseUrl": client.base_url})


@commvault_bp.route("/disconnect", methods=["DELETE", "POST"])
@require_permission("connectors", "write")
def disconnect(user_id):
    try:
        success, _ = delete_user_secret(user_id, "commvault")
    except Exception as exc:
        logger.exception("[COMMVAULT] Failed to disconnect: %s", exc)
        return jsonify({"error": "Failed to disconnect Commvault"}), 500
    return jsonify({"success": bool(success)})


@commvault_bp.route("/clients", methods=["GET"])
@require_permission("connectors", "read")
def list_clients(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "Commvault is not connected"}), 400
    try:
        return jsonify({"clients": client.get_clients()[:MAX_RESULTS_CAP]})
    except CommvaultAPIError as exc:
        return jsonify({"error": str(exc)}), 502


@commvault_bp.route("/vms", methods=["GET"])
@require_permission("connectors", "read")
def list_vms(user_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "Commvault is not connected"}), 400
    try:
        return jsonify({"vms": client.get_vms()[:MAX_RESULTS_CAP]})
    except CommvaultAPIError as exc:
        return jsonify({"error": str(exc)}), 502


@commvault_bp.route("/jobs/<job_id>", methods=["GET"])
@require_permission("connectors", "read")
def get_job(user_id, job_id):
    client = _client_from_stored(user_id)
    if client is None:
        return jsonify({"error": "Commvault is not connected"}), 400
    try:
        return jsonify({"job": client.get_job(job_id)})
    except CommvaultAPIError as exc:
        return jsonify({"error": str(exc)}), 502
