#!/usr/bin/env python3
"""
Create ServiceNow records when new Aurora incidents appear.

Polls Aurora incidents via the internal API and exports any incident that does
not yet have a linked ServiceNow record.
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AURORA_ROOT = Path(os.environ.get("AURORA_ROOT", "/home/ubuntu/aurora"))
ENV_PATH = Path(os.environ.get("AURORA_TO_SNOW_ENV", AURORA_ROOT / ".env"))
STATE_PATH = Path(
    os.environ.get(
        "AURORA_TO_SNOW_STATE",
        AURORA_ROOT / "data" / "aurora-to-snow-state.json",
    )
)
OUTBOUND_STATE_PATH = Path(
    os.environ.get(
        "OUTBOUND_POLLER_STATE",
        AURORA_ROOT / "data" / "outbound-poller-state.json",
    )
)
LOG_LEVEL = os.environ.get("AURORA_TO_SNOW_LOG_LEVEL", "INFO").upper()

DEFAULT_USER_ID = "a3b2eaa0-2423-4ebb-ad80-9c99a508822b"
DEFAULT_ORG_ID = "5daed403-4a51-4f0c-942c-21f9a127d954"
DEFAULT_API_URL = "http://127.0.0.1:5081"
DEFAULT_LIVENESS_TIMEOUT_SEC = 5

SEVERITY_TO_SNOW_PRIORITY = {
    "critical": "1",
    "high": "2",
    "medium": "3",
    "low": "4",
}

INSTANCE_ID_RE = re.compile(r"\bi-[0-9a-f]{8,17}\b", re.IGNORECASE)
DEFAULT_BRAND_NAME = "Aurora"
DEFAULT_EC2_STOPPED_TITLE = "aurora-ec2-instance-stopped"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("aurora-to-snow")


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        log.error("Env file not found: %s", path)
        return env
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key] = value
    return env


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_api_healthy(env: dict[str, str]) -> bool:
    """Return True when Aurora liveness responds with HTTP 200 within timeout."""
    api_url = env.get("AURORA_API_URL", DEFAULT_API_URL).rstrip("/")
    timeout = int(
        env.get("AURORA_TO_SNOW_LIVENESS_TIMEOUT_SEC", str(DEFAULT_LIVENESS_TIMEOUT_SEC))
    )
    url = f"{api_url}/health/liveness"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as exc:
        log.warning("Aurora API liveness check failed (%s): %s", url, exc)
        return False


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class HttpClient:
    def __init__(self, timeout_sec: int = 60, verify_ssl: bool = True) -> None:
        self.timeout_sec = timeout_sec
        self.ctx = ssl.create_default_context()
        if not verify_ssl:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> dict[str, Any]:
        req = urllib.request.Request(url, data=body, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {url}: {detail[:1000]}") from exc


class AuroraClient:
    def __init__(self, env: dict[str, str], http: HttpClient) -> None:
        self.api_url = env.get("AURORA_API_URL", DEFAULT_API_URL).rstrip("/")
        self.user_id = env.get("AURORA_POLL_USER_ID", DEFAULT_USER_ID)
        self.org_id = env.get("AURORA_POLL_ORG_ID", DEFAULT_ORG_ID)
        self.internal_secret = env["INTERNAL_API_SECRET"]
        self.http = http

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-User-ID": self.user_id,
            "X-Org-ID": self.org_id,
            "X-Internal-Secret": self.internal_secret,
        }

    def list_incidents(self, limit: int = 50) -> list[dict[str, Any]]:
        url = f"{self.api_url}/api/incidents?limit={limit}"
        payload = self.http.request("GET", url, headers=self._headers())
        incidents = payload.get("incidents", [])
        return incidents if isinstance(incidents, list) else []

    def trigger_test_incident(self, title: str, description: str, service: str, severity: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "title": title,
                "issue_description": description,
                "service": service,
                "severity": severity,
            }
        ).encode("utf-8")
        url = f"{self.api_url}/api/incidents/trigger-rca"
        return self.http.request("POST", url, headers=self._headers(), body=body)


class ServiceNowClient:
    def __init__(self, env: dict[str, str], http: HttpClient) -> None:
        self.instance = env["SNOW_INSTANCE"].rstrip("/")
        user = env["SNOW_USER"]
        password = env["SNOW_PASSWORD"]
        token = b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}",
        }
        self.create_table = env.get("SNOW_CREATE_TABLE") or env.get("SNOW_TABLE", "incident")
        self.assignment_group = env.get("SNOW_CREATE_ASSIGNMENT_GROUP", "").strip()
        self.http = http

    def create_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.instance}/api/now/table/{self.create_table}"
        body = json.dumps(payload).encode("utf-8")
        result = self.http.request("POST", url, headers=self.headers, body=body)
        record = result.get("result", {})
        if not isinstance(record, dict) or not record.get("sys_id"):
            raise RuntimeError(f"Unexpected ServiceNow create response: {result!r}")
        return record

    def get_record(self, sys_id: str, fields: str = "sys_id,number,short_description,state") -> dict[str, Any]:
        params = urllib.parse.urlencode({"sysparm_fields": fields})
        url = f"{self.instance}/api/now/table/{self.create_table}/{sys_id}?{params}"
        result = self.http.request("GET", url, headers=self.headers)
        record = result.get("result", {})
        return record if isinstance(record, dict) else {}


def snow_priority(severity: str | None) -> str:
    return SEVERITY_TO_SNOW_PRIORITY.get((severity or "").strip().lower(), "3")


# Env var -> ServiceNow field for optional create payload defaults (IT#0011459263 template).
SNOW_CREATE_ENV_FIELDS = (
    ("SNOW_CREATE_COMPANY", "company"),
    ("SNOW_CREATE_SERVICE_REQ_TYPE", "service_req_type"),
    ("SNOW_CREATE_ACTUAL_SERVICE_REQUEST", "actual_service_request"),
    ("SNOW_CREATE_SERVICE_TYPE", "service_type"),
    ("SNOW_CREATE_CASE_TYPE", "case_type"),
    ("SNOW_CREATE_ASSIGNMENT_GROUP", "assignment_group"),
    ("SNOW_CREATE_CALLER_ID", "caller_id"),
    ("SNOW_CREATE_CATEGORY", "category"),
    ("SNOW_CREATE_URGENCY", "urgency"),
    ("SNOW_CREATE_IMPACT", "impact"),
    ("SNOW_CREATE_CONTACT_TYPE", "contact_type"),
    ("SNOW_CREATE_OPENED_BY", "opened_by"),
    ("SNOW_CREATE_USER_BELONGS_TO", "userbelongsto"),
)


def apply_snow_create_defaults(payload: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    for env_key, field in SNOW_CREATE_ENV_FIELDS:
        value = env.get(env_key, "").strip()
        if value:
            payload[field] = value
    priority = env.get("SNOW_CREATE_PRIORITY", "").strip()
    if priority:
        payload["priority"] = priority
    if "service_req_type" in payload and "actual_service_request" not in payload:
        actual = env.get("SNOW_CREATE_ACTUAL_SERVICE_REQUEST", "").strip()
        payload["actual_service_request"] = actual or payload["service_req_type"]
    return payload


def incident_metadata(incident: dict[str, Any]) -> dict[str, Any]:
    alert = incident.get("alert") or {}
    metadata = alert.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def already_linked(incident: dict[str, Any], state: dict[str, Any]) -> bool:
    incident_id = str(incident.get("id") or "")
    if not incident_id:
        return True
    if incident_id in state.get("exported", {}):
        return True
    metadata = incident_metadata(incident)
    for key in ("servicenow_sys_id", "snow_sys_id", "service_now_sys_id"):
        if metadata.get(key):
            return True
    return False


def imported_from_snow(incident_id: str, outbound_state: dict[str, Any]) -> bool:
    processed = outbound_state.get("processed", {})
    if not isinstance(processed, dict):
        return False
    for entry in processed.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("aurora_incident_id") or "") == incident_id:
            return True
    return False


def excluded_instance_ids(env: dict[str, str]) -> set[str]:
    """Instance IDs to ignore (e.g. Aurora host) when resolving affected EC2."""
    ids: set[str] = set()
    host = env.get("AURORA_HOST_INSTANCE_ID", "i-000311f7c2960f7c9").strip()
    if host and INSTANCE_ID_RE.fullmatch(host):
        ids.add(host)
    for part in env.get("SNOW_EXCLUDE_INSTANCE_IDS", "").split(","):
        part = part.strip()
        if INSTANCE_ID_RE.fullmatch(part):
            ids.add(part)
    return ids


def _valid_instance_id(value: str, excluded: set[str]) -> str:
    value = (value or "").strip()
    if INSTANCE_ID_RE.fullmatch(value) and value not in excluded:
        return value
    return ""


def _instance_ids_from_text(text: str, excluded: set[str]) -> list[str]:
    found: list[str] = []
    for match in INSTANCE_ID_RE.finditer(text or ""):
        iid = match.group(0)
        if iid not in excluded and iid not in found:
            found.append(iid)
    return found


def _instance_id_from_dimensions(dimensions: Any, excluded: set[str] | None = None) -> str:
    if not isinstance(dimensions, list):
        return ""
    excluded = excluded or set()
    preferred = ""
    fallback = ""
    for dim in dimensions:
        if not isinstance(dim, dict):
            continue
        name = str(dim.get("name") or dim.get("Name") or "").lower()
        value = str(dim.get("value") or dim.get("Value") or "").strip()
        if not _valid_instance_id(value, excluded):
            continue
        if "instanceid" in name.replace("_", ""):
            return value
        if not fallback:
            fallback = value
    return preferred or fallback


def extract_instance_id(
    incident: dict[str, Any], metadata: dict[str, Any], env: dict[str, str] | None = None,
) -> str:
    excluded = excluded_instance_ids(env or {})
    candidates: list[str] = []

    def add(value: str) -> None:
        valid = _valid_instance_id(value, excluded)
        if valid and valid not in candidates:
            candidates.append(valid)

    def add_from_text(text: str) -> None:
        for iid in _instance_ids_from_text(text, excluded):
            add(iid)

    add(_instance_id_from_dimensions(metadata.get("dimensions"), excluded))

    for key in ("InstanceId", "instance_id", "instanceId", "ec2_instance_id"):
        add(str(metadata.get(key) or ""))

    payloads: list[Any] = [metadata]
    for key in ("raw_payload", "payload", "alarm_payload", "message"):
        if key in metadata:
            payloads.append(metadata.get(key))
    for payload in payloads:
        if isinstance(payload, dict):
            trigger = payload.get("Trigger")
            if isinstance(trigger, dict):
                add(_instance_id_from_dimensions(trigger.get("Dimensions"), excluded))
            add(_instance_id_from_dimensions(payload.get("Dimensions"), excluded))

    add_from_text(str(metadata.get("user_description") or ""))

    alert = incident.get("alert") or {}
    add(str(alert.get("service") or ""))
    add(str(metadata.get("service") or ""))

    add_from_text(str(incident.get("summary") or ""))
    add_from_text(json.dumps(metadata, default=str))

    return candidates[0] if candidates else ""


def build_snow_title(incident: dict[str, Any], env: dict[str, str], metadata: dict[str, Any]) -> str:
    prefix = env.get("SNOW_TITLE_PREFIX", "Server down").strip() or "Server down"
    instance_id = extract_instance_id(incident, metadata, env)
    if instance_id:
        return f"{prefix} - {instance_id}"[:160]
    service = str((incident.get("alert") or {}).get("service") or "unknown").strip()
    return f"{prefix} - {service}"[:160]


def build_snow_payload(incident: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    incident_id = str(incident.get("id") or "")
    alert = incident.get("alert") or {}
    metadata = incident_metadata(incident)
    title = build_snow_title(incident, env, metadata)
    service = (alert.get("service") or "unknown").strip()
    instance_id = extract_instance_id(incident, metadata, env)
    severity = (incident.get("severity") or alert.get("severity") or "medium").strip()
    summary = (incident.get("summary") or "").strip()
    frontend = env.get("FRONTEND_URL", "https://aurora.sifylivelearn.com").rstrip("/")
    incident_url = f"{frontend}/incidents/{incident_id}"

    description_lines = snow_description_lines(
        incident,
        env,
        incident_id,
        service,
        instance_id,
        severity,
        incident_url,
        summary,
        metadata,
    )

    payload: dict[str, Any] = {
        "short_description": title[:160],
        "description": "\n".join(description_lines)[:4000],
        "priority": snow_priority(severity),
    }
    return apply_snow_create_defaults(payload, env)


def brand_name(env: dict[str, str]) -> str:
    return env.get("INFINITAIZEN_BRAND_NAME", DEFAULT_BRAND_NAME).strip() or DEFAULT_BRAND_NAME


def ec2_stopped_incident_title(env: dict[str, str]) -> str:
    return (
        env.get("INFINITAIZEN_EC2_STOPPED_TITLE", DEFAULT_EC2_STOPPED_TITLE).strip()
        or DEFAULT_EC2_STOPPED_TITLE
    )


def snow_description_lines(
    incident: dict[str, Any],
    env: dict[str, str],
    incident_id: str,
    service: str,
    instance_id: str,
    severity: str,
    incident_url: str,
    summary: str,
    metadata: dict[str, Any],
) -> list[str]:
    label = brand_name(env)
    description_lines = [
        f"{label} Incident: {incident_id}",
        f"Service: {service}",
    ]
    if instance_id:
        description_lines.append(f"Instance ID: {instance_id}")
    description_lines.extend(
        [
            f"Severity: {severity}",
            f"Status: {incident.get('status', 'investigating')}",
            f"{label} URL: {incident_url}",
        ]
    )
    if summary:
        description_lines.extend(["", f"{label} summary:", summary])
    user_description = metadata.get("user_description")
    if user_description:
        description_lines.extend(["", "Original description:", str(user_description)])
    return description_lines


def build_snow_incident_metadata(
    record: dict[str, Any],
    snow: ServiceNowClient,
    exported_at: str,
) -> dict[str, str]:
    sys_id = str(record.get("sys_id") or "")
    number = str(record.get("number") or "")
    return {
        "snow_sys_id": sys_id,
        "servicenow_sys_id": sys_id,
        "service_now_sys_id": sys_id,
        "snow_number": number,
        "snow_table": snow.create_table,
        "snow_url": f"{snow.instance}/{snow.create_table}.do?sys_id={sys_id}",
        "snow_exported_at": exported_at,
    }


def write_snow_metadata_to_incident(
    incident_id: str,
    snow_info: dict[str, str],
    env: dict[str, str],
) -> None:
    container = env.get("AURORA_POSTGRES_CONTAINER", "aurora-postgres")
    db_user = env.get("POSTGRES_USER", "aurora")
    db_name = env.get("POSTGRES_DB", "aurora_db")
    meta_json = json.dumps(snow_info).replace("'", "''")
    sql = (
        "UPDATE incidents "
        f"SET alert_metadata = COALESCE(alert_metadata, '{{}}'::jsonb) || '{meta_json}'::jsonb, "
        "updated_at = CURRENT_TIMESTAMP "
        f"WHERE id = '{incident_id}'::uuid "
        "RETURNING id;"
    )
    cmd = [
        "docker", "exec", container,
        "psql", "-U", db_user, "-d", db_name, "-t", "-A", "-c", sql,
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Failed to update incident alert_metadata: {exc.output}") from exc
    first_line = out.splitlines()[0].strip() if out else ""
    if first_line != incident_id:
        raise RuntimeError(
            f"Incident {incident_id} not updated in Postgres (returned {out!r})"
        )
    log.info("Updated incident %s alert_metadata with ServiceNow link", incident_id)


def read_incident_snow_metadata(incident_id: str, env: dict[str, str]) -> dict[str, Any]:
    container = env.get("AURORA_POSTGRES_CONTAINER", "aurora-postgres")
    db_user = env.get("POSTGRES_USER", "aurora")
    db_name = env.get("POSTGRES_DB", "aurora_db")
    sql = (
        "SELECT COALESCE(alert_metadata, '{}'::jsonb)::text "
        f"FROM incidents WHERE id = '{incident_id}'::uuid;"
    )
    cmd = [
        "docker", "exec", container,
        "psql", "-U", db_user, "-d", db_name, "-t", "-A", "-c", sql,
    ]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    if not out:
        return {}
    data = json.loads(out)
    return data if isinstance(data, dict) else {}


def export_incident(
    incident: dict[str, Any],
    snow: ServiceNowClient,
    env: dict[str, str],
    state: dict[str, Any],
) -> bool:
    incident_id = str(incident.get("id") or "")
    if already_linked(incident, state):
        return False
    if imported_from_snow(incident_id, load_json(OUTBOUND_STATE_PATH, {"processed": {}})):
        log.info("Skipping %s (originated from ServiceNow inbound poller)", incident_id)
        return False

    payload = build_snow_payload(incident, env)
    log.info("Creating ServiceNow record for Aurora incident %s", incident_id)
    record = snow.create_record(payload)
    exported_at = datetime.now(timezone.utc).isoformat()
    snow_info = build_snow_incident_metadata(record, snow, exported_at)
    write_snow_metadata_to_incident(incident_id, snow_info, env)
    exported = state.setdefault("exported", {})
    exported[incident_id] = {
        "snow_sys_id": record.get("sys_id"),
        "snow_number": record.get("number"),
        "table": snow.create_table,
        "title": payload.get("short_description"),
        "exported_at": exported_at,
    }
    log.info(
        "Created ServiceNow %s (%s) for Aurora incident %s",
        record.get("number") or record.get("sys_id"),
        record.get("sys_id"),
        incident_id,
    )
    return True


def poll_once(env: dict[str, str]) -> dict[str, int]:
    if not truthy(env.get("SNOW_EXPORT_ENABLED")):
        log.info("SNOW_EXPORT_ENABLED is false; skipping")
        return {"checked": 0, "exported": 0}

    if truthy(env.get("AURORA_TO_SNOW_SKIP_ON_UNHEALTHY", "true")):
        if not is_api_healthy(env):
            log.warning("Skipping SNOW export: Aurora API is unhealthy")
            return {"checked": 0, "exported": 0}

    for key in ("SNOW_INSTANCE", "SNOW_USER", "SNOW_PASSWORD", "INTERNAL_API_SECRET"):
        if not env.get(key):
            log.error("Missing required env var: %s", key)
            return {"checked": 0, "exported": 0}

    timeout = int(env.get("AURORA_TO_SNOW_TIMEOUT_SEC", "60"))
    verify_ssl = truthy(env.get("SNOW_VERIFY_SSL", "true"))
    http = HttpClient(timeout_sec=timeout, verify_ssl=verify_ssl)
    aurora = AuroraClient(env, http)
    snow = ServiceNowClient(env, http)
    state = load_json(STATE_PATH, {"exported": {}, "last_run": None})

    limit = int(env.get("AURORA_TO_SNOW_LIMIT", "50"))
    incidents = aurora.list_incidents(limit=limit)
    exported_count = 0
    for incident in incidents:
        try:
            if export_incident(incident, snow, env, state):
                exported_count += 1
        except Exception as exc:
            log.error("Failed exporting incident %s: %s", incident.get("id"), exc)

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_json(STATE_PATH, state)
    return {"checked": len(incidents), "exported": exported_count}


def run_test(env: dict[str, str]) -> int:
    """Create a test Aurora incident, export to SNOW, verify record exists."""
    timeout = int(env.get("AURORA_TO_SNOW_TIMEOUT_SEC", "60"))
    verify_ssl = truthy(env.get("SNOW_VERIFY_SSL", "true"))
    http = HttpClient(timeout_sec=timeout, verify_ssl=verify_ssl)
    aurora = AuroraClient(env, http)
    snow = ServiceNowClient(env, http)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    test_instance_id = env.get("SNOW_TEST_INSTANCE_ID", "i-0904ee0fe91daa25f").strip()
    if not INSTANCE_ID_RE.fullmatch(test_instance_id):
        raise RuntimeError(f"Invalid SNOW_TEST_INSTANCE_ID: {test_instance_id!r}")
    title = ec2_stopped_incident_title(env)
    description = (
        f"EC2 instance {test_instance_id} has stopped. "
        f"Automated end-to-end test for {brand_name(env)} -> ServiceNow export ({stamp})."
    )
    created = aurora.trigger_test_incident(
        title=title,
        description=description,
        service=test_instance_id,
        severity="high",
    )
    incident_id = str(created.get("incident_id") or "")
    if not incident_id:
        raise RuntimeError(f"Failed to create test incident: {created}")

    log.info("Created test Aurora incident %s", incident_id)
    incidents = aurora.list_incidents(limit=20)
    incident = next((row for row in incidents if str(row.get("id")) == incident_id), None)
    if not incident:
        raise RuntimeError(f"Test incident {incident_id} not found in incident list")

    state = load_json(STATE_PATH, {"exported": {}})
    if not export_incident(incident, snow, env, state):
        raise RuntimeError("Export step did not create a ServiceNow record")
    save_json(STATE_PATH, state)

    exported = state["exported"][incident_id]
    sys_id = exported["snow_sys_id"]
    record = snow.get_record(sys_id)
    if not record.get("sys_id"):
        raise RuntimeError(f"Could not verify ServiceNow record {sys_id}")

    incident_metadata_db = read_incident_snow_metadata(incident_id, env)
    if incident_metadata_db.get("snow_sys_id") != sys_id:
        raise RuntimeError(
            f"Incident alert_metadata missing snow_sys_id (got {incident_metadata_db!r})"
        )

    print(
        json.dumps(
            {
                "ok": True,
                "aurora_incident_id": incident_id,
                "snow_sys_id": sys_id,
                "snow_number": exported.get("snow_number") or record.get("number"),
                "snow_table": snow.create_table,
                "short_description": record.get("short_description"),
                "expected_title": build_snow_title(incident, env, incident_metadata(incident)),
                "instance_id": extract_instance_id(incident, incident_metadata(incident), env),
                "test_instance_id": test_instance_id,
                "incident_alert_metadata": {
                    "snow_sys_id": incident_metadata_db.get("snow_sys_id"),
                    "snow_number": incident_metadata_db.get("snow_number"),
                    "snow_url": incident_metadata_db.get("snow_url"),
                    "snow_exported_at": incident_metadata_db.get("snow_exported_at"),
                },
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    env = load_env(ENV_PATH)
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        return run_test(env)
    stats = poll_once(env)
    log.info(
        "Aurora -> ServiceNow poll complete (checked=%s, exported=%s)",
        stats["checked"],
        stats["exported"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
