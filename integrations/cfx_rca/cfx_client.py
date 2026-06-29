"""GET-only CloudFabrix API client.

- All data access is via HTTP GET. No POST/PUT/DELETE against CFX data.
- The ONLY non-GET call is the token rotate endpoint, invoked lazily and only
  when a data GET returns 401 (token expired). This is the user-provided refresh
  mechanism, not a data mutation.
- SSL verification can be disabled (CFX base URL is an IP whose cert is for
  *.sify.net); controlled by CFX_VERIFY_SSL.
"""
from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import CfxConfig

logger = logging.getLogger("cfx_rca.client")


class CfxClient:
    def __init__(self, config: CfxConfig) -> None:
        self.cfg = config
        self._token = self._bearer(config.api_token)
        self._ctx = ssl.create_default_context()
        if not config.verify_ssl:
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    @staticmethod
    def _bearer(token: str) -> str:
        token = (token or "").strip()
        if not token:
            return ""
        if not token.lower().startswith("bearer "):
            token = f"Bearer {token}"
        return token

    # -- low level ---------------------------------------------------------
    def _request(self, method: str, url: str, body: bytes | None = None) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = self._token
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=self.cfg.timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail) if detail.strip() else {}
            except json.JSONDecodeError:
                parsed = {"_raw": detail[:1000]}
            return exc.code, parsed

    def _refresh_token(self) -> bool:
        """Lazy token rotation. Returns True on success. Updates in-memory token
        and persists the rotated pair back to .env so the next run is valid."""
        if not self.cfg.refresh_url or not self.cfg.refresh_token:
            logger.warning("No refresh_url/refresh_token configured; cannot refresh")
            return False
        refresh = self.cfg.refresh_token
        if refresh.lower().startswith("bearer "):
            refresh = refresh[7:].strip()
        body = json.dumps({"refresh_token": refresh}).encode()
        status, payload = self._request("POST", self.cfg.refresh_url, body)
        if status != 200 or not isinstance(payload, dict):
            logger.error("Token refresh failed: HTTP %s", status)
            return False
        result = payload.get("serviceResult") or {}
        new_access = (result.get("access_token") or "").strip()
        new_refresh = (result.get("refresh_token") or "").strip()
        if not new_access:
            logger.error("Token refresh response missing access_token")
            return False
        self._token = self._bearer(new_access)
        self.cfg.api_token = new_access
        if new_refresh:
            self.cfg.refresh_token = new_refresh
        self._persist_tokens(new_access, new_refresh)
        logger.info("CFX token refreshed (expires %s)", result.get("access_token_expires_at"))
        return True

    def _persist_tokens(self, access: str, refresh: str) -> None:
        try:
            path = Path(self.cfg.env_path)
            text = path.read_text(encoding="utf-8")
            access_line = f'CFX_API_TOKEN="{access if access.lower().startswith("bearer ") else "Bearer " + access}"'
            text = re.sub(r"^CFX_API_TOKEN=.*$", access_line, text, flags=re.MULTILINE)
            if refresh:
                text = re.sub(
                    r"^CFX_REFRESH_TOKEN=.*$",
                    f'CFX_REFRESH_TOKEN="{refresh}"',
                    text,
                    flags=re.MULTILINE,
                )
            path.write_text(text, encoding="utf-8")
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Could not persist rotated tokens: %s", exc)

    def get(self, path: str, params: dict[str, Any] | None = None, _retried: bool = False) -> Any:
        url = self.cfg.api_base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        status, payload = self._request("GET", url)
        if status == 401 and not _retried:
            if self._refresh_token():
                return self.get(path, params, _retried=True)
        if status != 200:
            logger.warning("GET %s -> HTTP %s", path, status)
            return {"_status": status, "_error": payload}
        return payload

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def rows(payload: Any) -> list[dict[str, Any]]:
        """Extract row list from the various CFX response envelopes."""
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("pstream_data", "data", "rows", "results", "items", "records",
                    "graphs", "relationship_maps", "datasets", "pstreams",
                    "organizations", "nodes", "edges", "correlation_policies"):
            val = payload.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
        return []

    # -- domain reads (all GET) -------------------------------------------
    def pstream_data(self, name: str, limit: int = 100, offset: int = 0,
                     cfxql: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": str(limit)}
        if offset:
            params["offset"] = str(offset)
        if cfxql:
            params["cfxql_query"] = cfxql
        q = urllib.parse.quote(name, safe="")
        return self.rows(self.get(f"/api/v2/pstreams/pstream/{q}/data", params))

    def graph_nodes(self, graph: str, db: str, limit: int = 500, offset: int = 0,
                    cfxql: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"db_name": db, "limit": str(limit)}
        if offset:
            params["offset"] = str(offset)
        if cfxql:
            params["cfxql_query"] = cfxql
        q = urllib.parse.quote(graph, safe="")
        return self.rows(self.get(f"/api/v2/graphdb/graph/{q}/nodes", params))

    def graph_edges(self, graph: str, db: str, limit: int = 500, offset: int = 0,
                    cfxql: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"db_name": db, "limit": str(limit)}
        if offset:
            params["offset"] = str(offset)
        if cfxql:
            params["cfxql_query"] = cfxql
        q = urllib.parse.quote(graph, safe="")
        return self.rows(self.get(f"/api/v2/graphdb/graph/{q}/edges", params))

    def relationship_map(self, name: str) -> dict[str, Any]:
        q = urllib.parse.quote(name, safe="")
        payload = self.get(f"/api/v2/relationship_maps/relationship_map/{q}")
        return payload if isinstance(payload, dict) else {}

    def organizations(self) -> list[dict[str, Any]]:
        return self.rows(self.get("/api/v2/organizations"))
