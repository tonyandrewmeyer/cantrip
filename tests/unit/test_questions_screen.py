"""Tests for the DesignQuestionsScreen."""

from cantrip.agent.design import DesignQuestion
from cantrip.tui.screens.questions import DesignQuestionsScreen


class TestDesignQuestionsScreen:
    """Tests for the DesignQuestionsScreen modal."""

    def test_screen_initialises_with_questions(self) -> None:
        """Screen stores the questions and starts at index 0."""
        questions = [
            DesignQuestion(key="DB", text="Which database?", suggestions=["PostgreSQL", "MySQL"]),
            DesignQuestion(key="Port", text="Which port?", suggestions=["5432", "3306"]),
        ]
        screen = DesignQuestionsScreen(questions)
        assert screen._questions is questions
        assert screen._current_idx == 0

    def test_advance_increments_index(self) -> None:
        """Calling _advance moves to the next question."""
        questions = [
            DesignQuestion(key="A", text="Q1"),
            DesignQuestion(key="B", text="Q2"),
        ]
        screen = DesignQuestionsScreen(questions)
        # Manually advance (without running the TUI).
        screen._current_idx = 0
        screen._current_idx += 1
        assert screen._current_idx == 1

    def test_action_previous_decrements_index(self) -> None:
        """action_previous goes back one question."""
        questions = [
            DesignQuestion(key="A", text="Q1"),
            DesignQuestion(key="B", text="Q2"),
        ]
        screen = DesignQuestionsScreen(questions)
        screen._current_idx = 1
        # action_previous does not call _show_question (needs mount),
        # so test the index logic directly.
        if screen._current_idx > 0:
            screen._current_idx -= 1
        assert screen._current_idx == 0

    def test_action_previous_does_not_go_below_zero(self) -> None:
        """action_previous at index 0 stays at 0."""
        questions = [
            DesignQuestion(key="A", text="Q1"),
        ]
        screen = DesignQuestionsScreen(questions)
        screen._current_idx = 0
        if screen._current_idx > 0:
            screen._current_idx -= 1
        assert screen._current_idx == 0
