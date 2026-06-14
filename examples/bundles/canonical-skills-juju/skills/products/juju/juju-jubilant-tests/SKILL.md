---
name: juju-jubilant-tests
description: 'Writing integration tests for charms with Jubilant + pytest-jubilant.
  WHEN: write integration tests for a Juju charm, use Jubilant + pytest-jubilant,
  deploy charms in a test, relate to postgresql or COS, run actions in tests, write
  cross-model COS Lite smoke tests.'
license: Apache-2.0
metadata:
  author: Canonical/cantrip
  version: 1.0.0
  summary: Writing integration tests for Juju charms with Jubilant + pytest-jubilant;
    cross-model COS Lite smoke patterns.
  tags:
  - juju
  - testing
  - jubilant
  - integration-tests
---

<!--
Generated from Cantrip's source skill at
`src/cantrip/skills/jubilant-tests/SKILL.md`
(https://github.com/canonical/cantrip). Do NOT hand-edit —
re-run `make juju-skills-bundle` instead.

Procedure steps may reference cantrip-specific helper tools (for
example `charm_validate`, `quick_pack`, `harness_inventory`).
Substitute the equivalent `charmcraft` / `juju` / standard CLI
invocation when running without cantrip.
-->

# Writing Integration Tests with Jubilant

Use **Jubilant** plus **pytest-jubilant** for all charm integration tests.
**Never use pytest-operator or python-libjuju** — they are legacy approaches.

Jubilant provides a clean Python API for controlling Juju during tests; it
drives a real Juju controller, so tests exercise the full charm lifecycle.
`pytest-jubilant` adds the pytest plumbing — a managed `juju` fixture,
debug-log capture on failure, and CLI options like `--juju-dump-logs`.

## Key Concepts

- **`jubilant.Juju()`** — the main entry point; wraps the Juju CLI
- **`juju.deploy()`** — deploy a charm (local path or Charmhub name)
- **`juju.wait()`** — block until applications reach a target status
- **`juju.status()`** — get full model status as typed Python objects
- **`juju.run()`** — execute a command on a unit
- **`juju.run_action()`** — run a Juju action and wait for results
- **`pytest_jubilant.JujuFactory`** — request a *second* `Juju` (e.g. for
  COS in a separate model)

## Step 1: Set Up Test Dependencies

Pin to current stable majors in the integration dependency group:

```toml
[dependency-groups]
integration = [
    "jubilant>=1.8,<2",
    "pytest-jubilant>=2,<3",
]
```

`pytest-jubilant` registers itself as a pytest plugin automatically.

## Step 2: Conftest — Just the `charm` Fixture

`pytest-jubilant` provides a module-scoped `juju` fixture out of the
box: it creates a temporary Juju model per test file, tears it down
afterwards, and dumps debug logs on failure. **Do not write your own
`juju` fixture** — let the plugin do it.

You only need a `charm` fixture so tests can deploy the packed `.charm`:

```python
# tests/integration/conftest.py
import os
import pathlib

import pytest


@pytest.fixture(scope="session")
def charm():
    """Return the path of the charm under test."""
    charm = os.environ.get("CHARM_PATH")
    if not charm:
        charm_dir = pathlib.Path()  # Assume the cwd is the charm root.
        charms = list(charm_dir.glob("*.charm"))
        assert charms, f"No charms were found in {charm_dir.absolute()}"
        assert len(charms) == 1, f"Found more than one charm: {charms}"
        charm = charms[0]
    path = pathlib.Path(charm).resolve()
    assert path.is_file(), f"{path} is not a file"
    return path
```

The `.resolve()` call matters — Jubilant rejects relative paths.

## Step 3: Write a Basic Deploy Test

```python
# tests/integration/test_charm.py
import jubilant


APP_NAME = "my-charm"


def test_deploy(juju: jubilant.Juju, charm):
    juju.deploy(charm)  # path object, not f"./{charm}"
    juju.wait(jubilant.all_active, timeout=300)
    status = juju.status()
    assert status.apps[APP_NAME].is_active
```

Pass the `charm` path object directly to `deploy` — never wrap it in a
formatted string.

## Step 4: Test with Related Applications

```python
def test_database_integration(juju: jubilant.Juju, charm):
    juju.deploy(charm)
    juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
    juju.integrate(APP_NAME, "postgresql-k8s")
    juju.wait(jubilant.all_active, timeout=10 * 60)
```

## Step 5: Test Actions

```python
def test_backup_action(juju: jubilant.Juju):
    task = juju.run(f"{APP_NAME}/0", "backup", {"path": "/data"})
    assert task.status == "completed"
    assert "backup-id" in task.results
```

## Step 6: Test Configuration

```python
def test_config_change(juju: jubilant.Juju):
    juju.config(APP_NAME, {"log-level": "debug"})
    juju.wait(jubilant.all_active, timeout=120)
```

## Step 7: Cross-model — COS Lite Integration

When verifying observability, deploy COS Lite in a *second* model via
`pytest_jubilant.JujuFactory`, then offer the relation across the model
boundary:

```python
import json

import jubilant
import pytest
import pytest_jubilant
import requests


@pytest.fixture(scope="module")
def cos(juju_factory: pytest_jubilant.JujuFactory):
    yield juju_factory.get_juju(suffix="cos")


def test_deploy_cos(cos: jubilant.Juju):
    cos.deploy("cos-lite", trust=True)
    cos.wait(jubilant.all_active, timeout=10 * 60)


def test_integrate_loki(juju: jubilant.Juju, cos: jubilant.Juju):
    cos.offer("loki", endpoint="logging")
    juju.integrate(APP_NAME, f"{cos.model}.loki")
    juju.wait(jubilant.all_active)
    cos.wait(jubilant.all_active)


def test_loki_data(cos: jubilant.Juju):
    """Verify the workload's logs are landing in Loki."""
    task = cos.run("traefik/0", "show-proxied-endpoints")
    results = json.loads(task.results["proxied-endpoints"])
    loki_url = results["loki/0"]["url"]
    api = f"{loki_url}/loki/api/v1/label/juju_application/values"
    response = requests.get(api, timeout=30)
    response.raise_for_status()
    assert APP_NAME in response.json()["data"]
```

The pattern — Traefik action → JSON parse → Loki/Prometheus/Tempo HTTP
API check — works for any post-deploy COS smoke test.

## Step 8: Capture Logs in CI

`pytest-jubilant` already dumps `juju debug-log` on test failure. For
extra detail in CI, run with `--juju-dump-logs <dir>`:

```bash
tox -e integration -- --juju-dump-logs logs
```

Then upload the directory as a CI artefact. See the `set-up-ci` how-to
in the upstream ops docs for the recommended GitHub Actions wiring.

## Patterns and Best Practices

1. **Use `jubilant.all_active`** (and `all_blocked`, `any_error`, etc.)
   instead of hand-rolling status predicates.

2. **Set generous timeouts.** Integration tests involve real infrastructure.
   Use at least 300 seconds for initial deploys, 600+ seconds when
   relating multiple applications, and 10×60 for COS Lite (the bundle
   takes time to settle).

3. **Test the charm from its packed `.charm` file** so you exercise the
   full build, not just the source tree.

4. **Remember `trust=True`** when deploying charms that need cluster-wide
   permissions (storage providers, ingress controllers, K8s cluster
   bundles like cos-lite).

5. **Don't hardcode unit names** beyond `<app>/0`. Use `juju.status()` to
   discover unit names dynamically when the application might scale.

## Common Pitfalls

- **Do not roll your own `juju` fixture** — `pytest-jubilant` provides
  one already with model creation, teardown, and failure-time log dumping.
- **Do not pass `f"./{charm}"`** to `juju.deploy` — pass the resolved
  `pathlib.Path` directly.
- **Do not use `python-libjuju`** directly. Jubilant wraps the Juju CLI
  and provides a cleaner API.
