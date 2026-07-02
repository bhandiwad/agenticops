"""Langfuse tracing for the agent + LLM layer.

Design goal: uniform coverage across *every* agent — LangGraph agents, "typed"/direct-LLM
agents (RCA triage, synthesis, guardrails, summarizers), sub-agents, and future user-built or
imported agents — by instrumenting the shared chokepoints rather than each agent:

- ``@observe`` (or ``traced``) wraps agent-dispatch / workflow-node / direct-LLM entrypoints to
  create a trace span and propagate context.
- ``langchain_handler()`` returns a Langfuse LangChain callback handler to attach at the
  LangGraph / LLM invoke sites; it auto-nests generations + tool calls under the active span.
- ``update_trace()`` tags the active trace with session / user / incident / workflow ids so a
  trace is discoverable from an incident or a workflow run.

Everything is OFF unless ``LANGFUSE_ENABLED`` is truthy and keys are present, and every call is
defensive — tracing must NEVER break or slow an agent. Secrets are masked before export.
"""

from __future__ import annotations

import logging
import os
import re
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

# Redact values whose key or content looks like a credential before anything leaves the process.
_SECRET_KEY_RE = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|apikey|authorization|auth|credential|private[_-]?key|"
    r"bearer|session|cookie)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._\-]+|eyJ[A-Za-z0-9._\-]{10,}|(?:sk|pk|xox[bpsa])-[A-Za-z0-9._\-]{8,}|"
    r"AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})",
)
_REDACTED = "***REDACTED***"


def enabled() -> bool:
    return (
        os.getenv("LANGFUSE_ENABLED", "false").strip().lower() in _TRUTHY
        and bool(os.getenv("LANGFUSE_PUBLIC_KEY"))
        and bool(os.getenv("LANGFUSE_SECRET_KEY"))
    )


def _mask(data: Any, _depth: int = 0) -> Any:
    """Recursively redact credential-looking keys/values. Bounded depth for safety."""
    if _depth > 6:
        return data
    try:
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                    out[k] = _REDACTED
                else:
                    out[k] = _mask(v, _depth + 1)
            return out
        if isinstance(data, (list, tuple)):
            return type(data)(_mask(v, _depth + 1) for v in data)
        if isinstance(data, str):
            return _SECRET_VALUE_RE.sub(_REDACTED, data)
    except Exception:  # noqa: BLE001 - masking must never raise
        return _REDACTED
    return data


_client = None
_client_tried = False


def _get_client():
    """Lazily construct the singleton Langfuse client (or None). Never raises."""
    global _client, _client_tried
    if _client is not None or _client_tried:
        return _client
    _client_tried = True
    if not enabled():
        return None
    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000"),
            mask=_mask,
        )
        logger.info("[Tracing] Langfuse client initialized (host=%s)", os.getenv("LANGFUSE_HOST"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Tracing] Langfuse init failed; tracing disabled: %s", exc)
        _client = None
    return _client


def langchain_handler():
    """Return a Langfuse LangChain CallbackHandler to append to an invoke's callbacks, or None.

    Attach at LangGraph / LLM invoke sites: ``config={"callbacks": [*existing, handler]}``.
    The handler nests generations/tool-calls under the active ``@observe`` span automatically.
    """
    if _get_client() is None:
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Tracing] CallbackHandler unavailable: %s", exc)
        return None


def observe(name: Optional[str] = None, as_type: Optional[str] = None) -> Callable:
    """Decorator that traces a function as a span when tracing is enabled, else a no-op.

    Use on agent-dispatch / workflow-node / direct-LLM entrypoints so typed and sub-agents
    become proper parent spans with their LLM + tool calls nested underneath.
    """
    def decorator(fn: Callable) -> Callable:
        if not enabled():
            return fn
        try:
            from langfuse import observe as _lf_observe
        except Exception:  # noqa: BLE001
            return fn
        kwargs = {}
        if name:
            kwargs["name"] = name
        if as_type:
            kwargs["as_type"] = as_type

        try:
            wrapped = _lf_observe(**kwargs)(fn)
        except Exception:  # noqa: BLE001
            return fn

        @wraps(fn)
        def guard(*a, **k):
            try:
                return wrapped(*a, **k)
            except Exception:
                # A failure inside the langfuse wrapper must not lose the real call.
                return fn(*a, **k)
        return guard
    return decorator


def update_trace(**attrs: Any) -> None:
    """Tag the active trace (session_id, user_id, tags, metadata, input, output). No-op if off."""
    client = _get_client()
    if client is None:
        return
    try:
        clean = {k: v for k, v in attrs.items() if v is not None}
        if "metadata" in clean:
            clean["metadata"] = _mask(clean["metadata"])
        client.update_current_trace(**clean)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Tracing] update_trace failed: %s", exc)


def get_trace_url() -> Optional[str]:
    """URL of the current trace (for 'open trace' links from incidents/workflows), or None."""
    client = _get_client()
    if client is None:
        return None
    try:
        return client.get_trace_url()
    except Exception:  # noqa: BLE001
        return None


def flush() -> None:
    """Flush buffered events (call at the end of a background run so nothing is lost)."""
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:  # noqa: BLE001
        pass
