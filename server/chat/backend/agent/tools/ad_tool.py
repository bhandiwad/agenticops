"""Active Directory tools (on-prem), executed as PowerShell on a Domain Controller via WinRM.

- ad_replication_health: read-only — runs repadmin to summarize AD replication health.
- ad_bulk_create_users: write (background/workflow only) — creates users from a structured list
  via New-ADUser, returning a per-user result.

Both use the stored Windows/WinRM credentials to reach the target Domain Controller.
"""

import json
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from connectors.winrm_connector.client import WinRMClient, WinRMError
from utils.auth.token_management import get_token_data

logger = logging.getLogger(__name__)


class ADReplicationHealthArgs(BaseModel):
    dc_host: str = Field(description="Domain Controller hostname/IP to query.")


class ADUser(BaseModel):
    sam_account_name: str = Field(description="sAMAccountName (login), e.g. jdoe.")
    name: str = Field(description="Display name / CN, e.g. 'Jane Doe'.")
    user_principal_name: str = Field(default="", description="UPN, e.g. jdoe@corp.local (optional).")
    password: str = Field(description="Initial password (user must change at next logon).")
    ou_path: str = Field(default="", description="Target OU distinguished name (optional; default Users).")


class ADBulkCreateUsersArgs(BaseModel):
    dc_host: str = Field(description="Domain Controller hostname/IP to run against.")
    users: List[ADUser] = Field(description="Users to create.")


def _winrm_creds(user_id: str) -> Optional[dict]:
    data = get_token_data(user_id, "winrm")
    if data and data.get("username") and data.get("password"):
        return data
    return None


def is_ad_available(user_id: str) -> bool:
    # AD ops run over the WinRM transport against a DC.
    return _winrm_creds(user_id) is not None


def _client(creds: dict, host: str) -> WinRMClient:
    return WinRMClient(
        host=host, username=creds["username"], password=creds["password"],
        transport=creds.get("transport", "ntlm"), use_ssl=creds.get("use_ssl", True),
        verify_ssl=bool(creds.get("verify_ssl", True)), port=creds.get("port"),
    )


def _ps_single_quote(value: str) -> str:
    """Escape a value for a single-quoted PowerShell string."""
    return (value or "").replace("'", "''")


def ad_replication_health(dc_host: str, user_id: Optional[str] = None) -> str:
    if not user_id:
        return json.dumps({"ok": False, "error": "User context not available"})
    creds = _winrm_creds(user_id)
    if not creds:
        return json.dumps({"ok": False, "error": "Windows/WinRM is not connected"})
    if not (dc_host or "").strip():
        return json.dumps({"ok": False, "error": "dc_host is required"})

    script = "repadmin /replsummary; Write-Output '---SHOWREPL---'; repadmin /showrepl * /csv"
    try:
        result = _client(creds, dc_host).run_ps(script)
    except WinRMError as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({
        "ok": bool(result.get("ok")),
        "dc_host": dc_host,
        "status_code": result.get("status_code"),
        "replication_report": (result.get("stdout") or "")[:40000],
        "stderr": result.get("stderr"),
    })


def ad_bulk_create_users(dc_host: str, users: List[dict], user_id: Optional[str] = None) -> str:
    """Create AD users from a list. Background/workflow execution only."""
    if not user_id:
        return json.dumps({"ok": False, "error": "User context not available"})
    creds = _winrm_creds(user_id)
    if not creds:
        return json.dumps({"ok": False, "error": "Windows/WinRM is not connected"})
    if not (dc_host or "").strip():
        return json.dumps({"ok": False, "error": "dc_host is required"})
    if not users:
        return json.dumps({"ok": False, "error": "users list is empty"})

    # Build a PowerShell block that creates each user and reports a per-user JSON line.
    lines = ["Import-Module ActiveDirectory -ErrorAction SilentlyContinue", "$results = @()"]
    for u in users:
        u = u if isinstance(u, dict) else {}
        sam = _ps_single_quote(str(u.get("sam_account_name", "")).strip())
        name = _ps_single_quote(str(u.get("name", "")).strip())
        upn = _ps_single_quote(str(u.get("user_principal_name", "")).strip())
        pwd = _ps_single_quote(str(u.get("password", "")))
        ou = _ps_single_quote(str(u.get("ou_path", "")).strip())
        if not sam or not name or not pwd:
            continue
        ou_param = f"-Path '{ou}' " if ou else ""
        upn_param = f"-UserPrincipalName '{upn}' " if upn else ""
        lines.append(
            "try { "
            f"New-ADUser -SamAccountName '{sam}' -Name '{name}' {upn_param}{ou_param}"
            f"-AccountPassword (ConvertTo-SecureString '{pwd}' -AsPlainText -Force) "
            "-Enabled $true -ChangePasswordAtLogon $true -ErrorAction Stop; "
            f"$results += [pscustomobject]@{{ sam='{sam}'; status='created' }} "
            "} catch { "
            f"$results += [pscustomobject]@{{ sam='{sam}'; status='error'; error=$_.Exception.Message }} "
            "}"
        )
    lines.append("$results | ConvertTo-Json -Compress")
    script = "\n".join(lines)

    try:
        result = _client(creds, dc_host).run_ps(script)
    except WinRMError as exc:
        return json.dumps({"ok": False, "error": str(exc)})

    parsed = None
    raw = (result.get("stdout") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
    return json.dumps({
        "ok": bool(result.get("ok")),
        "dc_host": dc_host,
        "status_code": result.get("status_code"),
        "results": parsed if parsed is not None else raw[:20000],
        "stderr": result.get("stderr"),
    })
