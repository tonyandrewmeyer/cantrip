"""User-configurable hooks (Phase 46.1 + 46.2).

Users can declare small scripts in ``~/.config/cantrip/hooks.yaml``
(user scope) or ``./cantrip.hooks.yaml`` (repo scope) that run at
lifecycle points — before/after every tool call, before/after
compaction, around subagent invocations.  Hooks run as subprocesses
with a JSON payload on stdin so they can observe (and eventually
influence) agent behaviour without forking Cantrip.

The config pair mirrors the MCP config convention
(``cantrip.mcp.yaml``) so users don't have to learn two layouts.

Schema
------

.. code-block:: yaml

    hooks:
      - name: log-tool-calls
        event: pre_tool_call
        run: bash -c 'jq -r .tool >> /tmp/cantrip-tools.log'
        timeout: 5
        continue_on_error: true

Each hook declares:

* ``name`` (string, optional) — a label used in logs and the future
  ``/hooks`` slash command.  Defaults to the first word of ``run``.
* ``event`` (string, required) — one of the :class:`HookEvent` values.
  (Deliberately not called ``on`` — unquoted ``on:`` in YAML 1.1
  parses as a boolean ``True`` key, which would silently break
  user configs.)
* ``run`` (string, required) — the command line to invoke.  Passed to
  ``/bin/sh -c`` so shell features (pipes, redirection, env-var
  expansion) work out of the box.
* ``timeout`` (number, optional) — seconds before the hook is killed.
  Defaults to 30 s — long enough for a ``curl`` or a ``jq`` pipeline,
  short enough that a misbehaving hook can't freeze the agent.
* ``continue_on_error`` (bool, optional, default ``true``) — when
  ``false``, a hook that exits non-zero logs at ``WARNING`` rather
  than ``DEBUG``.  (True veto semantics — where a pre-hook refuses
  the operation — land in Phase 46.4.)

Repo scope overrides user scope on name collision: a ``.yaml`` in
the charm directory is authoritative for the charm, and the user
config acts as a fallback for every charm the user works on.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import enum
import json
import logging
import os
import pathlib
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Default timeout for a single hook invocation.  Tuned to a value that
# is generous enough for a small shell pipeline (``jq``, ``curl``) but
# short enough that a hung hook fails fast rather than wedging the
# whole agent.
DEFAULT_HOOK_TIMEOUT = 30.0

USER_CONFIG_PATH = pathlib.Path("~/.config/cantrip/hooks.yaml")
REPO_CONFIG_FILENAME = "cantrip.hooks.yaml"


class HookConfigError(Exception):
    """Raised when a ``hooks.yaml`` file cannot be parsed."""


class HookEvent(enum.StrEnum):
    """Lifecycle events Cantrip exposes to user hooks.

    Not every event is wired up in 46.1/46.2 — ``pre_pack``,
    ``pre_push``, ``pre_pr``, ``on_task_complete``, and
    ``on_session_end`` are reserved so users can write hooks targeting
    them today and later sub-phases flip the switch in the agent
    without breaking configs.
    """

    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_SUBAGENT = "pre_subagent"
    POST_SUBAGENT = "post_subagent"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    PRE_PACK = "pre_pack"
    PRE_PUSH = "pre_push"
    PRE_PR = "pre_pr"
    ON_TASK_COMPLETE = "on_task_complete"
    ON_SESSION_END = "on_session_end"


@dataclasses.dataclass(frozen=True)
class HookConfig:
    """A single hook declaration parsed from ``hooks.yaml``.

    The ``event`` field is named ``event`` (not ``on``) both here and
    in the YAML schema to avoid the YAML 1.1 ``on: true`` trap.
    """

    name: str
    event: HookEvent
    run: str
    timeout: float = DEFAULT_HOOK_TIMEOUT
    continue_on_error: bool = True


@dataclasses.dataclass(frozen=True)
class HookResult:
    """Outcome of one hook invocation.  Used for logs and transcript events."""

    name: str
    event: HookEvent
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


def _user_config_path() -> pathlib.Path | None:
    """Resolve the user-scope hooks file, honouring the env override."""
    override = os.environ.get("CANTRIP_HOOKS_USER_CONFIG")
    if override:
        return pathlib.Path(override).expanduser()
    return USER_CONFIG_PATH.expanduser()


def _candidate_paths(repo_root: pathlib.Path | str | None) -> list[pathlib.Path]:
    """Return the user- then repo-scope config paths in load order.

    Repo is loaded after user so a repo-level ``name`` collision
    overrides the user-level hook of the same name — matching the
    MCP config semantics.  ``repo_root`` is coerced to ``pathlib.Path``
    so callers can pass either a ``Path`` or a ``str`` — the CLI and
    TUI pass ``charm_path`` through verbatim and users provide it as
    either type.
    """
    user = _user_config_path()
    paths: list[pathlib.Path] = [user] if user else []
    if repo_root is not None:
        paths.append(pathlib.Path(repo_root) / REPO_CONFIG_FILENAME)
    return paths


def load_hooks(repo_root: pathlib.Path | str | None = None) -> list[HookConfig]:
    """Discover and merge hooks from the user + repo scope YAML files.

    Returns a deterministic list (user hooks first in declaration
    order, repo hooks after, name collisions resolved in favour of the
    repo declaration).  Missing files are not errors; malformed files
    log a warning and contribute nothing so a broken user config can't
    take down the agent.
    """
    by_name: dict[str, HookConfig] = {}
    for source in _candidate_paths(repo_root):
        if not source.is_file():
            continue
        try:
            entries = _parse_yaml(source)
        except HookConfigError as exc:
            log.warning("Ignoring malformed hooks config at %s: %s", source, exc)
            continue
        for hook in entries:
            by_name[hook.name] = hook
    return list(by_name.values())


def _parse_yaml(path: pathlib.Path) -> list[HookConfig]:
    """Parse one hooks YAML file into :class:`HookConfig` instances."""
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise HookConfigError(f"could not parse {path}: {exc}") from exc
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise HookConfigError(
            f"top-level value in {path} must be a mapping, got {type(raw).__name__}"
        )
    hooks_block = raw.get("hooks")
    if hooks_block is None:
        return []
    if not isinstance(hooks_block, list):
        raise HookConfigError(
            f"`hooks` in {path} must be a list, got {type(hooks_block).__name__}"
        )
    out: list[HookConfig] = []
    for index, spec in enumerate(hooks_block):
        if not isinstance(spec, dict):
            raise HookConfigError(
                f"hook #{index} in {path} must be a mapping, got {type(spec).__name__}"
            )
        out.append(_parse_hook(spec, path, index))
    return out


def _parse_hook(spec: dict[str, Any], path: pathlib.Path, index: int) -> HookConfig:
    """Validate one hook spec.  Raises :class:`HookConfigError` on bad input."""
    event_raw = spec.get("event")
    if not isinstance(event_raw, str) or not event_raw.strip():
        raise HookConfigError(f"hook #{index} in {path}: `event` must be a non-empty string")
    try:
        event = HookEvent(event_raw.strip())
    except ValueError as exc:
        valid = ", ".join(sorted(e.value for e in HookEvent))
        raise HookConfigError(
            f"hook #{index} in {path}: unknown event {event_raw!r} (expected one of: {valid})"
        ) from exc

    run_raw = spec.get("run")
    if not isinstance(run_raw, str) or not run_raw.strip():
        raise HookConfigError(f"hook #{index} in {path}: `run` must be a non-empty string")

    name_raw = spec.get("name")
    if name_raw is None:
        # Default the hook name to the first shell word of ``run`` so
        # logs are readable without forcing every user to write a
        # ``name:`` line.
        name = run_raw.strip().split()[0] or f"hook-{index}"
    elif not isinstance(name_raw, str) or not name_raw.strip():
        raise HookConfigError(
            f"hook #{index} in {path}: `name` must be a non-empty string when set"
        )
    else:
        name = name_raw.strip()

    timeout_raw = spec.get("timeout", DEFAULT_HOOK_TIMEOUT)
    if isinstance(timeout_raw, bool) or not isinstance(timeout_raw, (int, float)):
        raise HookConfigError(f"hook {name!r} in {path}: `timeout` must be a number")
    if timeout_raw <= 0:
        raise HookConfigError(f"hook {name!r} in {path}: `timeout` must be positive")

    continue_raw = spec.get("continue_on_error", True)
    if not isinstance(continue_raw, bool):
        raise HookConfigError(
            f"hook {name!r} in {path}: `continue_on_error` must be true or false"
        )

    return HookConfig(
        name=name,
        event=event,
        run=run_raw.strip(),
        timeout=float(timeout_raw),
        continue_on_error=continue_raw,
    )


class HookRunner:
    """Dispatches events to configured hooks.

    The runner keeps a pre-bucketed event → hooks map so ``fire()`` is
    O(1) in the number of hooks for the non-matching events — a hot
    path since ``pre_tool_call`` / ``post_tool_call`` fire on every
    tool invocation.
    """

    def __init__(self, hooks: list[HookConfig] | None = None):
        """Build a runner for *hooks* (defaults to no hooks)."""
        self._by_event: dict[HookEvent, list[HookConfig]] = {}
        for hook in hooks or []:
            self._by_event.setdefault(hook.event, []).append(hook)

    @classmethod
    def from_disk(cls, repo_root: pathlib.Path | str | None = None) -> HookRunner:
        """Convenience constructor that loads ``hooks.yaml`` from disk."""
        return cls(load_hooks(repo_root=repo_root))

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
        stdin_bytes = json.dumps(enriched, default=str).encode("utf-8")

        results: list[HookResult] = []
        for hook in hooks:
            result = await self._run_one(hook, stdin_bytes)
            results.append(result)
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
        )


__all__ = [
    "DEFAULT_HOOK_TIMEOUT",
    "REPO_CONFIG_FILENAME",
    "USER_CONFIG_PATH",
    "HookConfig",
    "HookConfigError",
    "HookEvent",
    "HookResult",
    "HookRunner",
    "load_hooks",
]
