"""Declarative retry blocks for tasks (Phase 73.4).

A retry block lets a custom command (or, in a follow-up, a recipe)
declare its own success predicate as a list of *checks* — shell
commands, file-existence probes, JSON-schema validators — and
have Cantrip re-run the underlying task until either every check
passes or a budget is exhausted.

Three distinctions worth keeping straight:

* :class:`~cantrip.agent.ralph.RalphConfig` is "keep iterating
  until the *agent* says ``STOP``".  Self-reported convergence.
* :class:`RetryConfig` is "keep iterating until *my* shell command
  says yes".  User-specified, deterministic predicate.
* The Phase 100 ``wait_for`` tool is a one-shot block on a single
  predicate inside a tool call.  No re-run, no LLM round-trip.

Public surface:

* :class:`RetryConfig` plus the three check dataclasses.
* :func:`parse_retry_config` — turns a YAML-frontmatter ``retry``
  block into a validated :class:`RetryConfig`.
* :func:`run_with_retry` — wraps an awaitable task callable,
  evaluates checks, retries on failure with a corrective prompt,
  and runs ``on_failure`` once at the end if the budget runs out.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import subprocess
import time
from collections.abc import Awaitable, Callable
from typing import Any

from cantrip.agent.permissions import (
    PermissionManager,
    PermissionOutcome,
    PermissionRuleset,
)
from cantrip.agent.permissions import (
    evaluate as evaluate_permissions,
)
from cantrip.llm.structured import StructuredOutputError, validate_against_schema

log = logging.getLogger(__name__)


#: Hard ceiling on a single shell-check run.  Long enough to cover a
#: typical ``pytest`` smoke run, short enough that a hung command
#: doesn't strand the retry budget.
DEFAULT_SHELL_CHECK_TIMEOUT_SECONDS: float = 60.0

#: Default total retry budget when the user omits ``timeout_seconds``.
DEFAULT_TIMEOUT_SECONDS: float = 600.0

#: Default retry count when the user omits ``max_retries``.  ``1``
#: matches Goose: one initial attempt plus one retry on failure.
DEFAULT_MAX_RETRIES: int = 1

#: Hard cap on ``max_retries`` to keep a runaway recipe from
#: looping the model forever.  ``timeout_seconds`` already bounds
#: wall time; this bounds attempt count too.
MAX_RETRIES_CEILING: int = 50


class RetryConfigError(ValueError):
    """Raised when a ``retry:`` block fails parsing or validation."""


# ---------------------------------------------------------------------------
# Check types — discriminated union over the three v1 shapes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ShellCheck:
    """Pass when ``command`` exits with status 0.

    The command runs through :func:`subprocess.run` with
    ``check=False``; stdout / stderr feed into the failure summary
    that gets prepended to the next retry's prompt.  The command
    goes through the Phase 68.2 permission policy so denied
    commands cannot smuggle in via a retry block.
    """

    command: str
    timeout_seconds: float = DEFAULT_SHELL_CHECK_TIMEOUT_SECONDS


@dataclasses.dataclass(frozen=True, slots=True)
class FileExistsCheck:
    """Pass when ``path`` resolves to an existing regular file.

    Path safety mirrors :func:`cantrip.agent.commands.custom.
    _resolve_file_reference`: absolute paths and ``..``-traversal
    outside the repo root are rejected.
    """

    path: str


@dataclasses.dataclass(frozen=True, slots=True)
class JsonSchemaCheck:
    """Pass when the task's final output validates against ``schema``.

    Wraps :func:`cantrip.llm.structured.validate_against_schema` so
    the same validator the planner / oracle / acceptance flows use
    drives retry-block enforcement.  Markdown fences are stripped
    before parsing so a chatty model wrapping JSON in ```` ```json ````
    still passes when the underlying object is correct.
    """

    schema: dict[str, Any]


Check = ShellCheck | FileExistsCheck | JsonSchemaCheck


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class RetryConfig:
    """Validated retry block — what gets parsed out of YAML frontmatter."""

    max_retries: int = DEFAULT_MAX_RETRIES
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    checks: tuple[Check, ...] = ()
    on_failure: str | None = None

    @property
    def total_attempts_cap(self) -> int:
        """Maximum number of task attempts (initial + retries)."""
        return self.max_retries + 1


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {"max_retries", "timeout_seconds", "checks", "on_failure"}
)
_CHECK_KEYS_BY_TYPE: dict[str, frozenset[str]] = {
    "shell": frozenset({"type", "command", "timeout_seconds"}),
    "file_exists": frozenset({"type", "path"}),
    "json_schema": frozenset({"type", "schema"}),
}


def parse_retry_config(data: object) -> RetryConfig | None:
    """Parse a ``retry:`` mapping from YAML frontmatter.

    ``None`` (the absent block) returns ``None``.  Anything else
    must be a mapping; bad shapes raise :class:`RetryConfigError`
    with a key-prefixed message so the caller can surface the
    error verbatim.
    """
    if data is None:
        return None
    if not isinstance(data, dict):
        raise RetryConfigError(f"'retry' must be a YAML mapping, got {type(data).__name__}")

    unknown = set(data.keys()) - _TOP_LEVEL_KEYS
    if unknown:
        raise RetryConfigError(
            f"unknown 'retry' keys {sorted(unknown)}; expected subset of {sorted(_TOP_LEVEL_KEYS)}"
        )

    max_retries = _parse_max_retries(data.get("max_retries", DEFAULT_MAX_RETRIES))
    timeout_seconds = _parse_timeout(data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    checks = _parse_checks(data.get("checks", []))
    on_failure_obj = data.get("on_failure")
    if on_failure_obj is not None and not isinstance(on_failure_obj, str):
        raise RetryConfigError(
            f"'retry.on_failure' must be a string or null, got {type(on_failure_obj).__name__}"
        )
    on_failure = on_failure_obj.strip() if isinstance(on_failure_obj, str) else None
    if on_failure == "":
        on_failure = None

    return RetryConfig(
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        checks=checks,
        on_failure=on_failure,
    )


def _parse_max_retries(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetryConfigError(
            f"'retry.max_retries' must be an integer, got {type(value).__name__}"
        )
    if value < 0:
        raise RetryConfigError(f"'retry.max_retries' must be >= 0, got {value}")
    if value > MAX_RETRIES_CEILING:
        raise RetryConfigError(
            f"'retry.max_retries' must be <= {MAX_RETRIES_CEILING}, got {value}"
        )
    return value


def _parse_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RetryConfigError(
            f"'retry.timeout_seconds' must be a number, got {type(value).__name__}"
        )
    if value <= 0:
        raise RetryConfigError(f"'retry.timeout_seconds' must be > 0, got {value}")
    return float(value)


def _parse_checks(value: object) -> tuple[Check, ...]:
    if not isinstance(value, list):
        raise RetryConfigError(f"'retry.checks' must be a list, got {type(value).__name__}")
    parsed: list[Check] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise RetryConfigError(
                f"'retry.checks[{index}]' must be a mapping, got {type(item).__name__}"
            )
        check_type = item.get("type")
        if not isinstance(check_type, str):
            raise RetryConfigError(f"'retry.checks[{index}].type' must be a string")
        allowed_keys = _CHECK_KEYS_BY_TYPE.get(check_type)
        if allowed_keys is None:
            raise RetryConfigError(
                f"'retry.checks[{index}].type' must be one of "
                f"{sorted(_CHECK_KEYS_BY_TYPE)}, got {check_type!r}"
            )
        unknown_keys = set(item.keys()) - allowed_keys
        if unknown_keys:
            raise RetryConfigError(
                f"'retry.checks[{index}]' has unknown keys "
                f"{sorted(unknown_keys)} for type {check_type!r}"
            )
        parsed.append(_build_check(check_type, item, index))
    return tuple(parsed)


def _build_check(check_type: str, data: dict[str, object], index: int) -> Check:
    if check_type == "shell":
        command = data.get("command")
        if not isinstance(command, str) or not command.strip():
            raise RetryConfigError(f"'retry.checks[{index}].command' must be a non-empty string")
        timeout = data.get("timeout_seconds", DEFAULT_SHELL_CHECK_TIMEOUT_SECONDS)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise RetryConfigError(f"'retry.checks[{index}].timeout_seconds' must be a number")
        if timeout <= 0:
            raise RetryConfigError(f"'retry.checks[{index}].timeout_seconds' must be > 0")
        return ShellCheck(command=command, timeout_seconds=float(timeout))
    if check_type == "file_exists":
        path = data.get("path")
        if not isinstance(path, str) or not path.strip():
            raise RetryConfigError(f"'retry.checks[{index}].path' must be a non-empty string")
        if pathlib.PurePath(path).is_absolute():
            raise RetryConfigError(
                f"'retry.checks[{index}].path' must be relative; got absolute path {path!r}"
            )
        return FileExistsCheck(path=path)
    if check_type == "json_schema":
        schema = data.get("schema")
        if not isinstance(schema, dict):
            raise RetryConfigError(f"'retry.checks[{index}].schema' must be a mapping")
        return JsonSchemaCheck(schema=schema)
    raise RetryConfigError(f"unhandled check type {check_type!r}")  # unreachable


# ---------------------------------------------------------------------------
# Evaluation result types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of a single check evaluation."""

    check: Check
    passed: bool
    detail: str = ""

    @property
    def label(self) -> str:
        """Short identifier suitable for retry-prompt summaries."""
        if isinstance(self.check, ShellCheck):
            return f"shell `{self.check.command}`"
        if isinstance(self.check, FileExistsCheck):
            return f"file_exists `{self.check.path}`"
        return "json_schema"


@dataclasses.dataclass(frozen=True, slots=True)
class RetryOutcome:
    """Result of a complete :func:`run_with_retry` invocation."""

    output: str
    attempts: int
    converged: bool
    timed_out: bool
    failures: tuple[CheckResult, ...] = ()
    on_failure_ran: bool = False


# ---------------------------------------------------------------------------
# Permission gate (shared between checks and on_failure)
# ---------------------------------------------------------------------------


class _PermissionRefused(Exception):
    """Internal signal: a permission gate denied a shell command.

    Surfaces as a failed :class:`CheckResult` (or a no-op
    ``on_failure``) rather than tearing down the run — the retry
    runner handles predicates that can't pass in this session.
    """


async def _gate_shell_command(
    command: str,
    *,
    permissions: PermissionRuleset | None,
    permission_manager: PermissionManager | None,
    agent_name: str,
) -> None:
    """Raise :class:`_PermissionRefused` if the command is not allowed."""
    if permissions is None:
        return
    decision = evaluate_permissions(
        permissions,
        "run_command",
        {"command": command},
        agent_name=agent_name,
    )
    if decision.outcome is PermissionOutcome.DENY:
        raise _PermissionRefused(f"refused by permissions policy: {decision.reason}")
    if decision.outcome is PermissionOutcome.ASK:
        if permission_manager is None:
            raise _PermissionRefused(
                "needs approval but this session has no interactive permission surface"
            )
        approved = await permission_manager.request(
            tool_name="run_command",
            reason=decision.reason,
            arguments={"command": command},
        )
        if not approved:
            raise _PermissionRefused("user declined the permission prompt")


# ---------------------------------------------------------------------------
# Check evaluators
# ---------------------------------------------------------------------------


async def _evaluate_check(
    check: Check,
    output: str,
    *,
    repo_root: pathlib.Path | None,
    permissions: PermissionRuleset | None,
    permission_manager: PermissionManager | None,
    agent_name: str,
) -> CheckResult:
    if isinstance(check, ShellCheck):
        return await _evaluate_shell(
            check,
            repo_root=repo_root,
            permissions=permissions,
            permission_manager=permission_manager,
            agent_name=agent_name,
        )
    if isinstance(check, FileExistsCheck):
        return _evaluate_file_exists(check, repo_root=repo_root)
    return _evaluate_json_schema(check, output)


async def _evaluate_shell(
    check: ShellCheck,
    *,
    repo_root: pathlib.Path | None,
    permissions: PermissionRuleset | None,
    permission_manager: PermissionManager | None,
    agent_name: str,
) -> CheckResult:
    try:
        await _gate_shell_command(
            check.command,
            permissions=permissions,
            permission_manager=permission_manager,
            agent_name=agent_name,
        )
    except _PermissionRefused as exc:
        return CheckResult(check=check, passed=False, detail=str(exc))

    cwd = repo_root if repo_root is not None else pathlib.Path.cwd()
    try:
        completed = subprocess.run(
            ["sh", "-c", check.command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=check.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            check=check,
            passed=False,
            detail=f"timed out after {check.timeout_seconds:.0f}s",
        )
    except (OSError, FileNotFoundError) as exc:
        return CheckResult(check=check, passed=False, detail=f"failed to launch: {exc}")

    if completed.returncode == 0:
        return CheckResult(check=check, passed=True)

    detail = f"exit {completed.returncode}"
    tail = (completed.stderr or completed.stdout or "").strip()
    if tail:
        if len(tail) > 600:
            tail = tail[:600] + " […]"
        detail = f"{detail}: {tail}"
    return CheckResult(check=check, passed=False, detail=detail)


def _evaluate_file_exists(
    check: FileExistsCheck, *, repo_root: pathlib.Path | None
) -> CheckResult:
    base = repo_root if repo_root is not None else pathlib.Path.cwd()
    candidate = pathlib.Path(check.path)
    if candidate.is_absolute():
        return CheckResult(
            check=check,
            passed=False,
            detail=f"absolute path {check.path!r} not permitted",
        )
    try:
        resolved = (base / candidate).resolve(strict=False)
        base_resolved = base.resolve(strict=False)
        resolved.relative_to(base_resolved)
    except (OSError, ValueError):
        return CheckResult(
            check=check,
            passed=False,
            detail=f"path {check.path!r} escapes the repo root",
        )
    if resolved.is_file():
        return CheckResult(check=check, passed=True)
    return CheckResult(
        check=check,
        passed=False,
        detail=f"no such file (resolved to {resolved})",
    )


def _evaluate_json_schema(check: JsonSchemaCheck, output: str) -> CheckResult:
    try:
        validate_against_schema(output, check.schema)
    except StructuredOutputError as exc:
        return CheckResult(check=check, passed=False, detail=str(exc))
    return CheckResult(check=check, passed=True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _build_retry_prompt(
    original: str,
    last_output: str,
    failures: tuple[CheckResult, ...],
    *,
    attempt: int,
) -> str:
    """Compose the corrective prompt for retry attempt *attempt*.

    The original goal stays verbatim at the top so a long-context
    model doesn't drift toward the failure summary.  The summary
    lists every failed check with its label and detail; the last
    attempt's output is included as a tail excerpt so the model
    can see what it produced.
    """
    failure_lines = [f"- {result.label}: {result.detail}" for result in failures]
    tail = last_output.strip()
    if len(tail) > 1500:
        tail = tail[:1500] + " […]"
    if not tail:
        tail = "(no output)"
    return (
        f"{original}\n\n"
        f"---\nAttempt {attempt - 1} failed these checks:\n"
        + "\n".join(failure_lines)
        + "\n\nThe previous response was:\n"
        + tail
        + "\n\nFix the above and try again."
    )


async def _run_on_failure(
    command: str,
    *,
    repo_root: pathlib.Path | None,
    permissions: PermissionRuleset | None,
    permission_manager: PermissionManager | None,
    agent_name: str,
) -> bool:
    """Best-effort cleanup hook on final failure.

    Returns ``True`` if the command ran (regardless of exit status),
    ``False`` if the permission gate refused or launch failed.  No
    raise — cleanup hooks shouldn't unwind the caller.
    """
    try:
        await _gate_shell_command(
            command,
            permissions=permissions,
            permission_manager=permission_manager,
            agent_name=agent_name,
        )
    except _PermissionRefused as exc:
        log.info("retry on_failure %r refused: %s", command, exc)
        return False

    cwd = repo_root if repo_root is not None else pathlib.Path.cwd()
    try:
        subprocess.run(
            ["sh", "-c", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=DEFAULT_SHELL_CHECK_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("retry on_failure %r timed out", command)
    except (OSError, FileNotFoundError) as exc:
        log.warning("retry on_failure %r failed to launch: %s", command, exc)
        return False
    return True


async def run_with_retry(
    task: Callable[[str], Awaitable[str]],
    prompt: str,
    *,
    config: RetryConfig,
    repo_root: pathlib.Path | None = None,
    permissions: PermissionRuleset | None = None,
    permission_manager: PermissionManager | None = None,
    agent_name: str = "primary",
    monotonic: Callable[[], float] = time.monotonic,
) -> RetryOutcome:
    """Run *task* with declarative retry.

    The runner calls *task* with *prompt*, evaluates every check
    against the returned output, and (on failure) re-runs *task*
    with a corrective prompt that quotes the failed checks and
    the previous output.  ``timeout_seconds`` bounds total wall
    time; once the deadline passes the runner returns with
    :attr:`RetryOutcome.timed_out` set rather than starting another
    attempt.

    ``on_failure`` runs once at the end if the runner exits without
    converging.  It is best-effort and never raises.
    """
    if not config.checks:
        # No checks → no convergence criterion → run once and return.
        output = await task(prompt)
        return RetryOutcome(output=output, attempts=1, converged=True, timed_out=False)

    deadline = monotonic() + config.timeout_seconds
    attempt = 0
    current_prompt = prompt
    last_output = ""
    failures: tuple[CheckResult, ...] = ()
    timed_out = False

    while attempt < config.total_attempts_cap:
        if monotonic() >= deadline:
            timed_out = True
            break
        attempt += 1
        last_output = await task(current_prompt)
        results = await _run_checks(
            config.checks,
            last_output,
            repo_root=repo_root,
            permissions=permissions,
            permission_manager=permission_manager,
            agent_name=agent_name,
        )
        failures = tuple(r for r in results if not r.passed)
        if not failures:
            return RetryOutcome(
                output=last_output,
                attempts=attempt,
                converged=True,
                timed_out=False,
            )

        if monotonic() >= deadline:
            timed_out = True
            break

        if attempt < config.total_attempts_cap:
            current_prompt = _build_retry_prompt(
                prompt,
                last_output,
                failures,
                attempt=attempt + 1,
            )

    on_failure_ran = False
    if config.on_failure:
        on_failure_ran = await _run_on_failure(
            config.on_failure,
            repo_root=repo_root,
            permissions=permissions,
            permission_manager=permission_manager,
            agent_name=agent_name,
        )
    return RetryOutcome(
        output=last_output,
        attempts=attempt,
        converged=False,
        timed_out=timed_out,
        failures=failures,
        on_failure_ran=on_failure_ran,
    )


async def _run_checks(
    checks: tuple[Check, ...],
    output: str,
    *,
    repo_root: pathlib.Path | None,
    permissions: PermissionRuleset | None,
    permission_manager: PermissionManager | None,
    agent_name: str,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in checks:
        results.append(
            await _evaluate_check(
                check,
                output,
                repo_root=repo_root,
                permissions=permissions,
                permission_manager=permission_manager,
                agent_name=agent_name,
            )
        )
    return results


__all__ = [
    "Check",
    "CheckResult",
    "FileExistsCheck",
    "JsonSchemaCheck",
    "RetryConfig",
    "RetryConfigError",
    "RetryOutcome",
    "ShellCheck",
    "parse_retry_config",
    "run_with_retry",
]
