---
title: "How to undo agent changes — Cantrip"
description: "Roll back the last user turn — files and conversation — with /undo and /redo."
h1: "Undo agent changes"
subtitle: "Roll back the working tree and conversation history when the agent makes a mess."
section: howto
breadcrumb_label: "Undo agent changes"
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
  - label: "How Cantrip works"
    href: "explanation-architecture.html"
---

{#what-it-does}
## What `/undo` does

Cantrip snapshots your charm's working tree into a hidden git
repository immediately before each user turn enters the
conversation loop. `/undo` restores that snapshot **and**
strips the user's last message plus every assistant and tool
message that followed it from the conversation history.

Two affordances matter here:

- The snapshot is taken **before** the agent acts on a turn, so
  `/undo` rolls back to "the tree as it was when you typed that
  prompt".
- The snapshot repo lives outside your charm tree (under
  `$XDG_STATE_HOME/cantrip/snapshots/`), so it does not
  appear in `git status`, will not be committed by accident,
  and is unaffected by `git clean -fdx`.

`/undo` stacks. Run it twice to walk back two user turns; run
it three times for three. Each step restores files **and**
truncates conversation messages.

{#redo}
## Re-applying with `/redo`

`/redo` un-does the most recent `/undo` — it restores both the
working-tree state and the messages that were sliced off.

Two important details:

- Redo state is held in memory only. Restarting Cantrip drops
  it. This is deliberate: re-applying an undo across a restart
  would land in a context that no longer matches the
  conversation, which is a loud footgun.
- `/redo` is cleared the moment a new user turn arrives. Once
  you have spoken again, the agent has moved on, and the redo
  entries from before that no longer fit the present.

{#disabling}
## Turning snapshots off

Snapshotting commits the entire charm working tree (minus
gitignored paths and the `.cantrip/` session store) before
every user turn. For most charms this is sub-second. For a
charm that vendors a large dependency tree it can stutter.

Two equivalent escape hatches:

<pre><code><span class="prompt">$</span> cantrip --no-snapshots /path/to/my-charm</code></pre>

<pre><code><span class="prompt">$</span> CANTRIP_SNAPSHOTS=false cantrip /path/to/my-charm</code></pre>

When snapshots are off, `/undo` and `/redo` print a clear
"snapshots disabled" message rather than silently doing
nothing. Re-enable per session by relaunching without the
flag, or set `CANTRIP_SNAPSHOTS=true` to override an
inherited environment.

{#what-it-does-not}
## What `/undo` does not do

- It does not touch your real git repository's branches,
  refs, or working tree commits. The snapshot repo is
  separate.
- It does not roll back deployed charm changes in Juju —
  redeployment is a separate, much larger operation
  (`/deploy`, the work-queue, etc.).
- It does not roll back memory writes or anything else
  outside the charm root. Memories live in `~/.config/cantrip/`
  and survive `/undo`.
- It does not snapshot files Cantrip itself manages inside
  the charm tree (`.cantrip/` session store, Phase 44
  `.cantrip-worktrees/` for parallel subagents). Restoring
  those would corrupt agent state that lives outside the
  per-turn contract.
