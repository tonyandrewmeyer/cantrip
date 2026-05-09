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
    "planning": "626398db2135fcdd26ad393642f8626c47f73d9f717e73669793a55683c5b753",
    "design_to_build": "f52527c8fd4346d6ef475e739ff169446dd2dfdcc2b3ac693cc80106a7a1c348",
    "day2_to_build": "1899b2166787c97b03307690c01a74a5b10c6a10bc30d4280e3425c4efe7bc7c",
    "replanning": "c0897f92f3b813908b088c6ae14aed7b811e9592ca01f78e902b40aac20fbc87",
}

_EXPECTED_LENGTHS = {
    "planning": 4571,
    "design_to_build": 2828,
    "day2_to_build": 2456,
    "replanning": 4813,
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
