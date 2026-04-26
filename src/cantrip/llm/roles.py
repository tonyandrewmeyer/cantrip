"""Phase 72.3: provider roles for retrieval — ``embed`` and ``rerank``.

Cantrip's primary :class:`~cantrip.llm.base.LLMProvider` interface is
designed for conversational completion: messages in, streamed tokens
out, with tool-call shape baked in.  Embedding and reranking are
*not* conversational — no system prompt, no tool calls, no streaming
— so wedging them into ``LLMProvider`` would force every chat
provider to learn endpoints it doesn't speak.

Two narrower ABCs solve this without distorting the chat surface:

* :class:`EmbedProvider` — turns a list of texts into vectors.
* :class:`RerankProvider` — orders documents by relevance to a query.

A provider may implement one, both, or neither.  Concrete
implementations live in :mod:`cantrip.llm.voyage` (Anthropic-ecosystem
recommendation) and :mod:`cantrip.llm.openai_embeddings`.

A :class:`RoleRouter` ties roles to providers.  Retrieval-using code
(Phase 72.1 ``@docs``, Phase 43 memory retrieval) calls the router
rather than instantiating a provider directly, so swapping Voyage for
OpenAI is a config change rather than a code change.
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod


class RoleNotConfigured(Exception):
    """No provider is configured for the requested role.

    Surfaced to callers as a clean message rather than an
    AttributeError or NotImplementedError.  The message names the
    role and points at the env var / CLI flag that would configure it.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Output of an embed call.

    ``vectors`` is one float list per input text, in the same order.
    ``model`` is the model identifier the provider used (so callers
    can record per-model cost).  ``input_tokens`` is the billable
    token count returned by the provider; ``0`` means "the provider
    didn't tell us" — callers should treat that as opaque rather
    than zero-cost.
    """

    vectors: tuple[tuple[float, ...], ...]
    model: str
    input_tokens: int = 0

    @property
    def dimensions(self) -> int:
        """Number of dimensions in each vector (zero if no vectors)."""
        if not self.vectors:
            return 0
        return len(self.vectors[0])


@dataclasses.dataclass(frozen=True, slots=True)
class RerankResult:
    """Output of a rerank call.

    ``indices`` is the input documents reordered by relevance,
    descending — ``indices[0]`` is the most relevant.
    ``scores`` aligns one-to-one with ``indices`` and uses the
    provider's native scoring (Voyage returns scores in roughly the
    [0, 1] range; OpenAI-style implementations derive cosine
    similarity).  ``model`` and ``input_tokens`` mirror
    :class:`EmbeddingResult`.
    """

    indices: tuple[int, ...]
    scores: tuple[float, ...]
    model: str
    input_tokens: int = 0

    def top_k(self, k: int) -> tuple[int, ...]:
        """Return the *k* most relevant document indices."""
        return self.indices[:k]


class EmbedProvider(ABC):
    """Provider that turns a list of texts into vectors."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The embedding model identifier (e.g. ``voyage-3``)."""

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> EmbeddingResult:
        """Return one vector per element of *texts*.

        *input_type* is ``"document"`` for content being indexed and
        ``"query"`` for the search-side text — Voyage and Cohere
        both perform better when the role is declared.  Providers
        without an asymmetric mode ignore the hint.
        """


class RerankProvider(ABC):
    """Provider that orders documents by relevance to a query."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The rerank model identifier (e.g. ``voyage-rerank-2``)."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_k: int | None = None,
    ) -> RerankResult:
        """Return *documents* re-ordered by relevance to *query*.

        When *top_k* is set the provider may return only the top *k*
        results; callers receive whatever the provider supplies and
        slice further if they need a tighter cap.
        """


class RoleRouter:
    """Resolve which provider services each retrieval role.

    Built once at agent construction; retrieval-using callers query it
    instead of instantiating providers directly.  The router does not
    own the chat / edit / apply roles — those flow through
    :func:`cantrip.llm.create_provider` and the existing primary +
    light providers.

    Phase 72.3 v1 only registers ``embed`` and ``rerank`` because
    those are the two roles that cannot be served by today's chat
    providers.  ``summarize`` is a chat-shaped role that the existing
    light provider handles, so it stays out of the router for now.
    """

    def __init__(self) -> None:
        self._embed: EmbedProvider | None = None
        self._rerank: RerankProvider | None = None

    def register_embed(self, provider: EmbedProvider) -> None:
        """Set the provider that handles embed calls."""
        self._embed = provider

    def register_rerank(self, provider: RerankProvider) -> None:
        """Set the provider that handles rerank calls."""
        self._rerank = provider

    @property
    def embed_provider(self) -> EmbedProvider | None:
        """Currently registered embed provider, if any."""
        return self._embed

    @property
    def rerank_provider(self) -> RerankProvider | None:
        """Currently registered rerank provider, if any."""
        return self._rerank

    def get_embed(self) -> EmbedProvider:
        """Return the embed provider or raise :class:`RoleNotConfigured`.

        Retrieval-using code calls this when an embed is required;
        the raised error names the role and points at the env vars
        and CLI flags that would configure one, so the user gets a
        single clear message instead of a chain of attribute errors.
        """
        if self._embed is None:
            raise RoleNotConfigured(
                "No embed provider configured. Set CANTRIP_EMBED_PROVIDER "
                "(e.g. 'voyage' or 'openai') or pass --embed-provider to "
                "`cantrip run`. See `docs/docs/howto-providers.html` for "
                "supported provider/model combinations."
            )
        return self._embed

    def get_rerank(self) -> RerankProvider:
        """Return the rerank provider or raise :class:`RoleNotConfigured`."""
        if self._rerank is None:
            raise RoleNotConfigured(
                "No rerank provider configured. Set CANTRIP_RERANK_PROVIDER "
                "(currently only 'voyage' is supported) or pass "
                "--rerank-provider to `cantrip run`."
            )
        return self._rerank

    def has_embed(self) -> bool:
        """``True`` when an embed provider is registered."""
        return self._embed is not None

    def has_rerank(self) -> bool:
        """``True`` when a rerank provider is registered."""
        return self._rerank is not None
