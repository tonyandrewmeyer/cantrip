"""Tests for Phase 75.6 — high-traffic tools populate ``ToolResult.caption``.

The captions surface inline in the chat (TUI + Web) via the ``TOOL_INVOKED``
event and replace the formulaic ``tool_name(arg=value)`` fallback the agent
loop would otherwise synthesise.  These tests assert the caption shape for
the tools listed in the 75.6 exit criterion: file-system, git, and
charm-tooling.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.charm import (
    CharmcraftFetchLibsTool,
    CharmcraftPackTool,
    CharmValidateTool,
)
from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from cantrip.agent.tools.git import (
    GitCloneTool,
    GitCommitTool,
    GitPushTool,
)
from cantrip.agent.tools.glob import GlobTool
from cantrip.agent.tools.grep import GrepTool


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ===========================================================================
# File-system
# ===========================================================================


class TestFileSystemCaptions:
    @pytest.mark.asyncio
    async def test_read_file(self, temp_dir) -> None:
        target = temp_dir / "sample.txt"
        target.write_text("line 1\nline 2\nline 3\n")
        result = await ReadFileTool(base_path=temp_dir).execute(path="sample.txt")
        assert result.success
        assert result.caption == "Read 3 lines from sample.txt"

    @pytest.mark.asyncio
    async def test_read_file_range(self, temp_dir) -> None:
        target = temp_dir / "sample.txt"
        target.write_text("a\nb\nc\nd\ne\n")
        result = await ReadFileTool(base_path=temp_dir).execute(
            path="sample.txt", start_line=2, end_line=4
        )
        assert result.success
        # Two newlines in the slice ``b\nc\nd\n`` → caption reports 3 lines.
        assert result.caption == "Read 3 lines from sample.txt"

    @pytest.mark.asyncio
    async def test_write_file(self, temp_dir) -> None:
        result = await WriteFileTool(base_path=temp_dir).execute(path="out.txt", content="hello")
        assert result.success
        assert result.caption == "Wrote 5 bytes to out.txt"

    @pytest.mark.asyncio
    async def test_list_directory(self, temp_dir) -> None:
        (temp_dir / "a.txt").write_text("a")
        (temp_dir / "b.txt").write_text("b")
        result = await ListDirectoryTool(base_path=temp_dir).execute(path=".")
        assert result.success
        assert result.caption is not None
        assert result.caption.startswith("Listed 2 entries in")

    @pytest.mark.asyncio
    async def test_edit_file(self, temp_dir) -> None:
        target = temp_dir / "f.txt"
        target.write_text("hello world")
        result = await EditFileTool(base_path=temp_dir).execute(
            path="f.txt", old_string="world", new_string="cantrip"
        )
        assert result.success
        assert result.caption == "Edited f.txt (1 replacement)"

    @pytest.mark.asyncio
    async def test_grep_with_matches(self, temp_dir) -> None:
        # Build a fake search corpus where one term shows up in two files.
        (temp_dir / "a.py").write_text("HookEvent matters\n")
        (temp_dir / "b.py").write_text("HookEvent again\n")
        result = await GrepTool(base_path=temp_dir).execute(pattern="HookEvent", path=".")
        assert result.success
        # Caption shape: ``N matches for 'HookEvent' across 2 file(s)``.
        assert result.caption is not None
        assert result.caption.startswith("2 matches for 'HookEvent' across 2 file(s)")

    @pytest.mark.asyncio
    async def test_grep_no_matches(self, temp_dir) -> None:
        (temp_dir / "a.py").write_text("nothing interesting\n")
        result = await GrepTool(base_path=temp_dir).execute(pattern="ZZZ_unmatched", path=".")
        assert result.success
        assert result.caption == "No matches for 'ZZZ_unmatched'"

    @pytest.mark.asyncio
    async def test_glob_with_matches(self, temp_dir) -> None:
        (temp_dir / "a.py").write_text("a")
        (temp_dir / "b.py").write_text("b")
        (temp_dir / "c.txt").write_text("c")
        result = await GlobTool(base_path=temp_dir).execute(pattern="*.py", path=".")
        assert result.success
        assert result.caption is not None
        assert result.caption.startswith("2 files matching '*.py'")

    @pytest.mark.asyncio
    async def test_glob_no_matches(self, temp_dir) -> None:
        result = await GlobTool(base_path=temp_dir).execute(pattern="*.never", path=".")
        assert result.success
        assert result.caption == "No files matching '*.never'"


# ===========================================================================
# Git
# ===========================================================================


class TestGitCaptions:
    @pytest.mark.asyncio
    async def test_clone_strips_protocol_and_dot_git(self, temp_dir) -> None:
        # Stub _run_git so the test doesn't actually clone anything.
        from cantrip.agent.tools import git as git_mod

        async def _run_clone(url: str) -> mock.MagicMock:
            tool = GitCloneTool()
            with mock.patch.object(
                git_mod,
                "_run_git",
                return_value=git_mod.ToolResult(success=True, output=""),
            ):
                return await tool.execute(url=url)

        result = await _run_clone("https://github.com/foo/bar.git")
        assert result.caption == "Cloned github.com/foo/bar"

        result = await _run_clone("git@github.com:foo/bar.git")
        assert result.caption == "Cloned github.com:foo/bar"

    @pytest.mark.asyncio
    async def test_commit_subject(self, temp_dir) -> None:
        # Initialise a git repo with a staged change.
        subprocess.run(["git", "init", "-q"], cwd=temp_dir, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=temp_dir,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_dir, check=True)
        (temp_dir / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_dir, check=True)

        result = await GitCommitTool().execute(
            message="Add a thing\n\nLong body that should be ignored.",
            path=str(temp_dir),
        )
        assert result.success
        assert result.caption == "Committed: 'Add a thing'"

    @pytest.mark.asyncio
    async def test_commit_long_subject_truncated(self, temp_dir) -> None:
        subprocess.run(["git", "init", "-q"], cwd=temp_dir, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=temp_dir,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_dir, check=True)
        (temp_dir / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_dir, check=True)

        long_msg = "A" * 80
        result = await GitCommitTool().execute(message=long_msg, path=str(temp_dir))
        assert result.success
        assert result.caption is not None
        assert "…" in result.caption

    @pytest.mark.asyncio
    async def test_push_caption(self) -> None:
        from cantrip.agent.tools import git as git_mod

        with mock.patch.object(
            git_mod,
            "_run_git",
            return_value=git_mod.ToolResult(success=True, output=""),
        ):
            result = await GitPushTool().execute(remote="origin", branch="main", confirmed=True)
        assert result.success
        assert result.caption == "Pushed → origin/main"

    @pytest.mark.asyncio
    async def test_push_caption_no_branch(self) -> None:
        from cantrip.agent.tools import git as git_mod

        with mock.patch.object(
            git_mod,
            "_run_git",
            return_value=git_mod.ToolResult(success=True, output=""),
        ):
            result = await GitPushTool().execute(remote="origin", confirmed=True)
        assert result.success
        assert result.caption == "Pushed → origin"


# ===========================================================================
# Charm tooling
# ===========================================================================


class TestCharmToolingCaptions:
    @pytest.mark.asyncio
    async def test_charmcraft_pack_caption(self, temp_dir) -> None:
        # Stub the subprocess call and pre-create a fake .charm file so the
        # tool's "find the created .charm" branch finds it.
        (temp_dir / "fake.charm").write_bytes(b"x" * (2 * 1024 * 1024))

        with mock.patch("cantrip.agent.tools.charm.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="ok", stderr="")
            result = await CharmcraftPackTool().execute(path=str(temp_dir))

        assert result.success
        assert result.caption is not None
        assert result.caption.startswith("Packed → fake.charm")
        assert "MB" in result.caption

    @pytest.mark.asyncio
    async def test_charmcraft_fetch_libs_count(self, temp_dir) -> None:
        with mock.patch("cantrip.agent.tools.charm.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout="Fetched library a.b\nFetched library c.d\n",
                stderr="",
            )
            result = await CharmcraftFetchLibsTool().execute(path=str(temp_dir))

        assert result.success
        assert result.caption == "Fetched 2 libs"
        assert result.data["fetched_count"] == 2

    @pytest.mark.asyncio
    async def test_charmcraft_fetch_libs_no_lines(self, temp_dir) -> None:
        with mock.patch("cantrip.agent.tools.charm.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
            result = await CharmcraftFetchLibsTool().execute(path=str(temp_dir))
        assert result.success
        assert result.caption == "Fetched libraries"

    @pytest.mark.asyncio
    async def test_charm_validate_caption(self, temp_dir) -> None:
        # CharmValidateTool runs RunCharmTestsTool + CharmcraftPackTool.
        # Stub both to deterministic passes.
        from cantrip.agent.tools import charm as charm_mod

        fake_tests_result = mock.AsyncMock(
            return_value=mock.MagicMock(
                success=True,
                output="passed",
                data={"summary": "12 passed"},
            )
        )
        fake_pack_result = mock.AsyncMock(
            return_value=mock.MagicMock(
                success=True,
                output="ok",
                data={"charm_file": str(temp_dir / "fake.charm")},
                error=None,
            )
        )
        with (
            mock.patch.object(charm_mod, "RunCharmTestsTool") as fake_tests_cls,
            mock.patch.object(charm_mod, "CharmcraftPackTool") as fake_pack_cls,
        ):
            fake_tests_cls.return_value.execute = fake_tests_result
            fake_pack_cls.return_value.execute = fake_pack_result
            (temp_dir / "fake.charm").write_text("x")
            result = await CharmValidateTool().execute(path=str(temp_dir))

        assert result.success
        assert result.caption is not None
        assert "charm_validate" in result.caption
        assert "PASSED" in result.caption
