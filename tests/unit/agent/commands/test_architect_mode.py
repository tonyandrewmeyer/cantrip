"""Tests for Phase 71.2 — architect / editor two-model split.

Scenarios covered:

* ``handle_architect`` slash command (toggle, on/off, editor override,
  status-bar event, error paths).
* ``state.architect_mode`` opting in via the ``--architect`` CLI flag
  (REPL + print-mode plumbing).
* Conversation loop: when architect mode is on, both passes run, both
  record usage attributed to their own provider, both fire transcript
  events, and tool calls land on the editor's response.
* Fall-through: ``architect_consecutive_failures`` ticks on
  all-failed editor rounds and resets on a successful round; once it
  hits ``architect_failure_threshold`` the editor escalates to the
  architect provider for the next pass.
* ``_describe_editor`` helper returns the right label for each
  configuration.
"""

from __future__ import annotations

import pytest

from cantrip.agent.commands import modes as mode_commands
from cantrip.agent.core import CantripAgent
from cantrip.llm.base import Message, Response, Role, ToolCall, ToolResult
from cantrip.ui import events
from tests.conftest import FakeProvider


def _named(model_name: str, **kwargs: object) -> FakeProvider:
    """FakeProvider with a stable model_name (so usage attribution is checkable)."""
    provider = FakeProvider(**kwargs)
    provider.model_name = model_name
    return provider


# ---------------------------------------------------------------------------
# /architect slash command
# ---------------------------------------------------------------------------


class TestArchitectSlash:
    def test_bare_toggles_on_then_off(self):
        agent = CantripAgent(provider=_named("opus"))
        result = mode_commands.handle_architect(agent, "")
        assert agent.state.architect_mode is True
        assert "Architect mode on" in result
        result = mode_commands.handle_architect(agent, "")
        assert agent.state.architect_mode is False
        assert "Architect mode off" in result

    def test_explicit_on_off(self):
        agent = CantripAgent(provider=_named("opus"))
        mode_commands.handle_architect(agent, "on")
        assert agent.state.architect_mode is True
        mode_commands.handle_architect(agent, "off")
        assert agent.state.architect_mode is False

    def test_editor_override_parses_provider_only(self):
        agent = CantripAgent(provider=_named("opus"))
        result = mode_commands.handle_architect(agent, "on claude")
        assert agent.state.architect_mode is True
        assert agent.state.editor_provider == "claude"
        assert agent.state.editor_model is None
        assert "Editor: `claude" in result

    def test_editor_override_parses_provider_and_model(self):
        agent = CantripAgent(provider=_named("opus"))
        mode_commands.handle_architect(agent, "on claude/claude-haiku-4-5-20251001")
        assert agent.state.editor_provider == "claude"
        assert agent.state.editor_model == "claude-haiku-4-5-20251001"

    def test_unknown_editor_provider_rejected(self):
        agent = CantripAgent(provider=_named("opus"))
        result = mode_commands.handle_architect(agent, "on bogus")
        assert "Unknown editor provider" in result
        assert agent.state.architect_mode is False

    def test_off_drops_editor_override(self):
        agent = CantripAgent(provider=_named("opus"))
        mode_commands.handle_architect(agent, "on claude/x")
        assert agent.state.editor_provider == "claude"
        mode_commands.handle_architect(agent, "off")
        assert agent.state.editor_provider is None
        assert agent.state.editor_model is None

    def test_no_op_when_already_in_target_state(self):
        agent = CantripAgent(provider=_named("opus"))
        mode_commands.handle_architect(agent, "on")
        result = mode_commands.handle_architect(agent, "on")
        assert "already on" in result.lower()

    def test_bad_argument_returns_usage(self):
        agent = CantripAgent(provider=_named("opus"))
        result = mode_commands.handle_architect(agent, "yes please")
        assert result.startswith("Usage:")
        assert agent.state.architect_mode is False

    def test_editor_spec_with_off_rejected(self):
        agent = CantripAgent(provider=_named("opus"))
        result = mode_commands.handle_architect(agent, "off claude")
        assert "Editor override only makes sense" in result

    def test_status_bar_event_published(self):
        agent = CantripAgent(provider=_named("opus"))
        seen: list[str] = []

        def listener(event: events.Event) -> None:
            if event.type is events.EventType.STATUS_BAR_CHANGED:
                seen.append(str(event.payload.get("mode", "")))

        agent.event_bus.subscribe(events.EventType.STATUS_BAR_CHANGED, listener)
        mode_commands.handle_architect(agent, "on")
        mode_commands.handle_architect(agent, "off")
        assert "architect" in seen
        assert "build" in seen


# ---------------------------------------------------------------------------
# Editor provider resolution
# ---------------------------------------------------------------------------


class TestEditorProviderResolution:
    def test_describe_editor_uses_override(self):
        agent = CantripAgent(provider=_named("opus"))
        agent.state.editor_provider = "claude"
        agent.state.editor_model = "claude-haiku"
        assert mode_commands._describe_editor(agent) == "claude/claude-haiku"

    def test_describe_editor_uses_light_provider(self):
        agent = CantripAgent(
            provider=_named("opus"),
            light_provider=_named("haiku"),
        )
        # Light provider name comes from FakeProvider.name == "fake".
        assert mode_commands._describe_editor(agent) == "fake/haiku"

    def test_describe_editor_falls_back_to_main(self):
        agent = CantripAgent(provider=_named("opus"))
        # No light provider, no override.
        assert mode_commands._describe_editor(agent) == "fake/opus"

    def test_editor_provider_helper_picks_light_when_no_override(self):
        light = _named("haiku")
        agent = CantripAgent(provider=_named("opus"), light_provider=light)
        assert agent._editor_provider() is light

    def test_editor_provider_helper_falls_back_to_main(self):
        agent = CantripAgent(provider=_named("opus"))
        assert agent._editor_provider() is agent.provider

    def test_editor_provider_escalates_after_repeated_failures(self):
        light = _named("haiku")
        agent = CantripAgent(provider=_named("opus"), light_provider=light)
        agent.state.architect_mode = True
        agent.state.architect_consecutive_failures = agent.state.architect_failure_threshold
        assert agent._editor_provider() is agent.provider

    def test_all_tool_calls_failed_predicate(self):
        empty: list[ToolResult] = []
        assert CantripAgent._all_tool_calls_failed(empty) is False

        only_ok = [ToolResult(tool_call_id="x", content="ok", is_error=False)]
        assert CantripAgent._all_tool_calls_failed(only_ok) is False

        all_fail = [
            ToolResult(tool_call_id="x", content="bad", is_error=True),
            ToolResult(tool_call_id="y", content="bad", is_error=True),
        ]
        assert CantripAgent._all_tool_calls_failed(all_fail) is True

        mixed = [
            ToolResult(tool_call_id="x", content="bad", is_error=True),
            ToolResult(tool_call_id="y", content="ok", is_error=False),
        ]
        assert CantripAgent._all_tool_calls_failed(mixed) is False


# ---------------------------------------------------------------------------
# Two-pass turn execution
# ---------------------------------------------------------------------------


class TestArchitectEditorTurn:
    @pytest.mark.asyncio
    async def test_dual_pass_runs_both_and_records_usage(self):
        architect = _named(
            "opus",
            responses=[
                Response(
                    content="Edit `src/charm.py` to add error handling.",
                    usage={"prompt_tokens": 100, "completion_tokens": 30},
                )
            ],
        )
        editor = _named(
            "haiku",
            responses=[
                Response(
                    content="Done.",
                    tool_calls=[ToolCall(id="c1", name="write_file", arguments={"path": "x"})],
                    usage={"prompt_tokens": 80, "completion_tokens": 10},
                )
            ],
        )
        agent = CantripAgent(provider=architect, light_provider=editor)
        agent.state.architect_mode = True

        msgs = [Message(role=Role.USER, content="add error handling")]
        response = await agent._run_architect_editor_turn(msgs, llm_tools=None)

        # Editor's response surfaces with its tool call.
        assert response.content == "Done."
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "write_file"

        # Both passes ticked their providers (FakeProvider's
        # ``_call_count`` is the simplest invariant).
        assert architect._call_count == 1
        assert editor._call_count == 1

    @pytest.mark.asyncio
    async def test_dual_pass_records_separate_transcript_events(self, tmp_path):
        from cantrip.agent.store import SessionStore

        architect = _named(
            "opus",
            responses=[
                Response(content="Plan", usage={"prompt_tokens": 1, "completion_tokens": 1})
            ],
        )
        editor = _named(
            "haiku",
            responses=[
                Response(content="Edit", usage={"prompt_tokens": 1, "completion_tokens": 1})
            ],
        )
        agent = CantripAgent(
            provider=architect,
            charm_path=tmp_path,
            light_provider=editor,
        )
        agent.state.architect_mode = True

        msgs = [Message(role=Role.USER, content="hi")]
        await agent._run_architect_editor_turn(msgs, llm_tools=None)

        # The store records both passes as named events.
        store = agent._store
        assert isinstance(store, SessionStore)
        event_types = [row["event_type"] for row in store.load_events()]
        assert "architect_pass" in event_types
        assert "editor_pass" in event_types

    @pytest.mark.asyncio
    async def test_dual_pass_attributes_usage_per_provider(self, tmp_path):
        architect = _named(
            "opus",
            responses=[
                Response(
                    content="plan",
                    usage={"prompt_tokens": 100, "completion_tokens": 20},
                )
            ],
        )
        editor = _named(
            "haiku",
            responses=[
                Response(
                    content="edit",
                    usage={"prompt_tokens": 50, "completion_tokens": 10},
                )
            ],
        )
        agent = CantripAgent(
            provider=architect,
            charm_path=tmp_path,
            light_provider=editor,
        )
        agent.state.architect_mode = True

        msgs = [Message(role=Role.USER, content="hi")]
        await agent._run_architect_editor_turn(msgs, llm_tools=None)

        rows = list(agent._store.get_usage_by_model())
        # Two rows — one per model — with the right token counts.
        attrib = {row["model"]: row for row in rows}
        assert "opus" in attrib
        assert "haiku" in attrib
        assert attrib["opus"]["prompt_tokens"] == 100
        assert attrib["haiku"]["prompt_tokens"] == 50


# ---------------------------------------------------------------------------
# CLI flag wiring
# ---------------------------------------------------------------------------


class TestArchitectCLIFlag:
    def test_main_argparse_accepts_architect(self, monkeypatch: pytest.MonkeyPatch):
        # ``parse_args`` reads ``sys.argv`` directly; substitute via
        # monkeypatch so we can assert on the parsed namespace.
        import sys

        monkeypatch.setattr(sys, "argv", ["cantrip", "run", "--architect", "."])
        from cantrip.main import parse_args

        ns = parse_args()
        assert ns.architect is True
        assert ns.editor_provider is None

    def test_main_argparse_accepts_editor_overrides(self, monkeypatch: pytest.MonkeyPatch):
        import sys

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cantrip",
                "run",
                "--architect",
                "--editor-provider",
                "claude",
                "--editor-model",
                "claude-haiku-4-5-20251001",
                ".",
            ],
        )
        from cantrip.main import parse_args

        ns = parse_args()
        assert ns.architect is True
        assert ns.editor_provider == "claude"
        assert ns.editor_model == "claude-haiku-4-5-20251001"
