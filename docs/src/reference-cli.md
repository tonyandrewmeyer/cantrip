---
title: "CLI reference — Cantrip"
description: "Complete reference for all Cantrip CLI commands, flags, and environment variables."
h1: "CLI reference"
subtitle: "All commands, flags, and environment variables."
section: reference
breadcrumb_label: "CLI reference"
on_this_page:
  - { anchor: "run", label: "cantrip run" }
  - { anchor: "compare", label: "cantrip compare" }
  - { anchor: "export-transcript", label: "export-transcript" }
  - { anchor: "hooks", label: "cantrip hooks" }
  - { anchor: "skill", label: "cantrip skill" }
  - { anchor: "slash-commands", label: "Slash commands" }
  - { anchor: "env-vars", label: "Environment variables" }
  - { anchor: "session-file", label: "Session file" }
---

{#synopsis}
## Synopsis

```
cantrip [run] [OPTIONS] [PATH]
cantrip compare CHARM_A CHARM_B
cantrip export-transcript PATH [OPTIONS]
cantrip hooks test EVENT [--payload JSON] [--path DIR]
cantrip skill export NAME PATH [--charm-path DIR] [--force]
cantrip --version
cantrip --help
```

The `run` subcommand is the default — you can omit it.
`cantrip /path/to/charm` is equivalent to
`cantrip run /path/to/charm`.

{#run}
## cantrip run

Start the agent and build or improve a charm.

### Positional arguments

<dl>
  <dt>PATH</dt>
  <dd>
    Path to the charm project directory. Defaults to the current
    directory. The directory is created if it does not exist.
  </dd>
</dl>

### Provider and model

<dl>
  <dt>--provider {gemini,claude,inference-snap}</dt>
  <dd>
    LLM provider to use. Default: <code>gemini</code>.
  </dd>

  <dt>--model MODEL</dt>
  <dd>
    Specific model name. Provider-dependent. When omitted, the
    provider's default model is used.
  </dd>

  <dt>--snap SNAP_NAME</dt>
  <dd>
    Inference snap name when using <code>--provider inference-snap</code>.
    Default: <code>gemma3</code>.
  </dd>
</dl>

### Light model (cost routing)

<dl>
  <dt>--light-model MODEL</dt>
  <dd>
    Cheaper model for internal tasks (compaction, research summaries).
    Auto-detected if omitted.
  </dd>

  <dt>--light-provider {gemini,claude,inference-snap}</dt>
  <dd>
    Use a different provider for light tasks, enabling hybrid mode.
  </dd>

  <dt>--light-snap SNAP_NAME</dt>
  <dd>
    Lighter inference snap for internal tasks (e.g.
    <code>nemotron-3-nano</code>).
  </dd>
</dl>

### Interface

<dl>
  <dt>--no-tui</dt>
  <dd>
    Run in CLI mode (command-line REPL) without the terminal UI.
  </dd>

  <dt>--web</dt>
  <dd>
    Run with a browser-based Web UI instead of the TUI.
  </dd>

  <dt>--web-port PORT</dt>
  <dd>
    Port for the Web UI. Default: <code>8471</code>.
  </dd>

  <dt>--theme THEME</dt>
  <dd>
    TUI colour theme. Options: <code>cantrip</code>,
    <code>ubuntu</code>, <code>monokai</code>,
    <code>solarized-dark</code>, <code>light</code>.
  </dd>
</dl>

### Behaviour

<dl>
  <dt>--improve CHARM_PATH</dt>
  <dd>
    Audit and improve an existing charm at the given path instead of
    building a new one.
  </dd>

  <dt>--watcher</dt>
  <dd>
    Start the event watcher on launch. The watcher monitors the dev
    model for status changes and creates diagnostic tasks
    automatically.
  </dd>

  <dt>--concurrency N</dt>
  <dd>
    Maximum number of concurrent subagent tasks. Default:
    <code>3</code>.
  </dd>
</dl>

{#compare}
## cantrip compare

Diff two charm implementations along four dimensions and print a
human-readable report. Useful for evaluating a Cantrip-generated
charm against a hand-crafted or upstream one without running a
full `diff -r`. Reads both modern
`charmcraft.yaml` and the legacy
`metadata.yaml` / `config.yaml` /
`actions.yaml` split so charms on either layout
compare cleanly.

### Positional arguments

<dl>
  <dt>CHARM_A</dt>
  <dd>First charm directory. Required.</dd>
  <dt>CHARM_B</dt>
  <dd>Second charm directory. Required.</dd>
</dl>

### Output

The report groups drift into sections:

- **Structure** — which landmark files and
  directories exist on each side (e.g. `tests/integration`,
  `terraform`, `.github/workflows`).
- **Config options** — added, removed, and
  changed `config.options` keys, with both sides'
  values printed for every changed option.
- **provides / requires / peers** — relation
  endpoints, compared by name and interface.
- **Actions**, **Containers**,
  **Extensions** — sets of names.
- **Tests** — unit- and integration-test
  file counts, always rendered even when identical so
  "both zero" is itself a visible finding.

Sections that match on both sides render as
`(identical — same X)` so your eye can skip
straight to drift.

{#export-transcript}
## cantrip export-transcript

Export a session transcript from a `.cantrip` file.

### Positional arguments

<dl>
  <dt>PATH</dt>
  <dd>
    Charm directory containing a <code>.cantrip</code> session file.
    Required.
  </dd>
</dl>

### Options

<dl>
  <dt>--format {html,markdown,jsonl}</dt>
  <dd>
    Output format. Default: <code>html</code>.
  </dd>

  <dt>--output FILE</dt>
  <dd>
    Output file path. Default:
    <code>transcript.&lt;ext&gt;</code> in the charm directory.
  </dd>

  <dt>--task TASK_ID</dt>
  <dd>
    Export only a specific task and its subagent conversation.
  </dd>

  <dt>--phase {research,build,deploy,test}</dt>
  <dd>
    Export only tasks in the given phase.
  </dd>

  <dt>--since TIMESTAMP</dt>
  <dd>
    Export only messages and events at or after the given ISO
    timestamp (e.g. <code>2026-04-15T10:00:00Z</code>).
  </dd>

  <dt>--page-size N</dt>
  <dd>
    Split HTML output into pages of N conversation messages each.
    Creates numbered files (<code>transcript_1.html</code>,
    <code>transcript_2.html</code>, etc.) with navigation links.
  </dd>
</dl>

{#hooks}
## cantrip hooks

Manage user-defined hooks configured in
`~/.config/cantrip/hooks.yaml` or
`cantrip.hooks.yaml`. See
[How to configure hooks](howto-hooks.html) for the
schema.

{#hooks-test}
### cantrip hooks test

Fires a synthetic event against the loaded hook config and
prints per-hook results — exit code, duration,
stdout/stderr excerpts, veto / timeout status. Useful while
authoring a config to check an `if:` filter
matches and a `run:` command exits cleanly. Exits
0 on success, 2 on argument / JSON errors.

```
cantrip hooks test EVENT [--payload JSON] [--path DIR]
```

<dl>
  <dt><code>EVENT</code> <span class="arg-req">required</span></dt>
  <dd>
    One of the <a href="howto-hooks.html#events">hook event
    names</a>: <code>pre_tool_call</code>,
    <code>post_tool_call</code>, <code>pre_compact</code>,
    <code>post_compact</code>, <code>pre_subagent</code>,
    <code>post_subagent</code>, plus the reserved-for-later
    names.
  </dd>
  <dt><code>--payload JSON</code></dt>
  <dd>
    Optional JSON object merged into the synthetic event
    alongside the auto-added <code>event</code> and
    <code>timestamp</code> fields. Your <code>if:</code>
    filter evaluates against the merged payload. Must be a
    JSON object; lists and scalars are rejected with exit 2.
  </dd>
  <dt><code>--path DIR</code></dt>
  <dd>
    Repo root for <code>cantrip.hooks.yaml</code> discovery.
    Defaults to the current working directory. The user-scope
    config at <code>~/.config/cantrip/hooks.yaml</code> is
    always loaded; repo hooks with a colliding
    <code>name</code> override user hooks.
  </dd>
</dl>

{#skill}
## cantrip skill

Manage Cantrip skills. See [How to add a custom
skill](howto-skills.html) for the standard SKILL.md format and
the three directories Cantrip discovers skills from.

{#skill-export}
### cantrip skill export

Writes a discovered skill to a file in the standard SKILL.md
format — the same shape Claude Code, `gh skill`, Cursor, Codex,
Gemini CLI, and Windsurf use. Works on the bundled skills and
on user skills under `~/.claude/skills/` or
`~/.config/cantrip/skills/`. The exported file drops straight
back into any of those trees and Cantrip re-imports it without
translation. Exits 0 on success, 2 on unknown-skill or
existing-target errors.

```
cantrip skill export NAME PATH [--charm-path DIR] [--force]
```

<dl>
  <dt><code>NAME</code> <span class="arg-req">required</span></dt>
  <dd>
    Name of the skill to export — as listed in
    <code>index.list_skills()</code> or in the
    <code>&lt;available_skills&gt;</code> system-prompt block.
  </dd>
  <dt><code>PATH</code> <span class="arg-req">required</span></dt>
  <dd>
    Output path. A <code>.md</code> path is honoured verbatim
    (single-file layout); any other path is treated as a
    directory and the file is written as
    <code>&lt;path&gt;/&lt;name&gt;/SKILL.md</code> (directory
    layout). Parent directories are created as needed.
  </dd>
  <dt><code>--charm-path DIR</code></dt>
  <dd>
    Path whose occurrences are replaced with the literal
    <code>&lt;CHARM_PATH&gt;</code> placeholder in the exported
    body. Defaults to no charm-path scrubbing. Secret scrubbing
    (GitHub tokens, AWS keys, <code>Bearer …</code> values,
    <code>password=…</code> pairs, Slack tokens) always runs.
  </dd>
  <dt><code>--force</code></dt>
  <dd>
    Overwrite the target file if it already exists. Without
    this flag Cantrip refuses to clobber an existing file and
    exits 2.
  </dd>
</dl>

{#slash-commands}
## Slash commands

Type these directly into the chat (TUI or Web) to drive features
that don’t go through the LLM. Output renders as a system
message; the agent is not consulted.

### Memory

Manage durable lessons across sessions. See
[the memory how-to](howto-memory.html) for workflow.

<dl>
  <dt><code>/memory [scope]</code></dt>
  <dd>
    List every remembered entry. <code>scope</code> is optional
    (<code>charm</code> or <code>global</code>); omit to list both.
  </dd>

  <dt><code>/memory help</code></dt>
  <dd>Print the full syntax block.</dd>

  <dt>
    <code>/remember &lt;kind&gt; [scope] -- &lt;title&gt; -- &lt;body&gt;</code>
  </dt>
  <dd>
    Record a new memory. <code>kind</code> is <code>fact</code>,
    <code>rule</code>, or <code>lesson</code>; <code>scope</code>
    defaults to <code>charm</code>. The
    <code>&nbsp;--&nbsp;</code> separator (space dash dash space)
    lets titles and bodies contain any punctuation.
  </dd>

  <dt><code>/forget &lt;title&gt; [scope]</code></dt>
  <dd>
    Delete a memory by exact title. Quoted titles with whitespace
    are supported. When the same title exists in both scopes the
    handler refuses with an <em>ambiguous</em> message rather than
    guessing.
  </dd>

  <dt><code>/memory export &lt;name&gt; &lt;output_path&gt; [scope]</code></dt>
  <dd>
    Bundle memories into a <code>SKILL.md</code> file at
    <code>&lt;output_path&gt;/&lt;name&gt;/SKILL.md</code> (or
    directly at <code>&lt;output_path&gt;</code> when it ends in
    <code>.md</code>). Charm paths are replaced with
    <code>&lt;CHARM_PATH&gt;</code> and obvious secrets
    (GitHub/AWS tokens, Bearer, <code>password=</code>, Slack)
    are scrubbed.
  </dd>

  <dt><code>/memory export-md &lt;output_dir&gt; [scope]</code></dt>
  <dd>
    Write one Markdown file per memory under the directory —
    the companion format for gist or PR-style sharing.
  </dd>

  <dt><code>/memory import &lt;source_path&gt; [target_scope]</code></dt>
  <dd>
    Read a <code>SKILL.md</code> or a directory of memory
    <code>.md</code> files and merge into the target scope
    (<code>global</code> by default). Duplicates skip by default.
  </dd>
</dl>

{#arena}
### Arena (blind A/B)

Compare two models on the same prompt, blinded, and record the
outcome as a global-scope memory. Useful when you’re picking
a light provider for day-to-day work and want a quick head-to-head
without reading model cards. See
[Racing and Arena](explanation-race.html) for the
design, the scoring rubric used by the non-interactive
Best-of-N race, and the transcript events both surfaces emit.

<dl>
  <dt><code>/arena &lt;prompt&gt;</code></dt>
  <dd>
    Run the primary and light providers concurrently on
    <code>prompt</code>. Both responses are shuffled into labels
    <code>A</code> and <code>B</code>&mdash;model names are hidden
    until you pick. Reply <code>A</code>, <code>B</code>,
    <code>tie</code>, or <code>skip</code> when the two responses
    arrive. A second <code>/arena</code> is rejected while one is
    pending so the labels don&rsquo;t get mixed up.
  </dd>
</dl>

Recognised picks write a `fact` memory at
`global` scope with `source="arena"`,
tagged `arena` and `model-preference`. Titles
are `arena-preference-<8-hex>`, and the body cites
both models by name plus a 200-character excerpt of the prompt so
the preference is attributable to a specific ask. Ties record a
neutral “rated equivalent” entry;
`skip` clears the session without writing a memory.
Requires a configured light provider (`--light-provider`
or `CANTRIP_LIGHT_PROVIDER`)—without one the
command prints a setup hint and exits.

### MCP (Model Context Protocol)

Inspect configured MCP servers and discover new ones from
marketplaces. See [the MCP how-to](howto-mcp.html)
for configuration.

<dl>
  <dt><code>/mcp</code></dt>
  <dd>
    List configured servers, their connection status, and the
    tool count each exposes. Status markers: <code>[ok]</code>
    connected, <code>[!!]</code> failed, <code>[--]</code>
    stopped, <code>[..]</code> pending.
  </dd>

  <dt><code>/mcp help</code></dt>
  <dd>Print the full syntax block.</dd>

  <dt><code>/mcp tools &lt;server&gt;</code></dt>
  <dd>
    List every tool a named server advertises, with descriptions.
    Tools appear to the agent as
    <code>mcp__&lt;server&gt;__&lt;tool&gt;</code>.
  </dd>

  <dt><code>/mcp marketplace</code></dt>
  <dd>
    List servers from configured marketplaces (read-only).
    Descriptors include the install hint, required env vars, and
    OAuth scopes. Cantrip never auto-installs &mdash; you copy the
    descriptor into <code>cantrip.mcp.yaml</code> after reviewing
    it.
  </dd>

  <dt><code>/mcp marketplace refresh</code></dt>
  <dd>
    Bypass the 24-hour cache and re-fetch every marketplace.
  </dd>
</dl>

{#env-vars}
## Environment variables

| Variable | Required for | Description |
|---|---|---|
| `GEMINI_API_KEY` | `--provider gemini` | Google Gemini API key |
| `ANTHROPIC_API_KEY` | `--provider claude` | Anthropic API key |
| `CANTRIP_MEMORY_DIR` | optional | Override the global memory directory. Defaults to `$XDG_CONFIG_HOME/cantrip/memory` (falls back to `~/.config/cantrip/memory`). |
| `CANTRIP_MEMORY_SOFT_EXPIRY_DAYS` | optional | Days untouched before a memory is archived by `memory_sweep`. Default `60`. Non-integer or non-positive values log a warning and fall back to the default. |
| `CANTRIP_MEMORY_HARD_EXPIRY_DAYS` | optional | Days archived before a memory is surfaced as a deletion candidate by `memory_purge_check`. Default `180`. |
| `CANTRIP_MCP_USER_CONFIG` | optional | Override the user-scope MCP config path. Defaults to `~/.config/cantrip/mcp.yaml`. |
| `CANTRIP_MCP_TOKEN_DIR` | optional | Override the per-server OAuth token storage directory. Defaults to `~/.config/cantrip/mcp_tokens/` at `0700`, with token files at `0600`. |
| `CANTRIP_MCP_GPG_TOKENS` | optional | Set to `1`/`true`/`yes`/`on` to encrypt OAuth tokens at rest with `gpg --symmetric`. Requires a configured `gpg-agent` so writes don’t block. |
| `CANTRIP_MCP_MARKETPLACE_CACHE` | optional | Override the marketplace response cache directory. Defaults to `~/.cache/cantrip/marketplaces/`; 24-hour TTL. |
| `CANTRIP_MAX_WORKTREES` | optional | Cap concurrent subagent worktrees under `.cantrip-worktrees/<task-id>/`. Set to `0` to disable worktree isolation entirely and run every subagent in the main tree. |
| `CANTRIP_NOTIFY` | optional | Notify when a task finishes. Set to `bell` for a terminal bell (`\a` to stderr), `desktop` to shell out to `notify-send` with the task title, or `both`. Defaults to off. The desktop path silently no-ops on platforms where `notify-send` is not on `PATH`. |
| `CANTRIP_NO_UPDATE_CHECK` | optional | Skip the background PyPI self-update check. Accepts `1`, `true`, `yes`, or `on` (case-insensitive). Useful on corporate networks that block `pypi.org` or for scripted runs that shouldn't talk to the public internet at all. The same effect can be made persistent by setting `update_check_disabled = true` in `~/.config/cantrip/settings.json`. |
| `CANTRIP_UPDATE_CACHE_DIR` | optional | Override the disk cache directory for the PyPI check. Defaults to `~/.cache/cantrip/`; the verdict lives in `update.json` with a 24-hour TTL. |

The `inference-snap` provider does not require an API key
as it runs models locally.

{#session-file}
## Session file

Cantrip stores session state in a `.cantrip` file (SQLite
database) in the charm project directory. This file contains:

- Conversation history (messages, tool calls, results)
- Task queue (status, dependencies, results)
- Design decisions
- Token usage metrics
- Virtual file cache

When you run `cantrip` in a directory that contains a
`.cantrip` file, the launcher prompts you to choose
<kbd>R</kbd>esume, <kbd>F</kbd>resh, or <kbd>T</kbd>ranscript:

- **Resume** — load the prior session (conversation,
  task queue, decisions) and continue where you left off.
- **Fresh** — rename the existing session to
  `.cantrip.bak-<timestamp>` so nothing is lost, then
  start with an empty store.
- **Transcript** — show the last 20 persisted
  messages inline, then re-ask the question.

The TUI shows a dedicated resume screen with the same three choices;
the Web UI shows a banner across the top of the chat panel. On a
non-TTY stdin (scripts, piped input) the CLI falls back to silent
resume so automation keeps working.

{#self-update-check}
## Self-update check

On startup, Cantrip queries the PyPI JSON API in the background
to see whether a newer release of the `cantrip`
distribution has been published. The result is cached on disk at
`~/.cache/cantrip/update.json` for 24&nbsp;hours, so
day-to-day startups don't hit the network.

When a newer version is available each front-end surfaces a
non-blocking notice:

- **TUI** — a Rich panel prints after the
  Textual screen tears down, so the prompt never interrupts
  mid-session.
- **Web UI** — a dismissible banner appears at
  the top of the page. Dismissal is remembered per version in
  `localStorage`, so the banner reappears on the next
  release without further intervention.
- **CLI** (`--no-tui`) — a single
  two-line notice prints after the REPL exits: the new version,
  the PyPI project URL, and the exact upgrade command for the
  detected installer.

The upgrade command is installer-aware. Cantrip inspects
`sys.executable` to pick among
`uv tool upgrade cantrip`, `pipx upgrade cantrip`,
`pip install --user --upgrade cantrip`,
`pip install --upgrade cantrip`, and
`snap refresh cantrip`. When nothing matches the
notice falls back to the PyPI URL rather than guess.

Pre-releases (`1.2.0rc1`) are hidden unless the
installed version is already a pre-release. If the installed
version has been yanked on PyPI the notice shifts in tone to
recommend upgrading — see
`CANTRIP_NO_UPDATE_CHECK` above to disable the check
entirely.

The `/update` slash command forces a cache-bypassing
check from inside a session and renders the result in the chat
panel. Use it to confirm a newly published release without
waiting for the 24-hour cache TTL. Two flags toggle the
persistent opt-out without hand-editing
`settings.json`:

- `/update --no-check` writes
  `update_check_disabled = true`.
- `/update --check` clears the flag.

The `CANTRIP_NO_UPDATE_CHECK` environment variable
shadows the settings file and stays in force for the running
session regardless of `/update --check`.
