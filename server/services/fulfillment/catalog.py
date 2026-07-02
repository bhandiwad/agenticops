"""Fulfillment Catalog — the data-driven registry that maps a ticket (incident remediation OR
service request) to an EXISTING capability (a workflow, an Aurora action, or an agent role).

The engine is domain-agnostic: fulfilling a request means "run whatever already does this".
Adding a new fulfillable service is a new catalog entry, not new engine code. Entries are
selected deterministically by intent + category/keyword match; the LLM only fills parameters.

Built-in defaults are code-seeded (versioned in git, work out of the box). A per-org override
layer can extend/replace them later (see get_catalog); Phase 1 returns the defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Intents
REMEDIATION = "remediation"
SERVICE_REQUEST = "service_request"

# Risk classes drive the policy engine (auto vs approval).
RISK_SAFE = "safe"            # read-only or trivially reversible
RISK_STANDARD = "standard"    # mutating but routine
RISK_PRIVILEGED = "privileged"  # security/identity/infra-sensitive — never auto


@dataclass(frozen=True)
class FulfillmentEntry:
    key: str
    title: str
    intent: str                     # REMEDIATION | SERVICE_REQUEST
    target_type: str                # "workflow" | "action" | "agent"
    target_ref: str                 # workflow key / action id / agent role
    risk_class: str = RISK_STANDARD
    read_only: bool = False
    categories: tuple = ()          # SNOW category values that map here (exact, case-insensitive)
    keywords: tuple = ()            # matched against short_description / free text
    params: tuple = ()              # parameter names the planner should fill from the ticket
    description: str = ""

    def matches_category(self, category: Optional[str]) -> bool:
        if not category or not self.categories:
            return False
        c = category.strip().lower()
        return any(c == cat.strip().lower() for cat in self.categories)

    def keyword_score(self, text: Optional[str]) -> int:
        if not text or not self.keywords:
            return 0
        t = text.lower()
        return sum(1 for kw in self.keywords if kw.lower() in t)


# --------------------------------------------------------------------------- #
# Built-in catalog: every target below already exists (workflows we shipped).
# New services are added here (or per-org) pointing at a workflow/action/agent.
# --------------------------------------------------------------------------- #
DEFAULT_CATALOG: List[FulfillmentEntry] = [
    # ---- Service requests -------------------------------------------------- #
    FulfillmentEntry(
        key="open_firewall_port", title="Open a firewall port",
        intent=SERVICE_REQUEST, target_type="workflow", target_ref="fortigate_open_port",
        risk_class=RISK_PRIVILEGED,
        categories=("network", "firewall", "security"),
        keywords=("open port", "firewall rule", "allow port", "whitelist", "open firewall"),
        params=("protocol", "port", "dstaddr", "srcintf", "dstintf", "srcaddr", "nat"),
        description="Create a FortiGate allow policy for the requested port (approval-gated).",
    ),
    FulfillmentEntry(
        key="backup_vm", title="Back up a VM",
        intent=SERVICE_REQUEST, target_type="workflow", target_ref="commvault_backup_vm",
        risk_class=RISK_STANDARD,
        categories=("backup", "storage"),
        keywords=("backup", "take a backup", "snapshot", "protect vm"),
        params=("entity_type", "entity_id", "backup_level"),
        description="Trigger a Commvault backup of the requested VM/subclient and validate it.",
    ),
    FulfillmentEntry(
        key="create_ad_user", title="Create Active Directory user(s)",
        intent=SERVICE_REQUEST, target_type="workflow", target_ref="ad_bulk_user_add",
        risk_class=RISK_PRIVILEGED,
        categories=("identity", "active directory", "access"),
        keywords=("create user", "new user", "add user", "onboard", "ad account", "provision user"),
        params=("dc_host", "users"),
        description="Create the requested AD user(s) on a Domain Controller (approval-gated).",
    ),
    FulfillmentEntry(
        key="windows_patch", title="Patch/upgrade a Windows host",
        intent=SERVICE_REQUEST, target_type="workflow", target_ref="windows_patch_update",
        risk_class=RISK_STANDARD,
        categories=("patching", "maintenance", "windows"),
        keywords=("patch", "windows update", "install updates", "upgrade windows", "hotfix", "kb"),
        params=("host", "patch_scope"),
        description="Apply approved Windows updates to the host, verify, update the ticket.",
    ),
    FulfillmentEntry(
        key="ad_replication_health", title="Active Directory replication health report",
        intent=SERVICE_REQUEST, target_type="workflow", target_ref="ad_replication_health",
        risk_class=RISK_SAFE, read_only=True,
        categories=("identity", "active directory", "report"),
        keywords=("replication health", "repadmin", "ad health", "dc health"),
        params=("dc_host",),
        description="Read-only AD replication health check recorded on the ticket.",
    ),

    # ---- Remediation (incident) ------------------------------------------- #
    FulfillmentEntry(
        key="vm_threshold_remediation", title="Remediate a VM threshold breach",
        intent=REMEDIATION, target_type="workflow", target_ref="vm_threshold_remediation",
        risk_class=RISK_STANDARD,
        keywords=("cpu", "memory", "disk full", "high load", "threshold", "out of memory",
                  "disk usage", "service down", "restart service"),
        params=("host", "os", "breach"),
        description="Diagnose the breach, then (approved) remediate and verify recovery.",
    ),
    FulfillmentEntry(
        key="vm_troubleshoot", title="Troubleshoot a hung/unreachable VM",
        intent=REMEDIATION, target_type="workflow", target_ref="vm_troubleshoot",
        risk_class=RISK_SAFE, read_only=True,
        keywords=("unreachable", "hung", "not responding", "cannot connect", "vm down",
                  "host down", "no ping"),
        params=("host", "os"),
        description="Read-only diagnosis of a hung/unreachable VM, findings on the ticket.",
    ),
    FulfillmentEntry(
        key="open_firewall_port_remediation", title="Open a firewall port (remediation)",
        intent=REMEDIATION, target_type="workflow", target_ref="fortigate_open_port",
        risk_class=RISK_PRIVILEGED,
        keywords=("blocked by firewall", "port blocked", "connectivity blocked", "denied by policy"),
        params=("protocol", "port", "dstaddr", "srcintf", "dstintf", "srcaddr", "nat"),
        description="Open a firewall port to remediate a blocked-connectivity root cause.",
    ),
]


def list_default_catalog() -> List[FulfillmentEntry]:
    return list(DEFAULT_CATALOG)


def get_catalog(user_id: Optional[str] = None, org_id: Optional[str] = None) -> List[FulfillmentEntry]:
    """Effective catalog for an org: built-in defaults + per-org overrides.

    Phase 1 returns the built-in defaults. The per-org override layer (DB-backed, added later)
    plugs in here without changing callers.
    """
    return list_default_catalog()


def match_entry(
    intent: str,
    *,
    category: Optional[str] = None,
    text: Optional[str] = None,
    catalog: Optional[List[FulfillmentEntry]] = None,
    min_keyword_score: int = 1,
) -> Optional[FulfillmentEntry]:
    """Deterministically pick the best catalog entry for a ticket within an intent.

    Scoring: an exact category match is worth a large boost; otherwise the entry with the most
    keyword hits wins. Returns None if nothing meets ``min_keyword_score`` and no category hit —
    the caller then falls back to a human (no guessing).
    """
    entries = [e for e in (catalog or list_default_catalog()) if e.intent == intent]
    best: Optional[FulfillmentEntry] = None
    best_score = 0
    for e in entries:
        score = e.keyword_score(text)
        if e.matches_category(category):
            score += 100
        if score > best_score:
            best_score, best = score, e
    if best is None or best_score < min_keyword_score:
        return None
    return best


def get_entry(key: str, catalog: Optional[List[FulfillmentEntry]] = None) -> Optional[FulfillmentEntry]:
    for e in (catalog or list_default_catalog()):
        if e.key == key:
            return e
    return None
