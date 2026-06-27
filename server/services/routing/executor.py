"""Execute trigger-routed lifecycle agents.

Given a :class:`LifecycleEvent`, the executor:
  1. resolves the org's disabled event types + disabled agents,
  2. routes the event to ordered lifecycle agents (trigger_router.route_event),
  3. builds a dispatch plan from each agent's role (prompt, limits, model,
     applying per-org overrides),
  4. dispatches each as a background chat (reusing run_background_chat, the same
     path Actions use).

Dispatch is gated by AURORA_TRIGGER_ROUTER_ENABLED (default OFF) and fully
fail-safe: any error is swallowed so emitting an event can never break the
incident lifecycle hook that called it. ``build_dispatch_plan`` is pure and
unit-tested; the dispatch I/O (DB + Celery) is exercised in staging by flipping
the flag.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from services.routing.events import LifecycleEvent
from services.routing.trigger_router import route_event

logger = logging.getLogger(__name__)

# Lifecycle agent kinds that only read/analyze run in read-only ("ask") mode;
# the rest may write (notify, save postmortem, plan/execute remediation) and run
# in "agent" mode. Mode still gates writes per-command at execution time.
_READONLY_KINDS = frozenset({"correlation", "dedup", "summarizer"})


def _flag_enabled() -> bool:
    return os.getenv("AURORA_TRIGGER_ROUTER_ENABLED", "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class AgentDispatch:
    agent_name: str
    kind: str
    mode: str            # "ask" | "agent"
    prompt: str
    max_turns: int
    max_seconds: int
    model: Optional[str]
    tool_allowlist: List[str]  # catalog tool names this agent may use


def _lifecycle_prompt(role_body: str, event: LifecycleEvent) -> str:
    ctx = [
        f"Lifecycle event: {event.event_type}",
        f"Incident: {event.incident_id}" if event.incident_id else None,
        f"Service: {event.service}" if event.service else None,
        f"Severity: {event.severity}" if event.severity else None,
        f"Source: {event.source}" if event.source else None,
    ]
    context = "\n".join(c for c in ctx if c)
    return f"{role_body}\n\n---\nContext for this run:\n{context}"


def build_dispatch_plan(
    agent_names: List[str],
    event: LifecycleEvent,
    *,
    overrides: Optional[Dict[str, dict]] = None,
    prompt_overrides: Optional[Dict[str, str]] = None,
    custom_roles: Optional[Dict[str, object]] = None,
) -> List[AgentDispatch]:
    """Build an ordered dispatch plan for the routed agents. Pure.

    Each agent's role supplies the prompt body, limits, and model; ``overrides``
    (per-org agent_overrides) may adjust limits/model. Agents missing from the
    registry are skipped. ``overrides`` does not re-check ``enabled`` here —
    disabled agents are already filtered out by route_event.
    """
    from chat.backend.agent.orchestrator.role_registry import (
        RoleRegistry,
        apply_agent_override,
    )
    from chat.backend.agent.tools.tool_registry import allowed_tools_for_capabilities

    overrides = overrides or {}
    prompt_overrides = prompt_overrides or {}
    custom_roles = custom_roles or {}
    reg = RoleRegistry.get_instance()
    plan: List[AgentDispatch] = []
    for name in agent_names:
        role = reg.get(name) or custom_roles.get(name)
        if role is None:
            logger.warning("trigger executor: routed agent %r not in registry — skipping", name)
            continue
        # Per-org prompt override (prompt versioning) wins over the markdown body.
        role_body = prompt_overrides.get(name) or role.body
        merged = apply_agent_override(
            {
                "max_turns": role.max_turns,
                "max_seconds": role.max_seconds,
                "model": role.model,
            },
            overrides.get(name),
        )
        plan.append(AgentDispatch(
            agent_name=name,
            kind=role.kind,
            mode="ask" if role.kind in _READONLY_KINDS else "agent",
            prompt=_lifecycle_prompt(role_body, event),
            max_turns=int(merged["max_turns"]),
            max_seconds=int(merged["max_seconds"]),
            model=merged.get("model"),
            tool_allowlist=sorted(allowed_tools_for_capabilities(role.tools)),
        ))
    return plan


def dispatch_lifecycle_event(user_id: str, event: LifecycleEvent) -> List[str]:
    """Route + dispatch a lifecycle event. Flag-gated and fully fail-safe.

    Returns the list of agent names dispatched (empty when the flag is off, the
    route is disabled, or on any error). Never raises.
    """
    if not _flag_enabled():
        return []
    try:
        from services.registry.overrides import get_agent_overrides, get_disabled_agents_safe
        from services.routing.rules import get_disabled_event_types_safe

        # Org-defined custom routes (extra agent/workflow steps), fail-open.
        extra_routes = {}
        try:
            from services.routing.custom_routes import get_custom_routes_safe
            extra_routes = get_custom_routes_safe(user_id)
        except Exception:
            logger.debug("trigger executor: custom-route lookup failed; using defaults")

        decision = route_event(
            event,
            disabled_event_types=get_disabled_event_types_safe(user_id),
            disabled_agents=get_disabled_agents_safe(user_id),
            extra_routes=extra_routes or None,
        )
        if not decision.targets:
            return []

        overrides = {}
        try:
            overrides = get_agent_overrides(user_id, event.org_id)
        except Exception:
            logger.debug("trigger executor: override lookup failed; using defaults")

        # Per-org prompt overrides (prompt versioning), fail-open per agent.
        prompt_overrides = {}
        try:
            from services.prompts.versions import get_active_prompt_safe
            for name in decision.agents:
                ov = get_active_prompt_safe(user_id, f"agent:{name}")
                if ov:
                    prompt_overrides[name] = ov
        except Exception:
            logger.debug("trigger executor: prompt-override lookup failed; using defaults")

        # Resolve any org custom agents referenced by the routes.
        custom_roles = {}
        try:
            from services.registry.custom_agents import get_custom_agents_map_safe
            custom_roles = get_custom_agents_map_safe(user_id)
        except Exception:
            logger.debug("trigger executor: custom-agent lookup failed; using built-ins only")

        plan = build_dispatch_plan(
            decision.agents, event, overrides=overrides, prompt_overrides=prompt_overrides,
            custom_roles=custom_roles,
        )
        from chat.background.task import create_background_chat_session, run_background_chat

        dispatched: List[str] = []
        for spec in plan:
            try:
                trigger_meta = {
                    "source": "trigger_router",
                    "event_type": event.event_type,
                    "agent": spec.agent_name,
                    "incident_id": event.incident_id,
                }
                session_id = create_background_chat_session(
                    user_id=user_id,
                    title=f"{spec.agent_name}: {event.event_type}",
                    trigger_metadata=trigger_meta,
                )
                run_background_chat.delay(
                    user_id=user_id,
                    session_id=session_id,
                    initial_message=spec.prompt,
                    trigger_metadata=trigger_meta,
                    mode=spec.mode,
                    send_notifications=False,
                    incident_id=event.incident_id,
                    tool_allowlist=spec.tool_allowlist,
                    is_postmortem=(spec.kind == "postmortem"),
                )
                dispatched.append(spec.agent_name)
                # Evidence: record that this agent was dispatched for the event.
                try:
                    from services.observability.evidence import record_evidence_safe
                    record_evidence_safe(
                        user_id, kind="agent_dispatch", source="trigger_router",
                        title=f"{spec.agent_name} dispatched for {event.event_type}",
                        incident_id=event.incident_id, session_id=session_id,
                    )
                except Exception:
                    pass
            except Exception:
                logger.exception("trigger executor: failed to dispatch %s", spec.agent_name)

        # Workflow targets: prefer a V2 node-graph def (Temporal); fall back to V1.
        workflow_refs = [t["ref"] for t in decision.targets if t.get("target_type") == "workflow"]
        for wf_key in workflow_refs:
            d = None
            try:
                from services.workflows.defs import get_def
                d = get_def(user_id, event.org_id, wf_key)
            except Exception:
                d = None
            if d:
                try:
                    from workflows_v2.client import start_run
                    res = start_run(d["graph"], {"user_id": user_id, "org_id": event.org_id,
                                                 "incident_id": event.incident_id})
                    dispatched.append(f"workflow:{wf_key}({'started' if res.get('ok') else 'error'})")
                except Exception:
                    logger.exception("trigger executor: V2 workflow start failed for %s", wf_key)
            else:
                try:
                    from services.workflows.workflow_executor import run_workflow
                    result = run_workflow(user_id, wf_key, incident_id=event.incident_id)
                    dispatched.append(f"workflow:{wf_key}({result.status})")
                except Exception:
                    logger.exception("trigger executor: V1 workflow dispatch failed for %s", wf_key)

        logger.info(
            "trigger executor: event=%s dispatched=%s", event.event_type, dispatched
        )
        return dispatched
    except Exception:
        logger.exception("trigger executor: dispatch_lifecycle_event failed (fail-safe)")
        return []


__all__ = ["AgentDispatch", "build_dispatch_plan", "dispatch_lifecycle_event"]
