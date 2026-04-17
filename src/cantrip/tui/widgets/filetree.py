"""File tree widget showing the charm directory."""

import collections.abc
from pathlib import Path

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DirectoryTree, Static

# Directories and patterns to hide from the tree.
_HIDDEN_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".tox",
        ".venv",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".cantrip",
    }
)


class _FilteredTree(DirectoryTree):
    """DirectoryTree subclass that hides noisy entries."""

    def filter_paths(
        self, paths: collections.abc.Iterable[Path]
    ) -> collections.abc.Iterable[Path]:
        """Hide hidden/noise directories from the tree."""
        return [p for p in paths if p.name not in _HIDDEN_NAMES]


class CharmTreeWidget(Widget):
    """Displays a live directory tree rooted at the charm working directory.

    The tree auto-refreshes on a timer so new files appear as the agent
    writes them.
    """

    DEFAULT_CSS = """
    CharmTreeWidget {
        height: 1fr;
        padding: 1;
    }

    CharmTreeWidget .tree-header {
        text-style: bold;
        margin-bottom: 1;
    }

    CharmTreeWidget _FilteredTree {
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self, charm_path: Path, **kwargs: object) -> None:
        """Initialise with the charm directory path."""
        super().__init__(**kwargs)
        self._charm_path = charm_path

    def compose(self) -> ComposeResult:
        """Compose the widget layout."""
        yield Static("Charm Files", classes="tree-header")
        tree = _FilteredTree(str(self._charm_path), id="charm-dir-tree")
        tree.guide_depth = 3
        yield tree

    def on_mount(self) -> None:
        """Start a periodic refresh so new files appear."""
        self.set_interval(3.0, self._refresh_tree)

    def _refresh_tree(self) -> None:
        """Reload the directory tree to pick up new or removed files."""
        results = self.query("#charm-dir-tree")
        if not results:
            return
        tree = results.first(_FilteredTree)
        tree.reload()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Show the selected file path in a toast notification."""
        event.stop()
        path = Path(event.path)
        # Show relative to charm root for brevity.
        try:
            display = str(path.relative_to(self._charm_path))
        except ValueError:
            display = str(path)
        self.notify(display, title="File", timeout=3)
