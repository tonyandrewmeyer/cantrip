---
name: scenario-tests
description: Writing unit tests for charms with ops.testing (Scenario)
---

# Writing Unit Tests with Scenario

Use `ops.testing` (commonly called Scenario) for all charm unit tests. **Never use Harness** — it is deprecated.

## Key Concepts

Scenario tests are **state-transition tests**: you declare an input `State`, fire an event, and assert on the output `State`. No mocking of Juju internals is needed.

### Core Components

- **`Context`** — wraps your charm class; provides `ctx.on.<event>()` to fire events
- **`State`** — immutable snapshot of the Juju world: relations, config, containers, secrets, storage
- **`ctx.run(event, state)`** — fires the event against the state, returns the output state

## Step 1: Set Up Test Dependencies

Add `ops[testing]` to the charm's test dependencies in `pyproject.toml` or `tox.ini`:

```toml
[project.optional-dependencies]
dev = ["ops[testing]"]
```

## Step 2: Write a Basic Test

```python
import ops
from ops import testing


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on.start, self._on_start)

    def _on_start(self, event: ops.StartEvent):
        self.unit.status = ops.ActiveStatus("ready")


def test_start_sets_active():
    ctx = testing.Context(MyCharm)
    state = testing.State()
    out = ctx.run(ctx.on.start(), state)
    assert out.unit_status == testing.ActiveStatus("ready")
```

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

```python
def test_config_changed():
    state = testing.State(config={"log-level": "debug"})
    ctx = testing.Context(MyCharm)
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == testing.ActiveStatus()
```

## Step 5: Test with Containers (K8s charms)

```python
def test_pebble_ready():
    container = testing.Container(
        name="workload",
        can_connect=True,
    )
    state = testing.State(containers=[container])
    ctx = testing.Context(MyCharm)
    out = ctx.run(ctx.on.pebble_ready(container), state)

    # Check the Pebble plan was set.
    updated_container = out.get_container("workload")
    plan = updated_container.plan
    assert "workload" in plan.services
```

## Step 6: Test Actions

```python
def test_backup_action():
    ctx = testing.Context(MyCharm)
    state = testing.State()
    out = ctx.run(ctx.on.action("backup", params={"path": "/data"}), state)
    assert out.action_results == {"status": "success"}
```

## Step 7: Test Secrets

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

## Patterns and Best Practices

1. **Test state transitions, not implementation.** Assert on the output `State` (status, relation data, config), not on internal charm attributes.

2. **One event per test.** Each test fires exactly one event. If you need to simulate a sequence, chain multiple `ctx.run()` calls, feeding the output state of one into the next.

3. **Use `ctx.on.<event>()`** to construct events — never instantiate event objects directly.

4. **Leader tests.** Set `leader=True` on the `State` to test leader-only behaviour:
   ```python
   state = testing.State(leader=True)
   ```

5. **Test both happy and error paths.** Check that the charm sets `BlockedStatus` or `WaitingStatus` when preconditions are not met.

6. **Deferred events.** Check `out.deferred` to verify events were deferred when expected.

## Common Pitfalls

- **Do not use `unittest.mock.patch`** on Juju internals. Scenario handles all Juju interactions through the `State`.
- **Do not import from `ops.testing` inside functions** — keep imports at module level.
- **Container `can_connect=False`** is the default. Set it to `True` when testing Pebble interactions.
