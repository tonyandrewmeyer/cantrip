# Skills: Load-on-demand charm expertise

*2026-04-18T10:07:04Z by Showboat 0.6.1*
<!-- showboat-id: 39d572df-b402-4e47-8dd3-ffc4f703426a -->

Cantrip's agent doesn't try to stuff every charm convention into its system prompt. Instead, it ships a library of **skills** — small, focused markdown files with YAML frontmatter — and loads them on demand when the agent decides the topic is relevant.

Each skill lives in its own directory under `src/cantrip/skills/` as a single `SKILL.md` file. The frontmatter `description` field is indexed (cheap, always in context); the body is only read when the agent calls `LoadSkill`.

## The skill library

```bash
ls src/cantrip/skills/ | grep -v __ | grep -v templates | grep -v terraform.py
```

```output
adding-actions
adding-config
charm-improvement
charmcraft
concierge
custom-charm
find-bugs
harness-migration
infrastructure-charm
ingress
jhack
jubilant-tests
observability
operational-readiness
performance
publishing
relation-data-design
scenario-tests
security-review
terraform
twelve-factor
```

21 skills covering the full lifecycle — writing actions and config, adding observability, migrating from Harness to Scenario, publishing, security review, 12-Factor and infrastructure patterns, and more.

## Anatomy of a skill

A skill is just markdown with YAML frontmatter. Here's the `observability` skill — the one that teaches the agent about COS integration and `ops-tracing`:

```bash
head -30 src/cantrip/skills/observability/SKILL.md
```

````output
---
name: observability
description: Adding COS observability integration and ops-tracing to charms
---

# Observability and COS Integration

Every production charm should integrate with the **Canonical Observability Stack (COS)**. This means traces, metrics, logs, and dashboards — all wired up through standard Juju relations.

## Key Components

| Component | Purpose | Relation Interface |
|-----------|---------|-------------------|
| **ops-tracing** | Distributed tracing from charm code | `tracing` |
| **Prometheus** | Metrics collection | `prometheus-scrape`, `metrics-endpoint` |
| **Loki** | Log aggregation | `loki-push-api`, `logging` |
| **Grafana** | Dashboards | `grafana-dashboard` |
| **Tempo** | Trace storage and querying | `tracing` |
| **Alertmanager** | Alert routing | `alertmanager-dispatch` |

## Step 1: Add ops-tracing

> **Note:** The `charmcraft_init` tool now automatically injects ops-tracing for standard charms (`kubernetes`/`machine` profiles) — it adds the dependency to `requirements.txt`, the tracing relation to `charmcraft.yaml`, and the import/setup call to `src/charm.py`. For PaaS framework profiles, it adds the tracing relation to `charmcraft.yaml` only. If your charm was scaffolded with `charmcraft_init`, you can skip to Step 2.

ops-tracing instruments charm code so every hook execution, relation event, and Pebble interaction produces a trace span.

Install from PyPI:

```toml
[project.dependencies]
````

## Two-tier loading in code

`SkillsIndex` in `src/cantrip/agent/skills.py` is a two-tier loader:

- **Tier 1** — `discover()` scans every `*/SKILL.md`, parses only the frontmatter, and builds a name→description map. Cheap, always in context.
- **Tier 2** — `load_skill(name)` reads the full body on demand when the agent calls the `LoadSkill` tool.

Let's inspect the frontmatter of every skill (this is what the agent sees in its system prompt):

```bash
for f in src/cantrip/skills/*/SKILL.md; do awk '/^---$/{n++; next} n==1 && /^description:/{sub(/^description: */, ""); printf "%-25s %s\n", skill, $0} n==1 && /^name:/{sub(/^name: */, ""); skill=$0}' "$f"; done | sort
```

```output
adding-actions            Implementing Juju actions for operational tasks in charms
adding-config             Adding and validating charm configuration options
charm-improvement         Auditing and improving existing charms to modern standards
charmcraft                Expert guidance for developing, building, testing, and publishing Juju charms using charmcraft
concierge                 Provisioning charm development and testing environments using concierge presets and custom configuration
custom-charm              End-to-end workflow for building ops-framework charms for custom applications (K8s and machine)
find-bugs                 Review newly written charm code for common charm bugs before finishing a BUILD task
harness-migration         Migrating deprecated ops.testing.Harness tests to state-transition (Scenario) tests
infrastructure-charm      Workflow for charming infrastructure software (databases, caches, message brokers, proxies, monitoring)
ingress                   Configuring HTTP ingress with Traefik for Kubernetes charms
jhack                     Using jhack utilities for rapid charm development, debugging, relation inspection, and event replay
jubilant-tests            Writing integration tests for charms with Jubilant
observability             Adding COS observability integration and ops-tracing to charms
operational-readiness     Implementing operational readiness features — status reporting, health checks, pause/resume, backup/restore, diagnostics, upgrade pre-flight, certificate management, and secret rotation
performance               Identifying and fixing common charm performance issues
publishing                Publishing charms to Charmhub (upload, release, channel management)
relation-data-design      Designing and implementing relation data bags for charm integrations
scenario-tests            Writing unit tests for charms with ops.testing (Scenario)
security-review           Charm-specific security review to run before a BUILD task finishes
terraform                 Generating Terraform modules for declarative charm deployment
twelve-factor             End-to-end workflow for building 12-factor PaaS charms with rockcraft and charmcraft
```

## Load-on-demand flow

When the agent encounters a task that mentions (say) observability, its plan includes a `LoadSkill(observability)` tool call. The loader reads `src/cantrip/skills/observability/SKILL.md`, strips the frontmatter, and injects the markdown body into the subagent's context.

Adding a new skill is as simple as:

```bash
mkdir src/cantrip/skills/my-new-skill
cat > src/cantrip/skills/my-new-skill/SKILL.md <<'EOF'
---
name: my-new-skill
description: One-line summary shown to the agent
---

# Body

Markdown content with examples, code, and guidance.
EOF
```

No registration step — `SkillsIndex.discover()` picks it up on the next launch.
