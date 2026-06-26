"""Evidence store: a unified record of artifacts an agent run relied on or
produced (tool outputs, citations, findings, notifications), queryable per
incident for audit and review.

``record_evidence_safe`` is the fail-safe writer agent code can call from any
run context; ``list_evidence`` powers the read API/UI.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)

_COLS = ["id", "incident_id", "session_id", "source", "kind", "title", "content", "ref", "created_at"]


def record_evidence_safe(
    user_id: str,
    *,
    kind: str,
    title: str = "",
    content: str = "",
    source: str = "",
    ref: str = "",
    incident_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Fail-safe evidence writer. Resolves org from the user; never raises."""
    try:
        ev_id = str(uuid.uuid4())
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[Evidence:record]")
                if not org_id:
                    return None
                cur.execute(
                    """INSERT INTO run_evidence
                           (id, org_id, incident_id, session_id, source, kind, title, content, ref, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (ev_id, org_id, incident_id, session_id, source, kind,
                     title[:1000] if title else "", content, ref, datetime.now(timezone.utc)),
                )
                conn.commit()
        return ev_id
    except Exception as exc:  # pragma: no cover — defensive, never break a run
        logger.debug("record_evidence_safe failed (non-fatal): %s", exc)
        return None


def list_evidence(user_id: str, org_id: str, incident_id: str, limit: int = 200) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Evidence:list]")
            cur.execute(
                f"SELECT {', '.join(_COLS)} FROM run_evidence "
                "WHERE org_id = %s AND incident_id = %s ORDER BY created_at ASC LIMIT %s",
                (org_id, incident_id, limit),
            )
            rows = []
            for r in cur.fetchall():
                d = dict(zip(_COLS, r))
                d["id"] = str(d["id"])
                if d.get("incident_id"):
                    d["incident_id"] = str(d["incident_id"])
                if d.get("created_at"):
                    d["created_at"] = d["created_at"].isoformat()
                rows.append(d)
            return rows
