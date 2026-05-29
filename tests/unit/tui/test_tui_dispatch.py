"""Targeted Pilot tests for the bus / tree / input dispatch glue.

Phase 93.1 backfill for ``src/cantrip/tui/app.py``: ``_on_bus_task_updated``
routes CONFIRM tasks to one of six presenter methods based on the
task ID prefix; ``_handle_tree_command`` opens the session-tree
picker; the small bus handlers (``_on_bus_cache_metrics``, the mode
branch of ``_on_bus_status_bar``) and helpers
(``_present_bootstrap_confirmation``, the github-repo branch of
``_handle_bootstrap_response``, the ``on_input_changed`` NoMatches
guards) round out the remaining easily-coverable holes.
"""

from unittest.mock import MagicMock, patch

import pytest

from cantrip.agent.git.git_branch import BOOTSTRAP_CONFIRM_PREFIX, PUSH_CONFIRM_PREFIX
from cantrip.agent.github_issues import TRIAGE_CONFIRM_PREFIX
from cantrip.agent.planner import IMPROVEMENT_CONFIRM_BASE
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.race.race import RACE_CONFIRM_PREFIX
from cantrip.tui.app import CantripApp
from cantrip.tui.widgets import chat as chat_widget
from cantrip.tui.widgets import modelbar as modelbar_widget
from cantrip.tui.widgets import statusbar as statusbar_widget
from cantrip.ui import events as ui_events
from tests.unit.tui.test_tui import _patch_app

pytestmark = pytest.mark.tui


def _system_messages(pilot) -> str:
    chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
    return " ".join(m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM)


# ---------------------------------------------------------------------------
# _on_bus_task_updated CONFIRM dispatch
# ---------------------------------------------------------------------------


class TestBusConfirmDispatch:
    """``_on_bus_task_updated`` routes BLOCKED CONFIRM tasks to the right
    presenter helper based on the ID prefix.  The presenters themselves
    are tested in ``test_tui_confirmations``; this class verifies the
    routing decision and the surrounding state changes (``_pending_confirm_id``,
    checklist refresh)."""

    @staticmethod
    def _confirm_event(task_id: str) -> ui_events.Event:
        return ui_events.task_updated(
            task_id=task_id,
            title="confirm",
            status=TaskStatus.BLOCKED.value,
            category=TaskCategory.CONFIRM.value,
        )

    @pytest.mark.asyncio
    async def test_pending_confirm_blocks_redispatch(self) -> None:
        """If a CONFIRM is already pending, a fresh BLOCKED event is
        ignored — the user finishes one prompt at a time."""
        p1, p2, mock_agent = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "race-confirm-existing"
                pilot.app._on_bus_task_updated(self._confirm_event(f"{PUSH_CONFIRM_PREFIX}feat"))
                await pilot.pause()
                # Pending stays on the existing CONFIRM.
                assert pilot.app._pending_confirm_id == "race-confirm-existing"
                # The new task was never looked up.
                mock_agent.work_queue.get_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_task_short_circuits_after_setting_pending(self) -> None:
        """If the queue forgot the task, set pending and bail without
        invoking any presenter — the next BLOCKED event for the same
        task will retry once the queue catches up."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.work_queue.get_task = MagicMock(return_value=None)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(pilot.app, "_present_push_confirmation") as presenter:
                    pilot.app._on_bus_task_updated(
                        self._confirm_event(f"{PUSH_CONFIRM_PREFIX}feat")
                    )
                    await pilot.pause()
                    presenter.assert_not_called()
                # Pending was set before the lookup so the next event is a no-op.
                assert pilot.app._pending_confirm_id == f"{PUSH_CONFIRM_PREFIX}feat"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("task_id_prefix", "presenter_name"),
        [
            (PUSH_CONFIRM_PREFIX, "_present_push_confirmation"),
            (TRIAGE_CONFIRM_PREFIX, "_present_triage_confirmation"),
            (IMPROVEMENT_CONFIRM_BASE, "_present_improvement_confirmation"),
            (RACE_CONFIRM_PREFIX, "_present_race_confirmation"),
            (BOOTSTRAP_CONFIRM_PREFIX, "_present_bootstrap_confirmation"),
        ],
    )
    async def test_prefix_routes_to_named_presenter(
        self, task_id_prefix: str, presenter_name: str
    ) -> None:
        """Each known prefix must reach the matching presenter exactly once."""
        task_id = f"{task_id_prefix}xyz" if task_id_prefix.endswith("-") else task_id_prefix
        p1, p2, mock_agent = _patch_app()
        task = AgentTask(
            id=task_id,
            title="confirm",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
        )
        mock_agent.work_queue.get_task = MagicMock(return_value=task)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(pilot.app, presenter_name) as presenter:
                    pilot.app._on_bus_task_updated(self._confirm_event(task_id))
                    await pilot.pause()
                    presenter.assert_called_once_with(task)
                assert pilot.app._pending_confirm_id == task_id

    @pytest.mark.asyncio
    async def test_unknown_prefix_falls_back_to_design_questions(self) -> None:
        """An ID that matches none of the known CONFIRM prefixes falls
        through to the design-questions presenter — that's the original
        ``confirm-design-*`` flow before the other CONFIRMs grew up
        around it."""
        task_id = "confirm-design-abc"
        p1, p2, mock_agent = _patch_app()
        task = AgentTask(
            id=task_id,
            title="confirm",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
        )
        mock_agent.work_queue.get_task = MagicMock(return_value=task)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(pilot.app, "_present_design_questions") as presenter:
                    pilot.app._on_bus_task_updated(self._confirm_event(task_id))
                    await pilot.pause()
                    presenter.assert_called_once_with(task)


# ---------------------------------------------------------------------------
# _handle_tree_command
# ---------------------------------------------------------------------------


def _stub_store(*, messages: list[dict] | None = None) -> MagicMock:
    """Build a session-store mock whose metadata methods return real
    dicts/lists.

    ``CantripApp.on_mount`` calls ``_update_model_info`` which reaches
    into ``store.get_usage_since`` / ``get_total_usage`` /
    ``get_usage_by_model`` and assigns the integer fields straight onto
    ``ModelInfoBar`` reactives.  The plain ``MagicMock()`` returns
    nested mocks that fail the reactive int validators, so any test
    that swaps ``mock_agent.store`` for a real-ish stand-in must wire
    those methods first.
    """
    store = MagicMock()
    store.get_usage_since = MagicMock(
        return_value={"prompt_tokens": 0, "completion_tokens": 0, "request_count": 0}
    )
    store.get_total_usage = MagicMock(return_value={"prompt_tokens": 0, "completion_tokens": 0})
    store.get_usage_by_model = MagicMock(return_value=[])
    store.load_messages = MagicMock(return_value=messages or [])
    store.load_active_branch = MagicMock(return_value=[{"id": m["id"]} for m in (messages or [])])
    return store


class TestHandleTreeCommand:
    """Every branch of ``_handle_tree_command``."""

    @pytest.mark.asyncio
    async def test_no_store_writes_hint_message(self) -> None:
        """``/tree`` without a session store produces a hint, not a crash."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.store = None
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                pilot.app._handle_tree_command(chat)
                assert "needs a saved session" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_no_messages_writes_hint_message(self) -> None:
        """An empty session writes a 'no turns yet' hint instead of opening
        the modal with nothing to render."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.store = _stub_store()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                pilot.app._handle_tree_command(chat)
                assert "No turns yet" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_picker_pushed_when_messages_exist(self) -> None:
        """When messages exist the picker is handed to ``push_screen``
        with a callback.  Pushing the actual modal is patched out — the
        ``TreePickerScreen``'s own modal tests cover that path."""
        from cantrip.tui.screens.tree import TreePickerScreen

        p1, p2, mock_agent = _patch_app()
        messages = [{"id": 1, "parent_turn_id": None, "role": "user", "content": "hi"}]
        mock_agent.store = _stub_store(messages=messages)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                with patch.object(pilot.app, "push_screen") as pushed:
                    pilot.app._handle_tree_command(chat)
                pushed.assert_called_once()
                screen_arg, callback_arg = pushed.call_args.args
                assert isinstance(screen_arg, TreePickerScreen)
                assert callable(callback_arg)

    @pytest.mark.asyncio
    async def test_picker_callback_on_none_is_noop(self) -> None:
        """The captured callback no-ops on ``turn_id=None`` (Esc)."""
        p1, p2, mock_agent = _patch_app()
        messages = [{"id": 1, "parent_turn_id": None, "role": "user", "content": "hi"}]
        mock_agent.store = _stub_store(messages=messages)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                with patch.object(pilot.app, "push_screen") as pushed:
                    pilot.app._handle_tree_command(chat)
                _, callback = pushed.call_args.args
                with patch("cantrip.tui.app.slash_commands.handle_branch") as branched:
                    callback(None)
                    branched.assert_not_called()
                # Cancel must not write a system message.
                assert _system_messages(pilot).strip() == ""

    @pytest.mark.asyncio
    async def test_picker_callback_with_turn_id_records_branch(self) -> None:
        """The captured callback round-trips a turn id through
        ``slash_commands.handle_branch`` and writes the result."""
        p1, p2, mock_agent = _patch_app()
        messages = [
            {"id": 1, "parent_turn_id": None, "role": "user", "content": "hi"},
            {"id": 2, "parent_turn_id": 1, "role": "assistant", "content": "hello"},
        ]
        mock_agent.store = _stub_store(messages=messages)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                with patch.object(pilot.app, "push_screen") as pushed:
                    pilot.app._handle_tree_command(chat)
                _, callback = pushed.call_args.args
                with patch(
                    "cantrip.tui.app.slash_commands.handle_branch",
                    return_value="Switched to turn 2.",
                ) as branched:
                    callback(2)
                    branched.assert_called_once()
                    assert branched.call_args.args[1] == "2"
                assert "Switched to turn 2." in _system_messages(pilot)


# ---------------------------------------------------------------------------
# Bus handlers — cache metrics + status-bar mode
# ---------------------------------------------------------------------------


class TestBusCacheAndModeHandlers:
    """``_on_bus_cache_metrics`` mirrors the modelbar reactives, and the
    ``mode`` field on a STATUS_BAR_CHANGED payload feeds the read-only
    tint applied while ``/plan`` or ``/build`` is gating tools."""

    @pytest.mark.asyncio
    async def test_cache_metrics_updates_modelbar(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                evt = ui_events.cache_metrics_updated(
                    cache_creation_tokens=1_200,
                    cache_read_tokens=4_800,
                )
                pilot.app._on_bus_cache_metrics(evt)
                await pilot.pause()
                bar = pilot.app.query_one("#model-info", modelbar_widget.ModelInfoBar)
                assert bar.cache_creation_tokens == 1_200
                assert bar.cache_read_tokens == 4_800

    @pytest.mark.asyncio
    async def test_cache_metrics_swallows_missing_modelbar(self) -> None:
        """If the modelbar has been removed (e.g. tearing down a screen),
        the handler must swallow the lookup rather than crash the bus."""
        from textual.css.query import NoMatches

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                evt = ui_events.cache_metrics_updated(
                    cache_creation_tokens=10,
                    cache_read_tokens=20,
                )
                with patch.object(pilot.app, "query_one", side_effect=NoMatches("x")):
                    pilot.app._on_bus_cache_metrics(evt)  # must not raise

    @pytest.mark.asyncio
    async def test_status_bar_mode_field_applies(self) -> None:
        """A STATUS_BAR_CHANGED payload carrying ``mode`` lights up the
        status bar's mode reactive (Phase 68.4)."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                payload = {"mode": "plan"}
                evt = ui_events.Event(
                    type=ui_events.EventType.STATUS_BAR_CHANGED,
                    payload=payload,
                )
                pilot.app._on_bus_status_bar(evt)
                await pilot.pause()
                status_bar = pilot.app.query_one("#status-bar", statusbar_widget.StatusBar)
                assert status_bar.mode == "plan"

    @pytest.mark.asyncio
    async def test_status_bar_loop_state_applies(self) -> None:
        """``loop_state=paused`` lights up the bar's PAUSED badge (Phase 99.1)."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                evt = ui_events.Event(
                    type=ui_events.EventType.STATUS_BAR_CHANGED,
                    payload={"loop_state": "paused"},
                )
                pilot.app._on_bus_status_bar(evt)
                await pilot.pause()
                status_bar = pilot.app.query_one("#status-bar", statusbar_widget.StatusBar)
                assert status_bar.loop_state == "paused"


# ---------------------------------------------------------------------------
# Small remaining helpers
# ---------------------------------------------------------------------------


class TestPresentBootstrapConfirmation:
    """The two-line ``_present_bootstrap_confirmation`` chat write."""

    @pytest.mark.asyncio
    async def test_writes_repo_bootstrap_block(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                task = MagicMock()
                task.description = "Create my-charm-operator on GitHub?"
                pilot.app._present_bootstrap_confirmation(task)
                msgs = _system_messages(pilot)
                assert "Repo bootstrap" in msgs
                assert "Create my-charm-operator on GitHub?" in msgs


class TestBootstrapResponseGithubRepoUpdate:
    """The github-repo-success branch of ``_handle_bootstrap_response``.

    When ``handle_repo_bootstrap`` produces a repo and the agent now
    carries ``state.github_repo``, the handler refreshes the header
    subtitle and the model-info bar — that branch was the last
    uncovered fork in the bootstrap response.
    """

    @pytest.mark.asyncio
    async def test_successful_bootstrap_refreshes_subtitle_and_modelbar(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.charm_name = "my-charm"
        mock_agent.state.github_repo = "user/my-charm-operator"
        mock_agent.handle_repo_bootstrap = MagicMock(return_value="Repository created.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = f"{BOOTSTRAP_CONFIRM_PREFIX}my-charm-operator"
                with (
                    patch.object(pilot.app, "_update_header_subtitle") as upd_subtitle,
                    patch.object(pilot.app, "_update_model_info") as upd_model,
                ):
                    handled = pilot.app._handle_bootstrap_response("approve")
                    assert handled is True
                    upd_subtitle.assert_called_once()
                    upd_model.assert_called_once()


class TestOnInputChanged:
    """The two NoMatches guards in ``on_input_changed``.

    The chat input fires a ``Changed`` event for every keystroke; the
    slash and ``@``-mention popups may not be mounted in every layout
    (e.g. mid-modal).  Both ``query_one`` calls are wrapped in
    ``try/except NoMatches`` so a missing popup doesn't take down the
    keystroke path."""

    @staticmethod
    def _make_event(value: str = "ls", input_id: str = "chat-input"):
        from textual.widgets import Input

        event = MagicMock(spec=["input", "value"])
        inner = MagicMock(spec=Input)
        inner.id = input_id
        inner.cursor_position = len(value)
        event.input = inner
        event.value = value
        return event

    @pytest.mark.asyncio
    async def test_non_chat_input_short_circuits(self) -> None:
        """An input event from any other widget is ignored."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(pilot.app, "query_one") as q:
                    pilot.app.on_input_changed(self._make_event(input_id="other"))
                    q.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_slash_suggestions_swallows_lookup(self) -> None:
        """If the slash popup is missing the handler must return cleanly."""
        from textual.css.query import NoMatches

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(pilot.app, "query_one", side_effect=NoMatches("x")):
                    # No raise — the keystroke path is forgiving.
                    pilot.app.on_input_changed(self._make_event())

    @pytest.mark.asyncio
    async def test_missing_mention_suggestions_swallows_lookup(self) -> None:
        """The slash popup exists but the mention popup doesn't —
        common when the mention provider hasn't been mounted yet."""
        from textual.css.query import NoMatches

        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                slash = MagicMock()
                # First call resolves the slash popup, second raises NoMatches.
                with patch.object(
                    pilot.app,
                    "query_one",
                    side_effect=[slash, NoMatches("mention-suggestions")],
                ):
                    pilot.app.on_input_changed(self._make_event())
                slash.update_from_value.assert_called_once_with("ls")
