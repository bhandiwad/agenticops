---
name: commvault
id: commvault
description: "Commvault backup integration — inspect clients/VMs and check backup job status. Backups are triggered only via the approval-gated VM-backup workflow."
category: infrastructure
connection_check:
  method: get_token_data
  provider_key: commvault
  required_any_fields: [username]
tools:
  - query_commvault
index: "Commvault backup — clients, VMs, and backup job status (poll/validate a job)"
rca_priority: 22
allowed-tools: query_commvault
metadata:
  author: aurora
  version: "1.0"
---

# Commvault Backup

Inspect a connected Commvault environment (read-only for investigation) using `query_commvault`.

## Tool usage

`query_commvault(resource_type=TYPE, job_id=ID)`

Resource types:
- `clients` — protected clients
- `vms` — virtualization VMs and their backup status
- `job` — status of a specific backup job (pass `job_id`) — used to poll/validate a backup

## RCA / status workflow (read-only)

1. `query_commvault(resource_type='vms')` — check which VMs are protected and their last
   backup status.
2. `query_commvault(resource_type='job', job_id=...)` — inspect a specific job's status when
   validating whether a backup succeeded.

## Important rules

- **Never trigger a backup from RCA/chat.** Backups run only through the approval-gated
  VM-backup workflow, which triggers the job, polls it to completion to validate success, and
  records the outcome on the ServiceNow ticket.
