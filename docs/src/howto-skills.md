---
title: "How to add a custom skill — Cantrip"
description: "Drop a standard-format skill into ~/.claude/skills/ or ~/.config/cantrip/skills/ and Cantrip uses it alongside the bundled charm-building skills."
h1: "Add a custom skill"
subtitle: "Extend Cantrip's knowledge with your own charm-building skills — no recompile, no config edits, just a Markdown file in the right place."
section: howto
breadcrumb_label: "Add a custom skill"
see_also:
  - label: "Slash commands reference"
    href: "reference-cli.html#slash-commands"
  - label: "Agent tools reference"
    href: "reference-tools.html"
  - label: "Use durable memory"
    href: "howto-memory.html"
  - label: "cantrip skill export"
    href: "reference-cli.html#skill-export"
---

{#overview}
## What a skill is

A **skill** is a focused Markdown document that teaches Cantrip
how to accomplish one charm-building task — how to write
Scenario tests, how to set up ingress, how to migrate from
Harness. The bundled set ships with Cantrip; the body loads on
demand when the agent needs it.

The same directory format is used by Claude Code, `gh skill`,
Cursor, Codex, Gemini CLI, and Windsurf — so a skill authored
for any of those tools works with Cantrip without translation.

{#locations}
## Where Cantrip looks

Cantrip discovers skills at startup from three places, in order:

1. **Bundled skills** inside the Cantrip package. You don't
   touch these.
2. `~/.claude/skills/` — shared with Claude Code and other
   vendor-neutral tools.
3. `~/.config/cantrip/skills/` — Cantrip-specific. Use this
   when you want a skill that only Cantrip should see.

Later directories override earlier ones on name conflict, so a
skill in `~/.config/cantrip/skills/scenario-tests/` takes
precedence over the bundled version. Cantrip logs an
`overrides` message at INFO level when this happens so the
precedence is auditable.

Missing directories are silently skipped — external
directories are optional.

{#format}
## Skill format

Two layouts are accepted:

- **Directory style** —
  `<root>/<name>/SKILL.md` (the Cantrip bundled layout and the
  Claude Code convention).
- **Single-file style** — `<root>/<name>.md` (common in
  lightweight user skills).

Both start with YAML frontmatter:

```markdown
---
name: my-skill
description: A one-line summary shown in the skill index.
tools:
  - juju_status
  - read_file
---

# My skill

The body is Markdown. Cantrip loads it on demand when the
agent decides this skill is relevant to the task at hand.
```

- **`name`** (required) — the identifier Cantrip uses
  internally and the one the agent names when loading the
  skill. Must be unique across all discovered skills in the
  same precedence bucket.
- **`description`** (required) — appears in the prompt-level
  skill index the agent reads on every turn, so it should be
  short and task-oriented ("Writing Scenario tests", not "A
  skill about testing").
- **`tools`** (optional) — a list of tool names the skill
  expects to use. Accepts either a YAML list or Claude Code's
  comma-separated string (`tools: tool_a, tool_b`). Cantrip
  preserves this but does not enforce it yet — it becomes
  load-bearing when Phase 50.4 lands MCP-aware skills.

{#example}
## Example: a reminder about your team's charm conventions

```bash
mkdir -p ~/.config/cantrip/skills
cat > ~/.config/cantrip/skills/team-conventions.md <<'EOF'
---
name: team-conventions
description: Coding and review conventions for charms owned by the platform team.
---

# Team conventions

- All charms use `ops[testing]` (Scenario) for unit tests,
  never Harness.
- Integration tests live in `tests/integration/` and use
  Jubilant.
- New charms must include `ops-tracing` from the start.
- Pull requests need a reviewer from the platform team
  before merging to `main`.
EOF
```

Restart Cantrip. The new skill appears in
`index.format_for_prompt()` and the agent can
`load_skill("team-conventions")` the next time it's
relevant.

{#exporting}
## Exporting a skill

`cantrip skill export NAME PATH` writes any discovered skill to a
standalone SKILL.md file in the same vendor-neutral format Cantrip
imports from. It works on the bundled skills as well as your own —
so you can start from a bundled skill, tweak it locally under
`~/.config/cantrip/skills/`, and then export the modified copy to
share with a teammate.

```bash
# Export to a skills tree (creates <dir>/<name>/SKILL.md)
cantrip skill export scenario-tests ~/my-skills-bundle

# Export to an explicit .md file (single-file layout)
cantrip skill export scenario-tests ~/scratch/scenario-tests.md

# Overwrite an existing file
cantrip skill export scenario-tests ~/scratch/scenario-tests.md --force

# Scrub occurrences of your current charm path to <CHARM_PATH>
cantrip skill export my-skill ~/share --charm-path ~/work/my-charm
```

Export is symmetric with import — dropping the resulting file into
`~/.claude/skills/` or `~/.config/cantrip/skills/` and restarting
Cantrip picks it up again.

### Sanitisation

The body is passed through the same scrubber used by `/memory
export`:

- Occurrences of the path given to `--charm-path` are replaced with
  the literal string `<CHARM_PATH>`.
- High-confidence credential shapes — GitHub tokens
  (`ghp_…`, `gho_…`, `ghs_…`, `github_pat_…`), AWS access keys
  (`AKIA…`), HTTP `Bearer` tokens, `password: value` / `password=value`
  pairs, Slack tokens (`xox?-…`) — are replaced with `[REDACTED]`.

The command prints the number of secret-pattern matches replaced so
you can see at a glance whether anything was scrubbed before you
share the file.

{#troubleshooting}
## Troubleshooting

### "My skill isn't being picked up"

Cantrip logs skipped skills at warning level. Start Cantrip
with `--log-level=DEBUG` and look for lines like:

```
Skipping malformed skill file: /home/you/.claude/skills/bad/SKILL.md
```

The usual causes:

- The file is missing the opening `---` frontmatter delimiter.
- The frontmatter is not a YAML mapping (a bare list, for
  example).
- `name` or `description` is missing or empty.

### "My skill overrides the bundled one — is that a mistake?"

Cantrip logs this explicitly at INFO level:

```
Skill 'scenario-tests' from /home/you/.config/cantrip/skills/scenario-tests/SKILL.md
overrides bundled at /path/to/cantrip/skills/scenario-tests/SKILL.md
```

If that's what you want, no action is needed. If you'd rather
keep the bundled skill, rename your file or move it to a
different directory.
