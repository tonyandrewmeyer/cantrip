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


# How many directory levels to expand automatically.
_AUTO_EXPAND_DEPTH = 4


class _FilteredTree(DirectoryTree):
    """DirectoryTree subclass that hides noisy entries and auto-expands."""

    def filter_paths(
        self, paths: collections.abc.Iterable[Path]
    ) -> collections.abc.Iterable[Path]:
        """Hide hidden/noise directories from the tree."""
        return [p for p in paths if p.name not in _HIDDEN_NAMES]

    @staticmethod
    def _node_depth(node: object) -> int:
        """Count the depth of a node relative to the root."""
        depth = 0
        current = getattr(node, "parent", None)
        while current is not None:
            depth += 1
            current = getattr(current, "parent", None)
        return depth

    def on_tree_node_expanded(self, event: DirectoryTree.NodeExpanded) -> None:
        """Auto-expand child directories up to the configured depth."""
        for child in event.node.children:
            if (
                child.allow_expand
                and not child.is_expanded
                and self._node_depth(child) < _AUTO_EXPAND_DEPTH
            ):
                child.expand()


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
        """Prevent file selection from bubbling (read-only view)."""
        event.stop()
