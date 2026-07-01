"""
LLM Provider Registry and Factory.

This module provides a registry of all available LLM providers and a factory
for creating chat model instances based on provider selection strategy.

Provider Selection Modes:
- 'direct': Use direct provider APIs based on model prefix (default)
- 'auto': Same as direct - resolve provider from model, no fallback
- 'openrouter': Use OpenRouter for all models (explicit only)

Note: OpenRouter is NOT a fallback. If direct provider is unavailable,
the call will fail with a clear error message.

Environment Variables:
- LLM_PROVIDER_MODE: Selection strategy (default: 'direct')
- OPENROUTER_API_KEY: OpenRouter API key (only needed if mode=openrouter)
- OPENAI_API_KEY: Direct OpenAI API key
- ANTHROPIC_API_KEY: Direct Anthropic API key
- GOOGLE_AI_API_KEY: Google AI Studio API key
"""

import logging
import os
from typing import Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from .base_provider import BaseLLMProvider
from .openrouter_provider import OpenRouterProvider
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider
from .google_provider import GoogleProvider
from .vertex_provider import VertexAIProvider
from .ollama_provider import OllamaProvider
from .bedrock_provider import BedrockProvider
from ..model_mapper import ModelMapper

logger = logging.getLogger(__name__)

# Hint for which env var configures each provider (used in "not available" errors).
_ENV_VAR_HINTS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_AI_API_KEY",
    "vertex": "VERTEX_AI_PROJECT",
    "ollama": "OLLAMA_BASE_URL",
    "bedrock": "BEDROCK_BASE_URL or BEDROCK_REGION",
    "openrouter": "OPENROUTER_API_KEY",
}


class ProviderRegistry:
    """Registry of all available LLM providers."""

    def __init__(self):
        """Initialize the provider registry."""
        self._providers: Dict[str, BaseLLMProvider] = {}
        self._initialize_providers()

    def _initialize_providers(self):
        """Initialize all provider instances."""
        # OpenRouter provider (explicit mode only, not a fallback)
        self._providers["openrouter"] = OpenRouterProvider()

        # Initialize direct providers
        self._providers["openai"] = OpenAIProvider()
        self._providers["anthropic"] = AnthropicProvider()
        self._providers["google"] = GoogleProvider()
        self._providers["vertex"] = VertexAIProvider()
        self._providers["ollama"] = OllamaProvider()
        self._providers["bedrock"] = BedrockProvider()

        logger.info("Initialized provider registry")

    def get_provider(self, provider_name: str) -> Optional[BaseLLMProvider]:
        """
        Get a provider by name.

        Args:
            provider_name: Name of the provider

        Returns:
            Provider instance or None if not found
        """
        return self._providers.get(provider_name)

    def get_available_providers(self) -> Dict[str, BaseLLMProvider]:
        """
        Get all providers that are currently available (have valid credentials).

        Returns:
            Dictionary of available provider instances
        """
        return {
            name: provider
            for name, provider in self._providers.items()
            if provider.is_available()
        }

    def get_provider_for_model(
        self, model: str, mode: str = "direct"
    ) -> BaseLLMProvider:
        """
        Get the appropriate provider for a model based on selection mode.

        Modes:
        - ``openrouter``: route everything through OpenRouter.
        - ``direct`` / ``auto`` (default): resolve the provider from the model-id prefix.
        - a **provider name** (e.g. ``bedrock``, ``vertex``, ``anthropic``): route every
          model that provider can serve through it, translating the clean model id to that
          provider's native id. A model the forced provider can't serve (e.g. a Gemini
          guardrail under ``bedrock`` mode) falls back to prefix-based direct routing so
          auxiliary calls don't break.

        Args:
            model: Model name (e.g., 'anthropic/claude-opus-4.7')
            mode: Provider selection mode

        Returns:
            Provider instance

        Raises:
            RuntimeError: If no suitable provider is available
        """
        if mode is None:
            mode = "direct"

        if mode == "openrouter":
            # Explicit OpenRouter mode - use OpenRouter for everything
            provider = self._providers["openrouter"]
            if not provider.is_available():
                raise RuntimeError(
                    "OpenRouter provider is not available (missing OPENROUTER_API_KEY)"
                )
            return provider

        # Explicit provider-name mode (e.g. LLM_PROVIDER_MODE=bedrock): force that provider
        # for any model it can serve; otherwise fall through to direct prefix routing.
        if mode not in ("direct", "auto"):
            forced = self._providers.get(mode)
            if forced is None:
                raise ValueError(
                    f"Invalid provider mode: {mode}. Use 'direct', 'auto', 'openrouter', "
                    f"or a configured provider name ({', '.join(sorted(self._providers))})."
                )
            if not forced.is_available():
                # The operator explicitly forced this provider; don't silently route
                # elsewhere (that would leak traffic off the intended Bedrock/VPC path).
                hint = _ENV_VAR_HINTS.get(mode, f"{mode.upper()}_API_KEY")
                raise RuntimeError(
                    f"LLM_PROVIDER_MODE={mode} but the '{mode}' provider is not configured. "
                    f"Set {hint} (or change LLM_PROVIDER_MODE)."
                )
            if forced.supports_model(model):
                logger.info(f"Routing model {model} via forced provider '{mode}'")
                return forced
            # Available but can't serve this specific model (e.g. a Gemini guardrail under
            # bedrock mode): fall back to prefix-based direct routing so auxiliary calls work.
            logger.info(
                f"Forced provider '{mode}' cannot serve '{model}'; falling back to direct prefix routing"
            )
            # fall through to direct resolution below

        # 'direct' / 'auto' (and the forced-mode fallback): resolve provider from model prefix.
        # No OpenRouter fallback - if direct provider unavailable, fail with a clear error.
        detected_provider = ModelMapper.detect_provider(model)

        if not detected_provider or detected_provider == "openrouter":
            raise RuntimeError(
                f"Model '{model}' has no direct provider mapping. "
                f"Use mode='openrouter' to route through OpenRouter, or check model name format (e.g., 'anthropic/claude-opus-4.7')."
            )

        provider = self._providers.get(detected_provider)
        if provider and provider.is_available():
            logger.info(
                f"Using {detected_provider} provider for model {model} (mode={mode})"
            )
            return provider

        # Provider exists but not available (missing credentials)
        hint = _ENV_VAR_HINTS.get(
            detected_provider, f"{detected_provider.upper()}_API_KEY"
        )
        raise RuntimeError(
            f"Provider '{detected_provider}' is not available for model '{model}'. "
            f"Configure {hint} or set LLM_PROVIDER_MODE=openrouter to use OpenRouter instead."
        )

    def resolve_provider_name(self, model: str, mode: str = "direct") -> str:
        """Return the *name* of the provider that :meth:`get_provider_for_model` selects.

        Mirrors the routing exactly (forced provider-name mode, fallback, prefix), so
        callers can label a model by the provider that actually serves it — not just its
        id prefix. Needed because a clean ``anthropic/`` model under ``LLM_PROVIDER_MODE=
        bedrock`` is served by Bedrock, and the forced tool_choice format must match the
        serving client, not the prefix.
        """
        provider = self.get_provider_for_model(model, mode=mode)
        for name, candidate in self._providers.items():
            if candidate is provider:
                return name
        return ModelMapper.detect_provider(model) or ""

    def get_provider_info(self) -> List[Dict]:
        """
        Get information about all providers.

        Returns:
            List of provider information dictionaries
        """
        return [
            {
                "name": name,
                "available": provider.is_available(),
                "class": provider.__class__.__name__,
            }
            for name, provider in self._providers.items()
        ]


# Global provider registry instance
_registry = None


def get_registry() -> ProviderRegistry:
    """
    Get the global provider registry instance.

    Returns:
        The global ProviderRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def create_chat_model(
    model: str, temperature: float = 0.4, provider_mode: Optional[str] = None, **kwargs
) -> BaseChatModel:
    """
    Factory function to create a chat model instance.

    Args:
        model: Model name (in any format)
        temperature: Temperature setting (default 0.4)
        provider_mode: Provider selection mode (default from env LLM_PROVIDER_MODE)
        **kwargs: Additional parameters to pass to the provider

    Returns:
        Configured LangChain chat model instance

    Raises:
        RuntimeError: If no suitable provider is available

    Examples:
        >>> # Use direct provider (default) - resolves from model prefix
        >>> model = create_chat_model("anthropic/claude-opus-4.5")  # Uses Anthropic API

        >>> # Explicit OpenRouter mode
        >>> model = create_chat_model("openai/gpt-5", provider_mode="openrouter")
    """
    # Get provider mode from environment if not specified
    if provider_mode is None:
        provider_mode = os.getenv("LLM_PROVIDER_MODE")

    logger.info(f"Creating chat model: {model} (mode: {provider_mode})")

    # Get the appropriate provider
    registry = get_registry()
    provider = registry.get_provider_for_model(model, mode=provider_mode)

    # Create and return the chat model
    return provider.get_chat_model(model, temperature=temperature, **kwargs)


def _transient_llm_exceptions() -> tuple:
    """Build a tuple of provider exception classes that are safe to fail over on.

    Targets *transient / availability* failures only — rate limits, connection
    errors, timeouts, and 5xx server errors — NOT validation errors (400s such as
    bad tool schemas), which would fail identically on any backup and should surface.

    Provider SDKs are imported defensively: if one isn't installed, its errors are
    simply omitted from the tuple.
    """
    exc: list = []

    for mod_name in ("anthropic", "openai"):
        try:
            mod = __import__(mod_name)
        except Exception:
            continue
        for cls_name in (
            "RateLimitError",
            "APIConnectionError",
            "APITimeoutError",
            "InternalServerError",
        ):
            cls = getattr(mod, cls_name, None)
            if isinstance(cls, type):
                exc.append(cls)

    return tuple(exc)


def create_chat_model_with_fallback(
    model: str, temperature: float = 0.4, provider_mode: Optional[str] = None, **kwargs
) -> BaseChatModel:
    """Create a primary chat model, optionally attaching a backup for failover.

    Behavior:
    - Reads ``FALLBACK_MODEL`` from :class:`ModelConfig`. When it is empty (default) or
      equal to ``model``, this returns exactly what :func:`create_chat_model` returns —
      i.e. it is a strict no-op and preserves current behavior.
    - When a distinct ``FALLBACK_MODEL`` is set, returns
      ``primary.with_fallbacks([fallback], exceptions_to_handle=<transient errors>)``.

    IMPORTANT — tool calling: LangChain's ``RunnableWithFallbacks`` does NOT expose
    ``.bind_tools``. Only use this helper on code paths where tools are NOT bound onto
    the returned object afterwards (e.g. plain ``.invoke`` / structured-output calls).
    For tool-calling agents, bind tools first and use
    :func:`bind_tools_with_fallback` instead so the fallback is applied AFTER
    ``bind_tools`` on both models.
    """
    # Imported here (not at module top) to avoid a circular import: llm.py imports
    # create_chat_model from this package.
    from chat.backend.agent.llm import ModelConfig

    primary = create_chat_model(
        model, temperature=temperature, provider_mode=provider_mode, **kwargs
    )

    fallback_model = ModelConfig.FALLBACK_MODEL
    if not fallback_model or fallback_model == model:
        return primary

    try:
        fallback = create_chat_model(
            fallback_model,
            temperature=temperature,
            provider_mode=provider_mode,
            **kwargs,
        )
    except Exception as e:
        # A misconfigured backup must never break the primary path.
        logger.warning(
            f"FALLBACK_MODEL='{fallback_model}' could not be created ({e}); "
            "continuing without fallback."
        )
        return primary

    exceptions = _transient_llm_exceptions()
    logger.info(
        f"LLM fallback enabled: primary={model} -> fallback={fallback_model} "
        f"(failover on {len(exceptions)} transient error types)"
    )
    return primary.with_fallbacks([fallback], exceptions_to_handle=exceptions)


def bind_tools_with_fallback(primary: BaseChatModel, tools, **bind_kwargs):
    """Bind ``tools`` to the primary and attach a tool-bound backup for failover.

    This is the tool-calling-safe fallback primitive. The fallback is applied AFTER
    ``bind_tools`` on BOTH models, i.e.::

        primary.bind_tools(tools).with_fallbacks([fallback.bind_tools(tools)])

    so the resulting runnable is a valid tool-calling model (unlike wrapping the raw
    model in ``with_fallbacks`` first, which would strip ``.bind_tools``).

    No-op safety: when ``FALLBACK_MODEL`` is empty or equals the primary's model id,
    this returns exactly ``primary.bind_tools(tools, **bind_kwargs)`` — identical to
    current behavior.

    Args:
        primary: An already-constructed :class:`BaseChatModel` (the primary).
        tools: Tools to bind (same value passed to both primary and fallback).
        **bind_kwargs: Extra kwargs forwarded to ``bind_tools`` on both models
            (e.g. ``tool_choice``). NOTE: a forced ``tool_choice`` computed for the
            primary provider may not be valid for a different-provider fallback.
    """
    from chat.backend.agent.llm import ModelConfig

    primary_bound = primary.bind_tools(tools, **bind_kwargs)

    fallback_model = ModelConfig.FALLBACK_MODEL
    primary_model_id = (
        getattr(primary, "model_name", None)
        or getattr(primary, "model", None)
        or getattr(primary, "model_id", None)
    )
    if not fallback_model or fallback_model == primary_model_id:
        return primary_bound

    try:
        fallback = create_chat_model(fallback_model)
        fallback_bound = fallback.bind_tools(tools, **bind_kwargs)
    except Exception as e:
        logger.warning(
            f"FALLBACK_MODEL='{fallback_model}' could not be prepared for tool "
            f"binding ({e}); continuing without fallback."
        )
        return primary_bound

    exceptions = _transient_llm_exceptions()
    logger.info(
        f"LLM tool-calling fallback enabled: fallback={fallback_model} "
        f"(failover on {len(exceptions)} transient error types)"
    )
    return primary_bound.with_fallbacks([fallback_bound], exceptions_to_handle=exceptions)


def get_available_providers() -> Dict[str, bool]:
    """
    Get status of all providers.

    Returns:
        Dictionary mapping provider names to availability status

    Example:
        >>> get_available_providers()
        {'openrouter': True, 'openai': False, 'anthropic': True, ...}
    """
    registry = get_registry()
    return {
        name: provider.is_available() for name, provider in registry._providers.items()
    }


# Export key classes and functions
__all__ = [
    "BaseLLMProvider",
    "OpenRouterProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GoogleProvider",
    "VertexAIProvider",
    "OllamaProvider",
    "BedrockProvider",
    "ProviderRegistry",
    "get_registry",
    "create_chat_model",
    "create_chat_model_with_fallback",
    "bind_tools_with_fallback",
    "get_available_providers",
]
