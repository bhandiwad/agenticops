"""Shared operational stats — usable from both Flask routes and the agent runtime.

Both functions set RLS context explicitly via ``set_rls_context`` so they work outside
a Flask request (e.g. when called from an agent tool in the chatbot/worker).
"""

from __future__ import annotations

import logging

from utils.db.connection_pool import db_pool
from utils.auth.stateless_auth import set_rls_context

logger = logging.getLogger(__name__)

_PERIOD_MAP = {"7d": "7 days", "30d": "30 days", "90d": "90 days", "180d": "180 days", "365d": "365 days"}


def period_interval(period: str) -> str:
    return _PERIOD_MAP.get(period, "30 days")


def _total(d: dict) -> int:
    return sum(d.values())


def _success_rate(d: dict) -> float:
    t = _total(d)
    ok = sum(v for k, v in d.items() if str(k).lower() in (
        "completed", "succeeded", "success", "ok", "complete", "done", "approved"))
    return round(ok / t * 100, 1) if t else 0


def ops_summary(user_id: str, period: str = "30d") -> dict:
    """Workflow / action / agent run throughput + approvals (RLS-scoped)."""
    interval = period_interval(period)
    with db_pool.get_user_connection() as conn:
        cur = conn.cursor()
        set_rls_context(cur, conn, user_id, log_prefix="[OpsStats]")

        cur.execute("SELECT status, COUNT(*) FROM workflow_runs WHERE started_at >= NOW() - %s::interval GROUP BY status", (interval,))
        wf = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT workflow_key, COUNT(*) FROM workflow_runs WHERE started_at >= NOW() - %s::interval GROUP BY workflow_key ORDER BY COUNT(*) DESC LIMIT 8", (interval,))
        wf_top = [{"workflow": r[0], "count": r[1]} for r in cur.fetchall()]
        cur.execute("SELECT DATE_TRUNC('day', started_at)::date AS d, COUNT(*), COUNT(*) FILTER (WHERE status IN ('failed','error','timed_out')) FROM workflow_runs WHERE started_at >= NOW() - %s::interval GROUP BY d ORDER BY d", (interval,))
        wf_over_time = [{"date": str(r[0]), "runs": r[1], "failed": r[2]} for r in cur.fetchall()]

        cur.execute("SELECT status, COUNT(*) FROM action_runs WHERE started_at >= NOW() - %s::interval GROUP BY status", (interval,))
        act = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("SELECT status, COUNT(*) FROM workflow_node_runs WHERE created_at >= NOW() - %s::interval AND node_type = 'agent' GROUP BY status", (interval,))
        agent = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("SELECT status, COUNT(*) FROM approvals WHERE created_at >= NOW() - %s::interval GROUP BY status", (interval,))
        appr = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'")
        appr_pending = cur.fetchone()[0]

    return {
        "workflows": {"byStatus": wf, "total": _total(wf), "successRate": _success_rate(wf), "overTime": wf_over_time, "top": wf_top},
        "actions": {"byStatus": act, "total": _total(act), "successRate": _success_rate(act)},
        "agents": {"byStatus": agent, "total": _total(agent), "successRate": _success_rate(agent)},
        "approvals": {"byStatus": appr, "pending": appr_pending, "total": _total(appr)},
    }


def incident_summary(user_id: str, period: str = "30d") -> dict:
    """Incident volume + MTTD/MTTA/MTTR + top services (RLS-scoped)."""
    interval = period_interval(period)
    with db_pool.get_user_connection() as conn:
        cur = conn.cursor()
        set_rls_context(cur, conn, user_id, log_prefix="[OpsStats]")

        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE started_at >= NOW() - %s::interval) AS total,
              COUNT(*) FILTER (WHERE status IN ('investigating','analyzed') AND aurora_status NOT IN ('complete','resolved')) AS active,
              COUNT(*) FILTER (WHERE status = 'resolved' AND started_at >= NOW() - %s::interval) AS resolved,
              COUNT(*) FILTER (WHERE status = 'analyzed' AND started_at >= NOW() - %s::interval) AS analyzed,
              AVG(EXTRACT(EPOCH FROM (resolved_at - started_at))) FILTER (WHERE resolved_at IS NOT NULL AND started_at >= NOW() - %s::interval) AS mttr,
              AVG(EXTRACT(EPOCH FROM (analyzed_at - started_at))) FILTER (WHERE analyzed_at IS NOT NULL AND started_at >= NOW() - %s::interval) AS mtta,
              AVG(EXTRACT(EPOCH FROM (investigation_started_at - started_at))) FILTER (WHERE investigation_started_at IS NOT NULL AND started_at >= NOW() - %s::interval) AS mttd
            FROM incidents
            """,
            (interval, interval, interval, interval, interval, interval),
        )
        row = cur.fetchone()

        cur.execute(
            "SELECT alert_service, COUNT(*) AS c FROM incidents "
            "WHERE started_at >= NOW() - %s::interval AND alert_service IS NOT NULL AND status != 'merged' "
            "GROUP BY alert_service ORDER BY c DESC LIMIT 10", (interval,))
        top_services = [{"service": r[0], "count": r[1]} for r in cur.fetchall()]

    def _sec(v):
        return round(v, 1) if v else None

    return {
        "total": row[0] or 0, "active": row[1] or 0, "resolved": row[2] or 0, "analyzed": row[3] or 0,
        "avgMttrSeconds": _sec(row[4]), "avgMttaSeconds": _sec(row[5]), "avgMttdSeconds": _sec(row[6]),
        "topServices": top_services,
    }
