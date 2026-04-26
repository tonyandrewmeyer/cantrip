"""Phase 72.1 — docs-index vector store and chunker."""

from __future__ import annotations

import pathlib

from cantrip.docs_index.chunk import (
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    TextChunk,
    chunk_text,
)
from cantrip.docs_index.store import Chunk, DocsStore

# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------


class TestChunker:
    """Token-aware chunking with paragraph-aware boundaries."""

    def test_empty_input(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("    \n\n  \n") == []

    def test_short_input_one_chunk(self) -> None:
        text = "Tiny doc body."
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].ordinal == 0

    def test_default_constants(self) -> None:
        assert DEFAULT_CHUNK_TOKENS == 500
        assert DEFAULT_OVERLAP_TOKENS == 50

    def test_chunks_are_ordinal_ordered(self) -> None:
        # Build a deterministic body that exceeds one chunk.
        paragraph = "x " * 600  # ~1200 chars
        body = "\n\n".join([paragraph] * 4)
        chunks = chunk_text(body, chunk_tokens=200, overlap_tokens=20)
        assert len(chunks) >= 4
        ordinals = [c.ordinal for c in chunks]
        assert ordinals == sorted(ordinals)
        assert ordinals == list(range(len(ordinals)))

    def test_overlap_is_respected(self) -> None:
        body = "abcdefghijklmnopqrstuvwxyz" * 200
        chunks = chunk_text(body, chunk_tokens=50, overlap_tokens=10)
        assert len(chunks) >= 2
        # Each chunk's start advances by less than chunk_chars (==
        # overlap is positive).  ``50 tokens × 4 chars = 200``;
        # ``10 tokens × 4 chars = 40``; advance per step ≤ 160.
        for prev, nxt in zip(chunks[:-1], chunks[1:], strict=True):
            advance = nxt.char_start - prev.char_start
            assert advance < 200

    def test_paragraph_break_preferred(self) -> None:
        # The chunker should prefer to split on the blank line.
        body = ("a" * 300) + "\n\n" + ("b" * 300)
        chunks = chunk_text(body, chunk_tokens=80, overlap_tokens=5)
        # First chunk should end before or at the blank-line break.
        assert chunks[0].text.endswith("a")
        assert "b" not in chunks[0].text or chunks[0].text.count("a") > 250

    def test_returns_TextChunk(self) -> None:
        chunks = chunk_text("one paragraph", chunk_tokens=100, overlap_tokens=10)
        assert isinstance(chunks[0], TextChunk)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def _make_chunk(
    *,
    url: str = "https://docs.example/page",
    ordinal: int = 0,
    vector: tuple[float, ...] = (1.0, 0.0, 0.0),
    text: str = "body",
    title: str = "Title",
    section: str = "Section",
    model: str = "voyage-3",
) -> Chunk:
    return Chunk(
        url=url,
        title=title,
        section=section,
        ordinal=ordinal,
        text=text,
        vector=vector,
        model=model,
    )


class TestDocsStore:
    """Insert + search + upsert behaviour."""

    def test_empty_store_search_returns_empty(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore("juju", tmp_path / "j" / "index.db")
        assert store.search((1.0, 0.0, 0.0)) == []
        assert store.count() == 0
        store.close()

    def test_upsert_then_count(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore("juju", tmp_path / "j" / "index.db")
        store.upsert(
            [
                _make_chunk(ordinal=0),
                _make_chunk(ordinal=1, vector=(0.0, 1.0, 0.0)),
            ]
        )
        assert store.count() == 2

    def test_upsert_replaces_same_url_ordinal(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore("juju", tmp_path / "j" / "index.db")
        store.upsert([_make_chunk(text="first")])
        store.upsert([_make_chunk(text="second")])
        # Same chunk_hash → second insert replaced the first.
        assert store.count() == 1

    def test_search_orders_by_cosine(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore("juju", tmp_path / "j" / "index.db")
        store.upsert(
            [
                _make_chunk(url="https://x/a", ordinal=0, vector=(1.0, 0.0, 0.0), text="a"),
                _make_chunk(url="https://x/b", ordinal=0, vector=(0.0, 1.0, 0.0), text="b"),
                _make_chunk(url="https://x/c", ordinal=0, vector=(0.5, 0.5, 0.0), text="c"),
            ]
        )
        # Query close to the first chunk's vector.
        hits = store.search((0.9, 0.1, 0.0), top_k=3)
        assert hits[0].url == "https://x/a"
        # Mixed vector ranks above the orthogonal one.
        assert hits[1].url == "https://x/c"
        assert hits[2].url == "https://x/b"
        # Scores are descending.
        assert hits[0].score >= hits[1].score >= hits[2].score
        # All hits carry the configured site name.
        assert all(hit.site == "juju" for hit in hits)

    def test_search_top_k_limits(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore("juju", tmp_path / "j" / "index.db")
        store.upsert(
            [
                _make_chunk(url=f"https://x/{i}", ordinal=0, vector=(float(i), 0.0, 0.0))
                for i in range(5)
            ]
        )
        hits = store.search((1.0, 0.0, 0.0), top_k=2)
        assert len(hits) == 2

    def test_search_excerpt_truncation(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore("juju", tmp_path / "j" / "index.db")
        long_text = "x" * 5000
        store.upsert([_make_chunk(text=long_text)])
        hits = store.search((1.0, 0.0, 0.0), top_k=1, excerpt_chars=100)
        assert len(hits[0].excerpt) <= 100
        assert hits[0].excerpt.endswith("…")

    def test_models_distinct(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore("juju", tmp_path / "j" / "index.db")
        store.upsert(
            [
                _make_chunk(url="https://x/a", ordinal=0, model="voyage-3"),
                _make_chunk(url="https://x/b", ordinal=0, model="voyage-3"),
                _make_chunk(url="https://x/c", ordinal=0, model="text-embedding-3-small"),
            ]
        )
        assert store.models() == ("text-embedding-3-small", "voyage-3")

    def test_delete_url(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore("juju", tmp_path / "j" / "index.db")
        store.upsert(
            [
                _make_chunk(url="https://x/a", ordinal=0),
                _make_chunk(url="https://x/a", ordinal=1, vector=(0.0, 1.0, 0.0)),
                _make_chunk(url="https://x/b", ordinal=0, vector=(0.0, 0.0, 1.0)),
            ]
        )
        deleted = store.delete_url("https://x/a")
        assert deleted == 2
        assert store.count() == 1

    def test_chunk_hash_stable(self) -> None:
        chunk1 = _make_chunk(url="https://x/a", ordinal=3)
        chunk2 = _make_chunk(url="https://x/a", ordinal=3, text="different body")
        # Hash depends only on (url, ordinal), not body.
        assert chunk1.chunk_hash == chunk2.chunk_hash
        chunk3 = _make_chunk(url="https://x/a", ordinal=4)
        assert chunk1.chunk_hash != chunk3.chunk_hash
