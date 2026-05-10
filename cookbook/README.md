# Cantrip Cookbook

Runnable recipes for driving Cantrip through real charm-building
workflows. Each recipe lives in its own directory and follows a
shared format so CI can check recipe health and humans can copy-paste
a recipe into a terminal.

Inspired by
[awesome-copilot/cookbook/copilot-sdk/python/recipe](https://github.com/github/awesome-copilot/tree/main/cookbook/copilot-sdk/python/recipe)
— same idea, shaped for Cantrip's charm-focused surface.

## Recipe format

Every recipe directory holds:

| File | Purpose |
|------|---------|
| `README.md` | Walkthrough: what this recipe does, what you need installed, what the result looks like. |
| `prompts.md` | Exact user prompts to paste into Cantrip, in order. Each prompt is one fenced block. |
| `verify.py` | Runnable checker: takes a charm directory as argv, asserts the result matches the shape this recipe teaches. `sys.exit(0)` on success, `sys.exit(1)` with a message on failure. |
| `expected/` | *Optional.* Committed example of what the recipe produces. When present, `verify.py` runs against it in CI as a regression fixture. |

The `verify.py` is the important artifact. It's what lets a recipe
double as a regression test: drop a newly-built charm directory
against it and see whether the recipe still produces the promised
shape.

## Recipes

| Status | Recipe | What it shows |
|--------|--------|---------------|
| ✅ shipped | [`build-a-sprint-charm/`](build-a-sprint-charm/README.md) | The fastest path — sprint mode, no tests, ops-only deps, packs in under a minute |
| ✅ shipped | [`migrate-harness-to-scenario/`](migrate-harness-to-scenario/README.md) | Drive the `harness-migration` skill to rewrite an existing Harness suite as Scenario tests |
| 🗓️ proposed | `build-a-stateful-charm/` | Stateful workload with Scenario tests, COS integration, ops-tracing |
| 🗓️ proposed | `add-observability/` | Wire COS into an existing charm — Tempo + Loki + Grafana |
| 🗓️ proposed | `generate-a-terraform-module/` | Produce a Terraform module that consumes the charm |
| 🗓️ proposed | `deploy-with-juju-and-cos/` | End-to-end deploy + dashboard-ready observability |

Proposed recipes are tracked in ROADMAP Phase 55.6 as follow-up
items. Open a PR with a new `cookbook/<name>/` directory to
promote one from proposed to shipped.

## Running a recipe

```bash
# Read the recipe.
cat cookbook/build-a-sprint-charm/README.md

# Paste the prompts into a live Cantrip session.
cantrip path/to/new/charm/dir

# Once Cantrip finishes, verify the result.
python cookbook/build-a-sprint-charm/verify.py path/to/new/charm/dir
```

## Running the verifier in CI

`tests/unit/test_cookbook_recipes.py` walks every
`cookbook/*/verify.py`: a recipe with a sibling `expected/` charm
fixture has its verifier run against it; a recipe without one gets
a hand-written in-process fixture matching what the recipe promises.
Either way the *structure* check — README, prompts, verifier exist
and the verifier is valid Python — runs over every `cookbook/*/`.

This gives us two levels of protection:

1. **Structure drift** — a recipe can't be merged with a broken
   format (missing files, invalid Python).
2. **Output drift** — for recipes with `expected/` committed,
   `verify.py` runs against it. If the recipe's shape assertions
   stop matching the committed output, CI fails.

Live Cantrip runs (LLM + charmcraft + juju) are deliberately
**not** part of CI — they're too slow, too credentialled, and too
environment-dependent. The cookbook is documentation + a shape
contract, not an end-to-end integration suite.
