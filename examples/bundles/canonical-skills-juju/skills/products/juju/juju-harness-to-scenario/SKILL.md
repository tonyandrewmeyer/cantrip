---
name: juju-harness-to-scenario
description: 'Migrating deprecated ops.testing.Harness tests to state-transition (Scenario)
  tests. WHEN: migrate ops.testing.Harness tests to Scenario, modernise legacy Juju
  charm unit tests, rewrite Harness-based tests as state-transition tests, port relation_changed
  / pebble_ready / action tests off Harness.'
license: Apache-2.0
metadata:
  author: Canonical/cantrip
  version: 1.0.0
  summary: Migrating deprecated ops.testing.Harness unit tests to state-transition
    (Scenario) tests, file by file.
  tags:
  - juju
  - ops
  - testing
  - scenario
  - harness
  - migration
---

<!--
Generated from Cantrip's source skill at
`src/cantrip/skills/harness-migration/SKILL.md`
(https://github.com/canonical/cantrip). Do NOT hand-edit —
re-run `make juju-skills-bundle` instead.

Procedure steps may reference cantrip-specific helper tools (for
example `charm_validate`, `quick_pack`, `harness_inventory`).
Substitute the equivalent `charmcraft` / `juju` / standard CLI
invocation when running without cantrip.
-->

<!--
Adapted from canonical/copilot-collections skill
`migrate-harness-tests-to-state-transition-test`:

  https://github.com/canonical/copilot-collections/tree/main/skills/migrate-harness-tests-to-state-transition-test

Sourced on 2026-04-18 at upstream revision a4e2d1d (skill content last changed
in commit 129ec67). Re-check upstream periodically — if the original has moved
forward, port improvements here and bump the revision noted above.
-->

# Migrating Harness Tests to Scenario

Use this skill when an existing charm's unit tests still use `ops.testing.Harness`
and need to be rewritten as state-transition tests with `ops.testing.Context` /
`State`. Harness is deprecated; new charms scaffolded by cantrip already use
Scenario (see the `scenario-tests` skill).

## When to load

- `charm_audit` reports Harness usage, or the user asks to modernise tests.
- You are iterating on an existing charm that imports `testing.Harness`,
  `ops.testing.Harness`, or calls `Harness(...)` directly.

For writing a fresh Scenario suite from scratch, load `scenario-tests` instead.

## Inventory first

Run the `harness_inventory` tool to enumerate remaining Harness usages. It
walks `tests/`, applies the upstream copilot-collections detector regex,
and returns a per-file checklist with `harness` / `scenario` counts and a
`mixed` flag for files that import both. Re-run after each migrated file
to watch the count drop.

## Preflight

1. Check `pyproject.toml` — `ops[testing]` must be in every dependency group
   that runs unit tests. Remove any lingering `ops-scenario` package (it has
   been folded into `ops[testing]`).
2. Re-sync after editing deps (`uv sync --group <group>`) so the venv has the
   Scenario `Context`.

## The mental model shift

Harness mutates state imperatively across many calls. Scenario builds the
**entire input state up front**, fires one event, and asserts on the output.

| Harness | Scenario replacement |
| --- | --- |
| `Harness(MyCharm)` + `harness.begin()` | `ctx = testing.Context(MyCharm)` |
| `harness.set_leader(True)` | `testing.State(leader=True)` |
| `harness.update_config({...})` before emit | `testing.State(config={...})` |
| `harness.add_relation(...)` | `testing.Relation(endpoint=..., remote_app_data=...)` in `State.relations` |
| `harness.container_pebble_ready(...)` | `testing.Container(..., can_connect=True)` in `State.containers` |
| `harness.charm.on.<event>.emit(...)` | `ctx.run(ctx.on.<event>(...), state_in)` |
| `harness.run_action("name", params)` | `ctx.run(ctx.on.action("name", params=...), state)` — read `ctx.action_results` |
| `harness.evaluate_status()` | Fires automatically after every `ctx.run(...)` |

Each migrated test should exercise **one** Juju event. If a Harness test chained
several events, split it into multiple tests or feed `state_out` of one call
into the next `ctx.run(...)`.

## Event recipes

### Action

```python
from ops import testing

def test_backup_action():
    ctx = testing.Context(MyCharm)
    state_in = testing.State(containers={testing.Container("workload", can_connect=True)})
    state_out = ctx.run(
        ctx.on.action("backup", params={"path": "/data"}),
        state_in,
    )
    assert ctx.action_results == {"status": "success"}
    assert state_out.unit_status == testing.ActiveStatus()
```

For failure paths:

```python
import pytest
with pytest.raises(testing.ActionFailed) as exc:
    ctx.run(ctx.on.action("backup", params={"path": "/bad"}), state_in)
assert "permission denied" in exc.value.message
```

### Relation changed

```python
rel = testing.Relation(
    endpoint="database",
    remote_app_data={"endpoints": "db.local:5432"},
)
state_in = testing.State(relations={rel})
state_out = ctx.run(ctx.on.relation_changed(rel), state_in)
```

Put the *post-change* data directly into `remote_app_data`; Scenario never
replays incremental updates.

### Pebble ready

```python
container = testing.Container("workload", can_connect=True)
state_in = testing.State(containers={container})
state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
assert "workload" in state_out.get_container(container.name).plan.services
```

Inspect the container on `state_out.get_container(name)` — the object in
`state_in` is immutable.

### Collect-status coverage

`_on_collect_status` runs implicitly after every `ctx.run`. Provide the state
its handlers inspect (containers, layers, service statuses), and add negative
variants:

```python
layer = pebble.Layer({"services": {"workload": {"command": "run", "startup": "enabled"}}})
active = testing.Container(
    "workload",
    layers={"base": layer},
    service_statuses={"workload": pebble.ServiceStatus.ACTIVE},
    can_connect=True,
)
down = testing.Container("workload", can_connect=False)

def test_status_active():
    state_out = ctx.run(ctx.on.update_status(), testing.State(containers={active}))
    assert state_out.unit_status == testing.ActiveStatus()

def test_status_waiting_when_disconnected():
    state_out = ctx.run(ctx.on.update_status(), testing.State(containers={down}))
    assert isinstance(state_out.unit_status, testing.WaitingStatus)
```

## Per-file workflow

1. List assertions in the Harness test so you can preserve coverage.
2. Identify the single event being exercised; choose the matching `ctx.on.*`.
3. Build `state_in` with everything the handler (and `_on_collect_status`)
   needs.
4. Replace Harness emit with `ctx.run(...)`. Assert on `state_out`, emitted
   statuses, `ctx.action_results`, and monkeypatched workload helpers.
5. Remove Harness imports and fixtures from the file.
6. Run the file: `run_charm_tests` with `test_type: "unit"` and
   `test_path: "tests/unit/<file>.py"`.
7. Fix fallout, then re-run the inventory grep — the file should no longer
   appear.

After every file is clean, run `charm_validate` to confirm unit tests pass,
coverage holds above the 80% floor, and packing still succeeds.

## Done criteria

- The inventory grep over `tests/` returns no hits.
- `ops[testing]` is in all unit-test dependency groups; `ops-scenario` is gone.
- Every migrated file has `_on_collect_status` covered with at least one
  success and one failure path when it has branches.
- `charm_validate` passes.

## References

- Upstream copilot-collections skill (source for this skill):
  [canonical/copilot-collections — migrate-harness-tests-to-state-transition-test](https://github.com/canonical/copilot-collections/tree/main/skills/migrate-harness-tests-to-state-transition-test)
- Canonical guide: [How to migrate unit tests from Harness](https://documentation.ubuntu.com/ops/latest/howto/legacy/migrate-unit-tests-from-harness/)
- Cantrip's `scenario-tests` skill — patterns for writing new Scenario suites.
