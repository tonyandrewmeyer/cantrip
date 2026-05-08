"""Evaluation runner.

Discovers eval specs, optionally runs Cantrip against them, scores
the results, and generates comparison reports.

Can be used both programmatically and as a CLI::

    uv run python -m tests.eval.runner score tests/eval/charms/flask-bookmark gold-claude
    uv run python -m tests.eval.runner generate tests/eval/charms/ntfy --provider claude
    uv run python -m tests.eval.runner run tests/eval/charms/ntfy --provider claude
    uv run python -m tests.eval.runner validate
    uv run python -m tests.eval.runner compare tests/eval/charms/flask-bookmark gold-* cantrip-*

The ``generate`` and ``run`` subcommands shell out to ``cantrip run
--print`` against the spec's prompt; ``run`` chains generation into
scoring so Phase 79.4's "actually use provider X to generate the
charm before scoring" loop is one command.
"""

import argparse
import pathlib
import sys

from .generator import GenerationResult, generate_charm, shell_quote
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


def generate_and_score(
    spec: EvalSpec,
    spec_dir: pathlib.Path,
    *,
    provider: str,
    model: str | None = None,
    cantrip_executable: str = "cantrip",
    timeout_seconds: float = 30 * 60,
    runner=None,
) -> tuple[GenerationResult, EvalResult | None]:
    """Generate a charm with provider *X* and score the result.

    Returns the generation outcome plus the scored ``EvalResult``.
    The score is ``None`` only when generation itself failed *and*
    left no artefacts behind — partial output still gets scored (the
    rubric is the most useful signal we have for "did the failed run
    produce *anything* worth keeping?").  ``runner`` is forwarded to
    :func:`generate_charm`; tests inject a fake to avoid spawning a
    real Cantrip process.
    """
    generation = generate_charm(
        spec,
        spec_dir,
        provider=provider,
        model=model,
        cantrip_executable=cantrip_executable,
        timeout_seconds=timeout_seconds,
        runner=runner,
    )
    if not generation.success and not _generation_left_artefacts(generation.charm_dir):
        return generation, None
    score = score_directory(
        spec,
        generation.charm_dir,
        provider=provider,
        model=model or "default",
    )
    return generation, score


def _generation_left_artefacts(charm_dir: pathlib.Path) -> bool:
    """Whether the generation run produced any charm files worth scoring.

    Empty directories carry no signal — short-circuit scoring rather
    than walking a rubric over a non-existent ``charmcraft.yaml``.
    """
    if not charm_dir.is_dir():
        return False
    return any(charm_dir.iterdir())


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

    # generate: drive Cantrip print-mode against a spec to produce a charm.
    generate_p = sub.add_parser(
        "generate",
        help="Run Cantrip print-mode against a spec to produce a charm directory",
    )
    generate_p.add_argument("spec_dir", type=pathlib.Path, help="Spec directory")
    generate_p.add_argument(
        "--provider",
        required=True,
        help="Cantrip provider name (claude, gemini, fireworks, openrouter, ...)",
    )
    generate_p.add_argument("--model", default=None, help="Specific model identifier")
    generate_p.add_argument(
        "--cantrip-executable",
        default="cantrip",
        help="Cantrip command on PATH (default: 'cantrip'; use 'uv run cantrip' in dev)",
    )
    generate_p.add_argument(
        "--timeout-seconds",
        type=float,
        default=30 * 60,
        help="Hard wall-clock limit for the print-mode subprocess (default: 1800s)",
    )

    # run: generate then score in one invocation.
    run_p = sub.add_parser(
        "run",
        help="Generate a charm with provider X and score it against the spec",
    )
    run_p.add_argument("spec_dir", type=pathlib.Path, help="Spec directory")
    run_p.add_argument(
        "--provider",
        required=True,
        help="Cantrip provider name (claude, gemini, fireworks, openrouter, ...)",
    )
    run_p.add_argument("--model", default=None, help="Specific model identifier")
    run_p.add_argument(
        "--cantrip-executable",
        default="cantrip",
        help="Cantrip command on PATH (default: 'cantrip'; use 'uv run cantrip' in dev)",
    )
    run_p.add_argument(
        "--timeout-seconds",
        type=float,
        default=30 * 60,
        help="Hard wall-clock limit for the print-mode subprocess (default: 1800s)",
    )

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

    elif args.command == "generate":
        spec = EvalSpec.load(args.spec_dir)
        generation = generate_charm(
            spec,
            args.spec_dir,
            provider=args.provider,
            model=args.model,
            cantrip_executable=args.cantrip_executable,
            timeout_seconds=args.timeout_seconds,
        )
        print(f"Charm directory: {generation.charm_dir}")
        print(f"Command: {shell_quote(generation.command)}")
        if not generation.success:
            sys.stderr.write(generation.stderr)
            sys.exit(generation.returncode or 1)

    elif args.command == "run":
        spec = EvalSpec.load(args.spec_dir)
        generation, result = generate_and_score(
            spec,
            args.spec_dir,
            provider=args.provider,
            model=args.model,
            cantrip_executable=args.cantrip_executable,
            timeout_seconds=args.timeout_seconds,
        )
        print(f"Charm directory: {generation.charm_dir}")
        if result is None:
            sys.stderr.write(generation.stderr)
            print(
                "Generation failed with no charm artefacts to score; "
                f"see stderr above and re-run with: {shell_quote(generation.command)}",
                file=sys.stderr,
            )
            sys.exit(generation.returncode or 1)
        print(format_report(result))
        # Surface a non-zero exit when the generated charm misses any
        # critical criterion so CI invocations of ``run`` fail loudly.
        if result.critical_failures:
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
