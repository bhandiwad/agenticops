"""High-level Microsoft Teams notification operations for agents and routes.

Teams notifications are delivered via an Incoming Webhook URL the user pastes in.
We POST a MessageCard payload to that webhook — there is no OAuth flow.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from utils.auth.token_management import get_token_data
from utils.log_sanitizer import sanitize

logger = logging.getLogger(__name__)


def post_teams_message(user_id: str, text: str, title: str | None = None) -> dict[str, Any]:
    """Send a message to the user's configured Teams Incoming Webhook.

    Best-effort: never raises. Returns ``{"ok": True}`` or
    ``{"ok": False, "error": ...}``. The webhook URL is never logged.
    """
    try:
        creds = get_token_data(user_id, "teams") or {}
    except Exception as exc:
        logger.error("[Teams] Failed to load webhook for %s: %s", sanitize(user_id), exc)
        return {"ok": False, "error": "Failed to load Teams webhook"}

    webhook_url = creds.get("webhook_url")
    if not webhook_url:
        return {"ok": False, "error": "Teams is not connected"}

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": title or "AgenticOps",
        "themeColor": "6264A7",
        "title": title,
        "text": text,
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code >= 400:
            logger.warning("[Teams] Webhook returned %s for user %s", resp.status_code, sanitize(user_id))
            return {"ok": False, "error": f"Teams webhook returned status {resp.status_code}"}
        return {"ok": True}
    except Exception as exc:
        logger.warning("[Teams] Failed to post message for %s: %s", sanitize(user_id), exc)
        return {"ok": False, "error": "Failed to post message to Teams"}
