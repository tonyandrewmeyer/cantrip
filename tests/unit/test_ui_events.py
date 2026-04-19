"""UI integration tests — verify both UIs handle the same events.

These tests verify that the shared event bus contract is honoured:
the same event payloads that drive TUI widget updates are also
valid JSON payloads that the WebSocket bridge would forward to
the browser.  No browser automation is required.
"""

import json

from cantrip.ui import events


class TestEventContract:
    """Every event type produces a valid, complete payload."""

    def _round_trip(self, event: events.Event) -> dict:
        """Serialise and parse, asserting structure."""
        raw = event.to_json()
        parsed = json.loads(raw)
        assert "type" in parsed
        assert "data" in parsed
        assert "timestamp" in parsed
        assert parsed["type"] == event.type.value
        return parsed

    def test_task_updated_has_required_fields(self):
        event = events.task_updated(
            task_id="abc123",
            title="Build charm",
            status="active",
            category="build",
            description="Scaffold and build",
            result=None,
            blocked_reason=None,
        )
        data = self._round_trip(event)["data"]
        assert data["id"] == "abc123"
        assert data["title"] == "Build charm"
        assert data["status"] == "active"
        assert data["category"] == "build"
        # These fields are used by both the TUI checklist and the
        # web UI's updateTask() function.
        assert "description" in data
        assert "result" in data
        assert "blocked_reason" in data
        # Worktree visibility (Phase 44.4) — absent means no active worktree.
        assert data["worktree_path"] is None

    def test_task_updated_carries_worktree_path(self):
        event = events.task_updated(
            task_id="t1",
            title="Build",
            status="active",
            category="build",
            worktree_path="/tmp/charm/.cantrip-worktrees/t1",
        )
        data = self._round_trip(event)["data"]
        assert data["worktree_path"] == "/tmp/charm/.cantrip-worktrees/t1"

    def test_task_updated_from_task_reads_worktree_path(self):
        class _T:
            id = "t1"
            title = "Build"
            status = "active"
            category = "build"
            description = ""
            result = None
            blocked_reason = None
            worktree_path = "/tmp/charm/.cantrip-worktrees/t1"

        data = self._round_trip(events.task_updated_from_task(_T()))["data"]
        assert data["worktree_path"] == "/tmp/charm/.cantrip-worktrees/t1"

    def test_task_updated_status_values_match_web_css(self):
        """The status values must match the CSS class names in style.css."""
        valid_statuses = {"pending", "active", "done", "failed", "blocked"}
        for status in valid_statuses:
            event = events.task_updated(
                task_id="t",
                title="T",
                status=status,
                category="build",
            )
            data = json.loads(event.to_json())["data"]
            assert data["status"] == status

    def test_chat_message_has_role_and_content(self):
        for role in ("user", "assistant", "system"):
            event = events.chat_message(role=role, content="hello")
            data = self._round_trip(event)["data"]
            assert data["role"] == role
            assert data["content"] == "hello"

    def test_thinking_changed_has_active_bool(self):
        for active in (True, False):
            event = events.thinking_changed(active=active)
            data = self._round_trip(event)["data"]
            assert data["active"] is active

    def test_watcher_event_has_summary(self):
        event = events.watcher_event(
            source="status",
            category="charm",
            summary="redis-k8s/0 active",
            detail="workload status changed",
            app="redis-k8s",
            unit="redis-k8s/0",
        )
        data = self._round_trip(event)["data"]
        assert data["summary"] == "redis-k8s/0 active"
        assert data["source"] == "status"

    def test_status_bar_changed_partial_fields(self):
        """Status bar events may contain only the changed fields."""
        event = events.status_bar_changed(task_label="building")
        data = self._round_trip(event)["data"]
        assert data["task_label"] == "building"
        assert "cos_health" not in data

    def test_preflight_updated_has_indices(self):
        event = events.preflight_updated(
            group_index=0,
            item_index=2,
            status="passed",
        )
        data = self._round_trip(event)["data"]
        assert data["group_index"] == 0
        assert data["item_index"] == 2
        assert data["status"] == "passed"

    def test_tasks_snapshot_is_list(self):
        tasks = [
            {"id": "1", "title": "A", "status": "done", "category": "build"},
            {"id": "2", "title": "B", "status": "pending", "category": "test"},
        ]
        event = events.tasks_snapshot(tasks)
        data = self._round_trip(event)["data"]
        assert len(data["tasks"]) == 2

    def test_juju_status_changed_passes_through(self):
        status_data = {
            "apps": {"redis-k8s": {"status": "active", "units": {}}},
            "relations": [],
        }
        event = events.juju_status_changed(status_data=status_data)
        data = self._round_trip(event)["data"]
        assert "redis-k8s" in data["apps"]


class TestBusBroadcastContract:
    """The wildcard subscriber pattern used by the web server works for all types."""

    def test_wildcard_receives_all_event_types(self):
        bus = events.EventBus()
        received: list[events.Event] = []
        bus.subscribe(None, received.append)

        all_events = [
            events.task_updated(task_id="1", title="T", status="done", category="build"),
            events.chat_message(role="user", content="hi"),
            events.thinking_changed(active=True),
            events.watcher_event(source="s", category="c", summary="sum"),
            events.status_bar_changed(task_label="x"),
            events.preflight_updated(group_index=0, item_index=0, status="running"),
            events.tasks_snapshot([]),
            events.juju_status_changed(status_data={}),
        ]

        for ev in all_events:
            bus.publish(ev)

        assert len(received) == len(all_events)
        # Every event should be JSON-serialisable (the web server
        # forwards them as-is to WebSocket clients).
        for ev in received:
            parsed = json.loads(ev.to_json())
            assert parsed["type"] in [e.value for e in events.EventType]

    def test_event_type_enum_covers_all_factories(self):
        """Every factory function produces a known event type."""
        factory_types = {
            events.task_updated(task_id="x", title="x", status="x", category="x").type,
            events.chat_message(role="x", content="x").type,
            events.thinking_changed(active=True).type,
            events.watcher_event(source="x", category="x", summary="x").type,
            events.status_bar_changed().type,
            events.preflight_updated(group_index=0, item_index=0, status="x").type,
            events.tasks_snapshot([]).type,
            events.juju_status_changed(status_data={}).type,
            events.memory_written(title="x", scope="charm", kind="fact", source="x").type,
            events.memory_recalled(title="x", scope="charm", kind="fact").type,
            events.mcp_elicitation_request(
                request_id="x", server_name="x", mode="form", message="x"
            ).type,
        }
        enum_types = set(events.EventType)
        assert factory_types == enum_types
