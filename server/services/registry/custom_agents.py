"""Org-authored custom agents (typed roles defined from the UI).

Built-in agents are markdown roles loaded by RoleRegistry; custom agents are
per-org rows here. They surface in the Agents API, are dispatchable by the
trigger router / actions, and carry the same shape (kind, capability tags,
limits, model, prompt) as a built-in role.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,127}$")
# Lifecycle kinds an org may author. (Investigator agents participate in RCA
# triage; the rest are dispatched by the trigger router / actions / workflows.)
_VALID_KINDS = (
    "investigator", "correlation", "dedup", "summarizer", "remediation",
    "runbook_executor", "notification", "postmortem", "custom",
)


def _load_tags(raw) -> list:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return []
    return raw or []


def _row_to_dict(r) -> dict:
    return {
        "name": r[0], "kind": r[1], "description": r[2] or "",
        "capability_tags": _load_tags(r[3]), "max_turns": r[4], "max_seconds": r[5],
        "model": r[6], "prompt": r[7], "enabled": r[8], "custom": True,
    }


_SELECT = ("name, kind, description, capability_tags, max_turns, max_seconds, "
           "model, prompt, enabled")


def list_custom_agents(user_id: str, org_id: str) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomAgents:list]")
            cur.execute(f"SELECT {_SELECT} FROM custom_agents WHERE org_id = %s ORDER BY name", (org_id,))
            return [_row_to_dict(r) for r in cur.fetchall()]


def create_custom_agent(user_id: str, org_id: str, *, name: str, kind: str, description: str,
                        capability_tags: list, prompt: str, max_turns: int = 16,
                        max_seconds: int = 360, model: Optional[str] = None) -> None:
    from chat.backend.agent.tools.tool_registry import KNOWN_CAPABILITIES
    from chat.backend.agent.orchestrator.role_registry import RoleRegistry

    if not _NAME_RE.match(name or ""):
        raise ValueError("name must be lowercase snake_case (2-128 chars)")
    if RoleRegistry.get_instance().get(name) is not None:
        raise ValueError(f"'{name}' is a built-in agent name")
    if kind not in _VALID_KINDS:
        raise ValueError(f"kind must be one of {_VALID_KINDS}")
    tags = list(capability_tags or [])
    unknown = set(tags) - KNOWN_CAPABILITIES
    if unknown:
        raise ValueError(f"unknown capability tags: {sorted(unknown)}")
    if not (prompt or "").strip():
        raise ValueError("prompt is required")

    now = datetime.now(timezone.utc)
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomAgents:create]")
            cur.execute(
                """INSERT INTO custom_agents
                       (id, org_id, name, kind, description, capability_tags, max_turns, max_seconds, model, prompt, created_by, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (org_id, name)
                   DO UPDATE SET kind = EXCLUDED.kind, description = EXCLUDED.description,
                                 capability_tags = EXCLUDED.capability_tags, max_turns = EXCLUDED.max_turns,
                                 max_seconds = EXCLUDED.max_seconds, model = EXCLUDED.model,
                                 prompt = EXCLUDED.prompt, updated_at = EXCLUDED.updated_at""",
                (str(uuid.uuid4()), org_id, name, kind, description, json.dumps(tags),
                 int(max_turns), int(max_seconds), model or None, prompt, user_id, now, now),
            )
            conn.commit()


def delete_custom_agent(user_id: str, org_id: str, name: str) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[CustomAgents:delete]")
            cur.execute("DELETE FROM custom_agents WHERE org_id = %s AND name = %s", (org_id, name))
            deleted = cur.rowcount
            conn.commit()
            return deleted > 0


def _to_role_meta(d: dict):
    from chat.backend.agent.orchestrator.role_registry import RoleMeta
    return RoleMeta(
        name=d["name"], description=d.get("description", ""),
        tools=list(d.get("capability_tags") or []),
        max_turns=int(d.get("max_turns") or 16), max_seconds=int(d.get("max_seconds") or 360),
        rca_priority=200, model=d.get("model") or None, body=d.get("prompt") or "",
        kind=d.get("kind") or "custom",
    )


def get_custom_agents_map_safe(user_id: str) -> Dict[str, object]:
    """Fail-safe: {name: RoleMeta} for the org's enabled custom agents, for the
    dispatch path to resolve custom-agent references. Never raises."""
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[CustomAgents:map]")
                if not org_id:
                    return {}
                cur.execute(f"SELECT {_SELECT} FROM custom_agents WHERE org_id = %s AND enabled = true", (org_id,))
                return {r[0]: _to_role_meta(_row_to_dict(r)) for r in cur.fetchall()}
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("get_custom_agents_map_safe failed: %s", exc)
        return {}
