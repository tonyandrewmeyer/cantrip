from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING


class CheckpointsMixin:
    """Durable step-checkpoint persistence."""

    if TYPE_CHECKING:
        # Provided by SessionStore; declared for type-checkers only.
        _db: sqlite3.Connection

    def record_checkpoint(
        self,
        task_id: str,
        step_name: str,
        ordinal: int,
        input_hash: str,
        result_kind: str,
        result_blob: bytes,
    ) -> None:
        """Store one step result for resume on replay.

        Serialisation is the caller's responsibility — ``result_blob`` is
        stored verbatim in the ``result_blob`` BLOB column.  The
        roadmap's msgpack-or-JSON envelope lives one layer up in
        :mod:`cantrip.agent.runtime.durability` so callers picking a different
        encoding aren't forced through an extra decode.

        The ``(task_id, step_name, ordinal)`` triple is unique — upsert
        semantics via ``INSERT OR REPLACE`` handle the "same step re-run
        after input-hash invalidation" path from 52.2 without callers
        needing a prior DELETE.
        """
        self._db.execute(
            "INSERT OR REPLACE INTO step_checkpoints "
            "(task_id, step_name, ordinal, input_hash, result_blob, result_kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, step_name, ordinal, input_hash, result_blob, result_kind),
        )
        self._db.commit()

    def get_checkpoint(self, task_id: str, step_name: str, ordinal: int) -> sqlite3.Row | None:
        """Return the stored row for ``(task_id, step_name, ordinal)`` or ``None``.

        Callers match on ``input_hash`` before trusting the blob —
        :mod:`cantrip.agent.runtime.durability` wraps the raw row in a typed
        record and handles the invalidation path.
        """
        return self._db.execute(
            "SELECT task_id, step_name, ordinal, input_hash, result_kind, "
            "result_blob, created_at "
            "FROM step_checkpoints "
            "WHERE task_id = ? AND step_name = ? AND ordinal = ?",
            (task_id, step_name, ordinal),
        ).fetchone()

    def next_checkpoint_ordinal(self, task_id: str, step_name: str) -> int:
        """Return the next unused ordinal for a ``(task_id, step_name)`` pair.

        Starts at ``1`` — the first ``llm_turn`` in a task is
        ``ordinal=1``, the next is ``2``, and so on.  Callers don't
        track counters; they just ask for the next slot.  Off-the-end
        requests (probing past the last recorded step) return
        ``max(ordinal) + 1`` so replay can drop out of the cached
        prefix cleanly.
        """
        row = self._db.execute(
            "SELECT COALESCE(MAX(ordinal), 0) FROM step_checkpoints "
            "WHERE task_id = ? AND step_name = ?",
            (task_id, step_name),
        ).fetchone()
        return int(row[0]) + 1

    def list_checkpoints_for_task(self, task_id: str) -> list[sqlite3.Row]:
        """Return every recorded checkpoint for *task_id* in insertion order."""
        return list(
            self._db.execute(
                "SELECT task_id, step_name, ordinal, input_hash, result_kind, "
                "result_blob, created_at "
                "FROM step_checkpoints WHERE task_id = ? "
                "ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        )

    def count_checkpoints_for_task(self, task_id: str) -> int:
        """Return how many checkpoints are stored for *task_id*."""
        row = self._db.execute(
            "SELECT COUNT(*) FROM step_checkpoints WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row[0])

    def purge_checkpoints_for_task(self, task_id: str) -> int:
        """Delete every checkpoint for *task_id*.  Returns the row count removed.

        Called by :class:`CheckpointStore` on successful task
        completion to reclaim space; failed / paused tasks retain
        their checkpoints so the next run can resume.  The
        ``CANTRIP_KEEP_CHECKPOINTS`` env-var opt-out lives one layer
        up so the SQL path stays simple.
        """
        cursor = self._db.execute(
            "DELETE FROM step_checkpoints WHERE task_id = ?",
            (task_id,),
        )
        self._db.commit()
        return cursor.rowcount
