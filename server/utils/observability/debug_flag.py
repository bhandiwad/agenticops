"""Per-user 'debug tracing' flag, stored in Redis (no schema change, cross-process).

When a user enables debug tracing, their agent runs are tagged ``debug`` in Langfuse and tool
outputs are captured at full fidelity (no truncation) so a run can be inspected end-to-end.
Reads are cheap and fail-open to False so this never affects normal execution.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_KEY = "aurora:trace_debug:{}"
_TTL_SECONDS = 7 * 24 * 3600  # auto-expire so a forgotten toggle doesn't linger forever


def _redis():
    try:
        from utils.cache.redis_client import get_redis_client
        return get_redis_client()
    except Exception:  # noqa: BLE001
        return None


def is_debug_enabled(user_id: str | None) -> bool:
    if not user_id:
        return False
    r = _redis()
    if r is None:
        return False
    try:
        return bool(r.get(_KEY.format(user_id)))
    except Exception:  # noqa: BLE001
        return False


def set_debug(user_id: str, enabled: bool) -> bool:
    r = _redis()
    if r is None:
        return False
    try:
        key = _KEY.format(user_id)
        if enabled:
            r.set(key, "1", ex=_TTL_SECONDS)
        else:
            r.delete(key)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("[Tracing] set_debug failed", exc_info=True)
        return False
