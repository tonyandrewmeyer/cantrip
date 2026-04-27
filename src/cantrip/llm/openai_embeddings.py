"""OpenAI embed provider (Phase 72.3).

OpenAI ships ``text-embedding-3-small`` and ``text-embedding-3-large``
on a stable ``/v1/embeddings`` endpoint shared by every
OpenAI-wire-compatible host (Fireworks, vLLM, OpenRouter when it
proxies an embed-capable model).  This module wraps that endpoint
in the Phase 72.3 :class:`~cantrip.llm.roles.EmbedProvider` ABC.

There is no OpenAI-side rerank API.  Users who want rerank with an
OpenAI embed pipeline pair this provider with
:class:`cantrip.llm.voyage.VoyageRerankProvider` (or build a
cosine-similarity reranker on top of :meth:`embed` themselves) — the
:class:`~cantrip.llm.roles.RoleRouter` is the place to mix and match.

Auth: ``OPENAI_API_KEY``, with an optional ``base_url`` override
(``OPENAI_EMBED_BASE_URL`` env var) so a self-hosted vLLM, Ollama,
llama.cpp-server, LocalAI, or Canonical inference snap can serve the
same shape.  When the base URL is overridden, the API key becomes
optional — most local OSS servers do not authenticate.  Users who do
want to authenticate against a self-hosted endpoint can still set
``OPENAI_API_KEY``; it will be forwarded as a bearer token whenever
present.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from cantrip.llm.base import (
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
)
from cantrip.llm.roles import EmbeddingResult, EmbedProvider

log = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_TIMEOUT_SECONDS = 30.0
_DEFAULT_MODEL = "text-embedding-3-small"


def _resolve_base(base_url: str | None) -> tuple[str, bool]:
    """Resolve the embed base URL and whether it points at default OpenAI.

    Returns ``(base, is_default_openai)``.  Callers use the second
    element to decide whether ``OPENAI_API_KEY`` is mandatory: the
    real OpenAI service always needs a key, but a local
    OpenAI-compatible server (Ollama, vLLM, llama.cpp-server,
    inference-snap) usually does not.
    """
    override = base_url or os.environ.get("OPENAI_EMBED_BASE_URL")
    if override:
        return override, False
    return _DEFAULT_BASE_URL, True


def _api_key(*, required: bool) -> str | None:
    """Return ``OPENAI_API_KEY``; raise if *required* and unset.

    *required* is true when the endpoint is the default OpenAI host;
    callers pointing at a self-hosted OpenAI-compatible server pass
    ``required=False`` so the key becomes optional.  An empty key
    when the call is keyless returns ``None`` — the embed method
    omits the ``Authorization`` header in that case rather than
    sending ``Bearer ``.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    if required:
        raise ProviderError(
            "OPENAI_API_KEY is not set. "
            "Get a key from https://platform.openai.com/ and export it before "
            "starting cantrip, or set OPENAI_EMBED_BASE_URL to point at a "
            "self-hosted OpenAI-compatible embed server (no key required)."
        )
    return None


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP errors to Cantrip's typed provider exceptions."""
    if response.is_success:
        return
    status = response.status_code
    body = response.text[:500]
    if status == 429:
        raise ProviderRateLimitError(f"OpenAI embed rate limited: {body}")
    if 500 <= status < 600:
        raise ProviderOverloadedError(f"OpenAI embed overloaded ({status}): {body}")
    raise ProviderError(f"OpenAI embed failed ({status}): {body}")


class OpenAIEmbedProvider(EmbedProvider):
    """Embed via the OpenAI ``/v1/embeddings`` endpoint."""

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        *,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        base, is_default = _resolve_base(base_url)
        self._endpoint = f"{base.rstrip('/')}/embeddings"
        # Probe the env var at construction (matches Voyage's fail-fast).
        # Custom endpoints make the key optional — local OSS servers
        # (Ollama, vLLM, llama.cpp-server) don't authenticate.
        self._key = _api_key(required=is_default)

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> EmbeddingResult:
        """Embed *texts* via OpenAI; *input_type* is ignored.

        OpenAI's embed models do not differentiate document/query input;
        the parameter is accepted to satisfy the
        :class:`EmbedProvider` contract and ignored on the wire.
        """
        del input_type
        if not texts:
            return EmbeddingResult(vectors=(), model=self._model, input_tokens=0)
        payload: dict[str, Any] = {
            "model": self._model,
            "input": texts,
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        # Omit Authorization entirely when keyless — some local
        # servers (Ollama, llama.cpp-server) reject ``Bearer `` with
        # an empty token instead of treating it as anonymous.
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                self._endpoint,
                json=payload,
                headers=headers,
            )
        _raise_for_status(response)
        body = response.json()
        return _parse_response(body, self._model)


def _parse_response(body: dict[str, Any], model: str) -> EmbeddingResult:
    """Decode the OpenAI embed envelope.

    OpenAI returns ``data`` sorted by ``index`` — we preserve order
    explicitly with a sort to defend against any future reshuffling
    or proxy that drops the field.
    """
    raw_data = body.get("data")
    if not isinstance(raw_data, list):
        raise ProviderError("OpenAI embed response missing 'data' array")
    entries: list[tuple[int, tuple[float, ...]]] = []
    for entry in raw_data:
        if not isinstance(entry, dict):
            raise ProviderError("OpenAI embed entry not a JSON object")
        embedding = entry.get("embedding")
        index = entry.get("index", 0)
        if not isinstance(embedding, list) or not isinstance(index, int):
            raise ProviderError("OpenAI embed entry missing index/embedding")
        entries.append((index, tuple(float(v) for v in embedding)))
    entries.sort(key=lambda pair: pair[0])
    vectors = tuple(vec for _, vec in entries)
    usage = body.get("usage") or {}
    tokens = int(usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0
    return EmbeddingResult(vectors=vectors, model=model, input_tokens=tokens)
