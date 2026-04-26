"""Voyage AI embed and rerank provider implementations (Phase 72.3).

Voyage is the embedding/rerank house Anthropic recommends alongside
Claude — they offer a coherent set of models (``voyage-3``,
``voyage-3-lite``, ``voyage-code-3``, ``rerank-2``,
``rerank-2-lite``) with first-class ``input_type`` semantics for
asymmetric retrieval.  This module wires them onto the Phase 72.3
:class:`~cantrip.llm.roles.EmbedProvider` and
:class:`~cantrip.llm.roles.RerankProvider` ABCs.

Authentication: the ``VOYAGE_API_KEY`` environment variable.  The
provider raises :class:`~cantrip.llm.base.ProviderError` at
construction when the key is missing rather than letting the first
real call surface a 401 — fail-fast at boot is friendlier than a
late explosion mid-retrieval.
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
from cantrip.llm.roles import (
    EmbeddingResult,
    EmbedProvider,
    RerankProvider,
    RerankResult,
)

log = logging.getLogger(__name__)

_API_BASE = "https://api.voyageai.com/v1"
_TIMEOUT_SECONDS = 30.0
_DEFAULT_EMBED_MODEL = "voyage-3"
_DEFAULT_RERANK_MODEL = "rerank-2"


def _api_key() -> str:
    """Return the Voyage API key from the environment.

    Centralised so both providers share the same lookup and the
    error message stays in one place.
    """
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise ProviderError(
            "VOYAGE_API_KEY is not set. "
            "Get a key from https://www.voyageai.com/ and export it before "
            "starting cantrip."
        )
    return key


def _headers(key: str) -> dict[str, str]:
    """Build the Authorization headers for a Voyage request."""
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _raise_for_status(response: httpx.Response, action: str) -> None:
    """Translate non-2xx responses into Cantrip provider errors.

    Voyage uses standard HTTP semantics: 429 for quota, 5xx for
    transient overloads, 4xx for the rest.  Mapping these to the
    typed errors in :mod:`cantrip.llm.base` lets the agent layer
    apply the same retry / surface-once logic it already runs for
    chat providers.
    """
    if response.is_success:
        return
    status = response.status_code
    body = response.text[:500]
    if status == 429:
        raise ProviderRateLimitError(f"Voyage {action} rate limited: {body}")
    if 500 <= status < 600:
        raise ProviderOverloadedError(f"Voyage {action} overloaded ({status}): {body}")
    raise ProviderError(f"Voyage {action} failed ({status}): {body}")


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------


class VoyageEmbedProvider(EmbedProvider):
    """Embed via Voyage's ``/v1/embeddings`` endpoint."""

    def __init__(self, model: str = _DEFAULT_EMBED_MODEL) -> None:
        self._model = model
        # Probe the env var at construction so a misconfigured session
        # fails before the first retrieval call rather than mid-turn.
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
        """Call Voyage and return one vector per element of *texts*."""
        if not texts:
            return EmbeddingResult(vectors=(), model=self._model, input_tokens=0)
        if input_type not in {"document", "query"}:
            raise ProviderError(
                f"Voyage input_type must be 'document' or 'query', got {input_type!r}"
            )
        payload: dict[str, Any] = {
            "model": self._model,
            "input": texts,
            "input_type": input_type,
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{_API_BASE}/embeddings",
                json=payload,
                headers=_headers(self._key),
            )
        _raise_for_status(response, "embed")
        body = response.json()
        return _parse_embed_response(body, self._model)


def _parse_embed_response(body: dict[str, Any], model: str) -> EmbeddingResult:
    """Decode the JSON envelope from ``/v1/embeddings``.

    Defended against partial responses: a missing ``data`` array, a
    non-list ``embedding`` field, or a missing ``usage.total_tokens``
    each raise a :class:`ProviderError` with a readable message
    instead of a deep ``KeyError``/``TypeError``.
    """
    raw_data = body.get("data")
    if not isinstance(raw_data, list):
        raise ProviderError("Voyage embed response missing 'data' array")
    vectors: list[tuple[float, ...]] = []
    for entry in raw_data:
        embedding = entry.get("embedding") if isinstance(entry, dict) else None
        if not isinstance(embedding, list):
            raise ProviderError("Voyage embed entry missing 'embedding' list")
        vectors.append(tuple(float(v) for v in embedding))
    usage = body.get("usage") or {}
    tokens = int(usage.get("total_tokens", 0)) if isinstance(usage, dict) else 0
    return EmbeddingResult(
        vectors=tuple(vectors),
        model=model,
        input_tokens=tokens,
    )


# ---------------------------------------------------------------------------
# Rerank
# ---------------------------------------------------------------------------


class VoyageRerankProvider(RerankProvider):
    """Rerank via Voyage's ``/v1/rerank`` endpoint."""

    def __init__(self, model: str = _DEFAULT_RERANK_MODEL) -> None:
        self._model = model
        self._key = _api_key()

    @property
    def model_name(self) -> str:
        return self._model

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_k: int | None = None,
    ) -> RerankResult:
        """Call Voyage and return *documents* re-ordered by relevance."""
        if not documents:
            return RerankResult(indices=(), scores=(), model=self._model, input_tokens=0)
        payload: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": documents,
        }
        if top_k is not None:
            payload["top_k"] = top_k
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{_API_BASE}/rerank",
                json=payload,
                headers=_headers(self._key),
            )
        _raise_for_status(response, "rerank")
        body = response.json()
        return _parse_rerank_response(body, self._model)


def _parse_rerank_response(body: dict[str, Any], model: str) -> RerankResult:
    """Decode the JSON envelope from ``/v1/rerank``.

    Returns indices in the order Voyage supplies (already
    relevance-descending), with the matching scores.
    """
    raw_data = body.get("data")
    if not isinstance(raw_data, list):
        raise ProviderError("Voyage rerank response missing 'data' array")
    indices: list[int] = []
    scores: list[float] = []
    for entry in raw_data:
        if not isinstance(entry, dict):
            raise ProviderError("Voyage rerank entry not a JSON object")
        index = entry.get("index")
        score = entry.get("relevance_score")
        if not isinstance(index, int) or not isinstance(score, (int, float)):
            raise ProviderError("Voyage rerank entry missing index/relevance_score")
        indices.append(index)
        scores.append(float(score))
    usage = body.get("usage") or {}
    tokens = int(usage.get("total_tokens", 0)) if isinstance(usage, dict) else 0
    return RerankResult(
        indices=tuple(indices),
        scores=tuple(scores),
        model=model,
        input_tokens=tokens,
    )
