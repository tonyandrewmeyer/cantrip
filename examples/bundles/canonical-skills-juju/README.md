# Canonical Skills — Juju Bundle (generated)

This directory is the regenerated output of
`scripts/build_juju_skills_bundle.py`. Do **not** hand-edit any file under
`skills/`; edit the source skill in `src/cantrip/skills/<name>/SKILL.md` and
re-run `make juju-skills-bundle` to refresh the bundle.

The bundle is intended for publication to
[`canonical/skills`](https://github.com/canonical/skills) under
`skills/products/juju/<skill-name>/SKILL.md`. See
[`design/JUJU_SKILLS_BUNDLE.md`](../../design/research/JUJU_SKILLS_BUNDLE.md) for the
scope decision, frontmatter contract, and deferred items.

## Contents

| Bundle name | Source | Summary |
|---|---|---|
| `juju-charmcraft-yaml` | `src/cantrip/skills/charmcraft/` | Authoring charmcraft.yaml, building and packaging charms, managing charm libraries, and publishing to Charmhub. |
| `juju-charm-py-custom` | `src/cantrip/skills/custom-charm/` | End-to-end workflow for building ops-framework Juju charms for custom applications on Kubernetes (Pebble) or machine (systemd). |
| `juju-charm-py-infrastructure` | `src/cantrip/skills/infrastructure-charm/` | Charm workflow for infrastructure software with peer relations, leader election, primary/replica failover, backup and restore. |
| `juju-relation-data` | `src/cantrip/skills/relation-data-design/` | Designing and implementing Juju relation databags (app + unit + peer), with safe secret sharing over relations. |
| `juju-observability-cos` | `src/cantrip/skills/observability/` | Wire Juju charms into the Canonical Observability Stack (ops-tracing, Prometheus + alerts, Loki, Grafana, Tempo, Alertmanager, Sloth, Catalogue, SEC0045). |
| `juju-scenario-tests` | `src/cantrip/skills/scenario-tests/` | Writing unit tests for Juju charms with ops.testing (Scenario), the modern state-transition replacement for the deprecated Harness. |
| `juju-jubilant-tests` | `src/cantrip/skills/jubilant-tests/` | Writing integration tests for Juju charms with Jubilant + pytest-jubilant; cross-model COS Lite smoke patterns. |
| `juju-harness-to-scenario` | `src/cantrip/skills/harness-migration/` | Migrating deprecated ops.testing.Harness unit tests to state-transition (Scenario) tests, file by file. |
| `juju-charm-actions` | `src/cantrip/skills/adding-actions/` | Implementing Juju actions for operational tasks: declaration, handlers, progress logging, Scenario tests. |
| `juju-charm-config` | `src/cantrip/skills/adding-config/` | Adding and validating Juju charm configuration options; applying config to Pebble layers and machine workloads. |

## Regenerate

```bash
make juju-skills-bundle           # write the bundle from source
make juju-skills-bundle-check     # exit 1 if the regenerated bundle differs from the committed copy
```

The `-check` form is the drift guard `make check` runs via
`tests/unit/test_juju_skills_bundle.py`.

## Publishing

The push to `canonical/skills` is manual in v1. Copy
`examples/bundles/canonical-skills-juju/skills/products/juju/` into a local checkout
of `canonical/skills` and open a PR there. Upstream
`scripts/validate_skills.py` will validate the frontmatter on its CI.
