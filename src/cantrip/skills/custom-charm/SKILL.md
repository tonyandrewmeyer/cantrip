---
name: custom-charm
description: End-to-end workflow for building ops-framework charms for custom applications (K8s and machine)
---

# Custom Application Charm Workflow

This skill covers building a Juju charm for an application that does **not** fit a recognised 12-factor PaaS framework (Flask, Django, FastAPI, Go, Express, Spring Boot). These charms use the full ops framework — you write `src/charm.py` yourself, managing the workload lifecycle directly via Pebble (K8s) or systemd/apt (machine).

## When to Use This Path

Use this path (Path B) when:
- The application is **not** one of the six PaaS-supported frameworks
- You need **full control** over the workload lifecycle (custom start sequences, multi-process, etc.)
- The workload requires **non-standard packaging** (not a simple WSGI/ASGI/HTTP server)
- The user explicitly requests a custom ops-framework charm

Do **not** use this path for:
- Flask, Django, FastAPI, Go, Express, Spring Boot → use the `twelve-factor` skill instead
- Infrastructure software (databases, caches, message brokers) → Path C

## Substrate Decision Matrix

Choose the substrate **before** scaffolding. Ask the user to confirm.

| Signal | Substrate | Reasoning |
|--------|-----------|-----------|
| Dockerfile or OCI image exists | K8s | Already containerised; natural fit for Pebble |
| Cloud-native / stateless workload | K8s | Designed for orchestration |
| Bare metal / GPU / kernel modules | Machine | Needs direct hardware access |
| systemd service files present | Machine | Already designed for systemd |
| Heavy OS-level integration (PAM, cron, udev) | Machine | Relies on host OS services |
| No strong signal | K8s (default) | Easier to distribute and test |

## Step-by-Step Workflow

### 1. Analyse the Application

Run `analyse_framework` on the source directory. When no PaaS framework is detected, the tool returns `workload_hints` indicating whether a Dockerfile, docker-compose file, or systemd service files are present, along with a `suggested_substrate`.

### 2. Confirm the Substrate

Present the substrate recommendation to the user with reasoning. Wait for confirmation before proceeding — this choice affects everything downstream.

### 3. Scaffold the Charm

Use `charmcraft_init` with the appropriate profile:

- **K8s:** `profile: "kubernetes"`
- **Machine:** `profile: "machine"`

```bash
charmcraft init --profile=kubernetes --name=my-app
```

This creates the base structure: `charmcraft.yaml`, `src/charm.py`, `tox.ini`, and test directories.

### 4. Customise `charmcraft.yaml`

#### K8s Charm

Add containers, resources, and storage:

```yaml
name: my-app
type: charm
bases:
  - build-on:
      - name: ubuntu
        channel: "22.04"
    run-on:
      - name: ubuntu
        channel: "22.04"

containers:
  my-app:
    resource: oci-image

resources:
  oci-image:
    type: oci-image
    description: OCI image for the application

storage:
  data:
    type: filesystem
    minimum-size: 1G
    location: /data

requires:
  tracing:
    interface: tracing
    limit: 1
```

#### Machine Charm

Machine charms typically need no containers or OCI resources:

```yaml
name: my-app
type: charm
bases:
  - build-on:
      - name: ubuntu
        channel: "22.04"
    run-on:
      - name: ubuntu
        channel: "22.04"

storage:
  data:
    type: filesystem
    minimum-size: 1G
    location: /data

requires:
  tracing:
    interface: tracing
    limit: 1
```

### 5. Write `src/charm.py`

#### K8s Charm (Pebble)

```python
#!/usr/bin/env python3
"""Charm for my-app on Kubernetes."""

import ops
import ops_tracing


class MyAppCharm(ops.CharmBase):
    """Charm the application using Pebble."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        ops_tracing.setup(self)
        self._container = self.unit.get_container("my-app")

        framework.observe(self.on["my-app"].pebble_ready, self._on_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Start the workload when the container is ready."""
        self._container.add_layer("my-app", self._pebble_layer(), combine=True)
        self._container.autostart()
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Update the workload config and restart if running."""
        if not self._container.can_connect():
            event.defer()
            return
        self._container.add_layer("my-app", self._pebble_layer(), combine=True)
        self._container.replan()
        self.unit.status = ops.ActiveStatus()

    def _pebble_layer(self) -> ops.pebble.LayerDict:
        """Return the Pebble layer configuration."""
        return {
            "summary": "my-app layer",
            "description": "Pebble layer for my-app",
            "services": {
                "my-app": {
                    "override": "replace",
                    "summary": "my-app service",
                    "command": "/usr/bin/my-app",
                    "startup": "enabled",
                    "environment": {},
                },
            },
        }


if __name__ == "__main__":
    ops.main(MyAppCharm)
```

**Key patterns for K8s charms:**
- Get the container with `self.unit.get_container("container-name")`
- Observe `pebble-ready` — this fires when the container's Pebble agent becomes reachable
- Use `add_layer()` + `autostart()` on first start; `add_layer()` + `replan()` on changes
- Check `self._container.can_connect()` before interacting with Pebble; defer if not ready
- Use `self._container.push()` to write config files into the container
- Use `self._container.exec()` to run commands inside the container

#### Machine Charm (systemd)

```python
#!/usr/bin/env python3
"""Charm for my-app on machines."""

import subprocess

import ops
import ops_tracing


class MyAppCharm(ops.CharmBase):
    """Charm the application using apt and systemd."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        ops_tracing.setup(self)

        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install packages and prepare the system."""
        self.unit.status = ops.MaintenanceStatus("Installing dependencies")
        subprocess.check_call(["apt-get", "update", "-y"])
        subprocess.check_call(["apt-get", "install", "-y", "my-app"])

    def _on_start(self, event: ops.StartEvent) -> None:
        """Start the workload service."""
        subprocess.check_call(["systemctl", "enable", "--now", "my-app"])
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Update configuration and restart the service."""
        self._write_config()
        subprocess.check_call(["systemctl", "restart", "my-app"])
        self.unit.status = ops.ActiveStatus()

    def _write_config(self) -> None:
        """Write the application config file from charm config."""
        # Read charm config and write to the appropriate location.
        # Example: /etc/my-app/config.yaml
        pass


if __name__ == "__main__":
    ops.main(MyAppCharm)
```

**Key patterns for machine charms:**
- Use `install` event for package installation (`apt-get`, `snap install`)
- Use `start` event to enable and start the systemd service
- Write config files to standard locations (`/etc/my-app/`, etc.)
- Use `subprocess.check_call()` for system commands
- Use `systemctl restart` after config changes

### 6. Common Patterns

#### Status Management

Set status to communicate the charm's state to the operator:

```python
# During long operations.
self.unit.status = ops.MaintenanceStatus("Installing packages")

# When waiting for a relation.
self.unit.status = ops.WaitingStatus("Waiting for database relation")

# When a required config option is missing.
self.unit.status = ops.BlockedStatus("Missing required config: database-url")

# When everything is working.
self.unit.status = ops.ActiveStatus()
```

#### Config Validation

Validate config early and set `BlockedStatus` on invalid input:

```python
def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
    port = self.config.get("port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        self.unit.status = ops.BlockedStatus("Invalid port number")
        return
    # Apply the valid config...
```

#### Relation Handling

Read and write relation data in event handlers:

```python
def _on_database_relation_changed(self, event: ops.RelationChangedEvent) -> None:
    if not event.unit:
        return
    host = event.relation.data[event.unit].get("host")
    port = event.relation.data[event.unit].get("port")
    if not host or not port:
        self.unit.status = ops.WaitingStatus("Waiting for database credentials")
        return
    # Configure the workload with the database connection...
```

For detailed relation data patterns, load the `relation-data-design` skill.

#### Storage

Access Juju-managed storage in event handlers:

```python
def _on_storage_attached(self, event: ops.StorageAttachedEvent) -> None:
    storage_path = event.storage.location
    # Use storage_path for persistent data...
```

#### Secrets (Juju 3.x)

Use Juju secrets for sensitive data:

```python
def _on_secret_changed(self, event: ops.SecretChangedEvent) -> None:
    secret = event.secret
    content = secret.get_content(refresh=True)
    password = content.get("password")
    # Apply the new secret...
```

### 7. Build and Deploy

Custom charms do **not** need rockcraft. The cycle is:

```bash
charmcraft pack
juju deploy ./my-app_amd64.charm
```

For K8s charms with an OCI image resource:

```bash
charmcraft pack
juju deploy ./my-app_amd64.charm --resource oci-image=docker.io/library/my-app:latest
```

Use the `charmcraft_pack` and `juju_deploy` tools. For K8s charms, pass the OCI image via `resources={"oci-image": "..."}`.

### 8. Fast Dev Cycle

For Python source changes only, use the fast path:

1. Edit `src/charm.py` (or files in `src/` and `lib/`)
2. `charm_sync` to push changes to the running unit
3. `juju_dispatch` to fire an event (e.g. `config-changed`, `update-status`)

Use the full `charmcraft_pack` → `juju_refresh` cycle when:
- `charmcraft.yaml` changed (new relations, config options, resources)
- Dependencies changed (`requirements.txt`)
- Before declaring the charm done

### 9. Generate Tests

**Unit tests:** Load the `scenario-tests` skill. Cover:
- `install` / `start` → `ActiveStatus`
- `pebble-ready` (K8s) → Pebble layer applied, service started
- `config-changed` → config applied, service restarted
- Relation events → data read/written correctly
- Actions (if any)

**Integration tests:** Load the `jubilant-tests` skill. Cover:
- Deploy → `ActiveStatus`
- Relate to required integrations
- Config changes take effect
- Actions produce expected results

### 10. Validate

Run `charm_validate` before declaring the charm complete. This runs unit tests and `charmcraft pack`, producing a pass/fail checklist.

## Re-Deploying After Changes

```
charmcraft_pack → juju_refresh --path → juju_wait → verify
```

No rockcraft or registry push needed for custom charms (unlike 12-factor).

## Common Pitfalls

1. **Interacting with Pebble before it is ready** — always check `can_connect()` and defer if the container is not reachable. The `pebble-ready` event fires when it becomes available.

2. **Forgetting to `combine=True` in `add_layer()`** — without it, repeated calls create duplicate layers instead of merging.

3. **Blocking the hook with long-running commands** — hooks have a timeout (default 5 minutes). For long installations, consider breaking work across events or increasing the timeout.

4. **Writing config directly in the install hook** — config values may not be set yet during install. Use `config-changed` for applying configuration.

5. **Using `kubernetes` profile for a PaaS framework** — if the app is Flask/Django/etc., use the framework profile with the `twelve-factor` skill instead. The `kubernetes` profile gives a bare ops charm.

6. **Missing OCI image resource for K8s charms** — the `containers` section in `charmcraft.yaml` must reference a `resource`, and that resource must be declared in the `resources` section.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Unit stuck in `waiting` with "waiting for Pebble" | Container not started or image pull failed | Check `juju debug-log`; verify OCI image resource is correct |
| `pebble-ready` never fires | Container name mismatch between `charmcraft.yaml` and charm code | Ensure the container name in `self.on["name"]` matches `charmcraft.yaml` |
| `ConnectionError` from Pebble | Calling Pebble methods before `can_connect()` returns True | Add a `can_connect()` guard and defer the event |
| Service crashes after `replan()` | Bad command or missing binary in the container | Check the Pebble layer `command`; use `container.exec()` to debug |
| `apt-get` fails during install (machine) | Missing universe repo or network issue | Add `add-apt-repository` or check proxy settings |
| `systemctl` fails (machine) | Service file not installed or unit not enabled | Verify the package installs a `.service` file; use `systemctl status` |
| Charm goes to `error` on relation event | Accessing relation data that does not exist yet | Guard with `if not event.unit: return` and check for required keys |
| Config change has no effect | Forgot to restart the service after writing new config | Call `replan()` (K8s) or `systemctl restart` (machine) after applying config |
