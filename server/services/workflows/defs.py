"""CRUD for Workflow V2 graph definitions + run/node-run reads for the editor and
run inspector. Pure DB (RLS-scoped); no Temporal dependency.

A def is a node-graph stored in ``workflow_defs.graph`` (JSONB):
``{"nodes": [{id,type,ref,config,position,label}], "edges": [{source,target,port}]}``.
Single mutable version (1) per (org, key) — versioning history is a later concern.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import List, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger("workflows.defs")

_KEY_OK = __import__("re").compile(r"^[a-z][a-z0-9_]{1,63}$")


def list_defs(user_id: str, org_id: str) -> List[dict]:
    """All defs for the org, enriched with last-run status/time + run count for the
    dashboard."""
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[wf2:list_defs]")
            cur.execute(
                """SELECT d.key, d.name, d.graph, d.enabled, d.updated_at,
                          lr.status, lr.started_at, COALESCE(rc.cnt, 0)
                   FROM workflow_defs d
                   LEFT JOIN LATERAL (
                       SELECT status, started_at FROM workflow_runs r
                       WHERE r.org_id = d.org_id AND r.workflow_key = d.key
                       ORDER BY started_at DESC LIMIT 1
                   ) lr ON true
                   LEFT JOIN LATERAL (
                       SELECT COUNT(*) cnt FROM workflow_runs r
                       WHERE r.org_id = d.org_id AND r.workflow_key = d.key
                   ) rc ON true
                   WHERE d.org_id = %s
                   ORDER BY d.updated_at DESC""",
                (org_id,),
            )
            rows = cur.fetchall()
    out = []
    for r in rows:
        graph = r[2] if isinstance(r[2], dict) else (json.loads(r[2]) if r[2] else {})
        out.append({
            "key": r[0], "name": r[1], "graph": graph, "enabled": r[3],
            "updated_at": r[4].isoformat() if r[4] else None,
            "node_count": len(graph.get("nodes", [])),
            "last_run_status": r[5],
            "last_run_at": r[6].isoformat() if r[6] else None,
            "run_count": r[7],
        })
    return out


def set_enabled(user_id: str, org_id: str, key: str, enabled: bool) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[wf2:set_enabled]")
            cur.execute(
                "UPDATE workflow_defs SET enabled = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE org_id = %s AND key = %s",
                (enabled, org_id, key),
            )
            updated = cur.rowcount > 0
            conn.commit()
    return updated


def get_def(user_id: str, org_id: str, key: str) -> Optional[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[wf2:get_def]")
            cur.execute(
                "SELECT key, name, graph, enabled FROM workflow_defs WHERE org_id = %s AND key = %s "
                "ORDER BY version DESC LIMIT 1",
                (org_id, key),
            )
            r = cur.fetchone()
    if not r:
        return None
    graph = r[2] if isinstance(r[2], dict) else (json.loads(r[2]) if r[2] else {})
    return {"key": r[0], "name": r[1], "graph": graph, "enabled": r[3]}


def upsert_def(user_id: str, org_id: str, *, key: str, name: str, graph: dict) -> None:
    if not _KEY_OK.match(key or ""):
        raise ValueError("key must be lowercase snake_case (2-64 chars)")
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        raise ValueError("graph must be an object with a nodes array")
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[wf2:upsert_def]")
            cur.execute(
                "INSERT INTO workflow_defs (id, org_id, key, name, version, graph, created_by) "
                "VALUES (%s,%s,%s,%s,1,%s,%s) "
                "ON CONFLICT (org_id, key, version) DO UPDATE "
                "SET name = EXCLUDED.name, graph = EXCLUDED.graph, updated_at = CURRENT_TIMESTAMP",
                (str(uuid.uuid4()), org_id, key, name or key, json.dumps(graph), user_id),
            )
            conn.commit()


def seed_builtin_defs(user_id: str, org_id: str) -> None:
    """Seed built-in workflow templates for an org if they don't already exist.

    Idempotent and non-destructive: a template is only inserted when its key is absent, so a
    user's edits to a seeded workflow are never clobbered on re-seed. Called lazily when the
    workflow list is fetched, so shipped templates (e.g. the FortiGate open-port workflow)
    appear automatically without a migration.
    """
    try:
        from workflows_v2.sample_graphs import (
            FIREWALL_OPEN_PORT, BACKUP_VM, WINDOWS_PATCH, VM_TROUBLESHOOT,
            AD_BULK_USER_ADD, AD_REPLICATION_HEALTH, VM_THRESHOLD_REMEDIATION, TOPOLOGY_REFRESH,
        )
    except Exception:  # noqa: BLE001 - never block listing on a template import
        return
    for tmpl in (FIREWALL_OPEN_PORT, BACKUP_VM, WINDOWS_PATCH, VM_TROUBLESHOOT,
                 AD_BULK_USER_ADD, AD_REPLICATION_HEALTH, VM_THRESHOLD_REMEDIATION, TOPOLOGY_REFRESH):
        try:
            if get_def(user_id, org_id, tmpl["key"]) is None:
                upsert_def(user_id, org_id, key=tmpl["key"], name=tmpl["name"], graph=tmpl)
                logger.info("wf2: seeded built-in workflow %r for org %s", tmpl["key"], org_id)
        except Exception:  # noqa: BLE001 - a bad template must not break the list
            logger.exception("wf2: failed to seed built-in workflow %r", tmpl.get("key"))


def delete_def(user_id: str, org_id: str, key: str) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[wf2:delete_def]")
            cur.execute("DELETE FROM workflow_defs WHERE org_id = %s AND key = %s", (org_id, key))
            deleted = cur.rowcount > 0
            conn.commit()
    return deleted


def list_runs(user_id: str, org_id: str, key: Optional[str] = None, limit: int = 50) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[wf2:list_runs]")
            if key:
                cur.execute(
                    "SELECT id, workflow_key, status, started_at, ended_at FROM workflow_runs "
                    "WHERE org_id = %s AND workflow_key = %s ORDER BY started_at DESC LIMIT %s",
                    (org_id, key, limit),
                )
            else:
                cur.execute(
                    "SELECT id, workflow_key, status, started_at, ended_at FROM workflow_runs "
                    "WHERE org_id = %s ORDER BY started_at DESC LIMIT %s",
                    (org_id, limit),
                )
            rows = cur.fetchall()
    return [{"id": str(r[0]), "workflow_key": r[1], "status": r[2],
             "started_at": r[3].isoformat() if r[3] else None,
             "ended_at": r[4].isoformat() if r[4] else None} for r in rows]


def get_run_nodes(user_id: str, org_id: str, run_id: str) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[wf2:run_nodes]")
            cur.execute(
                "SELECT node_id, node_type, status, input, output, created_at FROM workflow_node_runs "
                "WHERE run_id = %s AND org_id = %s ORDER BY created_at",
                (run_id, org_id),
            )
            rows = cur.fetchall()

    def _j(v):
        if v is None or isinstance(v, (dict, list)):
            return v
        try:
            return json.loads(v)
        except Exception:
            return v

    return [{"node_id": r[0], "node_type": r[1], "status": r[2],
             "input": _j(r[3]), "output": _j(r[4]),
             "created_at": r[5].isoformat() if r[5] else None} for r in rows]
