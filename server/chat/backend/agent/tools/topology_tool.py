"""Topology-graph write tools (Memgraph).

Lets a topology-curator agent keep the network/service topology graph current by upserting
Service nodes and dependency edges. Background/workflow execution only.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TopologyUpsertServiceArgs(BaseModel):
    name: str = Field(description="Unique service/node name (e.g. host, VM, app, or cluster).")
    resource_type: str = Field(description="Type, e.g. 'vm', 'host', 'service', 'database', 'firewall'.")
    provider: str = Field(default="onprem", description="Provider/source, e.g. 'onprem', 'aws', 'azure', 'vmware'.")
    region: str = Field(default="", description="Region/site (optional).")
    endpoint: str = Field(default="", description="Address/endpoint (optional).")
    criticality: str = Field(default="", description="Criticality, e.g. 'high'|'medium'|'low' (optional).")


class TopologyAddDependencyArgs(BaseModel):
    from_service: str = Field(description="Dependent service name (the one that depends on the other).")
    to_service: str = Field(description="Depended-upon service name.")
    dep_type: str = Field(default="depends_on", description="Dependency type, e.g. 'depends_on', 'connects_to', 'routes_through'.")


def _memgraph():
    from services.graph.memgraph_client import get_memgraph_client
    return get_memgraph_client()


def topology_upsert_service(name: str, resource_type: str, provider: str = "onprem",
                            region: str = "", endpoint: str = "", criticality: str = "",
                            user_id: Optional[str] = None) -> str:
    if not user_id:
        return json.dumps({"ok": False, "error": "User context not available"})
    if not (name or "").strip() or not (resource_type or "").strip():
        return json.dumps({"ok": False, "error": "name and resource_type are required"})
    try:
        _memgraph().upsert_service(
            user_id=user_id, name=name, resource_type=resource_type, provider=provider or "onprem",
            region=region or "", endpoint=endpoint or "", criticality=criticality or "",
            discovered_from="topology_agent",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[Topology] upsert_service failed: %s", exc)
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "service": name})


def topology_add_dependency(from_service: str, to_service: str, dep_type: str = "depends_on",
                            user_id: Optional[str] = None) -> str:
    if not user_id:
        return json.dumps({"ok": False, "error": "User context not available"})
    if not (from_service or "").strip() or not (to_service or "").strip():
        return json.dumps({"ok": False, "error": "from_service and to_service are required"})
    try:
        _memgraph().upsert_dependency(
            user_id=user_id, from_service=from_service, to_service=to_service,
            dep_type=dep_type or "depends_on", confidence=1.0, discovered_from="topology_agent",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[Topology] upsert_dependency failed: %s", exc)
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "edge": f"{from_service} -{dep_type}-> {to_service}"})
