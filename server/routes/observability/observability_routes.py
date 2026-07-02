"""Observability routes: tracing status (for the UI link) + per-user debug-tracing toggle."""

import logging
import os

from flask import Blueprint, jsonify, request

from utils.auth.rbac_decorators import require_auth_only
from utils.observability import tracing
from utils.observability.debug_flag import is_debug_enabled, set_debug

logger = logging.getLogger(__name__)

observability_bp = Blueprint("observability", __name__)


@observability_bp.route("/observability/status", methods=["GET"])
@require_auth_only
def status(user_id):
    """Whether tracing is on + the browser-reachable Langfuse URL (for the 'open traces' link)."""
    return jsonify({
        "enabled": tracing.enabled(),
        "publicUrl": os.getenv("LANGFUSE_PUBLIC_URL") or None,
        "debug": is_debug_enabled(user_id),
    })


@observability_bp.route("/observability/debug", methods=["GET"])
@require_auth_only
def get_debug(user_id):
    return jsonify({"debug": is_debug_enabled(user_id)})


@observability_bp.route("/observability/debug", methods=["POST"])
@require_auth_only
def set_debug_route(user_id):
    payload = request.get_json(force=True, silent=True) or {}
    enabled = bool(payload.get("enabled"))
    ok = set_debug(user_id, enabled)
    return jsonify({"success": ok, "debug": enabled})
