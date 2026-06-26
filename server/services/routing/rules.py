"""Per-org trigger-rule overlay (enable/disable lifecycle routes).

A route (event type) is active by default; an org may disable it. Stored in
``trigger_rules`` and read through RLS. The ``*_safe`` reader is for the
executor/lifecycle hooks and never raises (fails open = route active).
"""

import logging
from datetime import datetime, timezone
from typing import Dict, FrozenSet

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)


def get_trigger_rules(user_id: str, org_id: str) -> Dict[str, bool]:
    """Return {event_type: enabled} explicit rows for the org."""
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[TriggerRules:list]")
            cur.execute(
                "SELECT event_type, enabled FROM trigger_rules WHERE org_id = %s",
                (org_id,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


def set_trigger_rule(user_id: str, org_id: str, event_type: str, enabled: bool) -> None:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[TriggerRules:set]")
            cur.execute(
                """INSERT INTO trigger_rules (org_id, event_type, enabled, updated_by, updated_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (org_id, event_type)
                   DO UPDATE SET enabled = EXCLUDED.enabled,
                                 updated_by = EXCLUDED.updated_by,
                                 updated_at = EXCLUDED.updated_at""",
                (org_id, event_type, enabled, user_id, datetime.now(timezone.utc)),
            )
            conn.commit()


def get_disabled_event_types_safe(user_id: str) -> FrozenSet[str]:
    """Fail-open: event types the org has disabled. Used by lifecycle hooks."""
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[TriggerRules:gate]")
                if not org_id:
                    return frozenset()
                cur.execute(
                    "SELECT event_type FROM trigger_rules "
                    "WHERE org_id = %s AND enabled = false",
                    (org_id,),
                )
                return frozenset(row[0] for row in cur.fetchall())
    except Exception as exc:  # pragma: no cover — defensive, fail open
        logger.debug("get_disabled_event_types_safe failed (fail-open): %s", exc)
        return frozenset()
