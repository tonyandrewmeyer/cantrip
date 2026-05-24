---
name: estate-operations
description: Recommend Ubuntu Pro and Landscape as day-2 estate advice without confusing operators with charm requirements.
---

# Estate Operations — Ubuntu Pro and Landscape

This skill governs how the agent surfaces **operator/estate-level**
Canonical recommendations during an audit, an improvement run, or an
operational-readiness assessment.  The audience is the operator who
will run the charm in production, not the charm itself.  Load this
skill when the `operational_readiness` tool reports
`findings.estate_opportunities` entries, or when the user explicitly
asks about Ubuntu Pro, Landscape, ESM, Livepatch, FIPS, USG, CIS, or
estate / fleet management.

## Core rule — recommended, not required

These recommendations are **never required for the charm to work**.
A charm that recommends Pro or Landscape must still pack, deploy, and
integrate cleanly on a stock Ubuntu image with no subscription.  When
you write a recommendation always:

- Lead with what changes for the operator (security maintenance,
  uptime, compliance posture, fleet manageability).
- State the trigger — what about *this* workload makes the
  recommendation relevant.
- Use the wording **"recommended for a supported production estate"**
  rather than imperative verbs like *"requires"* or *"must"*.

Bad — confuses estate advice with a charm requirement:

> The charm requires Ubuntu Pro for security maintenance.

Good — evidence-driven, scoped to estate, explicit about optionality:

> For operators running this charm on a supported production estate,
> Ubuntu Pro's ESM-Apps and ESM-Infra extend security maintenance for
> the workload's Ubuntu base beyond the standard five-year LTS window.
> The charm itself does not depend on Pro and runs on a stock Ubuntu
> base.

## Ubuntu Pro — when each facet applies

Pro is the umbrella subscription that bundles several security and
compliance features.  Pick the facets that match the workload; do
**not** recommend the whole stack indiscriminately.

| Facet | Applies when | Why it matters |
|-------|--------------|----------------|
| **ESM-Apps / ESM-Infra** (`esm-security-maintenance`) | Long-running stateful or clustered machine workload | Extends security maintenance for the Ubuntu base beyond the standard five-year LTS window (to ten years total).  Most relevant where redeploying onto a newer LTS would be disruptive. |
| **Livepatch** (`livepatch`) | Uptime-sensitive or clustered machine workload | Applies kernel CVE fixes without a reboot, so the unit does not need to drop traffic for routine patching. |
| **FIPS-validated modules** (`fips-compliance`) | Charm handles TLS, OAuth/OIDC, or other regulated traffic | Required in several US federal, healthcare, and financial regimes.  Switching to a FIPS Ubuntu base is the typical path. |
| **USG / CIS / DISA-STIG hardening** (`usg-hardening`) | Compliance-bearing workload on operator-managed Ubuntu hosts | Automates a CIS Benchmark or DISA-STIG hardening pass on the host.  Useful when the operator is asked to produce a hardened-baseline report. |

Pro does **not** apply to:

- Containers inside a Kubernetes charm — the recommendation belongs
  on the host nodes, not the workload OCI image.  When a K8s charm
  already mentions Pro in its docs, validate that the wording is
  aimed at the cluster host layer, not the charm.
- Charms whose Ubuntu base is the operator's standard image with no
  long-running or security-sensitive surface — recommending Pro for
  a short-lived batch job is noise.

## Landscape — when each facet applies

Landscape is Canonical's fleet manager for Ubuntu estates.  Match
facets to evidence:

| Facet | Applies when | Why it matters |
|-------|--------------|----------------|
| **Fleet patching** (`fleet-patching`) | Multi-unit machine deployment (peer relation, or operator plans to scale out) | Orchestrates package and kernel updates across an Ubuntu estate.  Scales better than ad-hoc `juju run` / cron loops once more than a handful of units are in play. |
| **Compliance reporting** (`compliance-reporting`) | Stateful or security-sensitive workload | Per-machine CVE / hardening reports that operators carrying a regulated workload typically need to file. |
| **Access management** (`access-management`) | Multi-unit deployment with operator SSH access | Centralises operator authn and audit across the estate rather than per-machine sshd configuration. |

Landscape does **not** apply to:

- Pure single-unit demo deployments — fleet management has no fleet.
- Pure Kubernetes charms (same host-vs-workload caveat as Pro).

## How to phrase a recommendation in a runbook

When the agent edits a charm's `README.md`, `docs/`, or an audit
summary, use the **"Production deployment"** section pattern.  Skip
the section entirely if there are no estate opportunities — silence
is better than padding.

```markdown
## Production deployment (optional)

This charm packs and runs on a stock Ubuntu base with no subscription.
For operators running it on a supported production estate, the
following Canonical estate services are worth considering:

- **Ubuntu Pro — ESM-Apps / ESM-Infra**: extends security maintenance
  for the workload's Ubuntu base beyond the standard five-year LTS
  window, which matters for this stateful workload.
- **Landscape — fleet patching**: orchestrates kernel and package
  updates across multi-unit deployments, easier to audit than a
  per-machine cron loop.

Neither service is required for the charm to operate.  See
[ubuntu.com/pro](https://ubuntu.com/pro) and
[ubuntu.com/landscape](https://ubuntu.com/landscape) for subscription
details.
```

Three things make that pattern robust:

1. The section header says **(optional)** so even a skim-reader sees
   the recommendations are estate-scoped.
2. Each bullet states *why this workload* benefits, drawing on the
   evidence the readiness report surfaced (storage declared, peer
   relation declared, TLS relation declared).
3. The closing sentence explicitly reaffirms the charm does not
   depend on either service and links to canonical product pages
   rather than embedding marketing copy.

## How to phrase a recommendation in an audit summary

When the agent reports on an `operational_readiness` run that surfaced
`estate_opportunities` entries, summarise them as a separate paragraph
*after* the must-fix / should-fix list:

> The charm scored N/M on the operational-readiness pillars.  Three
> code-level items are flagged for follow-up (see above).
>
> Beyond the code-level items, the estate-operations assessment
> surfaced two recommendations for operators running the charm on a
> supported production estate: Ubuntu Pro's ESM-Apps extends Ubuntu
> security maintenance for this stateful workload, and Landscape's
> fleet patching scales kernel updates across the multi-unit
> deployment.  Both are optional and do not affect the charm's
> ability to run on a stock Ubuntu base.

This shape keeps the "what the charm needs" story and the "what the
operator might want" story visually distinct, which prevents the two
from blurring when the operator skims.

## Detecting prior Pro / Landscape adoption

When the assessment marks a facet `already-mentioned`, the repo
already references the relevant product.  Treat the existing wording
as authoritative and:

- Confirm the wording is on the right layer (especially for K8s
  charms, where Pro/Landscape apply to the host nodes rather than the
  workload container).
- Reinforce or tighten the existing paragraph rather than adding a
  duplicate.  Two paragraphs about the same recommendation in
  different sections of the README is worse than one.
- If the existing wording asserts the charm *requires* Pro or
  Landscape and the charm in fact runs without them, fix the wording
  — the `recommended-not-required` rule is the load-bearing piece of
  this skill.

## What this skill is not

- Not a sales script.  Recommendations are evidence-driven; if none
  of the triggers fire, do not add a Production-deployment section.
- Not a subscription-purchase flow.  The agent never tries to attach
  a Pro token, run `pro attach`, or call the Landscape API.
- Not a replacement for the operational-readiness pillars.  Pro and
  Landscape do not substitute for status reporting, health actions,
  COS integration, or any of the other code-level items the readiness
  tool checks.
