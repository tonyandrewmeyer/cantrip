"""LLM provider implementations."""

from cantrip.llm.base import LLMProvider, Message, ProviderError, ProviderRateLimitError, Response

__all__ = [
    "LLMProvider",
    "Message",
    "ProviderError",
    "ProviderRateLimitError",
    "Response",
    "create_provider",
    "resolve_light_model",
]

# Maps a main model to a cheaper variant within the same provider family.
_LIGHT_MODEL_MAP: dict[str, str] = {
    # Claude: route to Haiku.
    "claude-sonnet-4-5-20250929": "claude-haiku-4-5-20251001",
    "claude-opus-4-6-20250917": "claude-sonnet-4-5-20250929",
    # Gemini: route Pro to Flash; Flash stays as-is.
    "gemini-3-pro-preview": "gemini-3-flash-preview",
}


def resolve_light_model(provider_name: str, main_model: str) -> str:
    """Resolve the appropriate light model for internal tasks.

    Looks up *main_model* in ``_LIGHT_MODEL_MAP`` and returns a cheaper
    variant.  Falls back to *main_model* itself when no lighter variant
    is known (no savings, but no breakage).

    The *provider_name* argument is accepted for future use (e.g.
    cross-provider routing) but is currently unused.
    """
    _ = provider_name  # Reserved for future routing logic.
    return _LIGHT_MODEL_MAP.get(main_model, main_model)


def create_provider(name: str, model: str | None = None) -> LLMProvider:
    """Create an LLM provider by name.

    Args:
        name: Provider name ("gemini" or "claude").
        model: Optional model override. If not given, the provider's default is used.
    """
    if name == "gemini":
        from cantrip.llm.gemini import GeminiProvider

        kwargs = {}
        if model:
            kwargs["model"] = model
        return GeminiProvider(**kwargs)

    elif name == "claude":
        from cantrip.llm.claude import ClaudeProvider

        kwargs = {}
        if model:
            kwargs["model"] = model
        return ClaudeProvider(**kwargs)

    else:
        raise ValueError(f"Unknown provider: {name!r}. Use 'gemini' or 'claude'.")
