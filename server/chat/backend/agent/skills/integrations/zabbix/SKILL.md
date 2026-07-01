---
name: zabbix
id: zabbix
description: "Zabbix monitoring integration — query hosts, active problems, firing triggers, and item latest-values for infrastructure/VM investigations."
category: observability
connection_check:
  method: get_token_data
  provider_key: zabbix
  required_any_fields: [api_token, apiToken, username]
tools:
  - query_zabbix
index: "Zabbix monitoring — hosts, active problems, firing triggers, item latest values, host groups"
rca_priority: 8
allowed-tools: query_zabbix
metadata:
  author: aurora
  version: "1.0"
---

# Zabbix Monitoring

Query a connected Zabbix server to investigate infrastructure/VM health. This is a
**remote, read-only** integration: use the `query_zabbix` tool. The Zabbix JSON-RPC API is
used; multiple Zabbix versions are supported (auth is negotiated per version).

## Tool usage

`query_zabbix(resource_type=TYPE, limit=N)`

Resource types:
- `problems` — current active problems (most recent first) — start here for an incident
- `triggers` — firing triggers (by priority), with expanded descriptions
- `hosts` — monitored hosts and availability
- `items` — item latest-values (metrics like CPU, memory, disk)
- `hostgroups` — host groups

## RCA workflow (read-only)

1. `query_zabbix(resource_type='problems')` — what is actively alerting right now.
2. `query_zabbix(resource_type='triggers')` — highest-priority firing triggers and their
   descriptions.
3. `query_zabbix(resource_type='hosts')` / `items` — confirm which hosts are affected and
   inspect the metric latest-values behind the alert.
4. Correlate with other signals and report the likely cause + affected hosts.

## Important rules

- Read-only: never attempt to modify Zabbix configuration.
- Prefer `problems` for "what's wrong now"; use `items` to read the underlying metric values.
