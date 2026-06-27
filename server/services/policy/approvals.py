"""HITL approval queue: create/list/decide approval requests.

When the policy engine decides a background tool action requires approval, the
command gate records a pending approval here (instead of silently denying) and a
human resolves it from the Approvals inbox. All access is RLS-scoped.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)

_VALID_DECISIONS = ("approved", "rejected")


def action_hash(tool_name: str, summary: str) -> str:
    """Stable hash identifying a specific action (tool + rendered summary).

    Used so a granted approval is consumable only by the *same* action, not any
    invocation of the same tool. Pure.
    """
    raw = f"{tool_name}\x1f{(summary or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]


def create_approval(
    user_id: str,
    org_id: str,
    *,
    tool_name: str,
    summary: str = "",
    session_id: Optional[str] = None,
    incident_id: Optional[str] = None,
) -> str:
    """Insert a pending approval; returns its id."""
    approval_id = str(uuid.uuid4())
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Approvals:create]")
            cur.execute(
                """INSERT INTO approvals
                       (id, org_id, tool_name, summary, status, session_id, incident_id, requested_by, created_at)
                   VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s)""",
                (approval_id, org_id, tool_name, summary, session_id, incident_id,
                 user_id, datetime.now(timezone.utc)),
            )
            conn.commit()
    return approval_id


def consume_if_approved_safe(user_id: str, tool_name: str, summary: str = "") -> bool:
    """Fail-safe: if a single-use, recently-approved, unconsumed approval exists
    for this *specific action* (org, tool_name, action_hash), mark it consumed
    and return True (the gate then allows this one execution). Otherwise return
    False. Never raises.

    Matching on action_hash (tool + rendered summary) ensures an approval for one
    action can't authorize a different invocation of the same tool. It is
    single-use (``consumed_at``) and time-bounded, so a stale approval can't
    silently allow repeated actions.
    """
    try:
        ah = action_hash(tool_name, summary)
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[Approvals:consume]")
                if not org_id:
                    return False
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                # Atomically claim the oldest matching approval. Match the exact
                # action_hash; tolerate legacy rows with NULL hash for the same tool.
                cur.execute(
                    """UPDATE approvals SET consumed_at = %s
                       WHERE id = (
                           SELECT id FROM approvals
                           WHERE org_id = %s AND tool_name = %s AND status = 'approved'
                             AND consumed_at IS NULL AND created_at >= %s
                             AND (action_hash = %s OR action_hash IS NULL)
                           ORDER BY created_at ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING id""",
                    (datetime.now(timezone.utc), org_id, tool_name, cutoff, ah),
                )
                claimed = cur.fetchone()
                conn.commit()
                return claimed is not None
    except Exception as exc:  # pragma: no cover — defensive, fail closed (no allow)
        logger.debug("consume_if_approved_safe failed (fail-closed): %s", exc)
        return False


def create_approval_safe(
    user_id: str,
    *,
    tool_name: str,
    summary: str = "",
    session_id: Optional[str] = None,
    incident_id: Optional[str] = None,
    resume_payload: Optional[dict] = None,
) -> Optional[str]:
    """Fail-safe variant for the command gate: resolves org from the user and
    never raises (returns None on error). Avoids duplicate pending rows for the
    same (session, tool). ``resume_payload`` captures enough context to re-run
    the blocked run after approval."""
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[Approvals:gate]")
                if not org_id:
                    return None
                # Dedup: one pending approval per (session, tool).
                if session_id:
                    cur.execute(
                        "SELECT id FROM approvals WHERE org_id = %s AND session_id = %s "
                        "AND tool_name = %s AND status = 'pending' LIMIT 1",
                        (org_id, session_id, tool_name),
                    )
                    existing = cur.fetchone()
                    if existing:
                        return str(existing[0])
                approval_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO approvals
                           (id, org_id, tool_name, summary, status, session_id, incident_id, requested_by, resume_payload, action_hash, created_at)
                       VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s)""",
                    (approval_id, org_id, tool_name, summary, session_id, incident_id,
                     user_id, json.dumps(resume_payload) if resume_payload else None,
                     action_hash(tool_name, summary), datetime.now(timezone.utc)),
                )
                conn.commit()
                return approval_id
    except Exception as exc:  # pragma: no cover — defensive, never break the gate
        logger.debug("create_approval_safe failed (fail-open): %s", exc)
        return None


def resume_from_payload(user_id: str, resume_payload: Optional[dict]) -> bool:
    """Best-effort re-dispatch of a blocked background run after approval.

    Re-runs the captured prompt as a fresh background chat; when the run reaches
    the same action again, the now-consumable approval lets it through (the gate
    consumes it). Returns True if a run was enqueued. Never raises.
    """
    if not resume_payload:
        return False
    # Workflow V2 (Temporal): signal the running run to resume the HITL node.
    # Guarded + best-effort — a no-op if Temporal isn't reachable from this process.
    if resume_payload.get("kind") == "wf_v2_signal":
        try:
            from workflows_v2.signal import signal_resume
            return signal_resume(
                resume_payload.get("temporal_workflow_id"),
                resume_payload.get("node_id"),
                {"decision": "approved"},
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("resume_from_payload (wf_v2_signal) failed: %s", exc)
            return False
    # Workflow-continuation payload: resume the workflow past its approval gate.
    if resume_payload.get("kind") == "workflow":
        try:
            from services.workflows.workflow_executor import run_workflow
            result = run_workflow(
                user_id,
                resume_payload["workflow_key"],
                incident_id=resume_payload.get("incident_id"),
                start_index=int(resume_payload.get("next_index", 0)),
            )
            return result.status in ("completed", "paused")
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("resume_from_payload (workflow) failed: %s", exc)
            return False
    if not resume_payload.get("prompt"):
        return False
    try:
        from chat.background.task import create_background_chat_session, run_background_chat
        meta = {"source": "approval_resume", "incident_id": resume_payload.get("incident_id")}
        session_id = create_background_chat_session(
            user_id=user_id,
            title="Resumed after approval",
            trigger_metadata=meta,
        )
        run_background_chat.delay(
            user_id=user_id,
            session_id=session_id,
            initial_message=resume_payload["prompt"],
            trigger_metadata=meta,
            mode=resume_payload.get("mode", "agent"),
            send_notifications=False,
            incident_id=resume_payload.get("incident_id"),
            tool_allowlist=resume_payload.get("tool_allowlist"),
        )
        return True
    except Exception as exc:  # pragma: no cover — defensive, never break the decision
        logger.warning("resume_from_payload failed (non-fatal): %s", exc)
        return False


def list_approvals(user_id: str, org_id: str, status: str = "pending", limit: int = 100) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Approvals:list]")
            if status == "all":
                cur.execute(
                    "SELECT id, tool_name, summary, status, session_id, incident_id, "
                    "requested_by, decided_by, decided_at, reason, created_at "
                    "FROM approvals WHERE org_id = %s ORDER BY created_at DESC LIMIT %s",
                    (org_id, limit),
                )
            else:
                cur.execute(
                    "SELECT id, tool_name, summary, status, session_id, incident_id, "
                    "requested_by, decided_by, decided_at, reason, created_at "
                    "FROM approvals WHERE org_id = %s AND status = %s ORDER BY created_at DESC LIMIT %s",
                    (org_id, status, limit),
                )
            cols = ["id", "tool_name", "summary", "status", "session_id", "incident_id",
                    "requested_by", "decided_by", "decided_at", "reason", "created_at"]
            rows = []
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                d["id"] = str(d["id"])
                if d.get("incident_id"):
                    d["incident_id"] = str(d["incident_id"])
                for ts in ("decided_at", "created_at"):
                    if d.get(ts):
                        d[ts] = d[ts].isoformat()
                rows.append(d)
            return rows


def decide_approval(user_id: str, org_id: str, approval_id: str, decision: str, reason: str = ""):
    """Approve/reject a pending approval.

    Returns ``(updated, resume_payload)``: ``updated`` is True iff a pending row
    was transitioned; ``resume_payload`` is the stored dict when the decision is
    'approved' (else None), so the caller can re-dispatch the blocked run.
    """
    if decision not in _VALID_DECISIONS:
        raise ValueError(f"invalid decision: {decision}")
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Approvals:decide]")
            cur.execute(
                """UPDATE approvals
                   SET status = %s, decided_by = %s, decided_at = %s, reason = %s
                   WHERE id = %s AND org_id = %s AND status = 'pending'
                   RETURNING resume_payload""",
                (decision, user_id, datetime.now(timezone.utc), reason, approval_id, org_id),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                return False, None
            resume_payload = row[0] if decision == "approved" else None
            if isinstance(resume_payload, str):
                try:
                    resume_payload = json.loads(resume_payload)
                except (TypeError, ValueError):
                    resume_payload = None
            return True, resume_payload
