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


@observability_bp.route("/observability/incident-trace", methods=["GET"])
@require_auth_only
def incident_trace(user_id):
    """Deterministic Langfuse deep-link for an incident's RCA run: the RCA background chat is
    linked to the incident (chat_sessions.incident_id) and its trace is tagged with that
    session_id, so we link to the Langfuse session view. Returns {url: None} when tracing is off
    or no RCA session exists yet."""
    incident_id = (request.args.get("incident_id") or "").strip()
    if not incident_id:
        return jsonify({"error": "incident_id required"}), 400
    public = os.getenv("LANGFUSE_PUBLIC_URL")
    if not tracing.enabled() or not public:
        return jsonify({"url": None})

    session_id = None
    try:
        from utils.db.connection_pool import db_pool
        from utils.auth.stateless_auth import set_rls_context
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                set_rls_context(cur, conn, user_id, log_prefix="[obs:incident-trace]")
                cur.execute(
                    "SELECT id FROM chat_sessions WHERE incident_id = %s::uuid LIMIT 1",
                    (incident_id,),
                )
                row = cur.fetchone()
                session_id = str(row[0]) if row else None
    except Exception:  # noqa: BLE001
        session_id = None

    if not session_id:
        return jsonify({"url": None})
    project = os.getenv("LANGFUSE_INIT_PROJECT_ID", "aurora")
    return jsonify({"url": f"{public.rstrip('/')}/project/{project}/sessions/{session_id}"})


@observability_bp.route("/observability/debug", methods=["POST"])
@require_auth_only
def set_debug_route(user_id):
    payload = request.get_json(force=True, silent=True) or {}
    enabled = bool(payload.get("enabled"))
    ok = set_debug(user_id, enabled)
    return jsonify({"success": ok, "debug": enabled})
