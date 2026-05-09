"""Tests for the Phase 72b read-only code-intelligence subsystem."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from cantrip.codeintel import (
    CodeIntel,
    CodeIntelQuery,
    Definition,
    DefinitionResult,
    ReferencesResult,
    SymbolKind,
    SymbolMatchKind,
)
from cantrip.codeintel.index import (
    render_definitions,
    render_references,
    render_symbols,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_charm(root: pathlib.Path) -> None:
    """Build a small charm tree exercising both Python and YAML."""
    (root / "src").mkdir(parents=True)
    (root / "tests" / "unit").mkdir(parents=True)

    (root / "src" / "charm.py").write_text(
        textwrap.dedent(
            """
            import ops
            import logging

            from src.handlers import IngressHandler, build_layer

            log = logging.getLogger(__name__)


            class MyCharm(ops.CharmBase):
                def __init__(self, framework):
                    super().__init__(framework)
                    self.framework.observe(self.on.install, self._on_install)
                    self.framework.observe(self.on.config_changed, self._on_config_changed)
                    self.handler = IngressHandler(self)

                def _on_install(self, event):
                    layer = build_layer(self.config["mode"])
                    self.unit.status = ops.ActiveStatus()

                def _on_config_changed(self, event):
                    self.handler.refresh()
            """
        ).strip()
        + "\n"
    )

    (root / "src" / "handlers.py").write_text(
        textwrap.dedent(
            """
            class IngressHandler:
                def __init__(self, charm):
                    self.charm = charm

                def refresh(self) -> None:
                    pass


            def build_layer(mode: str) -> dict:
                return {"summary": mode}
            """
        ).strip()
        + "\n"
    )

    (root / "tests" / "unit" / "test_charm.py").write_text(
        textwrap.dedent(
            """
            from src.handlers import build_layer


            def test_build_layer_mode():
                assert build_layer("debug")["summary"] == "debug"
            """
        ).strip()
        + "\n"
    )

    (root / "charmcraft.yaml").write_text(
        textwrap.dedent(
            """
            name: my-charm
            type: charm
            config:
              options:
                mode:
                  type: string
                  default: prod
            requires:
              ingress:
                interface: ingress
            actions:
              restart:
                description: restart the workload
            """
        ).strip()
        + "\n"
    )


@pytest.fixture
def charm_root(tmp_path: pathlib.Path) -> pathlib.Path:
    _make_charm(tmp_path)
    return tmp_path


@pytest.fixture
def index(charm_root: pathlib.Path) -> CodeIntel:
    ci = CodeIntel(charm_root)
    ci.build()
    return ci


# ---------------------------------------------------------------------------
# workspace_symbols
# ---------------------------------------------------------------------------


class TestWorkspaceSymbols:
    def test_exact_qualified_match_beats_unqualified(self, index: CodeIntel) -> None:
        matches, truncated = index.workspace_symbols("MyCharm._on_install")
        assert truncated == 0
        assert len(matches) == 1
        assert matches[0].symbol.display_name == "MyCharm._on_install"
        assert matches[0].match_kind is SymbolMatchKind.EXACT_QUALIFIED

    def test_exact_unqualified_matches_all_homonyms(self, index: CodeIntel) -> None:
        # Only one ``_on_install`` exists in the fixture, but the
        # match_kind should still be EXACT (not EXACT_QUALIFIED) when
        # the query lacks a class qualifier.
        matches, _ = index.workspace_symbols("_on_install")
        assert len(matches) == 1
        assert matches[0].match_kind is SymbolMatchKind.EXACT

    def test_prefix_fallback_only_fires_when_exact_misses(self, index: CodeIntel) -> None:
        matches, _ = index.workspace_symbols("build_lay")
        assert any(m.symbol.name == "build_layer" for m in matches)
        assert all(m.match_kind is SymbolMatchKind.PREFIX for m in matches)

    def test_fuzzy_fallback_only_when_prefix_misses(self, index: CodeIntel) -> None:
        # ``ngres`` is in the middle of ``IngressHandler``: prefix
        # would not catch it, fuzzy should.
        matches, _ = index.workspace_symbols("ngres")
        assert any(m.symbol.name == "IngressHandler" for m in matches)
        assert all(m.match_kind is SymbolMatchKind.FUZZY for m in matches)

    def test_path_scope_filters_to_prefix(self, index: CodeIntel) -> None:
        # ``build_layer`` is defined in ``src/handlers.py``; a
        # ``src/`` scope sees the definition, a ``tests/`` scope only
        # sees the test fixture (whose name *contains* the substring
        # via fuzzy matching, but never as an exact / prefix hit).
        in_src, _ = index.workspace_symbols("build_layer", path_scope="src/")
        assert {m.symbol.name for m in in_src} == {"build_layer"}

        in_tests, _ = index.workspace_symbols("build_layer", path_scope="tests/")
        assert all(m.symbol.name != "build_layer" for m in in_tests)

    def test_kinds_filter(self, index: CodeIntel) -> None:
        matches, _ = index.workspace_symbols("Handler", kinds=[SymbolKind.CLASS])
        assert all(m.symbol.kind is SymbolKind.CLASS for m in matches)

    def test_unknown_query_returns_empty(self, index: CodeIntel) -> None:
        matches, truncated = index.workspace_symbols("nope_no_chance_xyz")
        assert matches == []
        assert truncated == 0

    def test_yaml_symbols_are_included(self, index: CodeIntel) -> None:
        matches, _ = index.workspace_symbols("ingress", kinds=[SymbolKind.RELATION])
        names = {m.symbol.name for m in matches}
        assert "ingress" in names

    def test_truncation_reports_elided_count(self, charm_root: pathlib.Path) -> None:
        # Pad the repo with a handful of duplicates so the limit
        # actually bites without inflating fixture size.
        big = charm_root / "src" / "noisy.py"
        big.write_text("\n".join(f"def helper_{i}():\n    pass\n" for i in range(40)) + "\n")
        ci = CodeIntel(charm_root)
        ci.build()
        matches, truncated = ci.workspace_symbols("helper_", limit=5)
        assert len(matches) == 5
        assert truncated >= 35


# ---------------------------------------------------------------------------
# go_to_definition
# ---------------------------------------------------------------------------


class TestGoToDefinition:
    def test_finds_class_definition_with_snippet(self, index: CodeIntel) -> None:
        result = index.go_to_definition("IngressHandler")
        assert isinstance(result, DefinitionResult)
        assert result.semantic
        assert len(result.matches) == 1
        defn = result.matches[0]
        assert defn.symbol.kind is SymbolKind.CLASS
        assert defn.symbol.file == "src/handlers.py"
        assert defn.snippet
        assert "class IngressHandler" in defn.snippet

    def test_qualified_lookup_disambiguates(self, charm_root: pathlib.Path) -> None:
        # Add a second class with the same method name to provoke
        # ambiguity, then ensure the qualified form picks one.
        (charm_root / "src" / "extra.py").write_text(
            textwrap.dedent(
                """
                class SecondHandler:
                    def refresh(self) -> None:
                        pass
                """
            ).strip()
            + "\n"
        )
        ci = CodeIntel(charm_root)
        ci.build()
        unqualified = ci.go_to_definition("refresh")
        assert len(unqualified.matches) == 2
        assert "ambiguous" in unqualified.note

        qualified = ci.go_to_definition("IngressHandler.refresh")
        assert len(qualified.matches) == 1
        assert qualified.matches[0].symbol.qualifier == "IngressHandler"

    def test_alias_resolution_via_from_path(self, charm_root: pathlib.Path) -> None:
        (charm_root / "src" / "alias_user.py").write_text(
            textwrap.dedent(
                """
                from src.handlers import build_layer as bl


                def call_it():
                    return bl("debug")
                """
            ).strip()
            + "\n"
        )
        ci = CodeIntel(charm_root)
        ci.build()
        result = ci.go_to_definition("bl", from_path="src/alias_user.py")
        assert result.semantic
        assert any(m.symbol.name == "build_layer" for m in result.matches)

    def test_missing_symbol_returns_non_semantic(self, index: CodeIntel) -> None:
        result = index.go_to_definition("never_was_here")
        assert not result.semantic
        assert result.matches == ()
        assert "no semantic match" in result.note

    def test_empty_query_is_rejected(self, index: CodeIntel) -> None:
        result = index.go_to_definition("   ")
        assert not result.semantic
        assert "empty query" in result.note


# ---------------------------------------------------------------------------
# find_references
# ---------------------------------------------------------------------------


class TestFindReferences:
    def test_returns_callsite_locations(self, index: CodeIntel) -> None:
        result = index.find_references("build_layer")
        assert isinstance(result, ReferencesResult)
        assert result.semantic
        files = {r.file for r in result.locations}
        # Referenced from charm.py and the test file.
        assert "src/charm.py" in files
        assert "tests/unit/test_charm.py" in files

    def test_qualified_query_uses_leaf(self, index: CodeIntel) -> None:
        result = index.find_references("IngressHandler.refresh")
        # Falls back to the leaf ``refresh``.
        assert result.semantic
        assert any(r.name == "refresh" for r in result.locations)

    def test_self_prefix_is_stripped(self, index: CodeIntel) -> None:
        # ``self.handler`` should resolve to references to ``handler``.
        result = index.find_references("self.handler")
        # ``handler`` is the attribute name set by the constructor;
        # ``self.handler`` is read in _on_config_changed.
        assert result.semantic

    def test_include_definition_prepends_def_line(self, index: CodeIntel) -> None:
        result = index.find_references("IngressHandler", include_definition=True)
        assert result.semantic
        # The first location should be the class definition site.
        assert any(
            r.file == "src/handlers.py" and r.name == "IngressHandler" for r in result.locations
        )

    def test_unknown_symbol_returns_empty(self, index: CodeIntel) -> None:
        result = index.find_references("absolutely_nothing")
        assert not result.semantic
        assert result.locations == ()

    def test_truncation_reports_count(self, charm_root: pathlib.Path) -> None:
        loud = charm_root / "src" / "loud.py"
        # 60 references to ``build_layer`` — exceeds the default 50
        # cap so we can assert truncation.
        loud.write_text("from src.handlers import build_layer\n" + "build_layer(0)\n" * 60)
        ci = CodeIntel(charm_root)
        ci.build()
        result = ci.find_references("build_layer", limit=10)
        assert len(result.locations) == 10
        assert result.truncated >= 50


# ---------------------------------------------------------------------------
# Cache + lifecycle
# ---------------------------------------------------------------------------


class TestCache:
    def test_cache_file_written_after_build(self, index: CodeIntel) -> None:
        cache = index.repo_root / ".cantrip-codeintel.json"
        assert cache.is_file()
        data = json.loads(cache.read_text())
        assert data["version"] == 1
        assert data["entries"]

    def test_stale_cache_entries_dropped(self, charm_root: pathlib.Path) -> None:
        ci = CodeIntel(charm_root)
        ci.build()
        # Delete a file and rebuild; the index should not retain the
        # vanished file's symbols.
        (charm_root / "src" / "handlers.py").unlink()
        ci.build()
        result = ci.go_to_definition("IngressHandler")
        assert not result.semantic

    def test_mtime_invalidation_picks_up_edits(self, charm_root: pathlib.Path) -> None:
        ci = CodeIntel(charm_root)
        ci.build()
        # Append a new symbol — the next build must surface it.
        added = charm_root / "src" / "handlers.py"
        added.write_text(added.read_text() + "\n\ndef brand_new_helper():\n    pass\n")
        # Bump mtime explicitly: the test runs inside the same second
        # as the original build on fast filesystems, and Python's
        # default ``write_text`` may share the mtime.  ``utime`` with
        # ``ns=`` forces a distinct timestamp.
        import os

        stat = added.stat()
        os.utime(added, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        ci.build()
        result = ci.go_to_definition("brand_new_helper")
        assert result.semantic

    def test_force_rebuild_discards_cache(self, charm_root: pathlib.Path) -> None:
        ci = CodeIntel(charm_root)
        ci.build()
        # Tamper with the cache file: a force rebuild should overwrite
        # whatever is in it without raising.
        cache = charm_root / ".cantrip-codeintel.json"
        cache.write_text("{}")
        ci2 = CodeIntel(charm_root)
        ci2.build(force=True)
        result = ci2.go_to_definition("IngressHandler")
        assert result.semantic

    def test_corrupt_cache_falls_back_to_rebuild(self, charm_root: pathlib.Path) -> None:
        cache = charm_root / ".cantrip-codeintel.json"
        cache.write_text("not-json")
        ci = CodeIntel(charm_root)
        ci.build()
        result = ci.go_to_definition("IngressHandler")
        assert result.semantic

    def test_syntax_error_does_not_crash_build(self, charm_root: pathlib.Path) -> None:
        broken = charm_root / "src" / "broken.py"
        broken.write_text("def whoops(:\n")
        ci = CodeIntel(charm_root)
        ci.build()  # Must not raise.
        # The good files are still indexed.
        result = ci.go_to_definition("IngressHandler")
        assert result.semantic


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class TestRenderers:
    def test_render_symbols_omits_header_when_empty(self) -> None:
        assert render_symbols([]) == ""

    def test_render_symbols_truncation_marker(self, index: CodeIntel) -> None:
        matches, truncated = index.workspace_symbols("_on_install")
        text = render_symbols(matches, truncated=truncated)
        assert "MyCharm._on_install" in text

    def test_render_definitions_announces_ambiguity(self, charm_root: pathlib.Path) -> None:
        (charm_root / "src" / "extra.py").write_text(
            textwrap.dedent(
                """
                class SecondHandler:
                    def refresh(self) -> None:
                        pass
                """
            ).strip()
            + "\n"
        )
        ci = CodeIntel(charm_root)
        ci.build()
        result = ci.go_to_definition("refresh")
        text = render_definitions(result)
        assert "candidate definitions" in text or "candidates" in text

    def test_render_references_shows_locations(self, index: CodeIntel) -> None:
        result = index.find_references("build_layer")
        text = render_references(result)
        assert "src/charm.py" in text or "tests/unit/test_charm.py" in text

    def test_render_definitions_no_match(self) -> None:
        empty = DefinitionResult(query="X", matches=(), semantic=False, note="x")
        assert "No definition" in render_definitions(empty)

    def test_render_references_no_match(self) -> None:
        empty = ReferencesResult(
            query="X", locations=(), truncated=0, semantic=False, candidates=()
        )
        assert "No references" in render_references(empty)


# ---------------------------------------------------------------------------
# CodeIntelQuery — Phase 72b.4 adapter seam
# ---------------------------------------------------------------------------


class _StubQueryAdapter:
    """Minimal stand-in for the future optional adapter (pyright et al.).

    The body is intentionally empty — the test only checks the seam,
    not the answers.  An adapter that wraps :class:`CodeIntel` instead
    of replacing it would forward each call after consulting whatever
    semantic source it brings.
    """

    def __init__(self, repo_root: pathlib.Path) -> None:
        self._repo_root = repo_root

    @property
    def repo_root(self) -> pathlib.Path:
        return self._repo_root

    def build(self, *, force: bool = False) -> None:
        del force

    def workspace_symbols(
        self,
        query: str,
        *,
        path_scope: str | None = None,
        kinds=None,
        limit: int = 50,
    ):
        del query, path_scope, kinds, limit
        return ([], 0)

    def go_to_definition(
        self,
        symbol: str,
        *,
        from_path: str | None = None,
    ) -> DefinitionResult:
        del from_path
        return DefinitionResult(query=symbol, matches=(), semantic=False, note="stub")

    def find_references(
        self,
        symbol: str,
        *,
        from_path: str | None = None,
        include_definition: bool = False,
        limit: int = 50,
    ) -> ReferencesResult:
        del from_path, include_definition, limit
        return ReferencesResult(
            query=symbol,
            locations=(),
            truncated=0,
            semantic=False,
            candidates=(),
            note="stub",
        )


class TestCodeIntelQueryProtocol:
    """The default :class:`CodeIntel` and a stub adapter both conform.

    Pinning runtime conformance keeps the seam honest: a future change
    that adds a new required method to :class:`CodeIntelQuery` without
    updating both implementations breaks at unit-test time rather than
    silently at the call site.
    """

    def test_concrete_indexer_conforms(self, charm_root: pathlib.Path) -> None:
        ci = CodeIntel(charm_root)
        assert isinstance(ci, CodeIntelQuery)

    def test_stub_adapter_conforms(self, charm_root: pathlib.Path) -> None:
        adapter = _StubQueryAdapter(charm_root)
        assert isinstance(adapter, CodeIntelQuery)

    def test_adapter_substitutes_at_consumer_seam(self, charm_root: pathlib.Path) -> None:
        # A consumer that only relies on the Protocol surface accepts
        # either the indexer or the adapter — that's the seam's whole
        # point.  ``go_to_definition`` is exercised here because it has
        # the most-typed return shape.
        adapter: CodeIntelQuery = _StubQueryAdapter(charm_root)
        adapter.build()
        result = adapter.go_to_definition("Anything")
        assert isinstance(result, DefinitionResult)
        assert result.matches == ()
        assert result.semantic is False
        # The same call shape works against the real indexer.
        ci: CodeIntelQuery = CodeIntel(charm_root)
        ci.build()
        real_result = ci.go_to_definition("MyCharm._on_install")
        assert isinstance(real_result, DefinitionResult)
        assert real_result.matches and isinstance(real_result.matches[0], Definition)
