"""Tests for RoleRegistry kind discrimination and the expanded typed-agent set.

RoleRegistry loads role markdown with no heavy deps, so these run in the
lightweight env. They lock:
  * existing investigator roles keep kind=investigator (backward compatible),
  * the new lifecycle/typed agents load with their declared kinds,
  * RCA dispatch (list_investigators) excludes lifecycle agents,
  * every role's capability tags use the canonical tool_registry vocabulary.
"""

from __future__ import annotations

from chat.backend.agent.tools.tool_registry import KNOWN_CAPABILITIES
from chat.backend.agent.orchestrator.role_registry import (
    INVESTIGATOR_KIND,
    RoleRegistry,
)

# The lifecycle/typed agents added on top of the RCA investigators, with their
# expected kinds.
_EXPECTED_LIFECYCLE_ROLES = {
    "correlation_agent": "correlation",
    "dedup_agent": "dedup",
    "summarizer_agent": "summarizer",
    "remediation_planner_agent": "remediation",
    "runbook_executor_agent": "runbook_executor",
    "notification_agent": "notification",
    "postmortem_agent": "postmortem",
}


def _registry() -> RoleRegistry:
    # Fresh instance to avoid singleton state bleeding across the suite.
    return RoleRegistry()


def test_existing_investigator_roles_default_to_investigator_kind():
    reg = _registry()
    investigators = reg.list_investigators()
    # The six pre-existing RCA investigators have no `kind` in frontmatter and
    # must default to investigator.
    names = {r.name for r in investigators}
    assert {"general_investigator", "error_signal_investigator"} <= names
    assert all(r.kind == INVESTIGATOR_KIND for r in investigators)


def test_lifecycle_roles_load_with_declared_kinds():
    reg = _registry()
    for name, kind in _EXPECTED_LIFECYCLE_ROLES.items():
        role = reg.get(name)
        assert role is not None, f"{name} did not load"
        assert role.kind == kind, f"{name}: expected kind {kind}, got {role.kind}"


def test_list_investigators_excludes_lifecycle_agents():
    reg = _registry()
    investigator_names = {r.name for r in reg.list_investigators()}
    for name in _EXPECTED_LIFECYCLE_ROLES:
        assert name not in investigator_names, (
            f"{name} must not be an RCA dispatch target"
        )


def test_list_all_includes_every_role():
    reg = _registry()
    all_names = {r.name for r in reg.list_all()}
    assert set(_EXPECTED_LIFECYCLE_ROLES) <= all_names
    # list_all is a superset of list_investigators.
    assert {r.name for r in reg.list_investigators()} <= all_names


def test_list_all_filter_by_kind():
    reg = _registry()
    notif = reg.list_all(kind="notification")
    assert [r.name for r in notif] == ["notification_agent"]
    assert reg.list_all(kind="does_not_exist") == []


def test_every_role_uses_canonical_capability_vocabulary():
    """Roles and the tool catalog must speak one capability language."""
    reg = _registry()
    for role in reg.list_all():
        unknown = set(role.tools) - KNOWN_CAPABILITIES
        assert not unknown, (
            f"role {role.name} uses tags outside the canonical vocabulary: "
            f"{sorted(unknown)}"
        )


def test_lifecycle_roles_have_nonempty_prompt_body():
    reg = _registry()
    for name in _EXPECTED_LIFECYCLE_ROLES:
        role = reg.get(name)
        assert role.body and len(role.body) > 50, f"{name} has no prompt body"
