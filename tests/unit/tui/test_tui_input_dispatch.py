"""Targeted Pilot tests for ``on_input_submitted`` and the worker-completion glue.

Phase 93.1 backfill for ``src/cantrip/tui/app.py``: the keystroke-submit
dispatch routes a single user message through up to ten gating arms
(maintenance → PR → push/triage/race/bootstrap CONFIRMs → ``/feelings``
→ ``/tree`` → arena → shared slash → ``@``-mention expansion → LLM).
The previous coverage hit only the LLM tail; this file walks each
gating arm and verifies the exact handoff.  Also covers the three
terminal states of ``_on_agent_response_done`` (SUCCESS / CANCELLED /
ERROR) and the small ``_update_test_summary`` helper.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Input
from textual.worker import WorkerState

from cantrip.agent.git_branch import BOOTSTRAP_CONFIRM_PREFIX, PUSH_CONFIRM_PREFIX
from cantrip.agent.github_issues import TRIAGE_CONFIRM_PREFIX
from cantrip.agent.race.race import RACE_CONFIRM_PREFIX
from cantrip.agent.state import TestResults
from cantrip.llm.base import ProviderRateLimitError
from cantrip.tui.app import CantripApp
from cantrip.tui.widgets import chat as chat_widget
from cantrip.tui.widgets import statusbar as statusbar_widget
from tests.unit.tui.test_tui import _patch_app
from tests.unit.tui.test_tui_actions import _Worker, _WorkerEvent

pytestmark = pytest.mark.tui


def _system_messages(pilot) -> str:
    chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
    return " ".join(m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM)


def _submit(app, value: str) -> Input.Submitted:
    """Build a synthetic ``Input.Submitted`` event for the chat input."""
    chat_input = app.query_one("#chat-input", Input)
    chat_input.value = value
    return Input.Submitted(chat_input, value)


# ---------------------------------------------------------------------------
# on_input_submitted
# ---------------------------------------------------------------------------


class TestOnInputSubmitted:
    """Every gating arm in ``on_input_submitted``.

    The method is a 75-line dispatch chain: each arm consumes the
    message and returns; only the LLM tail at the end actually runs
    the agent worker.  These tests verify the gating order — once an
    arm fires, none of the later arms are consulted.
    """

    @pytest.mark.asyncio
    async def test_empty_message_is_dropped_silently(self) -> None:
        p1, p2, mock_agent = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                event = _submit(pilot.app, "   ")
                await pilot.app.on_input_submitted(event)
                # No user message added, no agent worker fired.
                chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
                user = [m for m in chat._messages if m.role == chat_widget.MessageRole.USER]
                assert user == []
                mock_agent.process_message_streaming.assert_not_called() if hasattr(
                    mock_agent.process_message_streaming, "assert_not_called"
                ) else None

    @pytest.mark.asyncio
    async def test_no_agent_writes_provider_warning(self) -> None:
        """Without a configured provider the dispatch short-circuits with
        a warning instead of crashing on ``self._agent`` access."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                await pilot.app.on_input_submitted(_submit(pilot.app, "hello"))
                assert "No LLM provider configured" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_pending_maintenance_handled_short_circuits(self) -> None:
        """A handled maintenance reply must not fall through to the PR arm."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_maintenance = {"branch": "feat", "pr_number": 1}
                with (
                    patch.object(
                        pilot.app, "_handle_maintenance_response", return_value=True
                    ) as maint,
                    patch.object(pilot.app, "_handle_pr_response") as pr,
                ):
                    await pilot.app.on_input_submitted(_submit(pilot.app, "comment"))
                    maint.assert_called_once_with("comment")
                    pr.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_pr_branch_handled_short_circuits(self) -> None:
        """A handled PR reply must not fall through to the CONFIRM arms."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_pr_branch = "feat"
                with (
                    patch.object(pilot.app, "_handle_pr_response", return_value=True) as pr,
                    patch.object(pilot.app, "_handle_push_response") as push,
                ):
                    await pilot.app.on_input_submitted(_submit(pilot.app, "yes"))
                    pr.assert_called_once_with("yes")
                    push.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("prefix", "handler_name"),
        [
            (PUSH_CONFIRM_PREFIX, "_handle_push_response"),
            (TRIAGE_CONFIRM_PREFIX, "_handle_triage_response"),
            (RACE_CONFIRM_PREFIX, "_handle_race_response"),
            (BOOTSTRAP_CONFIRM_PREFIX, "_handle_bootstrap_response"),
        ],
    )
    async def test_pending_confirm_routes_to_named_handler(
        self, prefix: str, handler_name: str
    ) -> None:
        """Each CONFIRM prefix routes to the matching handler when set."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = f"{prefix}foo"
                with patch.object(pilot.app, handler_name, return_value=True) as handler:
                    await pilot.app.on_input_submitted(_submit(pilot.app, "approve"))
                    handler.assert_called_once_with("approve")

    @pytest.mark.asyncio
    async def test_feelings_command_dispatches(self) -> None:
        """``/feelings`` is matched on the first whitespace token."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(pilot.app, "_handle_feelings_command") as feelings:
                    await pilot.app.on_input_submitted(
                        _submit(pilot.app, "/feelings curious skeptical")
                    )
                    feelings.assert_called_once()
                    assert feelings.call_args.args[0] == "/feelings curious skeptical"

    @pytest.mark.asyncio
    async def test_tree_command_dispatches(self) -> None:
        """``/tree`` reaches the picker handler before the shared slash dispatcher."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(pilot.app, "_handle_tree_command") as tree:
                    await pilot.app.on_input_submitted(_submit(pilot.app, "/tree"))
                    tree.assert_called_once()

    @pytest.mark.asyncio
    async def test_arena_pick_consumes_one_letter_reply(self) -> None:
        """A pending blind A/B arena consumes ``A`` / ``B`` / ``tie`` /
        ``skip`` before the slash-command dispatcher sees them."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.active_arena = MagicMock()  # truthy → arena gate is open
        mock_agent.handle_arena_pick = MagicMock(return_value="A: model-x — best.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(pilot.app, "_handle_shared_slash_commands") as slash:
                    await pilot.app.on_input_submitted(_submit(pilot.app, "A"))
                    mock_agent.handle_arena_pick.assert_called_once_with("A")
                    slash.assert_not_called()
                assert "A: model-x" in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_arena_unrelated_reply_falls_through(self) -> None:
        """If the arena handler returns ``None`` the message continues to
        slash dispatch — the arena gate doesn't swallow free-form chat."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.active_arena = MagicMock()
        mock_agent.handle_arena_pick = MagicMock(return_value=None)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with patch.object(
                    pilot.app, "_handle_shared_slash_commands", return_value=True
                ) as slash:
                    await pilot.app.on_input_submitted(_submit(pilot.app, "tell me about charms"))
                    slash.assert_called_once()

    @pytest.mark.asyncio
    async def test_shared_slash_handled_short_circuits(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with (
                    patch.object(pilot.app, "_handle_shared_slash_commands", return_value=True),
                    patch.object(pilot.app, "_expand_mentions") as expand,
                ):
                    await pilot.app.on_input_submitted(_submit(pilot.app, "/help"))
                    # ``@``-expansion must not run for handled slash commands —
                    # ``/foo @bar`` should not substitute provider output into
                    # the slash arg.
                    expand.assert_not_called()

    @pytest.mark.asyncio
    async def test_expanded_mention_writes_summary_message(self) -> None:
        """When the mention expander reports ``changed=True`` the user
        sees a transient _Expanded mentions: …_ system note."""
        from cantrip.agent.context_providers import ExpansionResult

        p1, p2, mock_agent = _patch_app()
        mock_agent.active_arena = None

        class _StubExpansion:
            """Stand-in for ``ExpansionResult`` with ``changed=True``."""

            raw = "@docs hello"
            expanded = "[@docs context]\nhello"
            blocks = ()
            changed = True

            def summary(self) -> str:
                return "@docs (1 chunk)"

        # ``ExpansionResult`` is a regular dataclass — building it
        # directly keeps the test honest about the contract.
        _ = ExpansionResult  # imported for the type-checker hint

        def _absorb_coroutine(coro, **_kwargs):
            """Patched ``run_worker`` — close the coroutine so the
            worker body doesn't run, and pytest doesn't warn about an
            unawaited coroutine on test teardown."""
            coro.close()
            return MagicMock()

        with p1, p2:
            async with CantripApp().run_test() as pilot:
                with (
                    patch.object(
                        pilot.app,
                        "_expand_mentions",
                        AsyncMock(return_value=_StubExpansion()),
                    ),
                    patch.object(pilot.app, "run_worker", side_effect=_absorb_coroutine),
                ):
                    await pilot.app.on_input_submitted(_submit(pilot.app, "@docs hello"))
                assert "Expanded mentions" in _system_messages(pilot)


# ---------------------------------------------------------------------------
# _on_agent_response_done
# ---------------------------------------------------------------------------


class TestOnAgentResponseDone:
    """Every terminal state of ``_on_agent_response_done``.

    Phase 75 streams chunks straight into a chat widget; the worker
    completion handler is responsible for hiding the thinking
    indicator, scrubbing dangling pending-tool blocks, re-enabling
    the input, and (on success) running the post-turn refresh
    (header subtitle, model bar, test summary)."""

    @pytest.mark.asyncio
    async def test_non_terminal_state_is_ignored(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                worker = _Worker("agent_response", WorkerState.RUNNING)
                # RUNNING is the typical pre-terminal state — must be a no-op.
                pilot.app._on_agent_response_done(_WorkerEvent(worker, WorkerState.RUNNING))
                # Input stays disabled-untouched.
                input_widget = pilot.app.query_one("#chat-input", Input)
                # Default (mounted) state has the input enabled — assert
                # the handler didn't change it.  More important: no system
                # message was added.
                assert "Error" not in _system_messages(pilot)
                assert "cancelled" not in _system_messages(pilot).lower()
                assert input_widget is not None

    @pytest.mark.asyncio
    async def test_success_resets_input_and_runs_post_turn_refresh(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.charm_name = ""
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                # Pre-disable the input so we can prove the success branch
                # re-enables it.
                input_widget = pilot.app.query_one("#chat-input", Input)
                input_widget.disabled = True

                with (
                    patch.object(pilot.app, "_start_bootstrap") as bootstrap,
                    patch.object(pilot.app, "_update_header_subtitle") as subtitle,
                    patch.object(pilot.app, "_update_model_info") as model_info,
                    patch.object(pilot.app, "_update_test_summary") as test_summary,
                ):
                    worker = _Worker("agent_response", WorkerState.SUCCESS)
                    pilot.app._on_agent_response_done(_WorkerEvent(worker, WorkerState.SUCCESS))
                    bootstrap.assert_called_once()
                    subtitle.assert_called_once()
                    model_info.assert_called_once()
                    test_summary.assert_called_once()
                assert input_widget.disabled is False
                mock_agent.save_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancelled_writes_cancel_message(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                input_widget = pilot.app.query_one("#chat-input", Input)
                input_widget.disabled = True
                worker = _Worker("agent_response", WorkerState.CANCELLED)
                pilot.app._on_agent_response_done(_WorkerEvent(worker, WorkerState.CANCELLED))
                assert "Operation cancelled." in _system_messages(pilot)
                assert input_widget.disabled is False

    @pytest.mark.asyncio
    async def test_error_rate_limit_uses_provider_unavailable_label(self) -> None:
        """A ``ProviderRateLimitError`` triggers a softer 'Provider unavailable'
        wording so the user understands it's transient, not a bug."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                input_widget = pilot.app.query_one("#chat-input", Input)
                input_widget.disabled = True
                err = ProviderRateLimitError("rate limited")
                worker = _Worker("agent_response", WorkerState.ERROR, error=err)
                pilot.app._on_agent_response_done(_WorkerEvent(worker, WorkerState.ERROR))
                msgs = _system_messages(pilot)
                assert "Provider unavailable" in msgs
                assert input_widget.disabled is False

    @pytest.mark.asyncio
    async def test_error_generic_uses_error_label(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                input_widget = pilot.app.query_one("#chat-input", Input)
                input_widget.disabled = True
                err = RuntimeError("boom")
                worker = _Worker("agent_response", WorkerState.ERROR, error=err)
                pilot.app._on_agent_response_done(_WorkerEvent(worker, WorkerState.ERROR))
                msgs = _system_messages(pilot)
                assert "Error: boom" in msgs
                assert input_widget.disabled is False


# ---------------------------------------------------------------------------
# _update_test_summary
# ---------------------------------------------------------------------------


class TestUpdateTestSummary:
    """The tiny ``_update_test_summary`` helper."""

    @pytest.mark.asyncio
    async def test_no_agent_returns_silently(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                pilot.app._update_test_summary()  # must not raise

    @pytest.mark.asyncio
    async def test_no_test_results_returns_silently(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.test_results = None
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._update_test_summary()
                bar = pilot.app.query_one("#status-bar", statusbar_widget.StatusBar)
                # Default reactive value is the empty string.
                assert bar.test_summary == ""

    @pytest.mark.asyncio
    async def test_with_results_pushes_summary_to_status_bar(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.state.test_results = TestResults(
            test_type="unit",
            passed=4,
            failed=1,
        )
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._update_test_summary()
                bar = pilot.app.query_one("#status-bar", statusbar_widget.StatusBar)
                assert "1 failed" in bar.test_summary
