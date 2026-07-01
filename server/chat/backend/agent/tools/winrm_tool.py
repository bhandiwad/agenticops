"""WinRM execution tool for Windows hosts.

winrm_exec runs a PowerShell script on a Windows host using the stored default Windows
credentials. Registered in background/workflow execution only (Windows patch/upgrade,
troubleshooting, AD, and threshold-remediation workflows) — never in interactive chat.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from connectors.winrm_connector.client import WinRMClient, WinRMError
from utils.auth.token_management import get_token_data

logger = logging.getLogger(__name__)


class WinRMExecArgs(BaseModel):
    host: str = Field(description="Target Windows host (hostname or IP on the management network).")
    script: str = Field(description="PowerShell script to run on the host.")
    use_ssl: Optional[bool] = Field(default=None, description="Override HTTPS/5986 (default) vs HTTP/5985.")


def _stored(user_id: str) -> Optional[dict]:
    data = get_token_data(user_id, "winrm")
    if data and data.get("username") and data.get("password"):
        return data
    return None


def is_winrm_connected(user_id: str) -> bool:
    return _stored(user_id) is not None


def winrm_exec(host: str, script: str, use_ssl: Optional[bool] = None, user_id: Optional[str] = None) -> str:
    if not user_id:
        return json.dumps({"ok": False, "error": "User context not available"})
    data = _stored(user_id)
    if not data:
        return json.dumps({"ok": False, "error": "Windows/WinRM is not connected"})
    if not (host or "").strip() or not (script or "").strip():
        return json.dumps({"ok": False, "error": "Both 'host' and 'script' are required"})

    client = WinRMClient(
        host=host,
        username=data["username"],
        password=data["password"],
        transport=data.get("transport", "ntlm"),
        use_ssl=data.get("use_ssl", True) if use_ssl is None else bool(use_ssl),
        verify_ssl=bool(data.get("verify_ssl", True)),
        port=data.get("port"),
    )
    try:
        result = client.run_ps(script)
    except WinRMError as exc:
        return json.dumps({"ok": False, "host": host, "error": str(exc)})

    result["host"] = host
    out = json.dumps(result, default=str)
    if len(out) > 60000:
        out = out[:60000] + '..."}'
    return out
