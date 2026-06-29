"""Microsoft Teams notification connector routes — connect, status, disconnect, test.

Webhook-based (not OAuth): the user pastes a Teams Incoming Webhook URL and we
POST notifications to it. The webhook URL is treated as a secret and is never logged.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from routes.teams.connector_service import post_teams_message
from utils.auth.rbac_decorators import require_permission
from utils.auth.token_management import get_token_data, store_tokens_in_db
from utils.log_sanitizer import sanitize
from utils.secrets.secret_ref_utils import delete_user_secret

logger = logging.getLogger(__name__)

teams_bp = Blueprint("teams", __name__)

# Hosts permitted for Teams Incoming Webhooks / Workflows.
_ALLOWED_HOST_MARKERS = ("webhook.office.com", ".logic.azure.com")


def _is_valid_teams_webhook(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    host = parsed.hostname or ""
    return any(marker in host for marker in _ALLOWED_HOST_MARKERS)


def _get_stored_credentials(user_id: str) -> dict[str, Any] | None:
    try:
        return get_token_data(user_id, "teams")
    except Exception as exc:
        logger.error("[Teams] Failed to load credentials for %s: %s", sanitize(user_id), exc)
        return None


@teams_bp.route("/connect", methods=["POST"])
@require_permission("connectors", "write")
def connect(user_id: str):
    data = request.get_json(force=True, silent=True) or {}
    webhook_url = (data.get("webhook_url") or "").strip()
    name = (data.get("name") or "").strip() or "Teams"

    if not webhook_url:
        return jsonify({"error": "webhook_url is required"}), 400
    if not _is_valid_teams_webhook(webhook_url):
        return jsonify({"error": "A valid Microsoft Teams Incoming Webhook URL is required"}), 400

    try:
        store_tokens_in_db(user_id, {"webhook_url": webhook_url, "name": name}, "teams")
        logger.info("[Teams] Stored webhook for user %s (name=%s)", sanitize(user_id), sanitize(name))
    except Exception as exc:
        logger.exception("[Teams] Failed to store webhook: %s", exc)
        return jsonify({"error": "Failed to store Teams webhook"}), 500

    return jsonify({"connected": True, "name": name})


@teams_bp.route("/status", methods=["GET"])
@require_permission("connectors", "read")
def status(user_id: str):
    creds = _get_stored_credentials(user_id)
    if not creds or not creds.get("webhook_url"):
        return jsonify({"connected": False})
    return jsonify({"connected": True, "name": creds.get("name") or "Teams"})


@teams_bp.route("/disconnect", methods=["POST", "DELETE"])
@require_permission("connectors", "write")
def disconnect(user_id: str):
    try:
        success, deleted_count = delete_user_secret(user_id, "teams")
        if not success:
            return jsonify({"connected": False, "error": "Failed to delete stored webhook"}), 500
        logger.info("[Teams] Disconnected provider (deleted %s token entries)", deleted_count)
        return jsonify({"connected": False, "deleted": deleted_count})
    except Exception:
        logger.exception("[Teams] Failed to disconnect")
        return jsonify({"error": "Failed to disconnect Teams"}), 500


@teams_bp.route("/test", methods=["POST"])
@require_permission("connectors", "write")
def test(user_id: str):
    result = post_teams_message(
        user_id,
        text="This is a test notification from AgenticOps.",
        title="AgenticOps test message",
    )
    return jsonify(result)
