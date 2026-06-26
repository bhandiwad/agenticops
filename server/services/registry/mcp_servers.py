"""Per-org registry of external MCP servers the agent may connect to.

Stores server *config* in the ``mcp_servers`` table (RLS); any auth token is
stored separately in Vault via the standard token helpers (never in the DB).
This is the configuration foundation — wiring the MCP client to actually
connect to registered servers (discovery + ToolSpec normalization) is a
follow-up that builds on these rows.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from utils.auth.stateless_auth import set_rls_context
from utils.db.connection_pool import db_pool

logger = logging.getLogger(__name__)

_VALID_TRANSPORTS = ("http", "sse", "stdio")
_COLS = ["id", "name", "transport", "url", "enabled", "read_only", "has_auth",
         "created_by", "created_at", "updated_at"]


def _vault_provider(name: str) -> str:
    return f"mcp_{name}"


def _row_to_dict(row) -> dict:
    d = dict(zip(_COLS, row))
    d["id"] = str(d["id"])
    for ts in ("created_at", "updated_at"):
        if d.get(ts):
            d[ts] = d[ts].isoformat()
    return d


def list_mcp_servers(user_id: str, org_id: str) -> List[dict]:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[MCPServers:list]")
            cur.execute(
                f"SELECT {', '.join(_COLS)} FROM mcp_servers WHERE org_id = %s ORDER BY name",
                (org_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def get_enabled_mcp_servers_safe(user_id: str) -> List[dict]:
    """Fail-safe: enabled registered MCP servers for the user's org. Used by the
    agent tool-loading path; never raises (returns [] on error)."""
    try:
        with db_pool.get_connection() as conn:
            with conn.cursor() as cur:
                org_id = set_rls_context(cur, conn, user_id, log_prefix="[MCPServers:enabled]")
                if not org_id:
                    return []
                cur.execute(
                    f"SELECT {', '.join(_COLS)} FROM mcp_servers "
                    "WHERE org_id = %s AND enabled = true ORDER BY name",
                    (org_id,),
                )
                return [_row_to_dict(r) for r in cur.fetchall()]
    except Exception as exc:  # pragma: no cover — defensive, fail open (no servers)
        logger.debug("get_enabled_mcp_servers_safe failed: %s", exc)
        return []


def get_server_auth_token(user_id: str, name: str) -> Optional[str]:
    """Retrieve a registered server's auth token from Vault, or None."""
    try:
        from utils.auth.token_management import get_token_data
        data = get_token_data(user_id, _vault_provider(name))
        if isinstance(data, dict):
            return data.get("token")
    except Exception as exc:
        logger.debug("get_server_auth_token failed for %s: %s", name, exc)
    return None


def create_mcp_server(
    user_id: str,
    org_id: str,
    *,
    name: str,
    transport: str = "http",
    url: Optional[str] = None,
    read_only: bool = True,
    auth_token: Optional[str] = None,
) -> str:
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(f"invalid transport: {transport}")
    has_auth = bool(auth_token)
    if has_auth:
        # Store the secret in Vault, never in the DB.
        from utils.auth.token_management import store_tokens_in_db
        store_tokens_in_db(user_id, {"token": auth_token}, _vault_provider(name))

    server_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[MCPServers:create]")
            cur.execute(
                """INSERT INTO mcp_servers
                       (id, org_id, name, transport, url, enabled, read_only, has_auth, created_by, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s)""",
                (server_id, org_id, name, transport, url, read_only, has_auth, user_id, now, now),
            )
            conn.commit()
    return server_id


def update_mcp_server(user_id: str, org_id: str, server_id: str, *, enabled: Optional[bool] = None,
                      read_only: Optional[bool] = None) -> bool:
    sets, params = [], []
    if enabled is not None:
        sets.append("enabled = %s")
        params.append(enabled)
    if read_only is not None:
        sets.append("read_only = %s")
        params.append(read_only)
    if not sets:
        return False
    sets.append("updated_at = %s")
    params.append(datetime.now(timezone.utc))
    params.extend([server_id, org_id])
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[MCPServers:update]")
            cur.execute(
                f"UPDATE mcp_servers SET {', '.join(sets)} WHERE id = %s AND org_id = %s",
                tuple(params),
            )
            updated = cur.rowcount
            conn.commit()
            return updated > 0


def delete_mcp_server(user_id: str, org_id: str, server_id: str) -> bool:
    with db_pool.get_connection() as conn:
        with conn.cursor() as cur:
            set_rls_context(cur, conn, user_id, log_prefix="[MCPServers:delete]")
            cur.execute(
                "SELECT name, has_auth FROM mcp_servers WHERE id = %s AND org_id = %s",
                (server_id, org_id),
            )
            row = cur.fetchone()
            if not row:
                return False
            name, has_auth = row[0], row[1]
            cur.execute(
                "DELETE FROM mcp_servers WHERE id = %s AND org_id = %s",
                (server_id, org_id),
            )
            conn.commit()
    if has_auth:
        try:
            from utils.secrets.secret_ref_utils import delete_user_secret
            delete_user_secret(user_id, _vault_provider(name))
        except Exception:
            logger.debug("delete_mcp_server: failed to delete vault secret (non-fatal)")
    return True
