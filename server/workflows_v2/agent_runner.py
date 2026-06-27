"""Synchronous agent execution for Workflow V2 agent nodes (Epic #3).

Reuses the existing background-chat agent path **unchanged** — it builds the same
dispatch spec, creates a background chat session, runs ``_execute_background_chat``
(the exact coroutine the Celery task runs) to completion, and returns the agent's
final assistant message as the node output so downstream nodes can consume it.

This is invoked from the ``run_agent`` Temporal activity inside a worker thread
(via ``run_in_executor``), so ``asyncio.run`` here is safe (no running loop in the
thread). The Celery ``run_background_chat`` path is not modified.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger("workflows_v2.agent_runner")


def _last_assistant_message(user_id: str, session_id: str) -> str:
    from utils.db.connection_pool import db_pool
    from utils.auth.stateless_auth import set_rls_context
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                set_rls_context(cur, conn, user_id, log_prefix="[wf-v2:agent-read]")
                cur.execute("SELECT messages FROM chat_sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
        if not row or not row[0]:
            return ""
        messages = row[0]
        if isinstance(messages, str):
            messages = json.loads(messages)
        for msg in reversed(messages):
            if msg.get("sender") in ("bot", "assistant"):
                return msg.get("text") or msg.get("content") or ""
    except Exception:
        logger.exception("wf-v2: failed to read last assistant message")
    return ""


def run_agent_node(user_id: str, ref: str, incident_id: Optional[str],
                   context: dict, custom_roles: Optional[dict] = None) -> dict:
    """Run a single agent synchronously and return its output. Never raises —
    returns a status dict so the interpreter can continue."""
    try:
        from services.routing.events import RCA_COMPLETED, LifecycleEvent
        from services.routing.executor import build_dispatch_plan
        from chat.background.task import create_background_chat_session, _execute_background_chat

        org_id = (context or {}).get("org_id", "")
        if custom_roles is None:
            try:
                from services.registry.custom_agents import get_custom_agents_map_safe
                custom_roles = get_custom_agents_map_safe(user_id)
            except Exception:
                custom_roles = {}

        event = LifecycleEvent(event_type=RCA_COMPLETED, org_id=org_id, incident_id=incident_id)
        specs = build_dispatch_plan([ref], event, custom_roles=custom_roles or {})
        if not specs:
            return {"agent": ref, "status": "no_spec", "summary": ""}
        spec = specs[0]

        meta = {"source": "workflow_v2", "agent": spec.agent_name}
        session_id = create_background_chat_session(
            user_id=user_id, title=f"wf-v2: {spec.agent_name}", trigger_metadata=meta,
        )

        # Run the agent to completion (same coroutine the Celery task runs).
        asyncio.run(_execute_background_chat(
            user_id=user_id,
            session_id=session_id,
            initial_message=spec.prompt,
            trigger_metadata=meta,
            mode=spec.mode,
            send_notifications=False,
            incident_id=incident_id,
            tool_allowlist=spec.tool_allowlist,
            is_postmortem=(spec.kind == "postmortem"),
        ))

        summary = _last_assistant_message(user_id, session_id)
        return {"agent": spec.agent_name, "session_id": session_id,
                "status": "completed", "summary": summary}
    except Exception as e:  # noqa: BLE001 - node failures must not crash the run
        logger.exception("wf-v2: run_agent_node failed for %s", ref)
        return {"agent": ref, "status": "error", "error": str(e)[:300], "summary": ""}


def run_action_node(user_id: str, action_id: str, incident_id: Optional[str], context: dict) -> dict:
    """Execute an Aurora Action synchronously and return its output. Mirrors
    dispatch_action's routing (agent-target / workflow-target / NL) but runs the
    work to completion (reusing the background-chat path) so the node has output."""
    try:
        from utils.db.connection_pool import db_pool
        from utils.auth.stateless_auth import set_rls_context

        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                set_rls_context(cur, conn, user_id, log_prefix="[wf-v2:action]")
                cur.execute(
                    "SELECT org_id, name, instructions, mode, COALESCE(target_type,''), "
                    "COALESCE(target_ref,'') FROM actions WHERE id = %s",
                    (action_id,),
                )
                row = cur.fetchone()
        if not row:
            return {"action": action_id, "status": "error", "error": "action not found"}
        org_id, name, instructions, mode, target_type, target_ref = row

        # Workflow-target action: start the target workflow (fire-and-forget).
        if target_type == "workflow" and target_ref:
            from services.workflows.defs import get_def
            from workflows_v2.client import start_run
            d = get_def(user_id, org_id, target_ref)
            if d:
                res = start_run(d["graph"], {"user_id": user_id, "org_id": org_id, "incident_id": incident_id})
                return {"action": name, "status": "dispatched_workflow", "workflow": target_ref, "result": res}

        from services.routing.events import RCA_COMPLETED, LifecycleEvent
        from services.routing.executor import build_dispatch_plan
        from chat.background.task import create_background_chat_session, _execute_background_chat

        prompt = instructions or name
        run_mode = mode or "ask"
        tool_allowlist = None
        is_pm = False
        # Agent-target action: layer instructions on the agent's role prompt.
        if target_type == "agent" and target_ref:
            event = LifecycleEvent(event_type=RCA_COMPLETED, org_id=org_id, incident_id=incident_id)
            try:
                from services.registry.custom_agents import get_custom_agents_map_safe
                custom_roles = get_custom_agents_map_safe(user_id)
            except Exception:
                custom_roles = {}
            specs = build_dispatch_plan([target_ref], event, custom_roles=custom_roles or {})
            if specs:
                spec = specs[0]
                prompt = spec.prompt + (f"\n\n---\nAdditional instructions:\n{instructions}" if instructions else "")
                run_mode = spec.mode
                tool_allowlist = spec.tool_allowlist
                is_pm = (spec.kind == "postmortem")

        meta = {"source": "workflow_v2_action", "action": name}
        session_id = create_background_chat_session(user_id=user_id, title=f"action: {name}", trigger_metadata=meta)
        asyncio.run(_execute_background_chat(
            user_id=user_id, session_id=session_id, initial_message=prompt,
            trigger_metadata=meta, mode=run_mode, send_notifications=False,
            incident_id=incident_id, tool_allowlist=tool_allowlist, is_postmortem=is_pm,
        ))
        return {"action": name, "session_id": session_id, "status": "completed",
                "summary": _last_assistant_message(user_id, session_id)}
    except Exception as e:  # noqa: BLE001
        logger.exception("wf-v2: run_action_node failed for %s", action_id)
        return {"action": action_id, "status": "error", "error": str(e)[:300]}
