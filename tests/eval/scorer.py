"""Evaluation scorer.

Runs a rubric against a charm directory and produces an EvalResult.
Also generates comparison reports between Cantrip output and gold standards.
"""

import pathlib

from . import checks as checks_module
from .spec import Criterion, CriterionResult, EvalResult, EvalSpec


def run_rubric(
    spec: EvalSpec,
    charm_dir: pathlib.Path,
    *,
    provider: str = "unknown",
    model: str = "unknown",
) -> EvalResult:
    """Evaluate a generated charm directory against the spec's rubric."""
    result = EvalResult(spec_name=spec.name, provider=provider, model=model)

    for criterion in spec.rubric.criteria:
        cr = _evaluate_criterion(criterion, charm_dir)
        result.results.append(cr)

    return result


def validate_gold_standard(spec: EvalSpec, spec_dir: pathlib.Path) -> list[str]:
    """Check that all gold standards score 100% on the rubric.

    Returns a list of failure messages (empty = all pass).
    """
    failures = []
    for gold_name in spec.gold_standards:
        gold_dir = spec_dir / gold_name
        if not gold_dir.is_dir():
            failures.append(f"gold standard '{gold_name}' directory missing")
            continue

        result = run_rubric(spec, gold_dir, provider="gold", model=gold_name)
        failures.extend(
            f"[{gold_name}] {cr.criterion.name}: {cr.detail}"
            for cr in result.results
            if not cr.passed
        )
    return failures


def format_report(result: EvalResult) -> str:
    """Format an evaluation result as a markdown report."""
    lines = [
        f"# Evaluation Report: {result.spec_name}",
        "",
        f"**Provider:** {result.provider}  ",
        f"**Model:** {result.model}  ",
        f"**Score:** {result.score}/{result.max_score} ({result.percentage:.0f}%)",
        "",
    ]

    # Critical failures banner.
    crit = result.critical_failures
    if crit:
        lines.append(f"**{len(crit)} CRITICAL failure(s):**")
        lines.extend(f"- {r.criterion.name}: {r.detail}" for r in crit)
        lines.append("")

    # Per-category breakdown.
    lines.append("## Scores by Category")
    lines.append("")
    lines.append("| Category | Score | Pct |")
    lines.append("|----------|-------|-----|")
    for cat, (earned, possible) in sorted(result.category_scores().items()):
        pct = (earned / possible * 100) if possible else 0
        lines.append(f"| {cat} | {earned}/{possible} | {pct:.0f}% |")
    lines.append("")

    # Detailed results.
    lines.append("## Detailed Results")
    lines.append("")
    for r in result.results:
        icon = "PASS" if r.passed else "FAIL"
        sev = r.criterion.severity.value.upper()
        lines.append(f"- [{icon}] **{r.criterion.name}** ({sev}): {r.detail}")
    lines.append("")

    return "\n".join(lines)


def format_comparison(results: list[EvalResult]) -> str:
    """Format a side-by-side comparison of multiple evaluation runs."""
    if not results:
        return "No results to compare."

    # Collect all categories.
    categories: set[str] = set()
    for r in results:
        categories.update(r.category_scores().keys())

    lines = [
        "# Evaluation Comparison",
        "",
        "| Metric |" + "|".join(f" {r.provider}/{r.model} " for r in results) + "|",
        "|--------|" + "|".join("--------" for _ in results) + "|",
        "| **Overall** |" + "|".join(f" {r.percentage:.0f}% " for r in results) + "|",
    ]

    for cat in sorted(categories):
        row = f"| {cat} |"
        for r in results:
            earned, possible = r.category_scores().get(cat, (0, 0))
            pct = (earned / possible * 100) if possible else 0
            row += f" {pct:.0f}% |"
        lines.append(row)

    lines.append("")

    # Failures per run.
    for r in results:
        failed = [cr for cr in r.results if not cr.passed]
        if failed:
            lines.append(f"### Failures: {r.provider}/{r.model}")
            lines.append("")
            for cr in failed:
                sev = cr.criterion.severity.value
                lines.append(f"- [{sev}] {cr.criterion.name}: {cr.detail}")
            lines.append("")

    return "\n".join(lines)


def _evaluate_criterion(criterion: Criterion, charm_dir: pathlib.Path) -> CriterionResult:
    """Run a single criterion check against a charm directory."""
    checker = getattr(checks_module, criterion.check, None)
    if checker is None:
        return CriterionResult(
            criterion=criterion,
            passed=False,
            detail=f"unknown checker '{criterion.check}'",
        )

    try:
        passed, detail = checker(charm_dir, **criterion.args)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return CriterionResult(
            criterion=criterion,
            passed=False,
            detail=f"checker raised {type(exc).__name__}: {exc}",
        )

    return CriterionResult(criterion=criterion, passed=passed, detail=detail)
