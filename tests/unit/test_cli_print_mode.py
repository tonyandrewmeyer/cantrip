"""Tests for Phase 67.3 — ``cantrip run --print`` non-interactive mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest import mock

import pytest

from cantrip import print_mode
from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm.base import ProviderError
from cantrip.ui import events as ui_events
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    """Build a minimally-populated argparse Namespace for ``run_print``."""
    base: dict[str, object] = {
        "provider": "claude",
        "model": None,
        "snap": "gemma3",
        "light_model": None,
        "light_snap": None,
        "light_provider": None,
        "base_url": None,
        "path": tmp_path,
        "improve": None,
        "max_iterations": None,
        "max_tokens": None,
        "no_snapshots": True,
        "yolo": False,
        "print_goal": "build a charm",
        "json_output": False,
        "ralph_max_iterations": 0,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _make_agent(tmp_path: Path, *, provider: FakeProvider | None = None) -> CantripAgent:
    """Build a real CantripAgent with a FakeProvider so tests can drive
    the public surface without mocking the agent itself."""
    return CantripAgent(provider=provider or FakeProvider(), charm_path=tmp_path)


# ---------------------------------------------------------------------------
# _emit_event — JSON line-per-event format
# ---------------------------------------------------------------------------


class TestEmitEvent:
    def test_emits_well_formed_ndjson_with_trailing_newline(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ev = ui_events.chat_message(role="assistant", content="done")
        print_mode._emit_event(ev)

        out = capsys.readouterr().out
        assert out.endswith("\n")
        line = out.rstrip("\n")
        # Round-trip: each line is a parseable JSON object.
        parsed = json.loads(line)
        assert parsed["type"] == "chat_message"
        assert parsed["data"]["role"] == "assistant"
        assert parsed["data"]["content"] == "done"
        assert "timestamp" in parsed

    def test_each_call_produces_exactly_one_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        for content in ("a", "b", "c"):
            print_mode._emit_event(ui_events.chat_message(role="assistant", content=content))

        lines = [line for line in capsys.readouterr().out.split("\n") if line]
        assert len(lines) == 3
        for line in lines:
            json.loads(line)


# ---------------------------------------------------------------------------
# _emit_progress — selective human-readable lines
# ---------------------------------------------------------------------------


class TestEmitProgress:
    def test_renders_task_updates_with_category_prefix(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ev = ui_events.task_updated(
            task_id="t1",
            title="Pack the charm",
            status="active",
            category="build",
        )
        print_mode._emit_progress(ev)

        out = capsys.readouterr().out
        assert "[task:build]" in out
        assert "Pack the charm" in out
        assert "active" in out

    def test_renders_chat_messages_with_role_prefix(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ev = ui_events.chat_message(role="assistant", content="all done")
        print_mode._emit_progress(ev)

        out = capsys.readouterr().out
        assert "[assistant]" in out
        assert "all done" in out

    def test_renders_permission_decisions(self, capsys: pytest.CaptureFixture[str]) -> None:
        ev = ui_events.permission_decided(
            tool_name="run_command",
            outcome="deny",
            reason="rm -rf",
        )
        print_mode._emit_progress(ev)

        out = capsys.readouterr().out
        assert "[permission]" in out
        assert "run_command" in out
        assert "deny" in out

    def test_renders_yolo_auto_approval(self, capsys: pytest.CaptureFixture[str]) -> None:
        ev = ui_events.permission_auto_approved(
            tool_name="git_push",
            reason="ask -> auto",
        )
        print_mode._emit_progress(ev)

        out = capsys.readouterr().out
        assert "git_push" in out
        assert "auto-approved" in out

    def test_skips_non_progress_events(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Cache-metric ticks and watcher heartbeats shouldn't spam stdout
        # — print mode is for "the agent did X", not "the bus is alive".
        print_mode._emit_progress(
            ui_events.cache_metrics_updated(cache_creation_tokens=1, cache_read_tokens=1)
        )
        print_mode._emit_progress(ui_events.thinking_changed(active=True))

        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _pending_confirmations / _format_pending_confirmations
# ---------------------------------------------------------------------------


class TestPendingConfirmations:
    def test_returns_pending_and_blocked_confirm_tasks(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent.work_queue.add_task(
            AgentTask(title="Approve push", category=TaskCategory.CONFIRM, id="c1")
        )
        agent.work_queue.add_task(
            AgentTask(
                title="Approve race",
                category=TaskCategory.CONFIRM,
                id="c2",
                status=TaskStatus.BLOCKED,
                blocked_reason="awaiting user",
            )
        )
        # A done CONFIRM doesn't show up — it's already resolved.
        agent.work_queue.add_task(
            AgentTask(title="Old", category=TaskCategory.CONFIRM, id="c3", status=TaskStatus.DONE)
        )
        # A non-CONFIRM pending task doesn't show up either.
        agent.work_queue.add_task(AgentTask(title="Pack", category=TaskCategory.BUILD, id="b1"))

        pending = print_mode._pending_confirmations(agent)
        ids = {t.id for t in pending}
        assert ids == {"c1", "c2"}

    def test_format_includes_task_titles_and_yolo_hint(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        task = AgentTask(title="Approve push", category=TaskCategory.CONFIRM, id="c1")
        agent.work_queue.add_task(task)

        msg = print_mode._format_pending_confirmations([task])
        assert "Approve push" in msg
        assert "[c1]" in msg
        assert "--yolo" in msg


# ---------------------------------------------------------------------------
# _final_exit_code
# ---------------------------------------------------------------------------


class TestFinalExitCode:
    def test_zero_when_queue_empty(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        assert print_mode._final_exit_code(agent) == 0

    def test_zero_when_all_tasks_done(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent.work_queue.add_task(
            AgentTask(title="Pack", category=TaskCategory.BUILD, id="t1", status=TaskStatus.DONE)
        )
        assert print_mode._final_exit_code(agent) == 0

    def test_nonzero_when_any_task_failed(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent.work_queue.add_task(
            AgentTask(
                title="Pack",
                category=TaskCategory.BUILD,
                id="t1",
                status=TaskStatus.FAILED,
            )
        )
        assert print_mode._final_exit_code(agent) == 1

    def test_nonzero_when_any_task_blocked(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent.work_queue.add_task(
            AgentTask(
                title="Push",
                category=TaskCategory.DEPLOY,
                id="t1",
                status=TaskStatus.BLOCKED,
                blocked_reason="awaiting confirmation",
            )
        )
        assert print_mode._final_exit_code(agent) == 1


# ---------------------------------------------------------------------------
# _drain_queue
# ---------------------------------------------------------------------------


class TestDrainQueue:
    @pytest.mark.asyncio
    async def test_returns_true_when_queue_is_empty(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        assert await print_mode._drain_queue(agent) is True

    @pytest.mark.asyncio
    async def test_returns_true_when_all_tasks_settle(self, tmp_path: Path) -> None:
        agent = _make_agent(tmp_path)
        agent.work_queue.add_task(
            AgentTask(title="t", category=TaskCategory.BUILD, id="t1", status=TaskStatus.DONE)
        )
        agent.work_queue.add_task(
            AgentTask(title="t", category=TaskCategory.BUILD, id="t2", status=TaskStatus.FAILED)
        )
        assert await print_mode._drain_queue(agent) is True

    @pytest.mark.asyncio
    async def test_returns_false_when_timeout_fires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Shrink the timeout so the test doesn't have to wait 30 minutes
        # for the false branch.
        monkeypatch.setattr(print_mode, "_DRAIN_TIMEOUT_SECONDS", 0.1)

        agent = _make_agent(tmp_path)
        agent.work_queue.add_task(AgentTask(title="active", category=TaskCategory.BUILD, id="t1"))

        result = await print_mode._drain_queue(agent)
        assert result is False


# ---------------------------------------------------------------------------
# run_print — end-to-end wiring
# ---------------------------------------------------------------------------


class TestRunPrint:
    def test_rejects_empty_goal(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = print_mode.run_print(_make_args(tmp_path, print_goal=""))
        assert rc == 2
        assert "non-empty goal" in capsys.readouterr().err

    def test_provider_error_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with mock.patch(
            "cantrip.print_mode.create_provider",
            side_effect=ProviderError("bad key"),
        ):
            rc = print_mode.run_print(_make_args(tmp_path))
        assert rc == 1
        assert "bad key" in capsys.readouterr().err

    def test_pending_confirm_blocks_run_when_not_yolo(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A persisted CONFIRM task refuses-and-exits non-zero by default."""
        fake_agent = mock.MagicMock()
        fake_agent.state.yolo_mode = False
        fake_agent.work_queue.all_tasks.return_value = [
            AgentTask(title="Approve", category=TaskCategory.CONFIRM, id="c1"),
        ]

        with (
            mock.patch("cantrip.print_mode.create_provider", return_value=mock.MagicMock()),
            mock.patch("cantrip.print_mode.resolve_light_provider", return_value=(None, None)),
            mock.patch("cantrip.print_mode.CantripAgent", return_value=fake_agent),
        ):
            rc = print_mode.run_print(_make_args(tmp_path))

        assert rc == 1
        err = capsys.readouterr().err
        assert "Refusing to run unattended" in err
        assert "Approve" in err
        # We should never have called the runner — the up-front gate
        # bails before asyncio.run.
        fake_agent.start_executor.assert_not_called()

    def test_pending_confirm_allowed_under_yolo(self, tmp_path: Path) -> None:
        """``--yolo`` skips the up-front refusal."""
        fake_agent = mock.MagicMock()
        fake_agent.state.yolo_mode = True
        fake_agent.work_queue.all_tasks.return_value = [
            AgentTask(title="Approve", category=TaskCategory.CONFIRM, id="c1"),
        ]

        async def _fake_run(*_args, **_kwargs):
            return 0

        with (
            mock.patch("cantrip.print_mode.create_provider", return_value=mock.MagicMock()),
            mock.patch("cantrip.print_mode.resolve_light_provider", return_value=(None, None)),
            mock.patch("cantrip.print_mode.CantripAgent", return_value=fake_agent),
            mock.patch("cantrip.print_mode._run_async", side_effect=_fake_run) as run_async,
        ):
            rc = print_mode.run_print(_make_args(tmp_path, yolo=True))

        assert rc == 0
        run_async.assert_called_once()

    def test_keyboard_interrupt_returns_130(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_agent = mock.MagicMock()
        fake_agent.state.yolo_mode = False
        fake_agent.work_queue.all_tasks.return_value = []

        def _interrupt(coro):
            if hasattr(coro, "close"):
                coro.close()
            raise KeyboardInterrupt

        with (
            mock.patch("cantrip.print_mode.create_provider", return_value=mock.MagicMock()),
            mock.patch("cantrip.print_mode.resolve_light_provider", return_value=(None, None)),
            mock.patch("cantrip.print_mode.CantripAgent", return_value=fake_agent),
            mock.patch("cantrip.print_mode.asyncio.run", side_effect=_interrupt),
        ):
            rc = print_mode.run_print(_make_args(tmp_path))

        assert rc == 130
        assert "interrupted" in capsys.readouterr().err

    def test_passes_yolo_flag_to_state(self, tmp_path: Path) -> None:
        """``--yolo`` flips ``state.yolo_mode`` before the runner starts."""
        captured: dict[str, object] = {}

        # ``_run_async`` is ``async def``, so ``mock.patch`` builds an
        # ``AsyncMock``.  The side_effect must be a coroutine function
        # for AsyncMock to await it; a plain function that returns a
        # coroutine would leak unawaited.
        async def _capture_run(agent, goal, json_output, ralph_config=None):
            captured["yolo"] = agent.state.yolo_mode
            captured["goal"] = goal
            captured["json"] = json_output
            captured["ralph"] = ralph_config
            return 0

        with (
            mock.patch("cantrip.print_mode.create_provider", return_value=FakeProvider()),
            mock.patch(
                "cantrip.print_mode.resolve_light_provider",
                return_value=(None, None),
            ),
            mock.patch("cantrip.print_mode._run_async", side_effect=_capture_run),
        ):
            rc = print_mode.run_print(
                _make_args(tmp_path, yolo=True, json_output=True, print_goal="charm me")
            )

        assert rc == 0
        assert captured["yolo"] is True
        assert captured["goal"] == "charm me"
        assert captured["json"] is True


# ---------------------------------------------------------------------------
# _run_async — drives one goal through a real agent
# ---------------------------------------------------------------------------


class TestRunAsync:
    @pytest.mark.asyncio
    async def test_emits_ndjson_for_chat_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent = _make_agent(tmp_path)

        async def _fake_process(_message: str) -> str:
            # Simulate the conversation loop: emit a chat_message event
            # and return the assistant's text.
            agent.event_bus.publish(ui_events.chat_message(role="assistant", content="hello"))
            return "hello"

        agent.process_message = _fake_process  # type: ignore[method-assign]
        agent.start_executor = lambda: None  # type: ignore[method-assign]

        async def _noop_stop():
            return None

        agent.stop_executor = _noop_stop  # type: ignore[method-assign]

        rc = await print_mode._run_async(agent, "go", json_output=True)

        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.split("\n") if line]
        # Every line is JSON-parseable; at least one of them is the
        # chat_message we emitted.
        parsed = [json.loads(line) for line in lines]
        kinds = [p["type"] for p in parsed]
        assert "chat_message" in kinds

    @pytest.mark.asyncio
    async def test_pending_confirm_after_run_blocks_with_nonzero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A CONFIRM task created *during* the run still trips the refusal."""
        agent = _make_agent(tmp_path)

        async def _fake_process(_message: str) -> str:
            # Mid-run, the agent enqueues a CONFIRM task (Phase 64-style).
            agent.work_queue.add_task(
                AgentTask(title="Approve push", category=TaskCategory.CONFIRM, id="c1")
            )
            return "stopped for confirmation"

        agent.process_message = _fake_process  # type: ignore[method-assign]
        agent.start_executor = lambda: None  # type: ignore[method-assign]

        async def _noop_stop():
            return None

        agent.stop_executor = _noop_stop  # type: ignore[method-assign]

        rc = await print_mode._run_async(agent, "deploy", json_output=False)

        assert rc == 1
        err = capsys.readouterr().err
        assert "Refusing to run unattended" in err
        assert "Approve push" in err

    @pytest.mark.asyncio
    async def test_provider_error_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        agent = _make_agent(tmp_path)

        async def _fake_process(_message: str) -> str:
            raise ProviderError("rate limited")

        agent.process_message = _fake_process  # type: ignore[method-assign]
        agent.start_executor = lambda: None  # type: ignore[method-assign]

        async def _noop_stop():
            return None

        agent.stop_executor = _noop_stop  # type: ignore[method-assign]

        rc = await print_mode._run_async(agent, "go", json_output=False)

        assert rc == 1
        assert "rate limited" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_json_mode_emits_user_and_assistant_chat_messages(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """JSON consumers see the prompt and reply as chat_message events.

        ``process_message`` doesn't publish either itself — the TUI
        reads from the streaming yield path.  Print mode therefore has
        to emit them or NDJSON consumers reconstruct nothing useful.
        """
        agent = _make_agent(tmp_path)

        async def _fake_process(_message: str) -> str:
            return "the answer is 42"

        agent.process_message = _fake_process  # type: ignore[method-assign]
        agent.start_executor = lambda: None  # type: ignore[method-assign]

        async def _noop_stop():
            return None

        agent.stop_executor = _noop_stop  # type: ignore[method-assign]

        rc = await print_mode._run_async(agent, "what's the answer?", json_output=True)

        assert rc == 0
        out = capsys.readouterr().out
        events = [json.loads(line) for line in out.splitlines() if line]
        roles = [
            (e["data"].get("role"), e["data"].get("content"))
            for e in events
            if e["type"] == "chat_message"
        ]
        assert ("user", "what's the answer?") in roles
        assert ("assistant", "the answer is 42") in roles

    @pytest.mark.asyncio
    async def test_slash_command_dispatched_not_sent_to_llm(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``/help`` and friends must invoke the dispatcher, not the LLM.

        Before the fix, a slash command in print mode was treated as a
        normal user prompt and the model would hallucinate a help
        message.  The dispatcher should short-circuit before
        ``process_message`` is ever called.
        """
        agent = _make_agent(tmp_path)
        called: list[str] = []

        async def _fake_process(message: str) -> str:
            called.append(message)
            return "should never run"

        agent.process_message = _fake_process  # type: ignore[method-assign]
        agent.start_executor = lambda: None  # type: ignore[method-assign]

        async def _noop_stop():
            return None

        agent.stop_executor = _noop_stop  # type: ignore[method-assign]

        rc = await print_mode._run_async(agent, "/help", json_output=False)

        assert rc == 0
        assert called == []  # process_message must not run for a slash command.
        out = capsys.readouterr().out
        # The shared slash dispatcher always renders some recognisable
        # help marker — be loose about exact text since /help wording
        # evolves.
        assert "/help" in out or "Slash commands" in out

    @pytest.mark.asyncio
    async def test_drain_timeout_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force the drain to time out so we hit that branch.
        monkeypatch.setattr(print_mode, "_DRAIN_TIMEOUT_SECONDS", 0.1)

        agent = _make_agent(tmp_path)

        async def _fake_process(_message: str) -> str:
            agent.work_queue.add_task(
                AgentTask(title="stuck", category=TaskCategory.BUILD, id="t1")
            )
            return "queued"

        agent.process_message = _fake_process  # type: ignore[method-assign]
        agent.start_executor = lambda: None  # type: ignore[method-assign]

        async def _noop_stop():
            return None

        agent.stop_executor = _noop_stop  # type: ignore[method-assign]

        rc = await print_mode._run_async(agent, "go", json_output=False)

        assert rc == 1
        assert "Timed out" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# main.py wiring — print mode pre-empts TUI/Web
# ---------------------------------------------------------------------------


class TestMainDispatch:
    def test_print_flag_is_parsed(self) -> None:
        from cantrip import main

        with mock.patch("sys.argv", ["cantrip", "run", "--print", "do the thing"]):
            args = main.parse_args()
        assert args.print_goal == "do the thing"
        assert args.json_output is False

    def test_print_and_json_flags_combine(self) -> None:
        from cantrip import main

        with mock.patch("sys.argv", ["cantrip", "run", "--print", "go", "--json"]):
            args = main.parse_args()
        assert args.print_goal == "go"
        assert args.json_output is True

    def test_short_p_alias(self) -> None:
        from cantrip import main

        with mock.patch("sys.argv", ["cantrip", "run", "-p", "ship it"]):
            args = main.parse_args()
        assert args.print_goal == "ship it"

    def test_print_with_web_is_rejected(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        from cantrip import main

        args = argparse.Namespace(
            command="run",
            provider="claude",
            model=None,
            snap="gemma3",
            base_url=None,
            light_model=None,
            light_snap=None,
            light_provider=None,
            no_tui=False,
            web=True,
            web_port=8471,
            concurrency=None,
            max_iterations=None,
            max_tokens=None,
            improve=None,
            no_snapshots=True,
            yolo=False,
            theme=None,
            path=tmp_path,
            print_goal="do it",
            json_output=False,
            ralph_max_iterations=0,
        )
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake"}, clear=False):
            rc = main._run(args)
        assert rc == 2
        assert "mutually exclusive" in capsys.readouterr().err
