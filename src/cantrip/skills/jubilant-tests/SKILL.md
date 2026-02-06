---
name: jubilant-tests
description: Writing integration tests for charms with Jubilant
---

# Writing Integration Tests with Jubilant

Use **Jubilant** for all charm integration tests. **Never use pytest-operator or python-libjuju** — they are legacy approaches.

Jubilant provides a clean Python API for controlling Juju during tests. It drives a real Juju controller, so tests exercise the full charm lifecycle.

## Key Concepts

- **`jubilant.Juju()`** — the main entry point; wraps the Juju CLI
- **`juju.deploy()`** — deploy a charm (local path or Charmhub name)
- **`juju.wait()`** — block until applications reach a target status
- **`juju.status()`** — get full model status as typed Python objects
- **`juju.run()`** — execute a command on a unit
- **`juju.run_action()`** — run a Juju action and wait for results

## Step 1: Set Up Test Dependencies

Add Jubilant to the charm's integration test dependencies:

```toml
[project.optional-dependencies]
integration = ["jubilant"]
```

## Step 2: Create a Conftest Fixture

```python
# tests/integration/conftest.py
import pathlib

import jubilant
import pytest


@pytest.fixture(scope="module")
def juju():
    j = jubilant.Juju()
    j.add_model("test-model")
    yield j
    j.destroy_model("test-model", force=True)


@pytest.fixture(scope="module")
def charm_path():
    return pathlib.Path(__file__).parent.parent.parent
```

## Step 3: Write a Basic Deploy Test

```python
# tests/integration/test_charm.py

def test_deploy(juju, charm_path):
    juju.deploy(charm_path)
    juju.wait(apps=["my-charm"], status="active", timeout=300)
    status = juju.status()
    app = status.apps["my-charm"]
    assert app.status.current == "active"
```

## Step 4: Test with Related Applications

```python
def test_database_integration(juju, charm_path):
    juju.deploy(charm_path)
    juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
    juju.integrate("my-charm:database", "postgresql-k8s:database")
    juju.wait(
        apps=["my-charm", "postgresql-k8s"],
        status="active",
        timeout=600,
    )

    status = juju.status()
    assert status.apps["my-charm"].status.current == "active"
```

## Step 5: Test Actions

```python
def test_backup_action(juju):
    result = juju.run_action("my-charm/0", "backup", path="/data")
    assert result.status == "completed"
    assert "backup-id" in result.results
```

## Step 6: Test Configuration

```python
def test_config_change(juju):
    juju.config("my-charm", {"log-level": "debug"})
    juju.wait(apps=["my-charm"], status="active", timeout=120)

    status = juju.status()
    assert status.apps["my-charm"].status.current == "active"
```

## Step 7: Run Commands on Units

```python
def test_workload_running(juju):
    result = juju.run("my-charm/0", "pebble services")
    assert "active" in result.stdout
```

## Patterns and Best Practices

1. **Use `scope="module"` fixtures** for the Juju connection and model to avoid creating a new model per test. Tests within a module share state.

2. **Always call `juju.wait()`** after deploy, integrate, or config changes. Juju operations are asynchronous; wait ensures the model has settled.

3. **Set generous timeouts.** Integration tests involve real infrastructure. Use at least 300 seconds for initial deploys, 600 seconds when relating multiple applications.

4. **Clean up models** in fixture teardown with `destroy_model(force=True)`.

5. **Test the charm from its packed `.charm` file** when possible, to validate the full build. Use `charm_path` pointing to the project root so Jubilant can find it.

6. **Test COS integration** if the charm supports observability:
   ```python
   def test_cos_integration(juju):
       juju.deploy("grafana-agent-k8s", channel="latest/stable")
       juju.integrate("my-charm:grafana-dashboard", "grafana-agent-k8s")
       juju.wait(apps=["my-charm", "grafana-agent-k8s"], status="active")
   ```

## Common Pitfalls

- **Do not use `python-libjuju` directly.** Jubilant wraps the Juju CLI and provides a cleaner API.
- **Do not hardcode unit names** beyond `<app>/0`. Use `juju.status()` to discover unit names dynamically when the application might scale.
- **Remember `trust=True`** when deploying charms that need cluster-wide permissions (e.g., storage providers, ingress controllers).
