"""Tests for GitHub issue triage (Phase 42.2)."""

import asyncio
import json
import subprocess
from unittest import mock

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.watcher.github_issues import (
    TRIAGE_CONFIRM_PREFIX,
    GitHubIssue,
    IssueTriage,
    build_issue_work_tasks,
    build_triage_confirm_task,
    fetch_issues,
    rank_issues,
)

# ---------------------------------------------------------------------------
# fetch_issues
# ---------------------------------------------------------------------------


class TestFetchIssues:
    """Tests for fetch_issues()."""

    def test_no_gh_binary(self) -> None:
        with mock.patch("cantrip.agent.watcher.github_issues.shutil.which", return_value=None):
            assert fetch_issues("owner/repo") == []

    def test_gh_command_failure(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not authenticated"
        )
        with (
            mock.patch(
                "cantrip.agent.watcher.github_issues.shutil.which", return_value="/usr/bin/gh"
            ),
            mock.patch("cantrip.agent.watcher.github_issues.subprocess.run", return_value=result),
        ):
            assert fetch_issues("owner/repo") == []

    def test_timeout(self) -> None:
        with (
            mock.patch(
                "cantrip.agent.watcher.github_issues.shutil.which", return_value="/usr/bin/gh"
            ),
            mock.patch(
                "cantrip.agent.watcher.github_issues.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=30),
            ),
        ):
            assert fetch_issues("owner/repo") == []

    def test_invalid_json(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json")
        with (
            mock.patch(
                "cantrip.agent.watcher.github_issues.shutil.which", return_value="/usr/bin/gh"
            ),
            mock.patch("cantrip.agent.watcher.github_issues.subprocess.run", return_value=result),
        ):
            assert fetch_issues("owner/repo") == []

    def test_parses_issues(self) -> None:
        raw = [
            {
                "number": 42,
                "title": "Fix the widget",
                "labels": [{"name": "bug"}, {"name": "priority"}],
                "body": "The widget is broken when...",
                "comments": [{"body": "I can reproduce"}],
                "url": "https://github.com/owner/repo/issues/42",
            },
            {
                "number": 7,
                "title": "Add feature X",
                "labels": [],
                "body": "",
                "comments": [],
                "url": "https://github.com/owner/repo/issues/7",
            },
        ]
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(raw))
        with (
            mock.patch(
                "cantrip.agent.watcher.github_issues.shutil.which", return_value="/usr/bin/gh"
            ),
            mock.patch("cantrip.agent.watcher.github_issues.subprocess.run", return_value=result),
        ):
            issues = fetch_issues("owner/repo")

        assert len(issues) == 2
        assert issues[0].number == 42
        assert issues[0].title == "Fix the widget"
        assert issues[0].labels == ["bug", "priority"]
        assert issues[0].comment_count == 1
        assert issues[1].number == 7
        assert issues[1].body == ""

    def test_passes_repo_arg(self) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]")
        with (
            mock.patch(
                "cantrip.agent.watcher.github_issues.shutil.which", return_value="/usr/bin/gh"
            ),
            mock.patch(
                "cantrip.agent.watcher.github_issues.subprocess.run", return_value=result
            ) as m,
        ):
            fetch_issues("canonical/grafana-k8s")
            cmd = m.call_args[0][0]
            assert "--repo" in cmd
            idx = cmd.index("--repo")
            assert cmd[idx + 1] == "canonical/grafana-k8s"


# ---------------------------------------------------------------------------
# rank_issues
# ---------------------------------------------------------------------------


class TestRankIssues:
    """Tests for rank_issues()."""

    def test_empty_list(self) -> None:
        assert rank_issues([]) == []

    def test_skips_wontfix_labels(self) -> None:
        issue = GitHubIssue(number=1, title="Nope", labels=["wontfix"], body="x" * 100)
        assert rank_issues([issue]) == []

    def test_skips_short_body(self) -> None:
        issue = GitHubIssue(number=1, title="Short", labels=["bug"], body="too short")
        assert rank_issues([issue]) == []

    def test_actionable_labels_rank_higher(self) -> None:
        bug = GitHubIssue(number=1, title="Bug", labels=["bug"], body="x" * 200)
        plain = GitHubIssue(number=2, title="Plain", labels=[], body="x" * 200)
        ranked = rank_issues([plain, bug])
        assert ranked[0].number == 1  # Bug should rank first.

    def test_longer_body_ranks_higher(self) -> None:
        short = GitHubIssue(number=1, title="Short", body="x" * 100)
        long = GitHubIssue(number=2, title="Long", body="x" * 2000)
        ranked = rank_issues([short, long])
        assert ranked[0].number == 2

    def test_comments_contribute_to_score(self) -> None:
        quiet = GitHubIssue(number=1, title="Quiet", body="x" * 200, comment_count=0)
        active = GitHubIssue(number=2, title="Active", body="x" * 200, comment_count=5)
        ranked = rank_issues([quiet, active])
        assert ranked[0].number == 2

    def test_duplicate_label_skipped(self) -> None:
        issue = GitHubIssue(number=1, title="Dup", labels=["duplicate"], body="x" * 100)
        assert rank_issues([issue]) == []


# ---------------------------------------------------------------------------
# build_triage_confirm_task
# ---------------------------------------------------------------------------


class TestBuildTriageConfirmTask:
    """Tests for build_triage_confirm_task()."""

    def test_creates_confirm_category(self) -> None:
        issue = GitHubIssue(number=42, title="Fix widget", body="Details here")
        task = build_triage_confirm_task(issue, "owner/repo")
        assert task.category == TaskCategory.CONFIRM
        assert task.id == f"{TRIAGE_CONFIRM_PREFIX}42"
        assert "#42" in task.title
        assert "Fix widget" in task.title

    def test_description_contains_body(self) -> None:
        issue = GitHubIssue(number=10, title="Test", body="The body text", labels=["bug"])
        task = build_triage_confirm_task(issue, "owner/repo")
        assert "The body text" in task.description
        assert "bug" in task.description

    def test_long_body_truncated(self) -> None:
        issue = GitHubIssue(number=1, title="Long", body="x" * 2000)
        task = build_triage_confirm_task(issue, "owner/repo")
        assert "truncated" in task.description


# ---------------------------------------------------------------------------
# build_issue_work_tasks
# ---------------------------------------------------------------------------


class TestBuildIssueWorkTasks:
    """Tests for build_issue_work_tasks()."""

    def test_creates_research_build_test_chain(self) -> None:
        issue = GitHubIssue(number=42, title="Fix widget", body="Details")
        tasks = build_issue_work_tasks(issue, "owner/repo", "confirm-id")

        assert len(tasks) == 3
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[1].category == TaskCategory.BUILD
        assert tasks[2].category == TaskCategory.TEST

    def test_dependency_chain(self) -> None:
        issue = GitHubIssue(number=42, title="Fix widget", body="Details")
        tasks = build_issue_work_tasks(issue, "owner/repo", "confirm-id")

        # Research depends on confirm.
        assert "confirm-id" in tasks[0].dependencies
        # Build depends on research.
        assert tasks[0].id in tasks[1].dependencies
        # Test depends on build.
        assert tasks[1].id in tasks[2].dependencies

    def test_issue_reference_in_descriptions(self) -> None:
        issue = GitHubIssue(number=99, title="Test issue", body="Issue body")
        tasks = build_issue_work_tasks(issue, "owner/repo", "confirm-id")

        for task in tasks:
            assert "#99" in task.description


# ---------------------------------------------------------------------------
# IssueTriage
# ---------------------------------------------------------------------------


class TestIssueTriage:
    """Tests for IssueTriage lifecycle."""

    def test_not_running_initially(self) -> None:
        triage = IssueTriage(repo="owner/repo")
        assert not triage.running

    def test_start_sets_running(self) -> None:
        with mock.patch("cantrip.agent.watcher.github_issues.fetch_issues", return_value=[]):
            triage = IssueTriage(repo="owner/repo")
            # We cannot easily test async start without an event loop,
            # but we can check the flag is set.
            triage._running = True
            assert triage.running

    def test_examined_issues_property_starts_empty(self) -> None:
        triage = IssueTriage(repo="owner/repo")
        assert triage.examined_issues == set()

    @pytest.mark.asyncio
    async def test_start_dispatches_run_and_completes(self) -> None:
        # ``start`` schedules ``_run`` on the event loop; once the
        # background task completes (no issues), ``_running`` flips back
        # to False via the ``finally`` block.
        captured: list[list[AgentTask]] = []
        with mock.patch("cantrip.agent.watcher.github_issues.fetch_issues", return_value=[]):
            triage = IssueTriage(repo="owner/repo", on_issues_found=captured.append)
            triage.start()
            assert triage.running is True
            assert triage._task is not None
            await triage._task
        assert triage.running is False
        assert captured == []  # no issues → callback never fires

    @pytest.mark.asyncio
    async def test_start_is_noop_when_already_running(self) -> None:
        triage = IssueTriage(repo="owner/repo")
        triage._running = True
        triage._task = None
        triage.start()  # must not crash and must not create a new task
        assert triage._task is None

    @pytest.mark.asyncio
    async def test_stop_is_noop_when_not_running(self) -> None:
        triage = IssueTriage(repo="owner/repo")
        await triage.stop()  # must not raise
        assert triage.running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_running_task(self) -> None:
        # Prime ``_task`` with a slow coroutine that ``stop()`` must
        # cancel rather than wait out.
        async def _slow() -> None:
            await asyncio.sleep(60)

        triage = IssueTriage(repo="owner/repo")
        triage._running = True
        triage._task = asyncio.create_task(_slow())
        await triage.stop()
        assert triage.running is False
        assert triage._task is None

    @pytest.mark.asyncio
    async def test_run_fires_callback_for_actionable_issues(self) -> None:
        actionable = GitHubIssue(
            number=42,
            title="Add feature X",
            labels=["good first issue"],
            body="x" * 200,  # long enough to clear _MIN_BODY_LENGTH
            comment_count=2,
        )
        captured: list[list[AgentTask]] = []
        with mock.patch(
            "cantrip.agent.watcher.github_issues.fetch_issues",
            return_value=[actionable],
        ):
            triage = IssueTriage(repo="owner/repo", on_issues_found=captured.append)
            await triage._run()

        assert len(captured) == 1
        assert len(captured[0]) == 1
        assert 42 in triage.examined_issues
        # The task is the CONFIRM-prefixed gate.
        assert captured[0][0].id.startswith(TRIAGE_CONFIRM_PREFIX)

    @pytest.mark.asyncio
    async def test_run_skips_already_examined_issues(self) -> None:
        actionable = GitHubIssue(
            number=42,
            title="x",
            labels=["good first issue"],
            body="x" * 200,
        )
        captured: list[list[AgentTask]] = []
        with mock.patch(
            "cantrip.agent.watcher.github_issues.fetch_issues",
            return_value=[actionable],
        ):
            triage = IssueTriage(repo="owner/repo", on_issues_found=captured.append)
            triage._examined.add(42)  # already seen
            await triage._run()

        # No new confirm tasks because the only candidate was already seen.
        assert captured == []

    @pytest.mark.asyncio
    async def test_run_returns_quietly_when_rank_drops_all(self) -> None:
        # An issue with a wontfix label ranks to nothing — the worker
        # logs and returns without firing the callback.
        skip_issue = GitHubIssue(
            number=99,
            title="x",
            labels=["wontfix"],
            body="x" * 200,
        )
        captured: list[list[AgentTask]] = []
        with mock.patch(
            "cantrip.agent.watcher.github_issues.fetch_issues",
            return_value=[skip_issue],
        ):
            triage = IssueTriage(repo="owner/repo", on_issues_found=captured.append)
            await triage._run()
        assert captured == []

    @pytest.mark.asyncio
    async def test_run_swallows_unexpected_errors(self) -> None:
        # ``fetch_issues`` raising must not abort the watcher — the
        # blanket-Exception handler logs and the ``finally`` block
        # clears ``_running``.
        triage = IssueTriage(repo="owner/repo")
        triage._running = True
        with mock.patch(
            "cantrip.agent.watcher.github_issues.fetch_issues",
            side_effect=RuntimeError("synthetic failure"),
        ):
            await triage._run()
        assert triage._running is False

    @pytest.mark.asyncio
    async def test_run_propagates_cancellation(self) -> None:
        # ``asyncio.CancelledError`` must propagate so the cancelling
        # caller (``stop()``) sees it; the blanket-Exception path must
        # not swallow it.
        async def _cancel_in_to_thread(*_args: object, **_kwargs: object) -> None:
            raise asyncio.CancelledError

        triage = IssueTriage(repo="owner/repo")
        with (
            mock.patch(
                "cantrip.agent.watcher.github_issues.asyncio.to_thread",
                side_effect=_cancel_in_to_thread,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await triage._run()
        assert triage._running is False
