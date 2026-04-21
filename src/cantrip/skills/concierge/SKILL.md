---
name: concierge
description: Provisioning charm development and testing environments using concierge presets and custom configuration
---

# Concierge Development Environment Assistant

Expert guidance for provisioning and managing charm development and testing environments using concierge.

## What is Concierge?

Concierge is an opinionated utility for automating the setup of charm development machines. It:
- Installs craft tools (charmcraft, snapcraft, rockcraft)
- Configures providers (LXD, MicroK8s, K8s, Google Cloud)
- Bootstraps Juju controllers
- Installs additional packages (snaps and debs)
- Provides environment restoration capabilities

## Core Workflows

### Quick Start with Presets

```bash
# Full development environment (recommended for most developers)
concierge prepare -p dev

# Machine charm development only
concierge prepare -p machine

# Kubernetes-focused development
concierge prepare -p k8s

# Lightweight K8s with MicroK8s
concierge prepare -p microk8s

# Build tools only (no Juju)
concierge prepare -p crafts
```

**Presets comparison:**

| Preset | Juju | LXD | K8s | MicroK8s | Charmcraft | Snapcraft | Rockcraft | Jhack |
|--------|------|-----|-----|----------|------------|-----------|-----------|-------|
| **dev** | Yes | Yes (bootstrapped) | Yes (bootstrapped) | -- | Yes | Yes | Yes | Yes |
| **machine** | Yes | Yes (bootstrapped) | -- | -- | Yes | Yes | -- | -- |
| **k8s** | Yes | Yes (build only) | Yes (bootstrapped) | -- | Yes | -- | Yes | -- |
| **microk8s** | Yes | Yes (build only) | -- | Yes (bootstrapped) | Yes | -- | Yes | -- |
| **crafts** | -- | Yes | -- | -- | Yes | Yes | Yes | -- |

### Environment Status

```bash
# Check provisioning status
concierge status

# Possible states: "provisioning", "succeeded", "failed"
```

### Restoring Original State

```bash
# Reverse the prepare operation
concierge restore
```

**WARNING:** `restore` does NOT account for packages/configuration that existed before `prepare`. It literally reverses the `prepare` operation. If you had LXD installed before running `prepare`, `restore` will remove it.

### Preview mode (`--dry-run`)

Both `prepare` and `restore` accept `--dry-run`, which prints the
shell commands that *would* run without actually touching the system.
Useful for reviewing what a preset or custom config will do before
committing — especially on a machine that already has snaps or a Juju
controller you don't want clobbered.

```bash
concierge prepare -p k8s --dry-run
concierge restore --dry-run
```

### Custom Configuration

Create a `concierge.yaml` file in your working directory:

```yaml
juju:
  channel: "3.6/stable"
  agent_version: "3.6.0"
  bootstrap_constraints:
    cores: 4
    mem: 8G
  model_defaults:
    logging-config: "<root>=INFO"
  # Arbitrary flags appended to `juju bootstrap`; shell-style splitting.
  extra-bootstrap-args: --config idle-connection-timeout=90s --auto-upgrade=true

providers:
  microk8s:
    enable: true
    bootstrap: true
    channel: "1.31-strict/stable"
    # Mirror docker.io when rate limits or corporate proxies bite.
    # Values interpolate ``$VAR`` / ``${VAR}`` from the environment.
    image-registry:
      url: https://mirror.example.com
      username: ${REGISTRY_USER}
      password: ${REGISTRY_PASS}

  lxd:
    enable: true
    bootstrap: true
    channel: "5.21/stable"

  k8s:
    enable: false
    # Same image-registry shape also supported on the k8s provider.

  gcloud:
    enable: false

host:
  snaps:
    - name: astral-uv
      channel: "latest/edge"
      classic: true
    - name: jhack
      channel: "latest/stable"

  debs:
    - build-essential
    - python3-dev
```

Then run:
```bash
concierge prepare -c concierge.yaml
```

### Overriding Configuration

```bash
# Override snap channels
concierge prepare -p dev --juju-channel=4.0/edge

# Install extra packages
concierge prepare -p dev \
  --extra-snaps=astral-uv/latest/edge,jhack \
  --extra-debs=build-essential,python3-tox

# Skip Juju installation/bootstrap
concierge prepare -p crafts --disable-juju

# Use Google Cloud credentials
concierge prepare -p k8s --google-credential-file=~/gcloud-creds.json
```

**Channel override flags:**
- `--juju-channel`
- `--lxd-channel`
- `--k8s-channel`
- `--microk8s-channel`
- `--charmcraft-channel`
- `--snapcraft-channel`
- `--rockcraft-channel`

### Environment Variables

All flags have environment variable equivalents:

```bash
export CONCIERGE_JUJU_CHANNEL="4.0/edge"
export CONCIERGE_EXTRA_SNAPS="astral-uv/latest/edge,jhack"
export CONCIERGE_EXTRA_DEBS="build-essential"

concierge prepare -p dev
```

**Variable naming:** Flag `--juju-channel` becomes `CONCIERGE_JUJU_CHANNEL`

## Common Workflows

### Setting Up a New Development Machine

```bash
# 1. Install concierge
sudo snap install --classic concierge

# 2. Prepare full dev environment
concierge prepare -p dev --extra-snaps=jhack

# 3. Verify installation
concierge status
juju controllers
lxc list

# 4. Start developing
cd my-charm-project
charmcraft pack
juju deploy ./my-charm.charm
```

### Quick K8s Testing Environment

```bash
concierge prepare -p k8s
juju controllers
juju add-model test
juju deploy postgresql-k8s
```

### Minimal Build-Only Setup

```bash
# Just install craft tools (no Juju)
concierge prepare -p crafts
cd my-charm && charmcraft pack
```

### CI/CD Environment Setup

```bash
concierge prepare -p dev \
  --juju-channel=3.6/stable \
  --extra-snaps=astral-uv/latest/edge \
  --extra-debs=python3-tox,make

concierge status
```

```yaml
# GitHub Actions example
- name: Prepare environment
  run: |
    sudo snap install --classic concierge
    concierge prepare -p dev --extra-snaps=astral-uv/latest/edge

- name: Verify setup
  run: concierge status

- name: Run tests
  run: |
    charmcraft pack
    charmcraft test
```

## Best Practices

### Choosing a Preset

1. **Use `dev` for general charm development** — includes everything most developers need
2. **Use `machine` for traditional charms** — no K8s overhead
3. **Use `k8s` or `microk8s` for K8s-only work** — lighter than `dev`
4. **Use `crafts` for build servers** — minimal installation for building only

### Configuration Management

1. **Check config into version control** — share team configurations via `concierge.yaml`
2. **Use environment variables in CI** — easier than managing config files
3. **Document custom setups** — add comments to `concierge.yaml`
4. **Test configurations locally first** — before deploying to CI

### Safety

1. **Never run `restore` on production machines** — it removes configurations blindly
2. **Use virtual machines for testing** — try configurations safely
3. **Check status before and after** — `concierge status` shows what happened
4. **Review preset contents** — know what will be installed before running

### Development Workflow

1. **Prepare once per machine** — don't re-run `prepare` unnecessarily
2. **Update tools via snap** — use `snap refresh` for updates, not `restore`+`prepare`
3. **Use jhack for iteration** — once environment is ready, jhack speeds up development
4. **Keep environments consistent** — use same preset across team

## Configuration Priority

Concierge uses this priority order (highest to lowest):

1. **Command-line flags** — `--juju-channel=4.0/edge`
2. **Environment variables** — `CONCIERGE_JUJU_CHANNEL=4.0/edge`
3. **Configuration file** — `concierge.yaml`
4. **Preset defaults** — built-in preset values
5. **Fallback** — if no config found, defaults to `dev` preset

## Troubleshooting

### Prepare Fails

```bash
# Run with verbose logging
concierge prepare -p dev -v

# Run with trace logging for detailed output
concierge prepare -p dev --trace

# Check status
concierge status
```

**Common issues:**
- Insufficient permissions — run with sudo
- Network connectivity — check internet access
- Conflicting installations — remove existing snaps first
- Disk space — ensure adequate free space (10GB+ recommended)

### Controller Bootstrap Fails

```bash
# Check Juju logs
juju debug-log -m controller

# Manually bootstrap if needed
juju bootstrap lxd
juju bootstrap microk8s

# Check provider status
lxc list            # For LXD
microk8s status     # For MicroK8s
```

### Snap Installation Failures

```bash
# Check snap connectivity
snap version
snap list

# Manually install problematic snaps
sudo snap install juju --channel=3.6/stable --classic

# Then retry prepare
concierge prepare -p dev
```

## Command Reference

```bash
# Prepare environment
concierge prepare [flags]
concierge prepare -p <preset>
concierge prepare -c <config-file>

# Check status
concierge status

# Restore/cleanup
concierge restore

# Shell completion
concierge completion bash
concierge completion zsh
concierge completion fish

# Help
concierge --help
concierge prepare --help
concierge --version

# Logging
concierge prepare -p dev -v        # Verbose
concierge prepare -p dev --trace   # Trace (very detailed)
```

## Resources

- **Concierge GitHub**: https://github.com/canonical/concierge
- **Juju docs**: https://documentation.ubuntu.com/juju/latest/
- **Charmcraft docs**: https://documentation.ubuntu.com/charmcraft/
- **LXD docs**: https://documentation.ubuntu.com/lxd/
- **MicroK8s docs**: https://microk8s.io/docs
