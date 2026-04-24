"""Generic OpenAI-compatible LLM provider.

An escape-hatch provider for any endpoint that speaks the OpenAI
chat-completions API: Together, Groq, DeepInfra, vLLM deployments,
LiteLLM proxies, self-hosted TGI, etc.

Use this when Cantrip doesn't ship a dedicated provider for your
backend.  Dedicated providers (e.g. ``fireworks``, ``inference-snap``)
are preferred when available because they carry sensible defaults for
model IDs, context windows, and capability flags; this one requires
the caller to supply everything explicitly.

Required:

* ``--base-url`` — full URL including the ``/v1`` suffix, e.g.
  ``https://api.together.xyz/v1``.
* ``--model`` — the model identifier to send in each request.
* ``OPENAI_COMPATIBLE_API_KEY`` env var — bearer token.  (Endpoints
  that don't need auth, such as a local vLLM instance, can set this
  to any non-empty string.)
"""

import logging
import os
from typing import Any

import httpx

from cantrip.llm._openai_compat import OpenAICompatBase
from cantrip.llm.base import ProviderError

log = logging.getLogger(__name__)

# Conservative default context window when the caller doesn't specify
# one and the ``/models`` probe can't find the selected model.
_FALLBACK_CONTEXT_WINDOW = 32_768


class OpenAICompatibleProvider(OpenAICompatBase):
    """LLM provider for any OpenAI-compatible chat-completions endpoint."""

    @property
    def name(self) -> str:
        """Short identifier for this provider."""
        return "openai-compatible"

    @property
    def _error_label(self) -> str:
        """Label used in error messages — includes the host for clarity."""
        return f"openai-compatible ({self.base_url})"

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        api_key: str | None = None,
        context_window: int | None = None,
        supports_tools: bool = True,
        supports_vision: bool = False,
    ):
        """Initialise the generic OpenAI-compatible provider.

        Args:
            model: Model identifier to send in each request.  Required
                — there is no sensible default across arbitrary
                endpoints.
            base_url: Full API base URL including the ``/v1`` path
                component.  Required.
            api_key: Bearer token.  Falls back to the
                ``OPENAI_COMPATIBLE_API_KEY`` environment variable.
            context_window: Override the context-window size in tokens.
                If omitted, Cantrip probes ``/models`` for a matching
                entry and falls back to a conservative default when the
                probe fails.
            supports_tools: Whether the endpoint supports OpenAI-style
                function calling.  Defaults to True.
            supports_vision: Whether the endpoint accepts ``image_url``
                content parts.  Defaults to False.

        Raises:
            ProviderError: If no API key is available.
        """
        resolved_key = api_key or os.environ.get("OPENAI_COMPATIBLE_API_KEY")
        if not resolved_key:
            raise ProviderError(
                "OPENAI_COMPATIBLE_API_KEY environment variable not set.\n"
                "  Set it to your bearer token, or to any non-empty string "
                "if the endpoint does not require auth."
            )

        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=300.0,
            headers={"Authorization": f"Bearer {resolved_key}"},
        )

        self._context_window = context_window or _FALLBACK_CONTEXT_WINDOW
        self._supports_tools = supports_tools
        self._supports_vision = supports_vision

        if context_window is None:
            self._probe_context_window(resolved_key)

    def _probe_context_window(self, api_key: str) -> None:
        """Best-effort ``/models`` probe to discover the context window.

        Endpoints vary widely in how (and whether) they advertise model
        metadata.  A probe failure is non-fatal — the caller-supplied
        or fallback context window stays in effect.
        """
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=10.0,
                headers={"Authorization": f"Bearer {api_key}"},
            ) as client:
                resp = client.get("/models")
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as e:
            log.debug("openai-compatible /models probe failed: %s", e)
            return

        entry = self._find_model_entry(payload, self.model_name)
        if entry is None:
            return

        # Try the keys used by the backends we know about: Fireworks and
        # Together use ``context_length``; vLLM uses ``max_model_len``;
        # llama.cpp (via the inference-snap wrapper) uses ``n_ctx_train``.
        for key in ("context_length", "max_model_len", "n_ctx_train"):
            ctx = entry.get(key)
            if isinstance(ctx, int) and ctx > 0:
                self._context_window = ctx
                return

    @staticmethod
    def _find_model_entry(payload: dict[str, Any], model_id: str) -> dict[str, Any] | None:
        """Locate *model_id* in a ``/models`` response."""
        for entry in payload.get("data", []):
            if entry.get("id") == model_id:
                return entry
        return None

    # count_tokens inherited from LLMProvider (character-based heuristic).
