"""Tests for Phase 68.4 plan mode."""

from __future__ import annotations

import pytest

from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.core import (
    CantripAgent,
    _extract_proposed_changes,
    _plan_mode_refusal,
)
from cantrip.agent.safety.permissions import (
    PLAN_MODE_ALLOWED_TOOLS,
    PLAN_MODE_OVERLAY,
    PermissionOutcome,
    PermissionRule,
    PermissionRuleset,
    compose_rulesets,
    evaluate,
)
from cantrip.agent.state import AgentState
from cantrip.llm.base import Response
from cantrip.ui import events
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# PLAN_MODE_OVERLAY matrix
# ---------------------------------------------------------------------------


class TestPlanModeOverlay:
    def test_read_only_tools_allow(self):
        for tool in (
            "read_file",
            "glob",
            "grep",
            "git_diff",
            "git_log",
            "juju_status",
            "web_search",
            "web_fetch",
            "memory_read",
        ):
            decision = evaluate(PLAN_MODE_OVERLAY, tool)
            assert decision.outcome is PermissionOutcome.ALLOW, tool

    def test_write_tools_deny(self):
        for tool in (
            "write_file",
            "edit_file",
            "git_push",
            "git_commit",
            "run_command",
            "juju_deploy",
            "juju_destroy_model",
        ):
            decision = evaluate(PLAN_MODE_OVERLAY, tool)
            assert decision.outcome is PermissionOutcome.DENY, tool
            assert "plan-mode" in decision.reason

    def test_composes_onto_base_as_last_wins(self):
        """A base rule that allows a write tool is overridden by plan mode."""
        base = PermissionRuleset(
            tools=(
                # Pretend the user allowed ``write_file`` globally.
                PermissionRule("write_file", PermissionOutcome.ALLOW, source="user"),
            )
        )
        composed = compose_rulesets(base, PLAN_MODE_OVERLAY)
        assert evaluate(composed, "write_file").outcome is PermissionOutcome.DENY
        # A read-only tool stays ALLOW.
        assert evaluate(composed, "read_file").outcome is PermissionOutcome.ALLOW


# ---------------------------------------------------------------------------
# /plan and /build slash commands
# ---------------------------------------------------------------------------


class TestSlashCommands:
    def test_plan_flips_state_and_emits_event(self):
        agent = CantripAgent(provider=FakeProvider())
        received: list[events.Event] = []
        agent.event_bus.subscribe(events.EventType.STATUS_BAR_CHANGED, received.append)

        result = slash_commands.dispatch(agent, "/plan")

        assert result is not None
        assert agent.state.plan_mode is True
        assert "Plan mode on" in result.text
        assert any(ev.payload.get("mode") == "plan" for ev in received)

    def test_build_clears_state_and_emits_event(self):
        agent = CantripAgent(provider=FakeProvider())
        agent.state.plan_mode = True
        agent.state.plan_summary = "- edit foo.py\n- run tests"
        received: list[events.Event] = []
        agent.event_bus.subscribe(events.EventType.STATUS_BAR_CHANGED, received.append)

        result = slash_commands.dispatch(agent, "/build")

        assert result is not None
        assert agent.state.plan_mode is False
        assert "Build mode on" in result.text
        assert "Resumed" in result.text
        # The plan summary was spliced into messages as an assistant turn.
        assert any(
            m.role.value == "assistant" and "Proposed changes" in m.content
            for m in agent.state.messages
        )
        assert agent.state.plan_summary is None
        assert any(ev.payload.get("mode") == "build" for ev in received)

    def test_double_plan_is_noop(self):
        agent = CantripAgent(provider=FakeProvider())
        agent.state.plan_mode = True
        result = slash_commands.dispatch(agent, "/plan")
        assert result is not None
        assert "Already in plan mode" in result.text

    def test_double_build_is_noop(self):
        agent = CantripAgent(provider=FakeProvider())
        result = slash_commands.dispatch(agent, "/build")
        assert result is not None
        assert "Already in build mode" in result.text

    def test_help_lists_new_verbs(self):
        assert "/plan" in slash_commands.help_text()
        assert "/build" in slash_commands.help_text()

    def test_catalogue_includes_new_verbs(self):
        verbs = {entry.verb for entry in slash_commands.COMMAND_CATALOGUE}
        assert "/plan" in verbs
        assert "/build" in verbs


# ---------------------------------------------------------------------------
# Main-agent plan-mode refusal helper
# ---------------------------------------------------------------------------


class TestPlanModeRefusal:
    def test_returns_none_when_plan_mode_off(self):
        state = AgentState()
        assert _plan_mode_refusal(state, "write_file") is None

    def test_returns_none_for_allowed_tool(self):
        state = AgentState(plan_mode=True)
        assert _plan_mode_refusal(state, "read_file") is None

    def test_refuses_disallowed_tool(self):
        state = AgentState(plan_mode=True)
        result = _plan_mode_refusal(state, "write_file")
        assert result is not None
        assert result.success is False
        assert "Plan mode" in (result.error or "")

    def test_mcp_tools_bypass(self):
        state = AgentState(plan_mode=True)
        assert _plan_mode_refusal(state, "mcp__server__tool") is None

    def test_every_allowlisted_tool_is_unique(self):
        """Protect against copy-paste typos drifting the allowlist."""
        assert len(PLAN_MODE_ALLOWED_TOOLS) == len(set(PLAN_MODE_ALLOWED_TOOLS))


# ---------------------------------------------------------------------------
# Proposed-changes extractor
# ---------------------------------------------------------------------------


class TestExtractProposedChanges:
    def test_captures_section(self):
        content = (
            "I've thought about it.\n\n"
            "## Proposed changes\n"
            "- Edit src/charm.py: add `status` handler\n"
            "- Run `make check`\n"
        )
        assert _extract_proposed_changes(content) == (
            "- Edit src/charm.py: add `status` handler\n- Run `make check`"
        )

    def test_case_insensitive(self):
        content = "### PROPOSED CHANGES\n\n- One\n- Two\n"
        assert _extract_proposed_changes(content) == "- One\n- Two"

    def test_stops_at_next_heading(self):
        content = "## Proposed changes\n- Do a thing\n\n## Notes\nThese should not leak.\n"
        captured = _extract_proposed_changes(content)
        assert captured == "- Do a thing"

    def test_missing_section_returns_none(self):
        assert _extract_proposed_changes("No plan here.") is None


# ---------------------------------------------------------------------------
# Plan summary capture flow
# ---------------------------------------------------------------------------


class TestPlanSummaryCapture:
    @pytest.mark.asyncio
    async def test_assistant_response_captures_proposed_changes(self):
        response = Response(
            content=(
                "Here is my plan.\n\n"
                "## Proposed changes\n"
                "- Add a README section\n"
                "- Run `make format`\n"
            )
        )
        agent = CantripAgent(provider=FakeProvider([response]))
        agent.state.plan_mode = True

        await agent.process_message("Plan the docs update.")

        assert agent.state.plan_summary == ("- Add a README section\n- Run `make format`")

    @pytest.mark.asyncio
    async def test_no_capture_when_plan_mode_off(self):
        response = Response(
            content="## Proposed changes\n- Something\n",
        )
        agent = CantripAgent(provider=FakeProvider([response]))
        # Default state has plan_mode=False.

        await agent.process_message("Say hi.")

        assert agent.state.plan_summary is None

    @pytest.mark.asyncio
    async def test_no_section_leaves_prior_summary(self):
        # Seed a prior summary from a previous turn.
        agent = CantripAgent(provider=FakeProvider([Response(content="Just chatting.")]))
        agent.state.plan_mode = True
        agent.state.plan_summary = "- prior\n- notes"

        await agent.process_message("Hi.")

        # Prior summary survives an unrelated response.
        assert agent.state.plan_summary == "- prior\n- notes"


# ---------------------------------------------------------------------------
# System prompt appendix
# ---------------------------------------------------------------------------


class TestSystemPromptAppendix:
    def test_plan_mode_appends_guidance(self):
        agent = CantripAgent(provider=FakeProvider())
        # Baseline prompt.
        prompt_build = agent._build_system_prompt()
        assert "Plan mode" not in prompt_build

        agent.state.plan_mode = True
        prompt_plan = agent._build_system_prompt()
        assert "Plan mode" in prompt_plan
        assert "Proposed changes" in prompt_plan
