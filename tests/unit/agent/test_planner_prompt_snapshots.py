"""Snapshot tests for the extracted planner prompt templates.

Phase 53.1 moved three prompt constants out of ``planner.py`` into Jinja2
templates under ``src/cantrip/agent/prompts/planning/``.  These tests
freeze the rendered output so accidental template edits surface as a
diff rather than a silent behaviour change.

Phase 114.3 ported them from SHA256 + length assertions to ``syrupy``
snapshots: the on-disk snapshot lives in
``__snapshots__/test_planner_prompt_snapshots.ambr`` next to this file
and a deliberate template edit shows up as a readable text diff.  After
an intentional change, regenerate with::

    uv run pytest tests/unit/agent/test_planner_prompt_snapshots.py --snapshot-update

and commit the updated ``.ambr`` alongside the template.
"""

from __future__ import annotations

from cantrip.agent.planner import (
    PlanningContext,
    _build_day2_to_build_prompt,
    _build_design_to_build_prompt,
    _build_planning_prompt,
    _build_replanning_prompt,
)

_CANONICAL_CONTEXT = PlanningContext(
    intent="Build a charm for a fancy web app",
    charm_name="myapp",
    charm_type="kubernetes",
    framework="flask",
    source_url="https://example.com/repo",
)


def test_planning_prompt_snapshot(snapshot) -> None:
    assert _build_planning_prompt(_CANONICAL_CONTEXT) == snapshot


def test_design_to_build_prompt_snapshot(snapshot) -> None:
    assert _build_design_to_build_prompt(_CANONICAL_CONTEXT) == snapshot


def test_day2_to_build_prompt_snapshot(snapshot) -> None:
    assert _build_day2_to_build_prompt(_CANONICAL_CONTEXT) == snapshot


def test_replanning_prompt_snapshot(snapshot) -> None:
    assert _build_replanning_prompt(_CANONICAL_CONTEXT) == snapshot
