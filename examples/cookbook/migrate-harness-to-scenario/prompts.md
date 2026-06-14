# Harness→Scenario migration prompts

Paste these into Cantrip in order, from the charm's directory. Wait
for each autonomous run to complete before pasting the next.

## 1 — Load the skill and take inventory

```
This charm's unit tests still use ops.testing.Harness. Load the
harness-migration skill, run the harness_inventory tool, and show me
the per-file checklist of what's left to migrate. Don't change
anything yet.
```

This grounds Cantrip in the migration workflow and produces the
baseline count it will work down. `harness_inventory` walks `tests/`
and reports `harness` / `scenario` / `mixed` counts per file.

## 2 — Fix the dependency story

```
Before migrating any tests: make sure pyproject.toml has ops[testing]
in every dependency group that runs unit tests, remove any standalone
ops-scenario pin, then re-sync (uv sync --group <group>) so the venv
has Scenario's Context.
```

Scenario's `Context` lives in the `testing` extra. If `ops[testing]`
isn't there, every migrated file fails to import.

## 3 — Migrate, one file at a time

```
Now migrate the Harness tests to Scenario, one file at a time.
For each file: list its assertions first so coverage is preserved,
identify the single Juju event it exercises, rebuild the input state
with testing.State, replace the Harness emit with ctx.run(...), and
remove the Harness imports and fixtures. Run that file's tests, fix
fallout, then re-run harness_inventory before moving to the next
file. Keep going until the inventory shows zero remaining Harness
files.
```

The "one file at a time, re-run the inventory" loop is the heart of
the recipe — it keeps the migration auditable and stops Cantrip
from rewriting half the suite before discovering a pattern that
doesn't translate.

## 4 — Confirm done

```
/tasks
```

```
Run charm_validate to confirm unit tests pass, coverage holds above
the 80% floor, and packing still succeeds. Then run harness_inventory
once more — it should report zero remaining Harness files.
```

Then run the verifier and the suite yourself:

```bash
python /path/to/cantrip/cookbook/migrate-harness-to-scenario/verify.py .
uv run pytest tests/unit/
```

## Optional — commit

```
git_add the migrated test files and pyproject.toml, then git_commit
with the message "Migrate unit tests from Harness to Scenario".
```
