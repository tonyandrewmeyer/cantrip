"""Tests for Phase 69.2 unattended (yolo) mode."""

from __future__ import annotations

import asyncio

import pytest

from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.core import CantripAgent
from cantrip.agent.safety.permissions import PermissionAskRequest, PermissionManager
from cantrip.ui import events
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# PermissionManager.yolo
# ---------------------------------------------------------------------------


class TestPermissionManagerYolo:
    @pytest.mark.asyncio
    async def test_request_auto_approves_when_yolo_on(self):
        manager = PermissionManager(timeout_seconds=5.0)
        manager.set_yolo(True)

        approved = await manager.request(tool_name="run_command", reason="rule matches")

        assert approved is True
        assert manager.pending == []

    @pytest.mark.asyncio
    async def test_auto_approve_callback_fires(self):
        manager = PermissionManager(timeout_seconds=5.0)
        received: list[PermissionAskRequest] = []
        manager.set_on_auto_approve(received.append)
        manager.set_yolo(True)

        approved = await manager.request(
            tool_name="git_push",
            reason="git push*",
            arguments={"command": "git push origin main"},
        )

        assert approved is True
        assert len(received) == 1
        assert received[0].tool_name == "git_push"
        assert received[0].command == "git push origin main"

    @pytest.mark.asyncio
    async def test_normal_request_still_parks_when_yolo_off(self):
        manager = PermissionManager(timeout_seconds=5.0)
        received: list[PermissionAskRequest] = []
        manager.set_on_request(received.append)
        # Yolo off by default.

        async def approve_soon() -> None:
            while not manager.pending:
                await asyncio.sleep(0)
            manager.resolve(manager.pending[0], approved=True)

        task = asyncio.create_task(approve_soon())
        approved = await manager.request(tool_name="x", reason="y")
        await task

        assert approved is True
        assert len(received) == 1  # Normal fanout fired, not auto-approve.

    @pytest.mark.asyncio
    async def test_set_yolo_resolves_pending_requests(self):
        manager = PermissionManager(timeout_seconds=5.0)
        t = asyncio.create_task(manager.request(tool_name="x", reason="y"))
        # Let the request register.
        while not manager.pending:
            await asyncio.sleep(0)
        manager.set_yolo(True)
        approved = await t
        assert approved is True

    def test_yolo_mode_property(self):
        manager = PermissionManager()
        assert manager.yolo_mode is False
        manager.set_yolo(True)
        assert manager.yolo_mode is True
        manager.set_yolo(False)
        assert manager.yolo_mode is False


# ---------------------------------------------------------------------------
# /yolo slash command
# ---------------------------------------------------------------------------


class TestSlashCommand:
    def test_toggle_flips_state(self):
        agent = CantripAgent(provider=FakeProvider())
        assert agent.state.yolo_mode is False

        result = slash_commands.dispatch(agent, "/yolo")
        assert result is not None
        assert agent.state.yolo_mode is True
        assert "Yolo mode on" in result.text

        result = slash_commands.dispatch(agent, "/yolo")
        assert result is not None
        assert agent.state.yolo_mode is False
        assert "Yolo mode off" in result.text

    def test_explicit_on_and_off(self):
        agent = CantripAgent(provider=FakeProvider())
        slash_commands.dispatch(agent, "/yolo on")
        assert agent.state.yolo_mode is True
        slash_commands.dispatch(agent, "/yolo off")
        assert agent.state.yolo_mode is False

    def test_noop_when_already_in_target_state(self):
        agent = CantripAgent(provider=FakeProvider())
        slash_commands.dispatch(agent, "/yolo on")
        result = slash_commands.dispatch(agent, "/yolo on")
        assert result is not None
        assert "Already in yolo mode on" in result.text

    def test_rejects_unknown_argument(self):
        agent = CantripAgent(provider=FakeProvider())
        result = slash_commands.dispatch(agent, "/yolo maybe")
        assert result is not None
        assert "Usage" in result.text
        assert agent.state.yolo_mode is False

    def test_emits_status_bar_event(self):
        agent = CantripAgent(provider=FakeProvider())
        received: list[events.Event] = []
        agent.event_bus.subscribe(events.EventType.STATUS_BAR_CHANGED, received.append)

        slash_commands.dispatch(agent, "/yolo")
        slash_commands.dispatch(agent, "/yolo off")

        modes = [ev.payload.get("mode") for ev in received]
        assert "yolo" in modes
        assert "build" in modes

    def test_help_text_includes_yolo(self):
        assert "/yolo" in slash_commands.help_text()

    def test_catalogue_includes_yolo(self):
        verbs = {entry.verb for entry in slash_commands.COMMAND_CATALOGUE}
        assert "/yolo" in verbs


# ---------------------------------------------------------------------------
# Event factory
# ---------------------------------------------------------------------------


class TestAutoApprovedEvent:
    def test_factory_builds_expected_payload(self):
        ev = events.permission_auto_approved(
            tool_name="run_command",
            reason="sudo *",
            request_id="abc",
            command="sudo apt update",
        )
        assert ev.type is events.EventType.PERMISSION_AUTO_APPROVED
        assert ev.payload["tool_name"] == "run_command"
        assert ev.payload["reason"] == "sudo *"
        assert ev.payload["request_id"] == "abc"
        assert ev.payload["command"] == "sudo apt update"
