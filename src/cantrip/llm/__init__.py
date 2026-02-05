"""LLM provider implementations."""

from cantrip.llm.base import LLMProvider, Message, ProviderError, ProviderRateLimitError, Response

__all__ = [
    "LLMProvider",
    "Message",
    "ProviderError",
    "ProviderRateLimitError",
    "Response",
    "create_provider",
]


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
