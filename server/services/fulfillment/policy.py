"""Fulfillment Policy engine — decides whether a matched catalog entry runs automatically or
requires human approval, given its risk class and the org's safe-allowlist.

Posture (per product decision): conservative safe-allowlist + per-org override.
- read_only entries         -> AUTO (no mutation)
- risk_class 'safe'         -> AUTO only if the entry is on the allowlist
- risk_class 'standard'     -> AUTO only if the entry is on the allowlist; else APPROVAL
- risk_class 'privileged'   -> ALWAYS APPROVAL (never auto, regardless of allowlist)

The allowlist = a conservative built-in set (read-only + explicitly safe entries) UNIONed with
``AURORA_AUTO_REMEDIATE_ALLOWLIST`` (comma-separated entry keys) and any per-org list. A
privileged entry can never be auto-run even if someone allowlists it — that's the safety rail.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from services.fulfillment.catalog import FulfillmentEntry, RISK_PRIVILEGED, RISK_SAFE, RISK_STANDARD

logger = logging.getLogger(__name__)

AUTO = "auto"
APPROVAL = "approval"

# Conservative built-in auto-allowlist: read-only diagnostics/reports are always safe to run.
# Mutating entries are NOT built-in-auto; an operator opts them in via the env/per-org allowlist.
_BUILTIN_AUTO_KEYS = frozenset({
    "vm_troubleshoot",        # read-only diagnosis
    "ad_replication_health",  # read-only report
})


def _env_allowlist() -> frozenset:
    raw = os.getenv("AURORA_AUTO_REMEDIATE_ALLOWLIST", "")
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


def _org_allowlist(org_id: Optional[str]) -> frozenset:
    """Per-org allowlist override hook. Phase 2 uses env-only; a DB/UI layer plugs in here."""
    return frozenset()


def allowlist(org_id: Optional[str] = None) -> frozenset:
    return _BUILTIN_AUTO_KEYS | _env_allowlist() | _org_allowlist(org_id)


def decide(entry: FulfillmentEntry, org_id: Optional[str] = None) -> str:
    """Return AUTO or APPROVAL for a matched catalog entry."""
    # Read-only never mutates → safe to auto-run.
    if entry.read_only:
        return AUTO
    # Privileged is the hard safety rail: always human-approved.
    if entry.risk_class == RISK_PRIVILEGED:
        return APPROVAL
    # safe/standard auto-run only when explicitly allowlisted.
    if entry.risk_class in (RISK_SAFE, RISK_STANDARD) and entry.key in allowlist(org_id):
        return AUTO
    return APPROVAL


def safety_gate(entry: FulfillmentEntry, params: Optional[dict] = None) -> tuple[bool, str]:
    """Final policy-level gate before an AUTO dispatch. Defense-in-depth on top of decide():
    privileged actions must never reach here as AUTO. The workflows/agents themselves still run
    the command-safety judge on any shell/infra action, so this is the coarse policy check.

    Returns (ok_to_auto, reason). ok=False forces the caller to fall back to approval.
    """
    if entry.risk_class == RISK_PRIVILEGED and not entry.read_only:
        return False, "privileged action cannot auto-run"
    return True, ""
