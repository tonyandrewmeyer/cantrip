"""Shared :class:`EmbedProvider` / :class:`RerankProvider` fakes.

Three test modules used to roll their own ``_StubEmbed`` because
nothing centralised the role-provider stand-in.  This module is the
single home for those doubles.

:class:`StubEmbed` returns deterministic vectors and records every
call so tests can assert the call shape.  :class:`StubRerank` returns
documents in reverse order — useful for asserting that a rerank
actually changed ordering — and also records calls.
"""

from __future__ import annotations

from cantrip.llm.roles import EmbeddingResult, EmbedProvider, RerankProvider, RerankResult


class StubEmbed(EmbedProvider):
    """Deterministic embed provider for tests.

    Two modes:

    * Pass *vector* to make every input embed to that fixed tuple.
      Useful when a search test wants to feed a known query vector
      and assert what falls out.
    * Default: each input text gets the vector ``(0.0, 1.0, 2.0)``
      (a stable position-derived vector).  Useful when the test only
      cares that *some* vector was produced.

    Recorded state:

    * :attr:`calls` — every ``(texts, input_type)`` pair seen.
    """

    def __init__(
        self,
        *,
        vector: tuple[float, ...] | None = None,
        model: str = "stub-embed",
    ) -> None:
        self._vector = vector
        self._model = model
        self.calls: list[tuple[list[str], str]] = []

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str], *, input_type: str = "document") -> EmbeddingResult:
        self.calls.append((list(texts), input_type))
        if self._vector is not None:
            vectors = tuple(self._vector for _ in texts)
        else:
            vectors = tuple(tuple(float(i) for i in range(3)) for _ in texts)
        return EmbeddingResult(vectors=vectors, model=self._model, input_tokens=len(texts))


class StubRerank(RerankProvider):
    """Rerank provider that reverses input order — useful for asserting reordering.

    Records every ``(query, documents)`` pair in :attr:`calls`.
    """

    def __init__(self, *, model: str = "stub-rerank") -> None:
        self._model = model
        self.calls: list[tuple[str, list[str]]] = []

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
        self.calls.append((query, list(documents)))
        n = len(documents)
        order = tuple(range(n - 1, -1, -1))
        scores = tuple(float(i) / max(n, 1) for i in range(n, 0, -1))
        if top_k is not None:
            order = order[:top_k]
            scores = scores[:top_k]
        return RerankResult(indices=order, scores=scores, model=self._model, input_tokens=n)
