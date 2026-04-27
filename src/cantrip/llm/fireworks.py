"""Fireworks.ai LLM provider.

Fireworks serves open-weights models (Kimi, GLM, MiniMax, DeepSeek, …)
behind an OpenAI-compatible chat-completions API at
``https://api.fireworks.ai/inference/v1``.  The wire format and HTTP
plumbing live in ``_openai_compat``; this module only adds the
Fireworks-specific base URL, bearer-token auth, and a one-shot
``/models`` probe that populates the context window and capability
flags for whichever model the caller selects.
"""

import logging
import os
from typing import Any

import httpx

from cantrip.llm._openai_compat import OpenAICompatBase
from cantrip.llm.base import Message, ProviderError, Response, Tool

# Fireworks rejects non-streaming requests with ``max_tokens > 4096``
# (400 "Requests with max_tokens > 4096 must have stream=true").  This
# matters the moment reasoning models are in play: Phase 77 bumps
# ``max_tokens`` by ``thinking_budget + 4096`` to leave room for
# reasoning alongside the final answer, and that routinely crosses
# the cap.
_NON_STREAMING_MAX_TOKENS_CAP = 4096

log = logging.getLogger(__name__)

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"

# Default model — Kimi K2.6 is a strong agentic/coding model with a
# 256k context window and native tool-use support, which matches
# Cantrip's two-loop agent design.  Callers can override with
# ``--model accounts/fireworks/models/<name>``.
DEFAULT_MODEL = "accounts/fireworks/models/kimi-k2p6"

# Fallback used when ``/models`` probing fails or the selected model
# isn't listed.  Most Fireworks chat models exceed this comfortably;
# using a conservative value keeps compaction/budget accounting safe.
_FALLBACK_CONTEXT_WINDOW = 32_768


class FireworksProvider(OpenAICompatBase):
    """LLM provider backed by the Fireworks.ai inference API."""

    @property
    def name(self) -> str:
        """Short identifier for this provider."""
        return "fireworks"

    @property
    def _error_label(self) -> str:
        """Label used in error messages."""
        return "Fireworks.ai"

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """Initialise the Fireworks provider.

        Args:
            model: Fireworks model identifier (e.g.
                ``accounts/fireworks/models/kimi-k2p6``).  Defaults to
                :data:`DEFAULT_MODEL`.
            api_key: Bearer token for the Fireworks API.  Falls back to
                the ``FIREWORKS_API_KEY`` environment variable.
            base_url: Override the API base URL (useful for proxies or
                compatible re-hosts).  Defaults to
                :data:`FIREWORKS_BASE_URL`.

        Raises:
            ProviderError: If no API key is available.
        """
        resolved_key = api_key or os.environ.get("FIREWORKS_API_KEY")
        if not resolved_key:
            raise ProviderError(
                "FIREWORKS_API_KEY environment variable not set.\n"
                "  Get a key from: https://fireworks.ai/account/api-keys\n"
                "  Then: export FIREWORKS_API_KEY='your-key-here'"
            )

        self.model_name = model or DEFAULT_MODEL
        self.base_url = (base_url or FIREWORKS_BASE_URL).rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=300.0,
            headers={"Authorization": f"Bearer {resolved_key}"},
        )

        # Conservative defaults; ``_probe_capabilities`` upgrades these
        # from the ``/models`` catalogue when the API is reachable.
        self._context_window = _FALLBACK_CONTEXT_WINDOW
        self._supports_tools = True
        self._supports_vision = False

        self._probe_capabilities(resolved_key)

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> Response:
        """Generate a completion, auto-streaming past Fireworks's non-stream cap.

        Fireworks returns a 400 Bad Request when a non-streaming
        request carries ``max_tokens > 4096`` (the server requires
        ``stream=true`` above that).  Phase 77 reserves
        ``thinking_budget + 4096`` so reasoning models don't starve
        the reply — for ``thinking_budget >= 1`` that always crosses
        the cap.  Rather than leak the server's constraint into every
        caller, delegate to ``stream()`` internally and rebuild a
        :class:`Response` from the chunks.
        """
        effective = self._effective_max_tokens(max_tokens, thinking_budget)
        if effective is None or effective <= _NON_STREAMING_MAX_TOKENS_CAP:
            return await super().complete(
                messages,
                tools,
                temperature,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
                response_schema=response_schema,
            )

        content_parts: list[str] = []
        tool_calls = []
        usage: dict[str, int] = {}
        metadata: dict[str, Any] = {}
        async for chunk in self.stream(
            messages,
            tools,
            temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            response_schema=response_schema,
        ):
            if chunk.content:
                content_parts.append(chunk.content)
            if chunk.is_final:
                tool_calls = chunk.tool_calls
                usage = chunk.usage
                metadata = chunk.metadata
        return Response(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason="tool_use" if tool_calls else "stop",
            usage=usage,
            metadata=metadata,
        )

    @staticmethod
    def _effective_max_tokens(max_tokens: int | None, thinking_budget: int | None) -> int | None:
        """Mirror ``OpenAICompatBase._build_request_body``'s thinking floor.

        Returns whatever ``max_tokens`` value the wire request would
        carry once the ``thinking_budget`` bump is applied.  Kept
        static so the non-streaming-cap check stays in one place.
        """
        if thinking_budget:
            floor = thinking_budget + 4096
            return floor if max_tokens is None else max(max_tokens, floor)
        return max_tokens

    def _probe_capabilities(self, api_key: str) -> None:
        """Query ``/models`` once to set context window and capability flags.

        Fireworks returns the full model catalogue; find the selected
        model and copy over ``context_length``, ``supports_tools``, and
        ``supports_image_input``.  A probe failure is non-fatal — the
        conservative fallbacks set in ``__init__`` remain in effect.
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
        except (httpx.HTTPError, ValueError) as e:
            # ``ValueError`` covers ``json.JSONDecodeError`` so a probe
            # endpoint that returns non-JSON degrades to the fallback
            # context window instead of crashing provider construction.
            log.debug("Fireworks /models probe failed: %s", e)
            return

        entry = self._find_model_entry(payload, self.model_name)
        if entry is None:
            log.info(
                "Fireworks model %s not listed in /models; using conservative "
                "defaults (context=%d).",
                self.model_name,
                self._context_window,
            )
            return

        ctx = entry.get("context_length")
        if isinstance(ctx, int) and ctx > 0:
            self._context_window = ctx
        # Fireworks model flags are booleans, not an array of capability
        # strings — mirror them directly onto our feature flags.
        if "supports_tools" in entry:
            self._supports_tools = bool(entry["supports_tools"])
        if "supports_image_input" in entry:
            self._supports_vision = bool(entry["supports_image_input"])

    @staticmethod
    def _find_model_entry(payload: dict[str, Any], model_id: str) -> dict[str, Any] | None:
        """Locate *model_id* in a Fireworks ``/models`` response."""
        for entry in payload.get("data", []):
            if entry.get("id") == model_id:
                return entry
        return None

    # count_tokens inherited from LLMProvider (character-based heuristic).
