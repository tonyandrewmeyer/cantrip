---
name: adding-actions
description: Implementing Juju actions for operational tasks in charms
globs: [actions.yaml, charmcraft.yaml, metadata.yaml, src/charm.py, src/**/charm.py]
---

# Adding Actions to Charms

Juju **actions** are operator-triggered tasks — think "backup the database", "rotate credentials", or "dump debug info". They run on demand and return structured results.

## Key Concepts

- **Actions are for operational tasks** — things an operator does occasionally, not things that happen automatically
- **Actions run on a specific unit** — invoked with `juju run <unit> <action>`
- **Actions can accept parameters** and return structured results
- **Actions should be idempotent** where possible — running the same action twice should be safe

## Step 1: Define Actions in Metadata

Create or edit `charmcraft.yaml` to declare actions:

```yaml
actions:
  backup:
    description: Create a backup of the application data.
    params:
      path:
        type: string
        description: Destination path for the backup file.
        default: /var/backups
    required: [path]

  rotate-credentials:
    description: Rotate database credentials and update all connected applications.

  get-admin-password:
    description: Retrieve the current admin password.
```

### Parameter Types

Juju action parameters use JSON Schema types:

- `string` — text values
- `integer` — whole numbers
- `number` — floating-point numbers
- `boolean` — true/false
- `array` — lists (with `items` specifying element type)
- `object` — nested structures

## Step 2: Implement Action Handlers

```python
import ops


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on.backup_action, self._on_backup)
        self.framework.observe(
            self.on.rotate_credentials_action,
            self._on_rotate_credentials,
        )
        self.framework.observe(
            self.on.get_admin_password_action,
            self._on_get_admin_password,
        )

    def _on_backup(self, event: ops.ActionEvent):
        path = event.params["path"]
        try:
            backup_id = self._perform_backup(path)
            event.set_results({
                "backup-id": backup_id,
                "path": path,
                "status": "success",
            })
        except FileNotFoundError:
            event.fail(f"Backup path does not exist: {path}")

    def _on_rotate_credentials(self, event: ops.ActionEvent):
        if not self.unit.is_leader():
            event.fail("Credential rotation must run on the leader unit.")
            return
        new_password = self._rotate_db_password()
        event.set_results({"status": "rotated"})

    def _on_get_admin_password(self, event: ops.ActionEvent):
        password = self._get_stored_password()
        event.set_results({"password": password})
```

## Step 3: Handle Long-Running Actions

For actions that take time, use progress logging:

```python
def _on_backup(self, event: ops.ActionEvent):
    event.log("Starting backup...")
    # Phase 1
    self._dump_database(event.params["path"])
    event.log("Database dumped, compressing...")
    # Phase 2
    archive = self._compress_backup(event.params["path"])
    event.log("Backup complete.")
    event.set_results({"archive": str(archive)})
```

## Step 4: Run Actions

```bash
# Run with default parameters.
juju run my-charm/0 backup

# Run with parameters.
juju run my-charm/0 backup path=/mnt/backups

# Run on the leader.
juju run my-charm/leader get-admin-password
```

## Step 5: Test Actions with Scenario

```python
from ops import testing


def test_backup_action():
    ctx = testing.Context(MyCharm)
    state = testing.State()
    out = ctx.run(ctx.on.action("backup", params={"path": "/data"}), state)
    assert out.action_results["status"] == "success"
    assert "backup-id" in out.action_results


def test_backup_action_invalid_path():
    ctx = testing.Context(MyCharm)
    state = testing.State()
    out = ctx.run(ctx.on.action("backup", params={"path": "/nonexistent"}), state)
    assert out.action_failure  # Action called event.fail()
```

## Design Principles

1. **Actions are for operator-initiated tasks.** Do not use actions for things that should happen automatically (use events/hooks for those).

2. **Return structured results.** Use `event.set_results()` with clear key-value pairs. Callers parse these programmatically.

3. **Fail explicitly.** Call `event.fail("reason")` with a descriptive message when an action cannot complete. Do not silently succeed.

4. **Leader-only actions.** Some actions (like credential rotation) should only run on the leader. Check `self.unit.is_leader()` and fail with a clear message if not.

5. **Use hyphens in action names** (e.g., `rotate-credentials`). Juju converts hyphens to underscores for the Python event name (`rotate_credentials_action`).

6. **Document parameters clearly** in the `charmcraft.yaml` `actions` section. Operators rely on `juju actions my-charm` to understand what is available.

## Common Pitfalls

- **Forgetting the observer or the terminating call.** The action-name → event-attribute mapping (`my-action` → `self.on.my_action_action`) and the requirement that every handler call `event.set_results()` or `event.fail()` are checked deterministically by `charmlint` (rules `ACT006` and `ACT007`). Run `charmlint` to surface these — the skill body no longer recites them.
- **Modifying charm state in actions without guards** — actions can run concurrently with hooks. Be careful about shared state.
- **Returning sensitive data** — action results are stored in Juju's database and visible to anyone with model access. Use Juju secrets for sensitive values.
