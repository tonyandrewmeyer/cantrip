---
name: relation-data-hygiene
description: Is the relation databag schema well-formed, documented, and minimal?
severity: warning
globs:
  - src/charm.py
  - src/**/relations/*.py
  - lib/charms/**/v*/*.py
  - metadata.yaml
  - charmcraft.yaml
---

You are evaluating how the charm reads from and writes to its
relation databags.  This is one of the most common sources of
operator confusion when a charm misbehaves.

Pass when **all** of the following hold for every integration the
charm participates in:

- Each key written to a databag has a clear, documented purpose —
  either a comment at the write site, a docstring on the
  surrounding method, or (preferably) an explicit schema
  (Pydantic-style or `dataclass`-backed wrapper).
- The charm never silently ignores missing required keys on a
  databag it consumes — it either waits (with a clear status
  message), raises a relation-data error, or sets blocked status
  with a message that names the missing key.
- Secrets-in-relation-data are wrapped via the Juju Secrets API
  (the `secret` content-type, not raw passwords in databags)
  unless the relation interface predates secrets and the charm
  authors documented why.
- No relation handler writes the same key with two different
  meanings depending on the codepath.

Fail when any of the above is violated.  Quote the smallest
relevant code excerpt as `evidence`.  When the fix is mechanical
(rename, wrap in secret, add a status message), describe it in
`suggested_fix`; when it requires schema design work, say so
explicitly so the operator-author doesn't think this is a
five-minute change.
