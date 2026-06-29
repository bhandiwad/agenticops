"""Ingestion orchestrator.

This module is the single funnel through which ALL data flows, regardless of
origin. The webhook-readiness guarantee comes from one fact:

    poll mode and webhook mode both call `ingest_records(...)`.

Today `run_poll()` pulls CFX incident streams via GET and feeds them in. Later,
an HTTP webhook handler (CFX or ServiceNow) parses its payload into the same raw
record shape and calls `ingest_records(...)` / `ingest_one(...)` — no change to
normalize/enrich/store/schema is required.

Incident source streams (confirmed populated during discovery):
    - oia-incident-inserts-stream     (full incident inserts)
    - oia-incidents-stream            (incident state)
    - oia-incidents-external-tickets-stream (SNOW ticket linkage)
    - oia-alerts-stream               (alert-level detail / asset IPs)
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from .cfx_client import CfxClient
from .config import CfxConfig
from .enrich import enrich_record
from .models import EnrichedIncident
from .store import JsonStore, PostgresStore, write_all
from .topology import TopologyIndex, TopologyResolver, sync_topology

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cfx_rca.ingest")

INCIDENT_STREAMS = [
    "oia-incident-inserts-stream",
    "oia-incidents-stream",
]
EXTERNAL_TICKET_STREAM = "oia-incidents-external-tickets-stream"


# --------------------------------------------------------------------------
# Core funnel — shared by poll AND webhook
# --------------------------------------------------------------------------
def ingest_records(
    records: Iterable[dict[str, Any]],
    *,
    topo: TopologyIndex | None,
    source: str,
    source_stream: str = "",
    snow_lookup: dict[str, dict[str, Any]] | None = None,
    max_depth: int = 2,
) -> list[EnrichedIncident]:
    """Normalize + enrich a batch of raw records into EnrichedIncident docs.

    `snow_lookup` optionally maps cfx_incident_id -> SNOW detail dict (e.g. from
    the external-tickets stream or a live ServiceNow fetch / SNOW webhook)."""
    snow_lookup = snow_lookup or {}
    out: list[EnrichedIncident] = []
    for rec in records:
        inc_id = (
            rec.get("incident_id")
            or rec.get("i_incident_id")
            or rec.get("incidentid")
        )
        detail = snow_lookup.get(str(inc_id)) if inc_id else None
        out.append(
            enrich_record(
                rec, topo, source=source, source_stream=source_stream,
                snow_detail=detail, max_depth=max_depth,
            )
        )
    return out


def ingest_one(record: dict[str, Any], *, topo: TopologyIndex | None,
               source: str, source_stream: str = "",
               snow_detail: dict[str, Any] | None = None) -> EnrichedIncident:
    """Single-record entrypoint — what a future webhook handler will call."""
    return enrich_record(record, topo, source=source, source_stream=source_stream,
                         snow_detail=snow_detail)


# --------------------------------------------------------------------------
# SNOW linkage lookup (from CFX external-tickets stream, GET only)
# --------------------------------------------------------------------------
def build_snow_lookup(client: CfxClient, limit: int = 500) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    try:
        rows = client.pstream_data(EXTERNAL_TICKET_STREAM, limit=limit)
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not read external ticket stream: %s", exc)
        return lookup
    for row in rows:
        inc_id = row.get("incident_id") or row.get("i_incident_id")
        if inc_id:
            lookup[str(inc_id)] = row
    logger.info("Built SNOW lookup with %d external-ticket rows", len(lookup))
    return lookup


# --------------------------------------------------------------------------
# Poll mode (today)
# --------------------------------------------------------------------------
def run_poll(cfg: CfxConfig, *, limit: int = 200, max_depth: int = 1,
             use_postgres: bool = False, pg_dsn: str | None = None,
             refresh_topology: bool = False, streams: list[str] | None = None,
             topo_mode: str = "live") -> dict[str, Any]:
    client = CfxClient(cfg)
    out_root = Path(cfg.output_dir)

    if topo_mode == "bulk":
        cache_path = out_root / "topology_cache.json"
        topo = sync_topology(
            client, cfg, cache_path=cache_path, use_cache=not refresh_topology
        )
    else:
        topo = TopologyResolver(client, cfg, max_depth=max_depth)

    snow_lookup = build_snow_lookup(client)

    all_items: list[EnrichedIncident] = []
    seen: set[str] = set()
    per_stream: dict[str, int] = {}
    for stream in (streams or INCIDENT_STREAMS):
        rows = client.pstream_data(stream, limit=limit)
        per_stream[stream] = len(rows)
        items = ingest_records(
            rows, topo=topo, source="cfx_poll", source_stream=stream,
            snow_lookup=snow_lookup, max_depth=max_depth,
        )
        for it in items:
            iid = it.incident.cfx_incident_id or ""
            if iid and iid in seen:
                continue
            if iid:
                seen.add(iid)
            all_items.append(it)

    if use_postgres and pg_dsn:
        store = PostgresStore(pg_dsn)
    else:
        store = JsonStore(cfg.output_dir)
    written = write_all(store, all_items)
    if isinstance(store, PostgresStore):
        store.close()

    linked = sum(1 for i in all_items if i.snow.ticket_number)
    resolved = sum(1 for i in all_items if i.topology.resolved)
    summary = {
        "incidents_ingested": written,
        "with_snow_ticket": linked,
        "with_topology_match": resolved,
        "per_stream_rows": per_stream,
        "topology_mode": topo_mode,
        "topology_nodes_cached": len(getattr(topo, "nodes", []) or []),
        "topology_edges_cached": len(getattr(topo, "edges", []) or []),
        "output_dir": str(out_root),
        "backend": "postgres" if isinstance(store, PostgresStore) else "json",
    }
    logger.info("Poll complete: %s", json.dumps(summary))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="CFX -> SNOW -> topology enrichment ingest")
    ap.add_argument("--env", default=None, help="Path to aurora .env")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--depth", type=int, default=1, help="Topology traversal depth")
    ap.add_argument("--topo-mode", choices=["live", "bulk"], default="live",
                    help="live=cfxql per-node (complete); bulk=paged index cache")
    ap.add_argument("--postgres", action="store_true", help="Write to additive Postgres table")
    ap.add_argument("--pg-dsn", default=None, help="Postgres DSN (else from DATABASE_URL/env)")
    ap.add_argument("--refresh-topology", action="store_true", help="Ignore topology cache")
    ap.add_argument("--streams", nargs="*", default=None)
    ap.add_argument("--print-sample", type=int, default=0, help="Print N enriched samples")
    args = ap.parse_args()

    cfg = CfxConfig.from_env(args.env) if args.env else CfxConfig.from_env()
    pg_dsn = args.pg_dsn or cfg.raw.get("DATABASE_URL") or cfg.raw.get("POSTGRES_DSN")

    summary = run_poll(
        cfg, limit=args.limit, max_depth=args.depth,
        use_postgres=args.postgres, pg_dsn=pg_dsn,
        refresh_topology=args.refresh_topology, streams=args.streams,
        topo_mode=args.topo_mode,
    )
    print(json.dumps(summary, indent=2))

    if args.print_sample:
        idx_path = Path(cfg.output_dir) / "index.json"
        if idx_path.exists():
            index = json.loads(idx_path.read_text())
            shown = 0
            for inc_id, meta in index.items():
                doc = json.loads((Path(cfg.output_dir) / meta["file"]).read_text())
                print("\n=== SAMPLE", inc_id, "===")
                print(json.dumps({
                    "incident": doc["incident"],
                    "snow": doc["snow"],
                    "affected_assets": doc["affected_assets"],
                    "topology": {
                        "resolved": doc["topology"]["resolved"],
                        "matched_nodes": doc["topology"]["matched_nodes"],
                        "dependents": doc["topology"]["dependents"][:5],
                        "impacted_layers": doc["topology"]["impacted_layers"],
                    },
                    "join_keys": doc["join_keys"],
                    "agent_context": doc["agent_context"],
                }, indent=2, default=str))
                shown += 1
                if shown >= args.print_sample:
                    break


if __name__ == "__main__":
    main()
