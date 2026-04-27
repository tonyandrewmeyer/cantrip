"""OpenRouter.ai LLM provider.

OpenRouter is a meta-provider that exposes hundreds of models — OpenAI
GPT, Anthropic Claude via Bedrock, Meta Llama, Mistral, Grok, DeepSeek,
and so on — behind a single OpenAI-compatible API at
``https://openrouter.ai/api/v1``.  Useful when Cantrip's dedicated
providers (``claude``, ``gemini``, ``fireworks``, ``inference-snap``)
don't cover the model you want, or when you want to A/B the same
prompt across vendors through one key.

Models are selected with a ``<vendor>/<model>`` slug, e.g.
``openai/gpt-4o`` or ``meta-llama/llama-3.3-70b-instruct``.  The
default is ``openai/gpt-4o`` — a well-known, long-lived choice that
complements Cantrip's other providers rather than duplicating them.

OpenRouter asks clients to identify themselves with ``HTTP-Referer``
and ``X-Title`` headers so usage shows up on their model-ranking
dashboards; Cantrip sends both.
"""

import logging
import os
from typing import Any

import httpx

from cantrip.llm._openai_compat import OpenAICompatBase
from cantrip.llm.base import ProviderError

log = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Default model — GPT-4o is a long-lived, broadly-capable model that
# sits outside the coverage of Cantrip's other native providers
# (Anthropic / Google / Fireworks / inference-snap), so it's the most
# useful "just works" default when someone reaches for OpenRouter.
DEFAULT_MODEL = "openai/gpt-4o"

# App-identification headers OpenRouter uses for their dashboards.  The
# Referer is a canonical project URL; the Title is what shows up in
# their ranking tables.
_APP_REFERER = "https://github.com/canonical/cantrip"
_APP_TITLE = "Cantrip"

# Fallback used when ``/models`` probing fails or the selected model
# isn't listed.
_FALLBACK_CONTEXT_WINDOW = 32_768


class OpenRouterProvider(OpenAICompatBase):
    """LLM provider backed by the OpenRouter.ai meta-API."""

    @property
    def name(self) -> str:
        """Short identifier for this provider."""
        return "openrouter"

    @property
    def _error_label(self) -> str:
        """Label used in error messages."""
        return "OpenRouter"

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """Initialise the OpenRouter provider.

        Args:
            model: Model slug (e.g. ``openai/gpt-4o``,
                ``meta-llama/llama-3.3-70b-instruct``).  Defaults to
                :data:`DEFAULT_MODEL`.
            api_key: Bearer token for the OpenRouter API.  Falls back to
                the ``OPENROUTER_API_KEY`` environment variable.
            base_url: Override the API base URL.  Defaults to
                :data:`OPENROUTER_BASE_URL`.

        Raises:
            ProviderError: If no API key is available.
        """
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not resolved_key:
            raise ProviderError(
                "OPENROUTER_API_KEY environment variable not set.\n"
                "  Get a key from: https://openrouter.ai/settings/keys\n"
                "  Then: export OPENROUTER_API_KEY='your-key-here'"
            )

        self.model_name = model or DEFAULT_MODEL
        self.base_url = (base_url or OPENROUTER_BASE_URL).rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=300.0,
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "HTTP-Referer": _APP_REFERER,
                "X-Title": _APP_TITLE,
            },
        )

        # Conservative defaults; ``_probe_capabilities`` upgrades these
        # from the ``/models`` catalogue when the API is reachable.
        self._context_window = _FALLBACK_CONTEXT_WINDOW
        self._supports_tools = True
        self._supports_vision = False

        self._probe_capabilities(resolved_key)

    def _probe_capabilities(self, api_key: str) -> None:
        """Query ``/models`` once to set context window and capability flags.

        OpenRouter's model catalogue carries richer metadata than
        Fireworks — capabilities are encoded as list membership rather
        than booleans:

        * ``context_length`` — top-level int.
        * ``architecture.input_modalities`` — list containing
          ``"image"`` when the model accepts image input.
        * ``supported_parameters`` — list containing ``"tools"`` when
          function calling is supported.

        A probe failure is non-fatal — the conservative fallbacks set
        in ``__init__`` stay in effect.
        """
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=10.0,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": _APP_REFERER,
                    "X-Title": _APP_TITLE,
                },
            ) as client:
                resp = client.get("/models")
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            # ``ValueError`` covers ``json.JSONDecodeError`` so a probe
            # endpoint that returns non-JSON degrades to the fallback
            # context window instead of crashing provider construction.
            log.debug("OpenRouter /models probe failed: %s", e)
            return

        entry = self._find_model_entry(payload, self.model_name)
        if entry is None:
            log.info(
                "OpenRouter model %s not listed in /models; using conservative "
                "defaults (context=%d).",
                self.model_name,
                self._context_window,
            )
            return

        ctx = entry.get("context_length")
        if isinstance(ctx, int) and ctx > 0:
            self._context_window = ctx

        architecture = entry.get("architecture") or {}
        input_modalities = architecture.get("input_modalities") or []
        if isinstance(input_modalities, list) and "image" in input_modalities:
            self._supports_vision = True

        supported = entry.get("supported_parameters") or []
        if isinstance(supported, list):
            # Explicit membership wins both ways — if the catalogue
            # lists supported parameters and "tools" isn't in it, the
            # model cannot do function calling.
            self._supports_tools = "tools" in supported

    @staticmethod
    def _find_model_entry(payload: dict[str, Any], model_id: str) -> dict[str, Any] | None:
        """Locate *model_id* in an OpenRouter ``/models`` response."""
        for entry in payload.get("data", []):
            if entry.get("id") == model_id:
                return entry
        return None

    # count_tokens inherited from LLMProvider (character-based heuristic).
