# Prompt-based review checks (Phase 70.4)

Cantrip ships two complementary lint surfaces:

* **charmlint** (Phase 24) — deterministic AST/YAML rules. Fast,
  reproducible, easy to enforce in CI. The right place for "this
  field must be a string" or "this hook handler must catch
  ModelError".
* **Checks** (Phase 70.4) — prompt-based judgment rules. The right
  place for "does the README explain what the charm does?" or "is
  this action name something an operator would recognise?". One
  structured LLM call per rule; the answer is a validated
  `CheckResult` (`pass` | `fail`, severity, message, evidence,
  suggested fix).

Both feed `/review`, which renders one combined report. The two
surfaces are deliberately separate because the failure modes are
different — a deterministic rule that passes is correct; an LLM
rule that passes is *probably* correct. Mixing the two genres into
a single mechanism encourages either over-trusting the LLM or
under-trusting `charmlint`.

## When to write a Check vs. a charmlint rule

| Property                       | charmlint              | Check                        |
|--------------------------------|------------------------|------------------------------|
| AST/regex/YAML can express it  | yes                    | no                           |
| Verdict needs human judgment   | no                     | yes                          |
| CI gate (must always block)    | yes                    | not yet — output is advisory |
| Cost per run                   | free (local CPU)       | one LLM call per rule        |
| Reproducible across runs       | yes                    | mostly (low temperature)     |

Rule of thumb: if you can write the rule as a unit test, write a
charmlint rule. If you can only describe the rule by giving
examples ("an action called `do-thing` is bad; one called
`rotate-credentials` is good"), write a Check.

## File format

Checks live in `*.md` files under one of:

1. `<charm>/.cantrip/checks/` — repo scope (highest precedence).
2. `~/.config/cantrip/checks/` — user scope.
3. `src/cantrip/checks/` — bundled defaults (lowest precedence).

Each file is a YAML frontmatter block followed by the rule body
that the model receives verbatim:

```markdown
---
name: charm-readme-coherence
description: Does the README narrative match what the code actually does?
severity: warning      # critical/high/error/medium/warning/low/info
globs:                 # optional — default scope is every file
  - README.md
  - src/**/*.py
tools: []              # reserved for future tool-using checks
---

You are evaluating whether the charm's `README.md` accurately
describes what `src/charm.py` and the metadata declare.

Pass when ...
Fail when ...
```

`name` and `description` are required. Everything else has
sensible defaults.

## Precedence and shadowing

When two layers define the same `name`, the later layer wins —
repo overrides user overrides bundled. Each shadow records a
diagnostic in the report ("`x` from repo (`/path/x.md`) shadows
bundled (`/.../x.md`)") so the team sees they've replaced a
default. Quiet shadowing is the documented anti-pattern.

## Runtime contract

* Each Check is one structured LLM call. No tool use, no
  multi-turn dialogue. The runner reads the matching files,
  embeds them in the user message (capped at 32 KB per file,
  20 files per check), and asks for a JSON object matching the
  `CHECK_RESULT` schema (`cantrip.llm.schemas.CHECK_RESULT`).
* `severity` from the model is accepted only when it's a
  recognised value; otherwise the rule's declared severity wins.
* Error paths (LLM call failed, schema violation, no files in
  scope) surface as `error` or `skipped` results — never as a
  silent pass.
* Results sort failures-first so the operator reads the most
  actionable items at the top.

## Adding a Check

1. Create `<charm>/.cantrip/checks/<rule-name>.md` (or any of the
   other directories).
2. Add frontmatter with `name`, `description`, and (when the
   rule is file-scoped) `globs`.
3. Write the rule body in plain English. Be specific about the
   pass and fail criteria — the model returns `status: pass`
   when the criteria hold and `status: fail` otherwise.
4. Run `/review` to see it execute.

## When *not* to write a Check

* The rule should always block CI. (Make it a charmlint rule
  instead — Checks are advisory by design.)
* The rule needs to walk the whole repo or hit external
  systems. (Write a multi-step subagent task or a tool.)
* The rule is "the model should improve this code". (That's the
  oracle / agent loop, not a check.)

## Future work

* `tools:` frontmatter currently parsed but unused — Phase 70.4
  v2 will let a check declare a read-only tool allowlist
  (`fs_read`, `list_files`) so it can introspect the workspace
  beyond what the runner pre-loads.
* Phase 10 (existing-charm improvement) and Phase 17 (acceptance
  testing) will run Checks automatically when those flows ship
  the planner integration.

## Shipped

* `--severity` and `--name` filters on `/review` for incremental
  triage.  Both flags accept comma-separated values and are
  repeatable; `--name` uses `fnmatch.fnmatchcase` so
  `--name 'cos-*'` does what an operator expects.  Implemented
  in `src/cantrip/agent/commands/slash.py` (`_parse_review_filters`
  + `_apply_review_filters`); pinned by twelve cases in
  `tests/unit/agent/test_prompt_checks.py::TestSlashReview`.
