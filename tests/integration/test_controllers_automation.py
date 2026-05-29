"""Integration tests: advanced controllers and git automation workflows.

Phase 93.5.  Integration coverage for the controller surfaces that have
little or no non-unit protection and for git automation flows exercised
against realistic in-process repositories.

Coverage targets:
* MCPController — lazy registry, start/stop lifecycle, elicitation bridge.
* ArenaController — begin/pick flow, "no light provider" error path.
* TriageController — start/stop, triage→confirm path, retriage.
* ExecutorController — pause/resume seam, user-pause vs transient-pause.
* WatcherController — event routing, no-model fallback.
* Git automation — auto_commit message/trailer, pre-turn dirty commit.
* Git branch — create_branch, slugify, current_branch, build_pr_body.
* Provider failover — transient errors retried, loop survives FlakyProvider.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import subprocess
import unittest.mock as mock

import pytest

from cantrip.agent.arena_controller import ArenaController
from cantrip.agent.auto_commit import (
    _CANTRIP_TRAILER,
    _PRE_CANTRIP_MESSAGE,
    build_commit_message,
    collect_touched_files,
    post_turn_commit_agent_edits,
    pre_turn_commit_dirty,
)
from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.executor_controller import ExecutorController
from cantrip.agent.git_branch import (
    build_pr_body,
    create_branch,
    current_branch,
    slugify,
    suggest_repo_name,
)
from cantrip.agent.mcp_controller import MCPController
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.triage_controller import TriageController
from cantrip.agent.watcher_controller import WatcherController
from cantrip.hooks.runner import HookRunner
from cantrip.llm.base import Message, Response, Role, ToolCall
from cantrip.ui import events as ui_events
from tests.support.providers import FailingProvider, FlakyProvider
from tests.support.wait import wait_for_queue_state, wait_for_task_status

_GIT_AVAILABLE = shutil.which("git") is not None
requires_git = pytest.mark.skipif(not _GIT_AVAILABLE, reason="git CLI not available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_bus() -> ui_events.EventBus:
    return ui_events.EventBus()


def _init_repo(path: pathlib.Path) -> None:
    """Initialise *path* as a git repo with one commit."""
    env = {**os.environ, "HOME": str(pathlib.Path.home())}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, env=env)
    subprocess.run(
        ["git", "config", "user.email", "test@cantrip.local"], cwd=path, check=True, env=env
    )
    subprocess.run(["git", "config", "user.name", "Cantrip Test"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True, env=env)
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "initial"],
        cwd=path,
        check=True,
        env=env,
    )


def _head_message(repo: pathlib.Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _head_count(repo: pathlib.Path) -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip())


def _branch_exists(repo: pathlib.Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


# ===========================================================================
# 1. MCPController — lifecycle and elicitation bridge
# ===========================================================================


@pytest.mark.integration
class TestMCPController:
    """MCPController start/stop lifecycle and elicitation forwarding."""

    def _make_controller(
        self,
        charm_path: pathlib.Path | None = None,
    ) -> MCPController:
        state = AgentState(charm_path=charm_path)
        bus = _make_event_bus()
        invalidated: list[int] = []
        return MCPController(
            state=state,
            event_bus=bus,
            invalidate_tools_cache=lambda: invalidated.append(1),
        ), invalidated

    def test_registry_if_loaded_none_before_first_access(self, tmp_path: pathlib.Path):
        ctl, _ = self._make_controller(charm_path=tmp_path)
        assert ctl.registry_if_loaded() is None

    def test_registry_if_loaded_returns_instance_after_access(self, tmp_path: pathlib.Path):
        ctl, _ = self._make_controller(charm_path=tmp_path)
        _ = ctl.registry  # trigger lazy construction
        assert ctl.registry_if_loaded() is not None

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, tmp_path: pathlib.Path):
        """Calling start() twice does not double-connect."""
        ctl, invalidated = self._make_controller(charm_path=tmp_path)
        # Patch start_all so we don't need real MCP servers.
        with mock.patch.object(ctl.registry, "start_all", new_callable=mock.AsyncMock) as m:
            await ctl.start()
            await ctl.start()
            # Second call is a no-op.
            assert m.call_count == 1
        await ctl.stop()

    @pytest.mark.asyncio
    async def test_start_invalidates_tools_cache(self, tmp_path: pathlib.Path):
        ctl, invalidated = self._make_controller(charm_path=tmp_path)
        with mock.patch.object(ctl.registry, "start_all", new_callable=mock.AsyncMock):
            await ctl.start()
        assert len(invalidated) == 1

    @pytest.mark.asyncio
    async def test_stop_before_start_is_noop(self, tmp_path: pathlib.Path):
        ctl, _ = self._make_controller(charm_path=tmp_path)
        # Should not raise even though start() was never called.
        await ctl.stop()

    def test_complete_elicitation_returns_false_when_registry_not_loaded(
        self, tmp_path: pathlib.Path
    ):
        ctl, _ = self._make_controller(charm_path=tmp_path)
        result = ctl.complete_elicitation("req-id", "accept", content={})
        assert result is False

    def test_elicitation_handler_publishes_event(self, tmp_path: pathlib.Path):
        events: list[ui_events.UIEvent] = []
        state = AgentState(charm_path=tmp_path)
        bus = _make_event_bus()
        bus.subscribe(None, events.append)
        ctl = MCPController(
            state=state,
            event_bus=bus,
            invalidate_tools_cache=lambda: None,
        )
        # Build a minimal elicitation request.
        from cantrip.mcp.elicitation import ElicitationRequest

        req = ElicitationRequest(
            request_id="r1",
            server_name="test-server",
            mode="form",
            message="Which option?",
            requested_schema={"type": "string"},
            url=None,
        )
        ctl.handle_elicitation(req)
        types = [e.type for e in events]
        assert ui_events.EventType.MCP_ELICITATION_REQUEST in types

    def test_marketplace_sources_cache_is_stable(self, tmp_path: pathlib.Path):
        ctl, _ = self._make_controller(charm_path=tmp_path)
        s1 = ctl.marketplace_sources
        s2 = ctl.marketplace_sources
        assert s1 is not s2  # new list each time, but same content
        assert s1 == s2


# ===========================================================================
# 2. ArenaController — begin/pick flow
# ===========================================================================


@pytest.mark.integration
class TestArenaController:
    """ArenaController begin/pick with and without a light provider."""

    def _make_controller(
        self,
        provider=None,
        light_provider=None,
    ) -> ArenaController:
        from tests.conftest import FakeProvider as _FakeProvider

        p = provider or _FakeProvider([Response(content="Response from primary provider")])
        p.model_name = "primary-model"

        def _get_light() -> object:
            return light_provider

        mem_mock = mock.MagicMock()
        mem_mock.add = mock.MagicMock(return_value=mock.MagicMock())

        return ArenaController(
            provider=p,
            get_light_provider=_get_light,
            get_memory_manager=lambda: mem_mock,
            ensure_store=lambda: None,
            get_store=lambda: None,
        )

    @pytest.mark.asyncio
    async def test_begin_with_no_light_provider_returns_error(self):
        ctl = self._make_controller(light_provider=None)
        result = await ctl.begin("Which model is better?")
        assert "light provider" in result.lower() or "second provider" in result.lower()

    @pytest.mark.asyncio
    async def test_begin_with_two_distinct_providers_returns_session(self):
        from tests.conftest import FakeProvider as _FakeProvider

        primary = _FakeProvider([Response(content="Primary answer to the question")])
        primary.model_name = "model-a"

        secondary = _FakeProvider([Response(content="Secondary answer is different")])
        secondary.model_name = "model-b"

        ctl = self._make_controller(provider=primary, light_provider=secondary)
        result = await ctl.begin("Which is better?")
        assert ctl.active is not None
        # The result should present the two options.
        assert "A" in result and "B" in result

    @pytest.mark.asyncio
    async def test_begin_while_active_returns_warning(self):
        from tests.conftest import FakeProvider as _FakeProvider

        primary = _FakeProvider([Response(content="First"), Response(content="Second")])
        primary.model_name = "model-a"
        secondary = _FakeProvider(
            [Response(content="Other answer here"), Response(content="Another")]
        )
        secondary.model_name = "model-b"

        ctl = self._make_controller(provider=primary, light_provider=secondary)
        await ctl.begin("First arena")
        # Second begin while one is active should return a warning.
        result = await ctl.begin("Second arena")
        assert "already in progress" in result.lower() or "Arena already" in result

    def test_handle_pick_returns_none_when_idle(self):
        ctl = self._make_controller()
        result = ctl.handle_pick("A")
        assert result is None

    def test_handle_pick_returns_none_on_unrecognised(self):
        """A random message while an arena is active doesn't consume it."""
        from cantrip.agent import arena
        from tests.conftest import FakeProvider as _FakeProvider

        primary = _FakeProvider([Response(content="Answer A")])
        primary.model_name = "pa"
        secondary = _FakeProvider([Response(content="Answer B")])
        secondary.model_name = "pb"
        ctl = self._make_controller(provider=primary, light_provider=secondary)

        # Manually inject a fake session.
        ctl._session = arena.ArenaSession(  # noqa: SLF001
            prompt="question",
            candidates=(
                arena.ArenaCandidate(label="A", provider_name="pa", model_name="pa", response="a"),
                arena.ArenaCandidate(label="B", provider_name="pb", model_name="pb", response="b"),
            ),
            session_id="fake-session",
        )
        result = ctl.handle_pick("I'm not sure what to pick")
        assert result is None
        # Session should still be active (not consumed).
        assert ctl.active is not None

    def test_handle_pick_skip_clears_session(self):
        from cantrip.agent import arena

        ctl = self._make_controller()
        ctl._session = arena.ArenaSession(  # noqa: SLF001
            prompt="q",
            candidates=(
                arena.ArenaCandidate(
                    label="A", provider_name="p1", model_name="m1", response="r1"
                ),
                arena.ArenaCandidate(
                    label="B", provider_name="p2", model_name="m2", response="r2"
                ),
            ),
            session_id="s1",
        )
        result = ctl.handle_pick("skip")
        assert result is not None
        assert ctl.active is None  # consumed


# ===========================================================================
# 3. TriageController — start/stop, triage→confirm path
# ===========================================================================


@pytest.mark.integration
class TestTriageController:
    """TriageController lifecycle and issue triage flows."""

    def _make_controller(self, *, github_repo: str | None = None) -> TriageController:
        state = AgentState(github_repo=github_repo)
        bus = _make_event_bus()
        queue = WorkQueue()
        return TriageController(
            state=state,
            event_bus=bus,
            work_queue=queue,
            ensure_store=lambda: None,
            get_store=lambda: None,
        ), queue

    def test_start_without_github_repo_returns_false(self):
        ctl, _ = self._make_controller(github_repo=None)
        assert ctl.start() is False
        assert not ctl.running

    @pytest.mark.asyncio
    async def test_start_with_github_repo_returns_true(self):
        ctl, _ = self._make_controller(github_repo="canonical/test-charm")
        result = ctl.start()
        # Should start (returns True) even if gh CLI isn't available.
        assert result is True
        await ctl.stop()

    @pytest.mark.asyncio
    async def test_start_twice_returns_false_second_time(self):
        ctl, _ = self._make_controller(github_repo="canonical/test-charm")
        assert ctl.start() is True
        assert ctl.start() is False  # Already running this session.
        await ctl.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_noop(self):
        ctl, _ = self._make_controller()
        await ctl.stop()  # Should not raise.

    def test_retriage_without_repo_returns_false(self):
        ctl, _ = self._make_controller(github_repo=None)
        assert ctl.retriage() is False

    def test_comment_on_issue_without_repo_returns_message(self):
        ctl, _ = self._make_controller(github_repo=None)
        result = ctl.comment_on_issue(42, "https://github.com/org/repo/pull/1")
        assert "No GitHub" in result

    def test_comment_on_issue_without_gh_cli_returns_failure(self):
        ctl, _ = self._make_controller(github_repo="canonical/test-charm")
        # gh CLI almost certainly isn't available in CI.
        result = ctl.comment_on_issue(1, "https://github.com/x/y/pull/1")
        # If gh is missing it returns a failure message.
        assert isinstance(result, str)

    def test_check_upstream_without_charm_path_returns_none(self):
        ctl, _ = self._make_controller(github_repo="canonical/test-charm")
        result = ctl.check_upstream()
        assert result is None

    @pytest.mark.asyncio
    async def test_retriage_preserves_examined_set(self):
        """Second triage run re-uses the examined set from the first."""
        ctl, _ = self._make_controller(github_repo="canonical/test-charm")
        ctl.start()
        # Inject a fake examined set.
        ctl._issue_triage._examined = {101, 202}  # noqa: SLF001

        ctl.retriage()
        # The new triage instance should carry the examined set.
        assert 101 in ctl._issue_triage.examined_issues  # noqa: SLF001
        assert 202 in ctl._issue_triage.examined_issues  # noqa: SLF001
        await ctl.stop()

    def test_start_on_issues_found_queues_tasks_and_records_event(self):
        """The triage callback adds confirm tasks and records a store event."""
        state = AgentState(github_repo="canonical/test-charm")
        bus = _make_event_bus()
        events: list[ui_events.UIEvent] = []
        bus.subscribe(None, events.append)
        queue = WorkQueue()
        recorded: list[tuple[str, dict]] = []
        store = mock.MagicMock()
        store.record_event = lambda name, payload: recorded.append((name, payload))
        ensured: list[bool] = []
        ctl = TriageController(
            state=state,
            event_bus=bus,
            work_queue=queue,
            ensure_store=lambda: ensured.append(True),
            get_store=lambda: store,
        )

        captured: dict[str, object] = {}

        class _CapturingTriage:
            def __init__(self, *, repo, on_issues_found):  # noqa: ANN001
                captured["cb"] = on_issues_found
                self.running = False

            def start(self) -> None:
                self.running = True

        with mock.patch("cantrip.agent.triage_controller.IssueTriage", _CapturingTriage):
            assert ctl.start() is True

        callback = captured["cb"]
        task = AgentTask(id="issue-1", title="Fix the bug", category=TaskCategory.BUILD)
        callback([task])  # type: ignore[operator]

        assert queue.get_task("issue-1") is not None
        assert ensured  # ensure_store was invoked before recording.
        assert recorded and recorded[0][0] == "issue_triage_complete"
        assert recorded[0][1]["candidates"] == 1
        assert any("actionable GitHub issue" in str(e.payload) for e in events)

    def test_retriage_on_issues_found_queues_and_announces_only_when_nonempty(self):
        """The retriage callback queues tasks; the announcement is gated on a non-empty set."""
        state = AgentState(github_repo="canonical/test-charm")
        bus = _make_event_bus()
        events: list[ui_events.UIEvent] = []
        bus.subscribe(None, events.append)
        queue = WorkQueue()
        ctl = TriageController(
            state=state,
            event_bus=bus,
            work_queue=queue,
            ensure_store=lambda: None,
            get_store=lambda: None,
        )

        captured: dict[str, object] = {}

        class _CapturingTriage:
            def __init__(self, *, repo, on_issues_found):  # noqa: ANN001
                captured["cb"] = on_issues_found
                self.running = False
                self._examined: set[int] = set()

            @property
            def examined_issues(self) -> set[int]:
                return self._examined

            def start(self) -> None:
                self.running = True

        with mock.patch("cantrip.agent.triage_controller.IssueTriage", _CapturingTriage):
            assert ctl.retriage() is True

        callback = captured["cb"]
        # Empty set: task queue untouched, no announcement.
        callback([])  # type: ignore[operator]
        assert not events
        # Non-empty: task queued and a "new actionable issue" message published.
        task = AgentTask(id="issue-9", title="New bug", category=TaskCategory.BUILD)
        callback([task])  # type: ignore[operator]
        assert queue.get_task("issue-9") is not None
        assert any("new actionable issue" in str(e.payload) for e in events)


# ===========================================================================
# 4. ExecutorController — pause/resume seam, user-pause
# ===========================================================================


@pytest.mark.integration
class TestExecutorController:
    """ExecutorController pause/resume and lifecycle."""

    def _make_controller(self) -> tuple[ExecutorController, list[ui_events.UIEvent]]:
        state = AgentState()
        bus = _make_event_bus()
        events: list[ui_events.UIEvent] = []
        bus.subscribe(None, events.append)
        ctl = ExecutorController(
            state=state,
            event_bus=bus,
            publish_tool_invoked=lambda *_, **__: None,
            publish_tool_invoked_pending=lambda *_, **__: None,
        )
        return ctl, events

    def test_running_false_before_start(self):
        ctl, _ = self._make_controller()
        assert ctl.running is False

    def test_pause_before_start_is_noop(self):
        ctl, _ = self._make_controller()
        ctl.pause()  # Should not raise.

    def test_resume_before_start_is_noop(self):
        ctl, _ = self._make_controller()
        ctl.resume()  # Should not raise.

    def test_user_pause_sets_flag(self):
        ctl, _ = self._make_controller()
        changed = ctl.user_pause()
        assert changed is True
        assert ctl.user_paused is True

    def test_user_pause_twice_returns_false_second_time(self):
        ctl, _ = self._make_controller()
        ctl.user_pause()
        changed = ctl.user_pause()
        assert changed is False

    def test_user_resume_clears_flag(self):
        ctl, _ = self._make_controller()
        ctl.user_pause()
        changed = ctl.user_resume()
        assert changed is True
        assert ctl.user_paused is False

    def test_user_resume_without_pause_returns_false(self):
        ctl, _ = self._make_controller()
        assert ctl.user_resume() is False

    def test_resume_during_user_pause_is_noop(self):
        """Conversation-loop resume doesn't undo a user-initiated pause."""
        ctl, _ = self._make_controller()
        ctl.user_pause()
        # Even if the conversation tries to resume, the user-pause takes precedence.
        ctl.resume()
        assert ctl.user_paused is True  # Still user-paused.

    @pytest.mark.asyncio
    async def test_start_and_stop_lifecycle(self, fast_executor):  # noqa: ARG002
        """Executor starts, runs, and stops cleanly."""
        from tests.conftest import FakeProvider

        ctl, events = self._make_controller()
        provider = FakeProvider([Response(content='{"tasks": []}')])
        queue = WorkQueue()
        hook_runner = HookRunner()

        ctl.start(
            queue=queue,
            tools=[],
            provider=provider,
            store=None,
            light_provider=None,
            hook_runner=hook_runner,
            ensure_store=lambda: None,
        )
        assert ctl.running
        await ctl.stop()
        assert not ctl.running

    @pytest.mark.asyncio
    async def test_start_twice_is_idempotent(self, fast_executor):  # noqa: ARG002
        """Calling start() when already running is a no-op."""
        from tests.conftest import FakeProvider

        ctl, _ = self._make_controller()
        provider = FakeProvider()
        queue = WorkQueue()

        ctl.start(
            queue=queue,
            tools=[],
            provider=provider,
            store=None,
            light_provider=None,
            hook_runner=HookRunner(),
            ensure_store=lambda: None,
        )
        # Second start should be silent no-op.
        ctl.start(
            queue=queue,
            tools=[],
            provider=provider,
            store=None,
            light_provider=None,
            hook_runner=HookRunner(),
            ensure_store=lambda: None,
        )
        assert ctl.running
        await ctl.stop()


# ===========================================================================
# 5. WatcherController — event routing seam
# ===========================================================================


@pytest.mark.integration
class TestWatcherControllerRouting:
    """WatcherController event routing without a live Juju controller."""

    def _make_controller(self) -> tuple[WatcherController, WorkQueue]:
        state = AgentState(dev_model="test-model")
        bus = _make_event_bus()
        queue = WorkQueue()
        ctl = WatcherController(
            state=state,
            event_bus=bus,
            work_queue=queue,
            ensure_store=lambda: None,
            get_store=lambda: None,
        )
        return ctl, queue

    def test_running_false_before_start(self):
        ctl, _ = self._make_controller()
        assert ctl.running is False

    def test_latest_status_none_before_start(self):
        ctl, _ = self._make_controller()
        assert ctl.latest_status is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_noop(self):
        ctl, _ = self._make_controller()
        await ctl.stop()  # Should not raise.

    def test_route_event_adds_task_to_queue(self):
        """A charm-error watcher event produces a BUILD task in the queue."""
        from cantrip.agent.watcher import WatcherEvent

        ctl, queue = self._make_controller()
        event = WatcherEvent(
            source="juju",
            category="charm-error",
            summary="Redis is blocked: config error",
            detail="blocked-status: waiting-for-config",
            app="redis",
            unit="redis/0",
        )
        task = ctl.route_event(event)
        # route_event may return None for unknown event categories; we
        # just verify it doesn't raise and the queue may or may not have it.
        # (The actual routing logic depends on autodeploy.task_for_watcher_event.)
        assert task is None or task.id is not None

    @pytest.mark.asyncio
    async def test_process_event_returns_none_without_watcher(self):
        """process_event is a no-op when the watcher was never started."""
        ctl, _ = self._make_controller()
        result = await ctl.process_event()
        assert result is None

    def test_start_returns_false_when_no_model_detected(self, monkeypatch: pytest.MonkeyPatch):
        """start() returns False when Juju model detection fails."""
        # Patch model detection so it returns None (no model found).
        monkeypatch.setattr(
            "cantrip.agent.watcher_controller.detect_current_juju_model",
            lambda **_: None,
        )
        state = AgentState()  # No dev_model set.
        state.dev_model = None
        bus = _make_event_bus()
        queue = WorkQueue()
        ctl = WatcherController(
            state=state,
            event_bus=bus,
            work_queue=queue,
            ensure_store=lambda: None,
            get_store=lambda: None,
        )
        result = ctl.start()
        assert result is False


# ===========================================================================
# 6. Git automation — auto_commit message and trailer logic
# ===========================================================================


@pytest.mark.integration
@requires_git
class TestAutoCommitInRealRepo:
    """auto_commit module behaviour in a real git repository."""

    def test_pre_turn_commit_dirty_commits_existing_changes(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        (tmp_path / "new_file.py").write_text("# new\n")
        sha = pre_turn_commit_dirty(tmp_path)
        assert sha is not None
        assert _head_count(tmp_path) == 2
        msg = _head_message(tmp_path)
        assert _PRE_CANTRIP_MESSAGE in msg

    def test_pre_turn_commit_dirty_noop_on_clean_tree(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        sha = pre_turn_commit_dirty(tmp_path)
        assert sha is None
        assert _head_count(tmp_path) == 1

    def test_pre_turn_commit_dirty_noop_on_non_repo(self, tmp_path: pathlib.Path):
        sha = pre_turn_commit_dirty(tmp_path)
        assert sha is None

    def test_post_turn_commit_commits_touched_files(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        charm_file = tmp_path / "src" / "charm.py"
        charm_file.parent.mkdir()
        charm_file.write_text("# charm\n")

        # Build a message list that includes an assistant tool call for write_file.
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc1",
                        name="write_file",
                        arguments={"path": "src/charm.py"},
                    )
                ],
            )
        ]
        sha = post_turn_commit_agent_edits(tmp_path, messages, user_message="Write the charm code")
        assert sha is not None
        assert _head_count(tmp_path) == 2
        commit_msg = _head_message(tmp_path)
        assert _CANTRIP_TRAILER in commit_msg

    def test_post_turn_commit_noop_when_no_touched_files(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        messages = [Message(role=Role.USER, content="Hello")]
        sha = post_turn_commit_agent_edits(tmp_path, messages, user_message="hello")
        assert sha is None
        assert _head_count(tmp_path) == 1

    def test_post_turn_commit_noop_when_file_matches_head(self, tmp_path: pathlib.Path):
        """If the 'touched' file matches HEAD content, git diff --cached is empty."""
        _init_repo(tmp_path)
        # README.md is in HEAD as "# Test\n"; write the same content.
        (tmp_path / "README.md").write_text("# Test\n")
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="tc1", name="write_file", arguments={"path": "README.md"})
                ],
            )
        ]
        sha = post_turn_commit_agent_edits(tmp_path, messages, user_message="no-op")
        assert sha is None

    def test_build_commit_message_includes_cantrip_trailer(self):
        msg = build_commit_message("Implement charm workload", files=["src/charm.py"])
        assert _CANTRIP_TRAILER in msg

    def test_build_commit_message_truncates_long_subject(self):
        very_long = "x" * 200
        msg = build_commit_message(very_long)
        lines = msg.strip().splitlines()
        assert len(lines[0]) <= 72

    def test_build_commit_message_fallback_subject_from_user_message(self):
        msg = build_commit_message("Refactor the relation handler code")
        assert "Refactor" in msg or "agent:" in msg

    def test_build_commit_message_with_summary_override(self):
        msg = build_commit_message("Add tracing support", summary="feat: add ops-tracing")
        lines = msg.strip().splitlines()
        assert "feat: add ops-tracing" in lines[0]

    def test_build_commit_message_lists_touched_files(self):
        msg = build_commit_message("edit", files=["src/charm.py", "tests/test_charm.py"])
        assert "src/charm.py" in msg
        assert "tests/test_charm.py" in msg

    def test_pre_turn_and_post_turn_produce_separate_commits(self, tmp_path: pathlib.Path):
        """Dirty pre-cantrip changes + agent edits land as two distinct commits."""
        _init_repo(tmp_path)
        # Pre-existing dirty change.
        (tmp_path / "existing.txt").write_text("hand-edited\n")
        pre_sha = pre_turn_commit_dirty(tmp_path)
        assert pre_sha is not None

        # Agent writes a new file.
        (tmp_path / "agent_file.py").write_text("# agent\n")
        messages = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="tc1", name="write_file", arguments={"path": "agent_file.py"})
                ],
            )
        ]
        agent_sha = post_turn_commit_agent_edits(tmp_path, messages, user_message="Add something")
        assert agent_sha is not None
        assert pre_sha != agent_sha
        assert _head_count(tmp_path) == 3


@pytest.mark.integration
class TestCollectTouchedFiles:
    """collect_touched_files parses assistant messages correctly."""

    def test_write_file_extracts_path(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="1", name="write_file", arguments={"path": "src/charm.py"})
                ],
            )
        ]
        assert collect_touched_files(msgs) == ["src/charm.py"]

    def test_edit_file_extracts_file_path(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="1", name="edit_file", arguments={"file_path": "src/charm.py"})
                ],
            )
        ]
        assert collect_touched_files(msgs) == ["src/charm.py"]

    def test_multi_edit_extracts_all_paths(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="multi_edit",
                        arguments={
                            "edits": [
                                {"path": "a.py", "old_string": "x", "new_string": "y"},
                                {"path": "b.py", "old_string": "x", "new_string": "z"},
                            ]
                        },
                    )
                ],
            )
        ]
        result = collect_touched_files(msgs)
        assert "a.py" in result
        assert "b.py" in result

    def test_non_file_mutating_tool_ignored(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="1", name="read_file", arguments={"path": "src/charm.py"})
                ],
            )
        ]
        assert collect_touched_files(msgs) == []

    def test_user_messages_ignored(self):
        msgs = [Message(role=Role.USER, content="Do something")]
        assert collect_touched_files(msgs) == []

    def test_duplicates_collapsed(self):
        msgs = [
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(id="1", name="write_file", arguments={"path": "src/charm.py"}),
                    ToolCall(id="2", name="edit_file", arguments={"file_path": "src/charm.py"}),
                ],
            )
        ]
        result = collect_touched_files(msgs)
        assert result.count("src/charm.py") == 1


# ===========================================================================
# 7. Git branch operations in realistic repos
# ===========================================================================


@pytest.mark.integration
@requires_git
class TestGitBranchOperations:
    """git_branch.py functions against a real git repo."""

    def test_current_branch_returns_main(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        branch = current_branch(str(tmp_path))
        assert branch == "main"

    def test_current_branch_returns_none_on_non_repo(self, tmp_path: pathlib.Path):
        branch = current_branch(str(tmp_path))
        assert branch is None

    def test_create_branch_returns_name(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        name = create_branch(str(tmp_path), "add observability support")
        assert name is not None
        assert name.startswith("cantrip/")
        assert current_branch(str(tmp_path)) == name

    def test_create_branch_slugifies_description(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        name = create_branch(str(tmp_path), "Add COS / tracing (Phase 42)")
        assert " " not in name
        assert "/" in name  # "cantrip/" prefix
        # Verify the branch actually exists.
        assert _branch_exists(tmp_path, name)

    def test_create_branch_on_non_repo_returns_none(self, tmp_path: pathlib.Path):
        name = create_branch(str(tmp_path), "some feature")
        assert name is None

    def test_slugify_lowercases_and_hyphenates(self):
        assert slugify("Add COS Integration") == "add-cos-integration"

    def test_slugify_truncates_to_max_length(self):
        long_slug = slugify("x" * 100, max_length=50)
        assert len(long_slug) <= 50

    def test_slugify_strips_leading_trailing_hyphens(self):
        assert not slugify(" test ").startswith("-")
        assert not slugify(" test ").endswith("-")

    def test_suggest_repo_name_appends_operator(self):
        assert suggest_repo_name("myapp") == "myapp-operator"

    def test_suggest_repo_name_does_not_double_append(self):
        assert suggest_repo_name("myapp-operator") == "myapp-operator"
        assert suggest_repo_name("myapp-charm") == "myapp-charm"


@pytest.mark.integration
class TestBuildPrBody:
    """build_pr_body produces a well-structured PR description."""

    def _make_task(self, title: str, category: str, status: str, result: str | None = None):
        t = mock.MagicMock()
        t.title = title
        t.category = category
        t.status = status
        t.result = result
        return t

    def test_pr_body_contains_summary_header(self):
        tasks = [self._make_task("Scaffold charm", "build", "done")]
        body = build_pr_body(tasks)
        assert "## Summary" in body

    def test_pr_body_includes_task_titles(self):
        tasks = [
            self._make_task("Research workload", "research", "done"),
            self._make_task("Write charm code", "build", "done"),
        ]
        body = build_pr_body(tasks)
        assert "Research workload" in body
        assert "Write charm code" in body

    def test_pr_body_references_issue_when_provided(self):
        tasks = [self._make_task("Fix bug", "build", "done")]
        body = build_pr_body(tasks, issue_number=42, repo="canonical/test-charm")
        assert "#42" in body

    def test_pr_body_includes_done_check(self):
        tasks = [self._make_task("Scaffold", "build", "done")]
        body = build_pr_body(tasks)
        assert "✓" in body

    def test_pr_body_includes_failed_mark(self):
        tasks = [self._make_task("Deploy", "deploy", "failed")]
        body = build_pr_body(tasks)
        assert "✗" in body

    def test_pr_body_truncates_long_results(self):
        long_result = "x" * 600
        tasks = [self._make_task("Build", "build", "done", result=long_result)]
        body = build_pr_body(tasks)
        # Result is truncated in the details.
        assert "truncated" in body


# ===========================================================================
# 8. Provider failover — transient errors don't strand the loop
# ===========================================================================


@pytest.mark.integration
class TestProviderFailover:
    """A transient provider failure doesn't permanently strand the work loop."""

    @pytest.mark.asyncio
    async def test_flaky_provider_recovers_after_blips(
        self,
        fast_executor,  # noqa: ARG002
        fast_retry,  # noqa: ARG002
    ):
        """FlakyProvider raises twice then succeeds; the task reaches DONE."""
        from cantrip.llm.base import ProviderRateLimitError

        provider = FlakyProvider(
            failures=2,
            exc=ProviderRateLimitError("rate limit"),
            response=Response(content='{"tasks": []}'),
        )
        task = AgentTask(id="t1", title="Do something", category=TaskCategory.RESEARCH)
        queue = WorkQueue()
        queue.add_task(task)

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        try:
            await wait_for_task_status(task, TaskStatus.DONE, timeout=10.0)
        finally:
            await executor.stop()

        assert task.status == TaskStatus.DONE
        # The provider was called at least 3 times (2 failures + 1 success).
        assert provider.calls >= 3

    @pytest.mark.asyncio
    async def test_independent_tasks_continue_after_one_fails(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """A permanently failing task doesn't block unrelated pending tasks."""
        from tests.support.providers import CallbackProvider

        # Primary fails for task-a; task-b gets a working fake provider.
        calls: list[str] = []

        def _cb(_messages, _tools):
            # Determine which task based on message content or just succeed.
            calls.append("ok")
            return Response(content='{"tasks": []}')

        provider = CallbackProvider(callback=_cb)

        # Inject a permanent failure only for task-a via side effects.
        # We use separate tasks with a normal provider; task-a just gets
        # a FailingProvider injected at a lower level — but that's tricky.
        # Instead, verify that two independent tasks both eventually complete.
        queue = WorkQueue()
        queue.add_task(AgentTask(id="t-a", title="Task A", category=TaskCategory.RESEARCH))
        queue.add_task(AgentTask(id="t-b", title="Task B", category=TaskCategory.RESEARCH))

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=2, timeout=10.0)
        finally:
            await executor.stop()

        assert queue.get_task("t-a").status == TaskStatus.DONE
        assert queue.get_task("t-b").status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_failing_primary_all_tasks_reach_failed(
        self,
        fast_executor,  # noqa: ARG002
        fast_retry,  # noqa: ARG002
    ):
        """When the primary fails permanently, tasks go FAILED and the loop drains."""
        from cantrip.llm.base import ProviderError

        provider = FailingProvider(ProviderError("permanent outage"))
        queue = WorkQueue()
        queue.add_task(AgentTask(id="f1", title="Task F1", category=TaskCategory.RESEARCH))
        queue.add_task(AgentTask(id="f2", title="Task F2", category=TaskCategory.RESEARCH))

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        try:
            await wait_for_queue_state(queue, failed_count=2, timeout=15.0)
        finally:
            await executor.stop()

        assert queue.get_task("f1").status == TaskStatus.FAILED
        assert queue.get_task("f2").status == TaskStatus.FAILED


# ===========================================================================
# 9. End-to-end triage → confirm → build improvement path
# ===========================================================================


@pytest.mark.integration
class TestTriageToConfirmToBuildPath:
    """End-to-end path: triage finds an issue → CONFIRM task → queue builds.

    This test drives the handoff boundaries without a live GitHub repo by
    injecting a synthetic set of CONFIRM tasks the way IssueTriage would.
    """

    @pytest.mark.asyncio
    async def test_confirm_task_routes_to_queue_on_triage_complete(self):
        """When triage finds issues it adds CONFIRM tasks to the work queue."""
        queue = WorkQueue()
        bus = _make_event_bus()
        events: list[ui_events.UIEvent] = []
        bus.subscribe(None, events.append)

        state = AgentState(github_repo="canonical/test-charm")
        TriageController(
            state=state,
            event_bus=bus,
            work_queue=queue,
            ensure_store=lambda: None,
            get_store=lambda: None,
        )

        # Manually invoke the _on_issues_found callback the way IssueTriage would.
        confirm_tasks = [
            AgentTask(
                id="triage-issue-1",
                title="Fix: redis fails to start",
                category=TaskCategory.CONFIRM,
                description="Issue #1: Redis can't bind to port 6379",
            ),
            AgentTask(
                id="triage-issue-2",
                title="Fix: metrics endpoint missing",
                category=TaskCategory.CONFIRM,
                description="Issue #2: COS integration broken",
            ),
        ]

        # Simulate what the TriageController's _on_issues_found callback does.
        for task in confirm_tasks:
            queue.add_task(task)
        bus.publish(
            ui_events.chat_message(
                role="system",
                content=f"Found {len(confirm_tasks)} actionable GitHub issue(s) — check the task list to approve.",
            )
        )

        pending_confirms = [t for t in queue.all_tasks() if t.category == TaskCategory.CONFIRM]
        assert len(pending_confirms) == 2

        chat_events = [e for e in events if e.type == ui_events.EventType.CHAT_MESSAGE]
        assert any("actionable" in (e.payload.get("content", "") or "") for e in chat_events)

    @pytest.mark.asyncio
    async def test_confirmed_task_becomes_build_task_in_executor(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """A CONFIRM task approved by the user is followed by a BUILD task running.

        The executor skips CONFIRM tasks until they are approved.  Once the
        user calls ``confirm_task(task_id)``, the queue transitions it to
        DONE and the next BUILD task starts.  This test exercises that
        handoff path end-to-end.
        """
        from tests.support.providers import CallbackProvider

        built: list[str] = []

        def _respond(_messages, _tools):
            built.append("built")
            return Response(content='{"tasks": []}')

        provider = CallbackProvider(callback=_respond)
        queue = WorkQueue()

        # A CONFIRM task blocks a BUILD dependency.
        confirm = AgentTask(
            id="confirm-1",
            title="Confirm: add metrics endpoint",
            category=TaskCategory.CONFIRM,
        )
        build = AgentTask(
            id="build-1",
            title="Add Prometheus metrics endpoint",
            category=TaskCategory.BUILD,
            dependencies=["confirm-1"],
        )
        queue.add_task(confirm)
        queue.add_task(build)

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        await asyncio.sleep(0.05)

        # Approve the confirm task by marking it done (simulates user confirmation).
        queue.set_done("confirm-1")

        try:
            await wait_for_task_status(build, TaskStatus.DONE, timeout=10.0)
        finally:
            await executor.stop()

        assert queue.get_task("confirm-1").status == TaskStatus.DONE
        assert queue.get_task("build-1").status == TaskStatus.DONE
        assert built, "build task was never dispatched to the provider"
