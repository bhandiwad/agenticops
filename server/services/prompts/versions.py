"""Per-org prompt version management.

Agents/workflows ship code/markdown-defined default prompts; an org may register
versioned overrides and activate one. ``get_active_prompt_safe`` lets the agent
build path prefer an org's active override (fail-open to the default).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)


def list_prompt_versions(user_id: str, org_id: str, prompt_key: str) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Prompts:list]")
            cur.execute(
                """SELECT id, version, content, is_active, created_by, created_at
                   FROM prompt_versions WHERE org_id = %s AND prompt_key = %s
                   ORDER BY version DESC""",
                (org_id, prompt_key),
            )
            rows = []
            for r in cur.fetchall():
                rows.append({
                    "id": str(r[0]), "version": r[1], "content": r[2],
                    "is_active": r[3], "created_by": r[4],
                    "created_at": r[5].isoformat() if r[5] else None,
                })
            return rows


def create_prompt_version(user_id: str, org_id: str, prompt_key: str, content: str,
                          activate: bool = True) -> int:
    """Create the next version for a prompt key; optionally activate it."""
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Prompts:create]")
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) FROM prompt_versions WHERE org_id = %s AND prompt_key = %s",
                (org_id, prompt_key),
            )
            next_version = int(cur.fetchone()[0]) + 1
            if activate:
                cur.execute(
                    "UPDATE prompt_versions SET is_active = false WHERE org_id = %s AND prompt_key = %s",
                    (org_id, prompt_key),
                )
            cur.execute(
                """INSERT INTO prompt_versions (id, org_id, prompt_key, version, content, is_active, created_by, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (str(uuid.uuid4()), org_id, prompt_key, next_version, content, activate,
                 user_id, datetime.now(timezone.utc)),
            )
            conn.commit()
            return next_version


def activate_prompt_version(user_id: str, org_id: str, prompt_key: str, version: int) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Prompts:activate]")
            cur.execute(
                "UPDATE prompt_versions SET is_active = false WHERE org_id = %s AND prompt_key = %s",
                (org_id, prompt_key),
            )
            cur.execute(
                "UPDATE prompt_versions SET is_active = true WHERE org_id = %s AND prompt_key = %s AND version = %s",
                (org_id, prompt_key, version),
            )
            updated = cur.rowcount
            conn.commit()
            return updated > 0


def get_active_prompt_safe(user_id: str, prompt_key: str) -> Optional[str]:
    """Fail-open: the org's active prompt override content for ``prompt_key``,
    or None (caller falls back to the code/markdown default). Never raises."""
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[Prompts:active]")
                if not org_id:
                    return None
                cur.execute(
                    "SELECT content FROM prompt_versions "
                    "WHERE org_id = %s AND prompt_key = %s AND is_active = true LIMIT 1",
                    (org_id, prompt_key),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("get_active_prompt_safe failed: %s", exc)
        return None
