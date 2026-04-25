---
name: adding-config
description: Adding and validating charm configuration options
globs: [config.yaml, charmcraft.yaml, metadata.yaml, src/charm.py, src/**/charm.py]
---

# Adding Configuration Options

Charm configuration lets operators customise behaviour without modifying code. Config values are set with `juju config` and delivered to the charm via `config-changed` events.

## Key Concepts

- **Config is declared in `charmcraft.yaml`** with types, defaults, and descriptions
- **`config-changed` fires** whenever any config value changes
- **Config values persist** across hook executions — read them from `self.config` any time
- **Validate early** — check config in `config-changed` and set `BlockedStatus` if invalid

## Step 1: Declare Config Options

In `charmcraft.yaml`:

```yaml
config:
  options:
    log-level:
      type: string
      default: info
      description: |
        Logging verbosity. One of: debug, info, warning, error.
    port:
      type: int
      default: 8080
      description: |
        Port the workload listens on.
    enable-tls:
      type: boolean
      default: false
      description: |
        Enable TLS for the workload.
    max-connections:
      type: int
      default: 100
      description: |
        Maximum number of concurrent connections.
```

### Supported Types

| Type | Juju Type | Python Type | Example |
|------|-----------|-------------|---------|
| String | `string` | `str` | `"info"` |
| Integer | `int` | `int` | `8080` |
| Float | `float` | `float` | `0.5` |
| Boolean | `boolean` | `bool` | `true` |

## Step 2: Handle config-changed

```python
import ops

VALID_LOG_LEVELS = {"debug", "info", "warning", "error"}


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        log_level = self.config.get("log-level", "info")
        if log_level not in VALID_LOG_LEVELS:
            self.unit.status = ops.BlockedStatus(
                f"Invalid log-level: {log_level!r}. "
                f"Must be one of: {', '.join(sorted(VALID_LOG_LEVELS))}"
            )
            return

        port = self.config["port"]
        if not (1 <= port <= 65535):
            self.unit.status = ops.BlockedStatus(
                f"Invalid port: {port}. Must be between 1 and 65535."
            )
            return

        # Config is valid — apply it.
        self._apply_config()
        self.unit.status = ops.ActiveStatus()

    def _apply_config(self):
        """Apply current config to the workload."""
        # For K8s charms, update the Pebble layer.
        # For machine charms, update config files and restart services.
        ...
```

## Step 3: Apply Config to Pebble (K8s Charms)

```python
def _apply_config(self):
    container = self.unit.get_container("workload")
    if not container.can_connect():
        return

    layer = {
        "services": {
            "workload": {
                "override": "replace",
                "command": "/app/start",
                "environment": {
                    "LOG_LEVEL": self.config["log-level"],
                    "PORT": str(self.config["port"]),
                    "ENABLE_TLS": str(self.config["enable-tls"]).lower(),
                    "MAX_CONNECTIONS": str(self.config["max-connections"]),
                },
            },
        },
    }
    container.add_layer("workload", layer, combine=True)
    container.replan()
```

## Step 4: Apply Config to Machine Charms

```python
def _apply_config(self):
    import subprocess

    config_content = self._render_config_file()
    config_path = "/etc/myapp/config.yaml"

    # Write the config file.
    with open(config_path, "w") as f:
        f.write(config_content)

    # Restart the service.
    subprocess.check_call(["systemctl", "restart", "myapp"])
```

## Step 5: Use Config in Other Hooks

Config is always available via `self.config`, not just in `config-changed`:

```python
def _on_database_changed(self, event: ops.RelationChangedEvent):
    port = self.config["port"]
    # Use port when configuring the database connection.
    ...
```

## Step 6: Test Config with Scenario

```python
from ops import testing


def test_valid_config():
    state = testing.State(config={"log-level": "debug", "port": 9090})
    ctx = testing.Context(MyCharm)
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == testing.ActiveStatus()


def test_invalid_log_level():
    state = testing.State(config={"log-level": "verbose"})
    ctx = testing.Context(MyCharm)
    out = ctx.run(ctx.on.config_changed(), state)
    assert isinstance(out.unit_status, testing.BlockedStatus)
    assert "Invalid log-level" in out.unit_status.message


def test_invalid_port():
    state = testing.State(config={"port": 0})
    ctx = testing.Context(MyCharm)
    out = ctx.run(ctx.on.config_changed(), state)
    assert isinstance(out.unit_status, testing.BlockedStatus)
```

## Step 7: Set Config as an Operator

```bash
# Set a single option.
juju config my-charm log-level=debug

# Set multiple options.
juju config my-charm log-level=debug port=9090

# Reset to default.
juju config my-charm --reset log-level

# View current config.
juju config my-charm
```

## Design Principles

1. **Validate all config values.** Set `BlockedStatus` with a clear message if any value is invalid. Never silently ignore bad config.

2. **Use sensible defaults.** The charm should work out of the box with default config values. Operators should only need to change config for customisation.

3. **Config names use hyphens** (e.g., `log-level`, `max-connections`). This is the Juju convention. Access them in Python with `self.config["log-level"]`.

4. **Keep config options stable.** Renaming or removing config options breaks existing deployments. Add new options freely; deprecate old ones gradually.

5. **Document each option clearly.** The `description` field in `charmcraft.yaml` is what operators see when running `juju config my-charm --all`. Write it for a human audience.

6. **Apply config idempotently.** `config-changed` fires on every `juju config` call, even if the value did not actually change. The handler should apply config without side effects if nothing changed.

## Common Pitfalls

- **Not handling `config-changed` at all** — config values are still accessible via `self.config`, but the workload will not be updated until the charm explicitly applies them.
- **Crashing on invalid config** — always validate and set `BlockedStatus` instead of raising exceptions.
- **Assuming config types are correct** — Juju enforces the type declared in metadata, but it is good practice to validate ranges and allowed values.
- **Forgetting to `replan()` after updating a Pebble layer** — the service will not restart with the new config until `replan()` is called.
