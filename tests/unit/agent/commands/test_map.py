"""Tests for ``/map`` and ``/map-refresh`` (Phase 85.3 slash surface).

The handlers read a single attribute off the agent — ``repo_map`` — and
call ``build`` / ``render_summary`` / ``render_full_markdown`` on it.  A
:class:`SimpleNamespace` stand-in is enough; these tests pin the
summary-vs-full toggle, the empty / absent paths, and the diagnostics
fallback when the underlying map raises.
"""

from __future__ import annotations

from types import SimpleNamespace

from cantrip.agent.commands.map import handle_map, handle_map_refresh


class _FakeRepoMap:
    """Smallest repo-map shape the /map handlers exercise.

    ``summary`` / ``full`` are the two rendered bodies; ``rankings`` is
    only ever measured with ``len`` so a plain list of sentinels is fine.
    ``raise_on_build`` forces the diagnostics fallback path.
    """

    def __init__(
        self,
        *,
        summary: str = "charm.py  Charm",
        full: str = "## charm.py\n- Charm",
        rankings: int = 3,
        raise_on_build: bool = False,
    ) -> None:
        self.summary = summary
        self.full = full
        self.rankings = list(range(rankings))
        self._raise = raise_on_build
        self.build_calls: list[bool] = []

    def build(self, force: bool = False) -> None:
        self.build_calls.append(force)
        if self._raise:
            raise RuntimeError("parse exploded")

    def render_summary(self) -> str:
        return self.summary

    def render_full_markdown(self) -> str:
        return self.full


def _agent(repo_map: _FakeRepoMap | None) -> SimpleNamespace:
    return SimpleNamespace(repo_map=repo_map)


class TestHandleMap:
    def test_no_repo_map_explains_absence(self) -> None:
        result = handle_map(_agent(None))
        assert "No repository map" in result
        assert "active charm path" in result

    def test_summary_renders_with_footer_and_count(self) -> None:
        rm = _FakeRepoMap(summary="a\nb", rankings=5)
        result = handle_map(_agent(rm))
        # Summary view shows "showing N of M" because the rendered body
        # has fewer lines (2) than the ranking count (5).
        assert "showing 2 of 5 files" in result
        assert "/map full" in result
        assert "```" in result  # fenced summary
        assert rm.build_calls == [False]

    def test_full_view_unfenced(self) -> None:
        rm = _FakeRepoMap()
        result = handle_map(_agent(rm), "full")
        assert "Repository map" in result
        # Full view skips the triple-backtick wrapper so per-file
        # headings keep their own structure.
        assert "## charm.py" in result
        assert "```" not in result

    def test_empty_render_reports_no_parseable_files(self) -> None:
        rm = _FakeRepoMap(summary="")
        result = handle_map(_agent(rm))
        assert "Repository map is empty" in result

    def test_build_failure_routes_to_diagnostics(self) -> None:
        rm = _FakeRepoMap(raise_on_build=True)
        result = handle_map(_agent(rm))
        # diagnostics.report_internal_error mentions the command name and
        # points at a log path rather than leaking the traceback.
        assert "/map" in result


class TestHandleMapRefresh:
    def test_no_repo_map(self) -> None:
        result = handle_map_refresh(_agent(None))
        assert "No repository map" in result

    def test_refresh_forces_rebuild(self) -> None:
        rm = _FakeRepoMap(summary="a\nb", rankings=4)
        result = handle_map_refresh(_agent(rm))
        assert rm.build_calls == [True]
        assert "Repository map rebuilt" in result
        assert "/map-refresh full" in result

    def test_refresh_full_view(self) -> None:
        rm = _FakeRepoMap()
        result = handle_map_refresh(_agent(rm), "full")
        assert "Repository map rebuilt" in result
        assert "## charm.py" in result

    def test_refresh_empty_render(self) -> None:
        rm = _FakeRepoMap(summary="")
        result = handle_map_refresh(_agent(rm))
        assert "no parseable files" in result

    def test_refresh_build_failure_routes_to_diagnostics(self) -> None:
        rm = _FakeRepoMap(raise_on_build=True)
        result = handle_map_refresh(_agent(rm))
        assert "/map-refresh" in result
