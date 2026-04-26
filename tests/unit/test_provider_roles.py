"""Phase 72.3 — provider roles, role router, and embed/rerank providers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cantrip.llm.base import (
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
)
from cantrip.llm.openai_embeddings import OpenAIEmbedProvider
from cantrip.llm.roles import (
    EmbeddingResult,
    EmbedProvider,
    RerankProvider,
    RerankResult,
    RoleNotConfigured,
    RoleRouter,
    build_role_router,
    record_role_usage,
)
from cantrip.llm.voyage import (
    VoyageEmbedProvider,
    VoyageRerankProvider,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubEmbed(EmbedProvider):
    """Returns a canned vector list — no real HTTP."""

    def __init__(self, model: str = "stub-embed") -> None:
        self._model = model
        self.calls: list[tuple[list[str], str]] = []

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str], *, input_type: str = "document") -> EmbeddingResult:
        self.calls.append((list(texts), input_type))
        vectors = tuple(tuple(float(i) for i in range(3)) for _ in texts)
        return EmbeddingResult(vectors=vectors, model=self._model, input_tokens=len(texts))


class _StubRerank(RerankProvider):
    """Returns documents reversed so we can assert ordering changed."""

    def __init__(self, model: str = "stub-rerank") -> None:
        self._model = model
        self.calls: list[tuple[str, list[str]]] = []

    @property
    def model_name(self) -> str:
        return self._model

    async def rerank(
        self, query: str, documents: list[str], *, top_k: int | None = None
    ) -> RerankResult:
        self.calls.append((query, list(documents)))
        n = len(documents)
        order = tuple(range(n - 1, -1, -1))
        scores = tuple(float(i) / max(n, 1) for i in range(n, 0, -1))
        if top_k is not None:
            order = order[:top_k]
            scores = scores[:top_k]
        return RerankResult(indices=order, scores=scores, model=self._model, input_tokens=n)


# ---------------------------------------------------------------------------
# RoleRouter
# ---------------------------------------------------------------------------


class TestRoleRouter:
    """Wiring + missing-role error path."""

    def test_unconfigured_router_raises_on_get_embed(self) -> None:
        router = RoleRouter()
        with pytest.raises(RoleNotConfigured) as exc_info:
            router.get_embed()
        # The error names the env var so the user can act on it.
        assert "CANTRIP_EMBED_PROVIDER" in str(exc_info.value)

    def test_unconfigured_router_raises_on_get_rerank(self) -> None:
        router = RoleRouter()
        with pytest.raises(RoleNotConfigured) as exc_info:
            router.get_rerank()
        assert "CANTRIP_RERANK_PROVIDER" in str(exc_info.value)

    def test_register_returns_provider(self) -> None:
        router = RoleRouter()
        embed = _StubEmbed()
        rerank = _StubRerank()
        router.register_embed(embed)
        router.register_rerank(rerank)
        assert router.get_embed() is embed
        assert router.get_rerank() is rerank
        assert router.has_embed() is True
        assert router.has_rerank() is True

    def test_optional_accessors_return_none_when_unset(self) -> None:
        router = RoleRouter()
        assert router.embed_provider is None
        assert router.rerank_provider is None
        assert router.has_embed() is False
        assert router.has_rerank() is False


class TestEmbeddingResult:
    """``EmbeddingResult`` shape — used by retrieval-using callers."""

    def test_dimensions_zero_when_empty(self) -> None:
        result = EmbeddingResult(vectors=(), model="x")
        assert result.dimensions == 0

    def test_dimensions_reflects_first_vector(self) -> None:
        result = EmbeddingResult(vectors=((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)), model="x")
        assert result.dimensions == 3


class TestRerankResult:
    """``RerankResult`` shape — top-k slicing for callers."""

    def test_top_k_slices(self) -> None:
        result = RerankResult(indices=(2, 0, 1, 3), scores=(0.9, 0.7, 0.5, 0.1), model="x")
        assert result.top_k(2) == (2, 0)
        assert result.top_k(10) == (2, 0, 1, 3)


# ---------------------------------------------------------------------------
# Voyage embed
# ---------------------------------------------------------------------------


class TestVoyageEmbedProvider:
    """Voyage embed wire format and error mapping."""

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
        with pytest.raises(ProviderError) as exc_info:
            VoyageEmbedProvider()
        assert "VOYAGE_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_embed_parses_vectors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        body = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3]},
                {"embedding": [0.4, 0.5, 0.6]},
            ],
            "usage": {"total_tokens": 12},
        }
        response = httpx.Response(
            200,
            json=body,
            request=httpx.Request("POST", "https://x"),
        )
        provider = VoyageEmbedProvider()
        with patch("cantrip.llm.voyage.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance
            result = await provider.embed(["hi", "world"])
        assert result.dimensions == 3
        assert result.vectors[0] == (0.1, 0.2, 0.3)
        assert result.input_tokens == 12
        assert result.model == "voyage-3"

    @pytest.mark.asyncio
    async def test_empty_input_skips_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        provider = VoyageEmbedProvider()
        # No HTTP mock — empty input must short-circuit before networking.
        result = await provider.embed([])
        assert result.vectors == ()
        assert result.input_tokens == 0

    @pytest.mark.asyncio
    async def test_rate_limited_raises_typed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        response = httpx.Response(
            429,
            text="quota exceeded",
            request=httpx.Request("POST", "https://x"),
        )
        provider = VoyageEmbedProvider()
        with patch("cantrip.llm.voyage.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance
            with pytest.raises(ProviderRateLimitError):
                await provider.embed(["hi"])

    @pytest.mark.asyncio
    async def test_5xx_raises_overloaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        response = httpx.Response(
            502,
            text="bad gateway",
            request=httpx.Request("POST", "https://x"),
        )
        provider = VoyageEmbedProvider()
        with patch("cantrip.llm.voyage.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance
            with pytest.raises(ProviderOverloadedError):
                await provider.embed(["hi"])

    @pytest.mark.asyncio
    async def test_invalid_input_type_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        provider = VoyageEmbedProvider()
        with pytest.raises(ProviderError):
            await provider.embed(["hi"], input_type="bogus")


# ---------------------------------------------------------------------------
# Voyage rerank
# ---------------------------------------------------------------------------


class TestVoyageRerankProvider:
    """Voyage rerank wire format."""

    @pytest.mark.asyncio
    async def test_rerank_orders_by_relevance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        body = {
            "data": [
                {"index": 2, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.7},
                {"index": 1, "relevance_score": 0.1},
            ],
            "usage": {"total_tokens": 30},
        }
        response = httpx.Response(
            200,
            json=body,
            request=httpx.Request("POST", "https://x"),
        )
        provider = VoyageRerankProvider()
        with patch("cantrip.llm.voyage.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance
            result = await provider.rerank("q", ["a", "b", "c"], top_k=2)
        # Returned order matches the API.
        assert result.indices == (2, 0, 1)
        assert result.scores[0] == pytest.approx(0.95)
        assert result.input_tokens == 30
        # top_k slice helper.
        assert result.top_k(2) == (2, 0)

    @pytest.mark.asyncio
    async def test_empty_documents_skips_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        provider = VoyageRerankProvider()
        result = await provider.rerank("q", [])
        assert result.indices == ()


# ---------------------------------------------------------------------------
# OpenAI embed
# ---------------------------------------------------------------------------


class TestOpenAIEmbedProvider:
    """OpenAI embed wire format and base-URL override."""

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ProviderError):
            OpenAIEmbedProvider()

    @pytest.mark.asyncio
    async def test_embed_orders_by_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        # Returned out-of-order — the parser must sort by index.
        body = {
            "data": [
                {"index": 1, "embedding": [9.0, 9.0]},
                {"index": 0, "embedding": [1.0, 1.0]},
            ],
            "usage": {"prompt_tokens": 5},
        }
        response = httpx.Response(
            200,
            json=body,
            request=httpx.Request("POST", "https://x"),
        )
        provider = OpenAIEmbedProvider()
        with patch("cantrip.llm.openai_embeddings.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance
            result = await provider.embed(["a", "b"])
        assert result.vectors[0] == (1.0, 1.0)
        assert result.vectors[1] == (9.0, 9.0)
        assert result.input_tokens == 5

    @pytest.mark.asyncio
    async def test_empty_input_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        provider = OpenAIEmbedProvider()
        result = await provider.embed([])
        assert result.vectors == ()

    def test_base_url_override_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_EMBED_BASE_URL", "http://localhost:8000/v1")
        provider = OpenAIEmbedProvider()
        # Endpoint resolves with the override even without an explicit
        # base_url argument — keeps self-hosted vLLM swappable.
        assert provider._endpoint == "http://localhost:8000/v1/embeddings"


# ---------------------------------------------------------------------------
# Builder + recording helpers
# ---------------------------------------------------------------------------


class TestBuildRoleRouter:
    """``build_role_router`` reads CLI args + env vars."""

    def test_no_config_yields_empty_router(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CANTRIP_EMBED_PROVIDER", raising=False)
        monkeypatch.delenv("CANTRIP_RERANK_PROVIDER", raising=False)
        router = build_role_router()
        assert router.has_embed() is False
        assert router.has_rerank() is False

    def test_env_var_drives_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANTRIP_EMBED_PROVIDER", "voyage")
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        router = build_role_router()
        # Voyage providers store the model in ``model_name``.
        assert router.has_embed() is True
        assert router.get_embed().model_name == "voyage-3"

    def test_cli_arg_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANTRIP_EMBED_PROVIDER", "voyage")
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        router = build_role_router(embed_provider="openai", embed_model="text-embedding-3-large")
        assert router.get_embed().model_name == "text-embedding-3-large"

    def test_unknown_provider_id_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CANTRIP_EMBED_PROVIDER", raising=False)
        with pytest.raises(ValueError, match="Unknown embed provider"):
            build_role_router(embed_provider="bogus")


class TestRecordRoleUsage:
    """``record_role_usage`` writes embed/rerank rows to the store."""

    def test_records_to_store(self) -> None:
        captured: list[dict[str, object]] = []

        class _StoreSpy:
            def record_usage(
                self,
                *,
                provider: str,
                model: str,
                prompt_tokens: int,
                completion_tokens: int,
                category: str | None,
                role: str | None,
            ) -> int:
                captured.append(
                    {
                        "provider": provider,
                        "model": model,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "category": category,
                        "role": role,
                    }
                )
                return len(captured)

        rowid = record_role_usage(
            _StoreSpy(),
            provider_id="voyage",
            model="voyage-3",
            input_tokens=42,
            role="embed",
        )
        assert rowid == 1
        assert captured[0]["provider"] == "voyage"
        assert captured[0]["model"] == "voyage-3"
        assert captured[0]["prompt_tokens"] == 42
        assert captured[0]["completion_tokens"] == 0
        assert captured[0]["role"] == "embed"

    def test_returns_none_when_store_lacks_method(self) -> None:
        # Legacy callers without a real store should not crash.
        result = record_role_usage(
            object(),
            provider_id="voyage",
            model="voyage-3",
            input_tokens=10,
            role="embed",
        )
        assert result is None
