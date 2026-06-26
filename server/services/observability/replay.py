"""Run replay: reconstruct the ordered tool-execution timeline of an agent run
from the existing ``execution_steps`` table (tool name, input, output, status,
timing), for debugging/replay in the UI. Read-only."""

import logging
from typing import List

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)


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
