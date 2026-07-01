"""Commvault REST API client (v11 Web Service).

Talks to the Commvault Web Service REST API (``/webconsole/api`` on the CommServe / Web
Server). Authentication is a per-invocation login: POST ``/Login`` with the username and a
base64-encoded password returns a session token, sent as the ``Authtoken`` header on
subsequent calls. The API is stable across CommServe v11 feature releases.

Commvault CommServe hosts are typically on a private/management network, so the SSRF guard is
consulted with the operator's ``AURORA_SSRF_ALLOWED_CIDRS`` allowlist.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

import requests

from utils.net.ssrf import is_safe_public_url

logger = logging.getLogger(__name__)

COMMVAULT_TIMEOUT = 30


class CommvaultAPIError(Exception):
    """Raised for Commvault API / connectivity failures."""


class CommvaultClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        timeout: int = COMMVAULT_TIMEOUT,
    ):
        # base_url is the Web Service root, e.g. https://commserve.example.com/webconsole/api
        self.base_url = (base_url or "").rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._token: Optional[str] = None

    # ------------------------------------------------------------------
    def _headers(self, with_auth: bool = True) -> Dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if with_auth and self._token:
            headers["Authtoken"] = self._token
        return headers

    def _request(self, method: str, path: str, json_body: Optional[Dict[str, Any]] = None,
                 with_auth: bool = True) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        ok, reason = is_safe_public_url(url)
        if not ok:
            logger.warning("[COMMVAULT] request blocked (SSRF guard): %s", reason)
            raise CommvaultAPIError(
                "Commvault URL is not permitted. If it is on a private management network, "
                "add its range to AURORA_SSRF_ALLOWED_CIDRS."
            )
        try:
            resp = requests.request(method, url, headers=self._headers(with_auth),
                                    json=json_body, timeout=self.timeout, verify=self.verify_ssl)
        except requests.RequestException as exc:
            logger.error("[COMMVAULT] %s %s network error: %s", method, path, exc)
            raise CommvaultAPIError("Unable to reach Commvault") from exc

        if resp.status_code in (401, 403):
            raise CommvaultAPIError("Commvault rejected the session (unauthorized/expired token)")
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise CommvaultAPIError(f"Commvault API error {resp.status_code}") from exc

        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise CommvaultAPIError("Commvault returned a non-JSON response") from exc

    # ------------------------------------------------------------------
    def login(self) -> str:
        """Authenticate and cache the session token. Raises on failure."""
        body = {
            "username": self.username,
            "password": base64.b64encode((self.password or "").encode("utf-8")).decode("ascii"),
        }
        data = self._request("POST", "/Login", json_body=body, with_auth=False)
        token = data.get("token")
        if not token:
            err = data.get("errList") or data.get("errorMessage") or "no token returned"
            raise CommvaultAPIError(f"Commvault login failed: {err}")
        self._token = token
        return token

    def _ensure_auth(self) -> None:
        if not self._token:
            self.login()

    def validate(self) -> Dict[str, Any]:
        """Login and confirm an authed call works. Raises on failure."""
        self.login()
        # Lightweight authed probe.
        self._request("GET", "/CommServ")
        return {"ok": True}

    # ------------------------------------------------------------------
    # Read methods
    def get_clients(self) -> List[Dict[str, Any]]:
        self._ensure_auth()
        data = self._request("GET", "/Client")
        return (data.get("clientProperties") or data.get("clients") or []) if isinstance(data, dict) else []

    def get_vms(self) -> List[Dict[str, Any]]:
        self._ensure_auth()
        data = self._request("GET", "/VM")
        return data.get("vmStatusInfoList", []) if isinstance(data, dict) else []

    def get_job(self, job_id: Any) -> Dict[str, Any]:
        """Return details for a job. status is under jobs[0].jobSummary.status."""
        self._ensure_auth()
        data = self._request("GET", f"/Job/{job_id}")
        jobs = data.get("jobs") or data.get("totalRecordsWithoutPaging")
        if isinstance(data.get("jobs"), list) and data["jobs"]:
            return data["jobs"][0]
        return data if isinstance(data, dict) else {}

    def job_status(self, job_id: Any) -> Optional[str]:
        """Convenience: the human-readable status string for a job, or None."""
        job = self.get_job(job_id)
        summary = job.get("jobSummary") if isinstance(job, dict) else None
        if isinstance(summary, dict):
            return summary.get("status")
        return job.get("status") if isinstance(job, dict) else None

    # ------------------------------------------------------------------
    # Write primitive (used by the approval-gated VM backup workflow)
    def backup_subclient(self, subclient_id: Any, backup_level: str = "FULL") -> Dict[str, Any]:
        """Trigger a backup for a subclient. Returns the created job id(s)."""
        self._ensure_auth()
        level = (backup_level or "FULL").upper()
        return self._request("POST", f"/Subclient/{subclient_id}/action/backup?backupLevel={level}")

    def backup_vm(self, vm_uuid: str, backup_level: str = "FULL") -> Dict[str, Any]:
        """Trigger a backup for a virtualization VM by its UUID/GUID."""
        self._ensure_auth()
        level = (backup_level or "FULL").upper()
        return self._request("POST", f"/v2/vsa/vm/{vm_uuid}/backup?backupLevel={level}")
