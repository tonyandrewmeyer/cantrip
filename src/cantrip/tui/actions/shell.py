"""Phase 69.3 ``Ctrl-X`` shell-mode helpers.

Shell mode lets the user type a command into the chat input and run
it as a subprocess without the LLM ever seeing the call or its output.
The output renders as a ``$ cmd`` block in the chat; the row is
recorded under a deliberately-unrecognised ``"shell"`` role so the
agent's branch-rebuild path skips it on resume (see
``CantripAgent._rebuild_messages_from_active_branch``).

The pure helpers in this module are unit-testable without touching
Textual or starting an event loop.  ``run_shell_command`` runs the
subprocess synchronously and is intentionally blocking — call sites
that need to keep the UI responsive should hop through
``asyncio.to_thread``.
"""

from __future__ import annotations

import dataclasses
import logging
import shlex
import subprocess
from typing import TYPE_CHECKING

from cantrip.agent.sandbox import SandboxedRunner, SandboxPolicy

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)


# Cap captured output before storing or rendering so a runaway command
# (``yes`` typed on the wrong line) cannot blow up the SQLite row or
# saturate the chat scroll.  Matches the ceiling used by ``run_command``.
_MAX_OUTPUT_CHARS = 50_000

# Hard timeout on a single shell-mode command.  The user can rerun for
# anything that needs longer; an unbounded subprocess wedged into the
# UI worker would block the whole input dispatch chain.
_DEFAULT_TIMEOUT_SECONDS = 60


@dataclasses.dataclass(frozen=True, slots=True)
class ParsedShellInput:
    """Result of splitting a raw shell-mode line.

    ``argv`` is empty when the line had nothing executable after the
    optional ``$$`` prefix; the caller should surface
    :attr:`error` to the user instead of running anything.
    """

    argv: tuple[str, ...]
    hidden_from_agent: bool
    error: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class ShellRunResult:
    """Captured output of one shell-mode subprocess invocation."""

    argv: tuple[str, ...]
    exit_code: int
    output: str
    timed_out: bool = False


def parse_shell_input(raw: str) -> ParsedShellInput:
    """Split *raw* into argv, honouring the ``$$`` incognito prefix.

    The prefix is detected before tokenisation so a leading ``$$``
    never lands in ``argv[0]``.  ``shlex`` failures (unbalanced
    quotes, dangling backslash) come back as a friendly error rather
    than a raised exception so the dispatch chain in ``CantripApp``
    can surface them as a system message.
    """
    stripped = raw.strip()
    if not stripped:
        return ParsedShellInput(argv=(), hidden_from_agent=False, error="Empty command.")
    hidden = False
    if stripped.startswith("$$"):
        hidden = True
        stripped = stripped[2:].lstrip()
    if not stripped:
        return ParsedShellInput(
            argv=(),
            hidden_from_agent=hidden,
            error="Empty command after ``$$`` incognito prefix.",
        )
    try:
        parts = shlex.split(stripped)
    except ValueError as exc:
        return ParsedShellInput(
            argv=(),
            hidden_from_agent=hidden,
            error=f"Invalid shell syntax: {exc}",
        )
    if not parts:
        return ParsedShellInput(
            argv=(),
            hidden_from_agent=hidden,
            error="Empty command.",
        )
    return ParsedShellInput(argv=tuple(parts), hidden_from_agent=hidden)


def _truncate(text: str) -> str:
    """Cap *text* to :data:`_MAX_OUTPUT_CHARS` with a clear marker."""
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n[... output truncated at {_MAX_OUTPUT_CHARS} chars ...]"


def run_shell_command(
    argv: Sequence[str],
    *,
    cwd: str,
    runner: SandboxedRunner | None = None,
    policy: SandboxPolicy | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> ShellRunResult:
    """Run *argv* under the sandbox and capture stdout+stderr.

    Phase 49 sandboxing applies — the subprocess inherits the same
    PID/network/mount isolation as the agent's ``run_command`` tool.
    Network is left disabled by default for the same reason: a typo
    in shell mode should not be the path that exfiltrates a token.

    ``FileNotFoundError`` (missing binary) and
    ``subprocess.TimeoutExpired`` are caught and reported as
    nonzero-exit results so the dispatcher can render them like any
    other failure rather than crashing the UI worker.
    """
    if runner is None:
        runner = SandboxedRunner()
    if policy is None:
        # Shell mode handles human-typed commands; the user can opt
        # into network-aware behaviour by relaunching the agent with
        # the appropriate policy.  The default mirrors run_command.
        policy = SandboxPolicy()
    argv_tuple = tuple(argv)
    try:
        completed = runner.run(
            argv_tuple,
            cwd=cwd,
            policy=policy,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return ShellRunResult(
            argv=argv_tuple,
            exit_code=127,
            output=f"command not found: {exc.filename or argv_tuple[0]}",
        )
    except subprocess.TimeoutExpired:
        return ShellRunResult(
            argv=argv_tuple,
            exit_code=124,
            output=f"command timed out after {timeout:.0f}s",
            timed_out=True,
        )
    output = (completed.stdout or "") + (completed.stderr or "")
    return ShellRunResult(
        argv=argv_tuple,
        exit_code=completed.returncode,
        output=_truncate(output),
    )


def metadata_for_persisted_row(
    result: ShellRunResult, *, hidden_from_agent: bool
) -> dict[str, object]:
    """Build the metadata dict stored alongside the shell row.

    The flag is recorded explicitly even when the row is already
    naturally invisible to the agent (its ``"shell"`` role is not in
    the ``cantrip.llm.Role`` enum, so the rebuild path skips it).  The
    captured output sits under ``output`` so the
    :class:`~cantrip.agent.context_providers_builtin.TerminalProvider`
    can render the last visible shell-mode block inline as
    ``@terminal`` without re-running the command.
    """
    return {
        "hidden_from_agent": hidden_from_agent,
        "argv": list(result.argv),
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "output": result.output,
    }
