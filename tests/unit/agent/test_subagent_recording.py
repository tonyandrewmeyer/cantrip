"""Tests for subagent conversation recording."""

import pathlib
from unittest import mock

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.store import SessionStore
from cantrip.agent.subagent import Subagent, SubagentContext
from cantrip.llm import base as llm


def _make_context(task_id: str = "test-task") -> SubagentContext:
    return SubagentContext(
        task=AgentTask(
            id=task_id,
            title="Test task",
            category=TaskCategory.RESEARCH,
            description="Do research",
        ),
        charm_name="test-charm",
    )


class TestSubagentRecording:
    @pytest.fixture
    def store(self, tmp_path: pathlib.Path):
        s = SessionStore(tmp_path / ".cantrip")
        s.open()
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_messages_recorded_to_store(self, store):
        """Verify that subagent messages are written to the store."""
        context = _make_context()
        provider = mock.AsyncMock(spec=llm.LLMProvider)
        # Return a simple text response (no tool calls).
        provider.complete.return_value = llm.Response(
            content="Research complete.",
            tool_calls=[],
        )
        provider.name = "test"
        provider.model_name = "test-model"
        provider.context_window_tokens = 8000

        subagent = Subagent(
            context=context,
            tools=[],
            provider=provider,
            store=store,
        )
        result = await subagent.run()
        assert result.text == "Research complete."

        msgs = store.load_subagent_messages("test-task")
        # Should have: system, user, final assistant
        assert len(msgs) == 3
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[2]["role"] == "assistant"
        assert msgs[2]["content"] == "Research complete."

    @pytest.mark.asyncio
    async def test_no_recording_without_store(self):
        """Subagent works fine without a store (no crash)."""
        context = _make_context()
        provider = mock.AsyncMock(spec=llm.LLMProvider)
        provider.complete.return_value = llm.Response(
            content="Done.",
            tool_calls=[],
        )
        provider.name = "test"
        provider.model_name = "test-model"
        provider.context_window_tokens = 8000

        subagent = Subagent(
            context=context,
            tools=[],
            provider=provider,
            # No store parameter
        )
        result = await subagent.run()
        assert result.text == "Done."
