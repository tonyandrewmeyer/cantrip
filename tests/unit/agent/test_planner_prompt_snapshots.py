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
    "planning": "569a95628ed0487c2fa441fa11d4629b86eae5441c301aa625a0c7962ec59927",
    "design_to_build": "9842c92af6254e51807998ce0a2d619371f6ac7a7c24ae660d10629d85ddf3ef",
    "day2_to_build": "b1495ce751204a0ba6a54fbce3e073ea2c90dc169fae043bb636ea22d3fcb7f1",
    "replanning": "4a7c7d4477d930b19f2f551c493e1c15ecc7e313dcd4a7fb995a7dff9c4335d3",
}

_EXPECTED_LENGTHS = {
    "planning": 4499,
    "design_to_build": 2796,
    "day2_to_build": 2424,
    "replanning": 4741,
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
