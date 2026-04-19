"""Tests for the shared slash-command dispatcher."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cantrip.agent import slash_commands
from cantrip.agent.memory import GlobalMemoryStore, MemoryManager
from cantrip.agent.slash_commands import SlashResult, dispatch
from cantrip.agent.store import SessionStore


@pytest.fixture
def session_store(tmp_path: Path) -> Iterator[SessionStore]:
    s = SessionStore(tmp_path / ".cantrip")
    s.open()
    yield s
    s.close()


@pytest.fixture
def memory_manager(tmp_path: Path, session_store: SessionStore) -> MemoryManager:
    return MemoryManager(
        session_store=session_store,
        global_store=GlobalMemoryStore(tmp_path / "globalmem"),
    )


def _fake_agent(
    memory_manager: MemoryManager | None = None,
    *,
    charm_path: Path | None = None,
    mcp_registry=None,
    marketplace_sources: list | None = None,
    marketplace_loader=None,
    store=None,
    provider_model: str = "fake-model",
    cache_read: int = 0,
    cache_write: int = 0,
) -> SimpleNamespace:
    """Build the smallest agent-shaped object the dispatcher inspects."""
    return SimpleNamespace(
        _memory_manager=memory_manager,
        state=SimpleNamespace(charm_path=charm_path),
        mcp_registry=mcp_registry,
        mcp_marketplace_sources=marketplace_sources or [],
        mcp_marketplace_loader=marketplace_loader,
        store=store,
        provider=SimpleNamespace(model_name=provider_model),
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_write,
    )


class TestDispatch:
    """Core dispatch contract: verb routing, return shape, unknowns."""

    def test_unknown_verb_returns_none(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager)
        assert dispatch(agent, "/notacommand foo") is None

    def test_plain_text_returns_none(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager)
        assert dispatch(agent, "hello world") is None

    def test_help_renders(self, memory_manager: MemoryManager) -> None:
        result = dispatch(_fake_agent(memory_manager), "/help")
        assert isinstance(result, SlashResult)
        assert result.followup is None
        assert "/memory" in result.text
        assert "/mcp" in result.text

    def test_question_mark_aliases_help(self, memory_manager: MemoryManager) -> None:
        result = dispatch(_fake_agent(memory_manager), "?")
        assert result is not None
        assert result.text == slash_commands.help_text()

    def test_case_insensitive_verb(self, memory_manager: MemoryManager) -> None:
        result = dispatch(_fake_agent(memory_manager), "/HELP")
        assert result is not None
        assert "/memory" in result.text

    def test_memory_routes_to_handler(self, memory_manager: MemoryManager) -> None:
        memory_manager.write(scope="charm", title="t1", kind="fact", body="b")
        result = dispatch(_fake_agent(memory_manager), "/memory")
        assert result is not None
        assert "t1" in result.text

    def test_remember_routes_to_handler(self, memory_manager: MemoryManager) -> None:
        result = dispatch(_fake_agent(memory_manager), "/remember fact -- foo -- bar")
        assert result is not None
        assert "foo" in result.text

    def test_forget_routes_to_handler(self, memory_manager: MemoryManager) -> None:
        memory_manager.write(scope="charm", title="keep", kind="fact", body="b")
        result = dispatch(_fake_agent(memory_manager), '/forget "keep"')
        assert result is not None
        assert "Forgot" in result.text

    def test_quit_returns_quit_flag(self, memory_manager: MemoryManager) -> None:
        result = dispatch(_fake_agent(memory_manager), "/quit")
        assert result is not None
        assert result.quit is True

    def test_exit_returns_quit_flag(self, memory_manager: MemoryManager) -> None:
        """``/exit`` is an alias for ``/quit``."""
        result = dispatch(_fake_agent(memory_manager), "/exit")
        assert result is not None
        assert result.quit is True

    def test_non_quit_commands_do_not_set_quit(self, memory_manager: MemoryManager) -> None:
        result = dispatch(_fake_agent(memory_manager), "/help")
        assert result is not None
        assert result.quit is False


class TestMcpDispatch:
    """The /mcp branch — sync vs. async marketplace follow-up."""

    def test_mcp_without_registry(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager, mcp_registry=None)
        result = dispatch(agent, "/mcp")
        assert result is not None
        assert result.followup is None
        assert "MCP is not configured" in result.text

    def test_mcp_overview_uses_registry(self, memory_manager: MemoryManager) -> None:
        registry = MagicMock()
        registry.snapshot.return_value = []
        agent = _fake_agent(memory_manager, mcp_registry=registry)
        result = dispatch(agent, "/mcp")
        assert result is not None
        assert result.followup is None
        assert "No MCP servers configured" in result.text

    def test_mcp_marketplace_returns_followup(self, memory_manager: MemoryManager) -> None:
        """Marketplace lookup must defer via followup, not block dispatch."""
        registry = MagicMock()
        loader = MagicMock()

        async def fake_load_all(*_args, **_kwargs):
            return []

        loader.load_all = fake_load_all
        agent = _fake_agent(
            memory_manager,
            mcp_registry=registry,
            marketplace_sources=[MagicMock()],
            marketplace_loader=loader,
        )
        result = dispatch(agent, "/mcp marketplace")
        assert result is not None
        assert result.followup is not None
        assert inspect.iscoroutine(result.followup)
        assert "Loading" in result.text
        # Tidy up — leaving an unawaited coroutine raises a RuntimeWarning.
        result.followup.close()


class TestCost:
    """/cost routes to format_cost and handles the no-data case."""

    def test_cost_without_store(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager, store=None)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "No usage data" in result.text

    def test_cost_with_empty_usage(self, memory_manager: MemoryManager) -> None:
        store = MagicMock()
        store.get_total_usage.return_value = {"prompt_tokens": 0, "completion_tokens": 0}
        store.get_usage_by_model.return_value = []
        agent = _fake_agent(memory_manager, store=store)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "No tokens used" in result.text

    def test_cost_renders_totals(self, memory_manager: MemoryManager) -> None:
        store = MagicMock()
        store.get_total_usage.return_value = {"prompt_tokens": 1000, "completion_tokens": 200}
        store.get_usage_by_model.return_value = []
        agent = _fake_agent(memory_manager, store=store)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "1,000" in result.text
        assert "200" in result.text
        assert "1,200" in result.text
