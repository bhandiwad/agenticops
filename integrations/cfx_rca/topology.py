"""Topology graph sync, asset resolution, and dependency traversal.

Pulls nodes and edges from the CFX topology graph (read-only, paged) into a
local index. Given an affected asset (IP / CI name), resolves the matching
graph node(s) and walks edges to find dependents (impact blast radius) for RCA
and postmortem.

The index is cached to disk so repeated incident enrichment in a run does not
re-fetch the graph. The same index is reused identically by future webhook
ingestion.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .cfx_client import CfxClient
from .config import CfxConfig
from .models import (
    AffectedAsset,
    TopologyDependent,
    TopologyNodeRef,
    TopologyView,
    _clean,
)

logger = logging.getLogger("cfx_rca.topology")

# Candidate node fields that may carry an IP / identifier / label / type.
_NODE_IP_FIELDS = ("host_os_ip", "ip", "ip_address", "management_ip", "asset_ip", "node_ip")
_NODE_NAME_FIELDS = ("node_label", "label", "name", "hostname", "asset_name", "ci_name", "shortname")
_NODE_TYPE_FIELDS = ("node_type", "type", "asset_type")
_NODE_LAYER_FIELDS = ("layer", "layer_id", "layer_name")
_NODE_ID_FIELDS = ("_id", "id", "node_id", "_key")

_EDGE_FROM_FIELDS = ("_from", "from", "source", "left_id", "left_node")
_EDGE_TO_FIELDS = ("_to", "to", "target", "right_id", "right_node")
_EDGE_FROM_LABEL = ("left_label", "from_label", "source_label")
_EDGE_TO_LABEL = ("right_label", "to_label", "target_label")
_EDGE_REL_FIELDS = ("relation_type", "relation", "rel_type", "edge_type", "label")


def _pick(d: dict[str, Any], fields: tuple[str, ...]) -> Any:
    for f in fields:
        if f in d:
            v = _clean(d.get(f))
            if v is not None:
                return v
    return None


def _norm(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


class TopologyIndex:
    """In-memory graph index with IP/name lookup and neighbor traversal."""

    def __init__(self, graph_name: str, db_name: str) -> None:
        self.graph_name = graph_name
        self.db_name = db_name
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._by_ip: dict[str, list[dict[str, Any]]] = {}
        self._by_name: dict[str, list[dict[str, Any]]] = {}
        self._adj: dict[str, list[dict[str, Any]]] = {}
        self.truncated = False

    # -- building ----------------------------------------------------------
    def add_nodes(self, nodes: list[dict[str, Any]]) -> None:
        for n in nodes:
            self.nodes.append(n)
            nid = _pick(n, _NODE_ID_FIELDS)
            if nid is not None:
                self._by_id[str(nid)] = n
            ip = _pick(n, _NODE_IP_FIELDS)
            if ip:
                self._by_ip.setdefault(_norm(ip), []).append(n)
            # node_id often embeds the IP, e.g. _100.64.219.183_abrtd
            for f in _NODE_ID_FIELDS:
                raw = _clean(n.get(f))
                if raw:
                    self._index_embedded_ip(str(raw), n)
            name = _pick(n, _NODE_NAME_FIELDS)
            if name:
                self._by_name.setdefault(_norm(name), []).append(n)

    def _index_embedded_ip(self, raw: str, node: dict[str, Any]) -> None:
        import re

        for m in re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", raw):
            self._by_ip.setdefault(_norm(m), []).append(node)

    def add_edges(self, edges: list[dict[str, Any]]) -> None:
        for e in edges:
            self.edges.append(e)
            frm = _pick(e, _EDGE_FROM_FIELDS) or _pick(e, _EDGE_FROM_LABEL)
            to = _pick(e, _EDGE_TO_FIELDS) or _pick(e, _EDGE_TO_LABEL)
            if frm is not None:
                self._adj.setdefault(str(frm), []).append(e)
            if to is not None:
                self._adj.setdefault(str(to), []).append(e)

    def finalize(self) -> None:
        logger.info(
            "Topology index: %d nodes, %d edges, %d IP keys, %d name keys",
            len(self.nodes), len(self.edges), len(self._by_ip), len(self._by_name),
        )

    # -- resolution --------------------------------------------------------
    def resolve_asset(self, asset: AffectedAsset) -> list[TopologyNodeRef]:
        refs: list[TopologyNodeRef] = []
        seen: set[str] = set()

        def add(node: dict[str, Any], matched_by: str) -> None:
            nid = str(_pick(node, _NODE_ID_FIELDS) or "")
            key = nid or id(node)
            if str(key) in seen:
                return
            seen.add(str(key))
            refs.append(TopologyNodeRef(
                node_key=str(_pick(node, ("_key",)) or nid),
                node_id=nid or None,
                node_type=_pick(node, _NODE_TYPE_FIELDS),
                layer=_pick(node, _NODE_LAYER_FIELDS),
                label=_pick(node, _NODE_NAME_FIELDS),
                matched_by=matched_by,
            ))

        if asset.ip:
            for node in self._by_ip.get(_norm(asset.ip), []):
                add(node, "ip")
        for cand, by in ((asset.ci_name, "ci_name"), (asset.name, "name"),
                         (asset.shortname, "shortname")):
            if cand:
                for node in self._by_name.get(_norm(cand), []):
                    add(node, by)
        return refs

    # -- traversal ---------------------------------------------------------
    def neighbors(self, node_ref: TopologyNodeRef, max_depth: int = 2,
                  max_nodes: int = 50) -> list[TopologyDependent]:
        if not node_ref.node_id:
            return []
        out: list[TopologyDependent] = []
        visited: set[str] = {node_ref.node_id}
        frontier: list[tuple[str, int]] = [(node_ref.node_id, 0)]
        while frontier and len(out) < max_nodes:
            current, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            for edge in self._adj.get(current, []):
                frm = str(_pick(edge, _EDGE_FROM_FIELDS) or _pick(edge, _EDGE_FROM_LABEL) or "")
                to = str(_pick(edge, _EDGE_TO_FIELDS) or _pick(edge, _EDGE_TO_LABEL) or "")
                other = to if frm == current else frm
                direction = "outbound" if frm == current else "inbound"
                if not other or other in visited:
                    continue
                visited.add(other)
                node = self._by_id.get(other, {})
                out.append(TopologyDependent(
                    node_id=other,
                    label=_pick(node, _NODE_NAME_FIELDS) or other,
                    node_type=_pick(node, _NODE_TYPE_FIELDS),
                    layer=_pick(node, _NODE_LAYER_FIELDS),
                    relation_type=_pick(edge, _EDGE_REL_FIELDS),
                    direction=direction,
                    depth=depth + 1,
                ))
                frontier.append((other, depth + 1))
                if len(out) >= max_nodes:
                    break
        return out

    def build_view(self, assets: list[AffectedAsset], max_depth: int = 2) -> TopologyView:
        view = TopologyView(graph_name=self.graph_name, db_name=self.db_name)
        layers: set[str] = set()
        for asset in assets:
            for ref in self.resolve_asset(asset):
                view.matched_nodes.append(ref)
                if ref.layer:
                    layers.add(str(ref.layer))
                for dep in self.neighbors(ref, max_depth=max_depth):
                    view.dependents.append(dep)
                    if dep.layer:
                        layers.add(str(dep.layer))
        view.resolved = bool(view.matched_nodes)
        view.impacted_layers = sorted(layers)
        if not view.resolved:
            view.note = "No topology node matched the incident asset (IP/CI name)."
        return view

    # -- persistence -------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Pretty-print so grep/line tools cannot scan the entire graph as one line.
        path.write_text(
            json.dumps(
                {
                    "graph_name": self.graph_name,
                    "db_name": self.db_name,
                    "nodes": self.nodes,
                    "edges": self.edges,
                    "truncated": self.truncated,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def _cfxql_escape(value: str) -> str:
    return str(value).replace("'", "").strip()


def _looks_like_ip(value: str) -> bool:
    parts = str(value).split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


class TopologyResolver:
    """Live, targeted topology resolution using cfxql against the full graph.

    Resolves an asset to its node(s) and walks edges per-node (complete, not
    truncated). Caches node/edge queries within a run and enforces a per-incident
    query budget so depth-N traversal stays bounded. Used identically by polling
    and by future webhook ingestion.
    """

    def __init__(self, client: CfxClient, cfg: CfxConfig, *, max_depth: int = 1,
                 neighbor_cap: int = 25, query_budget: int = 60) -> None:
        self.client = client
        self.cfg = cfg
        self.graph_name = cfg.topology_graph
        self.db_name = cfg.topology_db
        self.max_depth = max_depth
        self.neighbor_cap = neighbor_cap
        self.query_budget = query_budget
        self._node_cache: dict[str, list[dict[str, Any]]] = {}
        self._edge_cache: dict[str, list[dict[str, Any]]] = {}
        # kept for parity with the index-based interface
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []

    # -- node resolution ---------------------------------------------------
    def _resolve_nodes(self, label_candidates: list[str],
                       ip_candidates: list[str]) -> list[dict[str, Any]]:
        clauses: list[str] = []
        for lab in label_candidates:
            lab = _cfxql_escape(lab)
            if lab:
                clauses.append(f"node_label = '{lab}'")
        for ip in ip_candidates:
            ip = _cfxql_escape(ip)
            if ip:
                clauses.append(f"host_os_ip = '{ip}'")
        if not clauses:
            return []
        cfxql = " OR ".join(dict.fromkeys(clauses))
        if cfxql in self._node_cache:
            return self._node_cache[cfxql]
        rows = self.client.graph_nodes(self.graph_name, self.db_name, limit=25, cfxql=cfxql)
        self._node_cache[cfxql] = rows
        return rows

    def resolve_asset(self, asset: AffectedAsset) -> list[TopologyNodeRef]:
        labels = [c for c in (asset.ci_name, asset.name, asset.shortname, asset.ip) if c]
        ips = [c for c in (asset.ip,) if c and _looks_like_ip(c)]
        refs: list[TopologyNodeRef] = []
        seen: set[str] = set()
        for node in self._resolve_nodes(labels, ips):
            nid = node.get("_id") or node.get("node_id")
            if not nid or nid in seen:
                continue
            seen.add(nid)
            refs.append(TopologyNodeRef(
                node_key=node.get("_key"),
                node_id=nid,
                node_type=node.get("node_type"),
                layer=node.get("layer"),
                label=node.get("node_label"),
                matched_by="ip" if (asset.ip and _looks_like_ip(asset.ip)
                                    and node.get("host_os_ip") == asset.ip) else "label",
            ))
        return refs

    # -- edge traversal ----------------------------------------------------
    def _edges_for(self, node_id: str, label: str | None) -> list[dict[str, Any]]:
        key = node_id or (label or "")
        if key in self._edge_cache:
            return self._edge_cache[key]
        clauses = []
        if node_id:
            clauses.append(f"_from = '{_cfxql_escape(node_id)}'")
            clauses.append(f"_to = '{_cfxql_escape(node_id)}'")
        if label:
            lab = _cfxql_escape(label)
            clauses.append(f"left_label = '{lab}'")
            clauses.append(f"right_label = '{lab}'")
        rows = self.client.graph_edges(
            self.graph_name, self.db_name, limit=200, cfxql=" OR ".join(clauses)
        )
        self._edge_cache[key] = rows
        return rows

    def neighbors(self, node_ref: TopologyNodeRef, max_depth: int | None = None,
                  max_nodes: int | None = None) -> list[TopologyDependent]:
        depth_limit = self.max_depth if max_depth is None else max_depth
        cap = self.neighbor_cap if max_nodes is None else max_nodes
        out: list[TopologyDependent] = []
        visited: set[str] = {node_ref.node_id or ""}
        frontier: list[tuple[str, str | None, int]] = [
            (node_ref.node_id or "", node_ref.label, 0)
        ]
        queries = 0
        while frontier and len(out) < cap and queries < self.query_budget:
            cur_id, cur_label, depth = frontier.pop(0)
            if depth >= depth_limit:
                continue
            queries += 1
            for edge in self._edges_for(cur_id, cur_label):
                frm = str(edge.get("_from") or "")
                outbound = (frm == cur_id) or (
                    edge.get("left_label") == cur_label and frm != cur_id and not cur_id
                )
                if outbound:
                    other_id = str(edge.get("_to") or "")
                    other_label = edge.get("right_label")
                    other_type = edge.get("right_node_type")
                    direction = "outbound"
                else:
                    other_id = str(edge.get("_from") or "")
                    other_label = edge.get("left_label")
                    other_type = edge.get("left_node_type")
                    direction = "inbound"
                marker = other_id or str(other_label)
                if not marker or marker in visited:
                    continue
                visited.add(marker)
                out.append(TopologyDependent(
                    node_id=other_id or None,
                    label=other_label,
                    node_type=other_type,
                    layer=None,
                    relation_type=edge.get("relation_type"),
                    direction=direction,
                    depth=depth + 1,
                ))
                if depth + 1 < depth_limit:
                    frontier.append((other_id, other_label, depth + 1))
                if len(out) >= cap:
                    break
        return out

    def build_view(self, assets: list[AffectedAsset], max_depth: int | None = None) -> TopologyView:
        view = TopologyView(graph_name=self.graph_name, db_name=self.db_name)
        layers: set[str] = set()
        for asset in assets:
            for ref in self.resolve_asset(asset):
                view.matched_nodes.append(ref)
                if ref.layer:
                    layers.add(str(ref.layer))
                for dep in self.neighbors(ref, max_depth=max_depth):
                    view.dependents.append(dep)
        view.resolved = bool(view.matched_nodes)
        view.impacted_layers = sorted(layers)
        if not view.resolved:
            view.note = "No topology node matched the incident asset (label/IP)."
        return view


def sync_topology(client: CfxClient, cfg: CfxConfig, max_nodes: int = 20000,
                  max_edges: int = 40000, page: int = 500,
                  cache_path: Path | None = None,
                  use_cache: bool = True) -> TopologyIndex:
    if cache_path and use_cache and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            idx = TopologyIndex(data.get("graph_name", cfg.topology_graph),
                                data.get("db_name", cfg.topology_db))
            idx.add_nodes(data.get("nodes", []))
            idx.add_edges(data.get("edges", []))
            idx.truncated = data.get("truncated", False)
            idx.finalize()
            logger.info("Loaded topology from cache: %s", cache_path)
            return idx
        except Exception as exc:  # pragma: no cover
            logger.warning("Cache load failed (%s); refetching", exc)

    idx = TopologyIndex(cfg.topology_graph, cfg.topology_db)
    offset = 0
    while len(idx.nodes) < max_nodes:
        batch = client.graph_nodes(cfg.topology_graph, cfg.topology_db, limit=page, offset=offset)
        if not batch:
            break
        idx.add_nodes(batch)
        offset += len(batch)
        if len(batch) < page:
            break
    if len(idx.nodes) >= max_nodes:
        idx.truncated = True

    offset = 0
    while len(idx.edges) < max_edges:
        batch = client.graph_edges(cfg.topology_graph, cfg.topology_db, limit=page, offset=offset)
        if not batch:
            break
        idx.add_edges(batch)
        offset += len(batch)
        if len(batch) < page:
            break
    if len(idx.edges) >= max_edges:
        idx.truncated = True

    idx.finalize()
    if cache_path:
        idx.save(cache_path)
    return idx
