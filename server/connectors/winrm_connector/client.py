"""WinRM execution client for Windows hosts (via pywinrm).

Runs PowerShell / cmd on Windows VMs over WS-Management (WinRM), the counterpart to the SSH
path used for Linux. Credentials are domain/local Windows credentials (NTLM by default).

``pywinrm`` is imported lazily so a missing optional dependency degrades this transport to a
clear error rather than crashing the app at import time. Windows hosts live on private/
management networks, so the SSRF guard is consulted with the operator's
``AURORA_SSRF_ALLOWED_CIDRS`` allowlist.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from utils.net.ssrf import is_safe_public_url

logger = logging.getLogger(__name__)

DEFAULT_HTTP_PORT = 5985
DEFAULT_HTTPS_PORT = 5986
WINRM_TIMEOUT = 60


class WinRMError(Exception):
    """Raised for WinRM connectivity / execution failures."""


class WinRMClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        transport: str = "ntlm",
        use_ssl: bool = True,
        port: Optional[int] = None,
        verify_ssl: bool = True,
        timeout: int = WINRM_TIMEOUT,
    ):
        self.host = (host or "").strip()
        self.username = username
        self.password = password
        self.transport = (transport or "ntlm").lower()
        self.use_ssl = use_ssl
        self.port = port or (DEFAULT_HTTPS_PORT if use_ssl else DEFAULT_HTTP_PORT)
        self.verify_ssl = verify_ssl
        self.timeout = timeout

    def _endpoint(self) -> str:
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.host}:{self.port}/wsman"

    def _session(self):
        endpoint = self._endpoint()
        ok, reason = is_safe_public_url(endpoint)
        if not ok:
            logger.warning("[WINRM] request blocked (SSRF guard): %s", reason)
            raise WinRMError(
                "Windows host is not permitted. If it is on a private management network, "
                "add its range to AURORA_SSRF_ALLOWED_CIDRS."
            )
        try:
            import winrm  # lazy: optional dependency
        except ImportError as exc:  # pragma: no cover
            raise WinRMError("pywinrm is not installed on the server") from exc

        cert_validation = "validate" if (self.use_ssl and self.verify_ssl) else "ignore"
        return winrm.Session(
            endpoint,
            auth=(self.username, self.password),
            transport=self.transport,
            server_cert_validation=cert_validation,
            read_timeout_sec=self.timeout + 10,
            operation_timeout_sec=self.timeout,
        )

    # ------------------------------------------------------------------
    def _result(self, r) -> Dict[str, Any]:
        out = (r.std_out or b"").decode("utf-8", errors="replace") if isinstance(r.std_out, bytes) else (r.std_out or "")
        err = (r.std_err or b"").decode("utf-8", errors="replace") if isinstance(r.std_err, bytes) else (r.std_err or "")
        return {
            "status_code": r.status_code,
            "ok": r.status_code == 0,
            "stdout": out[:60000],
            "stderr": err[:20000],
        }

    def run_ps(self, script: str) -> Dict[str, Any]:
        """Run a PowerShell script and return {status_code, ok, stdout, stderr}."""
        try:
            return self._result(self._session().run_ps(script))
        except WinRMError:
            raise
        except Exception as exc:  # noqa: BLE001 - pywinrm raises a variety of transport errors
            logger.error("[WINRM] run_ps failed on %s: %s", self.host, exc)
            raise WinRMError(f"WinRM execution failed: {exc}") from exc

    def run_cmd(self, command: str, args: Optional[list] = None) -> Dict[str, Any]:
        """Run a cmd.exe command and return {status_code, ok, stdout, stderr}."""
        try:
            return self._result(self._session().run_cmd(command, args or []))
        except WinRMError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("[WINRM] run_cmd failed on %s: %s", self.host, exc)
            raise WinRMError(f"WinRM execution failed: {exc}") from exc

    def validate(self) -> Dict[str, Any]:
        """Confirm connectivity + auth by reading the remote hostname."""
        result = self.run_ps("$env:COMPUTERNAME")
        if not result.get("ok"):
            raise WinRMError(result.get("stderr") or "WinRM validation failed")
        return {"ok": True, "computer_name": (result.get("stdout") or "").strip()}
