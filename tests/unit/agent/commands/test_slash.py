"""Tests for the shared slash-command dispatcher."""

from __future__ import annotations

import inspect
import pathlib
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cantrip.agent.commands import share as share_commands
from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.commands.slash import SlashResult, dispatch
from cantrip.agent.memory import GlobalMemoryStore, MemoryManager
from cantrip.agent.store import SessionStore


@pytest.fixture
def session_store(tmp_path: pathlib.Path) -> Iterator[SessionStore]:
    s = SessionStore(tmp_path / ".cantrip")
    s.open()
    yield s
    s.close()


@pytest.fixture
def memory_manager(tmp_path: pathlib.Path, session_store: SessionStore) -> MemoryManager:
    return MemoryManager(
        session_store=session_store,
        global_store=GlobalMemoryStore(tmp_path / "globalmem"),
    )


def _fake_agent(
    memory_manager: MemoryManager | None = None,
    *,
    charm_path: pathlib.Path | None = None,
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
        store.get_replay_savings.return_value = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "request_count": 0,
        }
        agent = _fake_agent(memory_manager, store=store)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "No tokens used" in result.text

    def test_cost_renders_totals(self, memory_manager: MemoryManager) -> None:
        store = MagicMock()
        store.get_total_usage.return_value = {"prompt_tokens": 1000, "completion_tokens": 200}
        store.get_usage_by_model.return_value = []
        store.get_usage_by_category.return_value = []
        store.get_replay_savings.return_value = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "request_count": 0,
        }
        agent = _fake_agent(memory_manager, store=store)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "1,000" in result.text
        assert "200" in result.text
        assert "1,200" in result.text
        # With zero savings, the cached-from-checkpoint line is omitted.
        assert "Cached from checkpoint" not in result.text

    def test_cost_renders_cached_from_checkpoint_when_nonzero(
        self, memory_manager: MemoryManager
    ) -> None:
        """Phase 52.6: replayed tokens show up alongside live usage."""
        store = MagicMock()
        store.get_total_usage.return_value = {"prompt_tokens": 800, "completion_tokens": 100}
        store.get_usage_by_model.return_value = []
        store.get_usage_by_category.return_value = []
        store.get_replay_savings.return_value = {
            "prompt_tokens": 250,
            "completion_tokens": 50,
            "request_count": 3,
        }
        agent = _fake_agent(memory_manager, store=store)
        result = dispatch(agent, "/cost")
        assert result is not None
        assert "Cached from checkpoint: 300 tokens" in result.text
        assert "250 prompt" in result.text
        assert "50 completion" in result.text
        assert "3 replayed turn(s)" in result.text

    def test_cost_renders_category_breakdown(self, memory_manager: MemoryManager) -> None:
        """Phase 31.4: ``/cost`` surfaces a **By category** table."""
        store = MagicMock()
        store.get_total_usage.return_value = {
            "prompt_tokens": 500,
            "completion_tokens": 250,
        }
        store.get_usage_by_model.return_value = []
        store.get_replay_savings.return_value = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "request_count": 0,
        }
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


class TestBudget:
    """Phase 55.3: ``/budget`` shows or raises the per-goal budget."""

    def _make_agent(
        self,
        memory_manager: MemoryManager,
        store: SessionStore,
        *,
        budget=None,
        tasks: list | None = None,
    ) -> SimpleNamespace:
        from cantrip.agent.queue import WorkQueue

        queue = WorkQueue()
        for task in tasks or []:
            queue.add_task(task)
        return SimpleNamespace(
            _memory_manager=memory_manager,
            state=SimpleNamespace(
                charm_path=None,
                goal_budget=budget,
                messages=[],
            ),
            mcp_registry=None,
            mcp_marketplace_sources=[],
            mcp_marketplace_loader=None,
            store=store,
            provider=SimpleNamespace(model_name="fake-model"),
            cache_read_tokens=0,
            cache_creation_tokens=0,
            work_queue=queue,
        )

    def test_no_budget_set_shows_usage_hint(
        self, memory_manager: MemoryManager, session_store: SessionStore
    ) -> None:
        agent = self._make_agent(memory_manager, session_store, budget=None)
        result = dispatch(agent, "/budget")
        assert result is not None
        assert "No goal budget" in result.text

    def test_shows_summary_when_budget_set(
        self, memory_manager: MemoryManager, session_store: SessionStore
    ) -> None:
        from cantrip.agent.goal_budget import GoalBudget

        budget = GoalBudget(max_iterations=10)
        agent = self._make_agent(memory_manager, session_store, budget=budget)
        result = dispatch(agent, "/budget")
        assert result is not None
        assert "0/10" in result.text

    def test_raise_iteration_cap_in_place(
        self, memory_manager: MemoryManager, session_store: SessionStore
    ) -> None:
        from cantrip.agent.goal_budget import GoalBudget

        budget = GoalBudget(max_iterations=5)
        agent = self._make_agent(memory_manager, session_store, budget=budget)
        result = dispatch(agent, "/budget --max-iterations 50")
        assert result is not None
        assert budget.max_iterations == 50
        assert "50" in result.text

    def test_set_cap_creates_budget_if_none(
        self, memory_manager: MemoryManager, session_store: SessionStore
    ) -> None:
        agent = self._make_agent(memory_manager, session_store, budget=None)
        result = dispatch(agent, "/budget --max-prompt-tokens 10000")
        assert result is not None
        assert agent.state.goal_budget is not None
        assert agent.state.goal_budget.max_prompt_tokens == 10_000

    def test_clear_drops_budget(
        self, memory_manager: MemoryManager, session_store: SessionStore
    ) -> None:
        from cantrip.agent.goal_budget import GoalBudget

        agent = self._make_agent(
            memory_manager, session_store, budget=GoalBudget(max_iterations=5)
        )
        result = dispatch(agent, "/budget --clear")
        assert result is not None
        assert agent.state.goal_budget is None

    def test_raise_unblocks_budget_blocked_tasks(
        self, memory_manager: MemoryManager, session_store: SessionStore
    ) -> None:
        """Raising the cap moves budget-blocked tasks back to pending."""
        from cantrip.agent.goal_budget import GoalBudget
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        blocked_task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        other_blocked = AgentTask(id="t2", title="Wait", category=TaskCategory.BUILD)
        agent = self._make_agent(
            memory_manager,
            session_store,
            budget=GoalBudget(max_iterations=1),
            tasks=[blocked_task, other_blocked],
        )
        # Block both — one for budget, one for something else.
        agent.work_queue.set_blocked("t1", "Goal budget exceeded: 1 iterations (cap: 1).")
        agent.work_queue.set_blocked("t2", "Waiting for user confirmation")

        dispatch(agent, "/budget --max-iterations 100")

        assert agent.work_queue.get_task("t1").status is TaskStatus.PENDING
        # Not budget-blocked → untouched.
        assert agent.work_queue.get_task("t2").status is TaskStatus.BLOCKED

    def test_rejects_unknown_flag(
        self, memory_manager: MemoryManager, session_store: SessionStore
    ) -> None:
        agent = self._make_agent(memory_manager, session_store, budget=None)
        result = dispatch(agent, "/budget --wat 10")
        assert result is not None
        assert "Usage" in result.text

    def test_rejects_negative_value(
        self, memory_manager: MemoryManager, session_store: SessionStore
    ) -> None:
        agent = self._make_agent(memory_manager, session_store, budget=None)
        result = dispatch(agent, "/budget --max-iterations -1")
        assert result is not None
        assert ">= 0" in result.text


class TestExport:
    """/export writes the live transcript to disk via the shared renderers."""

    def test_defaults_to_html_in_charm_dir(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
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
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        del session_store
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/export markdown")
        assert result is not None
        destination = tmp_path / "transcript.md"
        assert destination.exists()
        assert "markdown" in result.text.lower()

    def test_custom_output_path(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        del session_store
        target = tmp_path / "out" / "session.jsonl"
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, f"/export jsonl {target}")
        assert result is not None
        assert target.exists()
        assert str(target) in result.text

    def test_extra_arguments_report_usage(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
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
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        agent = _fake_agent(memory_manager, charm_path=empty)
        result = dispatch(agent, "/export")
        assert result is not None
        assert "no `.cantrip`" in result.text


class TestShare:
    """Phase 67.4 — ``/share`` uploads the HTML transcript as a secret gist."""

    def _agent_with_charm(
        self, memory_manager: MemoryManager, charm_path: pathlib.Path
    ) -> SimpleNamespace:
        """Agent shell with a ``.cantrip`` file so /share doesn't short-circuit."""
        (charm_path / ".cantrip").write_bytes(b"sqlite-placeholder")
        return _fake_agent(memory_manager, charm_path=charm_path)

    def test_missing_charm_path_short_circuits(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager, charm_path=None)
        result = dispatch(agent, "/share")
        assert result is not None
        assert result.followup is None
        assert "no charm path" in result.text

    def test_missing_cantrip_db_short_circuits(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        agent = _fake_agent(memory_manager, charm_path=empty)
        result = dispatch(agent, "/share")
        assert result is not None
        assert result.followup is None
        assert "no `.cantrip`" in result.text

    def test_charm_ready_returns_followup(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        agent = self._agent_with_charm(memory_manager, tmp_path)
        result = dispatch(agent, "/share")
        assert result is not None
        assert result.followup is not None
        assert "Uploading session" in result.text
        result.followup.close()

    @pytest.mark.asyncio
    async def test_share_happy_path_returns_gist_url(self, tmp_path: pathlib.Path) -> None:
        from unittest.mock import patch

        charm_path = tmp_path / "charm"
        charm_path.mkdir()
        (charm_path / ".cantrip").write_bytes(b"sqlite-placeholder")

        async def _fake_comm(_self):
            return (b"https://gist.github.com/user/abc123\n", b"")

        # Mock the transcript pipeline so the test doesn't need a real
        # SQLite file on disk.
        with (
            patch("cantrip.transcript.export.load_transcript", return_value={}),
            patch("cantrip.transcript.html.render_html", return_value="<html/>"),
            patch("cantrip.agent.commands.share.shutil.which", return_value="/usr/bin/gh"),
            patch("cantrip.agent.commands.share.asyncio.create_subprocess_exec") as mock_exec,
        ):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = _fake_comm.__get__(mock_proc)

            async def _fake_exec(*_args, **_kwargs):
                return mock_proc

            mock_exec.side_effect = _fake_exec

            result = await share_commands.share_to_gist(
                charm_path / ".cantrip",
                charm_path,
            )

        assert "https://gist.github.com/user/abc123" in result

    @pytest.mark.asyncio
    async def test_share_falls_back_to_local_path_when_gh_missing(
        self, tmp_path: pathlib.Path
    ) -> None:
        from unittest.mock import patch

        charm_path = tmp_path / "charm"
        charm_path.mkdir()
        (charm_path / ".cantrip").write_bytes(b"sqlite-placeholder")

        with (
            patch("cantrip.transcript.export.load_transcript", return_value={}),
            patch("cantrip.transcript.html.render_html", return_value="<html/>"),
            patch("cantrip.agent.commands.share.shutil.which", return_value=None),
        ):
            result = await share_commands.share_to_gist(
                charm_path / ".cantrip",
                charm_path,
            )

        assert "`gh` is not installed" in result
        assert "gh gist create" in result
        # The user should see the local path so they can upload manually.
        assert "cantrip-session-charm-" in result

    @pytest.mark.asyncio
    async def test_share_surfaces_gh_auth_failure_with_retry_command(
        self, tmp_path: pathlib.Path
    ) -> None:
        from unittest.mock import patch

        charm_path = tmp_path / "charm"
        charm_path.mkdir()
        (charm_path / ".cantrip").write_bytes(b"sqlite-placeholder")

        async def _fake_comm(_self):
            return (b"", b"You are not logged into any GitHub hosts. Run gh auth login\n")

        with (
            patch("cantrip.transcript.export.load_transcript", return_value={}),
            patch("cantrip.transcript.html.render_html", return_value="<html/>"),
            patch("cantrip.agent.commands.share.shutil.which", return_value="/usr/bin/gh"),
            patch("cantrip.agent.commands.share.asyncio.create_subprocess_exec") as mock_exec,
        ):
            mock_proc = MagicMock()
            mock_proc.returncode = 4
            mock_proc.communicate = _fake_comm.__get__(mock_proc)

            async def _fake_exec(*_args, **_kwargs):
                return mock_proc

            mock_exec.side_effect = _fake_exec

            result = await share_commands.share_to_gist(
                charm_path / ".cantrip",
                charm_path,
            )

        assert "Failed to upload gist" in result
        assert "gh auth login" in result
        assert "gh gist create" in result


class TestCopy:
    """Phase 76 — ``/copy`` puts a chat message on the system clipboard."""

    def _seed_messages(self, store: SessionStore, msgs: list[tuple[str, str]]) -> None:
        """Append (role, content) pairs to the live session store."""
        for role, content in msgs:
            store.record_message(role=role, content=content)

    def test_missing_charm_path(self, memory_manager: MemoryManager) -> None:
        agent = _fake_agent(memory_manager, charm_path=None)
        result = dispatch(agent, "/copy")
        assert result is not None
        assert result.clipboard_text is None
        assert "no charm path" in result.text

    def test_missing_cantrip_db(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        agent = _fake_agent(memory_manager, charm_path=empty)
        result = dispatch(agent, "/copy")
        assert result is not None
        assert result.clipboard_text is None
        assert "no `.cantrip`" in result.text

    def test_no_messages_yet(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        del session_store
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/copy")
        assert result is not None
        assert result.clipboard_text is None
        assert "no messages" in result.text

    def test_no_assistant_messages_falls_back_to_last_message(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        # When the first turn errors before the agent produces an
        # assistant message, ``/copy`` should still capture something
        # rather than refusing — fall back to the most recent message
        # and label the role so the user knows what landed on the
        # clipboard.
        self._seed_messages(session_store, [("user", "hello")])
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/copy")
        assert result is not None
        assert result.clipboard_text == "hello"
        assert "no assistant messages yet" in result.text
        assert "user" in result.text

    def test_explicit_assistant_with_no_assistant_messages_refuses(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        # ``/copy assistant`` is an explicit role request — keep the
        # refusal so the user knows their selector found nothing
        # rather than silently copying a different role.
        self._seed_messages(session_store, [("user", "hello")])
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/copy assistant")
        assert result is not None
        assert result.clipboard_text is None
        assert "no assistant messages" in result.text

    def test_default_copies_last_assistant_body(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        self._seed_messages(
            session_store,
            [
                ("user", "hi"),
                ("assistant", "first reply"),
                ("user", "more"),
                ("assistant", "**second reply** with markdown"),
            ],
        )
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/copy")
        assert result is not None
        assert result.clipboard_text == "**second reply** with markdown"
        assert "last assistant message" in result.text
        # Confirmation includes a character count so the user knows
        # something concrete landed in the clipboard.
        assert "chars" in result.text

    def test_last_grabs_any_role(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        self._seed_messages(
            session_store,
            [
                ("assistant", "earlier reply"),
                ("user", "the user's last message"),
            ],
        )
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/copy last")
        assert result is not None
        assert result.clipboard_text == "the user's last message"
        assert "user" in result.text

    def test_explicit_index(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        self._seed_messages(
            session_store,
            [("user", "one"), ("assistant", "two"), ("user", "three")],
        )
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/copy 2")
        assert result is not None
        assert result.clipboard_text == "two"
        assert "#2" in result.text

    def test_index_out_of_range(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        self._seed_messages(session_store, [("user", "only")])
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/copy 99")
        assert result is not None
        assert result.clipboard_text is None
        assert "out of range" in result.text

    def test_invalid_argument_shows_usage(
        self, memory_manager: MemoryManager, tmp_path: pathlib.Path, session_store: SessionStore
    ) -> None:
        # Seed at least one message so the dispatch reaches the
        # selector parser instead of bailing on "no messages yet".
        self._seed_messages(session_store, [("user", "hi")])
        agent = _fake_agent(memory_manager, charm_path=tmp_path)
        result = dispatch(agent, "/copy banana")
        assert result is not None
        assert result.clipboard_text is None
        assert "Usage" in result.text


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


class TestModel:
    """``/model`` prints the active model or swaps the provider mid-session."""

    def _agent(self, *, provider_name="gemini", model_name="gemini-3-flash-preview"):
        """Minimal agent shape the ``/model`` handler inspects."""
        return SimpleNamespace(
            _memory_manager=None,
            state=SimpleNamespace(charm_path=None),
            mcp_registry=None,
            mcp_marketplace_sources=[],
            mcp_marketplace_loader=None,
            store=None,
            provider=SimpleNamespace(
                name=provider_name,
                model_name=model_name,
                context_window_tokens=1_048_576,
            ),
            _light_provider=None,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            switch_model=MagicMock(),
        )

    def test_bare_model_prints_active(self):
        agent = self._agent()
        result = dispatch(agent, "/model")
        assert result is not None
        assert result.followup is None
        assert "gemini/gemini-3-flash-preview" in result.text
        assert "`/model <provider>" in result.text

    def test_bare_model_surfaces_light_provider(self):
        agent = self._agent()
        agent._light_provider = SimpleNamespace(
            name="claude",
            model_name="claude-haiku-4-5-20251001",
        )
        result = dispatch(agent, "/model")
        assert result is not None
        assert "light: claude/claude-haiku-4-5-20251001" in result.text

    def test_unknown_provider_surfaces_known_set(self):
        agent = self._agent()
        result = dispatch(agent, "/model no-such-provider")
        assert result is not None
        agent.switch_model.assert_not_called()
        assert "Unknown provider" in result.text
        assert "`claude`" in result.text

    def test_provider_only_switches_to_default_model(self):
        agent = self._agent()

        # Simulate what switch_model does to the provider pointer.
        def _swap(name, _model=None):
            agent.provider = SimpleNamespace(
                name=name,
                model_name="claude-sonnet-4-6",
                context_window_tokens=200_000,
            )

        agent.switch_model.side_effect = _swap
        result = dispatch(agent, "/model claude")
        assert result is not None
        agent.switch_model.assert_called_once_with("claude", None)
        assert "Switched to **claude/claude-sonnet-4-6**" in result.text
        assert "200,000 tokens" in result.text

    def test_provider_slash_model_parses_on_first_slash(self):
        """Fireworks model slugs contain ``/`` — only the first one splits."""
        agent = self._agent()

        def _swap(name, model=None):
            agent.provider = SimpleNamespace(
                name=name,
                model_name=model,
                context_window_tokens=262_144,
            )

        agent.switch_model.side_effect = _swap
        result = dispatch(agent, "/model fireworks/accounts/fireworks/models/kimi-k2p6")
        assert result is not None
        agent.switch_model.assert_called_once_with(
            "fireworks",
            "accounts/fireworks/models/kimi-k2p6",
        )

    def test_provider_error_surfaces_cleanly(self):
        from cantrip.llm.base import ProviderError

        agent = self._agent()
        agent.switch_model.side_effect = ProviderError("FIREWORKS_API_KEY not set")
        result = dispatch(agent, "/model fireworks")
        assert result is not None
        assert "Failed to switch model" in result.text
        assert "FIREWORKS_API_KEY" in result.text


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
        self,
        memory_manager: MemoryManager,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
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
        self,
        memory_manager: MemoryManager,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
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
            pypi_url="https://pypi.org/project/juju-cantrip/0.2.0/",
            release_timestamp=None,
        )
        monkeypatch.setattr(update, "check_for_update", AsyncMock(return_value=info))
        monkeypatch.setattr(update, "update_check_disabled", lambda: False)
        monkeypatch.setattr(update, "detect_install_method", lambda: update.InstallMethod.UV_TOOL)
        text = await slash_commands._run_update_slash_check()
        assert "0.2.0" in text
        assert "uv tool upgrade juju-cantrip" in text
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


class TestSandbox:
    """Phase 49.5 — ``/sandbox`` shows current mechanism + policy."""

    def test_sandbox_without_tool_returns_none_mechanism(
        self, memory_manager: MemoryManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cantrip.agent import sandbox

        monkeypatch.setattr(sandbox, "sandbox_available", lambda: "none")
        monkeypatch.setattr(sandbox, "get_event_sink", lambda: None)
        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/sandbox")
        assert result is not None
        assert "none" in result.text
        assert "run_command" in result.text
        assert "off" in result.text  # transcript-logging line

    def test_sandbox_with_bwrap_mentions_full_isolation(
        self, memory_manager: MemoryManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cantrip.agent import sandbox

        monkeypatch.setattr(sandbox, "sandbox_available", lambda: "bwrap")
        monkeypatch.setattr(sandbox, "get_event_sink", lambda: None)
        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/sandbox")
        assert result is not None
        assert "bwrap" in result.text
        assert "full filesystem" in result.text

    def test_sandbox_with_unshare_mentions_bubblewrap_upgrade_path(
        self, memory_manager: MemoryManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cantrip.agent import sandbox

        monkeypatch.setattr(sandbox, "sandbox_available", lambda: "unshare")
        monkeypatch.setattr(sandbox, "get_event_sink", lambda: None)
        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/sandbox")
        assert result is not None
        assert "unshare" in result.text
        assert "bubblewrap" in result.text

    def test_sandbox_with_sink_registered_shows_on(
        self, memory_manager: MemoryManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cantrip.agent import sandbox

        monkeypatch.setattr(sandbox, "sandbox_available", lambda: "bwrap")
        monkeypatch.setattr(sandbox, "get_event_sink", lambda: lambda *_a: None)
        agent = _fake_agent(memory_manager)
        result = dispatch(agent, "/sandbox")
        assert result is not None
        assert "Transcript logging:** on" in result.text


class TestCommandCatalogue:
    """The shared catalogue drives UI autocomplete and must stay in sync."""

    def test_every_dispatched_verb_is_catalogued(self) -> None:
        """Scan ``dispatch()`` for ``/<verb>`` literals; all must be in the catalogue.

        Guards against drift when a new verb lands in the dispatcher but
        the catalogue (and therefore the TUI slash-autocomplete popup)
        is not updated.
        """
        import ast

        # The dispatch entry point is a thin try/except wrapper around
        # ``_dispatch_inner`` (Phase 7 hardening), which is where the
        # ``if verb == "/foo":`` literals actually live.  Read both so
        # the drift test stays accurate if someone moves a verb back.
        source = (
            inspect.getsource(slash_commands.dispatch)
            + "\n"
            + inspect.getsource(slash_commands._dispatch_inner)
        )
        tree = ast.parse(source)
        dispatched: set[str] = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("/")
        }
        assert dispatched, "Expected at least one /-verb literal in dispatcher source."
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
