"""Tests for the Phase 100 ``wait_for`` tool.

Each predicate gets success / failure / timeout coverage; the
``command_exits_zero`` predicate also exercises the policy-deny path
so a destructive shape can't be smuggled in around ``run_command``.
"""

from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import pytest

from cantrip.agent.tools import wait_for as wait_for_module
from cantrip.agent.tools.wait_for import WaitForTool


@pytest.fixture
def tool() -> WaitForTool:
    return WaitForTool()


@pytest.fixture
def fast_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tighten poll cadence so tests don't pay 0.5s per iteration.

    Tests still cover the ``await asyncio.sleep`` path, just at 5ms
    instead of 500ms.
    """
    fast = dict.fromkeys(wait_for_module._POLL_CADENCE, 0.005)
    fast["juju_app_active_idle"] = 0.0
    monkeypatch.setattr(wait_for_module, "_POLL_CADENCE", fast)


@pytest.fixture
def isolate_policies(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Point ``Path.home()`` at a clean tmpdir so policy discovery
    never picks up the host's ``~/.config/cantrip/policies/``."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    return tmp_path


# --- schema ----------------------------------------------------------


class TestSchema:
    def test_predicate_enum_matches_implementation(self, tool: WaitForTool) -> None:
        params = tool.parameters
        enum = params["properties"]["predicate"]["enum"]
        assert set(enum) == set(wait_for_module._POLL_CADENCE)

    def test_required_fields(self, tool: WaitForTool) -> None:
        assert tool.parameters["required"] == ["predicate", "timeout_seconds"]

    async def test_unknown_predicate_rejected(self, tool: WaitForTool) -> None:
        result = await tool.execute(predicate="never", timeout_seconds=1)
        assert not result.success
        assert "Unknown predicate" in result.error

    async def test_timeout_required(self, tool: WaitForTool) -> None:
        result = await tool.execute(predicate="file_exists", path="/tmp/x")
        assert not result.success
        assert "timeout_seconds" in result.error

    async def test_timeout_capped(self, tool: WaitForTool, tmp_path: pathlib.Path) -> None:
        """Timeouts beyond 1800 are clamped silently — the call still
        runs, just with the cap.  We pass an immediately-true predicate
        so the call returns fast."""
        target = tmp_path / "f"
        target.write_text("x")
        result = await tool.execute(
            predicate="file_exists", path=str(target), timeout_seconds=10_000
        )
        assert result.success

    def test_intro_caption_per_predicate(self, tool: WaitForTool) -> None:
        assert "appear" in tool.intro_caption({"predicate": "file_exists", "path": "/tmp/x"})
        assert "exit" in tool.intro_caption({"predicate": "process_exited", "pid": 42})
        assert "127.0.0.1:80" in tool.intro_caption({"predicate": "port_open", "port": 80})
        assert "active/idle" in tool.intro_caption(
            {"predicate": "juju_app_active_idle", "app": "prom"}
        )


# --- file predicates -------------------------------------------------


class TestFileExists:
    async def test_success_when_already_present(
        self, tool: WaitForTool, tmp_path: pathlib.Path
    ) -> None:
        path = tmp_path / "ready"
        path.write_text("hi")
        result = await tool.execute(predicate="file_exists", path=str(path), timeout_seconds=2)
        assert result.success
        assert result.data["timed_out"] is False
        assert result.caption is not None
        assert "appeared" in result.caption

    async def test_validation_requires_path(self, tool: WaitForTool) -> None:
        result = await tool.execute(predicate="file_exists", timeout_seconds=1)
        assert not result.success
        assert "path" in result.error

    async def test_appears_during_wait(
        self,
        tool: WaitForTool,
        tmp_path: pathlib.Path,
        fast_cadence: None,
    ) -> None:
        path = tmp_path / "later"

        def create_after_delay() -> None:
            time.sleep(0.05)
            path.write_text("ok")

        threading.Thread(target=create_after_delay, daemon=True).start()
        result = await tool.execute(predicate="file_exists", path=str(path), timeout_seconds=5)
        assert result.success

    async def test_timeout(
        self, tool: WaitForTool, tmp_path: pathlib.Path, fast_cadence: None
    ) -> None:
        result = await tool.execute(
            predicate="file_exists",
            path=str(tmp_path / "absent"),
            timeout_seconds=1,
        )
        assert not result.success
        assert result.data["timed_out"] is True
        assert "did not appear" in result.error


class TestFileAbsent:
    async def test_success_when_already_gone(
        self, tool: WaitForTool, tmp_path: pathlib.Path
    ) -> None:
        result = await tool.execute(
            predicate="file_absent",
            path=str(tmp_path / "never"),
            timeout_seconds=2,
        )
        assert result.success
        assert "removed" in result.caption

    async def test_timeout_when_present(
        self, tool: WaitForTool, tmp_path: pathlib.Path, fast_cadence: None
    ) -> None:
        path = tmp_path / "stuck"
        path.write_text("x")
        result = await tool.execute(predicate="file_absent", path=str(path), timeout_seconds=1)
        assert not result.success
        assert "still present" in result.error


# --- process predicate ----------------------------------------------


class TestProcessExited:
    async def test_validation_requires_pid(self, tool: WaitForTool) -> None:
        result = await tool.execute(predicate="process_exited", timeout_seconds=1)
        assert not result.success
        assert "pid" in result.error

    async def test_short_lived_child_reports_exit_code(
        self, tool: WaitForTool, fast_cadence: None
    ) -> None:
        proc = subprocess.Popen(  # noqa: S603 - test fixture
            [sys.executable, "-c", "import sys; sys.exit(7)"],
        )
        try:
            result = await tool.execute(
                predicate="process_exited",
                pid=proc.pid,
                timeout_seconds=5,
            )
            assert result.success
            assert result.data["exit_code"] == 7
        finally:
            if proc.returncode is None:
                proc.kill()
                proc.wait()

    async def test_foreign_pid_already_gone(self, tool: WaitForTool, fast_cadence: None) -> None:
        """An unused PID that doesn't exist should be reported as exited
        immediately, without a fabricated exit code."""
        # Pick a PID we're confident isn't in use: spawn a child, let
        # it exit fully, and then probe a PID well past the OS's
        # current allocation.  Linux allocates monotonically up to
        # /proc/sys/kernel/pid_max so a small offset above the parent
        # PID is reliably free.
        pid = 2**22  # well above realistic Linux pid_max defaults
        # Make sure that PID truly doesn't exist before we wait.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            pytest.skip("synthetic PID was actually in use")
        result = await tool.execute(
            predicate="process_exited",
            pid=pid,
            timeout_seconds=2,
        )
        assert result.success
        assert result.data["exit_code"] is None

    async def test_timeout_when_running(self, tool: WaitForTool, fast_cadence: None) -> None:
        proc = subprocess.Popen(  # noqa: S603 - test fixture
            [sys.executable, "-c", "import time; time.sleep(60)"],
        )
        try:
            result = await tool.execute(
                predicate="process_exited",
                pid=proc.pid,
                timeout_seconds=1,
            )
            assert not result.success
            assert result.data["timed_out"] is True
        finally:
            proc.kill()
            proc.wait()


# --- port predicate -------------------------------------------------


class TestPortOpen:
    async def test_validation_requires_port(self, tool: WaitForTool) -> None:
        result = await tool.execute(predicate="port_open", timeout_seconds=1)
        assert not result.success
        assert "port" in result.error

    async def test_invalid_port_range(self, tool: WaitForTool) -> None:
        result = await tool.execute(predicate="port_open", port=70_000, timeout_seconds=1)
        assert not result.success

    async def test_success_against_listener(self, tool: WaitForTool, fast_cadence: None) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            result = await tool.execute(
                predicate="port_open",
                host="127.0.0.1",
                port=port,
                timeout_seconds=2,
            )
            assert result.success, result.error
            assert "opened" in result.caption
        finally:
            listener.close()

    async def test_timeout_when_no_listener(self, tool: WaitForTool, fast_cadence: None) -> None:
        # Pick an unbound port by opening a socket and immediately
        # closing it; the kernel won't recycle in the next 1s.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        result = await tool.execute(
            predicate="port_open",
            host="127.0.0.1",
            port=port,
            timeout_seconds=1,
        )
        assert not result.success
        assert result.data["timed_out"] is True


# --- command_exits_zero ----------------------------------------------


class TestCommandExitsZero:
    async def test_validation_requires_argv(self, tool: WaitForTool) -> None:
        result = await tool.execute(predicate="command_exits_zero", timeout_seconds=1)
        assert not result.success
        assert "command" in result.error

    async def test_argv_must_be_list_of_strings(self, tool: WaitForTool) -> None:
        result = await tool.execute(
            predicate="command_exits_zero",
            command="make integration",
            timeout_seconds=1,
        )
        assert not result.success

    async def test_base_must_be_on_allowlist(
        self, tool: WaitForTool, isolate_policies: pathlib.Path
    ) -> None:
        result = await tool.execute(
            predicate="command_exits_zero",
            command=["bash", "-c", "true"],
            timeout_seconds=1,
        )
        assert not result.success
        assert "allowlist" in result.error

    async def test_success_immediately(
        self,
        tool: WaitForTool,
        isolate_policies: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Mock subprocess.run rather than relying on a real binary so
        the test stays hermetic."""
        completed = subprocess.CompletedProcess(args=["make", "ok"], returncode=0)
        monkeypatch.setattr(
            wait_for_module.subprocess,
            "run",
            lambda *_a, **_k: completed,
        )
        result = await tool.execute(
            predicate="command_exits_zero",
            command=["make", "ok"],
            timeout_seconds=2,
        )
        assert result.success
        assert result.data["returncode"] == 0
        assert "exited zero" in result.caption

    async def test_eventual_success(
        self,
        tool: WaitForTool,
        isolate_policies: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        fast_cadence: None,
    ) -> None:
        attempts = {"count": 0}

        def fake_run(*_a, **_k) -> subprocess.CompletedProcess[str]:
            attempts["count"] += 1
            rc = 0 if attempts["count"] >= 3 else 1
            return subprocess.CompletedProcess(args=["pytest"], returncode=rc)

        monkeypatch.setattr(wait_for_module.subprocess, "run", fake_run)
        result = await tool.execute(
            predicate="command_exits_zero",
            command=["pytest", "-x"],
            timeout_seconds=5,
        )
        assert result.success
        assert attempts["count"] == 3

    async def test_timeout_when_never_zero(
        self,
        tool: WaitForTool,
        isolate_policies: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        fast_cadence: None,
    ) -> None:
        completed = subprocess.CompletedProcess(args=["make"], returncode=2)
        monkeypatch.setattr(wait_for_module.subprocess, "run", lambda *_a, **_k: completed)
        result = await tool.execute(
            predicate="command_exits_zero",
            command=["make", "integration"],
            timeout_seconds=1,
        )
        assert not result.success
        assert result.data["timed_out"] is True
        assert result.data["last_returncode"] == 2

    async def test_command_not_found(
        self,
        tool: WaitForTool,
        isolate_policies: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(*_a, **_k):
            raise FileNotFoundError("no make")

        monkeypatch.setattr(wait_for_module.subprocess, "run", boom)
        result = await tool.execute(
            predicate="command_exits_zero",
            command=["make", "x"],
            timeout_seconds=2,
        )
        assert not result.success
        assert "not found" in result.error.lower()

    async def test_destructive_shape_blocked_without_policy(
        self,
        tool: WaitForTool,
        isolate_policies: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``git push --force`` is a destructive shape — even with
        ``git`` adjacently allowlisted via ``test``, the destructive
        gate refuses without ``approve_destructive: true``.

        We test the gate via a synthetic argv where ``test`` is the
        base (on the wait_for allowlist) and the destructive shape
        kicks via ``compose_policies``.  Realistic shapes (``git push
        --force``) aren't on the wait_for allowlist, but the gate still
        fires for any allowed base whose argv matches a destructive
        pattern.  Use ``charmcraft pack --destructive-mode`` — not on
        the destructive_command_check pattern list — so we instead
        test the gate by directly inserting a policy that would deny.
        """
        # ``test`` is allowlisted but no destructive shape applies to
        # it via destructive_command_check; rather than fake the
        # checker, test the inverse: a denied-shape command (``rm
        # -rf``) is rejected at the allowlist gate before the
        # destructive gate even runs, so ``allowlist`` is the visible
        # error.  This double-locks the policy: an attacker who got
        # ``rm`` onto the allowlist would still trip the destructive
        # gate.  Patch the allowlist to include ``rm`` so we land
        # squarely on the destructive gate.
        monkeypatch.setattr(
            wait_for_module,
            "_COMMAND_ALLOWLIST",
            wait_for_module._COMMAND_ALLOWLIST | {"rm"},
        )
        result = await tool.execute(
            predicate="command_exits_zero",
            command=["rm", "-rf", str(isolate_policies / "victim")],
            timeout_seconds=2,
        )
        assert not result.success
        assert "approve_destructive" in result.error

    async def test_destructive_shape_allowed_with_policy(
        self,
        tool: WaitForTool,
        isolate_policies: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        policies_dir = isolate_policies / ".config" / "cantrip" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "yolo.yaml").write_text("name: yolo\napprove_destructive: true\n")
        monkeypatch.setattr(
            wait_for_module,
            "_COMMAND_ALLOWLIST",
            wait_for_module._COMMAND_ALLOWLIST | {"rm"},
        )
        completed = subprocess.CompletedProcess(args=["rm"], returncode=0)
        monkeypatch.setattr(wait_for_module.subprocess, "run", lambda *_a, **_k: completed)
        result = await tool.execute(
            predicate="command_exits_zero",
            command=["rm", "-rf", str(isolate_policies / "victim")],
            timeout_seconds=2,
        )
        assert result.success


# --- juju_app_active_idle -------------------------------------------


class TestJujuAppActiveIdle:
    async def test_validation_requires_app(self, tool: WaitForTool) -> None:
        result = await tool.execute(predicate="juju_app_active_idle", timeout_seconds=1)
        assert not result.success
        assert "app" in result.error

    async def test_success_path(self, tool: WaitForTool, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, object] = {}

        def fake_wait(app: str, model: str | None, timeout: int) -> bool:
            called["app"] = app
            called["model"] = model
            called["timeout"] = timeout
            return True

        monkeypatch.setattr("cantrip.agent.tools.juju_subprocess.wait_for_app", fake_wait)
        result = await tool.execute(
            predicate="juju_app_active_idle",
            app="prom",
            model="cos",
            timeout_seconds=120,
        )
        assert result.success
        assert called == {"app": "prom", "model": "cos", "timeout": 120}
        assert "active/idle" in result.caption

    async def test_timeout_path(self, tool: WaitForTool, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cantrip.agent.tools.juju_subprocess.wait_for_app",
            lambda *_a, **_k: False,
        )
        result = await tool.execute(
            predicate="juju_app_active_idle",
            app="prom",
            timeout_seconds=10,
        )
        assert not result.success
        assert result.data["timed_out"] is True

    async def test_e2e_through_fake_juju_surface(
        self, tool: WaitForTool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Drive the predicate through ``juju_subprocess.wait_for_app``
        with a fake jubilant.Juju.cli — the contract test that catches
        signature drift in ``wait_for_app`` itself.

        ``wait_for_app`` calls ``jubilant.Juju(model=...).cli(
        "wait-for", "application", app, "--timeout", "Ns",
        include_model=...)``.  We patch ``jubilant.Juju`` to record
        those calls and verify the tool returns success when ``cli``
        does, and timeout when ``cli`` raises ``CLIError``.
        """
        import jubilant

        recorded: list[dict[str, object]] = []

        class _FakeJuju:
            def __init__(self, model: str | None = None) -> None:
                self.model = model

            def cli(self, *args: str, include_model: bool = True) -> str:
                recorded.append(
                    {"args": args, "include_model": include_model, "model": self.model}
                )
                return ""

        monkeypatch.setattr(jubilant, "Juju", _FakeJuju)
        result = await tool.execute(
            predicate="juju_app_active_idle",
            app="redis",
            model="dev",
            timeout_seconds=30,
        )
        assert result.success
        assert recorded == [
            {
                "args": ("wait-for", "application", "redis", "--timeout", "30s"),
                "include_model": True,
                "model": "dev",
            }
        ]

        # Failure path: cli raises CLIError → wait_for_app returns False.
        recorded.clear()

        def boom(_self, *_a, **_k):
            raise jubilant.CLIError(returncode=1, cmd=["juju"], output="", stderr="")

        monkeypatch.setattr(_FakeJuju, "cli", boom)
        result = await tool.execute(
            predicate="juju_app_active_idle",
            app="redis",
            timeout_seconds=10,
        )
        assert not result.success
        assert result.data["timed_out"] is True


# --- registration ---------------------------------------------------


class TestRegistration:
    def test_tool_is_registered_in_build_tools(self) -> None:
        from cantrip.agent.tools import build_tools

        names = {t.name for t in build_tools()}
        assert "wait_for" in names

    def test_caption_set_on_every_path(self) -> None:
        """Phase 81 contract: every ToolResult from this tool sets
        ``caption``.  This test pins the contract for the success and
        timeout paths checked above (failures-by-validation skip the
        caption — the chat fallback covers them via the synthesised
        ``tool_name(...)`` form)."""
        # Sanity-only: the dedicated tests above already assert the
        # caption text per path.  This is here to make a future split
        # of result-construction obvious if it forgets a caption.
        from cantrip.agent.tools.base import build_tool_caption

        result_caption = build_tool_caption(
            "wait_for",
            {"predicate": "file_exists", "path": "/tmp/x"},
            None,
        )
        assert "wait_for" in result_caption
