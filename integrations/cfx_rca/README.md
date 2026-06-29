# CFX → ServiceNow → Topology Enrichment (RCA / Postmortem Foundation)

Additive Aurora integration that produces a **canonical join** mapping
CloudFabrix (CFX) incidents to their **ServiceNow ticket numbers** and
**affected topology nodes + dependents**. This is the data foundation Aurora
agents use for RCA, postmortem analysis, ServiceNow linking, and affected-asset
discovery.

> **Non-invasive:** This package only adds new files. It does **not** modify any
> existing Aurora code, routes, containers, or tables. CFX is accessed
> **read-only (GET)**; the only non-GET call is the user-provided token *rotate*
> endpoint, invoked lazily on 401.

## Why this also covers webhooks (no future changes needed)

All data — polled now, or pushed via webhooks later — flows through **one
funnel**: `ingest_records()` / `ingest_one()`. Polling and webhooks both produce
a raw record dict and call the same normalize → enrich → store pipeline against
the same schema.

```
                 ┌─────────── poll (now) ──────────┐
raw CFX record ──┤                                 ├──► normalize ──► enrich ──► store
                 └────── webhook (later) ──────────┘     (join keys + topology + SNOW)
```

Adding live ingestion later = wire `webhook.WebhookProcessor` into a new Flask
blueprint. Nothing in `normalize.py`, `enrich.py`, `topology.py`, `store.py`, or
the schema changes.

## Layout

| File | Responsibility |
|------|----------------|
| `config.py` | Loads CFX creds from Aurora `.env` |
| `cfx_client.py` | GET-only CFX client, lazy token rotate |
| `normalize.py` | Source-agnostic raw → canonical (poll + webhook) |
| `topology.py` | Live cfxql resolver + optional bulk index cache; asset→node + dependents |
| `enrich.py` | The join: incident + SNOW ticket + topology + agent seeds |
| `models.py` | Versioned canonical schema (`EnrichedIncident`) |
| `store.py` | JSON store (default) + optional additive Postgres table |
| `ingest.py` | Poll orchestrator + shared ingest funnel (CLI) |
| `webhook.py` | Future live ingestion entrypoints (same funnel) |
| `schema.sql` | Additive `cfx_enriched_incidents` table |

## Run (read-only poll)

```bash
cd /home/ubuntu/aurora/integrations
# live resolver (default): targeted cfxql per incident, complete dependents
python3 -m cfx_rca.ingest --limit 200 --depth 1 --topo-mode live --print-sample 2
# optional bulk index cache (faster but truncated graph):
python3 -m cfx_rca.ingest --topo-mode bulk --refresh-topology
# write to the additive Postgres table instead of JSON:
python3 -m cfx_rca.ingest --postgres --pg-dsn "$DATABASE_URL"
```

**First run results (Sify_IT_Services):** 235 incidents ingested, 53 linked to
ServiceNow tickets, 100 with topology node matches, dependents populated (e.g.
SAN switch → 25 connected hypervisors/storage arrays).

Output (JSON backend) lands in `/home/ubuntu/aurora/data/cfx_rca/`:
- `incidents/<cfx_incident_id>.json` — full enriched documents
- `index.json` — quick per-incident summary
- `join_index.json` — reverse lookup by SNOW ticket / asset IP / CI sys_id
- `topology_cache.json` — cached graph (nodes/edges)

## Canonical document (`EnrichedIncident`, schema 1.0)

```jsonc
{
  "ingest":   { "source": "cfx_poll|cfx_webhook|snow_webhook", "source_stream", "ingested_at", "schema_version" },
  "incident": { "cfx_incident_id", "severity", "status", "incident_type", "summary",
                "alert_count", "alert_sources", "created_ts", "occurred_ts", ... },
  "snow":     { "ticket_number", "ticket_sys_id", "ticket_status", "company_sys_id",
                "ci_sys_id", "url", "source_stream" },
  "affected_assets": [ { "ip", "name", "ci_name", "ci_sys_id", "node_type", "layer" } ],
  "topology": { "resolved", "graph_name", "matched_nodes":[...],
                "dependents":[ {"node_id","label","node_type","layer","relation_type","direction","depth"} ],
                "impacted_layers":[...] },
  "correlation": { "correlation_batch_id", "parent_incident_id", "member_alert_ids" },
  "join_keys":   { "cfx_incident_id", "snow_ticket_number", "snow_ticket_sys_id",
                   "asset_ips", "ci_sys_ids", "ci_names" },      // <-- cross-system join
  "agent_context": { "rca_seed", "postmortem_seed", "snow_seed" } // LLM-ready
}
```

`join_keys` is the cross-system index Aurora agents query by:
- RCA agent → `topology.dependents` + `correlation`
- Postmortem agent → `agent_context.postmortem_seed` + `impacted_layers`
- SNOW-link agent → `snow.*` / `join_keys.snow_ticket_number`
- Affected-assets agent → `affected_assets` + `topology.matched_nodes`

## Adding webhooks later (illustrative)

```python
from cfx_rca.config import CfxConfig
from cfx_rca.webhook import WebhookProcessor

proc = WebhookProcessor(CfxConfig.from_env())   # warm topology + store at startup

# new blueprint, does not touch existing routes
@bp.post("/webhooks/cfx")
def cfx_hook():
    return proc.handle_cfx_event(request.get_json())

@bp.post("/webhooks/snow")
def snow_hook():
    return proc.handle_snow_event(request.get_json())
```

Same maps, same schema, same store — zero changes to the enrichment layer.
