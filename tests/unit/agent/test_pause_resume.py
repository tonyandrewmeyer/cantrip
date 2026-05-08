"""Tests for Phase 99.1 ``/pause`` and ``/resume`` slash commands."""

from __future__ import annotations

from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.core import CantripAgent
from cantrip.ui import events
from tests.conftest import FakeProvider


class TestExecutorControllerUserPause:
    def test_user_pause_sets_flag_and_returns_true_first_time(self):
        agent = CantripAgent(provider=FakeProvider())
        ctl = agent._executor_ctl

        assert ctl.user_paused is False
        assert ctl.user_pause() is True
        assert ctl.user_paused is True
        # Second call is a no-op — already paused.
        assert ctl.user_pause() is False

    def test_user_resume_clears_flag_and_returns_true_first_time(self):
        agent = CantripAgent(provider=FakeProvider())
        ctl = agent._executor_ctl
        ctl.user_pause()

        assert ctl.user_resume() is True
        assert ctl.user_paused is False
        # Second call is a no-op — already running.
        assert ctl.user_resume() is False

    def test_transient_resume_skipped_while_user_paused(self):
        """``ExecutorController.resume()`` must not unpause user-paused loops.

        The conversation loop calls ``resume()`` after every chat turn;
        if that quietly cleared a user pause the autonomous loop would
        restart the moment the user typed any reply.
        """
        agent = CantripAgent(provider=FakeProvider())
        ctl = agent._executor_ctl
        ctl.user_pause()

        # Simulates the conversation-loop finally block.
        ctl.resume()

        assert ctl.user_paused is True


class TestSlashPause:
    def test_dispatch_toggles_user_paused(self):
        agent = CantripAgent(provider=FakeProvider())
        assert agent._executor_ctl.user_paused is False

        result = slash_commands.dispatch(agent, "/pause")
        assert result is not None
        assert agent._executor_ctl.user_paused is True
        assert "Autonomous loop paused" in result.text

    def test_dispatch_redundant_invocation_is_noop(self):
        agent = CantripAgent(provider=FakeProvider())
        slash_commands.dispatch(agent, "/pause")

        result = slash_commands.dispatch(agent, "/pause")
        assert result is not None
        assert "Already paused" in result.text
        assert agent._executor_ctl.user_paused is True

    def test_rejects_arguments(self):
        agent = CantripAgent(provider=FakeProvider())
        result = slash_commands.dispatch(agent, "/pause now")
        assert result is not None
        assert "Usage" in result.text
        assert agent._executor_ctl.user_paused is False

    def test_emits_status_bar_event(self):
        agent = CantripAgent(provider=FakeProvider())
        received: list[events.Event] = []
        agent.event_bus.subscribe(events.EventType.STATUS_BAR_CHANGED, received.append)

        slash_commands.dispatch(agent, "/pause")

        loop_states = [ev.payload.get("loop_state") for ev in received]
        assert "paused" in loop_states


class TestSlashResume:
    def test_dispatch_clears_user_paused(self):
        agent = CantripAgent(provider=FakeProvider())
        slash_commands.dispatch(agent, "/pause")

        result = slash_commands.dispatch(agent, "/resume")
        assert result is not None
        assert agent._executor_ctl.user_paused is False
        assert "Autonomous loop resumed" in result.text

    def test_dispatch_redundant_invocation_is_noop(self):
        agent = CantripAgent(provider=FakeProvider())
        # Not paused.
        result = slash_commands.dispatch(agent, "/resume")
        assert result is not None
        assert "Already running" in result.text
        assert agent._executor_ctl.user_paused is False

    def test_rejects_arguments(self):
        agent = CantripAgent(provider=FakeProvider())
        slash_commands.dispatch(agent, "/pause")

        result = slash_commands.dispatch(agent, "/resume now")
        assert result is not None
        assert "Usage" in result.text
        # Pause flag stays put — argv rejection is a guard, not a toggle.
        assert agent._executor_ctl.user_paused is True

    def test_emits_status_bar_event(self):
        agent = CantripAgent(provider=FakeProvider())
        slash_commands.dispatch(agent, "/pause")

        received: list[events.Event] = []
        agent.event_bus.subscribe(events.EventType.STATUS_BAR_CHANGED, received.append)
        slash_commands.dispatch(agent, "/resume")

        # Phase 99.4: /resume publishes whatever the lifecycle projection
        # says — never ``paused``, never the hard-coded literal.  An
        # empty queue resolves to ``done`` here; any of the non-paused
        # labels is the correct answer for "the user-pause flag came
        # off".
        loop_states = [ev.payload.get("loop_state") for ev in received]
        assert loop_states  # at least one event emitted
        assert "paused" not in loop_states
        assert all(s in {"running", "done", "blocked", "budget-limited"} for s in loop_states)


class TestCatalogueAndHelp:
    def test_catalogue_includes_pause_and_resume(self):
        verbs = {entry.verb for entry in slash_commands.COMMAND_CATALOGUE}
        assert "/pause" in verbs
        assert "/resume" in verbs

    def test_help_text_includes_pause_and_resume(self):
        text = slash_commands.help_text()
        assert "/pause" in text
        assert "/resume" in text
