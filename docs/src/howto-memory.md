---
title: "How to use durable memory — Cantrip"
description: "Record and manage durable lessons across Cantrip sessions: /memory, /remember, /forget, export/import, TTL, auto-capture."
h1: "Use durable memory"
subtitle: "Record lessons once, carry them forward across every session and every charm Cantrip touches."
section: howto
breadcrumb_label: "Use durable memory"
see_also:
  - label: "Slash commands reference"
    href: "reference-cli.html#slash-commands"
  - label: "Agent tools reference"
    href: "reference-tools.html"
---

{#overview}
## What Cantrip remembers

Cantrip’s memory layer is separate from its conversation
history. Individual chats forget everything on exit; memory
survives. Two scopes exist:

- **Charm-scope** — specific to one charm.
  Stored inside the charm’s `.cantrip` SQLite
  database alongside the session.
- **Global-scope** — shared across every
  charm. Stored under
  `~/.config/cantrip/memory/` as Markdown files with
  YAML frontmatter (override via `CANTRIP_MEMORY_DIR`).

Each memory has a *kind*:

- **`fact`** — neutral information (“this charm uses Postgres 16”).
- **`rule`** — a constraint the user expects Cantrip to follow (“never push to main without approval”).
- **`lesson`** — something learned from a past mistake or recovery (“`charmcraft pack` fails when `uv.lock` is stale; run `uv lock` first”).

{#manual}
## Record a memory manually

Type a `/remember` command directly into the chat.
The <code>&nbsp;--&nbsp;</code> separator (space dash dash space)
lets titles and bodies contain any punctuation:

<pre><code><span class="comment"># A lesson, scoped to this charm:</span>
/remember lesson -- uv-lock-stale -- Run `uv lock` before charmcraft pack.

<span class="comment"># A rule, shared globally across every future charm:</span>
/remember rule global -- never-force-push -- Do not force-push to main.

<span class="comment"># A fact, charm-scoped (the default):</span>
/remember fact -- postgres-version -- Workload pins Postgres 16.</code></pre>

Cantrip confirms with a line in chat:
`Wrote rule memory: never-force-push (global)`.
The memory is immediately available in the next prompt.

{#auto}
## Let the auto-writer capture corrections

When you correct Cantrip’s approach (“actually, use
postgres instead”, “don’t run charmcraft pack
again”), Cantrip’s auto-writer detects the correction,
consults the LLM to decide whether the event is worth remembering,
and — if so — writes a memory automatically. You
don’t need to call `/remember` for every
correction.

The writer applies a
*“would this save ≥5 minutes next time?”*
gate, so most trivial events correctly collapse to a skip.
Successful writes appear inline as
`Wrote rule memory: … (charm)` so you can see
what was captured. File paths Cantrip touched while the event
unfolded are recorded as SHA-256 citations — more on that
in [Revalidation](#revalidation).

{#list}
## List and search

<pre><code><span class="comment"># List every memory across both scopes:</span>
/memory

<span class="comment"># Just charm-scope:</span>
/memory charm

<span class="comment"># Just global:</span>
/memory global</code></pre>

Output renders as a Markdown bullet list with the title, kind,
scope, and any tags. Bodies are not included — ask the
agent to read a memory by title if you want the content.

{#forget}
## Forget a memory

<pre><code><span class="comment"># Exact-title delete:</span>
/forget uv-lock-stale

<span class="comment"># Multi-word titles need quotes:</span>
/forget "never force push"

<span class="comment"># Disambiguate when the same title exists in both scopes:</span>
/forget "shared title" charm</code></pre>

If the same title exists in both charm- and global-scope and you
don’t specify which, Cantrip refuses with an
*ambiguous* message rather than guessing.

{#revalidation}
## Revalidation — self-quarantine when the source drifts

Auto-captured memories store SHA-256 hashes of the files Cantrip
touched while the event unfolded. When the agent calls
`memory_revalidate` (either explicitly or via a
follow-up on the same charm), every citation is re-checked
against the current file contents:

- If the SHA still matches, the memory stays `active`.
- If the SHA has drifted (or the file is gone), the memory is
  marked `quarantined` and no longer surfaces in the
  system prompt. This prevents Cantrip from acting on stale
  guidance after the code has moved on.
- Quarantined memories can recover automatically — a later
  revalidation that passes flips them back to `active`.

{#ttl}
## TTL — archive stale memories, purge ancient ones

Two thresholds keep the memory index focused:

- **Soft expiry (60 days)** — memories with no
  access or validation activity for this long are archived
  (`status = archived`) by
  `memory_sweep`. Archived memories are hidden from
  the prompt but remain on disk.
- **Hard prompt (180 days)** — archived memories
  older than this surface as deletion candidates via
  `memory_purge_check`, letting the agent ask you
  whether to delete or refresh.

Override the defaults per deployment with
`CANTRIP_MEMORY_SOFT_EXPIRY_DAYS` and
`CANTRIP_MEMORY_HARD_EXPIRY_DAYS`.

{#export}
## Export a memory bundle

Turn a set of memories into a portable
`SKILL.md` the skills loader can consume:

<pre><code><span class="prompt">$</span> <span class="comment"># In the chat:</span>
/memory export my-charmhub-lessons ~/exports global</code></pre>

This writes `~/exports/my-charmhub-lessons/SKILL.md`
containing every global-scope memory as a
`## Memory: <title>` section under YAML
frontmatter. Before writing Cantrip runs the export through a
sanitiser:

- Charm-specific paths are replaced with `<CHARM_PATH>`
  so the bundle is portable.
- Local SHA-256 citations are stripped (they only make sense on
  the machine that wrote them).
- Obvious secrets are scrubbed: GitHub tokens (`ghp_`,
  `gho_`, `ghs_`, `github_pat_`),
  AWS access keys (`AKIA…`), Bearer tokens,
  `password=`/`password: ` assignments,
  Slack tokens (`xox*-…`). False positives are
  intentional — a wrongly scrubbed body can be re-edited; a
  leaked credential cannot.

The response message notes the count:
`Exported 7 memories to … (2 secret redactions)`.
Review the output before sharing it.

### Plain-Markdown dump

If the recipient expects one file per memory (gist, PR diff),
use `export-md` instead:

```
/memory export-md ~/dump global
```

{#import}
## Import someone else’s bundle

<pre><code><span class="comment"># Default target scope is global:</span>
/memory import ~/downloaded/SKILL.md

<span class="comment"># Or pull into the current charm:</span>
/memory import ~/downloaded/SKILL.md charm</code></pre>

Auto-detects the format — a single `SKILL.md`
with `## Memory:` sections, or a directory of
one-memory-per-file Markdown. Duplicate titles in the target
scope are skipped by default so re-importing is safe.

{#troubleshooting}
## Troubleshooting

### “Memory not appearing in the system prompt”

The prompt index only surfaces `active` memories.
Check with:

<pre><code><span class="comment"># Ask the agent to inspect a title:</span>
is there a memory called "uv-lock-stale"?
<span class="comment"># or in chat:</span>
/memory</code></pre>

If the memory shows a `quarantined` status, a
citation SHA no longer matches its source — update the body
to reflect current state and re-save, or delete it.

### “Forgot a memory with the wrong scope”

Recover by importing the bundle you exported before the mistake:

```
/memory import ~/backups/last-good-bundle/SKILL.md charm
```

### “Auto-writer is capturing too much”

The auto-writer runs an LLM-side gate (“would this save
≥5 minutes next time?”) so most trivial corrections
collapse to skip. If a memory is captured you don’t want,
`/forget` it — the detection heuristic
won’t re-fire on the same trigger.
