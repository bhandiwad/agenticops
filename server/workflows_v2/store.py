"""Postgres persistence for Workflow V2 runs (Epic #2).

Writes run + per-node IO to the RLS-scoped ``workflow_runs`` / ``workflow_node_runs``
tables (created by ``db_utils``). All writes set RLS context for the run's user so
rows are correctly org-scoped. Used from Temporal activities (outside the workflow
sandbox), so normal imports/IO are fine.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

logger = logging.getLogger("workflows_v2.store")


def _as_uuid_or_none(value) -> Optional[str]:
    """Coerce to a UUID string, or None if it isn't one (the incident_id column is
    UUID; node/run contexts may carry a non-UUID ref)."""
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def create_run(user_id: str, org_id: str, workflow_key: str,
               temporal_run_id: Optional[str] = None,
               incident_id: Optional[str] = None) -> Optional[str]:
    from utils.db.connection_pool import db_pool
    from utils.auth.stateless_auth import set_rls_context
    run_id = str(uuid.uuid4())
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                set_rls_context(cur, conn, user_id, log_prefix="[wf-v2:create_run]")
                cur.execute(
                    "INSERT INTO workflow_runs (id, org_id, user_id, workflow_key, temporal_run_id, status, incident_id) "
                    "VALUES (%s,%s,%s,%s,%s,'running',%s)",
                    (run_id, org_id, user_id, workflow_key, temporal_run_id, _as_uuid_or_none(incident_id)),
                )
                conn.commit()
        return run_id
    except Exception:
        logger.exception("wf-v2: create_run failed")
        return None


def persist_node_run(user_id: str, org_id: str, run_id: Optional[str], node_id: str,
                     node_type: str, status: str, input_: dict, output) -> None:
    if not run_id:
        return
    from utils.db.connection_pool import db_pool
    from utils.auth.stateless_auth import set_rls_context
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                set_rls_context(cur, conn, user_id, log_prefix="[wf-v2:node]")
                cur.execute(
                    "INSERT INTO workflow_node_runs (id, run_id, org_id, node_id, node_type, status, input, output) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (str(uuid.uuid4()), run_id, org_id, node_id, node_type, status,
                     json.dumps(input_), json.dumps(output)),
                )
                conn.commit()
    except Exception:
        logger.exception("wf-v2: persist_node_run failed (non-fatal)")


def finish_run(user_id: str, org_id: str, run_id: Optional[str], status: str) -> None:
    if not run_id:
        return
    from utils.db.connection_pool import db_pool
    from utils.auth.stateless_auth import set_rls_context
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                set_rls_context(cur, conn, user_id, log_prefix="[wf-v2:finish_run]")
                cur.execute(
                    "UPDATE workflow_runs SET status=%s, ended_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (status, run_id),
                )
                conn.commit()
    except Exception:
        logger.exception("wf-v2: finish_run failed (non-fatal)")
