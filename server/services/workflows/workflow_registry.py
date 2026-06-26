"""Workflow registry: ordered/conditional composition of agents + actions + gates.

A Workflow is an ordered list of steps; each step is one of:
  * ``agent``    — run a typed agent (ref = role name from the agent registry)
  * ``action``   — run an Aurora Action (ref = action id/key)
  * ``approval`` — a human approval gate that must pass before later steps run

This module is pure (no DB / no execution). It provides the built-in workflows,
validation against the agent registry, and a JSON-able serialization for the
API/UI. Execution lives in ``workflow_executor`` (flag-gated, fail-safe).

Built-ins encode the AgenticOps reference flows, tying together the agent
registry, the trigger router, and the HITL approval gate:
  * ``rca_complete``  — summarizer -> notification -> postmortem
  * ``remediation``   — remediation_planner -> [approval] -> runbook_executor
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

STEP_AGENT = "agent"
STEP_ACTION = "action"
STEP_APPROVAL = "approval"
_STEP_TYPES = (STEP_AGENT, STEP_ACTION, STEP_APPROVAL)

KIND_LLM = "llm"
KIND_SOP = "sop"


@dataclass(frozen=True)
class WorkflowStep:
    type: str
    ref: str = ""                       # agent name / action id; "" for approval
    condition: Optional[Dict[str, str]] = None
    label: str = ""


@dataclass(frozen=True)
class Workflow:
    key: str
    name: str
    kind: str
    steps: List[WorkflowStep]
    description: str = ""


DEFAULT_WORKFLOWS: Dict[str, Workflow] = {
    "rca_complete": Workflow(
        key="rca_complete",
        name="RCA completion",
        kind=KIND_LLM,
        description="After RCA: summarize, notify stakeholders, draft postmortem.",
        steps=[
            WorkflowStep(STEP_AGENT, "summarizer_agent", label="Summarize findings"),
            WorkflowStep(STEP_AGENT, "notification_agent", label="Notify stakeholders"),
            WorkflowStep(STEP_AGENT, "postmortem_agent", label="Draft postmortem"),
        ],
    ),
    "remediation": Workflow(
        key="remediation",
        name="Guided remediation",
        kind=KIND_SOP,
        description="Plan a fix, require human approval, then execute the runbook.",
        steps=[
            WorkflowStep(STEP_AGENT, "remediation_planner_agent", label="Plan remediation"),
            WorkflowStep(STEP_APPROVAL, "", label="Human approval gate"),
            WorkflowStep(STEP_AGENT, "runbook_executor_agent", label="Execute approved runbook"),
        ],
    ),
}


def validate_workflow(wf: Workflow) -> List[str]:
    """Return a list of validation errors (empty == valid). Checks step types and
    that ``agent`` steps reference real agents in the registry."""
    errors: List[str] = []
    if not wf.steps:
        errors.append(f"{wf.key}: workflow has no steps")
    if wf.kind not in (KIND_LLM, KIND_SOP):
        errors.append(f"{wf.key}: invalid kind {wf.kind!r}")

    agent_names = set()
    try:
        from chat.backend.agent.orchestrator.role_registry import RoleRegistry
        agent_names = {r.name for r in RoleRegistry.get_instance().list_all()}
    except Exception:
        agent_names = set()  # registry unavailable — skip agent-existence check

    for i, step in enumerate(wf.steps):
        if step.type not in _STEP_TYPES:
            errors.append(f"{wf.key}[{i}]: invalid step type {step.type!r}")
            continue
        if step.type == STEP_AGENT:
            if not step.ref:
                errors.append(f"{wf.key}[{i}]: agent step missing ref")
            elif agent_names and step.ref not in agent_names:
                errors.append(f"{wf.key}[{i}]: unknown agent {step.ref!r}")
        elif step.type == STEP_ACTION and not step.ref:
            errors.append(f"{wf.key}[{i}]: action step missing ref")
    return errors


def serialize_workflow(wf: Workflow, *, enabled: bool = True) -> dict:
    return {
        "key": wf.key,
        "name": wf.name,
        "kind": wf.kind,
        "description": wf.description,
        "enabled": enabled,
        "steps": [
            {"type": s.type, "ref": s.ref, "label": s.label, "condition": s.condition}
            for s in wf.steps
        ],
    }


def default_workflows_serialized() -> List[dict]:
    return [serialize_workflow(wf) for wf in DEFAULT_WORKFLOWS.values()]


def workflow_from_dict(d: dict) -> Workflow:
    """Build a Workflow from a stored/custom dict (steps = list of step dicts)."""
    steps = [
        WorkflowStep(
            type=s.get("type", ""),
            ref=s.get("ref", "") or "",
            condition=s.get("condition"),
            label=s.get("label", "") or "",
        )
        for s in (d.get("steps") or [])
    ]
    return Workflow(
        key=d["key"],
        name=d.get("name") or d["key"],
        kind=d.get("kind") or KIND_LLM,
        steps=steps,
        description=d.get("description", "") or "",
    )


__all__ = [
    "STEP_AGENT", "STEP_ACTION", "STEP_APPROVAL", "KIND_LLM", "KIND_SOP",
    "WorkflowStep", "Workflow", "DEFAULT_WORKFLOWS",
    "validate_workflow", "serialize_workflow", "default_workflows_serialized",
    "workflow_from_dict",
]
