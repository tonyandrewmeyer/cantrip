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

## Phase 7: Polish and Ecosystem

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
- [ ] Full COS integration (all components)
- [ ] Sloth (SLO management), Parca / Pyroscope (profiling)
- [ ] Identity integration
- [ ] Litmus chaos testing integration

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

## Phase 36: Review Claude Code Best Practices for Cantrip

**Goal:** Review the community-curated best practices at
`github.com/shanraisshan/claude-code-best-practice` and evaluate whether any
techniques would improve (a) how we build Cantrip itself (CLAUDE.md, workflow,
prompt structure, tool design) or (b) how the Cantrip agent operates (system
prompts, subagent guidance, tool patterns, conversation loop design).

- [ ] Clone and review the repository contents — extract every concrete
  recommendation (prompt engineering, CLAUDE.md structure, tool use patterns,
  context management, task decomposition, etc.)
- [ ] Evaluate each recommendation against Cantrip's current CLAUDE.md and
  development workflow — adopt anything that would improve Claude Code's
  effectiveness when working on this codebase
- [ ] Evaluate each recommendation against Cantrip's own agent architecture —
  system prompts (`src/cantrip/agent/prompts/`), subagent guidance
  (`src/cantrip/agent/prompts/subagent/`), tool design (`src/cantrip/agent/tools/`),
  and conversation loop (`src/cantrip/agent/core.py`) — adopt patterns that
  would make Cantrip a more effective autonomous agent
- [ ] Document findings: what was adopted, what was rejected (and why)

**Exit criteria:** Review complete. Any adopted changes are implemented and
passing `make check`.

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

## Phase 46: User-Configurable Hooks

**Goal:** Expose the executor's lifecycle points as user-configurable hooks so
operators can inject domain policy (security review, custom linters, signoff,
external approvals, notifications) without forking Cantrip. Claude Code shipped
conditional `if:` hooks and a PreCompact hook in the review window; Windsurf
shipped Cascade Hooks. Cantrip already has internal hooks in `planner.py` and
the watcher — this phase formalises them and opens them up.

### 46.1 High — Hook event taxonomy ✓

- [x] Full taxonomy declared in ``cantrip.hooks.HookEvent`` (StrEnum):
  ``pre_tool_call``, ``post_tool_call``, ``pre_subagent``,
  ``post_subagent``, ``pre_compact``, ``post_compact``, plus
  reserved-for-later ``pre_pack``, ``pre_push``, ``pre_pr``,
  ``on_task_complete``, ``on_session_end``.  The reserved names
  accept hook declarations today but don't fire until later
  sub-phases wire up the call sites — users can pre-write configs
  without breakage when the switch flips.
- [x] Wired to agent lifecycle:
  ``pre_tool_call`` / ``post_tool_call`` fire in both main-agent
  paths (synchronous ``core.py`` loop and streaming
  ``process_message_streaming``) and in the subagent gather loop
  (with a ``source`` field of ``main`` / ``main-stream`` /
  ``subagent`` so hooks can tell callers apart).
  ``pre_compact`` / ``post_compact`` fire in both compaction call
  sites, with ``tokens_before`` + ``tokens_after`` carrying the
  headline metric.  ``pre_subagent`` / ``post_subagent`` fire in
  ``Subagent.run()``'s try/finally so ``post_subagent`` runs even
  on failure, with the ``exit_state`` of the run.
- [x] Payloads documented on the new
  ``docs/docs/howto-hooks.html`` page — tool events carry
  ``tool`` + ``arguments`` + ``success`` (post) + ``error``;
  subagent events carry ``task_id`` + ``title`` + ``category``;
  compact events carry ``tokens_before`` + ``tokens_after``;
  every payload auto-includes ``event`` + ``timestamp``.
- [x] Decision: hooks do **not** ride the Phase 15.1 UI event bus.
  That bus is fire-and-forget (``_deliver()`` uses
  ``ensure_future``) — listeners can't block the publisher, which
  would break the future veto semantics in 46.4.  Instead hooks go
  through a dedicated ``HookRunner.fire()`` that awaits each
  subprocess sequentially, so the 46.4 upgrade is a small local
  change rather than a bus-redesign.

### 46.2 High — Hook config format and discovery ✓

- [x] Two YAML config scopes, matching the MCP convention
  (``cantrip.mcp.yaml``) for consistency:
  ``~/.config/cantrip/hooks.yaml`` (user, overridable via
  ``$CANTRIP_HOOKS_USER_CONFIG``) and ``cantrip.hooks.yaml`` in
  the charm directory (repo).  Repo hooks with the same ``name``
  override user-scope hooks; a malformed file logs at WARNING and
  contributes nothing so a broken user config can't take out the
  repo's hooks or the agent itself.
- [x] Deviation from the roadmap wording: the schema key is
  ``event:`` not ``on:``.  Unquoted ``on:`` in YAML 1.1 parses as
  a boolean ``True`` key (PyYAML's default), which would silently
  break every user config — surfacing a very poor error message to
  a non-expert user.  ``event:`` dodges the trap and reads just as
  well.  The ``HookConfig`` dataclass field name follows the
  schema: ``HookConfig.event``, not ``HookConfig.on``.
- [x] Schema:
  ``name`` (optional; default: first word of ``run``),
  ``event`` (required; one of ``HookEvent``),
  ``run`` (required; ``/bin/sh -c``-style command),
  ``timeout`` (optional; default 30 s, must be positive),
  ``continue_on_error`` (optional; default True).  Every field has
  strict type checking; unknown ``event`` values list the valid set
  so the error points at the fix.
- [x] Hooks run as subprocesses via
  ``asyncio.create_subprocess_shell`` with the JSON payload on
  stdin.  ``HookResult`` captures exit code, stdout, stderr,
  duration, and a ``timed_out`` flag.  Execution is sequential per
  event in declaration order — deterministic ordering matters for
  the future veto path and gives a cleaner audit log.
- [x] CLI + TUI construct the agent with
  ``HookRunner.from_disk(repo_root=charm_path)`` so loaded hooks
  take effect from session start; tests construct an empty runner
  by default (no I/O, no YAML).  ``HookRunner`` is threaded through
  the ``BackgroundExecutor`` → ``Subagent`` path so subagent events
  fire the same hooks.
- [x] 28 unit tests in ``tests/unit/test_hooks.py`` covering YAML
  parse (empty file, missing ``hooks`` key, bad top-level type,
  bad list type, unknown event, missing ``run``, bad timeout type,
  negative timeout, bad ``continue_on_error`` type, default-name
  derivation, explicit name, default timeout, all-events-parse),
  config discovery (empty, repo-wins, both-included, malformed
  user config survives), and runner execution (no-op on empty,
  JSON payload on stdin, non-matching skipped, multiple hooks fire
  in order, timeout enforced, failing hook doesn't raise, stderr
  captured, ``hooks_for`` / ``hook_count`` diagnostics,
  ``from_disk`` smoke test).  Plus an end-to-end
  ``TestAgentFiresHooks`` case proving the main-agent tool-call
  loop fires ``pre_tool_call`` + ``post_tool_call`` on every
  invocation.

### 46.3 Medium — Conditional filters ✓

- [x] New ``if:`` key on each hook declaration accepts a boolean
  expression evaluated against the event payload before the hook
  runs — examples from the doc page: ``tool == "git_push"``,
  ``category == "BUILD" and exit_state == "completed"``,
  ``tool in ["git_push", "git_commit", "charmcraft_upload"]``,
  ``arguments.channel == "edge"``.
- [x] Expression language built on Python's own ``ast`` module
  instead of a handwritten grammar or ``eval()``: allows
  ``BoolOp`` / ``UnaryOp`` / ``Compare`` / ``Constant`` / ``Name`` /
  ``Attribute`` / ``Subscript`` / ``List`` / ``Tuple`` and rejects
  everything else at compile time.  That covers the common cases
  (``==``, ``!=``, ``<=``, ``>=``, ``in``, ``not in``, ``and``,
  ``or``, ``not``, nested field access, subscript access, list
  literals) and keeps function calls, method calls, lambdas,
  comprehensions, and imports out of the config completely.
- [x] Deviation from the roadmap's example: ``path.matches("charm.py")``
  isn't supported because method calls are rejected by the
  validator on purpose — a user who can write
  ``tool.startswith(...)`` in their config can also write
  ``__import__('os').system(...)``.  Substring checks work via
  ``"git" in tool``; regex matching is left for a future
  skill-style extension.
- [x] Compiled at config-load time inside ``_parse_hook`` — bad
  expressions fail with a ``HookConfigError`` that names the hook
  and points at the broken line, not at fire-time when the
  operator is already waiting on a tool call.
- [x] Missing payload fields are evaluated through a
  ``_Missing`` sentinel that makes every comparison (except ``==``
  / ``!=`` against itself) return ``False`` — so a hook with
  ``if: task.category == "BUILD"`` against a payload without a
  ``task`` field simply skips rather than raising.  Users can
  write one hook config that targets fields from several event
  shapes without KeyError crashes.
- [x] ``HookRunner.fire`` evaluates ``hook.if_expr`` against the
  *enriched* payload (so the auto-added ``event`` + ``timestamp``
  fields are available to filters) and skips the hook without
  spawning a subprocess when the filter rejects the event.  31 new
  unit tests cover parse-time rejection (syntax error, function
  call, method call, lambda, comprehension, statement-shape),
  evaluation (all operators, ``in``, ``not in``, nested attribute,
  subscript, numeric comparison, list literals), missing-field
  semantics (missing at top + nested levels, ``!=`` vs missing,
  ordering op vs missing), YAML parse (accepted, missing, empty,
  malformed-name-surfaced), and runner dispatch (matching fires,
  non-matching skips, ``event`` auto-field accessible, mixed
  filtered + unfiltered hooks on the same event).

### 46.4 Medium — Hook result handling ✓

- [x] Veto semantics live on ``HookResult``: new ``vetoed`` property
  is True when ``continue_on_error=False`` and the hook either
  exited non-zero or timed out.  ``continue_on_error=True``
  (the 46.2 default) preserves the observer behaviour — a failing
  lenient hook logs but doesn't block.  ``veto_reason`` synthesises
  a one-line explanation with the hook name and the last stderr
  line (falling back to ``exit <code>`` when stderr is empty and to
  ``timed out after Ns`` for timeouts), so the operator gets an
  actionable message without grepping logs.  New
  ``first_veto(results)`` helper walks a result list and returns
  the first vetoing hook, or ``None``.
- [x] Tool-call veto wired in all three tool-call sites.
  ``pre_tool_call`` results are scanned with ``first_veto``; a veto
  synthesises ``ToolResult(success=False, error="Blocked by hook
  'x': <reason>")`` so the LLM sees the veto verbatim on its next
  turn and can react (apologise, retry with different args, ask
  the user).  The tool function never runs.  ``post_tool_call``
  still fires for vetoed calls with ``success: false`` and a
  ``vetoed_by`` field so observability hooks see the full decision
  record — they can filter with
  ``if: vetoed_by != None`` to get just blocked events.
- [x] Subagent tool-call veto works the same way, extended for
  ``asyncio.gather`` concurrency: pre-hooks fire sequentially and
  their vetoes are recorded per-call; the gather substitutes
  vetoed tools with the synthesised error while un-vetoed tools
  run in parallel as before.  Ordering is preserved so
  ``post_tool_call`` hooks see results in LLM-declared order.
- [x] Subagent-lifecycle veto: a ``pre_subagent`` veto returns
  ``SubagentResult(exit_state=BLOCKED, summary="Blocked by hook
  'x': <reason>")`` before ``_run_inner`` runs, so the whole task
  is blocked (the LLM is never called, no tools execute, the
  executor records the result like any other BLOCKED task).  The
  ``post_subagent`` hook still fires with the exit state + a
  ``vetoed_by`` field so auditors see the attempt.
- [x] Compaction veto: a ``pre_compact`` veto skips the compact +
  emergency-truncate paths entirely so the context stays intact —
  exactly the Claude Code PreCompact behaviour the roadmap
  referenced.  ``post_compact`` does not fire when compaction was
  blocked.  Wired in both the synchronous ``_run_conversation_loop``
  and the streaming ``process_message_streaming`` paths.
- [x] 17 new unit tests: ``HookResult.vetoed`` across the four
  exit-code / timeout / continue-on-error permutations;
  ``veto_reason`` for stderr / empty / timeout cases;
  ``first_veto`` ordering; main-agent tool-call veto (tool skipped,
  LLM sees error) + non-vetoing failure preserved;
  ``pre_compact`` veto skips ``context_manager.compact``; subagent
  ``pre_subagent`` veto returns BLOCKED without calling the LLM;
  subagent ``pre_tool_call`` veto synthesises error without
  invoking the tool.
- [x] **46.4b — stdout-to-payload mutation landed.**  A
  ``pre_tool_call`` hook can now rewrite the pending tool
  arguments by printing a JSON envelope of the shape
  ``{"mutate": {"arguments": {...}}}`` to stdout; the object
  replaces ``tc.arguments`` before the tool runs.  Only
  ``pre_tool_call`` honours the envelope — other events parse
  and discard.  ``HookRunner.fire`` threads each successful
  mutation into the next hook's stdin payload, so chained hooks
  see the running composed state (``arguments.branch ==
  "main"`` filters work against a rewritten branch).  Vetoing
  hooks (``continue_on_error: false`` + non-zero exit) have
  their envelopes ignored because the call won't run.
  Malformed envelopes log at WARNING and are ignored; plain-text
  stdout is untouched so existing hooks keep working.
  ``HookResult`` gained a ``mutated_arguments: dict | None``
  field (the composed state after this hook's turn); new
  module-level ``final_arguments(results)`` walks a results list
  in reverse to pull the final mutation.  All three
  ``pre_tool_call`` sites wired (``core.py`` conversation +
  streaming + ``subagent.py`` gather path) — the subagent path
  records one ``call_arguments`` entry per tool call so the
  parallel ``asyncio.gather`` substitutes the mutated form per
  call.  ``post_tool_call`` receives the *effective* arguments
  so the audit trail reflects what actually ran.  21 new unit
  tests (``TestParseMutationEnvelope`` ×9,
  ``TestFinalArgumentsHelper`` ×5,
  ``TestHookRunnerAppliesMutations`` ×7).
  ``docs/src/howto-hooks.md`` gains a *Rewriting arguments*
  section with a ``run_shell`` token-redaction example.

### 46.5 Low — Hook telemetry and debugging ✓

- [x] ``HookStats`` accumulator in ``cantrip.hooks`` tracks per-hook
  invocations, successes, failures, vetoes, timeouts, total + average
  duration, and last-invoked timestamp.  ``HookRunner`` gained a
  ``set_listener(callback)`` method that fires after each executed
  hook (skipped-by-filter hooks don't feed the listener, keeping
  stats focused on actual executions).  Listener exceptions are
  swallowed at DEBUG so a broken telemetry sink can never abort the
  agent loop.
- [x] ``CantripAgent`` wires a listener at construction time that
  does two things on each executed hook: folds the result into its
  ``HookStats`` (exposed as ``agent.hook_stats``) and writes a
  ``hook_invocation`` transcript event into the session store via
  ``record_event("hook_invocation", detail)``.  Detail carries
  ``hook_name``, ``event``, ``exit_code``, ``duration_seconds``
  (rounded to 4 decimals), ``vetoed``, ``timed_out``,
  ``continue_on_error``, and a stderr excerpt (first 200 chars) when
  present — enough to reconstruct a failure without bloating the
  transcript with long stack traces.  ``sqlite3.Error`` during
  recording is logged at DEBUG.
- [x] ``/hooks`` slash command added to the shared dispatcher
  (``COMMAND_CATALOGUE`` + ``dispatch``), identical surface on CLI,
  TUI, and Web.  Three-section renderer: "no hooks configured"
  empty-state with config-path hints; grouped-by-event listing with
  ``if:`` filter source, **veto-capable** flag for
  ``continue_on_error: false`` hooks, and per-hook stats
  (invocations, successes/failures/vetoes/timeouts, avg duration,
  last-seen time) from ``HookStats.for_hook``; transcript-logging
  footer mirroring the ``/sandbox`` pattern.
- [x] ``cantrip hooks test <event> [--payload JSON] [--path DIR]``
  new argparse subcommand in ``cantrip.main``.  Validates the event
  name + ``--payload`` shape before loading config (so CLI errors
  surface the same way regardless of whether hooks happen to be
  configured), discovers via the same
  ``HookRunner.from_disk(repo_root=...)`` path as the live agent,
  and prints a per-hook summary with checkmarks (``✓`` success,
  ``∅`` veto, ``✗`` failure), duration, stdout/stderr excerpts.
  Useful while authoring a hook config: confirms the ``if:`` filter
  matches, the command exits cleanly, and how long it takes — no
  need to spin up an agent session.
- [x] 20 new unit tests: ``HookStats`` counter semantics (empty /
  success / failure / veto / timeout / avg-duration / sorted-
  snapshot); ``HookRunner.set_listener`` (called per hook / skipped
  for filtered / exception swallowed / detachable); end-to-end
  agent wiring (tool call feeds the stats accumulator);
  ``format_hooks_status`` renderer (empty runner, grouped listing,
  invoked-hook stats); ``_hooks_test`` CLI (unknown event, empty
  config, happy path, invalid JSON payload, non-object payload).
- [x] ``docs/docs/howto-hooks.html`` gets a new "Inspecting hooks"
  section describing ``/hooks`` and ``cantrip hooks test``, plus
  a pointer to the ``hook_invocation`` transcript event.  The
  "Current limits" item about stdout-capture-but-no-mutation
  stays — that's 46.4b territory, still open.

**Exit criteria:** Users can configure hooks via YAML, filter them with `if:`
expressions, and see their invocations in the transcript and `/hooks` view;
pre-hooks can veto actions; PreCompact hooks can block compaction. `make check`
passes throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Event taxonomy (46.1) | Phase 15.1 shared event bus | Reuses the same event plumbing |
| Config format (46.2) | 46.1 | Declares the events to bind to |
| Conditional filters (46.3) | 46.2 | Applied on the merged config |
| Result handling (46.4) | 46.2, Phase 40 compaction safety | PreCompact integrates with the compaction subsystem |
| Telemetry (46.5) | Phase 14.1 transcript recording | Hook events extend the transcript schema |

---

## Phase 51: Team Collaboration — Research

**Goal:** Investigate what Cantrip could do to support a *team* working on a
charm rather than an individual operator. Every assumption in the codebase
today is single-user: one laptop, one concierge-prepared local Juju
environment, one session, one decision log, one memory scope, one set of
approvals. This phase is exploratory — we do not yet know whether the right
answer is a thin shared-git-plus-PR workflow (Phase 42 already covers most of
that), a shared Cantrip server with per-user sessions backing a common state,
or a real-time collaborative agent with live presence. The purpose of this
phase is to figure out which of those — if any — fits with Cantrip's design,
and to produce a written recommendation.

This is a **research phase** — no production code changes expected.

### 51.1 User research

- [ ] Identify concrete team archetypes: charm-authoring team of 2–5, a
  charm-ops team operating across many charms, a charm-improvement team
  fixing issues in other people's charms (Canonical's own workflow is the
  closest datapoint)
- [ ] Map each archetype's friction against Cantrip today: where does the
  single-user assumption hurt? Candidates to probe: concurrent editing of the
  same charm, two operators deploying to the same model, review-before-push
  gates, sharing deploy credentials, passing a half-finished build between
  shifts, auditing who approved what
- [ ] Surface actual user requests — check Phase 42.2 issue-triage data and
  CHANGELOG feedback for team-shaped requests; interview 2–3 teams building
  charms today if possible

### 51.2 Remote and shared Juju controllers

- [ ] Document what changes when the target controller is not the local
  concierge-prepared environment — authentication, credential storage,
  controller discovery, cross-controller awareness (Phase 22.1 already
  enumerates controllers, but assumes they are local)
- [ ] Identify the Jubilant / Juju CLI behaviours that differ for remote
  controllers: `juju register`, macaroon auth, connection pooling, model
  isolation, and whether preflight checks make sense when the controller is
  shared
- [ ] Assess coordination hazards: two team members deploying the same charm
  to the same model, concurrent `juju config` writes, overlapping debug-log
  streams — which of these need Cantrip-side coordination vs Juju's existing
  semantics?
- [ ] Consider how charm-improvement mode (Phase 10) would behave against a
  production controller: what would "safe" mean in that context?

### 51.3 Shared interface

- [ ] Today's Web UI (Phase 15) is a single-user localhost server. Sketch
  what multi-user would look like: a shared server, per-user connections via
  the existing event bus (Phase 15.1), presence (who is viewing / editing),
  simple turn-taking vs true concurrent editing
- [ ] Identify the minimum viable shared interface: is it a read-only
  dashboard over a single author's Cantrip session, or does every user drive
  their own agent against shared state?
- [ ] Evaluate authentication models: SSO, GitHub OAuth (Phase 42 already
  uses `gh`), or a lightweight shared-secret pattern — each has different
  deployment-cost trade-offs

### 51.4 Shared state, memory, and decisions

- [ ] For each existing state scope, decide whether a team version makes
  sense: decisions log (currently per-session), memory (Phase 43 — per-charm
  and global; does per-team fit alongside those?), skills (currently local),
  transcripts (Phase 14 — currently personal, but teams might want a shared
  audit log)
- [ ] Consider attribution: if two users contribute to one session, how are
  their inputs labelled in transcripts and commits?
- [ ] Consider memory conflict: if two users teach Cantrip contradictory
  lessons about the same charm, who wins and how is the conflict surfaced?

### 51.5 Role-based workflows and approvals

- [ ] Map existing CONFIRM tasks (deploy, destructive actions, PR creation)
  to a role model: is the user who requested the action always the approver,
  or can approvals be delegated?
- [ ] Assess whether the Phase 46 hooks mechanism is enough to express
  team-specific approval policy, or whether team support needs a first-class
  role system
- [ ] Consider handoff: user A leaves a task mid-way (end of shift, blocked
  on a question); user B picks it up. What state needs to travel, and does
  session-resume (Phase 11.3 / 31.3) already cover it when the operator
  changes?

### 51.6 Candidate architectures

- [ ] **Thin (shared git + PR workflow):** each user runs their own Cantrip
  locally, coordination happens entirely through GitHub. Phase 42 already
  delivers most of this — the research question is what small additions
  (branch etiquette, assignee-based triage, PR-level decision sharing) would
  close the remaining gaps
- [ ] **Medium (shared Cantrip server):** one long-running Cantrip process
  per team with a web-authenticated UI; per-user sessions share the memory,
  decisions, and transcript layers. This is the Windsurf Agent Command
  Center / Cursor self-hosted cloud-agents shape
- [ ] **Heavy (real-time collaborative agent):** multiple users drive the
  same session simultaneously with presence and live artefacts (Cursor
  Canvases). Probably too ambitious without clear demand
- [ ] For each candidate, list: estimated implementation cost, new failure
  modes introduced, parts of the existing codebase affected, and which
  user-research archetypes it serves

### 51.7 Decision and write-up

- [ ] Write a findings document summarising: whether team support is a
  direction Cantrip should pursue at all, which archetype(s) are worth
  optimising for, which candidate architecture fits Cantrip's
  single-operator-biased design with the least disruption, and what the
  explicit non-goals are
- [ ] If any direction is promising, outline a concrete follow-on phase with
  scoped sub-items — but be willing to conclude "not now" if the user
  research or architecture sketch does not support it
- [ ] Capture the written assessment in `design/` alongside the ACP research
  output so future planning has a shared reference

**Exit criteria:** A written assessment of whether Cantrip should support
teams, which team archetypes are worth targeting, which architectural
direction best fits Cantrip's design, and whether the next step is a concrete
implementation phase or a deliberate decision to stay single-user. `make
check` passes throughout (this phase should not add code beyond a findings
document).

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| User research (51.1) | None | Pure research; can start any time |
| Remote controllers (51.2) | Phase 22 multi-controller | Builds on existing controller awareness |
| Shared interface (51.3) | Phase 15 Web UI | Extends the existing event bus + server |
| Shared state (51.4) | Phase 43 memory | Memory scopes are the natural extension point |
| Role workflows (51.5) | Phase 46 hooks (if adopted) | Hooks may obviate a bespoke role system |
| Architecture sketches (51.6) | 51.1–51.5 | Needs the research inputs to sketch against |
| Decision write-up (51.7) | 51.6 | Consolidates into a recommendation |

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

The target publishing destination is **`canonical/copilot-collections`**
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

### 56.3 Medium — Publish to `canonical/copilot-collections`

- [ ] Create the repo structure under `canonical/copilot-collections`
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
  maintains control via `canonical/copilot-collections`; upstreaming
  to awesome-copilot is a possible future step, not part of this
  phase.
- Not Juju-specific IDE plugins or VS Code extensions.  Assets only —
  the installation story leans on existing Copilot / Claude Code
  mechanisms.

**Exit criteria:** `canonical/copilot-collections/juju/` (or the
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

## Phase 65: TUI Right-Panel Review — Task Panel and Multi-Model Pane

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

### 65.1 Medium — Audit the task panel

- [ ] Sit with a non-trivial session (several research / build /
  test tasks) and capture screenshots of the pinned section,
  collapsed group rows, expanded detail, and the subagent-phase
  indicator in every state transition (pending → active →
  done / failed / blocked).
- [ ] Write the findings into the roadmap or a short design note
  under ``design/``.  Likely candidates based on a read of
  ``src/cantrip/tui/widgets/tasks.py``: the ``_format_detail``
  helper uses leading spaces for indent (fine in a ``RichLog``,
  awkward in a ``Static`` with a CSS margin), the collapsed-group
  row "✓ N tasks done (click to show)" doesn't visually align
  with active group headers, and the ``⟳ Category · Title``
  pinned format collides with the ``⟳ Title`` category format
  when the same task category sits in both places.
- [ ] Fix each finding as its own commit so blame stays
  comprehensible.

### 65.2 Medium — Decide what the multi-model pane should show

- [ ] For each mode Cantrip runs in (dev model only, dev + COS,
  pre-deploy), list what the pane currently shows and what would
  *actually* help the user.  Candidate answers: collapse the COS
  section by default (already done; confirm it's still useful
  when expanded), hide the pane entirely until a model is
  connected, inline the single most useful datum (e.g.
  "3 apps, 1 error" summary) so the pane earns its vertical
  space without taking the full ``1fr`` allowance.
- [ ] Either rework ``MultiModelStatusWidget`` to match the chosen
  design, or retire it in favour of a one-line status strip and
  move Juju detail to the existing ``/status`` modal.

### 65.3 Low — Spacing and consistency

- [ ] Review the right-panel CSS (``cantrip.tcss``) after 65.1 and
  65.2 land: dividers, padding, ``max-height: 50%`` on
  ``#task-checklist`` vs ``#charm-files``, and whether the
  retired/shrunk multi-model pane still needs ``height: 1fr``.

### What this phase is *not*

- Not a redesign of the task data model.  Categories, statuses,
  pinned rules all stay as they are.
- Not a Web-UI counterpart — Web follows in a later phase once
  the TUI answers are clear.

**Exit criteria:** written audit of the task panel committed;
each audit finding resolved in its own commit; the multi-model
pane either shows genuinely useful information in every mode or
is retired; manual walk-through in a live session confirms the
right panel looks tidy from empty state through mid-build through
completion.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Task audit (65.1) | none | Independent |
| Multi-model decision (65.2) | none | Independent |
| CSS cleanup (65.3) | 65.1, 65.2 | Follows the widget changes |

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

## Phase 70: Amp-Inspired Depth — Librarian, Oracle, Scoped Guidance, Prompt Checks

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

### 70.1 High — Librarian: Charmhub and Launchpad cross-charm search

- [ ] New read-only subagent under ``src/cantrip/agent/subagents/``
  (name ``librarian`` or ``charm_search`` — pick during design).
  Tools limited to a small whitelist: ``charmhub_search``,
  ``charmhub_fetch``, ``launchpad_search``, ``launchpad_fetch``,
  ``webfetch`` (fallback), and read-only fs tools scoped to
  a cache directory.
- [ ] ``charmhub_search`` tool hits the Charmhub API
  (``api.charmhub.io``; document the exact endpoints in the
  phase) for name/keyword/topic search, returns structured
  hits with charm name, maintainer, last-release date, tags,
  and a quality signal (has-tests, publishes-to-latest, uses
  ops-vs-reactive).
- [ ] ``charmhub_fetch`` pulls a charm's source tarball (or
  Launchpad/GitHub URL from the charm's metadata) into a
  read-only cache under ``~/.cache/cantrip/charm-library/``
  and returns a navigable file tree.  TTL on the cache; never
  writes outside the cache path.
- [ ] Filters: the subagent is told "find charms that use X"
  where X is the user's problem shape — the agent applies
  a quality filter (maintained within last 12 months,
  non-draft, has ``src/charm.py`` or equivalent) before
  surfacing excerpts.
- [ ] Output contract: every hit comes back as
  ``{charm, source_url, snippet, why_this_matches,
  quality_flags}`` so the primary agent can cite without
  paraphrasing.  Citations land in the transcript (Phase 14).
- [ ] Invocation: primary agent dispatches during
  RESEARCH-phase tasks; user can force via a new
  ``/search-charms <query>`` slash command.  Results feed
  the design document (Phase 5).
- [ ] ``tests/unit/test_librarian.py`` against a recorded
  fixture set — no live Charmhub hits in unit tests.
- [ ] Document in ``docs/docs/howto-charm-library.html``.

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

### 70.5 Medium — Painter: charm icon generation

- [ ] New tool ``charm_icon_generate`` available during the
  BUILD phase.  Inputs: workload name, one-line description,
  optional palette hint, optional reference-image paths
  (up to three, matching Amp's limit).  Output: an
  ``icon.svg`` written to the charm root.
- [ ] Backend: provider-agnostic image tool abstraction in
  ``src/cantrip/llm/image.py`` (new) with at least one
  implementation (Gemini image, as Amp uses, or whatever
  Phase 48's multimodal work settles on).  Other providers
  slot in behind the same interface.
- [ ] Charmhub constraints baked into the system prompt for
  the image call: square aspect, flat/simple style, high
  contrast, legible at 64×64 and 32×32, no embedded text.
  Regenerate-from-reference is supported so a charm team can
  iterate against their visual language.
- [ ] Output is emitted as raster first (PNG) and converted
  to SVG via ``potrace`` or equivalent, with a warning to
  the user that a designer hand-polish is still recommended
  before release.  Reasoning: reliable SVG generation from
  image models is still weak; rastering then tracing is the
  honest path.
- [ ] Invocation surface: ``/icon [description]`` slash
  command for interactive use, plus an auto-invocation path
  during ``cantrip run`` when the charm is missing a
  non-default ``icon.svg`` at BUILD completion (asks first
  via a CONFIRM task from Phase 64; never silently
  overwrites an existing icon).
- [ ] Cost accounting mirrors Oracle (70.2): a
  ``max_icon_cost_per_session`` cap so nobody racks up a
  bill iterating on icons.
- [ ] Document in ``docs/docs/howto-charm-icon.html`` with
  the Charmhub icon-style guidance and the
  "designer-polish-before-release" disclaimer.
- [ ] ``tests/unit/test_icon_generation.py`` — stubbed
  image provider, output paths, CONFIRM integration, cost
  cap, refusal to overwrite a non-default existing icon.

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

- [ ] Add ``cantrip permissions test`` (Amp parity) — evaluates
  every rule in the permission config against a set of
  hypothetical tool calls and prints the matching rule and
  outcome.  One-hour addition to 68.2; listed here so the
  idea doesn't get lost.

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
  <noreply@canonical.com>`` trailer.  Subject line is
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

## Phase 72: Continue-Inspired Context Providers — @-Mentions, Indexed Docs, Model Roles, Diagnostics Priming

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

### 72.1 High — Indexed charm-ecosystem documentation (``@docs``)

- [ ] New subsystem ``src/cantrip/docs_index/`` with a crawl
  + embed + local vector-store pipeline.  Target sites, all
  opt-in via config:
  - Juju documentation (``juju.is/docs`` and
    ``canonical-juju.readthedocs-hosted.com``)
  - Ops reference (``ops.readthedocs.io``)
  - Charmcraft reference
    (``canonical-charmcraft.readthedocs-hosted.com``)
  - Rockcraft reference
    (``canonical-rockcraft.readthedocs-hosted.com``)
  - Jubilant docs (``canonical-jubilant.readthedocs-hosted.com``)
  - Charmhub charm-guidelines page
- [ ] Storage: SQLite + ``sqlite-vec`` (or ``faiss`` if it's
  already in the dependency tree) at
  ``~/.cache/cantrip/docs-index/<site-hash>/``.  Chunk size
  ~500 tokens; overlap 50.  Embed with the provider's
  ``embed``-role model (72.3) — fall back to a local
  sentence-transformer model if no remote embed provider
  is configured.
- [ ] ``cantrip docs index [--site <name> | --all]``
  subcommand triggers a crawl; ``cantrip docs refresh``
  updates incrementally.  Transparent caching: docs older
  than ``settings.docs.max_age_days`` (default 14) get
  re-crawled.
- [ ] Retrieval surface: a new ``docs_search`` tool the
  agent can invoke, and the 72.2 ``@docs`` mention for
  user-initiated lookups.  Both return ``{site, url,
  excerpt, score}`` tuples so every citation is
  traceable — never paraphrase.
- [ ] Prompt guidance (``src/cantrip/agent/prompts/system.py``)
  teaches the agent to consult ``docs_search`` before
  answering "how do I …" questions about the charm
  ecosystem.
- [ ] Document in ``docs/docs/howto-docs-index.html``
  (new page).
- [ ] ``tests/unit/test_docs_index.py`` — crawl a fixture
  tree, embed with stub provider, query and assert
  top-k ordering.

### 72.2 High — ``@``-mention context-provider registry

- [ ] Central registry in
  ``src/cantrip/agent/context_providers.py`` with a
  ``ContextProvider`` protocol: ``name``, ``description``,
  ``expand(args: str) -> list[ContextBlock]``.  Tab-complete
  integrates with Phase 61 autocomplete.
- [ ] Baseline providers:
  - ``@file <path>`` — inline file contents (existing
    ``fs_read`` under new surface)
  - ``@diff`` — ``git diff`` since last commit
  - ``@tree [path]`` — directory tree (respects
    ``.gitignore``)
  - ``@terminal`` — last N lines of the Phase 69.3 shell-
    mode output buffer
  - ``@url <url>`` — ``webfetch`` result, markdownified
  - ``@problems`` — see 72.4
  - ``@docs <site> <query>`` — see 72.1
  - ``@charm <name>`` — fetch charm metadata + source index
    via Phase 70.1 Librarian
  - ``@juju <show-unit <app/0> | status | config <app>>`` —
    inline juju read-only output
- [ ] Expansion happens in the TUI/Web input layer before
  the message reaches the agent, so the agent sees a fully-
  expanded prompt (one fewer tool call needed) and the
  transcript records both the typed form and the expanded
  form.
- [ ] Bounded: each provider has a token budget
  (``settings.context_providers.<name>.max_tokens``,
  reasonable defaults per provider).  Over-budget content
  is truncated with a summary line ("file truncated; use
  ``@file <path> --full`` to override").
- [ ] Third-party providers registered via Phase 46 hooks
  or MCP (Phase 45) — don't lock this to built-ins.
  Document the protocol in
  ``design/CONTEXT_PROVIDERS.md`` (new).
- [ ] ``tests/unit/test_context_providers.py`` — parsing
  ``@foo bar baz`` correctly, expansion + token-budget
  enforcement, unknown-provider graceful handling, transcript
  records both forms.

### 72.3 Medium — Model roles: embed and rerank

- [ ] Extend the provider-config schema (``cantrip.yaml``)
  to let a provider declare ``roles: [chat, edit, apply,
  embed, rerank, summarize]``.  Default for an unnamed
  provider is ``[chat, edit]`` — today's behaviour, no
  migration required.
- [ ] Provider-layer hook: ``provider.embed(texts: list[str])
  -> list[list[float]]`` and ``provider.rerank(query: str,
  docs: list[str]) -> list[int]``.  Not every provider has
  to implement these; the layer raises a clean "no embed
  provider configured" error with a pointer to the docs.
- [ ] Concrete implementations: Anthropic/Voyage for
  ``embed``; Anthropic/Voyage for ``rerank``; OpenAI for
  both; a local ``sentence-transformers`` fallback shipped
  as an optional dependency for offline use.
- [ ] Retrieval-using callers (72.1 ``@docs``, future
  Phase 43 memory retrieval) depend on this — land it
  first in this phase so those features have infrastructure.
- [ ] Cost accounting: embed and rerank calls enter the
  same ``/cost`` breakdown as chat/edit, under distinct
  role labels so it's clear where the spend is.
- [ ] ``tests/unit/test_provider_roles.py`` — role routing,
  fallback behaviour, cost tracking per role, missing-role
  error path.

### 72.4 Medium — Diagnostics-as-pre-turn-context (``@problems``)

- [~] ``@problems`` context provider (registered in 72.2)
  runs, on expansion:
  - ``ruff check --output-format=json .`` (or just the
    charm's ``src/`` and ``tests/`` to keep it cheap)
  - ``ty check --output-format json .``
  - ``charmlint --format json`` (from Phase 24)
  and emits a compact block grouping issues by severity and
  file, capped at 1500 tokens (longer reports get
  summarised with a "N more issues suppressed; run
  ``cantrip lint`` for the full list").  **Aggregator,
  truncation, and "N more suppressed" footer landed in
  ``cantrip.agent.lint_context``; the ``@problems`` mention
  surface waits on the Phase 72.2 ``@``-provider registry.**
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

## Phase 82: Pre/Post Tool Captions — Inline Status Replacement

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

### 82.1 Core — ``intro_caption`` hook + pending event

- [ ] Add ``intro_caption(arguments)`` to ``Tool`` in
  ``cantrip.agent.tools.base`` — optional method returning a
  present-continuous string.  Default returns ``None`` so existing
  tools keep working unchanged.
- [ ] Synthesise a generic fallback (``"Running <tool_name>…"`` or
  ``"<verb> <key>=<value>…"`` derived from
  ``_CAPTION_KEY_PREFERENCE``) when no override is set.
- [ ] Emit a new ``TOOL_INVOKED_PENDING`` event from the agent loop
  and the subagent runner *before* dispatching the tool, carrying
  the intro caption and the tool-call id.  ``TOOL_INVOKED`` keeps
  its existing payload and is matched to the pending event by
  tool-call id at the renderer.

### 82.2 Bespoke intro captions for high-traffic tools

- [ ] File-system: ``read_file`` → ``"Reading src/charm.py…"``,
  ``write_file`` → ``"Writing tests/integration/test_charm.py…"``,
  ``edit_file`` / ``multi_edit`` → ``"Editing <path>…"``.
- [ ] Git: ``git_clone`` → ``"Cloning <url>…"``, ``git_commit`` →
  ``"Committing…"``, ``git_push`` → ``"Pushing to <remote>/<branch>…"``.
- [ ] Charm tooling: ``charmcraft_pack`` →
  ``"Packing the charm…"``, ``quick_pack`` →
  ``"Quick-packing…"``, ``charm_validate`` →
  ``"Validating the charm…"``, ``charm_audit`` →
  ``"Auditing the charm…"``.
- [ ] Juju: ``juju_deploy`` → ``"Deploying <app>…"``,
  ``juju_wait`` → ``"Waiting for <model> to settle…"``,
  ``juju_refresh`` → ``"Refreshing <app>…"``,
  ``juju_status`` → ``"Reading juju status…"``.
- [ ] Acceptance / observability: ``run_charm_tests`` →
  ``"Running unit tests…"`` / ``"Running integration tests…"``,
  ``tempo_query`` → ``"Querying Tempo…"``, ``loki_query`` →
  ``"Querying Loki…"``.
- [ ] Web / registry: ``web_fetch`` → ``"Fetching <host>…"``,
  ``registry_search`` → ``"Searching Docker Hub…"``,
  ``registry_image_info`` → ``"Inspecting <image>…"``.

### 82.3 Renderers — in-place update by tool-call id

- [ ] TUI: render the pending block with a spinner glyph; replace
  it with the ``TOOL_INVOKED`` line when the matching event
  arrives.  No new chat lines — the block updates in place.
- [ ] Web UI: same behaviour with a CSS spinner that swaps to the
  Phase 75 success/failure colour cue on update.  Match the
  event-bus contract documented in ``design/UI.md``.
- [ ] Failure path: if the tool errors before producing a
  ``TOOL_INVOKED`` (timeout, cancellation, dispatcher exception),
  the pending block must still resolve — convert it to an error
  line rather than leaving a dangling spinner.

### 82.4 Tests

- [ ] Unit: ``intro_caption`` default + per-tool overrides return
  the expected strings; tool-call id round-trips between the
  pending and final events.
- [ ] Renderer integration: emit pending then final, assert the
  rendered transcript contains exactly one inline block per tool
  call (no duplicate lines).
- [ ] Failure path: emit pending then a synthetic dispatcher
  exception; assert the block becomes an error line, not an
  orphan spinner.

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

## Phase 83: Pause-and-Edit Interrupt — Research

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

### 83.1 Research — survey peer interrupt models

- [ ] Catalogue how Claude Code, Cursor, Aider, Goose, and Amp
  handle mid-turn interruption: hard cancel, soft pause, edit-in-
  place, queue-next-instruction, or some combination.  Note the
  keybinding, the surfaced affordance, and what state the agent
  preserves across the interrupt (tool-call buffer? assistant
  partial text? reasoning trace?).
- [ ] Inventory user complaints / feature requests in those
  projects' issue trackers for "lost my context after Ctrl+C" or
  "wish I could amend mid-turn" — a small number of high-signal
  asks is the trigger to pursue this.

### 83.2 Design — what would "pause and edit" mean for Cantrip

- [ ] Identify the resumable unit.  Cantrip's loop interleaves
  model calls and tool calls; pausing *between* steps is cheap
  (just stop dispatching the next step) but pausing *during* a
  long tool call (``charmcraft_pack``, ``juju_wait``) is harder —
  the tool keeps running unless we kill it.  Decide which is the
  product.
- [ ] Sketch the TUI affordance.  Options: (a) <kbd>Esc</kbd>
  pauses, second <kbd>Esc</kbd> cancels — chord-style; (b) a
  dedicated keybind (<kbd>Ctrl+P</kbd>?) for pause; (c) an
  on-screen "Pause" button alongside the thinking indicator.
  Note the collision risk with Phase 76 (``/copy``) and the
  modal-Escape behaviour from Phase 65.
- [ ] Sketch the message-flow change.  When the user types into
  a paused turn, where does the edit go: prepended to the next
  user turn, replacing the in-flight system note, or injected as
  a tool-result-style synthetic message?  Each shape has a
  different effect on the model's understanding of what just
  happened.

### 83.3 Decision — ship, defer, or drop

- [ ] Write up findings in ``design/PAUSE_AND_EDIT.md`` (mirror
  the Phase 39 ACP write-up format): peer survey table,
  decision, and revisit triggers.
- [ ] If "ship": carve out a Phase 83b implementation phase with
  concrete agent-loop, TUI, Web UI, and event-bus deltas.
- [ ] If "defer / drop": record the reason and the conditions
  that would re-open it (e.g. user reports "I keep losing my
  half-built design when I cancel", or a peer ships a clearly
  better pattern worth copying).

### What this phase is *not*

- Not a commitment to ship pause-and-edit.  This phase is a
  decision gate; Phase 82 already covers the inline-status side
  of mid-turn responsiveness.
- Not a rework of the existing cancel path.  Hard cancel via
  <kbd>Ctrl+C</kbd> / <kbd>Esc</kbd> stays as-is regardless of
  outcome.

**Exit criteria:** ``design/PAUSE_AND_EDIT.md`` exists and lands
on a verdict (ship / defer / drop) with explicit revisit
triggers.  If the verdict is "ship", a Phase 83b implementation
phase is scoped.

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

### 84.1 Build the deferred-item index

- [ ] Grep ``ROADMAP.md`` and ``ROADMAP_ARCHIVE.md`` for the
  explicit-deferral markers we already use: ``Deferred:``,
  ``defer pending``, ``revisit when``, ``re-open when``,
  ``deferred follow-up``, ``follow-up phase``.  Capture the
  surrounding context (which phase, which sub-task) and the
  stated revisit trigger for each hit.
- [ ] Save the catalogue as ``design/DEFERRED.md`` — a flat
  table with columns *Phase / Sub-task*, *What was deferred*,
  *Revisit trigger*, *Notes*.  One row per deferral.  This is
  the artefact the next pass reads.

### 84.2 Re-evaluate each deferral

- [ ] For each entry: has the revisit trigger fired?  Three
  buckets per row.
  - **Trigger fired** — open a new sub-phase or task to land
    the work, link it back to the deferral, mark the row as
    re-opened.
  - **Trigger not fired** — leave the deferral in place but
    refresh the trigger description if the original wording is
    stale.
  - **No longer relevant** — the underlying need disappeared,
    the world moved on, or the surrounding phase's verdict
    changed.  Delete the deferral entry and the original
    bullet, with a one-line note in the archive explaining the
    drop.
- [ ] Stamp the audit date on ``design/DEFERRED.md`` after the
  pass so the next sweep knows what it's looking back over.

### 84.3 Schedule the next sweep

- [ ] Pick a cadence that matches the rate at which deferrals
  arrive — quarterly seems right based on the current rate.
  Record the cadence in ``design/DEFERRED.md`` and use the
  ``/schedule`` background-agent surface to fire a reminder
  rather than relying on someone to remember.

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

### 85.1 Sweep — close the small style drifts

- [ ] Replace `from datetime import datetime` at
  `src/cantrip/tui/widgets/chat.py:6` with `import datetime`
  and update call sites in that file.  This is the only
  `from datetime import datetime` left in `src/cantrip/`.
- [ ] Annotate or narrow the four `except Exception` clauses
  that lack a rationale comment to match the project's
  established `# noqa: BLE001 - <reason>` pattern (the other
  24 already do): `src/cantrip/hooks.py:845`,
  `src/cantrip/agent/github_issues.py:354`,
  `src/cantrip/agent/core.py:881`,
  `src/cantrip/agent/executor.py:772`.  Prefer narrowing to a
  specific exception when the call site supports it; only fall
  back to `Exception` with a documented reason.
- [ ] Decide the `Path` / `dataclass` import policy and apply
  it.  The codebase is currently split (51 files use
  `from pathlib import Path`, 27 use `import pathlib`; same
  for `dataclass`/`dataclasses`).  Either: (a) carve `Path`
  and `@dataclass` out as runtime exceptions in
  `AGENTS.md` and leave the present mix; or (b) commit to
  module-only imports and codemod the minority side.  Whatever
  the choice, document it in `AGENTS.md` and resolve the
  inconsistency.

### 85.2 Move — `agent/memory/` subpackage

- [ ] Convert the four-file memory family into a subpackage:
  `agent/memory.py` (1 017 lines) becomes `agent/memory/
  core.py`; `agent/memory_writer.py` →
  `agent/memory/writer.py`; `agent/memory_export.py` →
  `agent/memory/export.py`; `agent/memory_commands.py` →
  `agent/memory/commands.py`.
- [ ] Re-export the public surface (currently
  `MemoryEntry`, `MemoryManager`, plus the writer/export
  entry points imported by `agent/core.py`) from
  `agent/memory/__init__.py` so import sites elsewhere change
  by one segment, not by symbol.
- [ ] Update test imports and move
  `tests/unit/test_memory*.py` (4 files) into
  `tests/unit/agent/memory/` to mirror.
- [ ] Run `make check` and `make unit`; confirm no behavioural
  drift.

### 85.3 Move — `agent/commands/` subpackage

- [ ] Group the slash-command handlers into one folder:
  `agent/slash_commands.py` (1 663 lines) →
  `agent/commands/slash.py`; `agent/custom_commands.py` →
  `agent/commands/custom.py`; `agent/memory_commands.py`
  (already moving to `agent/memory/` in 85.2 — keep it there
  and re-export from `agent/commands/__init__.py` if the
  dispatcher prefers a single entry point);
  `agent/mcp_commands.py` → `agent/commands/mcp.py`.
- [ ] If `agent/commands/slash.py` is still >1 000 lines after
  the move, split the bigger handler clusters out:
  `commands/budget.py`, `commands/cost.py`, `commands/map.py`,
  `commands/share.py`, `commands/transcript.py`.  Keep
  `dispatch()` and `_dispatch_inner()` in
  `commands/__init__.py` so the entry point stays singular.

### 85.4 Decompose — `CantripAgent` god class

- [ ] Extract one cohort at a time as a delegate object held
  by `CantripAgent`.  The seven natural cohorts (with rough
  line ranges in `agent/core.py`):
  1. **MCP lifecycle** (lines 2911-3025) — `mcp_registry`,
     `mcp_marketplace_sources`, `mcp_marketplace_loader`,
     `start_mcp`, `complete_mcp_elicitation`, `stop_mcp`.
     Most self-contained; do this one first.
  2. **Executor lifecycle** (2786-2910) — `executor_running`,
     `start_executor`, `stop_executor`, plus the wrapper
     callbacks.
  3. **Watcher lifecycle** (2023-2150) — `watcher_running`,
     `start_watcher`, `stop_watcher`, `route_watcher_event`,
     `process_watcher_event`.
  4. **Issue triage** (2152-2270) — `issue_triage_running`,
     `start_issue_triage`, `stop_issue_triage`,
     `retriage_issues`, `comment_on_issue`,
     `check_upstream`.
  5. **Arena** (2388-2480) — `active_arena`,
     `begin_arena`, `handle_arena_pick`.
  6. **Confirmations router** (2480-2780) —
     `handle_race_confirmation`, `handle_push_confirmation`,
     `handle_pr_creation`, `handle_repo_bootstrap`,
     `handle_triage_confirmation`,
     `should_offer_bootstrap`,
     `build_repo_bootstrap_confirm_task`.
  7. **Session persistence** (3026-3290) —
     `save_state`, `preview_session`, `transcript_tail`,
     `archive_session`, `load_state`,
     `build_resume_summary`.
- [ ] For each extraction: introduce a focused class in its
  own module (e.g. `agent/mcp_controller.py`,
  `agent/watcher_controller.py`, `agent/arena_controller.py`,
  `agent/confirmations.py`, `agent/persistence/session.py`),
  hold an instance on `CantripAgent` as
  `self._mcp` / `self._watcher` / etc., keep the existing
  property/method names on `CantripAgent` as one-line
  delegators (so the public surface used by `cli.py`,
  `tui/app.py`, `web/server.py`, `slash_commands.py`,
  `print_mode.py` does not move).
- [ ] After all seven cohorts move, `agent/core.py` should
  drop below 1 500 lines and contain mostly `process_message`,
  `process_message_streaming`, `prepare`, `warm_up`, the
  property accessors, and the run-time hooks.  Re-check the
  number; the goal is comprehensibility, not a target line
  count.
- [ ] No public-API rename in this phase.  Each step must
  preserve external behaviour and import paths so the diff
  reviews as a pure refactor.

### 85.5 Decompose — `BackgroundExecutor` and `CantripApp`

- [ ] `agent/executor.py` (1 713 lines) already shows clean
  internal cohorts: split `_DefaultGitService` (lines 146-258)
  to `agent/executor/git_service.py`,
  `_DefaultEnvironmentChecker` (260-285) and
  `_DefaultFollowupPlanner` (287-298) to
  `agent/executor/policies.py`, `_SessionStoreAdapter`
  (299-330) to `agent/executor/store_adapter.py`.  Leave
  `BackgroundExecutor` itself in `agent/executor/core.py`
  (or `agent/executor.py` if the rest is small enough).
- [ ] `tui/app.py` (1 859 lines) is one `CantripApp` class
  with 83 methods.  Group action handlers by surface — chat
  actions, status actions, screen-switching actions,
  watcher/executor actions — and lift each group into a
  module under `tui/actions/` that takes the app instance as
  argument.  Keep `compose()`, `on_mount()`, and Textual
  reactive plumbing in `tui/app.py`.

### 85.6 Decompose — function-level giants

- [ ] `src/cantrip/agent/tools/publishing.py:1108
  generate_docs_scaffold` (502 lines).  Currently emits
  ~30 documentation files via inline f-string concatenation.
  Move the templated content out alongside the existing
  Jinja templates the prompts subsystem uses: create
  `src/cantrip/charm/docs_templates/` (or extend
  `src/cantrip/charm/templates/`) with one `.md.j2` /
  `.rst.j2` per generated file, and reduce the function to a
  loop that walks the template list and renders each.
  Acceptance-artefact substitution stays in the renderer; the
  templates carry only the static skeleton.
- [ ] `src/cantrip/main.py:46 parse_args` (452 lines).
  Argparse setup is naturally splittable: extract one
  `_add_X_options(parser)` helper per subsystem (model,
  session, hooks, web, watcher, etc.), keep the top-level
  `parse_args` as a slim composition of those helpers.  No
  CLI behaviour change.
- [ ] `src/cantrip/agent/tools/rockcraft.py:915
  _deploy_k8s_registry` (128 lines) and the four `juju.py`
  `execute()` methods that exceed 100 lines (lines 188,
  1381, 1821, 2048): extract the body into
  module-private helpers per logical phase.  These do not
  block the phase; they are the next-cleanest one-shot
  improvements once the bigger moves above land.

### 85.7 Move — top-level Python files into packages

- [ ] `src/cantrip/hooks.py` (946 lines) →
  `src/cantrip/hooks/` with at least
  `hooks/runner.py` (the executor + stats), `hooks/config.py`
  (loading/parsing), and `hooks/types.py` (the dataclasses).
  Re-export the public API from `hooks/__init__.py`.
- [ ] `src/cantrip/update.py` (817 lines) → `update/` with
  `update/check.py`, `update/install.py`, `update/release.py`
  (or whatever the existing internal cohorts suggest after a
  closer read).
- [ ] `src/cantrip/main.py` (1 080 lines) — once 85.6 has
  removed the `parse_args` block, decide whether the
  remaining `_run` plus helpers warrants a package or stays
  flat.  Likely stays flat at ~600 lines; defer this bullet
  if so.

### 85.8 Mirror — `tests/unit/` folder structure

- [ ] Move test files into folders that mirror `src/cantrip/`
  for the heaviest groups.  Concretely:
  `tests/unit/agent/` (catch-all for non-grouped agent tests),
  `tests/unit/agent/memory/` (already covered in 85.2),
  `tests/unit/agent/commands/`, `tests/unit/agent/tools/`,
  `tests/unit/llm/`, `tests/unit/mcp/`, `tests/unit/tui/`,
  `tests/unit/web/`, `tests/unit/repomap/`.  The 167-flat-
  files state at the top level of `tests/unit/` is the
  symptom; the goal is that browsing the test tree gives
  the same shape as browsing `src/`.
- [ ] Keep the existing sub-folders in place (`executor/`,
  `subagent/`, `planner/`, `charm_tools/`, `charmlint/`,
  `quickpack/`) — they're already correctly grouped.
- [ ] Rename one ambiguous pair: `tests/unit/test_tool_caption.py`
  (helper unit-tests) and `tests/unit/test_tool_captions.py`
  (per-tool integration tests) differ only by an `s`.  Pick
  unambiguous names — e.g. `test_caption_builder.py` and
  `test_caption_coverage.py`.
- [ ] Run `make unit` after the moves; pytest discovery is
  path-relative so this is mostly a `git mv` exercise plus
  `__init__.py` housekeeping.

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
| M7: Showcase | 7 | Demo-ready with full ecosystem, testing, and publishing |
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
| M56: Juju Copilot Bundle | 56 | `canonical/copilot-collections` hosts a Juju-specific instruction/skill bundle derived from Cantrip's system prompt, with CI validation and a regeneration path |
| M57: Test Cleanup | 57 | Unit coverage ≥85%; zero test warnings; oversized unit files split; quickpack tests reorganised to match charmlint |
| M58: Rust Tested | 58 | `cargo test` runs in CI for both Rust crates; every `.rs` file above 60% coverage; regressions surface at unit-test time, not via spread |
| M59: Property Tested | 59 | Hypothesis-backed property tests cover the planner dependency graph, charmlint rule engine, quickpack jujuignore, and watcher status-diff |
| M60: Accessible Web UI | 60 | Web UI passes WCAG 2.1 AA: visible focus indicators, labelled controls, live regions for chat/status, overlays behave as modal dialogs; rodney/showboat regression guard in CI |
| M61: Slash Autocomplete | 61 | Typing ``/`` in the TUI surfaces a catalogue-driven suggestion popup; Tab completes the active verb; CLI readline gets the same catalogue for parity |
| M62: On-Theme Activity Labels | 62 | Status-bar and Web "Thinking..." literals replaced by randomly-selected spellcasting verbs (incanting, conjuring, brewing, …) so the UI matches the cantrip/juju theme |
| M63: Self-Update Check | 63 ✓ | PyPI polled at startup; TUI, Web, and CLI surface a non-blocking notice with filtered changelog and an installer-aware upgrade command when a newer Cantrip is published |
| M64: Polite Repo Bootstrap | 64 ✓ | Create-GitHub-repo offer moved out of the main chat and suggests ``<workload>-operator`` by default |
| M65: Right-Panel Tidy | 65 | TUI task panel audited and tightened; multi-model pane either earns its space or is retired |
| M66: Transcript/Log Visible | 66 ✓ | Transcript and debug-log modals render their content (or a clear empty state) on every launch, with a smoke test guarding the fix |
| M67: Pi-Inspired Sessions | 67 ✓ | Session tree rewind/branch, mid-session ``/model``, ``cantrip run --print --json`` for scripts, and ``/share`` to secret gist — four gaps the Pi coding agent fills that charm authors also hit |
| M68: OpenCode Safety Rails | 68 ✓ | Snapshot-backed ``/undo``/``/redo`` for file changes, declarative ask/allow/deny permissions, markdown-defined user slash commands, and a session-level plan mode — four guardrails adopted from OpenCode that map onto Cantrip's existing subsystems |
| M69: Kimi Workflow Features | 69 | Bounded Ralph-Loop iterate-until-green, ``--yolo`` unattended switch, ``Ctrl-X`` shell mode, and Mermaid/D2 Flow skills — four Kimi CLI patterns that fit Cantrip's autonomous loop, skill system, and CI story |
| M70: Amp-Inspired Depth | 70 | Librarian subagent that searches Charmhub and Launchpad, Oracle tool for on-demand second-opinion reasoning, glob-conditional guidance in AGENTS.md / skills, prompt-based review Checks that layer on top of charmlint, and a Painter tool that generates a Charmhub-style ``icon.svg`` |
| M71: Aider Engineering Hygiene | 71 ✓ | Tree-sitter-backed repo-map with graph-ranked symbols, architect/editor two-model mode, auto-commit-per-turn with dirty-commit separation, and a per-edit ruff/ty/charmlint feedback loop |
| M72: Continue Context Providers | 72 | Indexed charm-ecosystem docs (``@docs juju|ops|charmcraft|rockcraft``), an ``@``-mention context-provider registry, ``embed`` and ``rerank`` model roles, and ``@problems`` diagnostics-as-pre-turn-context |
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
| M84: Deferred-Item Sweep | 84 | `design/DEFERRED.md` exists, every "Deferred:" entry across `ROADMAP.md` and `ROADMAP_ARCHIVE.md` is labelled fired / not-fired / dropped, and the next sweep is on the calendar so deferrals don't rot into forgotten todos |
| M43: Memory | 43 | Cantrip learns per-charm and cross-charm lessons with citations, revalidation, user controls, and skill export |
