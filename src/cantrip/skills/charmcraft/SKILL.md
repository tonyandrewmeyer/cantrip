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
charmcraft init --profile=kubernetes       # K8s charm (default)
charmcraft init --profile=machine          # Machine charm
charmcraft init --profile=django-framework # Django app
charmcraft init --profile=fastapi-framework # FastAPI app
charmcraft init --profile=flask-framework  # Flask app

# With custom name and author
charmcraft init --name=my-charm --author="Your Name"

# List/expand extensions
charmcraft list-extensions
charmcraft expand-extensions
```

If the directory is not empty (for example, there is a plan, `CLAUDE.md`, or a `.git` folder), you need to add `--force`.

**After init:**
1. Customise `charmcraft.yaml` (metadata, bases, relations, config)
2. Edit `README.md` (becomes Charmhub documentation)
3. Implement `src/charm.py` (using Ops framework)
4. Update tests in `tests/unit/` and `tests/integration/`

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

# Base configuration (required for charms)
bases:
  - build-on:
      - name: ubuntu
        channel: "22.04"
        architectures: [amd64]
    run-on:
      - name: ubuntu
        channel: "22.04"
        architectures: [amd64]

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

### Multi-Base Builds

```yaml
bases:
  - build-on:
      - name: ubuntu
        channel: "22.04"
    run-on:
      - name: ubuntu
        channel: "22.04"
  - build-on:
      - name: ubuntu
        channel: "24.04"
    run-on:
      - name: ubuntu
        channel: "24.04"
```

Pack for specific base: `charmcraft pack --bases-index=0`

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
