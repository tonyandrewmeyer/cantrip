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
        store.get_usage_by_category.return_value = []
        agent = _fake_agent(memory_manager, store=store)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "No tokens used" in result.text

    def test_cost_renders_totals(self, memory_manager: MemoryManager) -> None:
        store = MagicMock()
        store.get_total_usage.return_value = {"prompt_tokens": 1000, "completion_tokens": 200}
        store.get_usage_by_model.return_value = []
        store.get_usage_by_category.return_value = []
        agent = _fake_agent(memory_manager, store=store)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "1,000" in result.text
        assert "200" in result.text
        assert "1,200" in result.text

    def test_cost_renders_category_breakdown(self, memory_manager: MemoryManager) -> None:
        """Phase 31.4: ``/cost`` surfaces a **By category** table."""
        store = MagicMock()
        store.get_total_usage.return_value = {
            "prompt_tokens": 500,
            "completion_tokens": 250,
        }
        store.get_usage_by_model.return_value = []
        store.get_usage_by_category.return_value = [
            {
                "category": "build",
                "provider": "claude",
                "model": "claude-opus-4",
                "prompt_tokens": 300,
                "completion_tokens": 150,
                "request_count": 2,
            },
            {
                "category": "research",
                "provider": "claude",
                "model": "claude-haiku-4-5-20251001",
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "request_count": 5,
            },
        ]
        agent = _fake_agent(memory_manager, store=store)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "**By category**" in result.text
        # Sorted alphabetically — build before research.
        build_idx = result.text.index("build:")
        research_idx = result.text.index("research:")
        assert build_idx < research_idx
        assert "450 tokens" in result.text  # build: 300 + 150
        assert "300 tokens" in result.text  # research: 200 + 100


class TestExport:
    """/export writes the live transcript to disk via the shared renderers."""

    def test_defaults_to_html_in_charm_dir(
        self, memory_manager: MemoryManager, tmp_path: Path, session_store: SessionStore
    ) -> None:
        del session_store  # fixture keeps the .cantrip file open for writes
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/export")
        assert result is not None
        destination = tmp_path / "transcript.html"
        assert destination.exists()
        assert str(destination) in result.text
        body = destination.read_text()
        assert "<html" in body.lower()

    def test_explicit_format_markdown(
        self, memory_manager: MemoryManager, tmp_path: Path, session_store: SessionStore
    ) -> None:
        del session_store
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/export markdown")
        assert result is not None
        destination = tmp_path / "transcript.md"
        assert destination.exists()
        assert "markdown" in result.text.lower()

    def test_custom_output_path(
        self, memory_manager: MemoryManager, tmp_path: Path, session_store: SessionStore
    ) -> None:
        del session_store
        target = tmp_path / "out" / "session.jsonl"
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, f"/export jsonl {target}")
        assert result is not None
        assert target.exists()
        assert str(target) in result.text

    def test_extra_arguments_report_usage(
        self, memory_manager: MemoryManager, tmp_path: Path, session_store: SessionStore
    ) -> None:
        del session_store
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/export html /tmp/a.html surprise")
        assert result is not None
        assert "Usage" in result.text
        assert not (tmp_path / "transcript.html").exists()

    def test_missing_charm_path_reports_error(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager, charm_path=None)
        result = dispatch(agent, "/export")
        assert result is not None
        assert "no charm path" in result.text.lower()

    def test_missing_cantrip_file_reports_error(
        self, memory_manager: MemoryManager, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        agent = _fake_agent(memory_manager, charm_path=empty)
        result = dispatch(agent, "/export")
        assert result is not None
        assert "no `.cantrip`" in result.text


class TestArena:
    """/arena returns usage when bare and a followup when given a prompt."""

    def test_bare_arena_returns_usage(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/arena")
        assert result is not None
        assert result.followup is None
        assert "/arena <prompt>" in result.text

    def test_arena_with_prompt_returns_followup(self, memory_manager: MemoryManager) -> None:
        # The followup is agent.begin_arena(args); we verify the
        # dispatcher wires it without awaiting it (the follow-up is an
        # awaitable this test just closes).

        class _Agent(SimpleNamespace):
            def begin_arena(self, prompt: str) -> object:
                async def _run() -> str:
                    return f"ran with: {prompt}"

                return _run()

        agent = _Agent(
            _memory_manager=memory_manager,
            state=SimpleNamespace(charm_path=None),
            mcp_registry=None,
            mcp_marketplace_sources=[],
            mcp_marketplace_loader=None,
            store=None,
            provider=SimpleNamespace(model_name="fake"),
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        result = dispatch(agent, "/arena compare two takes")
        assert result is not None
        assert result.followup is not None
        assert "A and B" in result.text
        # Close the awaitable so pytest's unraisable-warning detector
        # doesn't flag it.
        result.followup.close()  # type: ignore[attr-defined]


class TestUpdate:
    """``/update`` dispatch and the toggle flags."""

    def test_bare_update_returns_followup(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/update")
        assert result is not None
        assert result.followup is not None
        assert "PyPI" in result.text
        result.followup.close()  # type: ignore[attr-defined]

    def test_no_check_writes_settings(
        self, memory_manager: MemoryManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        from cantrip import update

        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(update, "_SETTINGS_PATH", settings_path)

        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/update --no-check")
        assert result is not None
        assert "disabled" in result.text
        written = json.loads(settings_path.read_text())
        assert written["update_check_disabled"] is True

    def test_check_re_enables_settings(
        self, memory_manager: MemoryManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        from cantrip import update

        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"update_check_disabled": True, "other": "keep"}))
        monkeypatch.setattr(update, "_SETTINGS_PATH", settings_path)

        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/update --check")
        assert result is not None
        assert "re-enabled" in result.text
        written = json.loads(settings_path.read_text())
        assert written["update_check_disabled"] is False
        # Unrelated keys must survive the toggle.
        assert written["other"] == "keep"

    def test_unknown_flag_shows_usage(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/update --weird")
        assert result is not None
        assert result.followup is None
        assert "Usage" in result.text

    def test_extra_tokens_show_usage(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/update --check please")
        assert result is not None
        assert "Usage" in result.text


class TestUpdateFollowup:
    """The ``/update`` follow-up coroutine hits PyPI cache-bypassed."""

    @pytest.mark.asyncio
    async def test_latest_version_returns_up_to_date_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock

        from cantrip import update

        monkeypatch.setattr(update, "check_for_update", AsyncMock(return_value=None))
        monkeypatch.setattr(update, "update_check_disabled", lambda: False)
        text = await slash_commands._run_update_slash_check()
        assert "latest" in text

    @pytest.mark.asyncio
    async def test_newer_release_renders_formatted_notice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock

        from cantrip import update

        info = update.UpdateInfo(
            current="0.1.0",
            latest="0.2.0",
            pypi_url="https://pypi.org/project/cantrip/0.2.0/",
            release_timestamp=None,
        )
        monkeypatch.setattr(update, "check_for_update", AsyncMock(return_value=info))
        monkeypatch.setattr(update, "update_check_disabled", lambda: False)
        monkeypatch.setattr(update, "detect_install_method", lambda: update.InstallMethod.UV_TOOL)
        text = await slash_commands._run_update_slash_check()
        assert "0.2.0" in text
        assert "uv tool upgrade cantrip" in text
        # The running process still executes the old code — the notice
        # says so explicitly because /update fires mid-session.
        assert "restart" in text.lower()

    @pytest.mark.asyncio
    async def test_disabled_check_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cantrip import update

        monkeypatch.setattr(update, "update_check_disabled", lambda: True)
        text = await slash_commands._run_update_slash_check()
        assert "disabled" in text
        assert "--check" in text

    @pytest.mark.asyncio
    async def test_network_error_reports_cleanly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import AsyncMock

        from cantrip import update

        monkeypatch.setattr(update, "update_check_disabled", lambda: False)
        monkeypatch.setattr(
            update, "check_for_update", AsyncMock(side_effect=OSError("no network"))
        )
        text = await slash_commands._run_update_slash_check()
        assert "Could not reach PyPI" in text
        assert "no network" in text


class TestCommandCatalogue:
    """The shared catalogue drives UI autocomplete and must stay in sync."""

    def test_every_dispatched_verb_is_catalogued(self) -> None:
        """Scan ``dispatch()`` for ``/<verb>`` literals; all must be in the catalogue.

        Guards against drift when a new verb lands in the dispatcher but
        the catalogue (and therefore the TUI slash-autocomplete popup)
        is not updated.
        """
        import ast

        source = inspect.getsource(slash_commands.dispatch)
        tree = ast.parse(source)
        dispatched: set[str] = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("/")
        }
        assert dispatched, "Expected at least one /-verb literal in dispatch()."
        catalogue_verbs = {cmd.verb for cmd in slash_commands.COMMAND_CATALOGUE}
        missing = dispatched - catalogue_verbs
        assert not missing, (
            f"dispatch() handles verbs missing from COMMAND_CATALOGUE: {sorted(missing)}"
        )

    def test_catalogue_verbs_are_shared_verbs(self) -> None:
        """COMMAND_CATALOGUE cannot leak verbs the dispatcher does not accept."""
        catalogue_verbs = {cmd.verb for cmd in slash_commands.COMMAND_CATALOGUE}
        assert catalogue_verbs <= slash_commands.SHARED_VERBS

    def test_catalogue_entries_have_non_empty_summaries(self) -> None:
        for cmd in slash_commands.COMMAND_CATALOGUE:
            assert cmd.summary, f"empty summary for {cmd.verb}"

    def test_catalogue_verbs_are_unique(self) -> None:
        verbs = [cmd.verb for cmd in slash_commands.COMMAND_CATALOGUE]
        assert len(verbs) == len(set(verbs))
