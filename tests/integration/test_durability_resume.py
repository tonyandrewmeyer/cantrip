"""Integration tests: durability, resume, and long-running-session recovery.

Phase 93.3.  Cantrip's unit suite covers the session store, work queue,
context manager, and subagent checkpointing in isolation; these tests
exercise the *whole* checkpoint → stop → restart → resume path:

- A partially-run subagent task is force-stopped mid-LLM-call; a fresh
  executor at the same ``.cantrip`` replays the persisted checkpoints
  and finishes the task without re-running the cached LLM turns or tool
  calls (``TestCheckpointStopRestartResume``).
- ``CantripAgent.load_state()`` restores decisions, conversation
  history, and the work queue together — including resetting a task
  that was ACTIVE when the previous session ended and keeping a pending
  follow-up's dependency intact (``TestSessionResumeWithActiveWork``).
- The context-budget lifecycle survives a restart: compaction fires,
  a summariser failure falls back to emergency truncation, and an
  already-exhausted compaction budget carries through resume without
  wedging the conversation loop (``TestContextBudgetLifecycle``).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from cantrip.agent.core import CantripAgent
from cantrip.agent.durability import CheckpointStore
from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider
from tests.support.wait import wait_for_queue_state, wait_until

if TYPE_CHECKING:
    import pathlib

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _CountingTool(Tool):
    """A stub tool that records every :meth:`execute` call.

    Lets a test prove the resumed subagent served a cached tool result
    rather than re-running the tool — ``calls`` stays empty on replay.
    """

    def __init__(self, name: str, *, output: str = "ok", success: bool = True) -> None:
        self._name = name
        self._output = output
        self._success = success
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Counting stub tool {self._name}"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(success=self._success, output=self._output, caption=f"{self._name} ran")


class _HangAfterProvider(FakeProvider):
    """Returns the canned responses, then hangs forever on the next call.

    Models a process that died mid-LLM-call: every turn before the hang
    was durably checkpointed by the subagent, the in-flight one never
    was.  The hung coroutine is unblocked by ``force_stop()`` cancelling
    the subagent task.
    """

    async def complete(
        self,
        messages: list[Any],
        tools: list[Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict | None = None,
    ) -> Response:
        self.last_response_schema = response_schema
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            await asyncio.sleep(0)
            return resp
        await asyncio.Event().wait()  # pragma: no cover — cancelled by force_stop
        raise AssertionError("unreachable")  # pragma: no cover


class _SummaryFailingProvider(FakeProvider):
    """:class:`FakeProvider` whose context-compaction summary call raises.

    The conversation loop calls ``provider.complete(..., temperature=0.3)``
    only when summarising history for compaction (every other call uses a
    higher temperature), so keying the failure on that value targets the
    summariser without touching ordinary turns.
    """

    async def complete(
        self,
        messages: list[Any],
        tools: list[Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict | None = None,
    ) -> Response:
        if temperature == 0.3:
            raise RuntimeError("summariser unavailable")
        return await super().complete(
            messages, tools, temperature, max_tokens, thinking_budget, response_schema
        )


# ---------------------------------------------------------------------------
# Bullet 1 + 2 — checkpoint → stop → restart → resume; executor/store boundary
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCheckpointStopRestartResume:
    """A force-stopped task resumes from its persisted step checkpoints."""

    @pytest.mark.asyncio
    async def test_partial_task_resumes_without_replaying_cached_steps(
        self,
        tmp_path: pathlib.Path,
        fast_executor,
    ) -> None:
        db = tmp_path / ".cantrip"

        # --- Session 1: run the task far enough to checkpoint turn 1 + the
        # tool call, then hang inside the second LLM call and force-stop. ---
        store1 = SessionStore(db)
        queue1 = WorkQueue()
        queue1.add_task(
            AgentTask(
                id="resumable",
                title="Resume me",
                category=TaskCategory.RESEARCH,
                description="A task that gets interrupted partway through.",
            )
        )
        read_tool_1 = _CountingTool("read_file", output="file contents")
        provider1 = _HangAfterProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "f.py"})],
                ),
                # The third complete() call (the post-tool turn) hangs.
            ]
        )
        executor1 = BackgroundExecutor(
            queue=queue1,
            tools=[read_tool_1],
            provider=provider1,
            state=AgentState(charm_name="probe"),
            store=store1,
        )
        executor1.start()
        checkpoints1 = CheckpointStore(store1)
        # llm_turn#1 (returns the tool call) + tool:read_file#1.
        await wait_until(lambda: checkpoints1.count_for_task("resumable") >= 2)
        await executor1.force_stop()
        store1.close()

        assert read_tool_1.calls == [{"path": "f.py"}]  # ran live in session 1

        # --- Session 2: fresh executor, queue, provider, and store handle
        # at the same path.  The interrupted task is PENDING again. ---
        store2 = SessionStore(db)
        loaded = store2.load_tasks()
        assert [t.id for t in loaded] == ["resumable"]
        assert loaded[0].status == TaskStatus.PENDING

        queue2 = WorkQueue()
        queue2.add_tasks(loaded)
        read_tool_2 = _CountingTool("read_file", output="MUST NOT RUN ON REPLAY")
        provider2 = FakeProvider(responses=[Response(content="Wrapped up the file work.")])
        purged: list[str] = []

        def _on_done(task: AgentTask) -> None:
            CheckpointStore(store2).on_task_done(task.id)
            purged.append(task.id)

        executor2 = BackgroundExecutor(
            queue=queue2,
            tools=[read_tool_2],
            provider=provider2,
            state=AgentState(charm_name="probe"),
            store=store2,
            on_task_done=_on_done,
        )
        executor2.start()
        try:
            await wait_for_queue_state(queue2, done_count=1)
        finally:
            await executor2.stop()

        # Only the final LLM turn ran live; turn 1 and the tool call were
        # served from the checkpoints, so the counting tool never fired.
        assert provider2._call_count == 1
        assert read_tool_2.calls == []
        done = queue2.get_task("resumable")
        assert done is not None and done.status == TaskStatus.DONE
        assert done.result == "Wrapped up the file work."

        # Checkpoints are purged once the task reaches DONE (via the real
        # on_task_done wiring), so a future run starts clean.
        assert purged == ["resumable"]
        assert CheckpointStore(store2).count_for_task("resumable") == 0
        store2.close()

    @pytest.mark.asyncio
    async def test_completed_task_is_not_re_run_after_restart(
        self,
        tmp_path: pathlib.Path,
        fast_executor,
    ) -> None:
        """A task that finished before the restart stays DONE and isn't re-dispatched."""
        db = tmp_path / ".cantrip"

        store1 = SessionStore(db)
        queue1 = WorkQueue()
        queue1.add_task(
            AgentTask(
                id="already-done", title="Done before restart", category=TaskCategory.RESEARCH
            )
        )
        executor1 = BackgroundExecutor(
            queue=queue1,
            tools=[],
            provider=FakeProvider(responses=[Response(content="Original result.")]),
            state=AgentState(),
            store=store1,
        )
        executor1.start()
        try:
            await wait_for_queue_state(queue1, done_count=1)
        finally:
            await executor1.stop()
        store1.close()

        # Restart: a provider that would explode if a subagent ran again.
        class _ExplodingProvider(FakeProvider):
            async def complete(self, *args: Any, **kwargs: Any) -> Response:
                raise AssertionError("a DONE task must not be re-executed on resume")

        store2 = SessionStore(db)
        queue2 = WorkQueue()
        queue2.add_tasks(store2.load_tasks())
        executor2 = BackgroundExecutor(
            queue=queue2,
            tools=[],
            provider=_ExplodingProvider(),
            state=AgentState(),
            store=store2,
        )
        executor2.start()
        # Give the poll loop a few iterations to (not) pick the task up.
        await asyncio.sleep(0.1)
        await executor2.stop()

        task = queue2.get_task("already-done")
        assert task is not None and task.status == TaskStatus.DONE
        assert task.result == "Original result."
        store2.close()


# ---------------------------------------------------------------------------
# Bullet 1 + 4 — session-wide resume (decisions + transcript + queue together)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSessionResumeWithActiveWork:
    """``CantripAgent.load_state()`` restores the whole session at once."""

    @pytest.mark.asyncio
    async def test_active_task_and_pending_followup_survive_resume(
        self, tmp_path: pathlib.Path
    ) -> None:
        agent = CantripAgent(
            provider=FakeProvider(responses=[Response(content="Acknowledged.")]),
            charm_path=tmp_path,
        )
        agent.state.charm_name = "redis"
        agent.state.charm_type = "k8s"
        agent.state.add_decision("path", "12-factor", reason="Flask detected")
        await agent.process_message("Start the build please.")

        # A completed research task, a task that's mid-flight, and a
        # follow-up blocked on the mid-flight one.
        agent.work_queue.add_task(
            AgentTask(id="research-1", title="Research redis", category=TaskCategory.RESEARCH)
        )
        agent.work_queue.set_done("research-1", "Found upstream docs.")
        agent.work_queue.add_task(
            AgentTask(id="build-1", title="Write the charm", category=TaskCategory.BUILD)
        )
        agent.work_queue.set_active("build-1")
        agent.work_queue.add_task(
            AgentTask(
                id="test-1",
                title="Write Scenario tests",
                category=TaskCategory.TEST,
                dependencies=["build-1"],
            )
        )
        agent.save_state()

        # --- Restart at the same path. ---
        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert agent2.load_state() is True

        # Charm metadata + decisions.
        assert agent2.state.charm_name == "redis"
        assert agent2.state.charm_type == "k8s"
        assert [(d.type, d.choice) for d in agent2.state.decisions] == [("path", "12-factor")]

        # Conversation history (active branch).
        contents = [m.content for m in agent2.state.messages]
        assert "Start the build please." in contents
        assert "Acknowledged." in contents

        # Work queue: DONE survives with its result; ACTIVE was reset to
        # PENDING; the follow-up is still PENDING with its dependency.
        done = agent2.work_queue.get_task("research-1")
        assert done is not None and done.status == TaskStatus.DONE
        assert done.result == "Found upstream docs."

        revived = agent2.work_queue.get_task("build-1")
        assert revived is not None and revived.status == TaskStatus.PENDING

        followup = agent2.work_queue.get_task("test-1")
        assert followup is not None and followup.status == TaskStatus.PENDING
        assert followup.dependencies == ["build-1"]

    @pytest.mark.asyncio
    async def test_interrupted_task_finishes_after_resume_via_executor(
        self,
        tmp_path: pathlib.Path,
        fast_executor,
    ) -> None:
        """Queue a task, save, restart, run the executor — it picks the task up and finishes it."""
        agent = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agent.work_queue.add_task(
            AgentTask(id="pending-work", title="Finish me later", category=TaskCategory.RESEARCH)
        )
        agent.work_queue.set_active("pending-work")  # mid-flight when the session ended
        agent.save_state()

        agent2 = CantripAgent(
            provider=FakeProvider(responses=[Response(content="Done after resume.")]),
            charm_path=tmp_path,
        )
        assert agent2.load_state() is True
        assert agent2.work_queue.get_task("pending-work").status == TaskStatus.PENDING

        agent2.start_executor()
        try:
            await wait_for_queue_state(agent2.work_queue, done_count=1)
        finally:
            await agent2.stop_executor()

        finished = agent2.work_queue.get_task("pending-work")
        assert finished is not None and finished.status == TaskStatus.DONE
        assert finished.result == "Done after resume."


# ---------------------------------------------------------------------------
# Bullet 3 — context-budget lifecycle end to end
# ---------------------------------------------------------------------------


_BIG_FILE = "big.txt"


def _write_big_file(charm_path: pathlib.Path, *, lines: int = 280) -> None:
    """Write a file fat enough that two ``read_file`` results blow a 400-token window.

    Stays under the 10 000-char virtualisation threshold so the content
    lands in the conversation history verbatim rather than as a pointer —
    that's what pushes ``should_compact`` over the line.
    """
    body = "\n".join(f"data row {i:04d} payload value here" for i in range(lines))
    (charm_path / _BIG_FILE).write_text(body)


def _read_big_file_call(call_id: str) -> ToolCall:
    return ToolCall(id=call_id, name="read_file", arguments={"path": _BIG_FILE})


@pytest.mark.integration
class TestContextBudgetLifecycle:
    """Compaction trigger, summariser failure, and exhausted-budget resume.

    Compaction in the conversation loop only runs between tool-call
    rounds, so these tests drive two ``read_file`` rounds against a fat
    file under a tiny context window — the second round's post-tool
    history clears the threshold and triggers compaction.
    """

    @pytest.mark.asyncio
    async def test_compaction_fires_and_counter_survives_resume(
        self, tmp_path: pathlib.Path
    ) -> None:
        _write_big_file(tmp_path)
        provider = FakeProvider(
            responses=[
                Response(content="", tool_calls=[_read_big_file_call("c1")]),
                Response(content="", tool_calls=[_read_big_file_call("c2")]),
                Response(content="Summary of the conversation so far."),
                Response(content="All caught up."),
            ],
            context_window_tokens=400,
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        reply = await agent.process_message("read that file twice")

        assert isinstance(reply, str) and reply
        attempted = agent._context_manager.compactions_attempted
        assert attempted >= 1

        # The counter is persisted as compaction runs; a fresh agent at the
        # same path picks it up rather than handing the resumed session a
        # brand-new compaction budget.
        agent2 = CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert agent2.load_state() is True
        assert agent2._context_manager.compactions_attempted == attempted

    @pytest.mark.asyncio
    async def test_summariser_failure_falls_back_to_emergency_truncate(
        self, tmp_path: pathlib.Path
    ) -> None:
        _write_big_file(tmp_path)
        provider = _SummaryFailingProvider(
            responses=[
                Response(content="", tool_calls=[_read_big_file_call("c1")]),
                Response(content="", tool_calls=[_read_big_file_call("c2")]),
                # No canned summary response — the temp=0.3 summary call raises
                # before it would be consumed; the next reply ends the turn.
                Response(content="Recovered and carried on."),
            ],
            context_window_tokens=400,
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        reply = await agent.process_message("read that file twice")  # summary call raises

        # The summariser blew up but the conversation loop kept going via the
        # emergency-truncation fallback.
        assert isinstance(reply, str) and reply
        assert agent._context_manager.compactions_attempted >= 1
        assert agent._context_manager.emergencies_attempted >= 1

    @pytest.mark.asyncio
    async def test_exhausted_compaction_budget_survives_resume_and_session_continues(
        self, tmp_path: pathlib.Path
    ) -> None:
        agent = CantripAgent(
            provider=FakeProvider(responses=[Response(content="hello")]),
            charm_path=tmp_path,
        )
        await agent.process_message("hi")  # materialises the .cantrip store

        # Stand in for a prior session that already spent its compaction
        # budget (and a couple of emergency truncations on top).
        agent._store.save_compaction_counters(  # type: ignore[union-attr]
            8, 2, cycle_detected=False, budget_exhausted=True
        )

        agent2 = CantripAgent(
            provider=FakeProvider(responses=[Response(content="still serving turns")]),
            charm_path=tmp_path,
        )
        assert agent2.load_state() is True
        cm = agent2._context_manager
        assert cm.compactions_attempted == 8
        assert cm.emergencies_attempted == 2
        assert cm.budget_exhausted is True

        # An exhausted-budget session must keep answering rather than wedging,
        # and it must not try to compact again now that the budget is spent.
        reply = await agent2.process_message("are you still there?")
        assert isinstance(reply, str) and reply
        assert agent2._context_manager.compactions_attempted == 8
