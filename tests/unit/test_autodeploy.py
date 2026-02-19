"""Tests for the auto-deploy loop follow-up logic."""

from cantrip.agent.autodeploy import (
    _VERIFY_PREFIX,
    _WATCHER_PREFIX,
    followup_tasks,
    task_for_watcher_event,
    tasks_after_build,
    tasks_after_deploy,
    tasks_after_verify,
)
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState
from cantrip.agent.watcher import WatcherEvent, format_event_for_agent

# ===================================================================
# TestTasksAfterBuild
# ===================================================================


class TestTasksAfterBuild:
    """Tests for tasks_after_build — auto-deploy after code changes."""

    def test_creates_deploy_for_successful_build(self) -> None:
        task = AgentTask(id="b1", title="Scaffold charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        result = tasks_after_build(task)

        assert len(result) == 1
        assert result[0].category == TaskCategory.DEPLOY
        assert "Scaffold charm" in result[0].title

    def test_no_deploy_for_failed_build(self) -> None:
        task = AgentTask(id="b1", title="Scaffold charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED

        assert tasks_after_build(task) == []

    def test_no_deploy_for_non_build(self) -> None:
        task = AgentTask(id="r1", title="Research Redis", category=TaskCategory.RESEARCH)
        task.status = TaskStatus.DONE

        assert tasks_after_build(task) == []

    def test_deploy_depends_on_build(self) -> None:
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        result = tasks_after_build(task)

        assert result[0].dependencies == ["b1"]

    def test_no_deploy_for_pending_build(self) -> None:
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        task.status = TaskStatus.PENDING

        assert tasks_after_build(task) == []


# ===================================================================
# TestTasksAfterDeploy
# ===================================================================


class TestTasksAfterDeploy:
    """Tests for tasks_after_deploy — verification task creation."""

    def test_creates_verify_for_successful_deploy(self) -> None:
        task = AgentTask(id="d1", title="Deploy myapp", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.DONE

        result = tasks_after_deploy(task)

        assert len(result) == 1
        assert result[0].title.startswith(_VERIFY_PREFIX)
        assert "Deploy myapp" in result[0].title

    def test_no_verify_for_failed_deploy(self) -> None:
        task = AgentTask(id="d1", title="Deploy myapp", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.FAILED

        assert tasks_after_deploy(task) == []

    def test_no_verify_for_non_deploy(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        assert tasks_after_deploy(task) == []

    def test_verify_depends_on_deploy(self) -> None:
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.DONE

        result = tasks_after_deploy(task)

        assert result[0].dependencies == ["d1"]

    def test_verify_has_deploy_category(self) -> None:
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.DONE

        result = tasks_after_deploy(task)

        assert result[0].category == TaskCategory.DEPLOY


# ===================================================================
# TestTasksAfterVerify
# ===================================================================


class TestTasksAfterVerify:
    """Tests for tasks_after_verify — diagnostic task creation."""

    def test_debug_task_for_failed_verification(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy myapp",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED
        task.result = "Unit myapp/0 is in error state"

        result = tasks_after_verify(task)

        assert len(result) == 1
        assert "Diagnose" in result[0].title

    def test_no_debug_for_successful_verify(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy myapp",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.DONE

        assert tasks_after_verify(task) == []

    def test_no_debug_for_non_verify_task(self) -> None:
        task = AgentTask(id="d1", title="Deploy myapp", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.FAILED

        assert tasks_after_verify(task) == []

    def test_debug_includes_failure_result(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy myapp",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED
        task.result = "hook failed: install"

        result = tasks_after_verify(task)

        assert "hook failed: install" in result[0].description

    def test_debug_has_debug_category(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED

        result = tasks_after_verify(task)

        assert result[0].category == TaskCategory.DEBUG

    def test_debug_depends_on_verify(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED

        result = tasks_after_verify(task)

        assert result[0].dependencies == ["v1"]


# ===================================================================
# TestFollowupTasks
# ===================================================================


class TestFollowupTasks:
    """Tests for followup_tasks — unified dispatch."""

    def test_dispatches_to_deploy_handler(self) -> None:
        task = AgentTask(id="d1", title="Deploy app", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.DONE

        result = followup_tasks(task)

        assert len(result) == 1
        assert result[0].title.startswith(_VERIFY_PREFIX)

    def test_dispatches_to_verify_handler(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy app",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED

        result = followup_tasks(task)

        assert len(result) == 1
        assert "Diagnose" in result[0].title

    def test_dispatches_to_build_handler(self) -> None:
        task = AgentTask(id="b1", title="Scaffold charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        result = followup_tasks(task)

        assert len(result) == 1
        assert result[0].category == TaskCategory.DEPLOY

    def test_empty_for_non_deploy(self) -> None:
        task = AgentTask(id="r1", title="Research Redis", category=TaskCategory.RESEARCH)
        task.status = TaskStatus.DONE

        assert followup_tasks(task) == []

    def test_empty_for_debug_task(self) -> None:
        """DEBUG tasks produce no further follow-ups — chain is bounded."""
        task = AgentTask(id="dbg1", title="Diagnose failure", category=TaskCategory.DEBUG)
        task.status = TaskStatus.DONE

        assert followup_tasks(task) == []


# ===================================================================
# TestTaskForWatcherEvent
# ===================================================================


class TestTaskForWatcherEvent:
    """Tests for task_for_watcher_event — watcher event conversion."""

    def _make_state(self, dev_model: str | None = "dev") -> AgentState:
        return AgentState(dev_model=dev_model)

    def test_hook_failure_creates_debug_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.DEBUG

    def test_status_change_creates_debug_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="status_change",
            summary="myapp/0: active -> blocked",
            detail="Unit changed status",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.DEBUG

    def test_log_error_creates_debug_task(self) -> None:
        event = WatcherEvent(
            source="loki",
            category="log_error",
            summary="Log error in myapp",
            detail="Traceback...",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.DEBUG

    def test_new_app_creates_infra_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="new_app",
            summary="New application: redis",
            detail="Application appeared",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.INFRA

    def test_new_relation_creates_infra_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="new_relation",
            summary="New relation: myapp:db-postgres",
            detail="Relation added",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.INFRA

    def test_removed_app_creates_infra_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="removed_app",
            summary="Application removed: old-app",
            detail="Application gone",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.INFRA

    def test_none_without_dev_model(self) -> None:
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure",
            detail="boom",
        )
        result = task_for_watcher_event(event, self._make_state(dev_model=None))

        assert result is None

    def test_none_for_unknown_category(self) -> None:
        event = WatcherEvent(
            source="status",
            category="unknown_thing",
            summary="Something",
            detail="Details",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is None

    def test_title_prefixed_with_watcher(self) -> None:
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.title.startswith(_WATCHER_PREFIX)

    def test_description_uses_format_event(self) -> None:
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        expected = format_event_for_agent(event)
        assert result.description == expected
