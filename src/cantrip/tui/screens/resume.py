"""Resume-session prompt modal for the Cantrip TUI (Phase 31.3).

Shown on launch when a ``.cantrip`` file exists at the charm path.  The
user picks Resume, Fresh, or Transcript; the chosen verb is dispatched
back via the dismiss result so the app can load or archive before it
starts the executor.
"""

from __future__ import annotations

import typing
from typing import ClassVar

from textual.binding import Binding
from textual.containers import Center, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

if typing.TYPE_CHECKING:
    from textual.app import ComposeResult

    from cantrip.agent.session_preview import SessionPreview
    from cantrip.llm.base import Message


class ResumePromptScreen(ModalScreen[str]):
    """Modal that returns one of ``"resume"``, ``"fresh"``, or ``"escape"``."""

    DEFAULT_CSS = """
    ResumePromptScreen {
        align: center middle;
    }

    #resume-container {
        width: 100;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    #resume-title {
        width: 100%;
        height: 1;
        padding-bottom: 1;
    }

    .resume-title-text {
        text-style: bold;
        width: 1fr;
    }

    .resume-title-hint {
        color: $text-muted;
        width: auto;
    }

    .resume-summary {
        padding: 1 0;
    }

    .resume-choices {
        padding-top: 1;
        text-style: bold;
    }

    .resume-hint {
        color: $text-muted;
        text-style: italic;
    }

    #resume-transcript {
        height: auto;
        max-height: 20;
        padding-top: 1;
    }

    .transcript-line {
        color: $text-muted;
    }
    """

    BINDINGS: ClassVar[list] = [
        Binding("r", "choose_resume", "Resume"),
        Binding("f", "choose_fresh", "Fresh"),
        Binding("t", "toggle_transcript", "Transcript"),
        Binding("escape", "choose_resume", "Resume (default)", show=False),
    ]

    def __init__(
        self,
        preview: SessionPreview,
        transcript: list[Message] | None = None,
    ) -> None:
        """Initialise with a preview and optional cached transcript tail.

        ``transcript`` is fetched lazily the first time the user presses
        ``t`` so we don't pay the read cost when they just want to
        resume.
        """
        super().__init__()
        self._preview = preview
        self._transcript: list[Message] | None = transcript
        self._transcript_visible = False

    def compose(self) -> ComposeResult:
        """Compose the resume prompt."""
        with Center(), Vertical(id="resume-container"):
            with Horizontal(id="resume-title"):
                yield Static("Resume prior session?", classes="resume-title-text")
                yield Static("[R/F/T]", classes="resume-title-hint", markup=False)
            yield Static(self._preview.summary(), classes="resume-summary")
            yield Static(
                "[R]esume previous work   [F]resh start (archive old)   [T]ranscript (toggle)",
                classes="resume-choices",
                markup=False,
            )
            yield Static(
                "Fresh renames .cantrip to .cantrip.bak-<timestamp> so nothing is lost.",
                classes="resume-hint",
            )
            with ScrollableContainer(id="resume-transcript"):
                # Populated on the first `t` press.
                pass

    def action_choose_resume(self) -> None:
        """Close the modal and signal 'resume'."""
        self.dismiss("resume")

    def action_choose_fresh(self) -> None:
        """Close the modal and signal 'fresh'."""
        self.dismiss("fresh")

    def action_toggle_transcript(self) -> None:
        """Show or hide the transcript tail inline."""
        container = self.query_one("#resume-transcript", ScrollableContainer)
        self._transcript_visible = not self._transcript_visible
        if not self._transcript_visible:
            container.remove_children()
            return
        # Fill with transcript lines (lazy: load if not already provided).
        container.remove_children()
        if self._transcript is None:
            container.mount(Static("(no messages available)", classes="transcript-line"))
            return
        if not self._transcript:
            container.mount(Static("(no messages persisted)", classes="transcript-line"))
            return
        for msg in self._transcript:
            content = msg.content.replace("\n", " ")
            if len(content) > 200:
                content = content[:197] + "..."
            container.mount(
                Static(
                    f"{msg.role.value.upper()}: {content}",
                    classes="transcript-line",
                )
            )

    def set_transcript(self, messages: list[Message]) -> None:
        """Seed the transcript tail after construction.

        Called by the app after ``push_screen`` if we want to avoid
        blocking on a message-table read at modal creation time.
        """
        self._transcript = messages
        if self._transcript_visible:
            self.action_toggle_transcript()
            self.action_toggle_transcript()
