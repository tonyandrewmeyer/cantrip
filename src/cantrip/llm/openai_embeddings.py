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
(``OPENAI_EMBED_BASE_URL`` env var) so a self-hosted vLLM or
Fireworks endpoint can serve the same shape.
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


def _resolve_endpoint(base_url: str | None) -> str:
    """Return the ``/embeddings`` URL, with env override support."""
    base = base_url or os.environ.get("OPENAI_EMBED_BASE_URL") or _DEFAULT_BASE_URL
    return f"{base.rstrip('/')}/embeddings"


def _api_key() -> str:
    """Return ``OPENAI_API_KEY`` or raise a friendly error."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ProviderError(
            "OPENAI_API_KEY is not set. "
            "Get a key from https://platform.openai.com/ and export it before "
            "starting cantrip."
        )
    return key


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
        self._endpoint = _resolve_endpoint(base_url)
        # Probe the env var at construction (matches Voyage's fail-fast).
        self._key = _api_key()

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
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                self._endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
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
