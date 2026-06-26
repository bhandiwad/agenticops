"""Org-authored custom workflows (full step definitions stored in DB)."""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _load_steps(raw) -> list:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return []
    return raw or []


def list_custom_workflows(user_id: str, org_id: str) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomWF:list]")
            cur.execute(
                "SELECT key, name, kind, description, steps, enabled "
                "FROM custom_workflows WHERE org_id = %s ORDER BY name",
                (org_id,),
            )
            return [
                {"key": r[0], "name": r[1], "kind": r[2], "description": r[3] or "",
                 "steps": _load_steps(r[4]), "enabled": r[5], "custom": True}
                for r in cur.fetchall()
            ]


def create_custom_workflow(user_id: str, org_id: str, *, key: str, name: str,
                           kind: str, description: str, steps: list) -> None:
    if not _KEY_RE.match(key or ""):
        raise ValueError("key must be lowercase snake_case (2-64 chars)")
    # Validate the definition (step types + agent existence) before storing.
    from services.workflows.workflow_registry import validate_workflow, workflow_from_dict
    wf = workflow_from_dict({"key": key, "name": name, "kind": kind,
                             "description": description, "steps": steps})
    errors = validate_workflow(wf)
    if errors:
        raise ValueError("; ".join(errors))

    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomWF:create]")
            from services.workflows.workflow_registry import DEFAULT_WORKFLOWS
            if key in DEFAULT_WORKFLOWS:
                raise ValueError(f"'{key}' is a built-in workflow key")
            now = datetime.now(timezone.utc)
            cur.execute(
                """INSERT INTO custom_workflows (id, org_id, key, name, kind, description, steps, enabled, created_by, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s)
                   ON CONFLICT (org_id, key)
                   DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,
                                 description = EXCLUDED.description, steps = EXCLUDED.steps,
                                 updated_at = EXCLUDED.updated_at""",
                (str(uuid.uuid4()), org_id, key, name, kind, description,
                 json.dumps(steps), user_id, now, now),
            )
            conn.commit()


def set_custom_workflow_enabled(user_id: str, org_id: str, key: str, enabled: bool) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomWF:toggle]")
            cur.execute(
                "UPDATE custom_workflows SET enabled = %s, updated_at = %s WHERE org_id = %s AND key = %s",
                (enabled, datetime.now(timezone.utc), org_id, key),
            )
            updated = cur.rowcount
            conn.commit()
            return updated > 0


def delete_custom_workflow(user_id: str, org_id: str, key: str) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomWF:delete]")
            cur.execute(
                "DELETE FROM custom_workflows WHERE org_id = %s AND key = %s",
                (org_id, key),
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted > 0


def get_custom_workflow_safe(user_id: str, key: str):
    """Fail-safe: return a Workflow for an enabled custom workflow, or None."""
    try:
        from services.workflows.workflow_registry import workflow_from_dict
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[CustomWF:get]")
                if not org_id:
                    return None
                cur.execute(
                    "SELECT key, name, kind, description, steps FROM custom_workflows "
                    "WHERE org_id = %s AND key = %s AND enabled = true",
                    (org_id, key),
                )
                r = cur.fetchone()
                if not r:
                    return None
                return workflow_from_dict({
                    "key": r[0], "name": r[1], "kind": r[2],
                    "description": r[3], "steps": _load_steps(r[4]),
                })
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("get_custom_workflow_safe failed: %s", exc)
        return None
