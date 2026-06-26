"""HITL approvals API.

Blueprint: approvals_bp  (prefix /api/approvals)
  GET  /api/approvals?status=pending|all  — list approval requests
  POST /api/approvals/<id>/decide {decision: approved|rejected, reason?} — resolve
"""

import logging

from flask import Blueprint, jsonify, request

from utils.auth.rbac_decorators import require_permission
from utils.auth.stateless_auth import get_org_id_from_request
from routes.audit_routes import record_audit_event

logger = logging.getLogger(__name__)

approvals_bp = Blueprint("approvals", __name__, url_prefix="/api/approvals")

_ERR_NO_ORG = "No org context"


@approvals_bp.route("", methods=["GET"])
@require_permission("connectors", "read")
def list_pending(user_id):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    status = (request.args.get("status") or "pending").lower()
    if status not in ("pending", "all", "approved", "rejected"):
        status = "pending"
    try:
        from services.policy.approvals import list_approvals
        rows = list_approvals(user_id, org_id, status=status)
        return jsonify({"approvals": rows, "count": len(rows), "status": status})
    except Exception:
        logger.exception("approvals: failed to list")
        return jsonify({"error": "Failed to load approvals"}), 500


@approvals_bp.route("/<approval_id>/decide", methods=["POST"])
@require_permission("connectors", "write")
def decide(user_id, approval_id):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    decision = (body.get("decision") or "").lower()
    if decision not in ("approved", "rejected"):
        return jsonify({"error": "`decision` must be 'approved' or 'rejected'"}), 400
    reason = body.get("reason") or ""

    try:
        from services.policy.approvals import decide_approval
        updated, resume_payload = decide_approval(user_id, org_id, approval_id, decision, reason)
    except Exception:
        logger.exception("approvals: failed to decide")
        return jsonify({"error": "Failed to record decision"}), 500

    if not updated:
        return jsonify({"error": "Approval not found or already decided"}), 404

    try:
        record_audit_event(
            org_id, user_id, f"approval_{decision}", "approval", approval_id,
            {"reason": reason}, request,
        )
    except Exception:
        logger.debug("approvals: audit record failed (non-fatal)")

    # On approval, best-effort re-dispatch the blocked run so the approved
    # action actually executes (the gate consumes the approval on the re-run).
    resumed = False
    if decision == "approved":
        try:
            from services.policy.approvals import resume_from_payload
            resumed = resume_from_payload(user_id, resume_payload)
        except Exception:
            logger.debug("approvals: resume re-dispatch failed (non-fatal)")
    return jsonify({"id": approval_id, "status": decision, "resumed": resumed})
