"""Branch-coverage backfill for ``cantrip.agent.auto_commit``.

The base ``test_autocommit.py`` covers the happy-path commit shape
against real git repos.  This file fills the failure / fallback
branches that don't exercise on a healthy repo:

- ``_is_git_repo`` exception path
- ``_has_dirty_tree`` exception / non-zero rc
- ``_commit`` add-A-failure / commit-exception / non-zero rc /
  rev-parse-exception / rev-parse-empty
- ``_add_paths`` empty-paths short-circuit / subprocess error
- ``_staged_diff_empty`` subprocess error
- ``collect_touched_files`` non-dict edit entry
- ``_human_coauthor_trailer`` no-git / subprocess error
- ``_summarise_user_message`` empty-cleaned and long-cleaned branches
- ``build_commit_message`` long-prompt truncation
- ``post_turn_commit_agent_edits`` no-git, staged-diff-empty skip
"""

from __future__ import annotations

import pathlib
import subprocess
from unittest.mock import MagicMock, patch

from cantrip.agent import auto_commit as ac
from cantrip.llm.base import Message, Role, ToolCall


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# _is_git_repo
# ---------------------------------------------------------------------------


class TestIsGitRepo:
    """``_is_git_repo`` failure branches."""

    def test_subprocess_error_returns_false(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert ac._is_git_repo(tmp_path) is False

    def test_timeout_returns_false(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=1),
        ):
            assert ac._is_git_repo(tmp_path) is False


# ---------------------------------------------------------------------------
# _has_dirty_tree
# ---------------------------------------------------------------------------


class TestHasDirtyTree:
    """``_has_dirty_tree`` failure branches."""

    def test_subprocess_error_returns_false(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert ac._has_dirty_tree(tmp_path) is False

    def test_non_zero_returncode_returns_false(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            return_value=_proc(returncode=128),
        ):
            assert ac._has_dirty_tree(tmp_path) is False


# ---------------------------------------------------------------------------
# _commit
# ---------------------------------------------------------------------------


class TestCommit:
    """``_commit`` exception / failure branches."""

    def test_add_all_failure_returns_none(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            return_value=_proc(returncode=1, stderr="lock"),
        ):
            assert ac._commit(tmp_path, "msg", stage_all=True) is None

    def test_subprocess_error_returns_none(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert ac._commit(tmp_path, "msg") is None

    def test_commit_non_zero_returns_none(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            return_value=_proc(returncode=1, stderr="nothing to commit"),
        ):
            assert ac._commit(tmp_path, "msg") is None

    def test_rev_parse_subprocess_error_returns_none(self, tmp_path: pathlib.Path) -> None:
        # First call (commit) succeeds, second (rev-parse) raises.
        results = [_proc(returncode=0)]
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=[*results, OSError("eperm")],
        ):
            assert ac._commit(tmp_path, "msg") is None

    def test_rev_parse_non_zero_returns_none(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=[
                _proc(returncode=0),  # commit
                _proc(returncode=1),  # rev-parse
            ],
        ):
            assert ac._commit(tmp_path, "msg") is None

    def test_rev_parse_empty_stdout_returns_none(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=[
                _proc(returncode=0),  # commit
                _proc(returncode=0, stdout=""),  # rev-parse
            ],
        ):
            assert ac._commit(tmp_path, "msg") is None


# ---------------------------------------------------------------------------
# _add_paths
# ---------------------------------------------------------------------------


class TestAddPaths:
    """``_add_paths`` short-circuit and subprocess error."""

    def test_empty_paths_returns_false_without_calling_subprocess(
        self, tmp_path: pathlib.Path
    ) -> None:
        with patch("cantrip.agent.auto_commit.subprocess.run") as run:
            assert ac._add_paths(tmp_path, []) is False
        run.assert_not_called()

    def test_subprocess_error_returns_false(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert ac._add_paths(tmp_path, ["foo.py"]) is False


# ---------------------------------------------------------------------------
# _staged_diff_empty
# ---------------------------------------------------------------------------


class TestStagedDiffEmpty:
    """``_staged_diff_empty`` subprocess error path."""

    def test_subprocess_error_returns_true(self, tmp_path: pathlib.Path) -> None:
        # Errors return True (treat as "nothing staged") so callers
        # skip rather than crash.
        with patch(
            "cantrip.agent.auto_commit.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            assert ac._staged_diff_empty(tmp_path) is True


# ---------------------------------------------------------------------------
# collect_touched_files
# ---------------------------------------------------------------------------


def _assistant_with_tool(tool_name: str, args: dict) -> Message:
    return Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id="t1", name=tool_name, arguments=args)],
    )


class TestCollectTouchedFilesBranches:
    """Edits-list non-dict branch."""

    def test_non_dict_edit_entry_is_skipped(self) -> None:
        msg = _assistant_with_tool(
            "multi_edit",
            {"edits": [{"path": "a.py"}, "not-a-dict", {"path": "b.py"}]},
        )
        files = ac.collect_touched_files([msg])
        assert files == ["a.py", "b.py"]


# ---------------------------------------------------------------------------
# _human_coauthor_trailer
# ---------------------------------------------------------------------------


class TestHumanCoauthorTrailer:
    """``_human_coauthor_trailer`` failure branches."""

    def test_no_git_returns_none(self, tmp_path: pathlib.Path) -> None:
        with patch("cantrip.agent.auto_commit.shutil.which", return_value=None):
            assert ac._human_coauthor_trailer(tmp_path) is None

    def test_subprocess_error_returns_none(self, tmp_path: pathlib.Path) -> None:
        with (
            patch("cantrip.agent.auto_commit.shutil.which", return_value="/bin/git"),
            patch(
                "cantrip.agent.auto_commit.subprocess.run",
                side_effect=OSError("eperm"),
            ),
        ):
            assert ac._human_coauthor_trailer(tmp_path) is None


# ---------------------------------------------------------------------------
# _summarise_user_message
# ---------------------------------------------------------------------------


class TestSummariseUserMessage:
    """Whitespace-only and over-long subject branches."""

    def test_blank_message_returns_default_subject(self) -> None:
        assert ac._summarise_user_message("   \n  ") == f"{ac._FALLBACK_SUBJECT_PREFIX} edits"

    def test_long_message_is_truncated_with_ellipsis(self) -> None:
        long = "x" * 500
        out = ac._summarise_user_message(long)
        assert out.endswith("…")
        assert len(out) <= ac._FALLBACK_SUBJECT_LIMIT + len(f"{ac._FALLBACK_SUBJECT_PREFIX} ")


# ---------------------------------------------------------------------------
# build_commit_message — long prompt truncation
# ---------------------------------------------------------------------------


class TestBuildCommitMessageLongPrompt:
    """``build_commit_message`` prompt-line truncation branch."""

    def test_long_prompt_is_truncated(self) -> None:
        # Anything over 280 chars should fold into "Prompt: …" with a
        # trailing ellipsis.
        long = "x" * 500
        msg = ac.build_commit_message(long)
        # Find the "Prompt:" line.
        prompt_line = next(line for line in msg.splitlines() if line.startswith("Prompt: "))
        body = prompt_line.removeprefix("Prompt: ")
        assert body.endswith("…")
        assert len(body) <= 280


# ---------------------------------------------------------------------------
# post_turn_commit_agent_edits — staged-diff-empty + no-git branches
# ---------------------------------------------------------------------------


class TestPostTurnCommitBranches:
    """``post_turn_commit_agent_edits`` early-return / skip branches."""

    def test_no_git_returns_none(self, tmp_path: pathlib.Path) -> None:
        with patch("cantrip.agent.auto_commit.shutil.which", return_value=None):
            sha = ac.post_turn_commit_agent_edits(
                tmp_path,
                [_assistant_with_tool("write_file", {"path": "x.py"})],
                "do thing",
            )
        assert sha is None

    def test_staged_diff_empty_skips_commit(self, tmp_path: pathlib.Path) -> None:
        # ``_add_paths`` succeeds, ``_staged_diff_empty`` reports
        # nothing staged → the helper returns None without calling
        # ``_commit``.
        with (
            patch("cantrip.agent.auto_commit.shutil.which", return_value="/bin/git"),
            patch("cantrip.agent.auto_commit._is_git_repo", return_value=True),
            patch("cantrip.agent.auto_commit._add_paths", return_value=True),
            patch(
                "cantrip.agent.auto_commit._staged_diff_empty",
                return_value=True,
            ),
            patch("cantrip.agent.auto_commit._commit") as commit,
        ):
            sha = ac.post_turn_commit_agent_edits(
                tmp_path,
                [_assistant_with_tool("write_file", {"path": "x.py"})],
                "do thing",
            )
        assert sha is None
        commit.assert_not_called()
