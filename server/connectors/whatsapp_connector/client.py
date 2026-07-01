"""WhatsApp Business Cloud API client (Meta Graph API).

Sends messages via the Meta WhatsApp Business Cloud API. The host is fixed
(``graph.facebook.com``), so this is a normal SaaS integration — no SSRF allowlist is needed.
Auth is a permanent access token (system-user token); the sender is identified by a phone
number id. Text and pre-approved template messages are supported (templates are required to
initiate conversations outside the 24-hour session window).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

WHATSAPP_TIMEOUT = 20
DEFAULT_API_VERSION = "v21.0"
GRAPH_HOST = "https://graph.facebook.com"


class WhatsAppAPIError(Exception):
    """Raised for WhatsApp Cloud API / connectivity failures."""


class WhatsAppClient:
    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        api_version: str = DEFAULT_API_VERSION,
        timeout: int = WHATSAPP_TIMEOUT,
    ):
        self.access_token = access_token
        self.phone_number_id = str(phone_number_id or "").strip()
        self.api_version = (api_version or DEFAULT_API_VERSION).strip()
        self.timeout = timeout

    def _base(self) -> str:
        return f"{GRAPH_HOST}/{self.api_version}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self._base()}{path}"
        try:
            resp = requests.request(method, url, headers=self._headers(), json=json_body, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.error("[WHATSAPP] %s %s network error: %s", method, path, exc)
            raise WhatsAppAPIError("Unable to reach the WhatsApp Cloud API") from exc

        if resp.status_code in (401, 403):
            raise WhatsAppAPIError("WhatsApp rejected the access token (unauthorized)")
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            err = (data.get("error") or {}) if isinstance(data, dict) else {}
            raise WhatsAppAPIError(f"WhatsApp API error {resp.status_code}: {err.get('message', resp.text[:300])}")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    def validate(self) -> Dict[str, Any]:
        """Confirm the token + phone number id by reading the sender's number metadata."""
        if not self.phone_number_id:
            raise WhatsAppAPIError("phone_number_id is required")
        return self._request("GET", f"/{self.phone_number_id}?fields=display_phone_number,verified_name,quality_rating")

    def send_text(self, to: str, body: str, preview_url: bool = False) -> Dict[str, Any]:
        """Send a plain text message. ``to`` is an E.164 number without '+' (e.g. 15551234567)."""
        recipient = str(to or "").strip().lstrip("+")
        if not recipient:
            raise WhatsAppAPIError("recipient number 'to' is required")
        if not (body or "").strip():
            raise WhatsAppAPIError("message body is required")
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": bool(preview_url), "body": body[:4096]},
        }
        return self._request("POST", f"/{self.phone_number_id}/messages", json_body=payload)

    def send_template(self, to: str, template_name: str, language: str = "en_US",
                      components: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Send a pre-approved template message (needed to open a conversation)."""
        recipient = str(to or "").strip().lstrip("+")
        if not recipient:
            raise WhatsAppAPIError("recipient number 'to' is required")
        template: Dict[str, Any] = {"name": template_name, "language": {"code": language}}
        if components:
            template["components"] = components
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": template,
        }
        return self._request("POST", f"/{self.phone_number_id}/messages", json_body=payload)
