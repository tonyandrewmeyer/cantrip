---
name: charm-improvement
description: Auditing and improving existing charms to modern standards
---

# Charm Improvement

Use this skill when improving an existing charm — auditing it against best practices, filling gaps, modernising code, and preparing it for Charmhub listing.

## Workflow

1. **Audit** — run `charm_audit` on the charm directory to get a structured report
2. **Review** — present findings to the user, categorised as must-fix / should-fix / nice-to-have
3. **Fix** — address each category in a separate commit (observability, tests, code, listing)
4. **Validate** — run `charm_validate` and the full test suite to verify everything works

## Observability Gap Fill

### COS Relations Checklist

Every production charm should have these relations in `charmcraft.yaml`:

```yaml
requires:
  tracing:
    interface: tracing
    limit: 1
  logging:
    interface: loki_push_api
provides:
  metrics-endpoint:
    interface: prometheus_scrape
  grafana-dashboard:
    interface: grafana_dashboard
```

### ops-tracing Setup

Add to `requirements.txt`:
```
ops-tracing >= 1.0
```

Add to `src/charm.py`:
```python
import ops_tracing

class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        ops_tracing.setup(self)
```

ops-tracing instruments hooks, Pebble interactions, relations, status changes, and secrets automatically. Only add manual spans for long-running operations, external API calls, and fallback decision logic.

## Test Gap Fill

### Unit Tests (Scenario)

Use `ops.testing` (Scenario), **not** the deprecated Harness.

Key patterns:
```python
import ops
import ops.testing

def test_start_ready():
    ctx = ops.testing.Context(MyCharm)
    container = ops.testing.Container("workload", can_connect=True)
    state = ops.testing.State(containers=[container])
    out = ctx.run(ctx.on.pebble_ready(container), state)
    assert out.unit_status == ops.ActiveStatus()
```

Cover:
- Every observed event (install, config-changed, pebble-ready, relation-changed)
- Missing relations → BlockedStatus
- Invalid config → error handling
- Pebble not ready → WaitingStatus

### Integration Tests (Jubilant)

```python
import jubilant

def test_deploy(juju: jubilant.Juju):
    juju.deploy("./my-charm_amd64.charm", app="my-charm")
    juju.wait(apps=["my-charm"], status="active")

def test_relate_database(juju: jubilant.Juju):
    juju.deploy("postgresql-k8s", app="postgresql")
    juju.relate("my-charm:database", "postgresql:database")
    juju.wait(apps=["my-charm", "postgresql"], status="active")
```

### Harness Migration

If existing tests use `from ops.testing import Harness`, rewrite them using Scenario:
- `Harness(MyCharm)` → `ops.testing.Context(MyCharm)`
- `harness.begin()` → not needed
- `harness.charm.on.install.emit()` → `ctx.run(ctx.on.install(), state)`
- `harness.add_relation()` → `ops.testing.Relation(endpoint="db", interface="pgsql")`

## Deprecated API Migration

| Deprecated | Replacement | Notes |
|-----------|------------|-------|
| `StoredState` | Instance attributes, Juju secrets | StoredState has subtle persistence bugs |
| `Harness` | `ops.testing` (Scenario) | Harness is deprecated since ops 2.x |
| `charmcraft fetch-libs` | PyPI packages | PyPI versions are versioned and tested |
| `framework.breakpoint` | Removed | Use standard Python debugging |

## Listing Readiness

### Required charmcraft.yaml Fields

```yaml
name: my-charm
display-name: My Charm
summary: One-line description of the charm
description: |
  Detailed description of what the charm does,
  how to deploy it, and key features.
docs: https://discourse.charmhub.io/t/my-charm-docs
issues: https://github.com/org/my-charm/issues
source: https://github.com/org/my-charm
tags:
  - databases
```

### README Structure

A good README includes:
1. Title and badges
2. Description (what the charm does)
3. Deployment instructions
4. Configuration reference
5. Integrations (what it relates to)
6. Actions reference
7. Contributing guide

### Other Checks

- **LICENSE** — Apache-2.0 is standard for charms
- **icon.svg** — required for Charmhub listing (Cantrip flags the gap but does not generate artwork)
- **Clean pack** — `charmcraft pack` should succeed with no warnings
