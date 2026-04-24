"""Step-level durable-execution checkpoints (Phase 52.1).

A subagent task that rate-limits on LLM turn 18 shouldn't restart
from turn 1 on the next run.  This module exposes a small facade over
:class:`~cantrip.agent.store.SessionStore` for recording each
expensive step — LLM calls and tool invocations — so the replay path
in Phases 52.2 / 52.3 can resume from the last completed checkpoint.

The facade stays deliberately thin in 52.1: it handles serialisation
(JSON envelope with a raw-bytes escape hatch), ordinal allocation,
and task-scoped garbage collection.  The replay wrapper
(``checkpoint(ctx, step_name, fn)``) and the subagent wiring land in
52.2 / 52.3.

Inspired by Armin Ronacher's *Absurd* (Postgres-backed durable
execution) — the single-process SQLite flavour.  No queue, no
worker, no ``SKIP LOCKED``.  One charm, one ``.cantrip``, per-step
resume.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cantrip.agent.store import SessionStore

log = logging.getLogger(__name__)


# ``CANTRIP_KEEP_CHECKPOINTS=1`` preserves checkpoints for debugging
# stale-cache behaviour; otherwise successful task completion purges
# them.  Any truthy-ish value (``1``, ``true``, ``yes``) turns it on.
KEEP_CHECKPOINTS_ENV = "CANTRIP_KEEP_CHECKPOINTS"

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


def should_keep_checkpoints() -> bool:
    """Return True when the debug-mode env var requests retention.

    A truthy ``CANTRIP_KEEP_CHECKPOINTS`` makes :meth:`CheckpointStore.
    on_task_done` a no-op so a session can be inspected with
    ``SELECT * FROM step_checkpoints`` after the fact — useful when
    hunting a bug that might be cached in a stale checkpoint.
    """
    raw = os.environ.get(KEEP_CHECKPOINTS_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
    "CheckpointRecord",
    "CheckpointStore",
    "compute_input_hash",
    "should_keep_checkpoints",
]
