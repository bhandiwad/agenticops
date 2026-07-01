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
