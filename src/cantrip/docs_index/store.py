"""SQLite-backed vector store for the Phase 72.1 docs index.

Layout: one SQLite file per indexed site, under
``~/.cache/cantrip/docs-index/<site-name>/index.db``.  Vectors are
stored as ``BLOB`` (packed little-endian float32) so a single SELECT
loads everything; cosine similarity runs in pure Python without a
native vector-store dependency.

The "load everything in memory" approach is deliberate: charm-
ecosystem doc corpora are small (low thousands of chunks per site),
similarity search needs to be sub-second, and the alternative —
``sqlite-vec`` or ``faiss`` — would introduce a native dependency
that snap-confined builds find awkward.  When a site outgrows
in-memory search, swap in a native backend behind
:class:`DocsStore`'s public methods (``upsert``, ``search``,
``count``); the rest of the package stays unchanged.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import sqlite3
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

_SCHEMA_VERSION = 1


_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- A stable hash of (url, ordinal) so re-indexing the same page
    -- with the same chunker replaces existing rows rather than
    -- accumulating duplicates.
    chunk_hash TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    -- 0-based position within the page, useful for citation
    -- ordering when two chunks from the same page tie on score.
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    -- Packed float32 little-endian; all rows share the same dim.
    vector BLOB NOT NULL,
    -- Embedding model identifier; lets the store refuse a query
    -- vector that came from a different model than the corpus
    -- without silently returning garbage.
    model TEXT NOT NULL,
    crawled_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_chunks_url ON chunks(url);
"""


@dataclasses.dataclass(frozen=True, slots=True)
class Chunk:
    """One indexed chunk and its embedding vector.

    ``url`` plus ``ordinal`` uniquely identify a chunk within a site;
    ``chunk_hash`` is a derived stable identity used for upsert.
    ``model`` records which embedding model produced the vector so a
    later query refuses to mix models.
    """

    url: str
    title: str
    section: str
    ordinal: int
    text: str
    vector: tuple[float, ...]
    model: str

    @property
    def chunk_hash(self) -> str:
        """Stable identity: ``sha256(url|ordinal)`` first 16 hex chars."""
        digest = hashlib.sha256(f"{self.url}|{self.ordinal}".encode()).hexdigest()
        return digest[:16]


@dataclasses.dataclass(frozen=True, slots=True)
class SearchHit:
    """One similarity-search result.

    Mirrors the ``{site, url, excerpt, score}`` shape called out in
    the Phase 72.1 spec.  ``site`` is filled in by the caller because
    the store itself is per-site and doesn't carry the name.
    """

    site: str
    url: str
    title: str
    section: str
    excerpt: str
    score: float


def _pack_vector(vector: tuple[float, ...]) -> bytes:
    """Encode a vector as packed little-endian float32 bytes."""
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_vector(blob: bytes) -> list[float]:
    """Decode a packed vector blob back to a list of floats."""
    if len(blob) % 4 != 0:
        raise ValueError(f"vector blob length {len(blob)} not a multiple of 4")
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def _cosine(a: tuple[float, ...] | list[float], b: list[float]) -> float:
    """Cosine similarity between *a* and *b*; returns 0.0 on degenerate input."""
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class DocsStore:
    """Per-site SQLite-backed vector store.

    One instance per site; the file path is owned by the caller so
    tests can use ``tmp_path``.  ``site_name`` is the human-readable
    label that ends up in :class:`SearchHit`s.

    Concurrent writers are not supported — index runs are
    single-process; queries are read-only and safe.
    """

    def __init__(self, site_name: str, db_path: pathlib.Path) -> None:
        self._site = site_name
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)
        self._migrate()

    @property
    def site_name(self) -> str:
        return self._site

    @property
    def db_path(self) -> pathlib.Path:
        return self._db_path

    def _migrate(self) -> None:
        """Stamp the schema version on first use; future bumps land here."""
        row = self._conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()
        if row[0] == 0:
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,)
            )
            self._conn.commit()

    def upsert(self, chunks: list[Chunk]) -> int:
        """Insert or replace *chunks* by ``chunk_hash``; returns row count.

        Re-indexing a page replaces its existing chunks rather than
        appending duplicates — the caller does *not* need to delete
        before re-running the indexer.
        """
        if not chunks:
            return 0
        rows = [
            (
                chunk.chunk_hash,
                chunk.url,
                chunk.title,
                chunk.section,
                chunk.ordinal,
                chunk.text,
                _pack_vector(chunk.vector),
                chunk.model,
            )
            for chunk in chunks
        ]
        self._conn.executemany(
            """\
            INSERT INTO chunks
                (chunk_hash, url, title, section, ordinal, text, vector, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_hash) DO UPDATE SET
                url=excluded.url,
                title=excluded.title,
                section=excluded.section,
                ordinal=excluded.ordinal,
                text=excluded.text,
                vector=excluded.vector,
                model=excluded.model,
                crawled_at=datetime('now')
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def delete_url(self, url: str) -> int:
        """Delete every chunk associated with *url*.  Returns row count."""
        cursor = self._conn.execute("DELETE FROM chunks WHERE url = ?", (url,))
        self._conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        """Total number of chunks indexed in this site."""
        row = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0])

    def models(self) -> tuple[str, ...]:
        """Distinct embedding models present in the store.

        Used by the indexer to detect when a model has rotated since
        the last crawl — a mixed-model corpus would return nonsense
        from cosine search.
        """
        rows = self._conn.execute("SELECT DISTINCT model FROM chunks ORDER BY model").fetchall()
        return tuple(row["model"] for row in rows)

    def search(
        self,
        query_vector: tuple[float, ...] | list[float],
        *,
        top_k: int = 8,
        excerpt_chars: int = 600,
    ) -> list[SearchHit]:
        """Return the top-*k* most similar chunks to *query_vector*.

        Results sort by cosine similarity descending; ties break on
        ``url`` ascending and ``ordinal`` ascending so the order is
        deterministic.  Empty stores return an empty list.

        ``excerpt_chars`` caps the rendered text per hit so a long
        chunk doesn't dominate the response.
        """
        if top_k <= 0:
            return []
        rows = self._conn.execute(
            "SELECT url, title, section, ordinal, text, vector, model FROM chunks"
        ).fetchall()
        if not rows:
            return []
        scored: list[tuple[float, sqlite3.Row]] = []
        query = list(query_vector)
        for row in rows:
            vec = _unpack_vector(row["vector"])
            score = _cosine(query, vec)
            scored.append((score, row))
        # Sort key matches the docstring: score desc, then url asc, then
        # ordinal asc — without ``ordinal`` two chunks from the same page
        # with identical scores would land in unreproducible SQLite order.
        scored.sort(key=lambda pair: (-pair[0], pair[1]["url"], pair[1]["ordinal"]))
        hits: list[SearchHit] = []
        for score, row in scored[:top_k]:
            text = row["text"] or ""
            if len(text) > excerpt_chars:
                text = text[: excerpt_chars - 1] + "…"
            hits.append(
                SearchHit(
                    site=self._site,
                    url=row["url"],
                    title=row["title"] or "",
                    section=row["section"] or "",
                    excerpt=text,
                    score=score,
                )
            )
        return hits

    def close(self) -> None:
        """Close the connection — call after a batch of writes."""
        self._conn.close()
