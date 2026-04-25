"""Session-tree picker modal for the Cantrip TUI (Phase 67.1).

Renders the conversation as an indented tree of turns and lets the
user pick a node to fork from.  Dismisses with the selected turn id
on Enter; dismisses with ``None`` on Escape so the caller can leave
the active branch alone.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from cantrip.agent.slash_commands import TreeNode


class TreePickerScreen(ModalScreen[int | None]):
    """Modal that returns the chosen turn id, or ``None`` if cancelled."""

    DEFAULT_CSS = """
    TreePickerScreen {
        align: center middle;
    }

    #tree-container {
        width: 100;
        max-width: 90%;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #tree-title {
        width: 100%;
        text-style: bold;
        padding-bottom: 1;
    }

    #tree-hint {
        color: $text-muted;
        text-style: italic;
        padding-top: 1;
    }

    #tree-options {
        height: 1fr;
        max-height: 30;
        background: $surface;
    }

    #tree-empty {
        color: $text-muted;
        padding: 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, nodes: list[TreeNode]) -> None:
        """Initialise with a flat depth-first traversal of the tree."""
        super().__init__()
        self._nodes = nodes

    def compose(self) -> ComposeResult:
        """Compose the picker layout."""
        with Center(), Vertical(id="tree-container"):
            yield Static("Session tree", id="tree-title")
            if not self._nodes:
                yield Static(
                    "No turns yet — record a message before opening /tree.",
                    id="tree-empty",
                )
            else:
                yield OptionList(
                    *(self._option_for(node) for node in self._nodes),
                    id="tree-options",
                )
            yield Static(
                "Enter to fork from the selected turn · Esc to cancel · * marks the active branch",
                id="tree-hint",
            )

    @staticmethod
    def _option_for(node: TreeNode) -> Option:
        """Render one tree row as a selectable option, keyed by turn id."""
        prefix = "  " * node.depth
        marker = "*" if node.on_active_branch else " "
        timestamp = node.timestamp[:19] if node.timestamp else ""
        text = f"{prefix}{marker} [{node.id}] {node.role}: {node.label}"
        if timestamp:
            text = f"{text}  ({timestamp})"
        return Option(text, id=str(node.id))

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        """Dismiss with the selected turn id when the user presses Enter."""
        if event.option.id is None:
            self.dismiss(None)
            return
        try:
            self.dismiss(int(event.option.id))
        except ValueError:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Dismiss without selecting a turn."""
        self.dismiss(None)
