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

## Phase 7: Polish and Ecosystem ✓

**Goal:** TUI enhancements, advanced testing, full ecosystem integration.

### 7.1 TUI Enhancements
- [x] **Visual integration graph** (F8) — modal screen showing apps as bordered panels
  with status indicators, unit breakdowns, and a deduplicated relation section;
  highlights the user's charm with a star marker
- [x] Multiple model views (dev + COS side by side)
- [x] Log viewer (F3)
- [x] Trace viewer or Grafana deep links (F4)

### 7.2 Advanced Testing and Performance
- [x] **Performance skill** — identifies common charm performance pitfalls (blocking I/O
  in hooks, expensive status polling, unindexed relation data, oversized config)
- [x] **Load testing** — `GenerateLoadTestTool` (`generate_load_test`) produces
  Jubilant-based load tests measuring action throughput, config change settling time,
  and scaling behaviour; for web-facing charms with an HTTP port, also generates a k6
  script with ramp-up/sustained/ramp-down stages and latency/error-rate thresholds
- [x] **Benchmark harness** — `HookBenchmarkTool` (`hook_benchmark`) analyses `juju
  debug-log` output to extract hook execution times; computes per-hook statistics
  (min/max/avg/count); flags hooks exceeding a configurable threshold (default 5 s);
  produces a structured Markdown report with a summary table and slow-hook details;
  added to TEST tool allowlist
- [x] **Fuzz testing** — `FuzzTestTool` (`fuzz_charm`) reads `charmcraft.yaml` (or
  `config.yaml` + `actions.yaml`) to discover parameters, then generates randomised
  test cases with boundary values, type mismatches, injection strings, and edge cases;
  supports reproducible output via a `seed` parameter; produces a Markdown fuzz test
  plan; added to TEST and BUILD tool allowlists
- [x] **Chaos testing** — `ChaosTestTool` (`chaos_test`) performs destructive operations
  (kill-unit, remove-relation, scale-down, config-reset) on a deployed charm and waits
  for recovery to active/idle; produces a structured Markdown report with pre/post
  status; added to TEST tool allowlist
- [x] **Scaling tests** — `ScalingTestTool` (`scaling_test`) scales an application up
  to a target unit count, waits for settlement, optionally scales back to 1; verifies
  peer relations and leader election survive scaling; produces a report with status
  at each stage; added to TEST tool allowlist
- [x] **Test report** — `TestReportTool` (`test_report`) runs both unit and integration
  tests, aggregates results into a structured Markdown report with pass/fail counts,
  failure output excerpts, and an overall PASS/FAIL verdict; added to TEST tool allowlist

### 7.3 Integration Expansion
- [x] **COS integration — five of seven components delivered.**
  Prometheus (``prometheus_scrape`` interface in observability +
  infrastructure-charm skills), Grafana (``GrafanaDashboardProvider``
  guidance, ``GrafanaScreenshotTool``, F4 trace viewer deep-links),
  Loki (``LokiQueryTool``, ``log-forwarding`` relation guidance, F3
  log viewer), Tempo (``TempoQueryTool``, ``TempoWaterfallTool``,
  ``tracing`` relation), and Traefik-k8s (six skills cover
  ingress, twelve-factor, bundles, etc.) all ship.  Alertmanager
  and Catalogue-k8s are documented in
  ``src/cantrip/skills/observability/SKILL.md`` but lack
  integration examples and tooling — extracted to **Phase 87**
  rather than blocking this phase further.
- [x] **Sloth, Parca / Pyroscope — extracted to Phase 87.**  No skill,
  prompt, or tooling references the SLO-management or
  continuous-profiling tools today.  The work is real but distinct
  from the "showcase the existing observability stack" goal that
  closes Phase 7; tracked as a follow-on observability phase.
- [x] **Identity integration — extracted to Phase 88.**  Canonical
  Identity Platform (Hydra / Kratos / identity-platform-login-ui)
  needs its own design pass for credential fabric, secret
  relations, and OIDC relay — too substantial to land as a single
  Phase 7 bullet.  Tracked separately.
- [x] **Litmus chaos testing — superseded.**  Phase 7.2 shipped
  ``ChaosTestTool`` (``chaos_test``) with kill-unit, remove-relation,
  scale-down, and config-reset disruption types plus pre/post status
  capture and Markdown reporting; that covers the "chaos and quality
  assurance" exit criterion for Phase 7.  A future
  Kubernetes-native chaos surface (network faults, pod failures
  via the Litmus operator) belongs to a substrate-specific phase
  if and when an infrastructure-charm scenario demands it.

### 7.4 Charmhub Publishing
- [x] charmcraft upload integration
- [x] Release management
- [x] README generation

### 7.5 Advanced Workflows
- [x] Charm pairs (app + database deployed and related together)
- [x] Migration assistance (existing charm → improved charm) — see Phase 10
- [x] **Upgrade testing** — `UpgradeTestTool` (`upgrade_test`) refreshes a deployed
  application with a new `.charm` file, waits for recovery, captures pre/post status,
  checks debug-log for hook failures, detects status regressions, and reports an
  overall PASS/FAIL verdict with detailed comparison; supports resource attachments;
  added to TEST tool allowlist

**Exit criteria:** Showcase-ready demo of the full Canonical ecosystem. Agent autonomously
builds, tests, and publishes charms with full observability and quality assurance.

**Note:** Phase 7 was previously Phase 6. Renumbered when the Speed phase was inserted.

---

## Phase 36: Review Claude Code Best Practices for Cantrip ✓

**Goal:** Review the community-curated best practices at
`github.com/shanraisshan/claude-code-best-practice` and evaluate whether any
techniques would improve (a) how we build Cantrip itself (CLAUDE.md, workflow,
prompt structure, tool design) or (b) how the Cantrip agent operates (system
prompts, subagent guidance, tool patterns, conversation loop design).

This was a **research phase** with one small applied change.
Findings landed in
[`design/CLAUDE_CODE_BEST_PRACTICES.md`](design/CLAUDE_CODE_BEST_PRACTICES.md);
summary below.

### Decisions

- [x] **Source repo cloned and triaged.**  ~8.7 kloc across
  `best-practice/` (8 reference docs), `reports/` (10 analyses),
  `tips/` (9 video-tip summaries), `videos/` (6 talk
  summaries), and `implementation/` (5 examples).  Recommendations
  extracted into a punch list of ~120 items keyed by topic
  (CLAUDE.md size, hooks, slash commands, skills, subagents,
  MCP, settings, harness behaviour, agent design principles).
- [x] **Angle A (using Claude Code on Cantrip): one adoption.**
  Expanded the team-shared `.claude/settings.json` allow-list
  to cover the documented developer loop —
  `make check` / `unit` / `format` / `lint` / `coverage` /
  `all`, and `uv run pytest` / `ruff check` / `ruff format` /
  `ty` / `python -c` / `uv sync --dev`.  These commands run
  hundreds of times per session and were uniformly tripping
  permission prompts with no safety win.  No project
  `.claude/commands/`, `.claude/agents/`, `.claude/skills/`, or
  `.claude/hooks/` added — those would duplicate Cantrip's own
  agent / skill / subagent catalogues.
- [x] **Angle B (Cantrip's own agent design): no production
  code change.**  Most "Angle B" principles
  (subagents-as-context-isolation, research → synthesis →
  confirm → build, "don't use prompts for control flow",
  "build for the model six months from now", skill descriptions
  written for the model, cross-session memory) are already
  implemented.  Two genuinely-new Anthropic API capabilities —
  Programmatic Tool Calling and the tool-search-tool
  `defer_loading` pattern — recorded as watch-this items in
  `design/DEFERRED.md` with revisit triggers.
- [x] **Three deferred-item entries** added to
  `design/DEFERRED.md`: PTC for the Anthropic provider, the
  tool-search-tool `defer_loading` pattern, and a re-run
  trigger for the source-repo review itself.

### Revisit triggers

The source-repo review re-runs when **any** of:

1. Anthropic publishes Programmatic-Tool-Calling
   pricing / latency benchmarks against agentic-tool-use
   workloads (not pure eval suites).
2. Cantrip's typed tool catalogue passes ~60 entries
   (we are at ~35 today).
3. Claude Code ships a feature Cantrip's harness genuinely
   cannot replicate (e.g. cross-session multi-agent
   collaboration with a shared write surface — Agent Teams
   maturing out of experimental).
4. A Cantrip user reports concrete latency frustration that
   maps onto a recommendation rejected in this phase
   (`design/CLAUDE_CODE_BEST_PRACTICES.md` §3.3 / §4.3 are
   the rejection lists to reread first).

**Exit criteria met:** `design/CLAUDE_CODE_BEST_PRACTICES.md`
is the written review.  `.claude/settings.json` carries the
adopted allow-list expansion.  `design/DEFERRED.md` records
the three watch-this items so Phase 84's deferred-item sweep
re-evaluates them at the next audit cadence (2026-07-26).

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

## Phase 39: Agent Client Protocol (ACP) — Research ✓

**Goal:** Investigate using the [Agent Client Protocol](https://agentclientprotocol.com/)
as an alternative to driving an LLM directly. Instead of Cantrip calling a model
provider, it would drive an existing agent (e.g. Claude Code, or another
ACP-compatible agent) as its backend. This could let Cantrip leverage agents that
already have tool use, context management, and domain expertise built in.

This was a **research phase** — no production code changed.  Findings
landed in [`design/ACP_RESEARCH.md`](design/ACP_RESEARCH.md); summary
below.

### 39.1 Protocol familiarisation ✓

- [x] ACP spec read and documented: JSON-RPC 2.0 over stdio (local;
  remote HTTP/WebSocket still WIP), client = editor and agent =
  subprocess, baseline methods are `initialize`, `authenticate`,
  `session/new`, `session/prompt`, `session/load`, `session/set_mode`,
  `session/cancel`, with `session/update` and
  `session/request_permission` as agent→client notifications.
  Optional capability callbacks (`fs/*`, `terminal/*`) let the agent
  reach back into the client's filesystem and shell.  MCP integrates
  cleanly — the client can pass MCP servers to the agent during
  `session/new`.  See `design/ACP_RESEARCH.md` §1.
- [x] Feature mapping to `LLMProvider` done: ACP's session is roughly
  one `Subagent.run()`, prompt turn roughly one `complete()` round
  with tool execution, `stopReason` maps to `SubagentExitState`.
  The gap table (ACP concept → Cantrip analogue) is in §2.3.
- [x] Task-model gap documented: ACP plans are per-turn, Cantrip's
  `WorkQueue` is global; ACP has no "ask the user mid-turn"
  primitive; ACP's permission model (`session/request_permission`)
  has no analogue in Cantrip tools, which just run.  §2.3.

### 39.2 Candidate agents ✓

- [x] Agent survey landed (§3): Claude Code via
  [`claude-agent-acp`](https://github.com/zed-industries/claude-agent-acp)
  (Apache-licensed, TypeScript, wraps the Claude Agent SDK — not a
  subprocess spawn of Claude Code), plus Gemini CLI, Codex CLI,
  GitHub Copilot, Goose, Cline, OpenCode, OpenHands, Cursor,
  Augment Code, and ~20 more.  ACP Agent Registry went live
  January 2026 (JetBrains + Zed distribution).
- [x] Per-candidate notes: Claude Code adapter is the most
  interesting because its tool suite overlaps heavily with
  Cantrip's *implement*/*debug* subagents and it's actively
  maintained.  Goose is a natural cross-over with Phase 73.
  Python SDK exists (`agent-client-protocol` on PyPI, async base
  classes, Pydantic models) — Pydantic friction is flagged for
  future implementation phases (§3.4).
- [x] Claude Code feasibility assessed: viable via Option B
  (subagent backend).  Gains over direct Anthropic API calls are
  *tool access* (the agent's built-ins run alongside / instead of
  ours), not model quality.  Cost model changes because billing
  moves to the user's Anthropic account.

### 39.3 Integration sketch ✓

- [x] Three integration shapes drafted and evaluated (§4):
  - **A. ACP-as-`LLMProvider`** — the original sketch; breaks on
    the pivotal finding that ACP agents execute their own tools,
    while `LLMProvider` expects to return tool calls for Cantrip
    to execute.  Not recommended.
  - **B. ACP-as-subagent-backend** — replace the Subagent loop for
    specific task categories with an ACP session.  Most promising.
    Buys access to the remote agent's tool suite end-to-end while
    Cantrip's planner, queue, hooks, and race stay in charge.
    Costs: real engineering (probably a Phase-47-sized effort),
    tool duality (either lose Cantrip's charm tools on ACP tasks
    or re-expose them as MCP servers), race-feature composition
    problems, billing changes.
  - **C. Cantrip-as-ACP-agent** — the inverse shape, exposing
    Cantrip to Zed/JetBrains users via the Registry.  Credible
    but a different project; flagged so it isn't confused with A
    or B.
- [x] Architectural questions catalogued (§4.4): tool bridging
  via MCP, permission policy via Phase 46 hooks, worktree
  isolation (leans on Phase 49 sandboxing), telemetry / event-bus
  translation, cancellation flow.
- [x] Autonomous-loop impact sketched: Option B routes specific
  `AgentTask` categories through an `ACPSubagent` sibling class;
  the rest of the work queue is unchanged.

### 39.4 Decision and write-up ✓

- [x] Findings document at `design/ACP_RESEARCH.md`.  Verdict:
  **interesting, not urgent.**  Don't build speculatively; revisit
  Option B when a concrete trigger appears — a user asks for it,
  subagent evaluation scores indicate tool-heavier agents would
  help, or the ACP remote transport stabilises.  Revisit Option C
  when a non-trivial number of users want to drive Cantrip from
  an editor.
- [x] Cheap readiness steps recorded (§5.3): add the doc to
  CLAUDE.md's reference list, tag `LLMProvider` with a comment
  noting tool execution stays in Cantrip, monitor Python SDK 1.0.
  None of those count as "starting implementation".
- [x] No follow-on phase opened — the decision is "defer pending
  trigger", not "proceed to implementation".

**Exit criteria met:** `design/ACP_RESEARCH.md` is the written
assessment.  The document gives enough detail (protocol concepts,
Cantrip mapping, three integration shapes with tradeoffs, concrete
triggers) to decide that Phase 39 closes without opening a
follow-on implementation phase.

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

## Phase 51: Team Collaboration — Research ✓

**Goal:** Investigate what Cantrip could do to support a *team* working on
a charm rather than an individual operator.  Every assumption in the
codebase today is single-user: one laptop, one concierge-prepared local
Juju environment, one session, one decision log, one memory scope, one
set of approvals.  This phase decides whether the right answer is a
thin shared-git workflow (Phase 42 already covers most of that), a
shared Cantrip server with per-user sessions backing common state, or
a real-time collaborative agent with live presence — and produces a
written recommendation.

This was a **research phase** — no production code changed.  Findings
landed in [`design/TEAM_COLLABORATION.md`](design/TEAM_COLLABORATION.md);
summary below.

### Decisions

- [x] **Ship the thin shape's small additions as Phase 51b.**  The
  highest-leverage gap for the small (2–5) charm-authoring-team
  archetype is memory divergence between teammates' laptops; the
  fix is opt-in git-tracked ``.cantrip/shared/memory/`` plus
  shared decisions log plus a human co-author trailer next to the
  existing ``Cantrip <noreply@aotearoa.dev>`` line.  ~190 LOC
  + ~70 LOC tests + a docs page; no schema migration; no auth
  surface.  Could land alongside v1.0 or as a v1.0.x follow-up.
- [x] **Defer the medium shape (shared Cantrip server) behind
  named adoption triggers (Phase 51c).**  No demand signal in
  the repo today — no commit, CHANGELOG entry, issue, or
  transcript points at a team gap.  The medium shape is a
  1500–2500-LOC schema-and-server change with a security
  boundary, justified only when a real team adopts Cantrip and
  asks for state the thin shape cannot provide.
- [x] **Declare the heavy shape (real-time collaborative
  session) a non-goal.**  No peer ships this for an LLM agent
  session; Cursor's Canvases come closest but operate on
  artefacts, not the agent's reasoning loop.  Order-of-magnitude
  more cost than the medium shape against zero demand.
- [x] **Two side findings opened as separate phases.**  The
  research surfaced (a) the charm-improvement skill has no
  guard against deploying to a production controller — an
  existing safety hole independent of team work, opened as
  Phase 10b; and (b) Phase 46 hooks shipped without operator
  identity in the payload, capping role-based policy that any
  future team shape could express, opened as Phase 46b.
- [x] **Code-grounded mapping recorded** in
  ``design/TEAM_COLLABORATION.md`` §1: every place the
  single-user assumption lives in code, with file:line
  citations across schema (no operator field on ``Message``,
  ``Decision``, ``MemoryEntry``, ``AgentTask``, transcript
  rows), Web UI (localhost-only bind, single ``CantripAgent``
  singleton, broadcast event bus), session model (charm-path
  keyed, no creator), CONFIRM/hooks/attribution surfaces.
- [x] **Peer survey recorded** in §4: Cantrip sits in the
  local-plus-git-share bucket with Aider, Goose, and Claude
  Code; cloud-first agents (Copilot Workspace, Cursor cloud,
  Windsurf Command Center) require the security and billing
  boundary Cantrip lacks; Continue's Hub is the closest hybrid
  shape and the natural reference for a future Phase 51c.

### Revisit triggers

Phase 51c — *Shared Cantrip Server* — opens when **any** of:

1. **A real team adopts Cantrip and requests shared state.**  At
   least one team of 2+ humans uses Cantrip for one or more charms
   for at least a month and reports (issue, transcript, email)
   that the thin shape is insufficient — typically: shared
   dashboard, cross-laptop session handoff, or non-originator
   approvals.
2. **A Canonical-internal team commits to using Cantrip for a
   production charm.**  Brings audit, attribution, and approval
   requirements that the thin shape does not satisfy.
3. **A peer product ships a self-hostable per-team server that
   normalises the medium shape across the AI-coding-tools
   market.**  The cost calculus shifts when matching the market
   becomes the default expectation rather than a custom build.

When 1 or 2 fires, the implementation phase opens with §5.2's
scope as the deliverable and §1's mapping as the change list.
GitHub OAuth (uses Phase 42's existing ``gh`` dependency) is
the preferred auth model.

**Exit criteria met:** ``design/TEAM_COLLABORATION.md`` is the
written assessment.  Verdict is "thin shape ships as 51b, medium
shape defers behind triggers, heavy shape is a non-goal."  Two
side-finding phases opened (Phase 10b, Phase 46b) for
independent safety / hook-payload work surfaced by the research.

**Discovered:** While mapping single-user assumptions, the
charm-improvement skill's lack of a production-controller guard
surfaced as an existing safety hole that hurts solo users today
and would hurt teams more.  Independent of the team-collaboration
verdict; opened as Phase 10b.

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
- [ ] Conflict policy: textual git merge.  Document in the
  how-to that conflicts on the same key get resolved at the file
  level by whoever pulls last; no in-app conflict UI.  Tracked
  alongside 51b.4 docs.

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

## Phase 10b: Charm-Improvement Production-Controller Guard ✓

**Goal:** Stop the charm-improvement skill from deploying test
charms to a production controller by default.  Today
``skills/charm-improvement/SKILL.md`` instructs the agent to
deploy via ``jubilant.Juju()`` against the *current* controller —
whichever the local ``juju`` CLI defaults to.  If that's a
production controller (registered earlier with ``juju register``
for an unrelated purpose, then left as default), the agent will
deploy without warning.  See
[`design/TEAM_COLLABORATION.md`](design/TEAM_COLLABORATION.md)
§8.1 for how this surfaced.

This is a safety patch, not a redesign.  Phase 10's existing
charm-improvement pipeline stands; this only adds a confirm gate
in front of mutating Juju calls when the target controller looks
non-local.

### 10b.1 Heuristic default ✓

- [x] Detect controllers that are not the local
  concierge-prepared one — cloud type ``localhost`` / ``lxd``,
  ``microk8s`` / ``k8s`` whose API endpoints point at loopback
  (``127.0.0.1``, ``[::1]``, ``localhost``) or a snap-managed
  socket (``/var/snap/microk8s/...``).  Anything else flips a
  ``ControllerKind.NON_LOCAL`` flag at controller-resolution
  time (``src/cantrip/agent/controller_safety.py``).
- [x] Charm-improvement-mode tools that mutate (``juju_deploy``,
  ``juju_relate``, ``juju_refresh``, ``juju_destroy_model``,
  ``juju_remove_application``) require ``confirmed=true``
  before executing when the current controller is non-local.
  Refusal message names the controller and its cloud so the
  operator sees what they're about to touch.

### 10b.2 Explicit production list ✓

- [x] Settings-file field ``production_controllers: [str]`` in
  ``~/.config/cantrip/settings.json`` lets the operator name
  controllers that always require explicit confirm regardless
  of cloud type.  Belt-and-braces with the heuristic for cases
  where the heuristic under-classifies (e.g., a remote
  controller on a private network that *looks* local).
- [x] When a controller name matches the production list, the
  refusal message escalates language ("Refusing to run … against
  **production controller** `foo`") so the operator notices.

### 10b.3 Tests ✓

- [x] Unit tests for the heuristic classifier — local clouds
  pass through, non-local clouds get flagged
  (``tests/unit/test_controller_safety.py``).
- [x] Unit tests for the gate firing across all five tools
  (``tests/unit/test_juju_tools.py::TestControllerSafetyGate``).
- [x] Test covers the explicit-list override and the
  ``confirmed=true`` bypass.

**Exit criteria:** Charm-improvement runs against a non-local
controller emit a CONFIRM.  Settings field documented in
``docs/docs/reference-cli.html``.  CHANGELOG entry.  ``make
check`` passes.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Heuristic (10b.1) | Phase 22 controller enumeration | Reads the existing controllers list |
| Explicit list (10b.2) | Phase 46 settings schema | New settings key |
| Tests (10b.3) | 10b.1, 10b.2 | Both code paths covered |

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

## Phase 65: TUI Right-Panel Review — Task Panel and Multi-Model Pane ✓

**Goal:** The right panel of the TUI hosts three widgets in a
vertical stack: ``TaskChecklistWidget`` (``#task-checklist``),
``CharmTreeWidget`` (``#charm-files``), and
``MultiModelStatusWidget`` (``#juju-status``).  Two of them still
don't carry their weight: the task panel looks odd (inconsistent
indentation / grouping between preflight, pinned, and category
sections — details obscure titles, collapsed rows don't line up
with expanded ones), and the dev-vs-COS multi-model pane rarely
shows information worth the screen real estate it occupies.

This phase is a *review-and-fix* pass, not a rewrite.  The output
is a short written audit of what's wrong on each widget, then the
specific small fixes that follow.

### 65.1 Medium — Audit the task panel ✓

- [x] Drove the right panel under Textual's Pilot through ten
  scenarios (empty / preflight running / preflight done / mid-build
  with pinned ACTIVE+FAILED+BLOCKED + subagent phase / mid-build
  expanded detail / all-done / four multi-model modes) and captured
  both SVG screenshots and a flat text dump of every rendered
  ``Static`` under ``tmp/audit_phase65/scenarios/``.  The harness at
  ``tmp/audit_phase65/drive_right_panel.py`` is re-runnable.
- [x] Wrote the findings to ``design/RIGHT_PANEL_AUDIT.md``.
  Initial Finding A (a stale-children leak in
  ``_refresh_display``) was later retracted as a false alarm caused
  by the harness adding a duplicate preflight group on top of the
  one ``_start_prepare`` already registers; once the harness was
  fixed, the rendering was clean without intervention.  Findings
  B–G survived: ``_format_detail`` double-indent, pinned header
  visual indistinguishability, pinned ``Category · Title`` vs
  category ``Title`` format mismatch (collision is hypothetical,
  documented but not patched), three-line collapsed-group rendering,
  ``cos_expanded`` reactive without a watcher, and the multi-model
  pane wasting ``1fr`` while no model is connected.
- [x] Each finding shipped as its own commit:
  - **E** ``feat(tui): collapse fully-DONE category groups to a
    single row``
  - **C** ``feat(tui): give the pinned 'In progress' header its
    own emphasis``
  - **B** ``fix(tui): stop double-indenting expanded task detail``
  - **F** ``fix(tui): wire watch_cos_expanded so direct sets
    repaint``
  - **G** ``feat(tui): hide multi-model pane while no model is
    connected``

### 65.2 Medium — Decide what the multi-model pane should show ✓

- [x] Decision logged in ``design/RIGHT_PANEL_AUDIT.md`` finding G:
  hide the pane entirely while neither model is connected; once a
  model attaches, render the dev section as before; keep the
  collapsed-COS one-line summary as the default when both are
  attached; expand on click, identical to today.  Each section
  also hides individually when its own status is ``None`` so a
  connected dev model alone doesn't carry an empty COS section
  underneath.
- [x] Reworked ``MultiModelStatusWidget`` to match: the widget
  toggles its own ``display`` from the existing ``watch_dev_status``
  / ``watch_cos_status`` watchers, the ``Not connected`` /
  ``Not deployed`` Statics are gone (they only ever appeared in the
  now-hidden state), and a regression test pins the
  hide-while-empty contract.

### 65.3 Low — Spacing and consistency ✓

- [x] Right-panel CSS swept against ``cantrip.tcss``: dropped the
  duplicate ``height: auto`` / ``max-height: 50%`` on
  ``#task-checklist`` (the widget's ``DEFAULT_CSS`` already carries
  them), dropped the redundant ``height: 1fr`` on ``#charm-files``
  (``max-height: 50%`` caps it anyway), and switched
  ``#juju-status`` from ``1fr`` to ``auto`` so the pane sizes to
  its content (and takes zero space when hidden).

### What this phase is *not*

- Not a redesign of the task data model.  Categories, statuses,
  pinned rules all stay as they are.
- Not a Web-UI counterpart — Web follows in a later phase once
  the TUI answers are clear.

**Exit criteria:** written audit of the task panel committed
(``design/RIGHT_PANEL_AUDIT.md``, including a retraction of
Finding A so the dead end is visible to future readers); each
surviving finding (B, C, E, F, G) resolved in its own commit; the
multi-model pane self-hides while no model is connected and
otherwise behaves as before.  Full unit suite (6,196 tests) green
after the sweep.

---

## Phase 67: Pi-Inspired Session and Scripting Features ✓

**Goal:** Pi (``pi.dev``) is a minimal, extension-first coding agent.
Its core is deliberately small; features other agents bake in
(MCP, subagents, plan mode, permission gates) are packages.  A
walk of its landing page and command reference surfaces four
capabilities that Cantrip does not have today and that fit the
existing architecture cleanly.  Cantrip is not going to become a
general-purpose agent — we keep the charm focus — but each of the
items below addresses a gap a charm author already hits.

Four candidates, in rough priority order:

1. **Tree-structured sessions with rewind and branch.**  Pi stores
   each session as a tree and exposes ``/tree`` to navigate back
   to any prior node and branch from it.  Cantrip today stores a
   linear transcript in SQLite (Phase 14) and supports resume
   (Phase 31).  Rewind/branch is the single most useful missing
   piece: when the agent goes down the wrong path after a bad
   steering message, the only recovery today is to start over.
   With a tree, the user jumps back to the message before the
   bad turn and re-steers.  This reuses the existing transcript
   schema; the addition is parent-pointer metadata on each turn,
   a ``/branch`` or ``/rewind <turn-id>`` command, and a TUI
   view that lets the user pick a node.
2. **Mid-session model switching.**  Pi exposes ``/model``,
   ``Ctrl+L`` (switch), and ``Ctrl+P`` (cycle favourites).
   Cantrip already supports many providers (Phase 27, 41) and
   ``/arena`` for A/B, but has no way to say "finish this session
   on a cheaper model" without quitting and restarting.  The
   provider layer is already pluggable; this is a ``/model``
   command plus a hotkey in the TUI chat widget and a ``favorite
   models`` config list.
3. **Non-interactive print mode with JSON event stream.**  Pi's
   ``pi -p "query"`` returns a single-shot answer and
   ``--mode json`` streams events to stdout for scripts.
   Cantrip's CLI (``src/cantrip/cli.py``) is a REPL; there is no
   ``cantrip run --print "charm this flask app"`` for CI or
   shell pipelines.  The event bus (``cantrip.ui.events``) already
   carries typed events; a ``--json`` flag that serialises those
   to stdout gives scripting parity with the TUI.
4. **Session share to GitHub gist.**  Pi's ``/share`` uploads the
   exported session as a secret gist and returns a URL.  Cantrip
   already has ``/export`` (HTML, Markdown, JSONL).  Adding
   ``/share`` is a thin wrapper around the existing HTML exporter
   plus ``gh gist create`` — the GitHub integration (Phase 42)
   already authenticates ``gh`` for PR work, so credentials are
   in place.  Small and high-leverage for "look at what the
   agent just did" conversations.

Two Pi features are explicitly **out of scope**:

- **Extension package install** (``pi install npm:@foo/…`` /
  ``pi install git:…``).  Cantrip has the skills system
  (Phase 33, 50) and MCP servers (Phase 45); adding a third
  extension surface would fragment the ecosystem.  If the skill
  system ever needs a git-based install path, that belongs in
  Phase 50 (Skills Ecosystem Interop), not here.
- **Full SDK / RPC embedding mode.**  Pi is a library as much as
  a CLI; Cantrip is an app.  Exposing a public SDK is a much
  bigger commitment than the print-mode event stream covers, and
  we have no use case yet.

### 67.1 High — Session tree: rewind and branch ✓

- [x] Audited ``src/cantrip/agent/store.py``, ``core.py``,
  ``transcript/export.py``, and ``context.py`` for linear-session
  assumptions: ``load_messages`` did ``ORDER BY id``;
  ``load_state`` walked the result as a flat list; export and
  ``transcript_tail`` did the same; the compaction path operated on
  the in-memory list (which is rebuilt branch-aware now, so it gets
  the right slice for free).  Findings drove the schema and resume
  changes below.
- [x] Added ``parent_turn_id`` (nullable; ``NULL`` = root) to
  ``messages`` plus an index on ``parent_turn_id``.  ``session``
  gained ``active_head_message_id``.  v12 migration backfills the
  parent chain row-by-row so existing transcripts read as a
  degenerate linear tree, and points the head at the last existing
  message.  The index is created in a post-migration step so
  ``executescript`` doesn't hit a column-not-yet-added error on
  pre-v12 databases.  No ``session_id`` column on messages — the
  store is single-session per ``.cantrip`` file (``CHECK (id = 1)``
  on the session row).
- [x] ``/branch [turn-id]`` rewinds the active head to the given
  turn (or the parent of the most recent user turn when no
  argument is supplied), then rebuilds ``state.messages`` from
  ``load_active_branch``.  Off-branch rows stay in SQLite — they
  remain reachable through ``/tree`` and ``--branch`` re-export.
  ``/undo`` continues to delete via ``delete_messages_from``,
  which now rewinds the head to the parent of the deleted leaf so
  the next ``record_message`` doesn't dangle.
- [x] ``/tree`` ships in two forms.  The shared markdown form lists
  every persisted turn grouped under its parent, marks the active
  branch with ``*``, and exposes turn ids the user can pass to
  ``/branch``.  The TUI surface intercepts the verb and opens
  ``TreePickerScreen`` instead — an ``OptionList`` modal whose
  Enter result round-trips through ``handle_branch`` so the
  activate / rebuild logic stays centralised.
- [x] ``export-transcript`` now defaults to the currently active
  branch and accepts ``--branch <turn-id>`` to walk a different
  leaf.  ``load_active_branch`` gained an explicit ``head``
  parameter to back the new selector; off-branch rows stay
  exportable when the user wants them.
- [x] ``tests/unit/test_transcript_branching.py`` covers the round
  trip: head advance, branch/rewind round-trip, ``/undo``-style
  delete rewind, dangling-head tolerance on resume, ``/branch``
  with explicit and implicit turn ids, ``/tree`` rendering with
  active-branch markers, the TUI picker's option-id stability, the
  v11→v12 migration, the active-branch default on export, and
  ``--branch`` walking an explicit leaf.
- [ ] **Deferred: ``@@`` prompt affordance.**  The Amp-style
  cross-session picker needs a session registry Cantrip doesn't
  yet maintain (``~/.config/cantrip/sessions.json`` or similar)
  so ``@@`` can find sessions outside the active charm directory.
  In-session ``@T-<id>`` would be a smaller win but the spec is
  about *prior* sessions, so shipping an in-session-only version
  would mis-set expectations.  Re-open when a session registry
  lands or when concrete user reports of "wish I could quote that
  branch I had two days ago" arrive.

### 67.2 Medium — Mid-session model switching ✓

- [x] ``/model`` slash command in
  ``src/cantrip/agent/slash_commands.py``.  No argument: prints
  the active provider + model (plus the light provider when
  configured) and the switch syntax.  With argument: parses
  ``provider`` or ``provider/model`` (splitting on the *first*
  ``/`` so Fireworks slugs like
  ``fireworks/accounts/fireworks/models/kimi-k2p6`` work).  Five
  providers accepted (``gemini`` / ``claude`` / ``fireworks`` /
  ``openrouter`` / ``inference-snap``); ``openai-compatible`` is
  excluded because it needs a ``--base-url`` that doesn't fit
  the slash syntax — error message points at restarting with
  ``--provider openai-compatible --base-url ...``.  ``ProviderError``
  and ``ValueError`` during construction surface as
  ``_Failed to switch model: ..._`` without tearing down the
  session; the original provider stays active when the swap
  fails.
- [x] ``CantripAgent.switch_model(name, model=None)`` in
  ``src/cantrip/agent/core.py``: constructs via
  ``create_provider``, replaces ``self.provider`` atomically,
  rebuilds ``_light_provider`` via same-family
  ``resolve_light_provider`` (dropping any CLI-configured hybrid
  — documented), updates ``_context_manager.update_context_window``
  with the new window, invalidates ``_tools_cache`` /
  ``_tool_map_cache`` / ``_auto_writer_cache`` so next access
  rebuilds them with the new provider.  Cache accumulators
  (``cache_creation_tokens`` / ``cache_read_tokens``) survive the
  swap — they're session totals, not per-provider.
- [x] New ``model_switched`` event on ``ui_events``
  (``provider`` / ``model`` / ``previous_provider`` /
  ``previous_model`` / ``context_window``) published after each
  swap.  TUI's ``_update_model_info`` already polls every 5 s so
  the model bar catches up automatically; the event is there for
  listeners that want instant refresh.  Per-model cost breakdown
  in ``cantrip/cli.py`` already groups by model name in the
  usage store, so nothing extra was needed.  A ``model_switched``
  transcript event is also written via ``SessionStore.record_event``
  when a store exists.
- [x] ``docs/src/reference-cli.md`` gains a *Mid-session model
  switching* section under the slash-command catalogue; HTML
  regenerated via ``make docs``; parity checked via
  ``make docs-check``.
- [x] Tests: ``TestSwitchModel`` (4 cases) on the agent side —
  provider/window swap, cache invalidation, event emission,
  construction-error preserves the old provider.
  ``TestModel`` (6 cases) on the slash-command dispatcher —
  bare prints active, bare surfaces light provider, unknown
  provider names the known set, provider-only uses default
  model, ``provider/model`` parses on the first ``/`` only,
  ``ProviderError`` surfaces cleanly.
- [ ] **Deferred: TUI hotkey + favourites cycling.**  ``Ctrl+L``
  is already bound to ``clear_chat`` (classic terminal muscle
  memory — rebinding would surprise users).  ``favorite_models``
  needs a config-surface addition.  File as a follow-up when a
  concrete ergonomic case surfaces; the slash command covers the
  primary value today.

### 67.3 Medium — Non-interactive print mode ✓

- [x] Added ``cantrip run --print "<goal>"`` (alias ``-p``) to the
  ``run`` subparser, branching on ``args.print_goal`` in
  ``main._run`` before TUI/Web/CLI dispatch.  Runs the
  autonomous loop without a TUI; prints final assistant text
  (or the JSON stream) and exits when the work queue drains
  via the new ``cantrip.print_mode.run_print`` entrypoint.
- [x] Added ``--json`` to stream every
  ``cantrip.ui.events`` payload as NDJSON on stdout — one event
  per line, ``{type, data, timestamp}`` shape using
  ``Event.to_json``.  ``docs/docs/reference-cli.html`` documents
  the schema (`#print-events` anchor) covering all 19 event
  types as a supported public surface.  Combined with
  ``docs/docs/howto-print-mode.html`` for the task-oriented
  guide.
- [x] CONFIRM-tasks behaviour: print-mode refuses-and-exits
  non-zero with a human-readable list of pending confirmations
  by default.  Two refusal points: an up-front check on
  resumed-session state, and a post-drain re-check that catches
  CONFIRM tasks created mid-run.  ``--yolo`` (Phase 69.2) is
  the explicit opt-in that auto-approves the upstream ``ask``
  permissions; CONFIRM tasks generated by other paths still
  block (yolo flips only ``ask``).  ``_drain_queue`` short-
  circuits when a CONFIRM appears so the run doesn't hang
  forever on an unresolvable confirmation.
- [x] ``tests/unit/test_cli_print_mode.py`` — 30 cases covering
  the NDJSON line shape, the human-readable progress lines, the
  CONFIRM-task refusal logic (both up-front and mid-run), the
  drain-loop timeout branch, exit-code propagation
  (DONE/FAILED/BLOCKED), provider-error and KeyboardInterrupt
  paths, plus the argparse plumbing for ``--print``,
  ``--json``, and ``-p``.

### 67.4 Low — Session share to gist ✓

- [x] ``/share`` in the slash-command catalogue runs the existing
  HTML renderer (``transcript.html.render_html`` over a
  ``transcript_export.load_transcript`` payload), writes to a
  descriptive tempfile (``cantrip-session-<charm>-<ts>.html``),
  and launches ``gh gist create --desc "<description>" <file>``
  via ``asyncio.create_subprocess_exec``.  Returns a
  ``SlashResult`` with a ``"Uploading session as a secret gist…"``
  prelude and a followup coroutine so the UI stays responsive.
  Deviation from the roadmap: the command omits ``--public=false``
  because ``gh gist create`` already defaults to secret — adding
  the flag is redundant and tripped some older ``gh`` versions.
- [x] Graceful fallbacks: no ``gh`` in ``$PATH`` → prints the
  local tempfile path plus a copy-pasteable ``gh gist create``
  command the user can run themselves; ``gh`` present but
  exit-non-zero (typically auth failure) → surfaces stderr
  verbatim plus the same retry command and ``gh auth login``
  hint.  ``OSError`` / ``FileNotFoundError`` mid-launch also
  fall through to the retry-command branch so a transiently
  unreachable ``gh`` doesn't eat the transcript.  Never raises
  through to the dispatcher — every error path returns a
  human-readable string.
- [x] ``docs/src/reference-cli.md`` gets a *Share session as a
  gist* section under the slash-command catalogue; HTML
  regenerated via ``make docs``; parity checked.
- [x] Tests: ``TestShare`` (6 cases) on ``test_slash_commands.py``
  covering missing charm-path, missing ``.cantrip`` file,
  followup wiring, happy-path gist URL, ``gh``-missing fallback,
  and auth-failure retry hint.

### What this phase is *not*

- Not a rewrite of the transcript layer.  67.1 adds one column
  and one relationship; everything else stays.
- Not a public Cantrip SDK.  67.3 ships a stable event-stream
  format *on stdout* for scripts.  Embedding Cantrip as a library
  is a separate decision.
- Not a plugin marketplace.  Skill and MCP install paths stay
  where they are.
- Not "match Pi's UX".  Cantrip stays domain-specific; we cherry-
  pick what charm authors benefit from.

**Exit criteria:** (a) a user can rewind a session to before a
bad steering message and branch a new path, with the original
branch still reachable; (b) ``/model`` swaps the active provider
mid-session and the cost tracker keeps accurate per-model
totals; (c) ``cantrip run --print --json "<goal>"`` runs
unattended, emits a documented event stream, and refuses to
bypass pending confirmations; (d) ``/share`` uploads the current
session as a secret gist in one step, with a clean fallback
when ``gh`` is unavailable.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Session tree (67.1) | Phase 14 (transcripts), Phase 31 (resume) | Biggest item; land first so later items use branched sessions |
| Model switching (67.2) | Phase 27, 41 (multi-provider), Phase 47 (arena plumbing) | Independent of 67.1 |
| Print mode (67.3) | Phase 64 (CONFIRM tasks) | Needs the confirmation model to decide the block-or-approve rule |
| Share to gist (67.4) | Phase 14 (export), Phase 42 (``gh`` auth) | Thin wrapper; last |

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

## Phase 70: Amp-Inspired Depth — Librarian, Oracle, Scoped Guidance, Prompt Checks ✓

**Goal:** Amp (``ampcode.com``, Sourcegraph's frontier coding
agent) leans hard into three ideas that the charm-authoring
workflow would benefit from: invoking a *different* model for
hard one-off questions rather than running the whole session on
it, searching *other* codebases to learn from them, and giving
teams a way to encode review judgment that sits alongside
deterministic linters.  Four candidates stand out after filtering
against Phase 67 (Pi), Phase 68 (OpenCode), and Phase 69 (Kimi),
and against what Cantrip already has.

Five candidates, in rough priority order:

1. **Librarian subagent for Charmhub and Launchpad.**  Amp's
   Librarian searches public and private GitHub/Bitbucket
   repositories to answer "how did *someone else* solve this?"
   Cantrip operates on the active charm repo plus Phase 42
   GitHub tools, but has no primitive for "find the five
   existing charms that already use Pebble layers for an LDAP
   sidecar" — a query a human charmer makes constantly.
   Charmhub publishes a searchable index; Launchpad hosts the
   source.  A read-only subagent that queries both, filters to
   high-quality charms (maintained, 12-factor-or-ops, has
   tests), and returns excerpt+citation is the single most
   charm-specific feature on Amp's landing page.
2. **Oracle — on-demand second-opinion model.**  Amp's
   ``Oracle`` routes one prompt to a stronger reasoning model
   (their current pick is a GPT-5 variant) and returns the
   answer without committing the session to it.  Cantrip has
   Phase 47 (best-of-N racing) and ``/arena`` (Phase 31 A/B
   compare), but neither covers the "stop, ask the big model
   one architecture question, resume on the current model"
   pattern.  Cheap when used sparingly, high-leverage for
   Research-phase design decisions.
3. **Glob-conditional guidance in AGENTS.md / CLAUDE.md.**
   Amp's guidance files can include ``globs:`` frontmatter so
   a rule only enters the prompt when a matching file is in
   context (e.g. ``metadata.yaml``-specific tips only load for
   metadata work).  Cantrip's ``AGENTS.md`` / ``CLAUDE.md``
   and Phase 33 skill frontmatter are unconditional — every
   rule pays the token tax every turn.  Conditional loading
   cuts prompt bloat with a one-line frontmatter change.
4. **Checks — YAML prompt-based review rules.**  Amp reads
   ``.agents/checks/*.md`` with frontmatter (``name``,
   ``description``, ``severity-default``, ``tools``, optional
   file-glob scoping) and surfaces them during code review.
   Distinct from Cantrip's ``charmlint`` (Phase 24) which is a
   deterministic rule engine: Checks are *prompts*, applied by
   an LLM, for rules that don't reduce to AST patterns ("does
   this charm handle the secrets-changed event idempotently?",
   "is the ``install`` hook doing too much?").  A charm team
   codifies its review voice once; every PR gets it applied.
5. **Painter — icon generation for the charm.**  Every charm
   on Charmhub ships an ``icon.svg`` at the project root; it's
   what the Charmhub catalogue lists, what the Web UI shows
   against ``juju status`` applications, and what appears on
   the charm's page.  Authors today either hand-roll one in
   Inkscape or pay a designer; many charms ship with the
   default placeholder.  Amp's ``Painter`` (Gemini 3 Pro
   Image) generates and edits images with up to three
   reference images for style guidance.  A charm-scoped
   variant — "generate an icon for a charm that wraps
   ``<workload>``, Charmhub style (square, flat, simple,
   readable at 64×64)" — fills a real authoring gap and
   fits Phase 48's multimodal direction.  This was mistakenly
   out-of-scope in an earlier draft of this phase.

Five Amp features are explicitly **out of scope or deferred**:

- **Thread handoff as an explicit alternative to compaction.**
  Interesting idea — a clean fork+summary instead of in-place
  compression — but Phase 40 (Safe Compaction) already landed
  and Phase 67.1 (session tree rewind/branch) covers the "cut
  here and continue on a new trunk" ergonomics.  Revisit only
  if compaction proves unrecoverable in practice.
- **Permission delegation to an external binary.**  A fourth
  outcome alongside Phase 68.2's allow/ask/deny.  Not adopting
  now: enterprises are a later audience and delegation adds
  substantial surface area (subprocess, JSON contract, audit
  trail).  Re-open once 68.2 ships and real requests for
  external policy arrive.
- **``amp permissions test`` dry-run command.**  Genuinely
  useful but tiny; fold into Phase 68.2 rather than making it
  its own bullet here.  (Adding to 68.2's checklist below.)
- **Toolboxes (``AMP_TOOLBOX`` directory of executables).**
  MCP stdio servers (Phase 45) already cover the same space
  with a richer protocol and standard discovery.  A second,
  simpler plugin surface would fragment the ecosystem — the
  same reasoning that excluded Kimi's ``plugin.json``.
- **``@@`` thread references and ``$$`` incognito shell.**
  Small UX additions.  ``@@`` overlaps with Phase 67.1 (the
  branched-session picker).  ``$$`` (run a shell command but
  hide its output from the agent) is a niche privacy affordance
  on top of Phase 69.3 shell mode — revisit there if the need
  shows up.

### 70.1 High — Librarian: Charmhub and Launchpad cross-charm search ✓

- [x] New ``TaskCategory.LIBRARIAN`` — Cantrip's pattern is one
  ``Subagent`` class with a category-keyed tool whitelist and
  a per-category guidance file, so a new "subagent" is a new
  category.  Whitelist (read-only): ``charmhub_search``,
  ``charmhub_info``, ``charmhub_fetch``, ``launchpad_search``,
  ``launchpad_fetch``, ``web_fetch``, ``web_search``, plus the
  read-only fs tools (``read_file``, ``list_directory``,
  ``grep``, ``glob``, ``virtual_file_*``).  No write/edit/run
  tools.  Guidance lives in
  ``src/cantrip/agent/prompts/subagent/librarian.md`` and is
  loaded into ``_CATEGORY_GUIDANCE`` like every other category.
  Routes through the light provider via ``_LIGHT_CATEGORIES``.
- [x] ``charmhub_search`` enhanced to surface quality signals
  on every hit: ``last_release_date`` (from
  ``default-release.channel.released-at``), ``risk`` and
  ``channel`` (from ``default-release.channel.{risk,name}``),
  ``publisher_validation`` (from ``result.publisher.validation``),
  and ``source_url`` (from ``result.links.source``).  The new
  ``_quality_flags`` helper distils these into a short
  vocabulary (``recently-maintained`` / ``stale``,
  ``channel-stable`` / ``channel-edge``,
  ``publisher-canonical`` / ``publisher-verified``) that the
  Librarian renders inline in the search output.  Stale =
  released >12 months ago.
- [x] ``charmhub_fetch`` clones a charm's upstream source via
  ``git clone --depth=1 --filter=blob:none`` into
  ``~/.cache/cantrip/charm-library/charmhub/<name>/``.  Picks
  the URL from ``result.links.source`` (falls back to
  ``issues`` then ``website`` so a charm with only an issue
  tracker still resolves).  Writes a ``_cache_meta.json``
  sidecar with the fetched-at timestamp + revision; returns a
  navigable top-level listing capped at 30 entries.  Cache TTL
  is 7 days; pass ``force=true`` to refetch.  ``git`` absence
  surfaces a clean error rather than a traceback.  Override the
  cache root with ``CANTRIP_CHARM_LIBRARY_DIR`` for sandboxed
  CI runs.
- [x] ``launchpad_search`` + ``launchpad_fetch`` (new
  ``cantrip.agent.tools.launchpad`` module) cover projects
  that haven't been published to Charmhub.  Search hits
  ``api.launchpad.net/devel/projects?ws.op=search&text=…``;
  fetch follows the project's VCS field — Git projects clone
  from ``git.launchpad.net/<name>``, Bazaar projects surface
  a clear refusal with the web link so the user can browse.
  Both share the ``charm_library`` cache helper with the
  Charmhub fetch.
- [x] Cache helper ``cantrip.agent.tools.charm_library``:
  ``cache_root()``, ``entry_path(source, name)``, ``meta_path``,
  ``read_meta``, ``record_fetch``, ``is_fresh`` — single source
  of truth for cache layout, freshness, and metadata.  Path
  segments are flattened (``foo/bar`` → ``foo-bar``) to keep
  the layout one-level deep and prevent traversal-shaped
  attacks.
- [x] ``/search-charms <query>`` slash command runs Charmhub
  and Launchpad search in parallel via ``asyncio.gather`` and
  renders both blocks under one combined Markdown header.  No
  source clone is triggered from the slash; the agent invokes
  ``charmhub_fetch`` / ``launchpad_fetch`` if it needs the
  source.  Failures on either side surface inline so the other
  side's results still render.  Wired into
  ``COMMAND_CATALOGUE`` + ``SHARED_VERBS`` so the
  catalogue-drift test stays green; ``help_text`` documents
  the verb under the slash-command catalogue.
- [x] Output contract documented in the Librarian guidance
  (``prompts/subagent/librarian.md``): every hit emits
  ``## <name>`` + ``- **source_url**`` + ``- **why_this_matches**``
  + ``- **quality_flags**`` + ``- **snippet**`` so the primary
  agent can cite verbatim.  ``why_this_matches`` requires
  reasoning so the tools surface ``quality_flags`` and the
  agent fills in the rest.
- [x] Planner stays aware of the new category — the planner
  templates inject ``_VALID_CATEGORIES`` derived from
  ``TaskCategory``, so the LLM planner can queue
  ``librarian`` tasks naturally.  Snapshot tests refreshed
  for the +11-char drift in each of the four planner prompts.
- [x] ``tests/unit/test_librarian.py`` (32 cases): LIBRARIAN
  whitelist + guidance + light routing; quality-flag
  derivation across every signal permutation;
  ``charmhub_search`` end-to-end with the new fields;
  ``charm_library`` cache (env override, name flattening,
  sidecar round-trip, fresh / expired / missing / corrupt
  freshness checks); ``charmhub_fetch`` (cache hit, missing
  source link, 404, happy-path clone with sidecar verification,
  git-missing error path); ``launchpad_search`` (happy path,
  empty results, HTTP error); ``launchpad_fetch`` (Bazaar
  refusal, no-VCS error, Git happy path); ``/search-charms``
  slash dispatch (empty args usage line, followup wiring,
  combined render, single-backend failure, catalogue
  membership).
- [x] Documented in ``docs/docs/howto-charm-library.html`` —
  what the Librarian can and can't do, the cache layout +
  override env var, manual ``/search-charms`` walkthrough
  with the quality-flag table, the output contract, and how
  the Librarian gets invoked autonomously.  Card added to
  ``docs/src/index.md``; entry added to the howto sidebar
  in ``docs/src/_site.yaml``.

**Deferred:**
- Filtering on "has ``src/charm.py``" / ops-vs-reactive
  *post-fetch* — the spec mentions this as a quality filter
  but the cleanest implementation reads the cached source
  after a fetch.  Today the agent can do this manually with
  ``read_file`` + ``glob`` against the cache; folding it into
  ``charmhub_fetch`` as an automatic post-clone scan is a
  small follow-up worth doing once the Librarian sees real
  use.
- Charm-tarball download via the Charmhub ``download`` URL
  rather than git-clone of source — the tarball contains the
  *built* artefact (``manifest.yaml``, packed wheels) and
  doesn't include ``src/`` until very recent revisions.
  Source-via-git is the right surface for the Librarian's
  read-source use case.

### 70.2 High — Oracle: on-demand second-opinion model ✓

- [x] New primary-agent tool ``oracle_consult(question: str,
  context_hint: str = "")`` in
  ``src/cantrip/agent/tools/oracle.py``.  Spins up a one-shot
  provider call on a configurable "oracle" model (default
  ``claude/claude-opus-4-7`` with reasoning on; overridable
  via ``state.oracle_provider_name`` / ``state.oracle_model``),
  injects a compact context bundle (active charm task, last
  six messages capped at 800 chars each, optional caller
  ``context_hint``, the question), and returns the answer plus
  the response usage and an estimated USD cost.  No tools are
  given to the oracle call — it's a pure reasoning query.
  ``thinking_budget=8000``, ``max_tokens=4096``,
  ``temperature=0.2``.
- [x] The oracle call *does not* enter ``state.messages`` on
  the main session — it returns a ``ToolResult`` like any
  other tool, so the main context stays focused.  The
  transcript (Phase 14) captures the full oracle prompt
  + response + usage + cost as an ``oracle_consult`` side
  event so nothing is lost for audit; missing-store and
  refused-call paths are best-effort and don't fail the tool.
- [x] Per-turn budget ``state.oracle_max_calls_per_turn``
  (default ``1``) resets at the top of each conversation turn
  in both ``_run_conversation_loop`` and the streaming variant
  via ``state.oracle_calls_this_turn = 0``.  Per-session cap
  ``state.oracle_max_session_cost_usd`` (default ``$2``)
  accumulates ``estimate_cost`` results across the session.
  Exceeding either returns a structured tool error naming the
  exhausted budget and how to raise it; counters stay untouched
  on a refused call.
- [x] Distinct from Phase 47 (best-of-N racing) and ``/arena``
  (A/B compare): Oracle is the *one prompt, one answer,
  continue* pattern.  Documented side-by-side in
  ``docs/docs/explanation-race.html`` (sidebar label updated
  to "Multi-model patterns") with a three-column comparison
  table, an ``#oracle`` section covering defaults, budget
  model and rationale, and an ``oracle_consult`` entry in the
  transcript-events catalogue.  Tool catalogue updated under
  ``docs/docs/reference-tools.html``.
- [x] Prompt guidance in
  ``src/cantrip/agent/prompts/system.md.j2`` under "Consulting
  the oracle" names the four use cases the tool earns its
  keep on (charm-architecture, security-relevant design,
  library-vs-custom trade-offs, reactive→ops migration) and
  the three it doesn't (syntax lookups, routine implementation
  steps, obvious yes/no).
- [x] ``tests/unit/test_oracle.py`` (13 cases) — happy path
  (provenance footer, cost accounting against Opus 4.7
  pricing, state-driven model overrides, data payload), no
  main-context contamination, per-turn cap blocks second call
  and resets on simulated turn boundary, per-session cost cap
  refuses up-front, empty-question rejection, transcript
  side-event recording (with-store, without-store,
  refused-call).  Stubbed provider factory keeps tests off
  real money.

**Deferred:**
- ``settings.oracle_model`` config-file surface — the
  ROADMAP draft mentioned a settings layer that doesn't exist
  yet in Cantrip; runtime overrides via ``state.*`` cover the
  sticky-per-session use case today.  When a generic settings
  file lands (Phase 68.2 permission YAML is the closest
  analogue), point ``state.oracle_*`` defaults at it.
- A ``settings.oracle_max_calls_per_turn=0`` "off" knob — the
  current implementation already supports this (cap of zero
  refuses every call), but no slash command exposes the
  toggle.  File a follow-up if a user wants ``/oracle off``.

### 70.3 Medium — Glob-conditional guidance frontmatter ✓

- [x] Extend the skill frontmatter loader to recognise a
  ``globs:`` field.  Accepted as a YAML list or a comma-
  separated string; coerced via ``_coerce_string_list``
  alongside ``tools`` and ``mcp_servers``.  Guidance is
  included in the system prompt's ``<available_skills>``
  block only when at least one current-turn file path
  matches.  AGENTS.md / CLAUDE.md auto-load was *not*
  reachable without a separate architectural change
  (today AGENTS.md is a developer file and CLAUDE.md is
  generated per charm but never re-read).  Folded down to
  "skills only" for this phase; revisit if a future task
  starts loading either file into the prompt.
- [x] "Current-turn file path" predicate, defined in
  ``design/PROMPTS.md`` and implemented in
  ``CantripAgent._current_turn_files``: the union of (a)
  files cited by recent fs tool calls (existing
  ``_collect_recent_file_citations`` from the memory
  writer, 20-message window); (b) path-shaped tokens in
  the last six user messages
  (``_extract_user_mentioned_files``, regex-based, no
  fs-existence requirement so a "edit metadata.yaml"
  request loads the metadata skill *before* the file
  exists); (c) the active task's title / description.
- [x] Backwards-compatible default: skills without a
  ``globs:`` key stay unconditional.  ``format_for_prompt``
  with ``current_files=None`` (the legacy call shape)
  bypasses filtering entirely so existing callers stay on
  the historical "all skills always" behaviour.
- [x] Examples shipped on six bundled skills:
  ``scenario-tests`` (``tests/unit/**, src/charm.py,
  src/**/charm.py``), ``jubilant-tests``
  (``tests/integration/**``), ``adding-config``
  (``config.yaml, charmcraft.yaml, metadata.yaml,
  src/charm.py, src/**/charm.py``), ``adding-actions``
  (``actions.yaml, charmcraft.yaml, metadata.yaml,
  src/charm.py, src/**/charm.py``),
  ``relation-data-design`` (``metadata.yaml,
  charmcraft.yaml, src/charm.py, src/**/charm.py,
  lib/**``), ``harness-migration`` (``tests/unit/**,
  tests/test_*.py``).  Broad-applicability skills
  (``charmcraft``, ``observability``, ``find-bugs``,
  ``charm-debug``, …) intentionally remain unconditional.
- [x] Observability: ``CantripAgent._record_skill_filtering``
  writes a ``skill_filter`` transcript event with
  ``loaded``, ``skipped``, and ``files`` whenever the
  filter outcome changes — deduplicated against the
  previous turn via an in-memory signature so a stable
  session stays quiet.
- [x] ``tests/unit/test_conditional_guidance.py`` (30 cases)
  — frontmatter parsing (YAML list, comma-string, absent,
  malformed); glob matcher (bare basename, extension
  wildcard, ``**`` zero-or-more, ``**`` middle, anchored
  out-of-tree, no-charm-root, short-circuit, no-paths);
  ``format_for_prompt`` filtering (no-files-bypass,
  matching, non-matching, multi-glob-one-match,
  empty-files-still-filters); ``filtering_report``
  loaded/skipped split; ``_extract_user_mentioned_files``
  (basenames, relative paths, backticks/quotes, version
  strings, arbitrary words with dots, dedup, empty); and
  agent-level transcript event recording (first-filter,
  dedup-on-unchanged, re-emit-on-change,
  no-event-when-no-globbed-skills).
- [x] Documented in ``design/PROMPTS.md`` (new
  *Glob-conditional guidance* section: predicate
  definition with the three sources, anchoring rules,
  observability) and ``design/SKILLS.md`` (frontmatter
  schema gains ``globs:``, ``tools:``, and ``mcp_servers:``
  fields plus a *Glob-conditional loading* section with
  matching rules and the "when not to use globs"
  guidance).

### 70.4 Medium — Prompt-based review checks

- [x] New file type: ``.cantrip/checks/*.md`` (repo),
  ``~/.config/cantrip/checks/*.md`` (user), and
  ``src/cantrip/checks/*.md`` (bundled defaults — third
  layer not in original spec but needed so the three example
  checks can ship with Cantrip).  YAML frontmatter: ``name``,
  ``description``, ``severity``, ``globs``, ``tools``.  All
  fields except ``name`` and ``description`` are optional;
  unknown severities coerce to the default ``warning`` with
  a log warning.  ``tools`` is parsed but reserved — runtime
  is one LLM call per check, no tool use yet.
- [x] Checks run as one structured LLM call per rule,
  constrained by :data:`cantrip.llm.schemas.CHECK_RESULT`,
  returning ``{status: pass|fail, severity, message,
  evidence?, suggested_fix?}``.  Phase 10 existing-charm
  improvement and Phase 17 acceptance testing still need to
  call into the runner — deferred to follow-up work; the
  user-invoked ``/review`` surface lands now.
- [x] Distinct from ``charmlint`` (Phase 24, deterministic
  AST rules): documented boundary lives in
  ``design/CHECKS.md`` (new — covers when to write a Check
  vs. a charmlint rule, file format, precedence,
  runtime contract, future work).
- [x] Precedence: bundled → user → repo (later wins).  When
  a name collides, both prior layers' files surface as
  shadow diagnostics in the report so a team sees they've
  replaced a default.
- [x] Ship three built-in checks: ``charm-readme-coherence``,
  ``action-ergonomics``, ``relation-data-hygiene``.  Each is
  a single ``.md`` file with frontmatter + body prompt.
- [x] ``/review`` aggregates the Check report with
  :func:`cantrip.agent.lint_context.gather_project_diagnostics`
  output (Phase 72.4) into a single combined Markdown view —
  the operator sees Checks first, then a "Deterministic
  checks" section underneath.
- [x] ``tests/unit/test_prompt_checks.py`` — 29 cases:
  frontmatter parse + missing-field errors + severity
  coercion + comma-separated tools + missing-delimiter
  guards, three-layer precedence with shadow diagnostics,
  malformed-file skip, bundled checks discoverable, glob
  scoping (basename / path / ``**`` / cap), runner pass /
  fail / skipped / error paths, severity fallback, provider
  failure isolation, prompt includes rule body and file
  contents, aggregated report orders failures first, slash
  handler followup + empty-set message + arg validation +
  no-charm-path guard.

### 70.5 Medium — Painter: charm icon generation ✓

- [x] New tool ``charm_icon_generate`` (lives in
  ``src/cantrip/agent/tools/icon.py``) added to the BUILD
  whitelist alongside the existing deterministic
  ``generate_icon`` placeholder tool — they coexist
  intentionally so a session without an image-provider API
  key still has a working icon path.  Inputs: ``description``
  (required), ``path``, ``charm_name``, ``palette_hint``,
  ``force``.  Output: ``icon.svg`` written to the charm root.
- [x] Backend abstraction lives in
  ``src/cantrip/llm/image.py``: ``ImageResult`` dataclass +
  ``ImageProvider`` ABC + ``create_image_provider(name, *,
  model, api_key)`` factory.  First concrete implementation
  is ``GeminiImageProvider`` calling
  ``client.aio.models.generate_images`` for Imagen models
  (default ``imagen-3.0-generate-002``).  Other providers
  slot in by subclassing and registering in the factory.
  Lazy SDK import keeps the cold-start cost zero when the
  Painter isn't used.
- [x] Charmhub constraints baked into the prompt the Painter
  builds for every call (``_ICON_STYLE_PROMPT``): square,
  flat, simple, high-contrast, legible at 64×64 and 32×32,
  no embedded text.  Charm name + workload description +
  optional palette hint are appended; the prompt is one
  sentence the image provider can act on.
- [x] Output is raster-first: the returned PNG is wrapped
  inside a valid SVG envelope with an ``<image>`` element
  carrying a base64 ``data:`` URL.  Charmhub accepts the
  format; the doc page tells the user a designer-polish pass
  is recommended before release.  A leading XML comment
  carries the ``cantrip-icon-generated`` marker so successive
  ``/icon`` calls can iterate freely on a Painter-generated
  icon.  True vectorisation via ``potrace`` is intentionally
  deferred — embedded PNG is the honest path until the
  dependency cost is acceptable.
- [x] Invocation surface: ``/icon [description]`` slash
  command runs inline (not a queued task — the Painter is one
  HTTP call).  Empty args show usage; missing charm path or
  non-existent dir short-circuit cleanly.  Wired into
  ``COMMAND_CATALOGUE``, ``SHARED_VERBS``, ``help_text``;
  catalogue-drift test stays green.
- [x] Cost accounting mirrors Oracle: new
  ``state.icon_max_session_cost_usd`` (default ``$1.00``,
  ~25 Imagen attempts at $0.04 each) plus
  ``state.icon_session_cost_usd`` and ``state.icon_calls_total``
  accumulators on ``AgentState``.  Tripping the cap returns a
  structured tool error naming the spent amount and how to
  raise it; counters stay untouched on a refused call.  No
  per-turn cap (icons aren't easy to spam from one user
  message; the session cap alone is enough).
- [x] Refusal to overwrite real artwork:
  ``_existing_icon_is_expendable`` treats files matching the
  Phase 7 placeholder fingerprint or carrying our
  ``cantrip-icon-generated`` marker as expendable; anything
  else is refused unless ``force=true``.  The provider is not
  called and no cost is charged when the refusal trips.
- [x] Transcript event ``icon_generated`` recorded via the
  store getter so the audit log captures every Painter call
  with charm name, description, provider/model, cost, and
  cumulative session spend.  Recording failure logs at
  WARNING and never breaks the tool — the icon is already on
  disk.
- [x] Documented in
  ``docs/docs/howto-charm-icon.html``: when to use Painter
  vs. the deterministic placeholder, the cost cap, the
  refusal logic, what the SVG envelope actually contains,
  and the "designer-polish-before-release" disclaimer.
  Card added to ``docs/src/index.md``; entry added to the
  howto sidebar in ``docs/src/_site.yaml``.
- [x] ``tests/unit/test_icon_generation.py`` (32 cases):
  factory rejects unknown providers + missing API key;
  ``_build_prompt`` always includes the style block;
  ``_embed_png_in_svg`` produces valid XML carrying the
  marker and the base64 payload; ``_existing_icon_is_expendable``
  across missing/marker/placeholder/user-art cases; tool
  happy-path writes SVG with the marker, accumulates cost,
  passes the workload phrase into the prompt; charm-name
  fallback to charmcraft.yaml then dir name; refusal-to-
  overwrite-user-art and ``force=true`` overrides;
  placeholder + own-marker overwrite without force; cost-cap
  blocks before any provider call; ``ImageGenerationError``
  surfaces cleanly (no cost, no file); transcript event
  recorded; ``/icon`` slash dispatch (usage, missing charm
  path, non-existent dir, followup wiring, catalogue
  membership, end-to-end render).

**Deferred:**
- **Auto-invocation at BUILD completion** via a CONFIRM task
  ("you don't have an icon — want me to paint one?").  Needs
  the Phase 64 confirmation-task plumbing to wire cleanly.
  Re-open when a real user reports "I keep forgetting to
  paint an icon before publishing."
- **Reference-image input** (up to three reference PNGs).
  The abstraction supports `bytes`-typed extras but the
  prompt path doesn't yet.  Add when a charm team asks for
  brand-consistent iteration.
- **True vectorisation via potrace** (or
  ``svgtrace``/``vtracer``).  ``potrace`` needs the C
  library + a Python binding; reliable enough but adds a
  heavy dependency.  Re-open when the embedded-PNG path
  earns concrete user complaints.

### What this phase is *not*

- Not a rewrite of the subagent system.  Librarian (70.1) is
  a new subagent alongside the existing roster; Oracle
  (70.2) is a tool, not a subagent.
- Not a replacement for ``charmlint``.  70.4 layers prompt-
  based judgment on top of deterministic rules.
- Not a multi-provider orchestration engine.  70.2's Oracle
  is one configurable "summon bigger model" knob; picking
  and routing across many models is Phase 47 territory.
- Not Amp's enterprise surface (SSO, group thread visibility,
  zero-retention toggles).  Cantrip's enterprise story is
  Canonical-internal deployment, not a SaaS.
- Not "match Amp's UX".  Charm-specific cherry-pick.

**Exit criteria:** (a) ``/search-charms "ldap sidecar"``
returns high-quality Charmhub/Launchpad hits with excerpts
and citations that the main agent cites verbatim in its
design document; (b) during a non-trivial architecture turn
the primary agent consults ``oracle_consult`` no more than
once, inside budget, and the transcript records the oracle
exchange as a side event; (c) ``AGENTS.md`` can include a
``globs: [metadata.yaml]`` block that provably loads only on
metadata-editing turns, observed in the transcript; (d) a
charm repo can drop ``.cantrip/checks/upgrade-coherence.md``
and see it fire on the next ``/review`` with severity and
evidence, alongside charmlint output.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Librarian (70.1) | Phase 42 (GitHub), Phase 44 (subagent worktrees), Phase 45 (MCP for search backends) | Read-only subagent with a narrow tool surface |
| Oracle (70.2) | Phase 27, 41 (multi-provider), Phase 47 (cost accounting hooks) | Shares cost/usage plumbing with arena and race |
| Conditional guidance (70.3) | Phase 32 (prompt structure), Phase 33 (skill frontmatter) | Pure loader change; compatible with existing files |
| Checks (70.4) | Phase 24 (charmlint reporter), Phase 10 / 17 (review surfaces) | Shares the charmlint output format so reports merge cleanly |
| Painter (70.5) | Phase 48 (multimodal providers), Phase 64 (CONFIRM for overwrite) | New image-tool abstraction; raster→SVG via potrace with designer-polish disclaimer |

Phase 68.2 gains one follow-up from this review:

- [x] Add ``cantrip permissions test`` (Amp parity) — ships as
  ``cantrip permissions test TOOL [--command CMD] [--path PATH]
  [--agent NAME]`` plus a sibling ``cantrip permissions list``.
  Evaluates the discovered ruleset (built-in safe defaults + user
  ``~/.config/cantrip/permissions.yaml`` + repo
  ``.cantrip/permissions.yaml``) and prints the verdict, the matched
  rule, and the source file (or ``builtin:<section>``).  Honours
  ``--charm-path`` / ``--user-config`` / ``--no-builtin`` so a
  config can be probed in isolation; ``test --show-rules`` appends
  the full listing after the verdict.  Tests in
  ``tests/unit/test_permissions.py::TestPermissionsCLI``;
  documentation in ``docs/docs/reference-cli.html``.

---

## Phase 71: Aider-Inspired Engineering Hygiene — Repo-Map, Architect/Editor, Commit Discipline, Edit Loop ✓

**Goal:** Aider (``aider.chat``) is a long-running open-source
terminal coding agent with a distinct engineering aesthetic:
every turn is a git commit, every edit runs the linter, and
the agent never operates without a compressed "map" of the
repository's most-referenced symbols.  A walk of its docs
surfaces four patterns that aren't covered by Phases 67–70 and
that would directly cut the rework cost on Cantrip's BUILD
phase.

Four candidates, in rough priority order:

1. **Repo-map with graph-ranked symbols.**  Aider parses every
   source file with tree-sitter, builds a dependency graph
   where nodes are files and edges are symbol references, and
   runs a PageRank-style ranking to surface the most-cited
   classes and functions.  The map is rendered as a compact
   symbol list with signatures, injected into every turn
   under a configurable token budget (default 1000 tokens,
   dynamically resized).  Cantrip currently hands the agent
   whatever the planner mentioned plus whatever the agent
   reads on-turn — no persistent bird's-eye view.  Charms are
   small individually but often pull in several charmlibs,
   COS dashboards, and terraform modules; a repo-map lets the
   agent jump to the right file without grep-and-guess.
2. **Architect / Editor two-model split as a first-class
   mode.**  Aider's ``/architect`` routes each turn through two
   models: a strong reasoning model ("architect") proposes
   the change, then a cheap edit-specialist model ("editor")
   emits the concrete diff.  Distinct from Phase 70.2 Oracle
   (one prompt, on-demand, pure reasoning) — Architect is
   *every turn* of a session and covers the full
   propose→apply loop.  Cantrip has per-task ``ModelHint``
   (Phase 4.x) and a resolved-light-provider
   (``resolve_light_provider``) for small tasks, but not a
   stable two-model-per-turn pairing.  Cost savings in BUILD
   can be substantial: the expensive model does the thinking
   once; the cheap model does the mechanical edits.
3. **Auto-commit-per-turn with dirty-commit separation.**
   Aider commits the agent's edits as their own git commit
   with a weak-model-generated message on every turn, and if
   the working tree is dirty *before* the agent edits, it
   commits the user's pre-existing changes separately first.
   Attribution (``(aider)``) makes the split visible in
   ``git log``.  The result: ``/undo`` is literally
   ``git revert`` of the last aider commit — simpler than
   Phase 68.1's snapshot store.  Cantrip has ``git_commit``
   tools but doesn't enforce per-turn commits; it tends to
   batch.  Formalising this cuts audit ambiguity and gives
   a second, git-native undo path.
4. **Per-edit lint/test feedback loop.**  Aider's
   ``--auto-lint`` and ``--auto-test`` run the configured
   linter/test command after *every* edit, capture failures,
   and feed them back to the agent to self-correct before
   committing.  Distinct from Phase 69.1 Ralph Loop (outer,
   per-goal) and Phase 12 red/green (integration-level):
   this is inner, per-edit.  On charm work, the fastest
   failure signal is ``ruff check`` / ``ty`` / ``charmlint``;
   routing them through the same loop tightens correctness
   at the cost of a few extra subprocess calls per turn.

Five Aider features are explicitly **out of scope or
deferred**:

- **Edit-format selection per model** (``whole`` / ``diff`` /
  ``diff-fenced`` / ``udiff`` / ``editblock``).  Genuinely
  interesting — different models emit better diffs in
  different formats — but Cantrip's edit tools are already
  standardised.  Revisit if a specific provider in Phase 41
  shows a quality delta that edit format would close.
- **``/read-only`` reference-file pinning.**  "Add this file
  as context, don't edit it" is a useful affordance; fold into
  Phase 30 (tool completeness) as a one-liner on
  ``fs_read`` rather than its own bullet here.
- **``/voice`` — spoken prompt input.**  Niche for charm
  authoring; revisit if a user asks.
- **``/copy-context`` — copy chat as markdown for pasting
  into a web LLM.**  Overlaps with Phase 67.4 ``/share`` to
  gist and Phase 14 export.  Small win if it shows up, not
  worth its own item.
- **Aider's ``/help`` mode backed by a dedicated vector
  index of Aider's own docs.**  Cantrip's equivalent is the
  ``docs/docs/`` pages plus the system prompt; no
  vector-index build required.

### 71.1 High — Repo-map with graph-ranked symbols ✓

- [x] New subsystem under ``src/cantrip/repomap/``
  (``symbols.py`` / ``graph.py`` / ``render.py`` /
  ``repomap.py``) that parses Python with stdlib ``ast`` and
  charm metadata (``charmcraft.yaml`` / ``metadata.yaml`` /
  ``config.yaml`` / ``actions.yaml``) with ``pyyaml``.
  Stdlib ``ast`` is used in place of ``tree-sitter`` /
  ``tree-sitter-languages`` so the dependency budget stays
  at zero — extending to non-Python sources later is a one-
  module addition behind the same ``parse_*_file`` interface.
  Symbols carry kind (class / function / method / config-
  option / action / relation / container / storage /
  resource), signature (parenthesised parameters with
  annotations, base classes, interface names), and
  qualifier (enclosing class for methods).  TOML and
  Markdown are deferred — neither carries a charm-symbol
  surface today; revisit if hook scripts become a thing.
- [x] Reference graph runs caller-file → definer-file with
  edge weights spread across ambiguous definers; charm
  metadata interface names participate as references so
  ``requires.tracing`` in ``metadata.yaml`` connects to the
  charmlib that provides the interface.  PageRank
  (hand-rolled power iteration, damping 0.85, ~30 iterations
  to convergence on charm-sized graphs) ranks files.
  NetworkX is *not* added — the implementation is ~30 lines
  and avoids dragging in a heavy dep.  Per-file parse
  results cache to ``.cantrip/repomap.json`` keyed by
  mtime_ns; incremental rebuilds reparse only changed files.
- [x] Renderer (``render.py``) groups symbols by file with
  one heading line and indented symbol lines; classes first,
  then free functions, methods, then YAML kinds.  Token
  budget tracked via ``len(text) / 4`` (matches the rest of
  Cantrip's char-per-token estimate).  ``_MAX_SYMBOLS_PER_FILE
  = 12`` keeps one heavy file from monopolising the output
  even with a fat budget.  Default budget 1500 tokens per
  the roadmap.
- [x] System prompt injection lives in
  ``CantripAgent._build_system_prompt``: a new
  ``repo_map=`` kwarg flows through ``build_system_prompt``
  and into ``system.md.j2`` under a fenced
  ``## Repository Map`` block right after Available Skills.
  The compact prompt path (``provider.max_tools is not
  None``) skips the map entirely.  Files cited inline by
  the chat already take precedence — the map is a
  navigation aid documented as such.
- [x] ``/map`` (print the current view at the full
  configured budget) and ``/map-refresh`` (force a complete
  rebuild and reprint) registered in
  ``cantrip.agent.slash_commands``; both added to
  ``COMMAND_CATALOGUE``, ``SHARED_VERBS``, and ``help_text``.
- [x] Dynamic sizing keys off
  ``ContextManager.context_pressure(messages)`` (new helper
  returning ``estimate_tokens / context_window``):
  ``RepoMap.render_for_prompt(context_pressure=…)`` halves
  the budget at ≥80% pressure and drops the section
  entirely at ≥95%.  Mirrors the 0.80 compaction threshold.
- [x] ``tests/unit/test_repomap.py`` — 29 cases covering
  Python parsing (classes, methods, free functions, nested
  function suppression, syntax error tolerance, signature
  with annotations and defaults, relative path
  normalisation, inheritance-as-reference), charm-metadata
  parsing (relations / config / actions, interface
  signatures, malformed YAML), graph (referenced files
  outrank unreferenced, self-edges dropped, PageRank
  determinism, hub-and-spoke ordering, empty-graph,
  dangling-node mass redistribution), rendering (empty
  rankings, zero budget, ``class`` keyword formatting,
  truncation under tight budget), and the orchestrator
  (Python + YAML pickup, render contains key symbols, cache
  file written, mtime-keyed incremental invalidation, force
  rebuild, pressure shrink, drop threshold, missing-charm
  path, excluded directories such as ``.venv``).

### 71.2 High — Architect / Editor two-model split ✓

- [x] New session mode ``architect`` lives on
  :class:`AgentState` alongside Phase 68.4 plan/build:
  ``architect_mode``, ``editor_provider``, ``editor_model``,
  ``architect_consecutive_failures``,
  ``architect_failure_threshold`` (default 2).  When the flag
  is on, every conversation-loop call routes through a new
  ``_run_architect_editor_turn`` orchestrator instead of
  ``_complete_with_retry``.  Both
  ``_run_conversation_loop`` and the streaming
  ``_run_conversation_loop_streaming`` are wired.  The
  streaming path drops token-by-token rendering inside an
  architect-mode session — the editor's response is yielded
  as a single chunk after the dual-pass completes.
- [x] **Architect pass.**  Main provider with ``tools=None``
  and a short SYSTEM instruction
  (``CantripAgent._ARCHITECT_INSTRUCTION``) asking for plain-
  prose intent.  The architect literally cannot emit tool
  calls because it has none.
- [x] **Editor pass.**  Cheaper provider with the full tool
  list, fed the architect's proposal as a synthetic USER
  message wrapped in
  ``<architect_proposal>...</architect_proposal>``.  Editor
  resolution: explicit ``state.editor_provider`` /
  ``editor_model`` override → existing ``self._light_provider``
  → fallback to the main provider when no lighter variant
  exists.  When ``architect_consecutive_failures`` ≥
  ``architect_failure_threshold`` the next editor pass routes
  through the architect provider so a weak editor can't get
  stuck on an ambiguous proposal.
- [x] ``/architect`` slash command (bare toggles, ``on`` /
  ``off`` explicit, optional ``provider`` or
  ``provider/model`` second token to override the editor).
  ``--architect`` CLI flag wired through ``cantrip run`` →
  ``cli.py`` / ``print_mode.py`` / ``tui/app.py`` so all three
  surfaces opt into the dual-pass at startup.
  ``--editor-provider`` / ``--editor-model`` allow hybrid
  pairings (architect=Claude, editor=Gemini-Flash).
  ``STATUS_BAR_CHANGED`` event fires on toggle so the TUI /
  Web status indicator repaints.
- [x] Cost accounting: ``_record_usage`` gained an optional
  ``provider=`` parameter so the architect and editor passes
  attribute their tokens to the right provider/model in
  ``token_usage``; ``/cost`` shows two model lines per turn.
  Transcript records ``architect_pass`` and ``editor_pass``
  side events with ``{provider, model, prompt_tokens,
  completion_tokens, tool_calls, content_excerpt}`` so a
  reviewer can replay the design call when reading the
  exported transcript.
- [x] Documented in
  ``docs/docs/howto-architect-mode.html`` (when to use, how
  it works, editor resolution, fall-through, status
  indicator, interaction with plan mode / permissions /
  hooks / undo, what it is not).
  ``docs/src/reference-cli.md`` gains a new
  ``Architect / editor mode`` section under the slash-command
  catalogue plus the three new CLI flags under the run
  options table; HTML regenerates via ``make docs``.
- [x] ``tests/unit/test_architect_mode.py`` — 22 cases
  covering the slash command (bare toggle, explicit
  ``on`` / ``off``, editor override, error paths,
  status-bar event), editor resolution (override / light /
  fallback / failure escalation), the
  ``_all_tool_calls_failed`` predicate, dual-pass execution
  (both providers ticked, both events recorded, usage
  attributed per model), and CLI flag plumbing through
  ``parse_args``.

### 71.3 Medium — Auto-commit-per-turn with dirty-commit separation ✓

- [x] ``state.git_auto_commit`` (default ``True``) — after
  each turn that mutates files, the new
  :mod:`cantrip.agent.auto_commit` module stages the touched
  paths via ``git add -- <paths>`` (no catch-alls) and
  commits with a body that embeds the user prompt, a list of
  touched files, and a ``Co-Authored-By: Cantrip
  <noreply@aotearoa.dev>`` trailer.  Subject line is
  generated by the light provider via a short, low-token
  prompt; falls back to ``agent: <truncated user message>``
  when no light provider is configured or the call fails.
  ``state.last_cantrip_commit_sha`` records the new HEAD on
  every successful agent commit for future audit / undo
  routing.
- [x] **Dirty-commit separation.**  At the *start* of every
  turn (before the snapshot is taken) a pre-cantrip commit
  fires when ``git status --porcelain`` reports anything
  outstanding — modified-and-unstaged, staged, or untracked.
  Uses ``git add -A`` to sweep up untracked files too, then
  commits as ``chore(pre-cantrip): save in-progress work``.
  Hand-edits stay distinct from agent edits in
  ``git log``.  The pre-commit and the agent commit are both
  no-ops on a clean tree, in a non-repo, or when ``git`` is
  missing — all three return ``None`` and log at DEBUG so the
  conversation loop never breaks because of an auto-commit
  hiccup.
- [x] **Opt-out.**  ``--no-auto-commit`` on ``cantrip run``
  flips ``state.git_auto_commit`` to ``False`` at startup;
  ``/auto-commit on`` / ``/auto-commit off`` toggle
  mid-session.  The CLI flag is plumbed through
  ``cli.py`` / ``print_mode.py`` / ``tui/app.py`` so all
  three surfaces opt out consistently.
- [x] ``/undo`` coexistence: the howto documents the manual
  recipe (``git reset --soft HEAD~1`` to drop just the
  Cantrip commit, or ``git revert --no-commit HEAD`` to keep
  the commit but stage its inverse).  Automated routing of
  ``/undo`` between Phase 68.1 snapshots and a 71.3-aware
  revert is **deferred** — both mechanisms coexist cleanly
  today (snapshots run in a parallel hidden git repo
  independent of the user's charm repo) and the manual
  recipes cover the rare divergence.  Re-open as a follow-up
  when concrete user reports of "/undo left a dangling
  Cantrip commit in my history" arrive.
- [x] ``tests/unit/test_autocommit.py`` — 38 cases covering
  the primitives (``_is_git_repo``, ``_has_dirty_tree``),
  ``collect_touched_files`` (write_file / edit_file alias /
  multi_edit / dedup / non-mutating-tools / non-assistant),
  ``build_commit_message`` (summary subject, fallback,
  truncation, file-list overflow), pre-turn dirty commit
  (clean / modified / untracked / non-repo / None path),
  post-turn agent commit (happy path / explicit summary /
  no-op when no files touched / non-repo / non-existent
  path), the ``/auto-commit`` slash command (default,
  toggle, explicit on/off, no-op, bad arg),
  ``--no-auto-commit`` argparse plumbing, and end-to-end
  agent-loop integration (commit lands, opt-out skips,
  light-provider summariser used, pre-turn dirty-commit
  fires, opt-out skips pre-turn too).  The
  ``tmp_git_repo`` fixture lives in the test file itself
  so the rest of the suite stays unchanged.
- [x] Documented in
  ``docs/docs/howto-auto-commit.html`` (when to use, how it
  works, commit shape with worked example, opt-out paths,
  /undo interaction with manual recipes, what it is not).
  ``docs/src/reference-cli.md`` gains a new
  ``Auto-commit per turn`` section under the slash-command
  catalogue plus the ``--no-auto-commit`` CLI flag under
  the run options table; HTML regenerates via ``make docs``.

### 71.4 Medium — Per-edit lint/test feedback loop

- [x] After each ``write_file`` / ``edit_file`` /
  ``multi_edit`` that touches a Python file, run ``ruff
  check --output-format=json`` and ``ty check
  --output-format=concise`` (ty has no JSON sink yet — the
  concise format is parsed in
  ``src/cantrip/agent/tools/post_edit_lint.py``) on the
  touched paths.  Diagnostics are appended to the tool
  result as a "Lint diagnostics (post-edit):" block and
  also surfaced structurally in
  ``result.data["diagnostics"]``.  Failing lint never
  demotes the original tool result — file edits succeed
  even when the linter complains.
- [x] For charm-shaped YAML (``metadata.yaml``,
  ``charmcraft.yaml``, ``actions.yaml``, ``config.yaml``,
  ``manifest.yaml``), run ``charmlint`` against the charm
  directory.  Prefers the Rust binary for speed (same
  probe as :class:`CharmlintTool`), falls back to the
  Python library, and degrades silently when neither is
  installed (the skipped note is folded into the report
  so the agent knows the absence of diagnostics is "not
  checked", not "all clear").
- [ ] **Deferred: ``pytest --collect-only`` on touched
  test files.**  The roadmap lists this as optional
  ("optionally run the touched test file with ``pytest
  --collect-only`` to catch import errors cheaply").
  Holding it back until a concrete case surfaces — the
  ``ruff`` / ``ty`` pair already catches the common
  import-typo failure mode without spinning up a pytest
  session.  ``state.auto_test_collect_only`` is not yet
  wired; reopen this checkbox when we add it.
- [x] ``state.auto_lint`` (default ``True``) — escape
  hatch.  Set on ``state`` mid-session, or pass
  ``--no-auto-lint`` (REPL, TUI, Web, ``--print``) at
  startup.  Subagent callers go through ``execute_tool``
  without the keyword arguments and are not subject to
  the hook, so subagent transcripts stay focused.
- [x] Distinct from Phase 12 red/green (goal-level test
  gating) and Phase 69.1 Ralph Loop (outer iterate-until-
  green).  This is a *within-turn* quality signal — the
  agent sees the lint output in the same tool-result
  payload as the file write and can self-correct before
  the next round.
- [x] ``tests/unit/test_auto_lint.py`` (30 cases) —
  touching a Python file surfaces ruff diagnostics;
  touching ``metadata.yaml`` surfaces a charmlint
  warning; opt-out via ``state.auto_lint = False`` and
  via the bare-arg ``execute_tool`` call (subagent path)
  both skip the run; failed edits don't trigger lint;
  ``ty`` concise-format parser, report-rendering, missing
  binary and Python-fallback paths all covered.

### What this phase is *not*

- Not a replacement for Phase 68.1 snapshot undo.  71.3
  operates on git commits; 68.1 operates on working-tree
  snapshots.  Both land.
- Not a replacement for Phase 69.1 Ralph Loop or Phase 12
  red/green.  71.4 is the inner edit-level signal; the
  outer loops stay.
- Not a fork of Aider's repo-map code.  Cantrip re-implements
  the idea against its own tool surface — the charm-specific
  interface/charmlib graph edges (71.1) have no analogue in
  Aider.
- Not a mandatory cost increase.  Architect mode (71.2) is
  opt-in; default behaviour stays single-model.
- Not a voice/web-chat affordance.  Tracked in the deferred
  list above.

**Exit criteria:** (a) ``/map`` prints a ranked, bounded
symbol list for the current charm repo, refreshing on file
change and shrinking under compaction pressure; (b)
``/architect`` runs each turn through a configurable
architect model and editor model with per-pass cost
breakdown in ``/cost``; (c) every turn that touches files
produces a discrete, attributed git commit, with any pre-
existing dirty work preserved as a separate commit; (d)
editing a ``src/charm.py`` surfaces ``ruff`` / ``ty``
diagnostics in the same turn so the agent can self-correct
before moving on.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Repo-map (71.1) | Phase 32 (prompt structure) | New subsystem; minimal integration surface |
| Architect mode (71.2) | Phase 27, 41 (multi-provider), Phase 47 (cost accounting), Phase 68.4 (mode infrastructure) | Reuses plan-mode's mode machinery |
| Auto-commit (71.3) | Phase 30 (git tools), Phase 67.2 (light provider for messages) | Composes with Phase 68.1 — 68.1 is snapshot-based, 71.3 is commit-based; ``/undo`` routes to the right one |
| Auto-lint (71.4) | Phase 24 (charmlint), Phase 30 (tool surface) | Inner loop; coexists with Phase 12 and Phase 69.1 |

---

## Phase 72: Continue-Inspired Context Providers — @-Mentions, Indexed Docs, Model Roles, Diagnostics Priming ✅

**Goal:** Continue (``continue.dev``) centres its UX on
*context providers* — structured fragments a user injects into
a prompt by typing ``@<name>``.  Eighteen-plus built-in
providers (``@file``, ``@codebase``, ``@docs``, ``@diff``,
``@tree``, ``@terminal``, ``@problems``, ``@url`` …) turn the
``@`` into a vocabulary for "here's what the agent should look
at."  Four of Continue's ideas transplant cleanly onto
Cantrip and aren't covered by Phases 67–71.

Four candidates, in rough priority order:

1. **Indexed charm-ecosystem documentation (``@docs``).**
   Continue's ``@docs`` crawls a documentation site, embeds
   it, and serves relevant passages when the user mentions
   the site's name.  Charm authoring has a fixed,
   authoritative documentation surface — Juju docs, the
   ``ops`` reference, ``charmcraft.yaml`` reference, Rockcraft
   docs, Jubilant docs, Charmhub guidelines — and "the agent
   hallucinated a ``config-changed`` hook that doesn't exist"
   is a real and recurring failure.  A charm-scoped
   ``@docs <juju|ops|charmcraft|rockcraft|jubilant|charmhub>
   <query>`` that returns cited excerpts from the *canonical*
   source cuts that failure mode in half.
2. **Context-provider abstraction with ``@`` mentions.**  The
   pattern — user types ``@foo`` in the input and structured
   context is injected — is a generally useful input-layer
   primitive that Cantrip lacks.  Phase 68.3 uses ``@path``
   inside *command template bodies*, and Phase 67.1 adds
   ``@@`` for thread references, but a first-class
   ``@``-provider registry in the chat input is new.  Ship
   a baseline set that maps to existing tools: ``@file``,
   ``@diff``, ``@tree``, ``@terminal``, ``@url``, plus the
   charm-specific ``@charm <name>`` (fetch charm source from
   Charmhub via Phase 70.1 Librarian) and
   ``@juju <show-unit|status|config>``.
3. **Model roles — embed and rerank as first-class.**
   Continue's model config assigns *roles* (``chat``,
   ``edit``, ``apply``, ``embed``, ``rerank``,
   ``autocomplete``, ``summarize``) to each model so the
   system routes each request type appropriately.  Cantrip
   has ``create_provider`` / ``resolve_light_provider`` plus
   Phase 71.2 architect/editor, but no ``embed`` or
   ``rerank`` role — which means no infrastructure for
   RAG-style retrieval.  Both 72.1 ``@docs`` and a future
   memory-retrieval layer (Phase 43) need embed; rerank
   improves retrieval quality.  Define the roles now, even
   if only a subset of providers supply them.
4. **``@problems`` — diagnostics-as-pre-turn-context.**
   Continue's ``@problems`` pulls the IDE's lint/type errors
   as context; no IDE required if the agent just runs the
   linter itself.  A ``/diagnostics`` (or ``@problems``)
   that injects the current output of
   ``ruff check --output-format=json``,
   ``ty check --output-format json``, and
   ``charmlint --format json`` *before* the agent plans an
   edit primes the agent with the existing failure set —
   complementary to Phase 71.4 (which runs *after* each
   edit).  The agent starts a turn knowing what's broken and
   plans accordingly.

Five Continue features are explicitly **out of scope or
deferred**:

- **Inline autocomplete** (QwenCoder / Codestral small-model
  tab completion).  Cantrip isn't an IDE extension; the
  edit path is agent-tool-driven, not type-to-complete.
  Revisit only if an IDE surface ships.
- **``@debugger`` — live-debugger local variables.**  No
  live-debugger integration in Cantrip; `juju debug-hooks`
  and `pytest --pdb` are the relevant surfaces and they
  produce output the agent already reads.
- **Continue Hub (``uses: org/rules-name``) — central
  registry of shared rules and prompts.**  Overlaps with
  Phase 50 (Skills Ecosystem Interop).  If Canonical wants
  a registry of charm skills, Phase 50 is the place —
  don't spin up a parallel authority.
- **``data:`` config block — dev-data collection for
  fine-tuning.**  Cantrip's transcript (Phase 14) plus the
  observability work already underway cover the analytics
  use case.  No separate dev-data pipe.
- **Prompt files and Rules files as ``uses:``-referenced
  hub blocks.**  Prompt files already covered by Phase 68.3
  (markdown custom commands).  Rules files already covered
  by Phase 70.3 (glob-conditional guidance).  Don't
  duplicate — point the user at both from docs.

### 72.1 High — Indexed charm-ecosystem documentation (``@docs``) ✅

- [x] New subsystem :mod:`cantrip.docs_index` with the
  full crawl → chunk → embed → upsert → search pipeline.
  Six canonical surfaces registered in
  :mod:`cantrip.docs_index.sites`: ``juju``, ``ops``,
  ``charmcraft``, ``rockcraft``, ``jubilant``, ``charmhub``.
- [x] Storage: SQLite per-site under
  ``~/.cache/cantrip/docs-index/<site>/index.db``; vectors
  packed as float32 BLOB with cosine similarity in pure
  Python.  No ``sqlite-vec`` / ``faiss`` dependency —
  charm-ecosystem corpora are small enough that in-memory
  search stays sub-second.  Chunk size ~500 tokens, overlap
  50, paragraph-aware breaks.  Embed batches of 64 through
  the Phase 72.3 :class:`EmbedProvider`.  **Deferred:**
  sentence-transformers offline fallback (Phase 72.3
  defers it until a concrete caller hits the embed path —
  this phase doesn't change that decision; sessions
  without a remote embed provider see ``RoleNotConfigured``
  and skip ``@docs`` registration entirely).
- [x] ``cantrip docs index [--site <name> | --all]`` and
  ``cantrip docs list`` / ``cantrip docs search <site> <query>``
  subcommands in :mod:`cantrip.docs_index.cli`.  Re-indexing
  replaces rows by stable ``sha256(url|ordinal)`` hash.
  **Deferred:** ``cantrip docs refresh`` with
  ``If-Modified-Since`` honoring (Phase 72.1b if the corpus
  size makes the full re-crawl painful in practice).
- [x] Retrieval surfaces: typed
  :class:`~cantrip.agent.tools.docs_search.DocsSearchTool`
  registered in
  :func:`cantrip.agent.tools.build_tools` when the session
  has an embed-capable router; Phase 72.2
  ``@docs <site> <query>`` mention via
  :class:`~cantrip.agent.context_providers_builtin.DocsProvider`.
  Both return ``{site, url, title, excerpt, score}`` so
  every cited passage is traceable to a canonical URL.
- [x] System prompt guidance: a new "Indexed Documentation"
  section in ``src/cantrip/agent/prompts/system.md.j2``
  teaches the agent to consult ``docs_search`` before
  answering "how do I …" questions and to cite URLs
  verbatim rather than paraphrase.
- [x] Documented in ``docs/docs/howto-docs-index.html``
  (new page) and ``docs/docs/reference-cli.html`` (env vars
  + ``cantrip docs`` subcommand).
- [x] ``tests/unit/test_docs_index_store.py`` (16 cases),
  ``tests/unit/test_docs_index_pipeline.py`` (13 cases),
  ``tests/unit/test_docs_index_cli.py`` (9 cases),
  ``tests/unit/test_docs_search_tool.py`` (15 cases) —
  parser, store, end-to-end indexing with httpx mocked,
  CLI surface, agent tool, and the ``@docs`` provider
  including end-to-end through ``expand_mentions``.

### 72.2 High — ``@``-mention context-provider registry ✅

- [x] Central registry in
  :mod:`cantrip.agent.context_providers` with a
  :class:`ContextProvider` protocol (``info: ProviderInfo``,
  async ``expand(args, ctx) -> ContextBlock``).
  :class:`MentionSuggestions` widget integrates with the
  Phase 61 autocomplete pattern; Tab completes a trailing
  ``@<partial>`` segment mid-message without disturbing the
  surrounding prose.
- [x] Baseline providers shipped in
  :mod:`cantrip.agent.context_providers_builtin`:
  - ``@file <path>`` — inline file contents, traversal-safe
  - ``@diff`` — ``git diff HEAD``
  - ``@tree [path]`` — ``git ls-files`` listing (respects
    ``.gitignore``); falls back to plain walk
  - ``@url <url>`` — ``WebFetchTool`` wrapper (private-IP
    block + llms.txt probing inherited)
  - ``@problems`` — reuses Phase 72.4
    :class:`~cantrip.agent.lint_context.DiagnosticsCache`
  - ``@charm <name>`` — Charmhub metadata via
    ``CharmhubInfoTool``
  - ``@juju <subcmd>`` — read-only ``juju`` subprocess with a
    hard verb allowlist (``status``, ``show-unit``, ``config``,
    ``list-secrets``, ``show-relation``, ``show-application``,
    ``show-model``, ``list-models``)
  - **Deferred:** ``@terminal`` (waits on Phase 69.3 shell-mode
    output buffer); ``@docs <site> <query>`` (Phase 72.1).
- [x] Expansion happens in the TUI ``on_input_submitted`` and
  Web WebSocket handlers via :func:`expand_mentions` *after*
  slash-command dispatch, so the LLM sees a substituted prompt
  and the user sees an ``Expanded mentions: …`` system note.
  Multi-line blocks get a ``[@name]…[/@name]`` fence wrapper so
  the typed form stays visible alongside the substituted
  content in the transcript.
- [x] Bounded per-provider char budgets via :func:`truncate`
  with a ``[truncated N chars]`` footer.  Defaults baked in
  ``context_providers_builtin``; settings-file override is a
  future polish.
- [x] Third-party providers register via
  :meth:`ProviderRegistry.register` from Phase 46 hooks or
  Phase 45 MCP server bootstraps — same surface the baseline
  uses.  Protocol documented in
  ``design/CONTEXT_PROVIDERS.md``.
- [x] ``tests/unit/test_context_providers.py`` — 43 cases
  covering the parser (email, ``@@``, fenced/inline code, multi-
  mention), provider error path, autocomplete prefix detection,
  per-provider validation surfaces (file traversal, juju verb
  allowlist, missing args).

### 72.3 Medium — Model roles: embed and rerank ✅

- [x] Provider-role abstraction.  Two narrower ABCs in
  :mod:`cantrip.llm.roles` —
  :class:`EmbedProvider` (``texts -> EmbeddingResult``) and
  :class:`RerankProvider` (``query, docs -> RerankResult``) —
  keep the chat-shaped :class:`~cantrip.llm.base.LLMProvider`
  free of no-op embed/rerank stubs.  A
  :class:`RoleRouter` resolves per-role providers; retrieval
  callers query the router instead of instantiating
  providers directly.  `RoleNotConfigured` names the env var
  / CLI flag that would configure a missing role, replacing
  the old ``cantrip.yaml`` aspiration with the env-var +
  CLI surface Cantrip already uses everywhere.
- [x] Concrete implementations.
  :class:`~cantrip.llm.voyage.VoyageEmbedProvider` and
  :class:`~cantrip.llm.voyage.VoyageRerankProvider` (default
  models ``voyage-3`` and ``rerank-2``);
  :class:`~cantrip.llm.openai_embeddings.OpenAIEmbedProvider`
  with ``OPENAI_EMBED_BASE_URL`` override for self-hosted
  vLLM.  **Deferred:** sentence-transformers offline
  fallback — no concrete caller exercises the embed path
  yet, ship as optional dependency when 72.1 ``@docs``
  needs it.
- [x] Retrieval-using callers query
  :attr:`CantripAgent.role_router`; the agent's constructor
  accepts a router built by
  :func:`build_role_router` (env vars + CLI flags).  Each
  entry point (CLI / TUI / Web / print mode) passes its
  own router so misconfiguration surfaces at boot through
  the same error path as a missing chat-provider key.
- [x] Cost accounting.  ``token_usage`` schema v13 added
  a ``role`` column; legacy rows roll into ``chat``.
  ``/cost`` picks up a ``By role`` section when any non-chat
  row exists.  Pricing entries shipped for voyage-3 /
  -lite / -large / -code-3, rerank-2 / -lite, and
  text-embedding-3-small / -large (input-only:
  ``completion=0.0``).
- [x] ``tests/unit/test_provider_roles.py`` — 28 cases
  covering the ABCs, the router missing-role error,
  Voyage/OpenAI wire formats with httpx mocked, the
  env-var/CLI builder precedence, and the
  ``record_role_usage`` recording helper.
  ``tests/unit/test_store.py`` adds the role-column
  migration + grouping coverage.

### 72.4 Medium — Diagnostics-as-pre-turn-context (``@problems``) ✅

- [x] ``@problems`` context provider (registered in 72.2 via
  :class:`cantrip.agent.context_providers_builtin.ProblemsProvider`)
  runs, on expansion:
  - ``ruff check --output-format=json .`` (or just the
    charm's ``src/`` and ``tests/`` to keep it cheap)
  - ``ty check --output-format json .``
  - ``charmlint --format json`` (from Phase 24)
  and emits a compact block grouping issues by severity and
  file, capped at 1500 tokens (longer reports get
  summarised with a "N more issues suppressed; run
  ``cantrip lint`` for the full list").  Reuses the shared
  :class:`~cantrip.agent.lint_context.DiagnosticsCache` so a
  ``/diagnostics`` immediately followed by ``@problems`` does
  not pay for the linters twice.
- [x] Caching: run results cached for 30 seconds in
  :class:`cantrip.agent.lint_context.DiagnosticsCache`
  (TTL=30 s, keyed on resolved charm path, ``--refresh`` /
  ``force_refresh=True`` bypass).
- [x] ``/diagnostics`` slash command for the same output
  without an inline context-provider mention — registered
  in :data:`cantrip.agent.slash_commands.COMMAND_CATALOGUE`,
  rendered as Markdown so the severity headers stay legible
  in chat surfaces.
- [x] Autonomous-loop integration: BUILD and DEBUG
  subagents pick up a "## Current diagnostics" section in
  their briefing via
  :meth:`BackgroundExecutor._attach_diagnostics_brief`,
  using the same shared cache so a quick ``/diagnostics``
  immediately before a BUILD launch doesn't pay for the
  linters twice.  Other categories skip the lint pass —
  RESEARCH doesn't edit, DEPLOY operates on built artefacts,
  TEST runs its own pytest.
- [x] ``tests/unit/test_diagnostics_context.py`` — 26
  cases: JSON-parse-equivalent runner stubbing, multi-tool
  aggregation, severity-priority sort, tail truncation with
  honest count, TTL eviction, ``force_refresh``, runner
  crash isolation, charmlint skip without ``metadata.yaml``,
  charm-root fallback when ``src/`` and ``tests/`` are
  absent, subagent prompt picks up ``diagnostics_text``,
  slash handler followup path, RESEARCH skipped, aggregator
  failure does not abort subagent launch.

### What this phase is *not*

- Not an IDE extension.  Autocomplete, ``@debugger``, and
  the live-LSP integration stay out of scope until Cantrip
  ships an IDE surface.
- Not a vector-store product.  72.1 ships the minimum
  viable crawl+embed+query for *charm ecosystem docs*;
  indexing the whole charm repo is Phase 71.1 repo-map's
  job, not this phase's.
- Not a replacement for Phase 68.3 custom commands or
  Phase 70.3 conditional guidance.  Continue's ``prompt
  files`` and ``rules files`` as hub-hosted ``uses:``
  blocks overlap with those phases; we adopt the ``@``-
  provider pattern, not the hub pattern.
- Not a telemetry pipeline.  ``data:`` dev-data collection
  is out of scope.

**Exit criteria:** (a) ``@docs juju secrets`` returns
cited passages from the indexed Juju docs in under a
second; (b) typing ``@diff`` in the TUI input expands to
the current ``git diff`` before the message reaches the
agent, with both forms in the transcript; (c) a provider
can declare ``roles: [embed, rerank]`` and the ``docs_search``
tool uses that provider for retrieval, with embed+rerank
costs appearing in ``/cost``; (d) typing ``@problems`` (or
running ``/diagnostics``) injects ``ruff``/``ty``/``charmlint``
JSON output as a compact issues block the agent can plan
against before it edits.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| ``@docs`` index (72.1) | 72.3 (embed role), Phase 45 (MCP optional), Phase 67.3 (print-mode parity) | Biggest item; infra for retrieval |
| ``@``-provider registry (72.2) | Phase 61 (autocomplete), Phase 68.3 (file-ref semantics) | Input-layer expansion; fans out to providers |
| Model roles (72.3) | Phase 27, 41 (multi-provider) | Schema change on provider config |
| Diagnostics (72.4) | Phase 24 (charmlint JSON), Phase 71.4 (lint tool surface) | Reuses 71.4's subprocess plumbing |

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

## Phase 76: Copy-Friendly Chat — Toad-Inspired ✓

**Goal:** Make it easy to copy chunks of the chat window — a
single agent message, a single tool block, a whole turn.  Today
the TUI relies on the terminal's own copy machinery (``Ctrl+Shift+
C`` in most terminals), which breaks when Cantrip is running
inside a multiplexer or when multiple surfaces are on screen.
Toad (Will McGugan's TUI agent, built on Textual; not Charm
despite some early conflation) has well-regarded per-block copy
affordances — inspect what they do and adapt what fits.

**This was primarily an investigation phase.**  Shipped the
smallest concrete win and wrote up the rest in ``design/UI.md``
under *Copy-Friendly Chat (Phase 76)* so a future phase has a
starting point if user demand surfaces.

### 76.1 Research — What Toad does ✓

- [x] Researched Toad's public surface (``willmcgugan.github.io``
  announcement + released posts, ``batrachianai/toad`` GitHub,
  InfoQ writeup, HN thread).  Distinctive UX: a Jupyter-style
  block cursor over the conversation that lets users copy a cell
  to the clipboard or push it back into the prompt.  Beyond that:
  per-block SVG export (Textual screenshot trick) and ungarbled
  scrollback (architectural, not a copy feature).  No public
  evidence of OSC 52, format pickers, or hover affordances.
- [x] Catalogued Cantrip's current copy-friction points: zero
  clipboard infrastructure (no ``pyperclip``, no OSC 52 helper);
  TUI ``ChatWidget`` is a flat ``ScrollableContainer`` of
  ``Static`` children with no focus model or per-message DOM
  attribute; ``/export`` exists but writes the whole transcript
  to a file rather than pulling out a single message; ``/share``
  uploads as a gist but again whole-session.

### 76.2 Design — What fits Cantrip ✓

- [x] Picked the smallest concrete affordance that does NOT
  require a chat-widget refactor: a ``/copy`` slash command,
  Markdown-only, with OSC 52 underneath so it survives tmux /
  screen / ssh.  Block-cursor mode (Toad's headline feature) is
  deliberately deferred — it would mean refactoring
  ``ChatWidget`` to focusable per-block widgets, mirroring the
  same model in the Solid Web UI, and adding cursor state in
  both surfaces.  Documented the reasoning in ``design/UI.md``
  with a *what would change the verdict* list so a future phase
  has clear triggers.
- [x] Markdown-vs-plain-text policy: ship Markdown only.  Toad
  ships one format; we ship one format.  Adding a picker would
  mostly add UI, not value.

### 76.3 Implement — The one thing worth shipping now ✓

- [x] ``cantrip.clipboard`` module — ``osc52_sequence(text)``
  returns the universal terminal-clipboard escape;
  ``write_to_terminal(text)`` emits it to ``sys.__stdout__``
  (bypassing Textual's stdout interception) when the destination
  is a tty, returns ``False`` otherwise so callers can fall back
  cleanly.  Truncates at 75 KB to stay below xterm's OSC 52 cap.
- [x] ``cantrip.transcript.markdown.render_message(msg, *,
  include_header=False)`` extracted from the whole-transcript
  ``render_markdown`` so ``/copy`` and ``/export markdown``
  share one renderer.
- [x] ``SlashResult`` gains a ``clipboard_text: str | None``
  field; surfaces inspect it after rendering ``text``.  TUI
  delegates to Textual's ``App.copy_to_clipboard`` (handles tmux
  passthrough wrap); CLI calls ``clipboard.write_to_terminal``
  with a fall-back to printing the body inline; Web inlines
  the payload in a fenced code block (browser permissions block
  server-pushed ``navigator.clipboard.writeText`` without a
  fresh user gesture).
- [x] ``/copy`` slash command: bare grabs the last assistant
  message; ``/copy last`` grabs the most recent of any role;
  ``/copy <N>`` grabs the 1-based session index (matches
  ``/export markdown``).  Edge cases: missing charm path,
  missing ``.cantrip``, no messages, no assistant messages,
  out-of-range index, non-integer argument all return a
  human-readable string with ``clipboard_text`` left ``None``.
- [x] ``COMMAND_CATALOGUE`` + ``help_text`` updated;
  ``/help`` documents the verb; the catalogue-drift test
  enforces consistency.
- [x] ``docs/src/reference-cli.md`` gets a *Copy a chat
  message to the system clipboard* section under the slash-
  command catalogue, including the tmux ``set-clipboard on``
  prerequisite; HTML regenerated; ``make docs-check`` passes.
- [x] Tests: ``TestCopy`` (9 cases) on the dispatcher covering
  every edge case, plus ``test_clipboard.py`` (6 cases) on the
  OSC 52 module — round-trip, unicode, oversize truncation,
  tty / non-tty / OSError write paths.  Two existing CLI
  completer tests updated to reflect ``/copy`` sorting before
  ``/cost`` alphabetically.

**Exit criteria:** Either (a) a concrete copy affordance lands
and is documented, or (b) a written assessment in ``design/UI.md``
explains why the current flow is sufficient and what would
change that.  ``make check`` passes regardless.  Closed by
shipping (a) — ``/copy`` lands as the concrete affordance — and
(b) — ``design/UI.md`` writes up everything else as deferred so
the next phase has clear triggers.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Research (76.1) | None | Read-only |
| Design (76.2) | 76.1, Phase 75 (tool blocks as copyable units) | Tool blocks are new copy targets; wait until 75 lands |
| Implement (76.3) | 76.2 | Only if 76.2 surfaces a clear win |

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

- [ ] New ``tests/eval/test_system_prompt_smoke.py`` that
  renders the shipped ``system.py``, sends it as the system
  role with a fixed test prompt to each configured provider,
  and asserts basic shape invariants on the response
  (contains a tool call under expected names, respects
  non-trivial markdown fences, etc.).
- [ ] Matrix across Claude + Gemini + at least one
  open-weights model (Fireworks/Kimi or OpenRouter/Llama).
- [ ] Skippable when per-provider API keys aren't present in
  the environment so ``make check`` stays green locally
  without any keys.

### 79.3 Gate in CI against a cheap model

- [ ] New CI job that runs the 79.2 smoke test on every PR
  that touches ``src/cantrip/agent/prompts/`` or
  ``src/cantrip/agent/planner/templates/``.  Scoped to a
  cheap model (Gemini Flash or OpenRouter
  ``openai/gpt-4o-mini``) to keep CI cost bounded.
- [ ] Fails fast on 4xx from the LLM so a broken prompt
  template surfaces as a red check within a minute.

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

## Phase 81: Tool Caption Coverage — Shell, Juju, Acceptance ✓

**Goal:** Phase 75.6 shipped rich captions for the file-system,
git, and charm-tooling categories and left three groups on the
formulaic ``tool_name(arg=value)`` fallback as drive-by work.
Track them here so the improvement doesn't rot.  Each subsection
is small (one tool or a small family) and each can land
independently.

The phase grew beyond the original three categories: while
trimming the fallback list a coverage test was added that walks
every registered ``Tool`` and fails if a new tool is silently
falling back, so the choice between rich caption and fallback is
a visible code-review decision.  In the same pass the highest-
value drive-bys (git plumbing, GitHub commands, generators,
test harnesses, ``rockcraft_pack``, ``charmcraft_init``,
``charmcraft_release``, ``charmcraft_upload``, ``multi_edit``,
``charmlint``, ``charm_sync``, ``web_fetch``, ``web_search``)
also landed.  Captioned tools went from 28 to 73 of 111.

### 81.1 Low — ``run_command`` caption ✓

- [x] Populated ``ToolResult.caption`` in
  ``cantrip.agent.tools.run_command``: ``"<base> (exit N)"``,
  optionally followed by ``": <40-char snippet>"`` of the
  combined stdout/stderr.  Failing commands surface the start
  of the error in the chat block instead of the formulaic
  ``run_command(cmd=...)`` fallback.  Newlines are collapsed
  to spaces; snippets above 40 chars truncate with ``…``.
- [x] Four cases in ``tests/unit/test_tool_captions.py`` —
  success-with-output, success-no-output, failure-with-error,
  newline-collapse + truncate.

### 81.2 Low — Juju tool captions ✓

- [x] ``juju_deploy`` → ``"Deployed <name>"``, with
  ``"to <model>"`` appended when an explicit model is supplied.
  Falls back to the charm's stem when no ``app_name`` is given.
- [x] ``juju_config`` → ``"Set <app>: <key>=<value>"`` for a
  single value, ``"Set <app>: N values"`` otherwise.  Read
  mode (no values) emits ``"Read <app> config"``.
- [x] ``juju_status`` → ``"N app(s)"``, with ``", M blocked"``
  appended when any application is in ``blocked`` state.
- [x] ``juju_relate`` → ``"Integrated <app1> ↔ <app2>"``.
  (The roadmap's ``juju_remove_relation`` was a misnomer —
  the deletion path lives in ``juju_remove_application``,
  which stays on fallback because the destruction details are
  carried by the user-supplied argument.)
- [x] Eight cases in ``test_tool_captions.py`` covering status
  pluralisation, deploy-with-model and stem-fallback, relate,
  config single/multiple/get.

### 81.3 Low — Acceptance / test tool captions ✓

- [x] ``run_charm_tests`` parses the pytest summary line and
  emits ``"<P> passed, <F> failed"``-style captions, with
  fallbacks for runners that emit no summary
  (``"tests ran (no summary)"``) and for runner failures
  (``"tests failed (exit N)"``).
- [x] ``charm_audit`` → ``"clean"`` on a finding-free run,
  ``"<N> issue(s)"`` otherwise (singular/plural agreement).
- [x] ``acceptance_report`` → ``"Wrote ACCEPTANCE.md
  (<N> section(s))"``.  ``action_exerciser``,
  ``relation_smoke_test``, ``workload_endpoint_test``,
  ``config_variation_test``, ``config_under_load_test`` also
  caption their pass/fail counts so the per-charm acceptance
  matrix reads cleanly in the chat.
- [x] Seven cases in ``test_tool_captions.py``.

### 81.4 Medium — Future-proof caption coverage ✓

Discovered while trimming ``_FALLBACK_OK``.  The original 84-tool
fallback list was too coarse — most tools had clear one-line
verdicts available.  The follow-up pass took the captioned share
to **111 / 111**: every registered tool populates
``ToolResult.caption`` on its success path, and ``_FALLBACK_OK``
is empty.

- [x] New ``TestCaptionCoverage`` test in
  ``test_tool_captions.py`` walks every ``Tool`` instance from
  ``build_tools()``, inspects its source for a ``caption``
  reference, and fails when a tool is neither captioned nor
  on the explicit ``_FALLBACK_OK`` allowlist.  New tools must
  either populate ``result.caption`` on the success path or
  add their name to ``_FALLBACK_OK`` with a one-line
  justification, so the choice is a visible review decision.
- [x] Drive-by captions, in batches:
  - **Batch 1** (with the 81.4 land): git plumbing
    (status / log / diff / init / branch / checkout / add /
    stash), GitHub commands (PR create / view / list, issue
    list, repo create / bootstrap), generators
    (``generate_readme`` / ``generate_icon`` /
    ``generate_diagram`` / ``generate_docs`` /
    ``generate_load_test`` / ``generate_tests`` /
    ``extract_design_decisions`` /
    ``extract_troubleshooting``), test harnesses
    (``test_report``, ``scaling_test``, ``upgrade_test``,
    ``fuzz_charm``, ``chaos_test``, ``hook_benchmark``),
    acceptance probes (the four listed under 81.3),
    ``charmcraft_init`` / ``charmcraft_release`` /
    ``charmcraft_upload``, ``charmhub_search`` /
    ``charmhub_info``, ``rockcraft_pack``, ``multi_edit``,
    ``charmlint``, ``charm_sync``, ``web_fetch``,
    ``web_search``, ``quick_pack``.
  - **Batch 2** (clearing the long tail): the remaining Juju
    family (``juju_trust``, ``juju_refresh``, ``juju_ssh``,
    ``juju_run_action``, ``juju_add_model``,
    ``juju_destroy_model``, ``juju_offer``, ``juju_consume``,
    ``juju_wait``, ``juju_dispatch``, ``juju_get_app_config``,
    ``juju_list_offers``, ``juju_list_secrets``,
    ``juju_show_secret``, ``juju_show_unit``,
    ``juju_remove_application``, ``juju_read_relation_data``,
    ``juju_debug_log``, ``juju_stream_logs``,
    ``bundle_deploy``), observability queries
    (``loki_query``, ``tempo_query``), framework
    (``analyse_framework``), terraform
    (``generate_terraform`` / ``validate_terraform``),
    inference / registry probes (``list_inference_snaps``,
    ``registry_search`` / ``registry_image_info`` /
    ``skopeo_registry_push``), workspace listings
    (``workspace_info``), concierge (``concierge_prepare`` /
    ``concierge_status``), readiness
    (``operational_readiness``), PR review
    (``pr_review`` / ``pr_review_reply``), accessibility
    audits (``rodney`` / ``showboat``).
- [x] ``_FALLBACK_OK`` is now empty.  Future fallback usage
  will require an explicit code-review decision.

### What this phase is *not*

- Not a redesign of the caption framework.  Phase 75.1 / 75.2
  shipped that; this is just filling in the remaining tools.
- Not a backwards-compatibility concern.  The fallback keeps
  the chat readable until each caption lands; there's no
  pressure to ship them as a single batch.

**Exit criteria:** all three categories populate
``ToolResult.caption`` on the success path, with tests pinning
the shape.  ``make check`` passes throughout.  **Met.**  Coverage
test in 81.4 catches future omissions.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| ``run_command`` (81.1) | Phase 75 framework | One tool; smallest change |
| Juju captions (81.2) | Phase 75 framework | Five tools; mostly stub-driven tests |
| Acceptance captions (81.3) | Phase 17 reporters | Parses existing reporter output |
| Coverage test (81.4) | 81.1–81.3 | Follow-up; catches new tools without captions |

**Discovered:** Phase 75.6 closed with three categories on the
fallback; this phase tracks them so they don't rot.

---

## Phase 82: Pre/Post Tool Captions — Inline Status Replacement ✓

**Goal:** When a tool is invoked, render an *intro* caption immediately
(``"Packing the charm…"``, ``"Querying Tempo for the last 5 traces…"``)
so the user sees something is happening, then *replace it in place*
with the post-call caption (``"23 passed, 0 failed"``) once the tool
returns.  Today the chat block only appears after the tool finishes,
so long-running tools (``charmcraft_pack``, ``juju_wait``, web
fetches) leave the user staring at silence between the agent's last
text and the next visible event.

This is the inverse of the Phase 75 caption — Phase 75 is "what just
ran"; this phase adds "what's running now" and folds the two into a
single inline block that updates once.  Inspired by OpenAI's GPT-5.5
prompt-guidance recommendation (preambles before tool calls improve
perceived responsiveness in agent rollouts) — we already ship the
post-call half via Phases 75 and 81; the intro half closes the gap.

### 82.1 Core — ``intro_caption`` hook + pending event ✓

- [x] Added ``intro_caption(arguments)`` on
  :class:`cantrip.agent.tools.base.Tool` — optional override
  returning a present-continuous string.  Default returns ``None``
  so existing tools keep working unchanged.
- [x] :func:`build_tool_intro_caption` synthesises the generic
  ``"Running <tool_name>(<key>=<value>)…"`` fallback using the same
  ``_CAPTION_KEY_PREFERENCE`` list as the post-call helper, so the
  pre/post pair share one key-picking discipline.
- [x] New ``TOOL_INVOKED_PENDING`` event type + factory; the agent
  main loop (sync + streaming) and subagent runner publish it
  before dispatch, carrying the LLM-assigned ``tool_call_id``.
  ``TOOL_INVOKED`` gained the same id field (default ``None`` for
  back-compat) so renderers can match the pair.

### 82.2 Bespoke intro captions for high-traffic tools ✓

- [x] File-system: ``read_file`` → ``"Reading src/charm.py…"``,
  ``write_file`` → ``"Writing tests/integration/test_charm.py…"``,
  ``edit_file`` → ``"Editing <path>…"``, ``multi_edit`` →
  ``"Applying N edits to/across <files>…"``.
- [x] Git: ``git_clone`` → ``"Cloning <trimmed-url>…"`` (matches the
  post-call URL trim), ``git_commit`` → ``"Committing…"``,
  ``git_push`` → ``"Pushing → <remote>/<branch>…"``.
- [x] Charm tooling: ``charmcraft_pack`` → ``"Packing the charm…"``,
  ``quick_pack`` → ``"Quick-packing the charm…"``,
  ``charm_validate`` → ``"Validating the charm…"``,
  ``charm_audit`` → ``"Auditing the charm…"``.
- [x] Juju: ``juju_status`` → ``"Reading juju status[ (<model>)]…"``,
  ``juju_deploy`` → ``"Deploying <app>…"``,
  ``juju_refresh`` → ``"Refreshing <app>…"``,
  ``juju_wait`` →
  ``"Waiting for <app[ (model)]> to settle…"``.
- [x] Acceptance / observability: ``run_charm_tests`` →
  ``"Running unit/integration tests[ (<pattern>)]…"``,
  ``tempo_query`` → ``"Fetching trace …"`` /
  ``"Querying Tempo for <service>…"``, ``loki_query`` →
  ``"Querying Loki…"``.
- [x] Web / registry: ``web_fetch`` → ``"Fetching <host>…"``,
  ``registry_search`` →
  ``"Searching Docker Hub for '<query>'…"``,
  ``registry_image_info`` → ``"Inspecting <image[:tag]>…"``.

### 82.3 Renderers — in-place update by tool-call id ✓

- [x] TUI: ``ChatWidget`` tracks pending blocks in
  ``_pending_tool_blocks`` (id → widget).  ``add_pending_tool_block``
  renders ``⟳ <caption>`` with a ``tool-pending`` class;
  ``add_tool_block`` short-circuits to ``resolve_tool_block`` when
  the matching id is on file, so the pending block updates in place
  rather than appending a new line.
- [x] Web UI: ``cantrip.js`` parallel implementation with
  ``_pendingToolBlocks`` Map; matching id triggers
  ``_renderToolBlockBody`` against the existing div.  CSS class
  ``msg-tool-pending`` carries the dim-italic style.
  ``design/UI.md`` event contract gained the two TOOL_INVOKED
  variants.
- [x] Failure path: ``scrub_pending_tool_blocks`` (TUI) and
  ``scrubPendingToolBlocks`` (Web) convert any orphans into failed
  ``"cancelled"`` lines.  Wired to the worker-state-changed
  handler / ``setThinking(false)`` so a cancelled mid-tool turn
  never leaves a dangling spinner.

### 82.4 Tests ✓

- [x] Unit: ``test_tool_caption.py`` covers the
  ``build_tool_intro_caption`` fallback (overrides, no-tool
  caller, empty-args bare form, exception swallowing, long-value
  truncation).  ``test_tool_intro_captions.py`` (41 cases) asserts
  every bespoke 82.2 override.
- [x] Event round-trip: ``test_ui_events.py`` exercises the
  ``tool_invoked_pending`` factory + ``tool_call_id`` round-trip
  on ``tool_invoked``.  ``test_agent.py`` asserts the agent loop
  emits ``TOOL_INVOKED_PENDING`` then ``TOOL_INVOKED`` with the
  same id (and distinct captions).
- [x] Renderer integration: ``test_chat_tool_blocks.py`` (10 cases
  via Textual pilot) covers pending-then-final updating in place,
  failed-final swap, no-pending append fallback, duplicate
  pending no-op, scrub orphans as cancelled, late-final after
  scrub, unknown-id fallback to append, plus the bus-handler path
  for both event types.

### What this phase is *not*

- Not streaming tool *output* — only the caption is two-phase.
  Tool results still arrive in one chunk.
- Not a progress bar or token counter — Phase 31 covers cost
  streaming and is separate.
- Not a redesign of the post-call caption framework — Phases 75 /
  81 own that surface.  This phase only adds the pre-call half
  and the in-place update path.

**Exit criteria:** invoking a slow tool (``charmcraft_pack``,
``juju_wait``, ``web_fetch``) shows an immediate intro caption that
updates in place to the post-call caption when the tool returns.
``make check`` passes.  No regression in Phase 75 inline-block
rendering.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Pending event hook | Phase 75 inline blocks | Reuses TOOL_INVOKED renderer |
| Bespoke intro captions | Phase 81 (post-call captions) | Mirrors the same per-tool ergonomics |
| In-place replacement | Phase 75 + Web UI event-bus parity | Both renderers need update-by-id |

**Discovered:** While reviewing OpenAI's GPT-5.5 prompt-guidance
recommendations, the "preambles before tool calls" pattern stood
out as orthogonal to (but compatible with) Phase 75's post-call
captions.  The user proposed folding them into a single inline
block that transitions from intro to outcome.

---

## Phase 83: Pause-and-Edit Interrupt — Research ✓

**Goal:** Today's interrupt (<kbd>Ctrl+C</kbd> / <kbd>Esc</kbd> in
the TUI, the Cancel button or <kbd>Esc</kbd> in the Web UI) is a
*hard* cancel: ``asyncio.Task.cancel()`` unwinds the in-flight
turn, the agent forgets what it was doing past the last persisted
event, and the user has to retype a redirected instruction from
scratch.  Some peers (Claude Code, Cursor, Aider) instead let the
user *pause* the agent mid-turn, edit or amend the running
instruction, and resume — the agent keeps the partial reasoning
context and folds the edit in.  This phase decides whether
Cantrip should add such a mode and, if so, what the smallest
viable shape is.

This was a **research phase** — no production code changed.
Findings landed in
[`design/PAUSE_AND_EDIT.md`](design/PAUSE_AND_EDIT.md); summary
below.

### Decisions

- [x] **Defer the full pause-and-edit interrupt.**  Cancel today
  already preserves every completed round in ``state.messages``
  (only the in-flight LLM call's response is lost); no real user
  complaint surfaced; the most-common interrupt flavour
  (*augment* — "add this clarification") admits a leaner shape
  (queue-next-instruction) at ~25% of the cost.  The full
  pause-and-edit work waits on a concrete trigger.
- [x] **Peer survey recorded** in
  ``design/PAUSE_AND_EDIT.md`` §2: only Claude Code ships a
  mid-turn affordance Cantrip doesn't have (queue-next-
  instruction); Cursor's mid-stream-edit assumes a
  partial-assistant-message UI Cantrip doesn't render; Aider /
  Goose / Amp all match Cantrip's hard-cancel-and-retype.
- [x] **Resumable-unit and message-flow shapes decided** in
  §3.1 / §3.3: pause at the seam between LLM call and tool
  dispatch (or between tool result and next LLM call); paused
  edits resume as the next ``USER`` message (shape 1) — the
  only shape that doesn't require novel provider-side
  semantics.
- [x] **Phase 83b — *Queue-Next Instruction*** scoped as the
  smaller follow-up (130-180 LOC + tests, half a day to a day
  of work).  Activates against three named triggers (§6) before
  any pause-and-edit work.

### Revisit triggers

Phase 83b — Queue-Next Instruction — opens when **any** of:

1. **Repeated augment-flavour friction.**  A user retyping
   "original ask + clarification" after Esc shows up in a
   transcript audit, or is named as a pain point.
2. **Long-Ralph-loop steering.**  Phase 69.1's bounded Ralph
   loop runs unattended for many iterations and a user wants
   to *steer* it without aborting it.
3. **Web-UI accessibility request.**  Phase 60's WCAG audit
   flags Stop+retype as an accessibility blocker for
   keyboard-only users, where queue-next is more accessible
   than a chord keybind.

Phase 83c — Full pause-and-edit — opens *after* 83b ships
**and**:

4. Queue-next demonstrably doesn't cover the *redirect* flavour
   in real sessions (users keep cancelling rather than queueing
   because they don't want the tool to run at all), **or**
5. A peer ships a clearly better pattern worth copying.

**Exit criteria met:** ``design/PAUSE_AND_EDIT.md`` is the
written assessment.  Verdict is "defer", with the smaller
queue-next-instruction shape sketched at §4.2 ready for Phase
83b when a trigger fires.

**Discovered:** While adding the <kbd>Esc</kbd> cancel binding
to bring the TUI in line with Claude Code's cancel habit, the
user noted that Claude Code's *fuller* interrupt model also
permits editing the in-flight instruction.  Worth deciding on
deliberately rather than copy-pasting blindly.

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
- [ ] `src/cantrip/main.py` (1 080 lines) — once 85.6 has
  removed the `parse_args` block, decide whether the
  remaining `_run` plus helpers warrants a package or stays
  flat.  Likely stays flat at ~600 lines; defer this bullet
  if so.

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

## Phase 86: Kubernetes / kubectl Tool or Skill — Research ✓

**Goal:** Decide whether the agent should grow first-class
support for ``kubectl`` (and adjacent ``k8s`` snap / ``microk8s``
CLI) operations — and if so, in what shape.  Today the agent
relies on ``juju`` for everything that touches the substrate,
which is fine until something goes wrong *below* juju and the
charm is healthy from juju's perspective but broken at the
Kubernetes layer (CrashLoopBackOff, OOM, pulled-image fails,
PVC stuck pending, RBAC mis-binding, etc.).

This was a **research phase** — no production code changed.
Findings landed in
[`design/K8S_TOOL.md`](design/K8S_TOOL.md); summary below.

### Decisions

- [x] **Skill-expansion now, defer the typed tool.**  The
  six-verb read-only shortlist
  (``kubectl describe pod`` / ``logs --previous`` /
  ``get events`` / ``get pods`` / ``describe pvc`` / ``top pod``)
  lands as a new "Looking *underneath* Juju" section in
  ``src/cantrip/skills/fix-broken-juju-k8s/SKILL.md`` so the
  agent surfaces those verbs to the user via the existing
  escalation pattern.  No new ``Tool`` subclass, no
  ``run_command`` allowlist change, no kubeconfig probe in
  ``preflight.py``.
- [x] **Skill writes-policy line added.** ``kubectl delete /
  apply / exec / patch`` join the "Things you must NOT do"
  block — the agent suggests reads, never runs writes.
- [x] **Sandbox / kubeconfig finding recorded** in
  ``design/K8S_TOOL.md`` §3: ``kubectl`` does not have the
  ``juju`` snap's dbus problem, but bwrap unsets ``HOME`` and
  binds nothing under ``~/.kube/``, so any future typed tool
  must bypass the sandbox the same way ``tools/juju.py`` does
  (direct ``subprocess.run`` with explicit ``KUBECONFIG`` in
  env) rather than route via ``run_command``.
- [x] **Verb shortlist captured** at ``design/K8S_TOOL.md`` §2
  with the symptoms each verb answers and the Juju-substitute
  table that explains *why* each verb earns its place — five
  of the six have no Juju equivalent.

### Revisit triggers

A Phase 86b implementation phase opens when **any** of:

1. The agent autonomously reaches the "Juju says active, pod
   is in CrashLoopBackOff" gap and asks the user to run
   ``kubectl describe pod`` rather than answering itself.
2. ``fix-broken-juju-k8s`` loads frequently with the new §1.2
   content, and the agent walks the user through manual
   kubectl invocations across many turns.
3. The Phase 17 acceptance harness or
   ``tools/observability.py`` needs pod-level state Juju
   doesn't expose (e.g. asserting "no PVC stuck Pending").
4. A user asks for it directly.

When any of these fire, the implementation phase opens with the
verb shortlist as the deliverable scope, the sandbox-bypass
pattern as the architecture, and ``_kubeconfig_present()`` as
the pre-flight.

**Exit criteria met:** ``design/K8S_TOOL.md`` is the written
assessment.  The skill expansion in
``src/cantrip/skills/fix-broken-juju-k8s/SKILL.md`` ships the
read-path know-how to the agent today; the typed tool is
deferred against four named triggers.

---

## Phase 88: Canonical Identity Platform Integration ✓

**Goal:** Cantrip-built charms today can authenticate "alongside an
OIDC provider" (the twelve-factor skill mentions Hydra and Keycloak
in passing) but Cantrip has no first-class understanding of the
[Canonical Identity Platform](https://charmhub.io/topics/canonical-identity-platform) —
Hydra (OAuth2 / OIDC), Kratos (identity / sessions),
identity-platform-login-ui, and the various proxy charms that knit
them together.  This phase decides what that first-class support
should look like and ships the minimum viable integration.

### 88.1 Research — Identity Platform surface and Cantrip's role ✓

- [x] **Five relation interfaces matter** (see
  [`design/IDENTITY_PLATFORM.md`](design/IDENTITY_PLATFORM.md) §2):
  ``oauth`` is the headline (RP gets issuer URL + client ID +
  secret per relation); ``oauth-cli`` for device-code CLI flows;
  ``oidc-info`` for charms that introspect tokens themselves;
  ``hydra-token-introspect`` for resource-server validation;
  ``kratos-external-idp`` for federating Google / GitHub into
  Kratos.  All five live in the per-charm libs ecosystem
  (``charmcraft fetch-libs`` route) — not yet on PyPI per
  ``UPSTREAM_AUDIT.md``; LIB001 mapping update is a 88.2
  follow-up.
- [x] **Three topologies catalogued** (§3): SaaS-style public
  Hydra behind Traefik, internal-only with mTLS, and bundle-based
  hybrid via ``canonical-identity-platform``.  Trade-off table
  records security / setup-cost / fit notes per topology.
- [x] **Default topology decided: bundle-based hybrid** (§4).
  When a user says "add login" without qualification, Cantrip
  generates an ``oauth`` relation, suggests
  ``juju deploy canonical-identity-platform``, and integrates
  against the bundle's Hydra app.  Mirrors the COS-bundle pattern
  Cantrip already prescribes for observability.  SaaS-public-Hydra
  and internal-mTLS exist as prompt-driven escape hatches.

### 88.2 Skill — ``identity-platform`` charm-generation skill ✓

- [x] New skill ``src/cantrip/skills/identity-platform/`` with
  the standard SKILL.md format.  Body covers: the five relation
  interfaces (``oauth``, ``oauth-cli``, ``oidc-info``,
  ``hydra-token-introspect``, ``kratos-external-idp``), the
  bundle-based hybrid default topology, the
  ``charmcraft fetch-libs`` route for ``charms.hydra.*`` and
  ``charms.kratos.*`` (none on PyPI per
  ``UPSTREAM_AUDIT.md``), secret-relation wiring for client
  credentials, and topology escape hatches for SaaS-public-
  Hydra and internal-only-mTLS.  System prompt's fetch-libs
  list and the ``charmcraft`` skill updated to include the
  hydra / kratos namespaces; cross-links added from
  ``twelve-factor`` (OIDC section), ``custom-charm`` (relation
  data section), and ``infrastructure-charm`` (auth comment in
  the metadata template).
- [x] Three worked examples: 12-factor app + Hydra requirer
  (``oauth`` relation, paas-charm env injection), custom app
  with Kratos-backed sessions (full ``OAuthRequirer`` wiring),
  infrastructure charm with ``oauth-cli`` for
  service-to-service tokens.

### 88.3 Tooling — agent-side affordances ✓

- [x] **No new tool.**  Verdict recorded in
  ``design/IDENTITY_PLATFORM.md`` §6: the existing
  ``juju_read_relation_data`` covers the common debug case
  (inspect what Hydra wrote into the relation), ``juju_status``
  covers deployment health, and the 88.2 skill prose is enough
  for charm generation.  Same posture as Phase 86 took for
  kubectl — ship the skill knowledge, defer the typed tool
  family against a named trigger.  Trigger added to §7.5 of
  the design note: a typed ``identity_platform_*`` tool family
  becomes worth building when the agent ends up shelling out
  to ``hydra clients list`` / ``hydra clients get`` in real
  sessions more than a handful of times, or when relation-
  databag inspection isn't enough to debug a misconfigured
  client.
- [x] **Acceptance harness wiring.**
  ``src/cantrip/agent/tools/acceptance.py`` ``_INTERFACE_PARTNERS``
  now covers ``oauth`` / ``oauth-cli`` / ``oidc-info`` /
  ``hydra-token-introspect`` (partner ``hydra``) and
  ``kratos-external-idp`` (partner ``kratos``).  The Phase 17
  ``RelationSmokeTool`` automatically deploys the partner and
  exercises the relation when it sees an identity-platform
  endpoint on a generated charm — no per-charm wiring needed.
  Smoke partners are the standalone charms rather than the
  ``canonical-identity-platform`` bundle so the smoke topology
  is tightly scoped; bundle deploy is the *deployment* default
  (see the identity-platform skill), not the smoke default.
  Unit-tested in ``tests/unit/agent/tools/test_acceptance_tools.py
  ::TestInterfacePartners::test_identity_platform_interfaces_covered``.
- [x] **Acceptance runbook.**  ``design/IDENTITY_PLATFORM.md``
  §9 records the manual two-layer verification: Layer 1 is the
  automated relation smoke (every CI run, asserts databag has
  issuer URL + client ID + secret URI); Layer 2 is the manual
  browser-driven end-to-end on a real K8s (deploy the bundle,
  cross-model integrate, click through login-ui).  Full
  bundle-on-K8s automation isn't a unit-test surface; the
  runbook is the operator-runnable shape.

### What this phase is *not*

- Not a rewrite of the twelve-factor skill — it gains a
  cross-link to ``identity-platform`` rather than absorbing it.
- Not custom IAM (LDAP, SAML, ad-hoc OAuth).  Canonical-stack
  scope only.
- Not a generic security audit (Phase 16 / OWASP territory).

**Exit criteria:** A user asking the agent for "an app with
Canonical-Identity-Platform-backed login" gets a charm with
correctly-wired Hydra (or chosen alternative) relations, secret
fabric, and a passing acceptance test on the demo bundle.

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

### 89.1 Decide the slate

- [ ] List candidate stats (above + anything else that surfaces
  during the design pass), score each on (a) read-frequency
  during real charm sessions, (b) cost to compute live, (c)
  cost to keep fresh.  Pick four to ship; defer the rest behind
  named triggers in this phase note.

### 89.2 Layout

- [ ] Decide whether the stats column lives:
  - inside ``CharmTreeWidget`` as a right-docked sidebar (single
    widget, simpler placement), or
  - as a sibling widget next to the tree, with the parent
    ``#charm-files`` switching to a horizontal layout.
- [ ] Confirm the column doesn't clip the file tree at narrow
  terminal widths — gracefully fold to "tree only" below a
  threshold (or tie visibility to a binding the user can toggle).

### 89.3 Implementation

- [ ] Refresh cadence — decide per-stat (some are file-system
  watcher–driven, some are git-hook–driven, some can poll on
  the existing 3 s tree-refresh tick).  Avoid blocking the UI
  on a ``git log`` per tick; cache + invalidate.
- [ ] Tests under ``tests/unit/test_tui*.py`` for the renderer
  and a Pilot fixture that exercises a populated stats column
  against a synthetic charm checkout.

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

## Phase 91: Adopt from canonical/skills — 12-Factor Scripts and Skill Shape ✓

**Goal:** Canonical's public skills repo
(``github.com/canonical/skills``) opened PR #4 — three
tightly-coupled skills for the 12-factor flow:
``12factor-fit`` (preflight + framework detect + question bank
→ handoff payload), ``12factor-charm`` (``charmcraft init
--profile <fw>`` + paas-charm contract enforcement), and
``12factor-rock`` (``rockcraft init --profile <fw>`` + strict
edits-only-inside-extension boundary).  The skill bodies
encode operational rigour we mostly handle implicitly today,
and four self-contained Python scripts under those skills are
effectively deterministic tools wearing skill-script clothing.
Cantrip already ships its own ``twelve-factor`` skill and a
mature tool catalogue under ``src/cantrip/agent/tools/``; this
phase pulls in what's worth pulling in without fork-and-rebrand.

The upstream is Apache-2.0; ported scripts must carry an
attribution header citing the upstream path.

### 91.1 Steal verbatim — port the four scripts as Cantrip tools

- [x] ``detect_framework.py`` (284 lines, ``12factor-fit/
  scripts/``) → replace the heuristic guts of the existing
  ``AnalyseFrameworkTool`` (``analyse_framework``) with the
  upstream's scoring algorithm: dependency parsing
  (``go.mod``, ``package.json``, ``pyproject.toml`` including
  Poetry, ``requirements.txt`` with ``-r`` includes,
  ``pom.xml``, ``build.gradle``) plus source-pattern
  regex.  Add ``candidates``, ``signals``, ``web_app_guess``,
  ``web_app_signals``, and ``notes`` to the tool's ``data``
  payload.  Keep the existing surface (``path`` arg, profile
  mapping, ``needs_experimental`` flag, ``workload_hints``)
  so callers downstream are unaffected.  No new tool name —
  one detection tool, better detection.
- [x] ``check_rock_contract.py`` (289 lines, ``12factor-rock/
  scripts/``) → new tool that runs framework-specific fit
  checks (deps present, ASGI/WSGI entrypoint at standard
  paths, Maven-XOR-Gradle, base/framework compatibility) and
  returns JSON blockers + advisories.  Wire into the BUILD
  allowlist so the agent runs it before ``rockcraft pack``.
- [x] ``inspect_env_keys.py`` (144 lines, ``12factor-charm/
  scripts/``) → new tool: multi-language env-var extractor
  (Python, JS, Go, Java, Spring ``${…}``, ``.env``) with
  framework-aware contract hints.  Useful for charm⇄rock
  contract validation even outside the 12-factor path.
- [x] ``preflight_targets.py`` (212 lines, ``12factor-fit/
  scripts/``) → adapt as a session-start environment
  snapshot tool (kubectl context, juju controller,
  rockcraft/charmcraft snap channel, registry reachability,
  experimental-extension env vars).  Trim the rockcraft-snap
  skopeo path detection where Cantrip already has its own
  registry helpers; keep the JSON output shape.
- [x] Each ported tool ships an Apache-2.0 attribution header
  citing ``canonical/skills@<sha>:<path>`` and adheres to the
  Cantrip tool conventions: ``ToolBase`` subclass, populated
  ``ToolResult.caption`` (per Phase 81), unit tests covering
  every framework branch and a no-match case, registration
  in the matching tool allowlist.

### 91.2 Adapt — twelve-factor skill body and handoff contract

- [x] Restructure ``src/cantrip/skills/twelve-factor/SKILL.md``
  around the upstream's checkpoint workflow: inspect, detect
  (call the 91.1 tool), ask the mandatory questions, run
  preflight (call the 91.1 tool), produce a handoff payload.
  Keep the Cantrip-shape skill body single-file — embed the
  question bank inline rather than splitting into a
  ``references/`` sibling (our loader is single-file by
  design; see ``design/SKILLS.md``).
- [x] Adopt the upstream handoff YAML shape (framework,
  repo_path, deployment context, relations with explicit
  ``optional`` flags, migrations mode, background services,
  experimental flag) as Cantrip's internal relay structure
  between the fit, charm, and rock phases.  Documented inside
  the twelve-factor skill body itself rather than in
  ``design/SKILLS.md`` — lives where the agent reads it.
- [x] Pull the framework-specific contract tables from
  upstream's ``framework-rock-contracts.md`` and
  ``framework-charm-contracts.md`` (Spring Boot's
  no-``migrate.sh``, Django's auto-migrate, Go ``cmd/*``
  awareness, ExpressJS ``app/package.json`` requirements)
  into the Cantrip charm/rock skill bodies as concrete rules
  the agent can cite.

### 91.3 Watch — items deferred behind named triggers

- [ ] **Relation-optionality enforcement** — upstream's rule
  that relation ``optional`` must come from explicit user
  input, never inference (``12factor-charm/SKILL.md:50-112``).
  Trigger to adopt: Cantrip starts generating relations
  declaratively rather than via charmcraft templates.
- [ ] **Experimental-extension gating** — surface
  ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS`` /
  ``CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS`` requirements
  for FastAPI / Go / ExpressJS / Spring Boot.  Trigger:
  Cantrip's twelve-factor skill claims first-class support
  for any of those four frameworks.
- [ ] **``generate-agent-skills`` workflow + validator
  pipeline** — upstream's strict skill-authoring ceremony
  (scaffold script, validator, banned manual file creation).
  Trigger: Cantrip opens a public skills registry of its own.

### What this phase is *not*

- Not a wholesale fork of canonical/skills — Cantrip has its
  own skill-loader shape, its own tool conventions, and its
  own checkpoints.  We're cherry-picking deterministic
  helpers and concrete rules, not the surrounding ceremony.
- Not the meta ``generate-agent-skills`` skill — that's
  registry-publishing infrastructure, deferred to 91.3.
- Not the ``retrospective-artifacts`` skill — orthogonal to
  charm building.

**Exit criteria:** the four upstream scripts ship as Cantrip
tools with attribution, tests, captions, and allowlist
registration; the ``twelve-factor`` skill body adopts the
checkpoint workflow and handoff contract; the framework
contract tables are inlined into the charm and rock skill
bodies; ``make check`` is green; ``CHANGELOG.md`` notes the
adoption with credit to canonical/skills PR #4.

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

- [ ] Replace the fixed sleeps in the executor and e2e harnesses with
  polling / signalling helpers.  The review found multiple
  ``asyncio.sleep(0.05–0.2)`` and ``time.sleep(5/10)`` waits that are
  structurally flaky on slow CI runners; provide one shared helper and
  codemod the obvious cases onto it.
- [ ] Add a lightweight executor-test harness that waits on explicit
  queue / task state transitions rather than timing assumptions, then
  migrate ``tests/unit/executor/test_run_loop.py`` and similar files.
- [ ] Enforce Python coverage in the main developer loop.  ``make unit``
  already collects coverage; add a ``fail_under`` threshold and wire it
  into ``make check`` so coverage regressions are visible before merge.
- [ ] Expand the eval corpus beyond the current minimal set of gold
  charms: cover more substrates (machine + k8s), at least one custom /
  non-framework application path, and more relation / observability
  shapes so prompt or planner regressions are easier to detect.
- [ ] Add CI wiring for the eval work that is cheap enough to run
  regularly: keep the full provider-matrix ambition in Phase 79, but
  make the static gold-standard / rubric path and any cheap smoke path
  first-class rather than manual-only.
- [ ] Reduce test-maintenance drag in the heaviest files and fixtures:
  split the monolithic ``tests/unit/agent/test_agent.py`` into
  feature-scoped modules, centralise reusable fakes/builders, and
  document the fixture hierarchy so unit / integration / e2e layers stop
  growing parallel infrastructure by accident.
- [ ] Add a small audit of exception-path coverage in high-value modules
  (provider adapters, executor loop, juju/log plumbing, structured
  output, persistence) and backfill the missing regression tests the
  review called out.

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
- [ ] Consolidate environment-variable guidance so setup is not repeated
  piecemeal across README, tutorial, provider how-to, and CLI reference.
  One authoritative how-to page should own the env-var story, with the
  other docs linking to it.
- [ ] Sweep user-facing docs for stray internal phase-language
  references and remove them.  Roadmap/phase numbering belongs in the
  roadmap, archive, changelog, and design notes — not in the user docs.

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
