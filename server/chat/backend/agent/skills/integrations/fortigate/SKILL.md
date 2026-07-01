---
name: fortigate
id: fortigate
description: "FortiGate (FortiOS) firewall integration — inspect firewall policies, address and service objects, interfaces, and system status for network/security investigations."
category: security
connection_check:
  method: get_token_data
  provider_key: fortigate
  required_any_fields: [api_token, apiToken]
tools:
  - query_fortigate
index: "FortiGate firewall — inspect policies, addresses, services, interfaces, system/firmware status"
rca_priority: 20
allowed-tools: query_fortigate
metadata:
  author: aurora
  version: "1.0"
---

# FortiGate Firewall

Inspect a connected FortiGate (FortiOS) firewall to understand network reachability and
security posture. This is a **remote, read-only** integration: use the `query_fortigate`
tool for every lookup. The FortiOS `/api/v2` REST API is used, which is consistent across
FortiOS 6.x–7.x; the running firmware version is reported by `resource_type='status'`.

## Tool usage

`query_fortigate(resource_type=TYPE, limit=N)`

Resource types:
- `status` — firmware version, hostname, serial, high-level system status
- `policies` — firewall policies (src/dst interface, addresses, service, action)
- `addresses` — address objects
- `services` — custom service objects (port ranges)
- `interfaces` — system interfaces

## RCA workflow (read-only)

When a connectivity or "port blocked / unreachable" issue is suspected:
1. `query_fortigate(resource_type='policies')` — find policies governing the src→dst path;
   check `action` (accept/deny), `service`, and matching `srcaddr`/`dstaddr`.
2. `query_fortigate(resource_type='services')` — confirm whether a service for the port exists.
3. `query_fortigate(resource_type='addresses')` / `interfaces` — verify the objects and
   interfaces referenced by the relevant policies.
4. Report findings: which policy allows/denies the traffic, and what a fix would require.

## Important rules

- **Never modify firewall configuration from RCA.** Opening a port, creating a policy, or
  editing objects must go through the approval-gated **open-firewall-port workflow**, which
  requires a human approval before any change is applied.
- Report concrete policy names/IDs and the exact service/port so a change can be reviewed.
