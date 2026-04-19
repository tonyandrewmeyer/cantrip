"""Subagent tests: helpers."""

import pytest

from cantrip.agent.queue import ModelHint, TaskCategory
from cantrip.agent.subagent import (
    _PROTECTED_ROUNDS,
    _TRUNCATION_CONTENT_THRESHOLD,
    _TRUNCATION_PREVIEW_LEN,
    ExitState,
    _filter_tools,
    _parse_exit_state,
    _select_provider,
    _tools_for_llm,
    _truncate_messages,
)
from tests.conftest import FakeProvider
from tests.unit.subagent.conftest import _make_tool

# ===================================================================
# TestFilterTools
# ===================================================================


class TestFilterTools:
    """Tests for _filter_tools — category-based tool selection."""

    def test_research_gets_correct_tools(self) -> None:
        tools = [
            _make_tool("web_fetch"),
            _make_tool("write_file"),
            _make_tool("charmhub_search"),
            _make_tool("juju_deploy"),
        ]
        filtered = _filter_tools(tools, TaskCategory.RESEARCH)

        names = {t.name for t in filtered}
        assert "web_fetch" in names
        assert "charmhub_search" in names
        assert "write_file" in names
        assert "juju_deploy" not in names

    def test_build_gets_correct_tools(self) -> None:
        tools = [
            _make_tool("read_file"),
            _make_tool("write_file"),
            _make_tool("juju_deploy"),
        ]
        filtered = _filter_tools(tools, TaskCategory.BUILD)

        names = {t.name for t in filtered}
        assert "read_file" in names
        assert "write_file" in names
        assert "juju_deploy" not in names

    def test_confirm_returns_empty(self) -> None:
        tools = [_make_tool("read_file"), _make_tool("web_fetch")]
        filtered = _filter_tools(tools, TaskCategory.CONFIRM)

        assert filtered == []

    def test_deploy_includes_juju_tools(self) -> None:
        tools = [
            _make_tool("juju_deploy"),
            _make_tool("juju_status"),
            _make_tool("git_commit"),
        ]
        filtered = _filter_tools(tools, TaskCategory.DEPLOY)

        names = {t.name for t in filtered}
        assert "juju_deploy" in names
        assert "juju_status" in names
        assert "git_commit" not in names

    def test_debug_includes_observability(self) -> None:
        tools = [
            _make_tool("juju_debug_log"),
            _make_tool("tempo_query"),
            _make_tool("loki_query"),
            _make_tool("charmcraft_init"),
        ]
        filtered = _filter_tools(tools, TaskCategory.DEBUG)

        names = {t.name for t in filtered}
        assert "juju_debug_log" in names
        assert "tempo_query" in names
        assert "loki_query" in names
        assert "charmcraft_init" not in names

    def test_infra_includes_concierge(self) -> None:
        tools = [
            _make_tool("concierge_prepare"),
            _make_tool("concierge_status"),
            _make_tool("read_file"),
        ]
        filtered = _filter_tools(tools, TaskCategory.INFRA)

        names = {t.name for t in filtered}
        assert "concierge_prepare" in names
        assert "concierge_status" in names
        assert "read_file" not in names

    def test_deploy_includes_fast_path_tools(self) -> None:
        tools = [
            _make_tool("charm_sync"),
            _make_tool("juju_dispatch"),
            _make_tool("juju_deploy"),
            _make_tool("write_file"),
        ]
        filtered = _filter_tools(tools, TaskCategory.DEPLOY)

        names = {t.name for t in filtered}
        assert "charm_sync" in names
        assert "juju_dispatch" in names
        assert "juju_deploy" in names
        assert "write_file" not in names

    def test_empty_tools_returns_empty(self) -> None:
        assert _filter_tools([], TaskCategory.BUILD) == []


# ===================================================================
# TestSelectProvider
# ===================================================================


class TestSelectProvider:
    """Tests for _select_provider — routing to light vs primary."""

    def test_research_uses_light(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.RESEARCH, primary, light)
        assert result is light

    def test_infra_uses_light(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.INFRA, primary, light)
        assert result is light

    def test_build_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.BUILD, primary, light)
        assert result is primary

    def test_deploy_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.DEPLOY, primary, light)
        assert result is primary

    def test_no_light_falls_back_to_primary(self) -> None:
        primary = FakeProvider()
        result = _select_provider(TaskCategory.RESEARCH, primary, None)
        assert result is primary

    def test_test_category_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.TEST, primary, light)
        assert result is primary

    def test_debug_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.DEBUG, primary, light)
        assert result is primary

    def test_model_hint_primary_overrides_category(self) -> None:
        """Explicit PRIMARY hint forces primary even for a light category."""
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH,
            primary,
            light,
            model_hint=ModelHint.PRIMARY,
        )
        assert result is primary

    def test_model_hint_light_overrides_category(self) -> None:
        """Explicit LIGHT hint forces light even for a primary category."""
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.BUILD,
            primary,
            light,
            model_hint=ModelHint.LIGHT,
        )
        assert result is light

    def test_model_hint_light_without_provider_falls_back(self) -> None:
        """LIGHT hint without a light provider falls back to primary."""
        primary = FakeProvider()
        result = _select_provider(
            TaskCategory.BUILD,
            primary,
            None,
            model_hint=ModelHint.LIGHT,
        )
        assert result is primary


# ===================================================================
# TestToolsForLlm
# ===================================================================


class TestToolsForLlm:
    """Tests for _tools_for_llm — conversion to LLM descriptors."""

    def test_empty_returns_none(self) -> None:
        assert _tools_for_llm([]) is None

    def test_converts_tools(self) -> None:
        tools = [_make_tool("read_file"), _make_tool("web_fetch")]
        result = _tools_for_llm(tools)

        assert result is not None
        assert len(result) == 2
        assert result[0].name == "read_file"
        assert result[1].name == "web_fetch"


# ===================================================================
# TestParseExitState
# ===================================================================


class TestParseExitState:
    """Tests for _parse_exit_state — extracting exit states from LLM text."""

    def test_explicit_completed(self) -> None:
        assert _parse_exit_state("Done.\n\n[EXIT: completed]") == ExitState.COMPLETED

    def test_explicit_blocked(self) -> None:
        assert _parse_exit_state("Need creds.\n[EXIT: blocked]") == ExitState.BLOCKED

    def test_explicit_failed(self) -> None:
        assert _parse_exit_state("[EXIT: failed]") == ExitState.FAILED

    def test_explicit_noop(self) -> None:
        assert _parse_exit_state("Already done.\n[EXIT: noop]") == ExitState.NOOP

    def test_case_insensitive(self) -> None:
        assert _parse_exit_state("[EXIT: COMPLETED]") == ExitState.COMPLETED

    def test_without_brackets(self) -> None:
        assert _parse_exit_state("EXIT: blocked") == ExitState.BLOCKED

    def test_exit_state_variant(self) -> None:
        assert _parse_exit_state("[EXIT_STATE: failed]") == ExitState.FAILED

    def test_fallback_to_completed(self) -> None:
        assert _parse_exit_state("All done, charm deployed.") == ExitState.COMPLETED

    def test_heuristic_blocked(self) -> None:
        text = "I'm blocked — I need the database password from the user."
        assert _parse_exit_state(text) == ExitState.BLOCKED

    def test_heuristic_noop(self) -> None:
        text = "Nothing to do — the charm already has all COS relations."
        assert _parse_exit_state(text) == ExitState.NOOP


# ===================================================================
# TestTruncateMessages
# ===================================================================


class TestTruncateMessages:
    """Tests for _truncate_messages — context window management."""

    def _make_messages(
        self,
        *,
        num_rounds: int = 5,
        tool_content_len: int = 2000,
    ) -> list:
        """Build a message list simulating multiple tool-call rounds.

        Each round produces an assistant message (with a tool call) and a
        tool result message with content of *tool_content_len* characters.
        """
        from cantrip.llm import base as llm_mod

        msgs: list[llm_mod.Message] = [
            llm_mod.Message(role=llm_mod.Role.SYSTEM, content="System prompt."),
            llm_mod.Message(role=llm_mod.Role.USER, content="Do something."),
        ]
        for i in range(num_rounds):
            msgs.append(
                llm_mod.Message(
                    role=llm_mod.Role.ASSISTANT,
                    content=f"Round {i}",
                    tool_calls=[
                        llm_mod.ToolCall(id=f"tc-{i}", name="read_file", arguments={}),
                    ],
                )
            )
            msgs.append(
                llm_mod.Message(
                    role=llm_mod.Role.TOOL,
                    content="",
                    tool_results=[
                        llm_mod.ToolResult(
                            tool_call_id=f"tc-{i}",
                            content="x" * tool_content_len,
                        ),
                    ],
                )
            )
        return msgs

    def test_no_truncation_when_under_budget(self) -> None:
        """Messages within the budget are not modified."""
        msgs = self._make_messages(num_rounds=2, tool_content_len=100)
        # Use a large context window so we stay well under 80%.
        _truncate_messages(msgs, context_window_tokens=1_000_000)

        for msg in msgs:
            for tr in msg.tool_results:
                assert tr.content == "x" * 100

    def test_truncation_replaces_old_tool_results(self) -> None:
        """When over budget, older tool results are replaced with a summary."""
        msgs = self._make_messages(num_rounds=6, tool_content_len=5000)
        # Use a small context window to force truncation.
        _truncate_messages(msgs, context_window_tokens=1000)

        # Older rounds (before the protected tail) should be truncated.
        # The first tool result is at index 3 (system, user, assistant, tool).
        early_tool_msg = msgs[3]
        assert early_tool_msg.role.value == "tool"
        tr = early_tool_msg.tool_results[0]
        assert "[Tool result truncated" in tr.content
        assert "5000 chars" in tr.content

    def test_recent_messages_preserved(self) -> None:
        """The most recent _PROTECTED_ROUNDS rounds are never truncated."""
        msgs = self._make_messages(num_rounds=6, tool_content_len=5000)
        _truncate_messages(msgs, context_window_tokens=1000)

        # The last _PROTECTED_ROUNDS * 2 non-system messages should be intact.
        # Each round is 2 messages (assistant + tool), so the tail is
        # the last (_PROTECTED_ROUNDS * 2) messages.
        protected_start = len(msgs) - (_PROTECTED_ROUNDS * 2)
        for msg in msgs[protected_start:]:
            for tr in msg.tool_results:
                # Protected tool results keep their original content.
                assert tr.content == "x" * 5000

    def test_system_message_preserved(self) -> None:
        """The system message (index 0) is never modified."""
        msgs = self._make_messages(num_rounds=6, tool_content_len=5000)
        original_system = msgs[0].content
        _truncate_messages(msgs, context_window_tokens=1000)
        assert msgs[0].content == original_system

    def test_short_content_not_truncated(self) -> None:
        """Tool results shorter than the threshold are left alone."""
        msgs = self._make_messages(
            num_rounds=6,
            tool_content_len=_TRUNCATION_CONTENT_THRESHOLD - 1,
        )
        _truncate_messages(msgs, context_window_tokens=1000)

        for msg in msgs:
            for tr in msg.tool_results:
                # Nothing should have been truncated.
                assert "[Tool result truncated" not in tr.content

    def test_truncation_preview_length(self) -> None:
        """The truncation summary includes the configured preview length."""
        msgs = self._make_messages(num_rounds=4, tool_content_len=3000)
        _truncate_messages(msgs, context_window_tokens=500)

        # Find the first truncated tool result.
        for msg in msgs:
            for tr in msg.tool_results:
                if "[Tool result truncated" in tr.content:
                    assert f"First {_TRUNCATION_PREVIEW_LEN} chars:" in tr.content
                    return
        pytest.fail("No truncated tool results found")
