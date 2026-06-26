"""Run replay: reconstruct the ordered tool-execution timeline of an agent run
from the existing ``execution_steps`` table (tool name, input, output, status,
timing), for debugging/replay in the UI. Read-only."""

import logging
from typing import List

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)


def list_recent_runs(user_id: str, org_id: str, limit: int = 150) -> dict:
    """Cross-incident feed of recent agent/automation activity for the org.

    Merges recorded run evidence (agent dispatches, etc.) with a per-incident
    rollup of tool-execution steps so the Runs page can show what ran recently
    and link into each incident's replay. Read-only.
    """
    runs: List[dict] = []
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Runs:list]")
            # Recent recorded evidence (agent dispatches + artifacts).
            cur.execute(
                "SELECT id, incident_id, source, kind, title, created_at "
                "FROM run_evidence WHERE org_id = %s ORDER BY created_at DESC LIMIT %s",
                (org_id, limit),
            )
            for r in cur.fetchall():
                runs.append({
                    "id": str(r[0]),
                    "incident_id": str(r[1]) if r[1] else None,
                    "source": r[2], "kind": r[3], "title": r[4],
                    "created_at": r[5].isoformat() if r[5] else None,
                })
            # Per-incident tool-step counts for incidents with execution activity.
            cur.execute(
                "SELECT incident_id, COUNT(*), MAX(created_at) FROM execution_steps "
                "WHERE org_id = %s AND incident_id IS NOT NULL "
                "GROUP BY incident_id ORDER BY MAX(created_at) DESC LIMIT %s",
                (org_id, limit),
            )
            step_rollup = [
                {"incident_id": str(r[0]), "step_count": r[1],
                 "last_step_at": r[2].isoformat() if r[2] else None}
                for r in cur.fetchall()
            ]
    return {"runs": runs, "step_rollup": step_rollup}


def replay_incident(user_id: str, org_id: str, incident_id: str, limit: int = 500) -> List[dict]:
    """Return the ordered execution-step timeline for an incident's runs."""
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[Replay:incident]")
            cur.execute(
                """SELECT step_index, tool_name, tool_call_id, status, tool_input, tool_output, session_id
                   FROM execution_steps
                   WHERE org_id = %s AND incident_id = %s
                   ORDER BY step_index ASC LIMIT %s""",
                (org_id, incident_id, limit),
            )
            steps = []
            for r in cur.fetchall():
                output = r[5]
                steps.append({
                    "step_index": r[0],
                    "tool_name": r[1],
                    "tool_call_id": r[2],
                    "status": r[3],
                    "tool_input": r[4],
                    # Cap output so replay payloads stay bounded.
                    "tool_output": (output[:4000] if isinstance(output, str) else output),
                    "session_id": r[6],
                })
            return steps
