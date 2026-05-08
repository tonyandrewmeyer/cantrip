---
title: "How to score Cantrip against an eval spec — Cantrip"
description: "Generate a charm with a chosen provider and score it against the spec rubric using the eval runner."
h1: "Score Cantrip against an eval spec"
subtitle: "Use the bundled eval runner to drive Cantrip print-mode against a spec, score the result, and compare providers."
section: howto
breadcrumb_label: "Run an eval"
see_also:
  - label: "How to run a single goal non-interactively"
    href: "howto-print-mode.html"
  - label: "CLI reference"
    href: "reference-cli.html"
---

The eval suite under `tests/eval/charms/` ships YAML specs that describe
*what* a charm should do (the prompt) and *how to judge* the result (the
rubric).  Each spec sits beside zero or more gold-standard subdirectories
(`gold-claude`, `gold-gemini`, ...) plus any charm directories Cantrip
itself produced.  The runner has four CLI verbs:

- `validate` — every gold standard must score 100 %.
- `score` — score one charm directory against its spec's rubric.
- `generate` — drive `cantrip run --print` against the spec and emit a
  fresh charm directory.
- `run` — `generate` then `score` in one invocation.

{#prerequisites}
## Prerequisites

- A Cantrip checkout with `uv sync --dev` already run.
- The provider's API key exported in your shell — `ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`, `FIREWORKS_API_KEY`, or `OPENROUTER_API_KEY` — same
  as for any normal `cantrip run` invocation.  See [How to choose a
  provider](howto-provider.html) for the full env-var catalogue.
- The `cantrip` command on your `PATH`.  Inside the project venv this is
  `uv run cantrip`; outside, install Cantrip first.

{#single-run}
## Score one provider end to end

`run` is the shape Phase 79.4 added so a single command produces a
scored charm:

<pre><code>uv run python -m tests.eval.runner run \
    tests/eval/charms/ntfy \
    --provider claude \
    --model opus-4.7</code></pre>

This:

1. Picks a fresh subdirectory of `tests/eval/charms/ntfy/` — the naming
   convention is `cantrip-<provider>-<model-slug>-<YYYYMMDD-HHMMSS>` so
   re-runs of the same model land in different directories without
   colliding with the gold standards.
2. Shells out to `cantrip run --print "<spec.prompt>" <charm-dir>
   --provider <X> --model <Y> --yolo`.  `--yolo` is the default because
   print-mode refuses to start when there are pending CONFIRM tasks and
   an unattended eval has no way to answer them.  Pass `--no-tui` is
   implied by `--print` itself.
3. Hands the resulting charm directory to the rubric scorer and prints
   a Markdown report.
4. Exits non-zero if the run produced any critical-severity failure, so
   CI invocations fail loudly.

A failed run that left no artefacts behind exits without scoring; the
shell command Cantrip attempted is included in the error so you can
re-run it interactively to see what happened.

{#generate-only}
## Generate without scoring

`generate` runs only the print-mode step, which is what you want when
debugging the agent itself rather than measuring rubric coverage:

<pre><code>uv run python -m tests.eval.runner generate \
    tests/eval/charms/ntfy \
    --provider gemini</code></pre>

Pair it with `score` once you've inspected the result:

<pre><code>uv run python -m tests.eval.runner score \
    tests/eval/charms/ntfy \
    tests/eval/charms/ntfy/cantrip-gemini-default-20260509-123045</code></pre>

{#compare-providers}
## Compare providers side by side

Once two or more providers have generated charms, the `compare` verb
formats their rubric scores in a single table:

<pre><code>uv run python -m tests.eval.runner compare \
    tests/eval/charms/ntfy \
    tests/eval/charms/ntfy/gold-claude \
    tests/eval/charms/ntfy/cantrip-gemini-default-20260509-123045</code></pre>

`compare` reads the same rubric file and produces both an overall and
per-category breakdown plus the failure list per run.  Gold standards
score 100 % by definition, so a real-provider run sitting next to the
gold for the same charm is the cleanest way to read regression deltas.

{#adding-baselines}
## Add a baseline directory

Phase 79.4 commits to growing `gold-gemini` / `gold-fireworks` /
`gold-openrouter` baselines over time.  The recipe:

1. Run `tests/eval/runner.py generate` against the spec with the new
   provider.
2. Inspect the output, hand-tune any sharp edges, and rename the
   directory to `gold-<provider>` (e.g. `gold-gemini`).
3. Re-run `tests/eval/runner.py validate` — if the new gold scores
   100 %, commit it; otherwise iterate on the rubric or the charm
   until it does.
4. Add the resulting directory to the spec's containing folder; the
   runner picks it up automatically (no spec-file edits required).

Gold standards are checked into the repo so the rubric continues to
score deterministically without any provider call.

{#stub-the-runner}
## Drive the runner from a script

`tests.eval.runner.generate_and_score` is the public entry point if you
want to integrate the loop into a Python harness:

```python
from tests.eval.runner import generate_and_score
from tests.eval.spec import EvalSpec

spec = EvalSpec.load(pathlib.Path("tests/eval/charms/ntfy"))
generation, result = generate_and_score(
    spec,
    pathlib.Path("tests/eval/charms/ntfy"),
    provider="claude",
    model="opus-4.7",
)

if result is not None and result.critical_failures:
    sys.exit(1)
```

Tests inject a fake `runner` callable (a stub `subprocess.run`) so the
harness exercise itself never burns tokens; see
`tests/eval/test_runner_generate.py` for the pattern.
