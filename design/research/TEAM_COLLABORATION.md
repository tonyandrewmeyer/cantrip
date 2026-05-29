# Team Collaboration — Research Findings

> Output of Phase 51.  This is a research document, not a design.  It
> records the question (should Cantrip grow team-collaboration features
> beyond the single-operator shape it ships with?), the code-grounded
> single-user inventory, the peer-product survey, three candidate
> architectures with cost estimates, the verdict, and the revisit
> triggers.

## TL;DR

- **Cantrip is single-user end-to-end today, but only some of that
  is load-bearing.**  The Web UI binds to ``127.0.0.1`` with no
  auth (``web/server.py:841``); a single ``CantripAgent`` singleton
  serves every WebSocket client (``web/server.py:676``); the event
  bus broadcasts to all subscribers without addressing
  (``web/server.py:71-82``); and no schema row — message,
  decision, memory entry, task, transcript — carries an operator
  identity field.  Adding "who" anywhere is a hot-path migration
  touching every write.
- **Demand signal in the repo: zero.**  No CHANGELOG entry, no
  commit message, no issue-triage output mentions team needs.
  Phase 51's own prompt is the only place in the repo where team
  shape is named.  Cantrip's audience to date is one operator at
  one laptop.
- **The user-research archetype that matters is small (2–5)
  charm-authoring teams.**  Ops teams operating many charms and
  charm-improvement teams fixing other people's charms are
  hypothetical for Cantrip; the pattern that's plausible
  post-release is two-to-five charm authors collaborating on one
  charm, where coordination today happens entirely through git.
- **Three candidate architectures evaluated** (§5): a *thin*
  shape (each user runs Cantrip locally, share through opt-in
  git-tracked memory/decisions/attribution — small additions on
  top of Phase 42's GitHub workflow); a *medium* shape (one
  shared Cantrip server with GitHub-OAuth auth and per-user
  sessions over the existing event bus); a *heavy* shape (Cursor
  Canvases / Google Docs real-time collaboration).
- **Verdict (§6): ship the thin shape's small additions as
  Phase 51b, defer the medium shape behind a named adoption
  trigger, declare the heavy shape a non-goal.**  The thin
  additions are ~190 LOC + tests across three files
  (``agent/memory.py``, ``agent/store.py``, ``agent/auto_commit.py``)
  and could land alongside the imminent v1.0 release or as a
  v1.0.x follow-up.  The medium shape is a 1500–2500-LOC
  schema-and-server change with a security boundary, justified
  only when at least one real team adopts Cantrip and asks.
- **Two side findings independent of Phase 51** (§8):
  charm-improvement mode has no production-controller guard
  (an existing safety hole that hurts solo users today and would
  hurt teams more); Phase 46 hooks ship without operator
  identity in the payload, capping what role-based policy a
  hook could ever express.  Both warrant their own ROADMAP
  entries — Phase 10b and Phase 46b respectively — opened
  alongside this writeup.

The rest of this document walks the evidence.

## 1. The single-user surface today

### 1.1 Schema — no operator field anywhere

Every persistence row writes timestamp + content but no actor.
The relevant dataclasses and tables:

| Surface | Location | Identity column? |
|---|---|---|
| ``Message`` (LLM message) | ``llm/base.py:63-79`` | role only (USER / ASSISTANT) |
| ``Decision`` | ``agent/state.py:16-32`` | none |
| ``MemoryEntry`` | ``agent/memory.py:82-100`` | none (``source: str`` is "manual" / "auto" — not who) |
| ``WriteMemoryProposal`` | ``agent/memory_writer.py:63-86`` | none |
| ``AgentTask`` | ``agent/queue.py:42-78`` | none |
| ``messages`` table | ``agent/store.py:96-110`` | role only |
| ``decisions`` table | ``agent/store.py:60-66`` | none |
| ``session`` table | ``agent/store.py:32-58`` | timestamps only |
| Auto-commit trailer | ``agent/auto_commit.py`` | fixed ``Cantrip <noreply@aotearoa.dev>`` — same for every operator |

What this means for any team feature: adding "who" is a
schema migration plus a write-path touch on every code path
that produces one of these rows.  The migration itself is small
(SQLite ``ALTER TABLE`` for nullable columns); the write-path
sweep is wide.

### 1.2 Sessions — keyed by charm directory, not operator

``CantripAgent.__init__`` (``agent/core.py:358-383``) stores
``charm_path`` and opens ``charm_path / ".cantrip"``.  There is
no creator field, no owner check, no per-user session ID.  Any
local user with filesystem access to the charm directory can
``cantrip resume`` the session and pick up where the previous
operator left off — the resume path
(``agent/store.py:509-550``) restores state unconditionally and
worktree paths are recreated transparently.

This is incidentally the closest thing to "handoff" Cantrip has
today: the data model doesn't *block* a different person picking
up an in-flight session, but it doesn't *enable* it either —
nothing tells the next operator what's blocked, what's queued,
or what was decided by whom.

### 1.3 Memory — two scopes, neither per-user

``MemoryStore`` (``agent/memory.py``) supports two scopes:
charm-scope (per-charm, in the ``.cantrip`` SQLite) and
global-scope (per-OS-user, in
``$XDG_CONFIG_HOME/cantrip/memory/`` —
``agent/memory.py:57-68``).  Neither carries authorship.
Conflict resolution is implicit: later writes overwrite earlier
ones with no warning, no audit, no history.

Memory is the most consequential single-user assumption for the
*charm-authoring team* archetype.  If Alice teaches Cantrip
"this charm needs port 8080 because the upstream service rejects
others," Bob's Cantrip — running on Bob's laptop against the same
charm directory — has no way to learn that.  The lesson sits on
Alice's machine.  This is the highest-leverage gap a team-shape
could close.

### 1.4 Decisions — per session, no approver

The ``decisions`` table (``agent/store.py:60-66``) holds
``id, type, choice, reason, timestamp``.  The ``Decision``
dataclass (``agent/state.py:16-32``) carries the same fields.
``add_decision()`` (``agent/state.py:219-221``) takes no operator
parameter.  Every CONFIRM the agent issues today is approved by
the originator (the human at the keyboard); the answer goes onto
an ``asyncio.Future`` and into the decisions log without
recording who pressed yes.

For a 2–5 person team, the cost of this is low when everyone is
on their own laptop (whoever pressed yes was the operator); it
becomes load-bearing only in the medium shape, where multiple
operators share one CONFIRM queue.

### 1.5 Web UI — localhost-only, single-singleton, broadcast bus

Three load-bearing facts:

1. **Bind:** the server binds ``127.0.0.1`` unconditionally
   (``web/server.py:841``).  No auth layer of any kind — no
   token, cookie, or ``Authorization`` parsing.  Localhost is
   the access boundary.
2. **Singleton agent:** one ``CantripAgent`` instance is placed
   in the app state at startup (``web/server.py:676``) and
   shared by every connection.  Chat history lives in
   ``agent.state.messages``; tasks in ``agent._work_queue``;
   the in-flight turn in a single ``CURRENT_TURN_KEY`` slot
   (``web/server.py:45``).
3. **Broadcast bus:** ``_broadcast()`` (``web/server.py:71-82``)
   sends every event to every subscriber in a
   ``weakref.WeakSet`` of WebSocket clients.  The wildcard
   subscription at ``web/server.py:818`` means each client sees
   every event type — chat, thinking, tasks, juju-status,
   memory-written, all of it.

If two browsers connect to the same Cantrip server today, they
share the chat input slot, the cancel slot, the resume-decision
flag (``web/server.py:332``), and the in-flight turn task.
First click wins; subsequent clicks race or 409.  Read-only
endpoints (``/api/juju-status``, ``/api/logs``, the integration
graph) survive multiple clients fine — they fetch live and
mutate nothing — and the chat history list is append-only behind
a lock (``web/server.py:679``), so additions don't lose data
even if they interleave.

### 1.6 Controllers — already enumerates remote, but no coordination

Phase 22.1 (now archived) shipped controller enumeration:
``preflight.list_controllers()`` (``agent/preflight.py:639-672``)
and ``_list_healthy_controllers()``
(``agent/tools/environment.py:71-104``) both run ``juju
controllers --format=json`` and return everything Juju's local
config knows about, not just local concierge-prepared ones.

What's *not* there:

- **Auth.**  Cantrip never invokes ``juju register``, never
  parses macaroons, never takes a controller URL.  Auth is
  whatever the ``juju`` CLI was set up with before Cantrip ran.
- **Name disambiguation.**  ``preflight._find_k8s_controller()``
  (``agent/preflight.py:407``) returns the first controller
  matching a cloud type.  If Alice and Bob each have a local
  alias for the same remote controller (``alice-prod-k8s`` vs
  ``bob-prod-k8s``), Cantrip picks whichever the local CLI
  config lists first.  There is no canonical-endpoint check.
- **Lease reservation.**  ``JujuConfigTool``
  (``agent/tools/juju.py:1236-1285``) and ``JujuDeployTool``
  (``agent/tools/juju.py:239-315``) both call into ``jubilant``
  with no inter-operator coordination.  Two team members
  deploying the same charm to the same model rely on Juju's
  last-write-wins semantics; Cantrip adds no fencing.

### 1.7 CONFIRM, hooks, attribution — the role surface

Every CONFIRM type today (design ``agent/core.py:2243``;
day-2 ``agent/core.py:2338``; improvement audit
``agent/core.py:2403``; push ``agent/core.py:2835-2845``;
repo bootstrap ``agent/core.py:3129-3134``; triage
``agent/github_issues.py:193``; race-cost gate
``agent/executor.py:1230-1237``; permission
``agent/permissions.py:760-840``) parks on an ``asyncio.Future``
and resolves when the operator answers yes/no.  The originator
is always the approver.  Delegation has no representation in
the data model.

Phase 46 hooks (``hooks.py``, 945 lines) shipped a YAML-config
hook system with six events wired (``pre_tool_call``,
``post_tool_call``, ``pre_subagent``, ``post_subagent``,
``pre_compact``, ``post_compact``) and five reserved
(``pre_pack``, ``pre_push``, ``pre_pr``, ``on_task_complete``,
``on_session_end``).  The payload schema (``hooks.py:39-52``)
carries tool name, arguments, timing — but **no operator
identity**.  A team-deployed Cantrip server could express
team-wide policy ("no pushes after 5pm Friday" via a hook with
``if: now.hour >= 17``) but cannot express role-based policy
("Alice can approve deploys, Bob cannot") without a payload
extension.

Auto-commit attribution is a single fixed string:
``"Co-Authored-By: Cantrip <noreply@aotearoa.dev>"``
(``auto_commit.py``).  Every commit
Cantrip lands looks identical regardless of who was at the
keyboard.

## 2. Demand signal: zero in repo

A thorough sweep of ``ROADMAP.md``, ``ROADMAP_ARCHIVE.md``,
``CHANGELOG.md``, ``design/*.md``, ``docs/docs/*.html``, and
git log surfaced no team-shaped feature requests.  The phrase
"single-user", "single operator", "personal", "localhost only"
appears across the docs as descriptions of the current state but
never as a complaint or a request to fix.  The Phase 51 prompt
is the only place team needs are named in the entire repo.

This is the single largest input to the verdict.  Cantrip has
been in use long enough to accumulate Phase 1–88 of feature
work, eight CHANGELOG sections of releases, and dozens of
in-prompt user transcripts; none of it points at a team gap.
The phase opens not from observed user pain but from the
observation (correct) that the AI-coding-tools market is moving
toward team workflows in the same window Cantrip is releasing.

## 3. The archetype that matters

The phase prompt names three: small charm-authoring teams,
charm-ops teams, and charm-improvement teams.  Of the three,
**only the small charm-authoring team is plausible for
Cantrip's near-term audience** (per user research — release is
~2 weeks out, no team adopters yet).  Ops teams operating many
charms and improvement teams fixing other people's charms are
roles that exist in the Juju ecosystem (Canonical's own
field-engineering function is the closest example), but they
are not Cantrip's first-month users.

The shape of the small charm-authoring team:

- Two to five charm authors collaborating on one charm.
- Each has their own laptop and their own concierge-prepared
  local Juju environment (or a shared dev controller, depending
  on how they set up).
- Coordination today is whatever git provides: branch per task,
  PR for review, GitHub issues for triage.
- Phase 42 already delivers most of this — branch creation,
  PR creation tools, issue-triage workflows.

What this archetype actually wants from Cantrip-with-team
support is small and specific: shared lessons (don't re-teach
the same charm-specific quirks five times), shared design
decisions (don't have five Cantrips picking different approaches
for the same charm), and clear attribution (when a Cantrip
commit lands, know which human steered it).  None of those
require a shared server.

The "shift handover" example in the phase prompt — passing a
half-finished build between shifts — was a hypothetical, not an
observed pattern.  Charm work is not yet a 24/7 on-call
discipline driven by Cantrip; it remains an authoring activity
on a developer schedule.  This phase declines to design for
shift handover.

## 4. Peer survey

Three patterns in the AI-coding-tools market today:

| Tool | Local + git-share | Cloud-first agent | Hybrid |
|---|---|---|---|
| Aider | ✓ | | |
| Goose | ✓ | | |
| Claude Code (Anthropic) | ✓ (CLAUDE.md, memory, subagents) | | |
| Cantrip today | ✓ | | |
| GitHub Copilot Workspace | | ✓ (every session is a cloud workspace) | |
| Cursor (cloud agents / Background) | | ✓ (assigned to GitHub issues) | (IDE plugin local; cloud agents remote) |
| Windsurf (Command Center) | | ✓ (shared dashboard, agents run remote) | |
| Continue (Hub) | | | ✓ (local IDE plugin + cloud-shared rules / assistants) |

Three observations:

1. **The local-plus-git-share bucket is the largest** and most
   stable.  Aider, Goose, Claude Code, and Cantrip all sit here.
   Coordination is whatever git provides; the agent itself
   stays single-operator.
2. **Cloud-first agents are growing but require a security and
   billing boundary** Cantrip does not have today.  Cursor and
   Windsurf both run their team agents in their own cloud, not
   on the customer's machine.  Self-hosted equivalents
   (Continue's Hub model) carry deployment cost the customer
   absorbs.
3. **The hybrid bucket is the one Cantrip would most plausibly
   join** if it shipped team support.  Local-tool-plus-shared-
   server matches Cantrip's existing shape better than
   cloud-first.

No peer ships true real-time collaboration on a single agent
session.  Cursor's Canvases come closest (multiple users
editing the same artefact) but the agent itself is per-user.
The heavy shape (§5.3) has no peer precedent.

## 5. Three candidate architectures

### 5.1 Thin — opt-in git-tracked sync on top of Phase 42

**Shape.**  Each team member runs Cantrip locally as today.
Coordination is git, as today.  Three small additions close the
charm-authoring-team gaps without a server:

1. **Memory sync.**  Optional shared memory directory at
   ``<charm-root>/.cantrip/shared/memory/`` (Markdown files in
   the same format as global memory).  ``MemoryStore.load()``
   reads from local SQLite + the shared directory and merges,
   marking shared entries with ``source="shared"``.  Writes can
   target either scope based on a setting.  Memory written
   to ``.cantrip/shared/`` is committed to the repo and
   reaches teammates on the next pull.
2. **Decisions sync.**  Optional shared decisions log at
   ``<charm-root>/.cantrip/shared/decisions.jsonl`` (append-only
   JSON-lines).  ``SessionStore.load_session()`` reads decisions
   from SQLite and appends shared-log entries marked
   ``source="shared"``.  ``add_decision()`` optionally
   appends to the shared file when sharing is enabled.
3. **Attribution.**  The auto-commit trailer
   (``auto_commit.py``) keeps ``Co-Authored-By: Cantrip
   <noreply@aotearoa.dev>`` and *adds* a second
   ``Co-Authored-By:`` line built from ``git config user.name``
   and ``git config user.email``.  The ``Cantrip`` line stays
   as a marker that the agent steered the commit; the second
   line records which human did the steering.  Skipped silently
   when git config is unset or matches Cantrip's canonical, so
   single-operator setups see no change.

**Cost.**

| File | Change | LOC |
|---|---|---|
| ``agent/memory.py`` | Shared-dir loader + merge | ~50 |
| ``agent/memory_writer.py`` | Routing setting | ~20 |
| ``agent/store.py`` | Shared-decisions read/append | ~30 |
| ``agent/state.py`` | ``Decision.source`` field | ~5 |
| ``agent/auto_commit.py`` | Human co-author trailer | ~15 |
| Settings schema | Three opt-in flags | ~15 |
| Tests | Shared-dir merge precedence, write routing, attribution trailer | ~70 |
| Docs page | One ``docs/docs/howto-team-sync.html`` | — |

**Total: ~190 LOC + ~70 LOC tests + a docs page.**  Half a
week of focused work.  Could land alongside v1.0 if the
release schedule allows or as a v1.0.x follow-up.

**New failure modes.**  Three, all small:

- Two team members write conflicting shared-memory entries on
  the same key — the last commit wins (git's merge resolves
  textually).  Acceptable for an opt-in feature; surface as a
  warning in the merge guide.
- Shared decisions log grows unbounded — same as today's
  per-session log, just shared.  Existing GC and rotation
  policies (Phase 43.4 export rules) apply.
- A team member opts in and another doesn't; the opting-out
  member loses the benefit but loses no data.  Pure
  opportunity-cost failure mode.

**Archetype served.**  Charm-authoring teams of 2–5
collaborating on one charm.  Does nothing for ops teams or
real-time collaboration.  Does not require a server.  Does not
require auth.  Does not require schema migration to add an
operator column.

This is the recommended ship-now-or-soon shape.

### 5.2 Medium — shared Cantrip server with GitHub-OAuth auth

**Shape.**  One long-running Cantrip server per team on a
shared host.  Web UI exposes the existing event bus over
authenticated WebSocket connections.  Per-user sessions share
the memory, decisions, and transcript layers.  This is the
Windsurf Command Center / Cursor cloud agents shape, scaled
down to a single team's deployment.

**Concrete changes** (each touches the surface mapped in §1):

| Change | File / area | Estimate |
|---|---|---|
| Bind to non-localhost | ``web/server.py:841`` + deployment guide | ~10 LOC + ops |
| GitHub OAuth (uses Phase 42's ``gh`` dep) | ``web/server.py`` auth middleware + login UI + token storage | ~400 LOC |
| Per-user session isolation | ``CantripAgent`` becomes per-user, registry on the server | ~300 LOC |
| Per-connection state | Replace ``CHAT_LOCK_KEY`` / ``CURRENT_TURN_KEY`` / ``SESSION_DECIDED_KEY`` singletons with per-user dicts | ~200 LOC |
| Operator field on every write | ``Message``, ``Decision``, ``MemoryEntry``, ``AgentTask`` schemas + migration | ~250 LOC |
| Hot-path operator threading | Every write site reads operator from the request context | ~300 LOC |
| Hook payload extension | ``hooks.py`` payload gains ``operator`` field; existing hooks keep working | ~50 LOC |
| Event-bus addressing | ``_broadcast()`` learns to route per-user where appropriate | ~150 LOC |
| Conflict resolution UI | Memory / decisions / CONFIRM ambiguity surfacing | ~250 LOC |
| Tests | Per-user isolation, auth, schema migration, race conditions | ~400 LOC |
| Docs | Deployment guide, auth setup, operator-management | ~3 docs pages |

**Total: 1500–2500 LOC + ~400 LOC tests + a deployment story.**
Two to three weeks of focused work, plus operational support
for whoever hosts the team server.

**New failure modes.**  All security-critical:

- **Auth bugs are exfiltration vectors.**  A bug that lets
  user A see user B's transcripts, decisions, or memory writes
  is a privacy incident.  Test surface widens significantly.
- **Server outage kills the whole team's work.**  Today, each
  operator's Cantrip dies independently.  A team server is a
  shared single point of failure.
- **Concurrent-write races on the same ``.cantrip`` SQLite.**
  Today the SQLite file is single-writer.  A multi-operator
  server needs row-level transactions, write queuing, or
  per-user databases.
- **CONFIRM queue ambiguity.**  Today every CONFIRM is for the
  one operator at the keyboard.  In a shared server, a
  CONFIRM could be addressed to "Alice" but Bob sees it too;
  who can answer, and what stops Bob accidentally answering on
  Alice's behalf?
- **Memory pollution.**  One operator teaches Cantrip a wrong
  lesson and it taints every other operator's sessions for
  that charm.  Today the blast radius is one laptop.
- **Audit trail is now load-bearing.**  In single-user, the
  decisions log is informational.  In multi-user, it's
  evidence — needed for "who approved that production deploy?"
  questions.  Schema, retention, and export all become
  compliance surface.

**Archetype served.**  Same as thin (charm-authoring teams of
2–5), plus larger teams (6–20) that want a shared
operating-picture dashboard.  Could also serve ops teams *if*
the operational tooling around per-user ack and on-call
rotation were built — a separate scope this phase does not
estimate.

This is the deferred shape.  It is justified only when at
least one real team adopts Cantrip and asks for shared state
that the thin shape cannot provide.  See §7 for the named
revisit triggers.

### 5.3 Heavy — real-time collaborative session

**Shape.**  Multiple operators drive the same Cantrip session
simultaneously, with presence indicators ("Alice is typing"),
shared mid-stream artefacts, and conflict-free replicated data
types (CRDTs) backing the shared chat / decisions / memory.
This is the Cursor Canvases / Google Docs shape.

**Cost.**  An order of magnitude above the medium shape.  CRDT
libraries for the shared types, presence service, mid-stream
LLM-output broadcasting, conflict resolution UI for every
shared surface, multiplexed cancel semantics, and a much
deeper test matrix.  Conservative range: 8 000–15 000 LOC plus
ongoing maintenance cost on the CRDT layer.

**No peer ships this for an LLM agent session.**  Cursor's
Canvases come closest but operate on artefacts (files,
diagrams), not on the agent's reasoning loop.  The shape has no
proven product fit in the AI-coding-tools market.

**Verdict: declared a non-goal.**  Out of scope for any
foreseeable phase.  If the market converges on this shape and
demand emerges, the question reopens with new evidence — but
not as a Phase 51 follow-up.

## 6. Verdict

**Ship the thin shape's small additions as Phase 51b.  Defer
the medium shape behind a named adoption trigger.  Declare the
heavy shape a non-goal.  Open Phase 10b and Phase 46b for the
two side findings (§8) regardless of the team-collaboration
verdict.**

Reasons, in order of weight:

1. **The thin shape closes the highest-leverage gap (memory
   divergence between teammates) for ~190 LOC and no schema
   migration.**  Every other consideration — server, auth,
   per-user sessions — buys less per LOC than the
   git-tracked-shared-memory file does.  Memory is where
   single-user actually hurts the small charm-authoring team
   archetype; the rest is mostly cosmetic for that scale.
2. **Demand for the medium shape is zero today.**  No issue,
   no commit, no transcript points at it.  Building a
   security-boundary feature speculatively against zero demand
   is the wrong order of operations.  The natural sequence is
   release Cantrip, watch what teams that adopt it actually
   ask for, then build.
3. **The thin additions don't foreclose the medium shape.**
   ``.cantrip/shared/`` is opt-in, file-based, and orthogonal
   to a future server's per-user isolation.  A team that later
   wants a shared server can keep its shared memory and
   decisions files; the server reads them the same way the
   local agent does.  Nothing built in Phase 51b would have to
   be unbuilt for Phase 51c.
4. **The release window is tight (~2 weeks) and the team
   audience for Cantrip's first month is unproven.**  Shipping
   the thin additions is a low-risk improvement.  Shipping the
   medium additions in this window would mean releasing
   security-boundary code without operational maturity, against
   a problem no user has actually reported.

What lands in Phase 51 itself:

- This document (``design/TEAM_COLLABORATION.md``).
- Reference link in ``CLAUDE.md``'s *Reference Documents* list
  so future contributors find the analysis before
  re-litigating the question.
- Phase 51 marked ✓ in ``ROADMAP.md`` with the verdict and the
  revisit triggers for Phase 51c (the medium shape).
- New Phase 51b opened in ``ROADMAP.md`` with the thin-shape
  scope from §5.1 as the deliverable.
- Two side-finding phases opened (§8): Phase 10b
  (charm-improvement production-controller guard) and Phase 46b
  (operator field on hook payloads).

What does **not** land:

- No bind-to-non-localhost change in ``web/server.py``.
- No auth in the Web UI.
- No per-user session isolation.
- No operator-field schema migration on ``messages``,
  ``decisions``, ``memory_entries``, or ``tasks``.
- No CRDT, presence, or real-time-collab work.

## 7. Revisit triggers — Phase 51c (medium shape)

Open Phase 51c — *Shared Cantrip Server* — when **any** of
the following fire:

1. **A real team adopts Cantrip and requests shared state.**
   At least one team of 2+ humans uses Cantrip for one or more
   charms for at least a month, and reports (issue, transcript,
   email) that the thin shape is insufficient — typically one
   of: "we want a single dashboard for what Cantrip is doing
   across the team," or "we want cross-laptop session
   handoff," or "we want approvals from a non-originator."
2. **A Canonical-internal team commits to using Cantrip for a
   production charm.**  The internal-deployment story brings
   audit, attribution, and approval requirements that the thin
   shape does not satisfy.
3. **A peer product ships an obviously-better-than-thin shape
   that's worth matching.**  E.g. a self-hostable Cursor-style
   per-team server becomes standard, and the AI-coding-tools
   market normalises around the medium shape.

When 1 or 2 fires, the implementation phase opens with §5.2's
scope as the deliverable and §1's mapping as the change list.
GitHub OAuth (uses Phase 42's existing ``gh`` dependency)
remains the preferred auth model; SSO providers can be added
behind it if a Canonical-internal deployment requires.

When 3 fires, the design note revisits §5.2's cost estimate
with whatever the new market evidence shows — the shape may
need to shift toward (or away from) hybrid (per §4).

## 8. Side findings — independent of Phase 51 verdict

### 8.1 Phase 10b — charm-improvement production-controller guard

**Finding.**  The charm-improvement skill (``skills/
charm-improvement/SKILL.md``) instructs the agent to deploy
test charms via ``jubilant.Juju()`` against the *current*
controller — i.e., whichever controller the local ``juju`` CLI
defaults to.  If that controller happens to be a production
one (registered earlier with ``juju register`` for an unrelated
purpose, then left as default), the agent will deploy a test
charm to production without warning.  Cantrip enumerates all
controllers (``preflight.list_controllers()``,
``agent/preflight.py:639-672``) but does not classify them by
intended use.

**Hurts solo users today.**  An operator with a
production-controller default on their laptop is one
``charm-improvement`` flow away from accidentally landing test
units in production.  The blast radius is whatever the
production controller's permissions allow.

**Hurts teams more.**  In any team scenario (thin or medium),
team members have heterogeneous local CLI configs.  The
chance that *someone* on the team has a production controller
as default is much higher than the chance that any given solo
user does.

**Scope of fix.**  Two-shape recommendation:

1. *Heuristic default.*  Detect controllers that are not the
   local concierge-prepared one (cloud type ``localhost``,
   ``microk8s`` on 127.0.0.1, ``k8s`` on local socket).  Any
   non-local controller emits a CONFIRM before the
   charm-improvement skill executes ``juju deploy`` /
   ``juju relate`` / ``juju refresh``.
2. *Explicit list.*  Settings-schema field
   ``production_controllers: [str]`` lets the operator name
   controllers that always require explicit confirm regardless
   of cloud type.  Belt-and-braces with the heuristic.

**Cost.**  ~80 LOC + ~30 LOC tests + a settings-schema entry.
Ships independently of any team-collaboration work.

### 8.2 Phase 46b — operator identity in hook payloads

**Finding.**  Phase 46 hooks (``hooks.py``, 945 lines) shipped
with a payload schema (``hooks.py:39-52``) that carries tool
name, arguments, timing, but no operator identity.  This caps
what role-based policy a hook can ever express.  In single-user
Cantrip the cap is invisible (there is only one operator);
in any future team shape — even the thin shape's
attribution-aware commits — hooks cannot route on "who".

**Cost.**  ~30 LOC to add an optional ``operator`` field to
the payload, populated from ``git config user.name`` /
``user.email`` at hook-fire time, ``None`` when no git config
is set.  Existing hook scripts that don't read the field keep
working unchanged.

**Why now.**  Cheaper to add the field before any third-party
hook scripts depend on the existing payload shape than to add
it later as a breaking change.  Independent of the Phase 51
verdict; useful even if the medium shape is never built.

## 9. What this phase is *not*

- **Not a commitment to ship a shared Cantrip server.**  The
  medium shape is deferred against named triggers; it may stay
  deferred indefinitely if no team adopts Cantrip in a way that
  requires it.
- **Not a real-time-collab roadmap.**  The heavy shape is a
  declared non-goal.  Future research on collaborative agent
  sessions would open as a fresh phase, not a Phase 51 sequel.
- **Not a session-resume rework.**  Session resume
  (``agent/store.py:509-550``) stays as today.  Phase 51b's
  thin additions do not change the resume path; the medium
  shape (deferred) would.
- **Not a charm-improvement-skill rewrite.**  Phase 10b
  surfaces from this work but is a small safety patch, not a
  redesign.  Phase 10's existing-charm-improvement pipeline
  stands.
- **Not an audit-log feature.**  Decisions today are
  informational.  In single-user (and the thin shape) they
  remain so.  An audit log with retention, export, and
  compliance properties is a medium-shape concern; this phase
  does not pre-empt it.
