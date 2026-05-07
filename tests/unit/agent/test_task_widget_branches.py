"""Branch-coverage backfill for ``cantrip.tui.widgets.tasks``.

The base ``test_task_widget.py`` covers the happy-path rendering and
click flow against the headless Pilot.  This file fills the remaining
small branches:

- ``_elapsed_label`` time-range branches (None / negative / minutes / hours)
- ``_subagent_line`` no-elapsed branch
- ``_format_detail`` description truncation
- ``set_agent_activity`` change-detection
- ``add_preflight_group`` + ``update_preflight`` lifecycle and bounds
- ``on_click`` non-Click / NoWidget / category-row branches
- ``_is_group_collapsed`` empty-group branch
- ``_refresh_display`` no-container short-circuit
- Preflight rendering (in-progress vs collapsed)
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from cantrip.agent.preflight import CheckStatus
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.tui.widgets import tasks as tasks_widget
from cantrip.tui.widgets.tasks import (
    TaskChecklistWidget,
    _CategoryHeader,
    _CollapsedGroupRow,
    _elapsed_label,
    _format_detail,
    _subagent_line,
    _TaskDetail,
    _TaskRow,
)
from tests.unit.agent.test_task_widget import _ChecklistApp, _make_task

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


class TestElapsedLabel:
    """``_elapsed_label`` covers None / negative / seconds / minutes / hours."""

    def test_none_returns_empty(self) -> None:
        assert _elapsed_label(None) == ""

    def test_future_start_returns_empty(self) -> None:
        """Negative deltas (clock skew) shouldn't render as ``-3s``."""
        future = datetime.datetime.now() + datetime.timedelta(seconds=10)
        assert _elapsed_label(future) == ""

    def test_seconds_format(self) -> None:
        started = datetime.datetime.now() - datetime.timedelta(seconds=12)
        # Floor to >= 12 seconds, allowing ~1s scheduling slop.
        assert _elapsed_label(started) in ("12s", "13s")

    def test_minutes_format(self) -> None:
        started = datetime.datetime.now() - datetime.timedelta(minutes=3, seconds=14)
        label = _elapsed_label(started)
        assert label.startswith("3m")
        # Format is ``{minutes}m{seconds:02d}s`` — e.g. "3m14s" (5 chars)
        # or "3m15s" if scheduling slop bumps the second count.
        assert label.endswith("s")
        assert len(label) == 5

    def test_hours_format(self) -> None:
        started = datetime.datetime.now() - datetime.timedelta(hours=1, minutes=5)
        label = _elapsed_label(started)
        assert label.startswith("1h")
        assert label.endswith("m")
        # e.g. "1h05m" — minutes are zero-padded.
        assert "m" in label and label.split("h")[1].endswith("m")


class TestSubagentLine:
    """``_subagent_line`` returns None / no-elapsed / with-elapsed shapes."""

    def test_returns_none_without_phase(self) -> None:
        task = _make_task()
        task.subagent_phase = ""
        assert _subagent_line(task) is None

    def test_no_elapsed_omits_dot_separator(self) -> None:
        """If the start timestamp is missing, the line shows the phase
        on its own — no dangling ``·`` separator."""
        task = _make_task()
        task.subagent_phase = "thinking"
        task.subagent_started_at = None
        assert _subagent_line(task) == "  └ thinking"

    def test_with_elapsed_renders_phase_and_duration(self) -> None:
        task = _make_task()
        task.subagent_phase = "running: charmcraft_pack"
        task.subagent_started_at = datetime.datetime.now() - datetime.timedelta(seconds=5)
        line = _subagent_line(task)
        assert line is not None
        assert "running: charmcraft_pack" in line
        assert "·" in line  # the middle dot separator


class TestFormatDetailDescriptionTruncation:
    """The 200-char description truncation branch (mirror of result truncation)."""

    def test_long_description_truncates_with_ellipsis(self) -> None:
        task = _make_task(description="a" * 300)
        detail = _format_detail(task)
        # The detail block prefixes with "Info: " then 197 chars + "...".
        assert "..." in detail
        # Description body should not appear in full.
        assert "a" * 300 not in detail


# ---------------------------------------------------------------------------
# Inner-row dataclasses (Static subclasses)
# ---------------------------------------------------------------------------


class TestRowSubclasses:
    """The four ``Static`` subclasses store their identity for click routing."""

    def test_task_row_stores_task_id(self) -> None:
        row = _TaskRow("t1", "content")
        assert row.task_id == "t1"

    def test_task_detail_stores_task_id(self) -> None:
        detail = _TaskDetail("t1", "content")
        assert detail.task_id == "t1"

    def test_collapsed_group_row_stores_category(self) -> None:
        row = _CollapsedGroupRow(TaskCategory.BUILD, "Build · 3 tasks")
        assert row.category == TaskCategory.BUILD

    def test_category_header_stores_category(self) -> None:
        header = _CategoryHeader(TaskCategory.RESEARCH, "Research")
        assert header.category == TaskCategory.RESEARCH


# ---------------------------------------------------------------------------
# Pilot-driven branches
# ---------------------------------------------------------------------------


class TestSetAgentActivityChangeDetection:
    """``set_agent_activity`` short-circuits when the label is unchanged.

    The widget polls every 0.5s; without the dedup, every poll would
    flip ``_dirty`` and re-render even when nothing changed."""

    @pytest.mark.asyncio
    async def test_repeat_set_with_same_label_doesnt_dirty(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            checklist.set_agent_activity("Planning tasks…")
            # First call set the activity; clear dirty manually so the
            # next call has a clean baseline.
            checklist._dirty = False
            checklist.set_agent_activity("Planning tasks…")
            assert checklist._dirty is False

    @pytest.mark.asyncio
    async def test_set_to_different_label_marks_dirty(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            checklist.set_agent_activity("Planning tasks…")
            checklist._dirty = False
            checklist.set_agent_activity("Generating fixes…")
            assert checklist._dirty is True

    @pytest.mark.asyncio
    async def test_clear_with_none(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            checklist.set_agent_activity("Planning tasks…")
            checklist.set_agent_activity(None)
            assert checklist._agent_activity is None


class TestPreflightGroups:
    """``add_preflight_group`` + ``update_preflight`` lifecycle and bounds.

    The preflight list shows up at the top of the task pane during
    ``cantrip prepare`` / ``bootstrap``; the indices returned by
    ``add_preflight_group`` are how the worker callback addresses
    individual checks."""

    @pytest.mark.asyncio
    async def test_add_returns_increasing_indices(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            idx0 = checklist.add_preflight_group("Concierge", ["A", "B"])
            idx1 = checklist.add_preflight_group("Bootstrap", ["X"])
            assert idx0 == 0
            assert idx1 == 1

    @pytest.mark.asyncio
    async def test_update_passes_through_to_named_item(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            idx = checklist.add_preflight_group("Concierge", ["A", "B"])
            checklist.update_preflight(idx, 1, CheckStatus.PASSED)
            await pilot.pause(delay=0.7)
            container = checklist.query_one("#task-container")
            combined = " ".join(str(s.render()) for s in container.query("Static"))
            assert "Concierge" in combined
            assert "B" in combined
            # The PASSED check uses the ✓ glyph from _CHECK_STATUS_DISPLAY.
            assert "✓" in combined

    @pytest.mark.asyncio
    async def test_update_out_of_range_group_is_silent(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            # No group has been added — the update must be a noop.
            checklist.update_preflight(0, 0, CheckStatus.PASSED)
            assert checklist._dirty is False

    @pytest.mark.asyncio
    async def test_update_out_of_range_item_is_silent(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            idx = checklist.add_preflight_group("Concierge", ["A"])
            checklist._dirty = False
            # Index 5 doesn't exist in a single-item group.
            checklist.update_preflight(idx, 5, CheckStatus.FAILED)
            assert checklist._dirty is False

    @pytest.mark.asyncio
    async def test_fully_passed_group_collapses_to_summary_row(self) -> None:
        """When every check in a group is PASSED, the renderer folds it
        into a single ``✓ <title> · ready`` line."""
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            idx = checklist.add_preflight_group("Concierge", ["A", "B"])
            checklist.update_preflight(idx, 0, CheckStatus.PASSED)
            checklist.update_preflight(idx, 1, CheckStatus.PASSED)
            await pilot.pause(delay=0.7)
            container = checklist.query_one("#task-container")
            combined = " ".join(str(s.render()) for s in container.query("Static"))
            assert "Concierge · ready" in combined
            # Individual labels disappear in the collapsed form.
            assert "○ A" not in combined
            assert "○ B" not in combined


class TestOnClickBranches:
    """``on_click`` is the dispatcher between row clicks and toggle methods.

    The base file covers the happy paths via ``_toggle_*``; this fills
    the type / NoWidget / parent-walk branches that don't fire in the
    direct calls."""

    @pytest.mark.asyncio
    async def test_non_click_event_is_ignored(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            with (
                patch.object(checklist, "_toggle_detail") as toggle_detail,
                patch.object(checklist, "_toggle_group") as toggle_group,
            ):
                # Pass an arbitrary object — the early ``isinstance`` guard
                # must short-circuit without consulting the screen.
                checklist.on_click(MagicMock())
                toggle_detail.assert_not_called()
                toggle_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_widget_at_click_is_ignored(self) -> None:
        """If ``get_widget_at`` raises ``NoWidget``, the handler returns
        cleanly — clicking on margin shouldn't raise."""
        from textual.events import Click
        from textual.screen import NoWidget

        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            click = Click(
                widget=None,
                x=0,
                y=0,
                delta_x=0,
                delta_y=0,
                button=1,
                shift=False,
                meta=False,
                ctrl=False,
            )
            with (
                patch.object(checklist.screen, "get_widget_at", side_effect=NoWidget("nope")),
                patch.object(checklist, "_toggle_detail") as toggle_detail,
                patch.object(checklist, "_toggle_group") as toggle_group,
            ):
                checklist.on_click(click)
                toggle_detail.assert_not_called()
                toggle_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_click_on_collapsed_group_row_toggles_group(self) -> None:
        """Clicking a ``_CollapsedGroupRow`` walks back to its category
        and routes through ``_toggle_group``."""
        from textual.events import Click

        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            checklist.notify_changed(
                [_make_task("Done", status=TaskStatus.DONE, category=TaskCategory.RESEARCH)]
            )
            await pilot.pause(delay=0.7)
            # Find the collapsed-group row that was rendered.
            row = next(w for w in checklist.query("Static") if isinstance(w, _CollapsedGroupRow))
            click = Click(
                widget=row,
                x=0,
                y=0,
                delta_x=0,
                delta_y=0,
                button=1,
                shift=False,
                meta=False,
                ctrl=False,
            )
            with (
                patch.object(checklist.screen, "get_widget_at", return_value=(row, None)),
                patch.object(checklist, "_toggle_group") as toggle_group,
            ):
                checklist.on_click(click)
                toggle_group.assert_called_once_with(TaskCategory.RESEARCH)

    @pytest.mark.asyncio
    async def test_click_on_unrelated_widget_walks_until_widget_boundary(self) -> None:
        """A click on a widget that isn't a row still walks the parent
        chain and bails when it hits the checklist itself."""
        from textual.events import Click

        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            click = Click(
                widget=checklist,
                x=0,
                y=0,
                delta_x=0,
                delta_y=0,
                button=1,
                shift=False,
                meta=False,
                ctrl=False,
            )
            with (
                patch.object(
                    checklist.screen,
                    "get_widget_at",
                    return_value=(checklist, None),
                ),
                patch.object(checklist, "_toggle_detail") as toggle_detail,
                patch.object(checklist, "_toggle_group") as toggle_group,
            ):
                checklist.on_click(click)
                toggle_detail.assert_not_called()
                toggle_group.assert_not_called()


class TestRefreshDisplayEdgeCases:
    """Bits of ``_refresh_display`` that the base tests don't naturally hit."""

    def test_refresh_with_no_container_returns_silently(self) -> None:
        """Before mount the ``#task-container`` query returns an empty
        DOMQuery; the refresh path must bail without crashing."""
        widget = TaskChecklistWidget()
        # No app, no mount — query returns an empty DOMQuery.
        widget._refresh_display()  # must not raise

    @pytest.mark.asyncio
    async def test_agent_activity_row_renders_when_queue_empty(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            checklist.set_agent_activity("Planning tasks…")
            await pilot.pause(delay=0.7)
            container = checklist.query_one("#task-container")
            combined = " ".join(str(s.render()) for s in container.query("Static"))
            assert "Planning tasks…" in combined
            assert "⟳" in combined  # active glyph

    @pytest.mark.asyncio
    async def test_is_group_collapsed_returns_false_for_empty_category(self) -> None:
        """When a category has no eligible tasks (everything pinned) the
        collapse predicate returns False so the renderer skips the group
        instead of showing an empty summary row."""
        widget = TaskChecklistWidget()
        widget._tasks = [
            _make_task("Active build", status=TaskStatus.ACTIVE, category=TaskCategory.BUILD)
        ]
        # BUILD has only an ACTIVE task (pinned) — eligible group is empty.
        assert widget._is_group_collapsed(TaskCategory.BUILD) is False

    @pytest.mark.asyncio
    async def test_is_group_collapsed_respects_explicit_collapse_override(self) -> None:
        widget = TaskChecklistWidget()
        widget._tasks = [
            _make_task("Pending", status=TaskStatus.PENDING, category=TaskCategory.BUILD)
        ]
        widget._collapsed_groups.add(TaskCategory.BUILD)
        assert widget._is_group_collapsed(TaskCategory.BUILD) is True


class TestPreflightInProgressRendering:
    """Preflight groups not yet fully PASSED render header + per-item rows.

    Complements ``test_fully_passed_group_collapses_to_summary_row``: a
    group with at least one non-PASSED check renders the title-bar +
    divider + per-item form."""

    @pytest.mark.asyncio
    async def test_in_progress_group_renders_each_item(self) -> None:
        app = _ChecklistApp.build()
        async with app.run_test() as pilot:
            checklist = pilot.app.query_one("#task-checklist", TaskChecklistWidget)
            idx = checklist.add_preflight_group("Concierge", ["A", "B"])
            checklist.update_preflight(idx, 0, CheckStatus.PASSED)
            checklist.update_preflight(idx, 1, CheckStatus.RUNNING)
            await pilot.pause(delay=0.7)
            container = checklist.query_one("#task-container")
            combined = " ".join(str(s.render()) for s in container.query("Static"))
            # Title + items appear; not the collapsed ``· ready`` form.
            assert "Concierge" in combined
            assert "A" in combined
            assert "B" in combined
            assert "ready" not in combined


# Sanity check that the module-level constant ordering is the contract
# the renderer relies on.  Putting it here keeps the import live for
# coverage on the constant file.


def test_pinned_statuses_constant_is_complete() -> None:
    assert (
        frozenset({TaskStatus.ACTIVE, TaskStatus.FAILED, TaskStatus.BLOCKED})
        == tasks_widget._PINNED_STATUSES
    )


def test_make_task_helper_is_importable() -> None:
    """The shared helper from ``test_task_widget`` should keep working
    so this branches file doesn't drift apart from the base file."""
    task = _make_task("X")
    assert isinstance(task, AgentTask)
