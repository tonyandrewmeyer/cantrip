"""Tests for :mod:`cantrip.agent.sandbox` (Phase 49.1)."""

from __future__ import annotations

import pathlib
import subprocess
import sys
from unittest import mock

import pytest

from cantrip.agent.sandbox import (
    SandboxedRunner,
    SandboxPolicy,
    get_event_sink,
    sandbox_available,
    set_event_sink,
)


class TestSandboxAvailable:
    """``sandbox_available`` picks bwrap > unshare > none."""

    def test_prefers_bwrap_when_present(self):
        with (
            mock.patch("cantrip.agent.sandbox.sys.platform", "linux"),
            mock.patch(
                "cantrip.agent.sandbox.shutil.which",
                side_effect=lambda name: "/usr/bin/bwrap" if name == "bwrap" else None,
            ),
        ):
            assert sandbox_available() == "bwrap"

    def test_falls_back_to_unshare(self):
        def which(name):
            return "/usr/bin/unshare" if name == "unshare" else None

        with (
            mock.patch("cantrip.agent.sandbox.sys.platform", "linux"),
            mock.patch("cantrip.agent.sandbox.shutil.which", side_effect=which),
        ):
            assert sandbox_available() == "unshare"

    def test_none_when_neither_present(self):
        with (
            mock.patch("cantrip.agent.sandbox.sys.platform", "linux"),
            mock.patch("cantrip.agent.sandbox.shutil.which", return_value=None),
        ):
            assert sandbox_available() == "none"

    def test_picks_sandbox_exec_on_macos(self):
        def which(name):
            return "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None

        with (
            mock.patch("cantrip.agent.sandbox.sys.platform", "darwin"),
            mock.patch("cantrip.agent.sandbox.shutil.which", side_effect=which),
        ):
            assert sandbox_available() == "sandbox-exec"

    def test_none_on_macos_without_sandbox_exec(self):
        with (
            mock.patch("cantrip.agent.sandbox.sys.platform", "darwin"),
            mock.patch("cantrip.agent.sandbox.shutil.which", return_value=None),
        ):
            assert sandbox_available() == "none"

    def test_none_on_unknown_platform(self):
        with mock.patch("cantrip.agent.sandbox.sys.platform", "freebsd13"):
            assert sandbox_available() == "none"


class TestBwrapWrap:
    """bwrap command construction."""

    def test_basic_bwrap_command_has_namespaces_and_cwd(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="bwrap")
        cmd = runner.wrap(["make", "check"], cwd=tmp_path, policy=SandboxPolicy())
        assert cmd[0] == "bwrap"
        # Required isolation flags.
        for flag in (
            "--die-with-parent",
            "--new-session",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--unshare-net",
        ):
            assert flag in cmd, f"missing {flag}"
        # Working directory is bound read-write and set as chdir.
        assert "--bind" in cmd
        assert str(tmp_path) in cmd
        assert "--chdir" in cmd
        # Command tail follows the ``--`` separator.
        sep = cmd.index("--")
        assert cmd[sep + 1 :] == ["make", "check"]

    def test_network_enabled_drops_unshare_net(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="bwrap")
        cmd = runner.wrap(
            ["curl", "https://example.com"],
            cwd=tmp_path,
            policy=SandboxPolicy(network=True),
        )
        assert "--unshare-net" not in cmd

    def test_read_write_paths_are_bound(self, tmp_path: pathlib.Path):
        extra = tmp_path / "cache"
        extra.mkdir()
        runner = SandboxedRunner(mechanism="bwrap")
        cmd = runner.wrap(
            ["make"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_write_paths=(extra,)),
        )
        # Every ``--bind`` source appears in the command; confirm the
        # extra path shows up as well as cwd.
        binds = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--bind"]
        assert str(tmp_path.resolve()) in binds
        assert str(extra.resolve()) in binds

    def test_missing_read_write_path_is_skipped(self, tmp_path: pathlib.Path):
        """A non-existent policy path is silently dropped so a stale
        config doesn't break the run — cwd is still bound."""
        runner = SandboxedRunner(mechanism="bwrap")
        cmd = runner.wrap(
            ["make"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_write_paths=(tmp_path / "does-not-exist",)),
        )
        binds = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--bind"]
        assert str(tmp_path.resolve()) in binds
        assert not any("does-not-exist" in b for b in binds)

    def test_read_only_paths_use_ro_bind(self, tmp_path: pathlib.Path):
        extra = tmp_path / "shared-cache"
        extra.mkdir()
        runner = SandboxedRunner(mechanism="bwrap")
        cmd = runner.wrap(
            ["make"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_only_paths=(extra,)),
        )
        # System paths use --ro-bind-try; the caller's extra ro path
        # uses --ro-bind (must exist, which we asserted with mkdir()).
        ro_binds = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--ro-bind"]
        assert str(extra.resolve()) in ro_binds

    def test_cwd_not_double_bound(self, tmp_path: pathlib.Path):
        """If the caller lists cwd as an extra rw path, it's only bound once."""
        runner = SandboxedRunner(mechanism="bwrap")
        cmd = runner.wrap(
            ["make"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_write_paths=(tmp_path,)),
        )
        binds = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--bind"]
        assert binds.count(str(tmp_path.resolve())) == 1


class TestUnshareWrap:
    """unshare command construction (fallback — no filesystem bind mounts)."""

    def test_basic_unshare_command(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="unshare")
        cmd = runner.wrap(["make", "check"], cwd=tmp_path, policy=SandboxPolicy())
        assert cmd[0] == "unshare"
        for flag in (
            "--user",
            "--map-root-user",
            "--pid",
            "--fork",
            "--mount-proc",
            "--uts",
            "--ipc",
            "--kill-child",
            "--net",  # network off by default
        ):
            assert flag in cmd, f"missing {flag}"
        sep = cmd.index("--")
        assert cmd[sep + 1 :] == ["make", "check"]

    def test_unshare_with_network_enabled_drops_net(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="unshare")
        cmd = runner.wrap(
            ["curl", "https://example.com"],
            cwd=tmp_path,
            policy=SandboxPolicy(network=True),
        )
        assert "--net" not in cmd


class TestSandboxExecWrap:
    """macOS sandbox-exec command construction."""

    def test_sandbox_exec_uses_p_flag_and_profile(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="sandbox-exec")
        cmd = runner.wrap(["make", "check"], cwd=tmp_path, policy=SandboxPolicy())
        assert cmd[0] == "sandbox-exec"
        assert cmd[1] == "-p"
        profile = cmd[2]
        # Profile is SBPL — Lisp-like.
        assert profile.startswith("(version 1)")
        assert "(deny default)" in profile
        assert "(allow process-exec)" in profile
        # cwd must be allowed for read-write.
        assert f'(subpath "{tmp_path.resolve()}")' in profile
        # Network denied by default.
        assert "(deny network*)" in profile
        # argv appended after the profile literal.
        assert cmd[3:] == ["make", "check"]

    def test_sandbox_exec_network_allowed(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="sandbox-exec")
        cmd = runner.wrap(
            ["curl", "https://example.com"],
            cwd=tmp_path,
            policy=SandboxPolicy(network=True),
        )
        profile = cmd[2]
        assert "(allow network*)" in profile
        assert "(deny network*)" not in profile

    def test_sandbox_exec_read_only_paths(self, tmp_path: pathlib.Path):
        extra = tmp_path / "shared"
        extra.mkdir()
        runner = SandboxedRunner(mechanism="sandbox-exec")
        cmd = runner.wrap(
            ["make"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_only_paths=(extra,)),
        )
        profile = cmd[2]
        # Read-only path appears under (allow file-read* ... ), but not
        # under the file-write* block.
        assert f'(subpath "{extra.resolve()}")' in profile

    def test_sandbox_exec_read_write_paths_include_cwd(self, tmp_path: pathlib.Path):
        extra = tmp_path / "cache"
        extra.mkdir()
        runner = SandboxedRunner(mechanism="sandbox-exec")
        cmd = runner.wrap(
            ["make"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_write_paths=(extra,)),
        )
        profile = cmd[2]
        # The (allow file-read* file-write* ...) block names both.
        assert f'(subpath "{tmp_path.resolve()}")' in profile
        assert f'(subpath "{extra.resolve()}")' in profile

    def test_sandbox_exec_missing_rw_path_skipped(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="sandbox-exec")
        cmd = runner.wrap(
            ["make"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_write_paths=(tmp_path / "does-not-exist",)),
        )
        profile = cmd[2]
        assert "does-not-exist" not in profile


class TestNoSandboxFallback:
    """When no sandbox mechanism is available, run unchanged."""

    def test_argv_unchanged(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="none")
        cmd = runner.wrap(["make", "check"], cwd=tmp_path, policy=SandboxPolicy())
        assert cmd == ["make", "check"]

    def test_warns_once(self, tmp_path: pathlib.Path, caplog):
        # Reset the class-level guard so the warning fires in this test.
        SandboxedRunner._warned_about_fallback = False
        runner = SandboxedRunner(mechanism="none")
        with caplog.at_level("WARNING", logger="cantrip.agent.sandbox"):
            runner.wrap(["echo", "x"], cwd=tmp_path, policy=SandboxPolicy())
            runner.wrap(["echo", "y"], cwd=tmp_path, policy=SandboxPolicy())
        warning_lines = [r for r in caplog.records if "unsandboxed" in r.message]
        assert len(warning_lines) == 1, "warning must fire only once per process"


class TestEventSink:
    """Phase 49.5 observability — sandbox policy events."""

    def setup_method(self, _method):
        # The sink is a module-level global, so other tests that
        # instantiate a CantripAgent install one as a side effect.  Start
        # from a clean slate so each case exercises exactly one scenario.
        set_event_sink(None)

    def teardown_method(self, _method):
        set_event_sink(None)

    def test_set_and_clear_sink(self):
        assert get_event_sink() is None
        sink = mock.MagicMock()
        set_event_sink(sink)
        assert get_event_sink() is sink
        set_event_sink(None)
        assert get_event_sink() is None

    def test_run_invokes_sink_with_policy_details(self, tmp_path: pathlib.Path):
        events: list[tuple[str, dict]] = []
        set_event_sink(lambda name, data: events.append((name, data)))

        runner = SandboxedRunner(mechanism="none")
        with mock.patch(
            "cantrip.agent.sandbox.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ):
            runner.run(["echo", "hi"], cwd=tmp_path, policy=SandboxPolicy())

        assert len(events) == 1
        name, payload = events[0]
        assert name == "sandbox_policy"
        assert payload["mechanism"] == "none"
        assert payload["argv"] == ["echo", "hi"]
        assert payload["network"] is False
        assert payload["cwd"] == str(tmp_path.resolve())

    def test_sink_exception_does_not_break_run(self, tmp_path: pathlib.Path):
        """A misbehaving sink must not prevent the command from executing."""

        def broken_sink(_name, _data):
            raise RuntimeError("sink is broken")

        set_event_sink(broken_sink)
        runner = SandboxedRunner(mechanism="none")
        expected = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with mock.patch(
            "cantrip.agent.sandbox.subprocess.run",
            return_value=expected,
        ):
            result = runner.run(["echo", "x"], cwd=tmp_path)
        # The command still ran and returned its result unchanged.
        assert result is expected


class TestRunDelegation:
    """``run`` calls subprocess.run with the wrapped command."""

    def test_run_invokes_subprocess_with_wrapped_argv(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="bwrap")
        expected_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        with mock.patch(
            "cantrip.agent.sandbox.subprocess.run",
            return_value=expected_result,
        ) as mock_run:
            result = runner.run(["echo", "hello"], cwd=tmp_path, timeout=10)
        assert result.returncode == 0
        call_args, call_kwargs = mock_run.call_args
        argv = call_args[0]
        assert argv[0] == "bwrap"
        # ``echo hello`` is appended after the ``--`` separator.
        sep = argv.index("--")
        assert argv[sep + 1 :] == ["echo", "hello"]
        assert call_kwargs["timeout"] == 10
        assert call_kwargs["cwd"] == str(tmp_path.resolve())

    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="sandbox mechanisms only apply on Linux",
    )
    def test_real_execution_under_available_mechanism(self, tmp_path: pathlib.Path):
        """Smoke test: run a trivial command through whatever mechanism
        this host provides and confirm it exits cleanly."""
        runner = SandboxedRunner()
        result = runner.run(
            ["/bin/sh", "-c", "echo hi"],
            cwd=tmp_path,
            timeout=10,
        )
        assert result.returncode == 0
        assert "hi" in result.stdout
