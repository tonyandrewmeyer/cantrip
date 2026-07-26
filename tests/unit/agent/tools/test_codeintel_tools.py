"""Tests for the Phase 72b code-intelligence tools."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from cantrip.agent.tools.codeintel import (
    CodeDefinitionTool,
    CodeReferencesTool,
    CodeSymbolsTool,
    _coerce_kinds,
    build_codeintel_tools,
)
from cantrip.codeintel import CodeIntel

if TYPE_CHECKING:
    import pathlib

# ---------------------------------------------------------------------------
# Fixture builder — small charm with a couple of cross-file references.
# ---------------------------------------------------------------------------


def _make_charm(root: pathlib.Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "charm.py").write_text(
        textwrap.dedent(
            """
            from src.handlers import IngressHandler, build_layer


            class MyCharm:
                def __init__(self):
                    self.handler = IngressHandler()

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
def getter(index: CodeIntel):
    def _get() -> CodeIntel:
        return index

    return _get


# ---------------------------------------------------------------------------
# code_symbols
# ---------------------------------------------------------------------------


class TestCodeSymbolsTool:
    @pytest.mark.asyncio
    async def test_returns_match_with_caption_and_data(self, getter) -> None:
        tool = CodeSymbolsTool(getter)
        result = await tool.execute(query="IngressHandler")
        assert result.success
        assert "IngressHandler" in result.output
        assert "src/handlers.py" in result.output
        assert result.caption
        assert "IngressHandler" in result.caption
        assert result.data["match_count"] >= 1
        assert result.data["semantic"] is True

    @pytest.mark.asyncio
    async def test_no_match_returns_clean_message(self, getter) -> None:
        tool = CodeSymbolsTool(getter)
        result = await tool.execute(query="nothing_here_xyz")
        assert result.success
        assert "No symbols matching" in result.output
        assert result.data["match_count"] == 0

    @pytest.mark.asyncio
    async def test_kinds_argument_accepts_list_or_string(self, getter) -> None:
        tool = CodeSymbolsTool(getter)
        as_list = await tool.execute(query="Handler", kinds=["class"])
        as_string = await tool.execute(query="Handler", kinds="class")
        assert as_list.data["match_count"] == as_string.data["match_count"]

    @pytest.mark.asyncio
    async def test_path_scope_narrows_results(self, getter) -> None:
        tool = CodeSymbolsTool(getter)
        narrow = await tool.execute(query="MyCharm", path_scope="src/")
        assert narrow.data["match_count"] >= 1

    @pytest.mark.asyncio
    async def test_no_charm_path_returns_failure(self) -> None:
        tool = CodeSymbolsTool(lambda: None)
        result = await tool.execute(query="anything")
        assert not result.success
        assert "no active charm path" in (result.error or "")


# ---------------------------------------------------------------------------
# code_definition
# ---------------------------------------------------------------------------


class TestCodeDefinitionTool:
    @pytest.mark.asyncio
    async def test_resolves_definition_with_snippet(self, getter) -> None:
        tool = CodeDefinitionTool(getter)
        result = await tool.execute(symbol="IngressHandler")
        assert result.success
        assert "src/handlers.py" in result.output
        assert "class IngressHandler" in result.output
        assert result.data["semantic"] is True
        assert result.data["match_count"] == 1

    @pytest.mark.asyncio
    async def test_unknown_symbol_keeps_success_but_marks_non_semantic(self, getter) -> None:
        tool = CodeDefinitionTool(getter)
        result = await tool.execute(symbol="never_existed")
        assert result.success
        assert result.data["semantic"] is False
        assert result.data["match_count"] == 0
        assert "No definition" in result.output

    @pytest.mark.asyncio
    async def test_no_charm_path_returns_failure(self) -> None:
        tool = CodeDefinitionTool(lambda: None)
        result = await tool.execute(symbol="anything")
        assert not result.success


# ---------------------------------------------------------------------------
# code_references
# ---------------------------------------------------------------------------


class TestCodeReferencesTool:
    @pytest.mark.asyncio
    async def test_returns_callsites_with_caption(self, getter) -> None:
        tool = CodeReferencesTool(getter)
        result = await tool.execute(symbol="build_layer")
        assert result.success
        assert "src/charm.py" in result.output
        assert result.caption
        assert "build_layer" in result.caption
        assert result.data["semantic"] is True

    @pytest.mark.asyncio
    async def test_include_definition_is_passed_through(self, getter) -> None:
        tool = CodeReferencesTool(getter)
        without = await tool.execute(symbol="IngressHandler")
        with_def = await tool.execute(symbol="IngressHandler", include_definition=True)
        assert with_def.data["match_count"] >= without.data["match_count"]

    @pytest.mark.asyncio
    async def test_unknown_symbol_keeps_success_but_marks_non_semantic(self, getter) -> None:
        tool = CodeReferencesTool(getter)
        result = await tool.execute(symbol="never_existed")
        assert result.success
        assert result.data["semantic"] is False
        assert "No references" in result.output

    @pytest.mark.asyncio
    async def test_no_charm_path_returns_failure(self) -> None:
        tool = CodeReferencesTool(lambda: None)
        result = await tool.execute(symbol="anything")
        assert not result.success


# ---------------------------------------------------------------------------
# Helpers + factory
# ---------------------------------------------------------------------------


class TestCoerceKinds:
    def test_none_passthrough(self) -> None:
        assert _coerce_kinds(None) is None

    def test_string_with_commas(self) -> None:
        result = _coerce_kinds("class, function")
        assert result is not None
        assert {k.value for k in result} == {"class", "function"}

    def test_list_of_strings(self) -> None:
        result = _coerce_kinds(["class", "method"])
        assert result is not None
        assert {k.value for k in result} == {"class", "method"}

    def test_unknown_label_dropped(self) -> None:
        # ``widget`` is not a valid SymbolKind — should be silently skipped.
        result = _coerce_kinds(["class", "widget"])
        assert result is not None
        assert {k.value for k in result} == {"class"}

    def test_only_unknown_labels_returns_none(self) -> None:
        # If every label is bogus, return ``None`` so the index does
        # not silently filter to an empty set.
        assert _coerce_kinds(["widget", "doodad"]) is None


class TestFactory:
    def test_build_codeintel_tools_returns_three_tools(self, getter) -> None:
        tools = build_codeintel_tools(getter)
        names = {t.name for t in tools}
        assert names == {"code_symbols", "code_definition", "code_references"}
