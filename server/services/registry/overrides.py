"""DB access for per-org registry overlays.

Two overlay tables sit on top of the code/markdown-defined registries:
  * org_tool_availability — per-org enable/disable of whole catalog tools
    (default enabled). Enforced at tool-build time (fail-open).
  * agent_overrides — per-org enable/disable + max_turns/max_seconds/model
    override for typed agents (default enabled, markdown values otherwise).

All reads/writes go through RLS (set_rls_context). The ``*_safe`` readers are
used on hot/background paths and never raise — they fail open (no overlay).
"""

import logging
from datetime import datetime, timezone
from typing import Dict, FrozenSet, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Tool availability
# --------------------------------------------------------------------------- #
def get_tool_availability(user_id: str, org_id: str) -> Dict[str, bool]:
    """Return {tool_name: enabled} rows for the org (only explicit rows)."""
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[ToolAvail:list]")
            cur.execute(
                "SELECT tool_name, enabled FROM org_tool_availability WHERE org_id = %s",
                (org_id,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


def set_tool_availability(user_id: str, org_id: str, tool_name: str, enabled: bool) -> None:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[ToolAvail:set]")
            cur.execute(
                """INSERT INTO org_tool_availability (org_id, tool_name, enabled, updated_by, updated_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (org_id, tool_name)
                   DO UPDATE SET enabled = EXCLUDED.enabled,
                                 updated_by = EXCLUDED.updated_by,
                                 updated_at = EXCLUDED.updated_at""",
                (org_id, tool_name, enabled, user_id, datetime.now(timezone.utc)),
            )
            conn.commit()


def get_disabled_tools_safe(user_id: str) -> FrozenSet[str]:
    """Fail-open: return tool names explicitly disabled for the user's org.

    Used by get_cloud_tools at build time. Never raises — on any error returns
    an empty set so tool loading is unaffected.
    """
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[ToolAvail:gate]")
                if not org_id:
                    return frozenset()
                cur.execute(
                    "SELECT tool_name FROM org_tool_availability "
                    "WHERE org_id = %s AND enabled = false",
                    (org_id,),
                )
                return frozenset(row[0] for row in cur.fetchall())
    except Exception as exc:  # pragma: no cover — defensive, fail open
        logger.debug("get_disabled_tools_safe failed (fail-open): %s", exc)
        return frozenset()


# --------------------------------------------------------------------------- #
# Agent overrides
# --------------------------------------------------------------------------- #
def get_agent_overrides(user_id: str, org_id: str) -> Dict[str, dict]:
    """Return {agent_name: {enabled, max_turns, max_seconds, model}} for the org."""
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[AgentOverride:list]")
            cur.execute(
                "SELECT agent_name, enabled, max_turns, max_seconds, model "
                "FROM agent_overrides WHERE org_id = %s",
                (org_id,),
            )
            return {
                row[0]: {
                    "enabled": row[1],
                    "max_turns": row[2],
                    "max_seconds": row[3],
                    "model": row[4],
                }
                for row in cur.fetchall()
            }


def set_agent_override(
    user_id: str,
    org_id: str,
    agent_name: str,
    enabled: bool,
    max_turns: Optional[int] = None,
    max_seconds: Optional[int] = None,
    model: Optional[str] = None,
) -> None:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[AgentOverride:set]")
            cur.execute(
                """INSERT INTO agent_overrides
                       (org_id, agent_name, enabled, max_turns, max_seconds, model, updated_by, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (org_id, agent_name)
                   DO UPDATE SET enabled = EXCLUDED.enabled,
                                 max_turns = EXCLUDED.max_turns,
                                 max_seconds = EXCLUDED.max_seconds,
                                 model = EXCLUDED.model,
                                 updated_by = EXCLUDED.updated_by,
                                 updated_at = EXCLUDED.updated_at""",
                (org_id, agent_name, enabled, max_turns, max_seconds, model,
                 user_id, datetime.now(timezone.utc)),
            )
            conn.commit()


def get_disabled_agents_safe(user_id: str) -> FrozenSet[str]:
    """Fail-open: agent names explicitly disabled for the user's org."""
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[AgentOverride:gate]")
                if not org_id:
                    return frozenset()
                cur.execute(
                    "SELECT agent_name FROM agent_overrides "
                    "WHERE org_id = %s AND enabled = false",
                    (org_id,),
                )
                return frozenset(row[0] for row in cur.fetchall())
    except Exception as exc:  # pragma: no cover — defensive, fail open
        logger.debug("get_disabled_agents_safe failed (fail-open): %s", exc)
        return frozenset()
