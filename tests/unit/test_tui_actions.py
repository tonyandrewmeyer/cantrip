"""Targeted Pilot tests for CantripApp action and bus-handler branches.

Extends ``test_tui.py`` coverage onto the dormant code paths flagged by
ROADMAP 57.5: simple action bindings (F6–F9, Ctrl+F), inline bus-event
handlers (memory, status bar, task update), the ``/feelings`` worker
lifecycle, and ``action_cancel_agent``'s no-op branch.

The handler methods were written to run off a background thread via
``call_from_thread``, which raises if called from the app's own thread.
Tests here patch ``call_from_thread`` with a synchronous passthrough so
the wrapped closures execute in-place.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.worker import WorkerState

from cantrip.tui.app import CantripApp
from cantrip.tui.screens.graph import GraphScreen
from cantrip.tui.screens.logs import LogScreen
from cantrip.tui.screens.relation import RelationDetailScreen
from cantrip.tui.screens.transcript import TranscriptScreen
from cantrip.tui.widgets import chat as chat_widget
from cantrip.tui.widgets import status as status_widgets
from cantrip.tui.widgets import statusbar as statusbar_widget
from cantrip.ui import events as ui_events
from tests.unit.test_tui import _patch_app

pytestmark = pytest.mark.tui


def _sync_passthrough(app: CantripApp) -> None:
    """No-op retained for API compatibility.

    Earlier versions of the bus handlers called ``call_from_thread``
    to marshal work onto the UI thread.  That has since been replaced
    by binding the event bus to the UI loop in :meth:`CantripApp.on_mount`,
    so bus subscribers already run on the UI thread and can touch
    widgets directly.  Tests that previously needed to patch
    ``call_from_thread`` now work unmodified; the helper stays as a
    no-op so existing callers still read cleanly.
    """
    # Intentionally empty.


# ---------------------------------------------------------------------------
# Action bindings
# ---------------------------------------------------------------------------


class TestActionBindings:
    """F-key and Ctrl-key bindings that open screens or toggle panes."""

    @pytest.mark.asyncio
    async def test_f6_toggles_charm_files(self):
        """F6 toggles the charm file-tree pane visibility."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                tree = pilot.app.query_one("#charm-files")
                start = tree.display
                await pilot.press("f6")
                await pilot.pause()
                assert tree.display != start
                await pilot.press("f6")
                await pilot.pause()
                assert tree.display == start

    @pytest.mark.asyncio
    async def test_f7_toggles_model_info_bar(self):
        """F7 toggles the model info bar."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                bar = pilot.app.query_one("#model-info")
                start = bar.display
                await pilot.press("f7")
                await pilot.pause()
                assert bar.display != start

    @pytest.mark.asyncio
    async def test_f8_opens_graph_screen(self):
        """F8 pushes the integration GraphScreen."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("f8")
                await pilot.pause()
                assert isinstance(pilot.app.screen, GraphScreen)
                await pilot.press("escape")
                await pilot.pause()

    @pytest.mark.asyncio
    async def test_f9_opens_transcript_screen(self):
        """F9 pushes the TranscriptScreen (with no db when charm_path unset)."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.charm_path = None
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("f9")
                await pilot.pause()
                assert isinstance(pilot.app.screen, TranscriptScreen)

    @pytest.mark.asyncio
    async def test_ctrl_f_opens_search(self):
        """Ctrl+F opens the chat search bar."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.press("ctrl+f")
                await pilot.pause()
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                assert chat.search_active

    @pytest.mark.asyncio
    async def test_cancel_agent_noop_without_worker(self):
        """Ctrl+C with no agent_response worker is a no-op."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                status_bar = pilot.app.query_one("#status-bar", statusbar_widget.StatusBar)
                before = status_bar.task_label
                pilot.app.action_cancel_agent()
                await pilot.pause()
                # No worker running → status bar task_label untouched.
                assert status_bar.task_label == before


class TestRelationLineSelected:
    """Dispatcher that opens a RelationDetailScreen from a status click."""

    @pytest.mark.asyncio
    async def test_relation_line_opens_detail_screen(self):
        """A RelationLine.Selected event pushes a RelationDetailScreen."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.dev_model = "dev"
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                app = pilot.app
                event = status_widgets.RelationLine.Selected(
                    unit_name="app/0",
                    endpoint="db",
                    related_app="postgresql",
                )
                app.on_relation_line_selected(event)
                await pilot.pause()
                assert isinstance(app.screen, RelationDetailScreen)


# ---------------------------------------------------------------------------
# Bus-handler branches
# ---------------------------------------------------------------------------


class TestBusHandlers:
    """Inline bus handlers that marshal payloads onto the UI thread."""

    @pytest.mark.asyncio
    async def test_on_mount_binds_bus_loop(self):
        """``on_mount`` must bind the event bus to the UI loop.

        Regression: without this, the watcher's same-loop publish
        delivered synchronously on the UI thread, the
        ``call_from_thread`` guard raised RuntimeError, and the
        exception was swallowed — leaving the Dev / COS panes empty.
        """
        p1, p2, mock_agent = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as _pilot:
                mock_agent.event_bus.bind_loop.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_written_writes_system_message(self):
        """A MEMORY_WRITTEN event adds a 'Wrote <kind> memory' system message."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                _sync_passthrough(pilot.app)
                evt = ui_events.memory_written(
                    title="Don't mock the DB",
                    scope="project",
                    kind="feedback",
                    source="user",
                )
                pilot.app._on_bus_memory_written(evt)
                await pilot.pause()

                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Wrote feedback memory: Don't mock the DB" in combined

    @pytest.mark.asyncio
    async def test_memory_recalled_writes_system_message(self):
        """A MEMORY_RECALLED event adds a 'Recalled memory' line."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                _sync_passthrough(pilot.app)
                evt = ui_events.memory_recalled(
                    title="prefer uv",
                    scope="user",
                    kind="feedback",
                )
                pilot.app._on_bus_memory_recalled(evt)
                await pilot.pause()

                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Recalled memory: prefer uv (user)" in combined

    @pytest.mark.asyncio
    async def test_status_bar_changed_updates_reactives(self):
        """A STATUS_BAR_CHANGED payload flows to the status bar reactives."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                _sync_passthrough(pilot.app)
                evt = ui_events.status_bar_changed(
                    task_label="running: charmcraft",
                    cos_health="● COS healthy",
                    test_summary="1/1",
                    watcher_status="watching",
                )
                pilot.app._on_bus_status_bar(evt)
                await pilot.pause()

                status_bar = pilot.app.query_one("#status-bar", statusbar_widget.StatusBar)
                assert status_bar.task_label == "running: charmcraft"
                assert status_bar.cos_health == "● COS healthy"
                assert status_bar.test_summary == "1/1"
                assert status_bar.watcher_status == "watching"

    @pytest.mark.asyncio
    async def test_task_updated_without_agent_is_noop(self):
        """With no agent the handler short-circuits before touching the UI."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                evt = ui_events.task_updated(
                    task_id="t1",
                    title="x",
                    status="pending",
                    category="build",
                )
                # Should not raise even with no agent, checklist, or thread.
                pilot.app._on_bus_task_updated(evt)
                await pilot.pause()

    @pytest.mark.asyncio
    async def test_task_updated_non_confirm_refreshes_checklist(self):
        """A simple TASK_UPDATED with a non-confirm task just refreshes state."""
        p1, p2, mock_agent = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                _sync_passthrough(pilot.app)
                evt = ui_events.task_updated(
                    task_id="t1",
                    title="Build",
                    status="pending",
                    category="build",
                )
                pilot.app._on_bus_task_updated(evt)
                await pilot.pause()
                # The handler should have polled the queue for tasks.
                mock_agent.work_queue.all_tasks.assert_called()


# ---------------------------------------------------------------------------
# Worker completion callbacks
# ---------------------------------------------------------------------------


class _Worker:
    """Minimal stand-in for a Textual Worker with name + result + error."""

    def __init__(
        self,
        name: str,
        state: WorkerState,
        result: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.state = state
        self.result = result
        self.error = error


class _WorkerEvent:
    """Stand-in for ``Worker.StateChanged`` without needing a real Worker."""

    def __init__(self, worker: _Worker, state: WorkerState) -> None:
        self.worker = worker
        self.state = state


class TestMcpMarketplaceDone:
    """Every branch of ``_on_mcp_marketplace_done``."""

    @pytest.mark.asyncio
    async def test_success_with_output_adds_system_message(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                worker = _Worker("mcp_marketplace", WorkerState.SUCCESS, result="hit")
                pilot.app._on_mcp_marketplace_done(_WorkerEvent(worker, WorkerState.SUCCESS))
                await pilot.pause()
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "hit" in combined

    @pytest.mark.asyncio
    async def test_cancelled_adds_cancel_message(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                worker = _Worker("mcp_marketplace", WorkerState.CANCELLED)
                pilot.app._on_mcp_marketplace_done(_WorkerEvent(worker, WorkerState.CANCELLED))
                await pilot.pause()
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Marketplace lookup cancelled." in combined

    @pytest.mark.asyncio
    async def test_error_adds_failure_message(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                worker = _Worker("mcp_marketplace", WorkerState.ERROR, error=RuntimeError("nope"))
                pilot.app._on_mcp_marketplace_done(_WorkerEvent(worker, WorkerState.ERROR))
                await pilot.pause()
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Marketplace lookup failed" in combined

    @pytest.mark.asyncio
    async def test_non_terminal_state_is_ignored(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                before = len(chat._messages)
                worker = _Worker("mcp_marketplace", WorkerState.RUNNING)
                pilot.app._on_mcp_marketplace_done(_WorkerEvent(worker, WorkerState.RUNNING))
                await pilot.pause()
                assert len(chat._messages) == before


class TestFeelingsDone:
    """Every branch of ``_on_feelings_done``."""

    @pytest.mark.asyncio
    async def test_success_posts_report(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                worker = _Worker("feelings", WorkerState.SUCCESS, result="parliament report")
                pilot.app._on_feelings_done(_WorkerEvent(worker, WorkerState.SUCCESS))
                await pilot.pause()
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "parliament report" in combined

    @pytest.mark.asyncio
    async def test_cancelled_adjourns(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                worker = _Worker("feelings", WorkerState.CANCELLED)
                pilot.app._on_feelings_done(_WorkerEvent(worker, WorkerState.CANCELLED))
                await pilot.pause()
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Parliament adjourned" in combined

    @pytest.mark.asyncio
    async def test_error_reports_failure(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                worker = _Worker("feelings", WorkerState.ERROR, error=ValueError("x"))
                pilot.app._on_feelings_done(_WorkerEvent(worker, WorkerState.ERROR))
                await pilot.pause()
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Parliament failed" in combined


# ---------------------------------------------------------------------------
# /feelings command dispatch
# ---------------------------------------------------------------------------


class TestFeelingsCommand:
    """``_handle_feelings_command`` branches: unknown token and dispatch."""

    @pytest.mark.asyncio
    async def test_unknown_emotion_shows_error(self):
        """Unknown tokens produce a 'Unknown emotion(s)' system message."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                pilot.app._handle_feelings_command("/feelings marmalade", chat)
                await pilot.pause()
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Unknown emotion" in combined

    @pytest.mark.asyncio
    async def test_known_emotions_start_worker(self):
        """Known emotions trigger a 'Convening…' message and a feelings worker."""
        from cantrip.agent.emotions import ParliamentResult

        p1, p2, mock_agent = _patch_app()
        mock_agent.run_parliament = AsyncMock(
            return_value=ParliamentResult(suggestions=[], failed_emotions=[])
        )
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                pilot.app._handle_feelings_command("/feelings", chat)
                await pilot.pause(delay=0.3)
                combined = " ".join(
                    m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM
                )
                assert "Convening the inner parliament" in combined


# ---------------------------------------------------------------------------
# Shared-slash-command dispatcher
# ---------------------------------------------------------------------------


class TestSharedSlashCommands:
    """Edge cases for the slash-command bridge."""

    @pytest.mark.asyncio
    async def test_without_agent_returns_false(self):
        """With ``self._agent is None`` the dispatcher is skipped."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                handled = pilot.app._handle_shared_slash_commands("/help", chat)
                assert handled is False

    @pytest.mark.asyncio
    async def test_dispatch_result_with_followup_spawns_worker(self):
        """A non-None SlashResult with followup starts an mcp_marketplace worker."""
        from cantrip.agent.slash_commands import SlashResult

        async def _followup() -> str:
            return "done"

        p1, p2, _ = _patch_app()
        with (
            p1,
            p2,
            patch(
                "cantrip.tui.app.slash_commands.dispatch",
                return_value=SlashResult(text="hi", followup=_followup),
            ),
        ):
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                handled = pilot.app._handle_shared_slash_commands("/mcp", chat)
                assert handled is True
                worker_names = {w.name for w in pilot.app.workers}
                assert "mcp_marketplace" in worker_names

    @pytest.mark.asyncio
    async def test_dispatch_quit_schedules_exit(self):
        """A SlashResult with quit=True schedules app.exit after refresh."""
        from cantrip.agent.slash_commands import SlashResult

        p1, p2, _ = _patch_app()
        with (
            p1,
            p2,
            patch(
                "cantrip.tui.app.slash_commands.dispatch",
                return_value=SlashResult(text="bye", quit=True),
            ),
        ):
            async with CantripApp().run_test() as pilot:
                exit_mock = MagicMock()
                pilot.app.exit = exit_mock  # type: ignore[method-assign]
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                pilot.app._handle_shared_slash_commands("/quit", chat)
                await pilot.pause()
                exit_mock.assert_called()


# ---------------------------------------------------------------------------
# F3 — logs action (complementary to the F3 test in test_tui.py)
# ---------------------------------------------------------------------------


class TestLogsAction:
    """``action_logs`` respects the current dev model."""

    @pytest.mark.asyncio
    async def test_logs_screen_uses_dev_model(self):
        """When a dev model is set it's threaded into the LogScreen."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.dev_model = "development"
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app.action_logs()
                await pilot.pause()
                assert isinstance(pilot.app.screen, LogScreen)

    @pytest.mark.asyncio
    async def test_logs_screen_receives_cos_model(self):
        """Both dev and COS models are threaded into the LogScreen."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.dev_model = "development"
        mock_agent.state.cos_model = "cos"
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app.action_logs()
                await pilot.pause()
                screen = pilot.app.screen
                assert isinstance(screen, LogScreen)
                assert screen._dev_model == "development"
                assert screen._cos_model == "cos"


class TestLogScreenModelCycling:
    """``m`` binding cycles between dev and COS when both are set."""

    def test_init_prefers_dev_over_cos(self):
        screen = LogScreen(dev_model="dev", cos_model="cos")
        assert screen._model == "dev"

    def test_init_falls_back_to_cos(self):
        screen = LogScreen(cos_model="cos")
        assert screen._model == "cos"

    def test_init_accepts_legacy_positional_model(self):
        """Legacy ``model=`` callers still work — maps to ``dev_model``."""
        screen = LogScreen(model="dev")
        assert screen._model == "dev"
        assert screen._dev_model == "dev"
        assert screen._cos_model is None

    def test_cycle_swaps_dev_to_cos(self):
        screen = LogScreen(dev_model="dev", cos_model="cos")
        with patch.object(screen, "_fetch_logs"), patch.object(screen, "_stop_stream"):
            screen.action_cycle_model()
        assert screen._model == "cos"

    def test_cycle_swaps_back_to_dev(self):
        screen = LogScreen(dev_model="dev", cos_model="cos")
        with patch.object(screen, "_fetch_logs"), patch.object(screen, "_stop_stream"):
            screen.action_cycle_model()
            screen.action_cycle_model()
        assert screen._model == "dev"

    def test_cycle_is_noop_with_only_dev(self):
        screen = LogScreen(dev_model="dev")
        with patch.object(screen, "_fetch_logs") as fetch:
            screen.action_cycle_model()
        fetch.assert_not_called()
        assert screen._model == "dev"

    def test_cycle_is_noop_with_only_cos(self):
        screen = LogScreen(cos_model="cos")
        with patch.object(screen, "_fetch_logs") as fetch:
            screen.action_cycle_model()
        fetch.assert_not_called()
        assert screen._model == "cos"


# ---------------------------------------------------------------------------
# Confirmation-prompt response handlers
# ---------------------------------------------------------------------------


def _system_messages(pilot) -> str:
    """Concatenated text of all system messages, for substring asserts."""
    chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
    return " ".join(m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM)


class TestBootstrapResponse:
    """Every branch of ``_handle_bootstrap_response``."""

    @pytest.mark.asyncio
    async def test_no_agent_returns_false(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                assert pilot.app._handle_bootstrap_response("yes") is False

    @pytest.mark.asyncio
    async def test_skip_branch(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_bootstrap = True
                assert pilot.app._handle_bootstrap_response("skip") is True
                assert pilot.app._pending_bootstrap is False
                assert "Repository creation skipped." in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_yes_branch_creates_private_repo(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.charm_name = "my-charm"
        mock_agent.state.github_repo = None
        mock_agent.handle_repo_bootstrap = MagicMock(return_value="Repo created.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_bootstrap = True
                ok = pilot.app._handle_bootstrap_response("yes org=canonical desc=Nice")
                assert ok is True
                mock_agent.handle_repo_bootstrap.assert_called_once()
                call_kwargs = mock_agent.handle_repo_bootstrap.call_args.kwargs
                assert call_kwargs["private"] is True
                assert call_kwargs["org"] == "canonical"
                assert call_kwargs["description"] == "Nice"

    @pytest.mark.asyncio
    async def test_public_variant_sets_private_false(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.charm_name = "my-charm"
        mock_agent.state.github_repo = None
        mock_agent.handle_repo_bootstrap = MagicMock(return_value="ok")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_bootstrap = True
                pilot.app._handle_bootstrap_response("public")
                assert mock_agent.handle_repo_bootstrap.call_args.kwargs["private"] is False

    @pytest.mark.asyncio
    async def test_unrelated_message_returns_false(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_bootstrap = True
                assert pilot.app._handle_bootstrap_response("maybe later") is False


class TestPushResponse:
    """Every branch of ``_handle_push_response``."""

    @pytest.mark.asyncio
    async def test_no_confirm_returns_false(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = None
                assert pilot.app._handle_push_response("push") is False

    @pytest.mark.asyncio
    async def test_approve_branch(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.work_queue.set_done = MagicMock()
        mock_agent.handle_push_confirmation = MagicMock(
            return_value="Pushed! Reply **pr** to create a PR."
        )
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "push-branch-feat"
                ok = pilot.app._handle_push_response("push")
                assert ok is True
                assert pilot.app._pending_pr_branch == "feat"
                assert pilot.app._pending_confirm_id is None

    @pytest.mark.asyncio
    async def test_skip_branch(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.work_queue.set_done = MagicMock()
        mock_agent.handle_push_confirmation = MagicMock(return_value="Left local.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "push-branch-feat"
                assert pilot.app._handle_push_response("skip") is True
                assert pilot.app._pending_confirm_id is None
                assert pilot.app._pending_pr_branch is None

    @pytest.mark.asyncio
    async def test_unrelated_message_returns_false(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "push-branch-feat"
                assert pilot.app._handle_push_response("nonsense") is False


class TestTriageResponse:
    """Every branch of ``_handle_triage_response``."""

    @pytest.mark.asyncio
    async def test_no_confirm_returns_false(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = None
                assert pilot.app._handle_triage_response("approve") is False

    @pytest.mark.asyncio
    async def test_approve_with_work_tasks(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.work_queue.set_done = MagicMock()
        task = MagicMock()
        task.title = "Fix login"
        mock_agent.handle_triage_confirmation = MagicMock(return_value=[task])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "triage-issue-42"
                assert pilot.app._handle_triage_response("approve") is True
                assert "Working on the issue" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_approve_with_no_work_tasks(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.work_queue.set_done = MagicMock()
        mock_agent.handle_triage_confirmation = MagicMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "triage-issue-42"
                assert pilot.app._handle_triage_response("approve") is True
                assert "Could not generate work tasks" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_skip_branch(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.work_queue.set_done = MagicMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "triage-issue-42"
                assert pilot.app._handle_triage_response("skip") is True
                assert "Issue skipped." in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_unrelated_returns_false(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "triage-issue-42"
                assert pilot.app._handle_triage_response("later") is False


class TestPresentConfirmations:
    """The tiny ``_present_*_confirmation`` helpers that format chat prompts."""

    @pytest.mark.asyncio
    async def test_present_push_confirmation(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                task = MagicMock()
                task.description = "Push branch 'feat' to origin?"
                pilot.app._present_push_confirmation(task)
                await pilot.pause()
                assert "Reply **push**" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_present_triage_confirmation(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                task = MagicMock()
                task.description = "Issue #7: Login broken"
                pilot.app._present_triage_confirmation(task)
                await pilot.pause()
                assert "Issue triage" in _system_messages(pilot)


# ---------------------------------------------------------------------------
# Watcher action + bus event
# ---------------------------------------------------------------------------


class TestWatcher:
    """``action_toggle_watcher`` and ``_on_bus_watcher_event``."""

    @pytest.mark.asyncio
    async def test_toggle_watcher_stops_when_running(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.watcher_running = True
        mock_agent.stop_watcher = AsyncMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app.action_toggle_watcher()
                await pilot.pause(delay=0.3)
                assert "Watcher stopped." in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_toggle_watcher_starts_when_stopped(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.watcher_running = False
        mock_agent.start_watcher = MagicMock(return_value=True)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app.action_toggle_watcher()
                await pilot.pause()
                mock_agent.start_watcher.assert_called()

    @pytest.mark.asyncio
    async def test_toggle_watcher_without_agent_is_noop(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                pilot.app.action_toggle_watcher()  # should not raise

    @pytest.mark.asyncio
    async def test_on_bus_watcher_event_writes_chat_line(self):
        p1, p2, mock_agent = _patch_app()
        # ``_refresh_model_panes`` checks the agent's private ``_watcher`` — set
        # it to None so the method short-circuits cleanly.
        mock_agent._watcher = None
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                _sync_passthrough(pilot.app)
                evt = ui_events.watcher_event(
                    source="juju",
                    category="state",
                    summary="unit app/0 is active",
                )
                pilot.app._on_bus_watcher_event(evt)
                await pilot.pause()
                assert "unit app/0 is active" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_refresh_subagent_status_bar_picks_active_task(self):
        from datetime import datetime

        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        p1, p2, mock_agent = _patch_app()
        task = AgentTask(
            id="t1",
            title="Investigate",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.ACTIVE,
            description="",
            created_at=datetime(2025, 1, 1),
        )
        task.subagent_phase = "analysing traces"
        mock_agent.work_queue.all_tasks = MagicMock(return_value=[task])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._refresh_subagent_status_bar()
                await pilot.pause()
                status_bar = pilot.app.query_one("#status-bar", statusbar_widget.StatusBar)
                assert "Investigate" in status_bar.subagent_label
                assert "analysing traces" in status_bar.subagent_label


# ---------------------------------------------------------------------------
# Chat search-closed + quit action with agent
# ---------------------------------------------------------------------------


class TestMiscHandlers:
    """Small handlers that round out branch coverage."""

    @pytest.mark.asyncio
    async def test_search_closed_refocuses_input(self):
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                event = chat_widget.ChatWidget.SearchClosed()
                pilot.app.on_chat_widget_search_closed(event)
                await pilot.pause()
                # Just needs to run without raising; the focus call is
                # protected with suppress(NoMatches).

    @pytest.mark.asyncio
    async def test_action_quit_stops_services(self):
        p1, p2, mock_agent = _patch_app()
        mock_agent.executor_running = True
        mock_agent.watcher_running = True
        mock_agent.issue_triage_running = True
        mock_agent.stop_executor = AsyncMock()
        mock_agent.stop_watcher = AsyncMock()
        mock_agent.stop_issue_triage = AsyncMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                exit_mock = MagicMock()
                pilot.app.exit = exit_mock  # type: ignore[method-assign]
                await pilot.app.action_quit()
                mock_agent.stop_executor.assert_awaited()
                mock_agent.stop_watcher.assert_awaited()
                mock_agent.stop_issue_triage.assert_awaited()
                exit_mock.assert_called()
