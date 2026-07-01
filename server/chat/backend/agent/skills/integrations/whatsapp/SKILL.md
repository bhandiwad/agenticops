---
name: whatsapp
id: whatsapp
description: "WhatsApp Business (Meta Cloud API) notification channel — send text notifications from automation workflows (approval-needed / outcome)."
category: notification
connection_check:
  method: get_token_data
  provider_key: whatsapp
  required_any_fields: [access_token, phone_number_id]
tools:
  - send_whatsapp
index: "WhatsApp Business notifications — send text messages from workflows"
rca_priority: 90
allowed-tools: send_whatsapp
metadata:
  author: aurora
  version: "1.0"
---

# WhatsApp Notifications

Send WhatsApp notifications via the connected WhatsApp Business number (Meta Cloud API). The
`send_whatsapp` tool is available only in background/workflow execution — workflows use it to
notify a recipient that an approval is needed or that an action completed.

## Tool usage

`send_whatsapp(to="<E.164 number, e.g. 15551234567>", message="<text>")`

## Rules

- Keep messages concise and factual (what happened / what is needed).
- Note: outside a 24-hour customer session window, WhatsApp requires a pre-approved template;
  free-form text is delivered only within an open session.
