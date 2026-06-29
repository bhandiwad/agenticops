---
name: servicenow
id: servicenow
description: "ServiceNow ITSM connector — fetch tickets by number, load tickets linked to Aurora incidents, and resolve on request"
category: incident_management
connection_check:
  method: is_connected_function
  module: chat.backend.agent.tools.servicenow_tool
  function: is_servicenow_connected
tools:
  - get_servicenow_ticket_by_number
  - get_servicenow_ticket_for_incident
  - resolve_servicenow_ticket
index: "ITSM -- fetch ServiceNow ticket details and resolve linked tickets via the Aurora connector"
rca_priority: 2
allowed-tools: get_servicenow_ticket_by_number, get_servicenow_ticket_for_incident, resolve_servicenow_ticket
metadata:
  author: aurora
  version: "1.0"
---

# ServiceNow Connector

## Overview

Aurora's ServiceNow connector stores per-user credentials in Vault (connect via **Connectors → ServiceNow**).
All tools below use connector credentials automatically, with `.env` fallback for legacy deployments.

## When to use

**Call ServiceNow tools when:**

- The user provides a ServiceNow ticket number (`IT#...`, `INC...`)
- An Aurora incident has a linked SNOW ticket (`snow_sys_id` in alert_metadata)
- The user asks for ticket state, assignment, priority, or work notes from ServiceNow
- The user explicitly asks to resolve/close a SNOW ticket linked to an Aurora incident

**Prefer CFX enriched docs first** when doing full RCA and `get_cfx_enriched_incident` data exists — then call `get_servicenow_ticket_by_number` only for live fields (work notes, current state).

## Tools

1. `get_servicenow_ticket_by_number(ticket_number='IT#0011459406')` — read-only fetch by ticket number
2. `get_servicenow_ticket_for_incident(incident_id='<uuid>')` — fetch the ticket linked to an Aurora incident
3. `resolve_servicenow_ticket(incident_id='<uuid>', resolution_notes='...')` — resolve linked ticket (only when user explicitly requests)

## Fetch workflow

1. Read `ticket_number` or `incident_id` from action context / user message
2. Call the appropriate fetch tool (never guess ticket numbers)
3. Report: ticket_number, state, active, short_description, priority, assignment_group, assigned_to, opened_at, snow_url

## Safety

- Default to **read-only** unless the user explicitly requests resolve
- Only resolve the ticket linked to the given Aurora incident
- Do not create tickets or modify assignment/priority fields
