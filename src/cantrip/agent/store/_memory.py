from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from cantrip.agent.store._common import _memory_row_to_dict, _truncate


class MemoryMixin:
    """Charm-scoped memory CRUD and search."""

    if TYPE_CHECKING:
        # Provided by SessionStore; declared for type-checkers only.
        _db: sqlite3.Connection

    def record_memory(
        self,
        title: str,
        kind: str,
        body: str,
        *,
        source: str = "manual",
        citations: list[dict[str, object]] | None = None,
        tags: list[str] | None = None,
        status: str = "active",
    ) -> int:
        """Insert a new memory row and return its id."""
        cursor = self._db.execute(
            """\
            INSERT INTO memory (title, kind, body, source, citations, tags, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                kind,
                _truncate(body),
                source,
                json.dumps(citations or []),
                json.dumps(tags or []),
                status,
            ),
        )
        self._db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def update_memory(
        self,
        memory_id: int,
        *,
        body: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        citations: list[dict[str, object]] | None = None,
        last_accessed_at: str | None = None,
        last_validated_at: str | None = None,
    ) -> bool:
        """Partial update of a memory row. Returns True when a row was changed."""
        fields: list[str] = []
        params: list[object] = []
        if body is not None:
            fields.append("body = ?")
            params.append(_truncate(body))
        if kind is not None:
            fields.append("kind = ?")
            params.append(kind)
        if tags is not None:
            fields.append("tags = ?")
            params.append(json.dumps(tags))
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if citations is not None:
            fields.append("citations = ?")
            params.append(json.dumps(citations))
        if last_accessed_at is not None:
            fields.append("last_accessed_at = ?")
            params.append(last_accessed_at)
        if last_validated_at is not None:
            fields.append("last_validated_at = ?")
            params.append(last_validated_at)
        if not fields:
            return False
        fields.append("updated_at = datetime('now')")
        params.append(memory_id)
        cursor = self._db.execute(
            f"UPDATE memory SET {', '.join(fields)} WHERE id = ?",  # noqa: S608
            params,
        )
        self._db.commit()
        return cursor.rowcount > 0

    def touch_memory(self, memory_id: int) -> None:
        """Bump access_count and set last_accessed_at to now."""
        self._db.execute(
            "UPDATE memory SET access_count = access_count + 1, "
            "last_accessed_at = datetime('now') WHERE id = ?",
            (memory_id,),
        )
        self._db.commit()

    def delete_memory(self, memory_id: int) -> bool:
        """Remove a memory row. Returns True when a row was removed."""
        cursor = self._db.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
        self._db.commit()
        return cursor.rowcount > 0

    def get_memory(self, memory_id: int) -> dict[str, object] | None:
        """Fetch a memory row by id."""
        row = self._db.execute("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
        return _memory_row_to_dict(row) if row else None

    def get_memory_by_title(self, title: str) -> dict[str, object] | None:
        """Fetch a memory row by title."""
        row = self._db.execute("SELECT * FROM memory WHERE title = ?", (title,)).fetchone()
        return _memory_row_to_dict(row) if row else None

    def list_memory(
        self,
        *,
        kind: str | None = None,
        status: str | None = "active",
        tag: str | None = None,
    ) -> list[dict[str, object]]:
        """List memory rows matching optional filters, newest first.

        ``status=None`` returns every row regardless of status; the default
        hides archived and quarantined memories.  ``tag`` matches a single
        tag against the JSON-encoded tags column with a LIKE probe; callers
        that need exact matching should filter the result in Python.
        """
        query = "SELECT * FROM memory"
        conditions: list[str] = []
        params: list[object] = []
        if kind is not None:
            conditions.append("kind = ?")
            params.append(kind)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if tag is not None:
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC"
        rows = self._db.execute(query, params).fetchall()
        return [_memory_row_to_dict(r) for r in rows]

    def search_memory(
        self, query: str, *, status: str | None = "active"
    ) -> list[dict[str, object]]:
        """Keyword search across title and body. Case-insensitive substring match."""
        like = f"%{query}%"
        sql = (
            "SELECT * FROM memory WHERE (title LIKE ? OR body LIKE ?)"
            if status is None
            else "SELECT * FROM memory WHERE (title LIKE ? OR body LIKE ?) AND status = ?"
        )
        params: list[object] = [like, like]
        if status is not None:
            params.append(status)
        rows = self._db.execute(sql + " ORDER BY id DESC", params).fetchall()
        return [_memory_row_to_dict(r) for r in rows]
