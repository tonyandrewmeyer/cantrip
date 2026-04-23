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
    sandbox_available,
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

    def test_none_on_non_linux(self):
        with mock.patch("cantrip.agent.sandbox.sys.platform", "darwin"):
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
