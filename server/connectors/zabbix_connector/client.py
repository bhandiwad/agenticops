"""Zabbix API client (JSON-RPC).

Talks to the Zabbix ``/api_jsonrpc.php`` endpoint. Supports multiple Zabbix versions:
authentication is version-aware — Zabbix 6.4+ takes the token in an ``Authorization: Bearer``
header, while older versions take it in the request body's ``auth`` field. Both API tokens
(5.4+) and username/password (``user.login`` session token) are supported.

Zabbix servers are typically on a private/management network, so the SSRF guard is consulted
with the operator's ``AURORA_SSRF_ALLOWED_CIDRS`` allowlist.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from utils.net.ssrf import is_safe_public_url

logger = logging.getLogger(__name__)

ZABBIX_TIMEOUT = 20


class ZabbixAPIError(Exception):
    """Raised for Zabbix API / connectivity failures."""


class ZabbixClient:
    def __init__(
        self,
        base_url: str,
        api_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_ssl: bool = True,
        timeout: int = ZABBIX_TIMEOUT,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.endpoint = f"{self.base_url}/api_jsonrpc.php"
        self.api_token = api_token or None
        self.username = username or None
        self.password = password or None
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._session_token: Optional[str] = None
        self.detected_version: Optional[str] = None
        self._rpc_id = 0

    # ------------------------------------------------------------------
    def _version_tuple(self) -> tuple:
        try:
            return tuple(int(x) for x in (self.detected_version or "0").split(".")[:2])
        except (ValueError, AttributeError):
            return (0, 0)

    def _token(self) -> Optional[str]:
        return self.api_token or self._session_token

    def _call(self, method: str, params: Optional[Dict[str, Any]] = None, needs_auth: bool = True) -> Any:
        ok, reason = is_safe_public_url(self.endpoint)
        if not ok:
            logger.warning("[ZABBIX] request blocked (SSRF guard): %s", reason)
            raise ZabbixAPIError(
                "Zabbix URL is not permitted. If it is on a private management network, "
                "add its range to AURORA_SSRF_ALLOWED_CIDRS."
            )

        self._rpc_id += 1
        headers = {"Content-Type": "application/json-rpc"}
        body: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": self._rpc_id}

        token = self._token() if needs_auth else None
        if token:
            if self._version_tuple() >= (6, 4):
                headers["Authorization"] = f"Bearer {token}"
            else:
                body["auth"] = token

        try:
            resp = requests.post(self.endpoint, json=body, headers=headers,
                                 timeout=self.timeout, verify=self.verify_ssl)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error("[ZABBIX] %s network error: %s", method, exc)
            raise ZabbixAPIError("Unable to reach Zabbix") from exc
        except ValueError as exc:
            raise ZabbixAPIError("Zabbix returned a non-JSON response") from exc

        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise ZabbixAPIError(f"{err.get('message', 'error')}: {err.get('data', '')}".strip(": "))
        return data.get("result") if isinstance(data, dict) else None

    # ------------------------------------------------------------------
    def get_version(self) -> str:
        version = self._call("apiinfo.version", needs_auth=False)
        self.detected_version = str(version) if version else None
        return self.detected_version or ""

    def _login(self) -> None:
        """Obtain a session token for username/password auth (no-op for API-token mode)."""
        if self.api_token:
            return
        if not (self.username and self.password):
            raise ZabbixAPIError("Zabbix requires either an API token or username + password")
        # Param name is 'username' on modern Zabbix, 'user' on older releases — try both.
        last_err: Optional[Exception] = None
        for key in ("username", "user"):
            try:
                token = self._call("user.login", {key: self.username, "password": self.password}, needs_auth=False)
                if token:
                    self._session_token = str(token)
                    return
            except ZabbixAPIError as exc:
                last_err = exc
        raise ZabbixAPIError(f"Zabbix login failed: {last_err}" if last_err else "Zabbix login failed")

    def validate(self) -> Dict[str, Any]:
        """Detect version, authenticate, and confirm an authed call works. Raises on failure."""
        self.get_version()
        self._login()
        # Lightweight authed probe.
        self._call("host.get", {"countOutput": True, "limit": 1})
        return {"version": self.detected_version}

    def _ensure_auth(self) -> None:
        if not self.detected_version:
            self.get_version()
        if not self._token():
            self._login()

    # ------------------------------------------------------------------
    # Read methods
    def get_hosts(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_auth()
        return self._call("host.get", {
            "output": ["hostid", "host", "name", "status", "available"],
            "sortfield": "name", "limit": limit,
        }) or []

    def get_problems(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_auth()
        return self._call("problem.get", {
            "output": "extend", "recent": False,
            "sortfield": ["eventid"], "sortorder": "DESC", "limit": limit,
        }) or []

    def get_triggers(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_auth()
        return self._call("trigger.get", {
            "output": ["triggerid", "description", "priority", "value", "lastchange"],
            "only_true": True, "monitored": True, "expandDescription": True,
            "sortfield": "priority", "sortorder": "DESC", "limit": limit,
        }) or []

    def get_items(self, hostids: Optional[List[str]] = None, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_auth()
        params: Dict[str, Any] = {
            "output": ["itemid", "name", "key_", "lastvalue", "units", "hostid"],
            "sortfield": "name", "limit": limit,
        }
        if hostids:
            params["hostids"] = hostids
        return self._call("item.get", params) or []

    def get_hostgroups(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._ensure_auth()
        return self._call("hostgroup.get", {"output": ["groupid", "name"], "limit": limit}) or []
