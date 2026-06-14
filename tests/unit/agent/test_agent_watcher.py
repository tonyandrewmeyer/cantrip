"""Tests for ``CantripAgent`` watcher integration."""

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.watcher.watcher import WatcherEvent
from tests.conftest import FakeProvider


class TestWatcherIntegration:
    """Tests for watcher integration in CantripAgent."""

    def test_start_watcher_requires_dev_model(self, monkeypatch):
        """start_watcher returns False when no dev_model is available.

        With no state.dev_model and no detectable Juju model, the
        watcher has nothing to watch and the call is a no-op.
        """
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        monkeypatch.setattr(
            "cantrip.agent.controllers.watcher_controller.detect_current_juju_model",
            lambda **_kwargs: None,
        )

        assert agent.start_watcher() is False
        assert not agent.watcher_running
        assert not agent.state.watcher_enabled

    @pytest.mark.asyncio
    async def test_start_watcher_auto_detects_dev_model(self, monkeypatch):
        """start_watcher falls back to the current Juju model when state is empty."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        monkeypatch.setattr(
            "cantrip.agent.controllers.watcher_controller.detect_current_juju_model",
            lambda **_kwargs: "detected-model",
        )

        result = agent.start_watcher()

        assert result is True
        assert agent.state.dev_model == "detected-model"
        assert agent.watcher_running

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_start_watcher_auto_detects_cos_model(self, monkeypatch):
        """start_watcher also picks up a 'cos' model when present."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        monkeypatch.setattr(
            "cantrip.agent.controllers.watcher_controller.detect_cos_juju_model", lambda: "cos"
        )

        assert agent.start_watcher() is True
        assert agent.state.cos_model == "cos"

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_start_watcher_skips_cos_detection_when_already_set(self, monkeypatch):
        """cos_model already set on state is not overwritten."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.state.cos_model = "preset-cos"
        called = {"count": 0}

        def _spy() -> str | None:
            called["count"] += 1
            return "cos"

        monkeypatch.setattr(
            "cantrip.agent.controllers.watcher_controller.detect_cos_juju_model", _spy
        )
        agent.start_watcher()
        assert agent.state.cos_model == "preset-cos"
        assert called["count"] == 0

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_start_watcher_with_dev_model(self):
        """start_watcher succeeds with a dev_model set."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"

        result = agent.start_watcher()

        assert result is True
        assert agent.watcher_running
        assert agent.state.watcher_enabled

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_start_watcher_passes_substrate_to_detector(self, monkeypatch):
        """When charm_type is set, detect_current_juju_model gets prefer_substrate."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.charm_type = "k8s"

        seen: dict[str, str | None] = {}

        def _detect(prefer_substrate: str | None = None) -> str | None:
            seen["prefer_substrate"] = prefer_substrate
            return "auto-k8s"

        monkeypatch.setattr(
            "cantrip.agent.controllers.watcher_controller.detect_current_juju_model", _detect
        )

        assert agent.start_watcher() is True
        assert seen["prefer_substrate"] == "k8s"
        assert agent.state.dev_model == "auto-k8s"

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_start_watcher_drops_wrong_substrate_dev_model(self, monkeypatch):
        """A stale LXD dev_model is replaced when the charm is k8s."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "stale-lxd"
        agent.state.charm_type = "k8s"

        monkeypatch.setattr(
            "cantrip.agent.controllers.watcher_controller.juju_model_substrate",
            lambda name: "machine" if name == "stale-lxd" else None,
        )
        monkeypatch.setattr(
            "cantrip.agent.controllers.watcher_controller.detect_current_juju_model",
            lambda **_kwargs: "fresh-k8s",
        )

        assert agent.start_watcher() is True
        assert agent.state.dev_model == "fresh-k8s"

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_start_watcher_keeps_dev_model_when_substrate_unknown(self, monkeypatch):
        """Without charm_type, an existing dev_model is left alone."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "user-chosen"
        # charm_type intentionally unset.

        called = {"detect": 0}

        def _detect(**_kwargs) -> str | None:
            called["detect"] += 1
            return "should-not-be-used"

        monkeypatch.setattr(
            "cantrip.agent.controllers.watcher_controller.detect_current_juju_model", _detect
        )

        assert agent.start_watcher() is True
        assert agent.state.dev_model == "user-chosen"
        assert called["detect"] == 0

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_stop_watcher(self):
        """stop_watcher stops the watcher and clears the flag."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.start_watcher()

        await agent.stop_watcher()

        assert not agent.watcher_running
        assert not agent.state.watcher_enabled

    @pytest.mark.asyncio
    async def test_stop_watcher_when_not_running(self):
        """stop_watcher is a no-op when no watcher is active."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        await agent.stop_watcher()

        assert not agent.watcher_running

    @pytest.mark.asyncio
    async def test_process_watcher_event_no_watcher(self):
        """process_watcher_event returns None when no watcher is active."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        result = await agent.process_watcher_event()

        assert result is None

    @pytest.mark.asyncio
    async def test_process_watcher_event_empty_queue(self):
        """process_watcher_event returns None when queue is empty."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.start_watcher()

        result = await agent.process_watcher_event()

        assert result is None
        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_process_watcher_event_routes_to_queue(self):
        """process_watcher_event dequeues and routes to the task queue."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.start_watcher()

        # Manually enqueue an event.
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        agent._watcher_ctl._watcher._enqueue(event)

        result = await agent.process_watcher_event()

        assert result is not None
        assert "Hook failure on myapp/0" in result
        # Task should be in the work queue.
        tasks = agent.work_queue.all_tasks()
        assert len(tasks) >= 1
        assert any("Hook failure" in t.title for t in tasks)
        await agent.stop_watcher()

    def test_route_watcher_event_creates_task(self):
        """route_watcher_event creates a DEBUG task for a hook_failure event."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        task = agent.route_watcher_event(event)

        assert task is not None
        assert task.category.value == "debug"
        assert task in agent.work_queue.all_tasks()

    def test_route_watcher_event_no_dev_model_returns_none(self):
        """route_watcher_event returns None without a dev_model."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        # No dev_model set.

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure",
            detail="boom",
        )
        result = agent.route_watcher_event(event)

        assert result is None
        assert len(agent.work_queue.all_tasks()) == 0

    @pytest.mark.asyncio
    async def test_start_watcher_auto_routes_events(self):
        """Events enqueued by the watcher are automatically routed to the task queue."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"

        events_received: list[WatcherEvent] = []
        agent.start_watcher(on_event=lambda e: events_received.append(e))

        # Simulate an event through the watcher's internal enqueue.
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        agent._watcher_ctl._watcher._enqueue(event)

        # The auto-route callback fires synchronously during _enqueue.
        tasks = agent.work_queue.all_tasks()
        assert len(tasks) >= 1
        assert any("Hook failure" in t.title for t in tasks)
        # External callback should also have fired.
        assert len(events_received) == 1
        await agent.stop_watcher()

    def test_watcher_enabled_in_system_prompt(self):
        """watcher_enabled appears in the system prompt when active."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.state.watcher_enabled = True

        prompt = agent._build_system_prompt()

        assert "Event Watcher" in prompt
        assert "[Watcher]" in prompt

    def test_watcher_disabled_not_in_system_prompt(self):
        """Watcher section absent from system prompt when disabled."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        prompt = agent._build_system_prompt()

        assert "Event Watcher" not in prompt

    def test_paused_watcher_not_in_system_prompt(self):
        """The Event Watcher section is suppressed while reactions are paused."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.state.watcher_enabled = True
        agent.state.watcher_reacting = False

        prompt = agent._build_system_prompt()

        assert "Event Watcher" not in prompt

    def test_toggle_watcher_reacting_flips_flag(self):
        """toggle_watcher_reacting flips state.watcher_reacting and returns it."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)

        assert agent.watcher_reacting is True
        assert agent.toggle_watcher_reacting() is False
        assert agent.watcher_reacting is False
        assert agent.toggle_watcher_reacting() is True
        assert agent.watcher_reacting is True

    @pytest.mark.asyncio
    async def test_paused_watcher_does_not_route_events(self):
        """While reactions are paused the watcher still observes — fires the
        external callback — but does not queue tasks.
        """
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"
        agent.state.watcher_reacting = False

        events_received: list[WatcherEvent] = []
        agent.start_watcher(on_event=lambda e: events_received.append(e))

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        agent._watcher_ctl._watcher._enqueue(event)

        assert len(agent.work_queue.all_tasks()) == 0
        assert len(events_received) == 1

        # Resuming makes the next event route normally.
        agent.toggle_watcher_reacting()
        event2 = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/1",
            detail="hook failed: start",
            app="myapp",
            unit="myapp/1",
        )
        agent._watcher_ctl._watcher._enqueue(event2)
        assert len(agent.work_queue.all_tasks()) == 1

        await agent.stop_watcher()

    @pytest.mark.asyncio
    async def test_watcher_can_restart_after_stop(self):
        """A stopped watcher restarts cleanly (dev_model is retained)."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider)
        agent.state.dev_model = "dev"

        assert agent.start_watcher() is True
        assert agent.watcher_running
        await agent.stop_watcher()
        assert not agent.watcher_running

        assert agent.start_watcher() is True
        assert agent.watcher_running
        assert agent.state.dev_model == "dev"
        await agent.stop_watcher()
