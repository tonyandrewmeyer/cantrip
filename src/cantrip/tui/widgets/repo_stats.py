"""Repo-stats sidebar shown alongside the charm file tree.

Computes a small slate of glance-and-go signals from the charm
working directory:

- the most recently modified file (with relative timestamp),
- the most recent git commit (short hash, subject, age),
- a line-count summary (total + the top two languages),
- file and directory totals.

Test results and lint state are explicitly **not** in the slate —
those need a runner-side hook to avoid showing stale data.  The
trigger to revisit is a per-run test-results / charmlint event on
the shared bus that this widget can subscribe to.
"""

import asyncio
import dataclasses
import datetime
import os
import pathlib
import subprocess

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

# Hidden directory names matching ``filetree._HIDDEN_NAMES``; pruned
# from the walk so the agent's own caches don't show up in the
# stats.  ``.git`` is included so its blob storage doesn't dominate
# the file count.
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

# Extension → display-language mapping.  Only files whose extension
# is in this set contribute to the line count, which keeps the walk
# bounded on charm checkouts that vendor large binary or lockfile
# blobs.
_LANGUAGE_EXTS: dict[str, str] = {
    ".py": "py",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "md",
    ".j2": "jinja",
    ".rst": "rst",
    ".html": "html",
    ".css": "css",
    ".js": "js",
    ".ts": "ts",
    ".tsx": "ts",
    ".rs": "rust",
    ".go": "go",
    ".sh": "sh",
    ".cfg": "ini",
    ".ini": "ini",
    ".json": "json",
}

# Skip files larger than this when counting lines.  Catches generated
# bundle-output and lockfile fixtures without forcing the user to
# whitelist every project layout.
_MAX_FILE_BYTES = 1_000_000

# Defensive cap on total files scanned per refresh, so an accidental
# ``charm_path`` pointing somewhere huge (``~`` / ``/``) cannot
# wedge the UI thread.
_MAX_FILES_SCANNED = 5_000


@dataclasses.dataclass(slots=True, frozen=True)
class CommitInfo:
    """Snapshot of the working tree's HEAD commit."""

    short_hash: str
    subject: str
    when: datetime.datetime


@dataclasses.dataclass(slots=True, frozen=True)
class RepoStats:
    """Aggregated stats for the charm working directory.

    All fields are *snapshot* values; the widget refreshes them on a
    timer rather than holding live filesystem watches.
    """

    files: int
    directories: int
    total_lines: int
    lines_by_language: tuple[tuple[str, int], ...]
    most_recent_file: pathlib.PurePath | None
    most_recent_mtime: datetime.datetime | None
    last_commit: CommitInfo | None
    truncated: bool = False


_EMPTY_STATS = RepoStats(
    files=0,
    directories=0,
    total_lines=0,
    lines_by_language=(),
    most_recent_file=None,
    most_recent_mtime=None,
    last_commit=None,
)


def compute_repo_stats(root: pathlib.Path) -> RepoStats:
    """Walk ``root`` and return a :class:`RepoStats` snapshot.

    Cheap enough for a 3 s refresh tick on a typical charm
    checkout.  Hidden directories and oversized files are skipped;
    line counts cover the languages in :data:`_LANGUAGE_EXTS` only.
    """
    if not root.exists() or not root.is_dir():
        return _EMPTY_STATS

    file_count = 0
    dir_count = 0
    total_lines = 0
    lines_per_lang: dict[str, int] = {}
    newest_path: pathlib.Path | None = None
    newest_mtime: float = -1.0
    truncated = False

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in _HIDDEN_NAMES]
        dir_count += len(dirnames)
        for name in filenames:
            file_count += 1
            if file_count > _MAX_FILES_SCANNED:
                truncated = True
                break
            full = pathlib.Path(dirpath) / name
            try:
                stat = full.stat()
            except OSError:
                continue
            if stat.st_mtime > newest_mtime:
                newest_mtime = stat.st_mtime
                newest_path = full
            ext = full.suffix.lower()
            language = _LANGUAGE_EXTS.get(ext)
            if language is None or stat.st_size > _MAX_FILE_BYTES:
                continue
            lines = _count_lines(full)
            if lines is None:
                continue
            total_lines += lines
            lines_per_lang[language] = lines_per_lang.get(language, 0) + lines
        if truncated:
            break

    if newest_path is not None:
        rel: pathlib.PurePath = pathlib.PurePath(newest_path).relative_to(root)
        recent = rel
        recent_mtime: datetime.datetime | None = datetime.datetime.fromtimestamp(
            newest_mtime, tz=datetime.UTC
        )
    else:
        recent = None
        recent_mtime = None

    by_lang = tuple(sorted(lines_per_lang.items(), key=lambda kv: (-kv[1], kv[0])))
    return RepoStats(
        files=file_count,
        directories=dir_count,
        total_lines=total_lines,
        lines_by_language=by_lang,
        most_recent_file=recent,
        most_recent_mtime=recent_mtime,
        last_commit=read_last_commit(root),
        truncated=truncated,
    )


def _count_lines(path: pathlib.Path) -> int | None:
    """Return the line count for ``path`` or ``None`` on read error."""
    try:
        with path.open("rb") as fh:
            count = 0
            for _ in fh:
                count += 1
            return count
    except OSError:
        return None


def read_last_commit(root: pathlib.Path) -> CommitInfo | None:
    """Return :class:`CommitInfo` for ``root``'s HEAD, or ``None``.

    Returns ``None`` for non-git directories, repositories with no
    commits, or environments without ``git`` on the path.
    """
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h%x00%s%x00%ct"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    payload = result.stdout.strip()
    if not payload:
        return None
    parts = payload.split("\x00")
    if len(parts) != 3:
        return None
    short_hash, subject, ct = parts
    try:
        when = datetime.datetime.fromtimestamp(int(ct), tz=datetime.UTC)
    except ValueError:
        return None
    return CommitInfo(short_hash=short_hash, subject=subject, when=when)


def format_relative_time(when: datetime.datetime, *, now: datetime.datetime | None = None) -> str:
    """Format ``when`` as a compact relative-time string.

    Examples: ``"3s ago"``, ``"12m ago"``, ``"4h ago"``, ``"2d ago"``,
    ``"5mo ago"``, ``"1y ago"``.  Used for the most-recent-file and
    last-commit captions where exact timestamps are noise.
    """
    reference = now if now is not None else datetime.datetime.now(when.tzinfo)
    delta = reference - when
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


def _truncate(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` chars, appending an ellipsis."""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"
    return text[: limit - 1] + "…"


def render_stats_lines(stats: RepoStats, *, width: int) -> list[str]:
    """Render :class:`RepoStats` as a list of single-line strings.

    ``width`` is the available column width for the stats column;
    long values (commit subjects, file paths) are truncated so the
    output never wraps in a fixed-width terminal pane.  No row in
    the returned list exceeds ``width`` columns.
    """
    width = max(width, 12)
    lines: list[str] = []

    if stats.most_recent_file is not None and stats.most_recent_mtime is not None:
        rel_time = format_relative_time(stats.most_recent_mtime)
        path_text = str(stats.most_recent_file)
        prefix = "Recent: "
        budget = max(width - len(prefix) - len(rel_time) - 1, 8)
        lines.append(f"{prefix}{_truncate(path_text, budget)} {rel_time}")
    else:
        lines.append("Recent: —")

    commit = stats.last_commit
    if commit is None:
        lines.append("Commit: —")
    else:
        rel_time = format_relative_time(commit.when)
        lines.append(f"Commit: {commit.short_hash} {rel_time}")
        prefix = "  "
        budget = max(width - len(prefix), 8)
        lines.append(f"{prefix}{_truncate(commit.subject, budget)}")

    if stats.total_lines > 0:
        lines.append(f"Lines:  {stats.total_lines:,} total")
        if stats.lines_by_language:
            top = stats.lines_by_language[:2]
            tail = " / ".join(f"{count:,} {lang}" for lang, count in top)
            lines.append(f"  {_truncate(tail, max(width - 2, 8))}")
    else:
        lines.append("Lines:  —")

    suffix = " (truncated)" if stats.truncated else ""
    lines.append(f"Files:  {stats.files:,} ({stats.directories:,} dirs){suffix}")

    # Final defensive clamp — ensures no decorated row (long commit
    # hashes, "(truncated)" tag, language summary) overruns the
    # available column width even on a 12-col terminal.
    return [_truncate(line, width) for line in lines]


class RepoStatsWidget(Widget):
    """Render the latest :class:`RepoStats` snapshot as text rows.

    The widget is updated by :class:`CharmTreeWidget` rather than
    polling its own timer, so the parent owns the refresh cadence
    and stat computation can ride on a single thread call.
    """

    DEFAULT_CSS = """
    RepoStatsWidget {
        width: auto;
        min-width: 18;
        max-width: 50%;
        padding-left: 1;
        border-left: solid $primary;
    }

    RepoStatsWidget Static {
        width: 100%;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        """Initialise the empty stats column."""
        super().__init__(**kwargs)
        self._stats: RepoStats = _EMPTY_STATS

    def compose(self) -> ComposeResult:
        """Compose the layout — an empty static the parent populates."""
        yield Static("", id="repo-stats-body")

    def set_stats(self, stats: RepoStats) -> None:
        """Update the displayed stats, no-op if unchanged."""
        if stats == self._stats:
            return
        self._stats = stats
        body = self.query_one("#repo-stats-body", Static)
        width = max(self.size.width or 30, 18)
        body.update("\n".join(render_stats_lines(stats, width=width)))


async def compute_repo_stats_async(root: pathlib.Path) -> RepoStats:
    """Run :func:`compute_repo_stats` on a worker thread.

    Keeps the UI loop responsive on charm checkouts where the walk
    is large enough that a synchronous call would briefly stall the
    timer tick.
    """
    return await asyncio.to_thread(compute_repo_stats, root)
