# `charming-with-claude` skills review (2026-05-24)

Output of Phase 36b's review of the skills in
[`tonyandrewmeyer/charming-with-claude`](https://github.com/tonyandrewmeyer/charming-with-claude)
against cantrip's own bundled skills under `src/cantrip/skills/`.
This is the verdicts log; the adopted/adapted skills themselves
land in their respective directories under cantrip's bundle.

## TL;DR

| Verdict | Skill(s) |
|---|---|
| **Adopt** (new bundled skill) | `charm-logging`, `charm-development-commands`, `charm-docs`, `juju-doctor` |
| **Adapt** (cherry-pick into existing cantrip skill) | `charmcraft`, `concierge`, `jhack`, `migrate-to-jubilant` — *deferred to a follow-up* |
| **Dev-only Claude Code plugin** | `cli-standards`, `code-review`, `juju` |
| **Reject** | `go-standards` |

The four adopted skills land in this commit with their licence
attribution.  The adapt-bucket items stay as a follow-up note rather
than landing now — the cantrip versions of `charmcraft` / `concierge` /
`jhack` already cover the workflows we exercise, and merging the
longer external versions risks bloat without a triggering need.  The
dev-only plugin install is a user action on `~/.claude/`; cantrip
doesn't modify the user's Claude Code config without an explicit
request.

## Source repo and licence

- Repo: `github.com/tonyandrewmeyer/charming-with-claude`
- Licence: CC BY 4.0 (Tony Meyer, 2025) — adoption requires
  attribution and noting changes.  Each adopted skill carries a
  one-line attribution banner at the top of its body crediting the
  source repo and licence.

## Per-skill verdicts

### `charm-logging` — **Adopt**

Canonical charm logging guidelines (Python `logging` levels, message
formatting, tense, templating, common pitfalls).  Based on spec
OB061.  Self-contained, concrete (with worked do/don't examples), and
covers a gap: cantrip has no dedicated logging skill, and `charm-debug`
/ `find-bugs` only touch logging tangentially.  Lands at
`src/cantrip/skills/charm-logging/SKILL.md`, glob-scoped to charm
source files so it surfaces during code generation.

### `charm-development-commands` — **Adopt**

Standardised `format` / `lint` / `unit` / `integration` / `docs`
command names for tox / make / just runners.  Based on spec OP061.
Cantrip's existing skills mention testing but never the
ecosystem-wide CLI standard.  Lands at
`src/cantrip/skills/charm-development-commands/SKILL.md`, glob-scoped
to `tox.ini`, `Makefile`, `justfile`, and `pyproject.toml` so it
surfaces when the agent scaffolds or edits a project's test harness.

### `charm-docs` — **Adopt**

Diátaxis-based documentation structure (README template, single-page
vs multi-page Charmhub description tab, tutorial / how-to / reference
/ explanation split, CONTRIBUTING).  Based on spec DOC009.  Cantrip's
`publishing` and `charm-improvement` skills touch Charmhub but do not
encode Diátaxis structuring.  Lands at
`src/cantrip/skills/charm-docs/SKILL.md`, glob-scoped to `README.md`,
`docs/**`, and `CONTRIBUTING.md` so it surfaces only when the agent
is editing documentation surfaces.

### `juju-doctor` — **Adopt**

Probe-based deployment validation tool (live model or offline
sosreport).  Cantrip has no equivalent — `charm-debug` covers
runtime debugging but not artefact-driven post-deployment checks.
Useful both for charm authors writing solution rulesets and for
support engineers diagnosing customer deployments offline.  Lands at
`src/cantrip/skills/juju-doctor/SKILL.md`.  No globs — relevant
whenever the agent is asked to validate or diagnose a Juju
deployment.

### `charmcraft` — **Adapt** *(deferred)*

Cantrip already ships a `charmcraft` skill.  The external version is
longer (~300 lines vs cantrip's ~200) and adds detail on remote-build,
extensions, and resource upload/release.  Core workflows overlap.
Merging would mean re-reading the external SKILL.md alongside
cantrip's and picking the incremental detail; left for a follow-up
when one of the missing pieces (e.g., `extensions` guidance) is
actually exercised in a charm-build run.

### `concierge` — **Adapt** *(deferred)*

Cantrip already ships a `concierge` skill.  External version is more
detailed (~500 lines, full preset comparison table, deeper
troubleshooting).  Same logic as `charmcraft` — adapt on demand
rather than pre-emptively bloating the bundled skill.

### `jhack` — **Adapt** *(deferred)*

Cantrip already ships a `jhack` skill.  External version covers more
pebble subcommands and chaos-testing flows.  Same disposition as
above.

### `migrate-to-jubilant` — **Adapt** *(deferred)*

Migration guide for pytest-jubilant 1.x → 2.0.  Cantrip's
`harness-migration` skill targets Harness → Scenario (a different
migration); `jubilant-tests` covers writing new tests.  A dedicated
upgrade-focused `migrate-to-jubilant` skill is worth landing the
next time the agent is asked to upgrade an existing jubilant test
suite.  Deferred until that trigger.

### `cli-standards` — **Dev-only plugin**

Canonical CLI design standards (grammar, flags, verbosity, colour,
tone).  Useful for human developers writing CLI tools (including
cantrip itself), not for the charm-building runtime — charms expose
Juju relations and actions, not standalone CLIs.  Not adopted into
the bundle.

### `code-review` — **Dev-only plugin**

Canonical code review guidelines (tone, sign-offs, changeset size,
upstreaming).  Cantrip's `find-bugs` and `security-review` skills
already cover the agent-side review needs.  This skill targets human
PR workflows, so it's a Claude Code plugin install rather than a
runtime skill.

### `juju` — **Dev-only plugin**

Comprehensive Juju CLI reference (deploy, integrate, config, status,
secrets, debug).  Cantrip already embeds equivalent guidance in the
system prompt and the `juju` operations vocabulary.  Adopting this
into the bundle would duplicate the system-prompt content;
recommending it as a Claude Code plugin for users working with Juju
outside cantrip is the better fit.

### `go-standards` — **Reject**

Canonical Go coding standards.  Cantrip generates Python charms;
the `go-framework` Charmcraft profile is out of scope for cantrip's
current ecosystem coverage.  Nothing to adopt.

## Plugin-install offer

Three skills land in the dev-plugin bucket (`cli-standards`,
`code-review`, `juju`).  Installing them as Claude Code plugins is a
user action on `~/.claude/`; the recipe is `git clone` the repo and
symlink (or copy) the three skill directories under
`~/.claude/skills/`.  cantrip does not modify the user's Claude Code
config without an explicit request — the install step is left as a
note for the user rather than executed here.

## Follow-ups

- `charmcraft` / `concierge` / `jhack` adapt — re-evaluate when one
  of the missing pieces is actually needed during a charm-build run.
- `migrate-to-jubilant` — pick up next time the agent is asked to
  upgrade an existing jubilant test suite from 1.x to 2.0.
- Periodic re-sweep — `charming-with-claude` is an active
  experiments-and-skills repo.  Worth re-running this review when a
  significant batch of new skills lands upstream.
