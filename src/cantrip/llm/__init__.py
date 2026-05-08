"""LLM provider implementations."""

from cantrip.llm.base import (
    LLMProvider,
    Message,
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    Response,
)

__all__ = [
    "LLMProvider",
    "Message",
    "ProviderError",
    "ProviderOverloadedError",
    "ProviderRateLimitError",
    "Response",
    "create_provider",
    "resolve_light_model",
    "resolve_light_provider",
]

# Maps a main model to a cheaper variant within the same provider family.
_LIGHT_MODEL_MAP: dict[str, str] = {
    # Claude: route to Haiku.
    "claude-sonnet-4-5-20250929": "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6": "claude-haiku-4-5-20251001",
    "claude-opus-4-6-20250917": "claude-sonnet-4-5-20250929",
    "claude-opus-4-7": "claude-sonnet-4-6",
    # Gemini: route Pro to Flash; Flash and Flash-Lite stay as-is.
    "gemini-3.1-pro-preview": "gemini-3-flash-preview",
    "gemini-3-pro-preview": "gemini-3-flash-preview",
    "gemini-3.1-flash-lite": "gemini-3.1-flash-lite",
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


def resolve_light_provider(
    primary_provider: LLMProvider,
    provider_name: str,
    *,
    light_provider_name: str | None = None,
    light_model_override: str | None = None,
    snap_name: str = "gemma3",
    light_snap_name: str | None = None,
) -> tuple[LLMProvider | None, str | None]:
    """Resolve a light provider for cheap internal tasks.

    Returns ``(provider, display_name)`` or ``(None, None)`` when the
    primary provider is already the lightest available.

    Three modes:

    1. **Hybrid** (``light_provider_name`` set): cross-provider routing.
    2. **Multi-snap** (``light_snap_name`` set, primary is inference-snap):
       a lighter snap for internal work.
    3. **Same-provider** (default): cheaper model within the same family.
    """
    if light_provider_name:
        light_snap = light_snap_name or snap_name
        light = create_provider(light_provider_name, light_model_override, snap_name=light_snap)
        return light, f"{light_provider_name}:{light.model_name}"

    if light_snap_name and provider_name == "inference-snap":
        light = create_provider("inference-snap", snap_name=light_snap_name)
        return light, light_snap_name

    main_model = primary_provider.model_name
    resolved = light_model_override or resolve_light_model(provider_name, main_model)
    if resolved != main_model:
        light = create_provider(provider_name, resolved, snap_name=snap_name)
        return light, resolved

    return None, None


def create_provider(
    name: str,
    model: str | None = None,
    *,
    snap_name: str = "gemma3",
    base_url: str | None = None,
    snap_read_timeout: float | None = None,
) -> LLMProvider:
    """Create an LLM provider by name.

    Args:
        name: Provider name — one of ``inference-snap``, ``gemini``,
            ``claude``, ``fireworks``, ``openrouter``, ``opencode-zen``,
            ``openai-compatible``.
        model: Optional model override. If not given, the provider's default is used.
        snap_name: Inference snap to use (only for "inference-snap" provider).
        base_url: Override the API base URL.  Required for
            ``openai-compatible``; optional for ``inference-snap``,
            ``fireworks``, ``openrouter`` and ``opencode-zen``.
        snap_read_timeout: HTTP read timeout (seconds) for the
            inference-snap provider's chat completions.  Phase 102.1:
            ``None`` falls back to ``CANTRIP_SNAP_READ_TIMEOUT`` and
            finally the provider default.
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

    elif name == "inference-snap":
        from cantrip.llm.inference_snap import InferenceSnapProvider

        kwargs: dict = {"snap_name": snap_name}
        if model:
            kwargs["model"] = model
        if base_url:
            kwargs["base_url"] = base_url
        if snap_read_timeout is not None:
            kwargs["read_timeout"] = snap_read_timeout
        return InferenceSnapProvider(**kwargs)

    elif name == "fireworks":
        from cantrip.llm.fireworks import FireworksProvider

        fw_kwargs: dict = {}
        if model:
            fw_kwargs["model"] = model
        if base_url:
            fw_kwargs["base_url"] = base_url
        return FireworksProvider(**fw_kwargs)

    elif name == "openrouter":
        from cantrip.llm.openrouter import OpenRouterProvider

        or_kwargs: dict = {}
        if model:
            or_kwargs["model"] = model
        if base_url:
            or_kwargs["base_url"] = base_url
        return OpenRouterProvider(**or_kwargs)

    elif name == "opencode-zen":
        from cantrip.llm.opencode_zen import OpenCodeZenProvider

        oz_kwargs: dict = {}
        if model:
            oz_kwargs["model"] = model
        if base_url:
            oz_kwargs["base_url"] = base_url
        return OpenCodeZenProvider(**oz_kwargs)

    elif name == "openai-compatible":
        from cantrip.llm.openai_compatible import OpenAICompatibleProvider

        if not base_url:
            raise ValueError(
                "Provider 'openai-compatible' requires --base-url "
                "(e.g. https://api.together.xyz/v1)."
            )
        if not model:
            raise ValueError(
                "Provider 'openai-compatible' requires --model — there is "
                "no sensible default across arbitrary endpoints."
            )
        return OpenAICompatibleProvider(model=model, base_url=base_url)

    else:
        raise ValueError(
            f"Unknown provider: {name!r}. Use 'gemini', 'claude', "
            f"'inference-snap', 'fireworks', 'openrouter', "
            f"'opencode-zen', or 'openai-compatible'."
        )
