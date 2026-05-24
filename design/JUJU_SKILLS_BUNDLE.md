# Juju Skills Bundle for `canonical/skills`

Phase 56 (see [`ROADMAP.md`](../ROADMAP.md)) ships a Juju-focused subset of
Cantrip's own skill content to the public [`canonical/skills`][cs-repo] catalogue
so charm authors using *any* agentskills.io-compatible client (Claude Code,
GitHub Copilot CLI, Cursor, Codex, Gemini CLI, Windsurf, …) get the same
charm-development guidance Cantrip's autonomous agent already uses internally.

This document:

1. Captures **what** ships in the bundle and **why**.
2. Pins the **frontmatter contract** the canonical/skills validator enforces.
3. Describes the **build pipeline** (cantrip is the source of truth; the
   published assets are derived).
4. Records what we **deferred** and the trigger for revisiting each item.

The active deferrals are also tracked in [`design/DEFERRED.md`](DEFERRED.md);
this doc owns the *initial* scope decision.

[cs-repo]: https://github.com/canonical/skills

---

## 1. Scope decision — initial bundle (v1)

Cantrip currently ships **33** skills under `src/cantrip/skills/`. The
roadmap's Phase 56.1 enumerates the slices most worth lifting upstream:
charmcraft.yaml authoring, `src/charm.py` patterns, Scenario testing (not
Harness), Jubilant integration tests (not pytest-operator), ops-tracing
integration, COS integration, relation-data design, and the 12-factor / custom
/ infrastructure path split.

Below is the per-skill verdict for the initial bundle. The `Ship?` column maps
the source skill to its destination under
`bundles/canonical-skills-juju/skills/products/juju/<name>/SKILL.md`.

| Cantrip skill | Ship? | Reason |
|---|---|---|
| `scenario-tests` | **v1** | Roadmap-listed slice (Scenario, not Harness). |
| `jubilant-tests` | **v1** | Roadmap-listed slice (Jubilant, not pytest-operator). |
| `observability` | **v1** | Roadmap-listed slices (ops-tracing + COS) — extensive, self-contained. |
| `charmcraft` | **v1** | Roadmap-listed slice (`charmcraft.yaml` authoring). |
| `relation-data-design` | **v1** | Roadmap-listed slice (relation-data design). |
| `custom-charm` | **v1** | Roadmap-listed slice (Path B / `src/charm.py` patterns). |
| `infrastructure-charm` | **v1** | Roadmap-listed slice (Path C). |
| `harness-migration` | **v1** | High-leverage migration path; cantrip's version is itself adapted from `canonical/copilot-collections`. |
| `adding-actions` | **v1** | Starter operational skill, very self-contained. |
| `adding-config` | **v1** | Starter operational skill, very self-contained. |
| `twelve-factor` | **skip (dedup)** | Upstream already has `12factor-charm`, `12factor-fit`, `12factor-rock`. Re-shipping cantrip's integrated version would conflict. |
| `charm-library` | **deferred — v2** | Strong candidate, lots of content; defer to keep v1 reviewable. |
| `ingress` | **deferred — v2** | Strong candidate (Traefik wiring); defer to keep v1 reviewable. |
| `operational-readiness` | **deferred — v2** | Strong candidate (status / pause / backup / certs); defer to keep v1 reviewable. |
| `publishing` | **deferred — v2** | Strong candidate (Charmhub upload + channel strategy); defer to keep v1 reviewable. |
| `terraform` | **deferred — v2** | Strong candidate (Terraform module shape); defer to keep v1 reviewable. |
| `identity-platform` | **deferred — v2** | Strong candidate; defer until we've validated the v1 review loop. |
| `preset-bundles` | **deferred — v2** | Strong candidate (COS Lite / 12-Factor / Identity-Platform shapes). |
| `jhack` | **deferred — v2** | Useful debug aid; some content overlaps with built-in juju tooling. |
| `charm-debug` | **deferred — v2** | Heavily wired to cantrip's `juju` bundled-tool subcommands; needs translation. |
| `charm-migration` | **deferred — v2** | Overlaps with `harness-migration` in v1; revisit. |
| `concierge` | **deferred — v2** | Useful environment provisioning skill, but cantrip-flavoured today. |
| `fix-broken-juju-k8s` | **deferred — v2** | Useful recovery aid; heavily uses cantrip-internal tools. |
| `performance` | **deferred — v2** | Worth shipping once we've checked it stands alone. |
| `security-review` | **deferred — v2** | Worth shipping once we've checked it stands alone. |
| `find-bugs` | **skip** | Cantrip workflow concept (runs *before* a BUILD task completes); no standalone audience. |
| `iterate-fix` | **skip** | Cantrip workflow concept (deploy → test → debug retry loop wired to cantrip's executor). |
| `charm-improvement` | **skip** | Cantrip workflow concept (audit + confirm + fix categories). |
| `benchmark` | **skip** | Wraps the cantrip-specific `hook_benchmark` tool. |
| `bundle` | **skip** | Existing-bundle consumption only — Juju bundles are deprecated for authoring. |
| `skill-scanner` | **skip** | Cantrip-internal skill QA. |
| `skill-writer` | **skip** | Cantrip-specific skill-format authoring. |
| `workspace` | **skip** | Cantrip-specific `cantrip.workspace.yaml` manifest. |

**v1 ships 10 skills.** That covers every slice the roadmap explicitly named
and clears Phase 56's "at least six instruction / skill assets" exit
criterion comfortably while keeping the first review loop small.

### Why not 12-factor (`twelve-factor`)

Cantrip's `twelve-factor` skill is an integrated walk-through of fit → rock →
charm → build → push → deploy → verify. Upstream `canonical/skills` already
ships three smaller skills covering the same ground: `12factor-fit`,
`12factor-rock`, `12factor-charm`. Phase 56 explicitly forbids duplication
("Not a fork or rewrite") and the upstream split is the published shape, so
the bundle re-uses those rather than introducing a conflicting fourth
integrated skill.

### System-prompt extractions (deferred)

Phase 56 also mentions extracting *prompt sections* from
`src/cantrip/agent/prompts/system.md.j2` (e.g. "OCI Image Strategy", "Security
Event Logging / SEC0045", "Three Paths"). The 10 v1 skills already cover the
content in those sections — security-event-logging lives inside
`observability`, OCI image guidance lives across `custom-charm` /
`infrastructure-charm`, the three-paths split is implicit in the path skills.

Standalone system-prompt extractions stay deferred to v2 until we have a
concrete consumer request that the skill version doesn't already satisfy.

---

## 2. Frontmatter contract

The upstream validator at
`tmp/canonical-skills/scripts/validate_skills.py` enforces:

- **Top-level required:** `name` (kebab-case, unique), `description`
  (≥ 20 words, contains a `WHEN:`/`activat`/`trigger` marker),
  `license` (`Apache-2.0`).
- **`metadata:` required:** `author` (starts with `Canonical`),
  `version` (semver `X.Y.Z`).
- **`metadata:` recommended:** `tags` (list), `summary` (≤ 160 chars).
- **Directory:** each skill in its own folder under one of
  `meta/`, `products/`, `engineering/`, `documentation/`, `operations/`,
  `security/`, `practices/`. Charm work lives under
  `skills/products/juju/<skill-name>/SKILL.md`.

Cantrip's own frontmatter is a small subset (`name`, `description`,
optional `globs`). The build script (Section 3) rewrites every shipped
skill to match the canonical/skills shape, including:

- `description:` — promoted to a multi-line block that starts with cantrip's
  one-liner and appends a `WHEN: <trigger phrases>` line so the validator's
  trigger-phrase rule passes.
- `license:` — fixed at `Apache-2.0`.
- `metadata.author` — `Canonical/cantrip` (mirrors the published 12-factor
  skills' `Canonical/<team>` convention).
- `metadata.version` — `1.0.0` for the initial cut.
- `metadata.tags` — derived per-skill from the manifest below.
- `metadata.summary` — derived from the original cantrip description,
  trimmed to ≤ 160 chars.

`globs:` is dropped — it's a Continue/Aider-style convention and the
canonical/skills format doesn't use it.

---

## 3. Build pipeline

**Source of truth:** `src/cantrip/skills/<name>/SKILL.md` (cantrip-flavoured).
**Generated output:** `bundles/canonical-skills-juju/` (regenerated; do not
hand-edit).

The build is implemented in `scripts/build_juju_skills_bundle.py`:

```
make juju-skills-bundle         # regenerate bundle
make juju-skills-bundle-check   # exit 1 if regenerated content differs from committed copy
```

Per-skill transformation:

1. **Parse the source** (YAML frontmatter + Markdown body).
2. **Rewrite the frontmatter** to the canonical/skills shape (Section 2),
   using the in-script manifest for per-skill `tags`, `summary`, and the
   `WHEN:` trigger phrases.
3. **Apply tool-reference substitutions** for the common cantrip-internal
   tool names where a stable CLI equivalent exists:
   `charmcraft_pack` → `charmcraft pack`, `juju_deploy` → `juju deploy`,
   `juju_refresh` → `juju refresh`, `juju_relate` → `juju integrate`, etc.
   The full table lives in the script's `_TOOL_SUBSTITUTIONS` constant —
   keep it in lockstep with the prompt's "Tool Bundles" mapping.
4. **Prepend a banner** noting the file is generated from cantrip and
   pointing back at the source path.
5. **Write** to
   `bundles/canonical-skills-juju/skills/products/juju/<name>/SKILL.md`.

The drift-guard test at `tests/unit/test_juju_skills_bundle.py` runs the
script in `--check` mode, so a source edit that doesn't include the
regenerated bundle (or vice versa) fails CI.

### Why the bundle lives inside cantrip

- Keeps the source of truth and the regenerated artefact in one PR — reviewers
  see both halves.
- The drift-guard test prevents the bundle going stale.
- Publishing to `canonical/skills` itself is a separate, user-driven step
  (see [Section 5](#5-publishing-to-canonicalskills)) — that repo's CI
  validates the bundle on its own; nothing here pushes upstream
  automatically.

---

## 4. Per-skill manifest

The build script carries this manifest. It lives in code (not YAML) so a
manifest typo fails `ty` rather than the canonical/skills validator
post-publication.

| Bundle name | Source skill | Tags | Summary fragment |
|---|---|---|---|
| `juju-charmcraft-yaml` | `charmcraft` | `juju`, `charmcraft`, `charmcraft-yaml`, `packaging` | charmcraft.yaml authoring + library management |
| `juju-charm-py-custom` | `custom-charm` | `juju`, `ops`, `charm-py`, `kubernetes`, `machine` | end-to-end ops-framework charm for custom apps |
| `juju-charm-py-infrastructure` | `infrastructure-charm` | `juju`, `ops`, `charm-py`, `infrastructure`, `database`, `cache` | infrastructure charms with peer relations, leader election, failover |
| `juju-relation-data` | `relation-data-design` | `juju`, `ops`, `relations`, `data-bag`, `secrets` | designing relation databags |
| `juju-observability-cos` | `observability` | `juju`, `cos`, `prometheus`, `loki`, `grafana`, `tempo`, `ops-tracing` | wiring charms into the Canonical Observability Stack |
| `juju-scenario-tests` | `scenario-tests` | `juju`, `ops`, `testing`, `scenario`, `unit-tests` | unit tests with `ops.testing` (Scenario), never Harness |
| `juju-jubilant-tests` | `jubilant-tests` | `juju`, `testing`, `jubilant`, `integration-tests` | integration tests with Jubilant + pytest-jubilant |
| `juju-harness-to-scenario` | `harness-migration` | `juju`, `ops`, `testing`, `scenario`, `harness`, `migration` | migrating deprecated Harness tests to Scenario |
| `juju-charm-actions` | `adding-actions` | `juju`, `ops`, `actions`, `operational` | implementing Juju actions for operational tasks |
| `juju-charm-config` | `adding-config` | `juju`, `ops`, `config`, `config-changed` | adding and validating charm configuration options |

Every entry gets `author: Canonical/cantrip`, `version: 1.0.0`,
`license: Apache-2.0`.

---

## 5. Publishing to `canonical/skills`

Publishing is **manual** in v1. The flow is:

1. `make juju-skills-bundle` regenerates the bundle.
2. `make juju-skills-bundle-check` confirms zero drift.
3. The user copies `bundles/canonical-skills-juju/skills/products/juju/` into
   a local checkout of `canonical/skills` and opens a PR.
4. Upstream `validate_skills.py` runs in their CI and confirms the
   frontmatter is correct.

Phase 56.4's "GitHub Action that opens a PR when cantrip's system prompt or
skill content changes" is **deferred** — it needs a real publication
cadence before automation is worth maintaining.

---

## 6. Deferred items

| Deferred | Trigger to revisit |
|---|---|
| v2 skill set (`charm-library`, `ingress`, `operational-readiness`, `publishing`, `terraform`, `identity-platform`, `preset-bundles`, `jhack`, `charm-debug`, `charm-migration`, `concierge`, `fix-broken-juju-k8s`, `performance`, `security-review`) | v1 lands cleanly in `canonical/skills`; review feedback addressed; pipeline proven. |
| System-prompt section extractions (OCI Image Strategy, Three Paths intro, SEC0045 as its own skill) | A concrete consumer request that the skill-level coverage above doesn't already satisfy. |
| Automated regeneration PR via GitHub Action (Phase 56.4) | Real publication cadence emerges; manual flow proves to be the bottleneck. |
| Upstream signal-back loop (downstream usage tracking, quarterly prune) | Bundle has ≥ 3 months of publication history. |
