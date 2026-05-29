"""Targeted Pilot tests for the design / race / improvement CONFIRM flows.

Phase 93.1 backfill for ``src/cantrip/tui/app.py``: the design-questions
modal flow, the race-cost approve/decline prompt, and the improvement-
audit auto-approve flow were the largest remaining uncovered cluster
in the TUI app module.  The methods are pure dispatch — they read
pending state, call into the agent, and write system messages — so
they exercise cleanly through the headless Textual test harness.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from cantrip.agent.design import DesignQuestion
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.race.race import RACE_CONFIRM_PREFIX
from cantrip.tui.app import CantripApp
from cantrip.tui.screens import questions as questions_screen
from cantrip.tui.widgets import chat as chat_widget
from tests.unit.tui.test_tui import _patch_app

pytestmark = pytest.mark.tui


def _system_messages(pilot) -> str:
    chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
    return " ".join(m.content for m in chat._messages if m.role == chat_widget.MessageRole.SYSTEM)


def _user_messages(pilot) -> str:
    chat = pilot.app.query_one("#chat", chat_widget.ChatWidget)
    return " ".join(m.content for m in chat._messages if m.role == chat_widget.MessageRole.USER)


async def _wait_for_named_worker(pilot, name: str) -> None:
    """Wait for the worker registered under *name* to finish.

    ``pilot.app.workers.wait_for_complete()`` also waits on Textual's
    own ``_loader`` worker, which gets cancelled when the test exits —
    that turns into a spurious ``WorkerCancelled`` failure.  Filtering
    by name keeps the wait scoped to the worker the test actually cares
    about.
    """
    targets = [w for w in pilot.app.workers if w.name == name]
    if targets:
        await pilot.app.workers.wait_for_complete(targets)


# ---------------------------------------------------------------------------
# Design questions flow
# ---------------------------------------------------------------------------


class TestPresentDesignQuestions:
    """Every branch of ``_present_design_questions``."""

    @staticmethod
    def _confirm_task() -> AgentTask:
        return AgentTask(
            id="confirm-design",
            title="Confirm design",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            description="",
            dependencies=["synth"],
        )

    @pytest.mark.asyncio
    async def test_no_agent_returns(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                # Must not raise even though dependencies are missing.
                pilot.app._present_design_questions(self._confirm_task())

    @pytest.mark.asyncio
    async def test_no_design_text_clears_pending_confirm(self) -> None:
        """If the dependency chain has no result, fall back to the LLM
        path and clear ``_pending_confirm_id`` so the next user reply
        isn't misrouted."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.work_queue.get_task = MagicMock(return_value=None)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "confirm-design"
                pilot.app._present_design_questions(self._confirm_task())
                assert pilot.app._pending_confirm_id is None

    @pytest.mark.asyncio
    async def test_design_without_questions_clears_pending(self) -> None:
        """Plain design text with no Questions section is left to the LLM."""
        p1, p2, mock_agent = _patch_app()
        synth = AgentTask(
            id="synth",
            title="Synthesis",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            description="",
            result="# My Workload\n\n## Substrate\n\nk8s\n",
        )
        mock_agent.work_queue.get_task = MagicMock(return_value=synth)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "confirm-design"
                pilot.app._present_design_questions(self._confirm_task())
                assert pilot.app._pending_confirm_id is None

    @pytest.mark.asyncio
    async def test_questions_push_modal_screen(self) -> None:
        """A design with structured questions pushes the questions modal
        and writes the design summary into chat."""
        p1, p2, mock_agent = _patch_app()
        synth = AgentTask(
            id="synth",
            title="Synthesis",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            description="",
            result=(
                "# Wonder Workload\n\n"
                "## Substrate\n\nk8s\n\n"
                "## Questions\n\n"
                "- **scaling**: How many replicas?\n"
                "  - one\n"
                "  - three\n"
                "- **observability**: Wire COS?\n"
                "  - yes\n"
                "  - later\n"
            ),
        )
        mock_agent.work_queue.get_task = MagicMock(return_value=synth)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "confirm-design"
                pilot.app._present_design_questions(self._confirm_task())
                # Pending stays set until the modal callback resolves it.
                assert pilot.app._pending_confirm_id == "confirm-design"
                # Modal needs a pause to finish mounting after push_screen.
                await pilot.pause()
                assert isinstance(
                    pilot.app.screen,
                    questions_screen.DesignQuestionsScreen,
                )
                # Design summary made it into chat.
                msgs = _system_messages(pilot)
                assert "Wonder Workload" in msgs
                # Pop the modal so the test exits cleanly.
                await pilot.app.pop_screen()


class TestOnQuestionsAnswered:
    """Every branch of ``_on_questions_answered``."""

    @pytest.mark.asyncio
    async def test_no_agent_is_noop(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                pilot.app._pending_confirm_id = "confirm-design"
                pilot.app._on_questions_answered([DesignQuestion(key="k", text="t", answer="a")])
                # Nothing crashes; the no-agent branch clears pending too.
                assert pilot.app._pending_confirm_id is None

    @pytest.mark.asyncio
    async def test_no_pending_confirm_is_noop(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_design_confirmation = AsyncMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = None
                pilot.app._on_questions_answered([])
                # No worker is launched without a pending confirm.
                mock_agent.handle_design_confirmation.assert_not_called()

    @pytest.mark.asyncio
    async def test_answered_questions_build_overrides_and_kick_worker(self) -> None:
        """Answered questions are echoed into chat and threaded into the
        confirmation worker as a structured ``overrides`` string."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_design_confirmation = AsyncMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "confirm-design"
                answered = [
                    DesignQuestion(key="scaling", text="?", answer="three"),
                    DesignQuestion(key="cos", text="?", answer="yes"),
                    # Unanswered question is filtered out.
                    DesignQuestion(key="other", text="?", answer=None),
                ]
                pilot.app._on_questions_answered(answered)
                # Worker is launched in the background — wait for it.
                await _wait_for_named_worker(pilot, "design_confirmation")
                # The answers and the system follow-up both made it to chat.
                user_text = _user_messages(pilot)
                assert "scaling" in user_text and "three" in user_text
                assert "cos" in user_text and "yes" in user_text
                assert "Design approved" in _system_messages(pilot)
                # Overrides string preserves both answered keys.
                _, kwargs = mock_agent.handle_design_confirmation.call_args
                assert "scaling" in kwargs["overrides"]
                assert "cos" in kwargs["overrides"]
                assert "other" not in kwargs["overrides"]
                # Pending confirm has been cleared by the time we return.
                assert pilot.app._pending_confirm_id is None

    @pytest.mark.asyncio
    async def test_no_answers_passes_none_overrides(self) -> None:
        """Empty / ``None`` answer lists collapse to ``overrides=None`` —
        the worker still runs so the confirm task can be approved."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_design_confirmation = AsyncMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "confirm-design"
                pilot.app._on_questions_answered(None)
                await _wait_for_named_worker(pilot, "design_confirmation")
                _, kwargs = mock_agent.handle_design_confirmation.call_args
                assert kwargs["overrides"] is None


class TestCompleteDesignConfirmation:
    """Every branch of ``_complete_design_confirmation``."""

    @pytest.mark.asyncio
    async def test_no_agent_is_noop(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                # Direct ``await`` keeps this off the worker thread so the
                # no-agent branch is exercised deterministically.
                await pilot.app._complete_design_confirmation("confirm-design", None)

    @pytest.mark.asyncio
    async def test_build_tasks_render_titles_in_chat(self) -> None:
        p1, p2, mock_agent = _patch_app()
        build_tasks = [
            AgentTask(
                id="b1",
                title="Scaffold charm skeleton",
                category=TaskCategory.BUILD,
            ),
            AgentTask(
                id="b2",
                title="Wire ops-tracing",
                category=TaskCategory.BUILD,
            ),
        ]
        mock_agent.handle_design_confirmation = AsyncMock(return_value=build_tasks)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.app._complete_design_confirmation("confirm-design", "x")
                msgs = _system_messages(pilot)
                assert "Build plan created" in msgs
                assert "Scaffold charm skeleton" in msgs
                assert "Wire ops-tracing" in msgs
                mock_agent.work_queue.set_done.assert_called_with(
                    "confirm-design", "Approved by user"
                )

    @pytest.mark.asyncio
    async def test_no_build_tasks_reports_failure(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_design_confirmation = AsyncMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                await pilot.app._complete_design_confirmation("confirm-design", None)
                assert "No build tasks generated" in _system_messages(pilot)


# ---------------------------------------------------------------------------
# Race confirmation flow
# ---------------------------------------------------------------------------


class TestPresentRaceConfirmation:
    """Every branch of ``_present_race_confirmation``."""

    @pytest.mark.asyncio
    async def test_no_agent_returns(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                task = MagicMock()
                task.description = "Run a 3-way race for $0.42?"
                # Must not raise even with no agent attached.
                pilot.app._present_race_confirmation(task)
                assert "Run a 3-way race" not in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_writes_description_into_chat(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                task = MagicMock()
                task.description = "Run a 3-way race for $0.42?"
                pilot.app._present_race_confirmation(task)
                assert "Run a 3-way race for $0.42?" in _system_messages(pilot)


class TestHandleRaceResponse:
    """Every branch of ``_handle_race_response``."""

    _RACE_ID = f"{RACE_CONFIRM_PREFIX}t1"

    @pytest.mark.asyncio
    async def test_no_pending_confirm_returns_false(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = None
                assert pilot.app._handle_race_response("yes") is False

    @pytest.mark.asyncio
    async def test_wrong_prefix_returns_false(self) -> None:
        """A pending CONFIRM that isn't a race must pass straight through."""
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "push-branch-foo"
                assert pilot.app._handle_race_response("yes") is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token", ["yes", "y", "approve", "race", "ok", "  YES  "])
    async def test_approve_tokens_call_handler(self, token: str) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_race_confirmation = MagicMock(return_value="Race armed.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = self._RACE_ID
                assert pilot.app._handle_race_response(token) is True
                mock_agent.handle_race_confirmation.assert_called_once_with(
                    self._RACE_ID, approved=True
                )
                assert pilot.app._pending_confirm_id is None
                assert "Race armed." in _system_messages(pilot)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token", ["no", "n", "decline", "single", "skip"])
    async def test_decline_tokens_call_handler(self, token: str) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_race_confirmation = MagicMock(return_value="Race declined.")
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = self._RACE_ID
                assert pilot.app._handle_race_response(token) is True
                mock_agent.handle_race_confirmation.assert_called_once_with(
                    self._RACE_ID, approved=False
                )
                assert pilot.app._pending_confirm_id is None
                assert "Race declined." in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_unrelated_message_returns_false_and_keeps_pending(self) -> None:
        """Anything that isn't yes/no should fall through so the user can
        ask the LLM clarifying questions; the pending CONFIRM stays."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_race_confirmation = MagicMock()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = self._RACE_ID
                assert pilot.app._handle_race_response("how much will it cost") is False
                mock_agent.handle_race_confirmation.assert_not_called()
                assert pilot.app._pending_confirm_id == self._RACE_ID


# ---------------------------------------------------------------------------
# Improvement confirmation flow
# ---------------------------------------------------------------------------


class TestPresentImprovementConfirmation:
    """Every branch of ``_present_improvement_confirmation``."""

    @staticmethod
    def _confirm_task() -> AgentTask:
        return AgentTask(
            id="confirm-improvements",
            title="Confirm improvements",
            category=TaskCategory.CONFIRM,
            status=TaskStatus.BLOCKED,
            description="",
            dependencies=["audit"],
        )

    @pytest.mark.asyncio
    async def test_no_agent_returns(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                pilot.app._present_improvement_confirmation(self._confirm_task())
                assert _system_messages(pilot).strip() == ""

    @pytest.mark.asyncio
    async def test_short_audit_report_renders_inline(self) -> None:
        p1, p2, mock_agent = _patch_app()
        audit_task = AgentTask(
            id="audit",
            title="Audit charm",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            description="",
            result="Missing ops-tracing integration.",
        )
        mock_agent.work_queue.get_task = MagicMock(return_value=audit_task)
        mock_agent.handle_improvement_confirmation = AsyncMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._present_improvement_confirmation(self._confirm_task())
                await _wait_for_named_worker(pilot, "improvement_confirmation")
                msgs = _system_messages(pilot)
                assert "Audit complete" in msgs
                assert "Missing ops-tracing integration." in msgs
                assert "truncated" not in msgs
                assert "Approving all improvements" in msgs

    @pytest.mark.asyncio
    async def test_long_audit_report_is_truncated(self) -> None:
        """Audit reports over 2000 chars get clipped with a ``truncated`` hint."""
        p1, p2, mock_agent = _patch_app()
        long_body = "Gap: configure-relations. " * 200  # ~5000 chars
        audit_task = AgentTask(
            id="audit",
            title="Audit charm",
            category=TaskCategory.RESEARCH,
            status=TaskStatus.DONE,
            description="",
            result=long_body,
        )
        mock_agent.work_queue.get_task = MagicMock(return_value=audit_task)
        mock_agent.handle_improvement_confirmation = AsyncMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._present_improvement_confirmation(self._confirm_task())
                await _wait_for_named_worker(pilot, "improvement_confirmation")
                msgs = _system_messages(pilot)
                assert "truncated" in msgs

    @pytest.mark.asyncio
    async def test_no_audit_report_skips_audit_block(self) -> None:
        """If no dependency carries a result, the audit-preview block is
        skipped but the auto-approve still runs."""
        p1, p2, mock_agent = _patch_app()
        mock_agent.work_queue.get_task = MagicMock(return_value=None)
        mock_agent.handle_improvement_confirmation = AsyncMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._present_improvement_confirmation(self._confirm_task())
                await _wait_for_named_worker(pilot, "improvement_confirmation")
                msgs = _system_messages(pilot)
                assert "Audit complete" not in msgs
                assert "Approving all improvements" in msgs


class TestPresentNoAgentBranches:
    """No-agent guard branches on the small presenter helpers.

    ``_present_push_confirmation``, ``_present_triage_confirmation``,
    and ``_present_next_pending_triage`` each open with ``if not
    self._agent: return``.  The covering tests in ``test_tui_actions``
    drive the happy path; these cover the noop path so an accidental
    drop of the guard doesn't sneak through.
    """

    @pytest.mark.asyncio
    async def test_present_push_confirmation_no_agent(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                task = MagicMock()
                task.description = "Push branch?"
                pilot.app._present_push_confirmation(task)
                assert "Push branch?" not in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_present_triage_confirmation_no_agent(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                task = MagicMock()
                task.description = "Issue body"
                pilot.app._present_triage_confirmation(task)
                assert "Issue triage" not in _system_messages(pilot)

    @pytest.mark.asyncio
    async def test_present_next_pending_triage_no_agent(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                # Must not raise even though the queue is unreachable.
                pilot.app._present_next_pending_triage()


class TestCompleteImprovementConfirmation:
    """Every branch of ``_complete_improvement_confirmation``."""

    @pytest.mark.asyncio
    async def test_no_agent_is_noop(self) -> None:
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._agent = None
                await pilot.app._complete_improvement_confirmation("confirm-improvements")

    @pytest.mark.asyncio
    async def test_fix_tasks_render_titles_in_chat(self) -> None:
        p1, p2, mock_agent = _patch_app()
        fix_tasks = [
            AgentTask(
                id="f1",
                title="Add ops-tracing endpoint",
                category=TaskCategory.BUILD,
            ),
            AgentTask(
                id="f2",
                title="Wire COS dashboard",
                category=TaskCategory.BUILD,
            ),
        ]
        mock_agent.handle_improvement_confirmation = AsyncMock(return_value=fix_tasks)
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "confirm-improvements"
                await pilot.app._complete_improvement_confirmation("confirm-improvements")
                msgs = _system_messages(pilot)
                assert "Improvement plan created" in msgs
                assert "Add ops-tracing endpoint" in msgs
                assert "Wire COS dashboard" in msgs
                mock_agent.work_queue.set_done.assert_called_with(
                    "confirm-improvements", "Approved by user"
                )
                assert pilot.app._pending_confirm_id is None

    @pytest.mark.asyncio
    async def test_no_fix_tasks_reports_already_clean(self) -> None:
        p1, p2, mock_agent = _patch_app()
        mock_agent.handle_improvement_confirmation = AsyncMock(return_value=[])
        with p1, p2:
            async with CantripApp().run_test() as pilot:
                pilot.app._pending_confirm_id = "confirm-improvements"
                await pilot.app._complete_improvement_confirmation("confirm-improvements")
                assert "may already be up to standard" in _system_messages(pilot)
