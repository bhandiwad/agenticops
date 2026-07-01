"""ServiceNow Table API client for the Aurora connector."""
from __future__ import annotations

import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from typing import Any

logger = logging.getLogger(__name__)

TICKET_NUMBER_RE = re.compile(r"(?i)\b((?:IT#|INC)?\d{6,})\b")
DEFAULT_TABLE = "incident"
TIMEOUT_SEC = 60


class ServiceNowAPIError(Exception):
    """Raised when a ServiceNow API call fails."""


class ServiceNowClient:
    """Thin wrapper around the ServiceNow Table API."""

    def __init__(
        self,
        instance: str,
        username: str,
        password: str,
        *,
        table: str = DEFAULT_TABLE,
        verify_ssl: bool = True,
        resolve_state: str = "4",
        resolve_active: str = "false",
    ) -> None:
        self.instance = instance.rstrip("/")
        self.username = username
        self.password = password
        self.table = table or DEFAULT_TABLE
        self.verify_ssl = verify_ssl
        self.resolve_state = resolve_state
        self.resolve_active = resolve_active

    @staticmethod
    def normalize_instance_url(raw: str) -> str | None:
        value = (raw or "").strip().rstrip("/")
        if not value:
            return None
        if not re.match(r"^https?://", value, re.IGNORECASE):
            value = f"https://{value}"
        if not re.match(r"^https?://[A-Za-z0-9._-]+", value):
            return None
        return value

    @staticmethod
    def normalize_ticket_number(ticket_number: str) -> str:
        value = (ticket_number or "").strip()
        if not value:
            return ""
        match = TICKET_NUMBER_RE.search(value)
        return (match.group(1) if match else value).upper()

    @property
    def _headers(self) -> dict[str, str]:
        token = b64encode(f"{self.username}:{self.password}".encode()).decode()
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}",
        }

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.instance}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers)
        ctx = ssl.create_default_context()
        if not self.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT_SEC) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ServiceNowAPIError(f"HTTP {exc.code}: {detail[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise ServiceNowAPIError(f"Connection error: {exc}") from exc

    @staticmethod
    def display_val(raw: Any) -> Any:
        if isinstance(raw, dict):
            return raw.get("display_value") or raw.get("value")
        return raw

    def validate_connection(self) -> dict[str, Any]:
        """Lightweight connectivity check against the configured table."""
        path = (
            f"/api/now/table/{urllib.parse.quote(self.table, safe='')}"
            f"?sysparm_limit=1&sysparm_fields=sys_id,number"
        )
        payload = self._request("GET", path)
        count = len(payload.get("result") or [])
        return {"ok": True, "table": self.table, "sample_rows": count}

    def get_ticket_by_number(self, ticket_number: str) -> dict[str, Any]:
        normalized = self.normalize_ticket_number(ticket_number)
        if not normalized:
            raise ValueError("ticket_number is required")
        query = urllib.parse.quote(f"number={normalized}")
        path = (
            f"/api/now/table/{urllib.parse.quote(self.table, safe='')}"
            f"?sysparm_query={query}&sysparm_display_value=all&sysparm_limit=1"
        )
        payload = self._request("GET", path)
        results = payload.get("result") or []
        if not results:
            raise ServiceNowAPIError(f"No ticket found for number {normalized}")
        return self.format_ticket(results[0])

    def get_ticket_by_sys_id(self, sys_id: str, table: str | None = None) -> dict[str, Any]:
        tbl = table or self.table
        path = (
            f"/api/now/table/{urllib.parse.quote(tbl, safe='')}"
            f"/{sys_id}?sysparm_display_value=all"
        )
        payload = self._request("GET", path)
        record = payload.get("result")
        if not record:
            raise ServiceNowAPIError(f"No ticket found for sys_id {sys_id}")
        return self.format_ticket(record, table=tbl)

    def get_ci_by_name(self, name: str) -> dict[str, Any] | None:
        """Look up a Configuration Item in the CMDB by name (cmdb_ci)."""
        q = urllib.parse.quote(f"name={name}")
        payload = self._request(
            "GET",
            f"/api/now/table/cmdb_ci?sysparm_query={q}&sysparm_display_value=all&sysparm_limit=1",
        )
        result = payload.get("result") or []
        return result[0] if result else None

    def get_ci_relationships(self, ci_sys_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """Return cmdb_rel_ci rows where the CI is the parent or child (its topology neighbors)."""
        q = urllib.parse.quote(f"parent={ci_sys_id}^ORchild={ci_sys_id}")
        payload = self._request(
            "GET",
            f"/api/now/table/cmdb_rel_ci?sysparm_query={q}&sysparm_display_value=all&sysparm_limit={limit}",
        )
        return payload.get("result") or []

    def resolve_ticket(self, sys_id: str, *, table: str | None = None, close_notes: str = "") -> dict[str, Any]:
        tbl = table or self.table
        get_path = (
            f"/api/now/table/{urllib.parse.quote(tbl, safe='')}/{sys_id}"
            f"?sysparm_fields=number,state,active&sysparm_display_value=all"
        )
        current = self._request("GET", get_path).get("result", {})
        current_state = str(self.display_val(current.get("state")) or "")
        if current_state == self.resolve_state:
            return {
                "status": "already_resolved",
                "snow_sys_id": sys_id,
                "snow_number": self.display_val(current.get("number")),
                "state": current_state,
            }
        patch_body: dict[str, Any] = {
            "state": self.resolve_state,
            "active": self.resolve_active in ("1", "true", "yes", "on"),
        }
        if close_notes.strip():
            patch_body["close_notes"] = close_notes.strip()[:4000]
        patch_path = f"/api/now/table/{urllib.parse.quote(tbl, safe='')}/{sys_id}"
        updated = self._request("PATCH", patch_path, patch_body).get("result", {})
        return {
            "status": "resolved",
            "snow_sys_id": sys_id,
            "snow_number": self.display_val(updated.get("number")),
            "previous_state": current_state,
            "new_state": self.display_val(updated.get("state")),
            "active": self.display_val(updated.get("active")),
        }

    def format_ticket(self, record: dict[str, Any], table: str | None = None) -> dict[str, Any]:
        tbl = table or self.table
        sys_id = self.display_val(record.get("sys_id")) or record.get("sys_id")
        number = self.display_val(record.get("number"))
        return {
            "ticket_number": number,
            "snow_sys_id": sys_id,
            "snow_table": tbl,
            "snow_url": f"{self.instance}/{tbl}.do?sys_id={sys_id}",
            "state": self.display_val(record.get("state")),
            "active": self.display_val(record.get("active")),
            "short_description": self.display_val(record.get("short_description")),
            "description": self.display_val(record.get("description")),
            "priority": self.display_val(record.get("priority")),
            "urgency": self.display_val(record.get("urgency")),
            "impact": self.display_val(record.get("impact")),
            "assignment_group": self.display_val(record.get("assignment_group")),
            "assigned_to": self.display_val(record.get("assigned_to")),
            "company": self.display_val(record.get("company")),
            "contact_type": self.display_val(record.get("contact_type")),
            "opened_at": self.display_val(record.get("opened_at")),
            "sys_updated_on": self.display_val(record.get("sys_updated_on")),
            "close_notes": self.display_val(record.get("close_notes")),
            "work_notes": self.display_val(record.get("work_notes")),
        }

    def to_token_payload(self) -> dict[str, Any]:
        return {
            "instance": self.instance,
            "username": self.username,
            "password": self.password,
            "table": self.table,
            "verify_ssl": self.verify_ssl,
            "resolve_state": self.resolve_state,
            "resolve_active": self.resolve_active,
        }

    @classmethod
    def from_token_data(cls, data: dict[str, Any]) -> "ServiceNowClient":
        return cls(
            instance=data["instance"],
            username=data["username"],
            password=data["password"],
            table=data.get("table") or DEFAULT_TABLE,
            verify_ssl=bool(data.get("verify_ssl", True)),
            resolve_state=str(data.get("resolve_state") or "4"),
            resolve_active=str(data.get("resolve_active") or "false"),
        )


def load_client_for_user(user_id: str | None) -> ServiceNowClient | None:
    """Load connector credentials from Vault for a user."""
    if not user_id:
        return None
    try:
        from utils.auth.token_management import get_token_data
        data = get_token_data(user_id, "servicenow")
        if data and data.get("instance") and data.get("username") and data.get("password"):
            return ServiceNowClient.from_token_data(data)
    except Exception as exc:
        logger.debug("[ServiceNow] Could not load user credentials: %s", exc)
    return None


def load_client_from_env() -> ServiceNowClient | None:
    """Fallback to process environment (legacy .env integration)."""
    instance = (os.getenv("SNOW_INSTANCE") or "").strip()
    user = (os.getenv("SNOW_USER") or "").strip()
    password = (os.getenv("SNOW_PASSWORD") or "").strip()
    if not instance or not user or not password:
        return None
    return ServiceNowClient(
        instance=instance,
        username=user,
        password=password,
        table=(os.getenv("SNOW_CREATE_TABLE") or os.getenv("SNOW_TABLE") or DEFAULT_TABLE).strip(),
        verify_ssl=(os.getenv("SNOW_VERIFY_SSL") or "true").strip().lower() not in ("0", "false", "no"),
        resolve_state=(os.getenv("SNOW_RESOLVE_STATE") or "4").strip(),
        resolve_active=(os.getenv("SNOW_RESOLVE_ACTIVE") or "false").strip().lower(),
    )


def get_client(user_id: str | None = None) -> ServiceNowClient:
    """Prefer per-user connector credentials; fall back to env."""
    client = load_client_for_user(user_id) or load_client_from_env()
    if not client:
        raise ValueError(
            "ServiceNow is not configured. Connect ServiceNow in Connectors "
            "or set SNOW_INSTANCE, SNOW_USER, SNOW_PASSWORD."
        )
    return client
