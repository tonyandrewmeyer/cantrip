---
title: "How to share charm context with teammates — Cantrip"
description: "Three opt-in settings — shared memory, shared decisions log, human co-author trailer — turn Cantrip into a small-team tool without standing up a server."
h1: "Share charm context with teammates"
subtitle: "Three opt-in toggles share memory, decisions, and attribution with teammates via the same git repo, no server required."
section: howto
breadcrumb_label: "Share with teammates"
see_also:
  - label: "Use durable memory"
    href: "howto-memory.html"
  - label: "Auto-commit per turn"
    href: "howto-auto-commit.html"
---

{#what}
## What team-sync gives you

Cantrip is a single-operator tool by default — every memory and
every decision lives only on the machine that recorded it. Teams of
two to five charm authors collaborating on the same repo hit the
same gap repeatedly: each operator builds up context the others
never see.

Team-sync closes that gap with three opt-in toggles. All three are
file-based, all three live alongside the charm in git, and all
three are reversible by removing the
`<charm>/.cantrip-shared/` directory or flipping the matching
setting back off:

- **Shared memory** — charm-scope memories travel with the repo
  via `<charm>/.cantrip-shared/memory/`.
- **Shared decisions log** — every `add_decision`
  optionally appends to
  `<charm>/.cantrip-shared/decisions.jsonl` so the *why*
  behind every choice is visible to teammates.
- **Human co-author trailer** — auto-commit messages get a
  second `Co-Authored-By:` line built from `git
  config user.name` / `user.email`, so `git log` shows
  which human steered each agent commit.

The three are independent — you can flip any one on without the
others. None of them needs a Cantrip server, and none of them
changes behaviour for an operator who has not opted in.

{#shared-memory}
## Share memories across the team

The memory subsystem already has two scopes (charm and global —
see [Use durable memory](howto-memory.html)). Team-sync adds a
third surface: an opt-in shared directory under the charm root
that everybody on the team commits to git.

### Turn it on

Set the environment variable before launching Cantrip:

```
CANTRIP_TEAM_MEMORY_WRITES=shared cantrip run .
```

The setting takes one of three values:

- **`local`** *(default)* — charm-scope writes land in
  the per-charm SQLite store, matching pre-team-sync
  behaviour.
- **`shared`** — every new charm-scope memory lands in
  `<charm>/.cantrip-shared/memory/` and is staged for
  the next commit.
- **`ask`** — delegate the decision to a registered
  callback. With no callback wired up, falls back to
  `local` so an unconfigured TUI never silently drops
  writes.

### What teammates see

Reads always merge the shared directory regardless of the write
setting, so an operator who flipped to `shared` last
week still sees teammates' memories today even after toggling
back to `local`. Shared entries surface in
`/memory` listings with the `source: shared`
marker so they're easy to tell apart from local-only entries.

The on-disk format is the same Markdown-with-frontmatter shape as
[global memory](howto-memory.html#overview):

```
---
title: postgres-version
kind: fact
source: shared
created: 2026-04-30T12:00:00
status: active
tags: []
citations: []
---

Workload pins Postgres 16.
```

`source: shared` is the marker that makes a memory team-visible.
Hand-written files in `.cantrip-shared/memory/` work
just as well as auto-writer captures — the directory is a regular
folder, not a database.

### When to use shared scope

Three rules of thumb:

- **Shared** for facts and rules the *charm* needs to obey,
  not the operator. *"Workload pins Postgres 16"*. *"Never
  push to main without approval"*. The next teammate to touch
  this charm will need the same constraints.
- **Charm (local)** for opinions personal to the operator.
  *"I prefer to test on microk8s before k8s"*. Don't push your
  workflow preferences onto teammates.
- **Global** for cross-charm rules that apply to every charm
  you touch. Already personal — sharing globally would mean
  pushing your prefs onto everyone else's repos.

{#shared-decisions}
## Share the decisions log

Cantrip records every routing decision (which model, which
substrate, which path) in a per-session SQLite table. Team-sync
adds an append-only JSONL log alongside it so teammates pick up
the *why* on the next pull.

### Turn it on

```
CANTRIP_TEAM_DECISIONS_WRITES=shared cantrip run .
```

Two values:

- **`local`** *(default)* — decisions only land in the
  per-charm SQLite store.
- **`shared`** — every `add_decision` also appends a
  JSON line to `<charm>/.cantrip-shared/decisions.jsonl`.

### What's in the log

One JSON object per line:

```
{"type": "substrate", "choice": "K8s", "reason": "containers", "timestamp": "2026-04-30T12:00:00"}
{"type": "framework", "choice": "ops", "reason": "team standardised", "timestamp": "2026-04-30T12:01:34"}
```

On load, every entry is flagged with `source="shared"`
so:

- The local SQLite save path **skips** shared rows. The JSONL
  file is the canonical record; SQLite never duplicates it.
- The agent UI can render shared decisions distinctly from
  the operator's own.
- A save → load → save round-trip never grows the JSONL — only
  fresh `add_decision` calls do.

### Reads merge regardless of the write setting

Just like shared memory, reads always merge the shared decisions
log when `charm_path` is set. Toggling
`CANTRIP_TEAM_DECISIONS_WRITES` only changes whether
*new* decisions get pushed to the file; the rest of the team's
history is always visible.

{#attribution}
## Surface which human steered each commit

When [auto-commit-per-turn](howto-auto-commit.html) is on,
Cantrip stamps every commit with a
`Co-Authored-By: Cantrip <noreply@aotearoa.dev>`
trailer to mark the agent as a co-author. Team-sync extends this
with a second trailer built from your local git config:

```
feat(charm): add ops-tracing integration

Prompt: Add ops-tracing to src/charm.py …

Touched:
  - src/charm.py

Co-Authored-By: Cantrip <noreply@aotearoa.dev>
Co-Authored-By: Tony Meyer <tony.meyer@example.com>
```

No setting required — the trailer is added automatically when
`git config user.name` and `user.email` are set.
Skipped silently for single-operator setups where the git
config matches Cantrip's canonical, so no behavioural change for
existing solo installs.

{#layout}
## Where the files live

```
<charm>/
├── .cantrip                      ← per-operator SQLite session (gitignored)
├── .cantrip-shared/              ← committed; teammates pull this
│   ├── memory/
│   │   ├── postgres-version.md
│   │   ├── ops-tracing-required.md
│   │   └── …
│   └── decisions.jsonl
└── src/
    └── …
```

A few things worth noting:

- **`.cantrip` is per-operator.** It's the local SQLite
  session file — never commit it. Add to
  `.gitignore` if it isn't already.
- **`.cantrip-shared/` is committed.** Teammates pull it the
  same way they pull source. The path differs from the
  internal-design proposal of `.cantrip/shared/`
  because `.cantrip` is occupied by the SQLite file —
  a single path can't be both a file and a directory.
- **No external service.** Everything sits next to the charm.
  If you remove `.cantrip-shared/` and stop passing
  the env vars, the team-sync surface disappears with
  zero residue.

{#conflicts}
## Conflict policy — textual git merge

When two teammates edit the same shared memory or append the
same decision concurrently, git resolves the merge textually:

- **Memory files.** Two teammates who edit
  `.cantrip-shared/memory/postgres-version.md` on
  diverging branches see git's standard merge-conflict
  markers in the file. Resolve like any other Markdown
  conflict.
- **Decisions log.** The JSONL file is append-only, so
  concurrent appends usually merge cleanly — git treats
  them as adjacent line additions. Real conflicts (two
  appends at the literal same byte offset) again get the
  standard markers; remove duplicates by hand.
- **No in-app conflict UI.** Cantrip doesn't try to
  reconcile divergent shared state — that's git's job. The
  upside is that there's nothing to learn beyond
  `git pull` and `git push`.

If the JSONL file accumulates unwanted history, hand-edit it.
Cantrip never rewrites the file outside the append path, so
removing a stale line is safe.

{#worked-example}
## Worked example — two operators

Alice picks up a new charm and turns on team-sync from the
shell:

```
export CANTRIP_TEAM_MEMORY_WRITES=shared
export CANTRIP_TEAM_DECISIONS_WRITES=shared
cantrip run .
```

She does some work. The auto-writer captures a memory
("`postgres-version`") and Cantrip records a routing
decision ("`framework=ops`"). Both land under
`.cantrip-shared/`. Auto-commit-per-turn picks them up
and pushes a commit with both trailer lines. She pushes:

```
git push
```

Bob pulls. He doesn't even need the env vars set — *reads*
always merge the shared layer:

```
git pull
cantrip run .
```

His next session starts with Alice's
`postgres-version` memory loaded into the prompt index
and her `framework=ops` decision visible in
`/decisions`. The shared memory shows up in
`/memory` with a `source: shared` marker so
he knows it came from a teammate.

When he wants to *write* a shared memory of his own, he flips
the env var on for that session:

```
CANTRIP_TEAM_MEMORY_WRITES=shared cantrip run .
```

His new memory lands in `.cantrip-shared/memory/`,
auto-commit picks it up, and Alice gets it on her next
`git pull`.

{#what-its-not}
## What team-sync is *not*

- **Not a shared server.** No daemon, no service, no extra
  port. Coordination is git, the same way the rest of the
  charm is.
- **Not real-time collaboration.** Teammates see each
  other's changes only after a push and pull. If you need
  live co-editing, this isn't it.
- **Not a substitute for code review.** A shared memory is
  not a PR — anybody on the team can append. Use the same
  judgement you'd use about anything else committed to the
  repo.
- **Not the same as the global scope.** Global memories are
  yours alone, scoped to your laptop. Shared memories are
  charm-scoped and pushed to teammates.

{#troubleshooting}
## Troubleshooting

### "Why don't I see my teammate's memories?"

Check that `.cantrip-shared/` is actually in the repo:

```
git ls-files .cantrip-shared/
```

If the directory is missing, your teammate hasn't pushed any
shared writes yet, or `.cantrip-shared/` is in
`.gitignore` somewhere up the tree. Cantrip never
auto-creates the directory — it's only made on the first
shared write.

### "I want to stop sharing without losing what's already shared"

Just unset the env vars:

```
unset CANTRIP_TEAM_MEMORY_WRITES
unset CANTRIP_TEAM_DECISIONS_WRITES
```

Existing shared files stay where they are — teammates keep
seeing them on `git pull` until somebody removes the
files explicitly. New writes go back to the local SQLite
store.

### "I want to wipe the shared layer entirely"

```
git rm -r .cantrip-shared/
git commit -m "Stop using cantrip team-sync"
```

Reverting to a single-operator setup is just removing the
directory. Local SQLite stores are untouched.
