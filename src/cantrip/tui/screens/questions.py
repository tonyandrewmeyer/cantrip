"""Interactive design questions screen for the TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from cantrip.agent.design import DesignQuestion


class DesignQuestionsScreen(ModalScreen[list[DesignQuestion] | None]):
    """Modal screen that presents design questions one at a time.

    Each question is shown with its suggested answers as buttons plus a
    free-form input field.  After the last question the screen dismisses
    itself, returning the answered questions via the ``ModalScreen`` result
    mechanism.
    """

    DEFAULT_CSS = """
    DesignQuestionsScreen {
        align: center middle;
    }

    #questions-container {
        width: 80;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 2 3;
    }

    #question-title {
        text-style: bold;
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
    }

    #question-progress {
        color: $text-muted;
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
    }

    #question-text {
        padding: 1 0;
    }

    .suggestion-btn {
        width: 100%;
        margin: 1 0 0 0;
    }

    #free-form-label {
        color: $text-muted;
        padding-top: 1;
    }

    #free-form-input {
        margin-top: 1;
    }

    #skip-btn {
        margin-top: 1;
        width: 100%;
        color: $text-muted;
    }

    #prev-btn {
        margin-top: 1;
        width: 100%;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("left", "previous", "Previous", show=False),
        Binding("p", "previous", "Previous", show=False),
    ]

    def __init__(self, questions: list[DesignQuestion]) -> None:
        """Initialise with a list of questions to present."""
        super().__init__()
        self._questions = questions
        self._current_idx = 0

    def compose(self) -> ComposeResult:
        """Compose the initial layout."""
        with Center(), Vertical(id="questions-container"):
            yield Static("Design Questions", id="question-title")
            yield Static("", id="question-progress")
            yield Static("", id="question-text")
            yield Vertical(id="suggestions-area")
            yield Static("Or type your own answer:", id="free-form-label")
            yield Input(
                placeholder="Type a custom answer and press Enter...",
                id="free-form-input",
            )
            yield Button("Skip this question", id="skip-btn", variant="default")
            yield Button("← Previous question", id="prev-btn", variant="default")

    def on_mount(self) -> None:
        """Show the first question on mount."""
        self._show_question()

    def _show_question(self) -> None:
        """Display the current question and its suggestions."""
        if self._current_idx >= len(self._questions):
            self.dismiss(self._questions)
            return

        question = self._questions[self._current_idx]
        total = len(self._questions)
        idx = self._current_idx + 1

        self.query_one("#question-progress", Static).update(f"Question {idx} of {total}")
        self.query_one("#question-text", Static).update(f"**{question.key}**: {question.text}")

        # Rebuild suggestion buttons.
        area = self.query_one("#suggestions-area", Vertical)
        area.remove_children()
        for i, suggestion in enumerate(question.suggestions):
            btn = Button(suggestion, id=f"suggestion-{i}", classes="suggestion-btn")
            area.mount(btn)

        # Clear the free-form input.
        input_widget = self.query_one("#free-form-input", Input)
        input_widget.value = ""
        input_widget.focus()

        # Hide the Previous button on the first question.
        self.query_one("#prev-btn", Button).display = self._current_idx > 0

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle suggestion, skip, and previous button presses."""
        if event.button.id == "skip-btn":
            self._advance()
            return

        if event.button.id == "prev-btn":
            self.action_previous()
            return

        if event.button.id and event.button.id.startswith("suggestion-"):
            # Use the button label as the answer.
            self._questions[self._current_idx].answer = str(event.button.label)
            self._advance()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle free-form answer submission."""
        if event.input.id != "free-form-input":
            return
        value = event.value.strip()
        if value:
            self._questions[self._current_idx].answer = value
            self._advance()

    def _advance(self) -> None:
        """Move to the next question or finish."""
        self._current_idx += 1
        self._show_question()

    def action_previous(self) -> None:
        """Go back to the previous question."""
        if self._current_idx > 0:
            self._current_idx -= 1
            self._show_question()

    def action_cancel(self) -> None:
        """Cancel the screen, returning ``None`` to distinguish from completion."""
        self.dismiss(None)
