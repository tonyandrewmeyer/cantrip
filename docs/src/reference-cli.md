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
  - { anchor: "checkpoints", label: "cantrip checkpoints" }
  - { anchor: "slash-commands", label: "Slash commands" }
  - { anchor: "auto-commit", label: "Auto-commit per turn" }
  - { anchor: "architect-mode", label: "Architect / editor mode" }
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
cantrip checkpoints list [--db PATH] [--task-id ID]
cantrip checkpoints show [--db PATH] TASK_ID STEP_NAME ORDINAL
cantrip checkpoints delete [--db PATH] --task-id ID [--yes]
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
  <dt>--provider {gemini,claude,inference-snap,fireworks,openrouter,openai-compatible}</dt>
  <dd>
    LLM provider to use. Default: <code>gemini</code>.
    See <a href="howto-provider.html">Choose an LLM provider</a>
    for a full comparison.
  </dd>

  <dt>--model MODEL</dt>
  <dd>
    Specific model name. Provider-dependent. When omitted, the
    provider's default model is used. Required with
    <code>--provider openai-compatible</code>.
  </dd>

  <dt>--snap SNAP_NAME</dt>
  <dd>
    Inference snap name when using <code>--provider inference-snap</code>.
    Default: <code>gemma3</code>.
  </dd>

  <dt>--base-url URL</dt>
  <dd>
    API base URL override. Required with
    <code>--provider openai-compatible</code> (e.g.
    <code>https://api.together.xyz/v1</code>). Optional for
    <code>inference-snap</code> (overrides snap discovery),
    <code>fireworks</code>, and <code>openrouter</code> (for
    proxies or compatible hosts).
  </dd>
</dl>

### Light model (cost routing)

<dl>
  <dt>--light-model MODEL</dt>
  <dd>
    Cheaper model for internal tasks (compaction, research summaries).
    Auto-detected if omitted.
  </dd>

  <dt>--light-provider {gemini,claude,inference-snap,fireworks,openrouter}</dt>
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

  <dt>--no-snapshots</dt>
  <dd>
    Disable per-turn working-tree snapshots. By default Cantrip
    commits the charm tree into a hidden git repo before every
    user turn so <code>/undo</code> and <code>/redo</code> can
    roll back agent edits. Use this flag (or set
    <code>CANTRIP_SNAPSHOTS=false</code>) when working in a
    monorepo where snapshotting is too slow. See
    <a href="howto-undo.html">Undo agent changes</a>.
  </dd>

  <dt>--no-auto-lint</dt>
  <dd>
    Disable per-edit lint feedback. By default Cantrip runs
    <code>ruff</code> and <code>ty</code> on every Python file
    the agent writes, and <code>charmlint</code> on charm YAML
    (<code>metadata.yaml</code>, <code>charmcraft.yaml</code>,
    <code>actions.yaml</code>, <code>config.yaml</code>), then
    appends the diagnostics to the tool result so the agent
    can react to lint and type errors in the same turn. Edits
    succeed even when the linter reports issues — diagnostics
    are advisory, not gating. Use this flag if the linters are
    unavailable or the inline feedback is noisy in your
    workflow.
  </dd>

  <dt>--architect</dt>
  <dd>
    Phase 71.2 architect/editor two-model split. Each agent
    turn runs in two passes: an <em>architect</em> pass on the
    main model emits a plain-prose proposal (no tool calls),
    then an <em>editor</em> pass on a cheaper model translates
    the proposal into actual <code>fs_edit</code> /
    <code>fs_write</code> tool calls. Both passes appear
    separately in <code>/cost</code>. Toggle mid-session with
    <code>/architect</code>. See
    <a href="howto-architect-mode.html">Use architect mode</a>.
  </dd>

  <dt>--editor-provider NAME</dt>
  <dd>
    Override the editor provider when <code>--architect</code>
    is on. Useful for hybrid combinations like architect=Claude,
    editor=Gemini-Flash. Ignored without <code>--architect</code>.
  </dd>

  <dt>--editor-model SLUG</dt>
  <dd>
    Override the editor model slug when <code>--architect</code>
    is on. Defaults to the configured editor provider's default
    model. Ignored without <code>--architect</code>.
  </dd>

  <dt>--no-auto-commit</dt>
  <dd>
    Disable Phase 71.3 per-turn auto-commit. By default every
    turn that mutates files lands as a discrete git commit in
    the charm repo with a Cantrip co-author trailer; pre-existing
    dirty work commits separately as <code>chore(pre-cantrip):
    save in-progress work</code>. Use this flag (or
    <code>/auto-commit off</code> mid-session) when you prefer
    to batch agent edits into your own commits. See
    <a href="howto-auto-commit.html">Auto-commit per turn</a>.
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

  <dt>--branch TURN_ID</dt>
  <dd>
    Export the conversation path leading to a specific turn id
    (Phase 67.1).  Without this flag, the export follows the
    session's currently active branch — a forked session
    therefore exports only the active path by default.
    Off-branch turns stay reachable: list them with
    <code>/tree</code> and re-export with
    <code>--branch &lt;id&gt;</code> when needed.
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

{#checkpoints}
## cantrip checkpoints

Inspect and surgically remove step-level durable-execution
checkpoints stored under a session's `.cantrip` SQLite file.
Phase 52 persists each LLM turn and each tool call for an
in-flight subagent task so that an interrupted run resumes from
the last completed step instead of re-burning tokens from turn 1.
The `cantrip checkpoints` subcommand is the out-of-band surface
for that state — usually you won't touch it, but it's there when
a stale row is masking a fix or when you want to see what's
cached before deciding whether to resume.

All three subcommands accept `--db PATH` (default: `./.cantrip`).

{#checkpoints-list}
### cantrip checkpoints list

Prints a compact table per task showing every stored step
(`llm_turn#N` or `tool:<name>#N`), the storage kind, the first
12 characters of the input hash, and the creation timestamp.
With no filter, every task that has checkpoints is listed.

```
cantrip checkpoints list [--db PATH] [--task-id ID]
```

<dl>
  <dt><code>--db PATH</code></dt>
  <dd>Path to the <code>.cantrip</code> session file. Default: <code>./.cantrip</code>.</dd>
  <dt><code>--task-id ID</code></dt>
  <dd>Filter to a single task id. Default: list every task with checkpoints.</dd>
</dl>

{#checkpoints-show}
### cantrip checkpoints show

Pretty-prints a single stored blob. JSON-encoded kinds
(`llm_response`, `tool_result`, `value`) are decoded and printed
with `json.dumps(..., indent=2, sort_keys=True)`; `bytes` kinds
are printed as base64.

```
cantrip checkpoints show TASK_ID STEP_NAME ORDINAL [--db PATH]
```

<dl>
  <dt><code>TASK_ID</code> <span class="arg-req">required</span></dt>
  <dd>Task id the checkpoint belongs to — from <code>cantrip checkpoints list</code> or the transcript viewer.</dd>
  <dt><code>STEP_NAME</code> <span class="arg-req">required</span></dt>
  <dd>Step name, e.g. <code>llm_turn</code> or <code>tool:read_file</code>.</dd>
  <dt><code>ORDINAL</code> <span class="arg-req">required</span></dt>
  <dd>1-based ordinal within the step. The N-th <code>llm_turn</code> call for the task has ordinal N.</dd>
</dl>

Exits 1 when no row matches.

{#checkpoints-delete}
### cantrip checkpoints delete

Purges every checkpoint for one task. Useful when a stale row
is suspected of masking a real change, or when you want to force
a fresh run from turn 1 without setting
`CANTRIP_NO_RESUME` for the whole session.

```
cantrip checkpoints delete --task-id ID [--db PATH] [--yes]
```

<dl>
  <dt><code>--task-id ID</code> <span class="arg-req">required</span></dt>
  <dd>Task id whose checkpoints should be removed.</dd>
  <dt><code>--yes</code></dt>
  <dd>Skip the interactive <code>y/N</code> confirmation prompt. Intended for scripted use.</dd>
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

### Mid-session model switching

<dl>
  <dt><code>/model</code></dt>
  <dd>
    Print the active provider and model, plus the light provider
    when one is configured. Shows the syntax for switching.
  </dd>
  <dt><code>/model &lt;provider&gt;</code></dt>
  <dd>
    Swap to <code>provider</code>&rsquo;s default model. Accepts
    <code>gemini</code>, <code>claude</code>,
    <code>fireworks</code>, <code>openrouter</code>, and
    <code>inference-snap</code>. <code>openai-compatible</code>
    requires a <code>--base-url</code> that doesn&rsquo;t fit the
    slash syntax&mdash;restart the session instead.
  </dd>
  <dt><code>/model &lt;provider&gt;/&lt;model&gt;</code></dt>
  <dd>
    Swap to a specific model. Only the first <code>/</code> splits,
    so Fireworks-style slugs like
    <code>fireworks/accounts/fireworks/models/kimi-k2p6</code> work.
  </dd>
</dl>

The swap is atomic: the context-window budget tracks the new
provider&rsquo;s window, provider-dependent caches (tool list,
auto-writer) rebuild on next access, and a
<code>model_switched</code> event lands on the event bus so the
status bar and cost tracker follow. Cost accumulators survive the
swap&mdash;they&rsquo;re session totals, not per-provider. Any
cross-provider light routing (<code>--light-provider snap</code>
etc.) drops in favour of same-family routing; callers who rely on
a specific hybrid should restart the session.

{#auto-commit}
### Auto-commit per turn

<dl>
  <dt><code>/auto-commit</code></dt>
  <dd>
    Toggle the Phase 71.3 per-turn auto-commit.  Bare flips
    on/off; <code>/auto-commit on</code> and
    <code>/auto-commit off</code> are explicit.  When on,
    every turn that mutates files lands as a discrete git
    commit with a <code>Co-Authored-By: Cantrip</code>
    trailer; pre-existing dirty work commits first as
    <code>chore(pre-cantrip): save in-progress work</code>.
    See <a href="howto-auto-commit.html">Auto-commit per turn</a>.
  </dd>
</dl>

The auto-commit hook fires inside the conversation loop after
the final assistant message lands.  It walks the turn's tool
calls for <code>write_file</code> /
<code>edit_file</code> / <code>multi_edit</code>, stages the
touched paths via <code>git add -- &lt;paths&gt;</code> (no
catch-alls), and commits with a body that embeds the user
prompt plus a list of touched files.  When a light provider is
configured the subject is generated by it; otherwise we fall
back to <code>agent: &lt;truncated user message&gt;</code>.
The most recent agent commit's SHA lands on
<code>state.last_cantrip_commit_sha</code> for future audit.

{#architect-mode}
### Architect / editor mode

<dl>
  <dt><code>/architect</code></dt>
  <dd>
    Toggle the Phase 71.2 architect/editor split. With no
    argument, flips on/off; <code>/architect on</code> and
    <code>/architect off</code> are explicit. With a second
    token, sets the editor (same syntax as
    <code>/model</code>):
    <code>/architect on claude</code>,
    <code>/architect on claude/claude-haiku-4-5-20251001</code>.
    See <a href="howto-architect-mode.html">Use architect mode</a>
    for the design rationale and editor resolution rules.
  </dd>
</dl>

When architect mode is on, every conversation-loop call splits
into two passes: an <em>architect</em> pass on the main provider
that emits a plain-prose proposal (no tool calls), then an
<em>editor</em> pass on a cheaper provider that consumes the
proposal and emits the actual <code>fs_edit</code> /
<code>fs_write</code> calls. Both passes record usage attributed
to their own provider, so <code>/cost</code> shows two model
lines per turn. Both passes also fire transcript events
(<code>architect_pass</code> / <code>editor_pass</code>) for
audit. Streaming surfaces yield the editor's response as a
single chunk &mdash; the architect's proposal is internal, not
streamed to the user.

{#share}
### Share session as a gist

<dl>
  <dt><code>/share</code></dt>
  <dd>
    Export the live session as an HTML transcript and upload it as
    a <strong>secret</strong> GitHub gist via <code>gh gist
    create</code>. Returns the gist URL. Uses the same HTML
    renderer as <code>/export html</code> so the gist content is
    identical to what a local export would produce.
  </dd>
</dl>

Requires the GitHub CLI: install <code>gh</code> and run
<code>gh auth login</code> once. When <code>gh</code> is missing
or unauthenticated, <code>/share</code> still writes the HTML to a
temp file and prints a copy-pasteable
<code>gh gist create</code> command so nothing is lost&mdash;the
session is never blocked by a missing dependency. Cantrip does
not run its own hosting service; the gist lives on GitHub under
the authenticated user.

{#copy}
### Copy a chat message to the system clipboard

<dl>
  <dt><code>/copy</code></dt>
  <dd>
    Copy the most recent assistant message body, rendered as
    Markdown, to the system clipboard.  The TUI uses Textual's
    <code>App.copy_to_clipboard</code> helper; the CLI writes an
    OSC 52 escape directly to the controlling terminal so the
    copy works through tmux, screen, and ssh.
  </dd>
  <dt><code>/copy last</code></dt>
  <dd>
    Copy the last message of <em>any</em> role (including the
    user's own most recent message).  Useful when an agent reply
    interleaves with a tool block and you want the latest visible
    line.
  </dd>
  <dt><code>/copy &lt;N&gt;</code></dt>
  <dd>
    Copy the N-th message in 1-based session order.  Indices line
    up with <code>/export markdown</code> output so you can
    cross-reference if you need to copy something earlier in the
    transcript.
  </dd>
</dl>

For copy to actually reach the clipboard through tmux, your
<code>tmux.conf</code> needs <code>set -g set-clipboard on</code>
and tmux 3.2 or later.  Most modern terminal emulators (kitty,
alacritty, foot, iTerm2, gnome-terminal, Windows Terminal)
accept OSC 52 by default.  When the controlling terminal isn't a
tty (piped stdout, headless CI), the CLI prints the message body
inline so the user can still grab it manually.  The Web UI has
no equivalent server-pushed clipboard channel; <code>/copy</code>
inlines the payload in a fenced code block for browser
select-and-copy instead.

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

{#undo}
### Undo and redo

<dl>
  <dt><code>/undo</code></dt>
  <dd>
    Roll back the most recent user turn. Restores the working
    tree from the snapshot taken just before that turn started
    and removes the user&rsquo;s message plus every assistant /
    tool message that followed from history (in-memory and the
    SQLite session store). Stacks: run again to walk back further.
  </dd>

  <dt><code>/redo</code></dt>
  <dd>
    Re-apply the most recently undone turn. Restores the working
    tree to its post-turn state and re-appends the messages that
    were sliced off. The redo stack is in-memory only and clears
    the moment a new user turn arrives.
  </dd>
</dl>

{#branching}
### Branch and tree

Phase 67.1 turns the conversation history into a tree.
<code>/undo</code> deletes; <code>/branch</code> rewinds without
deleting, so every dead end stays reachable.

<dl>
  <dt><code>/branch [turn-id]</code></dt>
  <dd>
    Move the active head to a prior turn and rebuild the
    in-memory conversation from that point. With no argument,
    forks before the most recent user turn — the typical
    recovery from a bad steering message. Off-branch turns stay
    in the SQLite store and remain reachable through
    <code>/tree</code> and
    <code>export-transcript --branch &lt;id&gt;</code>.
  </dd>

  <dt><code>/tree</code></dt>
  <dd>
    Render the session as an indented tree of turns. Every
    surface gets a markdown form with turn ids and an active-
    branch marker (<code>*</code>); the TUI replaces it with an
    interactive picker — Enter on a row dispatches
    <code>/branch &lt;id&gt;</code>, Escape leaves the active
    branch alone.
  </dd>
</dl>

Snapshots are on by default. Disable per-session with
<code>--no-snapshots</code> on the command line or
<code>CANTRIP_SNAPSHOTS=false</code> in the environment.
The snapshot repo lives outside the charm tree (under
<code>$XDG_STATE_HOME/cantrip/snapshots/</code>) so it
will not appear in <code>git status</code> or be touched by
<code>git clean -fdx</code>. See
[Undo agent changes](howto-undo.html) for the full
how-to.

### Repository map

<dl>
  <dt><code>/map</code></dt>
  <dd>
    Print a compact summary of the top-ranked files in the active
    charm — one line per file with the file's primary symbol and
    a "+N more" hint.  Files are ordered by PageRank over a
    reference graph (caller → callee, plus YAML interface names
    from <code>charmcraft.yaml</code>).  Use this to confirm what
    the agent thinks the repo looks like before asking it to
    navigate.
  </dd>

  <dt><code>/map full</code></dt>
  <dd>
    Print the full per-file symbol breakdown — the same wall-of-
    text view the agent receives in its system prompt on every
    turn.  Useful for digging into a specific area; overwhelming
    as the default in a small chat panel.
  </dd>

  <dt><code>/map-refresh</code> / <code>/map-refresh full</code></dt>
  <dd>
    Discard the cache at <code>.cantrip-repomap.json</code> and
    reparse every source file from scratch, then print the
    compact (or full) summary.  Normal builds are incremental
    (only files whose mtime changed get reparsed); a refresh is
    useful after a large rename or when the cache looks stale.
  </dd>
</dl>

The map injects automatically into the system prompt under a
configurable token budget (default 1500). When the conversation
fills past 80% of the context window the budget halves; past 95%
it drops entirely so a near-full window isn't carrying a
bird's-eye view it can't act on.

### Review checks

<dl>
  <dt><code>/review</code></dt>
  <dd>
    Run every loaded prompt-based Check against the active charm.
    Each Check is one structured LLM call (the
    <code>CHECK_RESULT</code> schema constrains the reply to
    <code>{status, severity, message, evidence?, suggested_fix?}</code>),
    so the report is uniform regardless of which model you're
    using.  Failures appear first, then errors (couldn't reach a
    verdict), then skipped (no matching files), then passes.  When
    the active charm also has linter diagnostics, they appear
    underneath as a <em>Deterministic checks</em> section so you
    see one combined view.
  </dd>
</dl>

Checks are loaded from three layered locations (later wins on name
conflict): bundled defaults shipped with Cantrip, then
<code>~/.config/cantrip/checks/*.md</code> (user scope), then
<code>&lt;charm&gt;/.cantrip/checks/*.md</code> (repo scope).  Each
file is YAML frontmatter plus a markdown body — see
<a href="https://github.com/tonyandrewmeyer/cantrip/blob/main/design/CHECKS.md">design/CHECKS.md</a>
for the schema and the boundary with <code>charmlint</code>
(roughly: <code>charmlint</code> for AST/regex rules,
<code>/review</code> for "an experienced human would notice this
is off but you can't write it as a regex").

Three checks ship by default: <code>charm-readme-coherence</code>,
<code>action-ergonomics</code>, <code>relation-data-hygiene</code>.

### Project diagnostics

<dl>
  <dt><code>/diagnostics</code></dt>
  <dd>
    Run <code>ruff</code>, <code>ty</code>, and (if the directory
    looks like a charm) <code>charmlint</code> across the active
    charm and print the issues grouped by severity.  Output is
    capped at ~1500 tokens with a "<em>N more issues suppressed</em>"
    footer when the project has more issues than fit.  Result is
    cached for 30 seconds so repeated calls in the same turn don't
    re-run the linters.
  </dd>

  <dt><code>/diagnostics --refresh</code></dt>
  <dd>
    Force a fresh lint pass, bypassing the 30-second cache —
    useful right after editing files outside the agent's tools.
  </dd>
</dl>

The same aggregator runs automatically when the autonomous loop
starts a BUILD or DEBUG subagent, so the agent begins each task
already knowing what's broken.  Tools that aren't installed are
listed as <code>[skipped]</code> notes rather than silently
masking issues — a missing <code>ty</code> doesn't look the same
as "all clear."

{#env-vars}
## Environment variables

| Variable | Required for | Description |
|---|---|---|
| `GEMINI_API_KEY` | `--provider gemini` | Google Gemini API key |
| `ANTHROPIC_API_KEY` | `--provider claude` | Anthropic API key |
| `FIREWORKS_API_KEY` | `--provider fireworks` | Fireworks.ai API key |
| `OPENROUTER_API_KEY` | `--provider openrouter` | OpenRouter.ai API key |
| `OPENAI_COMPATIBLE_API_KEY` | `--provider openai-compatible` | Bearer token for the configured endpoint; set to any non-empty string when auth is not required. |
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
| `CANTRIP_NO_RESUME` | optional | Disable step-checkpoint replay for the next run. Accepts `1`, `true`, `yes`, or `on` (case-insensitive). Subagents skip the checkpoint lookup and re-execute every LLM turn and tool call live; fresh results still land in the store so the next run without the var sees a clean cache. Useful when hunting a bug that might itself be cached in a stale checkpoint. |
| `CANTRIP_KEEP_CHECKPOINTS` | optional | Preserve step checkpoints after a task reaches `DONE`. Accepts `1`, `true`, `yes`, or `on` (case-insensitive). By default, checkpoints are purged on successful task completion; setting this flips the purge into a no-op so rows can be inspected via `SELECT * FROM step_checkpoints` in the `.cantrip` SQLite file. Intended for debugging; leave unset in normal use. |
| `CANTRIP_SNAPSHOTS` | optional | Set to `0`, `false`, `no`, or `off` (case-insensitive) to disable per-turn working-tree snapshots backing `/undo` and `/redo`. Equivalent to passing `--no-snapshots`. Defaults to on; the snapshot repo lives at `$XDG_STATE_HOME/cantrip/snapshots/<hash>/`. |

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
`uv tool upgrade juju-cantrip`, `pipx upgrade juju-cantrip`,
`uv pip install --user --upgrade juju-cantrip`,
`uv pip install --upgrade juju-cantrip`, and
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
