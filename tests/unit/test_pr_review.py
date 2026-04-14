"""Tests for PR review tools (pr_review and pr_review_reply)."""

import json
import subprocess
from unittest import mock

import pytest

from cantrip.agent.tools.pr_review import (
    PrReviewReplyTool,
    PrReviewTool,
    _extract_comments,
    _format_comment,
)


class TestPrReviewToolProperties:
    """Tests for PrReviewTool metadata."""

    @pytest.fixture
    def tool(self):
        return PrReviewTool()

    def test_name(self, tool):
        assert tool.name == "pr_review"

    def test_required_params(self, tool):
        assert "repo" in tool.parameters["required"]
        assert "pr_number" in tool.parameters["required"]


class TestPrReviewReplyToolProperties:
    """Tests for PrReviewReplyTool metadata."""

    @pytest.fixture
    def tool(self):
        return PrReviewReplyTool()

    def test_name(self, tool):
        assert tool.name == "pr_review_reply"

    def test_required_params(self, tool):
        required = tool.parameters["required"]
        assert "repo" in required
        assert "pr_number" in required
        assert "comment_id" in required
        assert "body" in required


class TestExtractComments:
    """Tests for _extract_comments helper."""

    def test_extracts_fields(self):
        raw = [
            {
                "id": 123,
                "user": {"login": "alice"},
                "body": "Looks good",
                "path": "src/main.py",
                "line": 42,
                "side": "RIGHT",
                "in_reply_to_id": None,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]
        comments = _extract_comments(raw)
        assert len(comments) == 1
        assert comments[0]["id"] == 123
        assert comments[0]["author"] == "alice"
        assert comments[0]["body"] == "Looks good"
        assert comments[0]["path"] == "src/main.py"
        assert comments[0]["line"] == 42

    def test_missing_user(self):
        raw = [{"id": 1, "body": "test"}]
        comments = _extract_comments(raw)
        assert comments[0]["author"] == "unknown"

    def test_original_line_fallback(self):
        raw = [{"id": 1, "user": {"login": "bob"}, "body": "x", "original_line": 10}]
        comments = _extract_comments(raw)
        assert comments[0]["line"] == 10


class TestFormatComment:
    """Tests for _format_comment helper."""

    def test_basic_format(self):
        comment = {"author": "alice", "body": "Fix this", "path": "main.py", "line": 5}
        result = _format_comment(comment)
        assert "**alice**" in result
        assert "`main.py:5`" in result
        assert "Fix this" in result

    def test_no_path(self):
        comment = {"author": "bob", "body": "General note", "path": None, "line": None}
        result = _format_comment(comment)
        assert "**bob**" in result
        assert "General note" in result
        assert "`" not in result

    def test_reply_indicator(self):
        comment = {
            "author": "carol",
            "body": "Agreed",
            "path": None,
            "line": None,
            "in_reply_to_id": 456,
        }
        result = _format_comment(comment)
        assert "(reply to #456)" in result


class TestPrReviewToolExecution:
    """Tests for PrReviewTool.execute."""

    @pytest.fixture
    def tool(self):
        return PrReviewTool()

    @pytest.mark.asyncio
    async def test_gh_not_installed(self, tool):
        with mock.patch("cantrip.agent.tools.pr_review.shutil.which", return_value=None):
            result = await tool.execute(repo="owner/repo", pr_number=1)
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_gh_not_authenticated(self, tool):
        auth_result = mock.MagicMock()
        auth_result.returncode = 1
        with (
            mock.patch(
                "cantrip.agent.tools.pr_review.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.pr_review.subprocess.run",
                return_value=auth_result,
            ),
        ):
            result = await tool.execute(repo="owner/repo", pr_number=1)
        assert not result.success
        assert "authenticated" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fetch_comments_success(self, tool):
        auth_result = mock.MagicMock()
        auth_result.returncode = 0

        api_result = mock.MagicMock()
        api_result.returncode = 0
        api_result.stdout = json.dumps(
            [
                {
                    "id": 100,
                    "user": {"login": "reviewer"},
                    "body": "Please refactor this",
                    "path": "src/app.py",
                    "line": 15,
                    "side": "RIGHT",
                    "in_reply_to_id": None,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                },
            ]
        )

        call_count = 0

        def mock_run(_cmd, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return auth_result
            return api_result

        with (
            mock.patch(
                "cantrip.agent.tools.pr_review.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.pr_review.subprocess.run",
                side_effect=mock_run,
            ),
        ):
            result = await tool.execute(repo="owner/repo", pr_number=42)

        assert result.success
        assert "reviewer" in result.output
        assert "Please refactor this" in result.output
        assert result.data["count"] == 1

    @pytest.mark.asyncio
    async def test_no_comments(self, tool):
        auth_result = mock.MagicMock()
        auth_result.returncode = 0

        api_result = mock.MagicMock()
        api_result.returncode = 0
        api_result.stdout = "[]"

        call_count = 0

        def mock_run(_cmd, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return auth_result
            return api_result

        with (
            mock.patch(
                "cantrip.agent.tools.pr_review.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.pr_review.subprocess.run",
                side_effect=mock_run,
            ),
        ):
            result = await tool.execute(repo="owner/repo", pr_number=1)

        assert result.success
        assert "No review comments" in result.output
        assert result.data["count"] == 0

    @pytest.mark.asyncio
    async def test_api_failure(self, tool):
        auth_result = mock.MagicMock()
        auth_result.returncode = 0

        api_result = mock.MagicMock()
        api_result.returncode = 1
        api_result.stderr = "Not Found"
        api_result.stdout = ""

        call_count = 0

        def mock_run(_cmd, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return auth_result
            return api_result

        with (
            mock.patch(
                "cantrip.agent.tools.pr_review.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.pr_review.subprocess.run",
                side_effect=mock_run,
            ),
        ):
            result = await tool.execute(repo="owner/repo", pr_number=999)

        assert not result.success
        assert "Not Found" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        auth_result = mock.MagicMock()
        auth_result.returncode = 0

        call_count = 0

        def mock_run(cmd, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return auth_result
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

        with (
            mock.patch(
                "cantrip.agent.tools.pr_review.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.pr_review.subprocess.run",
                side_effect=mock_run,
            ),
        ):
            result = await tool.execute(repo="owner/repo", pr_number=1)

        assert not result.success
        assert "timed out" in result.error.lower()


class TestPrReviewReplyToolExecution:
    """Tests for PrReviewReplyTool.execute."""

    @pytest.fixture
    def tool(self):
        return PrReviewReplyTool()

    @pytest.mark.asyncio
    async def test_gh_not_installed(self, tool):
        with mock.patch("cantrip.agent.tools.pr_review.shutil.which", return_value=None):
            result = await tool.execute(
                repo="owner/repo",
                pr_number=1,
                comment_id=100,
                body="Done",
            )
        assert not result.success

    @pytest.mark.asyncio
    async def test_reply_success(self, tool):
        auth_result = mock.MagicMock()
        auth_result.returncode = 0

        api_result = mock.MagicMock()
        api_result.returncode = 0
        api_result.stdout = json.dumps({"id": 200})

        call_count = 0

        def mock_run(_cmd, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return auth_result
            return api_result

        with (
            mock.patch(
                "cantrip.agent.tools.pr_review.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.pr_review.subprocess.run",
                side_effect=mock_run,
            ) as mock_subproc,
        ):
            result = await tool.execute(
                repo="owner/repo",
                pr_number=42,
                comment_id=100,
                body="Fixed!",
            )

        assert result.success
        assert "Reply posted" in result.output
        assert result.data["comment_id"] == 100

        # Verify the API call passed the body as JSON via stdin.
        api_call = mock_subproc.call_args_list[-1]
        assert api_call.kwargs.get("input") == json.dumps({"body": "Fixed!"})

    @pytest.mark.asyncio
    async def test_reply_api_failure(self, tool):
        auth_result = mock.MagicMock()
        auth_result.returncode = 0

        api_result = mock.MagicMock()
        api_result.returncode = 1
        api_result.stderr = "Forbidden"
        api_result.stdout = ""

        call_count = 0

        def mock_run(_cmd, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return auth_result
            return api_result

        with (
            mock.patch(
                "cantrip.agent.tools.pr_review.shutil.which",
                return_value="/usr/bin/gh",
            ),
            mock.patch(
                "cantrip.agent.tools.pr_review.subprocess.run",
                side_effect=mock_run,
            ),
        ):
            result = await tool.execute(
                repo="owner/repo",
                pr_number=1,
                comment_id=100,
                body="test",
            )

        assert not result.success
        assert "Forbidden" in result.error
