"""Read-only Zabbix agent tool.

Exposes Zabbix monitoring state to the agent for investigation: hosts, active problems,
firing triggers, and item latest-values. Read-only.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from connectors.zabbix_connector.client import ZabbixClient, ZabbixAPIError
from utils.auth.token_management import get_token_data

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 12000
_RESOURCES = {"hosts", "problems", "triggers", "items", "hostgroups"}


class QueryZabbixArgs(BaseModel):
    resource_type: str = Field(
        description="One of: 'hosts', 'problems', 'triggers', 'items', 'hostgroups'.",
    )
    limit: int = Field(default=100, description="Max items to return (1-500).")


def _stored(user_id: str) -> Optional[dict]:
    data = get_token_data(user_id, "zabbix")
    if data and data.get("base_url") and (data.get("api_token") or (data.get("username") and data.get("password"))):
        return data
    return None


def is_zabbix_connected(user_id: str) -> bool:
    return _stored(user_id) is not None


def _client(data: dict) -> ZabbixClient:
    return ZabbixClient(
        base_url=data["base_url"],
        api_token=data.get("api_token"),
        username=data.get("username"),
        password=data.get("password"),
        verify_ssl=bool(data.get("verify_ssl", True)),
    )


def query_zabbix(resource_type: str, limit: int = 100, user_id: Optional[str] = None) -> str:
    if not user_id:
        return json.dumps({"error": "User context not available"})
    data = _stored(user_id)
    if not data:
        return json.dumps({"error": "Zabbix not connected. Please connect Zabbix first."})

    rt = (resource_type or "").strip().lower()
    if rt not in _RESOURCES:
        return json.dumps({"error": f"Invalid resource_type '{resource_type}'. Must be one of: {', '.join(sorted(_RESOURCES))}"})

    limit = max(1, min(int(limit or 100), 500))
    client = _client(data)
    try:
        if rt == "hosts":
            result = {"hosts": client.get_hosts(limit=limit)}
        elif rt == "problems":
            result = {"problems": client.get_problems(limit=limit)}
        elif rt == "triggers":
            result = {"triggers": client.get_triggers(limit=limit)}
        elif rt == "items":
            result = {"items": client.get_items(limit=limit)}
        else:  # hostgroups
            result = {"hostgroups": client.get_hostgroups(limit=limit)}
    except ZabbixAPIError as exc:
        return json.dumps({"error": str(exc)})

    out = json.dumps(result, default=str)
    if len(out) > _MAX_OUTPUT:
        out = out[:_MAX_OUTPUT] + '... (truncated; lower limit)"}'
    return out
