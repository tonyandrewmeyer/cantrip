"""Tests for the repo-stats sidebar (Phase 89)."""

import datetime
import pathlib
import subprocess

import pytest

from cantrip.tui.app import CantripApp
from cantrip.tui.widgets import filetree as filetree_widget
from cantrip.tui.widgets import repo_stats as repo_stats_widget
from cantrip.tui.widgets.repo_stats import (
    CommitInfo,
    RepoStats,
    RepoStatsWidget,
    compute_repo_stats,
    format_relative_time,
    read_last_commit,
    render_stats_lines,
)
from tests.unit.tui.test_tui import _patch_app

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# compute_repo_stats — pure walk + count
# ---------------------------------------------------------------------------


def _write_tree(root: pathlib.Path, files: dict[str, str]) -> None:
    """Materialise a synthetic charm checkout under ``root``."""
    for relpath, content in files.items():
        target = root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


class TestComputeRepoStats:
    """``compute_repo_stats`` walks the directory and aggregates counts."""

    def test_empty_directory_returns_zero_stats(self, tmp_path: pathlib.Path):
        """An empty directory yields the empty stats sentinel."""
        stats = compute_repo_stats(tmp_path)
        assert stats.files == 0
        assert stats.directories == 0
        assert stats.total_lines == 0
        assert stats.lines_by_language == ()
        assert stats.most_recent_file is None
        assert stats.last_commit is None

    def test_missing_directory_returns_empty_stats(self, tmp_path: pathlib.Path):
        """A non-existent path returns the empty sentinel rather than raising."""
        stats = compute_repo_stats(tmp_path / "does-not-exist")
        assert stats.files == 0
        assert stats.most_recent_file is None

    def test_counts_files_and_lines_by_language(self, tmp_path: pathlib.Path):
        """Multiple supported languages contribute to the line totals."""
        _write_tree(
            tmp_path,
            {
                "src/charm.py": "import ops\n\nclass Charm: pass\n",
                "src/util.py": "def foo():\n    return 1\n",
                "metadata.yaml": "name: example\nsummary: demo\n",
                "README.md": "# Hello\n",
            },
        )
        stats = compute_repo_stats(tmp_path)
        assert stats.files == 4
        # ``src`` directory only — ``metadata.yaml`` and ``README.md``
        # live at the root.
        assert stats.directories == 1
        # 3 + 2 (py) + 2 (yaml) + 1 (md) = 8 lines.
        assert stats.total_lines == 8
        languages = dict(stats.lines_by_language)
        assert languages["py"] == 5
        assert languages["yaml"] == 2
        assert languages["md"] == 1
        # Top language comes first when sorted descending.
        assert stats.lines_by_language[0][0] == "py"

    def test_hidden_dirs_pruned_from_walk(self, tmp_path: pathlib.Path):
        """``.git`` / ``__pycache__`` and friends are not visited."""
        _write_tree(
            tmp_path,
            {
                "src/charm.py": "x = 1\n",
                ".git/objects/abc": "blob",
                "__pycache__/charm.cpython-312.pyc": "compiled",
                ".tox/py312/bin/python": "shim",
                ".cantrip/session.json": "{}",
                "node_modules/foo/index.js": "module.exports = {}",
            },
        )
        stats = compute_repo_stats(tmp_path)
        # Only the ``src/charm.py`` file survives the prune list; the
        # six hidden-dir files do not contribute.
        assert stats.files == 1
        assert stats.most_recent_file == pathlib.PurePath("src/charm.py")

    def test_oversized_files_excluded_from_line_count(self, tmp_path: pathlib.Path):
        """Files larger than the cap still count, but not their lines."""
        big = tmp_path / "huge.json"
        big.write_text("x\n" * (repo_stats_widget._MAX_FILE_BYTES // 2 + 1))
        small = tmp_path / "small.py"
        small.write_text("import x\n")
        stats = compute_repo_stats(tmp_path)
        assert stats.files == 2
        # Big JSON is over the cap so its lines are not summed; the
        # small Python file contributes one line.
        assert stats.total_lines == 1
        languages = dict(stats.lines_by_language)
        assert languages == {"py": 1}

    def test_most_recent_file_uses_largest_mtime(self, tmp_path: pathlib.Path):
        """The newest mtime wins; older files do not displace it."""
        old = tmp_path / "old.py"
        old.write_text("a\n")
        old_time = (datetime.datetime.now() - datetime.timedelta(hours=1)).timestamp()
        import os

        os.utime(old, (old_time, old_time))
        new = tmp_path / "new.py"
        new.write_text("b\n")
        stats = compute_repo_stats(tmp_path)
        assert stats.most_recent_file == pathlib.PurePath("new.py")

    def test_files_scan_cap_marks_truncated(self, tmp_path: pathlib.Path):
        """Hitting the defensive scan cap sets ``truncated=True``."""
        # Far cheaper than building 5 000 files: lower the cap for the
        # duration of this test.  ``compute_repo_stats`` reads the
        # module-level constant, so monkeypatch is fine.
        cap_files = {f"f{i}.py": f"# line {i}\n" for i in range(20)}
        _write_tree(tmp_path, cap_files)

        original = repo_stats_widget._MAX_FILES_SCANNED
        try:
            repo_stats_widget._MAX_FILES_SCANNED = 5  # type: ignore[misc]
            stats = compute_repo_stats(tmp_path)
        finally:
            repo_stats_widget._MAX_FILES_SCANNED = original  # type: ignore[misc]
        assert stats.truncated is True
        # Cap permits one extra scan before the break, so files
        # is exactly cap + 1.  The exact number is less interesting
        # than the ``truncated`` flag.
        assert stats.files == 6


# ---------------------------------------------------------------------------
# read_last_commit — git interop
# ---------------------------------------------------------------------------


def _git(cwd: pathlib.Path, *args: str) -> None:
    """Run a git command in ``cwd`` with deterministic identity config."""
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": "2026-01-15T10:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-15T10:00:00Z",
    }
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**__import__("os").environ, **env},
        check=True,
        capture_output=True,
    )


class TestReadLastCommit:
    """``read_last_commit`` reads HEAD via subprocess."""

    def test_non_git_directory_returns_none(self, tmp_path: pathlib.Path):
        """A directory without ``.git/`` returns ``None``."""
        assert read_last_commit(tmp_path) is None

    def test_repo_with_no_commits_returns_none(self, tmp_path: pathlib.Path):
        """A freshly-initialised repo with no commits returns ``None``."""
        _git(tmp_path, "init", "-q", "--initial-branch=main")
        assert read_last_commit(tmp_path) is None

    def test_repo_with_commit_returns_commit_info(self, tmp_path: pathlib.Path):
        """A repo with one commit returns the populated CommitInfo."""
        _git(tmp_path, "init", "-q", "--initial-branch=main")
        (tmp_path / "README.md").write_text("# Hello\n")
        _git(tmp_path, "add", "README.md")
        _git(tmp_path, "commit", "-q", "-m", "initial commit")
        info = read_last_commit(tmp_path)
        assert info is not None
        assert len(info.short_hash) >= 7
        assert info.subject == "initial commit"
        assert info.when.year == 2026

    def test_compute_includes_last_commit(self, tmp_path: pathlib.Path):
        """``compute_repo_stats`` populates ``last_commit`` for git repos."""
        _git(tmp_path, "init", "-q", "--initial-branch=main")
        (tmp_path / "charm.py").write_text("import ops\n")
        _git(tmp_path, "add", "charm.py")
        _git(tmp_path, "commit", "-q", "-m", "feat: scaffold charm")
        stats = compute_repo_stats(tmp_path)
        assert stats.last_commit is not None
        assert stats.last_commit.subject == "feat: scaffold charm"


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class TestFormatRelativeTime:
    """Compact relative-time strings."""

    @pytest.mark.parametrize(
        ("delta_seconds", "expected"),
        [
            (5, "5s ago"),
            (90, "1m ago"),
            (60 * 60 * 3, "3h ago"),
            (60 * 60 * 24 * 4, "4d ago"),
            (60 * 60 * 24 * 60, "2mo ago"),
            (60 * 60 * 24 * 400, "1y ago"),
        ],
    )
    def test_format_relative_time(self, delta_seconds: int, expected: str):
        """Each bucket renders the expected suffix."""
        now = datetime.datetime(2026, 5, 9, tzinfo=datetime.UTC)
        when = now - datetime.timedelta(seconds=delta_seconds)
        assert format_relative_time(when, now=now) == expected

    def test_negative_delta_is_just_now(self):
        """A future timestamp degrades to ``just now`` rather than negative."""
        now = datetime.datetime(2026, 5, 9, tzinfo=datetime.UTC)
        when = now + datetime.timedelta(seconds=30)
        assert format_relative_time(when, now=now) == "just now"


class TestRenderStatsLines:
    """``render_stats_lines`` produces the bullet rows the widget shows."""

    def test_empty_stats_render_dashes(self):
        """The empty sentinel renders the four dash placeholders."""
        stats = RepoStats(
            files=0,
            directories=0,
            total_lines=0,
            lines_by_language=(),
            most_recent_file=None,
            most_recent_mtime=None,
            last_commit=None,
        )
        lines = render_stats_lines(stats, width=40)
        assert lines[0] == "Recent: —"
        assert lines[1] == "Commit: —"
        assert lines[2] == "Lines:  —"
        assert lines[3].startswith("Files:  0")

    def test_populated_stats_render_each_row(self):
        """A populated stats snapshot renders all four sections."""
        now = datetime.datetime(2026, 5, 9, 12, 0, tzinfo=datetime.UTC)
        stats = RepoStats(
            files=87,
            directories=12,
            total_lines=3142,
            lines_by_language=(("py", 2103), ("yaml", 412)),
            most_recent_file=pathlib.PurePath("src/charm.py"),
            most_recent_mtime=now - datetime.timedelta(minutes=2),
            last_commit=CommitInfo(
                short_hash="abc1234",
                subject="fix(tui): tighten file pane",
                when=now - datetime.timedelta(hours=1),
            ),
        )
        lines = render_stats_lines(stats, width=40)
        assert "Recent:" in lines[0]
        assert "src/charm.py" in lines[0]
        assert lines[1].startswith("Commit: abc1234")
        assert "fix(tui)" in lines[2]
        assert "3,142" in lines[3]
        assert "Files:  87" in lines[5]

    def test_long_subject_is_truncated_at_width(self):
        """Wide values are clipped with an ellipsis."""
        now = datetime.datetime(2026, 5, 9, tzinfo=datetime.UTC)
        stats = RepoStats(
            files=1,
            directories=0,
            total_lines=0,
            lines_by_language=(),
            most_recent_file=None,
            most_recent_mtime=None,
            last_commit=CommitInfo(
                short_hash="abc1234",
                subject="x" * 200,
                when=now,
            ),
        )
        lines = render_stats_lines(stats, width=20)
        # Subject row must not exceed the column width.
        assert max(len(line) for line in lines) <= 20
        assert any("…" in line for line in lines)

    def test_truncated_flag_surfaces_suffix(self):
        """The truncated stats flag tags the Files row."""
        stats = RepoStats(
            files=5000,
            directories=10,
            total_lines=0,
            lines_by_language=(),
            most_recent_file=None,
            most_recent_mtime=None,
            last_commit=None,
            truncated=True,
        )
        lines = render_stats_lines(stats, width=40)
        assert "(truncated)" in lines[-1]


# ---------------------------------------------------------------------------
# Pilot integration — widget mounts inside CharmTreeWidget
# ---------------------------------------------------------------------------


class TestRepoStatsWidgetIntegration:
    """End-to-end Pilot tests against a real charm-shaped tmpdir."""

    @pytest.mark.asyncio
    async def test_widget_mounts_alongside_tree(self, tmp_path: pathlib.Path):
        """The stats widget is composed inside ``#charm-files``."""
        _write_tree(
            tmp_path,
            {
                "src/charm.py": "import ops\n",
                "metadata.yaml": "name: demo\n",
            },
        )
        p1, p2, _ = _patch_app()
        with p1, p2:
            async with CantripApp(charm_path=tmp_path).run_test(size=(160, 40)) as pilot:
                stats = pilot.app.query_one("#charm-files-stats", RepoStatsWidget)
                # Trigger one tick so the widget receives a stats payload.
                tree = pilot.app.query_one(
                    "#charm-files",
                    filetree_widget.CharmTreeWidget,
                )
                await tree._refresh_stats()
                await pilot.pause()
                assert stats.display is True
                # The stats body received a populated snapshot from
                # the timer-driven refresh.
                snapshot = stats._stats
                assert snapshot.files == 2
                assert snapshot.most_recent_file is not None

    @pytest.mark.asyncio
    async def test_stats_fold_at_narrow_width(self, tmp_path: pathlib.Path):
        """Below the fold threshold the stats column hides itself."""
        _write_tree(tmp_path, {"src/charm.py": "import ops\n"})
        p1, p2, _ = _patch_app()
        with p1, p2:
            # 80 cols × 35% right panel = ~28 cols; below the
            # ``_STATS_FOLD_WIDTH`` threshold of 46 cols inside the
            # widget, so the sidebar should fold away.
            async with CantripApp(charm_path=tmp_path).run_test(size=(80, 30)) as pilot:
                tree = pilot.app.query_one(
                    "#charm-files",
                    filetree_widget.CharmTreeWidget,
                )
                await tree._refresh_stats()
                await pilot.pause()
                stats = pilot.app.query_one("#charm-files-stats", RepoStatsWidget)
                assert stats.display is False
