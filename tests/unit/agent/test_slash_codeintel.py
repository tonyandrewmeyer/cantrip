"""Tests for the Phase 72b slash commands (/symbols, /definition, /references)."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from cantrip.agent.commands.codeintel import (
    handle_definition,
    handle_references,
    handle_symbols,
)
from cantrip.agent.commands.custom import CustomCommandRegistry
from cantrip.agent.commands.slash import COMMAND_CATALOGUE, dispatch
from cantrip.codeintel import CodeIntel, index
from cantrip.repomap import symbols as symbols_module

if TYPE_CHECKING:
    import pathlib

# ---------------------------------------------------------------------------
# Fixture: small charm with a couple of cross-file references.
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
def agent_with_index(tmp_path: pathlib.Path) -> MagicMock:
    _make_charm(tmp_path)
    ci = CodeIntel(tmp_path)
    ci.build()
    agent = MagicMock()
    agent.code_intel = ci
    agent.custom_commands = CustomCommandRegistry(commands=())
    return agent


# ---------------------------------------------------------------------------
# /symbols
# ---------------------------------------------------------------------------


class TestSlashSymbols:
    def test_finds_match(self, agent_with_index: MagicMock) -> None:
        text = handle_symbols(agent_with_index, "IngressHandler")
        assert "IngressHandler" in text
        assert "src/handlers.py" in text

    def test_no_match_returns_friendly_message(self, agent_with_index: MagicMock) -> None:
        text = handle_symbols(agent_with_index, "nothing_here_xyz")
        assert "No symbols matching" in text

    def test_missing_query_shows_usage(self, agent_with_index: MagicMock) -> None:
        text = handle_symbols(agent_with_index, "")
        assert "Usage" in text

    def test_missing_charm_path(self) -> None:
        agent = MagicMock()
        agent.code_intel = None
        text = handle_symbols(agent, "IngressHandler")
        assert "no active charm path" in text

    def test_dispatch_routes_through_markdown(self, agent_with_index: MagicMock) -> None:
        result = dispatch(agent_with_index, "/symbols IngressHandler")
        assert result is not None
        assert result.markdown is True
        assert "IngressHandler" in result.text


# ---------------------------------------------------------------------------
# /definition
# ---------------------------------------------------------------------------


class TestSlashDefinition:
    def test_resolves_definition(self, agent_with_index: MagicMock) -> None:
        text = handle_definition(agent_with_index, "IngressHandler")
        assert "src/handlers.py" in text
        assert "class IngressHandler" in text

    def test_unknown_symbol(self, agent_with_index: MagicMock) -> None:
        text = handle_definition(agent_with_index, "absolutely_nothing")
        assert "No definition" in text

    def test_missing_argument_shows_usage(self, agent_with_index: MagicMock) -> None:
        assert "Usage" in handle_definition(agent_with_index, "")

    def test_missing_charm_path(self) -> None:
        agent = MagicMock()
        agent.code_intel = None
        text = handle_definition(agent, "x")
        assert "no active charm path" in text

    def test_dispatch_returns_markdown(self, agent_with_index: MagicMock) -> None:
        result = dispatch(agent_with_index, "/definition IngressHandler")
        assert result is not None
        assert result.markdown is True


# ---------------------------------------------------------------------------
# /references
# ---------------------------------------------------------------------------


class TestSlashReferences:
    def test_lists_callsites(self, agent_with_index: MagicMock) -> None:
        text = handle_references(agent_with_index, "build_layer")
        assert "src/charm.py" in text

    def test_unknown_symbol(self, agent_with_index: MagicMock) -> None:
        text = handle_references(agent_with_index, "absolutely_nothing")
        assert "No references" in text

    def test_missing_argument_shows_usage(self, agent_with_index: MagicMock) -> None:
        assert "Usage" in handle_references(agent_with_index, "")

    def test_missing_charm_path(self) -> None:
        agent = MagicMock()
        agent.code_intel = None
        text = handle_references(agent, "x")
        assert "no active charm path" in text

    def test_dispatch_returns_markdown(self, agent_with_index: MagicMock) -> None:
        result = dispatch(agent_with_index, "/references build_layer")
        assert result is not None
        assert result.markdown is True


# ---------------------------------------------------------------------------
# Error and multi-result paths (Phase 114.1)
# ---------------------------------------------------------------------------


class _StubCodeIntel:
    """Query stand-in that returns canned results or raises on build.

    The real :class:`CodeIntel` only produces ambiguous definitions and
    truncated reference lists on repositories large or duplicated
    enough to be awkward to fixture.  Handing the handler a prepared
    result keeps the assertion about *rendering* rather than about
    reproducing an index state.
    """

    def __init__(
        self,
        *,
        raises: Exception | None = None,
        symbols: tuple[index.SymbolMatch, ...] = (),
        symbols_truncated: int = 0,
        definition: index.DefinitionResult | None = None,
        references: index.ReferencesResult | None = None,
    ) -> None:
        self._raises = raises
        self._symbols = symbols
        self._symbols_truncated = symbols_truncated
        self._definition = definition
        self._references = references

    def build(self, *, force: bool = False) -> None:
        del force
        if self._raises is not None:
            raise self._raises

    def workspace_symbols(self, query: str) -> tuple[tuple[index.SymbolMatch, ...], int]:
        del query
        return self._symbols, self._symbols_truncated

    def go_to_definition(self, symbol: str) -> index.DefinitionResult:
        del symbol
        assert self._definition is not None
        return self._definition

    def find_references(self, symbol: str) -> index.ReferencesResult:
        del symbol
        assert self._references is not None
        return self._references


def _symbol(name: str, file: str, line: int = 1) -> symbols_module.Symbol:
    return symbols_module.Symbol(
        name=name,
        kind=symbols_module.SymbolKind.FUNCTION,
        file=file,
        line=line,
    )


def _agent_with(ci: _StubCodeIntel) -> MagicMock:
    agent = MagicMock()
    agent.code_intel = ci
    return agent


class TestInternalErrorsAreReported:
    """A parser blow-up lands in the diagnostics log, not the chat."""

    @pytest.fixture(autouse=True)
    def _state_home(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    @pytest.mark.parametrize(
        ("handler", "verb"),
        [
            (handle_symbols, "/symbols"),
            (handle_definition, "/definition"),
            (handle_references, "/references"),
        ],
    )
    def test_build_failure_is_swallowed(self, handler, verb: str) -> None:
        agent = _agent_with(_StubCodeIntel(raises=RuntimeError("tree-sitter segfault")))
        text = handler(agent, "IngressHandler")
        assert verb in text
        assert "diagnostics.log" in text
        assert "segfault" not in text, "raw exception text must not reach chat"


class TestResultRendering:
    """Plural / truncated forms the small fixture charm never produces."""

    def test_single_symbol_match_is_singular(self) -> None:
        ci = _StubCodeIntel(symbols=(index.SymbolMatch(symbol=_symbol("foo", "a.py")),))
        text = handle_symbols(_agent_with(ci), "foo")
        assert "**1 symbol match for `foo`**" in text

    def test_multiple_symbol_matches_are_plural_and_note_elision(self) -> None:
        ci = _StubCodeIntel(
            symbols=(
                index.SymbolMatch(symbol=_symbol("foo", "a.py")),
                index.SymbolMatch(symbol=_symbol("foo", "b.py")),
            ),
            symbols_truncated=3,
        )
        text = handle_symbols(_agent_with(ci), "foo")
        assert "**2 symbol matches for `foo`**" in text
        assert "3 more elided" in text

    def test_ambiguous_definition_announces_every_candidate(self) -> None:
        result = index.DefinitionResult(
            query="build_layer",
            matches=(
                index.Definition(_symbol("build_layer", "a.py"), snippet="", snippet_start_line=0),
                index.Definition(_symbol("build_layer", "b.py"), snippet="", snippet_start_line=0),
            ),
            semantic=True,
        )
        text = handle_definition(_agent_with(_StubCodeIntel(definition=result)), "build_layer")
        assert "**2 candidate definitions for `build_layer`**" in text
        assert "a.py" in text
        assert "b.py" in text

    def test_single_reference_is_singular_across_one_file(self) -> None:
        result = index.ReferencesResult(
            query="foo",
            locations=(symbols_module.ReferenceLocation(name="foo", file="a.py", line=3),),
            truncated=0,
            semantic=True,
            candidates=(),
        )
        text = handle_references(_agent_with(_StubCodeIntel(references=result)), "foo")
        assert "**1 reference to `foo` across 1 file**" in text
        assert "elided" not in text

    def test_truncated_references_are_flagged_in_the_header(self) -> None:
        result = index.ReferencesResult(
            query="foo",
            locations=(
                symbols_module.ReferenceLocation(name="foo", file="a.py", line=3),
                symbols_module.ReferenceLocation(name="foo", file="b.py", line=9),
            ),
            truncated=48,
            semantic=True,
            candidates=(),
        )
        text = handle_references(_agent_with(_StubCodeIntel(references=result)), "foo")
        assert "**2 references to `foo` across 2 files** *(+48 elided)*" in text


# ---------------------------------------------------------------------------
# Catalogue + drift guard
# ---------------------------------------------------------------------------


class TestCatalogueRegistration:
    def test_all_three_commands_registered(self) -> None:
        verbs = {info.verb for info in COMMAND_CATALOGUE}
        assert "/symbols" in verbs
        assert "/definition" in verbs
        assert "/references" in verbs
