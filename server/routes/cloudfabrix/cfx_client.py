"""CloudFabrix API client for the Aurora connector."""
from __future__ import annotations

import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 60
DEFAULT_TOPOLOGY_GRAPH = "cfx_rdaf_topology_graph"
DEFAULT_TOPOLOGY_DB = "cfx_rdaf_topology"
DEFAULT_RELATIONSHIP_MAP = "rdaf_topology_relationships"


class CloudFabrixAPIError(Exception):
    """Raised when a CloudFabrix API call fails."""


class CloudFabrixClient:
    """Thin wrapper around the CloudFabrix REST API (GET + token refresh)."""

    def __init__(
        self,
        api_base: str,
        api_token: str,
        *,
        refresh_token: str = "",
        refresh_url: str = "",
        project_id: str = "",
        customer_id: str = "",
        verify_ssl: bool = False,
        topology_graph: str = DEFAULT_TOPOLOGY_GRAPH,
        topology_db: str = DEFAULT_TOPOLOGY_DB,
        relationship_map: str = DEFAULT_RELATIONSHIP_MAP,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_token = api_token
        self.refresh_token = refresh_token or ""
        self.refresh_url = refresh_url or ""
        self.project_id = project_id or ""
        self.customer_id = customer_id or ""
        self.verify_ssl = verify_ssl
        self.topology_graph = topology_graph or DEFAULT_TOPOLOGY_GRAPH
        self.topology_db = topology_db or DEFAULT_TOPOLOGY_DB
        self.relationship_map = relationship_map or DEFAULT_RELATIONSHIP_MAP
        self._token = self._bearer(api_token)
        self._ctx = ssl.create_default_context()
        if not verify_ssl:
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    @staticmethod
    def normalize_api_base(raw: str) -> str | None:
        value = (raw or "").strip().rstrip("/")
        if not value:
            return None
        if not re.match(r"^https?://", value, re.IGNORECASE):
            value = f"https://{value}"
        if not re.match(r"^https?://[^\s/]+", value):
            return None
        return value

    @staticmethod
    def _bearer(token: str) -> str:
        token = (token or "").strip()
        if not token:
            return ""
        if not token.lower().startswith("bearer "):
            token = f"Bearer {token}"
        return token

    def _request(self, method: str, url: str, body: bytes | None = None) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = self._token
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=TIMEOUT_SEC) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail) if detail.strip() else {}
            except json.JSONDecodeError:
                parsed = {"_raw": detail[:1000]}
            return exc.code, parsed
        except urllib.error.URLError as exc:
            raise CloudFabrixAPIError(f"Connection error: {exc}") from exc

    def _refresh_access_token(self) -> bool:
        if not self.refresh_url or not self.refresh_token:
            return False
        refresh = self.refresh_token
        if refresh.lower().startswith("bearer "):
            refresh = refresh[7:].strip()
        body = json.dumps({"refresh_token": refresh}).encode()
        status, payload = self._request("POST", self.refresh_url, body)
        if status != 200 or not isinstance(payload, dict):
            return False
        result = payload.get("serviceResult") or {}
        new_access = (result.get("access_token") or "").strip()
        new_refresh = (result.get("refresh_token") or "").strip()
        if not new_access:
            return False
        self._token = self._bearer(new_access)
        self.api_token = new_access
        if new_refresh:
            self.refresh_token = new_refresh
        return True

    def get(self, path: str, params: dict[str, Any] | None = None, *, _retried: bool = False) -> Any:
        url = self.api_base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        status, payload = self._request("GET", url)
        if status == 401 and not _retried and self._refresh_access_token():
            return self.get(path, params, _retried=True)
        if status != 200:
            raise CloudFabrixAPIError(f"HTTP {status}: {payload}")
        return payload

    @staticmethod
    def rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if not isinstance(payload, dict):
            return []
        for key in (
            "pstream_data", "data", "rows", "results", "items", "records",
            "graphs", "relationship_maps", "datasets", "pstreams",
            "organizations", "nodes", "edges",
        ):
            val = payload.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
        return []

    def validate_connection(self) -> dict[str, Any]:
        """Lightweight connectivity check."""
        payload = self.get("/api/v2/organizations")
        orgs = self.rows(payload)
        return {
            "ok": True,
            "api_base": self.api_base,
            "organization_count": len(orgs),
            "sample_organization": (orgs[0].get("name") or orgs[0].get("org_name")) if orgs else None,
        }

    def to_token_payload(self) -> dict[str, Any]:
        return {
            "api_base": self.api_base,
            "api_token": self.api_token,
            "refresh_token": self.refresh_token,
            "refresh_url": self.refresh_url,
            "project_id": self.project_id,
            "customer_id": self.customer_id,
            "verify_ssl": self.verify_ssl,
            "topology_graph": self.topology_graph,
            "topology_db": self.topology_db,
            "relationship_map": self.relationship_map,
        }

    @classmethod
    def from_token_data(cls, data: dict[str, Any]) -> "CloudFabrixClient":
        return cls(
            api_base=data["api_base"],
            api_token=data["api_token"],
            refresh_token=data.get("refresh_token") or "",
            refresh_url=data.get("refresh_url") or "",
            project_id=data.get("project_id") or "",
            customer_id=data.get("customer_id") or "",
            verify_ssl=bool(data.get("verify_ssl", False)),
            topology_graph=data.get("topology_graph") or DEFAULT_TOPOLOGY_GRAPH,
            topology_db=data.get("topology_db") or DEFAULT_TOPOLOGY_DB,
            relationship_map=data.get("relationship_map") or DEFAULT_RELATIONSHIP_MAP,
        )


def load_client_for_user(user_id: str | None) -> CloudFabrixClient | None:
    if not user_id:
        return None
    try:
        from utils.auth.token_management import get_token_data

        data = get_token_data(user_id, "cloudfabrix")
        if data and data.get("api_base") and data.get("api_token"):
            return CloudFabrixClient.from_token_data(data)
    except Exception as exc:
        logger.debug("[CloudFabrix] Could not load user credentials: %s", exc)
    return None


def load_client_from_env() -> CloudFabrixClient | None:
    api_base = (os.getenv("CFX_API_BASE") or "").strip()
    api_token = (os.getenv("CFX_API_TOKEN") or "").strip()
    if not api_base or not api_token:
        return None
    verify = (os.getenv("CFX_VERIFY_SSL") or "false").strip().lower() not in ("0", "false", "no", "off")
    return CloudFabrixClient(
        api_base=api_base,
        api_token=api_token,
        refresh_token=(os.getenv("CFX_REFRESH_TOKEN") or "").strip(),
        refresh_url=(os.getenv("CFX_REFRESH_API_URL") or "").strip(),
        project_id=(os.getenv("CFX_PROJECT_ID") or os.getenv("CFX_POLL_PROJECT_ID") or "").strip(),
        customer_id=(os.getenv("CFX_CUSTOMER_ID") or "").strip(),
        verify_ssl=verify,
        topology_graph=(os.getenv("CFX_TOPOLOGY_GRAPH") or DEFAULT_TOPOLOGY_GRAPH).strip(),
        topology_db=(os.getenv("CFX_TOPOLOGY_DB") or DEFAULT_TOPOLOGY_DB).strip(),
        relationship_map=(os.getenv("CFX_RELATIONSHIP_MAP") or DEFAULT_RELATIONSHIP_MAP).strip(),
    )


def get_client(user_id: str | None = None) -> CloudFabrixClient:
    client = load_client_for_user(user_id) or load_client_from_env()
    if not client:
        raise ValueError(
            "CloudFabrix is not configured. Connect CloudFabrix in Connectors "
            "or set CFX_API_BASE and CFX_API_TOKEN."
        )
    return client
