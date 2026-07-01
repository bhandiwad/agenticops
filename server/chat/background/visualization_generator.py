"""Celery task for incremental visualization generation."""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import redis

from celery_config import celery_app
from chat.background.visualization_extractor import VisualizationData, VisualizationExtractor
from utils.db.connection_pool import db_pool
from utils.cache.redis_client import get_redis_client
from utils.auth.stateless_auth import set_rls_context
from chat.backend.constants import MAX_TOOL_OUTPUT_CHARS, INFRASTRUCTURE_TOOLS

logger = logging.getLogger(__name__)
_LOG_PREFIX = "[Visualization]"


def _get_affected_service(incident_id: str, user_id: str) -> str:
    """Best-effort: the incident's affected service/entity (seed for the topology)."""
    try:
        with db_pool.get_user_connection() as conn:
            cur = conn.cursor()
            set_rls_context(cur, conn, user_id, log_prefix=_LOG_PREFIX)
            cur.execute("SELECT alert_service, alert_title FROM incidents WHERE id = %s", (incident_id,))
            row = cur.fetchone()
        if not row:
            return ""
        return (row[0] or row[1] or "").strip()
    except Exception:  # noqa: BLE001
        logger.warning(f"{_LOG_PREFIX} could not resolve affected service for {incident_id}", exc_info=True)
        return ""


def _merge_graph_and_llm(graph_viz: VisualizationData, llm_viz: VisualizationData) -> VisualizationData:
    """Use the discovered graph as the trusted structure; overlay LLM-derived statuses onto
    matching nodes (by normalized name). LLM-only nodes/edges are intentionally NOT added —
    the graph is authoritative for structure, so we never show invented topology as fact."""
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    status_by_name = {}
    for n in (llm_viz.nodes or []):
        if n.status and n.status != "investigating":
            status_by_name.setdefault(_norm(n.label), n.status)
            status_by_name.setdefault(_norm(n.id), n.status)

    for gn in graph_viz.nodes:
        st = status_by_name.get(_norm(gn.label)) or status_by_name.get(_norm(gn.id))
        if st:
            gn.status = st

    # Carry over the LLM's root-cause hint only if it maps to a graph node.
    graph_ids = {n.id for n in graph_viz.nodes}
    if llm_viz.rootCauseId and llm_viz.rootCauseId in graph_ids:
        graph_viz.rootCauseId = llm_viz.rootCauseId
    return graph_viz

# Module-level singleton extractor (reuses LLM client across invocations)
_extractor: Optional[VisualizationExtractor] = None

def _get_extractor() -> VisualizationExtractor:
    """Get or create the singleton VisualizationExtractor."""
    global _extractor
    if _extractor is None:
        _extractor = VisualizationExtractor()
        logger.info(f"{_LOG_PREFIX} Created singleton VisualizationExtractor")
    return _extractor


@celery_app.task(
    bind=True,
    max_retries=1,
    name="chat.background.update_visualization",
    time_limit=120,  # Increased from 30s to 120s for LLM processing
    soft_time_limit=100,
)
def update_visualization(
    self,
    incident_id: str,
    user_id: str,
    session_id: str,
    force_full: bool = False,
    tool_calls_json: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate or update visualization for an RCA incident.
    
    Args:
        incident_id: UUID of the incident
        user_id: User performing the RCA
        session_id: Chat session ID
        force_full: If True, process all available context (final viz)
        tool_calls_json: JSON string of recent tool calls to process
    """
    logger.info(f"{_LOG_PREFIX} Starting update for incident {incident_id} (force_full={force_full})")

    # Hook: check if LLM call is allowed
    from utils.hooks import get_hook
    from utils.auth.stateless_auth import get_org_id_for_user
    hook_allowed, hook_message = get_hook("before_llm_call")(get_org_id_for_user(user_id), user_id)
    if not hook_allowed:
        logger.warning(f"{_LOG_PREFIX} Hook blocked for user {user_id}: {hook_message}")
        return {"incident_id": incident_id, "status": "hook_blocked", "error": hook_message}

    try:
        # Get recent tool calls
        if tool_calls_json:
            tool_calls = json.loads(tool_calls_json)
            logger.info(f"{_LOG_PREFIX} Using {len(tool_calls)} tool calls from parameters")
        else:
            tool_calls = _fetch_recent_tool_calls(session_id, user_id, limit=10 if not force_full else 50)
            logger.info(f"{_LOG_PREFIX} Fetched {len(tool_calls)} tool calls from llm_context_history")
        
        if not tool_calls:
            return {"status": "skipped", "reason": "no_tool_calls"}
        
        existing_viz = _fetch_existing_visualization(incident_id, user_id)
        
        extractor = _get_extractor()
        llm_viz = extractor.extract_incremental(
            tool_calls, existing_viz, is_final=force_full,
            user_id=user_id, session_id=session_id,
        )

        # Base the topology on the DISCOVERED infrastructure graph (trusted source of truth);
        # the LLM only annotates node statuses. Falls back to LLM-only when the graph has
        # nothing for this incident's entity (e.g. discovery hasn't run / unknown service).
        # Trusted-topology priority: CloudFabrix (richest, real CMDB-style topology) →
        # discovered cloud graph → LLM-only fallback. The LLM only overlays statuses.
        updated_viz = llm_viz
        try:
            from chat.background.graph_topology import (
                build_topology_from_cfx, build_topology_from_cmdb, build_topology_from_iac,
                build_topology_from_graph, build_topology_from_monitoring, build_topology_from_kb,
            )
            affected = _get_affected_service(incident_id, user_id)
            # Trust order: CFX → CMDB → IaC (declared) → discovered cloud → monitoring (observed)
            # → KB (inferred). First source with a topology wins; the LLM only overlays statuses.
            resolvers = [
                ("cfx", lambda: build_topology_from_cfx(incident_id, user_id)),
                ("cmdb", lambda: build_topology_from_cmdb(incident_id, user_id)),
                ("iac", lambda: build_topology_from_iac(user_id, affected, incident_id)),
                ("discovered", lambda: build_topology_from_graph(user_id, affected, incident_id)),
                ("monitoring", lambda: build_topology_from_monitoring(user_id, affected, incident_id)),
                ("kb", lambda: build_topology_from_kb(user_id, affected, incident_id)),
            ]
            base, base_src = None, None
            for name, fn in resolvers:
                base = fn()
                if base and base.nodes:
                    base_src = name
                    break
            if base and base.nodes:
                updated_viz = _merge_graph_and_llm(base, llm_viz)
                updated_viz.version = llm_viz.version
                logger.info(f"{_LOG_PREFIX} Using {base_src} topology "
                            f"({len(updated_viz.nodes)} nodes) for incident {incident_id}")
        except Exception:
            logger.warning(f"{_LOG_PREFIX} graph topology merge failed; using LLM-only", exc_info=True)

        if not updated_viz.nodes:
            logger.warning(f"{_LOG_PREFIX} No entities extracted for incident {incident_id}")
            return {"status": "skipped", "reason": "no_entities"}
        
        # Post-process: Remove 'investigating' status from final visualization
        if force_full:
            investigating_count = 0
            for node in updated_viz.nodes:
                if node.status == 'investigating':
                    node.status = 'unknown'
                    investigating_count += 1
            
            if investigating_count > 0:
                logger.info(f"{_LOG_PREFIX} Converted {investigating_count} 'investigating' nodes to 'unknown' in final visualization")
        
        validated_json = updated_viz.model_dump_json(indent=2)
        _store_visualization(incident_id, validated_json, user_id)
        _notify_sse_clients(incident_id, updated_viz.version)
        
        logger.info(
            f"{_LOG_PREFIX} Updated incident {incident_id}: "
            f"v{updated_viz.version}, {len(updated_viz.nodes)} nodes, {len(updated_viz.edges)} edges"
        )
        
        return {
            "status": "success",
            "version": updated_viz.version,
            "nodes": len(updated_viz.nodes),
            "edges": len(updated_viz.edges),
        }
    
    except Exception as e:
        logger.error(f"{_LOG_PREFIX} Update failed for incident {incident_id}: {e}")
        return {"status": "error", "error": str(e)}


def _fetch_recent_tool_calls(session_id: str, user_id: str, limit: int = 10) -> List[Dict]:
    """Fetch recent infrastructure tool calls for an RCA session.

    For orchestrator (fanout) RCAs, the parent session's llm_context_history
    is empty — all tool calls live under child session_ids like
    `{parent}::sa_N` / `{parent}::sa_wN_M`. We aggregate from execution_steps
    so the final visualization has the data it needs.
    """
    try:
        with db_pool.get_admin_connection() as conn:
            with conn.cursor() as cursor:
                if not set_rls_context(cursor, conn, user_id, log_prefix=_LOG_PREFIX):
                    return []

                # Parent session's llm_context_history (single-agent path)
                parent_calls: List[Dict] = []
                cursor.execute(
                    "SELECT llm_context_history FROM chat_sessions WHERE id = %s",
                    (session_id,),
                )
                row = cursor.fetchone()
                if row and row[0]:
                    llm_context = row[0]
                    if isinstance(llm_context, str):
                        llm_context = json.loads(llm_context)
                    for msg in llm_context:
                        if isinstance(msg, dict) and msg.get('name') in INFRASTRUCTURE_TOOLS:
                            parent_calls.append({
                                'tool': msg.get('name'),
                                'output': str(msg.get('content', ''))[:MAX_TOOL_OUTPUT_CHARS],
                            })

                # Child sub-agent sessions (orchestrator fanout path).
                # session_id format: `{parent}::{agent_id}` (e.g. `{uuid}::sa_1`,
                # `{uuid}::sa_w2_1`). execution_steps is the canonical store of
                # tool invocations and is indexed on session_id. Bound the query
                # so it doesn't scale with RCA history — fetch the most recent
                # `limit` rows and reverse to chronological order for the
                # visualization extractor.
                child_calls: List[Dict] = []
                # Prefix range scan over the `{parent}::` namespace — index-friendly
                # and immune to wildcards in session_id (LIKE would mismatch on `%`/`_`).
                # Upper bound replaces the final `:` with `;` (next ASCII codepoint),
                # making it the smallest string strictly greater than every `{sid}::*`.
                child_lo = f"{session_id}::"
                child_hi = f"{session_id}:;"
                cursor.execute(
                    """
                    SELECT tool_name, tool_output
                      FROM execution_steps
                     WHERE session_id >= %s AND session_id < %s
                       AND tool_name = ANY(%s)
                     ORDER BY created_at DESC
                     LIMIT %s
                    """,
                    (child_lo, child_hi, list(INFRASTRUCTURE_TOOLS), limit),
                )
                for tname, toutput in reversed(cursor.fetchall()):
                    child_calls.append({
                        'tool': tname,
                        'output': str(toutput or '')[:MAX_TOOL_OUTPUT_CHARS],
                    })

        combined = parent_calls + child_calls
        if not combined:
            logger.warning(
                f"{_LOG_PREFIX} No tool calls found for session {session_id} (parent or children)"
            )
            return []

        logger.info(
            f"{_LOG_PREFIX} Fetched {len(parent_calls)} parent + {len(child_calls)} child "
            f"infrastructure tool calls for session {session_id}"
        )
        return combined[-limit:]

    except Exception as e:
        logger.error(f"{_LOG_PREFIX} Failed to fetch tool calls: {e}")
        return []


def _fetch_existing_visualization(incident_id: str, user_id: str) -> Optional[VisualizationData]:
    """Fetch current visualization from incidents table."""
    try:
        with db_pool.get_admin_connection() as conn:
            with conn.cursor() as cursor:
                if not set_rls_context(cursor, conn, user_id, log_prefix=_LOG_PREFIX):
                    return None
                cursor.execute("""
                    SELECT visualization_code
                    FROM incidents
                    WHERE id = %s
                """, (incident_id,))
                
                row = cursor.fetchone()
        
        if row and row[0]:
            return VisualizationData.model_validate_json(row[0])
        
        return None
    
    except Exception as e:
        logger.error(f"{_LOG_PREFIX} Failed to fetch existing viz: {e}")
        return None


def _store_visualization(incident_id: str, json_str: str, user_id: str):
    """Store updated visualization in database."""
    try:
        with db_pool.get_admin_connection() as conn:
            with conn.cursor() as cursor:
                if not set_rls_context(cursor, conn, user_id, log_prefix=_LOG_PREFIX):
                    raise RuntimeError(f"Cannot resolve org_id for user {user_id}")
                cursor.execute("""
                    UPDATE incidents
                    SET visualization_code = %s,
                        visualization_updated_at = %s
                    WHERE id = %s
                """, (json_str, datetime.now(timezone.utc), incident_id))
                conn.commit()
    
    except Exception as e:
        logger.error(f"{_LOG_PREFIX} Failed to store viz: {e}")
        raise


def _notify_sse_clients(incident_id: str, version: int):
    """Notify SSE listeners via Redis pub/sub."""
    try:
        redis_client = get_redis_client()
        if not redis_client:
            logger.warning(f"{_LOG_PREFIX} Redis unavailable, skipping SSE notification")
            return
        
        channel = f"visualization:{incident_id}"
        message = json.dumps({"type": "update", "version": version})
        redis_client.publish(channel, message)
    except Exception as e:
        logger.warning(f"{_LOG_PREFIX} Failed to notify SSE clients: {e}")
