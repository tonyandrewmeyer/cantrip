# Cantrip Implementation Roadmap

## Design Philosophy

Cantrip is an **autonomous agent** that builds charms independently. The user describes what
to charm; the agent researches, designs, builds, deploys, and iterates — with the user
confirming key decisions and providing domain expertise. The agent does not wait to be told
what to do next.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              Cantrip                                       │
│                                                                            │
│  ┌──────────────────────┐         ┌──────────────────────────────────┐    │
│  │   Conversation Loop  │         │       Autonomous Work Loop       │    │
│  │                      │ ◄─────► │                                  │    │
│  │  User confirms,      │ steer/  │  Research → Design → Build →    │    │
│  │  overrides, provides │ notify  │  Deploy → Test → Debug → Fix    │    │
│  │  domain expertise    │         │                                  │    │
│  └──────────────────────┘         └──────────────────────────────────┘    │
│              │                                    │                        │
│              ▼                                    ▼                        │
│  ┌──────────────────────────────────────────────────────────────────┐     │
│  │                     TUI / Web UI                                 │     │
│  │   Chat panel  │  Task checklist  │  Juju status  │  Status bar   │     │
│  └──────────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────────┘
```

Two loops run concurrently:

1. **Conversation loop** — the user talks to the agent. Mostly confirming designs,
   providing operational knowledge, and steering priorities. The user should rarely need to
   tell the agent *what to do next* — only *whether it's right*.

2. **Autonomous work loop** — the agent picks tasks from a work queue and executes them
   without user prompting. Research, scaffolding, deploying, testing, debugging, redeploying.
   The watcher feeds events into the same queue.

The TUI shows both: the chat conversation and a visible task checklist so the user always
knows what the agent is doing, has done, and plans to do.

---

## Archived Phases

Completed phases (and the legacy Phases 0–3 summary) have been moved to
[`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md) to keep this file focused on
active work. The archive preserves the full detail of each finished phase.

---

## Phase 36b: Review charming-with-claude Skills

**Goal:** Review the skills in `github.com/tonyandrewmeyer/charming-with-claude`
and adopt them for use when building Cantrip and/or incorporate them into
Cantrip's own agent (system prompts, subagent guidance, skills).

- [ ] Clone the repo and review all available skills
- [ ] Evaluate each skill for (a) use as a Claude Code plugin when developing
  Cantrip itself, and (b) incorporation into Cantrip's own skill system for
  charm generation
- [ ] Install as a Claude Code plugin if useful for development
- [ ] For skills relevant to charm building, either adopt directly or adapt
  into Cantrip's agentskills.io-format skills
- [ ] Document findings: what was adopted, what was rejected (and why)

**Exit criteria:** Review complete. Useful skills adopted or adapted.
`make check` passes throughout.

---

## Dependencies and Blockers

| Item | Blocked By | Notes |
|------|------------|-------|
| Task planner (4.2) | Task model (4.1) | Need the data structures before the LLM can populate them |
| Background executor (4.3) | Task model (4.1) | Executor consumes the work queue |
| Task checklist widget (4.4) | Task model (4.1) | Widget renders task state |
| Auto-deploy loop (4.5) | Background executor (4.3) | Deploy tasks run through the executor |
| Research-driven design (5.x) | Background executor (4.3) | Research tasks are autonomous work |
| Parallel execution (6.1) | Phase 4 executor (4.3) | Extends the existing sequential executor |
| Fast path (6.2) | Phase 5 design pipeline | Needs the full pipeline working to know what to skip |
| Merge planning (6.4) | Phase 6 speed analysis | Needs discussion and evaluation first |
| Advanced testing (7.2) | Phase 4 autonomous core | Tests should run as autonomous tasks |
| Charmhub publishing (7.4) | Phase 5 design pipeline | Only publish well-researched charms |
| Inference snaps (8.2+) | Phase 8.1 basic provider | Need the basic provider working to evaluate quality |
| Terraform support (9.x) | Phase 5 design pipeline | Needs working charm build pipeline to generate modules from |
| Charm audit (10.1) | Phase 4 autonomous core | Audit tasks run as autonomous work |
| Test gap fill (10.3) | Phase 2 test generation | Builds on existing Scenario/Jubilant generation |
| Observability gap fill (10.2) | Phase 2 COS integration | Builds on existing COS tooling |
| Listing readiness (10.5) | Phase 7.4 publishing | Builds on existing Charmhub publishing support |
| Commit-after-build (11.1) | Phase 4 executor (4.3) | Extends subagent guidance and executor checks |
| Self-verification (11.2) | Phase 4 executor (4.3) | Extends BUILD tool allowlist and guidance |
| Session resume (11.3) | Phase 2.5 persistence | Builds on existing SQLite session store |
| Git-revert-on-failure (11.4) | Phase 1.5 git tools | Uses existing git tooling in the executor |
| Environment health checks (11.5) | Phase 4 executor (4.3) | Pre-task checks before subagent launch |
| Integration-tests-first (12.1) | Phase 4 planner (4.2) | Changes the build task sequence in the planner prompt |
| Test generation from design (12.2) | Phase 5 design pipeline | Needs approved DESIGN.md to extract testable contracts |
| Test-driven build subagent (12.3) | Phase 12.1 + 12.2 | Needs tests written before build subagent can target them |
| Incremental feature TDD (12.4) | Phase 12.3 | Extends the red/green cycle to feature additions via replanning |
| Unit tests second pass (12.5) | Phase 12.3 | Sequences unit tests after integration tests pass |
| Showboat/Rodney integration (13.1) | Phase 4 executor (4.3) | Wraps external CLI tools as agent tools |
| Demo document generation (13.2) | Phase 13.1 | Uses Showboat to capture live deployment output |
| Captured artefacts (13.3) | Phase 13.2 | Saves standalone files alongside the demo document |
| Visual assets (13.4) | Phase 13.1 + Phase 2.2 COS | Uses Rodney for Grafana/web UI screenshots |
| Demo tutorial (13.5) | Phase 5 design pipeline | Draws on WORKLOAD.md and DESIGN.md |
| Demo as pipeline stage (13.6) | Phase 13.2 + 13.5 | Integrates demo generation into the planner |
| Conversation recording (14.1) | Phase 2.5 persistence | Extends the existing SQLite store schema |
| Subagent recording (14.2) | Phase 14.1 + Phase 4.3 executor | Records full subagent conversations to SQLite |
| Event log (14.3) | Phase 14.1 | Adds event stream alongside message recording |
| HTML export (14.4) | Phase 14.1 + 14.2 | Needs recorded data to export |
| Additional export formats (14.5) | Phase 14.4 | Extends the export pipeline with JSONL/Markdown |
| Live transcript in TUI (14.6) | Phase 14.1 + 14.2 | Needs recording in place to display |
| Shared UI event bus (15.1) | Phase 4.4 TUI widgets | Refactors existing TUI widgets to event-driven |
| Localhost HTTP server (15.2) | Phase 15.1 | Needs event bus to bridge to WebSocket |
| Static frontend (15.3) | Phase 15.2 | Needs server to serve assets and provide API |
| Real-time updates (15.4) | Phase 15.2 + 15.3 | Needs both server and frontend in place |
| Alternative views (15.5) | Phase 15.3 | Extends the base frontend layout |
| Feature parity maintenance (15.6) | Phase 15.1 | Ongoing process once event bus exists |
| Security event identification (16.1) | Phase 5 design pipeline | Assessed during design phase |
| Tracing instrumentation guidance (16.2) | Phase 2 COS integration | Extends existing ops-tracing setup |
| Security event collection (16.3) | Phase 16.1 + Phase 2 COS | Needs security events + Loki/Grafana |
| Security/tracing audit (16.4) | Phase 10.1 + Phase 16.1 | Extends charm audit with security checks |
| Action exerciser (17.1) | Phase 4 executor (4.3) + Phase 4.5 auto-deploy | Needs a live deployment to exercise actions against |
| Relation smoke tests (17.2) | Phase 17.1 + Phase 5 design pipeline | Needs deployed charm and workload knowledge to pick partners |
| Workload endpoint testing (17.3) | Phase 17.1 + Phase 5 design pipeline | Needs research context to know how to probe the workload |
| Config variation testing (17.4) | Phase 17.1 | Needs a live deployment to apply config changes against |
| Upgrade and lifecycle testing (17.5) | Phase 17.1 | Needs a live deployment to test scale/refresh |
| Acceptance test report (17.6) | Phase 17.1–17.5 | Consolidates results from all acceptance test stages |
| Planner integration (17.6) | Phase 4 planner (4.2) + Phase 7.2 | Acceptance tests become a standard pipeline stage after integration tests |
| Landscape survey (18.1) | None | Can start any time — pure research |
| Architecture mapping (18.2) | Phase 18.1 | Needs the candidate list to map against |
| Proof of concept (18.3) | Phase 18.2 | Needs mapping results to select candidates for spike |
| Decision and recommendation (18.4) | Phase 18.3 | Needs spike results to make an informed recommendation |
| Readiness assessment tool (19.1) | Phase 10.1 charm audit | Extends the audit pattern with operability checks |
| Readiness skill (19.2) | Phase 0.4 skills infrastructure | New skill following existing SKILL.md pattern |
| Operability planner phase (19.3) | Phase 4 planner (4.2) + Phase 19.1 | Needs assessment tool results to generate fix tasks |
| Readiness report (19.4) | Phase 19.1 | Needs assessment results to generate the report |
| Improvement mode integration (19.3) | Phase 10 charm improvement | Extends the existing improvement pipeline |
| Pure state machine (21.1) | Phase 4 autonomous core | Formalises the existing executor routing logic |
| Service injection (21.2) | Phase 4 executor (4.3) | Refactors the executor to accept Protocol services |
| Noop detection (21.3) | Phase 21.2 | Needs service injection to capture state snapshots cleanly |
| Graceful shutdown (21.4) | Phase 4 executor (4.3) | Extends executor lifecycle management |
| Exit contracts (21.5) | Phase 4 subagent (4.6) | Formalises subagent result reporting |
| Scoped tool access (21.6) | Phase 4 planner (4.2) | Formalises existing category-based tool allowlists |
| Relation databag tool (20.1) | Phase 0.3 Juju integration | Reads relation data via Jubilant or juju show-unit |
| App config tool (20.2) | Phase 0.3 Juju integration | Reads config via juju config CLI |
| WebSocket log streaming (20.3) | Phase 3.1 watcher | Replaces/supplements SSH-to-Loki polling |
| Cross-model offers (20.4) | Phase 0.3 Juju integration | Multi-controller inspection |
| Detect K8s controller for COS (22.1) | Phase 0.3 Juju integration | Needs controller enumeration via Jubilant or subprocess |
| Cross-model COS integration (22.2) | Phase 22.1 | Needs K8s controller targeting + juju offer/consume |
| Preflight multi-controller awareness (22.3) | Phase 22.1 | Extends preflight to enumerate controllers |
| COS system prompt updates (22.4) | Phase 22.2 | Updates prompts and skills for cross-model COS |
| Secrets inspection (20.5) | Phase 0.3 Juju integration | Lists and inspects Juju secrets |
| TUI status enhancements (20.6) | Phase 1.3 TUI + Phase 20.1 | Needs relation data tool for detail panel |
| Bare Exception catches (25.1) | None | Style-guide compliance; can start any time |
| Shell injection fix (25.2) | None | Security fix; can start any time |
| Target version fix (25.3) | None | Config fix; can start any time |
| Duplicated `_run_juju()` (25.4) | None | Refactor; can start any time |
| Duplicated `_get_system_prompt()` (25.5) | None | Refactor; can start any time |
| Duplicated light provider resolution (25.6) | None | Refactor; can start any time |
| Streaming duplication (25.7) | None | Refactor; can start any time |
| Long function decomposition (25.8) | None | Refactor; can start any time |
| Claude prompt caching (27.1) | None | Provider-level change; can start any time |
| Fix max_tokens 4096 cap (27.2) | None | Provider-level change; can start any time |
| Gemini duplicate tool call IDs (27.3) | None | Provider-level bug fix; can start any time |
| Extended thinking support (27.4) | None | Provider-level change; can start any time |
| SQLite busy timeout (28.1) | None | Store-level fix; can start any time |
| Hardcoded task ID collisions (28.2) | None | Planner fix; can start any time |
| Executor exception hardening (28.3) | None | Executor fix; can start any time |
| Subagent context management (28.4) | Phase 4 subagent | Extends existing subagent runner |
| Concurrent subagent tools (28.5) | Phase 4 subagent | Changes tool execution in subagent.py |
| Streaming responses (28.6 + 31.2) | Phase 25.7 streaming dedup | Needs unified streaming path first |
| Wire RelationDetailScreen (29.1) | Phase 20.6 TUI status | Screen exists, needs handler in app.py |
| Shell injection fix (30.1) | None | Security fix; can start any time |
| Missing Juju tools (30.2) | Phase 0.3 Juju integration | New tools using existing juju patterns |
| Missing git tools (30.3) | Phase 1.5 git tools | New tools using existing git patterns |
| Existing bundle management (33.1) | Phase 0.3 Juju integration | Read/deploy existing bundles only; new bundles are deprecated |
| Charm migration (33.2) | Phase 10 charm improvement | Extends the improvement pipeline |
| Multi-charm workspace (33.3) | Phase 5 design pipeline | Needs design system for multi-charm coordination |
| ACP protocol familiarisation (39.1) | None | Pure research; can start any time |
| Candidate agents survey (39.2) | Phase 39.1 | Needs protocol understanding first |
| Integration sketch (39.3) | Phase 39.2 | Needs candidate assessment to design against |
| ACP decision write-up (39.4) | Phase 39.3 | Needs integration sketch to make recommendation |
| Compaction cycle detection (40.1) | Phase 28.7 compaction recovery | Extends existing compaction/emergency_truncate |
| Compaction retry budget (40.2) | Phase 28.1 SQLite upsert | Persists counters via session store |
| Post-compaction validation (40.3) | Phase 28.4 context window mgmt | Needs token estimation working |
| Gemini streaming usage (41.1) | None | Provider-level fix; can start any time |
| Extended thinking (41.2) | Phase 27.4 extended thinking | Anthropic-specific feature |
| Caching awareness (41.3) | Phase 27.1 Claude caching | Monitoring/logging improvement |
| Claude model ID updates (41.4) | None | Maintenance; can start any time |
| Provider token counting (41.5) | None | Provider-level enhancement |
| Cost display (41.6) | Phase 31 UX improvements | Builds on existing usage tracking |
| Compaction monitoring (41.7) | Phase 40 compaction safety | Feeds into cycle detection |
| Streaming chunk granularity (41.8) | Phase 28.6 streaming | Cosmetic; low priority |
| Rate limit coordination (41.9) | None | Provider-level tuning |
| Streaming usage robustness (41.10) | None | Defensive guard; can start any time |

---

## Phase 51b: Team Sync — Shared Memory, Decisions, Attribution

**Goal:** Close the highest-leverage gaps for a small (2–5)
charm-authoring team without standing up a shared server.  Three
opt-in additions on top of Phase 42's existing GitHub workflow,
all file-based and git-tracked, all reversible by removing the
``.cantrip/shared/`` directory or flipping a setting back off.
See [`design/TEAM_COLLABORATION.md`](design/TEAM_COLLABORATION.md)
§5.1 for the rationale.

### 51b.1 Shared memory directory

- [x] Optional shared memory directory in the same Markdown-
  frontmatter format as global memory
  (``$XDG_CONFIG_HOME/cantrip/memory/``), committed to the repo
  alongside the charm.  Lives at
  ``<charm-root>/.cantrip-shared/memory/`` rather than the spec's
  ``<charm-root>/.cantrip/shared/memory/`` because
  ``<charm>/.cantrip`` is the SQLite session file (a single path
  cannot be both a file and a directory) — the rename has no
  other behavioural consequence.  New ``SharedMemoryStore`` in
  ``src/cantrip/agent/memory/core.py`` is a thin parameterisation
  of ``GlobalMemoryStore`` that stamps entries with
  ``scope="charm"`` and ``source="shared"``; a ``for_charm``
  classmethod resolves the conventional path under the charm
  root.
- [x] ``MemoryManager`` reads from local SQLite + the shared
  directory and merges (``list_entries``, ``read``, ``search``,
  ``render_prompt_index``).  Local SQLite wins on ``read`` so a
  teammate's just-pulled entry doesn't shadow a deliberately
  customised local copy; listings surface both rows so divergence
  is visible.  ``update`` and ``forget`` look in SQLite first
  then fall through to the shared directory so an operator can
  edit or delete a shared entry through the same tool surface.
- [x] Setting ``team_memory_writes: shared | local | ask`` (env
  var ``CANTRIP_TEAM_MEMORY_WRITES``) controls where new
  charm-scope writes land.  Default ``local`` preserves today's
  behaviour; ``shared`` routes to the directory; ``ask``
  delegates to a registered decider callback and falls back to
  ``local`` when no callback is configured (so an unwired TUI
  never silently drops writes).  An invalid env value falls back
  to the default with a warning so a typo never disables
  charm-scope writes.
- [x] Conflict policy: textual git merge.  Documented in
  ``docs/src/howto-team-sync.md`` ``{#conflicts}``: memory
  conflicts surface as standard git markers in the per-key
  Markdown file (one file per memory name, so "same key"
  reduces to "same file"); the JSONL decisions log is append-
  only and usually merges cleanly, with byte-coincident
  appends getting the standard markers; no in-app conflict UI
  — git's the reconciler.

### 51b.2 Shared decisions log

- [x] Optional ``<charm-root>/.cantrip-shared/decisions.jsonl``
  append-only log mirroring the per-session ``decisions`` table.
  Sibling-path convention matches 51b.1's ``.cantrip-shared/``
  layout to avoid the ``.cantrip``-as-SQLite-file collision.
  Helpers in ``src/cantrip/agent/state.py``:
  ``shared_decisions_path``, ``append_shared_decision`` (best-
  effort write that swallows OSError so a failed shared write
  never unwinds the in-memory record), and
  ``load_shared_decisions`` (skips malformed lines at DEBUG,
  flags every returned ``Decision`` with ``source="shared"``).
- [x] ``SessionStore.load_session()`` (``src/cantrip/agent/store.py``)
  reads decisions from SQLite and appends shared-log entries
  marked ``source="shared"`` whenever ``state.charm_path`` is
  set.  ``save_session`` skips shared-source rows so the JSONL
  file stays the canonical record and a save → load → save
  loop never duplicates a teammate's decision into local SQLite.
- [x] ``AgentState.add_decision()`` (``src/cantrip/agent/state.py``)
  appends to the shared file when
  ``CANTRIP_TEAM_DECISIONS_WRITES=shared`` and ``charm_path``
  is set; otherwise behaves exactly as before.  Reads always
  merge the shared log regardless of the write setting, so an
  operator who flipped to ``shared`` last week still sees
  teammates' decisions after toggling back to ``local``.
- [x] ``Decision.source`` field added
  (``src/cantrip/agent/state.py``); schema migration v14 adds
  the matching nullable column to the ``decisions`` table
  (``src/cantrip/agent/store.py``).  Pre-v14 rows load as
  ``"local"`` so existing decisions retain their meaning.

### 51b.3 Human co-author trailer

- [x] Auto-commit trailer (``src/cantrip/agent/auto_commit.py``)
  keeps the ``Co-Authored-By: Cantrip <noreply@aotearoa.dev>``
  line as a marker that the agent steered the commit, and
  *adds* a second ``Co-Authored-By:`` line built from
  ``git config user.name`` / ``git config user.email``.
- [x] When ``git config user.name`` / ``user.email`` is unset
  (or returns Cantrip's own canonical), skip the second trailer
  silently — no breakage for existing single-user setups.
- [x] Tests cover: both trailers present, only Cantrip trailer
  when git config absent, no duplication when git config matches
  Cantrip's canonical.

### 51b.4 Documentation

- [x] New ``docs/docs/howto-team-sync.html`` covers the three
  opt-in settings, the shared-directory format, the textual-git
  -merge conflict policy, and a worked two-operator example.
  Sidebar nav (``docs/src/_site.yaml``) and the docs landing
  page card grid both surface the new how-to.
- [x] Updates to ``docs/docs/howto-memory.html`` mention shared
  scope alongside charm and global, with a cross-link to the
  team-sync how-to and a ``see_also`` entry.
- [x] CHANGELOG entry under Unreleased.

**Exit criteria:** Three settings ship with sensible defaults
(all ``local`` / off — opt-in only).  ``make check`` passes.
Existing single-user installations see zero behavioural change.
Two-operator integration test exercises the shared-memory and
shared-decisions paths against a temp repo.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Shared memory (51b.1) | Phase 43 memory scopes | Adds a third scope alongside charm/global |
| Shared decisions (51b.2) | Phase 14 decisions log | Mirrors the existing per-session log |
| Co-author trailer (51b.3) | Phase 42 auto-commit | Extends the existing trailer assembly |
| Docs (51b.4) | All of the above | One how-to + cross-references |

---

## Phase 56: Publish Juju Copilot / Claude Code Assets

**Goal:** The awesome-copilot survey turned up zero Juju-specific
content across 307 skills, 177 instructions, and 204 agents — every
charm author using Copilot or Claude Code today gets generic
Python/YAML advice.  Cantrip already embeds the right knowledge in
its system prompt and skills bundle; lifting a subset into standalone
reusable assets (`*.instructions.md` scoped via `applyTo:`, plus
skill folders) is cheap and unlocks ecosystem-wide value independent
of Cantrip's own adoption curve.

The target publishing destination is **`canonical/skills`**
(not `awesome-copilot` upstream) — Canonical owns the narrative and
versioning, and the assets can reference each other without waiting
on upstream review cycles.

### 56.1 High — Scope the initial asset bundle

- [ ] Enumerate the slices of Cantrip's system prompt and skills most
  valuable as standalone assets: `charmcraft.yaml` authoring,
  `src/charm.py` patterns, Scenario testing (not Harness), Jubilant
  integration tests (not pytest-operator), ops-tracing integration,
  COS integration, relation-data design, the 12-factor / custom /
  infrastructure path split
- [ ] Decide per-slice whether it ships as an `.instructions.md`
  (applies to files matching a glob) or a skill folder (triggers on
  an explicit user ask): instructions for style/lint-adjacent rules,
  skills for multi-step processes like "migrate Harness to Scenario"
- [ ] Draft a manifest file (`README.md` + index) listing the
  bundle's contents, compatibility matrix, and versioning policy

### 56.2 High — Extract and repackage from Cantrip's system prompt

- [ ] For each instruction asset, extract the relevant block from
  `src/cantrip/agent/prompts/system.md.j2` (plus the skills under
  `src/cantrip/agent/skills/`) and rewrite for the standalone
  audience.  The Cantrip prompt assumes the autonomous-loop
  context; the published assets are read by humans and other agents
- [ ] Add YAML frontmatter matching awesome-copilot's conventions
  (`description`, `applyTo`, etc.) so the assets drop cleanly into
  any existing Copilot / Claude Code setup
- [ ] Keep a one-way-mirror convention: Cantrip's system prompt is
  the source of truth; the published assets are derived.  Document
  how they stay in sync (ideally a `make` target that regenerates
  the published bundle from the Jinja2 sources)

### 56.3 Medium — Publish to `canonical/skills`

- [ ] Create the repo structure under `canonical/skills`
  (or the existing bundle if it already exists; check before
  creating) — likely a `juju/` subdirectory to leave room for other
  Canonical domains (`lxd/`, `rockcraft/`, etc.)
- [ ] Land the initial asset bundle with a `README.md` explaining
  how to install into VS Code, JetBrains, and Claude Code
- [ ] Add a minimal CI job that validates frontmatter and glob syntax
  so broken assets don't ship
- [ ] Announce internally (Cantrip updates, charm-dev channels) so
  charm authors know the bundle exists

### 56.4 Low — Keep the bundle current

- [ ] Add a GitHub Action that opens a PR when Cantrip's system
  prompt or skill content changes in a way that affects the
  published bundle (a simple diff-on-push is probably enough)
- [ ] Periodic review cadence (quarterly?) to prune stale rules and
  add newly discovered charm idioms
- [ ] Track downstream reception: stars, forks, issues, PRs against
  the bundle — feeds back into Cantrip's own prompt quality

### What this phase is *not*

- Not a fork or rewrite of Cantrip's prompts.  The published bundle
  is a derivative, regenerated from Cantrip's source, not a parallel
  knowledge base to maintain.
- Not a commitment to upstream to `awesome-copilot` itself.  Canonical
  maintains control via `canonical/skills`; upstreaming
  to awesome-copilot is a possible future step, not part of this
  phase.
- Not Juju-specific IDE plugins or VS Code extensions.  Assets only —
  the installation story leans on existing Copilot / Claude Code
  mechanisms.

**Exit criteria:** `canonical/skills/juju/` (or the
agreed-on path) exists with at least six instruction / skill assets
covering the slices from 56.1.  A regeneration mechanism (ideally a
`make` target in Cantrip) keeps the bundle in sync with Cantrip's
own system prompt.  CI validates frontmatter on every PR.  The bundle
is announced to at least one charm-developer channel.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Scope (56.1) | none | Inventory pass; independent |
| Extract (56.2) | 56.1 | Needs the scope decided first |
| Publish (56.3) | 56.2 | Needs the content to publish |
| Maintain (56.4) | 56.3 | Only meaningful once the bundle exists |

---

## Phase 69: Kimi-Inspired Workflow Features — Ralph Loop, Shell Mode, Flow Skills, Yolo

**Goal:** Kimi Code CLI (MoonshotAI's Python-based terminal agent)
ships a handful of patterns the charm-authoring workflow stands
to benefit from.  Four stand out as distinct additions — not
already delivered, and not covered by Phase 67 (Pi) or Phase 68
(OpenCode) — that map cleanly onto Cantrip's existing event bus,
skill system, and autonomous loop.

Four candidates, in rough priority order:

1. **Ralph Loop — bounded iterate-until-green.**  Kimi's
   ``--max-ralph-iterations`` re-feeds the same prompt to the
   agent until it emits ``STOP`` (or the iteration cap trips),
   with convergence detection to stop when nothing's changing.
   Cantrip already has red/green TDD (Phase 12) and the
   autonomous work loop, but the *explicit bounded refinement*
   pattern — "keep building-and-testing this charm until
   ``make check`` is green and integration tests pass, capped
   at N iterations" — is not a first-class primitive.  Ralph
   Loop fits as an opt-in outer loop above the existing work
   queue.  Particularly useful in ``cantrip run --print``
   (Phase 67.3) unattended mode.
2. **``--yolo`` unattended-mode switch.**  Kimi's
   ``--yolo`` / ``--auto-approve`` / ``-y`` globally suppresses
   approval prompts for a session.  Cantrip has CONFIRM tasks
   (Phase 64) and the Phase 68.2 permission layer, but no
   single switch to say "this is a CI run, auto-approve
   anything that's not ``deny``."  Phase 67.3 already flags
   this as a gap for print mode; Phase 69 resolves it.
3. **Shell command mode (``Ctrl-X``).**  Kimi toggles the prompt
   into a direct shell mode with ``Ctrl-X``: users run
   ``juju status``, ``kubectl get pods``, ``git log`` without
   leaving the session.  Cantrip has a ``bash`` tool, but
   invoking it goes through the agent — slow and costs tokens
   for a read-only peek.  A direct shell toggle in the TUI
   chat input is a genuine UX win for charm authors who
   juggle ``juju`` / ``microk8s`` / ``charmcraft`` CLIs all
   day.
4. **Flow skills — declarative workflow diagrams.**  Kimi's
   Flow skills embed Mermaid or D2 diagrams with decision
   nodes that the agent traverses step-by-step.  Cantrip has
   a skill system (Phase 33, 50) and a planner (Phase 32) but
   no "this is the canonical diagram for this workflow,
   follow it."  Flow skills fit charm lifecycle shapes
   precisely: reactive→ops migration decision tree, COS
   enablement flow, relation-broken debug ladder, upgrade
   path A→B→C with rollback branches.  The diagram *is* the
   documentation.

Four Kimi features are explicitly **out of scope**:

- **VS Code extension and zsh plugin.**  Cantrip's interface
  strategy is TUI + Web UI (Phase 15).  An IDE extension is a
  separate product-shape decision, not a roadmap item for this
  phase.
- **ACP server mode (``kimi acp``).**  Phase 39 already tracks
  ACP as a research item.  Defer.
- **Plugin.json language-agnostic executable tools.**  Phase 45
  MCP already covers "tools outside the agent process via
  stdio".  Adding a second, parallel plugin protocol would
  fragment Cantrip's extension surface.
- **Okabe agent's ``SendDMail`` checkpoint rollback as an
  agent-invocable tool.**  Phase 68.1 already gives users
  ``/undo``; letting the agent rewind itself is a much more
  speculative loop-control question and belongs in a research
  phase if ever.

### 69.1 High — Ralph Loop: bounded iterate-until-green ✓

- [x] Added ``RalphConfig`` (frozen dataclass) carrying
  ``max_iterations`` and ``convergence_signal`` (default
  ``STOP``) plus an ``is_enabled()`` helper.  Kimi semantics:
  ``0`` disables (single-shot pass-through), ``-1`` is
  unlimited bounded by an internal safety ceiling of 200
  iterations, positive integers cap the run.  Lives in
  ``src/cantrip/agent/ralph.py`` and is constructed from
  ``state.ralph_max_iterations`` (new ``AgentState`` field).
- [x] Outer-loop integration via the new ``run_ralph()``
  coroutine: each iteration calls a caller-supplied
  ``MessageProcessor`` (typically ``agent.process_message``);
  iteration ``N>1`` re-seeds with a framed prompt that
  preserves the original user goal verbatim plus a truncated
  summary of iteration ``N-1``'s response (capped at 1500
  chars to keep the prompt bounded).  ``on_iteration``
  callback hook lets ``cantrip.print_mode`` drain the work
  queue and surface pending CONFIRM tasks between
  iterations — so a stuck confirmation aborts the loop
  cleanly via ``_RalphAbortError``.
- [x] Convergence detection: ``has_converged()`` matches the
  signal as a standalone line (``STOP\n``) *or* a whitespace-
  separated word — substring matches inside larger words
  (``STOPPED``) deliberately do not trigger.  Stall
  detection: ``_is_stalled()`` compares response signatures
  (SHA-256 of trimmed text, truncated to 16 hex chars) and
  working-tree signatures (``git rev-parse HEAD`` plus
  ``git status --porcelain=v1 -z``, hashed) across
  consecutive iterations.  When git is unavailable both
  tree sigs are ``None`` and stall detection falls back to
  response-only matching, which still trips on identical
  replies.  Hashing keeps memory bounded across long runs.
- [x] Wired into ``cantrip run --print`` as ``--ralph N`` on
  the run subparser, then through ``run_print`` →
  ``_run_async`` → ``_run_ralph_loop``.  Slash command
  ``/ralph [N|off]`` stamps the cap on
  ``state.ralph_max_iterations`` mid-session: bare reports
  current setting, ``off``/``0`` disables, ``-1`` is
  unlimited, anything else parses as an int (bad arguments
  return a usage line).  The TUI invocation is informational
  — the actual refinement loop fires only inside print mode,
  where there's no human to drive iteration manually.
- [x] Four new ``EventType`` entries +
  ``ralph_iteration_started`` / ``ralph_converged`` /
  ``ralph_stalled`` / ``ralph_exhausted`` factories on
  ``cantrip.ui.events``.  ``max_iterations`` is ``None`` in
  the iteration-started payload for unlimited runs so the
  TUI can render ``N/?`` instead of ``N/-1``.  Print mode's
  human-readable progress emitter renders each event as a
  short ``[ralph] iteration N/M`` / ``[ralph] converged at
  iteration N (signal: STOP)`` line; the JSON stream emits
  the full payload one event per line.
- [x] ``tests/unit/test_ralph_loop.py`` — 51 cases covering
  ``RalphConfig`` defaults, ``has_converged()`` matching
  rules (own line, standalone word, no substring inside
  word, custom signals with internal whitespace), happy-path
  convergence on iterations 1 / 3 / N, iteration-cap
  exhaustion (``EXHAUSTED`` outcome), stall detection (with
  and without git), re-seeding preserves the original goal
  verbatim plus iteration-N framing, lifecycle event
  emission per pass, ``on_iteration`` callback firing and
  abort-via-exception, ``_tree_signature`` for git repos
  (skip when git unavailable), every ``/ralph`` slash form
  (bare reports, positive cap, ``-1`` unlimited, ``off``,
  ``0``, bad arg returns usage), help-text and catalogue
  drift, print-mode integration through ``_run_async``
  (drives multiple iterations, exhaustion returns ``1``,
  stall returns ``1``), and ``--ralph`` argparse plumbing
  through ``main.parse_args``.
- [x] Documented in ``docs/docs/howto-ralph.html`` with the
  "when to use" framing, the convergence-signal matching
  rules, the stall-detection rationale, exit codes, the
  full prompt shape on iteration N, and a CI-composition
  example.  Added ``--ralph`` flag to the CLI reference,
  four new event types to the print-mode event schema
  table, a ``/ralph`` section to the slash-commands list,
  and updated every how-to sidebar + the docs index card.

### 69.2 High — ``/yolo`` and ``--yolo`` unattended mode ✓

- [x] ``--yolo`` / ``-y`` flag on ``cantrip run`` stamps
  ``state.yolo_mode = True`` before the executor starts; TUI,
  CLI, and Web surfaces all honour the argument.  On startup
  the flag is synced onto the freshly-built
  :class:`PermissionManager` so the first subagent sees
  ``ask`` decisions as auto-approvals.
- [x] ``/yolo`` slash command toggles mid-session; ``/yolo on``
  / ``/yolo off`` are the explicit forms scripts use and any
  other argument is rejected with a usage line.  The TUI
  status bar gains a ``-yolo-mode`` CSS class
  (``$error-darken-1``) plus a ``YOLO MODE — confirmations
  off`` badge, distinct from the ``$warning-darken-2`` plan
  tint.
- [x] ``PermissionManager.set_yolo`` / ``yolo_mode`` short-
  circuit ``request()`` to return ``True`` immediately when
  yolo is active, and resolves any already-pending asks to
  approved so subagents parked on a future don't stall the
  run.  ``deny`` rules still short-circuit upstream of the
  manager — yolo only flips the ``ask`` tier.
- [x] Every auto-approval fires a
  ``PERMISSION_AUTO_APPROVED`` event via the new
  ``permission_auto_approved`` factory + ``EventType`` entry.
  The agent's ``_forward_permission_auto_approved`` bridges
  the executor's manager callback onto the event bus, so the
  transcript and every surface see the rule that would
  otherwise have prompted.
- [x] Documented in ``docs/docs/howto-unattended.html`` (new
  page) with the CI-run rationale, the ``deny``-still-blocks
  escape hatch, and the interaction with permissions / plan
  mode.  Linked from every how-to sidebar, the docs index,
  and a new ``/yolo`` + ``--yolo`` section in
  ``docs/docs/reference-cli.html``.
- [x] ``tests/unit/test_yolo.py`` — 13 tests covering
  ``PermissionManager`` yolo behaviour (auto-approve,
  callback fanout, pending-future resolution, still-parks-
  when-off), the ``/yolo`` slash command (bare toggle,
  explicit ``on``/``off``, no-op, bad argument, event
  emission), ``help_text`` + catalogue drift, and the event
  factory payload.

### 69.3 Medium — Shell command mode

- [ ] ``Ctrl-X`` keybind on the chat input toggles between
  "send to agent" and "send to shell" mode.  The prompt
  glyph changes (``» `` → ``$ ``) and the input field gets
  a distinct border/colour.
- [ ] Shell-mode submissions run through the same subprocess
  machinery the ``bash`` tool uses (Phase 30, Phase 49
  sandboxing still applies) but bypass the agent: the output
  is streamed into the chat panel as a ``$ cmd`` /
  ``<output>`` block, *not* as a tool call, and is cheap — no
  tokens consumed.
- [ ] The shell-mode block is still captured in the
  transcript (Phase 14) so audit history is complete.
- [ ] ``$$ cmd`` incognito prefix (from Amp): even inside
  shell mode, a leading ``$$`` runs the command but marks
  its output as *excluded from agent context*.  The user and
  the transcript see the result; the LLM does not.  Use
  cases are charm-specific and real:
  ``$$ juju show-unit mycharm/0 --format json`` (databags
  with secrets), ``$$ kubectl get secret`` (credentials),
  ``$$ cat .env`` (local dev config).  Implementation: a
  per-block ``hidden_from_agent: true`` flag on the
  transcript event so downstream context-assembly skips it.
- [ ] Built-in shell features limited to what ``subprocess``
  can handle — match Kimi's stance and document that ``cd``,
  shell aliases, and shell variables are not supported.
  Users who need them should drop to an actual shell.
- [ ] TUI help (``?``) lists the ``Ctrl-X`` toggle, the
  ``$$`` incognito prefix, and their limits.

### 69.4 Medium — Flow skills

- [ ] Extend the skill frontmatter schema (Phase 33) with a
  ``type: flow`` variant.  Body contains a fenced Mermaid or
  D2 diagram plus per-node annotations in a standard comment
  format (``%% node id: description``) that the runtime
  can parse out.
- [ ] ``/flow:<name>`` slash command: loads the flow, seeds
  the agent with the diagram *and* the first node's
  instructions, and tracks current-node state as the agent
  progresses.  Decision nodes with multiple outgoing edges
  force the agent to pick a branch before continuing.
- [ ] Ship three charm-relevant flows as built-ins:
  - ``charm-reactive-to-ops`` — reactive→ops migration
    decision tree (already a Phase 33.2 skill — port)
  - ``charm-cos-enable`` — add COS observability to an
    existing charm (metrics, logs, dashboards, tracing)
  - ``charm-upgrade-ladder`` — SUPPORTED→DEPRECATED→REMOVED
    upgrade paths with rollback branches
- [ ] TUI renders the flow diagram in the right-panel skill
  pane (or a modal) with the active node highlighted.  The
  Web UI does the same via its Mermaid renderer.
- [ ] ``design/SKILLS.md`` gains a "Flow skills" section
  covering the frontmatter extension, diagram syntax, and the
  node-tracking protocol.
- [ ] ``tests/unit/test_flow_skills.py`` — diagram parse,
  branch selection, happy-path completion, aborted flow
  leaves a clean state.

### What this phase is *not*

- Not a new agent architecture.  Ralph Loop is an outer
  wrapper on the existing autonomous loop; it doesn't
  replace the work queue.
- Not a relaxation of the permission model.  ``--yolo``
  still respects ``deny`` rules; it toggles only the ``ask``
  tier.
- Not a full shell emulation.  69.3 is a convenience
  pass-through to ``subprocess``, not tmux-in-Cantrip.
- Not a redesign of the skill loader.  Flow skills extend
  the existing schema with one new ``type`` value; ordinary
  skills keep working unchanged.
- Not a VS Code / zsh / JetBrains integration.  Tracked
  elsewhere or explicitly out of scope.

**Exit criteria:** (a) ``cantrip run --print --ralph 5 "charm
this flask app"`` iterates up to five refinement passes,
stopping early on convergence or stall; (b) ``--yolo`` makes
a fresh session non-blocking for ``ask`` rules while still
enforcing ``deny``, with every auto-approval audited; (c)
pressing ``Ctrl-X`` in the TUI drops into a visually-distinct
shell mode whose output lands in the transcript but not the
token stream; (d) ``/flow:charm-cos-enable`` walks a user
through adding COS to a charm via a Mermaid diagram rendered
in the right panel, with node transitions observable in the
event bus.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Ralph Loop (69.1) | Phase 12 (red/green), Phase 40 (safe compaction), Phase 67.3 (print mode) | Outer-loop wrapper; land after 67.3 so unattended Ralph is possible |
| Yolo mode (69.2) | Phase 64 (CONFIRM), 68.2 (permissions) | Flips only the ``ask`` tier; ``deny`` remains authoritative |
| Shell mode (69.3) | Phase 30 (bash tool), Phase 49 (sandbox), Phase 14 (transcript capture) | UX-only on top of existing subprocess plumbing |
| Flow skills (69.4) | Phase 33 (skills), Phase 50 (skill interop), Phase 15 (Web UI Mermaid) | Schema extension + TUI/Web diagram rendering |

---

## Phase 72b: Read-Only Code Intelligence - Exact Symbols, Definitions, and References

**Goal:** Phase 71.1's repo-map gives the agent a bird's-eye view of a
repository, but BUILD/DEBUG work still drops to grep when the question
is exact: "where is ``Foo.bar`` defined?", "who calls
``_render_layer``?", "what symbols exist under ``src/charm.py``?".
This phase copies the useful *read-only* LSP affordances - workspace
symbols, go-to-definition, and find-references - without assuming an
IDE surface, a long-lived editor session, or any write-capable
refactors.

### 72b.1 High - Shared code-intelligence index and query API

- [ ] New subsystem under ``src/cantrip/codeintel/`` that *reuses* the
  Phase 71.1 parser outputs rather than growing a second parser stack.
  ``repomap`` stays the bird's-eye renderer; ``codeintel`` owns exact
  query operations and compact result rendering.
- [ ] Extend the parsed-symbol model with stable symbol identifiers
  (qualified name + kind + file + line), reference locations, import
  aliases where recoverable, and a small snippet window around each
  definition/reference.  Persist in ``.cantrip/codeintel.json`` keyed
  by ``mtime_ns`` so incremental rebuilds stay cheap.
- [ ] Language coverage starts deliberately narrow: Python source plus
  charm metadata YAML (``charmcraft.yaml``, ``metadata.yaml``,
  ``config.yaml``, ``actions.yaml``).  Rust, Go, shell, Terraform,
  and Markdown stay literal-search territory until a concrete need
  appears.
- [ ] Query primitives:
  - ``workspace_symbols(query, path_scope=None, kinds=None)``
  - ``go_to_definition(symbol, from_path=None)``
  - ``find_references(symbol, from_path=None, include_definition=False)``
- [ ] Match policy is deterministic: exact qualified-name match first,
  then unqualified exact, then prefix/fuzzy fallback.  Ambiguous hits
  are surfaced explicitly with candidates; the tool never silently
  guesses.

### 72b.2 High - Read-only tools, slash commands, and ``@`` providers

- [ ] Three explicit read-only tools:
  ``code_symbols``, ``code_definition``, and ``code_references``.
  Keep them separate rather than a single ``code_intel`` tool with a
  mode string so tool selection stays legible to the model.
- [ ] Slash-command surface:
  ``/symbols <query>``, ``/definition <symbol>``, and
  ``/references <symbol>``.  Output format mirrors the tool results so
  print mode, TUI, and Web all see the same content.
- [ ] ``@``-provider surface layered on Phase 72.2's parser:
  ``@symbol <query>``, ``@definition <symbol>``, and
  ``@references <symbol>`` as ``REST_OF_LINE`` providers.  Each
  expansion uses the existing fenced-block convention so the typed
  mention and substituted content both remain visible in the
  transcript.
- [ ] Result shapes stay compact and audit-friendly:
  ``code_symbols`` returns kind / file / line / signature;
  ``code_definition`` returns the defining path + line plus a bounded
  snippet; ``code_references`` returns sorted callsites/import sites
  with honest truncation and ambiguity notes.
- [ ] Every surface states whether the answer came from the semantic
  index or from a literal-search fallback so misses do not masquerade
  as precise code intelligence.

### 72b.3 Medium - Agent and planner adoption

- [ ] Primary-agent guidance and subagent prompts updated so the search
  order becomes: repo-map for orientation, code-intelligence for exact
  symbol questions, grep/glob for literal text or unsupported
  languages.
- [ ] Safe read-only access added to the BUILD, DEBUG, RESEARCH, and
  LIBRARIAN tool allowlists.  This is deliberately *not* a new write
  path and should inherit the existing "safe by default" governance
  treatment for read-only tools.
- [ ] When a task title or user message contains symbol-shaped tokens
  (dotted names, ``snake_case`` helpers, ``CamelCase`` classes), the
  planner may prefetch one compact definition or symbol-match block so
  a BUILD/DEBUG subagent starts from the right file instead of
  burning a turn on navigation.
- [ ] ``/map`` and repo-map remain unchanged in purpose: they answer
  "what matters in this repo?".  Code-intelligence answers "where is
  this symbol?" and "who references it?".  Prompt text should state
  that distinction plainly so the two systems complement rather than
  duplicate each other.

### 72b.4 Medium - Validation, limits, and future adapter seam

- [ ] ``tests/unit/test_codeintel.py`` plus provider/slash-command
  coverage for: exact match, ambiguous match, moved files, stale-cache
  invalidation, syntax-error tolerance, YAML-derived symbols,
  path-scoped lookups, truncated reference lists, and transcript-safe
  mention expansion.
- [ ] Hard scope boundary: no rename-symbol, no code actions, no
  format-on-save, no workspace edits, no hover UI, no always-on
  background daemon.  Read-only lookup only.
- [ ] Design the query layer so a future optional adapter can sit
  behind it if Cantrip later wants one-shot ``pyright`` or
  ``yaml-language-server`` enrichment for tricky cases.  That adapter
  is *not* in scope here; the seam is.
- [ ] Failure mode must be plain and non-magical: "no semantic match"
  or "multiple candidates" is a valid result.  The caller can then
  fall back to ``grep``/``glob`` explicitly.

### What this phase is *not*

- Not an IDE extension.  No autocomplete, cursor tracking, editor
  buffers, inline hovers, or live-LSP session.
- Not a refactoring engine.  Rename, extract, organise-imports, and
  code actions stay out of scope.
- Not a replacement for repo-map or grep.  Repo-map stays the
  repository overview; grep stays the universal text search; this
  phase fills the exact-symbol gap in between.
- Not a multi-language promise.  Python + charm YAML earn first-class
  support because that is where Cantrip already has parser knowledge.

**Exit criteria:** (a) ``/definition RepoMap.render_for_prompt``
returns the defining file, line, and a bounded snippet from the
current repo; (b) ``/references SubagentContext`` returns ranked
reference sites with honest ambiguity / truncation notes; (c) typing
``@definition RepoMap.render_for_prompt`` or
``@references SubagentContext`` expands inline in the TUI/Web input
path using the existing fenced-block transcript format; (d) when a
symbol cannot be resolved semantically, the result says so plainly
instead of inventing a target.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Shared index/query layer (72b.1) | 71.1 repo-map | Reuse the parser/cache work; do not fork a second symbol-extraction stack |
| Slash commands + ``@`` providers (72b.2) | 72.2 provider registry, Phase 61 autocomplete, Phase 67.3 print-mode parity | Same parser / suggestion / transcript path |
| Agent adoption (72b.3) | Phase 32 planner, Phase 80 policy stack | Safe read-only tool allowlisting plus selective prefetch |
| Optional future adapter seam (72b.4) | none | Keep the abstraction ready without committing this phase to live LSP |

---

## Phase 73: Goose-Inspired Workflow Packaging — Recipes, MCP Apps, Retry, Structured Output

**Goal:** Goose (Block's open-source agent, part of the Agentic
AI Foundation at the Linux Foundation) treats agent work as
*packageable*: a recipe is a YAML bundle of parameters,
extensions, settings, retry policy, and response schema that a
team can check in, share, and re-run.  A walk of the Goose
docs surfaces four patterns distinct from Phases 67–72 and
from what Cantrip already has.

Four candidates, in rough priority order:

1. **Recipes — parameterised, retryable, schema-enforced
   workflows.**  Goose's recipe YAML schema bundles
   ``parameters`` (typed: string/number/boolean/date/file/
   select, with required/optional/prompted requirement), a
   Jinja-templated ``instructions`` or ``prompt``, required
   ``extensions`` (MCP servers with ``available_tools``
   filtering), ``settings`` (model/temperature/max_turns),
   ``sub_recipes`` (composable nested invocations with value
   overrides, sequential or parallel), plus ``response``
   (JSON-schema-enforced output) and ``retry`` (max_retries,
   timeout, shell validators, on_failure hook).  Template
   inheritance via ``{% extends "parent.yaml" %}``.  Distinct
   from Phase 69.4 Flow skills (visual decision diagrams)
   and Phase 33 skills (knowledge bundles): a Recipe is a
   *parameterised repeatable execution* — "upgrade this
   charm from reactive to ops with ``charm_name=``,
   ``target_framework=ops>=2.16``, retry if tests fail, emit
   a validated JSON upgrade report."
2. **MCP Apps — interactive HTML UIs in the chat.**  A
   2026-01 MCP extension standard (now supported by Claude
   Desktop, VS Code Copilot, Goose, Postman, MCPJam): MCP
   servers can return HTML in a sandboxed iframe, rendered
   inline in the conversation.  Charm-relevant examples: a
   relation-databag inspector, a Pebble-layer visual
   editor, a bundle-topology graph, a COS dashboard-preview
   form.  Cantrip's Web UI (Phase 15) can host the iframe;
   the TUI falls back to a text link.  Makes complex
   configuration a form rather than a JSON blob.
3. **Structured JSON response with schema enforcement.**
   Goose's ``response: {json_schema: …}`` forces the final
   agent output into a validated JSON shape.  Independent of
   recipes, usable anywhere structure matters: planner
   briefings, acceptance-test reports (Phase 17), Phase 70.4
   Checks output, the oracle's reply (Phase 70.2).  Most
   modern providers support structured outputs natively;
   surfacing the primitive as a per-call option is the
   value.
4. **Declarative retry with shell validators.**  Goose's
   ``retry: { max_retries, timeout_seconds, checks: [{type:
   shell, command: …}], on_failure }`` lets a recipe (or
   any task) declare its own success predicate — a shell
   command that must exit zero — rather than trusting the
   agent's self-report.  Complements Phase 12 red/green
   (goal-level), Phase 69.1 Ralph Loop (outer per-goal),
   and Phase 71.4 per-edit lint: this is *per-task*,
   user-specified, and deterministic.

Five Goose features are explicitly **out of scope or
deferred**:

- **Rust rewrite of Cantrip's core.**  Goose's Rust
  implementation is a product-shape choice; Cantrip's
  Python/Rust split is already tuned for its own needs.
- **Desktop app as a parallel surface to TUI/Web.**
  Phase 15 Web UI plus the TUI cover Cantrip's interface
  matrix; adding a Tauri/Electron desktop is a separate
  decision.
- **Parallel subagent dispatch triggered by conversational
  keywords** ("parallel", "simultaneously").  Phase 44
  worktrees + Phase 32 planner already dispatch parallel
  work; the *keyword-as-trigger* UX is a small planner
  prompt tweak rather than a new subsystem.  Folding the
  idea into Phase 32 as a one-line prompt guidance note.
- **``.goosehints`` with keyword-tagged conditional retrieval.**
  Overlaps with Phase 70.3 glob-conditional guidance.
  Glob-on-paths is Cantrip's primary axis; keyword-tagged
  retrieval would be a second axis with questionable
  marginal value.  Skip unless users ask for tag-based
  filtering specifically.
- **ACP bidirectional (Goose as client of Claude Code /
  Codex).**  Phase 39 covers ACP research.

### 73.1 High — Recipes: parameterised repeatable workflows

- [ ] Recipe schema in ``.cantrip/recipes/*.yaml`` (repo) and
  ``~/.config/cantrip/recipes/*.yaml`` (user).  Top-level
  fields: ``version``, ``title``, ``description``,
  ``parameters`` (list), ``instructions`` (Jinja-templated
  prompt), ``settings`` (provider/model/temperature/
  max_turns, all optional — inherit session defaults),
  ``extensions`` (list of required MCP servers or Phase 30
  tool names), ``response`` (see 73.3), ``retry`` (see
  73.4), ``sub_recipes`` (list of nested invocations).
- [ ] Parameter types: ``string``, ``number``, ``boolean``,
  ``date``, ``file``, ``select`` (with ``options``).
  Requirement: ``required`` / ``optional`` / ``prompted``
  (interactive ask-at-invocation).  Defaults supported.
- [ ] Invocation surface: ``/recipe <name> [key=value …]``
  slash command.  Unknown required params trigger an
  interactive prompt (or fail with a clear list in print
  mode, Phase 67.3).  Sub-recipes invoke the same way from
  within a parent's template.
- [ ] Sub-recipes support ``sequential_when_repeated`` like
  Goose; default is parallel when the parent runs them in a
  loop, sequential when invoked once.  Uses Phase 44
  worktree dispatch for parallel sub-recipes.
- [ ] Template engine: reuse Cantrip's existing Jinja2
  integration (Phase 32 planner / Phase 53 prompt templates)
  with the same template-injection guard.  ``{{
  recipe_dir }}`` and the parent's scope available.
- [ ] Ship three charm-relevant built-in recipes:
  - ``charm-new`` — parameterised "create a new charm for
    workload X" wrapping the Phase 1 research→scaffold flow
  - ``charm-cos-add`` — adds COS observability to an
    existing charm
  - ``charm-reactive-to-ops`` — upgrades a reactive charm
    to ops (overlaps with Phase 69.4 Flow skill; they
    compose — the Flow diagram is the decision tree,
    the Recipe is the parameterised execution)
- [ ] Document in ``docs/docs/howto-recipes.html`` and
  ``design/RECIPES.md`` (new — recipe schema reference,
  authoring guide, worked examples).
- [ ] ``tests/unit/test_recipes.py`` — schema parse,
  parameter validation, template expansion (including
  escape sequences), sub-recipe invocation, interactive-
  prompt path, failure on missing required param.

### 73.2 Medium — MCP Apps: interactive HTML in the chat

- [ ] Adopt the MCP Apps extension spec
  (``modelcontextprotocol.io/extensions/apps/overview``) in
  Cantrip's MCP client (Phase 45).  When a tool result
  includes an ``ui`` block with ``mime: text/html``, route
  it to the UI layer as an app-render event.
- [ ] Web UI (Phase 15) renders the HTML in a sandboxed
  iframe with ``sandbox="allow-scripts allow-forms"`` (no
  ``allow-same-origin`` — must communicate only via
  ``postMessage``).  Size constraints, no parent-DOM
  access, no cookie/storage access — match the MCP Apps
  security model verbatim.
- [ ] ``postMessage`` bridge: the app can emit structured
  events (``{type: 'tool_call', name, arguments}``) that
  Cantrip routes back through the agent's tool pipeline
  (with the Phase 68.2 permission layer gating them
  normally).  App events are audited in the transcript.
- [ ] TUI fallback: an MCP-App tool result renders as a
  one-line summary (``[MCP App: <title>; open in web UI
  at <url>]``) plus the text-form of any fallback content
  the server provides.
- [ ] Document one worked example — a "pebble-layer
  editor" MCP server (out of tree, reference only) that
  takes a layer YAML, renders a form in the Web UI, and
  returns the edited YAML.  Belongs in
  ``docs/docs/explanation-mcp-apps.html``.
- [ ] ``tests/unit/test_mcp_apps.py`` — sandbox attrs
  correct, postMessage round-trip, permission gate
  applied to emitted tool calls, TUI fallback.

### 73.3 Medium — Structured JSON response with schema enforcement

- [x] New per-call ``response_schema: dict | None``
  parameter on every ``LLMProvider.complete()`` /
  ``.stream()``.  Gemini routes it into
  ``response_mime_type=application/json`` +
  ``response_schema`` on ``GenerateContentConfig``;
  OpenAI-compatible endpoints (Fireworks, OpenRouter,
  vLLM, inference-snap) wrap it in the ``response_format``
  ``json_schema`` envelope (``{name, schema, strict}``);
  Anthropic accepts the kwarg for interface parity but
  doesn't enforce — they have no ``response_format``
  analogue today.  ``provider.supports_response_schema``
  surfaces the native-vs-caller-side distinction.
  Validation runs in Cantrip regardless via
  :mod:`cantrip.llm.structured`, so the contract is the
  same on every backend.
- [x] Four built-in schemas in
  :mod:`cantrip.llm.schemas` (``PLANNER_BRIEFING``,
  ``ORACLE_ANSWER``, ``CHECK_RESULT``,
  ``ACCEPTANCE_REPORT``) plus a ``BUILTIN_SCHEMAS``
  registry for name-driven lookup (recipes, settings).
  Each schema is a plain ``dict`` matching JSON Schema
  draft 2020-12 — no Pydantic, no DSL, same surface
  every provider already accepts.
- [ ] **Deferred: migrate existing call sites onto the new
  primitive.**  The planner (Phase 32) still parses
  free-form JSON via regex + ``json.loads``; the oracle
  (Phase 70.2) returns text; the acceptance tool (Phase
  17) takes pre-assembled markdown rather than synthesising
  a structured payload.  Each migration is its own commit
  — call this out when those phases get follow-up work.
  The primitive is available; consumers adopt at their
  own pace.
- [x] On validation failure, the
  :func:`complete_structured` helper appends the malformed
  reply as an ASSISTANT turn and a USER turn quoting the
  schema + the validation error, then retries up to
  ``retries`` times (default ``1``).  Final failure raises
  ``StructuredOutputError`` carrying the *last* raw text,
  the schema, and the underlying parser/validator
  exception.
- [x] Documented in
  ``docs/docs/reference-response-schemas.html`` (new
  Reference page) covering when to use a schema, the four
  built-ins, the provider matrix, the
  ``complete_structured`` entry point, and the validation
  + retry semantics.
- [x] ``tests/unit/test_structured_response.py`` (35 cases)
  — happy path, markdown-fence stripping, JSON parse
  failures, schema-violation triggers one retry with
  corrective prompt, final failure surfaces the last
  attempt's raw text, ``retries=0`` and negative-retry
  guards, ``response_schema`` forwarded to the provider,
  OpenAI-compat builds the correct ``response_format``
  envelope (with title-derived ``name``), Gemini and
  Fireworks claim native support while Anthropic does not,
  every built-in schema accepts a canonical sample payload
  and rejects an obvious violation.

### 73.4 Medium — Declarative retry with shell validators

- [ ] Retry block schema, usable inside recipes (73.1) and
  standalone on ``/task`` invocations:
  ```
  retry:
    max_retries: 3
    timeout_seconds: 600
    checks:
      - type: shell
        command: "uv run pytest tests/unit -q"
      - type: file_exists
        path: "src/charm.py"
    on_failure: "echo 'rolled back'"
  ```
- [ ] Check types: ``shell`` (command runs, exit 0 = pass),
  ``file_exists`` (path check), ``json_schema`` (apply
  73.3 to the task's final output).  Extensible — register
  new check types via Phase 46 hooks.
- [ ] Retry semantics: after the task completes, run
  ``checks``.  If all pass → done.  If any fail → increment
  retry count, re-run the task with the previous failure
  summary prepended to context, until ``max_retries`` or
  ``timeout_seconds`` exhausted.  ``on_failure`` shell
  command runs once on final failure for cleanup.
- [ ] Checks run through the Phase 68.2 permission layer,
  Phase 49 sandbox, and Phase 69.3 shell-mode subprocess
  plumbing — not a new execution path.
- [ ] Distinct from Phase 69.1 Ralph Loop: Ralph is "keep
  iterating the goal until the *agent* says STOP", 73.4
  is "keep iterating this task until *my shell command*
  says yes".  User-specified success predicate.
- [ ] ``tests/unit/test_declarative_retry.py`` — check
  types, retry count, timeout trip, on_failure runs on
  final failure only, permission gate respected.

### What this phase is *not*

- Not a second UI.  Desktop app, Rust rewrite, parallel
  dispatch keywords — all out of scope or already covered.
- Not a replacement for Phase 69.4 Flow skills.  Flows are
  visual decision trees; Recipes are parameterised
  execution bundles.  They compose.
- Not a plugin runtime.  MCP Apps (73.2) renders an HTML
  payload from an existing MCP server — no new plugin
  protocol, no Python-side sandboxing, no JS runtime
  inside Cantrip.
- Not a generic structured-output framework with
  Pydantic/attrs bindings.  73.3 uses plain dict JSON
  schemas — same surface as the provider APIs we already
  call.
- Not ``.goosehints``.  Phase 70.3 already covers the
  "conditional guidance" axis on file globs; keyword
  tagging doesn't earn a second mechanism.

**Exit criteria:** (a) ``/recipe charm-cos-add
charm_name=myapp metrics_endpoint=/metrics`` runs a
parameterised workflow with validated JSON output and
retries on Jubilant test failure; (b) an MCP server
returning an ``ui: text/html`` block renders as an
interactive form in the Web UI with postMessage-bridged
tool calls audited in the transcript; (c) Phase 70.4
Check output is JSON-schema-validated before aggregation,
with a documented malformed-output retry path; (d) a
recipe's ``retry.checks: [{type: shell, command: "uv run
pytest tests/unit -q"}]`` drives the task to convergence
on a user-specified predicate, distinct from Ralph Loop.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Recipes (73.1) | Phase 32 (Jinja templates), Phase 33 (skill-adjacent discovery), Phase 44 (worktree dispatch for sub-recipes), 73.3/73.4 (response and retry blocks) | Largest item; recipes compose 73.3 and 73.4 |
| MCP Apps (73.2) | Phase 45 (MCP client), Phase 15 (Web UI), Phase 68.2 (permission gate on app-emitted tool calls) | Follows the MCP Apps spec verbatim; no Cantrip extensions to the protocol |
| Structured response (73.3) | Phase 27, 41 (multi-provider) | Provider-call option; can land standalone, consumed by 73.1 and 70.4 |
| Declarative retry (73.4) | Phase 49 (sandbox), Phase 68.2 (permission gate on check commands), Phase 69.3 (subprocess plumbing) | Standalone; consumed by 73.1 |

---

## Phase 79: Per-Provider Eval Gate for System-Prompt Changes

**Goal:** Replace today's static gold-standard scoring with an
eval harness that actually exercises each supported LLM
provider, so that system-prompt changes are gated on
behavioural regression across the provider matrix.  Anthropic's
April 23 postmortem attributes a 3% quality drop to a prompt
tweak ("Keep text between tool calls to ≤25 words.") that their
narrow initial eval missed — their remediation is to run
*per-model* evals on every prompt change.  Cantrip's eval suite
has the same gap, only wider.

### 79.1 Current state audit (already done)

The eval runner at ``tests/eval/runner.py`` scores hand-written
charm directories against YAML rubrics (``spec.yaml``).  It
does **not** call any LLM.  The ``--provider`` flag is
descriptive metadata only — no dispatch.  Only one gold dir
exists (``tests/eval/charms/ntfy/gold-claude``).  ``make eval``
runs ``pytest tests/eval -v``; the suite is **not** in CI
(``.github/workflows/ci.yaml:81-86`` only runs
``tests/unit`` + ``tests/integration``).  The unit tests at
``tests/unit/test_system_prompt.py`` cover Jinja2 template
rendering and character-count thresholds — adding "Keep
responses under 100 words" to ``src/cantrip/agent/prompts/
system.py`` would pass every existing test.

### 79.2 Add an LLM-in-loop prompt smoke test

Not a full charm generation — a lightweight per-provider
sanity check that can run on every prompt change.

- [x] New ``tests/eval/test_system_prompt_smoke.py`` renders the
  shipped ``cantrip.agent.prompts.system.build_system_prompt()``,
  sends it as the system role with a fixed user prompt to each
  configured provider, and asserts two shape invariants:
  (1) given a ``read_file`` tool and a question that obviously
  needs file content, the response must contain a ``read_file``
  tool call; (2) given a bare greeting, the response must be non-
  empty (or include tool calls) — catches the 4xx-eaten-by-the-
  adapter / template-breakage failure mode that the static gold-
  standard scorer cannot see.
- [x] Matrix covers Claude (``ANTHROPIC_API_KEY``), Gemini
  (``GEMINI_API_KEY``), and two open-weights surfaces — Fireworks
  with Kimi K2 default (``FIREWORKS_API_KEY``) and OpenRouter with
  GPT-4o default (``OPENROUTER_API_KEY``).  Each provider runs at
  its default model so the smoke test exercises what a user
  actually gets without bespoke configuration.
- [x] ``pytest.param`` + per-provider ``pytest.mark.skipif`` on the
  env var means absent keys skip cleanly rather than fail.
  ``make check`` is unaffected (it runs ``tests/unit`` only); the
  eval suite under ``make eval`` skips the eight smoke cases
  without keys, runs them with keys.

### 79.3 Gate in CI against a cheap model

- [x] New ``.github/workflows/prompt-smoke.yaml`` job runs the
  79.2 smoke test on every PR that touches
  ``src/cantrip/agent/prompts/**`` or the smoke-test file
  itself.  Scoped to OpenRouter with ``openai/gpt-4o-mini``
  via ``CANTRIP_SMOKE_OPENROUTER_MODEL`` to keep cost bounded;
  the other provider keys stay unset so only the OpenRouter
  slice of the matrix runs in CI.  Fork PRs are skipped (they
  cannot read repo secrets) rather than show a misleading
  green check.  ``src/cantrip/agent/planner/`` does not have a
  ``templates/`` directory in the current layout — the path
  reference in the original phase note pre-dated the planner
  refactor; the smoke gate covers the actual planner-prompt
  surface via ``src/cantrip/agent/prompts/planning/``,
  ``src/cantrip/agent/prompts/tasks/``, and
  ``src/cantrip/agent/prompts/subagent/`` under the prompts
  path.
- [x] ``timeout-minutes: 5`` bounds wall-clock cost so a hung
  provider call cannot burn a full job budget; pytest exits
  non-zero on any test failure or provider 4xx, so a broken
  prompt template (Jinja2 error → import-time crash; provider
  rejects system content → ``ProviderError``; model fails the
  shape invariant → assertion error) surfaces as a red check
  in well under a minute.

### 79.4 Per-provider full-eval run (nice-to-have)

- [ ] Extend ``tests/eval/runner.py`` so ``score --provider
  X`` actually uses provider ``X`` to *generate* the charm
  before scoring, rather than scoring a pre-baked directory.
- [ ] Add ``gold-gemini`` and ``gold-fireworks`` baseline
  directories over time as each provider passes.
- [ ] Document the end-to-end loop in
  ``docs/src/howto-eval.md`` (new).

### 79.5 Prompt ablation harness (stretch)

- [ ] Tool that takes ``system.py``, drops each labelled
  section in turn, reruns 79.2, and reports score deltas.
  Lets a human author reason about which sections pull their
  weight before a prompt change lands — matches Anthropic's
  "continue ablations to understand the impact of each line"
  remediation.

**Exit criteria:**

- System-prompt changes have a per-provider regression guard.
- CI fails when a prompt edit breaks response shape on the
  cheap-model smoke test.
- At least 79.2 + 79.3 ship.  79.4 / 79.5 can land later.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| 79.2 | None | Additive tests + provider keys from CI secrets |
| 79.3 | 79.2 | Needs the test runner first |
| 79.4 | 79.2 | Bigger lift — touches the runner, not just new tests |
| 79.5 | 79.2 | Stretch; nice-to-have |

**Discovered:** Reviewing Anthropic's April 23 Claude Code
postmortem (2026-04-24).  Code audit of ``tests/eval/`` against
the current ``main`` branch confirmed the harness scores static
files only and does not dispatch on provider.

---

## Phase 84: Deferred-Item Sweep — Catalogue and Re-evaluate

**Goal:** Roadmap and archive both accumulate explicit deferrals —
sub-phases or sub-tasks shipped *minus* a piece that was scoped
out with a "revisit when…" condition.  Recent examples that
prompted this phase:

- 67.1 — Amp-style ``@@`` prior-session picker (waiting on a
  session registry that doesn't exist).
- 67.2 — TUI hotkey + favourites cycling for ``/model``
  (waiting on a concrete ergonomic case).
- 71.4 — ``pytest --collect-only`` on touched files
  (waiting on a different scope decision).
- 73.x — migrate existing call sites onto the new structured-
  output API.
- Multiple archived phases ("deferred to a follow-up", "needs
  in-loop integration", etc.) where the revisit trigger was
  recorded but no scheduled re-read of the trigger was set up.

Without a recurring sweep, deferrals turn into forgotten todos.
This phase exists so we have a place to (re-)check them.

### 84.1 Build the deferred-item index ✓

- [x] Grepped ``ROADMAP.md`` and ``ROADMAP_ARCHIVE.md`` for the
  explicit-deferral markers (``Deferred:``, ``defer pending``,
  ``revisit when``, ``re-open when``, ``deferred follow-up``,
  ``follow-up phase``).  Fourteen distinct deferrals captured —
  eleven in the active roadmap (Phases 67.1, 67.2, 70.1×2, 70.2×2,
  70.5×3, 71.4, 73.3) and three in the archive (Phases 48.5, 49.3,
  55.4).
- [x] Catalogue saved as ``design/DEFERRED.md`` — flat table with
  *Phase / Sub-task*, *What was deferred*, *Revisit trigger*,
  *Status*, *Notes* columns.  One row per deferral.  Sweep
  procedure documented at the foot of the file so the next pass
  reads off the same instructions.

### 84.2 Re-evaluate each deferral ✓ (2026-04-26 pass)

- [x] Re-evaluated every row in ``design/DEFERRED.md`` for the
  2026-04-26 pass.  All fourteen deferrals are **not fired**: no
  trigger has happened since the original deferral landed.  No
  rows moved to "Resolved" or "Dropped".
- [x] Audit date stamped on ``design/DEFERRED.md`` (2026-04-26)
  with the next due date (2026-07-26) so the next sweep knows
  what it's looking back over.

### 84.3 Schedule the next sweep

- [ ] Quarterly cadence picked and recorded in ``design/
  DEFERRED.md``; next sweep due **2026-07-26**.  Use ``/schedule``
  to set a background-agent reminder rather than relying on
  someone to remember — left to the user to launch since
  ``/schedule`` is a user-triggered surface.

### What this phase is *not*

- Not a place to *do* the deferred work.  84.2's "trigger
  fired" bucket opens a follow-up phase or task; the actual
  implementation lands in that phase, not here.
- Not a vehicle for re-litigating *closed* phases.  If a phase
  shipped with an exit decision ("ship", "defer", "drop"), the
  decision stands until evidence appears that the world
  changed.  The sweep records evidence; it does not relitigate.
- Not a documentation rewrite.  ``design/DEFERRED.md`` is a
  flat audit log, not a narrative.

**Exit criteria (per pass):** ``design/DEFERRED.md`` is
up-to-date with the current set of deferrals, every row is
labelled fired / not-fired / dropped, and any "fired" rows have
a concrete follow-up phase or task linked.  The next sweep date
is on the calendar.

**Discovered:** While closing Phase 67.1 the ``@@`` prior-
session picker was marked deferred pending a session registry.
Skimming ``ROADMAP_ARCHIVE.md`` afterwards turned up dozens of
similar deferrals scattered across phases without a re-read
plan — e.g. observability pieces in Phase 41, decisions in
Phase 73, scope cuts in Phase 71.  Without a periodic sweep
those deferrals would silently rot into todos no one
remembers.

---

## Phase 85: Structure and Style Sweep — Tame the Giants, Mirror the Layout

**Goal:** A mid-2026 structure review found that the package
spine is sound — `llm/`, `mcp/`, `repomap/`, `tui/`, `web/`,
`agent/tools/`, `agent/planner/`, `agent/prompts/` are all
intentional cuts and `__init__.py` files stay empty (no
implicit re-exports).  But several modules have grown into
load-bearing giants: `agent/core.py` is a 3 379-line god class
holding `CantripAgent` with 21 properties and ~90 methods;
`tui/app.py` is 1 859 lines of `CantripApp`; `agent/tools/
publishing.py` ships a 502-line `generate_docs_scaffold`
function that builds a docs tree by f-string concatenation;
`main.py:parse_args` is one 452-line block.  Meanwhile
`agent/` has accumulated 47 flat modules with obvious families
that want subpackages (memory, commands, triage, persistence)
and `tests/unit/` keeps 167 test files at one flat level
despite `src/` being well-nested.  Style adherence is close —
no `Optional[X]`, no US spellings, almost no TODOs — but two
small drifts have crept in (`from pathlib import Path` is
split 51/27 against `import pathlib`, four `except Exception`
clauses lack the rationale comment the others carry).  This
phase picks the right things off in the right order: cheap
sweeps first, mechanical folder moves next, behaviour-changing
decomposition last.

### 85.1 Sweep — close the small style drifts ✓

- [x] Replaced `from datetime import datetime` at
  `src/cantrip/tui/widgets/chat.py:6` with `import datetime` and
  updated the two call sites (`Message.timestamp` default factory
  and the chat-leaked-traceback writer).  No remaining
  `from datetime import datetime` in `src/cantrip/`.
- [x] Added `# noqa: BLE001 — <reason>` rationale comments to the
  four bare `except Exception` clauses flagged in the audit:
  `src/cantrip/hooks.py:845` (telemetry must not abort the agent),
  `src/cantrip/agent/github_issues.py:354` (background triage loop
  absorbs per-pass errors), `src/cantrip/agent/core.py:903`
  (compaction failure falls through to emergency truncate), and
  `src/cantrip/agent/executor.py:772` (executor loop tracks
  consecutive errors via the existing counter).  All other
  `except Exception` sites in `src/cantrip/` already carried the
  pattern.
- [x] Path / dataclass policy: option (b) — committed to
  module-only imports and codemodded the codebase.  All
  `from pathlib import Path` and `from dataclasses import …`
  runtime imports across `src/cantrip/` and `tests/` were
  rewritten to `import pathlib` / `import dataclasses` with
  qualified call sites (`pathlib.Path(...)`,
  `@dataclasses.dataclass`, `dataclasses.field(...)`).  The
  AGENTS.md rule stands as written; no carve-out needed.  One
  occurrence in `tests/e2e/seeds.py` is intentionally retained
  inside a string literal (Django `settings.py` fixture
  content).

### 85.2 Move — `agent/memory/` subpackage ✓

- [x] Converted the four-file memory family into a subpackage:
  `agent/memory.py` → `agent/memory/core.py`;
  `agent/memory_writer.py` → `agent/memory/writer.py`;
  `agent/memory_export.py` → `agent/memory/export.py`;
  `agent/memory_commands.py` → `agent/memory/commands.py`.
- [x] Re-exported the public surface — `MemoryEntry`,
  `MemoryManager`, `MemoryScopeError`, `GlobalMemoryStore`,
  `VALID_KINDS`/`VALID_STATUSES`, `slugify_title`,
  `sha_for_range`, `validate_citation`, citation/sweep
  dataclasses, plus the writer entry points
  (`AutoWriter`, `TriggerKind`, `WriteMemoryContext`,
  `collect_file_citations`) used by `agent/core.py` — from
  `agent/memory/__init__.py`.  External `from
  cantrip.agent.memory import …` lines are unchanged; only
  sites referencing `memory_writer`/`memory_export`/
  `memory_commands` move by one path segment.
- [x] Moved `tests/unit/test_memory*.py` (4 files) into
  `tests/unit/agent/memory/` (`test_core.py`, `test_writer.py`,
  `test_export.py`, `test_commands.py`) with `__init__.py`
  scaffolding, and updated their submodule imports.
- [x] `make check` (lint + ty + ruff format) and `make unit`
  (6 194 passed, 8 skipped) both green.

### 85.3 Move — `agent/commands/` subpackage ✓

- [x] Grouped the slash-command handlers into one folder:
  `agent/slash_commands.py` → `agent/commands/slash.py`;
  `agent/custom_commands.py` → `agent/commands/custom.py`;
  `agent/mcp_commands.py` → `agent/commands/mcp.py`.
  `agent/memory_commands.py` stayed in the memory subpackage
  (`agent/memory/commands.py`) per 85.2.  Re-exports from
  `agent/commands/__init__.py` keep `dispatch`, `SlashResult`,
  `CommandInfo`, `COMMAND_CATALOGUE`, `catalogue_for`, and
  `TreeNode` reachable from one entry point.
- [x] Split the bigger handler clusters out of `commands/slash.py`
  (was 2 174 lines after the rename):
  `commands/budget.py` (104 lines — ``/budget``),
  `commands/cost.py` (140 lines — ``/cost``),
  `commands/map.py` (138 lines — ``/map`` / ``/map-refresh``),
  `commands/share.py` (116 lines — gist upload helper for
  ``/share``; the dispatcher's ``SlashResult`` wrapper stays in
  `slash.py`), and `commands/transcript.py` (83 lines —
  ``/export``).  `slash.py` is now 1 671 lines; remaining
  handlers (help, undo/redo, branch/tree, plan/build, architect,
  auto-commit, yolo, ralph, review, diagnostics, copy,
  search-charms, icon, update, model, share-wrapper) stay
  alongside the dispatcher.

### 85.4 Decompose — `CantripAgent` god class

- [x] Extract one cohort at a time as a delegate object held
  by `CantripAgent`.  The seven natural cohorts (with rough
  line ranges in `agent/core.py`):
  1. ✓ **MCP lifecycle** — extracted to
     `agent/mcp_controller.py` as `MCPController`, held on
     `CantripAgent` as `self._mcp`.  Public surface unchanged:
     `mcp_registry`, `mcp_marketplace_sources`,
     `mcp_marketplace_loader`, `start_mcp`,
     `complete_mcp_elicitation`, `stop_mcp` (and the
     `_on_mcp_elicitation` test hook) stay as one-line
     delegators.  `_build_tools` reads the cached registry via
     `self._mcp.registry_if_loaded()` so the lazy "expose
     servers only after `start`" behaviour holds.  Test patches
     of `cantrip.agent.core.{MCPRegistry,MarketplaceLoader,
     load_mcp_configs,load_marketplace_sources}` retargeted to
     `cantrip.agent.mcp_controller.<name>`; tests injecting
     `agent._mcp_registry_cache` / `_mcp_started` retargeted to
     `agent._mcp._registry_cache` / `_started`.  Pure refactor —
     `make check` and `make unit` (6 412 passed, 8 skipped)
     green.
  2. ✓ **Executor lifecycle** — extracted to
     `agent/executor_controller.py` as `ExecutorController`, held
     on `CantripAgent` as `self._executor_ctl`.  Public surface
     unchanged: `executor_running`, `start_executor`,
     `stop_executor` stay as one-line delegators;
     `_pause_executor` / `_resume_executor` delegate likewise.
     The six callback closures (`_notify_bus`,
     `_purge_task_checkpoints`, `_forward_subagent_tool_invoked`,
     `_forward_subagent_tool_invoked_pending`,
     `_forward_budget_exceeded`, `_forward_rate_limited`) and
     `_forward_permission_auto_approved` moved wholesale.  Test
     patches of `cantrip.agent.core.BackgroundExecutor`
     retargeted to `cantrip.agent.executor_controller.
     BackgroundExecutor`; tests injecting `agent._executor`
     retargeted to `agent._executor_ctl._executor`.  Fixed a
     pre-existing bug in `/yolo` where `getattr(agent,
     "executor")` never resolved — now accesses
     `_executor_ctl.set_yolo()`.  Pure refactor — `make check`
     and `make unit` (6 412 passed, 8 skipped) green.
  3. ✓ **Watcher lifecycle** — extracted to
     `agent/watcher_controller.py` as `WatcherController`, held
     on `CantripAgent` as `self._watcher_ctl`.  Public surface
     unchanged: `watcher_running`, `start_watcher`,
     `stop_watcher`, `route_watcher_event`,
     `process_watcher_event` stay as one-line delegators.
     `latest_status` / `latest_cos_status` properties added to
     the controller so TUI code (`tui/actions/screens.py`,
     `tui/actions/watcher.py`) no longer reaches into the
     private `_watcher` instance.  Test patches of
     `cantrip.agent.core.{detect_current_juju_model,
     detect_cos_juju_model,juju_model_substrate}` retargeted to
     `cantrip.agent.watcher_controller.<name>`; tests injecting
     `agent._watcher._enqueue` retargeted to
     `agent._watcher_ctl._watcher._enqueue`.  Pure refactor —
     `make check` and `make unit` (6 412 passed, 8 skipped)
     green.
  4. ✓ **Issue triage** — extracted to
     `agent/triage_controller.py` as `TriageController`, held
     on `CantripAgent` as `self._triage_ctl`.  Public surface
     unchanged: `issue_triage_running`, `start_issue_triage`,
     `stop_issue_triage`, `retriage_issues`, `comment_on_issue`,
     `check_upstream` stay as one-line delegators.  Test patches
     of `cantrip.agent.core.{IssueTriage,gh_issue_comment,
     check_upstream_diverged}` retargeted to
     `cantrip.agent.triage_controller.<name>`; tests injecting
     `agent._issue_triage` retargeted to
     `agent._triage_ctl._issue_triage`.  Pure refactor —
     `make check` and `make unit` (6 412 passed, 8 skipped)
     green.
  5. ✓ **Arena** — extracted to
     `agent/arena_controller.py` as `ArenaController`, held on
     `CantripAgent` as `self._arena_ctl`.  Public surface
     unchanged: `active_arena`, `begin_arena`,
     `handle_arena_pick` stay as one-line delegators.  No test
     patches needed — arena tests target the `arena` module
     directly.  Pure refactor — `make check` and `make unit`
     (6 412 passed, 8 skipped) green.
  6. ✓ **Confirmations router** — extracted to
     `agent/confirmations.py` as `ConfirmationsController`, held
     on `CantripAgent` as `self._confirmations`.  Public surface
     unchanged: `handle_race_confirmation`,
     `handle_push_confirmation`, `handle_pr_creation`,
     `handle_repo_bootstrap`, `handle_triage_confirmation`,
     `should_offer_bootstrap`,
     `build_repo_bootstrap_confirm_task` stay as one-line
     delegators.  Shared helpers `_create_feature_branch` /
     `_build_push_confirm_task` remain on the agent and are
     passed to the controller as callables.
     `detect_github_repo` (module-level in `core.py`) passed
     via late-binding lambda to preserve test patchability.
     Test patches of `cantrip.agent.core.{push_branch,
     create_pull_request,build_pr_body,bootstrap_github_repo,
     can_bootstrap,build_issue_work_tasks}` retargeted to
     `cantrip.agent.confirmations.<name>`.  Pure refactor —
     `make check` and `make unit` (6 412 passed, 8 skipped)
     green.
  7. ✓ **Session persistence** → `agent/persistence.py`
     `PersistenceController` (327 lines).  Six methods extracted:
     `save_state`, `preview_session`, `transcript_tail`,
     `archive_session`, `load_state`, `build_resume_summary`.
     Shared internals injected as callables (`ensure_store`,
     `get_store`, `reset_store`, `restore_safety_state`,
     `rebuild_messages`).  Added `_reset_store()` helper on
     `CantripAgent`.  `core.py` 3199 → 2987 lines (−212).
     `make check` and `make unit` (6 412 passed, 8 skipped)
     green.
- [x] For each extraction: introduce a focused class in its
  own module, hold an instance on `CantripAgent`, keep the
  existing property/method names as one-line delegators.
  All seven cohorts done: `mcp_controller.py`,
  `executor_controller.py`, `watcher_controller.py`,
  `triage_controller.py`, `arena_controller.py`,
  `confirmations.py`, `persistence.py`.
- [x] After all seven cohorts: `agent/core.py` is 2 987 lines
  (down from 3 893 — a 906-line reduction).  The remaining
  code is the irreducible core: `process_message`,
  `process_message_streaming`, `prepare`, `warm_up`, context
  management, tool dispatch, model switching, memory, and
  property accessors.  Below the 1 500-line aspirational
  target but the goal was comprehensibility, not an
  arbitrary count — the remaining methods are tightly coupled
  and would not benefit from further extraction.
- [x] No public-API rename in this phase.  Each step preserved
  external behaviour and import paths — pure refactor.

### 85.5 Decompose — `BackgroundExecutor` and `CantripApp`

- [x] `agent/executor.py` (was 1 722 lines) split into a
  subpackage: `agent/executor/git_service.py` holds
  `_DefaultGitService`; `agent/executor/policies.py` holds
  `_DefaultEnvironmentChecker` and `_DefaultFollowupPlanner`;
  `agent/executor/store_adapter.py` holds
  `_SessionStoreAdapter`; `agent/executor/core.py` holds the
  `BackgroundExecutor` orchestrator (1 543 lines —
  comprehensible enough that further decomposition would just
  shuffle methods).  `__init__.py` re-exports the public
  surface (`BackgroundExecutor`, `_candidate_id_for`, the
  module-level constants `_POLL_INTERVAL`,
  `_DEFAULT_TASK_TIMEOUT`, `_ERROR_COOLDOWN`,
  `_MAX_NOOP_COUNT`, `_MAX_CONSECUTIVE_ERRORS`,
  `_TASK_TIMEOUTS`, `DEFAULT_MAX_CONCURRENCY`, plus the four
  default-service classes) so `from cantrip.agent.executor
  import …` callers do not move.  Test patches that targeted
  `cantrip.agent.executor.<name>` for module-private symbols
  (`Subagent`, `_POLL_INTERVAL`, `_ERROR_COOLDOWN`,
  `_DEFAULT_TASK_TIMEOUT`, `log` for `_check_uncommitted`)
  retargeted to `cantrip.agent.executor.core.<name>`; patches
  for git-service-private names (`subprocess`, `log` for
  `revert_to_clean`) retargeted to
  `cantrip.agent.executor.git_service.<name>`.  Pure refactor
  — `make check` and `make unit` (6 412 passed, 8 skipped)
  green.
- [x] `tui/app.py` action handlers grouped by surface and
  lifted into a new `tui/actions/` subpackage (was 2 053
  lines, now 1 934).  The four named buckets each get a
  module: `tui/actions/screens.py` (`show_help`, `show_debug`,
  `show_logs`, `show_graph`, `show_transcript`,
  `open_relation_detail`); `tui/actions/status.py`
  (`toggle_status`, `toggle_files`, `toggle_model_info`,
  `show_status_panel_when_data_arrives`); `tui/actions/chat.py`
  (`clear_chat`, `open_search`, `search_closed`,
  `cancel_agent`); `tui/actions/watcher.py`
  (`subscribe_events`, `start_watcher`, `stop_watcher`,
  `refresh_model_panes`, `on_watcher_event`, `on_juju_status`,
  `update_status_bar`, `refresh_subagent_status_bar`,
  `toggle_watcher`).  Each function takes the app instance as
  its first argument; `CantripApp` keeps thin `action_*` /
  `on_*` methods that delegate so Textual's binding discovery
  and event-handler-by-name plumbing keep working unchanged.
  `compose()`, `on_mount()`, the preflight integration, the
  bus subscriber registration, the confirmation flow methods
  (`_handle_*_response` / `_present_*_confirmation`), and the
  chat input pipeline (`on_input_submitted`,
  `_process_agent_message`) stay on the class — those are
  bigger cohorts and are left for a follow-up.  Pure refactor
  — `make check` and `make unit` (6 412 passed, 8 skipped)
  green.

### 85.6 Decompose — function-level giants

- [x] `src/cantrip/agent/tools/publishing.py:1108
  generate_docs_scaffold` (was 502 lines, now ~70 lines of
  context assembly + a render loop).  Each generated file
  now lives as its own template under
  `src/cantrip/charm/docs_templates/` (one `.md.j2`,
  `.rst.j2`, or filename-suffixed `.j2` per output, mirroring
  the output paths).  Dynamic per-item lists (config-option
  examples, action sections, integration entries) precompute
  to `_block` strings via small `_build_*_block` helpers and
  drop into templates as single placeholders, keeping the
  templates as static skeletons.  Acceptance-artefact
  overrides and the Phase 74.1 root-file bridges stay in the
  renderer.  Pure refactor — every existing test in
  `test_publishing.py`, `test_docs_from_acceptance.py`, and
  `test_docs_bridge.py` (135 cases) still passes, and an
  ad-hoc byte-for-byte comparison across eleven scenarios
  (rich/bare/no-actions/no-source/bridged/artefacts/etc.)
  matched the pre-refactor output exactly.
- [x] `src/cantrip/main.py:46 parse_args` (was 675 lines).
  Now a 32-line composition: nine `_add_<subcommand>_subparser`
  helpers cover `run`, `compare`, `export-transcript`, `hooks`,
  `skill`, `checkpoints`, `docs`, `audit`, `permissions`; six
  `_add_run_<group>_options` helpers split the `run` subparser
  into model / session / budget / loop / print / appearance
  groups; argv fall-through lifted into `_normalise_argv`.  No
  CLI behaviour change.
- [x] `src/cantrip/agent/tools/rockcraft.py
  _deploy_k8s_registry` (was 128 lines, now 43) decomposed
  into per-phase helpers: `_fetch_juju_status`,
  `_existing_registry_success`, `_deploy_registry_charm`,
  `_wait_for_registry_active`, `_fresh_registry_success`.
  The four `juju.py` `execute()` methods that exceeded 100
  lines now sit at 36–48 line bodies after extracting
  per-phase helpers: `JujuReadRelationDataTool` →
  `_fetch_show_unit_json` + `_format_relation_block`;
  `JujuGetAppConfigTool` → `_fetch_config_json` +
  `_render_config_table` + `_render_validation_block`;
  `JujuDeployTool` → `_resolve_and_stage_charm` +
  `_build_deploy_args` + `_deploy_success_result`;
  `CharmSyncTool` → `_collect_python_files` + `_push_file`.
  Pure refactor — no behaviour change, all 141 tests across
  `test_juju_tools.py`, `test_juju_introspection.py`, and
  `test_rockcraft_tools.py` still pass.

### 85.7 Move — top-level Python files into packages

- [x] `src/cantrip/hooks.py` (was 1 037 lines) →
  `src/cantrip/hooks/` package: `types.py` (HookEvent,
  HookConfig, HookResult, helpers), `filter.py` (the AST-based
  ``if:`` expression compiler + evaluator), `config.py`
  (load_hooks + YAML parsers), `runner.py` (HookRunner,
  HookStats, operator resolution).  `__init__.py` re-exports
  every public name plus the private symbols the test suite
  reaches for (``_FilterExpr``, ``_parse_yaml``, ``_resolve_operator``,
  …).  Pure refactor — the only test change is that the four
  ``_resolve_operator`` monkey-patches in ``test_hooks.py`` now
  target ``cantrip.hooks.runner._resolve_operator`` (the actual
  call-site lookup) instead of the package binding.
- [x] `src/cantrip/update.py` (was 822 lines) → `update/`
  package: `types.py` (UpdateInfo, InstallMethod), `release.py`
  (CHANGELOG fetch + ``## <version>`` extraction), `check.py`
  (opt-out / cache plumbing + the `check_for_update`
  orchestrator + PyPI-payload helpers), `install.py`
  (installer detection, upgrade-command rendering, CLI / slash
  notice formatters).  `__init__.py` re-exports the public API,
  the private symbols tests probe, and ``httpx`` (so
  ``mock.patch("cantrip.update.httpx.AsyncClient")`` continues
  to land on the live module).  ``upgrade_command`` resolves
  ``detect_install_method`` lazily through the package so
  external monkey-patches at the ``cantrip.update`` level still
  reach internal callers; eight ``_SETTINGS_PATH`` patches in
  ``test_update.py`` / ``test_slash.py`` were repointed to
  ``cantrip.update.check._SETTINGS_PATH``.
- [x] `src/cantrip/main.py` (was 1 575 lines after the 85.6
  ``parse_args`` extraction — well over the ~600-line
  defer-if-so threshold) → `src/cantrip/main/` package.
  Argument parsing moves to `main/parser.py`; the ``_run``
  TUI/Web/CLI dispatcher and its helpers
  (`_install_unraisable_hook`, `_is_cantrip_source_tree`,
  `_print_update_panel`, `_truncate_notes`,
  `_CANTRIP_PYPROJECT_*`) move to `main/run.py`; each
  subcommand handler gets its own module
  (`main/transcript.py`, `main/compare.py`,
  `main/hooks_cmd.py`, `main/skill_cmd.py`,
  `main/checkpoints.py`, `main/audit.py`,
  `main/permissions.py`).  `main/__init__.py` re-exports the
  public + monkey-patchable surface (`parse_args`, `_run`,
  `_install_unraisable_hook`, `_print_update_panel`, every
  ``_<cmd>`` handler) so `from cantrip.main import …` lines
  in tests keep working unchanged; the entry point
  `cantrip.main:main` resolves to `main/__init__.py`'s
  `main()`.  Test patches that targeted
  `cantrip.main._install_unraisable_hook` (8) and
  `cantrip.main._print_update_panel` (1) in
  `tests/unit/test_main.py` retargeted to
  `cantrip.main.run.<name>` so the patches reach the actual
  call site rather than the package alias.  Pure refactor —
  `make check` and `make unit` (7 172 passed, 9 skipped)
  green.

### 85.8 Mirror — `tests/unit/` folder structure

- [x] Moved 171 of the 184 flat test files at the top level of
  `tests/unit/` into folders mirroring `src/cantrip/`.  New
  groups (in addition to the existing `agent/`, `agent/memory/`,
  `agent/commands/`, `executor/`, `subagent/`, `planner/`,
  `charm_tools/`, `charmlint/`, `quickpack/`): `agent/tools/`
  (56 files), `llm/` (10), `mcp/` (7), `tui/` (12), `web/` (2),
  `ui/` (4), `repomap/` (1), `docs_index/` (3), `transcript/`
  (2).  13 files stay at the top level — they test top-level
  modules (`main`, `cli`-style standalones, `clipboard`,
  `compare`, `diagnostics`, `workspace`, `update`, `hooks`)
  or are root-level fixtures (`test_e2e_harness`, `test_status`,
  `test_pypi_attest`, `test_cookbook_recipes`).
- [x] Existing sub-folders (`executor/`, `subagent/`, `planner/`,
  `charm_tools/`, `charmlint/`, `quickpack/`) left in place;
  they were already correctly grouped.
- [x] Renamed the ambiguous pair: `test_tool_caption.py` →
  `test_caption_builder.py` (helper unit tests) and
  `test_tool_captions.py` → `test_caption_coverage.py`
  (per-tool coverage matrix), both now under
  `tests/unit/agent/tools/`.
- [x] `make unit` passes after the moves (6 411 passed, 8
  skipped).  Five `__file__`-relative path constants and two
  cross-test imports (`tests.unit.test_tui` → `tests.unit.tui.
  test_tui`) needed `parents[]` index updates to match the
  new depth; otherwise pytest discovery handled the renames
  automatically.

### What this phase is *not*

- Not a behaviour change.  Every step here should land as a
  pure refactor — same public API on `CantripAgent`,
  `CantripApp`, and the slash-command dispatcher; same CLI
  flags; same test outcomes.
- Not a rewrite of `agent/tools/`.  The big tool modules
  (`publishing.py`, `juju.py`, `observability.py`,
  `acceptance.py`, `charm.py`) are large because Cantrip
  delegates a lot of charm work to them; their internal
  shape is fine.  Only `generate_docs_scaffold` (a single
  template-y function) is called out for decomposition.
- Not a hunt for unused code.  If 85.4's delegation reveals
  dead methods, fix them in passing; do not let it expand
  into a wider sweep.
- Not a renaming pass.  Symbol names stay; only file/folder
  layout moves.

**Exit criteria:** `agent/core.py` is below 1 500 lines and
no longer holds the seven cohorts in 85.4; `agent/memory/`
exists as a subpackage; `tests/unit/` has folders that
mirror `src/cantrip/` for the heaviest groups; the four
documented `except Exception` clauses carry rationale
comments; `from datetime import datetime` is gone from
`src/cantrip/`; the `Path` / `dataclass` import policy is
either unified or explicitly carved out in `AGENTS.md`;
`make check` and `make unit` pass throughout; no public
import path on the `cantrip.agent` surface has changed.

**Discovered:** Mid-2026 structure-review pass after a heavy
run of feature phases (67–84).  The review confirmed the
package spine is sound but flagged four specific giants
(`agent/core.py`, `tui/app.py`, `agent/tools/publishing.py`,
`main.py:parse_args`), one missing subpackage (`agent/
memory/`), and a flat `tests/unit/` that no longer matches
the layered `src/`.  Sweeping these together rather than
file-by-file keeps the diff comprehensible as a single
intentional cleanup.
---

## Phase 89: TUI File Pane — Repo Stats Sidebar

**Goal:** The TUI file pane (``CharmTreeWidget``, ``#charm-files``)
is comfortably wide and shows a directory tree on the left with
empty space to its right.  A live session reading "Phase 65" land
flagged that the right-hand half of the pane is dead real estate
that could carry quick repo signals — the kind of glance-and-go
data a charm author asks for several times an hour and currently
has to drop into a terminal to fetch.

Candidate readouts (none final; the phase decides the slate):

- **Lines of code** — total and by-language (``ops`` / Python vs
  ``charmcraft`` YAML / Jinja).  Lines authored vs vendor.
- **Most recently changed file** — the working-tree-newest entry
  with a relative timestamp ("2 m ago"), so the user notices when
  the agent has touched something during a long-running task.
- **Most recent commit** — short hash, subject, age.  Useful as a
  "what landed last" signal without leaving the TUI.
- **Total files / directories** — for charms that scale into
  many libs.
- **Total tests / tests passing** — pulled from the most recent
  ``pytest`` run via the existing test-results path.
- **Lint state** — green / red, last run age.

### 89.1 Decide the slate ✓

- [x] Scored the candidate stats on (a) read-frequency during a
  real charm session, (b) cost to compute live, and (c) cost to
  keep fresh.  Picked four cheap-to-compute, high-signal stats
  drawn from filesystem + git only:
  - **Most recently changed file** with a relative timestamp.
  - **Most recent commit** (short hash, subject, age) — one cached
    `git log -1` per tick.
  - **Lines of code** total with a top-two language breakdown,
    bounded by an extension allowlist and a 1 MB per-file cap.
  - **File and directory counts** taken from the same filtered
    walk used by the tree, with a defensive 5 000-file scan cap.
  Test-pass count and lint state were deferred — they need a
  runner-side bus event to avoid showing stale data.  Trigger to
  revisit: a per-run test-results event lands on the bus from
  pytest (and an equivalent charmlint last-run summary), at which
  point the sidebar can subscribe to either or both.

### 89.2 Layout ✓

- [x] Stats column lives **inside `CharmTreeWidget`** as a
  right-docked sibling of the directory tree
  (`Horizontal(_FilteredTree, RepoStatsWidget)` inside a
  `#charm-files-body` container).  Single widget keeps the layout
  decisions and the refresh tick co-located, and the stats
  computation can ride on the same 3 s timer that already reloads
  the tree.
- [x] Below ~46 columns of widget width the sidebar hides itself
  via `display = False` on resize, so the file tree keeps the full
  pane on narrow terminals.  The fold flips back automatically when
  the user widens the window or closes the right side panels with
  <kbd>F2</kbd>; no separate binding required.

### 89.3 Implementation ✓

- [x] Refresh cadence rides the existing 3 s tree tick — every tick
  walks the working directory once on a worker thread (via
  `asyncio.to_thread`) so the UI loop never blocks on the walk or
  the `git log` call.  Stats computation is a single pure function
  (`compute_repo_stats(root) -> RepoStats`) that does the prune,
  the line-count, and the `git log -1` invocation in one pass; the
  widget consumes the resulting snapshot via `set_stats`.
- [x] Tests under `tests/unit/tui/test_repo_stats.py` cover the
  pure walk path (empty / missing / hidden-prune / oversize-skip /
  newest-mtime / scan-cap-truncated), the `read_last_commit` git
  interop (non-git / no-commits / populated), the `format_relative_time`
  / `render_stats_lines` formatters (every relative-time bucket plus
  the truncation-at-width assertion), and a Pilot integration that
  mounts the widget against a synthetic charm checkout and asserts
  both the populated state at wide widths and the fold at narrow
  widths.

### What this phase is *not*

- Not a CI dashboard.  Stats are local-repo only; nothing in
  this phase reaches out to GitHub Actions or external services.
- Not a charm-quality scorecard.  We're surfacing facts, not
  judgements; "most recently changed file" is informational, not
  a complaint.

**Exit criteria:** the right-hand portion of ``#charm-files``
carries the chosen four stats, refreshing without UI hitches in
a normal-size charm checkout, with a graceful fold for narrow
terminals.  Manual walk-through during a build session confirms
the data is helpful rather than noise.

---

## Phase 90: Topology as a First-Class View — Visual Model Pane and Graph Screen

**Goal:** Two community visualisations of the Juju ecosystem
have set a higher bar than what Cantrip currently shows.  The
Figma "COS solution" page (``bobbin-froth-37640366.figma.site/
solutions/cos``) treats each *integration line* as a clickable
object that reveals the interface name, what flows across it
(``alertmanager:alerting``, ``prometheus:metrics-endpoint``),
sample endpoints, and prose describing the relationship.  It
also fades unrelated charms when one is focused, and groups
charms into semantic layers (Data Layer, Control Plane, …).
CharmGraph (``charm-graph-hub.base44.app``) leans on a
"preset deployments" library so users start from a known-good
shape rather than an empty canvas, and exports the result as a
``bundle.yaml``.

Cantrip already owns the underlying data (``app.relations``,
the F8 ``GraphScreen`` in ``src/cantrip/tui/screens/graph.py``,
``MultiModelStatusWidget`` in ``src/cantrip/tui/widgets/
status.py``).  What's missing is treating the topology as a
first-class artefact rather than a status table with a separate
modal.  This phase rethinks both surfaces: the right-panel
multi-model pane (currently a dense text status block) and the
F8 graph screen (currently bordered panels + a flat dedup'd
relation list with no edge interaction).

### 90.1 Decide the surface mix

- [ ] Score the three borrowable ideas against Cantrip's
  agent-driven (not click-to-build) shape:
  - **Edge-as-object** — clicking a relation reveals interface
    name, direction, sample databag keys, prose description.
  - **Focus + fade** — selecting an app dims unconnected apps
    and unrelated edges in the same view.
  - **Preset solutions** — a small library of known-good
    bundle shapes (COS Lite, 12-Factor + COS, CKF, …) the
    *agent* can reference when composing relations; the user
    sees them as an overlay on the topology view, not as a
    palette to drag from.
- [ ] Decide which of the three lands in 90.x and which is
  deferred behind named triggers.  The agent-driven framing is
  the deciding question — drag-from-palette UX is explicitly
  out of scope; surfacing structure the agent already reasons
  about is in scope.
- [ ] Side-finding: capture the "edge data is the interesting
  data" insight as a context-provider candidate (``@relation
  prometheus:alertmanager``) for ``design/CONTEXT_PROVIDERS.md``
  if the survey shows the agent re-derives this every turn.

### 90.2 Rethink the right-panel multi-model pane

- [ ] ``MultiModelStatusWidget`` today renders each model as a
  collapsed/expanded text block of unit lines.  Replace the
  expanded-model body with a compact topology sketch: nodes
  for apps (single-glyph + name + status colour), edges for
  relations (one line per pair, regardless of how many
  endpoints), grouped by relation interface where it reduces
  clutter.  The collapsed summary stays text — a one-line
  ``model · N apps · M relations · status`` line.
- [ ] Honour terminal width: below a threshold, fall back to
  the current text view.  Above it, the sketch should fit the
  pane without horizontal scroll for a typical COS-Lite-sized
  model (≈6 apps, ≈10 relations).
- [ ] Selecting an app in the sketch is the entry point to the
  full F8 view focused on that app — not a modal of its own.

### 90.3 Rethink the F8 graph screen

- [ ] Edges become first-class.  The dedup'd relation list at
  the bottom of ``GraphScreen`` is replaced by an inline edge
  layer between the app panels; each edge carries its
  interface name as a label.  Selecting an edge opens an
  inline detail strip (not a new modal) showing: interface
  name, provider/requirer roles, observed databag keys (from
  ``app.relations`` and any cached ``juju show-unit`` data),
  and a one-paragraph description sourced from the
  agent's relation knowledge (skill or context provider).
- [ ] Focus + fade: selecting an app dims unconnected apps and
  unrelated edges.  Escape / re-selecting clears the focus.
- [ ] Layer hint: when the model matches a known preset
  (90.4), render apps grouped by the preset's semantic layer
  ("Data", "Routing", "User Access").  When it doesn't, fall
  back to the current alphabetical layout.  No layer
  invention — the grouping comes from the preset, not from
  guessing.

### 90.4 Preset bundle library (knowledge, not UX)

- [ ] Author a small JSON/YAML catalogue of known bundles
  under ``src/cantrip/agent/skills/`` (or the closest existing
  skill home — confirm with ``design/SKILLS.md``) that records
  for each preset: the apps, their semantic layer, the
  expected relation edges with interface names, and a one-line
  description per edge.  Initial set: COS Lite, Charmed
  Kubeflow (subset), 12-Factor + COS, Identity Platform
  (cross-reference Phase 88).
- [ ] Expose the catalogue to the agent as a context provider
  or tool — when the agent is composing relations or
  diagnosing a deployment, it can fetch the canonical edge
  list rather than rebuilding it from web docs every turn.
- [ ] The graph screen uses the catalogue *only* for layer
  grouping and edge prose; it does not prescribe deployment
  steps.

### What this phase is *not*

- Not a click-to-build deployment editor.  Cantrip is
  agent-driven; users describe charms, the agent composes the
  bundle.  CharmGraph's drag-from-palette UX is out of scope.
- Not a replacement for ``juju status``.  The text pane stays
  available; this phase adds a visual layer that earns its
  space, not a forced re-skin.
- Not new graph-layout machinery.  Stick to Textual primitives
  and Rich renderables; do not pull in a graph-drawing
  dependency.  If a clean layout requires more than that, log
  it as a Phase 90b trigger.

**Exit criteria:** the right-panel multi-model pane shows a
readable topology sketch for an expanded model at typical
terminal widths; the F8 screen renders edges as labelled,
selectable objects with an inline detail strip and focus-fade
behaviour; a preset catalogue exists and is wired into both
the agent (as knowledge) and the graph screen (as layer
grouping).  A live walk-through against COS Lite confirms the
visual surfaces are read more often than the underlying text
status during a representative session.

---

## Phase 92: Review Follow-Ups — Deterministic Scan, Validation Hardening, and Docs Discoverability

**Goal:** A broad April 2026 project review turned up four clusters of
follow-up work that are individually small-to-medium but collectively
important: one deferred-but-user-visible product gap (the unfinished
deterministic repo scan for custom apps), a handful of correctness and
validation hardening fixes in ``charmlint`` / ``quickpack``, several
test-suite reliability gaps, and documentation / onboarding surfaces
that ship features without making them easy to discover.  The phase is
explicitly a **follow-up sweep**: close the sharp edges the review
identified rather than opening a new product line.

### 92.1 High — Finish the deterministic pre-scan for non-PaaS repos

- [x] Turn ``src/cantrip/agent/tools/_scan.py`` from the current
  documented stub into the real implementation sketched in
  ``design/TOOLS.md``: filesystem walk with ``EXCLUDE_DIRS`` pruning,
  manifest expansion, entry-point probing, CI/CD detection, container /
  security / lint-config / env-template detection, charm-marker
  detection, and recent-git-churn summary.
- [x] Wire ``AnalyseFrameworkTool.execute()`` to call the scan helper so
  custom-application routing stops re-deriving deterministic facts ad
  hoc.  Keep the existing user-facing return shape
  (``framework``, ``language``, ``profile``, ``workload_hints``,
  ``candidates``, ``notes``) and layer the scan output underneath it
  rather than widening every downstream caller.
- [x] Add focused unit tests for the scan passes under
  ``tests/unit/test_scan.py`` using tiny synthetic repo fixtures:
  manifests-only, CI-only, entry-point-only, existing-charm marker,
  mixed Docker/systemd hints, and a pathological excluded-directory
  case so the walk budget stays bounded.
- [x] Record whether the scan should also feed future UI surfaces
  (repo-stats sidebar, onboarding summary, print-mode preamble) so the
  helper becomes the single source of truth for "what kind of repo is
  this?" rather than a planner-only utility.

### 92.2 High — Validation hardening in ``charmlint`` and ``quickpack``

- [x] Replace the current ``charmlint`` category extraction
  (``rule_id.rstrip("0123456789")``) with an explicit parser so
  category-level ``select`` / ``ignore`` / severity overrides cannot
  mis-handle edge-case rule IDs.  Add regression tests for category
  matching rather than relying on naming convention alone.
- [x] Remove the lazy rule-registration bootstrap in
  ``src/charmlint/linter.py`` in favour of an explicit, import-at-module-
  top registration path that keeps the rule set deterministic and
  easier to reason about under tests and future concurrency.
- [x] Harden ``quickpack``'s generated dispatch script: fail fast on
  missing interpreters, tighten shell quoting / error handling, and
  surface launcher problems as clear pack-time failures instead of
  delayed deploy-time breakage.
- [x] Validate ``quickpack`` metadata inputs earlier: reject invalid or
  out-of-tree entrypoints, validate ``charmcraft.yaml`` fields that the
  pack path depends on, and add tests covering malformed metadata so the
  failures stay crisp.
- [x] Audit the remaining broad ``except Exception`` sites touched by
  the review and either narrow them or document the boundary in the
  established ``# noqa: BLE001 — <reason>`` style where the broad catch
  is intentional.

### 92.3 High — Test reliability, coverage, and evaluation depth

- [x] Replace the fixed sleeps in the executor and e2e harnesses with
  polling / signalling helpers.  ``tests/support/wait.py`` exposes a
  shared ``wait_until`` predicate poller plus ``wait_for_task_status``,
  ``wait_for_queue_state``, and ``wait_for_value`` helpers.  Migrated
  ``tests/unit/executor/test_run_loop.py``, ``test_budget.py``,
  ``test_rate_limit.py``, and ``tests/integration/test_work_loop.py``
  off the previous ``asyncio.sleep(0.05–0.2)`` / fixed 2 s waits.
  The integration ``wait_for_queue_state`` shim now re-exports from
  ``tests.support.wait`` so existing call sites keep importing from
  ``tests.integration.conftest``.  The remaining ``time.sleep(5/10)``
  calls in ``tests/e2e/harness.py`` are already inside polling loops
  (Jubilant ``juju status`` reads with deadline-bounded loops) — they
  set the polling cadence rather than acting as fixed timing
  assumptions, so they are not in the "structurally flaky" bucket.
- [x] Add a lightweight executor-test harness that waits on explicit
  queue / task state transitions rather than timing assumptions, then
  migrate ``tests/unit/executor/test_run_loop.py`` and similar files.
  Done as part of the shared wait helpers above; the executor unit
  tests now wait on task/queue state directly via
  ``wait_for_task_status`` and ``wait_for_queue_state``.
- [x] Enforce Python coverage in the main developer loop.  ``make unit``
  already collects coverage; add a ``fail_under`` threshold and wire it
  into ``make check`` so coverage regressions are visible before merge.
  ``[tool.coverage.report].fail_under = 88`` is set in ``pyproject.toml``
  (current baseline ~88.77%, leaves a 1pp margin for xdist noise);
  pytest-cov consumes the threshold during ``make unit``, which
  ``make check`` already invokes, so any drop below 88% fails the
  developer loop and CI.
- [ ] Expand the eval corpus beyond the current minimal set of gold
  charms: cover more substrates (machine + k8s), at least one custom /
  non-framework application path, and more relation / observability
  shapes so prompt or planner regressions are easier to detect.
- [ ] Add CI wiring for the eval work that is cheap enough to run
  regularly: keep the full provider-matrix ambition in Phase 79, but
  make the static gold-standard / rubric path and any cheap smoke path
  first-class rather than manual-only.
- [x] Reduce test-maintenance drag in the heaviest files and fixtures.
  - [x] Split the monolithic ``tests/unit/agent/test_agent.py`` into
    feature-scoped modules.  ~1.5 kloc went into eight new siblings —
    ``test_agent_core.py``, ``test_agent_models.py``,
    ``test_agent_cache.py``, ``test_agent_persistence.py``,
    ``test_agent_context.py``, ``test_agent_tooling.py``,
    ``test_agent_watcher.py``, and ``test_agent_improvement.py`` —
    matching the existing ``test_agent_<feature>.py`` convention used by
    ``test_agent_arena.py`` / ``test_agent_github.py`` /
    ``test_agent_lifecycle.py``.  The duplicated ``TestInferGapsFromAudit``
    class (a strict subset of the canonical copy in
    ``test_audit_gap_inference.py``) was dropped rather than re-housed.
  - [x] Centralise reusable fakes/builders so unit / integration / e2e
    layers stop growing parallel infrastructure by accident.  Five new
    modules under ``tests/support/``:  ``providers.py`` (``RecordingProvider``,
    ``CallbackProvider``, ``MultiRoleProvider`` — the latter two moved out
    of ``tests/integration/conftest.py``), ``tools.py`` (``make_stub_tool``,
    replacing five inline ``_StubTool`` / ``_make_tool`` definitions plus
    the integration-conftest variant), ``worktrees.py`` (a single
    ``FakeAllocator`` + ``AllocCall`` / ``ReleaseCall`` dataclasses,
    replacing three near-duplicate ``FakeAllocator`` / ``_FakeAllocator``
    classes across ``test_executor_worktree.py``, ``test_executor_race.py``,
    and ``test_race.py``), and ``roles.py`` (``StubEmbed`` / ``StubRerank``,
    replacing three inline ``_StubEmbed`` definitions).  Inline
    ``RecordingProvider`` subclasses in ``test_run.py``, ``test_day2.py``,
    and ``test_design.py`` (5 occurrences) collapsed onto the shared one.
  - [x] Document the fixture hierarchy.  ``tests/README.md`` lays out the
    unit / integration / e2e / eval rings, the conftest layering rules,
    and a catalogue of every shared fake plus the protocol it stands in
    for; ``CLAUDE.md`` carries a pointer to it from the test-suite section
    so future contributors find the catalogue before reaching for an
    inline ``_StubX``.
- [x] Add a small audit of exception-path coverage in high-value modules
  (provider adapters, executor loop, juju/log plumbing, structured
  output, persistence) and backfill the missing regression tests the
  review called out.  Audit drove from the annotated coverage report
  (``cov_annotate/``) and landed seventeen focused regression tests:
  ``ClaudeProvider.complete()`` rate-limit / 5xx / generic-API-error
  mappings (and the matching ``stream()`` paths), ``GeminiProvider``
  ``ServerError`` / generic ``APIError`` mappings on both ``complete()``
  and ``stream()``, ``BackgroundExecutor._on_permission_decided``
  swallowing ``TypeError`` and ``RuntimeError`` from a broken UI hook
  without crashing the loop, ``preview_session`` falling through to an
  empty preview when the ``.cantrip`` file is corrupt or
  ``peek_session`` raises, and ``capture_databag_snapshot`` degrading
  to an empty ``DatabagSnapshot()`` when the ``juju`` CLI is missing,
  hangs, or returns malformed JSON.  Total coverage moved 88.76 → 88.88%.

### 92.4 Medium — Docs and discoverability sweep

- [x] Fix command discoverability in ``docs/src/reference-cli.md``:
  add ``cantrip audit`` and ``cantrip permissions`` to the
  ``on_this_page`` list, make sure every implemented subcommand appears
  in the reference navigation, and add brief prose explaining when a
  user reaches for each command.
- [x] Rework the README opening so it distinguishes **end-user install**
  from **contributor checkout** immediately.  The current clone+``uv
  sync`` path is correct for development but obscures the simpler
  install flow for users who just want the tool.
- [x] Add docs for the two underexplained interface surfaces:
  **Web UI** and **CLI/REPL mode** (``--web`` and ``--no-tui``).  Cover
  when to use each surface, any feature-parity caveats, and the
  workflows that are easier there than in the TUI.
- [x] Expand ``howto-print-mode`` with concrete CI / automation
  examples, and surface print mode, permissions, and audit from the docs
  landing page instead of leaving them buried in the CLI reference.
- [x] Add a short "Start here" path to the docs landing page:
  install, choose TUI/Web/CLI, build a new charm vs improve an existing
  one, then link to the relevant how-tos.  The current card grid is rich
  but gives new users no ordering signal.
- [x] Consolidate environment-variable guidance so setup is not repeated
  piecemeal across README, tutorial, provider how-to, and CLI reference.
  ``howto-provider.md`` gained an ``{#env-vars}`` section that owns the
  setup walk-through (per-provider exports, persistence guidance, embed
  / rerank keys); ``reference-cli.md#env-vars`` keeps the comprehensive
  table and now leads with a one-paragraph cross-reference to the
  how-to; README and ``tutorial.md`` collapse the duplicated
  ``export GEMINI_API_KEY`` step into a single example with explicit
  links to the consolidated env-var page.
- [x] Sweep user-facing docs for stray internal phase-language
  references and remove them.  ``grep -rn "Phase [0-9]"`` against
  ``docs/src/`` and ``docs/docs/`` returned zero matches; remaining
  ``phase`` mentions are the four user-facing workflow phases
  (research / build / deploy / test) which CLAUDE.md explicitly keeps.
  Nothing to remove — bullet closed by audit.

### What this phase is *not*

- Not a new architecture initiative.  The point is to finish deferred
  or rough-edged pieces already implied by the current design.
- Not a wholesale test-suite rewrite.  The target is the high-value
  reliability and maintenance problems the review surfaced first.
- Not a docs-platform rewrite.  The existing Markdown → HTML pipeline
  stands; this phase improves content structure and discoverability
  inside it.

**Exit criteria:** the deterministic scan is implemented and used by
``analyse_framework``; the ``charmlint`` / ``quickpack`` fixes above
land with regression tests; the flaky fixed-sleep cases are gone from
the reviewed executor/e2e paths and coverage is enforced in ``make
check``; the docs surface ``audit``, ``permissions``, Web UI, CLI mode,
print mode, onboarding, and env-var setup clearly enough that a new
user can find them without prior project knowledge.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Deterministic pre-scan (92.1) | Phase 91 framework-detection port, design/TOOLS.md Phase 55.7 stub note | Finishes the deferred implementation rather than inventing a new surface |
| Validation hardening (92.2) | Existing ``charmlint`` / ``quickpack`` test suites | Mostly surgical correctness work |
| Test reliability (92.3) | Phase 79 eval work for provider-matrix follow-ons | Coverage / gold standards can land independently of full provider-in-loop eval |
| Docs sweep (92.4) | Existing docs build pipeline | Source edits under ``docs/src/`` + regenerated HTML |

**Discovered:** Project-wide review on 2026-04-30 covering code,
tests, docs, and UX surfaces.  The strongest themes were the unfinished
deterministic repo scan, a handful of correctness hardening fixes, flaky
test timing, thin eval/discoverability coverage, and user-facing
features that exist but are too hard to find.

---

## Phase 93: Testing Depth Sweep — Failure Paths, Durability, and System-Level Confidence

**Goal:** Cantrip's **unit** suite is already broad and healthy
(``make coverage`` currently reports ~89% total Python coverage), but the
review on 2026-04-30 found that the **non-unit** story is much thinner than
the unit numbers suggest.  Integration / e2e / live / eval coverage is good
for the happy-path planner→build→deploy flow, transcript export, and a handful
of real charm-build scenarios, but the suite is still light on failure-mode
behaviour, restart/durability, sandbox/worktree isolation, git automation, and
newer controller surfaces.  This phase closes that gap by treating testing as
a product feature: the goal is not "more tests" in the abstract, but
confidence that Cantrip keeps working when reality is messy.

### 93.1 High — Backfill the highest-value unit-coverage holes

- [ ] Turn the current zero-coverage deterministic repo scan helper
  (``src/cantrip/agent/tools/_scan.py``) into a fully-tested module once
  Phase 92.1 lands.  The helper should not remain both architecturally
  important *and* entirely uncovered.
- [ ] Add focused unit coverage for the current "important but thinly covered"
  modules surfaced by the review: ``executor_controller.py``,
  ``preflight.py``, ``context_providers_builtin.py``,
  ``github_issues.py``, ``watcher.py``, ``auto_commit.py``,
  ``git_branch.py``, and the higher-branching paths in
  ``agent/tools/acceptance.py`` and ``agent/tools/charm.py``.
- [ ] Reduce the TUI blind spots in ``src/cantrip/tui/app.py`` and adjacent
  screens/widgets by promoting the highest-value flows to behaviour tests:
  screen switching, resume/restart affordances, task/status updates, modal
  transitions, and failure states that currently live only in manual use.
- [ ] When a module remains below the surrounding package average after this
  sweep, record *why* in the test or roadmap text instead of letting the gap
  look accidental.

### 93.2 High — Add failure-injection integration tests

- [ ] Add a first-class integration harness for **LLM/provider failures**:
  timeout, rate-limit, malformed response, provider 5xx, and tool-call shape
  violations.  Assert user-visible failure handling, retry behaviour, and
  queue/task state transitions rather than only that an exception bubbles.
- [ ] Add **tool execution failure** integration coverage: subprocess exits
  non-zero, partial output + timeout, missing binaries, Juju command failures,
  export/write failures, and cleanup hooks that should still run on final
  failure.
- [ ] Exercise the existing retry / recovery surfaces under pressure:
  transient failure that later succeeds, retry budget exhausted, and "final
  failure produces a crisp summary instead of hanging the loop".
- [ ] Cover degraded-environment paths that are realistic in operator use:
  controller unreachable, model missing, missing API key, network blip during
  export or provider call, and partial state already written when the failure
  hits.

### 93.3 High — Test durability, resume, and long-running-session recovery

- [ ] Add integration tests for **checkpoint → stop → restart → resume** on
  active sessions, including queued work, decisions, transcript state, and any
  pending follow-up tasks.
- [ ] Add crash-recovery tests for the executor / store boundary: interrupted
  task execution, partially-persisted task results, and replay after restart
  without duplicate work or corrupted queue state.
- [ ] Cover the context-budget lifecycle end to end: budget exhaustion,
  compaction trigger, compaction failure, and recovery once the session
  continues.
- [ ] Add explicit persistence/resume coverage for long-running flows that are
  currently unit-tested in pieces but not exercised as a whole.

### 93.4 High — Add isolation and security-oriented system tests

- [ ] Add tests proving the sandbox/workspace/worktree boundaries hold under
  pressure: path traversal attempts, symlink escapes, out-of-tree writes,
  temporary-file leakage, and cleanup after cancellation/failure.
- [ ] Add integration coverage for worktree lifecycle and git isolation:
  branch creation, temporary worktree setup/teardown, dirty-tree handling,
  merge/reconcile paths, and failure cleanup.
- [ ] Add system tests around the policy/permission boundary so "plan mode",
  destructive-command gates, and category-scoped tool access are verified in
  real flows rather than only at unit granularity.
- [ ] Treat these as regression guards for Phase 49's sandbox promise, not as
  optional hardening.

### 93.5 Medium — Cover advanced controllers and automation workflows

- [ ] Add integration coverage for the controller surfaces that currently have
  little or no non-unit protection: ``MCPController``,
  ``ArenaController``, ``TriageController``, and the extracted
  ``ExecutorController`` / ``WatcherController`` seams where real message flow
  matters.
- [ ] Add non-unit tests for git automation workflows: ``git_branch`` branch
  tracking, PR/open-feedback loops, and ``auto_commit`` message/trailer logic
  in realistic repositories rather than fake objects only.
- [ ] Add end-to-end coverage for at least one **triage → confirm → build
  improvement** path so the improvement workflow is tested across handoff
  boundaries, not only as isolated controller pieces.
- [ ] Add provider-routing / failover tests so a primary-provider problem does
  not silently strand the work loop when a fallback is configured.

### 93.6 Medium — Broaden the higher-level test portfolio

- [ ] Expand the **eval corpus** beyond the current happy-path examples with
  at least one more machine-oriented charm, one more custom/non-framework app,
  and one case that stresses relations / observability / operational actions
  more heavily than the current set.
- [ ] Add more **stateful e2e** scenarios: interrupted deploy, failed verify
  followed by debug task creation, improvement flows on an existing charm, and
  "user says no" / override branches that materially change the plan.
- [ ] Build **differential / metamorphic** checks where Cantrip should preserve
  invariants across providers or surfaces: stable task-graph validity, export
  shape, permission enforcement, and transcript/event consistency.
- [ ] Extend accessibility regression coverage beyond the current Web-only
  smoke test where feasible, and at minimum document the deliberate boundary
  if TUI accessibility remains manual.
- [ ] Where a "fuzz" or property style makes more sense than examples
  (workspace paths, provider payload normalisation, queue/task invariants),
  prefer that style over adding another list of hand-authored cases.
- [ ] Add **targeted traditional fuzzing** alongside the Hypothesis suite
  where coverage-guided or byte-oriented exploration is higher leverage than
  property tests alone: start with ``cargo-fuzz`` harnesses for
  ``charmlint-rs`` / ``quickpack-rs``, then add a small set of Python parser /
  export entrypoints such as transcript fence/export rendering and raw
  HTML/search-result parsers.  Keep this as an advisory or nightly lane rather
  than a default per-PR requirement unless it proves cheap enough.

### What this phase is *not*

- Not a vanity push for a single coverage percentage.  The problem is not that
  89% is too low; it is that the remaining uncovered and non-unit gaps cluster
  around failure, isolation, and recovery.
- Not a wholesale rewrite of the existing unit suite.  Keep the broad base;
  add the missing higher-confidence layers around it.
- Not a promise that every live/provider matrix case runs in default CI.  The
  aim is a balanced portfolio: cheap deterministic coverage in the main loop,
  with richer live/e2e paths still available where they earn their cost.

**Exit criteria:** the highest-value unit blind spots above are closed or
explicitly explained; failure-injection integration tests cover provider, tool,
and recovery paths that previously had no protection; restart/resume and
isolation behaviour are exercised end to end; advanced controller/git
automation flows have non-unit coverage; and the eval/e2e portfolio covers more
than the happy-path build/deploy story so a regression in failure handling or
durability is likely to be caught before release.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Unit hotspot backfill (93.1) | Phase 92.1 for the deterministic scan; existing TUI/unit harnesses | Mostly additive tests, with small seam tweaks where the code is hard to drive |
| Failure injection (93.2) | Existing integration/e2e harnesses; retry and structured-output surfaces from prior phases | Prefer reusable fake-provider / fake-tool helpers over one-off per-file harness code |
| Durability/resume (93.3) | Existing session store, persistence, queue, and compaction machinery | May surface small product fixes rather than test-only changes |
| Isolation/security (93.4) | Phase 49 sandboxing, Phase 44 worktrees, Phase 68 permissions | These are promise-keeping regression guards, not new product lines |
| Controllers/automation (93.5) | Phase 85 controller extraction, existing git/GitHub flows | Good candidate to share builders between unit and integration layers |
| Higher-level portfolio (93.6) | Existing eval/e2e/live suites; Phase 79 for future provider-matrix ambitions | Grow breadth without turning every scenario into an expensive live test |

**Discovered:** Test-suite review on 2026-04-30.  Findings: unit coverage is
strong overall (~89%), with the biggest blind spots concentrated in
``_scan.py``, TUI-heavy modules, and a handful of controller/git/acceptance
paths; non-unit coverage is much stronger for happy-path build/deploy flows
than for failure handling, durability, isolation, and advanced controller
workflows.

---

## Phase 94: Go Kubernetes Diagnostics Binary — Pod-Layer Insight for Charm Debugging

**Goal:** Implement the Kubernetes diagnostic gap identified in
[`design/K8S_TOOL.md`](design/K8S_TOOL.md) as a small, read-only **Go**
binary and wire it into Cantrip as a first-class typed tool.  The new
design document [`design/K8S_DIAGNOSTICS_BINARY.md`](design/K8S_DIAGNOSTICS_BINARY.md)
is the source of truth for scope, command shape, JSON contract, safety
boundary, and Python integration.

### 94.1 High — Ship the Go binary itself

- [ ] Add a new Go module under ``src/cantrip-kdiag/`` with a small,
  explicit package layout (`cmd/`, `internal/cli`, `internal/kube`,
  `internal/collect`, `internal/summarise`, `internal/output`) matching
  the design doc.
- [ ] Implement the three v1 commands from the design:
  ``summary``, ``pod``, and ``preflight``.
- [ ] Support kubeconfig/context loading, namespace selection, and
  bounded targeting by exact pod, Juju app, or Juju unit.
- [ ] Collect the initial read-only diagnostic set only: pods, container
  statuses, warning events, PVC state, previous log tails for crashed
  containers, and pod metrics when the metrics API is present.
- [ ] Emit deterministic JSON with an explicit schema version and crisp,
  documented exit codes for usage error, kubeconfig/context failure, API
  reachability failure, target-not-found, metrics unavailable, and
  internal error.

### 94.2 High — Integrate the binary into the Python tool layer

- [ ] Add a typed Python wrapper in ``src/cantrip/agent/tools/`` (likely
  ``k8s.py``) that invokes ``cantrip-kdiag`` via ``subprocess.run``,
  parses the JSON output, and returns a structured ``ToolResult`` with a
  concise caption plus the full report in ``data``.
- [ ] Register the new tool in ``build_tools()`` and scope its
  description/schema so the agent reaches for it only when Juju does not
  explain a pod-layer problem.
- [ ] Mirror the existing Juju-tool pattern for environment handling:
  bypass the subprocess sandbox, thread through ``KUBECONFIG`` /
  explicit context inputs, and fail clearly when the binary is missing.
- [ ] Decide whether v1 uses a single ``k8s_diagnostics`` tool with a
  mode parameter or a thin pair (summary vs pod drilldown); keep the
  external contract aligned with the Go commands rather than inventing a
  Python-only abstraction.

### 94.3 Medium — Teach the agent when to use it

- [ ] Update the Kubernetes diagnostic guidance so the agent prefers the
  typed tool over prescribing raw ``kubectl`` when the binary is
  available, while keeping the existing `fix-broken-juju-k8s` skill for
  substrate-rebuild flows and manual fallback.
- [ ] Add or update the relevant prompt/skill/tool guidance so the tool
  is used specifically for the documented gap cases:
  ``CrashLoopBackOff``, ``ImagePullBackOff``, ``OOMKilled``, PVC binding
  failures, and namespace-event clues that Juju does not surface.
- [ ] Keep the scope charm-focused and read-only; do not expose a raw
  generic Kubernetes command runner or write-path surface.

### 94.4 Medium — Validation, tests, and packaging hygiene

- [ ] Add Go tests for target resolution, warning synthesis, output
  shape, and the read-only collectors using fake clients where practical.
- [ ] Add Python unit tests for the wrapper tool covering happy path,
  missing binary, malformed JSON, non-zero exit codes, and missing
  kubeconfig/context.
- [ ] Decide the developer and CI build path for the binary (including
  where the built executable lives during tests) and document that path
  alongside the new subsystem rather than leaving it implicit.
- [ ] Add user/developer docs for the new tool surface only where the
  feature becomes externally visible; keep internal implementation notes
  in the design doc.

### What this phase is *not*

- Not a generic ``kubectl`` wrapper.
- Not a write path to the cluster (`apply`, `delete`, `patch`, `exec`,
  `port-forward`).
- Not a rewrite of other Cantrip native helpers in Go.
- Not a requirement to replace Juju-native debugging with Kubernetes
  debugging; the binary fills the specific gap where Juju's view stops.

**Exit criteria:** Cantrip can diagnose the common pod-layer failure modes
called out in ``design/K8S_TOOL.md`` through a first-class typed tool
powered by ``cantrip-kdiag``; the binary stays read-only and bounded; the
Python wrapper surfaces crisp structured output and failures; and tests
cover both the Go report contract and the Python integration.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Go binary (94.1) | `design/K8S_DIAGNOSTICS_BINARY.md`; Kubernetes client-go ecosystem | Keep the initial command set small and the contract explicit |
| Python integration (94.2) | 94.1; existing `Tool` / `ToolResult` conventions in `design/TOOLS.md` | Mirror Juju-tool subprocess patterns rather than shelling out through `run_command` |
| Agent guidance (94.3) | 94.2; existing Kubernetes skill content | Prefer typed-tool guidance without deleting the manual fallback story |
| Validation/docs (94.4) | 94.1 + 94.2 | Tests should lock the JSON contract and error handling in place |

**Discovered:** Follow-up design work on 2026-04-30 after reviewing
Cantrip's current features, planned features, and native-helper pattern
(``quickpack-rs`` / ``charmlint-rs``).  Verdict: Kubernetes pod-layer
diagnostics is the highest-value feature that is distinctly well suited to
a Go binary.

---

## Phase 95: Canonical Developer Surfaces — Launchpad, Snapcraft, and Charmcraft

**Goal:** Cantrip already showcases the core charm stack well, but
several high-leverage Canonical developer surfaces still sit outside the
agent's reach.  This phase turns the strongest first-party catalogue and
packaging surfaces into things the agent can actually use during charm
research, provider selection, and packaging flows — rather than just
mentioning them in docs.

### 95.1 Research and scope ✓

- [x] Broad product / technology survey written up in
  [`design/CANONICAL_SHOWCASE.md`](design/CANONICAL_SHOWCASE.md).
  Findings: Launchpad, Snapcraft, and Charmcraft are the
  highest-leverage first-party developer surfaces beyond the already-
  shipped charm stack; MAAS belongs to a substrate phase, Chisel to a
  packaging phase, and Ubuntu Pro / Landscape to an operational-
  readiness phase.

### 95.2 Marketplace descriptors and discoverability

- [ ] Ship documented marketplace / descriptor examples for
  **Launchpad**, **Snapcraft**, and **Charmcraft** MCP servers so a
  user can enable Canonical-native servers without reading design docs
  or inventing YAML from scratch.
- [ ] Decide the default exposure / safety story per server.  Search,
  info, and lint / analyse verbs should be read-only by default;
  publishing verbs (if exposed at all) require explicit allowlisting
  and the same confirmation posture as other destructive or external
  operations.
- [ ] Update the MCP docs so the Canonical servers are a first-class
  example alongside the generic Grafana / GitHub-style examples.

### 95.3 Agent-side adoption

- [ ] When a Launchpad server is configured, feed its results into the
  **Librarian** / `/search-charms` workflow so unpublished or
  in-progress Launchpad projects become first-class citations rather
  than a hidden parallel workflow.
- [ ] When a Snapcraft server is configured, use it in the
  inference-snap and provider-selection flows: enrich local snap
  discovery with store metadata, aliases, summaries, and supported
  channels rather than relying only on local enumeration.
- [ ] When a Charmcraft server is configured, use it as an optional
  second-opinion surface for `lint` / `analyse` in build and
  improvement flows, while keeping the built-in local tooling as the
  default fallback.

### What this phase is *not*

- Not a generic "marketplace everything Canonical ships" sweep.
- Not a Charmhub rewrite — Charmhub remains the primary charm-registry
  surface; Launchpad complements it.
- Not a publishing-by-default phase.  Read-path discovery comes first.

**Exit criteria:** a user who configures Canonical Launchpad,
Snapcraft, and/or Charmcraft MCP servers sees them in the docs, can
discover them via `/mcp marketplace`, and the agent uses them in charm
research, local-model discovery, and packaging flows without bespoke
prompting.

---

## Phase 96: Chiselled Rocks — Chisel-Aware Rockcraft Output

**Goal:** Cantrip already generates rocks for OCI-backed charms, but it
does not yet understand Canonical's chiselled-Ubuntu packaging story.
This phase teaches the agent when a workload is a good chiselled
candidate, how to generate that Rockcraft shape safely, and when to stay
with a fuller Ubuntu base for debugging or runtime reasons.

### 96.1 Eligibility rules

- [ ] Write the deterministic "is chiselled a good fit?" rubric:
  12-factor or otherwise simple container workloads, no shell-dependent
  runtime, no apt-at-runtime behaviour, package slices available, and a
  workable debug / support story.
- [ ] Record explicit blockers: workloads that expect a shell or
  ad-hoc OS utilities in production, opaque vendor install scripts,
  packages without the needed slices, or charm logic that would make the
  minimised filesystem shape too brittle.
- [ ] Decide whether the eligibility logic lives purely in skill /
  prompt guidance or deserves a small deterministic helper next to the
  existing Rockcraft tooling.

### 96.2 Generation and escape hatches

- [ ] Extend Rockcraft generation guidance so Cantrip can emit
  chiselled-rock examples when the workload passes the rubric, including
  a short explanation to the user about *why* the smaller base is safe
  here.
- [ ] Preserve a clear escape hatch back to ordinary Ubuntu bases when
  the workload needs shell tooling, the user prioritises operability
  over footprint, or the chiselled build fails for a slice-availability
  reason.
- [ ] Ensure the generated charm and rock wiring still compose cleanly
  with Pebble plans, health checks, and the existing 12-factor /
  custom-app flows.

### 96.3 Validation and user-facing docs

- [ ] Add tests / fixtures proving Cantrip's chiselled output still
  launches correctly and keeps the expected runtime files, entrypoints,
  and libraries.
- [ ] Update the relevant user-facing docs and examples so
  "Cantrip can build smaller, tighter rocks when appropriate" is a
  visible feature rather than an invisible prompt tweak.

### What this phase is *not*

- Not a blanket switch making every rock chiselled by default.
- Not a replacement for quickpack or charmcraft packaging paths.
- Not a packaging-minification contest detached from charm operability.

**Exit criteria:** for workloads that fit the rubric, Cantrip can
generate and explain a chiselled-Rockcraft path; for workloads that do
not, it cleanly falls back to the existing fuller-base path.

---

## Phase 97: Canonical Cloud Targets — MAAS, OpenStack, and MicroCloud

**Goal:** Cantrip's current environment story is strongest on local LXD
and Canonical K8s.  Canonical also ships substrate products that are a
natural fit for machine and infrastructure charm stories: MAAS for
bare-metal labs, OpenStack / Sunbeam for private-cloud targets, and
MicroCloud for compact local/private-cloud deployments.  This phase
decides what first-class support means for each and ships the
lowest-friction high-value pieces first.

### 97.1 Substrate-role design

- [ ] Write the design note that decides the role of each surface:
  **MAAS** as machine inventory / provisioning, **OpenStack / Sunbeam**
  as a target cloud for infra charms and demos, and **MicroCloud** as a
  compact private-cloud / edge lab.
- [ ] Decide how these surfaces relate to **Concierge** rather than
  bypassing it ad hoc.  The outcome may be extra presets, extra profile
  data, or documented MCP / tool integration — but not a second,
  conflicting environment abstraction.

### 97.2 MAAS path

- [ ] Decide whether the first MAAS surface is a built-in tool family,
  an MCP-first story, or a hybrid.  Start with safe read / prepare
  flows: list machines, inspect availability, and acquire / release
  capacity with explicit confirmation on any destructive step.
- [ ] Teach machine-charm workflows when MAAS is a better fit than local
  LXD and how to say so in design proposals, test plans, and runbooks.

### 97.3 OpenStack and MicroCloud profiles

- [ ] Add substrate-aware profiles or guidance for "target OpenStack"
  and "target MicroCloud" so infrastructure-charm work can tailor
  assumptions, companion charms, and acceptance guidance to those
  Canonical environments.
- [ ] Extend topology / bundle-style outputs so these substrates appear
  as first-class deployment contexts in generated design notes when
  relevant.

### 97.4 Examples and docs

- [ ] Ship at least one worked example for a MAAS-backed machine-charm
  workflow and one for an OpenStack- or MicroCloud-oriented
  infrastructure workflow.
- [ ] Document the boundaries clearly: when the phase gives actual agent
  automation vs when it gives substrate-aware guidance and runbooks.

### What this phase is *not*

- Not a promise that Cantrip itself bootstraps a private cloud from
  nothing.
- Not a replacement for the existing local LXD / k8s dev loop.
- Not an excuse to scatter substrate-specific one-offs through the
  prompt without a design note.

**Exit criteria:** a user asking for MAAS-, OpenStack-, or
MicroCloud-aware work gets substrate-specific guidance or automation
that fits Cantrip's existing environment story rather than a generic
"bring your own cloud" answer.

---

## Phase 98: Canonical Estate Operations — Ubuntu Pro and Landscape

**Goal:** Some Canonical products are best used not in the build loop,
but in Cantrip's **day-2** and **production-readiness** stories.
Ubuntu Pro and Landscape are the strongest examples: they matter when
Cantrip is auditing, improving, or operationalising charms for real
Ubuntu estates, not when it is merely scaffolding a demo.

### 98.1 Operational-readiness rubric

- [ ] Expand the operational-readiness guidance so the agent can ask
  whether a workload or deployment story should mention **Ubuntu Pro**
  (security maintenance, compliance posture, long-term patching) and/or
  **Landscape** (fleet management, patching, access management) when
  those are actually relevant.
- [ ] Keep the recommendations evidence-driven.  They should show up
  where the workload, substrate, or operator environment makes them a
  sensible Canonical recommendation — not as generic upsell text.

### 98.2 Improvement-mode outputs

- [ ] Add "Ubuntu Pro / Landscape opportunities" to the audit /
  improvement output alongside existing observability, backup, HA, and
  security findings when those Canonical products would materially
  improve the charm's production story.
- [ ] Provide consistent wording that distinguishes **recommended for a
  supported production estate** from **required for the charm to work**.

### 98.3 Detection and templates

- [ ] Where safe and cheap, detect hints that the operator already lives
  in a Pro / Landscape world (repo docs, deployment notes, packaging
  assumptions, estate-management references) and use that context in the
  generated runbooks.
- [ ] Add reusable templates or guidance snippets for charms that need
  production-hardening recommendations but no direct integration code.

### What this phase is *not*

- Not a commercial workflow or subscription-purchase flow.
- Not a mandate that every Cantrip-generated charm mention Pro or
  Landscape.
- Not a replacement for the existing security / observability /
  operational-readiness work.

**Exit criteria:** Cantrip's improvement and operational-readiness flows
can recommend Ubuntu Pro and Landscape in the right contexts with clear,
useful guidance and without making them feel bolted on.

---

## Phase 99: User-Facing Goal Lifecycle — Pause/Resume, Persistent Budget, Objective String

**Goal:** OpenAI's Codex CLI 0.128.0 added a ``/goal`` slash command
with a small but useful lifecycle: set an objective, pause and resume
autonomous work mid-run, persist the budget across restarts.  Cantrip
already covers ~80% of the value via its always-on autonomous loop, the
``/budget`` command (Phase 55.3), and the ``/ralph`` bounded
iterate-until-green loop (Phase 69.1).  What it lacks is *user-facing
control surfaces* for three small but real gaps:

1. **No ``/pause`` or ``/resume``.**  Internal ``Executor.pause()`` /
   ``Executor.resume()`` methods exist
   (``src/cantrip/agent/executor/core.py:424``) but aren't wired to
   slash dispatch.  Today the user can only ^C an active autonomous
   run, which loses chat context and forces a session reload.
2. **``goal_budget`` doesn't survive ``cantrip resume``.**  Phase 55.3
   ships ``/budget`` (``src/cantrip/agent/commands/budget.py``) but the
   ``GoalBudget`` instance isn't part of the SQLite session payload —
   the user re-specifies caps every time even though the rest of the
   state is restored.
3. **No first-class user-prose objective.**  Today the user's goal is
   reduced to ``--charm-name`` + ``--charm-type`` at startup.  Their
   actual goal sentence ("build a Postgres charm with COS plus Pebble
   notices") isn't stored, so Ralph's re-feed and any future
   goal-aware status surfaces work from a paraphrase rather than the
   user's words.

Three Codex ``/goal`` mechanics are explicitly **out of scope**:

- **A parallel goal-state machine** (``pursuing`` / ``paused`` /
  ``achieved`` / ``unmet`` / ``budget-limited``) that duplicates the
  existing ``WorkQueue`` + ``SubagentExitState`` semantics.  The
  status-bar projection in 99.4 reads from existing fields rather
  than adding a second source of truth.
- **LLM-based "is the goal achieved yet?" self-evaluation** at end of
  each turn.  This is the most-reported Codex ``/goal`` failure mode
  (overnight token burn).  Cantrip's planner draining a queue is a
  more tractable stop condition and ``/ralph N`` already gives a
  hard upper bound.
- **Auto-injected continuation / budget-limit prompt templates.**
  Cantrip's planner already drives next-task selection; a Codex-style
  continuation template would compete with it and fork
  ``design/PROMPTS.md``.

### 99.1 High — ``/pause`` and ``/resume`` slash commands

- [x] Add ``/pause`` and ``/resume`` to ``COMMAND_CATALOGUE`` in
  ``src/cantrip/agent/commands/slash.py`` with help strings that note
  CONFIRM tasks and chat keep working while the autonomous loop is
  paused.
- [x] Wire dispatch handlers that call the existing
  ``Executor.pause()`` / ``Executor.resume()`` methods.  Bare
  ``/pause`` pauses; ``/pause`` while already paused is a noop with a
  status message; mirror behaviour for ``/resume``.  Follow the
  ``/yolo`` dispatch pattern at ``src/cantrip/agent/commands/slash.py:1211``
  for tone, status messages, and `status_bar_changed` publishing.
- [x] Publish a ``status_bar_changed`` event so the TUI status
  indicator shows "paused" / "running" alongside the existing yolo /
  ralph badges.
- [x] Unit tests in ``tests/unit/agent/`` covering: dispatch
  toggles ``ExecutorController.user_paused``; redundant invocation is a
  noop; status-bar publication carries the right label; transient
  resume is skipped while user-paused.
- [x] Update ``docs/src/reference-cli.md`` (slash-command catalogue)
  and rebuild the rendered HTML via ``uv run python docs/src/_build.py``.

### 99.2 High — Persist ``goal_budget`` across ``cantrip resume``

- [x] Audit ``src/cantrip/agent/persistence.py`` save/load to confirm
  ``goal_budget`` is not in the saved session payload.
- [x] Extend the session schema (``src/cantrip/agent/persistence.py``
  and the SQLite migrations under ``src/cantrip/agent/store/``) to
  include the active ``GoalBudget``: iteration cap, prompt-token cap,
  completion-token cap, and the running spend totals.  (Spend totals
  reconstruct from the already-persisted ``token_usage`` table windowed
  by ``GoalBudget.started_at``, so the schema only adds the four cap /
  start-time fields.)
- [x] Backwards-compatible load: a session saved before this change
  loads cleanly with the cap defaulted to "none" — never crashes,
  never silently zeroes the budget.  Add a migration test.
- [x] Round-trip integration test: ``cantrip run`` with budget caps
  set, kill the process, ``cantrip resume`` shows the same cap in
  ``/budget`` output.
- [x] CHANGELOG entry under Unreleased noting the persistence change.

### 99.3 Medium — User-prose objective string on the session

- [x] Add an ``objective: str | None`` field to the persisted session
  state alongside ``charm_name`` / ``charm_type``.  Pick the
  CLI-injection shape (positional vs ``--objective`` flag) that fits
  the existing ``cantrip run`` argument layout without a breaking
  change.  (Chose ``--objective`` flag in the session-options group
  for parity with ``--web-port`` / ``--theme``; positional was already
  taken by the charm path.)
- [x] Slash: ``/goal <text>`` sets or updates the objective; ``/goal``
  with no args shows the current value plus the projection from
  99.4; ``/goal clear`` removes it.  Add to ``COMMAND_CATALOGUE``.
  (99.4 projection deferred to that phase; the bare ``/goal`` reports
  the stored objective today.)
- [x] Ralph re-feed (``src/cantrip/agent/ralph.py``) prefers the
  stored objective over the spec-derived paraphrase when present, so
  iterate-until-green loops use the user's words.
- [x] Tests cover: default empty, set/update/clear cycle, Ralph picks
  up the latest value across iterations, persistence across resume.
- [x] Update ``docs/src/reference-cli.md`` with the new flag and the
  ``/goal`` slash entry; rebuild HTML.

### 99.4 Medium — Status-bar projection of goal lifecycle state

- [x] Add a small helper (in ``src/cantrip/agent/state.py`` or beside
  ``goal_budget.py``) that projects current state into a Codex-style
  label: ``running``, ``paused``, ``done`` (queue empty and no
  active task), ``blocked`` (only blocked tasks remain), or
  ``budget-limited`` (latest budget event is
  ``GOAL_BUDGET_EXCEEDED``).  Read-only over existing fields — no
  new state, no new persistence.  (Landed as ``cantrip.agent.lifecycle``
  with a pure ``lifecycle_label()`` function; ``CantripAgent.lifecycle_label()``
  bridges it to live state.  Detects budget-limited by matching
  the ``Goal budget exceeded`` prefix on ``AgentTask.blocked_reason``,
  which is more reliable than reading the SQLite event log.)
- [x] Surface the label in the TUI status bar and the Web UI status
  indicator alongside the ``/yolo`` and ``/ralph`` badges.  (TUI
  swaps the existing ``loop_state`` reactive between the five labels
  with per-state CSS tints; Web UI gains a header chip
  (``#lifecycle-badge``) primed from ``/api/state`` and updated via
  the existing ``status_bar_changed`` event.)
- [x] Unit tests for the projection covering each label and the
  precedence ordering between them (e.g. ``paused`` beats
  ``blocked``; ``budget-limited`` beats ``running``).

### What this phase is *not*

- Not a new state machine.  Every label in 99.4 is a read-only view
  over existing executor / queue / budget fields.
- Not LLM-based goal-completion self-evaluation.  Cantrip never asks
  the model "is the goal achieved?" — ``done`` follows from an empty
  work queue.
- Not goal-aware continuation-prompt injection.  Cantrip's planner
  already drives next-task selection; a Codex-style continuation
  template would compete with it.
- Not a budget enforcement change.  Phase 55.3's ``GoalBudget`` stays
  the source of truth for caps; 99.2 only adds persistence.

**Exit criteria:** ``/pause`` and ``/resume`` toggle the autonomous
loop from chat; ``cantrip resume`` honours the previous ``/budget``
caps without re-specification; the user's free-text objective is
stored on the session and surfaces in ``/goal`` queries and Ralph
re-feeds; the status bar projects a single ``running`` / ``paused`` /
``done`` / ``blocked`` / ``budget-limited`` label using only the
existing field set.

---

## Phase 100: ``wait_for`` Tool — Typed Predicates Over Generic Stream Monitoring

**Goal:** Give the agent a first-class way to block on a *condition*
instead of either polling in a worker (burning context with each
status read) or blocking the whole turn on a sleep.  Today the agent
either calls ``run_command`` with a long timeout, or scripts an
``until ...; do sleep`` loop inline — both leak shell text into the
transcript and tie up the worker that owned the turn.  Claude Code
splits the same problem into two shapes; Cantrip should adopt the
useful half:

1. **One-shot wait** — *one* notification when a predicate flips
   (file appears, process exits, port opens, Juju app reaches
   ``active/idle``, ``make integration`` returns 0).  This is the
   high-value shape for the build/deploy loop: ``charmcraft pack``
   finishes, ``juju deploy`` settles, ``COS`` rolls out.
2. **Streaming watch** — *N* notifications, one per stdout line, for
   tail-and-grep patterns.  Cantrip's TUI already streams agent
   output and tool transcripts; the agent itself rarely needs a
   stdout stream because the durability layer reschedules turns
   instead of holding open connections.

This phase ships shape (1) only.  Shape (2) is a known follow-up that
requires conviction we don't yet have — defer behind named triggers
rather than implement speculatively.

A generic shell-based monitor is **explicitly out of scope** because
it invites the agent to leave timers running and burns transcript
context on uninteresting stdout lines.  Typed predicates avoid that
class of failure by construction.

### 100.1 High — ``wait_for`` tool with a closed predicate set

- [x] New module ``src/cantrip/agent/tools/wait_for.py`` registering
  a single ``wait_for`` tool.  Predicate is a tagged-union argument
  so the schema is enumerable rather than free-form shell.  Initial
  set:
  - ``file_exists`` — path becomes readable.
  - ``file_absent`` — path goes away (rollback / cleanup waits).
  - ``process_exited`` — PID terminates; reports exit code (best-effort:
    foreign PIDs return ``exit_code=None`` rather than fabricating a
    value, since ``waitpid`` only works for our own children).
  - ``port_open`` — TCP connect succeeds on host:port.
  - ``command_exits_zero`` — runs a *single* whitelisted command
    (``charmcraft``, ``juju``, ``make``, ``pytest``, ``test``)
    repeatedly until it returns 0.  No shell pipeline; argv only.
  - ``juju_app_active_idle`` — wraps existing
    ``juju_subprocess.wait_for_app`` (``src/cantrip/agent/tools/juju_subprocess.py:143``)
    so the agent stops scripting raw ``juju wait-for`` calls.
- [x] Hard ``timeout_seconds`` argument (required, capped at 1800s);
  the tool *always* returns within that bound with a clear
  ``timed_out`` field rather than running indefinitely.
- [x] Poll cadence picked by predicate type, not by the model:
  ``port_open`` / ``process_exited`` polls every 0.5s;
  ``command_exits_zero`` every 5s; ``juju_app_active_idle``
  delegates to ``juju wait-for --timeout`` (no Python-side polling);
  ``file_exists`` / ``file_absent`` every 0.5s.  No model-tuned
  knob.
- [x] ``ToolResult.caption`` summarises the outcome ("waited 47s for
  ``juju app prom`` to reach active/idle"), per the Phase 81 caption
  contract — every new tool must set a caption.  ``intro_caption``
  also overrides per predicate so the chat shows a present-continuous
  "Waiting for …" line while the call is in flight.
- [x] Integration with the worker model: ``wait_for`` runs as an
  ordinary tool inside the current turn.  No new background-task
  primitive; if the agent needs the wait to span turns, that's a
  scheduler concern (Phase 99 / executor pause), not a wait-for
  concern.
- [x] System-prompt guidance in
  ``src/cantrip/agent/prompts/system.md.j2`` pointing at ``wait_for``
  for "until X is true" needs, alongside a short anti-pattern note
  ("don't loop ``run_command sleep``").
- [x] Permission hook: ``command_exits_zero`` predicate goes through
  the same allow/deny machinery as ``run_command`` (Phase 80
  ``GovernancePolicy``) so a denied command in the active policy
  cannot be smuggled in via ``wait_for``.

### 100.2 Medium — Tests and reference docs

- [x] Unit tests in ``tests/unit/agent/tools/test_wait_for.py``
  covering each predicate's success, failure, and timeout paths plus
  the policy-deny path for ``command_exits_zero``.
- [x] One end-to-end test that drives ``wait_for(juju_app_active_idle)``
  against a fake ``jubilant.Juju`` surface so we catch contract drift
  if ``wait_for_app`` changes shape.  (Patches ``jubilant.Juju``
  directly rather than reusing a ``tests/conftest`` fake — none of
  the existing fakes covered the ``wait-for application --timeout Ns``
  call shape.)
- [x] ``docs/src/reference-tools.md`` gets a ``wait_for`` section with
  the predicate enum, timeout guidance, and a worked example
  ("wait for ``charmcraft pack`` to finish").  Rebuild HTML via
  ``uv run python docs/src/_build.py``.
- [x] CHANGELOG entry under Unreleased.

### What this phase is *not*

- **Not a generic ``monitor``-style stream tool.**  Tailing a log file
  and emitting per-line events is a separate shape with separate
  failure modes (silence-is-not-success, output-volume control,
  unbounded commands); revisit only if a real use case shows up.
  Named triggers: an agent task spends >30s scripting ``tail -f |
  grep`` patterns inline, *or* a subagent needs to react to events
  faster than the next turn boundary.
- **Not a shell-loop runner.**  ``command_exits_zero`` accepts argv
  only and gates the command name through the existing policy layer.
  No pipelines, no quoting, no ``until ...; do`` text reaching the
  shell.
- **Not a replacement for ``Executor.pause``.**  ``wait_for`` blocks
  the *current* tool call; it does not pause the autonomous loop.
  Phase 99.1's ``/pause`` covers the cross-turn case.
- **Not a scheduler / cron primitive.**  Recurring "every 5 minutes"
  needs are a routine concept, not a wait-for one.

**Exit criteria:** ``wait_for`` is a registered tool with the closed
predicate set above, every predicate has unit-test coverage of
success / failure / timeout, ``command_exits_zero`` honours the
active permission policy, and ``docs/src/reference-tools.md``
documents the tool with a worked example.  The system prompt nudges
the agent toward ``wait_for`` for "until X" needs.  Streaming-style
monitoring stays deferred behind two named triggers.

---

## Milestones

| Milestone | Phase | Definition |
|-----------|-------|------------|
| M0: Talking | 0 ✓ | CLI chat with Gemini + juju status |
| M1: First Charm | 1 ✓ | Flask app → running charm in 2 min |
| M2: Dev Loop | 2 ✓ | Fast iteration with trace debugging |
| M3: All Paths | 3 ✓ | 12-factor, custom, infra all working |
| M4: Autonomous | 4 ✓ | Agent works independently with visible task tracking |
| M5: Research-Driven | 5 | Agent proactively researches and proposes grounded designs |
| M6: Fast | 6 | Common charm build completes in under two minutes |
| M7: Showcase | 7 ✓ | Demo-ready with full ecosystem, testing, and publishing |
| M8: Local Models | 8 ✓ | Cantrip runs on local inference snaps with no cloud API |
| M9: Terraform | 9 | Cantrip generates and validates Terraform modules for charms |
| M10: Charm Improver | 10 | Cantrip audits and upgrades existing charms to modern standards |
| M11: Resilient Agent | 11 | Subagents commit, self-verify, and recover cleanly from failures |
| M12: Red/Green | 12 | Red/green TDD — integration tests first, agent iterates until green |
| M13: Demo-Ready | 13 | Every charm ships with runnable demo, captured output, and tutorial |
| M14: Full Transcript | 14 | Every session exportable as searchable HTML with full audit trail |
| M15: Web UI | 15 | Browser-based interface mirroring the TUI via shared event bus |
| M16: Security & Tracing | 16 | OWASP security events + clear manual tracing guidance |
| M17: Acceptance Tested | 17 | Cantrip deploys, exercises, and reports on every charm it builds |
| M18: Framework Decision | 18 ✓ | Evidence-based recommendation on build-vs-adopt for agent infrastructure |
| M19: Operationally Ready | 19 | Cantrip assesses and improves charms against Canonical's Operational Readiness Metrics |
| M20: Deep Introspection | 20 ✓ | Agent reads relation databags, config sources, secrets, and offers to diagnose issues autonomously |
| M21: Hardened Orchestrator | 21 ✓ | Formally verified state machine, protocol-injected services, noop detection, graceful shutdown |
| M22: Multi-Controller COS | 22 ✓ | COS observability works on both single-controller (K8s) and dual-controller (LXD + K8s) environments |
| M25: Code Health | 25 | All critical and high code-review findings resolved; `make check` green |
| M27: Provider Quality | 27 | Claude caching active; Gemini parallel tool calls correct; extended thinking available |
| M28: Robust Agent | 28 | SQLite concurrent writes safe; executor self-heals; subagent context managed |
| M29: Polished TUI | 29 | All screens functional; no blocking subprocess calls; dead features wired up or removed |
| M30: Complete Toolbox | 30 | Shell injection fixed; missing Juju/git tools available; existing tools hardened |
| M31: Great UX | 31 ✓ | Streaming responses; chat search; session resume; cost tracking visible |
| M32: Smart Planning | 32 | Compact prompt complete; dependency validation; watcher events all routed |
| M33: Expanded Skills | 33 ✓ | Existing bundle management; charm migration; multi-charm workspaces; interactive debug; benchmarking |
| M39: ACP Research | 39 | Written assessment of Agent Client Protocol as an alternative to direct LLM provider calls |
| M40: Safe Compaction | 40 | Compaction has cycle detection, retry budgets, and size validation — no infinite loops possible |
| M41: Provider Parity | 41 | All providers capture streaming usage; extended thinking available for Claude; accurate token counting; cost visibility; compaction monitoring |
| M42: GitHub Native | 42 | Cantrip triages issues, works on branches, opens PRs, and bootstraps repos — all with user approval |
| M44: Worktree Parallelism | 44 | Concurrent subagents run in isolated git worktrees with tested merge and revert paths |
| M45: MCP Client | 45 | Cantrip can attach third-party MCP servers with OAuth, elicitation, and category-scoped tool access |
| M46: User Hooks | 46 | Users configure pre/post lifecycle hooks with conditional filters; PreCompact can block compaction |
| M47: Best-of-N | 47 | High-value tasks optionally race multiple models and commit the test-pass-scored winner |
| M48: Multimodal Debug | 48 ✓ | Providers accept images; Grafana/Tempo/Juju-status rendering tools return PNGs the agent reasons about |
| M49: Sandboxed Shell | 49 ✓ | Untrusted subprocesses run under PID/mount namespaces with deny-rule and syscall hardening |
| M50: Skills Interop | 50 ✓ | Standard-format skills import and export round-trip; MCP-aware skills resolve dependencies at load time |
| M51: Team Research | 51 | Written assessment of whether and how Cantrip should support teams working on a charm, with architecture sketches and a next-step recommendation |
| M52: Durable Subagents | 52 ✓ | Subagent LLM turns and tool calls checkpoint into SQLite; interrupted tasks resume from the last completed step instead of re-burning tokens |
| M53: Knowledge-in-Markdown | 53 | Planner prompts and task descriptions live in Jinja2 templates; `planner.py` split along the deterministic / LLM seam; dev design docs cover tools, skills, and prompts |
| M54: Authored Docs | 54 ✓ | `docs/docs/` site rebuilds from committed markdown sources through `make docs`; no hand-authored HTML remains in the docs tree |
| M55: Awesome-Copilot Survey | 55 ✓ | Eight awesome-copilot patterns investigated end-to-end; each has a committed decision, prototype, or recommendation |
| M56: Juju Copilot Bundle | 56 | `canonical/skills` hosts a Juju-specific instruction/skill bundle derived from Cantrip's system prompt, with CI validation and a regeneration path |
| M57: Test Cleanup | 57 | Unit coverage ≥85%; zero test warnings; oversized unit files split; quickpack tests reorganised to match charmlint |
| M58: Rust Tested | 58 | `cargo test` runs in CI for both Rust crates; every `.rs` file above 60% coverage; regressions surface at unit-test time, not via spread |
| M59: Property Tested | 59 | Hypothesis-backed property tests cover the planner dependency graph, charmlint rule engine, quickpack jujuignore, and watcher status-diff |
| M60: Accessible Web UI | 60 | Web UI passes WCAG 2.1 AA: visible focus indicators, labelled controls, live regions for chat/status, overlays behave as modal dialogs; rodney/showboat regression guard in CI |
| M61: Slash Autocomplete | 61 | Typing ``/`` in the TUI surfaces a catalogue-driven suggestion popup; Tab completes the active verb; CLI readline gets the same catalogue for parity |
| M62: On-Theme Activity Labels | 62 | Status-bar and Web "Thinking..." literals replaced by randomly-selected spellcasting verbs (incanting, conjuring, brewing, …) so the UI matches the cantrip/juju theme |
| M63: Self-Update Check | 63 ✓ | PyPI polled at startup; TUI, Web, and CLI surface a non-blocking notice with filtered changelog and an installer-aware upgrade command when a newer Cantrip is published |
| M64: Polite Repo Bootstrap | 64 ✓ | Create-GitHub-repo offer moved out of the main chat and suggests ``<workload>-operator`` by default |
| M65: Right-Panel Tidy | 65 | TUI task panel audited and tightened; multi-model pane either earns its space or is retired |
| M90: Visual Topology | 90 | Right-panel multi-model pane and F8 graph screen treat the model as a visual topology — edges are first-class clickable objects with interface details, focus-fade dims unconnected apps, and a preset-bundle catalogue grounds layer grouping |
| M66: Transcript/Log Visible | 66 ✓ | Transcript and debug-log modals render their content (or a clear empty state) on every launch, with a smoke test guarding the fix |
| M67: Pi-Inspired Sessions | 67 ✓ | Session tree rewind/branch, mid-session ``/model``, ``cantrip run --print --json`` for scripts, and ``/share`` to secret gist — four gaps the Pi coding agent fills that charm authors also hit |
| M68: OpenCode Safety Rails | 68 ✓ | Snapshot-backed ``/undo``/``/redo`` for file changes, declarative ask/allow/deny permissions, markdown-defined user slash commands, and a session-level plan mode — four guardrails adopted from OpenCode that map onto Cantrip's existing subsystems |
| M69: Kimi Workflow Features | 69 | Bounded Ralph-Loop iterate-until-green, ``--yolo`` unattended switch, ``Ctrl-X`` shell mode, and Mermaid/D2 Flow skills — four Kimi CLI patterns that fit Cantrip's autonomous loop, skill system, and CI story |
| M70: Amp-Inspired Depth | 70 | Librarian subagent that searches Charmhub and Launchpad, Oracle tool for on-demand second-opinion reasoning, glob-conditional guidance in AGENTS.md / skills, prompt-based review Checks that layer on top of charmlint, and a Painter tool that generates a Charmhub-style ``icon.svg`` |
| M71: Aider Engineering Hygiene | 71 ✓ | Tree-sitter-backed repo-map with graph-ranked symbols, architect/editor two-model mode, auto-commit-per-turn with dirty-commit separation, and a per-edit ruff/ty/charmlint feedback loop |
| M72: Continue Context Providers | 72 | Indexed charm-ecosystem docs (``@docs juju|ops|charmcraft|rockcraft``), an ``@``-mention context-provider registry, ``embed`` and ``rerank`` model roles, and ``@problems`` diagnostics-as-pre-turn-context |
| M72b: Read-Only Code Intelligence | 72b | Exact workspace-symbol, go-to-definition, and find-references queries layered on repo-map and ``@``-providers, giving Cantrip precise code navigation without an IDE surface or write-capable refactors |
| M73: Goose Workflow Packaging | 73 | Parameterised retryable Recipes with sub-recipes, MCP Apps rendered as sandboxed iframes in the Web UI, JSON-schema-enforced structured responses, and declarative retry with shell validators |
| M74: Populated Charm Docs | 74 ✓ | Generated ``docs/`` tree is bridged with the Phase 13 root files, populated from real Phase 17 acceptance-test command/output capture, with an architecture page extracted from transcript design decisions and a troubleshooting page mined from the agent's resolved-error history |
| M75: Inline Tool Blocks | 75 ✓ | Every tool call renders as a one-line block in the TUI and Web chat with a success/failure colour cue, so trailing-colon preambles stop reading as broken speech |
| M76: Copy-Friendly Chat | 76 ✓ | Toad-inspired per-block copy affordances either ship (keybinding, slash command, OSC 52, or similar) or a written assessment in ``design/UI.md`` explains why the current flow is sufficient |
| M77: Reasoning Content Surfaced | 77 ✓ | OpenAI-compatible reasoning deltas (Kimi K2, DeepSeek-R1, GLM reasoning variants) are captured and rendered like Claude's extended thinking rather than silently dropped |
| M78: Observability Hardening | 78 ✓ | Cache cascades surface as visible warnings, Web UI shows cache metrics at parity with TUI, compaction stop-flags persist across session resume, and ``thinking`` payload is asserted on the wire for Claude + Gemini |
| M79: Eval Gates Prompt Changes | 79 | System-prompt edits trigger a per-provider LLM-in-loop smoke test that runs in CI against a cheap model, closing the "narrow eval missed a cross-model regression" gap described in Anthropic's April 23 postmortem |
| M80: Stacked Policies | 80 ✓ | `GovernancePolicy` + `compose_policies()` replace the single-level category filter; per-goal rate limit, JSONL audit trail, and in-code destructive-command gates ship together as the policy-allowlist layer in the defence-in-depth stack with Phases 46 / 49 / 55.3 / 55.5 |
| M81: Tool Caption Coverage | 81 ✓ | ``run_command``, the Juju tool family, and the acceptance/test reporters populate ``ToolResult.caption`` rather than relying on the Phase 75 fallback; coverage test forces the rich-caption-vs-fallback choice for new tools |
| M82: Pre/Post Tool Captions | 82 | Tools render an intro caption that updates in place to the post-call caption when the tool returns; the TUI and Web chat surface "running…" status without adding new chat lines |
| M83: Pause-and-Edit Research | 83 ✓ | Written decision (ship / defer / drop) on whether Cantrip's hard cancel should soften into a pausable, editable mid-turn affordance; verdict is *defer*, with queue-next-instruction sketched as the leaner follow-up shape against three named revisit triggers |
| M84: Deferred-Item Sweep | 84 | `design/DEFERRED.md` exists, every "Deferred:" entry across `ROADMAP.md` and `ROADMAP_ARCHIVE.md` is labelled fired / not-fired / dropped, and the next sweep is on the calendar so deferrals don't rot into forgotten todos |
| M86: K8s/kubectl Research | 86 ✓ | Written decision (typed tool, skill expansion, or stay-as-is) on whether the agent should grow first-class kubectl support for diagnostics and recovery paths the ``fix-broken-juju-k8s`` skill currently escalates to the user |
| M87: COS Coverage | 87 | Alertmanager, Catalogue-k8s, and Sloth gain skill-level guidance and worked examples at parity with Prometheus/Grafana; Parca/Pyroscope decision recorded in ``design/PROFILING.md`` (deferred to Phase 89 against four named triggers) |
| M88: Identity Platform | 88 | A user asking for "Canonical-Identity-Platform-backed login" gets a charm with correctly-wired Hydra relations, secret fabric, and a passing Phase 17 acceptance test |
| M92: Skill-derived Lint Rules | 92 | Six deterministic helpers — action-handler coverage, config-option coverage, charm-library semver, relation-data missing-guards, Pebble layer validation, harness-call inventory plus scenario-test event-shape coverage — ship as charmlint rule modules or standalone Cantrip tools, derived from existing skill bodies; affected skills shed their rule-recitation passages |
| M91: Canonical/skills Adoption | 91 ✓ | Four upstream 12-factor scripts (framework detect, rock-contract check, env-key inspect, preflight targets) ship as Cantrip tools with attribution and tests; ``twelve-factor`` skill body adopts the upstream checkpoint workflow and handoff payload; framework-specific contract tables inlined into the charm and rock skill bodies |
| M43: Memory | 43 | Cantrip learns per-charm and cross-charm lessons with citations, revalidation, user controls, and skill export |
| M99: Goal Lifecycle | 99 | `/pause` and `/resume` toggle the autonomous loop mid-run; `cantrip resume` preserves `/budget` caps; user-prose objective is a first-class session field surfaced via `/goal`; status bar projects running / paused / done / blocked / budget-limited |
| M100: Wait For | 100 | Typed-predicate ``wait_for`` tool with file/process/port/command/juju-app waits, hard timeouts, policy-gated commands, and reference docs; streaming-stream monitoring stays deferred behind named triggers |
