---
title: "How to surface Ubuntu Pro and Landscape recommendations — Cantrip"
description: "Understand the Estate Operations section in the operational-readiness report — when Ubuntu Pro and Landscape recommendations appear, what they mean, and how the agent phrases them."
h1: "Surface Ubuntu Pro and Landscape recommendations"
subtitle: "The operational-readiness tool surfaces day-2 estate recommendations alongside the code-level findings, scoped to operators running the charm on a supported Ubuntu production estate."
section: howto
breadcrumb_label: "Estate operations"
on_this_page:
  - { anchor: "what", label: "What you get" }
  - { anchor: "when", label: "When recommendations appear" }
  - { anchor: "shape", label: "Shape of the report" }
  - { anchor: "wording", label: "Required vs recommended" }
  - { anchor: "skill", label: "The bundled skill" }
see_also:
  - label: "Improve an existing charm"
    href: "howto-improve.html"
  - label: "Add a custom skill"
    href: "howto-skills.html"
  - label: "Agent tools"
    href: "reference-tools.html"
---

{#what}
## What you get

When the agent runs the `operational_readiness` tool on a charm,
the resulting `OPERATIONAL_READINESS.md` report carries a dedicated
**Estate Operations** section listing day-2 recommendations for two
Canonical products:

- **Ubuntu Pro** — extended security maintenance (ESM-Apps /
  ESM-Infra), Livepatch (kernel CVEs without reboot), FIPS-validated
  crypto modules, and USG / CIS / DISA-STIG hardening.
- **Landscape** — fleet patching, per-machine compliance reports,
  and centralised access management across an Ubuntu estate.

Each recommendation carries the **evidence** that triggered it — a
machine substrate, a peer relation, a TLS or identity-platform
relation, declared storage — so the operator can audit the
recommendation rather than treat it as a black box.

{#when}
## When recommendations appear

The detector is deliberately conservative. The Estate Operations
section disappears entirely from the report when no opportunities
apply. Specifically:

- A pure-Kubernetes charm with no Pro / Landscape mentions in its
  README, `docs/`, or charmcraft metadata returns an empty list. The
  recommendation belongs on the cluster's Ubuntu *host* nodes, not
  the workload container.
- A K8s charm that **already references** Pro or Landscape (in the
  README, `docs/`, or metadata `summary` / `description`) emits a
  single host-coverage entry asking the operator to confirm the
  existing wording targets the right layer.
- A machine-substrate charm emits ESM, Livepatch, and fleet-patching
  baselines, with severity escalating from `consider` to
  `recommended` when the charm declares storage or peer relations.
- TLS or identity-platform relations add `fips-compliance` and
  `usg-hardening` `consider` entries, since those facets matter
  primarily for regulated workloads.

{#shape}
## Shape of the report

The Estate Operations section sits below the pillar breakdown and
the Advisory block. Each opportunity carries three things:

- **Level** — `recommended` for strong evidence, `consider` for a
  weaker but still relevant fit, `already-mentioned` when the repo
  already references the product (in which case the agent
  reinforces the existing wording rather than duplicating it).
- **Rationale** — a one-sentence explanation written for the
  operator.
- **Evidence** — the observed signals that triggered the
  recommendation, so it can be audited.

Structured consumers (the improvement-mode summary, future audit
templates) read the same data via
`OperationalReadinessTool` output:
`result.data["findings"]["estate_opportunities"]` is a list of
dictionaries with `product`, `facet`, `level`, `rationale`, and
`evidence` fields.

{#wording}
## Required vs recommended

The single load-bearing rule: estate recommendations are
**recommended for a supported production estate**, never **required
for the charm to work**. The charm itself must pack and run on a
stock Ubuntu image with no subscription.

The report's preamble states the rule explicitly, and the bundled
`estate-operations` skill governs how the agent phrases the
recommendation in the user-facing summary, runbook edits, and
README sections. The skill explicitly rejects sales-script
phrasing — every recommendation is grounded in observed evidence,
and the recommendation disappears when the evidence does not
support it.

{#skill}
## The bundled skill

A bundled `estate-operations` skill ships with Cantrip and is
loaded on demand. When the agent sees a non-empty
`estate_opportunities` list in the readiness output (or when the
user explicitly asks about Ubuntu Pro, Landscape, ESM, Livepatch,
FIPS, or USG), it loads the skill and uses the skill's wording
patterns:

- **Production-deployment runbook section** — an optional section
  in the charm's README that lists relevant estate recommendations
  with a closing sentence reaffirming the charm does not depend on
  either service.
- **Audit-summary paragraph** — a separate paragraph after the
  must-fix / should-fix list, visually distinct from the code-level
  findings.
- **Already-mentioned reinforcement** — when the repo already
  references a product, the agent tightens the existing wording
  rather than adding a duplicate paragraph.

See `src/cantrip/skills/estate-operations/SKILL.md` in the
repository for the full skill body, the facet table, and the
worded examples.
