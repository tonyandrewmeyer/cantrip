"""File tree widget showing the charm directory."""

import collections.abc
import pathlib

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import DirectoryTree, Static

from cantrip.tui.widgets import repo_stats as repo_stats_widget

# Specific noise dirs to hide regardless of how their name looks.
# These are the long-standing entries; the dotfile-dir rule below
# (Phase 108.9) is what actually does most of the work.
_HIDDEN_NAMES = frozenset(
    {
        "__pycache__",
        "node_modules",
    }
)


def is_hidden_path(path: pathlib.Path) -> bool:
    """Return ``True`` when *path* should not appear in the file tree.

    Phase 108.9 rule: "noise dir by name *or* dotfile directory".
    Dotfile **files** the user routinely edits (``.gitignore``,
    ``.editorconfig``, ``.envrc``, ``.python-version``) stay
    visible.  Dotfile **directories** (``.git``, ``.tox``,
    ``.venv``, ``.mypy_cache``, ``.ruff_cache``, ``.pytest_cache``,
    ``.hypothesis``, ``.github``, ``.claude``, ``.craft``, …) are
    caches, build artefacts, or tool state — never things the
    user opens from the tree — so they collapse under the rule
    rather than a perpetually-growing allowlist.

    Also hides cantrip's own session-state files (``.cantrip``,
    ``.cantrip-repomap.json``, ``.cantrip-shm``, ``.cantrip-wal``,
    …) — these are SQLite databases and repo-map snapshots cantrip
    writes into the working directory, never user-edited content.

    The check uses :meth:`pathlib.Path.is_dir`, which costs one
    stat per entry; the tree only ever filters one directory's
    immediate children at a time so the overhead is bounded.
    """
    if path.name in _HIDDEN_NAMES:
        return True
    if path.name.startswith(".cantrip"):
        return True
    return path.name.startswith(".") and path.is_dir()


# Below this widget width, hide the stats sidebar so the tree still
# fits in narrow terminals.  Picked to leave the tree at least 24
# cols when the sidebar is showing at its 18-col minimum.
_STATS_FOLD_WIDTH = 46


class _FilteredTree(DirectoryTree):
    """DirectoryTree subclass that hides noisy entries."""

    def filter_paths(
        self, paths: collections.abc.Iterable[pathlib.Path]
    ) -> collections.abc.Iterable[pathlib.Path]:
        """Hide hidden/noise directories from the tree."""
        return [p for p in paths if not is_hidden_path(p)]


class CharmTreeWidget(Widget):
    """Displays a live directory tree rooted at the charm working directory.

    The tree auto-refreshes on a timer so new files appear as the agent
    writes them.  At wide terminal widths a sibling
    :class:`~cantrip.tui.widgets.repo_stats.RepoStatsWidget` shows
    glance-and-go signals (recent file, last commit, line counts);
    below :data:`_STATS_FOLD_WIDTH` columns the sidebar is hidden so
    the tree keeps the full pane.
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

    CharmTreeWidget #charm-files-body {
        height: 1fr;
    }

    CharmTreeWidget _FilteredTree {
        width: 1fr;
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self, charm_path: pathlib.Path, **kwargs: object) -> None:
        """Initialise with the charm directory path."""
        super().__init__(**kwargs)
        self._charm_path = charm_path

    def compose(self) -> ComposeResult:
        """Compose the widget layout."""
        yield Static("Charm Files", classes="tree-header")
        with Horizontal(id="charm-files-body"):
            tree = _FilteredTree(str(self._charm_path), id="charm-dir-tree")
            tree.guide_depth = 3
            yield tree
            yield repo_stats_widget.RepoStatsWidget(id="charm-files-stats")

    def on_mount(self) -> None:
        """Start a periodic refresh so new files appear."""
        self.set_interval(3.0, self._refresh_tree)
        self.set_interval(3.0, self._refresh_stats)

    def on_resize(self) -> None:
        """Fold or unfold the stats sidebar based on widget width."""
        self._apply_stats_visibility()

    def _apply_stats_visibility(self) -> None:
        """Hide the stats column if the widget is too narrow."""
        results = self.query("#charm-files-stats")
        if not results:
            return
        stats = results.first()
        stats.display = (self.size.width or 0) >= _STATS_FOLD_WIDTH

    def _refresh_tree(self) -> None:
        """Reload the directory tree to pick up new or removed files."""
        results = self.query("#charm-dir-tree")
        if not results:
            return
        tree = results.first(_FilteredTree)
        tree.reload()

    async def _refresh_stats(self) -> None:
        """Recompute the stats sidebar off the UI thread."""
        results = self.query("#charm-files-stats")
        if not results:
            return
        stats = await repo_stats_widget.compute_repo_stats_async(self._charm_path)
        results.first(repo_stats_widget.RepoStatsWidget).set_stats(stats)
        self._apply_stats_visibility()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Open a modal detail screen for the selected file."""
        event.stop()
        from cantrip.tui.screens.file_detail import FileDetailScreen

        self.app.push_screen(
            FileDetailScreen(pathlib.Path(event.path), charm_root=self._charm_path)
        )
