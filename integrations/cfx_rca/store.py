"""Persistence for enriched incidents.

Two backends, both ADDITIVE (never touch existing Aurora tables/files):

1. JSON store (default): one file per incident under output_dir/incidents/, plus
   an index.json and a join_index.json for fast lookup by cross-system key.
2. Postgres (optional, --postgres): a single new table `cfx_enriched_incidents`
   created with CREATE TABLE IF NOT EXISTS. JSONB document + generated columns
   for the join keys so Aurora agents can query by CFX id, SNOW number, or asset.

The Postgres backend reuses the existing aurora DB connection string but only
ever creates/writes its own dedicated table.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from .models import EnrichedIncident

logger = logging.getLogger("cfx_rca.store")


class JsonStore:
    def __init__(self, output_dir: str | Path) -> None:
        self.root = Path(output_dir)
        self.incident_dir = self.root / "incidents"
        self.incident_dir.mkdir(parents=True, exist_ok=True)
        self.index: dict[str, Any] = {}
        self.join_index: dict[str, list[str]] = {}

    @staticmethod
    def _safe(name: str) -> str:
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)

    def upsert(self, item: EnrichedIncident) -> str:
        doc = item.to_dict()
        inc_id = item.incident.cfx_incident_id or f"noid_{self._safe(str(id(item)))}"
        fname = self._safe(inc_id) + ".json"
        (self.incident_dir / fname).write_text(
            json.dumps(doc, indent=2, default=str), encoding="utf-8"
        )
        self.index[inc_id] = {
            "file": f"incidents/{fname}",
            "snow_ticket_number": item.snow.ticket_number,
            "severity": item.incident.severity,
            "status": item.incident.status,
            "asset_ips": item.join_keys.asset_ips,
            "matched_nodes": len(item.topology.matched_nodes),
            "dependents": len(item.topology.dependents),
        }
        self._add_join("cfx_incident_id", inc_id, inc_id)
        if item.snow.ticket_number:
            self._add_join("snow_ticket_number", item.snow.ticket_number, inc_id)
        if item.snow.ticket_sys_id:
            self._add_join("snow_sys_id", item.snow.ticket_sys_id, inc_id)
        for ip in item.join_keys.asset_ips:
            self._add_join("asset_ip", ip, inc_id)
        for sysid in item.join_keys.ci_sys_ids:
            self._add_join("ci_sys_id", sysid, inc_id)
        return inc_id

    def _add_join(self, kind: str, value: str, inc_id: str) -> None:
        key = f"{kind}::{value}"
        bucket = self.join_index.setdefault(key, [])
        if inc_id not in bucket:
            bucket.append(inc_id)

    def flush(self) -> None:
        (self.root / "index.json").write_text(
            json.dumps(self.index, indent=2, default=str), encoding="utf-8"
        )
        (self.root / "join_index.json").write_text(
            json.dumps(self.join_index, indent=2, default=str), encoding="utf-8"
        )
        logger.info("JSON store flushed: %d incidents -> %s", len(self.index), self.root)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cfx_enriched_incidents (
    cfx_incident_id      text PRIMARY KEY,
    snow_ticket_number   text,
    snow_ticket_sys_id   text,
    severity             text,
    status               text,
    org_name             text,
    asset_ips            text[],
    ci_sys_ids           text[],
    matched_node_count   int,
    dependent_count      int,
    source               text,
    document             jsonb NOT NULL,
    ingested_at          timestamptz DEFAULT now(),
    updated_at           timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cfx_enr_snow_number ON cfx_enriched_incidents (snow_ticket_number);
CREATE INDEX IF NOT EXISTS idx_cfx_enr_asset_ips   ON cfx_enriched_incidents USING gin (asset_ips);
CREATE INDEX IF NOT EXISTS idx_cfx_enr_document    ON cfx_enriched_incidents USING gin (document);
"""

UPSERT_SQL = """
INSERT INTO cfx_enriched_incidents
    (cfx_incident_id, snow_ticket_number, snow_ticket_sys_id, severity, status,
     org_name, asset_ips, ci_sys_ids, matched_node_count, dependent_count,
     source, document, updated_at)
VALUES (%(cfx_incident_id)s, %(snow_ticket_number)s, %(snow_ticket_sys_id)s,
        %(severity)s, %(status)s, %(org_name)s, %(asset_ips)s, %(ci_sys_ids)s,
        %(matched_node_count)s, %(dependent_count)s, %(source)s, %(document)s, now())
ON CONFLICT (cfx_incident_id) DO UPDATE SET
    snow_ticket_number = EXCLUDED.snow_ticket_number,
    snow_ticket_sys_id = EXCLUDED.snow_ticket_sys_id,
    severity = EXCLUDED.severity,
    status = EXCLUDED.status,
    org_name = EXCLUDED.org_name,
    asset_ips = EXCLUDED.asset_ips,
    ci_sys_ids = EXCLUDED.ci_sys_ids,
    matched_node_count = EXCLUDED.matched_node_count,
    dependent_count = EXCLUDED.dependent_count,
    source = EXCLUDED.source,
    document = EXCLUDED.document,
    updated_at = now();
"""


class PostgresStore:
    """Optional. Writes only to its own dedicated table."""

    def __init__(self, dsn: str) -> None:
        import psycopg2  # type: ignore

        self._pg = psycopg2
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = True
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)

    def upsert(self, item: EnrichedIncident) -> str:
        from psycopg2.extras import Json  # type: ignore

        inc_id = item.incident.cfx_incident_id
        if not inc_id:
            return ""
        params = {
            "cfx_incident_id": inc_id,
            "snow_ticket_number": item.snow.ticket_number,
            "snow_ticket_sys_id": item.snow.ticket_sys_id,
            "severity": item.incident.severity,
            "status": item.incident.status,
            "org_name": item.incident.org_name,
            "asset_ips": item.join_keys.asset_ips,
            "ci_sys_ids": item.join_keys.ci_sys_ids,
            "matched_node_count": len(item.topology.matched_nodes),
            "dependent_count": len(item.topology.dependents),
            "source": item.ingest.source,
            "document": Json(item.to_dict()),
        }
        with self.conn.cursor() as cur:
            cur.execute(UPSERT_SQL, params)
        return inc_id

    def flush(self) -> None:
        pass

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def write_all(store, items: Iterable[EnrichedIncident]) -> int:
    count = 0
    for item in items:
        store.upsert(item)
        count += 1
    store.flush()
    return count
