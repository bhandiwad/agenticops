"""Org-authored custom trigger routes (extra event → agent/workflow steps).

These augment the built-in DEFAULT_ROUTES: an org can route additional agents or
workflows off any lifecycle event, optionally gated by a match condition
(e.g. severity=critical). The executor loads them as ``extra_routes``.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)

_VALID_TARGET_TYPES = ("agent", "workflow")


def _load_match(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None
    return raw


def list_custom_routes(user_id: str, org_id: str) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomRoutes:list]")
            cur.execute(
                "SELECT id, event_type, target_type, target_ref, match, enabled "
                "FROM custom_trigger_routes WHERE org_id = %s ORDER BY event_type, created_at",
                (org_id,),
            )
            return [
                {"id": str(r[0]), "event_type": r[1], "target_type": r[2],
                 "target_ref": r[3], "match": _load_match(r[4]), "enabled": r[5]}
                for r in cur.fetchall()
            ]


def create_custom_route(user_id: str, org_id: str, *, event_type: str, target_type: str,
                        target_ref: str, match: Optional[dict] = None) -> str:
    from services.routing.events import EVENT_TYPES
    if event_type not in EVENT_TYPES:
        raise ValueError(f"event_type must be one of {EVENT_TYPES}")
    if target_type not in _VALID_TARGET_TYPES:
        raise ValueError(f"target_type must be one of {_VALID_TARGET_TYPES}")
    if not target_ref:
        raise ValueError("target_ref is required")
    route_id = str(uuid.uuid4())
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomRoutes:create]")
            cur.execute(
                """INSERT INTO custom_trigger_routes
                       (id, org_id, event_type, target_type, target_ref, match, enabled, created_by, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s)""",
                (route_id, org_id, event_type, target_type, target_ref,
                 json.dumps(match) if match else None, user_id, datetime.now(timezone.utc)),
            )
            conn.commit()
    return route_id


def delete_custom_route(user_id: str, org_id: str, route_id: str) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomRoutes:delete]")
            cur.execute(
                "DELETE FROM custom_trigger_routes WHERE id = %s AND org_id = %s",
                (route_id, org_id),
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted > 0


def get_custom_routes_safe(user_id: str) -> Dict[str, list]:
    """Fail-safe: return ``{event_type: [RouteStep, ...]}`` of enabled custom
    routes for the user's org, for use as route_event ``extra_routes``."""
    try:
        from services.routing.trigger_router import RouteStep
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[CustomRoutes:gate]")
                if not org_id:
                    return {}
                cur.execute(
                    "SELECT event_type, target_type, target_ref, match FROM custom_trigger_routes "
                    "WHERE org_id = %s AND enabled = true ORDER BY created_at",
                    (org_id,),
                )
                out: Dict[str, list] = {}
                for r in cur.fetchall():
                    out.setdefault(r[0], []).append(
                        RouteStep(ref=r[2], target_type=r[1], match=_load_match(r[3]))
                    )
                return out
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("get_custom_routes_safe failed: %s", exc)
        return {}
