<div align="center">

# AgenticOps Platform

**An agentic incident-operations platform** — AI agents that investigate incidents, propose root cause, and execute governed remediation through no-code workflows, with humans in the loop.

<a href="#quick-start">Quick Start</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;<a href="#user-guide">User Guide</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;<a href="#deploy">Deploy</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;<a href="#integrations">Integrations</a>&nbsp;&nbsp;&bull;&nbsp;&nbsp;<a href="#architecture">Architecture</a>

</div>

---

## What it is

AgenticOps turns alerts into resolved incidents with AI doing the heavy lifting and humans approving anything risky:

- **Investigates autonomously** — on an alert, specialist agents fan out across your logs, metrics, traces, cloud, and recent changes and return a structured root-cause analysis with evidence.
- **Acts safely** — build **no-code agentic workflows** (a node-graph builder) that branch, call tools/APIs, run agents, and **pause for human approval** before anything changes your systems.
- **Learns** — every postmortem and discovery finding flows into a searchable **Knowledge Base / Org Brain** that future investigations reuse.
- **Governed & multi-tenant** — per-org RBAC, policy gates, audit trails, secrets in Vault, row-level data isolation.

> One hard rule: **agents investigate and propose autonomously, but anything that changes your systems requires human approval first.**

---

## Quick Start

Run locally in a few minutes:

```bash
git clone <your-repo-url> && cd aurora

make init                # Generate secure secrets
nano .env                # Add your LLM API key (OpenAI, Anthropic, OpenRouter, …) + set MAIN_MODEL/RCA_MODEL
make prod-prebuilt       # Pull prebuilt images and start  (or: make prod-local to build from source)
```

Open **http://localhost:3000** — the first user to register becomes admin. Only an LLM API key is required; connectors are optional.

<details>
<summary><strong>Vault setup (required after first start)</strong></summary>

```bash
docker logs vault-init 2>&1 | grep "Root Token:"   # get the auto-generated root token
echo "VAULT_TOKEN=hvs.your-token-here" >> .env       # add it to .env
make down && make prod-prebuilt                       # restart to connect services to Vault
```
</details>

<details>
<summary><strong>Workflows engine (Temporal) — optional</strong></summary>

The node-graph Workflows run on Temporal via an opt-in overlay:

```bash
docker compose -p agenticops-temporal -f docker-compose.temporal.yml up -d
# set TEMPORAL_ADDRESS=temporal:7233 in .env so the app can start/route workflow runs
```
</details>

---

## User Guide

Everything below is a page in the left navigation. Agents investigate and propose; humans approve changes.

### 🗨️ New Chat
The conversational ops agent. Ask it to investigate an incident, query your stack, or run automation. It uses your connected tools and, during root-cause analysis, dispatches specialist **investigator sub-agents**. It can also **launch workflows and quick actions** on request (e.g. *"run the DB triage workflow for incident 123"*).

### 🚨 Incidents
The incident dashboard. Each incident has the AI **root-cause analysis**, an **Evidence & Replay** panel (every tool call and finding, replayable), the **infrastructure blast-radius** view, and an **auto-generated postmortem**. Incidents arrive from connected monitors/webhooks or can be created manually.

### 🤖 Agents
The specialist agent registry:
- **RCA investigators** (`general_investigator`, `runtime_state_investigator`, `recent_change_investigator`, `error_signal_investigator`, `ticket_history`, `runbook_lookup`) — dispatched during RCA.
- **Lifecycle agents** (`summarizer`, `correlation`, `dedup`, `remediation_planner`, `runbook_executor`, `notification`, `postmortem`) — fired by the trigger router on incident events.

Built-ins are code-defined (view-only prompts) but you can **enable/disable** them per org, set **prompt versions** (investigators), and **create your own custom agents** with capability tags.

### ⚡ Quick Actions
One-click, governed operations — run a single specialist agent on an incident (e.g. *Generate Incident Summary, Investigate Root Cause, Runtime Health Check, Recommend Remediation*). Reusable from incidents, from chat, and as **action nodes** inside workflows.

### 🧩 Workflows (Flow Builder)
A visual **node-graph builder** for agentic automations. Open **Workflows** for the dashboard (every workflow with status, last-run, run count, and Run / Pause / Edit / Delete), then **New workflow** to author on the canvas.

**Node types:**
| Node | What it does |
|---|---|
| **agent** | Runs a specialist agent; the **Purpose** field steers which tools/focus it uses |
| **action** | Runs an Aurora Quick Action (deterministic) |
| **http** | Calls any API / runbook / automation endpoint |
| **set** | Builds/reshapes data (key→value, expressions) |
| **if / switch / merge** | Branching and joining |
| **foreach** | Iterates over a list |
| **approval / form / wait** | Human-in-the-loop pauses (approve, collect input, timer, webhook) |
| **sub_workflow** | Runs another workflow as a child and returns its output |

**Authoring:** drag from a node's right handle to the next node's left handle to connect; click a node for typed config; click an edge to set a branch port (`true`/`false`/case); **Tidy** auto-lays-out the graph. Use **expressions** like `{{ $node.X.output.summary }}` and `{{ $context.incident_id }}` to pass data between nodes.

**Per-workflow:** schedule (cron) + webhook triggers, an **On error → workflow** handler, and an **RCA enrichment** flag (read-only workflows the RCA agent may auto-run during investigation). **Run** executes it; watch progress in **Runs**.

### 🔀 Triggers
Route incident **lifecycle events** (alert created, incident created, RCA completed, resolved) to **agents** or **workflows** automatically — optionally filtered by severity.

### 🕘 Runs
Execution history across all workflows — status, last-run time, and a per-node **replay** timeline (input/output/status) for debugging.

### ✅ Approvals
The human-in-the-loop inbox. When a workflow or an agent hits a risk gate, it pauses here; approving **resumes the exact run** (single-use, time-bounded).

### 🧠 Knowledge Base · Org Brain
Everything the platform has learned, searchable and reused by agents during RCA:
- **Org memory** — free-text context about your org/systems.
- **Documents** — upload runbooks, architecture docs, SOPs.
- **Discovery findings** — auto-captured during investigations.
- **Postmortems** — every solved incident's postmortem is auto-ingested, so future RCAs reuse past learnings.

### 🔌 MCP
Register external **MCP tool servers** (e.g. read-only docs/knowledge servers); their tools are discovered and made available, with read-only enforcement.

### Connectors & Settings
Connect cloud (AWS/Azure/GCP), monitoring (Datadog/Grafana/New Relic/…), ITSM/on-call (PagerDuty/OpsGenie/ServiceNow), source control, and chat (Slack/Google Chat). Credentials are stored per-user in Vault. A light/dark theme toggle lives in the nav footer.

---

## Deploy

| Method | Best for |
|--------|----------|
| `make prod-prebuilt` | Local evaluation, single-node |
| `make prod-local` | Build from source (feature branches, custom builds) |
| Helm chart | Production Kubernetes (GKE, EKS, AKS) |

```bash
helm repo add aurora https://raw.githubusercontent.com/Arvo-AI/aurora/gh-pages
helm repo update && helm show values aurora/aurora-oss > my-values.yaml
helm install aurora-oss aurora/aurora-oss -n aurora --create-namespace -f my-values.yaml
```

Keep environment variables in sync across `docker-compose.yaml`, `docker-compose.prod-local.yml`, and `.env.example`.

---

## Integrations

<div align="center">

![PagerDuty](https://img.shields.io/badge/PagerDuty-06AC38?style=flat-square&logo=pagerduty&logoColor=white)
![Datadog](https://img.shields.io/badge/Datadog-632CA6?style=flat-square&logo=datadog&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat-square&logo=grafana&logoColor=white)
![New Relic](https://img.shields.io/badge/New_Relic-1CE783?style=flat-square&logo=newrelic&logoColor=white)
![OpsGenie](https://img.shields.io/badge/OpsGenie-0052CC?style=flat-square&logo=opsgenie&logoColor=white)
![Dynatrace](https://img.shields.io/badge/Dynatrace-1496FF?style=flat-square&logo=dynatrace&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-232F3E?style=flat-square&logo=amazonwebservices&logoColor=white)
![Azure](https://img.shields.io/badge/Azure-0078D4?style=flat-square&logo=microsoftazure&logoColor=white)
![GCP](https://img.shields.io/badge/GCP-4285F4?style=flat-square&logo=googlecloud&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?style=flat-square&logo=kubernetes&logoColor=white)
![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white)
![Slack](https://img.shields.io/badge/Slack-4A154B?style=flat-square&logo=slack&logoColor=white)
![Jira](https://img.shields.io/badge/Jira-0052CC?style=flat-square&logo=jira&logoColor=white)
![Splunk](https://img.shields.io/badge/Splunk-000000?style=flat-square&logo=splunk&logoColor=white)

**LLMs:** OpenAI · Anthropic · Google Gemini · Vertex AI · AWS Bedrock · OpenRouter · Ollama (air-gapped) &nbsp;|&nbsp; **MCP** tool servers

</div>

---

## Architecture

- **Backend** (`server/`) — Flask API (`main_compute.py`), Celery workers, WebSocket chatbot (`main_chatbot.py`), LangGraph agent + RCA orchestrator, connectors.
- **Workflows V2** (`server/workflows_v2/`) — a generic interpreter that executes node-graph workflows on **Temporal** (durable runs, timers, signals for HITL, retries, child workflows).
- **Frontend** (`client/`) — Next.js 15 + TypeScript + Tailwind + shadcn/ui; the Flow Builder uses React Flow.
- **Data** — PostgreSQL (with row-level security), Weaviate (Knowledge Base vectors), Redis (queue), Memgraph (infra graph), SeaweedFS (object storage), HashiCorp Vault (secrets).

---

## Security & Privacy

- **Self-hosted** — your incident data stays in your infrastructure; no telemetry.
- **Per-org isolation** — PostgreSQL `FORCE ROW LEVEL SECURITY` scopes every tenant's data.
- **Secrets in Vault** — credentials are never stored in the database.
- **Governed actions** — RBAC on every route; risk-classified tools; human approval gates for anything that changes systems; full audit trail.

---

## Credits & License

Built on **[Aurora](https://github.com/Arvo-AI/aurora)** by Arvo AI (Apache-2.0); the AgenticOps platform, node-graph Workflows, and Knowledge Base extensions build on that foundation. Licensed under **Apache 2.0** — see [LICENSE](LICENSE).
