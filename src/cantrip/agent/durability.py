"""Step-level durable-execution checkpoints (Phase 52).

A subagent task that rate-limits on LLM turn 18 shouldn't restart
from turn 1 on the next run.  This module exposes a small facade over
:class:`~cantrip.agent.store.SessionStore` for recording each
expensive step — LLM calls and tool invocations — so the replay path
in Phase 52.3's subagent wiring can resume from the last completed
checkpoint.

The module is layered:

- 52.1 — :class:`CheckpointStore` handles the JSON envelope with a
  raw-bytes escape hatch, ordinal allocation, and task-scoped GC.
- 52.2 — :class:`CheckpointCtx` + :func:`checkpoint` are the replay
  wrapper around arbitrary async work.
- 52.3 — :func:`response_to_dict` / :func:`response_from_dict` and
  :func:`tool_result_to_dict` / :func:`tool_result_from_dict`
  serialise the concrete ``llm.Response`` and
  ``agent.tools.base.ToolResult`` dataclasses into the JSON envelope
  so the subagent loop's per-turn and per-tool checkpoints round-
  trip losslessly across process restarts.

Inspired by Armin Ronacher's *Absurd* (Postgres-backed durable
execution) — the single-process SQLite flavour.  No queue, no
worker, no ``SKIP LOCKED``.  One charm, one ``.cantrip``, per-step
resume.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from cantrip.agent.tools.base import ToolResult
from cantrip.llm import base as llm

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from cantrip.agent.store import SessionStore

log = logging.getLogger(__name__)


# ``CANTRIP_KEEP_CHECKPOINTS=1`` preserves checkpoints for debugging
# stale-cache behaviour; otherwise successful task completion purges
# them.  Any truthy-ish value (``1``, ``true``, ``yes``) turns it on.
KEEP_CHECKPOINTS_ENV = "CANTRIP_KEEP_CHECKPOINTS"

# ``CANTRIP_NO_RESUME=1`` disables checkpoint replay for the next
# subagent run.  Useful when hunting a bug that might itself be
# cached in a stale row — the subagent re-executes every step live
# instead of reading from the store.  Fresh results *are* still
# persisted; only lookups are bypassed.  (To also stop writes, pair
# with ``CANTRIP_KEEP_CHECKPOINTS`` not being set so the automatic
# GC on task completion sweeps the rows anyway.)
NO_RESUME_ENV = "CANTRIP_NO_RESUME"

# Kinds carried on every stored record.  ``llm_response`` and
# ``tool_result`` are the two 52.3 will populate; ``value`` is a
# catch-all for arbitrary JSON the 52.2 wrapper might want to cache
# (e.g. an early planning decision).  ``bytes`` marks a record that
# should bypass JSON decode on read — used when the caller pre-
# serialised via msgpack or similar.
KIND_LLM_RESPONSE = "llm_response"
KIND_TOOL_RESULT = "tool_result"
KIND_VALUE = "value"
KIND_BYTES = "bytes"


_TRUTHY = frozenset({"1", "true", "yes", "on"})


def should_keep_checkpoints() -> bool:
    """Return True when the debug-mode env var requests retention.

    A truthy ``CANTRIP_KEEP_CHECKPOINTS`` makes :meth:`CheckpointStore.
    on_task_done` a no-op so a session can be inspected with
    ``SELECT * FROM step_checkpoints`` after the fact — useful when
    hunting a bug that might be cached in a stale checkpoint.
    """
    return os.environ.get(KEEP_CHECKPOINTS_ENV, "").strip().lower() in _TRUTHY


def should_skip_resume() -> bool:
    """Return True when ``$CANTRIP_NO_RESUME`` requests a live re-run.

    Checked by the subagent at start-of-run: when set, the
    :class:`CheckpointCtx` is not constructed, so every LLM turn and
    every tool call runs live instead of consulting stored rows.
    Fresh results can still be written — only the *lookup* is
    bypassed.  Intended for debugging a run where a stale checkpoint
    is suspected of masking a fix.
    """
    return os.environ.get(NO_RESUME_ENV, "").strip().lower() in _TRUTHY


def compute_input_hash(*parts: object) -> str:
    """Return a stable SHA-256 hex digest over canonicalised *parts*.

    Each part is JSON-encoded with sorted keys, then concatenated with
    a NUL separator before hashing — so callers can pass mixed
    primitives, lists, and dicts without worrying about dict-key
    ordering.  Objects that aren't JSON-native fall back to
    ``repr()``; the digest stays deterministic per Python version.
    """
    parts_bytes = b"\x00".join(_canonicalise(part) for part in parts)
    return hashlib.sha256(parts_bytes).hexdigest()


def _canonicalise(value: object) -> bytes:
    """Deterministically encode *value* for :func:`compute_input_hash`."""
    try:
        return json.dumps(value, sort_keys=True, default=repr).encode("utf-8")
    except (TypeError, ValueError):
        return repr(value).encode("utf-8")


@dataclass(frozen=True)
class CheckpointRecord:
    """Typed wrapper over a ``step_checkpoints`` row.

    The raw SQLite row returned by
    :meth:`SessionStore.get_checkpoint` is a bag of columns; this
    dataclass makes downstream replay code more legible and gives the
    encode / decode boundary a single concrete type.
    """

    task_id: str
    step_name: str
    ordinal: int
    input_hash: str
    kind: str
    blob: bytes
    created_at: str

    def decode(self) -> object:
        """Return the stored value with kind-appropriate decoding.

        JSON-encoded kinds (``llm_response`` / ``tool_result`` /
        ``value``) return the decoded object; ``bytes`` returns the
        raw blob so callers that serialised via msgpack or similar
        can handle decoding themselves.  Malformed JSON raises so a
        corrupt checkpoint surfaces loudly rather than silently
        producing ``None``.
        """
        if self.kind == KIND_BYTES:
            return self.blob
        return json.loads(self.blob.decode("utf-8"))


class CheckpointStore:
    """Facade over :class:`SessionStore` for per-step checkpointing.

    Holds no state of its own — every method delegates to the
    session store.  Exposed as a separate class (matching the
    Phase 52.1 roadmap naming) so the replay wrapper landing in
    Phase 52.2 can depend on a stable surface while
    ``SessionStore``'s own API evolves.
    """

    def __init__(self, session_store: SessionStore) -> None:
        self._store = session_store

    def record(
        self,
        task_id: str,
        step_name: str,
        ordinal: int,
        input_hash: str,
        kind: str,
        value: object,
    ) -> None:
        """Persist one step result.

        The value is serialised according to ``kind``:

        - ``KIND_BYTES`` — ``value`` must be ``bytes``; stored
          verbatim.  Escape hatch for msgpack / pickle / protobuf.
        - everything else — ``value`` is JSON-encoded (UTF-8).  A
          :class:`TypeError` on non-serialisable values surfaces
          loudly so a stale caller sees the problem at record time,
          not later at decode time.
        """
        if kind == KIND_BYTES:
            if not isinstance(value, bytes | bytearray):
                raise TypeError(f"kind={kind!r} requires bytes; got {type(value).__name__}")
            blob = bytes(value)
        else:
            blob = json.dumps(value, sort_keys=True, default=_json_default).encode("utf-8")
        self._store.record_checkpoint(
            task_id=task_id,
            step_name=step_name,
            ordinal=ordinal,
            input_hash=input_hash,
            result_kind=kind,
            result_blob=blob,
        )
        log.debug(
            "recorded checkpoint task=%s step=%s#%d kind=%s bytes=%d",
            task_id,
            step_name,
            ordinal,
            kind,
            len(blob),
        )

    def get(self, task_id: str, step_name: str, ordinal: int) -> CheckpointRecord | None:
        """Return the checkpoint for a ``(task, step, ordinal)`` triple, or ``None``.

        The caller is responsible for the input-hash check — 52.2
        wraps this with invalidation semantics; 52.1 just round-
        trips the row.
        """
        row = self._store.get_checkpoint(task_id, step_name, ordinal)
        if row is None:
            return None
        return CheckpointRecord(
            task_id=row["task_id"],
            step_name=row["step_name"],
            ordinal=int(row["ordinal"]),
            input_hash=row["input_hash"],
            kind=row["result_kind"],
            blob=bytes(row["result_blob"]),
            created_at=row["created_at"],
        )

    def next_ordinal(self, task_id: str, step_name: str) -> int:
        """Return the next unused ordinal for a ``(task_id, step_name)`` pair."""
        return self._store.next_checkpoint_ordinal(task_id, step_name)

    def list_for_task(self, task_id: str) -> list[CheckpointRecord]:
        """Return every recorded checkpoint for *task_id* in insertion order."""
        return [
            CheckpointRecord(
                task_id=row["task_id"],
                step_name=row["step_name"],
                ordinal=int(row["ordinal"]),
                input_hash=row["input_hash"],
                kind=row["result_kind"],
                blob=bytes(row["result_blob"]),
                created_at=row["created_at"],
            )
            for row in self._store.list_checkpoints_for_task(task_id)
        ]

    def count_for_task(self, task_id: str) -> int:
        """Return the number of checkpoints stored for *task_id*."""
        return self._store.count_checkpoints_for_task(task_id)

    def record_event(self, event_type: str, detail: dict[str, object]) -> None:
        """Forward a structured event to the session store's event log.

        Used by :func:`checkpoint` to emit ``checkpoint_hit`` /
        ``checkpoint_miss`` / ``checkpoint_invalidated`` events so
        Phase 52.5's transcript tab and watcher dashboards can plot
        replay efficiency over a session without extra plumbing.
        """
        self._store.record_event(event_type, detail)

    def purge_task(self, task_id: str) -> int:
        """Delete every checkpoint for *task_id*.  Returns the row count removed.

        Callers typically go through :meth:`on_task_done` so the
        ``CANTRIP_KEEP_CHECKPOINTS`` opt-out is honoured; direct
        invocation bypasses the env-var check and is intended for
        ``cantrip checkpoints delete`` (Phase 52.5) and test
        teardown.
        """
        return self._store.purge_checkpoints_for_task(task_id)

    def on_task_done(self, task_id: str) -> None:
        """Purge checkpoints for a task that has reached the DONE state.

        Honours the ``CANTRIP_KEEP_CHECKPOINTS`` env var — when set,
        nothing is deleted so the session can be inspected after the
        fact.  Intended to be wired into
        :class:`BackgroundExecutor.on_task_done` via
        ``CantripAgent.start_executor``.
        """
        if should_keep_checkpoints():
            remaining = self._store.count_checkpoints_for_task(task_id)
            if remaining:
                log.debug(
                    "retaining %d checkpoint(s) for task %s ($%s set)",
                    remaining,
                    task_id,
                    KEEP_CHECKPOINTS_ENV,
                )
            return
        removed = self.purge_task(task_id)
        if removed:
            log.debug("purged %d checkpoint(s) for completed task %s", removed, task_id)


@dataclass
class CheckpointCtx:
    """Per-task context for :func:`checkpoint` — ordinal bookkeeping + store handle.

    Constructed once per subagent task.  The per-step counter
    (``_counters``) is a pure in-memory monotonic sequence so repeated
    calls to ``checkpoint(ctx, "llm_turn", …)`` auto-number without
    the caller tracking indices.  On replay the counter starts fresh:
    deterministic call ordering in the subagent loop means the same
    ``(step_name, ordinal)`` pairs line up with the persisted rows.
    """

    store: CheckpointStore
    task_id: str
    _counters: dict[str, int] = field(default_factory=dict)

    def next_ordinal(self, step_name: str) -> int:
        """Increment and return the per-step counter for *step_name*.

        Starts at ``1`` on first call.  Each step name has its own
        counter: ``llm_turn`` and ``tool:juju_status`` don't interfere.
        """
        current = self._counters.get(step_name, 0) + 1
        self._counters[step_name] = current
        return current


async def checkpoint[T](
    ctx: CheckpointCtx,
    step_name: str,
    fn: Callable[[], Awaitable[T]],
    *,
    input_hash: str | None = None,
    kind: str = KIND_VALUE,
) -> T:
    """Run *fn* once per ``(task, step_name, ordinal)``; replay on re-entry.

    Semantics mirror Armin Ronacher's *Absurd* ``ctx.step``:

    1. Allocate the next ordinal for this ``(task_id, step_name)``
       from the ctx counter.
    2. Look up the persisted checkpoint.  If present and the stored
       input hash matches (or the caller passed no hash), return the
       decoded value without running *fn*.
    3. On hash mismatch, log a warning and fall through to re-run —
       ``INSERT OR REPLACE`` semantics overwrite the stale row.
    4. On miss, ``await fn()`` and persist the result before
       returning it.

    *input_hash* is optional but strongly recommended in 52.3 wiring
    so code changes between runs force a re-execution rather than
    silently serving stale results.  When omitted, an empty string is
    stored — compatible with future calls that start providing one
    (they'll mismatch and invalidate).

    *kind* selects the storage envelope.  ``KIND_VALUE`` (default)
    and ``KIND_LLM_RESPONSE`` / ``KIND_TOOL_RESULT`` are JSON-encoded;
    ``KIND_BYTES`` stores raw bytes verbatim (caller must return
    ``bytes``).
    """
    ordinal = ctx.next_ordinal(step_name)
    record = ctx.store.get(ctx.task_id, step_name, ordinal)
    if record is not None:
        if input_hash is None or record.input_hash == input_hash:
            log.debug(
                "checkpoint hit: task=%s step=%s#%d kind=%s",
                ctx.task_id,
                step_name,
                ordinal,
                record.kind,
            )
            ctx.store.record_event(
                "checkpoint_hit",
                {
                    "task_id": ctx.task_id,
                    "step_name": step_name,
                    "ordinal": ordinal,
                    "kind": record.kind,
                },
            )
            return cast("T", record.decode())
        log.warning(
            "checkpoint input-hash mismatch — invalidating task=%s step=%s#%d "
            "(stored=%s current=%s)",
            ctx.task_id,
            step_name,
            ordinal,
            record.input_hash,
            input_hash,
        )
        ctx.store.record_event(
            "checkpoint_invalidated",
            {
                "task_id": ctx.task_id,
                "step_name": step_name,
                "ordinal": ordinal,
                "stored_hash": record.input_hash,
                "current_hash": input_hash,
            },
        )
    result = await fn()
    ctx.store.record(
        task_id=ctx.task_id,
        step_name=step_name,
        ordinal=ordinal,
        input_hash=input_hash or "",
        kind=kind,
        value=result,
    )
    log.debug(
        "checkpoint miss: task=%s step=%s#%d kind=%s (ran fn, persisted)",
        ctx.task_id,
        step_name,
        ordinal,
        kind,
    )
    ctx.store.record_event(
        "checkpoint_miss",
        {
            "task_id": ctx.task_id,
            "step_name": step_name,
            "ordinal": ordinal,
            "kind": kind,
        },
    )
    return result


# ---------------------------------------------------------------------------
# 52.3 — concrete serialisers for LLM responses and tool results
# ---------------------------------------------------------------------------


def _encode_image(img: llm.Image) -> dict[str, str]:
    """Base64-encode an image so it round-trips through JSON."""
    return {"data_b64": base64.b64encode(img.data).decode("ascii"), "mime": img.mime}


def _decode_image(payload: dict[str, str]) -> llm.Image:
    return llm.Image(
        data=base64.b64decode(payload["data_b64"].encode("ascii")),
        mime=payload["mime"],
    )


def response_to_dict(response: llm.Response) -> dict[str, Any]:
    """Serialise an :class:`llm.Response` into a JSON-compatible dict.

    Tool calls carry arbitrary JSON argument payloads the model
    produced; ``metadata`` and ``usage`` are plain dicts of primitives
    already.  The envelope keeps nothing the caller didn't give us —
    there's no hidden state in ``Response`` to recover.
    """
    return {
        "content": response.content,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls
        ],
        "finish_reason": response.finish_reason,
        "usage": dict(response.usage),
        "metadata": dict(response.metadata),
    }


def response_from_dict(data: dict[str, Any]) -> llm.Response:
    """Reconstruct an :class:`llm.Response` from :func:`response_to_dict`'s output."""
    return llm.Response(
        content=data.get("content", ""),
        tool_calls=[
            llm.ToolCall(id=tc["id"], name=tc["name"], arguments=dict(tc["arguments"]))
            for tc in data.get("tool_calls", [])
        ],
        finish_reason=data.get("finish_reason", "stop"),
        usage=dict(data.get("usage", {})),
        metadata=dict(data.get("metadata", {})),
    )


def tool_result_to_dict(result: ToolResult) -> dict[str, Any]:
    """Serialise a :class:`ToolResult` into a JSON-compatible dict.

    Images carry raw bytes, so they're base64-encoded in the envelope.
    Every other field is JSON-native or already a dict of primitives.
    """
    return {
        "success": result.success,
        "output": result.output,
        "data": dict(result.data),
        "error": result.error,
        "images": [_encode_image(img) for img in result.images],
        "caption": result.caption,
    }


def tool_result_from_dict(data: dict[str, Any]) -> ToolResult:
    """Reconstruct a :class:`ToolResult` from :func:`tool_result_to_dict`'s output."""
    return ToolResult(
        success=bool(data["success"]),
        output=data.get("output", ""),
        data=dict(data.get("data", {})),
        error=data.get("error"),
        images=[_decode_image(img) for img in data.get("images", [])],
        caption=data.get("caption"),
    )


def _json_default(value: object) -> object:
    """Extend :func:`json.dumps` to handle common non-JSON-native types.

    Keeps the record path forgiving without losing deterministic
    ordering — Cantrip uses :class:`pathlib.Path` and
    :class:`datetime.datetime` in tool arguments often enough that
    requiring callers to pre-stringify them would be a sharp edge.
    """
    import datetime
    import pathlib

    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    if isinstance(value, set | frozenset):
        return sorted(value, key=repr)
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON-serialisable for checkpoint"
    )


__all__ = [
    "KEEP_CHECKPOINTS_ENV",
    "KIND_BYTES",
    "KIND_LLM_RESPONSE",
    "KIND_TOOL_RESULT",
    "KIND_VALUE",
    "NO_RESUME_ENV",
    "CheckpointCtx",
    "CheckpointRecord",
    "CheckpointStore",
    "checkpoint",
    "compute_input_hash",
    "response_from_dict",
    "response_to_dict",
    "should_keep_checkpoints",
    "should_skip_resume",
    "tool_result_from_dict",
    "tool_result_to_dict",
]
