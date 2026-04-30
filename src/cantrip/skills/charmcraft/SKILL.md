---
name: charmcraft
description: Expert guidance for developing, building, testing, and publishing Juju charms using charmcraft
---

# Charmcraft Development Assistant

Expert guidance for developing, building, testing, and publishing Juju charms using charmcraft.

## Core Workflows

### Project Initialisation

```bash
# Initialise new charm with profile
charmcraft init --profile=kubernetes            # K8s charm (default)
charmcraft init --profile=machine               # Machine charm
charmcraft init --profile=flask-framework       # Flask 12-factor (stable)
charmcraft init --profile=django-framework      # Django 12-factor (stable)
charmcraft init --profile=fastapi-framework     # FastAPI 12-factor (experimental)
charmcraft init --profile=go-framework          # Go 12-factor (experimental)
charmcraft init --profile=express-framework     # ExpressJS 12-factor (experimental)
charmcraft init --profile=spring-boot-framework # Spring Boot 12-factor (experimental)

# Experimental profiles need:
#   CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true charmcraft init …
#   CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true charmcraft pack
# Cantrip's `charmcraft_init` tool sets the flag automatically for the
# four experimental profiles.

# With custom name and author
charmcraft init --name=my-charm --author="Your Name"

# List/expand extensions
charmcraft list-extensions
charmcraft expand-extensions
```

If the directory is not empty (for example, there is a plan, `AGENTS.md`, or a `.git` folder), you need to add `--force`.

**After init:**
1. Customise `charmcraft.yaml` (metadata, bases, relations, config)
2. Edit `README.md` (becomes Charmhub documentation)
3. Implement `src/charm.py` (using Ops framework).  Charmcraft 4.2's
   `kubernetes` and `machine` profiles scaffold a `src/workload.py`
   module alongside the charm so workload-specific logic stays out of
   `src/charm.py`.  Keep this split when you grow the charm — the
   charm class wires Juju events; the workload module talks to the
   process or container.
4. Update tests in `tests/unit/` and `tests/integration/`.  Templates
   now use `pytest-jubilant` for integration tests out of the box (see
   the `jubilant-tests` skill).

### Building and Packaging

```bash
# Build charm
charmcraft pack                    # Main command
charmcraft pack -o ./build/        # Custom output directory
charmcraft pack --bases-index=0    # Specific base (if multiple defined)

# Analyse charm (always run before uploading!)
charmcraft analyse ./my-charm_ubuntu-22.04-amd64.charm
charmcraft analyse --format=json ./my-charm.charm

# Clean build artefacts
charmcraft clean

# Remote build (for multi-architecture)
charmcraft remote-build
```

**Build lifecycle:** `pack` handles everything automatically. Only use individual steps (`pull`, `build`, `stage`, `prime`) for debugging.

**Always run `charmcraft analyse` before uploading to catch:**
- Missing/malformed metadata
- File permission issues
- Deprecated patterns

### Testing

```bash
# Run tests
charmcraft test                    # Integration tests
charmcraft test --shell            # Debug environment
charmcraft test --debug            # Shell on failure

# Local quality checks
tox -e format                      # Format with ruff
tox -e lint                        # Lint with ruff + pyright
tox -e unit                        # Unit tests (ops.testing)
tox -e integration                 # Integration tests
```

### Publishing to Charmhub

```bash
# Account setup
charmcraft login
charmcraft whoami
charmcraft register my-charm       # Register name first

# Upload and release
charmcraft upload ./my-charm.charm --release=edge
charmcraft status my-charm         # Check status
charmcraft revisions my-charm      # List revisions

# Release specific revision
charmcraft release my-charm --revision=5 --channel=stable

# Promote between channels
charmcraft promote my-charm --from=beta --to=stable

# Close channel
charmcraft close my-charm edge
```

**Channel structure:** `[track/]risk[/branch]`
- Risks: `edge` -> `beta` -> `candidate` -> `stable`
- Examples: `stable`, `edge`, `2.0/candidate`, `beta/hotfix-123`

**Always:** Upload to `edge` first, test thoroughly, then promote through channels.

#### Resources

```bash
# Manage resources (images, binaries)
charmcraft resources my-charm
charmcraft upload-resource my-charm my-resource --filepath=./file.tar.gz
charmcraft resource-revisions my-charm my-resource

# Release with specific resources
charmcraft release my-charm --revision=5 --channel=stable --resource=my-resource:3
```

### Library Management

```bash
# Using libraries (define in charmcraft.yaml first)
charmcraft fetch-libs              # Fetch defined libraries
charmcraft list-lib postgresql     # List available libs

# Publishing libraries
charmcraft create-lib my-charm my_library
charmcraft publish-lib charms.my_charm.v0.my_library
```

**In charmcraft.yaml:**
```yaml
charm-libs:
  - lib: postgresql.postgres_client
    version: "0"           # Major version (auto-updates minor)
  - lib: mysql.client
    version: "0.57"        # Pinned version
```

**Library versioning:**
- `v0`, `v1` = breaking changes (API changes)
- Patch auto-increments for non-breaking changes
- Libraries go in `lib/charms/{charm_name}/v{X}/{lib_name}.py`

### Libraries on PyPI (`charmlibs-*`)

A growing subset of the ecosystem has been lifted into the
`canonical/charmlibs` monorepo and is published to PyPI.  Prefer the
PyPI package — it's versioned, hash-pinnable, and avoids a `charmcraft
fetch-libs` step.  The import path changes from `charms.foo.vN.bar`
to `charmlibs.bar` (or `charmlibs.interfaces.bar`).

| PyPI package | Import | Replaces |
|--------------|--------|----------|
| `charmlibs-pathops` | `from charmlibs import pathops` | — (new; pathlib-style API for Pebble containers + local filesystem) |
| `charmlibs-apt` | `from charmlibs import apt` | `charms.operator_libs_linux.v0.apt` |
| `charmlibs-snap` | `from charmlibs import snap` | `charms.operator_libs_linux.v*.snap` |
| `charmlibs-passwd` | `from charmlibs import passwd` | `charms.operator_libs_linux.v*.passwd` |
| `charmlibs-sysctl` | `from charmlibs import sysctl` | `charms.operator_libs_linux.v*.sysctl` |
| `charmlibs-systemd` | `from charmlibs import systemd` | `charms.operator_libs_linux.v*.systemd` |
| `charmlibs-nginx-k8s` | `from charmlibs import nginx_k8s` | Charm-side nginx helpers |
| `charmlibs-interfaces-tls-certificates` | `from charmlibs.interfaces import tls_certificates` | `charms.tls_certificates_interface.v*` |
| `charmlibs-interfaces-certificate-transfer` | `from charmlibs.interfaces import certificate_transfer` | `charms.certificate_transfer_interface.v*` |
| `charmlibs-interfaces-otlp` | `from charmlibs.interfaces import otlp` | interface schema only |
| `charmlibs-interfaces-mcp` | `from charmlibs.interfaces import mcp` | interface schema only |
| `charmlibs-interfaces-sloth` | `from charmlibs.interfaces import sloth` | interface schema only |
| `charmlibs-interfaces-k8s-backup-target` | `from charmlibs.interfaces import k8s_backup_target` | interface schema only |
| `charmlibs-interfaces-gateway-metadata` | `from charmlibs.interfaces import gateway_metadata` | interface schema only |
| `cosl` | `import cosl` | COS Lite utilities (topology labels, Loki logging handler, cos-tool bindings) |

Install with uv:

```bash
uv add charmlibs-pathops
uv add charmlibs-apt charmlibs-snap  # just the submodules you need
```

### Libraries that still need `charmcraft fetch-libs`

These charm libraries are **not on PyPI yet** and must be fetched the
classic way:

- `charms.loki_k8s.*` — log-forwarder library
- `charms.grafana_k8s.*` — dashboard provider
- `charms.prometheus_k8s.*` — scrape library
- `charms.traefik_k8s.*` — ingress requirer
- `charms.tempo_k8s.*`, `charms.tempo_coordinator_k8s.*`
- `charms.catalogue_k8s.*`
- `charms.observability_libs.*`
- `charms.data_platform_libs.*` (Juju data-platform relation interfaces — PyPI namespace `dpcharmlibs` is reserved but not yet populated)
- `charms.sdcore_nms_k8s.*`
- `charms.hydra.*` — Canonical Identity Platform OAuth / OIDC requirer libs (`oauth`, `oauth_cli`, `oidc_info`, `token_introspect`); load the `identity-platform` skill when wiring these
- `charms.kratos.*` — Kratos identity / external-IdP libs (`kratos_external_idp`, `kratos_info`); load the `identity-platform` skill when wiring these
- most other charm-specific interface libraries (e.g. `charms.vault_kv.*` etc.) — check their host charm before assuming

## charmcraft.yaml Reference

### File Structure

```yaml
# Required fields
name: string              # Charm name (lowercase, hyphens, no spaces)
type: charm | bundle      # Always "charm"

# Recommended fields
title: string             # Human-readable title
summary: string           # Short description (< 100 chars)
description: |            # Full description (supports markdown)
  Multi-line description of your charm.

# Base configuration (Charmcraft 4.2 form — preferred)
base: ubuntu@24.04
build-base: ubuntu@24.04
platforms:
  amd64:
  arm64:           # Optional — list each platform you build for.

# Declare runtime expectations.  K8s charms on Charmcraft 4.2 should
# include both juju >= 3.6 and k8s-api so deployment fails fast on
# incompatible controllers.
assumes:
  - juju >= 3.6
  - k8s-api        # Drop this line for machine charms.

# Build configuration (required)
parts:
  charm:
    plugin: uv
    source: .
    build-snaps:
      - astral-uv

# Optional but recommended
extensions: []           # List of extensions to use
charm-libs: []           # Library dependencies
links:                   # Links shown on Charmhub
  documentation: https://discourse.charmhub.io/...
  issues: https://github.com/...
  source: https://github.com/...
  website: https://...
```

### Config Options

```yaml
config:
  options:
    port:
      type: int
      description: "Port to listen on"
      default: 8080
    enable-tls:
      type: boolean
      description: "Enable TLS/SSL"
      default: false
    server-name:
      type: string
      description: "Server hostname"
      default: "localhost"
```

Types: `string`, `int`, `float`, `boolean`, `secret`

### Actions

```yaml
actions:
  backup:
    description: "Create a backup"
    params:
      destination:
        type: string
        description: "Backup destination path"
    required: [destination]
    additionalProperties: false
```

Always include `additionalProperties: false` in action definitions.

### Relations

```yaml
provides:
  website:
    interface: http

requires:
  database:
    interface: postgresql
    optional: true

  ingress:
    interface: ingress
    optional: true
    limit: 1

peers:
  cluster:
    interface: cluster
```

**ALWAYS include `optional: true` or `optional: false`** for `requires` relations — never rely on the default.

### Containers (Kubernetes Charms)

```yaml
containers:
  my-app:
    resource: my-image
    mounts:
      - storage: data
        location: /data

resources:
  my-image:
    type: oci-image
    description: "Application image"
```

### Storage

```yaml
storage:
  data:
    type: filesystem
    description: "Application data"
    location: /var/lib/myapp
    minimum-size: 1G
```

### Storage events on K8s

K8s charms support a single instance of each declared storage; machine
charms get a list.  Read events with bracket notation, never attribute
notation:

```python
self.framework.observe(
    self.on["data"].storage_attached,   # bracket notation
    self._on_data_attached,
)
```

In the handler, resolve the workload mount from charmcraft metadata:

```python
mount = self.meta.containers["my-app"].mounts["data"].location
```

For K8s charms there is exactly one storage instance, so index `[0]`:

```python
storage = self.model.storages["data"][0]
```

Consider the `pathops` library (on PyPI) when you need pathlib-style
file operations against the workload container.

### Multi-Base Builds

To target multiple bases, declare a `platforms` entry per base/arch and
pack each separately.  Charmcraft 4.2 retired the `build-on`/`run-on`
matrix; use one charmcraft.yaml per base or override at pack time:

```bash
charmcraft pack --base=ubuntu@24.04
charmcraft pack --base=ubuntu@22.04
```

### Juju / Pebble / ops version matrix

When picking values for the `assumes:` block, line up with the version
matrix the upstream operator docs publish:

| Juju  | Pebble  | Notes                                     |
|-------|---------|-------------------------------------------|
| 3.6   | 1.19.2  | LTS — safe minimum for Charmcraft 4.2.    |
| 4.0   | 1.26.0  | Required for newer Pebble notice / check kinds. |

Bump the floor only when the charm actually uses a feature that needs it.

## Common Patterns

### Database Integration Example

```yaml
# In charmcraft.yaml
requires:
  database:
    interface: postgresql_client
    optional: true

charm-libs:
  - lib: data_platform_libs.data_interfaces
    version: "0"
```

```python
# In src/charm.py
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires

class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.database = DatabaseRequires(self, "database", "myapp")
        self.framework.observe(
            self.database.on.database_created,
            self._on_database_created
        )
```

## Best Practices

### Development Workflow
1. **Write integration tests first** — define expected behaviour
2. **Implement incrementally** — get basic functionality working
3. **Run quality checks** — `tox -e lint` and `tox -e format` frequently
4. **Analyse before upload** — `charmcraft analyse` on every build
5. **Test locally** — `charmcraft pack` then `juju deploy ./my-charm.charm`

### Version Control
Commit: `charmcraft.yaml`, all source, `uv.lock`, `pyproject.toml`, tests, docs

Ignore: `*.charm`, `__pycache__/`, `.tox/`, `venv/`, `.claude/settings.local.json`

## Troubleshooting

**Build fails:**
- Check `charmcraft.yaml` syntax
- Verify required files exist (`src/charm.py`, `uv.lock`)
- Run `charmcraft -v pack` for verbose output

**Upload fails:**
- Login: `charmcraft login`
- Register name: `charmcraft register my-charm`
- Analyse first: `charmcraft analyse ./my-charm.charm`

**Library errors:**
- Fetch: `charmcraft fetch-libs`
- Check library definitions in `charmcraft.yaml`

**Runtime issues:**
- Check Juju logs: `juju debug-log`
- Verify resources uploaded: `charmcraft resources my-charm`
- Test base compatibility

**Changes not reflected in charm:**
- Always repack after changes: `charmcraft clean && charmcraft pack`
- Refresh deployed charm: `juju refresh my-charm --path=./my-charm.charm`

## Quick Reference

```bash
# Setup
charmcraft init --profile=kubernetes
charmcraft login

# Development cycle
charmcraft pack
charmcraft analyse ./my-charm.charm
tox -e lint
tox -e unit

# Publishing
charmcraft upload ./my-charm.charm --release=edge
charmcraft status my-charm
charmcraft promote my-charm --from=edge --to=beta

# Libraries
charmcraft fetch-libs
charmcraft publish-lib charms.my_charm.v0.my_library

# Testing with Juju
juju deploy ./my-charm.charm
juju status
juju debug-log
```

## Resources

- **Charmcraft docs**: https://documentation.ubuntu.com/charmcraft/stable/
- **Juju docs**: https://documentation.ubuntu.com/juju/latest/
- **Ops framework**: https://documentation.ubuntu.com/ops/latest/
- **Charmhub**: https://charmhub.io/
