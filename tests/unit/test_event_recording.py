"""Tests for event log recording hooks."""

import pathlib

import pytest

from cantrip.agent.store import SessionStore


class TestEventRecordingInExecutor:
    """Verify that task status changes are recorded as events."""

    @pytest.fixture
    def store(self, tmp_path: pathlib.Path):
        s = SessionStore(tmp_path / ".cantrip")
        s.open()
        yield s
        s.close()

    def test_task_status_events_schema(self, store: SessionStore) -> None:
        """Event detail has the expected keys."""
        store.record_event(
            "task_status_change",
            {
                "task_id": "t1",
                "task_title": "Test task",
                "old_status": "pending",
                "new_status": "active",
            },
        )
        events = store.load_events(event_type="task_status_change")
        assert len(events) == 1
        detail = events[0]["detail"]
        assert detail["task_id"] == "t1"
        assert detail["old_status"] == "pending"
        assert detail["new_status"] == "active"

    def test_error_event_schema(self, store: SessionStore) -> None:
        """Error events include error type and message."""
        store.record_event(
            "error",
            {
                "task_id": "t1",
                "error_type": "ValueError",
                "error": "something went wrong",
            },
        )
        events = store.load_events(event_type="error")
        assert len(events) == 1
        assert events[0]["detail"]["error_type"] == "ValueError"

    def test_design_confirmed_event(self, store: SessionStore) -> None:
        """Design confirmed events record workload and task count."""
        store.record_event(
            "design_confirmed",
            {
                "workload": "redis",
                "substrate": "k8s",
                "charm_path": "Path B",
                "build_task_count": 3,
            },
        )
        events = store.load_events(event_type="design_confirmed")
        assert len(events) == 1
        assert events[0]["detail"]["workload"] == "redis"

    def test_session_resume_event(self, store: SessionStore) -> None:
        """Session resume events record charm name and task count."""
        store.record_event(
            "session_resume",
            {
                "charm_name": "my-charm",
                "task_count": 5,
            },
        )
        events = store.load_events(event_type="session_resume")
        assert len(events) == 1

    def test_watcher_event(self, store: SessionStore) -> None:
        """Watcher events record category and summary."""
        store.record_event(
            "watcher_event",
            {
                "category": "hook_failure",
                "summary": "install hook failed on my-charm/0",
            },
        )
        events = store.load_events(event_type="watcher_event")
        assert len(events) == 1
        assert events[0]["detail"]["category"] == "hook_failure"
