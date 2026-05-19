"""Unit tests for the watcher action cohort (Phase 93.1 backfill).

``cantrip.tui.actions.watcher`` is a thin set of helpers the TUI app
delegates to for the event watcher: subscribe, start/stop, status-bar
refresh, model-pane refresh, and the toggle binding.  These ran only
through the live app before; here they are driven directly with a
light fake ``app`` so the no-agent guards and the retry-timer branch
are covered explicitly.
"""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.css.query import NoMatches

from cantrip.agent.queue import TaskStatus
from cantrip.tui.actions import watcher as watcher_actions

pytestmark = pytest.mark.tui


def _fake_app(*, agent: object | None = None) -> MagicMock:
    """A MagicMock app whose ``query_one`` returns fresh widget stand-ins."""
    app = MagicMock()
    app._agent = agent
    app._watcher_retry_timer = None
    app.query_one.side_effect = lambda *_a, **_k: MagicMock()
    # Make ``run_worker`` consume the coroutine so it isn't left un-awaited.
    app.run_worker.side_effect = lambda coro, *_a, **_k: coro.close()
    return app


def _fake_agent(*, running: bool = False, reacting: bool = True) -> MagicMock:
    agent = MagicMock()
    agent.watcher_running = running
    agent.watcher_reacting = reacting
    agent.start_watcher = MagicMock(return_value=True)
    agent.stop_watcher = AsyncMock()

    def _toggle() -> bool:
        agent.watcher_reacting = not agent.watcher_reacting
        return agent.watcher_reacting

    agent.toggle_watcher_reacting = MagicMock(side_effect=_toggle)
    agent.event_bus = MagicMock()
    agent._watcher_ctl = MagicMock()
    agent.work_queue.all_tasks = MagicMock(return_value=[])
    return agent


# ---------------------------------------------------------------------------
# subscribe / start / stop
# ---------------------------------------------------------------------------


class TestSubscribe:
    def test_no_agent_is_a_noop(self) -> None:
        app = _fake_app(agent=None)
        watcher_actions.subscribe_events(app)  # must not raise

    def test_subscribes_to_both_event_types(self) -> None:
        agent = _fake_agent()
        app = _fake_app(agent=agent)
        watcher_actions.subscribe_events(app)
        assert agent.event_bus.subscribe.call_count == 2


class TestStartWatcher:
    def test_no_agent_is_a_noop(self) -> None:
        watcher_actions.start_watcher(_fake_app(agent=None))

    def test_already_running_is_a_noop(self) -> None:
        agent = _fake_agent(running=True)
        app = _fake_app(agent=agent)
        watcher_actions.start_watcher(app)
        agent.start_watcher.assert_not_called()

    def test_started_clears_pending_retry_timer(self) -> None:
        agent = _fake_agent()
        agent.start_watcher.return_value = True
        app = _fake_app(agent=agent)
        timer = MagicMock()
        app._watcher_retry_timer = timer
        watcher_actions.start_watcher(app)
        timer.stop.assert_called_once()
        assert app._watcher_retry_timer is None

    def test_not_started_schedules_a_retry(self) -> None:
        agent = _fake_agent()
        agent.start_watcher.return_value = False
        app = _fake_app(agent=agent)
        sentinel = object()
        app.set_interval.return_value = sentinel
        watcher_actions.start_watcher(app)
        app.set_interval.assert_called_once()
        assert app._watcher_retry_timer is sentinel

    def test_not_started_with_existing_timer_does_not_reschedule(self) -> None:
        agent = _fake_agent()
        agent.start_watcher.return_value = False
        app = _fake_app(agent=agent)
        app._watcher_retry_timer = MagicMock()
        watcher_actions.start_watcher(app)
        app.set_interval.assert_not_called()


class TestStopWatcher:
    @pytest.mark.asyncio
    async def test_no_agent_is_a_noop(self) -> None:
        await watcher_actions.stop_watcher(_fake_app(agent=None))

    @pytest.mark.asyncio
    async def test_stops_and_refreshes_status_bar(self) -> None:
        agent = _fake_agent(running=True)
        app = _fake_app(agent=agent)
        await watcher_actions.stop_watcher(app)
        agent.stop_watcher.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_clears_pending_retry_timer(self) -> None:
        agent = _fake_agent(running=True)
        app = _fake_app(agent=agent)
        timer = MagicMock()
        app._watcher_retry_timer = timer
        await watcher_actions.stop_watcher(app)
        timer.stop.assert_called_once()
        assert app._watcher_retry_timer is None


# ---------------------------------------------------------------------------
# model panes / bus handlers
# ---------------------------------------------------------------------------


class TestRefreshModelPanes:
    def test_no_agent_is_a_noop(self) -> None:
        watcher_actions.refresh_model_panes(_fake_app(agent=None))

    def test_pushes_latest_snapshots_when_present(self) -> None:
        agent = _fake_agent()
        agent._watcher_ctl.latest_status = {"dev": 1}
        agent._watcher_ctl.latest_cos_status = {"cos": 2}
        widget = MagicMock()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: widget
        watcher_actions.refresh_model_panes(app)
        assert widget.dev_status == {"dev": 1}
        assert widget.cos_status == {"cos": 2}

    def test_skips_panes_when_snapshots_are_none(self) -> None:
        agent = _fake_agent()
        agent._watcher_ctl.latest_status = None
        agent._watcher_ctl.latest_cos_status = None
        widget = types.SimpleNamespace()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: widget
        watcher_actions.refresh_model_panes(app)
        assert not hasattr(widget, "dev_status")
        assert not hasattr(widget, "cos_status")

    def test_on_watcher_event_posts_summary_and_refreshes(self) -> None:
        agent = _fake_agent()
        chat = MagicMock()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: chat
        event = types.SimpleNamespace(payload={"summary": "unit ready"})
        watcher_actions.on_watcher_event(app, event)
        chat.add_system_message.assert_called_once()
        assert "unit ready" in chat.add_system_message.call_args[0][0]

    def test_on_juju_status_refreshes_panes(self) -> None:
        agent = _fake_agent()
        app = _fake_app(agent=agent)
        # No agent → underlying refresh is a no-op; with agent it queries.
        watcher_actions.on_juju_status(app)
        app.query_one.assert_called()


# ---------------------------------------------------------------------------
# status bar
# ---------------------------------------------------------------------------


class TestStatusBar:
    def test_update_status_bar_shows_indicator_when_running(self) -> None:
        agent = _fake_agent(running=True)
        bar = MagicMock()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: bar
        watcher_actions.update_status_bar(app)
        assert bar.watcher_status == "👁 Watching"

    def test_update_status_bar_shows_paused_when_not_reacting(self) -> None:
        agent = _fake_agent(running=True, reacting=False)
        bar = MagicMock()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: bar
        watcher_actions.update_status_bar(app)
        assert bar.watcher_status == "👁 Watching (paused)"

    def test_update_status_bar_clears_indicator_when_idle(self) -> None:
        bar = MagicMock()
        app = _fake_app(agent=_fake_agent(running=False))
        app.query_one.side_effect = lambda *_a, **_k: bar
        watcher_actions.update_status_bar(app)
        assert bar.watcher_status == ""

    def test_refresh_subagent_status_bar_no_agent(self) -> None:
        watcher_actions.refresh_subagent_status_bar(_fake_app(agent=None))

    def test_refresh_subagent_status_bar_handles_missing_widget(self) -> None:
        app = _fake_app(agent=_fake_agent())
        app.query_one.side_effect = NoMatches("status-bar")
        watcher_actions.refresh_subagent_status_bar(app)  # must not raise

    def test_refresh_subagent_status_bar_shows_active_phase(self) -> None:
        agent = _fake_agent()
        task = types.SimpleNamespace(
            status=TaskStatus.ACTIVE, subagent_phase="build", title="Build charm"
        )
        agent.work_queue.all_tasks.return_value = [task]
        bar = MagicMock()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: bar
        watcher_actions.refresh_subagent_status_bar(app)
        assert "build" in bar.subagent_label and "Build charm" in bar.subagent_label

    def test_refresh_subagent_status_bar_clears_when_idle(self) -> None:
        agent = _fake_agent()
        agent.work_queue.all_tasks.return_value = [
            types.SimpleNamespace(status=TaskStatus.DONE, subagent_phase="", title="x")
        ]
        bar = MagicMock()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: bar
        watcher_actions.refresh_subagent_status_bar(app)
        assert bar.subagent_label == ""


# ---------------------------------------------------------------------------
# toggle binding
# ---------------------------------------------------------------------------


class TestToggleWatcher:
    def test_no_agent_is_a_noop(self) -> None:
        watcher_actions.toggle_watcher(_fake_app(agent=None))

    def test_pause_when_reacting(self) -> None:
        agent = _fake_agent(running=True, reacting=True)
        chat = MagicMock()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: chat
        watcher_actions.toggle_watcher(app)
        agent.toggle_watcher_reacting.assert_called_once()
        assert agent.watcher_reacting is False
        assert "paused" in chat.add_system_message.call_args[0][0]

    def test_resume_when_paused(self) -> None:
        agent = _fake_agent(running=True, reacting=False)
        chat = MagicMock()
        app = _fake_app(agent=agent)
        app.query_one.side_effect = lambda *_a, **_k: chat
        watcher_actions.toggle_watcher(app)
        agent.toggle_watcher_reacting.assert_called_once()
        assert agent.watcher_reacting is True
        assert "resumed" in chat.add_system_message.call_args[0][0]

    def test_toggle_does_not_start_or_stop_the_watcher(self) -> None:
        agent = _fake_agent(running=True)
        app = _fake_app(agent=agent)
        watcher_actions.toggle_watcher(app)
        agent.start_watcher.assert_not_called()
        agent.stop_watcher.assert_not_called()
