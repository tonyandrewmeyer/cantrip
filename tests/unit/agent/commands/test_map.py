"""Tests for ``/map`` and ``/map-refresh`` (Phase 114.1).

The handlers themselves are thin: they ask the repo map to build, pick
between the compact and full renderings, and wrap the result in the
Markdown envelope the chat surfaces expect.  What is worth pinning is
the *shape* of that envelope — the summary footer only appears when
something was actually elided, the full view is unfenced so per-file
headings survive, and every failure mode (no map, empty map, a build
that raises) produces prose rather than a traceback.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from cantrip.agent.commands import map as map_commands
from cantrip.agent.commands.map import handle_map, handle_map_refresh

if TYPE_CHECKING:
    import pathlib


class _StubRepoMap:
    """Minimal stand-in for :class:`cantrip.repomap.RepoMap`.

    Records ``build`` calls (and whether ``force`` was set) so the
    ``/map-refresh`` tests can assert the cache really is bypassed.
    ``raises`` makes ``build`` blow up so the diagnostics path is
    reachable without monkeypatching the real map.
    """

    def __init__(
        self,
        *,
        summary: str = "",
        full: str = "",
        rankings: int = 0,
        raises: Exception | None = None,
    ) -> None:
        self.summary = summary
        self.full = full
        self.rankings = list(range(rankings))
        self._raises = raises
        self.build_calls: list[bool] = []

    def build(self, force: bool = False) -> None:
        self.build_calls.append(force)
        if self._raises is not None:
            raise self._raises

    def render_summary(self) -> str:
        return self.summary

    def render_full_markdown(self) -> str:
        return self.full


def _agent(repo_map: _StubRepoMap | None) -> SimpleNamespace:
    return SimpleNamespace(repo_map=repo_map)


class TestWantsFull:
    """``/map full`` and its aliases opt into the wall-of-text view."""

    @pytest.mark.parametrize("args", ["full", "-v", "--verbose", "all"])
    def test_recognised_aliases(self, args: str) -> None:
        assert map_commands._wants_full(args) is True

    @pytest.mark.parametrize("args", ["  FULL  ", "All", "--VERBOSE"])
    def test_case_and_whitespace_insensitive(self, args: str) -> None:
        assert map_commands._wants_full(args) is True

    @pytest.mark.parametrize("args", ["", "brief", "full extra", "-vv"])
    def test_rejected(self, args: str) -> None:
        assert map_commands._wants_full(args) is False


class TestMap:
    """``/map`` — compact summary by default."""

    def test_no_repo_map_explains_why(self) -> None:
        text = handle_map(_agent(None))
        assert "No repository map" in text
        assert "active charm path" in text

    def test_empty_render_reports_nothing_parseable(self) -> None:
        rm = _StubRepoMap(summary="", rankings=0)
        text = handle_map(_agent(rm))
        assert "Repository map is empty" in text
        assert rm.build_calls == [False]

    def test_summary_includes_footer_hint(self) -> None:
        rm = _StubRepoMap(summary="src/charm.py  CharmBase", rankings=4)
        text = handle_map(_agent(rm))
        assert text.startswith("**Repository map**")
        assert "showing 1 of 4 files" in text
        assert "```" in text
        assert "Use `/map full`" in text

    def test_no_elision_omits_the_showing_clause(self) -> None:
        """One rendered line per ranked file means nothing was hidden."""
        rm = _StubRepoMap(summary="a\nb\nc", rankings=3)
        text = handle_map(_agent(rm))
        assert "**Repository map** (3 files)" in text
        assert "showing" not in text

    def test_full_view_is_unfenced(self) -> None:
        rm = _StubRepoMap(full="### src/charm.py\n\n- `CharmBase`", rankings=2)
        text = handle_map(_agent(rm), "full")
        assert "**Repository map** (2 files)" in text
        assert "### src/charm.py" in text
        assert "```" not in text
        # The full view is the whole story — no "use /map full" nudge.
        assert "/map full" not in text

    def test_build_failure_reports_via_diagnostics(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        rm = _StubRepoMap(raises=RuntimeError("tree-sitter exploded"))
        text = handle_map(_agent(rm))
        assert "/map" in text
        assert "tree-sitter exploded" not in text, "raw exception text must not reach chat"
        assert "diagnostics.log" in text


class TestMapRefresh:
    """``/map-refresh`` — same shape as ``/map`` but forces a reparse."""

    def test_no_repo_map_explains_why(self) -> None:
        assert "No repository map" in handle_map_refresh(_agent(None))

    def test_forces_a_rebuild(self) -> None:
        rm = _StubRepoMap(summary="src/charm.py  CharmBase", rankings=1)
        handle_map_refresh(_agent(rm))
        assert rm.build_calls == [True]

    def test_empty_render_reports_nothing_parseable(self) -> None:
        rm = _StubRepoMap(summary="", rankings=0)
        text = handle_map_refresh(_agent(rm))
        assert "Repository map rebuilt" in text
        assert "no parseable files" in text

    def test_summary_includes_refresh_specific_footer(self) -> None:
        rm = _StubRepoMap(summary="src/charm.py  CharmBase", rankings=9)
        text = handle_map_refresh(_agent(rm))
        assert text.startswith("**Repository map rebuilt**")
        assert "showing 1 of 9 files" in text
        assert "Use `/map-refresh full`" in text

    def test_full_view_is_unfenced(self) -> None:
        rm = _StubRepoMap(full="### src/charm.py", rankings=1)
        text = handle_map_refresh(_agent(rm), "full")
        assert "**Repository map rebuilt** (1 files)" in text
        assert "```" not in text

    def test_build_failure_reports_via_diagnostics(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        rm = _StubRepoMap(raises=OSError("permission denied"))
        text = handle_map_refresh(_agent(rm))
        assert "/map-refresh" in text
        assert "permission denied" not in text
