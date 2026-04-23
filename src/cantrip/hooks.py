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
      - name: log-git-push
        event: pre_tool_call
        if: tool == "git_push"
        run: logger -t cantrip "pushing $(jq -r .arguments.branch)"
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
* ``if`` (string, optional) — a boolean expression evaluated against
  the event payload before the hook runs; the hook fires only when
  the expression is truthy.  Supports comparisons (``==``, ``!=``,
  ``<``, ``<=``, ``>``, ``>=``, ``in``, ``not in``), boolean
  combinators (``and`` / ``or`` / ``not``), nested field access
  (``task.category``, ``arguments.branch``), and string / number /
  list literals.  Missing payload fields evaluate to a sentinel so
  a filter that references an absent field simply skips the hook
  rather than raising.  Python function calls, imports, lambdas
  etc. are rejected at config-load time.
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

import ast
import asyncio
import dataclasses
import datetime
import enum
import json
import logging
import os
import pathlib
import typing
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

    ``if_expr`` is the compiled form of the optional ``if:`` YAML key —
    a boolean expression evaluated against the event payload before
    the hook runs.  When ``None`` the hook always fires for its event.
    """

    name: str
    event: HookEvent
    run: str
    timeout: float = DEFAULT_HOOK_TIMEOUT
    continue_on_error: bool = True
    if_expr: _FilterExpr | None = None


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
    continue_on_error: bool = True

    @property
    def succeeded(self) -> bool:
        """True when the hook exited cleanly (zero, and didn't time out)."""
        return not self.timed_out and self.exit_code == 0

    @property
    def vetoed(self) -> bool:
        """Whether this result vetoes the pending operation.

        A ``pre_*`` hook vetoes when it failed *and* its config asked
        Cantrip to treat failures as authoritative rather than
        informational (``continue_on_error: false``).  ``post_*`` hooks
        never veto — the operation has already completed — but the
        property is still correct for them (it just has no effect on
        the caller, which doesn't check ``vetoed`` on post events).
        """
        return not self.continue_on_error and not self.succeeded

    @property
    def veto_reason(self) -> str:
        """One-line human-readable explanation of a veto.

        Falls back to a stderr-free message if the hook was silent so
        users aren't shown an empty reason string.  Used in error
        surfacing when ``vetoed`` is True.
        """
        if self.timed_out:
            return f"hook {self.name!r} timed out after {self.duration_seconds:.1f}s"
        stderr = self.stderr.strip().splitlines()
        detail = stderr[-1] if stderr else f"exit {self.exit_code}"
        return f"hook {self.name!r}: {detail}"


def first_veto(results: list[HookResult]) -> HookResult | None:
    """Return the first vetoing hook result, or None when nothing blocks.

    Convenience helper for agent call sites that fire ``pre_*`` events
    and need to decide whether to proceed with the pending operation.
    """
    for result in results:
        if result.vetoed:
            return result
    return None


# Sentinel returned by the filter evaluator when a payload field is
# missing.  Compared with ``==`` / ``in`` it yields ``False``, so a
# filter like ``task.category == "BUILD"`` against a payload without a
# ``task`` field simply skips the hook rather than raising — far more
# useful when events have heterogeneous payloads.
class _Missing:
    """Truthy-false sentinel for absent payload fields."""

    __slots__ = ()
    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return other is self

    def __ne__(self, other: object) -> bool:
        return other is not self

    def __contains__(self, _: object) -> bool:
        return False

    def __iter__(self):
        return iter(())

    def __getattr__(self, _name: str) -> _Missing:
        return self

    def __getitem__(self, _key: object) -> _Missing:
        return self

    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()


# AST node types allowed in ``if:`` expressions.  Function calls,
# lambdas, comprehensions, etc. are rejected at compile time — the
# expression language is intentionally small so a misconfigured hook
# can't shell out, read files, or loop.
_ALLOWED_AST_NODES = frozenset(
    {
        ast.Expression,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Attribute,
        ast.Subscript,
        ast.List,
        ast.Tuple,
    }
)


class _FilterExpr:
    """Compiled ``if:`` filter evaluated against an event payload.

    Stores the original source for diagnostics plus the pre-parsed AST
    so ``matches()`` is fast on the hot path.  All validation happens
    at compile time — bad expressions fail in ``_parse_hook`` with a
    clear error that points at the config line, not at fire-time when
    the operator is already waiting on a tool call.
    """

    __slots__ = ("source", "_tree")

    def __init__(self, source: str):
        self.source = source
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as exc:
            raise HookConfigError(f"invalid `if:` expression {source!r}: {exc.msg}") from exc
        _validate_ast(tree, source)
        self._tree = tree

    def matches(self, payload: dict[str, Any]) -> bool:
        """Return True when the filter accepts *payload*.

        Evaluation failures (missing keys, comparison-to-missing,
        unsupported operand types) resolve to False so a filter that
        references a key an event doesn't carry simply skips the hook
        rather than raising.
        """
        try:
            value = _eval_node(self._tree.body, payload)
        except (KeyError, AttributeError, TypeError):
            return False
        return bool(value) and value is not _MISSING


def _validate_ast(tree: ast.AST, source: str) -> None:
    """Walk *tree* and reject any node type outside the allowlist."""
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_AST_NODES:
            raise HookConfigError(
                f"disallowed expression element in `if:` {source!r}: {type(node).__name__}"
            )


def _eval_node(node: ast.AST, payload: dict[str, Any]) -> Any:
    """Recursively evaluate a validated AST node against *payload*.

    Only called on trees that survived ``_validate_ast``, so the match
    is exhaustive for the allowed node set — any unexpected type here
    is a validator bug, not a user input.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return payload.get(node.id, _MISSING)
    if isinstance(node, ast.Attribute):
        parent = _eval_node(node.value, payload)
        if isinstance(parent, dict):
            return parent.get(node.attr, _MISSING)
        if parent is _MISSING:
            return _MISSING
        return getattr(parent, node.attr, _MISSING)
    if isinstance(node, ast.Subscript):
        parent = _eval_node(node.value, payload)
        key = _eval_node(node.slice, payload)
        if parent is _MISSING or key is _MISSING:
            return _MISSING
        try:
            return parent[key]
        except (KeyError, IndexError, TypeError):
            return _MISSING
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, payload)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v, payload) for v in node.values)
        return any(_eval_node(v, payload) for v in node.values)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, payload)
        for op, right_node in zip(node.ops, node.comparators, strict=True):
            right = _eval_node(right_node, payload)
            if not _apply_comparison(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(elt, payload) for elt in node.elts]
    raise TypeError(f"unevaluatable node: {type(node).__name__}")


def _apply_comparison(op: ast.cmpop, left: Any, right: Any) -> bool:
    """Apply one comparison operator with missing-safe semantics."""
    if left is _MISSING or right is _MISSING:
        # Eq / NotEq against a missing sentinel compare correctly; all
        # other comparisons against missing are False so ordering ops
        # don't raise TypeError on ``None``.
        if isinstance(op, ast.Eq):
            return left is right
        if isinstance(op, ast.NotEq):
            return left is not right
        if isinstance(op, (ast.In, ast.NotIn)):
            return isinstance(op, ast.NotIn)
        return False
    try:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.In):
            return left in right
        if isinstance(op, ast.NotIn):
            return left not in right
    except TypeError:
        return False
    return False


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

    if_raw = spec.get("if")
    if_expr: _FilterExpr | None = None
    if if_raw is not None:
        if not isinstance(if_raw, str) or not if_raw.strip():
            raise HookConfigError(
                f"hook {name!r} in {path}: `if` must be a non-empty string when set"
            )
        try:
            if_expr = _FilterExpr(if_raw.strip())
        except HookConfigError as exc:
            # Re-raise with the hook's name + path prefixed so the
            # operator can find the broken entry without scanning the
            # whole file.
            raise HookConfigError(f"hook {name!r} in {path}: {exc}") from exc

    return HookConfig(
        name=name,
        event=event,
        run=run_raw.strip(),
        timeout=float(timeout_raw),
        continue_on_error=continue_raw,
        if_expr=if_expr,
    )


# Callback signature for ``HookRunner`` telemetry — the agent hooks
# this to route every execution through ``HookStats`` and the session
# store's transcript events.  Invoked after the subprocess completes
# (so ``duration_seconds`` is final) and only for hooks that actually
# ran — skipped hooks (by ``if:`` filter) don't feed the callback
# because they'd just noise up the stats.
HookResultListener = typing.Callable[[HookResult], None]


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

    def __init__(self, hooks: list[HookConfig] | None = None):
        """Build a runner for *hooks* (defaults to no hooks)."""
        self._by_event: dict[HookEvent, list[HookConfig]] = {}
        for hook in hooks or []:
            self._by_event.setdefault(hook.event, []).append(hook)
        self._listener: HookResultListener | None = None

    @classmethod
    def from_disk(cls, repo_root: pathlib.Path | str | None = None) -> HookRunner:
        """Convenience constructor that loads ``hooks.yaml`` from disk."""
        return cls(load_hooks(repo_root=repo_root))

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
        stdin_bytes = json.dumps(enriched, default=str).encode("utf-8")

        results: list[HookResult] = []
        for hook in hooks:
            # ``if:`` filters are evaluated against the enriched
            # payload so ``event`` and ``timestamp`` are available
            # even though the caller didn't pass them.
            if hook.if_expr is not None and not hook.if_expr.matches(enriched):
                log.debug(
                    "Hook %r (%s) skipped by if-filter %r",
                    hook.name,
                    hook.event.value,
                    hook.if_expr.source,
                )
                continue
            result = await self._run_one(hook, stdin_bytes)
            results.append(result)
            if self._listener is not None:
                try:
                    self._listener(result)
                except Exception:
                    # Telemetry failure must never abort the agent.
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


__all__ = [
    "DEFAULT_HOOK_TIMEOUT",
    "REPO_CONFIG_FILENAME",
    "USER_CONFIG_PATH",
    "HookConfig",
    "HookConfigError",
    "HookEvent",
    "HookResult",
    "HookResultListener",
    "HookRunner",
    "HookStats",
    "first_veto",
    "load_hooks",
]
