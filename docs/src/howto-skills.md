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

Cantrip discovers skills at startup from these places, in
order of *most-shared* → *most-specific*. Later directories
override earlier ones on name conflict, so the most specific
copy wins. Missing directories are silently skipped — every
external directory is optional.

**User scope:**

1. **Bundled skills** inside the Cantrip package. You don't
   touch these.
2. `~/.config/agents/skills/` — the "universal" user-scope
   bucket `gh skill install --scope user` writes into when no
   agent is named; also shared by several individual agents
   (opencode, kimi-cli, warp, replit).
3. `~/.claude/skills/` — shared with Claude Code. Also the
   Claude Code user-scope dir for `gh skill install
   --agent claude-code --scope user`.
4. `~/.config/cantrip/skills/` — Cantrip-specific. Use this
   when you want a skill that only Cantrip should see.

**Project scope** (when Cantrip runs inside a charm
directory — it uses the charm path as the project root):

5. `<charm>/.agents/skills/` — the shared project-scope bucket
   `gh skill install` writes into by default (no `--scope`).
6. `<charm>/.claude/skills/` — Claude Code's project-scope
   dir.

Project-scope skills win over every user-scope skill with the
same name, so a repo-local copy always trumps a shared one.
Cantrip logs an `overrides` message at INFO level when a later
directory shadows an earlier one so the precedence is
auditable.

{#gh-skill}
## Installing skills with `gh skill install`

Cantrip automatically picks up skills installed via GitHub
CLI's [`gh skill install`](https://cli.github.com/manual/gh_skill_install)
(released in `gh` v2.90). The command writes to whichever
directory the target agent reads from — there is no separate
"`gh skill`" directory. The two recommended combinations for
Cantrip users:

```bash
# Project-scope (default) — installs into <charm>/.agents/skills/
cd ~/charms/my-charm
gh skill install microsoft/skills/harness-migration

# User-scope — installs into ~/.claude/skills/
gh skill install microsoft/skills/harness-migration \
  --agent claude-code --scope user
```

Restart Cantrip. The installed skill appears in
`index.format_for_prompt()` and can be loaded with
`load_skill("<name>")` the next time the agent needs it.

Use `gh skill list` to see what's installed and where; use
`gh skill update` to pull new versions.

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
  preserves this for cross-vendor round-tripping but does not
  enforce it.
- **`mcp_servers`** (optional) — a list of MCP server names
  the skill depends on. Same shape as `tools` (YAML list or
  comma-separated string). Cantrip checks these names against
  the configured [MCP servers](howto-mcp.html) at load time —
  see [MCP dependencies](#mcp-deps) below.

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

{#mcp-deps}
## MCP dependencies

A skill that relies on tools from an [MCP
server](howto-mcp.html) — `filesystem`, `github`, a custom
server someone on your team set up — can declare that
dependency in its frontmatter:

```markdown
---
name: deploy-via-github
description: Deploys the charm by opening a PR against the
  operations repository.
mcp_servers:
  - github
---

# Deploy via GitHub

Use `mcp__github__create_pr` to…
```

When the agent calls `load_skill("deploy-via-github")`,
Cantrip looks at the current session's configured MCP servers
(loaded from `~/.config/cantrip/mcp.yaml` and
`cantrip.mcp.yaml` per [How to use MCP
servers](howto-mcp.html)) and, if any declared server is
missing, prepends a warning banner to the returned content:

```
> ⚠️  This skill declares MCP server dependencies that are NOT
>    configured in the current session: github.
>    The content below may reference tools from those servers
>    that won't be available.  Configure the servers via
>    `~/.config/cantrip/mcp.yaml` or `cantrip.mcp.yaml`, or
>    adapt the workflow to skip those steps.

# Deploy via GitHub

Use `mcp__github__create_pr` to…
```

The skill body still loads — silently hiding a skill because
a declared MCP server is missing would be worse than a
visible warning the agent can reason about. The skill index
the agent reads on every turn (`<available_skills>…`) also
lists the requirement:

```xml
<skill>
  <name>deploy-via-github</name>
  <description>Deploys the charm by opening a PR…</description>
  <required_mcp_servers>github</required_mcp_servers>
</skill>
```

so the agent can pick a different skill when the missing
server would block it.

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
