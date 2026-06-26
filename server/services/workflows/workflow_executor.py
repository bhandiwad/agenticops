"""Execute a workflow: walk its steps, dispatching agents/actions and pausing at
approval gates.

Flag-gated by AURORA_WORKFLOWS_ENABLED (default off) and fully fail-safe. The
``plan_workflow`` planner is pure and testable; ``run_workflow`` performs the
dispatch I/O (Celery / approvals) and is validated in staging.

Approval-gate semantics: stepping reaches an ``approval`` step, a HITL approval
is queued and execution STOPS (returns ``paused``). Completing the workflow past
the gate (resuming the remaining steps) is the documented follow-up — it reuses
the approvals resume mechanism with a workflow-continuation payload.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

from services.workflows.workflow_registry import (
    DEFAULT_WORKFLOWS,
    STEP_ACTION,
    STEP_AGENT,
    STEP_APPROVAL,
    Workflow,
)

logger = logging.getLogger(__name__)


def _flag_enabled() -> bool:
    return os.getenv("AURORA_WORKFLOWS_ENABLED", "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class PlannedStep:
    index: int
    type: str
    ref: str
    label: str


def plan_workflow(wf: Workflow) -> List[PlannedStep]:
    """Pure: expand a workflow into an ordered list of planned steps."""
    return [
        PlannedStep(i, s.type, s.ref, s.label or s.ref or s.type)
        for i, s in enumerate(wf.steps)
    ]


@dataclass(frozen=True)
class WorkflowRunResult:
    workflow_key: str
    status: str                  # "completed" | "paused" | "disabled" | "skipped" | "error"
    dispatched: List[str]
    paused_at: Optional[int] = None


def run_workflow(
    user_id: str,
    workflow_key: str,
    *,
    incident_id: Optional[str] = None,
    start_index: int = 0,
) -> WorkflowRunResult:
    """Run a workflow for the user, starting at ``start_index`` (used to resume
    past an approval gate). Flag-gated + fail-safe (never raises)."""
    if not _flag_enabled():
        return WorkflowRunResult(workflow_key, "disabled", [])
    try:
        wf = DEFAULT_WORKFLOWS.get(workflow_key)
        if wf is None:
            # Org-authored custom workflow (already enabled-checked in the loader).
            try:
                from services.workflows.custom import get_custom_workflow_safe
                wf = get_custom_workflow_safe(user_id, workflow_key)
            except Exception:
                wf = None
        if wf is None:
            return WorkflowRunResult(workflow_key, "error", [])

        # Respect per-org enable/disable for built-ins.
        if workflow_key in DEFAULT_WORKFLOWS:
            try:
                from services.workflows.rules import get_disabled_workflows_safe
                if workflow_key in get_disabled_workflows_safe(user_id):
                    return WorkflowRunResult(workflow_key, "skipped", [])
            except Exception:
                pass

        from services.routing.events import RCA_COMPLETED, LifecycleEvent
        from services.routing.executor import build_dispatch_plan

        dispatched: List[str] = []
        event = LifecycleEvent(event_type=RCA_COMPLETED, org_id="", incident_id=incident_id)

        # Resolve org custom agents so workflow agent-steps can reference them.
        custom_roles = {}
        try:
            from services.registry.custom_agents import get_custom_agents_map_safe
            custom_roles = get_custom_agents_map_safe(user_id)
        except Exception:
            logger.debug("run_workflow: custom-agent lookup failed; built-ins only")

        for step in plan_workflow(wf):
            if step.index < start_index:
                continue  # resuming: skip already-executed steps
            if step.type == STEP_APPROVAL:
                # Queue an approval gate and pause the workflow here. The approval
                # carries a workflow-continuation payload so approving resumes the
                # workflow at the next step.
                try:
                    from services.policy.approvals import create_approval_safe
                    create_approval_safe(
                        user_id,
                        tool_name=f"workflow:{workflow_key}",
                        summary=f"Approve to continue workflow '{wf.name}' at step '{step.label}'",
                        incident_id=incident_id,
                        resume_payload={
                            "kind": "workflow",
                            "workflow_key": workflow_key,
                            "next_index": step.index + 1,
                            "incident_id": incident_id,
                        },
                    )
                except Exception:
                    logger.debug("run_workflow: failed to queue approval gate (non-fatal)")
                return WorkflowRunResult(workflow_key, "paused", dispatched, paused_at=step.index)

            if step.type == STEP_AGENT:
                try:
                    from chat.background.task import create_background_chat_session, run_background_chat
                    specs = build_dispatch_plan([step.ref], event, custom_roles=custom_roles)
                    for spec in specs:
                        meta = {"source": "workflow", "workflow": workflow_key, "agent": spec.agent_name}
                        session_id = create_background_chat_session(
                            user_id=user_id, title=f"{workflow_key}: {spec.agent_name}", trigger_metadata=meta,
                        )
                        run_background_chat.delay(
                            user_id=user_id, session_id=session_id, initial_message=spec.prompt,
                            trigger_metadata=meta, mode=spec.mode, send_notifications=False,
                            incident_id=incident_id, tool_allowlist=spec.tool_allowlist,
                        )
                        dispatched.append(spec.agent_name)
                except Exception:
                    logger.exception("run_workflow: failed to dispatch agent step %s", step.ref)

            elif step.type == STEP_ACTION:
                try:
                    from services.actions.executor import dispatch_action
                    dispatch_action(step.ref, user_id, {"incident_id": incident_id})
                    dispatched.append(f"action:{step.ref}")
                except Exception:
                    logger.exception("run_workflow: failed to dispatch action step %s", step.ref)

        return WorkflowRunResult(workflow_key, "completed", dispatched)
    except Exception:
        logger.exception("run_workflow: failed (fail-safe)")
        return WorkflowRunResult(workflow_key, "error", [])


__all__ = ["PlannedStep", "plan_workflow", "WorkflowRunResult", "run_workflow"]
