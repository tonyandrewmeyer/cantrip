---
name: action-ergonomics
description: Are the action names, descriptions, and parameters user-friendly?
severity: warning
globs:
  - actions.yaml
  - charmcraft.yaml
  - src/charm.py
---

You are evaluating whether the charm's actions follow the Juju
charm UX conventions for ergonomics.

Pass when every declared action satisfies all of:

- The action name is `kebab-case`, a verb or verb-phrase, and
  describes the operator-visible effect (`rotate-credentials`,
  not `do-rotation` or `rotateCreds`).
- The action `description` is one sentence in plain English that
  tells the operator what the action does and what they should
  expect to happen — no Python jargon, no internal class names.
- Every parameter has a `description`, a `type`, and (where
  applicable) a sensible `default`.
- Required parameters have no default; optional parameters do.
- The action's behaviour as implemented in `src/charm.py` (the
  `_on_<name>_action` handler) matches what the description
  promises.

Fail when any action breaches one of the above; flag every
breaching action by name in the `message` field, and quote the
relevant action block in `evidence`.  Suggest a concrete renamed/
re-described version in `suggested_fix` when the issue is shape
rather than implementation.
