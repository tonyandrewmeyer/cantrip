"""Integration tests: slash-command dispatch through a real agent.

The unit suite under ``tests/unit/agent/commands/`` covers argument
parsing and per-handler branch logic against ``SimpleNamespace`` agent
doubles.  This file exercises the dispatcher seam end-to-end —
``slash_commands.dispatch(agent, "/<cmd>")`` against a *real*
:class:`CantripAgent` — so a wiring regression between the parser, the
command module, and the agent's live state / store / work-queue is
caught at the level the unit tests deliberately stub out.

Covers the three shapes the roadmap calls out: a state-mutating command
(``/budget``), a pure read command (``/cost``), and an error path
(an unknown verb).
"""

from __future__ import annotations

import pathlib

import pytest

from cantrip.agent.commands import slash as slash_commands
from cantrip.agent.commands.slash import SlashResult
from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm.base import Message, Response
from tests.support.providers import CallbackProvider


def _silent_provider() -> CallbackProvider:
    """A provider that replies with empty content — these tests never
    drive a real conversation turn, they only need a constructible agent."""
    return CallbackProvider(lambda _messages, _tools: Response(content=""))


@pytest.mark.integration
class TestSlashDispatchEndToEnd:
    def test_unknown_verb_returns_none(self, tmp_path: pathlib.Path) -> None:
        """An unrecognised verb falls through dispatch as plain chat input."""
        agent = CantripAgent(provider=_silent_provider(), charm_path=tmp_path)
        assert slash_commands.dispatch(agent, "/notacommand foo") is None
        # A non-slash message is likewise not a command.
        assert slash_commands.dispatch(agent, "build me a charm") is None

    @pytest.mark.asyncio
    async def test_cost_reads_live_usage(self, tmp_path: pathlib.Path) -> None:
        """``/cost`` rolls up usage the agent actually recorded this session."""

        def _respond(_messages: list[Message], _tools: object) -> Response:
            return Response(
                content="done",
                usage={"prompt_tokens": 1234, "completion_tokens": 567},
            )

        agent = CantripAgent(provider=CallbackProvider(_respond), charm_path=tmp_path)
        await agent.process_message("hello")

        result = slash_commands.dispatch(agent, "/cost")
        assert isinstance(result, SlashResult)
        assert result.markdown is True
        # The recorded prompt / completion / total land in the rollup.
        assert "1,234" in result.text
        assert "567" in result.text
        assert "1,801" in result.text

    def test_budget_mutates_state_and_unblocks_tasks(self, tmp_path: pathlib.Path) -> None:
        """``/budget --max-iterations`` raises the cap and frees blocked work."""
        agent = CantripAgent(provider=_silent_provider(), charm_path=tmp_path)

        # A task blocked specifically by the goal budget should be freed
        # when the cap is raised; one blocked for any other reason stays put.
        budget_task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        other_task = AgentTask(id="t2", title="Wait", category=TaskCategory.BUILD)
        agent.work_queue.add_task(budget_task)
        agent.work_queue.add_task(other_task)
        agent.work_queue.set_blocked("t1", "Goal budget exceeded: 1 iterations (cap: 1).")
        agent.work_queue.set_blocked("t2", "Waiting for user confirmation")

        result = slash_commands.dispatch(agent, "/budget --max-iterations 50")

        assert isinstance(result, SlashResult)
        assert agent.state.goal_budget is not None
        assert agent.state.goal_budget.max_iterations == 50
        assert agent.work_queue.get_task("t1").status is TaskStatus.PENDING
        assert agent.work_queue.get_task("t2").status is TaskStatus.BLOCKED

    def test_budget_show_reports_no_cap_by_default(self, tmp_path: pathlib.Path) -> None:
        """A fresh agent reports no goal budget until one is set."""
        agent = CantripAgent(provider=_silent_provider(), charm_path=tmp_path)
        result = slash_commands.dispatch(agent, "/budget")
        assert isinstance(result, SlashResult)
        assert "No goal budget" in result.text
