---
name: cloudfabrix
id: cloudfabrix
description: "CloudFabrix enriched incident join store — CFX incidents mapped to ServiceNow tickets, CMDB assets, and topology dependents"
category: observability
connection_check:
  method: is_connected_function
  module: chat.backend.agent.tools.cfx_rca_context
  function: is_cloudfabrix_connected
tools:
  - get_cfx_enriched_incident
  - list_cfx_enriched_incidents
index: "Observability -- load pre-enriched CFX+SNOW+topology join documents for RCA"
rca_priority: 2
allowed-tools: get_cfx_enriched_incident, list_cfx_enriched_incidents
metadata:
  author: aurora
  version: "1.0"
---

# CloudFabrix Enriched Incident Store

## Overview

Connect CloudFabrix via **Connectors → CloudFabrix** (`/cloudfabrix/auth`) to store API credentials in Vault.
Aurora maintains a **local join store** (`/app/data/cfx_rca`) populated by the CFX RCA Poll Agent.
Each document maps a CloudFabrix incident to its ServiceNow ticket, affected CMDB assets,
topology matched nodes, and downstream dependents.

This is **pre-computed enrichment** — faster and more complete than querying CFX and SNOW separately.

## When to use (MANDATORY for ticket-based RCA)

**You MUST call `get_cfx_enriched_incident` FIRST when:**

- The user mentions a ServiceNow ticket number (e.g. `IT#0011459657`)
- The user mentions a CFX incident id (e.g. `CFX20260626264027f973`)
- The user asks for topology, blast radius, dependents, or root cause for a known ticket
- Background RCA prompt includes a `cfx_context_summary` or `cfx_enriched` block (use it, then call the tool for full detail if needed)

**Do NOT skip this step** and go straight to ServiceNow or generic cloud tools when enriched data exists.

## Tools

- `get_cfx_enriched_incident(ticket_number='IT#...')` or `get_cfx_enriched_incident(cfx_incident_id='CFX...')`
  Returns: incident, snow, affected_assets, topology (matched_nodes + dependents), correlation, agent_context.rca_seed

- `list_cfx_enriched_incidents(limit=10, has_snow_ticket=true)` — browse recent enriched incidents when no specific id is given

## RCA workflow

1. **Load enriched doc** via `get_cfx_enriched_incident`
2. Read `agent_context.rca_seed` as the investigation starting point
3. Analyze `topology.dependents` for blast radius (label, node_type, relation_type, depth)
4. Use `correlation` for related alerts / parent incidents
5. Optionally call `get_servicenow_ticket_by_number` for **live** SNOW work notes / state (enriched doc may be slightly stale)
6. Use cloud/monitoring tools only for **additional** live telemetry not in the enriched doc

## Topology graph

When building an infrastructure graph, map:
- `topology.matched_nodes` → primary affected nodes
- `topology.dependents` → dependency edges (source=matched node, target=dependent)
- `affected_assets` → asset metadata (name, ip, ci_sys_id)

## If enriched doc is missing

Tell the user to run the **CFX RCA Poll Agent** (or wait for the next poll cycle), then retry.
Do not fabricate topology data.
