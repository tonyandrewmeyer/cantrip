"""Tests for new Juju and git tools (Phase 30.2 and 30.3)."""

import subprocess
from unittest import mock

import pytest

from cantrip.agent.tools.git import GitBranchTool, GitCheckoutTool, GitStashTool
from cantrip.agent.tools.github import GhPrListTool, GhPrViewTool

# ---------------------------------------------------------------------------
# GitBranchTool
# ---------------------------------------------------------------------------


class TestGitBranchTool:
    """Tests for GitBranchTool."""

    @pytest.mark.asyncio
    async def test_list_branches(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="* main\n  feature\n")
        with mock.patch("cantrip.agent.tools.git.subprocess.run", return_value=result):
            tool = GitBranchTool()
            r = await tool.execute()
            assert r.success
            assert "main" in r.output

    @pytest.mark.asyncio
    async def test_create_branch(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch("cantrip.agent.tools.git.subprocess.run", return_value=result) as m:
            tool = GitBranchTool()
            r = await tool.execute(name="feature/new")
            assert r.success
            cmd = m.call_args[0][0]
            assert cmd == ["git", "checkout", "-b", "feature/new"]


# ---------------------------------------------------------------------------
# GitCheckoutTool
# ---------------------------------------------------------------------------


class TestGitCheckoutTool:
    """Tests for GitCheckoutTool."""

    @pytest.mark.asyncio
    async def test_switch_branch(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch("cantrip.agent.tools.git.subprocess.run", return_value=result) as m:
            tool = GitCheckoutTool()
            r = await tool.execute(branch="main")
            assert r.success
            cmd = m.call_args[0][0]
            assert cmd == ["git", "checkout", "main"]

    @pytest.mark.asyncio
    async def test_nonexistent_branch(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error: pathspec 'nope' did not match"
        )
        with mock.patch("cantrip.agent.tools.git.subprocess.run", return_value=result):
            tool = GitCheckoutTool()
            r = await tool.execute(branch="nope")
            assert not r.success


# ---------------------------------------------------------------------------
# GitStashTool
# ---------------------------------------------------------------------------


class TestGitStashTool:
    """Tests for GitStashTool."""

    @pytest.mark.asyncio
    async def test_push(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Saved working directory"
        )
        with mock.patch("cantrip.agent.tools.git.subprocess.run", return_value=result):
            tool = GitStashTool()
            r = await tool.execute(action="push")
            assert r.success

    @pytest.mark.asyncio
    async def test_push_with_message(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Saved")
        with mock.patch("cantrip.agent.tools.git.subprocess.run", return_value=result) as m:
            tool = GitStashTool()
            await tool.execute(action="push", message="WIP")
            cmd = m.call_args[0][0]
            assert "-m" in cmd
            assert "WIP" in cmd

    @pytest.mark.asyncio
    async def test_pop(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Restored")
        with mock.patch("cantrip.agent.tools.git.subprocess.run", return_value=result):
            tool = GitStashTool()
            r = await tool.execute(action="pop")
            assert r.success

    @pytest.mark.asyncio
    async def test_list(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch("cantrip.agent.tools.git.subprocess.run", return_value=result):
            tool = GitStashTool()
            r = await tool.execute(action="list")
            assert r.success
            assert "No stashes" in r.output

    @pytest.mark.asyncio
    async def test_invalid_action(self) -> None:
        tool = GitStashTool()
        r = await tool.execute(action="invalid")
        assert not r.success
        assert "Unknown" in r.error


# ---------------------------------------------------------------------------
# GhPrListTool
# ---------------------------------------------------------------------------


class TestGhPrListTool:
    """Tests for GhPrListTool."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="#1\tFix bug\tOPEN\n")
        with (
            mock.patch("cantrip.agent.tools.github.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.tools.github._check_gh_auth", return_value=None),
            mock.patch("cantrip.agent.tools.github.subprocess.run", return_value=result),
        ):
            tool = GhPrListTool()
            r = await tool.execute()
            assert r.success
            assert "Fix bug" in r.output

    @pytest.mark.asyncio
    async def test_no_gh(self) -> None:
        with mock.patch("cantrip.agent.tools.github.shutil.which", return_value=None):
            tool = GhPrListTool()
            r = await tool.execute()
            assert not r.success


# ---------------------------------------------------------------------------
# GhPrViewTool
# ---------------------------------------------------------------------------


class TestGhPrViewTool:
    """Tests for GhPrViewTool."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        import json

        data = {
            "number": 42,
            "title": "Fix the widget",
            "state": "OPEN",
            "author": {"login": "user"},
            "reviewDecision": "APPROVED",
            "url": "https://github.com/o/r/pull/42",
            "headRefName": "fix-widget",
            "baseRefName": "main",
            "body": "Description here",
        }
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(data))
        with (
            mock.patch("cantrip.agent.tools.github.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.tools.github._check_gh_auth", return_value=None),
            mock.patch("cantrip.agent.tools.github.subprocess.run", return_value=result),
        ):
            tool = GhPrViewTool()
            r = await tool.execute(pr_number=42)
            assert r.success
            assert "Fix the widget" in r.output
            assert "APPROVED" in r.output
            assert r.data["number"] == 42

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Could not resolve"
        )
        with (
            mock.patch("cantrip.agent.tools.github.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("cantrip.agent.tools.github._check_gh_auth", return_value=None),
            mock.patch("cantrip.agent.tools.github.subprocess.run", return_value=result),
        ):
            tool = GhPrViewTool()
            r = await tool.execute(pr_number=999)
            assert not r.success
