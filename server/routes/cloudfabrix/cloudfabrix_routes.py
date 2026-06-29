"""CloudFabrix connector routes — connect, status, disconnect."""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from routes.cloudfabrix.connector_service import validate_credentials
from routes.cloudfabrix.cfx_client import CloudFabrixClient
from utils.auth.rbac_decorators import require_permission
from utils.auth.token_management import get_token_data, store_tokens_in_db
from utils.log_sanitizer import sanitize
from utils.secrets.secret_ref_utils import delete_user_secret

logger = logging.getLogger(__name__)

cloudfabrix_bp = Blueprint("cloudfabrix", __name__)


def _get_stored_credentials(user_id: str) -> dict[str, Any] | None:
    try:
        return get_token_data(user_id, "cloudfabrix")
    except Exception as exc:
        logger.error("[CloudFabrix] Failed to load credentials for %s: %s", sanitize(user_id), exc)
        return None


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off")


@cloudfabrix_bp.route("/connect", methods=["POST"])
@require_permission("connectors", "write")
def connect(user_id: str):
    data = request.get_json(force=True, silent=True) or {}
    api_base = CloudFabrixClient.normalize_api_base(data.get("apiBase") or data.get("api_base"))
    api_token = (data.get("apiToken") or data.get("api_token") or "").strip()
    refresh_token = (data.get("refreshToken") or data.get("refresh_token") or "").strip()
    refresh_url = (data.get("refreshApiUrl") or data.get("refresh_url") or "").strip()
    project_id = (data.get("projectId") or data.get("project_id") or "").strip()
    customer_id = (data.get("customerId") or data.get("customer_id") or "").strip()
    verify_ssl = _parse_bool(data.get("verifySsl", data.get("verify_ssl")), default=False)

    if not api_base:
        return jsonify({"error": "A valid CloudFabrix API base URL is required"}), 400
    if not api_token:
        return jsonify({"error": "apiToken is required"}), 400

    client = CloudFabrixClient(
        api_base=api_base,
        api_token=api_token,
        refresh_token=refresh_token,
        refresh_url=refresh_url,
        project_id=project_id,
        customer_id=customer_id,
        verify_ssl=verify_ssl,
        topology_graph=(data.get("topologyGraph") or data.get("topology_graph") or "").strip() or None,
        topology_db=(data.get("topologyDb") or data.get("topology_db") or "").strip() or None,
        relationship_map=(data.get("relationshipMap") or data.get("relationship_map") or "").strip() or None,
    )

    probe = validate_credentials(client)
    if not probe.get("ok"):
        logger.warning(
            "[CloudFabrix] Connect validation failed for %s: %s",
            sanitize(user_id),
            probe.get("error"),
        )
        return jsonify({"error": probe.get("error") or "Failed to validate CloudFabrix credentials"}), 502

    token_payload = client.to_token_payload()
    try:
        store_tokens_in_db(user_id, token_payload, "cloudfabrix")
        logger.info("[CloudFabrix] Stored credentials for user %s", sanitize(user_id))
    except Exception as exc:
        logger.exception("[CloudFabrix] Failed to store credentials: %s", exc)
        return jsonify({"error": "Failed to store CloudFabrix credentials"}), 500

    return jsonify({
        "success": True,
        "connected": True,
        "apiBase": client.api_base,
        "projectId": client.project_id or None,
        "customerId": client.customer_id or None,
        "organizationCount": probe.get("organizationCount"),
    })


@cloudfabrix_bp.route("/status", methods=["GET"])
@require_permission("connectors", "read")
def status(user_id: str):
    creds = _get_stored_credentials(user_id)
    if not creds:
        return jsonify({"connected": False})

    try:
        client = CloudFabrixClient.from_token_data(creds)
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
        "apiBase": client.api_base,
        "projectId": client.project_id or None,
        "customerId": client.customer_id or None,
        "organizationCount": probe.get("organizationCount"),
    })


@cloudfabrix_bp.route("/disconnect", methods=["POST", "DELETE"])
@require_permission("connectors", "write")
def disconnect(user_id: str):
    try:
        success, deleted_count = delete_user_secret(user_id, "cloudfabrix")
        if not success:
            return jsonify({"success": False, "error": "Failed to delete stored credentials"}), 500
        logger.info("[CloudFabrix] Disconnected provider (deleted %s token entries)", deleted_count)
        return jsonify({
            "success": True,
            "message": "CloudFabrix disconnected successfully",
            "deleted": deleted_count,
        })
    except Exception:
        logger.exception("[CloudFabrix] Failed to disconnect")
        return jsonify({"error": "Failed to disconnect CloudFabrix"}), 500
