"""Tests for the workflow registry + pure planner."""

from __future__ import annotations

from services.workflows.workflow_registry import (
    DEFAULT_WORKFLOWS,
    STEP_AGENT,
    STEP_APPROVAL,
    serialize_workflow,
    validate_workflow,
)
from services.workflows.workflow_executor import plan_workflow, run_workflow


def test_builtin_workflows_present():
    assert {"rca_complete", "remediation"} <= set(DEFAULT_WORKFLOWS)


def test_all_builtin_workflows_validate():
    # Agent steps must reference real registry agents; structure must be valid.
    for wf in DEFAULT_WORKFLOWS.values():
        errors = validate_workflow(wf)
        assert errors == [], f"{wf.key} invalid: {errors}"


def test_remediation_has_approval_gate_between_planner_and_executor():
    wf = DEFAULT_WORKFLOWS["remediation"]
    types = [s.type for s in wf.steps]
    refs = [s.ref for s in wf.steps]
    assert types == [STEP_AGENT, STEP_APPROVAL, STEP_AGENT]
    assert refs[0] == "remediation_planner_agent"
    assert refs[2] == "runbook_executor_agent"


def test_validate_flags_unknown_agent():
    from services.workflows.workflow_registry import Workflow, WorkflowStep, KIND_LLM
    bad = Workflow("bad", "Bad", KIND_LLM, [WorkflowStep(STEP_AGENT, "no_such_agent")])
    errors = validate_workflow(bad)
    assert any("unknown agent" in e for e in errors)


def test_serialize_workflow_shape():
    s = serialize_workflow(DEFAULT_WORKFLOWS["rca_complete"], enabled=False)
    assert s["key"] == "rca_complete" and s["enabled"] is False
    assert all(set(step) == {"type", "ref", "label", "condition"} for step in s["steps"])


def test_plan_workflow_preserves_order_and_indices():
    plan = plan_workflow(DEFAULT_WORKFLOWS["remediation"])
    assert [p.index for p in plan] == [0, 1, 2]
    assert [p.type for p in plan] == [STEP_AGENT, STEP_APPROVAL, STEP_AGENT]


def test_workflow_from_dict_roundtrip_and_validation():
    from services.workflows.workflow_registry import workflow_from_dict, validate_workflow
    wf = workflow_from_dict({
        "key": "custom_x", "name": "Custom X", "kind": "llm",
        "steps": [
            {"type": "agent", "ref": "summarizer_agent", "label": "Summarize"},
            {"type": "approval"},
            {"type": "agent", "ref": "notification_agent"},
        ],
    })
    assert [s.type for s in wf.steps] == ["agent", "approval", "agent"]
    assert validate_workflow(wf) == []
    # Unknown agent in a custom definition is rejected.
    bad = workflow_from_dict({"key": "bad", "name": "Bad", "kind": "llm",
                              "steps": [{"type": "agent", "ref": "ghost_agent"}]})
    assert any("unknown agent" in e for e in validate_workflow(bad))


def test_run_workflow_noop_when_flag_disabled(monkeypatch):
    monkeypatch.delenv("AURORA_WORKFLOWS_ENABLED", raising=False)
    result = run_workflow("user1", "remediation", incident_id="inc1")
    assert result.status == "disabled"
    assert result.dispatched == []
