"""Snapshot tests for the extracted planner prompt templates.

Phase 53.1 moved three prompt constants out of ``planner.py`` into Jinja2
templates under ``src/cantrip/agent/prompts/planning/``.  These tests
freeze the rendered output so accidental template edits surface as a
diff rather than a silent behaviour change.  If a template is edited
deliberately, update the expected SHA256 to match.
"""

from __future__ import annotations

import hashlib

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

# SHA256 of the rendered prompt under _CANONICAL_CONTEXT, as frozen at
# the end of Phase 53.1.  Update these only when the templates change
# intentionally.
_EXPECTED_SHAS = {
    "planning": "28106149f28916df9aa32971540de859a847cb32f43d6f0ec9ded1beeca6c0ee",
    "design_to_build": "69bc63a9427c52b58e5b8c81a27d45dd5084d0aa424405c7f8095e330dfb539c",
    "day2_to_build": "3c8d21b0e3742a93cd9f62497fad95e8aa782355aa5d35e5dcadafe79af46765",
    "replanning": "92391d65816f3707e405a621128aa9358e5f247709e2c7628d25adc0f4b0abe4",
}

_EXPECTED_LENGTHS = {
    "planning": 4488,
    "design_to_build": 2785,
    "day2_to_build": 2413,
    "replanning": 4730,
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_planning_prompt_snapshot() -> None:
    output = _build_planning_prompt(_CANONICAL_CONTEXT)
    assert len(output) == _EXPECTED_LENGTHS["planning"]
    assert _sha(output) == _EXPECTED_SHAS["planning"]


def test_design_to_build_prompt_snapshot() -> None:
    output = _build_design_to_build_prompt(_CANONICAL_CONTEXT)
    assert len(output) == _EXPECTED_LENGTHS["design_to_build"]
    assert _sha(output) == _EXPECTED_SHAS["design_to_build"]


def test_day2_to_build_prompt_snapshot() -> None:
    output = _build_day2_to_build_prompt(_CANONICAL_CONTEXT)
    assert len(output) == _EXPECTED_LENGTHS["day2_to_build"]
    assert _sha(output) == _EXPECTED_SHAS["day2_to_build"]


def test_replanning_prompt_snapshot() -> None:
    output = _build_replanning_prompt(_CANONICAL_CONTEXT)
    assert len(output) == _EXPECTED_LENGTHS["replanning"]
    assert _sha(output) == _EXPECTED_SHAS["replanning"]
