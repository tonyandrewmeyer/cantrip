---
name: charm-readme-coherence
description: Does the README narrative match what the code actually does?
severity: warning
globs:
  - README.md
  - src/charm.py
  - metadata.yaml
  - charmcraft.yaml
---

You are evaluating whether the charm's `README.md` accurately describes
what the code in `src/charm.py` and the metadata in `metadata.yaml` /
`charmcraft.yaml` actually do.

Pass when:

- The README mentions the workload(s) the charm operates and the
  capabilities it exposes (actions, integrations, configuration).
- Every relation/integration declared in metadata is at least
  mentioned in the README — even if briefly.
- The "what does this charm do" paragraph is not boilerplate
  ("This charm deploys X using Juju") — it tells a user *why*
  they would deploy this charm.
- Code-mentioned features (e.g. observability, backup actions,
  TLS) appear in the README; README-mentioned features all have
  corresponding code.

Fail when there is a meaningful gap in either direction —
README promises a feature the code doesn't implement, or the code
ships a feature the README doesn't mention.  Quote the smallest
README excerpt and the smallest code excerpt that demonstrate the
gap as the `evidence` field.
