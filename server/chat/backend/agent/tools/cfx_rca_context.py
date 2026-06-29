"""Shared helpers for loading CFX enriched join documents into RCA and chat.

The cfx_rca ingest pipeline writes JSON under CFX_RCA_OUTPUT_DIR. This module
resolves ServiceNow ticket numbers / CFX incident ids to those documents and
formats them for automatic RCA prompt injection or agent tool responses.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_TICKET_NUMBER_RE = re.compile(r"(?i)\b((?:IT#?|INC#?|REQ#?|RITM#?|CS#?)?\d{6,})\b")
_CFX_ID_RE = re.compile(r"(?i)\b(CFX[0-9a-f]{10,})\b")


def output_dir() -> Path:
    return Path(os.getenv("CFX_RCA_OUTPUT_DIR", "/app/data/cfx_rca"))


def is_cfx_rca_store_available() -> bool:
    """True when the enriched incident store has been populated at least once."""
    index_path = output_dir() / "index.json"
    if not index_path.exists():
        return False
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return bool(data)
    except Exception:
        return False


def is_cloudfabrix_connected(user_id: str | None = None) -> bool:
    """True when per-user connector credentials or legacy CFX_* env vars are configured."""
    try:
        from routes.cloudfabrix.cfx_client import load_client_for_user, load_client_from_env

        if user_id and load_client_for_user(user_id):
            return True
        return load_client_from_env() is not None
    except Exception:
        return bool((os.getenv("CFX_API_BASE") or "").strip() and (os.getenv("CFX_API_TOKEN") or "").strip())


def normalize_ticket_number(ticket_number: str) -> str:
    value = (ticket_number or "").strip()
    if not value:
        return ""
    match = _TICKET_NUMBER_RE.search(value)
    if not match:
        return value.upper()
    token = match.group(1).upper()
    # Preserve IT# style when hash present in source
    if "#" in value and not token.startswith("IT#") and token.startswith("IT"):
        return "IT#" + token[2:]
    return token


def extract_ticket_number(text: str) -> str:
    if not text:
        return ""
    match = _TICKET_NUMBER_RE.search(text)
    if not match:
        return ""
    raw = match.group(1)
    if "#" in text.upper() and raw.upper().startswith("IT") and "#" not in raw:
        return normalize_ticket_number("IT#" + raw[2:])
    return normalize_ticket_number(raw)


def extract_cfx_incident_id(text: str) -> str:
    if not text:
        return ""
    match = _CFX_ID_RE.search(text)
    return match.group(1) if match else ""


def _ticket_lookup_variants(ticket_number: str) -> list[str]:
    base = normalize_ticket_number(ticket_number)
    if not base:
        return []
    variants = {base, base.upper(), base.lower()}
    digits = re.sub(r"\D", "", base)
    if digits:
        variants.add(f"IT#{digits}")
        variants.add(f"IT{digits}")
        variants.add(f"INC{digits}")
        variants.add(digits)
    return [v for v in variants if v]


def _load_index() -> dict[str, Any]:
    path = output_dir() / "index.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_join_index() -> dict[str, list[str]]:
    path = output_dir() / "join_index.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_incident_id(
    *,
    cfx_incident_id: str = "",
    ticket_number: str = "",
) -> str:
    cfx_id = (cfx_incident_id or "").strip()
    if cfx_id:
        return cfx_id
    ticket = normalize_ticket_number(ticket_number)
    if not ticket:
        return ""
    join = _load_join_index()
    for variant in _ticket_lookup_variants(ticket):
        for key in (f"snow_ticket_number::{variant}", f"snow_ticket_number::{variant.upper()}"):
            hits = join.get(key) or []
            if hits:
                return hits[0]
    index = _load_index()
    for inc_id, meta in index.items():
        stored = (meta.get("snow_ticket_number") or "").strip()
        if stored and stored in _ticket_lookup_variants(ticket):
            return inc_id
        if stored and normalize_ticket_number(stored) == ticket:
            return inc_id
    return ""


def load_enriched_doc(
    *,
    cfx_incident_id: str = "",
    ticket_number: str = "",
) -> dict[str, Any] | None:
    inc_id = resolve_incident_id(
        cfx_incident_id=cfx_incident_id,
        ticket_number=ticket_number,
    )
    if not inc_id:
        return None
    index = _load_index()
    meta = index.get(inc_id)
    if meta and meta.get("file"):
        path = output_dir() / meta["file"]
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    direct = output_dir() / "incidents" / f"{inc_id}.json"
    if direct.exists():
        try:
            return json.loads(direct.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def extract_lookup_from_payload(payload: dict[str, Any], title: str = "") -> tuple[str, str]:
    """Return (ticket_number, cfx_incident_id) found in an RCA/chat payload."""
    ticket = ""
    cfx_id = ""
    if not isinstance(payload, dict):
        return ticket, cfx_id

    for key in ("snow_ticket_number", "ticket_number", "snow_number"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            ticket = normalize_ticket_number(val)
            break

    snow = payload.get("snow")
    if not ticket and isinstance(snow, dict):
        val = snow.get("ticket_number")
        if isinstance(val, str) and val.strip():
            ticket = normalize_ticket_number(val)

    metadata = payload.get("metadata")
    if not ticket and isinstance(metadata, dict):
        for key in ("snow_number", "snow_ticket_number", "ticket_number"):
            val = metadata.get(key)
            if isinstance(val, str) and val.strip():
                ticket = normalize_ticket_number(val)
                break

    if not ticket:
        for key in ("description", "issue_description", "message", "user_description"):
            val = payload.get(key)
            if isinstance(val, str):
                ticket = extract_ticket_number(val)
                if ticket:
                    break

    if not ticket and title:
        ticket = extract_ticket_number(title)

    for key in ("cfx_incident_id",):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            cfx_id = val.strip()
            break

    incident = payload.get("incident")
    if not cfx_id and isinstance(incident, dict):
        val = incident.get("cfx_incident_id")
        if isinstance(val, str) and val.strip():
            cfx_id = val.strip()

    if not cfx_id:
        blob = json.dumps(payload, default=str)
        cfx_id = extract_cfx_incident_id(blob)

    return ticket, cfx_id


def _format_dependents(topology: dict[str, Any], limit: int = 25) -> str:
    deps = topology.get("dependents") or []
    if not isinstance(deps, list) or not deps:
        return "  (none resolved)"
    lines: list[str] = []
    for dep in deps[:limit]:
        if not isinstance(dep, dict):
            continue
        label = dep.get("label") or dep.get("node_id") or "?"
        node_type = dep.get("node_type") or "?"
        relation = dep.get("relation_type") or dep.get("direction") or "?"
        depth = dep.get("depth", "?")
        lines.append(f"  - {label} ({node_type}) relation={relation} depth={depth}")
    if len(deps) > limit:
        lines.append(f"  ... and {len(deps) - limit} more")
    return "\n".join(lines) if lines else "  (none resolved)"


def format_cfx_context_for_rca(doc: dict[str, Any]) -> str:
    """Format enriched document as an RCA prompt section."""
    incident = doc.get("incident") or {}
    snow = doc.get("snow") or {}
    topology = doc.get("topology") or {}
    agent_ctx = doc.get("agent_context") or {}
    assets = doc.get("affected_assets") or []

    asset_names = []
    for asset in assets[:8]:
        if isinstance(asset, dict):
            asset_names.append(
                asset.get("name") or asset.get("ci_name") or asset.get("ip") or "?"
            )

    matched = topology.get("matched_nodes") or []
    matched_labels = []
    for node in matched[:8]:
        if isinstance(node, dict):
            matched_labels.append(node.get("label") or node.get("node_id") or "?")

    lines = [
        "## CFX ENRICHED INCIDENT DATA (pre-loaded from local join store)",
        "",
        "Use this block as authoritative context for ServiceNow linkage, affected assets,",
        "and topology dependents. You may still call get_cfx_enriched_incident for the",
        "full JSON, but do not ignore this pre-loaded summary.",
        "",
        f"CFX incident: {incident.get('cfx_incident_id', 'n/a')}",
        f"Severity: {incident.get('severity', 'n/a')} | Status: {incident.get('status', 'n/a')}",
        f"Type: {incident.get('incident_type', 'n/a')} | Summary: {incident.get('summary', 'n/a')}",
        f"Alert count: {incident.get('alert_count', 'n/a')} | Sources: {', '.join(incident.get('alert_sources') or []) or 'n/a'}",
        "",
        f"ServiceNow ticket: {snow.get('ticket_number') or 'not linked'}",
        f"SNOW status: {snow.get('ticket_status') or 'n/a'} | CI sys_id: {snow.get('ci_sys_id') or 'n/a'}",
        f"SNOW URL: {snow.get('url') or 'n/a'}",
        "",
        f"Primary affected assets: {', '.join(asset_names) or 'unknown'}",
        f"Topology matched nodes: {', '.join(matched_labels) or 'none'}",
        f"Impacted layers: {', '.join(topology.get('impacted_layers') or []) or 'n/a'}",
        "",
        "Topology dependents:",
        _format_dependents(topology),
        "",
    ]

    rca_seed = agent_ctx.get("rca_seed")
    if isinstance(rca_seed, str) and rca_seed.strip():
        lines.extend(["### RCA seed", rca_seed.strip(), ""])

    correlation = doc.get("correlation") or {}
    if correlation:
        lines.extend([
            "### Correlation",
            json.dumps(correlation, ensure_ascii=False, default=str)[:2000],
            "",
        ])

    return "\n".join(lines)


def build_cfx_payload_supplement(doc: dict[str, Any]) -> dict[str, Any]:
    """Compact dict merged into RCA webhook/chat payload for serialization."""
    incident = doc.get("incident") or {}
    snow = doc.get("snow") or {}
    return {
        "cfx_enriched": True,
        "cfx_incident_id": incident.get("cfx_incident_id"),
        "snow_ticket_number": snow.get("ticket_number"),
        "snow": snow,
        "affected_assets": doc.get("affected_assets"),
        "topology": {
            "matched_nodes": (doc.get("topology") or {}).get("matched_nodes"),
            "dependents": (doc.get("topology") or {}).get("dependents"),
            "impacted_layers": (doc.get("topology") or {}).get("impacted_layers"),
            "resolved": (doc.get("topology") or {}).get("resolved"),
        },
        "correlation": doc.get("correlation"),
        "agent_context": doc.get("agent_context"),
        "cfx_context_summary": format_cfx_context_for_rca(doc)[:12000],
    }


def get_cfx_rca_prompt_section(payload: dict[str, Any], title: str = "") -> str:
    """Load enriched doc from payload/title hints and return prompt text, or empty."""
    if not is_cfx_rca_store_available():
        return ""
    ticket, cfx_id = extract_lookup_from_payload(payload, title=title)
    if not ticket and not cfx_id:
        return ""
    doc = load_enriched_doc(cfx_incident_id=cfx_id, ticket_number=ticket)
    if not doc:
        return ""
    return format_cfx_context_for_rca(doc)


def build_chat_cfx_instruction(question: str) -> str:
    """Return a chat prefix instructing the agent to use CFX enriched data."""
    if not is_cfx_rca_store_available():
        return ""
    ticket = extract_ticket_number(question)
    cfx_id = extract_cfx_incident_id(question)
    if not ticket and not cfx_id:
        return ""
    lookup = ticket or cfx_id
    return (
        "[CFX ENRICHED DATA AVAILABLE]\n"
        f"Detected reference: {lookup}. For RCA, topology, or ServiceNow linkage questions, "
        "you MUST call get_cfx_enriched_incident FIRST "
        f"(ticket_number={ticket!r}, cfx_incident_id={cfx_id!r}) "
        "to load the pre-built CFX+ServiceNow+topology join document from the local store. "
        "Use topology.dependents, agent_context.rca_seed, and correlation in your analysis. "
        "Only fall back to live ServiceNow API calls if the enriched doc is missing fields.\n\n"
    )
