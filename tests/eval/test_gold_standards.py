"""Test that all gold-standard implementations score 100% on their rubrics.

This runs as part of the normal test suite to catch regressions in either
the gold standards or the rubric checker functions.
"""

import pytest

from tests.eval.runner import discover_specs
from tests.eval.scorer import validate_gold_standard
from tests.eval.spec import Severity

_SPECS = discover_specs()
_IDS = [spec.name for _, spec in _SPECS]


@pytest.mark.parametrize("spec_dir,spec", _SPECS, ids=_IDS)
def test_gold_standard_scores_perfectly(spec_dir, spec):
    """Every gold standard must score 100% against its rubric."""
    if not spec.gold_standards:
        pytest.skip("no gold standards yet")

    failures = validate_gold_standard(spec, spec_dir)
    assert not failures, f"Gold standard failures for {spec.name}:\n" + "\n".join(
        f"  - {f}" for f in failures
    )


@pytest.mark.parametrize("spec_dir,spec", _SPECS, ids=_IDS)
def test_rubric_has_criteria(spec_dir, spec):  # noqa: ARG001
    """Every spec must define at least one rubric criterion."""
    assert spec.rubric.criteria, f"{spec.name} has no rubric criteria"


@pytest.mark.parametrize("spec_dir,spec", _SPECS, ids=_IDS)
def test_rubric_has_critical_criteria(spec_dir, spec):  # noqa: ARG001
    """Every spec should have at least one critical criterion."""
    critical = [c for c in spec.rubric.criteria if c.severity is Severity.CRITICAL]
    assert critical, f"{spec.name} has no critical criteria"
