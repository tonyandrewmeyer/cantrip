"""Hook dispatch + execution runtime.

:class:`HookRunner` keeps a pre-bucketed event → hooks map so ``fire()``
is O(1) in the number of hooks for non-matching events — a hot path
since ``pre_tool_call`` / ``post_tool_call`` fire on every tool call.
:class:`HookStats` accumulates per-hook telemetry that the ``/hooks``
slash command renders.

The mutation-envelope spec (a ``pre_tool_call`` hook can rewrite the
pending tool arguments by printing ``{"mutate": {"arguments": {...}}}``
to stdout) is enforced inside :meth:`HookRunner.fire`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import json
import logging
import pathlib
from typing import Any

from cantrip.hooks.config import load_hooks
from cantrip.hooks.types import (
    HookConfig,
    HookEvent,
    HookResult,
    HookResultListener,
)

log = logging.getLogger(__name__)


def _parse_mutation_envelope(stdout: str, hook_name: str) -> dict[str, Any] | None:
    """Extract the ``mutate.arguments`` block from a hook's stdout.

    Returns the replacement arguments dict, or ``None`` when stdout is
    empty, non-JSON, JSON without a ``mutate`` key, or a malformed
    envelope.  Malformed shapes log at WARNING but never raise — a
    misbehaving hook must not break a tool call.
    """
    stripped = stdout.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        # Plain-text stdout (e.g. a logger line) is a perfectly valid
        # non-mutating hook output.  Don't warn.
        return None
    if not isinstance(payload, dict):
        return None
    mutate = payload.get("mutate")
    if mutate is None:
        return None
    if not isinstance(mutate, dict):
        log.warning(
            "Hook %r: `mutate` must be an object, got %s — ignored",
            hook_name,
            type(mutate).__name__,
        )
        return None
    arguments = mutate.get("arguments")
    if arguments is None:
        return None
    if not isinstance(arguments, dict):
        log.warning(
            "Hook %r: `mutate.arguments` must be an object, got %s — ignored",
            hook_name,
            type(arguments).__name__,
        )
        return None
    return arguments


class _OperatorUnset:
    """Sentinel distinguishing 'not yet looked up' from 'looked up, returned None'."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<operator-unset>"


_OPERATOR_UNSET = _OperatorUnset()


async def _read_git_config(key: str, repo_root: pathlib.Path | None) -> str | None:
    """Run ``git config <key>`` and return the value, or None when unset.

    Uses ``-C repo_root`` when *repo_root* is supplied so the lookup
    targets the charm's repo rather than wherever the agent process
    happens to be running.  Falls back to git's normal discovery when
    *repo_root* is None.  Any subprocess failure (git missing, bad
    args, non-git directory) resolves to None — the operator field is
    advisory, not load-bearing.
    """
    cmd: list[str] = ["git"]
    if repo_root is not None:
        cmd += ["-C", str(repo_root)]
    cmd += ["config", "--get", key]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (OSError, FileNotFoundError):
        return None
    try:
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    value = stdout_bytes.decode("utf-8", errors="replace").strip()
    return value or None


async def _resolve_operator(repo_root: pathlib.Path | None) -> dict[str, str] | None:
    """Build the ``operator`` payload field from git's user identity.

    Returns ``{"name": ..., "email": ...}`` with whichever fields are
    set, or ``None`` when neither ``git config user.name`` nor
    ``user.email`` resolves.  Hook scripts can branch on the field's
    presence to detect a configured operator without parsing two
    sub-keys.
    """
    name = await _read_git_config("user.name", repo_root)
    email = await _read_git_config("user.email", repo_root)
    if name is None and email is None:
        return None
    operator: dict[str, str] = {}
    if name is not None:
        operator["name"] = name
    if email is not None:
        operator["email"] = email
    return operator


@dataclasses.dataclass
class _HookHistory:
    """Mutable per-hook accumulator tracked by :class:`HookStats`.

    Fields are public rather than properties so the ``/hooks`` slash
    command can read them directly without juggling a separate view
    object.  Private to :class:`HookStats` — callers outside the
    module should use :meth:`HookStats.for_hook` to fetch snapshots.
    """

    name: str
    event: HookEvent
    invocations: int = 0
    successes: int = 0
    failures: int = 0
    vetoes: int = 0
    timeouts: int = 0
    total_duration_seconds: float = 0.0
    last_invoked_at: datetime.datetime | None = None
    last_exit_code: int | None = None
    last_vetoed: bool = False
    last_timed_out: bool = False

    @property
    def avg_duration_seconds(self) -> float:
        """Average wall-clock duration across every invocation."""
        if self.invocations == 0:
            return 0.0
        return self.total_duration_seconds / self.invocations


class HookStats:
    """Running telemetry for every hook executed in the current session.

    Owned by :class:`CantripAgent` and fed by the
    ``HookResultListener`` the agent registers on its ``HookRunner``.
    Drives the ``/hooks`` slash command.

    Kept small and in-memory: one ``_HookHistory`` per hook name, no
    per-invocation log — the transcript's ``hook_invocation`` events
    cover that, and re-scanning them from SQLite when the slash
    command runs is cheap.  The stats accumulator is the hot-path
    summary; transcript is the audit record.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, _HookHistory] = {}

    def record(self, result: HookResult) -> None:
        """Fold *result* into the per-hook accumulator."""
        history = self._by_name.get(result.name)
        if history is None:
            history = _HookHistory(name=result.name, event=result.event)
            self._by_name[result.name] = history
        history.invocations += 1
        history.total_duration_seconds += result.duration_seconds
        history.last_invoked_at = datetime.datetime.now()
        history.last_exit_code = result.exit_code
        history.last_vetoed = result.vetoed
        history.last_timed_out = result.timed_out
        if result.succeeded:
            history.successes += 1
        else:
            history.failures += 1
        if result.vetoed:
            history.vetoes += 1
        if result.timed_out:
            history.timeouts += 1

    def for_hook(self, name: str) -> _HookHistory | None:
        """Return the history for *name*, or None if the hook never ran."""
        return self._by_name.get(name)

    def snapshot(self) -> list[_HookHistory]:
        """Return every known hook history in deterministic order."""
        return sorted(self._by_name.values(), key=lambda h: h.name)

    def __len__(self) -> int:
        return len(self._by_name)


class HookRunner:
    """Dispatches events to configured hooks.

    The runner keeps a pre-bucketed event → hooks map so ``fire()`` is
    O(1) in the number of hooks for the non-matching events — a hot
    path since ``pre_tool_call`` / ``post_tool_call`` fire on every
    tool invocation.
    """

    def __init__(
        self,
        hooks: list[HookConfig] | None = None,
        *,
        repo_root: pathlib.Path | str | None = None,
    ):
        """Build a runner for *hooks* (defaults to no hooks).

        *repo_root* tells :meth:`fire` where to read git's user.name /
        user.email from when populating the ``operator`` payload field.
        ``None`` falls back to git's normal cwd-based discovery (which
        in turn falls back to the global config).
        """
        self._by_event: dict[HookEvent, list[HookConfig]] = {}
        for hook in hooks or []:
            self._by_event.setdefault(hook.event, []).append(hook)
        self._listener: HookResultListener | None = None
        self._repo_root: pathlib.Path | None = (
            pathlib.Path(repo_root) if repo_root is not None else None
        )
        # Operator identity is cached after the first fire() so we don't
        # spawn ``git config`` on every tool call.  Sentinel is ``...``
        # because ``None`` is a valid resolved value (git unconfigured).
        self._operator_cache: dict[str, str] | _OperatorUnset | None = _OPERATOR_UNSET

    @classmethod
    def from_disk(cls, repo_root: pathlib.Path | str | None = None) -> HookRunner:
        """Return convenience constructor that loads ``hooks.yaml`` from disk."""
        return cls(load_hooks(repo_root=repo_root), repo_root=repo_root)

    def set_listener(self, listener: HookResultListener | None) -> None:
        """Register (or clear) a per-result callback.

        The agent uses this to thread every execution through its
        :class:`HookStats` accumulator and record a ``hook_invocation``
        transcript event.  Listener exceptions are logged and
        swallowed at DEBUG so a misbehaving listener can never break
        the agent loop.

        Use ``None`` to detach — handy in tests that reuse the same
        runner for multiple agents.
        """
        self._listener = listener

    @property
    def hook_count(self) -> int:
        """Total number of registered hooks, across every event."""
        return sum(len(v) for v in self._by_event.values())

    def hooks_for(self, event: HookEvent) -> list[HookConfig]:
        """Return the hooks registered for *event* (read-only view)."""
        return list(self._by_event.get(event, ()))

    async def fire(
        self, event: HookEvent, payload: dict[str, Any] | None = None
    ) -> list[HookResult]:
        """Run every hook registered for *event* and collect results.

        *payload* is serialised to JSON and piped to the hook's stdin
        so scripts can consume it with ``jq`` or ``python -c 'json.load(
        sys.stdin)'``.  The ``event`` and a current ISO timestamp are
        always included so hooks can tell pre / post apart when they
        share a name.

        Hooks run sequentially.  If that becomes a bottleneck we can
        promote this to parallel execution under a bounded semaphore,
        but sequential gives deterministic ordering and a cleaner
        audit log — and makes the future veto semantics in 46.4
        unambiguous.
        """
        hooks = self._by_event.get(event, [])
        if not hooks:
            return []

        enriched = dict(payload or {})
        enriched["event"] = event.value
        enriched.setdefault("timestamp", datetime.datetime.now().isoformat())
        # Operator identity is resolved once per HookRunner — git config
        # rarely changes mid-session and shelling out twice on every
        # tool call would dwarf the cost of a fast hook.  Hooks that
        # don't reference ``operator`` keep working unchanged; the field
        # is purely additive.
        if isinstance(self._operator_cache, _OperatorUnset):
            self._operator_cache = await _resolve_operator(self._repo_root)
        enriched["operator"] = self._operator_cache

        # Only ``pre_tool_call`` honours the mutation envelope, so for
        # every other event we serialise stdin once and reuse it — the
        # payload cannot change between hooks in the same fire() call.
        mutations_enabled = event == HookEvent.PRE_TOOL_CALL
        static_stdin: bytes | None = (
            None if mutations_enabled else json.dumps(enriched, default=str).encode("utf-8")
        )

        results: list[HookResult] = []
        for hook in hooks:
            # ``if:`` filters are evaluated against the enriched
            # payload so ``event`` and ``timestamp`` are available
            # even though the caller didn't pass them.  For
            # pre_tool_call chains, the filter sees any prior hook's
            # mutations too — that's the right behaviour, a filter like
            # ``arguments.branch == "main"`` should skip a hook if an
            # earlier hook rewrote the branch.
            if hook.if_expr is not None and not hook.if_expr.matches(enriched):
                log.debug(
                    "Hook %r (%s) skipped by if-filter %r",
                    hook.name,
                    hook.event.value,
                    hook.if_expr.source,
                )
                continue
            stdin_bytes = (
                static_stdin
                if static_stdin is not None
                else json.dumps(enriched, default=str).encode("utf-8")
            )
            result = await self._run_one(hook, stdin_bytes)
            # Apply mutation only when enabled *and* the hook
            # succeeded: a vetoing hook (non-zero exit,
            # ``continue_on_error: false``) blocks the call so its
            # envelope can't influence a run that won't happen.
            if mutations_enabled and result.succeeded:
                mutation = _parse_mutation_envelope(result.stdout, hook.name)
                if mutation is not None:
                    enriched["arguments"] = mutation
                    result = dataclasses.replace(result, mutated_arguments=mutation)
            results.append(result)
            if self._listener is not None:
                try:
                    self._listener(result)
                except Exception:
                    log.debug("HookRunner listener raised", exc_info=True)
        return results

    async def _run_one(self, hook: HookConfig, stdin_bytes: bytes) -> HookResult:
        """Execute a single hook and return its :class:`HookResult`."""
        started = datetime.datetime.now()
        try:
            proc = await asyncio.create_subprocess_shell(
                hook.run,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            log.warning("Hook %r failed to spawn: %s", hook.name, exc)
            return HookResult(
                name=hook.name,
                event=hook.event,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                duration_seconds=0.0,
                timed_out=False,
                continue_on_error=hook.continue_on_error,
            )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes), timeout=hook.timeout
            )
        except TimeoutError:
            timed_out = True
            proc.kill()
            try:
                stdout_bytes, stderr_bytes = await proc.communicate()
            except (OSError, asyncio.CancelledError):
                stdout_bytes, stderr_bytes = b"", b""

        duration = (datetime.datetime.now() - started).total_seconds()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if timed_out:
            level = logging.INFO if hook.continue_on_error else logging.WARNING
            log.log(
                level,
                "Hook %r (%s) timed out after %.1fs",
                hook.name,
                hook.event.value,
                hook.timeout,
            )
            return HookResult(
                name=hook.name,
                event=hook.event,
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                timed_out=True,
                continue_on_error=hook.continue_on_error,
            )

        exit_code = proc.returncode
        if exit_code != 0:
            level = logging.DEBUG if hook.continue_on_error else logging.WARNING
            log.log(
                level,
                "Hook %r (%s) exited %s (stderr: %s)",
                hook.name,
                hook.event.value,
                exit_code,
                stderr.strip()[:200],
            )
        return HookResult(
            name=hook.name,
            event=hook.event,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            continue_on_error=hook.continue_on_error,
        )
