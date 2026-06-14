---
name: juju-scenario-tests
description: 'Writing unit tests for charms with ops.testing (Scenario). WHEN: write
  unit tests for a Juju charm, write Scenario tests with ops.testing, test charm with
  State and Context, test relations / config / pebble-ready / actions / secrets /
  collect-status, write multi-event state-transition tests.'
license: Apache-2.0
metadata:
  author: Canonical/cantrip
  version: 1.0.0
  summary: Writing unit tests for Juju charms with ops.testing (Scenario), the modern
    state-transition replacement for the deprecated Harness.
  tags:
  - juju
  - ops
  - testing
  - scenario
  - unit-tests
---

<!--
Generated from Cantrip's source skill at
`src/cantrip/skills/scenario-tests/SKILL.md`
(https://github.com/canonical/cantrip). Do NOT hand-edit —
re-run `make juju-skills-bundle` instead.

Procedure steps may reference cantrip-specific helper tools (for
example `charm_validate`, `quick_pack`, `harness_inventory`).
Substitute the equivalent `charmcraft` / `juju` / standard CLI
invocation when running without cantrip.
-->

# Writing Unit Tests with Scenario

Use `ops.testing` (commonly called Scenario) for all charm unit tests. **Never use Harness** — it is deprecated.

## Key Concepts

Scenario tests are **state-transition tests**: you declare an input `State`, fire an event, and assert on the output `State`. No mocking of Juju internals is needed.

### Core Components

- **`Context`** — wraps your charm class; provides `ctx.on.<event>()` to fire events
- **`State`** — immutable snapshot of the Juju world: relations, config, containers, secrets, storage
- **`ctx.run(event, state)`** — fires the event against the state, returns the output state

## Step 1: Set Up Test Dependencies

Add `ops[testing]` to the charm's `pyproject.toml` dependency groups:

```toml
[dependency-groups]
unit = ["ops[testing]", "pytest", "coverage"]
```

Charm dependencies live in `pyproject.toml`, not `requirements.txt`. The
`charmcraft init --profile kubernetes` (or `machine`) scaffolding produces
the right layout.

## Step 2: Write a Basic Test

```python
import ops
from ops import testing

from src.charm import MyCharm


def test_start_sets_active():
    ctx = testing.Context(MyCharm)
    state = testing.State()
    out = ctx.run(ctx.on.start(), state)
    assert out.unit_status == testing.ActiveStatus("ready")
```

`Context` reads metadata directly from `charmcraft.yaml` when handed the
real charm class — **do not pass `meta=` or `config=` overrides**. Those
kwargs are leftovers from older Scenario versions and are unnecessary
once the test imports the actual charm class.

## Step 3: Test with Relations

```python
def test_database_relation_joined():
    rel = testing.Relation(
        endpoint="database",
        interface="mysql",
        remote_app_data={"host": "db.local", "port": "3306"},
    )
    state = testing.State(relations=[rel])
    ctx = testing.Context(MyCharm)
    out = ctx.run(ctx.on.relation_joined(rel), state)
    assert out.unit_status == testing.ActiveStatus()
```

## Step 4: Test with Config

Use `pytest.mark.parametrize` for config-validation tests so each invalid
value produces a clearly-named failure:

```python
import pytest


@pytest.mark.parametrize(
    "log_level,expected",
    [
        ("debug", testing.ActiveStatus()),
        ("info", testing.ActiveStatus()),
        ("verbose", testing.BlockedStatus("invalid log-level")),
    ],
)
def test_config_validation(log_level, expected):
    state = testing.State(config={"log-level": log_level})
    ctx = testing.Context(MyCharm)
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == expected
```

## Step 5: Test Containers and Pushed Files (K8s charms)

For tests that exercise files the charm pushes into a container, fire
`pebble_ready` (not `start`) and read the result with `get_filesystem`:

```python
def test_pebble_ready_pushes_config():
    container = testing.Container(name="workload", can_connect=True)
    state = testing.State(containers={container})
    ctx = testing.Context(MyCharm)

    out = ctx.run(ctx.on.pebble_ready(container), state)

    # Read pushed files via get_filesystem — no mount setup required.
    root = testing.get_filesystem(ctx, "workload")
    config = (root / "etc" / "workload" / "config.yaml").read_text()
    assert "log-level: info" in config

    plan = out.get_container("workload").plan
    assert "workload" in plan.services
```

`get_filesystem(ctx, container_name)` returns a real temporary directory
populated with whatever the charm pushed. It avoids the older
mount-based testing pattern entirely.

## Step 6: Test `collect_status`

For charms that compute their unit status in `collect_status`, drive the
status by firing `update_status` with the relevant container layers and
service statuses, and use equality (`==`) rather than `isinstance`:

```python
def test_collect_status_active_when_workload_running():
    container = testing.Container(
        name="workload",
        can_connect=True,
        layers={"workload": testing.Layer({"services": {"workload": {}}})},
        service_statuses={"workload": ops.pebble.ServiceStatus.ACTIVE},
    )
    state = testing.State(containers={container})
    ctx = testing.Context(MyCharm)

    out = ctx.run(ctx.on.update_status(), state)

    assert out.unit_status == testing.ActiveStatus()
```

## Step 7: Test Actions

```python
def test_backup_action():
    ctx = testing.Context(MyCharm)
    state = testing.State()
    out = ctx.run(ctx.on.action("backup", params={"path": "/data"}), state)
    assert out.action_results == {"status": "success"}
```

## Step 8: Test Secrets

```python
def test_secret_changed():
    secret = testing.Secret(
        tracked_content={"password": "old"},
        latest_content={"password": "new"},
    )
    state = testing.State(secrets=[secret])
    ctx = testing.Context(MyCharm)
    out = ctx.run(ctx.on.secret_changed(secret), state)
    assert out.unit_status == testing.ActiveStatus()
```

## Step 9: Multi-Event Sequences

`State` is **immutable**. To carry state between events in a sequence,
use `dataclasses.replace()` to derive a new state from the output of the
previous event:

```python
import dataclasses


def test_install_then_config_change():
    ctx = testing.Context(MyCharm)
    initial = testing.State()

    after_start = ctx.run(ctx.on.start(), initial)
    assert after_start.unit_status == testing.ActiveStatus()

    # Carry forward whatever start() produced; tweak only the config.
    next_state = dataclasses.replace(after_start, config={"log-level": "debug"})
    final = ctx.run(ctx.on.config_changed(), next_state)
    assert final.unit_status == testing.ActiveStatus()
```

## Patterns and Best Practices

1. **Test state transitions, not implementation.** Assert on the output `State` (status, relation data, config), not on internal charm attributes.

2. **One event per test.** Each test fires exactly one event. To simulate a sequence, chain `ctx.run()` calls and use `dataclasses.replace()` between them — never mutate a `State` in place.

3. **Use `ctx.on.<event>()`** to construct events — never instantiate event objects directly.

4. **Leader tests.** Set `leader=True` on the `State` to test leader-only behaviour:
   ```python
   state = testing.State(leader=True)
   ```

5. **Test both happy and error paths.** Check that the charm sets `BlockedStatus` or `WaitingStatus` when preconditions are not met.

6. **Deferred events.** Check `out.deferred` to verify events were deferred when expected.

7. **Equality, not isinstance.** Compare statuses with `==` (e.g. `out.unit_status == testing.ActiveStatus("ready")`) so the message is checked too.

## Passing relation objects to `State.get_relation`

`State.get_relation` accepts either a relation ID or a relation object.
When you pass the object you submitted with the input `State`, the
return type is narrowed to the same kind (peer, regular, subordinate):

```python
rel_in = testing.Relation(endpoint="database", interface="postgresql")
state_in = testing.State(relations={rel_in})
state_out = ctx.run(ctx.on.relation_changed(rel_in), state_in)

# Pass the object itself — cleaner than pulling `.id` off first.
rel_out = state_out.get_relation(rel_in)
```

## Interactive debugging inside a test

``testing.Context.run`` now leaves ``sys.breakpointhook`` alone, so you
can drop a plain ``breakpoint()`` call into charm code under test and
get a pdb session when ``pytest -s tests/unit/test_charm.py`` reaches
it.  Unlike the live-charm ``Framework.breakpoint()`` + ``juju
debug-code`` combo, this needs no deployment — useful when you're
isolating a single state transition.

Remove the breakpoint before committing; CI running without ``-s``
will hang on a pdb prompt.

## charmcraft extensions in Scenario

For charms that use a ``charmcraft`` extension (the 12-factor
``paas-charm`` family, for example), Scenario now autoloads the
extension-expanded metadata, config, and actions the same way
``charmcraft pack`` does before writing the per-file YAML.  You do not
need to manually reconstruct the extended metadata in your tests —
``testing.Context(MyCharm)`` picks it up automatically as long as the
charm's ``charmcraft.yaml`` is discoverable from the charm class.

## Capturing live state for regression tests

When a deployed charm misbehaves and you want to write a regression test
that reproduces the exact databag and storage state, use
`jhack scenario snapshot <unit>` to dump the live state in
Scenario-friendly form. Paste the snapshot into a test file as the input
`State` and you have a deterministic reproduction of the production bug.

## Auditing test coverage

Run the `scenario_coverage` tool against the charm directory. It maps every
`framework.observe(self.on.X, self._on_Y)` registration to the test functions
under `tests/unit/` that reference the handler or event name, and flags two
event-shape gaps `pytest-cov` cannot see: missing `container.can_connect=False`
tests (when the charm has containers) and missing `relation-broken` tests
(when the charm has any relation). Use it before declaring a suite "done".

## Common Pitfalls

- **Do not pass `meta=` or `config=` to `Context()`** — Scenario reads
  these from `charmcraft.yaml` automatically.
- **Do not use `unittest.mock.patch`** on Juju internals. Scenario handles all Juju interactions through the `State`.
- **Do not import from `ops.testing` inside functions** — keep imports at module level.
- **Container `can_connect=False`** is the default. Set it to `True` when testing Pebble interactions.
- **Use `pebble_ready`, not `start`,** for tests that exercise container file operations or service plans.
