"""Tests for the shared UI event bus."""

import asyncio
import json
import threading

from cantrip.ui import events


class TestEvent:
    """Event dataclass behaviour."""

    def test_to_json_round_trips(self):
        event = events.chat_message(role="user", content="hello")
        raw = event.to_json()
        parsed = json.loads(raw)
        assert parsed["type"] == "chat_message"
        assert parsed["data"]["role"] == "user"
        assert parsed["data"]["content"] == "hello"
        assert isinstance(parsed["timestamp"], float)

    def test_frozen(self):
        event = events.thinking_changed(active=True)
        try:
            event.type = events.EventType.CHAT_MESSAGE  # type: ignore[misc]
            raise AssertionError("should be frozen")
        except AttributeError:
            pass


class TestEventBus:
    """EventBus subscribe / publish / unsubscribe."""

    def test_subscribe_and_publish(self):
        bus = events.EventBus()
        received: list[events.Event] = []
        bus.subscribe(events.EventType.CHAT_MESSAGE, received.append)

        event = events.chat_message(role="system", content="hi")
        bus.publish(event)

        assert len(received) == 1
        assert received[0] is event

    def test_wildcard_subscriber(self):
        bus = events.EventBus()
        received: list[events.Event] = []
        bus.subscribe(None, received.append)

        bus.publish(events.chat_message(role="user", content="a"))
        bus.publish(events.thinking_changed(active=True))

        assert len(received) == 2

    def test_type_filtered(self):
        """Subscribers only receive matching event types."""
        bus = events.EventBus()
        received: list[events.Event] = []
        bus.subscribe(events.EventType.THINKING_CHANGED, received.append)

        bus.publish(events.chat_message(role="user", content="ignored"))
        bus.publish(events.thinking_changed(active=False))

        assert len(received) == 1
        assert received[0].payload["active"] is False

    def test_unsubscribe(self):
        bus = events.EventBus()
        received: list[events.Event] = []
        bus.subscribe(events.EventType.CHAT_MESSAGE, received.append)
        bus.unsubscribe(events.EventType.CHAT_MESSAGE, received.append)

        bus.publish(events.chat_message(role="user", content="gone"))
        assert received == []

    def test_unsubscribe_missing_is_noop(self):
        bus = events.EventBus()
        bus.unsubscribe(events.EventType.CHAT_MESSAGE, lambda _e: None)

    def test_subscriber_exception_does_not_break_others(self):
        bus = events.EventBus()
        received: list[events.Event] = []

        def bad(_event: events.Event) -> None:
            raise RuntimeError("boom")

        bus.subscribe(events.EventType.CHAT_MESSAGE, bad)
        bus.subscribe(events.EventType.CHAT_MESSAGE, received.append)

        bus.publish(events.chat_message(role="user", content="ok"))
        assert len(received) == 1

    def test_cross_thread_publish(self):
        """Publishing from a non-loop thread schedules via call_soon_threadsafe."""
        loop = asyncio.new_event_loop()
        bus = events.EventBus()
        bus.bind_loop(loop)

        received: list[events.Event] = []
        bus.subscribe(events.EventType.TASK_UPDATED, received.append)

        event = events.task_updated(
            task_id="t1",
            title="Test",
            status="pending",
            category="build",
        )

        # Publish from a background thread; the loop processes it.
        def bg() -> None:
            bus.publish(event)

        async def run() -> None:
            thread = threading.Thread(target=bg)
            thread.start()
            # Give the call_soon_threadsafe time to land.
            await asyncio.sleep(0.05)
            thread.join()

        loop.run_until_complete(run())
        loop.close()

        assert len(received) == 1
        assert received[0].payload["id"] == "t1"

    def test_async_subscriber(self):
        """Async callbacks are scheduled as tasks."""
        received: list[events.Event] = []

        async def handler(event: events.Event) -> None:
            received.append(event)

        bus = events.EventBus()
        bus.subscribe(events.EventType.CHAT_MESSAGE, handler)

        async def run() -> None:
            bus.bind_loop(asyncio.get_running_loop())
            bus.publish(events.chat_message(role="user", content="async"))
            # Let the scheduled coroutine execute.
            await asyncio.sleep(0.01)

        asyncio.run(run())
        assert len(received) == 1


class TestFactoryFunctions:
    """Each factory produces a valid, serialisable Event."""

    def _assert_serialisable(self, event: events.Event) -> dict:
        raw = event.to_json()
        parsed = json.loads(raw)
        assert parsed["type"] == event.type.value
        return parsed

    def test_task_updated(self):
        event = events.task_updated(
            task_id="abc",
            title="Build charm",
            status="active",
            category="build",
            description="Build it",
            result=None,
            blocked_reason=None,
        )
        data = self._assert_serialisable(event)
        assert data["data"]["id"] == "abc"
        assert data["data"]["status"] == "active"

    def test_task_updated_from_task(self):
        """Works with a duck-typed task object."""

        class FakeTask:
            id = "x1"
            title = "Fake"
            status = type("S", (), {"value": "done"})()
            category = type("C", (), {"value": "test"})()
            description = "desc"
            result = "ok"
            blocked_reason = None

        event = events.task_updated_from_task(FakeTask())
        data = self._assert_serialisable(event)
        assert data["data"]["id"] == "x1"
        assert data["data"]["status"] == "done"

    def test_tasks_snapshot(self):
        event = events.tasks_snapshot([{"id": "1", "title": "T"}])
        data = self._assert_serialisable(event)
        assert len(data["data"]["tasks"]) == 1

    def test_chat_message(self):
        event = events.chat_message(role="assistant", content="hi")
        self._assert_serialisable(event)

    def test_thinking_changed(self):
        event = events.thinking_changed(active=True)
        data = self._assert_serialisable(event)
        assert data["data"]["active"] is True

    def test_juju_status_changed(self):
        event = events.juju_status_changed(status_data={"apps": {}})
        self._assert_serialisable(event)

    def test_watcher_event(self):
        event = events.watcher_event(
            source="status",
            category="charm",
            summary="Unit active",
        )
        data = self._assert_serialisable(event)
        assert data["data"]["source"] == "status"

    def test_status_bar_changed(self):
        event = events.status_bar_changed(task_label="building")
        data = self._assert_serialisable(event)
        assert data["data"]["task_label"] == "building"

    def test_preflight_updated(self):
        event = events.preflight_updated(group_index=0, item_index=2, status="passed")
        data = self._assert_serialisable(event)
        assert data["data"]["group_index"] == 0
