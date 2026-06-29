"""Webhook entrypoints for FUTURE live ingestion (CFX + ServiceNow).

This module is intentionally framework-light. It demonstrates that adding live
ingestion later requires NO changes to the maps/normalize/enrich/store layers —
each handler simply parses its payload into the same raw record shape and calls
the shared `ingest_one(...)` funnel, then persists via the same store.

Wire these into Aurora's existing Flask app later (a new blueprint) without
touching any current routes. Nothing here runs at poll time.
"""
from __future__ import annotations

from typing import Any

from .cfx_client import CfxClient
from .config import CfxConfig
from .ingest import ingest_one
from .normalize import normalize_snow_ticket
from .store import JsonStore, PostgresStore
from .topology import TopologyResolver


class WebhookProcessor:
    """Holds a warm topology resolver + store so webhook calls are fast.

    Construct once at app startup; call handle_cfx_event / handle_snow_event per
    delivery. The resolver queries CFX live (cfxql) per event, so it always
    reflects the current graph with no periodic full sync required.
    """

    def __init__(self, cfg: CfxConfig, store=None, topo: TopologyResolver | None = None,
                 max_depth: int = 1) -> None:
        self.cfg = cfg
        self.client = CfxClient(cfg)
        self.topo = topo or TopologyResolver(self.client, cfg, max_depth=max_depth)
        self.store = store or JsonStore(cfg.output_dir)

    def refresh_topology(self) -> None:
        # Live resolver needs no bulk refresh; just clear per-run caches.
        self.topo = TopologyResolver(self.client, self.cfg, max_depth=self.topo.max_depth)

    def handle_cfx_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """CFX incident/alert webhook -> enriched doc (same pipeline as poll)."""
        record = _unwrap(payload)
        item = ingest_one(record, topo=self.topo, source="cfx_webhook",
                          source_stream=payload.get("stream", "webhook"))
        inc_id = self.store.upsert(item)
        self.store.flush()
        return {"status": "ok", "cfx_incident_id": inc_id,
                "snow_ticket_number": item.snow.ticket_number,
                "topology_resolved": item.topology.resolved}

    def handle_snow_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """ServiceNow webhook -> augment the matching CFX incident's SNOW block.

        Correlate by cfx_incident_id if present, else by ticket number against the
        existing join index (JSON store) / table (Postgres).
        """
        record = _unwrap(payload)
        ticket = normalize_snow_ticket(record)
        # Caller links via ticket.ticket_number using join_index.json or the
        # cfx_enriched_incidents.snow_ticket_number column, then re-enriches that
        # incident with snow_detail=record through ingest_one(...). No schema change.
        return {"status": "accepted", "snow_ticket_number": ticket.ticket_number,
                "snow_sys_id": ticket.ticket_sys_id}


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Tolerate common webhook envelopes; return the flat record."""
    for key in ("data", "event", "record", "payload", "pstream_data"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            return inner
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            return inner[0]
    return payload
