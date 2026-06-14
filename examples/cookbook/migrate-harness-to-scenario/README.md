# Migrate Harness tests to Scenario

**Modernise an existing charm's unit tests.** `ops.testing.Harness`
is deprecated; new charms scaffolded by Cantrip already use
state-transition (Scenario) tests with `ops.testing.Context` /
`State`. This recipe drives Cantrip's `harness-migration` skill to
rewrite an *existing* Harness suite file-by-file, preserving
coverage, until `tests/` is Harness-free.

It's the right recipe for:

- An older charm you've inherited whose `tests/unit/` still imports
  `Harness`.
- A pre-`ops>=3` charm you're bringing up to current conventions
  before adding features.
- Clearing a `charm_audit` finding that flags Harness usage.

Not a from-scratch test-writing recipe — for that, point Cantrip at
the `scenario-tests` skill instead.

## What you need

- **Cantrip** installed (`uv sync --dev && uv pip install -e .`
  from the Cantrip repo, or however you usually do it).
- **An existing charm** with a working unit-test suite that uses
  `ops.testing.Harness`. The recipe migrates what's there; it
  doesn't invent tests.
- **`uv`** on `$PATH` — the migration re-syncs the test dependency
  group after editing `pyproject.toml`.
- **No Juju controller needed** — unit tests run in-process.

## What you get

A charm directory where:

```
<charm-dir>/
├── pyproject.toml          # ops[testing] in the unit-test dep group; no ops-scenario pin
└── tests/
    └── unit/
        └── test_*.py       # ctx = testing.Context(...); ctx.run(ctx.on.<event>(...), state)
                            # — zero references to Harness
```

Every migrated file fires **one** Juju event via `ctx.run(...)` and
asserts on the returned `state_out`, on emitted statuses, and on
`ctx.action_results`. `_on_collect_status` coverage carries over
(it runs implicitly after every `ctx.run`). Harness imports and
fixtures are gone.

## Walkthrough

1. From the charm's directory, start Cantrip:
   ```bash
   cd ~/charms/my-legacy-charm
   cantrip .
   ```

2. Paste the prompts from [`prompts.md`](prompts.md) one at a time.
   Wait for each autonomous run to finish before the next paste.
   The migration is iterative — Cantrip runs the `harness_inventory`
   tool, migrates a file, re-runs the inventory, and repeats until
   the count hits zero.

3. When Cantrip reports the suite is Harness-free, verify the shape:
   ```bash
   python /path/to/cantrip/cookbook/migrate-harness-to-scenario/verify.py .
   ```

   You should see `OK — Harness→Scenario migration shape verified.`
   with exit code 0. Failures print a short reason naming the file
   or dependency that tripped the assertion.

4. Run the suite yourself to confirm green and that coverage held:
   ```bash
   uv run pytest tests/unit/
   ```

## How the verifier works

[`verify.py`](verify.py) loads the charm directory and asserts:

- `tests/` exists and contains at least one `*.py` file.
- **No** test file under `tests/` references `Harness` —
  `testing.Harness`, `ops.testing.Harness`, or a bare `Harness(...)`
  call. (Same detector regex as the `harness_inventory` tool.)
- **At least one** test file uses a Scenario construct —
  `testing.Context`, `testing.State`, `ctx.run(...)`, or the legacy
  `Scenario(...)` — so the suite was migrated, not deleted.
- `pyproject.toml` exists, is valid TOML, declares `ops[testing]`
  somewhere in its dependency lists, and does **not** pin the
  standalone `ops-scenario` package (it's folded into `ops[testing]`
  now).

It does not run the tests or `charmcraft pack` — those need a real
environment. The verifier is a shape contract, not an integration
suite; run `uv run pytest tests/unit/` yourself for the behavioural
check.

## Why this recipe is in the cookbook

The `harness-migration` skill (`src/cantrip/skills/harness-migration/SKILL.md`)
spells out the migration mechanically — a per-file workflow, the
Harness→Scenario mapping table, event recipes for actions /
relation-changed / pebble-ready / collect-status. Having the
*outcome* spelled out as a verifier gives us two protections:

1. **Teaching artifact** — a user who reads `verify.py` learns
   exactly what "migrated" means: Harness gone, Scenario present,
   `ops[testing]` wired up.
2. **Regression fixture** — if the skill or the `harness_inventory`
   tool drifts (detector regex changes, the dependency story moves
   again), the verifier and the in-agent inventory disagree, and
   CI's structure sweep over `cookbook/*/` flags the recipe.

## Related

- [`harness-migration` skill](../../src/cantrip/skills/harness-migration/SKILL.md)
  — the in-agent guidance this recipe drives.
- `cantrip.agent.tools.harness_inventory` — the deterministic
  scan tool the skill leans on; shares this verifier's detector
  regexes.
- Cantrip's `scenario-tests` skill — patterns for writing fresh
  Scenario suites (use that, not this, for new charms).
- Canonical guide: [How to migrate unit tests from Harness](https://documentation.ubuntu.com/ops/latest/howto/legacy/migrate-unit-tests-from-harness/).
