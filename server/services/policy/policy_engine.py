"""Risk-based policy engine for tool execution.

Decides whether a tool action may run, must be denied, or requires human
approval, based on the tool's risk classification (tool_registry) and execution
context. This is the decision brain consumed by the command gate; it is pure
(no DB / no I/O) so it is fully unit-testable.

Decision model (defaults):
  * Foreground runs            -> ALLOW. Foreground HITL is handled by the
    existing interactive confirmation flow (command_gate._prompt_user); the
    policy engine does not override that UX.
  * Background / autonomous runs:
      - read-only tool          -> ALLOW
      - write / destructive / unknown -> REQUIRE_APPROVAL (queued for a human;
        the gate blocks execution until approved). Never auto-allows what the
        gate would otherwise deny.

The unknown case (tool not in the catalog, e.g. an action key like
``gitlab:create_merge_request`` or an MCP tool) is treated as write-equivalent
in the background — fail safe, require approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from chat.backend.agent.tools.tool_registry import Risk, tool_risk


class PolicyAction(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    reason: str
    risk: Optional[str] = None  # the tool's catalog risk, if known


def decide(
    tool_name: str,
    *,
    is_background: bool,
    risk_override: Optional[Risk] = None,
) -> PolicyDecision:
    """Return the policy decision for ``tool_name`` in the given context."""
    risk = risk_override or tool_risk(tool_name)
    risk_value = risk.value if risk else None

    if not is_background:
        return PolicyDecision(PolicyAction.ALLOW, "foreground: interactive HITL applies", risk_value)

    if risk is Risk.READ:
        return PolicyDecision(PolicyAction.ALLOW, "background read-only tool", risk_value)

    # write / destructive / unknown in background -> needs a human.
    label = risk_value or "unclassified"
    return PolicyDecision(
        PolicyAction.REQUIRE_APPROVAL,
        f"background {label} action requires approval",
        risk_value,
    )


__all__ = ["PolicyAction", "PolicyDecision", "decide"]
