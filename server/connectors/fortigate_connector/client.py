"""FortiGate (FortiOS) REST API client.

Talks to the FortiOS ``/api/v2`` REST API, which is stable across FortiOS 6.0 – 7.4:
``/api/v2/monitor/...`` for runtime/status and ``/api/v2/cmdb/...`` for configuration
objects. The running firmware version is detected from ``monitor/system/status`` and
surfaced so callers can adapt if needed.

Auth is a FortiOS REST API admin token, sent as a Bearer header by default. Some hardened
setups only accept the token as an ``access_token`` query parameter — set
``auth_in_query=True`` for that.

FortiGate management interfaces almost always live on a private/management network, so the
SSRF guard is consulted with the operator's ``AURORA_SSRF_ALLOWED_CIDRS`` allowlist rather
than the strict public-only default.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from utils.net.ssrf import is_safe_public_url

logger = logging.getLogger(__name__)

FORTIGATE_TIMEOUT = 20


class FortiGateAPIError(Exception):
    """Raised for FortiGate API / connectivity failures."""


class FortiGateClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
        vdom: Optional[str] = None,
        verify_ssl: bool = True,
        auth_in_query: bool = False,
        timeout: int = FORTIGATE_TIMEOUT,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_token = api_token
        self.vdom = vdom or None
        self.verify_ssl = verify_ssl
        self.auth_in_query = auth_in_query
        self.timeout = timeout
        # Detected at connect/validate time from monitor/system/status.
        self.detected_version: Optional[str] = None
        self.serial: Optional[str] = None
        self.hostname: Optional[str] = None

    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None,
                 json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        ok, reason = is_safe_public_url(url)
        if not ok:
            logger.warning("[FORTIGATE] request blocked (SSRF guard): %s", reason)
            raise FortiGateAPIError(
                "FortiGate URL is not permitted. If it is on a private management network, "
                "add its range to AURORA_SSRF_ALLOWED_CIDRS."
            )

        query: Dict[str, Any] = dict(params or {})
        if self.vdom:
            query.setdefault("vdom", self.vdom)
        headers = {"Accept": "application/json"}
        if self.auth_in_query:
            query["access_token"] = self.api_token
        else:
            headers["Authorization"] = f"Bearer {self.api_token}"

        try:
            response = requests.request(
                method, url, headers=headers, params=query, json=json_body,
                timeout=self.timeout, verify=self.verify_ssl,
            )
        except requests.RequestException as exc:
            logger.error("[FORTIGATE] %s %s network error: %s", method, path, exc)
            raise FortiGateAPIError("Unable to reach FortiGate") from exc

        if response.status_code in (401, 403):
            raise FortiGateAPIError("FortiGate rejected the API token (unauthorized)")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            logger.error("[FORTIGATE] %s %s failed (%s)", method, path, response.status_code)
            raise FortiGateAPIError(f"FortiGate API error {response.status_code}") from exc

        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise FortiGateAPIError("FortiGate returned a non-JSON response") from exc

    @staticmethod
    def _results(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """FortiOS wraps list results in ``results``; normalize to a list."""
        results = payload.get("results")
        if isinstance(results, list):
            return results
        if isinstance(results, dict):
            return [results]
        return []

    # ------------------------------------------------------------------
    # Read / status
    def get_system_status(self) -> Dict[str, Any]:
        """Validate connectivity + detect firmware version. Raises on failure."""
        payload = self._request("GET", "/api/v2/monitor/system/status")
        self.detected_version = payload.get("version") or payload.get("build")
        self.serial = payload.get("serial")
        results = payload.get("results") or {}
        if isinstance(results, dict):
            self.hostname = results.get("hostname") or results.get("host_name")
        return payload

    def list_firewall_policies(self, limit: int = 100) -> List[Dict[str, Any]]:
        payload = self._request("GET", "/api/v2/cmdb/firewall/policy")
        return self._results(payload)[: max(1, limit)]

    def list_addresses(self, limit: int = 200) -> List[Dict[str, Any]]:
        payload = self._request("GET", "/api/v2/cmdb/firewall/address")
        return self._results(payload)[: max(1, limit)]

    def list_services(self, limit: int = 200) -> List[Dict[str, Any]]:
        payload = self._request("GET", "/api/v2/cmdb/firewall.service/custom")
        return self._results(payload)[: max(1, limit)]

    def list_interfaces(self, limit: int = 200) -> List[Dict[str, Any]]:
        payload = self._request("GET", "/api/v2/cmdb/system/interface")
        return self._results(payload)[: max(1, limit)]

    def get_policy(self, policy_id: Any) -> Dict[str, Any]:
        payload = self._request("GET", f"/api/v2/cmdb/firewall/policy/{policy_id}")
        results = self._results(payload)
        return results[0] if results else {}

    # ------------------------------------------------------------------
    # Write primitives (used by the open-firewall-port workflow, behind approval)
    def create_service_object(self, name: str, protocol: str, port_range: str) -> Dict[str, Any]:
        """Create a custom firewall service for a TCP/UDP/SCTP port range."""
        proto = (protocol or "TCP").upper()
        body: Dict[str, Any] = {"name": name, "protocol": "TCP/UDP/SCTP"}
        if proto == "UDP":
            body["udp-portrange"] = port_range
        elif proto == "SCTP":
            body["sctp-portrange"] = port_range
        else:
            body["tcp-portrange"] = port_range
        return self._request("POST", "/api/v2/cmdb/firewall.service/custom", json_body=body)

    def create_address_object(self, name: str, subnet: str) -> Dict[str, Any]:
        """Create an IP/mask address object (subnet form, e.g. '10.0.0.5/32')."""
        return self._request(
            "POST", "/api/v2/cmdb/firewall/address",
            json_body={"name": name, "type": "ipmask", "subnet": subnet},
        )

    def create_firewall_policy(
        self,
        name: str,
        srcintf: str,
        dstintf: str,
        srcaddr: str,
        dstaddr: str,
        service: str,
        action: str = "accept",
        schedule: str = "always",
        nat: bool = False,
        comment: str = "",
    ) -> Dict[str, Any]:
        """Create an allow policy wiring src/dst interfaces, addresses and a service."""
        body: Dict[str, Any] = {
            "name": name,
            "srcintf": [{"name": srcintf}],
            "dstintf": [{"name": dstintf}],
            "srcaddr": [{"name": srcaddr}],
            "dstaddr": [{"name": dstaddr}],
            "service": [{"name": service}],
            "action": action,
            "schedule": schedule,
            "status": "enable",
            "logtraffic": "all",
            "nat": "enable" if nat else "disable",
        }
        if comment:
            body["comments"] = comment
        return self._request("POST", "/api/v2/cmdb/firewall/policy", json_body=body)
