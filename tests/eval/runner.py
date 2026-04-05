"""Evaluation runner.

Discovers eval specs, optionally runs Cantrip against them, scores
the results, and generates comparison reports.

Can be used both programmatically and as a CLI::

    uv run python -m tests.eval.runner score tests/eval/charms/flask-bookmark/cantrip-gemini
    uv run python -m tests.eval.runner validate tests/eval/charms/flask-bookmark
    uv run python -m tests.eval.runner compare tests/eval/charms/flask-bookmark/gold-* cantrip-*
"""

import argparse
import pathlib
import sys

from .scorer import format_comparison, format_report, run_rubric, validate_gold_standard
from .spec import EvalResult, EvalSpec

EVAL_DIR = pathlib.Path(__file__).parent / "charms"


def discover_specs() -> list[tuple[pathlib.Path, EvalSpec]]:
    """Find all evaluation specs under the charms/ directory."""
    specs = []
    if not EVAL_DIR.is_dir():
        return specs
    for spec_dir in sorted(EVAL_DIR.iterdir()):
        spec_file = spec_dir / "spec.yaml"
        if spec_file.exists():
            spec = EvalSpec.load(spec_dir)
            specs.append((spec_dir, spec))
    return specs


def score_directory(
    spec: EvalSpec,
    charm_dir: pathlib.Path,
    *,
    provider: str = "unknown",
    model: str = "unknown",
) -> EvalResult:
    """Score a single charm directory against its spec's rubric."""
    return run_rubric(spec, charm_dir, provider=provider, model=model)


def validate_all_gold_standards() -> dict[str, list[str]]:
    """Validate that every gold standard scores 100%.

    Returns {spec_name: [failure_messages]}.
    """
    failures: dict[str, list[str]] = {}
    for spec_dir, spec in discover_specs():
        problems = validate_gold_standard(spec, spec_dir)
        if problems:
            failures[spec.name] = problems
    return failures


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Cantrip evaluation runner")
    sub = parser.add_subparsers(dest="command")

    # score: evaluate a charm dir against its spec.
    score_p = sub.add_parser("score", help="Score a charm directory")
    score_p.add_argument("spec_dir", type=pathlib.Path, help="Spec directory")
    score_p.add_argument("charm_dir", type=pathlib.Path, help="Charm to evaluate")
    score_p.add_argument("--provider", default="unknown")
    score_p.add_argument("--model", default="unknown")

    # validate: check gold standards score 100%.
    sub.add_parser("validate", help="Validate all gold standards")

    # compare: side-by-side comparison.
    compare_p = sub.add_parser("compare", help="Compare multiple results")
    compare_p.add_argument("spec_dir", type=pathlib.Path, help="Spec directory")
    compare_p.add_argument(
        "charm_dirs", type=pathlib.Path, nargs="+", help="Charm directories to compare"
    )

    args = parser.parse_args()

    if args.command == "score":
        spec = EvalSpec.load(args.spec_dir)
        result = score_directory(spec, args.charm_dir, provider=args.provider, model=args.model)
        print(format_report(result))

    elif args.command == "validate":
        failures = validate_all_gold_standards()
        if not failures:
            print("All gold standards pass their rubrics.")
        else:
            for name, problems in failures.items():
                print(f"\n{name}:")
                for p in problems:
                    print(f"  - {p}")
            sys.exit(1)

    elif args.command == "compare":
        spec = EvalSpec.load(args.spec_dir)
        results = []
        for cd in args.charm_dirs:
            # Infer provider/model from directory name if possible.
            parts = cd.name.split("-", 1)
            provider = parts[0] if len(parts) > 1 else "unknown"
            model = parts[1] if len(parts) > 1 else cd.name
            results.append(score_directory(spec, cd, provider=provider, model=model))
        print(format_comparison(results))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
