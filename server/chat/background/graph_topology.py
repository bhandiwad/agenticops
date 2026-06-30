"""Build incident topology from the discovered Memgraph infrastructure graph.

This is the *trusted* base for the incident visualization: real services + dependencies
discovered from connected providers (provenance="discovered"), scoped to the incident's
affected entity + its 1-hop neighbors. The LLM only annotates this; it does not invent it.
Returns None when the graph has nothing for the entity (caller falls back to LLM-only).
"""

import logging
import re
from typing import Optional

from chat.background.visualization_extractor import VisualizationData, InfraNode, InfraEdge

logger = logging.getLogger(__name__)


def _nid(name: str) -> str:
    return ("g-" + re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").lower()).strip("-"))[:44] or "g-node"


def _label(name: str) -> str:
    name = name or ""
    return name if len(name) <= 22 else "…" + name[-21:]


def _resolve_seed(client, user_id: str, affected: str):
    if not affected:
        return None
    for finder in ("get_service", "find_service_by_endpoint", "find_service_by_cloud_id"):
        try:
            fn = getattr(client, finder, None)
            s = fn(user_id, affected) if fn else None
            if s:
                return s
        except Exception:  # noqa: BLE001
            pass
    # Fuzzy substring match against discovered service names.
    try:
        a = affected.lower()
        best = None
        for s in client.list_services(user_id):
            n = (s.get("name") or "").lower()
            if not n:
                continue
            if a == n:
                return s
            if a in n or n in a:
                best = best or s
        return best
    except Exception:  # noqa: BLE001
        return None


def build_topology_from_graph(user_id: str, affected_service: str, incident_id: str = "") -> Optional[VisualizationData]:
    """Return a discovered-topology VisualizationData for the incident, or None."""
    try:
        from services.graph.memgraph_client import get_memgraph_client
        client = get_memgraph_client()
    except Exception:  # noqa: BLE001
        logger.warning("[GraphViz] memgraph client unavailable", exc_info=True)
        return None

    try:
        seed = _resolve_seed(client, user_id, affected_service)
        if not seed or not seed.get("name"):
            return None
        name = seed["name"]
        seed_id = _nid(name)

        type_map = {}
        try:
            for s in client.list_services(user_id):
                if s.get("name"):
                    type_map[s["name"]] = s.get("resource_type") or "service"
        except Exception:  # noqa: BLE001
            pass

        deps = {}
        try:
            deps = client.get_dependencies(user_id, name, "both") or {}
        except Exception:  # noqa: BLE001
            pass

        nodes = {name: InfraNode(id=seed_id, label=_label(name), type=seed.get("resource_type") or "service",
                                 status="degraded", source="discovered", confidence=1.0)}
        edges = []

        for up in (deps.get("upstream") or []):
            n = up.get("name")
            if not n:
                continue
            nid = _nid(n)
            conf = float(up.get("confidence") or 0.9)
            nodes.setdefault(n, InfraNode(id=nid, label=_label(n), type=type_map.get(n, "service"),
                                          status="unknown", source="discovered", confidence=conf))
            edges.append(InfraEdge(source=seed_id, target=nid, type="dependency",
                                   label=up.get("dependency_type") or "depends on",
                                   provenance="discovered", confidence=conf))
        for dn in (deps.get("downstream") or []):
            n = dn.get("name")
            if not n:
                continue
            nid = _nid(n)
            conf = float(dn.get("confidence") or 0.9)
            nodes.setdefault(n, InfraNode(id=nid, label=_label(n), type=type_map.get(n, "service"),
                                          status="unknown", source="discovered", confidence=conf))
            edges.append(InfraEdge(source=nid, target=seed_id, type="dependency",
                                   label=dn.get("dependency_type") or "depends on",
                                   provenance="discovered", confidence=conf))

        logger.info("[GraphViz] built discovered topology for '%s' (incident %s): %d nodes, %d edges",
                    name, incident_id, len(nodes), len(edges))
        return VisualizationData(nodes=list(nodes.values()), edges=edges, affectedIds=[seed_id])
    except Exception:  # noqa: BLE001
        logger.warning("[GraphViz] build_topology_from_graph failed", exc_info=True)
        return None
