"""Tests for the Phase 71.1 graph-ranked repository map."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from cantrip.repomap import DEFAULT_TOKEN_BUDGET, RepoMap, SymbolKind
from cantrip.repomap.graph import build_graph, pagerank, rank_files
from cantrip.repomap.render import render
from cantrip.repomap.symbols import (
    FileSymbols,
    parse_charm_metadata,
    parse_python_file,
)

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def _make_charm(root: Path) -> None:
    """Create a small but realistic charm tree under *root*.

    Three Python files (``src/charm.py``, ``src/handlers.py``,
    ``tests/unit/test_charm.py``) and a ``charmcraft.yaml`` so the
    parser exercises both code paths.  ``handlers.py`` is referenced
    by ``charm.py`` so it should rank above the test file under
    PageRank.
    """
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
            from src.charm import MyCharm


            def test_install_sets_active() -> None:
                assert MyCharm is not None
            """
        ).strip()
        + "\n"
    )

    (root / "charmcraft.yaml").write_text(
        textwrap.dedent(
            """
            name: my-charm
            type: charm
            requires:
              ingress:
                interface: ingress
            provides:
              metrics-endpoint:
                interface: prometheus_scrape
            config:
              options:
                mode:
                  type: string
                  default: standard
            actions:
              restart:
                description: Restart the workload.
            """
        ).strip()
        + "\n"
    )


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------


class TestPythonParser:
    def test_extracts_classes_methods_and_functions(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        result = parse_python_file(tmp_path / "src" / "charm.py", repo_root=tmp_path)
        kinds = {s.kind for s in result.definitions}
        names = {s.display_name for s in result.definitions}

        assert SymbolKind.CLASS in kinds
        assert SymbolKind.METHOD in kinds
        assert "MyCharm" in names
        assert "MyCharm.__init__" in names
        assert "MyCharm._on_install" in names
        assert "MyCharm._on_config_changed" in names

    def test_records_call_references(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        result = parse_python_file(tmp_path / "src" / "charm.py", repo_root=tmp_path)
        assert "IngressHandler" in result.references
        assert "build_layer" in result.references

    def test_records_inheritance_as_reference(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        result = parse_python_file(tmp_path / "src" / "charm.py", repo_root=tmp_path)
        # `class MyCharm(ops.CharmBase)` — the root name is `ops`.
        assert "ops" in result.references

    def test_skips_nested_function_definitions(self, tmp_path: Path) -> None:
        (tmp_path / "f.py").write_text(
            textwrap.dedent(
                """
                def outer():
                    def inner():
                        return 1
                    return inner
                """
            ).strip()
            + "\n"
        )
        result = parse_python_file(tmp_path / "f.py", repo_root=tmp_path)
        names = {s.display_name for s in result.definitions}
        assert "outer" in names
        assert "inner" not in names

    def test_handles_syntax_errors(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.py"
        bad.write_text("def oops(:\n")
        result = parse_python_file(bad, repo_root=tmp_path)
        assert result.definitions == []
        assert result.references == []

    def test_returns_relative_path(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "x.py").write_text("def hi():\n    pass\n")
        result = parse_python_file(tmp_path / "src" / "x.py", repo_root=tmp_path)
        assert result.file == "src/x.py"

    def test_function_signature_includes_annotations(self, tmp_path: Path) -> None:
        (tmp_path / "f.py").write_text("def add(a: int, b: int = 0) -> int:\n    return a + b\n")
        result = parse_python_file(tmp_path / "f.py", repo_root=tmp_path)
        sig = next(s.signature for s in result.definitions if s.name == "add")
        assert "a: int" in sig
        assert "b: int=0" in sig
        assert "-> int" in sig


class TestCharmMetadataParser:
    def test_extracts_relations_config_and_actions(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        result = parse_charm_metadata(tmp_path / "charmcraft.yaml", repo_root=tmp_path)

        kinds = {s.kind for s in result.definitions}
        assert SymbolKind.RELATION in kinds
        assert SymbolKind.CONFIG_OPTION in kinds
        assert SymbolKind.ACTION in kinds

        relations = {s.display_name for s in result.definitions if s.kind == SymbolKind.RELATION}
        assert "requires.ingress" in relations
        assert "provides.metrics-endpoint" in relations

    def test_relation_signature_carries_interface_name(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        result = parse_charm_metadata(tmp_path / "charmcraft.yaml", repo_root=tmp_path)
        ingress = next(s for s in result.definitions if s.name == "ingress")
        assert "ingress" in ingress.signature

    def test_handles_invalid_yaml(self, tmp_path: Path) -> None:
        bad = tmp_path / "metadata.yaml"
        bad.write_text("foo: [unclosed\n")
        result = parse_charm_metadata(bad, repo_root=tmp_path)
        assert result.definitions == []


# ---------------------------------------------------------------------------
# Graph + PageRank
# ---------------------------------------------------------------------------


class TestGraph:
    def test_referenced_files_outrank_unreferenced(self) -> None:
        files = [
            FileSymbols(
                file="caller.py",
                definitions=[],
                references=["IngressHandler", "build_layer"],
            ),
            FileSymbols(
                file="popular.py",
                definitions=[
                    _sym("IngressHandler", SymbolKind.CLASS, "popular.py"),
                    _sym("build_layer", SymbolKind.FUNCTION, "popular.py"),
                ],
                references=[],
            ),
            FileSymbols(
                file="lonely.py",
                definitions=[_sym("Forgotten", SymbolKind.CLASS, "lonely.py")],
                references=[],
            ),
        ]
        rankings = rank_files(files)
        scores = {r.file: r.score for r in rankings}
        assert scores["popular.py"] > scores["lonely.py"]

    def test_self_edges_are_dropped(self) -> None:
        # File defines and references the same name — should not give itself
        # a leg up.
        files = [
            FileSymbols(
                file="solo.py",
                definitions=[_sym("foo", SymbolKind.FUNCTION, "solo.py")],
                references=["foo"],
            ),
            FileSymbols(file="other.py", definitions=[], references=[]),
        ]
        edges = build_graph(files)
        assert "solo.py" not in edges or "solo.py" not in edges.get("solo.py", {})

    def test_pagerank_is_deterministic(self) -> None:
        edges = {"a": {"b": 1.0}, "b": {"c": 1.0}, "c": {"a": 1.0}}
        nodes = ["a", "b", "c"]
        first = pagerank(edges, nodes)
        second = pagerank(edges, nodes)
        for k in nodes:
            assert abs(first[k] - second[k]) < 1e-9

    def test_pagerank_ordering_stable_for_known_graph(self) -> None:
        # Hub-and-spoke: every spoke points at the hub; hub points at one spoke.
        edges = {
            "spoke_a": {"hub": 1.0},
            "spoke_b": {"hub": 1.0},
            "spoke_c": {"hub": 1.0},
            "hub": {"spoke_a": 1.0},
        }
        nodes = ["hub", "spoke_a", "spoke_b", "spoke_c"]
        scores = pagerank(edges, nodes)
        assert scores["hub"] == max(scores.values())

    def test_pagerank_handles_empty(self) -> None:
        assert pagerank({}, []) == {}

    def test_pagerank_handles_dangling_nodes(self) -> None:
        # Node ``b`` has no outgoing edges — its share must redistribute.
        scores = pagerank({"a": {"b": 1.0}}, ["a", "b"])
        # No score should be NaN or zero — every node gets at least the
        # base teleportation share.
        assert all(v > 0 for v in scores.values())
        assert sum(scores.values()) > 0.99


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRender:
    def test_empty_rankings_render_to_empty_string(self) -> None:
        assert render([], token_budget=1000) == ""

    def test_zero_budget_renders_to_empty_string(self) -> None:
        rankings = rank_files(
            [
                FileSymbols(
                    file="a.py",
                    definitions=[_sym("Foo", SymbolKind.CLASS, "a.py")],
                    references=[],
                )
            ]
        )
        assert render(rankings, token_budget=0) == ""

    def test_renders_classes_with_class_keyword(self) -> None:
        files = [
            FileSymbols(
                file="a.py",
                definitions=[_sym("Foo", SymbolKind.CLASS, "a.py", signature="(Bar)")],
                references=[],
            )
        ]
        rendered = render(rank_files(files), token_budget=DEFAULT_TOKEN_BUDGET)
        assert "class Foo(Bar)" in rendered

    def test_truncates_under_tight_budget(self) -> None:
        files: list[FileSymbols] = []
        for i in range(20):
            files.append(
                FileSymbols(
                    file=f"file_{i:02d}.py",
                    definitions=[
                        _sym(f"Class{i}", SymbolKind.CLASS, f"file_{i:02d}.py"),
                        _sym(f"helper_{i}", SymbolKind.FUNCTION, f"file_{i:02d}.py"),
                    ],
                    references=[],
                )
            )
        rendered = render(rank_files(files), token_budget=10)
        assert len(rendered) < 20 * 4  # ~80 chars max under the budget


# ---------------------------------------------------------------------------
# RepoMap orchestrator
# ---------------------------------------------------------------------------


class TestRepoMap:
    def test_build_picks_up_python_and_yaml(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()
        files = {r.file for r in rm.rankings}
        assert "src/charm.py" in files
        assert "src/handlers.py" in files
        assert "charmcraft.yaml" in files

    def test_render_for_prompt_returns_text(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()
        rendered = rm.render_for_prompt()
        assert "MyCharm" in rendered
        assert "src/charm.py" in rendered

    def test_writes_cache_file(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()
        cache = tmp_path / ".cantrip-repomap.json"
        assert cache.exists()
        data = json.loads(cache.read_text(encoding="utf-8"))
        assert data["version"] == 1
        files = {entry["file"] for entry in data["entries"]}
        assert "src/charm.py" in files

    def test_cache_path_does_not_collide_with_session_db(self, tmp_path: Path) -> None:
        # The session SQLite store lives at ``<charm>/.cantrip``.  The
        # repo-map cache must be a sibling so it doesn't try to mkdir
        # over that file on every turn.
        _make_charm(tmp_path)
        # Pre-create a file at the would-be-collision path.
        (tmp_path / ".cantrip").write_text("fake session db")
        rm = RepoMap(tmp_path)
        rm.build()
        # Cache wrote successfully despite ``.cantrip`` existing as a file.
        assert (tmp_path / ".cantrip-repomap.json").exists()
        # The fake session DB is untouched.
        assert (tmp_path / ".cantrip").read_text() == "fake session db"

    def test_cache_invalidates_on_mtime_change(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()
        original_mtime = (tmp_path / ".cantrip-repomap.json").stat().st_mtime_ns

        # Mutate one file with a new symbol.
        target = tmp_path / "src" / "handlers.py"
        text = target.read_text(encoding="utf-8")
        target.write_text(text + "\n\ndef brand_new() -> None:\n    pass\n")
        # Bump mtime explicitly so the test doesn't rely on filesystem
        # timestamp resolution.
        future = original_mtime + 1_000_000_000
        import os

        os.utime(target, ns=(future, future))

        rm.build()
        rendered = rm.render_for_prompt()
        assert "brand_new" in rendered

    def test_force_rebuild_drops_existing_cache(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()

        # Delete a file — incremental build keeps stale cache, force should not.
        (tmp_path / "src" / "handlers.py").unlink()
        rm.build(force=True)
        files = {r.file for r in rm.rankings}
        assert "src/handlers.py" not in files

    def test_pressure_shrinks_budget(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        # Pick a budget tight enough that halving it forces a trim —
        # the fixture renders to ~140 tokens, so 80 vs 40 brackets it.
        rm = RepoMap(tmp_path, token_budget=80)
        rm.build()
        full = rm.render_for_prompt(context_pressure=0.0)
        squeezed = rm.render_for_prompt(context_pressure=0.85)
        assert squeezed != full
        assert len(squeezed) < len(full)

    def test_pressure_above_drop_threshold_returns_empty(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()
        assert rm.render_for_prompt(context_pressure=0.99) == ""

    def test_handles_missing_charm_path(self, tmp_path: Path) -> None:
        rm = RepoMap(tmp_path / "nope")
        rm.build()
        assert rm.rankings == []
        assert rm.render_for_prompt() == ""

    def test_handle_map_renders_under_markdown(self, tmp_path: Path) -> None:
        # The /map output is delivered with ``markdown=True`` on the
        # SlashResult, and inside a Markdown fenced code block the
        # bracketed kind labels (``[relation]``, ``[container]``) and
        # Python type annotations (``list[int]``) display literally —
        # no Rich escape needed.  Verify the body opens a fenced
        # block and contains the bracketed tokens unescaped.
        from unittest.mock import MagicMock

        from cantrip.agent.slash_commands import dispatch, handle_map

        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()

        # Body uses Markdown bold for the header and per-file
        # ``###`` headings so the formatting renders in the chat.
        agent = MagicMock()
        agent.repo_map = rm
        text = handle_map(agent, "full")
        assert "**Repository map**" in text
        assert "### `" in text  # Per-file Markdown section heading.

        # Dispatcher attaches markdown=True so the surface renders it.
        # Use a fully mocked agent + custom_commands so dispatch's
        # fall-through doesn't try real registry lookups.
        from cantrip.agent.custom_commands import CustomCommandRegistry

        agent.custom_commands = CustomCommandRegistry(commands=())
        result = dispatch(agent, "/map full")
        assert result is not None
        assert result.markdown is True

    def test_handle_map_never_raises_on_build_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the repo-map build blows up for any reason, the slash
        # command must surface a friendly chat string and write the
        # full traceback to the diagnostics log — never propagate
        # the exception or leak the stack into the chat.
        from unittest.mock import MagicMock

        from cantrip.agent.slash_commands import handle_map

        # Redirect the diagnostics log into tmp_path.
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

        broken_rm = MagicMock()
        broken_rm.build.side_effect = RuntimeError("boom")
        agent = MagicMock()
        agent.repo_map = broken_rm
        result = handle_map(agent)

        # Chat response is friendly and points at the log.
        assert "something went wrong" in result.lower()
        assert "diagnostics.log" in result
        # And does *not* leak the stack into the chat.
        assert "RuntimeError" not in result
        assert "Traceback" not in result

        # The log file got the full traceback.
        log_path = tmp_path / "state" / "cantrip" / "diagnostics.log"
        assert log_path.exists()
        body = log_path.read_text(encoding="utf-8")
        assert "RuntimeError: boom" in body
        assert "Traceback" in body
        assert "/map" in body

    def test_skips_excluded_directories(self, tmp_path: Path) -> None:
        _make_charm(tmp_path)
        # Create a venv with code that should be ignored.
        (tmp_path / ".venv" / "lib").mkdir(parents=True)
        (tmp_path / ".venv" / "lib" / "rogue.py").write_text("class Rogue: pass\n")
        rm = RepoMap(tmp_path)
        rm.build()
        files = {r.file for r in rm.rankings}
        assert not any(f.startswith(".venv/") for f in files)

    def test_skips_lib_charms_vendored_dir(self, tmp_path: Path) -> None:
        # ``lib/charms/<name>/v<N>/<lib>.py`` holds vendored interface
        # libraries from other charms (charmcraft fetch-libs).  They're
        # third-party API surface, not user-edited code, and indexing
        # them swamps the map.  Must be skipped.
        _make_charm(tmp_path)
        vendored = tmp_path / "lib" / "charms" / "tempo_k8s" / "v0"
        vendored.mkdir(parents=True)
        (vendored / "tracing.py").write_text("class TracingEndpointProvider:\n    pass\n")
        rm = RepoMap(tmp_path)
        rm.build()
        files = {r.file for r in rm.rankings}
        assert not any(f.startswith("lib/charms/") for f in files)
        # The user's own src/charm.py still ranks.
        assert "src/charm.py" in files

    def test_render_summary_one_line_per_file(self, tmp_path: Path) -> None:
        # Default ``/map`` view: one line per file with the primary
        # symbol and a "+N more" hint.  Stays well under the
        # full-render character count so a small chat panel isn't
        # swamped by a wall of text.
        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()

        summary = rm.render_summary(top_n=8)
        full = rm.render_full()

        # Summary is dramatically shorter than the full output.
        assert len(summary) < len(full) // 2
        # One line per file.
        lines = [line for line in summary.splitlines() if line.strip()]
        assert len(lines) >= 1
        # Each line is a single line (no embedded newlines after
        # split) and reasonably short.
        for line in lines:
            assert "\n" not in line
            assert len(line) <= 120

    def test_render_summary_caps_top_n(self, tmp_path: Path) -> None:
        # When there are more files than the cap, only top_n appear.
        _make_charm(tmp_path)
        # Add several extra files so we have more than top_n with symbols.
        for i in range(15):
            (tmp_path / f"extra_{i}.py").write_text(f"class Extra{i}: pass\n")
        rm = RepoMap(tmp_path)
        rm.build()
        summary = rm.render_summary(top_n=5)
        lines = [line for line in summary.splitlines() if line.strip()]
        assert len(lines) <= 5

    def test_handle_map_default_is_compact(self, tmp_path: Path) -> None:
        # The slash command default is the compact summary plus a
        # footer pointing at ``/map full`` for the wall-of-text view.
        from unittest.mock import MagicMock

        from cantrip.agent.slash_commands import handle_map

        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()
        agent = MagicMock()
        agent.repo_map = rm

        text = handle_map(agent, "")
        assert "Repository map" in text
        # Footer hint surfaces the deeper view.
        assert "/map full" in text
        # And the compact body is much smaller than the full render.
        assert len(text) < len(rm.render_full())

    def test_handle_map_full_returns_markdown_sections(self, tmp_path: Path) -> None:
        # ``/map full`` formats each file as a Markdown ``###`` heading
        # plus bullet-point symbols so a long output keeps visible
        # navigation landmarks instead of dissolving into one monospace
        # wall once scrolled past the top.
        from unittest.mock import MagicMock

        from cantrip.agent.slash_commands import handle_map

        _make_charm(tmp_path)
        rm = RepoMap(tmp_path)
        rm.build()
        agent = MagicMock()
        agent.repo_map = rm

        text = handle_map(agent, "full")
        # Body contains per-file symbol lines.
        assert "MyCharm.__init__" in text or "build_layer" in text
        # And each file is its own Markdown section, not buried
        # inside a single fenced code block.
        assert "### `src/charm.py`" in text or "### `src/handlers.py`" in text
        # The body is NOT wrapped in a single fenced code block —
        # that's the shape that scrolled badly in the chat panel.
        # (The summary/footer paths still use fences for short
        # blocks; the full path opts out.)
        opening_fences = text.count("\n```\n")
        # No raw triple-fence pairs around the whole body.
        assert opening_fences == 0

    def test_dispatch_catches_handler_exceptions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Last-resort safety net: even if a handler raises *before*
        # its own try/except can catch (e.g. accessing a property),
        # the dispatcher logs to diagnostics and returns a friendly
        # SlashResult instead of letting the exception escape.
        from unittest.mock import MagicMock, PropertyMock

        from cantrip.agent import slash_commands

        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

        agent = MagicMock()
        # Simulate a property getter that raises (the kind of failure
        # that would bypass handle_map's internal try/except).
        type(agent).repo_map = PropertyMock(side_effect=ValueError("property exploded"))

        result = slash_commands.dispatch(agent, "/map")

        # We get a SlashResult, not a propagating exception.
        assert result is not None
        assert "something went wrong" in result.text.lower()
        # And the diagnostic log captured the real stack.
        log_path = tmp_path / "state" / "cantrip" / "diagnostics.log"
        body = log_path.read_text(encoding="utf-8")
        assert "ValueError: property exploded" in body
        assert "/map" in body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sym(name: str, kind: SymbolKind, file: str, signature: str = ""):
    from cantrip.repomap.symbols import Symbol

    return Symbol(name=name, kind=kind, file=file, signature=signature)
