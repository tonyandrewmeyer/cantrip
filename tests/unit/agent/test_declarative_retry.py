"""Tests for declarative retry blocks (Phase 73.4)."""

from __future__ import annotations

import asyncio
import pathlib
from collections.abc import Awaitable, Callable

import pytest

from cantrip.agent.declarative_retry import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    FileExistsCheck,
    JsonSchemaCheck,
    RetryConfig,
    RetryConfigError,
    ShellCheck,
    parse_retry_config,
    run_with_retry,
)
from cantrip.agent.safety.permissions import (
    PermissionManager,
    PermissionOutcome,
    PermissionRule,
    PermissionRuleset,
)

# ---------------------------------------------------------------------------
# parse_retry_config
# ---------------------------------------------------------------------------


class TestParseRetryConfig:
    """Schema validation around the YAML-frontmatter retry block."""

    def test_none_is_none(self):
        assert parse_retry_config(None) is None

    def test_empty_block_uses_defaults(self):
        cfg = parse_retry_config({})
        assert cfg is not None
        assert cfg.max_retries == DEFAULT_MAX_RETRIES
        assert cfg.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert cfg.checks == ()
        assert cfg.on_failure is None

    def test_full_block_round_trip(self):
        cfg = parse_retry_config(
            {
                "max_retries": 3,
                "timeout_seconds": 120,
                "checks": [
                    {"type": "shell", "command": "pytest -q"},
                    {"type": "file_exists", "path": "src/charm.py"},
                    {
                        "type": "json_schema",
                        "schema": {"type": "object", "properties": {}},
                    },
                ],
                "on_failure": "echo rolled back",
            }
        )
        assert cfg is not None
        assert cfg.max_retries == 3
        assert cfg.timeout_seconds == 120.0
        assert len(cfg.checks) == 3
        shell, file_exists, json_schema = cfg.checks
        assert isinstance(shell, ShellCheck)
        assert shell.command == "pytest -q"
        assert isinstance(file_exists, FileExistsCheck)
        assert file_exists.path == "src/charm.py"
        assert isinstance(json_schema, JsonSchemaCheck)
        assert cfg.on_failure == "echo rolled back"

    def test_top_level_must_be_mapping(self):
        with pytest.raises(RetryConfigError, match="must be a YAML mapping"):
            parse_retry_config(["not", "a", "mapping"])

    def test_unknown_top_level_key_raises(self):
        with pytest.raises(RetryConfigError, match="unknown 'retry' keys"):
            parse_retry_config({"max_retries": 1, "wat": True})

    def test_max_retries_must_be_non_negative_int(self):
        with pytest.raises(RetryConfigError, match=">= 0"):
            parse_retry_config({"max_retries": -1})
        with pytest.raises(RetryConfigError, match="must be an integer"):
            parse_retry_config({"max_retries": "two"})
        with pytest.raises(RetryConfigError, match="must be an integer"):
            parse_retry_config({"max_retries": True})  # bool guard

    def test_max_retries_ceiling_enforced(self):
        with pytest.raises(RetryConfigError, match="must be <="):
            parse_retry_config({"max_retries": 999})

    def test_timeout_must_be_positive_number(self):
        with pytest.raises(RetryConfigError, match="must be > 0"):
            parse_retry_config({"timeout_seconds": 0})
        with pytest.raises(RetryConfigError, match="must be a number"):
            parse_retry_config({"timeout_seconds": "soon"})

    def test_checks_must_be_list(self):
        with pytest.raises(RetryConfigError, match="must be a list"):
            parse_retry_config({"checks": {"type": "shell"}})

    def test_check_unknown_type_rejected(self):
        with pytest.raises(RetryConfigError, match="must be one of"):
            parse_retry_config({"checks": [{"type": "carrier_pigeon"}]})

    def test_check_unknown_keys_rejected(self):
        with pytest.raises(RetryConfigError, match="unknown keys"):
            parse_retry_config({"checks": [{"type": "shell", "command": "ok", "max_attempts": 5}]})

    def test_shell_check_requires_non_empty_command(self):
        with pytest.raises(RetryConfigError, match="must be a non-empty string"):
            parse_retry_config({"checks": [{"type": "shell", "command": "  "}]})

    def test_file_exists_check_rejects_absolute_path(self):
        with pytest.raises(RetryConfigError, match="must be relative"):
            parse_retry_config({"checks": [{"type": "file_exists", "path": "/etc/passwd"}]})

    def test_json_schema_check_requires_mapping(self):
        with pytest.raises(RetryConfigError, match="must be a mapping"):
            parse_retry_config({"checks": [{"type": "json_schema", "schema": "not-a-dict"}]})

    def test_on_failure_must_be_string_or_null(self):
        with pytest.raises(RetryConfigError, match="must be a string or null"):
            parse_retry_config({"on_failure": 12})

    def test_blank_on_failure_normalised_to_none(self):
        cfg = parse_retry_config({"on_failure": "   "})
        assert cfg is not None
        assert cfg.on_failure is None


# ---------------------------------------------------------------------------
# run_with_retry — convergence, retry, timeout
# ---------------------------------------------------------------------------


def _task_returning(*outputs: str) -> Callable[[str], Awaitable[str]]:
    """Build a task callable that yields *outputs* in order, capturing prompts."""
    queue = list(outputs)
    received: list[str] = []

    async def task(prompt: str) -> str:
        received.append(prompt)
        if not queue:
            return outputs[-1]
        return queue.pop(0)

    task.received = received  # type: ignore[attr-defined]
    return task


@pytest.fixture
def repo_root(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path


class TestRunWithRetry:
    @pytest.mark.asyncio
    async def test_no_checks_runs_once(self, repo_root: pathlib.Path):
        cfg = RetryConfig()
        task = _task_returning("ok")
        outcome = await run_with_retry(task, "do it", config=cfg, repo_root=repo_root)
        assert outcome.converged is True
        assert outcome.attempts == 1
        assert outcome.output == "ok"
        assert task.received == ["do it"]  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_passing_check_first_attempt(self, repo_root: pathlib.Path):
        marker = repo_root / "marker"
        marker.write_text("yes")
        cfg = RetryConfig(
            max_retries=3,
            checks=(FileExistsCheck(path="marker"),),
        )
        task = _task_returning("done")
        outcome = await run_with_retry(task, "task", config=cfg, repo_root=repo_root)
        assert outcome.converged is True
        assert outcome.attempts == 1
        assert outcome.failures == ()

    @pytest.mark.asyncio
    async def test_retry_creates_marker_on_second_attempt(self, repo_root: pathlib.Path):
        marker = repo_root / "out.txt"
        cfg = RetryConfig(
            max_retries=3,
            checks=(FileExistsCheck(path="out.txt"),),
        )

        attempts = {"n": 0}
        prompts: list[str] = []

        async def task(prompt: str) -> str:
            prompts.append(prompt)
            attempts["n"] += 1
            if attempts["n"] >= 2:
                marker.write_text("eventually")
            return f"reply {attempts['n']}"

        outcome = await run_with_retry(task, "make it", config=cfg, repo_root=repo_root)
        assert outcome.converged is True
        assert outcome.attempts == 2
        assert "Attempt 1 failed" in prompts[1]
        assert "make it" in prompts[1]  # original goal preserved verbatim
        assert "file_exists `out.txt`" in prompts[1]

    @pytest.mark.asyncio
    async def test_exhausts_retries_records_failures(self, repo_root: pathlib.Path):
        cfg = RetryConfig(
            max_retries=2,
            checks=(FileExistsCheck(path="never.txt"),),
        )
        task = _task_returning("a", "b", "c", "d")
        outcome = await run_with_retry(task, "task", config=cfg, repo_root=repo_root)
        assert outcome.converged is False
        assert outcome.timed_out is False
        # 1 initial + 2 retries = 3 attempts.
        assert outcome.attempts == 3
        assert len(outcome.failures) == 1

    @pytest.mark.asyncio
    async def test_timeout_stops_before_next_attempt(self, repo_root: pathlib.Path):
        cfg = RetryConfig(
            max_retries=10,
            timeout_seconds=1.0,
            checks=(FileExistsCheck(path="nope"),),
        )

        # Fake clock: jumps 5 seconds after the first attempt so the
        # next iteration's deadline check trips.
        ticks = iter([0.0, 0.5, 5.0, 5.0, 5.0])

        def fake_monotonic() -> float:
            try:
                return next(ticks)
            except StopIteration:
                return 99.0

        outcome = await run_with_retry(
            _task_returning("a", "b", "c"),
            "task",
            config=cfg,
            repo_root=repo_root,
            monotonic=fake_monotonic,
        )
        assert outcome.converged is False
        assert outcome.timed_out is True
        # The clock jumped after the first attempt's checks ran, so
        # the second attempt was skipped.
        assert outcome.attempts == 1


# ---------------------------------------------------------------------------
# Check evaluators
# ---------------------------------------------------------------------------


class TestShellChecks:
    @pytest.mark.asyncio
    async def test_shell_pass(self, repo_root: pathlib.Path):
        cfg = RetryConfig(checks=(ShellCheck(command="true"),))
        outcome = await run_with_retry(
            _task_returning("done"), "go", config=cfg, repo_root=repo_root
        )
        assert outcome.converged is True

    @pytest.mark.asyncio
    async def test_shell_fail_includes_stderr_in_detail(self, repo_root: pathlib.Path):
        cfg = RetryConfig(
            max_retries=0,  # one attempt only
            checks=(ShellCheck(command="sh -c 'echo boom >&2; exit 7'"),),
        )
        outcome = await run_with_retry(
            _task_returning("done"), "go", config=cfg, repo_root=repo_root
        )
        assert outcome.converged is False
        assert outcome.attempts == 1
        assert "exit 7" in outcome.failures[0].detail
        assert "boom" in outcome.failures[0].detail

    @pytest.mark.asyncio
    async def test_shell_check_runs_in_repo_root(self, repo_root: pathlib.Path):
        marker = repo_root / "from-cwd"
        marker.write_text("here")
        cfg = RetryConfig(checks=(ShellCheck(command="test -f from-cwd"),))
        outcome = await run_with_retry(
            _task_returning("done"), "go", config=cfg, repo_root=repo_root
        )
        assert outcome.converged is True

    @pytest.mark.asyncio
    async def test_shell_check_denied_by_permissions(self, repo_root: pathlib.Path):
        cfg = RetryConfig(
            max_retries=0,
            checks=(ShellCheck(command="rm -rf /"),),
        )
        ruleset = PermissionRuleset(bash=(PermissionRule("rm *", PermissionOutcome.DENY),))
        outcome = await run_with_retry(
            _task_returning("done"),
            "go",
            config=cfg,
            repo_root=repo_root,
            permissions=ruleset,
        )
        assert outcome.converged is False
        assert "refused by permissions policy" in outcome.failures[0].detail

    @pytest.mark.asyncio
    async def test_shell_check_ask_without_manager(self, repo_root: pathlib.Path):
        cfg = RetryConfig(
            max_retries=0,
            checks=(ShellCheck(command="echo hi"),),
        )
        ruleset = PermissionRuleset(bash=(PermissionRule("echo *", PermissionOutcome.ASK),))
        outcome = await run_with_retry(
            _task_returning("done"),
            "go",
            config=cfg,
            repo_root=repo_root,
            permissions=ruleset,
            permission_manager=None,
        )
        assert outcome.converged is False
        assert "no interactive permission surface" in outcome.failures[0].detail

    @pytest.mark.asyncio
    async def test_shell_check_ask_approved(self, repo_root: pathlib.Path):
        cfg = RetryConfig(checks=(ShellCheck(command="true"),))
        ruleset = PermissionRuleset(bash=(PermissionRule("true*", PermissionOutcome.ASK),))
        manager = PermissionManager(timeout_seconds=5.0)

        async def approve_soon() -> None:
            while not manager.pending:
                await asyncio.sleep(0)
            manager.resolve(manager.pending[0], approved=True)

        approver = asyncio.create_task(approve_soon())
        outcome = await run_with_retry(
            _task_returning("done"),
            "go",
            config=cfg,
            repo_root=repo_root,
            permissions=ruleset,
            permission_manager=manager,
        )
        await approver
        assert outcome.converged is True


class TestFileExistsChecks:
    @pytest.mark.asyncio
    async def test_pass(self, repo_root: pathlib.Path):
        (repo_root / "ok").write_text("x")
        cfg = RetryConfig(checks=(FileExistsCheck(path="ok"),))
        outcome = await run_with_retry(
            _task_returning("done"), "go", config=cfg, repo_root=repo_root
        )
        assert outcome.converged is True

    @pytest.mark.asyncio
    async def test_fail_when_missing(self, repo_root: pathlib.Path):
        cfg = RetryConfig(
            max_retries=0,
            checks=(FileExistsCheck(path="missing"),),
        )
        outcome = await run_with_retry(
            _task_returning("done"), "go", config=cfg, repo_root=repo_root
        )
        assert outcome.converged is False
        assert "no such file" in outcome.failures[0].detail

    @pytest.mark.asyncio
    async def test_traversal_outside_root_rejected(self, repo_root: pathlib.Path):
        # Build a path that would resolve outside the repo root.
        cfg = RetryConfig(
            max_retries=0,
            checks=(FileExistsCheck(path="../escape"),),
        )
        outcome = await run_with_retry(
            _task_returning("done"), "go", config=cfg, repo_root=repo_root
        )
        assert outcome.converged is False
        assert "escapes the repo root" in outcome.failures[0].detail

    @pytest.mark.asyncio
    async def test_directory_does_not_count(self, repo_root: pathlib.Path):
        (repo_root / "subdir").mkdir()
        cfg = RetryConfig(
            max_retries=0,
            checks=(FileExistsCheck(path="subdir"),),
        )
        outcome = await run_with_retry(
            _task_returning("done"), "go", config=cfg, repo_root=repo_root
        )
        assert outcome.converged is False


class TestJsonSchemaChecks:
    @pytest.mark.asyncio
    async def test_pass_with_valid_json(self, repo_root: pathlib.Path):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        cfg = RetryConfig(checks=(JsonSchemaCheck(schema=schema),))
        outcome = await run_with_retry(
            _task_returning('{"name": "alice"}'),
            "go",
            config=cfg,
            repo_root=repo_root,
        )
        assert outcome.converged is True

    @pytest.mark.asyncio
    async def test_fail_with_unparseable_json(self, repo_root: pathlib.Path):
        schema = {"type": "object"}
        cfg = RetryConfig(
            max_retries=0,
            checks=(JsonSchemaCheck(schema=schema),),
        )
        outcome = await run_with_retry(
            _task_returning("not json at all"),
            "go",
            config=cfg,
            repo_root=repo_root,
        )
        assert outcome.converged is False
        assert "not valid JSON" in outcome.failures[0].detail

    @pytest.mark.asyncio
    async def test_fail_with_schema_violation(self, repo_root: pathlib.Path):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        cfg = RetryConfig(
            max_retries=0,
            checks=(JsonSchemaCheck(schema=schema),),
        )
        outcome = await run_with_retry(
            _task_returning("{}"),
            "go",
            config=cfg,
            repo_root=repo_root,
        )
        assert outcome.converged is False
        assert "did not match schema" in outcome.failures[0].detail


# ---------------------------------------------------------------------------
# on_failure
# ---------------------------------------------------------------------------


class TestOnFailure:
    @pytest.mark.asyncio
    async def test_runs_only_on_final_failure(self, repo_root: pathlib.Path):
        marker = repo_root / "rolled-back"
        cfg = RetryConfig(
            max_retries=1,
            checks=(FileExistsCheck(path="never"),),
            on_failure=f"touch {marker}",
        )
        outcome = await run_with_retry(
            _task_returning("a", "b"),
            "go",
            config=cfg,
            repo_root=repo_root,
        )
        assert outcome.converged is False
        assert outcome.on_failure_ran is True
        assert marker.exists()

    @pytest.mark.asyncio
    async def test_does_not_run_on_success(self, repo_root: pathlib.Path):
        marker_target = repo_root / "rolled-back"
        present = repo_root / "present"
        present.write_text("x")
        cfg = RetryConfig(
            checks=(FileExistsCheck(path="present"),),
            on_failure=f"touch {marker_target}",
        )
        outcome = await run_with_retry(
            _task_returning("a"),
            "go",
            config=cfg,
            repo_root=repo_root,
        )
        assert outcome.converged is True
        assert outcome.on_failure_ran is False
        assert not marker_target.exists()

    @pytest.mark.asyncio
    async def test_on_failure_denied_by_permissions(self, repo_root: pathlib.Path):
        cfg = RetryConfig(
            max_retries=0,
            checks=(FileExistsCheck(path="never"),),
            on_failure="rm -rf /",
        )
        ruleset = PermissionRuleset(bash=(PermissionRule("rm *", PermissionOutcome.DENY),))
        outcome = await run_with_retry(
            _task_returning("a"),
            "go",
            config=cfg,
            repo_root=repo_root,
            permissions=ruleset,
        )
        assert outcome.converged is False
        assert outcome.on_failure_ran is False


# ---------------------------------------------------------------------------
# Custom-command frontmatter integration
# ---------------------------------------------------------------------------


class TestCustomCommandRetryFrontmatter:
    """``retry:`` is a recognised key on custom commands and surfaces
    on the loaded :class:`CustomCommand`.
    """

    def test_loaded_with_retry_block(self, tmp_path: pathlib.Path):
        from cantrip.agent.commands.custom import load_command_file

        path = tmp_path / "build-and-test.md"
        path.write_text(
            "---\n"
            "description: Build and run unit tests\n"
            "retry:\n"
            "  max_retries: 2\n"
            "  timeout_seconds: 90\n"
            "  checks:\n"
            "    - type: shell\n"
            '      command: "pytest -q"\n'
            "    - type: file_exists\n"
            "      path: src/charm.py\n"
            '  on_failure: "echo rolled back"\n'
            "---\n"
            "Build the charm, run pytest.\n"
        )
        command = load_command_file(path)
        assert command.retry is not None
        assert command.retry.max_retries == 2
        assert command.retry.timeout_seconds == 90.0
        assert len(command.retry.checks) == 2
        assert command.retry.on_failure == "echo rolled back"

    def test_invalid_retry_block_surfaces_clear_error(self, tmp_path: pathlib.Path):
        from cantrip.agent.commands.custom import (
            CustomCommandError,
            load_command_file,
        )

        path = tmp_path / "bad.md"
        path.write_text(
            "---\ndescription: Bad retry block\nretry:\n  max_retries: -3\n---\nbody\n"
        )
        with pytest.raises(CustomCommandError, match=">= 0"):
            load_command_file(path)

    def test_retry_with_subtask_rejected(self, tmp_path: pathlib.Path):
        from cantrip.agent.commands.custom import (
            CustomCommandError,
            load_command_file,
        )

        path = tmp_path / "subtask.md"
        path.write_text(
            "---\n"
            "description: Retry on a subtask is not yet supported\n"
            "subtask: true\n"
            "agent: build\n"
            "retry:\n"
            "  max_retries: 2\n"
            "---\n"
            "body\n"
        )
        with pytest.raises(CustomCommandError, match="not yet supported on subtask"):
            load_command_file(path)
