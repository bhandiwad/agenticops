"""Windows (WinRM) connector routes: connect / status / disconnect.

Stores default Windows credentials (domain/local user + password + transport) used by the
WinRM execution transport for Windows VM operations (patching, troubleshooting, AD, remediation).
The connect flow validates the credentials by running a trivial PowerShell command on a
provided test host. Command execution itself happens through the background/workflow-gated
winrm_exec agent tool.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from connectors.winrm_connector.client import WinRMClient, WinRMError
from routes.winrm.config import DEFAULT_TRANSPORT
from utils.auth.rbac_decorators import require_permission
from utils.auth.token_management import get_token_data, store_tokens_in_db
from utils.log_sanitizer import sanitize, hash_for_log
from utils.net.ssrf import is_safe_public_url
from utils.secrets.secret_ref_utils import delete_user_secret

logger = logging.getLogger(__name__)

winrm_bp = Blueprint("winrm", __name__)


@winrm_bp.route("/connect", methods=["POST"])
@require_permission("connectors", "write")
def connect(user_id):
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    transport = (payload.get("transport") or DEFAULT_TRANSPORT).strip().lower()
    use_ssl = bool(payload.get("useSsl", True))
    verify_ssl = bool(payload.get("verifySsl", True))
    test_host = (payload.get("testHost") or "").strip()
    port = payload.get("port")

    if not username or not password:
        return jsonify({"error": "Windows username and password are required"}), 400
    if not test_host:
        return jsonify({"error": "A test host is required to validate the credentials"}), 400

    scheme = "https" if use_ssl else "http"
    ok, reason = is_safe_public_url(f"{scheme}://{test_host}")
    if not ok:
        logger.warning("[WINRM] connect blocked by SSRF guard for user %s: %s", sanitize(user_id), reason)
        return jsonify({
            "error": "This host is not permitted. If it is on a private management network, "
                     "add its range to AURORA_SSRF_ALLOWED_CIDRS."
        }), 400

    client = WinRMClient(host=test_host, username=username, password=password,
                         transport=transport, use_ssl=use_ssl, verify_ssl=verify_ssl,
                         port=int(port) if port else None)
    logger.info("[WINRM] Validating creds for user %s host=%s user=%s", sanitize(user_id), sanitize(test_host), hash_for_log(username))
    try:
        info = client.validate()
    except WinRMError as exc:
        logger.warning("[WINRM] Validation failed for user %s: %s", sanitize(user_id), exc)
        return jsonify({"error": f"Failed to validate WinRM: {exc}"}), 502

    token_payload = {
        "username": username,
        "password": password,
        "transport": transport,
        "use_ssl": use_ssl,
        "verify_ssl": verify_ssl,
        "port": int(port) if port else None,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        store_tokens_in_db(user_id, token_payload, "winrm")
    except Exception as exc:
        logger.exception("[WINRM] Failed to store credentials: %s", exc)
        return jsonify({"error": "Failed to store Windows credentials"}), 500

    return jsonify({"success": True, "computerName": info.get("computer_name"), "validated": True})


@winrm_bp.route("/status", methods=["GET"])
@require_permission("connectors", "read")
def status(user_id):
    data = get_token_data(user_id, "winrm")
    if not data or not data.get("username"):
        return jsonify({"connected": False})
    return jsonify({
        "connected": True,
        "username": data.get("username"),
        "transport": data.get("transport"),
        "useSsl": data.get("use_ssl"),
    })


@winrm_bp.route("/disconnect", methods=["DELETE", "POST"])
@require_permission("connectors", "write")
def disconnect(user_id):
    try:
        success, _ = delete_user_secret(user_id, "winrm")
    except Exception as exc:
        logger.exception("[WINRM] Failed to disconnect: %s", exc)
        return jsonify({"error": "Failed to disconnect Windows/WinRM"}), 500
    return jsonify({"success": bool(success)})
