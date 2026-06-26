"""Per-org enable/disable overlay for workflows (mirrors trigger rules)."""

import logging
from datetime import datetime, timezone
from typing import Dict, FrozenSet

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)


def get_workflow_rules(user_id: str, org_id: str) -> Dict[str, bool]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[WorkflowRules:list]")
            cur.execute(
                "SELECT workflow_key, enabled FROM workflow_rules WHERE org_id = %s",
                (org_id,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


def set_workflow_rule(user_id: str, org_id: str, workflow_key: str, enabled: bool) -> None:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[WorkflowRules:set]")
            cur.execute(
                """INSERT INTO workflow_rules (org_id, workflow_key, enabled, updated_by, updated_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (org_id, workflow_key)
                   DO UPDATE SET enabled = EXCLUDED.enabled,
                                 updated_by = EXCLUDED.updated_by,
                                 updated_at = EXCLUDED.updated_at""",
                (org_id, workflow_key, enabled, user_id, datetime.now(timezone.utc)),
            )
            conn.commit()


def get_disabled_workflows_safe(user_id: str) -> FrozenSet[str]:
    """Fail-safe: workflow keys the org has disabled."""
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[WorkflowRules:gate]")
                if not org_id:
                    return frozenset()
                cur.execute(
                    "SELECT workflow_key FROM workflow_rules WHERE org_id = %s AND enabled = false",
                    (org_id,),
                )
                return frozenset(row[0] for row in cur.fetchall())
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("get_disabled_workflows_safe failed: %s", exc)
        return frozenset()
