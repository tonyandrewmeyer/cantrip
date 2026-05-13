"""Tests for the RunCommandTool (scoped command runner)."""

import pathlib
import subprocess
from unittest import mock

import pytest

from cantrip.agent.sandbox import SandboxedRunner, SandboxPolicy
from cantrip.agent.tools.run_command import (
    _DEFAULT_TIMEOUT,
    _MAX_OUTPUT_CHARS,
    _MAX_TIMEOUT,
    DEFAULT_ALLOWLIST,
    RunCommandTool,
)


@pytest.fixture
def tool():
    return RunCommandTool()


@pytest.fixture
def custom_tool():
    return RunCommandTool(allowlist=frozenset({"echo", "ls"}))


class TestRunCommandProperties:
    """Tests for tool metadata."""

    def test_name(self, tool):
        assert tool.name == "run_command"

    def test_required_params(self, tool):
        assert "command" in tool.parameters["required"]

    def test_description_lists_commands(self, tool):
        assert "make" in tool.description
        assert "pytest" in tool.description

    def test_custom_allowlist_in_description(self, custom_tool):
        assert "echo" in custom_tool.description
        assert "make" not in custom_tool.description


class TestRunCommandExecution:
    """Tests for command execution."""

    @pytest.mark.anyio
    async def test_allowed_command_success(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="echo hello")

        assert result.success
        assert "hello" in result.output
        assert result.data["returncode"] == 0

    @pytest.mark.anyio
    async def test_blocked_command(self, tool):
        result = await tool.execute(command="rm -rf /")
        assert not result.success
        assert "not on the allowlist" in result.error
        assert "rm" in result.error

    @pytest.mark.anyio
    async def test_empty_command(self, tool):
        result = await tool.execute(command="")
        assert not result.success
        assert "Empty" in result.error

    @pytest.mark.anyio
    async def test_nonzero_exit_code(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error occurred"

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="ls nonexistent")

        assert not result.success
        assert "exit" in result.error.lower()
        assert result.data["returncode"] == 1

    @pytest.mark.anyio
    async def test_timeout(self, custom_tool):
        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["echo"], timeout=60),
        ):
            result = await custom_tool.execute(command="echo slow")

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.anyio
    async def test_command_not_found(self, custom_tool):
        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = await custom_tool.execute(command="echo hello")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.anyio
    async def test_stderr_appended(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output\n"
        mock_result.stderr = "warning\n"

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="echo hello")

        assert result.success
        assert "output" in result.output
        assert "stderr" in result.output
        assert "warning" in result.output

    @pytest.mark.anyio
    async def test_output_truncated(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "x" * (_MAX_OUTPUT_CHARS + 100)
        mock_result.stderr = ""

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="echo big")

        assert result.success
        assert result.data["truncated"]
        assert "truncated" in result.output

    @pytest.mark.anyio
    async def test_timeout_clamped(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            await custom_tool.execute(command="echo hi", timeout=9999)

        # Should be clamped to _MAX_TIMEOUT.
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["timeout"] == _MAX_TIMEOUT

    @pytest.mark.anyio
    async def test_invalid_syntax(self, tool):
        result = await tool.execute(command="make 'unclosed")
        assert not result.success
        assert "syntax" in result.error.lower()

    @pytest.mark.anyio
    async def test_custom_cwd(self, custom_tool):
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            await custom_tool.execute(command="ls", cwd="/tmp")

        # The sandbox runner resolves the cwd before passing it to
        # subprocess.run — on macOS ``/tmp`` is a symlink to ``/private/tmp``,
        # so compare against the resolved form to stay portable.
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["cwd"] == str(pathlib.Path("/tmp").resolve())


class TestJujuRejected:
    """``juju`` must not be runnable via the generic command runner.

    Snap-packaged ``juju`` invoked under our PID-namespace sandbox trips
    ``[Process 1 is a manager process, refusing.]`` from systemd over
    dbus.  The agent has typed Jubilant-backed tools for every juju
    operation we support, and those bypass the sandbox — so the generic
    runner refuses ``juju`` outright.
    """

    @pytest.mark.anyio
    async def test_juju_not_on_default_allowlist(self, tool):
        result = await tool.execute(command="juju status")
        assert not result.success
        assert "not on the allowlist" in result.error

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("command", "expected_hint"),
        [
            ("juju status", "`juju` tool"),
            ("git status", "`git` tool"),
            ("gh pr list", "`gh` tool"),
        ],
    )
    async def test_allowlist_miss_hints_at_the_dedicated_tool(self, tool, command, expected_hint):
        """An allowlist miss for a command with a typed tool points at that tool."""
        result = await tool.execute(command=command)
        assert not result.success
        assert "not on the allowlist" in result.error
        assert expected_hint in result.error

    @pytest.mark.anyio
    async def test_allowlist_miss_without_a_tool_has_no_hint(self, tool):
        """Commands with no dedicated tool just report the plain allowlist miss."""
        result = await tool.execute(command="rm -rf /tmp/x")
        assert not result.success
        assert "not on the allowlist" in result.error
        assert "tool" not in result.error


class TestRunCommandConstants:
    """Tests for module-level constants."""

    def test_default_allowlist(self):
        assert "make" in DEFAULT_ALLOWLIST
        assert "uv" in DEFAULT_ALLOWLIST
        assert "pytest" in DEFAULT_ALLOWLIST
        assert "ruff" in DEFAULT_ALLOWLIST
        assert "rm" not in DEFAULT_ALLOWLIST

    def test_default_timeout(self):
        assert _DEFAULT_TIMEOUT == 60

    def test_max_timeout(self):
        assert _MAX_TIMEOUT == 300


class TestWrapperDenylist:
    """Phase 49.2: reject commands that wrap another command.

    Defence-in-depth on top of the allowlist — even if an operator adds
    ``env`` or ``bash`` to the allowlist (e.g. for local debugging),
    wrapper-prefixed commands stay blocked.  The error must be distinct
    from the allowlist-miss error so an LLM can learn the difference.
    """

    @pytest.fixture
    def permissive_tool(self):
        """An allowlist that deliberately contains every wrapper we still want to block."""
        return RunCommandTool(
            allowlist=frozenset(
                {"env", "sudo", "bash", "sh", "nohup", "setsid", "timeout", "nice", "make"}
            )
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "command",
        [
            "env make lint",
            "sudo make lint",
            "watch make test",
            "nohup make build",
            "setsid make run",
            "timeout 30 make lint",
            "nice -n 10 make",
            "ionice -c 3 make",
            "chroot /tmp make",
            "stdbuf -oL make",
            "xargs make",
            "bash -c 'rm -rf /'",
            "sh -c 'rm -rf /'",
            "zsh -c 'rm -rf /'",
            "exec rm -rf /",
        ],
    )
    async def test_wrapper_rejected_even_when_allowlisted(self, permissive_tool, command):
        """Every wrapper form fails with the wrapper-specific error."""
        result = await permissive_tool.execute(command=command)
        assert not result.success
        assert "Wrapper command" in result.error
        assert "masks what is really being run" in result.error

    @pytest.mark.anyio
    async def test_wrapper_error_distinct_from_allowlist_miss(self, tool):
        """``env rm`` and ``rm`` produce different error messages.

        ``env`` is a wrapper, ``rm`` is just not allowlisted — the LLM
        needs to see the distinction so it learns to drop wrappers
        rather than retrying the same invocation.
        """
        wrapper_result = await tool.execute(command="env rm -rf /")
        plain_result = await tool.execute(command="rm -rf /")

        assert not wrapper_result.success and not plain_result.success
        assert "Wrapper command" in wrapper_result.error
        assert "Wrapper command" not in plain_result.error
        assert "not on the allowlist" in plain_result.error

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "command",
        [
            "FOO=bar make lint",
            "PATH=/usr/local/bin make",
            "MY_VAR=x PATH=/tmp make lint",
        ],
    )
    async def test_env_assignment_prefix_rejected(self, tool, command):
        """``NAME=value`` shell env-var assignments are wrapper-equivalent."""
        result = await tool.execute(command=command)
        assert not result.success
        assert "Environment-variable assignment" in result.error


class TestBlockedPackages:
    """Reject any command that tries to install Docker / containerd.

    Defence-in-depth on top of the allowlist — none of ``apt`` /
    ``apt-get`` / ``dpkg`` / ``snap`` are allowlisted by default, but
    if an operator widens the allowlist for local debugging, the
    docker block stays in place.  The dev machine's containerd is
    provided by the ``k8s`` snap; a parallel apt-installed containerd
    deadlocks both.
    """

    @pytest.fixture
    def permissive_tool(self):
        """Allowlist that includes the package managers a docker install would use."""
        return RunCommandTool(
            allowlist=frozenset({"apt", "apt-get", "dpkg", "snap", "yum", "dnf", "make"})
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "command",
        [
            "apt install docker.io",
            "apt-get install -y docker-ce containerd.io",
            "apt install docker",
            "snap install docker",
            "snap install --classic docker",
            "dpkg -i docker-ce_24.0.7-1_amd64.deb",
            "apt-get install containerd",
            "apt install docker-engine",
            "apt install docker-compose",
        ],
    )
    async def test_docker_install_rejected(self, permissive_tool, command):
        """Any install-shaped command mentioning a docker/containerd package fails."""
        result = await permissive_tool.execute(command=command)
        assert not result.success
        assert "Refusing to install blocked package" in result.error
        assert "k8s snap" in result.error

    @pytest.mark.anyio
    async def test_blocked_check_runs_before_allowlist(self, tool):
        """``apt`` isn't on the default allowlist, but the docker token is the
        more useful error to surface — the LLM should learn the policy, not
        retry the same package via a different manager."""
        result = await tool.execute(command="apt install docker.io")
        assert not result.success
        assert "Refusing to install blocked package" in result.error

    @pytest.mark.anyio
    async def test_docker_directory_path_not_blocked(self, custom_tool):
        """Tokens that merely *contain* the substring 'docker' (e.g. a
        directory path or a docker-tagged image reference) must not trip
        the rule — the check is whole-token only."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/etc/docker-config\n"
        mock_result.stderr = ""
        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="ls /etc/docker-config")
        assert result.success


class TestShellMetacharacters:
    """Phase 49.2: reject pipelines / compound commands at the source."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("command", "expected_label"),
        [
            ("make ; rm -rf /", "command separator"),
            ("make && rm -rf /", "AND list"),
            ("make || rm -rf /", "OR list"),
            ("make | rm", "pipe"),
            ("make `rm -rf /`", "backtick"),
            ("make $(rm -rf /)", "command substitution"),
            ("make > /etc/passwd", "output redirection"),
            ("make < /etc/shadow", "input redirection"),
        ],
    )
    async def test_shell_metacharacter_rejected(self, tool, command, expected_label):
        """Each metacharacter form produces an explicit 'Shell metacharacter' error."""
        result = await tool.execute(command=command)
        assert not result.success
        assert "Shell metacharacter" in result.error
        assert expected_label in result.error
        # The allowlist error must NOT fire — metacharacter check runs
        # first so the LLM sees the precise reason.
        assert "not on the allowlist" not in result.error

    @pytest.mark.anyio
    async def test_plain_allowlisted_command_still_works(self, custom_tool):
        """Sanity check: the new checks don't regress the happy path."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok\n"
        mock_result.stderr = ""
        with mock.patch(
            "cantrip.agent.tools.run_command.subprocess.run",
            return_value=mock_result,
        ):
            result = await custom_tool.execute(command="echo hello world")
        assert result.success


class TestRunCommandSandbox:
    """The tool runs commands through :class:`SandboxedRunner` (Phase 49.1)."""

    @pytest.mark.anyio
    async def test_uses_injected_sandbox_runner(self, tmp_path):
        """RunCommandTool delegates to the sandbox runner with a policy
        that blocks network and bind-mounts cwd."""
        captured: dict = {}

        class _SpyRunner(SandboxedRunner):
            def run(self, argv, *, cwd, policy=None, timeout=None, **kwargs):  # type: ignore[override]
                captured["argv"] = list(argv)
                captured["cwd"] = cwd
                captured["policy"] = policy
                captured["timeout"] = timeout
                result = mock.MagicMock()
                result.returncode = 0
                result.stdout = "ok\n"
                result.stderr = ""
                return result

        spy = _SpyRunner(mechanism="none")
        tool = RunCommandTool(
            allowlist=frozenset({"echo"}),
            sandbox_runner=spy,
        )
        result = await tool.execute(command="echo hello", cwd=str(tmp_path))
        assert result.success
        assert captured["argv"] == ["echo", "hello"]
        assert captured["policy"] is not None
        assert captured["policy"].network is False
        # cwd must be listed among the read-write paths so the command
        # can actually write to its working tree.
        rw_paths = {str(p) for p in captured["policy"].read_write_paths}
        assert str(tmp_path.resolve()) in rw_paths

    @pytest.mark.anyio
    async def test_default_tool_creates_its_own_runner(self, tmp_path):
        """Without explicit injection, the tool constructs a SandboxedRunner
        internally — verified by patching the class."""
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok\n"
        mock_result.stderr = ""
        with mock.patch(
            "cantrip.agent.tools.run_command.SandboxedRunner",
            return_value=mock.MagicMock(run=mock.MagicMock(return_value=mock_result)),
        ) as runner_class:
            tool = RunCommandTool(allowlist=frozenset({"echo"}))
            await tool.execute(command="echo hi", cwd=str(tmp_path))
        runner_class.assert_called_once()

    def test_sandbox_policy_construction_defaults_to_no_network(self):
        """Sanity check on the default SandboxPolicy shape used by the tool."""
        policy = SandboxPolicy()
        assert policy.network is False
        assert policy.read_write_paths == ()
