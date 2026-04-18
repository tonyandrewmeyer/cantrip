"""Tests for ``cantrip.cli`` — the no-TUI CLI mode."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from unittest import mock

import pytest

from cantrip import cli
from cantrip.agent.preflight import CheckStatus, PreflightEvent
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.llm.base import (
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
)
from cantrip.ui import events as ui_events


def _consume_coro(coro: object) -> int:
    """Stand-in for ``asyncio.run`` that closes the passed coroutine and
    returns 0.

    Using this as a ``side_effect`` keeps unawaited-coroutine warnings out
    of the test output when we only care that ``run_cli`` dispatched
    correctly.
    """
    if hasattr(coro, "close"):
        coro.close()
    return 0


def _make_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "provider": "gemini",
        "model": None,
        "snap": "gemma3",
        "light_model": None,
        "light_snap": None,
        "light_provider": None,
        "path": "/tmp/charm",
        "improve": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# Small pure helpers.
# ---------------------------------------------------------------------------


class TestPrintPreflightEvent:
    @pytest.mark.parametrize(
        "status, icon",
        [
            (CheckStatus.PENDING, "○"),
            (CheckStatus.RUNNING, "⟳"),
            (CheckStatus.PASSED, "✓"),
            (CheckStatus.FAILED, "✗"),
            (CheckStatus.SKIPPED, "–"),
        ],
    )
    def test_maps_each_status_to_its_icon(
        self,
        capsys: pytest.CaptureFixture[str],
        status: CheckStatus,
        icon: str,
    ) -> None:
        cli._print_preflight_event(PreflightEvent(check_name="juju", status=status, message="ok"))
        out = capsys.readouterr().out
        assert out.strip().startswith(icon)
        assert "ok" in out


class TestOnBusTaskEvent:
    def test_writes_status_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        event = ui_events.task_updated(
            task_id="t1",
            title="Build charm",
            status="pending",
            category="build",
        )
        cli._on_bus_task_event(event)
        out = capsys.readouterr().out
        assert "Build charm" in out
        assert "pending" in out


# ---------------------------------------------------------------------------
# _print_tasks / _print_cost / _print_juju_status
# ---------------------------------------------------------------------------


def _agent_with_tasks(*tasks: AgentTask) -> SimpleNamespace:
    queue = SimpleNamespace(all_tasks=lambda: list(tasks))
    return SimpleNamespace(work_queue=queue)


class TestPrintTasks:
    def test_no_tasks(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli._print_tasks(_agent_with_tasks())
        assert "No tasks" in capsys.readouterr().out

    def test_lists_tasks_with_icons_and_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = _agent_with_tasks(
            AgentTask(
                id="t1",
                title="Research workload",
                category=TaskCategory.RESEARCH,
                status=TaskStatus.DONE,
            ),
            AgentTask(
                id="t2",
                title="Write charm",
                category=TaskCategory.BUILD,
                status=TaskStatus.ACTIVE,
            ),
            AgentTask(
                id="t3",
                title="Waiting on human",
                category=TaskCategory.CONFIRM,
                status=TaskStatus.BLOCKED,
                blocked_reason="awaiting design approval",
            ),
        )
        cli._print_tasks(agent)
        out = capsys.readouterr().out
        assert "Research workload" in out
        assert "awaiting design approval" in out
        assert "Total: 3" in out
        # Summary should mention each status represented.
        assert "1 active" in out and "1 blocked" in out and "1 done" in out


class TestPrintCost:
    def test_no_store(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli._print_cost(SimpleNamespace(store=None))
        assert "No usage data" in capsys.readouterr().out

    def test_zero_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        store = SimpleNamespace(
            get_total_usage=lambda: {"prompt_tokens": 0, "completion_tokens": 0},
            get_usage_by_model=lambda: [],
        )
        cli._print_cost(
            SimpleNamespace(
                store=store,
                cache_creation_tokens=0,
                cache_read_tokens=0,
            )
        )
        assert "No tokens used yet" in capsys.readouterr().out

    def test_summary_with_cache_and_per_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        store = SimpleNamespace(
            get_total_usage=lambda: {
                "prompt_tokens": 1234,
                "completion_tokens": 567,
            },
            get_usage_by_model=lambda: [
                {
                    "model": "claude-opus-4",
                    "request_count": 3,
                    "prompt_tokens": 900,
                    "completion_tokens": 400,
                },
                {
                    "model": "gemini-3-flash",
                    "request_count": 2,
                    "prompt_tokens": 334,
                    "completion_tokens": 167,
                },
            ],
        )
        cli._print_cost(
            SimpleNamespace(
                store=store,
                cache_creation_tokens=200,
                cache_read_tokens=800,
                provider=SimpleNamespace(model_name="claude-opus-4"),
            )
        )
        out = capsys.readouterr().out
        assert "1,234" in out and "567" in out and "1,801" in out
        assert "Cache hit" in out and "80%" in out
        assert "claude-opus-4" in out and "1,300 tokens" in out
        assert "gemini-3-flash" in out
        # Cost now shown for priced models and an overall total.
        assert "Estimated total" in out


class TestPrintJujuStatus:
    @pytest.mark.asyncio
    async def test_no_dev_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = SimpleNamespace(state=SimpleNamespace(dev_model=None))
        await cli._print_juju_status(agent)
        assert "No development model" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_renders_apps_and_units(self, capsys: pytest.CaptureFixture[str]) -> None:
        unit = SimpleNamespace(
            workload_status=SimpleNamespace(current="active"),
            agent_status=SimpleNamespace(current="idle"),
        )
        app = SimpleNamespace(
            status=SimpleNamespace(current="active"),
            units={"my-app/0": unit},
        )
        status = SimpleNamespace(apps={"my-app": app})
        fake_juju = SimpleNamespace(status=lambda: status)

        agent = SimpleNamespace(state=SimpleNamespace(dev_model="dev"))
        with mock.patch("jubilant.Juju", return_value=fake_juju):
            await cli._print_juju_status(agent)

        out = capsys.readouterr().out
        assert "Model: dev" in out
        assert "my-app: active (1 units)" in out
        assert "my-app/0: active (idle)" in out

    @pytest.mark.asyncio
    async def test_handles_jubilant_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = SimpleNamespace(state=SimpleNamespace(dev_model="dev"))
        with mock.patch("jubilant.Juju", side_effect=OSError("controller unreachable")):
            await cli._print_juju_status(agent)
        assert "Failed to get Juju status" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _drain_executor
# ---------------------------------------------------------------------------


class TestDrainExecutor:
    @pytest.mark.asyncio
    async def test_returns_immediately_with_no_tasks(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent = _agent_with_tasks()
        await cli._drain_executor(agent)
        assert capsys.readouterr().out == ""

    @pytest.mark.asyncio
    async def test_waits_until_all_tasks_settle(self, capsys: pytest.CaptureFixture[str]) -> None:
        """First two checks report a running task; third reports done."""
        active = AgentTask(id="a", title="x", category=TaskCategory.BUILD)
        active.status = TaskStatus.ACTIVE
        done = AgentTask(id="a", title="x", category=TaskCategory.BUILD)
        done.status = TaskStatus.DONE

        call_count = 0

        def _all_tasks() -> list[AgentTask]:
            nonlocal call_count
            call_count += 1
            # First call via the truthy check, subsequent calls inside loop.
            if call_count <= 2:
                return [active]
            return [done]

        agent = SimpleNamespace(work_queue=SimpleNamespace(all_tasks=_all_tasks))
        with mock.patch("cantrip.cli.asyncio.sleep", new=mock.AsyncMock(return_value=None)):
            await cli._drain_executor(agent)

        out = capsys.readouterr().out
        assert "Waiting for tasks" in out
        assert "All tasks finished" in out

    @pytest.mark.asyncio
    async def test_times_out(self) -> None:
        """If tasks never settle, the deadline trips and control returns."""
        task = AgentTask(id="a", title="x", category=TaskCategory.BUILD)
        task.status = TaskStatus.ACTIVE
        agent = SimpleNamespace(work_queue=SimpleNamespace(all_tasks=lambda: [task]))

        with mock.patch.object(cli, "_DRAIN_TIMEOUT_SECONDS", 0):
            # With a zero deadline the while-loop condition fails immediately.
            await cli._drain_executor(agent)


# ---------------------------------------------------------------------------
# _prepare_cli / _bootstrap_cli
# ---------------------------------------------------------------------------


class TestPrepareCli:
    @pytest.mark.asyncio
    async def test_success_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = SimpleNamespace(
            prepare=mock.AsyncMock(return_value=None),
            state=SimpleNamespace(environment_ready=True),
        )
        await cli._prepare_cli(agent)
        out = capsys.readouterr().out
        assert "Environment ready" in out
        agent.prepare.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_partial_failure_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = SimpleNamespace(
            prepare=mock.AsyncMock(return_value=None),
            state=SimpleNamespace(environment_ready=False),
        )
        await cli._prepare_cli(agent)
        assert "some checks had errors" in capsys.readouterr().out


class TestBootstrapCli:
    @pytest.mark.asyncio
    async def test_no_op_without_charm_type(self) -> None:
        agent = SimpleNamespace(
            state=SimpleNamespace(charm_type=None, environment_ready=True),
            bootstrap_environment=mock.AsyncMock(),
        )
        await cli._bootstrap_cli(agent)
        agent.bootstrap_environment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = SimpleNamespace(
            state=SimpleNamespace(charm_type="machine", environment_ready=True),
            bootstrap_environment=mock.AsyncMock(),
        )
        await cli._bootstrap_cli(agent)
        out = capsys.readouterr().out
        assert "Re-bootstrapping" in out
        assert "Environment ready" in out

    @pytest.mark.asyncio
    async def test_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = SimpleNamespace(
            state=SimpleNamespace(charm_type="machine", environment_ready=False),
            bootstrap_environment=mock.AsyncMock(),
        )
        await cli._bootstrap_cli(agent)
        assert "had errors" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _spinner
# ---------------------------------------------------------------------------


class TestSpinner:
    @pytest.mark.asyncio
    async def test_clears_line_on_cancel(self) -> None:
        """Cancelling the spinner clears the terminal line."""
        import asyncio

        task = asyncio.create_task(cli._spinner("Thinking"))
        await asyncio.sleep(0)  # Let the loop kick off.
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_accepts_list_label(self) -> None:
        import asyncio

        label = ["Working"]
        task = asyncio.create_task(cli._spinner(label))
        await asyncio.sleep(0)
        label[0] = "Deploying"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------------------
# run_cli
# ---------------------------------------------------------------------------


class TestRunCli:
    def test_provider_error_exits_non_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with mock.patch("cantrip.cli.create_provider", side_effect=ProviderError("bad key")):
            rc = cli.run_cli(_make_args())
        assert rc == 1
        assert "bad key" in capsys.readouterr().out

    def test_provider_value_error_exits_non_zero(self) -> None:
        with mock.patch("cantrip.cli.create_provider", side_effect=ValueError("unknown provider")):
            rc = cli.run_cli(_make_args())
        assert rc == 1

    def test_success_path_runs_repl(self) -> None:
        """run_cli builds an agent, delegates to asyncio.run(_repl)."""
        fake_provider = mock.MagicMock()
        fake_light = mock.MagicMock()
        fake_agent = mock.MagicMock()
        fake_agent.state.github_repo = None
        fake_agent.state.mode = "design"

        with (
            mock.patch("cantrip.cli.create_provider", return_value=fake_provider),
            mock.patch(
                "cantrip.cli.resolve_light_provider",
                return_value=(fake_light, "light-model"),
            ),
            mock.patch("cantrip.cli.CantripAgent", return_value=fake_agent) as agent_cls,
            mock.patch("cantrip.cli.asyncio.run", side_effect=_consume_coro) as asyncio_run,
        ):
            rc = cli.run_cli(_make_args())

        assert rc == 0
        agent_cls.assert_called_once()
        asyncio_run.assert_called_once()

    def test_improve_mode_sets_state(self, tmp_path) -> None:
        fake_provider = mock.MagicMock()
        fake_agent = mock.MagicMock()
        fake_agent.state.mode = "design"
        fake_agent.state.github_repo = None
        charm = tmp_path / "existing-charm"
        charm.mkdir()

        with (
            mock.patch("cantrip.cli.create_provider", return_value=fake_provider),
            mock.patch(
                "cantrip.cli.resolve_light_provider",
                return_value=(None, None),
            ),
            mock.patch("cantrip.cli.CantripAgent", return_value=fake_agent),
            mock.patch("cantrip.cli.asyncio.run", side_effect=_consume_coro),
        ):
            cli.run_cli(_make_args(improve=charm))

        assert fake_agent.state.mode == "improve"
        assert fake_agent.state.charm_path == charm

    def test_handles_keyboard_interrupt(self, capsys: pytest.CaptureFixture[str]) -> None:
        fake_provider = mock.MagicMock()
        fake_agent = mock.MagicMock()
        fake_agent.state.github_repo = None
        fake_agent.state.mode = "design"

        def _raise_interrupt(coro):
            # Close the coroutine before raising so no unawaited warning leaks.
            coro.close()
            raise KeyboardInterrupt

        with (
            mock.patch("cantrip.cli.create_provider", return_value=fake_provider),
            mock.patch("cantrip.cli.resolve_light_provider", return_value=(None, None)),
            mock.patch("cantrip.cli.CantripAgent", return_value=fake_agent),
            mock.patch("cantrip.cli.asyncio.run", side_effect=_raise_interrupt),
        ):
            rc = cli.run_cli(_make_args())

        assert rc == 0
        assert "Goodbye" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _repl — drive with a canned input sequence.
# ---------------------------------------------------------------------------


def _make_repl_agent(
    *,
    process_message: mock.AsyncMock | None = None,
    tasks: list[AgentTask] | None = None,
    load_returns: bool = False,
) -> mock.MagicMock:
    """Build an agent stub the REPL can drive."""
    import weakref

    fake_agent = mock.MagicMock()
    fake_agent.state.mode = "design"
    fake_agent.state.github_repo = None
    fake_agent.state.charm_type = None
    fake_agent.state.dev_model = None
    fake_agent.state.environment_ready = True
    fake_agent.load_state.return_value = load_returns
    fake_agent.build_resume_summary.return_value = "resumed stuff"
    fake_agent.process_message = process_message or mock.AsyncMock(return_value="ok")
    fake_agent.save_state = mock.MagicMock()
    fake_agent.start_executor = mock.MagicMock()
    fake_agent.stop_executor = mock.AsyncMock()
    fake_agent.prepare = mock.AsyncMock(return_value=None)
    fake_agent.work_queue = SimpleNamespace(all_tasks=lambda: list(tasks or []))
    fake_agent.event_bus = SimpleNamespace(
        bind_loop=lambda _loop: None,
        subscribe=lambda _t, _cb: None,
    )
    fake_agent.cache_creation_tokens = 0
    fake_agent.cache_read_tokens = 0
    fake_agent.store = None
    # Keep a weak hold so subprocess-capturing mocks don't accidentally leak.
    _ = weakref.ref(fake_agent)
    return fake_agent


def _drive_repl(inputs: list[object]):
    """Return a mock for ``asyncio.to_thread(input, ...)`` that replays ``inputs``.

    Entries can be strings or exceptions — exceptions are raised instead of
    returned, so ``EOFError`` can be used to terminate the REPL cleanly.
    """
    pending = list(inputs)

    async def _fake(_fn, _prompt):
        if not pending:
            raise EOFError
        item = pending.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item()
        if isinstance(item, BaseException):
            raise item
        return item

    return _fake


class TestRepl:
    @pytest.mark.asyncio
    async def test_help_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = _make_repl_agent()
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["/help", EOFError]),
        ):
            await cli._repl(agent)
        out = capsys.readouterr().out
        assert "Available commands" in out

    @pytest.mark.asyncio
    async def test_resume_summary_printed_when_load_state_succeeds(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent = _make_repl_agent(load_returns=True)
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl([EOFError]),
        ):
            await cli._repl(agent)
        assert "[resume] resumed stuff" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_exit_command(self) -> None:
        agent = _make_repl_agent()
        with mock.patch("cantrip.cli.asyncio.to_thread", new=_drive_repl(["exit"])):
            await cli._repl(agent)
        agent.stop_executor.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blank_input_is_skipped(self) -> None:
        agent = _make_repl_agent()
        with mock.patch("cantrip.cli.asyncio.to_thread", new=_drive_repl(["", "   ", "exit"])):
            await cli._repl(agent)
        agent.process_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tasks_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        task = AgentTask(id="t1", title="Build", category=TaskCategory.BUILD)
        agent = _make_repl_agent(tasks=[task])
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["/tasks", "exit"]),
        ):
            await cli._repl(agent)
        assert "Build" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_status_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = _make_repl_agent()
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["/status", "exit"]),
        ):
            await cli._repl(agent)
        assert "No development model" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_cost_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = _make_repl_agent()
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["/cost", "exit"]),
        ):
            await cli._repl(agent)
        assert "No usage data" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_process_message_normal_turn(self, capsys: pytest.CaptureFixture[str]) -> None:
        agent = _make_repl_agent(process_message=mock.AsyncMock(return_value="assistant response"))
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["Hello", "exit"]),
        ):
            await cli._repl(agent)
        out = capsys.readouterr().out
        assert "assistant response" in out
        agent.save_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_provider_rate_limit_friendly_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent = _make_repl_agent(
            process_message=mock.AsyncMock(side_effect=ProviderRateLimitError("slow"))
        )
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["Hello", "exit"]),
        ):
            await cli._repl(agent)
        assert "temporarily unavailable" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_provider_overloaded_friendly_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent = _make_repl_agent(
            process_message=mock.AsyncMock(side_effect=ProviderOverloadedError("busy"))
        )
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["Hello", "exit"]),
        ):
            await cli._repl(agent)
        assert "temporarily unavailable" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_provider_error_printed_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent = _make_repl_agent(process_message=mock.AsyncMock(side_effect=ProviderError("boom")))
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["Hello", "exit"]),
        ):
            await cli._repl(agent)
        captured = capsys.readouterr()
        assert "Provider error: boom" in captured.err

    @pytest.mark.asyncio
    async def test_unexpected_error_printed_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent = _make_repl_agent(process_message=mock.AsyncMock(side_effect=ValueError("oops")))
        with mock.patch(
            "cantrip.cli.asyncio.to_thread",
            new=_drive_repl(["Hello", "exit"]),
        ):
            await cli._repl(agent)
        assert "Unexpected error: oops" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_drains_executor(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agent = _make_repl_agent(process_message=mock.AsyncMock(side_effect=KeyboardInterrupt))
        with (
            mock.patch(
                "cantrip.cli.asyncio.to_thread",
                new=_drive_repl(["Hello", "exit"]),
            ),
            mock.patch("cantrip.cli._drain_executor", new=mock.AsyncMock()) as drain,
        ):
            await cli._repl(agent)
        drain.assert_awaited()
        assert "[interrupted]" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_bootstrap_triggers_on_non_default_preset(self) -> None:
        """After a successful turn, a non-default preset re-bootstraps once."""
        agent = _make_repl_agent()
        agent.state.charm_type = "machine"

        with (
            mock.patch(
                "cantrip.cli.asyncio.to_thread",
                new=_drive_repl(["Hello", "exit"]),
            ),
            mock.patch(
                "cantrip.agent.tools.environment._juju_controller_healthy",
                return_value=False,
            ),
            mock.patch("cantrip.cli._bootstrap_cli", new=mock.AsyncMock()) as boot,
            mock.patch("cantrip.cli._prepare_cli", new=mock.AsyncMock()),
        ):
            await cli._repl(agent)

        boot.assert_called_once_with(agent)
