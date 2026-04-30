"""OpenCode Zen LLM provider.

OpenCode Zen is the model gateway operated by the OpenCode project at
``https://opencode.ai/zen/v1``.  It exposes a curated catalogue of
frontier and open-weights models — Anthropic Claude (Opus, Sonnet,
Haiku), OpenAI GPT-5 family, Gemini 3 family, and a handful of
Chinese open-weights models (GLM, Kimi, Qwen, MiniMax) — behind a
single OpenAI-compatible chat-completions API and a single bearer
token.  Useful as another meta-gateway alongside OpenRouter when a
caller prefers OpenCode's curation or pricing.

Models are selected by a bare slug (no vendor prefix), e.g.
``claude-haiku-4-5``, ``gpt-5.5``, ``gemini-3.1-pro``.  The default
is ``claude-haiku-4-5`` — a cheap, capable model that exercises
function calling cleanly and complements Cantrip's other providers.

OpenCode Zen's ``/models`` endpoint is a minimal OpenAI-style listing
(``id``, ``object``, ``created``, ``owned_by``) with no context-window
or capability metadata, so the probe only checks model existence;
context window and capability flags fall back to conservative
defaults that callers can override via ``--model`` plus the standard
provider knobs.
"""

import logging
import os
from typing import Any

import httpx

from cantrip.llm._openai_compat import OpenAICompatBase
from cantrip.llm.base import ProviderError

log = logging.getLogger(__name__)

OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"

# Default model — Claude Haiku 4.5 is a cheap, fast model with native
# tool-use that's well within Zen's free/low-cost tiers, so it's the
# most useful "just works" default for first-time users.
DEFAULT_MODEL = "claude-haiku-4-5"

# Fallback used when ``/models`` probing fails or the selected model
# isn't listed.  OpenCode Zen does not publish per-model context
# windows on the listing endpoint, so this is the working assumption
# for every model on the platform.
_FALLBACK_CONTEXT_WINDOW = 128_000


class OpenCodeZenProvider(OpenAICompatBase):
    """LLM provider backed by the OpenCode Zen API gateway."""

    @property
    def name(self) -> str:
        """Short identifier for this provider."""
        return "opencode-zen"

    @property
    def _error_label(self) -> str:
        """Label used in error messages."""
        return "OpenCode Zen"

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """Initialise the OpenCode Zen provider.

        Args:
            model: Model slug (e.g. ``claude-haiku-4-5``, ``gpt-5.5``,
                ``gemini-3.1-pro``).  Defaults to :data:`DEFAULT_MODEL`.
            api_key: Bearer token for the OpenCode Zen API.  Falls back
                to ``OPENCODE_ZEN_API_KEY``, then the historical
                ``ZEN_API_KEY`` alias.
            base_url: Override the API base URL.  Defaults to
                :data:`OPENCODE_ZEN_BASE_URL`.

        Raises:
            ProviderError: If no API key is available.
        """
        # Two env-var names because the ecosystem uses both:
        # OpenCode's own docs use ``OPENCODE_ZEN_API_KEY``, and many
        # users have ``ZEN_API_KEY`` set from earlier tooling.  The
        # explicit name wins; the alias is a fallback.
        resolved_key = (
            api_key or os.environ.get("OPENCODE_ZEN_API_KEY") or os.environ.get("ZEN_API_KEY")
        )
        if not resolved_key:
            raise ProviderError(
                "OPENCODE_ZEN_API_KEY environment variable not set.\n"
                "  Get a key from: https://opencode.ai/zen\n"
                "  Then: export OPENCODE_ZEN_API_KEY='your-key-here'"
            )

        self.model_name = model or DEFAULT_MODEL
        self.base_url = (base_url or OPENCODE_ZEN_BASE_URL).rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=300.0,
            headers={"Authorization": f"Bearer {resolved_key}"},
        )

        # Conservative defaults.  The ``/models`` probe only confirms
        # the slug is recognised; capability flags stay at these
        # values because Zen's catalogue does not publish them.  Tool
        # use is on by default — every chat model on Zen supports it
        # via the OpenAI-compat envelope — and vision stays off until
        # there's a per-model flag worth honouring.
        self._context_window = _FALLBACK_CONTEXT_WINDOW
        self._supports_tools = True
        self._supports_vision = False

        self._probe_models(resolved_key)

    def _probe_models(self, api_key: str) -> None:
        """Confirm the selected slug is in Zen's catalogue.

        OpenCode Zen's ``/models`` endpoint returns a bare OpenAI-style
        listing with no context-window or capability metadata, so this
        probe is informational only: when the slug is missing we log a
        warning so a typo surfaces early, but we still let the request
        proceed because the catalogue is updated more often than this
        client is.
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
            # Non-fatal: keep the conservative fallbacks set in
            # ``__init__`` and let the caller's first chat request
            # surface any real auth/connectivity problem.
            log.debug("OpenCode Zen /models probe failed: %s", e)
            return

        if not self._has_model(payload, self.model_name):
            log.warning(
                "OpenCode Zen model %r is not listed in /models; "
                "the slug may be wrong or newly added.",
                self.model_name,
            )

    @staticmethod
    def _has_model(payload: dict[str, Any], model_id: str) -> bool:
        """Return True when *model_id* appears in a ``/models`` listing."""
        return any(entry.get("id") == model_id for entry in payload.get("data", []))

    # count_tokens inherited from LLMProvider (character-based heuristic).
