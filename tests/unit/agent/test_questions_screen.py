"""Tests for the DesignQuestionsScreen.

Constructor and pure-logic tests use plain instantiation; full
interaction tests drive the screen through ``App.run_test`` / ``Pilot``
so ``_show_question`` and the button / input handlers are exercised.
"""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static

from cantrip.agent.design import DesignQuestion
from cantrip.tui.screens.questions import DesignQuestionsScreen

pytestmark = pytest.mark.tui


class _Host(App):
    """Minimal host for pushing a DesignQuestionsScreen."""

    def compose(self) -> ComposeResult:  # pragma: no cover - trivial
        yield from ()


def _make_questions() -> list[DesignQuestion]:
    """Build a two-question fixture with suggestion buttons on Q1."""
    return [
        DesignQuestion(
            key="DB",
            text="Which database?",
            suggestions=["PostgreSQL", "MySQL"],
        ),
        DesignQuestion(key="Port", text="Which port?"),
    ]


class TestDesignQuestionsScreenInit:
    """Tests for the DesignQuestionsScreen modal construction."""

    def test_screen_initialises_with_questions(self) -> None:
        """Screen stores the questions and starts at index 0."""
        questions = _make_questions()
        screen = DesignQuestionsScreen(questions)
        assert screen._questions is questions
        assert screen._current_idx == 0


class TestDesignQuestionsScreenPilot:
    """Pilot tests that drive the screen through mount + interactions."""

    @pytest.mark.asyncio
    async def test_mount_shows_first_question(self) -> None:
        """On mount, Q1 is rendered with progress indicator and suggestions."""
        async with _Host().run_test() as pilot:
            screen = DesignQuestionsScreen(_make_questions())
            await pilot.app.push_screen(screen)
            await pilot.pause()

            progress = screen.query_one("#question-progress", Static).render()
            text = screen.query_one("#question-text", Static).render()
            assert "Question 1 of 2" in str(progress)
            assert "Which database?" in str(text)

            # Both suggestions rendered as buttons.
            buttons = screen.query(".suggestion-btn")
            assert len(buttons) == 2

            # Previous is hidden on Q1.
            prev_btn = screen.query_one("#prev-btn", Button)
            assert prev_btn.display is False

    @pytest.mark.asyncio
    async def test_clicking_suggestion_answers_and_advances(self) -> None:
        """Pressing a suggestion button stores the label as the answer."""
        questions = _make_questions()
        async with _Host().run_test() as pilot:
            screen = DesignQuestionsScreen(questions)
            await pilot.app.push_screen(screen)
            await pilot.pause()

            btn = screen.query_one("#suggestion-0", Button)
            btn.press()
            await pilot.pause()

            assert questions[0].answer == "PostgreSQL"
            assert screen._current_idx == 1

            # Q2 has no suggestions, so the buttons are gone.
            buttons = screen.query(".suggestion-btn")
            assert len(buttons) == 0
            # Previous is now visible.
            prev_btn = screen.query_one("#prev-btn", Button)
            assert prev_btn.display is True

    @pytest.mark.asyncio
    async def test_free_form_input_sets_answer(self) -> None:
        """Submitting free-form text stores that text as the answer."""
        questions = _make_questions()
        async with _Host().run_test() as pilot:
            screen = DesignQuestionsScreen(questions)
            await pilot.app.push_screen(screen)
            await pilot.pause()

            input_widget = screen.query_one("#free-form-input", Input)
            input_widget.value = "Redis"
            await input_widget.action_submit()
            await pilot.pause()

            assert questions[0].answer == "Redis"
            assert screen._current_idx == 1

    @pytest.mark.asyncio
    async def test_empty_free_form_submission_ignored(self) -> None:
        """Submitting only whitespace does not advance."""
        questions = _make_questions()
        async with _Host().run_test() as pilot:
            screen = DesignQuestionsScreen(questions)
            await pilot.app.push_screen(screen)
            await pilot.pause()

            input_widget = screen.query_one("#free-form-input", Input)
            input_widget.value = "   "
            await input_widget.action_submit()
            await pilot.pause()

            assert questions[0].answer is None
            assert screen._current_idx == 0

    @pytest.mark.asyncio
    async def test_skip_button_advances_without_setting_answer(self) -> None:
        """The Skip button moves on without setting an answer."""
        questions = _make_questions()
        async with _Host().run_test() as pilot:
            screen = DesignQuestionsScreen(questions)
            await pilot.app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#skip-btn", Button).press()
            await pilot.pause()

            assert questions[0].answer is None
            assert screen._current_idx == 1

    @pytest.mark.asyncio
    async def test_previous_button_and_action(self) -> None:
        """The Previous button steps back one question; action guards zero."""
        questions = _make_questions()
        async with _Host().run_test() as pilot:
            screen = DesignQuestionsScreen(questions)
            await pilot.app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#skip-btn", Button).press()  # advance to Q2
            await pilot.pause()
            assert screen._current_idx == 1

            screen.query_one("#prev-btn", Button).press()
            await pilot.pause()
            assert screen._current_idx == 0

            # Action method alone must not go below zero.
            screen.action_previous()
            await pilot.pause()
            assert screen._current_idx == 0

    @pytest.mark.asyncio
    async def test_advance_past_last_question_dismisses(self) -> None:
        """Answering the last question dismisses the modal with the list."""
        questions = _make_questions()

        async def _run() -> list[DesignQuestion] | None:
            async with _Host().run_test() as pilot:
                app = pilot.app
                screen = DesignQuestionsScreen(questions)
                result_holder: dict[str, object] = {}

                def _callback(value: list[DesignQuestion] | None) -> None:
                    result_holder["value"] = value

                await app.push_screen(screen, _callback)
                await pilot.pause()

                screen.query_one("#skip-btn", Button).press()  # Q1 → Q2
                await pilot.pause()
                screen.query_one("#skip-btn", Button).press()  # Q2 → dismiss
                await pilot.pause()

                return result_holder.get("value")  # type: ignore[return-value]

        result = await _run()
        assert result is questions

    @pytest.mark.asyncio
    async def test_escape_cancels_with_none(self) -> None:
        """Pressing Esc dismisses the screen with ``None``."""
        questions = _make_questions()
        async with _Host().run_test() as pilot:
            app = pilot.app
            screen = DesignQuestionsScreen(questions)

            dismissed: dict[str, object] = {}

            def _callback(value: list[DesignQuestion] | None) -> None:
                dismissed["value"] = value

            await app.push_screen(screen, _callback)
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            assert dismissed["value"] is None

    @pytest.mark.asyncio
    async def test_unknown_input_id_is_ignored(self) -> None:
        """Input submissions from other ids don't move the index."""
        questions = _make_questions()
        async with _Host().run_test() as pilot:
            screen = DesignQuestionsScreen(questions)
            await pilot.app.push_screen(screen)
            await pilot.pause()

            # Build a fake event with a foreign input id.
            from textual.widgets import Input as _Input

            foreign = _Input(id="not-the-input")
            # Use the widget's Submitted message type.
            event = _Input.Submitted(foreign, "ignored")
            screen.on_input_submitted(event)
            await pilot.pause()

            assert screen._current_idx == 0
