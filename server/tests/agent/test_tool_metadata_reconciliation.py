"""Reconcile the new tool_registry catalog with the pre-existing tool metadata.

A partial tool-metadata table already lives in
``orchestrator/select_skills._TOOL_METADATA`` (capability_tags + ``mutates`` +
``cacheable``), and it is load-bearing: ``select_tools_for_role`` uses it to
build read-only, capability-scoped tool allowlists for RCA sub-agents.

``tool_registry`` is a superset (full coverage + a 3-tier ``risk`` + connector
id). These tests lock the relationship so the two cannot silently diverge,
and document the one intentional difference between ``risk`` and ``mutates``.

The ``risk`` vs ``mutates`` axes are complementary, not redundant:
  * ``mutates``  — does the tool, AS USED by a read-only sub-agent, write?
    Command-execution tools (cloud_exec/kubectl/terminal/tailscale) are marked
    ``mutates=False`` because write-safety is enforced per-command by the
    guardrail layer, so sub-agents may use them to *query* state.
  * ``risk``     — the maximum blast radius of the tool's capability. Those same
    command-execution tools are ``DESTRUCTIVE`` because they *can* destroy.

So the invariant that must hold is one-directional: anything the orchestrator
calls ``mutates`` must not be classified ``READ`` here.
"""

from __future__ import annotations

import pytest

from chat.backend.agent.tools.tool_registry import TOOL_CATALOG, Risk, tool_risk

select_skills = pytest.importorskip(
    "chat.backend.agent.orchestrator.select_skills",
    reason="orchestrator.select_skills not importable in this environment",
)
_TOOL_METADATA = select_skills._TOOL_METADATA

# Tools that are mutates=False in _TOOL_METADATA (so usable by read-only
# sub-agents) yet DESTRUCTIVE in the catalog (their capability CAN destroy).
# This divergence is intentional and falls into two groups; the set is locked so
# any new divergence forces a deliberate decision rather than slipping in:
#   1. Command-execution tools — write-safety enforced per-command by the
#      guardrail layer, not by the static flag.
#   2. Multi-action tools served as a read-only subset during RCA — their write
#      actions are withheld from sub-agents via the RCA tool description/subset.
_GATED_DESTRUCTIVE = {
    # group 1 — command execution
    "cloud_exec",
    "on_prem_kubectl",
    "terminal_exec",
    "tailscale_ssh",
    # group 2 — read-only subset during RCA
    "bitbucket_repos",
    "bitbucket_branches",
}


def test_every_metadata_tool_is_in_catalog():
    """The orchestrator must not know a tool the catalog hasn't classified."""
    missing = sorted(set(_TOOL_METADATA) - set(TOOL_CATALOG))
    assert not missing, f"tools in _TOOL_METADATA but unclassified in catalog: {missing}"


@pytest.mark.parametrize("name", sorted(_TOOL_METADATA))
def test_mutating_tools_are_not_read_in_catalog(name: str):
    """Safety direction: if the orchestrator says a tool mutates, the catalog
    must not call it read-only."""
    if _TOOL_METADATA[name].get("mutates") is True:
        assert tool_risk(name) is not Risk.READ, (
            f"{name} is mutates=True in _TOOL_METADATA but READ in the catalog"
        )


def test_metadata_capability_tags_are_subset_of_catalog():
    """The catalog must use the same capability vocabulary as the orchestrator
    and tag each shared tool with at least the orchestrator's tags. Keeps the
    two tag systems aligned (single vocabulary) so role allowlists resolve the
    same way regardless of which system a future consumer reads."""
    from chat.backend.agent.tools.tool_registry import KNOWN_CAPABILITIES, get_tool_spec
    offenders = {}
    for name, meta in _TOOL_METADATA.items():
        spec = get_tool_spec(name)
        if spec is None:
            continue
        meta_tags = set(meta.get("capability_tags", []))
        # Vocabulary alignment: orchestrator tags must be known to the catalog.
        assert meta_tags <= KNOWN_CAPABILITIES, (
            f"{name}: _TOOL_METADATA uses tags outside the catalog vocabulary: "
            f"{sorted(meta_tags - KNOWN_CAPABILITIES)}"
        )
        if not meta_tags <= spec.capabilities:
            offenders[name] = sorted(meta_tags - spec.capabilities)
    assert not offenders, (
        f"catalog tags missing orchestrator tags for: {offenders}"
    )


def test_gated_destructive_divergence_is_exactly_documented():
    """Lock the known risk-vs-mutates divergence so a new one fails loudly.

    The divergent set is the complete list of tools that are non-mutating in the
    orchestrator metadata but DESTRUCTIVE in the catalog. If it changes, a tool's
    classification must be reconciled deliberately.
    """
    divergent = {
        name
        for name in _TOOL_METADATA
        if _TOOL_METADATA[name].get("mutates") is False
        and tool_risk(name) is Risk.DESTRUCTIVE
    }
    assert divergent == _GATED_DESTRUCTIVE, (
        "risk/mutates divergence changed; reconcile intentionally. "
        f"got {sorted(divergent)}, expected {sorted(_GATED_DESTRUCTIVE)}"
    )
