"""Generic fulfillment engine: ticket -> catalog entry -> params -> policy -> dispatch.

Shared by both intents (incident remediation, service request). Given a ticket's text (and,
for incidents, the RCA finding), it deterministically matches a catalog entry, LLM-extracts the
entry's parameters, asks the policy engine whether to auto-run or require approval, then
dispatches the target via the existing machinery (workflow / action / agent). Fail-safe: any
failure returns a status dict, never raises into the caller.

Gated vs auto is a single flag on the workflow run context (``auto_approved``): the workflow's
own approval node waits for a human when it's false (lands in the Approvals inbox) and
auto-resolves when it's true. One workflow serves both paths.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from services.fulfillment import catalog as cat
from services.fulfillment import policy as pol

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _flatten(content: Any) -> str:
    """Reasoning models return a list of blocks; keep only text."""
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content if isinstance(content, str) else str(content or "")


def extract_params(entry: cat.FulfillmentEntry, text: str, extra: Optional[dict] = None) -> Dict[str, Any]:
    """LLM-extract the entry's declared params from the ticket text. Returns {} on any failure
    (the workflow/approval summary then shows blanks for a human to fill)."""
    if not entry.params:
        return {}
    try:
        from chat.backend.agent.providers import create_chat_model
        from chat.backend.agent.llm import ModelConfig
        from utils.observability import tracing

        llm = create_chat_model(ModelConfig.MAIN_MODEL, temperature=0)
        prompt = (
            "You extract structured parameters for an automation. Return STRICT JSON only, with "
            f"exactly these keys: {list(entry.params)}. Use null for anything not present. "
            f"Do not invent values.\n\nRequest:\n{text}\n\nContext: {json.dumps(extra or {}, default=str)[:1500]}"
        )
        cfg: Dict[str, Any] = {}
        h = tracing.langchain_handler()
        if h:
            cfg["callbacks"] = [h]
        resp = llm.invoke(prompt, config=cfg or None)
        raw = _flatten(getattr(resp, "content", resp))
        m = _JSON_RE.search(raw)
        parsed = json.loads(m.group(0)) if m else {}
        return {k: v for k, v in parsed.items() if k in entry.params and v not in (None, "")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Fulfillment] param extraction failed for %s: %s", entry.key, exc)
        return {}


def _dispatch(entry: cat.FulfillmentEntry, *, user_id: str, org_id: str,
              incident_id: Optional[str], ticket_number: Optional[str],
              params: Dict[str, Any], auto: bool) -> Dict[str, Any]:
    """Run the entry's target. Workflows carry auto_approved so the approval node gates or not."""
    if entry.target_type == "workflow":
        from services.workflows.defs import get_def
        from workflows_v2.client import start_run
        d = get_def(user_id, org_id, entry.target_ref)
        if not d:
            return {"status": "error", "error": f"workflow {entry.target_ref!r} not found for org"}
        context = {
            "user_id": user_id, "org_id": org_id, "incident_id": incident_id,
            "ticket_number": ticket_number, "auto_approved": bool(auto), **params,
        }
        res = start_run(d["graph"], context)
        return {"status": "dispatched" if res.get("ok") else "error",
                "target": f"workflow:{entry.target_ref}", "run": res}

    if entry.target_type == "action":
        from services.actions.executor import dispatch_action
        dispatch_action(entry.target_ref, user_id,
                        {"source": "fulfillment", "incident_id": incident_id, "params": params})
        return {"status": "dispatched", "target": f"action:{entry.target_ref}"}

    if entry.target_type == "agent":
        from chat.background.task import create_background_chat_session, run_background_chat
        sid = create_background_chat_session(user_id=user_id, title=f"fulfillment: {entry.key}",
                                             trigger_metadata={"source": "fulfillment", "entry": entry.key})
        run_background_chat.delay(
            user_id=user_id, session_id=sid,
            initial_message=f"{entry.description}\nParameters: {json.dumps(params, default=str)}",
            trigger_metadata={"source": "fulfillment", "entry": entry.key},
            mode="ask" if entry.read_only else "agent", incident_id=incident_id,
        )
        return {"status": "dispatched", "target": f"agent:{entry.target_ref}", "session_id": sid}

    return {"status": "error", "error": f"unknown target_type {entry.target_type!r}"}


def plan_and_dispatch(
    *, intent: str, text: str, user_id: str, org_id: str,
    category: Optional[str] = None, incident_id: Optional[str] = None,
    ticket_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Match a ticket to a catalog entry, fill params, apply policy, and dispatch. Fail-safe."""
    try:
        entry = cat.match_entry(intent, category=category, text=text, catalog=cat.get_catalog(user_id, org_id))
        if entry is None:
            logger.info("[Fulfillment] no catalog match (intent=%s); leaving for human", intent)
            return {"status": "no_match", "intent": intent}

        params = extract_params(entry, text, {"incident_id": incident_id, "ticket_number": ticket_number})

        decision = pol.decide(entry, org_id)
        if decision == pol.AUTO:
            ok, reason = pol.safety_gate(entry, params)
            if not ok:
                decision = pol.APPROVAL
                logger.info("[Fulfillment] safety gate forced approval for %s: %s", entry.key, reason)

        auto = decision == pol.AUTO
        result = _dispatch(entry, user_id=user_id, org_id=org_id, incident_id=incident_id,
                           ticket_number=ticket_number, params=params, auto=auto)
        result.update({"entry": entry.key, "title": entry.title, "intent": intent,
                       "decision": decision, "risk_class": entry.risk_class, "params": params})
        logger.info("[Fulfillment] %s -> %s (%s) decision=%s", intent, entry.key, entry.target_ref, decision)
        return result
    except Exception as exc:  # noqa: BLE001 - fulfillment must never break the caller
        logger.exception("[Fulfillment] plan_and_dispatch failed")
        return {"status": "error", "error": str(exc)[:200], "intent": intent}
