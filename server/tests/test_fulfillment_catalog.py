"""Unit tests for the fulfillment catalog + policy engine (pure, no DB/LLM)."""

from services.fulfillment import catalog as cat
from services.fulfillment import policy as pol


def test_category_and_keyword_match_selects_expected_entry():
    e = cat.match_entry(cat.SERVICE_REQUEST, category="firewall", text="please open port 443")
    assert e is not None and e.target_ref == "fortigate_open_port"

    e = cat.match_entry(cat.SERVICE_REQUEST, text="onboard a new user in AD")
    assert e is not None and e.key == "create_ad_user"

    e = cat.match_entry(cat.REMEDIATION, text="host is unreachable, no ping")
    assert e is not None and e.key == "vm_troubleshoot"


def test_no_match_returns_none_for_human_fallback():
    assert cat.match_entry(cat.SERVICE_REQUEST, text="something totally unrelated xyz") is None


def test_all_targets_are_workflow_action_or_agent():
    for e in cat.list_default_catalog():
        assert e.target_type in ("workflow", "action", "agent")
        assert e.intent in (cat.REMEDIATION, cat.SERVICE_REQUEST)
        assert e.risk_class in (cat.RISK_SAFE, cat.RISK_STANDARD, cat.RISK_PRIVILEGED)


def test_policy_readonly_is_auto():
    e = cat.get_entry("vm_troubleshoot")
    assert e.read_only and pol.decide(e) == pol.AUTO


def test_policy_privileged_never_auto_even_if_allowlisted(monkeypatch):
    monkeypatch.setenv("AURORA_AUTO_REMEDIATE_ALLOWLIST", "open_firewall_port,create_ad_user")
    fw = cat.get_entry("open_firewall_port")
    assert fw.risk_class == cat.RISK_PRIVILEGED
    assert pol.decide(fw) == pol.APPROVAL          # privileged rail wins over allowlist
    ok, _ = pol.safety_gate(fw)
    assert ok is False


def test_policy_standard_auto_only_when_allowlisted(monkeypatch):
    monkeypatch.delenv("AURORA_AUTO_REMEDIATE_ALLOWLIST", raising=False)
    backup = cat.get_entry("backup_vm")
    assert backup.risk_class == cat.RISK_STANDARD
    assert pol.decide(backup) == pol.APPROVAL       # not allowlisted -> approval
    monkeypatch.setenv("AURORA_AUTO_REMEDIATE_ALLOWLIST", "backup_vm")
    assert pol.decide(backup) == pol.AUTO           # allowlisted -> auto
