"""Prometheus exposition endpoint for Aurora platform self-monitoring (epic #33).

Exposes a small set of high-value, aggregate-only platform gauges at GET /metrics
in Prometheus text exposition format. All values are org-agnostic aggregates — no
tenant-identifying labels or per-tenant rows are emitted.

RLS note: incidents / workflow_runs / approvals / llm_usage_tracking are all
RLS-protected (FORCE ROW LEVEL SECURITY). A single cross-org aggregate query would
silently return 0 rows. So we enumerate orgs from the non-RLS `organizations` table,
set the RLS context per org, and sum the per-org aggregates — matching the
"Cross-org tasks" pattern documented in CLAUDE.md. Results are cached ~30s so a
scrape burst can't hammer the DB.

Auth: this endpoint carries no RBAC decorator. It is protected by the global
INTERNAL_API_SECRET before_request gate in main_compute.py (it is NOT added to the
open-prefix allowlist), so only internal callers presenting X-Internal-Secret can
scrape it. It is allowlisted in tests/architectural/test_route_auth_coverage.py.

Out of scope for this cut (follow-ups): structured logging and OpenTelemetry tracing.
"""

import logging
import threading
import time

from flask import Blueprint, Response

from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)

platform_metrics_bp = Blueprint("platform_metrics", __name__)

# prometheus_client is declared in requirements.txt. Import defensively anyway so a
# missing/optional metrics dependency degrades /metrics to a 503 instead of crashing the
# whole app at blueprint-import time (this endpoint is peripheral to the core API).
try:
    from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when the optional dep is absent
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    CollectorRegistry = Gauge = generate_latest = None  # type: ignore[assignment]
    _PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed; GET /metrics will return 503")

_CACHE_TTL_SECONDS = 30
_cache_lock = threading.Lock()
_cache = {"expires_at": 0.0, "payload": b""}


def _collect_platform_stats() -> dict:
    """Collect aggregate platform stats across all orgs (RLS-safe, best-effort).

    Every sub-aggregate is wrapped so one failing query can't blank the whole
    scrape. Returns plain numbers; the caller renders them into gauges.
    """
    stats = {
        "incidents_24h": 0,
        "workflow_runs_24h": {},   # status -> count
        "approvals_pending": 0,
        "llm_cost_24h": 0.0,
        "db_pool_in_use": 0,
        "db_pool_max": db_pool.max_connections,
    }

    # DB pool in-use count from the live psycopg2 pool (no query needed).
    try:
        pool = db_pool._get_pool()
        stats["db_pool_in_use"] = len(getattr(pool, "_used", {}))
    except Exception as e:
        logger.warning("[PlatformMetrics] pool introspection failed: %s", e)

    try:
        with db_pool.get_connection() as conn:
            # Enumerate orgs (organizations is NOT RLS-protected).
            with conn.cursor() as cur:  # No RLS needed — organizations table
                cur.execute("SELECT id FROM organizations")
                org_ids = [r[0] for r in cur.fetchall()]

            wf_status_counts: dict[str, int] = {}
            for org_id in org_ids:
                cur = conn.cursor()
                try:
                    # Set RLS context for this org before touching RLS tables.
                    # We have org_id directly (not a user_id), so set the session
                    # var explicitly rather than resolving via set_rls_context.
                    cur.execute("SET myapp.current_org_id = %s;", (org_id,))

                    cur.execute(
                        "SELECT COUNT(*) FROM incidents WHERE started_at >= NOW() - INTERVAL '24 hours'"
                    )
                    stats["incidents_24h"] += cur.fetchone()[0] or 0

                    cur.execute(
                        "SELECT status, COUNT(*) FROM workflow_runs "
                        "WHERE started_at >= NOW() - INTERVAL '24 hours' GROUP BY status"
                    )
                    for status, count in cur.fetchall():
                        wf_status_counts[status or "unknown"] = (
                            wf_status_counts.get(status or "unknown", 0) + (count or 0)
                        )

                    cur.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'")
                    stats["approvals_pending"] += cur.fetchone()[0] or 0

                    cur.execute(
                        "SELECT COALESCE(SUM(total_cost_with_surcharge), 0) FROM llm_usage_tracking "
                        "WHERE created_at >= NOW() - INTERVAL '24 hours'"
                    )
                    stats["llm_cost_24h"] += float(cur.fetchone()[0] or 0)
                except Exception as e:
                    logger.warning("[PlatformMetrics] per-org aggregate failed for org: %s", e)
                    try:
                        conn.rollback()  # clear any aborted-transaction state before next org
                    except Exception:
                        pass
                finally:
                    cur.close()

            stats["workflow_runs_24h"] = wf_status_counts
    except Exception as e:
        logger.warning("[PlatformMetrics] aggregate collection failed: %s", e)

    return stats


def _render_metrics() -> bytes:
    """Render current platform stats into Prometheus text exposition format."""
    stats = _collect_platform_stats()
    registry = CollectorRegistry()

    g_incidents = Gauge(
        "aurora_incidents_total_24h",
        "Incidents created in the last 24h (all orgs)",
        registry=registry,
    )
    g_incidents.set(stats["incidents_24h"])

    g_wf = Gauge(
        "aurora_workflow_runs_24h",
        "Workflow runs in the last 24h by status (all orgs)",
        ["status"],
        registry=registry,
    )
    for status, count in stats["workflow_runs_24h"].items():
        g_wf.labels(status=status).set(count)

    g_approvals = Gauge(
        "aurora_approvals_pending",
        "Currently pending approvals (all orgs)",
        registry=registry,
    )
    g_approvals.set(stats["approvals_pending"])

    g_cost = Gauge(
        "aurora_llm_cost_usd_24h",
        "LLM cost (incl. surcharge) in the last 24h in USD (all orgs)",
        registry=registry,
    )
    g_cost.set(stats["llm_cost_24h"])

    g_pool_in_use = Gauge(
        "aurora_db_pool_connections_in_use",
        "Database connections currently checked out of the pool",
        registry=registry,
    )
    g_pool_in_use.set(stats["db_pool_in_use"])

    g_pool_max = Gauge(
        "aurora_db_pool_connections_max",
        "Maximum size of the database connection pool",
        registry=registry,
    )
    g_pool_max.set(stats["db_pool_max"])

    return generate_latest(registry)


@platform_metrics_bp.route("/metrics", methods=["GET"])
def metrics_prometheus():
    """Prometheus scrape endpoint (internal-secret gated, ~30s cached)."""
    if not _PROMETHEUS_AVAILABLE:
        return Response("prometheus_client not installed\n", status=503, mimetype="text/plain")

    now = time.monotonic()
    with _cache_lock:
        if now < _cache["expires_at"] and _cache["payload"]:
            payload = _cache["payload"]
        else:
            payload = None

    if payload is None:
        payload = _render_metrics()
        with _cache_lock:
            _cache["payload"] = payload
            _cache["expires_at"] = time.monotonic() + _CACHE_TTL_SECONDS

    return Response(payload, mimetype=CONTENT_TYPE_LATEST)
