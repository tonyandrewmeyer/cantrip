# Agent Skills

Skills are self-contained bundles of charm-building knowledge the
agent can load on demand.  Each skill is a single `SKILL.md` file
(YAML frontmatter + markdown body) in its own directory under
`src/cantrip/skills/`.  This document covers the loader, the
frontmatter schema, the load-on-demand flow, and the rules for
adding a new skill.  Cross-vendor Skills-spec interop is tracked
separately in Phase 50 of [ROADMAP.md](../ROADMAP.md) and referenced
in `src/cantrip/agent/prompts/system.md.j2` rather than re-described
here.

## The `SkillsIndex`

`src/cantrip/agent/skills.py` defines `SkillsIndex`, a two-tier
loader:

- **Tier 1 — metadata only.**  `discover()` scans `skills_dir` for
  `*/SKILL.md` files, parses their frontmatter, and keeps a
  `dict[name, SkillMetadata]` of `(name, description, path)`.  This
  is the cheap view — no skill body is read.
- **Tier 2 — full body.**  `load_skill(name)` reads the `SKILL.md`
  file on demand and returns the markdown body (everything after the
  closing `---`).  Called by the `LoadSkillTool` when the agent
  decides a skill is relevant.

`SkillsIndex` keeps no in-memory cache of bodies — re-loading a skill
re-reads the file.  Skill files are a few KB at most, and re-reading
keeps the index hot-reloadable without invalidation plumbing.

## Frontmatter schema

```yaml
---
name: scenario-tests
description: Writing unit tests for charms with ops.testing (Scenario)
---
```

- **`name`** (required) — the slug the `LoadSkillTool` accepts.
  Convention: `kebab-case`, matches the directory name.
- **`description`** (required) — a one-line summary that appears in
  the system prompt's `<available_skills>` block, and in the tool
  descriptions the LLM uses to decide which skill to load.  Keep it
  under ~120 characters; the LLM sees all descriptions at once.
- **`tools`** (optional) — cross-vendor allowlist (Phase 50 interop).
  Accepted as a YAML list or a comma-separated string.  Cantrip's
  loader does not enforce it; round-tripping with other agents
  preserves the field intact.
- **`mcp_servers`** (optional) — names of MCP servers this skill
  depends on (Phase 50.4).  When the skill is loaded with a
  configured server missing, `LoadSkillTool` prepends a warning
  banner naming the gap.
- **`globs`** (optional) — list of file-path globs that scope the
  skill to specific files (Phase 70.3).  See *Glob-conditional
  loading* below.  Accepted as a YAML list or a comma-separated
  string; absent or empty means unconditional (the default).
- Any other keys are ignored today.

## Glob-conditional loading

A skill can opt into being shown to the agent *only when relevant*
by adding a `globs:` list to its frontmatter:

```yaml
---
name: scenario-tests
description: Writing unit tests for charms with ops.testing (Scenario)
globs: [tests/unit/**, src/charm.py, src/**/charm.py]
---
```

`SkillsIndex.format_for_prompt(current_files=…)` only emits a
`<skill>` entry for a globbed skill when at least one of the
`current_files` matches at least one of its globs.  Skills without
`globs:` stay unconditional, so existing skills don't change
behaviour.

**Matching rules:**

- A pattern containing `/` is a *path-shaped* glob.  It is anchored
  at the charm root: the file's path *relative to* `charm_path`
  must match starting from the first segment.  `**` matches zero
  or more path segments anywhere it appears.
- A pattern with no `/` is a *bare* glob.  It matches the file's
  basename only — so `metadata.yaml` matches `<charm>/metadata.yaml`
  and `<charm>/sub/metadata.yaml` alike, and `*.py` matches every
  Python file regardless of depth.
- All per-segment matching uses `fnmatch.fnmatchcase` semantics
  (`*`, `?`, `[abc]`, case-sensitive).

**Sources of "current files":**  defined precisely in
[PROMPTS.md](PROMPTS.md#glob-conditional-guidance-phase-703) — fs
tool citations, user-message file mentions, and the active task's
title/description.  When `current_files` is `None` (callers that
haven't been threaded through), filtering is bypassed entirely — a
backwards-compatibility escape hatch.

**Observability.**  When a globbed skill loads or is skipped,
`CantripAgent` records a `skill_filter` transcript event with the
`loaded`, `skipped`, and `files` lists, deduped against the prior
turn so a steady-state session stays quiet.  Use this to audit
"why did this skill fire?" after a session.

**When *not* to use globs:**  if a skill's guidance applies broadly
across charm work (security review, debugging, scaffolding, the
charmcraft expert reference), leave the field off.  Globs are for
skills whose advice is genuinely scoped to a file — not a soft
"this might be relevant" hint.

The parser is forgiving about missing or malformed skills — a warning
is logged and the skill is skipped rather than failing the whole
discovery pass.

## System-prompt injection

When the agent builds the system prompt (see [PROMPTS.md](PROMPTS.md)
for the layering), `SkillsIndex.format_for_prompt()` renders an XML
block:

```xml
<available_skills>
  <skill>
    <name>scenario-tests</name>
    <description>Writing unit tests for charms with ops.testing (Scenario)</description>
  </skill>
  ...
</available_skills>
```

The system prompt instructs the agent to call `load_skill` before
starting work in a domain it recognises.  The `<description>` is the
LLM's cue — the full body is never in the default context, which
keeps the system prompt cheap and leaves room for work-specific
context.

## Load-on-demand flow

1. Agent receives a task.
2. Agent reads `<available_skills>` in the system prompt and decides
   whether any are relevant.
3. Agent calls `load_skill` with the chosen name.  The tool returns
   the full markdown body as its `ToolResult.output`.
4. The body enters the conversation history as a tool result, where
   the agent can reference it for the rest of the task.

Because load-on-demand is a regular tool call, the body participates
in context compaction like any other message.  Skills that end up
irrelevant are eligible for virtualisation (see the context-manager
docs) — they don't permanently inflate the window.

## Adding a skill

1. **Pick a slug.**  `kebab-case`, unique across the skills tree.
2. **Create the directory** at `src/cantrip/skills/<slug>/`.
3. **Write `SKILL.md`.**  Start with YAML frontmatter, one blank
   line, then the body:
   ```markdown
   ---
   name: <slug>
   description: <one-line summary>
   ---

   # <Skill title>

   ...
   ```
4. **Structure the body around the agent's workflow**, not a
   reference manual.  Good skills open with "When to use this" and
   close with "When *not* to use this".  In between, teach the
   patterns the agent will reach for — code snippets, decision
   trees, checkpoint checklists.  Avoid long prose; the agent is
   reading, not browsing.
5. **No runtime code** inside the skills tree.  If a skill needs
   a deterministic helper (icon generator, dashboard template), put
   the helper under `src/cantrip/agent/tools/` and reference it from
   the skill body.
6. **Unit-test coverage** is automatic — `SkillsIndex.discover()` is
   exercised by existing tests, which pick up any new skill without
   extra wiring.

## Removing a skill

1. Delete the directory.
2. Grep for the skill name in `prompts/`, other `SKILL.md` files,
   and the subagent prompts under `prompts/subagent/`.  Remove or
   replace any reference.

No code change in `skills.py` or `tools/skills.py` is needed —
discovery is filesystem-driven.

## Current bundled skills

The 21 skills shipped in `src/cantrip/skills/` cover:

- **Language & framework** — `twelve-factor`, `custom-charm`,
  `infrastructure-charm`, `charmcraft`
- **Features** — `adding-config`, `adding-actions`, `ingress`,
  `observability`, `relation-data-design`, `terraform`,
  `identity-platform`
- **Quality** — `scenario-tests`, `jubilant-tests`,
  `harness-migration`, `find-bugs`, `security-review`
- **Ops** — `operational-readiness`, `performance`,
  `charm-improvement`, `jhack`
- **Publishing** — `publishing`
- **Environment** — `concierge`

The authoritative list is whatever `SkillsIndex.discover()` picks up
— treat this section as indicative, not exhaustive.

## What a skill is *not*

- **Not a tool.**  Skills are advisory text; they don't execute
  anything.  The agent calls real tools after reading them.
- **Not a prompt.**  A skill supplements the agent's reasoning when
  a topic comes up; a prompt is the framing of the conversation.
  Confusing the two leads to skills that lecture the agent about
  basic agent behaviour — out of scope.
- **Not a place for project-wide rules.**  Those belong in the
  system prompt (`prompts/system.md.j2`), which every turn sees.

## Skill-as-folder convention (Phase 55.1)

The awesome-copilot skills ecosystem uses a richer folder layout
than Cantrip does today:

```
skills/<name>/
├── SKILL.md
├── assets/
│   └── templates/          # Boilerplate files the agent copies out
│       ├── STACK.md
│       └── …
├── references/             # Load-on-demand context the body links to
│   ├── stack-detection.md
│   └── inquiry-checkpoints.md
└── scripts/                # Executable helpers the body invokes
    └── scan.py
```

*Example: `skills/acquire-codebase-knowledge/` in
[github/awesome-copilot](https://github.com/github/awesome-copilot)
at revision surveyed 2026-04-24.*

Three shapes in that repo span the spectrum:

- `pytest-coverage/SKILL.md` — a one-page skill, no siblings.
- `agent-governance/SKILL.md` — long prose, still single-file.
- `acquire-codebase-knowledge/` — fully populated (7 markdown
  templates, 2 reference files, one ~500-line Python scanner).

The SKILL.md body references siblings by relative markdown link
(`[STACK.md](assets/templates/STACK.md)`) and assumes the agent
can resolve the path against a *skill root*.  In Copilot-land
this works because the harness stages the whole folder in a
known location and exports `$SKILL_ROOT` when firing the skill.

### Cantrip's current layout

Every one of Cantrip's 32 bundled skills is a single
`SKILL.md` — the directory shell exists (we already discover
`<root>/<name>/SKILL.md`) but nothing lives next to it.  Skill
bodies range from ~100 lines (`iterate-fix`, `bundle`) to ~500
lines (`charmcraft`).  Content is workflow guidance: when-to-use
blocks, decision tables, short code snippets, done-criteria
checklists.  None of the skills ship a template file or an
executable helper script.

### What it would take to adopt

Two loader gaps stand between today's layout and useful
sibling files:

1. **`LoadSkillTool` returns only the body text.**  Siblings
   aren't listed, their paths aren't surfaced, and the agent has
   no way to reach them via `load_skill`.  Options: rewrite
   relative links in the body to absolute paths at load time;
   prepend a `Skill root: <abs>` header the body can reference;
   or add a dedicated `load_skill_asset(name, relative_path)`
   tool.
2. **The agent's `read_file` tool is path-based and sandboxed to
   the working tree** (see `src/cantrip/agent/tools/read_file.py`).
   Reading from under `src/cantrip/skills/…` — or from an
   external-scope skill dir — would need either a sandbox
   exception or the dedicated asset loader above.

Neither is large, but they're real infrastructure commitments.
The filesystem walker in `SkillsIndex._discover_one_root`
already tolerates any sibling files — they're just not
surfaced to the agent today.

### Recommendation — keep the shape, defer the plumbing

Cantrip's 32 bundled skills are workflow guides.  None of them
currently ships template content that would be meaningfully
cleaner as a separate file, and none has an executable helper.
The `harness-migration` skill (185 lines) has a Harness→Scenario
equivalents table that *could* move to
`references/harness-to-scenario-map.md`, but that split would
hurt readability more than it helps: the agent reads the whole
SKILL.md into context on load, and bouncing out to fetch a
reference file doubles the tool-call count with no quality win.

The pattern becomes valuable when a skill either:

- Ships an **executable helper** the agent runs as a
  subprocess.  The Phase 55.7 "deterministic pre-scan for Path
  B custom apps" is the first concrete candidate — it proposes
  vendoring or porting `awesome-copilot`'s ~500-line `scan.py`
  into Cantrip.  If that phase lands via the vendored script
  path (as opposed to a fully Cantrip-native Python tool), the
  script belongs under `skills/acquire-codebase-knowledge/scripts/`
  and the loader change becomes worth the spend.
- Ships **copy-me-into-the-repo templates** bigger than a
  snippet.  The Phase 55.6 "runnable cookbook" might surface
  such a case if a cookbook recipe wants a ready-made charm
  skeleton to paste in.  Same trigger.

Until one of those lands, the right move is:

- **Keep the existing directory shell** — we already match the
  folder shape by naming convention; the loader is happy to
  ignore siblings.  No change here.
- **Do not split current skills** into `SKILL.md +
  references/…`.  The split is a code-smell on 185-line bodies;
  it only pays off when siblings carry genuinely self-contained
  artefacts.
- **File the loader work as a prerequisite of Phase 55.7 (or
  55.6)**, not as a standalone phase.  When the first real
  asset-bearing skill arrives, do both together so the
  infrastructure lands with its motivating use case instead of
  in the abstract.

Cross-references:

- Phase 50 (Skills interop): the SKILL.md + frontmatter shape
  already matches the cross-vendor convention, so import/export
  of folder-layout skills is a pure loader-extension problem
  rather than a schema migration.
- Phase 53.5 (prompts/skills design split): when that lands, the
  decision here should remain discoverable in `design/SKILLS.md`
  (this section).  Do not move it to a parallel design doc.
