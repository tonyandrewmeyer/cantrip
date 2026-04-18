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
- Any other keys are ignored today.  Phase 50 (Skills interop) may
  adopt the cross-vendor `tools:` field; preserve forward
  compatibility by not picking names that collide.

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
  `observability`, `relation-data-design`, `terraform`
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
