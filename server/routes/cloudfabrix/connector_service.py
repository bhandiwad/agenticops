"""High-level CloudFabrix connector operations for agents, routes, and poll tasks."""
from __future__ import annotations

import logging
from typing import Any

from .cfx_client import CloudFabrixAPIError, CloudFabrixClient, get_client

logger = logging.getLogger(__name__)


def validate_credentials(client: CloudFabrixClient) -> dict[str, Any]:
    """Connectivity probe used by /connect and /status."""
    try:
        info = client.validate_connection()
        return {
            "ok": True,
            "apiBase": info.get("api_base"),
            "organizationCount": info.get("organization_count"),
            "sampleOrganization": info.get("sample_organization"),
        }
    except CloudFabrixAPIError as exc:
        return {"ok": False, "error": str(exc)}


def get_connector_config(user_id: str | None = None) -> dict[str, Any]:
    """Return connector settings for ingest/poll pipelines (agent-ready entrypoint)."""
    client = get_client(user_id)
    payload = client.to_token_payload()
    return {
        "status": "ok",
        "api_base": payload["api_base"],
        "api_token": payload["api_token"],
        "refresh_token": payload.get("refresh_token"),
        "refresh_url": payload.get("refresh_url"),
        "project_id": payload.get("project_id"),
        "customer_id": payload.get("customer_id"),
        "verify_ssl": payload.get("verify_ssl"),
        "topology_graph": payload.get("topology_graph"),
        "topology_db": payload.get("topology_db"),
        "relationship_map": payload.get("relationship_map"),
    }


def get_live_organizations(user_id: str | None = None) -> dict[str, Any]:
    """Optional live API read for agents (not the enriched local store)."""
    client = get_client(user_id)
    try:
        payload = client.get("/api/v2/organizations")
        orgs = client.rows(payload)
        return {"status": "ok", "count": len(orgs), "organizations": orgs[:20]}
    except CloudFabrixAPIError as exc:
        return {"error": str(exc)}
