"""Subagent checkpoint wiring (Phase 52.3).

Drives a ``Subagent`` through rounds with a fake provider + stub tools
and asserts:

- First run persists a ``llm_turn`` row per provider call and a
  ``tool:<name>`` row per tool invocation, reconstructable via the
  ``response_from_dict`` / ``tool_result_from_dict`` serialisers.
- Second run with the same store returns cached results: the
  provider is never called, the stub tool's ``execute`` is never
  called, yet the subagent produces the identical ``SubagentResult``.
- Parallel tool calls in one round land on distinct ordinals
  (different step names) and replay cleanly.
- An input-hash mismatch (different model name) invalidates the
  stored LLM turn and re-runs the provider.
- Tool failures are persisted as-is and replayed as failures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cantrip.agent.durability import (
    KIND_LLM_RESPONSE,
    KIND_TOOL_RESULT,
    CheckpointStore,
    response_from_dict,
    tool_result_from_dict,
)
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.store import SessionStore
from cantrip.agent.subagent import Subagent, SubagentContext
from cantrip.agent.tools.base import ToolResult
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider
from tests.unit.subagent.conftest import _make_tool

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterator


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Iterator[SessionStore]:
    s = SessionStore(tmp_path / ".cantrip")
    s.open()
    yield s
    s.close()


def _ctx(task_id: str = "task-1") -> SubagentContext:
    return SubagentContext(
        task=AgentTask(
            id=task_id,
            title="Checkpoint probe",
            category=TaskCategory.BUILD,
            description="Drive a subagent with a store and confirm checkpoints land.",
        ),
    )


class TestFirstRunRecords:
    """A fresh store captures every LLM turn and every tool call."""

    async def test_single_turn_no_tools(self, store: SessionStore) -> None:
        provider = FakeProvider(responses=[Response(content="done [EXIT: completed]")])
        sub = Subagent(_ctx(), tools=[], provider=provider, store=store)

        result = await sub.run()

        assert result.text == "done [EXIT: completed]"
        cps = CheckpointStore(store).list_for_task("task-1")
        # One LLM turn, no tool calls.
        assert [(c.step_name, c.ordinal, c.kind) for c in cps] == [
            ("llm_turn", 1, KIND_LLM_RESPONSE),
        ]
        response = response_from_dict(cps[0].decode())  # type: ignore[arg-type]
        assert response.content == "done [EXIT: completed]"

    async def test_round_with_tool_call(self, store: SessionStore) -> None:
        tool = _make_tool(
            "read_file",
            execute_return=ToolResult(success=True, output="contents", caption="Read f.py"),
        )
        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "f.py"})],
                ),
                Response(content="Read it. [EXIT: completed]"),
            ]
        )
        sub = Subagent(_ctx(), tools=[tool], provider=provider, store=store)

        result = await sub.run()

        assert "Read it." in result.text
        cps = CheckpointStore(store).list_for_task("task-1")
        # llm_turn#1 (returns tool call) → tool:read_file#1 → llm_turn#2 (final text).
        assert [(c.step_name, c.ordinal, c.kind) for c in cps] == [
            ("llm_turn", 1, KIND_LLM_RESPONSE),
            ("tool:read_file", 1, KIND_TOOL_RESULT),
            ("llm_turn", 2, KIND_LLM_RESPONSE),
        ]
        # Tool result round-trips through the envelope with its caption intact.
        stored_tool = tool_result_from_dict(cps[1].decode())  # type: ignore[arg-type]
        assert stored_tool.success is True
        assert stored_tool.output == "contents"
        assert stored_tool.caption == "Read f.py"


class TestReplaySkipsExecution:
    """Re-running with the same store short-circuits every step."""

    async def test_replay_no_provider_no_tool_calls(self, store: SessionStore) -> None:
        # First run: record everything.
        tool = _make_tool("read_file", execute_return=ToolResult(success=True, output="v1"))
        first_provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[ToolCall(id="tc1", name="read_file", arguments={"path": "f.py"})],
                ),
                Response(content="Done. [EXIT: completed]"),
            ]
        )
        first = Subagent(_ctx(), tools=[tool], provider=first_provider, store=store)
        first_result = await first.run()
        assert first_provider._call_count == 2
        assert tool.execute.call_count == 1

        # Second run: same task_id, same store, *different* provider that
        # would explode if consulted, *different* tool that would explode.
        exploding_tool = _make_tool("read_file")
        exploding_tool.execute.side_effect = AssertionError("tool must not run on replay")

        class ExplodingProvider(FakeProvider):
            async def complete(self, messages, tools=None, **_):  # type: ignore[override]
                raise AssertionError("provider must not be called on replay")

        replay_provider = ExplodingProvider(responses=[])
        replay = Subagent(_ctx(), tools=[exploding_tool], provider=replay_provider, store=store)

        replay_result = await replay.run()

        assert replay_result.text == first_result.text
        assert exploding_tool.execute.call_count == 0

    async def test_replay_after_partial_prior_run(self, store: SessionStore) -> None:
        """Session 1 crashed after turn 1; session 2 resumes from turn 2."""
        # Prime the store with only the first LLM turn + tool call.
        cps = CheckpointStore(store)
        cps.record(
            "task-1",
            "llm_turn",
            1,
            "",
            KIND_LLM_RESPONSE,
            {
                "content": "",
                "tool_calls": [{"id": "tc1", "name": "read_file", "arguments": {"path": "f.py"}}],
                "finish_reason": "stop",
                "usage": {},
                "metadata": {},
            },
        )
        cps.record(
            "task-1",
            "tool:read_file",
            1,
            "",
            KIND_TOOL_RESULT,
            {
                "success": True,
                "output": "old-contents",
                "data": {},
                "error": None,
                "images": [],
                "caption": None,
            },
        )

        # Now resume: only the final LLM turn should fire.
        tool = _make_tool(
            "read_file",
            execute_return=ToolResult(success=True, output="must-not-run"),
        )
        provider = FakeProvider(responses=[Response(content="Wrapped up. [EXIT: completed]")])
        sub = Subagent(_ctx(), tools=[tool], provider=provider, store=store)

        result = await sub.run()

        assert "Wrapped up." in result.text
        # Fresh provider call count == 1 (only the final turn).
        assert provider._call_count == 1
        # Tool was never called — we served from the store.
        assert tool.execute.call_count == 0


class TestParallelToolCalls:
    """Multiple tool calls in one round land on distinct per-name ordinals."""

    async def test_two_different_tools_same_round(self, store: SessionStore) -> None:
        read = _make_tool("read_file", execute_return=ToolResult(success=True, output="r"))
        grep = _make_tool("grep", execute_return=ToolResult(success=True, output="g"))
        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-r", name="read_file", arguments={"path": "a.py"}),
                        ToolCall(id="tc-g", name="grep", arguments={"pattern": "X"}),
                    ],
                ),
                Response(content="Both done. [EXIT: completed]"),
            ]
        )
        sub = Subagent(_ctx(), tools=[read, grep], provider=provider, store=store)

        await sub.run()

        cps = CheckpointStore(store).list_for_task("task-1")
        # Two distinct step names, both at ordinal 1 — independent counters.
        tool_checkpoints = {
            (c.step_name, c.ordinal) for c in cps if c.step_name.startswith("tool:")
        }
        assert tool_checkpoints == {("tool:read_file", 1), ("tool:grep", 1)}

    async def test_same_tool_twice_in_one_round(self, store: SessionStore) -> None:
        read = _make_tool("read_file", execute_return=ToolResult(success=True, output="r"))
        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="read_file", arguments={"path": "a.py"}),
                        ToolCall(id="tc-2", name="read_file", arguments={"path": "b.py"}),
                    ],
                ),
                Response(content="Both. [EXIT: completed]"),
            ]
        )
        sub = Subagent(_ctx(), tools=[read], provider=provider, store=store)

        await sub.run()

        cps = CheckpointStore(store).list_for_task("task-1")
        # Same step name → ordinals 1 and 2 under the ctx counter.
        assert [(c.step_name, c.ordinal) for c in cps if c.step_name == "tool:read_file"] == [
            ("tool:read_file", 1),
            ("tool:read_file", 2),
        ]


class TestInputHashInvalidation:
    """Stored rows are invalidated when the input hash changes."""

    async def test_model_name_change_invalidates_first_turn(
        self,
        store: SessionStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        # Session 1: fake model name "alpha".
        p1 = FakeProvider(responses=[Response(content="from alpha [EXIT: completed]")])
        p1.model_name = "alpha"
        sub1 = Subagent(_ctx(), tools=[], provider=p1, store=store)
        result1 = await sub1.run()
        assert "from alpha" in result1.text

        # Session 2: same task_id, different model name → hash mismatch.
        p2 = FakeProvider(responses=[Response(content="from beta [EXIT: completed]")])
        p2.model_name = "beta"
        sub2 = Subagent(_ctx(), tools=[], provider=p2, store=store)

        with caplog.at_level(logging.WARNING, logger="cantrip.agent.durability"):
            result2 = await sub2.run()

        # The stored checkpoint was invalidated — we got the fresh provider's output.
        assert "from beta" in result2.text
        assert p2._call_count == 1
        assert any("input-hash mismatch" in rec.message for rec in caplog.records)


class TestFailureCaching:
    """Deterministic tool failures are cached so they don't re-burn on resume."""

    async def test_tool_failure_persists_and_replays_as_failure(self, store: SessionStore) -> None:
        failing_tool = _make_tool(
            "charmcraft_pack",
            execute_return=ToolResult(
                success=False, output="", error="snapd barfed", caption="Pack failed"
            ),
        )
        provider1 = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[ToolCall(id="tc-1", name="charmcraft_pack", arguments={})],
                ),
                Response(content="Gave up. [EXIT: failed]"),
            ]
        )
        sub1 = Subagent(_ctx(), tools=[failing_tool], provider=provider1, store=store)
        await sub1.run()
        assert failing_tool.execute.call_count == 1

        # Replay: tool must NOT be called again; the stored failure is served.
        exploding_tool = _make_tool("charmcraft_pack")
        exploding_tool.execute.side_effect = AssertionError("must not re-run on replay")
        provider2 = FakeProvider(responses=[])  # Will hit cache for both turns.
        sub2 = Subagent(_ctx(), tools=[exploding_tool], provider=provider2, store=store)

        result2 = await sub2.run()

        assert "Gave up." in result2.text
        assert exploding_tool.execute.call_count == 0


class TestNoStoreBaseline:
    """Without a store the subagent never builds a ctx and behaves as pre-52.3."""

    async def test_no_store_no_checkpoints(self, tmp_path: pathlib.Path) -> None:
        # Run once without a store.
        tool = _make_tool("read_file", execute_return=ToolResult(success=True, output="x"))
        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[ToolCall(id="t", name="read_file", arguments={})],
                ),
                Response(content="ok [EXIT: completed]"),
            ]
        )
        sub = Subagent(_ctx(), tools=[tool], provider=provider, store=None)

        result = await sub.run()

        assert "ok" in result.text
        assert tool.execute.call_count == 1  # Ran live, not cached.
        # And of course there is no .cantrip file to inspect.
        assert not (tmp_path / ".cantrip").exists()


class TestResumeUX:
    """Phase 52.4 — opt-out env var and resume-from-step-N signal."""

    async def test_no_resume_env_disables_lookup(
        self,
        store: SessionStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``CANTRIP_NO_RESUME=1`` re-runs live even with a populated store."""
        # Pre-populate a fake LLM turn in the store.
        from cantrip.agent.durability import KIND_LLM_RESPONSE, CheckpointStore

        cps = CheckpointStore(store)
        cps.record(
            "task-1",
            "llm_turn",
            1,
            "",
            KIND_LLM_RESPONSE,
            {
                "content": "stale cached reply [EXIT: completed]",
                "tool_calls": [],
                "finish_reason": "stop",
                "usage": {},
                "metadata": {},
            },
        )
        monkeypatch.setenv("CANTRIP_NO_RESUME", "1")

        provider = FakeProvider(responses=[Response(content="fresh reply [EXIT: completed]")])
        sub = Subagent(_ctx(), tools=[], provider=provider, store=store)

        result = await sub.run()

        # The live call wins — the stale row was not consulted.
        assert "fresh reply" in result.text
        assert provider._call_count == 1

    async def test_no_resume_env_various_truthy_values(
        self,
        store: SessionStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for raw in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("CANTRIP_NO_RESUME", raw)
            from cantrip.agent.durability import should_skip_resume

            assert should_skip_resume(), f"{raw!r} should disable resume"

    async def test_no_resume_env_falsy_leaves_resume_on(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from cantrip.agent.durability import should_skip_resume

        for raw in ("0", "false", "", "no"):
            monkeypatch.setenv("CANTRIP_NO_RESUME", raw)
            assert not should_skip_resume(), f"{raw!r} must leave resume enabled"

    async def test_resume_phase_and_event_on_warm_task(
        self,
        store: SessionStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A task with pre-existing checkpoints gets a 'resuming from step N' signal."""
        import logging

        from cantrip.agent.durability import KIND_LLM_RESPONSE, CheckpointStore

        cps = CheckpointStore(store)
        # Prime two prior checkpoints for task-1.
        for ordinal in (1, 2):
            cps.record(
                "task-1",
                "llm_turn",
                ordinal,
                "",
                KIND_LLM_RESPONSE,
                {
                    "content": "",
                    "tool_calls": [{"id": f"tc{ordinal}", "name": "read_file", "arguments": {}}],
                    "finish_reason": "stop",
                    "usage": {},
                    "metadata": {},
                },
            )
        # Plus a tool checkpoint so the count reflects real mixed work.
        cps.record(
            "task-1",
            "tool:read_file",
            1,
            "",
            "tool_result",
            {
                "success": True,
                "output": "cached",
                "data": {},
                "error": None,
                "images": [],
                "caption": None,
            },
        )

        tool = _make_tool("read_file")
        provider = FakeProvider(responses=[Response(content="wrap-up [EXIT: completed]")])
        sub = Subagent(_ctx(), tools=[tool], provider=provider, store=store)

        with caplog.at_level(logging.INFO, logger="cantrip.agent.subagent"):
            await sub.run()

        # The log line names the step number and checkpoint count.
        matching = [rec for rec in caplog.records if "resuming task" in rec.message.lower()]
        assert matching, "expected a 'resuming' log line"
        # N = prior_steps + 1 = 3 + 1 = 4.
        assert "from step 4" in matching[0].message
        assert "3 checkpoint(s) cached" in matching[0].message

        # Event was recorded for the transcript / event log.
        resume_events = store.load_events(event_type="subagent_resume")
        assert len(resume_events) == 1
        import json as _json

        detail = resume_events[0]["detail"]
        if isinstance(detail, str):
            detail = _json.loads(detail)
        assert detail["task_id"] == "task-1"
        assert detail["prior_steps"] == 3
        assert detail["next_step"] == 4

    async def test_no_resume_signal_on_fresh_task(
        self,
        store: SessionStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A task with zero checkpoints stays quiet — no resume banner."""
        import logging

        provider = FakeProvider(responses=[Response(content="hi [EXIT: completed]")])
        sub = Subagent(_ctx(), tools=[], provider=provider, store=store)

        with caplog.at_level(logging.INFO, logger="cantrip.agent.subagent"):
            await sub.run()

        matching = [rec for rec in caplog.records if "resuming task" in rec.message.lower()]
        assert not matching, "fresh task must not log a resume line"
        assert store.load_events(event_type="subagent_resume") == []
