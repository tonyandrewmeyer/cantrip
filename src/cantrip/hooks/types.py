"""Public datatypes for user hooks (Phase 46.1+).

Light enough to import without dragging in YAML, asyncio, or the AST
filter machinery — call sites that just need to type-annotate a
``HookEvent`` argument should land here.
"""

from __future__ import annotations

import dataclasses
import enum
import pathlib
import typing
from typing import Any

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
    if_expr: Any = None  # filter._FilterExpr | None — annotated as Any to keep this module light.


@dataclasses.dataclass(frozen=True)
class HookResult:
    """Outcome of one hook invocation.  Used for logs and transcript events.

    ``mutated_arguments`` captures a ``pre_tool_call`` hook's successful
    request to rewrite the tool arguments (see the runner module for
    the envelope spec).  It holds the composed state as of *after* this
    hook ran — because the runner threads each hook's mutation into the
    next hook's stdin, the final value in a chain is the ``arguments``
    dict that will actually be passed to the tool.  ``None`` when the
    hook did not emit a mutation envelope, or for any event other than
    ``pre_tool_call``.
    """

    name: str
    event: HookEvent
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    continue_on_error: bool = True
    mutated_arguments: dict[str, Any] | None = None

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


def final_arguments(results: list[HookResult]) -> dict[str, Any] | None:
    """Return the composed tool arguments after a ``pre_tool_call`` chain.

    Walks *results* in reverse and returns the first hook's
    ``mutated_arguments``.  Because the runner threads each hook's
    mutation into the next hook's stdin, the last non-``None`` entry
    carries the final composed state — earlier hooks' edits have
    already been folded into it.

    Returns ``None`` when no hook requested a mutation; callers
    typically pair this with ``or`` to fall back to the original
    arguments::

        effective = final_arguments(pre_results) or tc.arguments
    """
    for result in reversed(results):
        if result.mutated_arguments is not None:
            return result.mutated_arguments
    return None


# Callback signature for ``HookRunner`` telemetry — the agent hooks
# this to route every execution through ``HookStats`` and the session
# store's transcript events.  Invoked after the subprocess completes
# (so ``duration_seconds`` is final) and only for hooks that actually
# ran — skipped hooks (by ``if:`` filter) don't feed the callback
# because they'd just noise up the stats.
HookResultListener = typing.Callable[[HookResult], None]
