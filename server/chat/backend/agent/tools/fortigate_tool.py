"""Read-only FortiGate agent tool.

Exposes FortiGate firewall configuration/state to the agent for investigation (policies,
address objects, service objects, interfaces, system status). This tool never mutates
config — firewall changes go through the approval-gated open-firewall-port workflow.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from connectors.fortigate_connector.client import FortiGateClient, FortiGateAPIError
from utils.auth.token_management import get_token_data

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 12000

_RESOURCES = {"status", "policies", "addresses", "services", "interfaces"}


class QueryFortiGateArgs(BaseModel):
    resource_type: str = Field(
        description="One of: 'status', 'policies', 'addresses', 'services', 'interfaces'.",
    )
    limit: int = Field(default=100, description="Max items to return (1-500).")


class FortiGateOpenPortArgs(BaseModel):
    protocol: str = Field(description="Protocol to allow: 'TCP', 'UDP', or 'SCTP'.")
    port: str = Field(description="Port or range, e.g. '443' or '8000-8100'.")
    dstaddr: str = Field(description="Destination: an existing FortiGate address object name, or an IP/subnet (e.g. '10.0.0.5' or '10.0.0.0/24') which will be created as an address object.")
    srcintf: str = Field(description="Source interface name (e.g. 'wan1', 'port1').")
    dstintf: str = Field(description="Destination interface name (e.g. 'port2').")
    srcaddr: str = Field(default="all", description="Source address object name (default 'all').")
    nat: bool = Field(default=False, description="Enable source NAT on the policy.")
    policy_name: Optional[str] = Field(default=None, description="Optional policy name; auto-generated if omitted.")
    comment: str = Field(default="", description="Optional comment recorded on the policy.")


def _stored(user_id: str) -> Optional[dict]:
    data = get_token_data(user_id, "fortigate")
    if data and data.get("base_url") and data.get("api_token"):
        return data
    return None


def is_fortigate_connected(user_id: str) -> bool:
    return _stored(user_id) is not None


def _client(data: dict) -> FortiGateClient:
    return FortiGateClient(
        base_url=data["base_url"],
        api_token=data["api_token"],
        vdom=data.get("vdom"),
        verify_ssl=bool(data.get("verify_ssl", True)),
        auth_in_query=bool(data.get("auth_in_query", False)),
    )


def query_fortigate(resource_type: str, limit: int = 100, user_id: Optional[str] = None) -> str:
    if not user_id:
        return json.dumps({"error": "User context not available"})
    data = _stored(user_id)
    if not data:
        return json.dumps({"error": "FortiGate not connected. Please connect FortiGate first."})

    rt = (resource_type or "").strip().lower()
    if rt not in _RESOURCES:
        return json.dumps({"error": f"Invalid resource_type '{resource_type}'. Must be one of: {', '.join(sorted(_RESOURCES))}"})

    limit = max(1, min(int(limit or 100), 500))
    client = _client(data)
    try:
        if rt == "status":
            payload = client.get_system_status()
            result = {
                "version": client.detected_version,
                "hostname": client.hostname,
                "serial": client.serial,
                "results": payload.get("results"),
            }
        elif rt == "policies":
            result = {"policies": client.list_firewall_policies(limit=limit)}
        elif rt == "addresses":
            result = {"addresses": client.list_addresses(limit=limit)}
        elif rt == "services":
            result = {"services": client.list_services(limit=limit)}
        else:  # interfaces
            result = {"interfaces": client.list_interfaces(limit=limit)}
    except FortiGateAPIError as exc:
        return json.dumps({"error": str(exc)})

    out = json.dumps(result, default=str)
    if len(out) > _MAX_OUTPUT:
        out = out[:_MAX_OUTPUT] + '... (truncated; narrow the query or lower limit)"}'
    return out


def _looks_like_ip(value: str) -> bool:
    parts = (value or "").split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def fortigate_open_port(
    protocol: str,
    port: str,
    dstaddr: str,
    srcintf: str,
    dstintf: str,
    srcaddr: str = "all",
    nat: bool = False,
    policy_name: Optional[str] = None,
    comment: str = "",
    user_id: Optional[str] = None,
) -> str:
    """Open a firewall port: create the service object (+ address object if needed) and an
    allow policy. Intended for the approval-gated open-firewall-port workflow only — this
    tool is registered exclusively in background/workflow execution, never in interactive chat.
    """
    if not user_id:
        return json.dumps({"ok": False, "error": "User context not available"})
    data = _stored(user_id)
    if not data:
        return json.dumps({"ok": False, "error": "FortiGate not connected"})

    proto = (protocol or "TCP").upper()
    if proto not in ("TCP", "UDP", "SCTP"):
        return json.dumps({"ok": False, "error": f"Invalid protocol '{protocol}' (use TCP/UDP/SCTP)"})

    client = _client(data)
    safe_port = str(port).replace(":", "-").replace("/", "-")
    svc_name = f"aurora-{proto.lower()}-{safe_port}"
    steps = []

    # 1. Custom service object for the port range (tolerate "already exists").
    try:
        client.create_service_object(svc_name, proto, str(port))
        steps.append(f"created service object {svc_name}")
    except FortiGateAPIError as exc:
        steps.append(f"service object {svc_name}: {exc} (continuing — may already exist)")

    # 2. Address object if the destination is an IP/subnet rather than an existing object name.
    dst_name = dstaddr
    if "/" in dstaddr or _looks_like_ip(dstaddr):
        subnet = dstaddr if "/" in dstaddr else f"{dstaddr}/32"
        dst_name = "aurora-" + subnet.replace("/", "_").replace(".", "-")
        try:
            client.create_address_object(dst_name, subnet)
            steps.append(f"created address object {dst_name} ({subnet})")
        except FortiGateAPIError as exc:
            steps.append(f"address object {dst_name}: {exc} (continuing — may already exist)")

    # 3. The allow policy wiring it together.
    name = policy_name or f"aurora-open-{svc_name}"
    try:
        res = client.create_firewall_policy(
            name=name, srcintf=srcintf, dstintf=dstintf, srcaddr=srcaddr,
            dstaddr=dst_name, service=svc_name, nat=nat,
            comment=comment or "Opened via Aurora approval workflow",
        )
    except FortiGateAPIError as exc:
        return json.dumps({"ok": False, "steps": steps, "error": f"policy create failed: {exc}"})

    steps.append(f"created firewall policy '{name}'")
    return json.dumps({
        "ok": True,
        "policy": name,
        "service": svc_name,
        "dstaddr": dst_name,
        "mkey": res.get("mkey") if isinstance(res, dict) else None,
        "steps": steps,
    })
