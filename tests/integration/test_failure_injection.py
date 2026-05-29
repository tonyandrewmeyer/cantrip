"""Integration tests: failure injection across provider, tool, and recovery paths.

Phase 93.2.  The happy-path work loop is well covered elsewhere; these
tests assert that when the model server, a tool, or the environment
misbehaves the agent fails *cleanly* — tasks reach a terminal state,
retries fire and then give up, and the surfaces that report back to a
caller say something specific rather than hanging or dumping a traceback.

The reusable doubles live in ``tests.support`` so each scenario stays a
few lines: :class:`~tests.support.providers.FailingProvider` /
:class:`~tests.support.providers.FlakyProvider` for provider outages,
:func:`~tests.support.tools.make_raising_tool` /
``make_stub_tool(success=False)`` for tool failures, and the
``fast_retry`` fixture to collapse the transient-error backoff.
"""

from __future__ import annotations

import os
import pathlib
import types

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.planner import PlanningContext, TaskPlanner
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.llm.base import (
    ProviderConnectionError,
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    Response,
    ToolCall,
)
from cantrip.llm.structured import StructuredOutputError
from tests.integration.conftest import SAMPLE_DESIGN_MD
from tests.support.providers import CallbackProvider, FailingProvider, FlakyProvider
from tests.support.tools import make_raising_tool, make_stub_tool
from tests.support.wait import wait_for_queue_state, wait_for_task_status

_VALID_BRIEFING = '{"tasks": [{"title": "Scaffold the charm", "category": "build"}]}'


@pytest.mark.integration
class TestProviderFailureInjection:
    """Provider-side failures: 5xx / overload / non-transient / malformed."""

    @pytest.mark.asyncio
    async def test_non_transient_provider_error_fails_task_with_summary(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """A non-transient ``ProviderError`` isn't retried — the task goes FAILED.

        ``set_failed`` stores the error string on the task, so the queue
        carries a crisp one-line cause rather than an empty terminal state.
        """
        provider = FailingProvider(ProviderError("model is down"))
        queue = WorkQueue()
        queue.add_task(AgentTask(id="t", title="Do a thing", category=TaskCategory.RESEARCH))

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        try:
            await wait_for_queue_state(queue, failed_count=1)
        finally:
            await executor.stop()

        task = queue.get_task("t")
        assert task.status == TaskStatus.FAILED
        assert task.result == "model is down"
        # No retry budget burned on a non-transient error.
        assert provider.calls == 1

    @pytest.mark.asyncio
    async def test_overloaded_provider_exhausts_retries_then_fails(
        self,
        fast_executor,  # noqa: ARG002
        fast_retry,  # noqa: ARG002
    ):
        """A persistently-overloaded provider exhausts ``complete_with_retry`` then fails the task.

        Regression guard: ``ProviderOverloadedError`` is *not* a
        ``ProviderError`` subclass, so before the executor's exception
        clause was widened the task coroutine died unhandled and the task
        stayed ``IN_PROGRESS`` — i.e. the work loop hung on it.
        """
        provider = FailingProvider(ProviderOverloadedError("503 overloaded"))
        queue = WorkQueue()
        queue.add_task(AgentTask(id="t", title="Build the charm", category=TaskCategory.BUILD))

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        try:
            await wait_for_queue_state(queue, failed_count=1)
        finally:
            await executor.stop()

        task = queue.get_task("t")
        assert task.status == TaskStatus.FAILED
        assert "overloaded" in (task.result or "")
        # The default transient-retry budget (3 attempts) was actually used.
        assert provider.calls >= 3

    @pytest.mark.asyncio
    async def test_connection_drop_exhausts_retries_then_fails(
        self,
        fast_executor,  # noqa: ARG002
        fast_retry,  # noqa: ARG002
    ):
        """A persistent mid-stream disconnect is retried as transient, then fails the task."""
        provider = FailingProvider(ProviderConnectionError("peer hung up"))
        queue = WorkQueue()
        queue.add_task(
            AgentTask(id="t", title="Research the workload", category=TaskCategory.RESEARCH)
        )

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        try:
            await wait_for_queue_state(queue, failed_count=1)
        finally:
            await executor.stop()

        assert queue.get_task("t").status == TaskStatus.FAILED
        assert provider.calls >= 3

    @pytest.mark.asyncio
    async def test_provider_failure_does_not_block_independent_task(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """One task hits a provider error; an independent task still completes."""

        def respond(messages, _tools):
            for msg in messages:
                if msg.role.value == "system" and "Break me" in msg.content:
                    raise ProviderError("provider exploded")
            return Response(content="Other task done.")

        provider = CallbackProvider(respond)
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id="bad", title="Break me", category=TaskCategory.RESEARCH),
                AgentTask(id="ok", title="Carry on", category=TaskCategory.RESEARCH),
            ]
        )

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        try:
            await wait_for_queue_state(queue, done_count=1, failed_count=1)
        finally:
            await executor.stop()

        assert queue.get_task("bad").status == TaskStatus.FAILED
        assert queue.get_task("ok").status == TaskStatus.DONE
        assert queue.get_task("ok").result == "Other task done."

    @pytest.mark.asyncio
    async def test_planner_recovers_from_malformed_then_valid_response(self):
        """A first un-parseable planner reply is corrected on the structured retry."""
        calls = {"n": 0}

        def respond(_messages, _tools):
            calls["n"] += 1
            if calls["n"] == 1:
                return Response(content="Sorry, I can't produce JSON right now.")
            return Response(content=_VALID_BRIEFING)

        planner = TaskPlanner(CallbackProvider(respond))
        tasks = await planner.plan_from_design(
            SAMPLE_DESIGN_MD, PlanningContext(intent="charm it")
        )

        assert calls["n"] == 2  # one corrective retry was issued
        assert [t.title for t in tasks] == ["Scaffold the charm"]
        assert tasks[0].category == TaskCategory.BUILD

    @pytest.mark.asyncio
    async def test_planner_raises_when_structured_output_never_valid(self):
        """When every planner reply fails validation the error surfaces, not silence."""
        calls = {"n": 0}

        def respond(_messages, _tools):
            calls["n"] += 1
            return Response(content="absolutely not JSON")

        planner = TaskPlanner(CallbackProvider(respond))
        with pytest.raises(StructuredOutputError):
            await planner.plan_from_design(SAMPLE_DESIGN_MD, PlanningContext(intent="charm it"))
        # Initial attempt plus the corrective retry both ran.
        assert calls["n"] == 2


@pytest.mark.integration
class TestToolExecutionFailures:
    """Tool-side failures: non-zero exit, timeout, missing binary, raises, error result."""

    @staticmethod
    def _run_command_tool(base_path: pathlib.Path, allowlist: frozenset[str] | None = None):
        from cantrip.agent.safety.sandbox import SandboxedRunner
        from cantrip.agent.tools.run_command import RunCommandTool

        # Force the no-op sandbox so the test is deterministic regardless of
        # whether ``bwrap`` / ``unshare`` are usable in the CI container.
        return RunCommandTool(
            base_path=base_path,
            allowlist=allowlist,
            sandbox_runner=SandboxedRunner(mechanism="none"),
        )

    @pytest.mark.asyncio
    async def test_run_command_nonzero_exit_returns_clean_error(self, tmp_path: pathlib.Path):
        tool = self._run_command_tool(tmp_path)
        result = await tool.execute(command='python3 -c "raise SystemExit(7)"', cwd=str(tmp_path))
        assert not result.success
        assert "exited with code 7" in (result.error or "")

    @pytest.mark.asyncio
    async def test_run_command_timeout_returns_clean_error(self, tmp_path: pathlib.Path):
        tool = self._run_command_tool(tmp_path)
        result = await tool.execute(
            command="python3 -c \"__import__('time').sleep(30)\"",
            cwd=str(tmp_path),
            timeout=1,
        )
        assert not result.success
        assert "timed out" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_run_command_missing_binary_returns_clean_error(self, tmp_path: pathlib.Path):
        tool = self._run_command_tool(tmp_path, allowlist=frozenset({"cantrip-no-such-binary"}))
        result = await tool.execute(command="cantrip-no-such-binary --help", cwd=str(tmp_path))
        assert not result.success
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_run_command_rejects_command_off_allowlist(self, tmp_path: pathlib.Path):
        tool = self._run_command_tool(tmp_path, allowlist=frozenset({"make"}))
        result = await tool.execute(command="rm -rf /", cwd=str(tmp_path))
        assert not result.success
        assert "allowlist" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_failing_tool_does_not_crash_subagent_loop(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """A tool that raises mid-execute becomes an error result; the subagent recovers.

        ``execute_tool`` catches the exception and hands the model an
        ``is_error`` result, so the subagent gets a second turn and the
        task still reaches ``DONE`` — the failing tool does not take the
        loop down with it.
        """
        invoked: list[tuple[str, bool]] = []
        provider = CallbackProvider(
            lambda messages, _tools: (
                Response(content="Read failed; reported it and carried on.")
                if any(tr.is_error for m in messages for tr in m.tool_results)
                else Response(
                    content="",
                    tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "x.py"})],
                )
            )
        )
        queue = WorkQueue()
        queue.add_task(AgentTask(id="t", title="Inspect the repo", category=TaskCategory.RESEARCH))

        executor = BackgroundExecutor(
            queue=queue,
            tools=[make_raising_tool("read_file")],
            provider=provider,
            state=AgentState(),
            on_tool_invoked=lambda name, _a, result, _ms, _id: invoked.append(
                (name, result.success)
            ),
        )
        executor.start()
        try:
            await wait_for_task_status(queue.get_task("t"), TaskStatus.DONE)
        finally:
            await executor.stop()

        assert ("read_file", False) in invoked
        assert queue.get_task("t").result == "Read failed; reported it and carried on."

    @pytest.mark.asyncio
    async def test_tool_returning_failure_result_does_not_crash_subagent_loop(
        self,
        fast_executor,  # noqa: ARG002
    ):
        """A tool that *returns* ``success=False`` is surfaced and the task still completes."""
        provider = CallbackProvider(
            lambda messages, _tools: (
                Response(content="Tool said no; moving on.")
                if any(tr.is_error for m in messages for tr in m.tool_results)
                else Response(
                    content="", tool_calls=[ToolCall(id="tc1", name="write_file", arguments={})]
                )
            )
        )
        queue = WorkQueue()
        queue.add_task(AgentTask(id="t", title="Write a file", category=TaskCategory.RESEARCH))

        executor = BackgroundExecutor(
            queue=queue,
            tools=[make_stub_tool("write_file", output="permission denied", success=False)],
            provider=provider,
            state=AgentState(),
        )
        executor.start()
        try:
            await wait_for_task_status(queue.get_task("t"), TaskStatus.DONE)
        finally:
            await executor.stop()

        assert queue.get_task("t").result == "Tool said no; moving on."


@pytest.mark.integration
class TestWorkLoopRecovery:
    """Retry / recovery under pressure: terminate cleanly, recover when transient."""

    @pytest.mark.asyncio
    async def test_persistent_provider_failure_terminates_and_persists(
        self,
        tmp_path: pathlib.Path,
        fast_executor,  # noqa: ARG002
    ):
        """Every subagent call fails — all tasks reach FAILED and the loop stops spinning.

        The store-backed run also proves "partial state already written
        when the failure hits": the FAILED status + cause land in the
        ``.cantrip`` file even though no task produced a result.
        """
        provider = FailingProvider(ProviderError("upstream unavailable"))
        queue = WorkQueue()
        queue.add_tasks(
            [
                AgentTask(id=f"t{i}", title=f"Task {i}", category=TaskCategory.RESEARCH)
                for i in range(3)
            ]
        )
        store = SessionStore(tmp_path / ".cantrip")

        executor = BackgroundExecutor(
            queue=queue, tools=[], provider=provider, state=AgentState(), store=store
        )
        executor.start()
        try:
            await wait_for_queue_state(queue, failed_count=3)
        finally:
            await executor.stop()

        assert all(t.status == TaskStatus.FAILED for t in queue.all_tasks())
        loaded = {t.id: t for t in store.load_tasks()}
        assert len(loaded) == 3
        assert all(t.status == TaskStatus.FAILED for t in loaded.values())
        assert all(t.result == "upstream unavailable" for t in loaded.values())

    @pytest.mark.asyncio
    async def test_transient_provider_failure_recovers_and_completes(
        self,
        fast_executor,  # noqa: ARG002
        fast_retry,  # noqa: ARG002
    ):
        """Two rate-limit blips then success — ``complete_with_retry`` recovers the task."""
        provider = FlakyProvider(
            failures=2,
            exc=ProviderRateLimitError("slow down"),
            response=Response(content="Recovered and finished."),
        )
        queue = WorkQueue()
        queue.add_task(AgentTask(id="t", title="Survive the blip", category=TaskCategory.RESEARCH))

        executor = BackgroundExecutor(queue=queue, tools=[], provider=provider, state=AgentState())
        executor.start()
        try:
            await wait_for_task_status(queue.get_task("t"), TaskStatus.DONE)
        finally:
            await executor.stop()

        assert queue.get_task("t").result == "Recovered and finished."
        # Two failures + the successful third call.
        assert provider.calls == 3


@pytest.mark.integration
class TestDegradedEnvironment:
    """Realistic operator-machine degradations: missing key, no controller, unwritable export."""

    def test_missing_api_key_surfaces_cleanly(self, monkeypatch: pytest.MonkeyPatch):
        """Creating a provider with no key raises a caller-handled error, not an opaque crash."""
        from cantrip.llm import create_provider

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises((ValueError, ProviderError)):
            create_provider("claude", "claude-sonnet-4-6")

    @pytest.mark.asyncio
    async def test_preflight_without_juju_reports_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """With no ``juju`` (and no concierge) on PATH, preflight reports it rather than throwing."""
        from cantrip.agent import preflight

        monkeypatch.setattr(preflight, "_concierge_available", lambda: False)
        monkeypatch.setattr(preflight.shutil, "which", lambda _name: None)

        runner = preflight.PreflightRunner(AgentState())
        result = await runner.warm_up()

        assert result.juju_available is False
        assert result.concierge_available is False

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses filesystem permission checks",
    )
    def test_transcript_export_write_failure_surfaces_cleanly(self, tmp_path: pathlib.Path):
        """A read-only destination produces a clean message and leaves the session file intact."""
        from cantrip.agent.commands.transcript import export_transcript

        charm_path = tmp_path / "charm"
        charm_path.mkdir()
        SessionStore(charm_path / ".cantrip").save_session(AgentState(charm_name="redis"))

        readonly = tmp_path / "readonly"
        readonly.mkdir(mode=0o500)
        try:
            agent = types.SimpleNamespace(state=types.SimpleNamespace(charm_path=charm_path))
            result = export_transcript(agent, f"markdown {readonly / 'transcript.md'}")
            assert "Failed to write" in result
            # The failed export must not have damaged the on-disk session.
            assert (charm_path / ".cantrip").exists()
        finally:
            readonly.chmod(0o700)
