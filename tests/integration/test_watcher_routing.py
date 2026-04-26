"""Integration tests: Watcher events -> work queue routing.

Exercises the watcher event routing logic: various event categories
are converted into appropriate task types and added to the work queue.
"""

import pathlib

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import TaskCategory, TaskStatus
from cantrip.agent.watcher import WatcherEvent
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.integration.conftest import wait_for_queue_state


@pytest.mark.integration
class TestWatcherEventRouting:
    """Test routing of watcher events into agent tasks."""

    def test_hook_failure_creates_debug_task(self, tmp_path: pathlib.Path):
        """A hook_failure event creates a DEBUG task."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.dev_model = "test-model"

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="Unit 'myapp/0' entered error state: install hook failed",
            app="myapp",
            unit="myapp/0",
        )
        task = agent.route_watcher_event(event)

        assert task is not None
        assert task.category == TaskCategory.DEBUG
        assert "[Watcher]" in task.title
        assert "Hook failure" in task.title

    def test_status_change_creates_debug_task(self, tmp_path: pathlib.Path):
        """A status_change event creates a DEBUG task."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.dev_model = "test-model"

        event = WatcherEvent(
            source="status",
            category="status_change",
            summary="myapp/0: active -> blocked",
            detail="Unit changed from 'active' to 'blocked'",
            app="myapp",
            unit="myapp/0",
        )
        task = agent.route_watcher_event(event)

        assert task is not None
        assert task.category == TaskCategory.DEBUG
        assert task.status == TaskStatus.PENDING

    def test_log_error_creates_debug_task(self, tmp_path: pathlib.Path):
        """A log_error event creates a DEBUG task."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.dev_model = "test-model"

        event = WatcherEvent(
            source="loki",
            category="log_error",
            summary="Log error in myapp",
            detail="Traceback: RuntimeError: connection refused",
            app="myapp",
        )
        task = agent.route_watcher_event(event)

        assert task is not None
        assert task.category == TaskCategory.DEBUG

    def test_new_app_creates_infra_task(self, tmp_path: pathlib.Path):
        """A new_app event creates an INFRA task."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.dev_model = "test-model"

        event = WatcherEvent(
            source="status",
            category="new_app",
            summary="New application: postgresql",
            detail="Application 'postgresql' appeared in the model.",
            app="postgresql",
        )
        task = agent.route_watcher_event(event)

        assert task is not None
        assert task.category == TaskCategory.INFRA
        assert "postgresql" in task.title

    def test_new_relation_creates_infra_task(self, tmp_path: pathlib.Path):
        """A new_relation event creates an INFRA task."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.dev_model = "test-model"

        event = WatcherEvent(
            source="status",
            category="new_relation",
            summary="New relation: myapp:db-postgresql:db",
            detail="Relation added involving 'myapp'.",
            app="myapp",
        )
        task = agent.route_watcher_event(event)

        assert task is not None
        assert task.category == TaskCategory.INFRA

    def test_no_task_without_dev_model(self, tmp_path: pathlib.Path):
        """Without dev_model, no task is created from a watcher event."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.dev_model = None

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="Install hook failed",
            app="myapp",
        )
        task = agent.route_watcher_event(event)

        assert task is None
        assert len(agent.work_queue.all_tasks()) == 0

    def test_unrecognised_category_returns_none(self, tmp_path: pathlib.Path):
        """An unknown event category produces no task."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.dev_model = "test-model"

        event = WatcherEvent(
            source="status",
            category="unknown_category",
            summary="Something happened",
            detail="Details here.",
        )
        task = agent.route_watcher_event(event)

        assert task is None

    @pytest.mark.asyncio
    async def test_watcher_event_task_executed_by_executor(
        self,
        tmp_path: pathlib.Path,
        fast_executor,  # noqa: ARG002
    ):
        """A routed DEBUG task is picked up and completed by the executor."""
        provider = FakeProvider(responses=[Response(content="Investigated the failure.")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.dev_model = "test-model"

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="Install hook failed",
            app="myapp",
        )
        task = agent.route_watcher_event(event)
        assert task is not None

        executor = BackgroundExecutor(
            queue=agent.work_queue,
            tools=[],
            provider=provider,
            state=agent.state,
        )
        executor.start()
        try:
            await wait_for_queue_state(agent.work_queue, done_count=1)
        finally:
            await executor.stop()

        completed = agent.work_queue.get_task(task.id)
        assert completed.status == TaskStatus.DONE
        assert completed.result == "Investigated the failure."
