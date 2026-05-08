"""Tests for the Phase 72b slash commands (/symbols, /definition, /references)."""

from __future__ import annotations

import pathlib
import textwrap
from unittest.mock import MagicMock

import pytest

from cantrip.agent.commands.codeintel import (
    handle_definition,
    handle_references,
    handle_symbols,
)
from cantrip.agent.commands.custom import CustomCommandRegistry
from cantrip.agent.commands.slash import COMMAND_CATALOGUE, dispatch
from cantrip.codeintel import CodeIntel

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
# Catalogue + drift guard
# ---------------------------------------------------------------------------


class TestCatalogueRegistration:
    def test_all_three_commands_registered(self) -> None:
        verbs = {info.verb for info in COMMAND_CATALOGUE}
        assert "/symbols" in verbs
        assert "/definition" in verbs
        assert "/references" in verbs
