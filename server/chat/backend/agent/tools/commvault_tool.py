"""Commvault agent tools.

- query_commvault: read-only (clients, VMs, and job status — used to poll/validate a backup).
- commvault_backup: triggers a backup job. Background/workflow execution only, so a backup
  can only be started from an approval-gated workflow, never from interactive chat.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from connectors.commvault_connector.client import CommvaultClient, CommvaultAPIError
from utils.auth.token_management import get_token_data

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 12000
_RESOURCES = {"clients", "vms", "job"}


class QueryCommvaultArgs(BaseModel):
    resource_type: str = Field(description="One of: 'clients', 'vms', 'job'.")
    job_id: str = Field(default="", description="Job id — required when resource_type='job' (to poll/validate a backup).")


class CommvaultBackupArgs(BaseModel):
    entity_type: str = Field(description="'vm' (backup by VM UUID) or 'subclient' (backup by subclient id).")
    entity_id: str = Field(description="The VM UUID/GUID or the subclient id to back up.")
    backup_level: str = Field(default="FULL", description="Backup level: FULL | INCREMENTAL | DIFFERENTIAL | SYNTHETIC_FULL.")


def _stored(user_id: str) -> Optional[dict]:
    data = get_token_data(user_id, "commvault")
    if data and data.get("base_url") and data.get("username") and data.get("password"):
        return data
    return None


def is_commvault_connected(user_id: str) -> bool:
    return _stored(user_id) is not None


def _client(data: dict) -> CommvaultClient:
    return CommvaultClient(
        base_url=data["base_url"],
        username=data["username"],
        password=data["password"],
        verify_ssl=bool(data.get("verify_ssl", True)),
    )


def query_commvault(resource_type: str, job_id: str = "", user_id: Optional[str] = None) -> str:
    if not user_id:
        return json.dumps({"error": "User context not available"})
    data = _stored(user_id)
    if not data:
        return json.dumps({"error": "Commvault not connected. Please connect Commvault first."})

    rt = (resource_type or "").strip().lower()
    if rt not in _RESOURCES:
        return json.dumps({"error": f"Invalid resource_type '{resource_type}'. Must be one of: {', '.join(sorted(_RESOURCES))}"})

    client = _client(data)
    try:
        if rt == "clients":
            result = {"clients": client.get_clients()[:200]}
        elif rt == "vms":
            result = {"vms": client.get_vms()[:200]}
        else:  # job
            if not job_id:
                return json.dumps({"error": "job_id is required for resource_type='job'"})
            job = client.get_job(job_id)
            summary = job.get("jobSummary") if isinstance(job, dict) else {}
            result = {"job_id": job_id, "status": (summary or {}).get("status") if isinstance(summary, dict) else None, "job": job}
    except CommvaultAPIError as exc:
        return json.dumps({"error": str(exc)})

    out = json.dumps(result, default=str)
    if len(out) > _MAX_OUTPUT:
        out = out[:_MAX_OUTPUT] + '... (truncated)"}'
    return out


def commvault_backup(entity_type: str, entity_id: str, backup_level: str = "FULL",
                     user_id: Optional[str] = None) -> str:
    """Trigger a Commvault backup. Returns the created job id(s) — the caller should then poll
    query_commvault(resource_type='job', job_id=...) to validate completion. Background/workflow
    execution only."""
    if not user_id:
        return json.dumps({"ok": False, "error": "User context not available"})
    data = _stored(user_id)
    if not data:
        return json.dumps({"ok": False, "error": "Commvault not connected"})

    et = (entity_type or "").strip().lower()
    if et not in ("vm", "subclient"):
        return json.dumps({"ok": False, "error": "entity_type must be 'vm' or 'subclient'"})
    if not entity_id:
        return json.dumps({"ok": False, "error": "entity_id is required"})

    client = _client(data)
    try:
        if et == "vm":
            res = client.backup_vm(entity_id, backup_level)
        else:
            res = client.backup_subclient(entity_id, backup_level)
    except CommvaultAPIError as exc:
        return json.dumps({"ok": False, "error": str(exc)})

    # Commvault returns job id(s) under jobIds / jobId depending on version.
    job_ids = res.get("jobIds") or ([res.get("jobId")] if res.get("jobId") else [])
    return json.dumps({
        "ok": True,
        "entity_type": et,
        "entity_id": entity_id,
        "backup_level": (backup_level or "FULL").upper(),
        "job_ids": job_ids,
        "raw": res,
        "note": "Backup submitted. Poll query_commvault(resource_type='job', job_id=<id>) to validate completion.",
    })
