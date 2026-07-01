"""WhatsApp notification tool (Meta Cloud API).

send_whatsapp sends a text message via the connected WhatsApp Business number. Registered in
background/workflow execution only, so automated workflows can notify a recipient (e.g. on
approval-needed or completion) but interactive chat cannot message people ad hoc.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from connectors.whatsapp_connector.client import WhatsAppClient, WhatsAppAPIError
from routes.whatsapp.config import DEFAULT_API_VERSION
from utils.auth.token_management import get_token_data

logger = logging.getLogger(__name__)


class SendWhatsAppArgs(BaseModel):
    to: str = Field(description="Recipient phone number in international format (E.164), e.g. 15551234567.")
    message: str = Field(description="The text message to send.")


def _stored(user_id: str) -> Optional[dict]:
    data = get_token_data(user_id, "whatsapp")
    if data and data.get("access_token") and data.get("phone_number_id"):
        return data
    return None


def is_whatsapp_connected(user_id: str) -> bool:
    return _stored(user_id) is not None


def send_whatsapp(to: str, message: str, user_id: Optional[str] = None) -> str:
    if not user_id:
        return json.dumps({"ok": False, "error": "User context not available"})
    data = _stored(user_id)
    if not data:
        return json.dumps({"ok": False, "error": "WhatsApp not connected"})
    if not (to or "").strip() or not (message or "").strip():
        return json.dumps({"ok": False, "error": "Both 'to' and 'message' are required"})

    client = WhatsAppClient(
        access_token=data["access_token"],
        phone_number_id=data["phone_number_id"],
        api_version=data.get("api_version") or DEFAULT_API_VERSION,
    )
    try:
        result = client.send_text(to, message)
    except WhatsAppAPIError as exc:
        return json.dumps({"ok": False, "error": str(exc)})

    msgs = result.get("messages") or []
    return json.dumps({"ok": True, "message_id": (msgs[0].get("id") if msgs else None), "to": to})
