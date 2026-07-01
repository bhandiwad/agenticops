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


def _cfx_topology_to_viz(doc: dict) -> Optional[VisualizationData]:
    """Build VisualizationData from a CloudFabrix enriched doc's topology block."""
    topo = (doc or {}).get("topology") or {}
    matched = topo.get("matched_nodes") or []
    dependents = topo.get("dependents") or []
    if not matched and not dependents:
        return None

    nodes = {}
    edges = []
    affected_ids = []

    def _key(n):
        return n.get("node_id") or n.get("node_key") or n.get("label") or ""

    for m in matched:
        k = _key(m)
        if not k:
            continue
        nid = _nid(k)
        nodes[k] = InfraNode(id=nid, label=_label(m.get("label") or k), type=(m.get("node_type") or "ci").lower(),
                             status="failed", source="cfx", confidence=1.0)
        affected_ids.append(nid)

    # Anchor dependents to the primary impacted CI (first matched node).
    anchor = affected_ids[0] if affected_ids else None
    for d in dependents:
        k = _key(d)
        if not k:
            continue
        nid = _nid(k)
        nodes.setdefault(k, InfraNode(id=nid, label=_label(d.get("label") or k), type=(d.get("node_type") or "ci").lower(),
                                      status="unknown", source="cfx", confidence=0.9))
        if anchor:
            inbound = (d.get("direction") or "").lower() == "inbound"
            src, tgt = (nid, anchor) if inbound else (anchor, nid)
            edges.append(InfraEdge(source=src, target=tgt, type="dependency",
                                   label=d.get("relation_type") or "connected-to",
                                   provenance="cfx", confidence=0.9))

    if not nodes:
        return None
    logger.info("[GraphViz] built CFX topology: %d nodes, %d edges", len(nodes), len(edges))
    return VisualizationData(nodes=list(nodes.values()), edges=edges, affectedIds=affected_ids)


def build_topology_from_cfx(incident_id: str, user_id: str) -> Optional[VisualizationData]:
    """Load the incident's CloudFabrix enriched doc (by ticket/CFX id parsed from the
    incident) and render its real topology. Returns None when no CFX topology is available."""
    try:
        from chat.backend.agent.tools.cfx_rca_context import (
            extract_ticket_number, extract_cfx_incident_id, load_enriched_doc,
        )
        from utils.db.connection_pool import db_pool
        from utils.auth.stateless_auth import set_rls_context
    except Exception:  # noqa: BLE001
        return None
    try:
        text = ""
        with db_pool.get_user_connection() as conn:
            cur = conn.cursor()
            set_rls_context(cur, conn, user_id, log_prefix="[GraphViz]")
            cur.execute("SELECT alert_title, alert_service FROM incidents WHERE id = %s", (incident_id,))
            row = cur.fetchone()
        if row:
            text = " ".join([str(x) for x in row if x])
        ticket = extract_ticket_number(text)
        cfx_id = extract_cfx_incident_id(text)
        if not (ticket or cfx_id):
            return None
        doc = load_enriched_doc(ticket_number=ticket, cfx_incident_id=cfx_id)
        if not doc:
            return None
        return _cfx_topology_to_viz(doc)
    except Exception:  # noqa: BLE001
        logger.warning("[GraphViz] build_topology_from_cfx failed", exc_info=True)
        return None


def build_topology_from_cmdb(incident_id: str, user_id: str) -> Optional[VisualizationData]:
    """Render topology from the ServiceNow CMDB (cmdb_ci + cmdb_rel_ci) for the incident's
    affected CI + its 1-hop relationships. Used where CloudFabrix isn't enabled. Returns None
    when ServiceNow isn't connected or the CI isn't found."""
    try:
        from utils.auth.token_management import get_token_data
        from routes.servicenow.snow_client import ServiceNowClient
        from utils.db.connection_pool import db_pool
        from utils.auth.stateless_auth import set_rls_context
    except Exception:  # noqa: BLE001
        return None
    try:
        data = get_token_data(user_id, "servicenow")
        if not data:
            return None
        client = ServiceNowClient.from_token_data(data)
        dv = ServiceNowClient.display_val

        with db_pool.get_user_connection() as conn:
            cur = conn.cursor()
            set_rls_context(cur, conn, user_id, log_prefix="[GraphViz]")
            cur.execute("SELECT alert_service, alert_title FROM incidents WHERE id = %s", (incident_id,))
            row = cur.fetchone()
        seed_name = ((row[0] or row[1] or "") if row else "").strip()
        if not seed_name:
            return None

        ci = client.get_ci_by_name(seed_name)
        if not ci:
            return None
        ci_sysid = str(dv(ci.get("sys_id")) or "")
        ci_name = str(dv(ci.get("name")) or seed_name)
        ci_type = str(dv(ci.get("sys_class_name")) or "ci").lower()
        seed_id = _nid(ci_name)

        nodes = {ci_name: InfraNode(id=seed_id, label=_label(ci_name), type=ci_type,
                                    status="failed", source="cmdb", confidence=1.0)}
        edges = []
        for rel in (client.get_ci_relationships(ci_sysid) if ci_sysid else []):
            parent = str(dv(rel.get("parent")) or "").strip()
            child = str(dv(rel.get("child")) or "").strip()
            rtype = str(dv(rel.get("type")) or "related")[:24]
            for other in (parent, child):
                if other and other not in nodes:
                    nodes[other] = InfraNode(id=_nid(other), label=_label(other), type="ci",
                                             status="unknown", source="cmdb", confidence=0.9)
            if parent and child:
                edges.append(InfraEdge(source=_nid(parent), target=_nid(child), type="dependency",
                                       label=rtype, provenance="cmdb", confidence=0.9))

        logger.info("[GraphViz] built CMDB topology for '%s' (incident %s): %d nodes, %d edges",
                    ci_name, incident_id, len(nodes), len(edges))
        return VisualizationData(nodes=list(nodes.values()), edges=edges, affectedIds=[seed_id])
    except Exception:  # noqa: BLE001
        logger.warning("[GraphViz] build_topology_from_cmdb failed", exc_info=True)
        return None


def build_topology_from_iac(user_id: str, affected_service: str, incident_id: str = "") -> Optional[VisualizationData]:
    """IaC (Terraform state) declared relationships. Honest connect-to-activate stub: this
    deployment has no per-environment Terraform *state* ingestion (the terraform tooling here
    provisions Aurora's own infra, not the user's), so there's nothing to read yet. Returns
    None until a TF-state source is wired; slots into the resolver so it lights up then."""
    try:
        from utils.auth.token_management import get_token_data
        state = get_token_data(user_id, "terraform_state")
    except Exception:  # noqa: BLE001
        state = None
    if not state:
        return None
    # (When TF-state ingestion exists, parse resources + depends_on/references into nodes/edges
    #  with source="iac", confidence high. Left unimplemented until that source is available.)
    return None


def build_topology_from_monitoring(user_id: str, affected_service: str, incident_id: str = "") -> Optional[VisualizationData]:
    """Observed service dependencies from Datadog APM (/api/v1/service_dependencies). Returns
    None when Datadog isn't connected. Edges are observed traffic (source='monitoring')."""
    if not affected_service:
        return None
    try:
        from utils.auth.token_management import get_token_data
        from routes.datadog.datadog_routes import DatadogClient
        import requests
    except Exception:  # noqa: BLE001
        return None
    try:
        creds = get_token_data(user_id, "datadog")
        if not creds:
            return None
        client = DatadogClient(creds.get("api_key", ""), creds.get("app_key", ""), creds.get("site"))
        resp = requests.get(
            f"{client.base_url}/api/v1/service_dependencies",
            headers={"DD-API-KEY": client.api_key, "DD-APPLICATION-KEY": client.app_key},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        deps = resp.json() or {}
        svc = next((k for k in deps if k.lower() == affected_service.lower()
                    or affected_service.lower() in k.lower()), None)
        if not svc:
            return None
        seed_id = _nid(svc)
        nodes = {svc: InfraNode(id=seed_id, label=_label(svc), type="service", status="degraded",
                                source="monitoring", confidence=0.85)}
        edges = []
        for callee in (deps.get(svc, {}).get("calls") or [])[:20]:
            nid = _nid(callee)
            nodes.setdefault(callee, InfraNode(id=nid, label=_label(callee), type="service",
                                               status="unknown", source="monitoring", confidence=0.85))
            edges.append(InfraEdge(source=seed_id, target=nid, type="communication",
                                   label="calls", provenance="monitoring", confidence=0.85))
        logger.info("[GraphViz] built monitoring topology for '%s': %d nodes", svc, len(nodes))
        return VisualizationData(nodes=list(nodes.values()), edges=edges, affectedIds=[seed_id])
    except Exception:  # noqa: BLE001
        logger.warning("[GraphViz] build_topology_from_monitoring failed", exc_info=True)
        return None


def build_topology_from_kb(user_id: str, affected_service: str, incident_id: str = "") -> Optional[VisualizationData]:
    """KB-derived, GROUNDED topology: search the Knowledge Base for the affected service, then
    link only to entities that (a) appear in those docs AND (b) already exist as discovered
    services — so it never invents entities. Edges are marked source='inferred' (dashed)."""
    if not affected_service:
        return None
    try:
        from routes.knowledge_base.weaviate_client import search_knowledge_base
        from services.graph.memgraph_client import get_memgraph_client
    except Exception:  # noqa: BLE001
        return None
    try:
        results = search_knowledge_base(user_id, f"{affected_service} dependencies architecture related services", limit=6)
        if not results:
            return None
        text = " ".join((r.get("content") or "") for r in results).lower()
        related = []
        try:
            for s in get_memgraph_client().list_services(user_id):
                n = s.get("name") or ""
                if n and n.lower() != affected_service.lower() and len(n) > 2 and n.lower() in text:
                    related.append(n)
        except Exception:  # noqa: BLE001
            pass
        related = related[:12]
        if not related:
            return None
        seed_id = _nid(affected_service)
        nodes = {affected_service: InfraNode(id=seed_id, label=_label(affected_service), type="service",
                                             status="degraded", source="inferred", confidence=0.4)}
        edges = []
        for n in related:
            nid = _nid(n)
            nodes.setdefault(n, InfraNode(id=nid, label=_label(n), type="service", status="unknown",
                                          source="inferred", confidence=0.4))
            edges.append(InfraEdge(source=seed_id, target=nid, type="dependency",
                                   label="referenced in docs", provenance="inferred", confidence=0.4))
        logger.info("[GraphViz] built KB-grounded topology for '%s': %d related", affected_service, len(related))
        return VisualizationData(nodes=list(nodes.values()), edges=edges, affectedIds=[seed_id])
    except Exception:  # noqa: BLE001
        logger.warning("[GraphViz] build_topology_from_kb failed", exc_info=True)
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
