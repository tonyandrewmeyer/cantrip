"""Tests for the Phase 72b ``@symbol`` / ``@definition`` / ``@references`` providers."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from cantrip.agent import context_providers_builtin
from cantrip.agent.context_providers import (
    ExpansionContext,
    expand_mentions,
)
from cantrip.codeintel import CodeIntel

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _make_charm(root: pathlib.Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "charm.py").write_text(
        textwrap.dedent(
            """
            from src.handlers import IngressHandler, build_layer


            class MyCharm:
                def install(self):
                    return build_layer("debug")
            """
        ).strip()
        + "\n"
    )
    (root / "src" / "handlers.py").write_text(
        textwrap.dedent(
            """
            class IngressHandler:
                def refresh(self) -> None:
                    pass


            def build_layer(mode: str) -> dict:
                return {"mode": mode}
            """
        ).strip()
        + "\n"
    )


@pytest.fixture
def charm_root(tmp_path: pathlib.Path) -> pathlib.Path:
    _make_charm(tmp_path)
    return tmp_path


@pytest.fixture
def index(charm_root: pathlib.Path) -> CodeIntel:
    ci = CodeIntel(charm_root)
    ci.build()
    return ci


@pytest.fixture
def registry(index: CodeIntel):
    return context_providers_builtin.build_default_registry(
        code_intel_getter=lambda: index,
    )


@pytest.fixture
def ctx(charm_root: pathlib.Path) -> ExpansionContext:
    return ExpansionContext(charm_path=charm_root)


# ---------------------------------------------------------------------------
# @symbol
# ---------------------------------------------------------------------------


class TestSymbolProvider:
    @pytest.mark.asyncio
    async def test_expansion_returns_match_block(self, registry, ctx) -> None:
        result = await expand_mentions("look at @symbol IngressHandler", registry, ctx)
        assert result.changed
        assert "IngressHandler" in result.expanded
        assert "src/handlers.py" in result.expanded

    @pytest.mark.asyncio
    async def test_no_match_renders_clean_block(self, registry, ctx) -> None:
        result = await expand_mentions("@symbol nothing_here_xyz", registry, ctx)
        assert "no matches" in result.expanded

    @pytest.mark.asyncio
    async def test_missing_query(self, registry, ctx) -> None:
        result = await expand_mentions("@symbol\nrest", registry, ctx)
        # ``@symbol`` with no trailing query — provider surfaces the error
        # block; the message body is preserved.
        assert "missing query" in result.expanded


# ---------------------------------------------------------------------------
# @definition
# ---------------------------------------------------------------------------


class TestDefinitionProvider:
    @pytest.mark.asyncio
    async def test_returns_definition_block(self, registry, ctx) -> None:
        result = await expand_mentions("@definition IngressHandler", registry, ctx)
        assert "src/handlers.py" in result.expanded
        assert "class IngressHandler" in result.expanded

    @pytest.mark.asyncio
    async def test_unknown_symbol(self, registry, ctx) -> None:
        result = await expand_mentions("@definition no_such_thing", registry, ctx)
        assert "no semantic match" in result.expanded


# ---------------------------------------------------------------------------
# @references
# ---------------------------------------------------------------------------


class TestReferencesProvider:
    @pytest.mark.asyncio
    async def test_returns_callsite_block(self, registry, ctx) -> None:
        result = await expand_mentions("@references build_layer", registry, ctx)
        assert "src/charm.py" in result.expanded

    @pytest.mark.asyncio
    async def test_unknown_symbol(self, registry, ctx) -> None:
        result = await expand_mentions("@references no_such_thing", registry, ctx)
        assert "no semantic match" in result.expanded


# ---------------------------------------------------------------------------
# Registry / availability
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_codeintel_providers_skipped_without_getter(self) -> None:
        # Build with no getter — none of the codeintel providers
        # should appear in the registry.
        registry = context_providers_builtin.build_default_registry()
        names = registry.names()
        assert "symbol" not in names
        assert "definition" not in names
        assert "references" not in names

    def test_codeintel_providers_registered_with_getter(self, index: CodeIntel) -> None:
        registry = context_providers_builtin.build_default_registry(
            code_intel_getter=lambda: index,
        )
        names = registry.names()
        assert "symbol" in names
        assert "definition" in names
        assert "references" in names

    @pytest.mark.asyncio
    async def test_no_charm_path_renders_clean_block(self) -> None:
        # The getter returns ``None`` — the provider should surface a
        # friendly inline notice rather than crashing.
        registry = context_providers_builtin.build_default_registry(
            code_intel_getter=lambda: None,
        )
        ctx = ExpansionContext()
        result = await expand_mentions("@symbol foo", registry, ctx)
        assert "no active charm path" in result.expanded
