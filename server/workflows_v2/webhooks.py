"""Webhook triggers for Workflow V2.

A high-entropy token maps to (org, def, creating user). The public hook endpoint
resolves the token (the secret) without any user/org context, then starts a run.
The lookup table is intentionally NOT RLS-protected so token resolution works
before an org is known — exactly like connector webhook secrets.
"""

from __future__ import annotations

import logging
import secrets
from typing import List, Optional

from utils.db.connection_pool import db_pool

logger = logging.getLogger("workflows_v2.webhooks")


def create_webhook(user_id: str, org_id: str, key: str) -> str:
    token = secrets.token_urlsafe(24)
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO wf2_webhook_triggers (token, org_id, key, user_id) VALUES (%s,%s,%s,%s)",
                (token, org_id, key, user_id),
            )
            conn.commit()
    return token


def resolve_webhook(token: str) -> Optional[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT org_id, key, user_id FROM wf2_webhook_triggers WHERE token = %s",
                (token,),
            )
            r = cur.fetchone()
    return {"org_id": r[0], "key": r[1], "user_id": r[2]} if r else None


def list_webhooks(org_id: str, key: str) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT token, created_at FROM wf2_webhook_triggers WHERE org_id = %s AND key = %s "
                "ORDER BY created_at DESC",
                (org_id, key),
            )
            rows = cur.fetchall()
    return [{"token": r[0], "created_at": r[1].isoformat() if r[1] else None} for r in rows]


def delete_webhook(org_id: str, token: str) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM wf2_webhook_triggers WHERE org_id = %s AND token = %s",
                (org_id, token),
            )
            deleted = cur.rowcount > 0
            conn.commit()
    return deleted
