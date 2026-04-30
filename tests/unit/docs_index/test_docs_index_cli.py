"""Phase 72.1 — ``cantrip docs`` subcommand dispatcher."""

from __future__ import annotations

import argparse
import pathlib

import pytest

from cantrip.docs_index import cli as docs_cli
from cantrip.docs_index import index, sites
from cantrip.docs_index.store import Chunk, DocsStore


def _make_args(**kwargs: object) -> argparse.Namespace:
    """Build an argparse.Namespace with sensible defaults."""
    base = {
        "command": "docs",
        "docs_command": None,
        "site": None,
        "all_sites": False,
        "embed_provider": None,
        "embed_model": None,
        "root": None,
        "query": "",
        "top_k": 5,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


def _seed_store(path: pathlib.Path, *, site: str, vectors: list[tuple[float, ...]]) -> None:
    """Write *vectors* to a per-site store at *path*; closes when done."""
    store = DocsStore(site, path)
    rows = [
        Chunk(
            url=f"https://x/p{i}",
            title=f"Page {i}",
            section="howto",
            ordinal=0,
            text=f"body {i}",
            vector=vec,
            model="stub-embed",
        )
        for i, vec in enumerate(vectors)
    ]
    store.upsert(rows)
    store.close()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestDispatch:
    """Top-level routing of the three subcommands."""

    def test_unknown_subcommand_returns_2(self) -> None:
        rc = docs_cli.dispatch(_make_args(docs_command="bogus"))
        assert rc == 2


# ---------------------------------------------------------------------------
# `cantrip docs list`
# ---------------------------------------------------------------------------


class TestList:
    """Listing surface — every registered site shown, with index status."""

    def test_lists_all_six_sites(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = docs_cli.dispatch(_make_args(docs_command="list", root=tmp_path))
        captured = capsys.readouterr()
        assert rc == 0
        for name in sites.names():
            assert name in captured.out
        # Every row reads "no" because the cache is empty.
        assert captured.out.count(" no  ") >= 6 or captured.out.count(" no ") >= 6

    def test_indexed_site_shows_chunk_count(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = index.store_path_for("ops", root=tmp_path)
        _seed_store(path, site="ops", vectors=[(1.0, 0.0), (0.0, 1.0), (0.5, 0.5)])
        rc = docs_cli.dispatch(_make_args(docs_command="list", root=tmp_path))
        captured = capsys.readouterr()
        assert rc == 0
        assert "yes" in captured.out
        # The chunk count appears for the ops row.
        ops_line = next(line for line in captured.out.splitlines() if line.startswith("ops"))
        assert "3" in ops_line


# ---------------------------------------------------------------------------
# `cantrip docs index`
# ---------------------------------------------------------------------------


class TestIndex:
    """Argument validation; live indexing is covered by the pipeline tests."""

    def test_missing_site_and_all_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = docs_cli.dispatch(_make_args(docs_command="index"))
        assert rc == 2
        captured = capsys.readouterr()
        assert "--site" in captured.err

    def test_site_and_all_are_mutually_exclusive(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = docs_cli.dispatch(_make_args(docs_command="index", site="ops", all_sites=True))
        assert rc == 2
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err

    def test_unknown_site_returns_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Configure embed so the "no provider" path doesn't fire first.
        monkeypatch.setenv("CANTRIP_EMBED_PROVIDER", "voyage")
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
        rc = docs_cli.dispatch(_make_args(docs_command="index", site="not-a-site"))
        assert rc == 1
        captured = capsys.readouterr()
        assert "unknown site" in captured.err

    def test_no_embed_configured_returns_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("CANTRIP_EMBED_PROVIDER", raising=False)
        monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
        rc = docs_cli.dispatch(_make_args(docs_command="index", site="ops"))
        assert rc == 1
        captured = capsys.readouterr()
        assert "embed provider" in captured.err.lower()


# ---------------------------------------------------------------------------
# `cantrip docs search`
# ---------------------------------------------------------------------------


class TestSearch:
    """Search-command argument validation + missing-index path."""

    def test_unknown_site(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = docs_cli.dispatch(_make_args(docs_command="search", site="bogus", query="hello"))
        assert rc == 1
        captured = capsys.readouterr()
        assert "unknown site" in captured.err

    def test_missing_index(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Point the cache at an empty tmp_path so nothing is indexed.
        monkeypatch.setattr(index, "_DEFAULT_CACHE_ROOT", tmp_path)
        rc = docs_cli.dispatch(_make_args(docs_command="search", site="ops", query="hello"))
        assert rc == 1
        captured = capsys.readouterr()
        assert "not indexed" in captured.err
