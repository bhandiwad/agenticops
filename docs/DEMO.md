# AgenticOps — End‑to‑End Demo Runbook

A single incident that exercises **chat → agent → tools → workflows → human approval → postmortem → Knowledge Base → dashboards → data‑aware chat**. ~10 minutes.

## Pre‑flight (already set up)
- **RCA‑enrichment workflow** `Incident Diagnostics (RCA enrichment)` — enabled, read‑only; **auto‑fires during every RCA**.
- **Remediation workflows with human approval** — `DB Problem: Triage & Remediate`, `VM Resource Crunch: Scale or Optimize`, `Network Link Down: Failover`, `Security Incident Response` (each has an **approval** gate + postmortem step).
- **AWS** connector is connected (gives investigators real tools). More tools available via the **MCP catalog**.

> Tip: phrase the trigger as a clear operational symptom tied to AWS so the agent calls `trigger_rca` and the investigators have relevant tools.

---

## Act 1 — Trigger from chat *(chat · agent · tool call)*
1. Open **New Chat**.
2. Type a symptom, e.g.:
   > *"payments‑api on prod is returning 5xx errors and latency spiked in the last 20 minutes — investigate."*
3. The agent calls the **`trigger_rca`** tool → creates an incident and dispatches a background RCA.
   **Show:** chat message → agent decides → tool invocation.

## Act 2 — RCA: agents + tools + a workflow firing itself *(agents · tools · workflows)*
4. Go to **Incidents** → open the new incident. Watch the **investigator sub‑agents** run (general, runtime‑state, recent‑change, error‑signal…) using **connected AWS tools**.
5. Open **Runs** → the **Incident Diagnostics (RCA enrichment)** workflow **auto‑fired** alongside the investigators (it has agent + merge nodes).
   **Show:** a workflow triggered automatically during RCA, not by a human.
6. Back on the incident → the **Root Cause Analysis** + **Evidence & Replay** populate (every tool call is replayable).

## Act 3 — Postmortem + Org Brain *(postmortem · Knowledge Base · learning loop)*
7. The incident gets an **auto‑generated postmortem**.
8. Open **Knowledge Base** → the postmortem has been **auto‑ingested** and is searchable.
   **Show:** the platform learns from every incident; future RCAs reuse it.

## Act 4 — Remediation with a human gate *(workflows · HITL · actions · durable resume)*
9. Open **Workflows** → **Run** `DB Problem: Triage & Remediate` (or `VM Resource Crunch`).
10. It investigates, then **pauses at an approval node**.
11. Go to **Approvals** → the pending request appears → **Approve**.
12. The workflow **resumes** (Temporal signal) and runs its remediation + notification steps to completion.
    **Show:** *nothing changes a system without explicit human approval*; the run is durable and resumes exactly where it paused.

## Act 5 — Dashboards reflect it all *(dashboards)*
13. Open **Dashboards**:
    - **Overview** — incident count, resolution rate, MTTR, change‑failure rate
    - **Volume / Response time / Reliability** — severity mix, MTTD/MTTA/MTTR, top services
    - **Operations** — workflow runs, action runs, agent runs, **approvals** (the one you just approved)

## Act 6 — Ask your data *(data‑aware chat)*
14. Click **Ask in chat** (top of Dashboards) and ask:
    > *"How many incidents in the last 7 days, what's our MTTR, and how many workflows ran?"*
15. The agent calls **`get_incident_stats`** / **`get_operations_stats`** and answers from the same live data the dashboards use.
    **Show:** one assistant that both *acts* and *reports* — no separate BI tool.

---

## Optional flourishes
- **Quick Actions** — run *Generate Incident Summary* on the incident (one‑click governed agent op).
- **MCP** — show the catalog (60+ pre‑built tool servers across cloud/network/DC/security/CMDB).
- **Triggers** — show event→agent/workflow routing (e.g. incident‑created → a workflow).
- **Theme** — light/dark toggle in the nav footer.

## If something looks quiet
- RCA runs in the background — give investigators ~30–60s.
- Workflows run on **Temporal**; the `aurora-temporal-worker` must be up.
- Keep the symptom AWS‑related (the only connected provider) so tools return data; otherwise the flow still completes, just with thinner evidence.
