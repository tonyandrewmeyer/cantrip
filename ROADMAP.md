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

## Phase 48: Multimodal Observability Diagnostics

**Goal:** Let the agent reason visually about the artefacts charm operators
actually look at — Grafana panels, Tempo trace waterfalls, Juju status trees,
workload web UIs. Today `LokiQueryTool` and `TempoQueryTool` return text only.
Claude Code, Codex CLI, and Gemini CLI added multimodal support in the review
window (image input, screenshots, macOS computer use), and the Anthropic and
Gemini SDKs already support image input. This phase adds the rendering tools
and provider-level plumbing so the agent can debug operationally, not just
textually.

### 48.1 High — Image-input support in providers ✓

- [x] Images ride inside ``Message`` (new ``Image(data: bytes, mime:
  str)`` dataclass + ``Message.images: list[Image]`` field) rather
  than through a separate method — this mirrors the SDK wire formats
  (Anthropic content blocks, Gemini ``Part.inline_data``, OpenAI
  ``image_url`` multi-part content), lets images attach to any user
  turn in a multi-turn conversation, and keeps ``complete()`` /
  ``stream()`` as the only provider entry points. ``LLMProvider``
  gained a ``supports_vision`` property (default False) so callers
  can gate vision-dependent tools.
- [x] ``ClaudeProvider`` sets ``supports_vision = True`` and converts
  ``Image`` attachments to ``image`` / ``source: {type: base64, …}``
  content blocks inside the user message.  Enforces a 5 MB per-image
  cap client-side (matches Anthropic's documented limit).
- [x] ``GeminiProvider`` sets ``supports_vision = True`` and converts
  ``Image`` attachments to ``Part.inline_data`` parts inside the
  user ``Content``.  Image parts precede the text part so the model
  reads the visual before the instruction.  20 MB per-image cap.
- [x] ``InferenceSnapProvider`` grew a runtime-detected
  ``supports_vision`` property — static allowlist of known vision
  snaps (``qwen-vl``, ``gemma3``), plus a capability-flag upgrade
  from the ``/models`` response (``"vision"`` or ``"image"`` in the
  ``capabilities`` array).  Static seed is never downgraded by the
  probe.  Vision snaps convert images to OpenAI multi-part
  ``image_url`` entries with ``data:<mime>;base64,<…>`` URIs;
  non-vision snaps raise ``NotImplementedError`` with a message
  naming ``qwen-vl`` / ``gemma3`` as the recommended switch.  20 MB
  per-image cap mirrors Gemini.
- [x] 29 new unit tests across ``test_llm_base`` (3),
  ``test_claude`` (5), ``test_gemini`` (5), and
  ``test_inference_snap`` (10 including the five vision-detection
  cases for allowlist / capability-flag / no-downgrade invariants),
  plus two base-interface tests (``supports_vision`` default,
  ``_messages_have_images`` helper). Happy-path + oversize-reject +
  non-vision-reject paths all covered.

### 48.2 High — Grafana screenshot tool ✓

- [x] ``GrafanaScreenshotTool`` (``grafana_screenshot``) renders a
  panel or full dashboard as PNG via Grafana's ``/render`` endpoint.
  Mirrors the in-unit SSH-fetch pattern that
  ``TempoQueryTool`` / ``LokiQueryTool`` already use — requests hit
  ``http://localhost:3000`` inside the Grafana unit, side-stepping
  ingress / TLS and giving the image-renderer plugin the host it
  expects.  Supports ``dashboard_uid``, optional ``panel_id``,
  ``time_range`` (Grafana duration syntax), ``width`` / ``height``
  (1–4000 px), and ``cos_model``.  Uses ``/render/d-solo/<uid>``
  with a ``panelId`` query for single panels and ``/render/d/<uid>``
  for the full dashboard.
- [x] Fetches the Grafana admin password via the charm's
  ``get-admin-password`` action and passes it as ``Basic`` auth on
  the in-unit HTTP request.  When the action is unavailable or
  returns no usable key, falls back to an unauthenticated request
  and prints a targeted hint (``run get-admin-password manually``)
  if Grafana answers with a non-PNG body — typically a 401 or the
  renderer-plugin error page.  The PNG magic-byte check flags HTML
  error pages so the agent doesn't store an HTML blob as a ``.png``.
- [x] A new ``_ssh_fetch_binary`` helper carries the existing
  shell-safe base64-encoded-script pattern into binary territory —
  the unit b64-encodes the response before printing to stdout so
  ``juju ssh`` (which returns ``str``) transports PNG bytes
  losslessly.  ``auth_header`` is optional and escaped through the
  same single-quote replacement the URL uses.
- [x] PNGs are saved to ``~/.cache/cantrip/screenshots/`` with a
  deterministic filename (``grafana-<uid>[-p<panel>]-<timestamp>.png``).
  The tool returns a rich text caption (dashboard UID, panel id,
  time range, dimensions, bytes, file path) plus a ``data`` dict so
  48.2b and the TUI can locate the image.
- [x] Client-side validation: ``dashboard_uid`` matches
  ``[A-Za-z0-9_.-]+`` (blocks path-traversal attempts before they
  hit the URL), ``time_range`` matches the Grafana duration regex
  (``\d+[smhdwMy]``), ``width`` / ``height`` clamped to 1–4000.
- [x] Registered in ``build_tools()`` and added to the ``DEBUG``
  subagent allowlist so debug subagents can grab screenshots when
  diagnosing a live deployment.  ``reference-tools.html`` updated.
- [x] 16 new unit tests in ``tests/unit/test_observability_tools.py``:
  ``_grafana_admin_password`` across four result-shapes,
  ``GrafanaScreenshotTool`` happy path (cache-dir write + caption),
  endpoint routing (d-solo vs d), auth-header inclusion, missing-
  password degradation, non-PNG error surfacing, password-hint copy,
  and the three client-side validation paths.
- [x] **48.2b — images threaded through tool results.** Agent
  ``ToolResult`` and ``llm.ToolResult`` each grew an
  ``images: list[Image]`` field.  ``core.py`` (both synchronous and
  streaming loops) and ``subagent.py`` forward images from the
  agent result into the ``llm.ToolResult`` they build, and
  ``ContextManager._virtualise_tool_message`` now preserves images
  when it rewrites the text content into a virtual-file pointer —
  so even a huge caption doesn't orphan the diagnostic picture.
  ``ClaudeProvider._convert_messages`` emits an image + text
  content-block list inside a ``tool_result`` block when the result
  carries images (images first, caption last, matching the Anthropic
  doc pattern) and falls back to the plain-string shape when it
  doesn't.  The same 5 MB per-image cap from 48.1 catches oversize
  payloads early.  ``GrafanaScreenshotTool`` now attaches the
  rendered PNG to its ``ToolResult.images`` so the plumbing lights
  up end-to-end for the one shipping tool.  Gemini and inference
  snaps drop images (their ``FunctionResponse`` / ``role: tool``
  messages are text-only by spec) and rely on the caption alone —
  the caption always carries panel id, time range, dimensions, and
  the local file path so nothing is lost operationally.  6 new unit
  tests across ``test_llm_base`` (ToolResult defaults),
  ``test_claude`` (tool_result image blocks, plain-string fallback,
  5 MB cap), ``test_context`` (image survival through
  virtualisation), ``test_agent`` (core forwards images agent →
  llm.ToolResult into the TOOL message), and ``test_observability_tools``
  (GrafanaScreenshotTool populates images).  Fixed 8 pre-existing
  test_agent mocks that used ad-hoc ``type("R", ...)`` objects —
  they now use the real ``ToolResult`` dataclass, so future
  additions to the dataclass don't silently break those tests.

### 48.3 Medium — Tempo trace waterfall rendering ✓

- [x] ``TempoWaterfallTool`` (``tempo_waterfall``) fetches a trace
  from Tempo using the existing in-unit SSH pattern
  (``_ssh_fetch_url`` / ``_find_cos_unit``), flattens the
  OpenTelemetry ``batches[].scopeSpans[]`` structure into span dicts
  with ``service``, ``name``, ``start_ns``, ``end_ns``,
  ``duration_ns``, and renders a PNG waterfall using Pillow.
  Accepts the legacy ``instrumentationLibrarySpans`` shape for
  older Tempo deployments.  Trace IDs are hex-validated client-side
  to block URL-smuggling attempts.
- [x] Chose Pillow over cairosvg / rich's ``export_svg()`` +
  rasteriser path: the waterfall is a small set of rectangles and
  text, easier to hand-draw than to template-through-SVG and
  convert.  Added ``pillow>=11.0`` to the core dependencies — new
  dep, broad wheels, widely maintained.
- [x] Renderer (``_render_waterfall_png``) draws a 1400px-wide canvas
  with a fixed-width label column (``service · span.name``) and a
  timeline column.  Faint grid lines at 0/25/50/75/100% anchor the
  reader's eye; bars use a light-blue default with the top-3
  longest spans recoloured warmer so they stand out without needing
  to read every number.  Durations are formatted with the most
  readable unit (ns / µs / ms / s).  Monospace font resolved via a
  fallback chain of standard Linux / macOS paths, dropping to
  Pillow's bitmap default if nothing else works.
- [x] Caps rendered spans at 80 to keep the image legible — the
  slowest-N highlighting is computed across the *full* span list
  before truncation, so even a truncated waterfall draws attention
  to the interesting bars that survived.  Caption reports ``N shown
  of M total`` and points the reader at ``tempo_query`` when the
  full list matters.
- [x] PNG saved to ``~/.cache/cantrip/screenshots/`` with a
  deterministic filename
  (``tempo-waterfall-<trace-id>-<timestamp>.png``), bytes attached
  to ``ToolResult.images`` via the 48.2b pipeline so vision-capable
  providers see the waterfall inline alongside the caption.
- [x] Registered in ``build_tools()`` and in the DEBUG subagent
  allowlist; ``reference-tools.html`` updated.  18 new unit tests
  across ``test_observability_tools.py``:
  ``_format_duration`` (4), ``_collect_spans_from_trace`` (5 covering
  legacy-library shape, missing-timestamp skip, empty-trace, default
  service), ``_render_waterfall_png`` (happy path + 200-span
  truncation), ``TempoWaterfallTool`` (7 end-to-end cases: no-juju,
  bad trace id, Tempo missing from COS, malformed JSON, empty
  trace, happy path with caption + data + image attachment, SSH
  failure).

### 48.4 Medium — Juju status tree rendering ✓

- [x] `JujuStatusRenderTool` (``juju_status_render``) fetches the current
  ``juju status`` via Jubilant and renders it as a coloured tree PNG.
  Layout: apps grouped with their units using the same ``├─`` / ``└─`` /
  ``│`` tree glyphs the TUI graph screen uses; each app or unit carries
  a status-coloured indicator (● active, ○ waiting, ◌ blocked, ◐
  maintenance, ✗ error) rendered in its status colour; app messages
  surface as child lines; a ``Relations (N):`` heading introduces the
  deduplicated relation list below.  Pillow drives the PNG directly —
  same pattern as the Tempo waterfall renderer (48.3), so no new
  dependency on cairosvg / resvg.
- [x] Saves the PNG to ``~/.cache/cantrip/screenshots/juju-status-<model>-
  <timestamp>.png`` via ``_status_cache_path`` and attaches the bytes to
  ``ToolResult.images`` so vision-capable providers (48.1 / 48.2b) see
  the image alongside the caption.  Caption summarises model name, app
  / unit / relation counts, and names any blocked-or-errored apps so
  the agent can act on the visual diagnosis without re-running
  ``juju_status``.
- [x] Pure line-building (``_juju_status_tree_lines``) and relation
  deduplication (``_collect_relation_entries``) are split out from the
  Pillow drawing helper (``_render_status_png``) so the rendering logic
  is unit-testable without a PNG decoder in the test suite.  The
  renderer caps rendered rows at 140 (``_STATUS_MAX_LINES``) so a
  200-app model produces a 2400-pixel image with a "… N more lines
  omitted" footer rather than a 4000-pixel one.
- [x] Registered in ``build_tools()`` and in the DEBUG subagent
  allowlist (``subagent.py``); ``reference-tools.md`` / HTML updated.
  15 new unit tests across ``test_observability_tools.py``:
  ``_juju_status_tree_lines`` (7 covering empty model, single-app, two-
  app branch glyphs, app messages, status-indicator colour, relation
  deduplication, relation heading count), ``_collect_relation_entries``
  (2 covering empty model and unknown-remote-app), ``_render_status_png``
  (3 — valid PNG bytes, truncation cap, no-cloud path), and
  ``JujuStatusRenderTool`` (5 — juju-not-installed, wait-for timeout,
  CLIError surfaces cleanly, happy path with caption / data / image
  attachment / blocked-apps highlighting, empty model still renders).

### 48.5 Low — Headless browser integration

- [ ] Optional `workload_screenshot` tool that spawns headless Chromium
  against a workload endpoint discovered by Phase 17.3 and returns the
  rendered page as PNG
- [ ] Off by default; requires an explicit config flag because of the
  dependency footprint

**Exit criteria:** Providers support image input, the observability tools
return diagnostically useful PNGs alongside text captions, and subagents can
reason about Grafana/Tempo/Juju-status visually. `make check` passes
throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Provider image input (48.1) | None | SDK-level feature already available |
| Grafana screenshot (48.2) | Phase 22 cross-model COS | Uses existing Grafana config |
| Tempo waterfall (48.3) | Phase 2.2 COS integration | Reads traces from Tempo |
| Juju status render (48.4) | Phase 0.3 Juju integration | Renders existing status output |
| Headless browser (48.5) | Phase 17.3 endpoint testing | Optional; large dependency footprint |

---

## Phase 49: Subprocess Sandboxing Hardening

**Goal:** Isolate subprocess execution so a hallucinated or compromised shell
command cannot touch files or processes outside its intended scope. Today
`RunCommandTool`, `CharmcraftPackTool`, `JujuDeployTool`, and the git tools
run with the agent's full trust. Claude Code landed PID-namespace sandboxing
on Linux (2.1.98) and deny-rule hardening for `env`/`sudo`/`watch` wrappers
(2.1.113) during the review window. The recipe is well-understood and directly
applicable to Cantrip.

### 49.1 High — Linux PID and mount namespace isolation ✓

- [x] A `SandboxedRunner` in `src/cantrip/agent/sandbox.py` wraps
  subprocess invocations with Linux user-namespace isolation.  Three
  mechanisms are probed in order of preference by
  `sandbox_available()` — ``bwrap`` (full filesystem + PID +
  network + namespace isolation, canonical), ``unshare`` (PID +
  network-only fallback when bwrap isn't installed), and ``none``
  (non-Linux / missing both; logs a one-time warning and runs the
  command unchanged so tests and non-Linux users aren't blocked).
- [x] Separate mount namespace with read-only bind mounts for
  system paths, read-write for the working tree — the ``bwrap``
  path mounts ``/usr`` / ``/bin`` / ``/sbin`` / ``/lib*`` / ``/etc``
  / ``/opt`` read-only via ``--ro-bind-try``, binds ``cwd``
  read-write, adds every ``SandboxPolicy.read_write_paths`` entry
  read-write and every ``SandboxPolicy.read_only_paths`` entry
  read-only, and provides a fresh tmpfs ``/tmp``.  Missing policy
  paths are logged at debug level and skipped so stale config
  doesn't break the run; cwd isn't double-bound if the caller
  lists it in ``read_write_paths``.  The ``unshare`` fallback
  drops the filesystem isolation but still provides PID and
  optional network isolation (the single most valuable sandbox
  property for exfiltration defence).
- [x] Opt-out whitelist is per-tool, not per-command — the policy
  is expressed as a frozen `SandboxPolicy(network=..., read_write_paths=..., read_only_paths=...)`
  dataclass that each tool constructs for its own invocation.
  `RunCommandTool` now uses `network=False` + `read_write_paths=(cwd,)`
  as its conservative default.  Other tools (`JujuDeployTool`,
  `GitPushTool`, …) keep the direct ``jubilant`` / ``subprocess``
  path until they adopt the runner in a follow-up — the sandbox is
  additive, not mandatory.
- [x] Unit tests: 16 cases in ``tests/unit/test_sandbox.py``
  covering mechanism selection (bwrap > unshare > none, non-Linux
  forced to none), bwrap command construction (namespace flags,
  network opt-out, rw/ro bind-mount pass-through, missing-path
  skipping, no-double-bind invariant), unshare fallback
  construction (same namespace / network flags), no-sandbox
  pass-through (argv unchanged, one-shot warning), and real-exec
  smoke test through whichever mechanism this host provides.
  ``test_run_command.py`` gains `TestRunCommandSandbox` with three
  cases proving the tool delegates to the injected runner with a
  no-network / cwd-rw policy, constructs its own runner by default,
  and preserves the `SandboxPolicy` defaults.

### 49.2 High — Deny-rule hardening ✓

- [x] Wrapper commands (``env``, ``sudo``, ``doas``, ``watch``,
  ``nohup``, ``setsid``, ``timeout``, ``ionice``, ``nice``,
  ``chroot``, ``stdbuf``, ``script``, ``xargs``, ``exec``, plus every
  common shell) rejected categorically in
  ``cantrip.agent.tools.run_command``.  Distinct error message from
  the allowlist-miss case so the LLM learns to drop the wrapper
  rather than retry.  Since Cantrip uses an allowlist (not a deny-
  list), this is defence-in-depth for the scenario where an operator
  adds a wrapper to the allowlist — ``env rm`` stays blocked either
  way.
- [x] Leading ``NAME=value`` env-var assignment prefixes rejected
  with a wrapper-equivalent error (``FOO=bar make`` is a shell
  wrapper, same attack surface as ``env``).
- [x] Shell metacharacters (``;``, ``&&``, ``||``, ``|``, backticks,
  ``$(...)``, ``>``, ``<``) rejected before the allowlist check.
  The tool runs with ``shell=False`` so these are inert today, but
  catching them at the source (a) makes the failure mode explicit
  so the LLM splits the command into two calls rather than retrying
  the same form, and (b) keeps a future refactor to ``shell=True``
  from inheriting the bypass.
- [x] 29 new tests: 14 wrapper forms, 3 ``NAME=value`` forms, 8
  metacharacter forms, 1 distinctness assertion, 1 happy-path
  regression check, 2 positive sanity checks.

### 49.3 Medium — Per-tool syscall allowlists (deferred)

- [ ] Seccomp-bpf allowlists for tools with constrained syscall needs.
  **Deferred** — Cantrip has no `libseccomp` dependency and hand-rolling
  BPF without it is error-prone enough to risk more harm than it
  mitigates.  Phase 49.1's `bwrap` layer already delivers what this
  phase's exit clause requires ("fall back to the namespace-only
  sandbox when seccomp is unavailable"): network blocking,
  filesystem isolation, and PID isolation.  Seccomp adds defence in
  depth against sandbox-escape syscalls (`mount`, `ptrace`, `bpf`,
  `setns`) but should be driven by a specific attack model — not
  shipped speculatively.  Re-open when a tool presents a concrete
  syscall-level attack surface or when a libseccomp binding becomes
  a transitive dep.

### 49.4 Medium — macOS path hardening ✓

- [x] On macOS, apply the `sandbox-exec` profile pattern — new
  ``"sandbox-exec"`` mechanism in ``cantrip.agent.sandbox``.  The
  runner detects ``sandbox-exec`` on ``darwin`` via ``shutil.which``
  and falls back to ``"none"`` when absent (Apple's deprecation
  notice means future macOS releases may remove it entirely, which
  the exit clause anticipates).  The emitted SBPL profile denies
  everything by default, then explicitly allows ``process-exec`` /
  ``process-fork`` / intra-sandbox signals / ``sysctl-read`` /
  ``mach-lookup`` / ``ipc-posix-sem``; ``file-read*`` on ``/usr``,
  ``/bin``, ``/sbin``, ``/System``, ``/Library``, ``/private/etc``,
  ``/private/var/db``, and ``/dev``; ``file-read*`` +
  ``file-write*`` on the working directory and every
  ``SandboxPolicy.read_write_paths`` entry that exists; and
  ``network*`` gated on ``policy.network``.  Missing rw paths are
  silently dropped as on Linux.
- [x] Fallback to a warning (no hard enforcement) where
  ``sandbox-exec`` is missing — ``sandbox_available()`` returns
  ``"none"`` and ``SandboxedRunner`` logs a one-shot warning naming
  ``sandbox-exec`` in the macOS message (unified with the Linux
  ``bwrap``/``unshare`` message).  5 new ``TestSandboxExecWrap``
  cases cover the profile scaffolding, network gate, rw/ro path
  injection, cwd coverage, and the missing-path skip.

### 49.5 Low — Sandbox observability ✓

- [x] Log sandbox policy decisions (argv, mechanism, cwd, network,
  bind mounts) to the transcript — ``cantrip.agent.sandbox`` gained
  a module-level event-sink slot (``set_event_sink`` /
  ``get_event_sink``, thread-safe via a lock).  When a sink is
  registered, ``SandboxedRunner.run`` emits a ``sandbox_policy``
  event with the full decision record before the subprocess spawns.
  ``CantripAgent._init_store`` installs a sink that routes events
  into ``SessionStore.record_event`` so every sandbox decision is
  durably audit-logged alongside tool calls and agent events.  Sink
  exceptions are swallowed at debug level so a misbehaving sink can
  never break the run.
- [x] ``/sandbox`` slash command shows current sandbox mode and
  per-tool overrides — new verb in the shared dispatcher that
  reports the active mechanism (bwrap / unshare / sandbox-exec /
  none, each with a one-line summary including the upgrade path
  when relevant), the ``run_command`` default policy (network off,
  working tree bound rw, system paths bound ro), and whether
  transcript logging is on (sink registered) or off.  4 dispatcher
  tests cover the four mechanism paths plus sink-registered
  reporting; catalogue-drift guards in ``test_slash_commands``
  continue to pass.

**Exit criteria:** Untrusted subprocess execution runs under PID/mount
namespace isolation with a per-tool network opt-out and deny-rule hardening
against common bypass wrappers. macOS has a best-effort equivalent via
`sandbox-exec`. `make check` passes throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| PID/mount namespaces (49.1) | Phase 25.2 shell-injection fix | Builds on cleaned-up command handling |
| Deny-rule hardening (49.2) | 49.1 | Extends command inspection |
| Syscall allowlists (49.3) | 49.1 | Layered on the namespace sandbox |
| macOS hardening (49.4) | 49.1 | Parallel platform implementation |
| Observability (49.5) | Phase 14.1 transcript | Emits sandbox events |

---

## Phase 50: Skills Ecosystem Interop

**Goal:** Let users bring skills from the cross-vendor Skills ecosystem
(Claude Code, `gh skill`, Cursor, Codex, Gemini CLI, Windsurf) into Cantrip,
and export Cantrip's own skills in the same format. The Skills spec stabilised
in the review window — Microsoft's `microsoft/skills` repository now includes
MCP-aware Azure and cloud skills directly applicable to charm work (and to
COS integration specifically).

### 50.1 Medium — Import from standard-format Skills directories ✓

- [x] Discover skills in `~/.config/cantrip/skills/` and
  `~/.claude/skills/` that follow the standard YAML-frontmatter +
  markdown shape, and surface them alongside Cantrip's built-in
  skills — ``SkillsIndex`` now accepts ``extra_dirs``; the default
  constructor walks ``[bundled, ~/.claude/skills, ~/.config/cantrip/
  skills]`` in order, with later directories winning on name
  conflict (so a Cantrip-specific user skill trumps a shared Claude
  Code skill, which trumps the bundled default).  Conflicts log at
  INFO level so the override is auditable in the transcript.
- [x] Both layouts are accepted: ``<root>/<name>/SKILL.md``
  (directory style — Cantrip bundled + Claude Code convention) and
  ``<root>/<name>.md`` (single-file style — common in lightweight
  user skills).  ``_resolve_skill_file`` handles the shape selection
  so either works without changing the loader.
- [x] Translate the frontmatter (``name``, ``description``, ``tools``)
  into Cantrip's internal skill dataclass — ``SkillMetadata`` grew a
  ``tools: list[str]`` field (with a ``_coerce_tools`` helper that
  accepts YAML lists, Claude Code's comma-separated string, or
  nothing; malformed ``tools`` falls back to an empty list so
  discovery never crashes) and a ``source`` tag
  (``bundled`` / ``external``) so callers can distinguish provenance
  at load time.
- [x] Test isolation: explicit ``SkillsIndex(tmp_path)`` no longer
  picks up external dirs (so unit tests can't accidentally read the
  developer's real ``~/.claude/skills/``), and the ten bundled-skill
  tests were switched to ``SkillsIndex(extra_dirs=[])`` to stay
  isolated from host state.  10 new tests in
  ``TestSkillsIndexExternalDirs`` cover missing-dir silence, external
  skills appearing alongside bundled, name-conflict override +
  INFO-level logging, single-file discovery, ``tools`` as list /
  comma-string / malformed, ``source`` tag propagation, default-dir
  ordering (Claude Code before Cantrip), and the test-isolation
  guarantee.
- [x] Imported skills can reference MCP tools from Phase 45 when the
  MCP client exposes them — ``tools`` is preserved on the metadata
  as forward-compatible groundwork for 50.4 (MCP-aware skills); the
  loader doesn't enforce the list yet, but a user can already
  declare MCP tool names in the frontmatter and they round-trip
  through ``list_skills()``.
- [x] ``docs/src/howto-skills.md`` added: covers skill format, the
  three discovery locations with precedence, both on-disk layouts,
  frontmatter fields, a worked example, and a troubleshooting
  section for "my skill isn't picked up" / "my skill overrides the
  bundled one".  Linked from ``_site.yaml`` and given a card on the
  docs index.

### 50.2 Medium — Export Cantrip skills to the standard format ✓

- [x] `cantrip skill export <name> <path>` emits a standard-format
  skill file for the named Cantrip skill.  Works on bundled skills
  and on user-authored skills under ``~/.claude/skills/`` or
  ``~/.config/cantrip/skills/``.  ``path`` is honoured verbatim when
  it ends in ``.md`` (single-file layout) and expanded to
  ``<path>/<name>/SKILL.md`` otherwise (directory layout); parent
  directories are created as needed and ``--force`` is required to
  overwrite an existing target.  Frontmatter re-emits ``name``,
  ``description``, and ``tools`` (omitted when empty).
  ``SkillsIndex`` grew a ``metadata_for(name)`` accessor so the
  exporter can read the stored ``SkillMetadata`` without
  re-parsing the file.
- [x] Sanitisation reuses ``cantrip.agent.memory_export.sanitise_body``
  so the Phase 43.4 export rules apply verbatim: ``--charm-path DIR``
  replaces occurrences of that path with the literal
  ``<CHARM_PATH>`` placeholder, and the same high-confidence
  credential patterns (GitHub tokens, AWS keys, HTTP ``Bearer``,
  ``password=…`` / ``password: …``, Slack tokens) become
  ``[REDACTED]``.  The CLI prints the redaction count so the
  operator can see at a glance whether anything was scrubbed
  before sharing.
- [x] Round-trip test added in ``test_skills.py`` — builds a fixture
  skill with frontmatter + body (including a ``tools:`` list),
  exports it, deletes the source tree, re-discovers via a fresh
  ``SkillsIndex`` rooted at the export target, and asserts
  ``name`` / ``description`` / ``tools`` / body content are
  preserved.  12 new tests in total cover the core exporter
  (directory vs file target, force vs refuse-to-overwrite,
  unknown-name error listing known skills, charm-path
  sanitisation, secret redaction + count, tools preservation,
  tools omission when empty, the round-trip itself) and CLI
  dispatch (happy-path exit 0 + target-written, unknown-skill
  exit 2).
- [x] ``docs/src/howto-skills.md`` gains an "Exporting a skill"
  section describing the command, the two layouts the path flag
  selects between, and the sanitisation rules; a ``see_also``
  link into the CLI reference lands alongside.
  ``docs/src/reference-cli.md`` documents
  ``cantrip skill export`` in full — positional args, both flags,
  and exit codes — and the synopsis gains the new subcommand line.

### 50.3 Low — `gh skill` discovery ✓

- [x] Detect skills installed via ``gh skill install`` at the paths
  the command actually uses.  Research pinned the behaviour: ``gh
  skill install`` (shipped in GitHub CLI v2.90, 2026-04-16) does
  not own a dedicated "gh skill" directory — it writes into
  whichever agent-specific directory each target tool reads from.
  For Cantrip's users the two that matter are the ``universal``
  user-scope bucket and the project-scope default.  Implemented by
  extending ``_default_external_skill_dirs()`` with
  ``~/.config/agents/skills/`` (the ``gh skill install --scope
  user`` default for ``universal`` / ``opencode`` / ``kimi-cli`` /
  ``warp`` / ``replit``) and adding a new
  ``_default_project_skill_dirs(project_root)`` helper that
  returns ``<root>/.agents/skills/`` (shared project dir for ~20
  agents) and ``<root>/.claude/skills/`` (Claude Code's
  project-scope dir).  ``SkillsIndex`` grew a ``project_root=``
  kwarg; ``CantripAgent`` threads the charm path through so
  project-scope skills are discovered end-to-end.  Precedence
  follows a *most-shared → most-specific* rule: universal →
  Claude → Cantrip-specific at user scope, then project-scope
  paths win over any user-scope copy.
- [x] Deviation from roadmap wording: project-scope discovery is
  new (not in the original Phase 50.3 sub-bullet) but it's the
  actual default of ``gh skill install``.  Stopping at user-scope
  would have missed the install path most users hit first.
- [x] 4 new tests in ``test_skills.py``: precedence ordering
  (universal → Claude → Cantrip), ``project_root=`` discovery,
  project-scope wins over user-scope on name conflict, and
  absence of project paths when ``project_root`` is omitted.  The
  pre-existing ``test_default_external_dirs_are_cantrip_then_
  claude`` was renamed and expanded to assert the three-way
  ordering; no existing test regressed.
- [x] Documentation: the *Where Cantrip looks* section in
  ``docs/src/howto-skills.md`` now distinguishes user-scope vs
  project-scope paths with all six directories listed in
  precedence order; a new *Installing skills with `gh skill
  install`* section covers both default project-scope and
  opt-in user-scope invocations, plus ``gh skill list`` /
  ``gh skill update`` for inspection.  ``README.md`` gains a
  two-paragraph callout after the memory/MCP block that points
  at the vendor-neutral skills ecosystem, shows a one-line
  ``gh skill install microsoft/skills/...`` invocation, and
  links through to the how-to.

### 50.4 Low — MCP-aware skills ✓

- [x] Skills can declare MCP server dependencies in their
  frontmatter via a new ``mcp_servers:`` key.  Same coercion
  rules as ``tools:`` (YAML list or comma-separated string);
  ``SkillMetadata`` grew an ``mcp_servers: list[str]`` field and
  ``_coerce_tools`` was generalised to ``_coerce_string_list``
  shared between the two fields.  Parsing happens inside
  ``_parse_frontmatter`` so every discovered skill surfaces the
  requirement the same way regardless of layout (directory
  vs single-file) or source (bundled vs external).
- [x] Deviation from the roadmap wording: "the loader checks
  the MCP client" is interpreted as *check at load time, not at
  discovery*.  Gating at discovery would silently hide skills
  the agent might still extract value from (the MCP warning is
  advisory, not always fatal — a skill might degrade
  gracefully).  Checking at ``load_skill`` and prepending a
  visible warning banner is the better failure mode.
- [x] ``LoadSkillTool`` accepts an optional
  ``mcp_registry: MCPRegistry | None`` kwarg.  On each call it
  reads the skill's ``mcp_servers`` list, compares against
  ``registry.configured`` (Phase 45.2), and prepends a clear
  banner to the returned body naming the unconfigured subset.
  Happy-path loads (no deps, or every dep configured) pay no
  formatting cost.  When ``mcp_registry`` is ``None`` (tests,
  degraded sessions), every declared server is treated as
  missing so the warning is conservative by default.  The
  banner never fails the call — ``ToolResult.success`` stays
  ``True`` so the agent keeps the skill content and can reason
  about the warning.
- [x] Prompt-level skill index (``format_for_prompt``) gained a
  ``<required_mcp_servers>`` child element per skill that
  declares deps, so the agent sees the requirement at index
  time and can pick an alternative skill when missing
  infrastructure would block it.  Skills without deps are
  unaffected — the element only appears when needed.
- [x] Wiring: ``build_tools()`` forwards ``mcp_registry`` into
  ``LoadSkillTool``; ``CantripAgent._build_tools`` already
  constructs the registry lazily (Phase 45.2), so the tool
  picks up the same instance the ``MCPTool`` aggregation uses.
- [x] Export round-trip: ``cantrip skill export`` emits
  ``mcp_servers:`` in frontmatter when non-empty (and omits it
  otherwise, matching the ``tools:`` behaviour from 50.2).  A
  re-imported skill preserves the dependency list verbatim.
- [x] 13 new tests cover the parse paths (YAML list,
  comma-string, missing, malformed-type fallback), the prompt
  rendering (declared → element emitted; none → omitted), the
  ``LoadSkillTool`` warning paths (server missing → banner;
  all configured → no banner; partial missing → banner lists
  only the missing subset; no registry → conservative treat-
  as-missing; no deps → banner suppressed even with an empty
  registry), and the export round-trip (``mcp_servers``
  preserved through export → fresh-index re-import; omitted
  when the source has none).
- [x] Documentation: ``docs/src/howto-skills.md`` gains an "MCP
  dependencies" section describing the frontmatter key, a worked
  example showing the banner the agent sees, and the mapping
  into the prompt index, plus a pointer to Phase 45's how-to-
  mcp page.  The skill-format section covers the new key
  alongside ``tools``.

**Exit criteria met:** Users can drop a standard-format skill into
`~/.config/cantrip/skills/` and have Cantrip use it (50.1); Cantrip skills
round-trip through the standard format (50.2); `gh skill install` destinations
are discovered at user scope and project scope (50.3); MCP-aware skills work
with the Phase 45 client with a clear warning when declared servers are
missing (50.4). `make check` passes.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Import (50.1) | Phase 0.4 skills infrastructure | Reuses the loader pipeline |
| Export (50.2) | Phase 43.4 export rules | Shares sanitisation with the memory export path |
| `gh skill` discovery (50.3) | Phase 42 GitHub integration | Builds on the existing `gh` dependency |
| MCP-aware skills (50.4) | Phase 45 MCP client | Requires the client to resolve declared deps |

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

## Phase 52: Step-Level Durable Execution for Subagent Loops

**Goal:** Stop throwing away in-flight LLM work when a subagent task fails,
rate-limits, or the user Ctrl+Cs mid-run.  Today a BUILD subagent that
rate-limits on turn 18 restarts from turn 1 on the next run — re-burning
every token and every tool call in between.  Cantrip already has
task-level persistence (`.cantrip` SQLite with `tasks`,
`subagent_messages`, transcripts); what it lacks is a *per-step*
checkpoint layer so replay can resume from the last completed step.

Inspired by Armin Ronacher's *Absurd* (Postgres-backed durable
execution) — but Cantrip is a single-process local tool, so the queue
and worker machinery are irrelevant.  The pattern we want is just
"checkpoint each expensive step, replay from the store on restart,"
adapted to SQLite.

### 52.1 Medium — Checkpoint schema and storage helpers ✓

- [x] Added a ``step_checkpoints`` table to the ``.cantrip`` SQLite
  schema via v10 migration.  Columns: ``id`` / ``task_id`` /
  ``step_name`` / ``ordinal`` / ``input_hash`` / ``result_blob`` /
  ``result_kind`` / ``created_at`` with ``UNIQUE(task_id,
  step_name, ordinal)`` and a ``ix_step_checkpoints_task`` index
  on ``task_id`` for the resume-time list scan.  Migration block
  is idempotent (``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX
  IF NOT EXISTS``) so reopening a partially migrated DB is safe.
- [x] Implemented ``CheckpointStore`` in
  ``src/cantrip/agent/durability.py`` as a thin facade over
  ``SessionStore``.  Roadmap-named methods:
  ``record(task_id, step_name, ordinal, input_hash, kind,
  value)``, ``get(task_id, step_name, ordinal)``,
  ``next_ordinal(task_id, step_name)``.  Plus ``list_for_task``
  / ``count_for_task`` / ``purge_task`` for the Phase 52.5
  debugging surface and the GC path.  ``next_ordinal`` starts at
  ``1`` and returns ``max(ordinal) + 1`` so callers don't track
  counters themselves; they just ask for the next slot.
- [x] Deviation from the roadmap wording: the serialisation layer
  is **JSON with a raw-bytes escape hatch**, not msgpack-with-
  JSON-fallback.  msgpack isn't a current dep (roadmap asserted
  otherwise — I checked ``pyproject.toml`` and the ``src/``
  tree, no ``import msgpack`` anywhere); adding a new dep for
  Phase 52.1 was more blast radius than the feature warrants
  when JSON already covers every concrete 52.2 / 52.3 value
  shape (LLM response dataclasses, tool result dicts).  Callers
  that need a binary envelope (pickle, msgpack, protobuf) can
  pass ``kind=KIND_BYTES`` and pre-serialised bytes; the record
  path stores them verbatim.  The JSON encoder handles
  ``pathlib.Path``, ``datetime``, and ``set`` via a ``default=``
  hook so tool args don't need pre-stringifying.
  ``compute_input_hash(*parts)`` helper canonicalises a mix of
  primitives / dicts / lists into a stable SHA-256 so dict-key
  ordering never changes the digest — 52.2's input-hash check
  reduces to a string compare.
- [x] Garbage collection wired via
  ``CheckpointStore.on_task_done(task_id)``, attached as the
  ``on_task_done`` callback on ``BackgroundExecutor`` in
  ``CantripAgent.start_executor`` (fires only when
  ``WorkQueue.set_done`` resolves — not on FAILED / BLOCKED).
  ``$CANTRIP_KEEP_CHECKPOINTS`` (``1`` / ``true`` / ``yes`` /
  ``on``) flips the purge into a no-op and logs the retained
  row count at DEBUG so a stale-cache bug hunt can inspect the
  rows without a manual ``DELETE`` afterwards.  The direct
  ``purge_task`` method bypasses the env var so ``cantrip
  checkpoints delete`` (52.5) and test teardown can still force
  a clean.
- [x] 30 new tests in ``tests/unit/test_durability.py`` covering
  schema (fresh DB + v9→v10 migration + unique constraint),
  SessionStore helpers (record / get / next_ordinal / list /
  count / purge — including the cross-task isolation
  invariant), the CheckpointStore facade (JSON round-trip,
  KIND_BYTES round-trip + type-mismatch rejection,
  non-serialisable-value loud-failure at record time,
  ``json_default`` covers Path / datetime / set, next_ordinal
  delegation, purge_task bypasses env var), the ``on_task_done``
  GC path (purge by default / skip when env set / other truthy
  env values recognised / zero-and-empty falsy / cross-task
  isolation), and ``compute_input_hash`` (determinism across
  invocations, dict-key-order invariance, different inputs →
  different hash, non-JSON types via ``repr()`` fallback).

### 52.2 Medium — `checkpoint()` wrapper helper ✓

- [x] Added ``async def checkpoint[T](ctx, step_name, fn, *,
  input_hash=None, kind=KIND_VALUE) -> T`` to
  ``src/cantrip/agent/durability.py`` using PEP 695 generic syntax
  (matching the codebase's ``mcp/token_storage._load_model[T]``
  precedent).  ``fn`` is a ``Callable[[], Awaitable[T]]`` so both
  ``provider.complete`` and ``tool.run`` drop in without wrapping.
- [x] ``CheckpointCtx`` is a frozen-ish dataclass with ``store`` +
  ``task_id`` + a private ``_counters: dict[str, int]`` default.
  Exposes ``next_ordinal(step_name)`` which increments and returns
  the monotonic per-step counter — starts at ``1``, each step name
  gets its own counter, so ``llm_turn`` and ``tool:juju_status``
  never interfere.  One ctx per subagent task, constructed fresh on
  each run.
- [x] Replay semantics match Absurd's ``ctx.step``: allocate the
  next ordinal, look up ``store.get(task_id, step_name, ordinal)``,
  return the decoded value on hit, otherwise ``await fn()`` and
  persist before returning.  Deterministic call ordering in the
  subagent loop means the same ``(step_name, ordinal)`` pairs line
  up with persisted rows across runs.
- [x] Input-hash mismatch path: when the caller passes an
  ``input_hash`` and the stored record's hash differs, log a
  ``WARNING`` ("checkpoint input-hash mismatch — invalidating …")
  and fall through to re-run.  ``INSERT OR REPLACE`` on the
  ``(task_id, step_name, ordinal)`` UNIQUE constraint overwrites the
  stale row naturally — no explicit delete needed.  Omitted
  ``input_hash`` (``None``) means "accept any stored row"; stored as
  ``""`` on record so a future opt-in hash will mismatch cleanly.
- [x] 13 new tests in ``tests/unit/test_durability.py`` split across
  ``TestCheckpointCtx`` (counter start-at-1, per-step independence,
  monotonic increment) and ``TestCheckpointWrapper`` (miss-runs-fn-
  and-persists, hit-skips-fn, auto-numbered repeated calls, mixed
  replay / fresh after a partial prior run, hash mismatch invalidates
  with log capture, matching hash hits, None hash accepts stored,
  KIND_BYTES round-trip across two ctxs, step-name isolation,
  task-id isolation, empty-string input_hash default).

### 52.3 Medium — Wire checkpoints into the subagent loop ✓

- [x] Added ``Subagent._llm_turn(ctx, messages, tools)`` that wraps
  ``_complete_with_retry`` with
  ``checkpoint(ctx, "llm_turn", ..., kind=KIND_LLM_RESPONSE)``.
  Input hash spans provider name + model name + canonicalised
  message prefix + canonicalised tool-schema list so any conversation
  divergence invalidates the stale row via the 52.2 hash-mismatch
  path rather than silently serving it.  On checkpoint hit the
  provider is never called — ``on_usage`` isn't invoked either,
  which is the desired replay behaviour (the original run already
  counted the tokens).
- [x] Added ``Subagent._execute_tool_with_checkpoint(ctx, name,
  arguments)`` that wraps ``_execute_tool`` with
  ``checkpoint(ctx, f"tool:{name}", ..., kind=KIND_TOOL_RESULT)``.
  Input hash is ``compute_input_hash(name, arguments)``.  Called
  from inside ``_tool_or_veto`` so the gather-based concurrent
  tool-call path is preserved — ordinal allocation happens
  synchronously at the start of each ``checkpoint()`` call, before
  any ``await``, so parallel tool calls line up with the tc
  ordering deterministically.  Vetoed calls are *not* checkpointed
  (they produce a synthetic result, which is free to rebuild on
  replay).
- [x] Tool failures *are* persisted.  The roadmap called for
  "negative checkpoints" so a deterministic error doesn't re-burn
  on resume — that's what the plain cache path already does: a
  ``ToolResult(success=False, error=...)`` round-trips through
  the envelope the same as a success.  A future session-level
  "retry failed steps" flag (pencilled into 52.4) can opt back into
  re-running failures without changing this layer.
- [x] ``Subagent._run_inner`` constructs a ``CheckpointCtx`` when a
  ``SessionStore`` is present and passes ``None`` otherwise — unit
  tests and any future store-less path stay on the pre-52.3 code
  path.  Streaming is untouched: subagents don't stream, and the
  conversation loop's streaming path is out of scope here.
- [x] Added ``response_to_dict`` / ``response_from_dict`` and
  ``tool_result_to_dict`` / ``tool_result_from_dict`` helpers in
  ``durability.py`` to lossless-round-trip the concrete dataclasses
  through the JSON envelope.  Image bytes are base64-encoded in the
  tool-result payload.
- [x] 9 new tests in
  ``tests/unit/subagent/test_checkpoint.py``: first-run records
  llm_turn/tool rows correctly; replay skips provider and tool
  execution entirely (asserts an "exploding" provider + tool are
  never touched); partial-prior-run resumes from the right
  point; two-different-tools-in-one-round land on distinct step
  names; same-tool-twice-in-one-round walks ordinals 1→2;
  model-name-change invalidates the first turn and re-runs the
  provider; tool-failure persists as ``success=False`` and replays
  without re-calling the tool; no-store baseline preserves
  pre-52.3 behaviour.  Plus 7 new tests in ``test_durability.py``
  covering the serialisers (content-only / tool-calls /
  usage+metadata round-trip for Response; success-path /
  failure-path / images-via-base64 for ToolResult).

### 52.4 Medium — Resume path on session start ✓ (inspection folded into 52.5)

- [x] ``CANTRIP_NO_RESUME=1`` opt-out: when set, the subagent leaves
  ``ctx = None`` at ``_run_inner`` entry so every LLM turn and every
  tool call re-runs live.  Fresh results still land in the store
  (the *lookup* is bypassed, not the write), so the next run
  without the var sees a clean cache.  ``should_skip_resume()``
  helper in ``durability.py`` mirrors ``should_keep_checkpoints``
  — same truthy-value parser (``1`` / ``true`` / ``yes`` / ``on``).
- [x] Resume-from-step-N signal: when a store-backed subagent starts
  and finds existing checkpoints for its task, it emits an
  ``INFO``-level log line (``"Subagent resuming task 'Build
  redis' from step 4 (3 checkpoint(s) cached)"``), sets the
  transient ``subagent_phase`` to ``resuming from step N`` so the
  TUI task pane shows it, and records a ``subagent_resume`` event
  into the session store's event log (``task_id`` / ``task_title``
  / ``prior_steps`` / ``next_step``) so the transcript and any
  future observability surface can replay the history.  ``N`` is
  ``count_for_task(task_id) + 1`` — the *next* step the subagent
  will attempt.
- [x] Deviation from the original plan: the checkpoint-inspection
  surface (``cantrip session inspect <session>`` / TUI F-key)
  folded into Phase 52.5.  52.5 already scopes the transcript-
  viewer "checkpoints" tab plus a ``cantrip checkpoints
  {list,show,delete}`` subcommand, so adding a separate
  ``session inspect`` path in 52.4 would double-ship the feature.
  52.5 absorbs the inspection bullet with the same behaviour.
- [x] 5 new tests in
  ``tests/unit/subagent/test_checkpoint.py::TestResumeUX``
  (``CANTRIP_NO_RESUME`` disables lookup even with pre-populated
  store, truthy / falsy value parsing, resume log + phase + event
  fire on a warm task, no signal on a fresh task).  Plus 3 new
  tests in ``test_durability.py::TestNoResumeEnv`` (truthy / falsy
  / unset-defaults-to-resume-on).

### 52.5 Low — Observability and debugging ✓

- [x] Transcript viewer (F9) gained a fourth view, ``checkpoints``,
  cycled via ``v``.  Per task: title + id + step count, then one
  line per row showing ``<step>#<ordinal>  <kind>  <input_hash[:12]>
  <created_at>``.  The input hash is deliberately truncated so the
  row fits a standard terminal width; full hashes come from
  ``cantrip checkpoints show``.  This also absorbs 52.4's
  deferred inspection bullet.
- [x] ``TranscriptData`` grew a ``checkpoints: dict[str,
  list[dict]]`` field populated by ``load_transcript``: blobs are
  *not* included (they can be large) — each row carries
  ``step_name`` / ``ordinal`` / ``input_hash`` / ``kind`` /
  ``created_at`` so rendering is cheap.  On-demand blob decode
  lives on the CLI (``cantrip checkpoints show``).
- [x] ``cantrip checkpoints`` CLI subcommand with three
  subcommands:
  ``list [--task-id X]`` (per-task table — every task if no
  filter), ``show <task_id> <step_name> <ordinal>`` (pretty-
  prints the decoded JSON blob, or base64 for
  ``KIND_BYTES``), and ``delete --task-id X [--yes]`` (purges a
  task's checkpoints, interactive ``y/N`` prompt unless
  ``--yes``).  All three take ``--db PATH`` (default
  ``./.cantrip``) so the subcommand works from any directory
  with a session file.
- [x] Hit / miss / invalidated events land in the session store's
  event log: ``checkpoint_hit`` / ``checkpoint_miss`` /
  ``checkpoint_invalidated`` with ``{task_id, step_name, ordinal,
  kind}`` (plus ``stored_hash`` / ``current_hash`` on the
  invalidation case).  Recorded inside :func:`checkpoint` via a
  new ``CheckpointStore.record_event`` forwarder so the
  transcript viewer and any future watcher dashboard can plot
  replay efficiency without extra plumbing.
- [x] 17 new tests: 3 in ``test_durability.py::TestCheckpointEventEmission``
  (miss / hit / hash-mismatch-invalidates-then-misses); 1 in
  ``test_transcript.py::TestLoadTranscript::
  test_load_transcript_populates_checkpoints``; 10 CLI handler
  tests in ``test_checkpoints_cli.py`` (list / show / delete with
  empty-state, all-tasks, task filter, missing task,
  JSON-decode, missing-row-errors, ``--yes`` purge, interactive
  prompt y/n); 3 TUI ``_checkpoint_lines`` render tests
  (empty-state / populated / unknown-task-id fallback).

### 52.6 Low — Cost accounting for replayed steps ✓

- [x] Rate-limit budget tracker already does not double-count on
  replay — a consequence of the 52.3 wiring: checkpoint hits
  short-circuit ``_complete_with_retry`` entirely, so
  ``on_usage`` (the callback that feeds the budget tracker +
  ``token_usage`` table) is *never invoked* on a hit.  No change
  needed in 52.6 for this half; the behaviour has been correct
  since 52.3.
- [x] Replayed-usage surface: the 52.5 ``checkpoint_hit`` event
  now carries ``prompt_tokens`` / ``completion_tokens`` when the
  cached row is a ``KIND_LLM_RESPONSE`` (tool hits contribute
  nothing).  New ``SessionStore.get_replay_savings()`` sums
  those fields across the event log and returns ``{prompt_tokens,
  completion_tokens, request_count}`` so ``/cost`` and the
  transcript can show the savings at a glance.  Both
  ``format_cost`` (TUI / Web ``/cost``) and ``cli._print_cost``
  (CLI ``/cost``) append a "Cached from checkpoint: X tokens
  (Y prompt, Z completion, N replayed turn(s))" line whenever
  the saved total is non-zero; the line is omitted on fresh
  sessions so the existing output is unchanged by default.
- [x] ``TranscriptData`` grew a ``replay_savings: dict[str,
  int]`` field populated by ``load_transcript`` from
  ``get_replay_savings``, so downstream renderers (HTML / JSONL /
  markdown in Phase 54) can surface the saved-token figure in
  exported transcripts without re-reading the database.
- [x] 9 new tests: 3 event-stamping (``llm_response`` hit stamps
  usage / ``tool_result`` hit does not / empty-``usage`` dict
  stays clean); 2 ``get_replay_savings`` sums (empty-session /
  mixed llm-and-tool hits); 1 transcript-data population test;
  1 ``format_cost`` positive case + assertions in the existing
  ``format_cost`` / ``_print_cost`` totals tests that the line
  stays *absent* on zero savings; 1 ``_print_cost`` positive
  case.

### What this phase is *not*

- Not a queue or worker rewrite.  Cantrip already has an in-process
  executor; the only thing we add is a checkpoint table.
- Not a distributed system.  No multi-process claims, no
  `SKIP LOCKED`, no `pgmq`.  One process holds one SQLite file — the
  existing concurrency story (Phase 28 WAL work) covers us.
- Not deterministic replay of arbitrary Python.  Checkpoints attach at
  LLM-call and tool-call boundaries only; non-deterministic bits
  (`datetime.now()`, random, thinking traces) between boundaries are
  fine because they're not what we replay.

**Exit criteria:** a BUILD subagent that rate-limits on LLM turn N,
restarts cleanly and resumes from turn N without re-issuing the first
N-1 calls.  Checkpoint hits are visible in the TUI and transcript.
`make check` passes; new unit tests cover the checkpoint wrapper,
input-hash invalidation, and resume flow.  No regression in existing
task-level persistence.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Checkpoint schema (52.1) | Phase 28 SQLite WAL work | New table + migration |
| `checkpoint()` helper (52.2) | 52.1 | Core API everything else builds on |
| Subagent wiring (52.3) | 52.2 | Touches the main agent loop; needs care |
| Resume UX (52.4) | 52.3 | User-visible behaviour |
| Observability (52.5) | 52.3 | Transcript viewer + CLI add-ons |
| Cost accounting (52.6) | Phase 41.5 token counting | Extends existing tracking |

---

## Phase 54: Reverse-Engineer `docs/docs/` from HTML to Markdown

**Goal:** Restore authored-markdown sources for the user-facing docs
site (`docs/docs/*.html`) so the site can evolve alongside the code
without hand-editing HTML.  The site was authored in HTML directly —
there is no surviving markdown, `mkdocs.yml`, or Sphinx `conf.py` in
the tree — so this is a careful reverse-engineering job, not a
rebuild.  The hand-crafted structure (the Diátaxis split into
tutorial / how-to / reference / explanation, the styling hooks in
`docs.css`, the cross-page navigation) is design work worth
preserving.

This phase is **investigation-heavy** up front: pick a conversion
path that survives round-tripping, verify it preserves everything
that matters, then commit to it.

### 54.1 High — Audit the existing HTML and pick a conversion path ✓

- [x] Inventory complete: 19 HTML pages under `docs/docs/`.  Chrome
  (nav / sidebar / footer / skip-link / mobile-nav script) is identical
  across all pages and belongs in a Jinja2 template.  Content-side
  custom markup: `<p class="subtitle">`, `<div class="breadcrumb">` with
  `<span class="sep">/</span>`, ~130 heading anchor IDs, `<div class="callout">`
  and `<div class="callout-warn callout">` admonitions (7 pages),
  `<pre><code>` with `<span class="prompt">` / `<span class="comment">` /
  `<span class="dim">` styling (7 pages), `<dl><dt><dd>` definition
  lists with optional `<span class="arg-req">required</span>`, the
  landing-page `<div class="doc-cards">` grid, tables (12 pages), and a
  handful of HTML entities.
- [x] Conversion path chosen: **markdown-it-py + mdit_py_plugins.attrs
  + Jinja2 + PyYAML**, all already in the dependency tree.  Rejected
  pandoc (not installed, heavy), MkDocs-Material (fights existing
  hand-crafted CSS), and one-shot markdownify (can't round-trip
  prompt-styled spans and would duplicate chrome into every source
  file).  See `design/DOCS_REBUILD.md` for the full rationale.
- [x] Pilot round-trip on `howto-export.html`: zero semantic-DOM
  differences between the rebuilt HTML and the committed file (every
  tag, attribute, text node, and character reference matches).  Byte-
  for-byte parity with the hand-authored HTML is infeasible — the
  author wrapped paragraphs and deeply indented tags, while the
  markdown renderer emits flush-left compact blocks.  The build script
  therefore runs a **semantic DOM diff** in `--check` mode (entity
  references normalised against Unicode, whitespace runs collapsed)
  and reserves `--check --strict` for once the committed HTML has been
  regenerated from markdown.
- [x] `design/DOCS_REBUILD.md` written: captures the rejected
  alternatives, the chosen stack, file layout (`docs/src/`),
  frontmatter schema, manual-reconciliation rules for raw-HTML cases
  (callouts, prompt-styled code, `<dl>`, doc-cards), entity handling,
  build behaviour, and the pilot findings.

### 54.2 High — Convert every page and reconcile ✓

- [x] All 20 pages under `docs/docs/` (the Diátaxis tree plus the
  landing `index.html`) now have markdown sources under `docs/src/`
  in the CommonMark + raw-HTML flavour chosen in 54.1.  The pages
  break down as one tutorial, eight how-tos, two references, eight
  explanations, and the landing index.
- [x] Custom chrome handled by the template: the landing index uses
  a no-sidebar / no-breadcrumb layout with an inline-style
  `doc-layout`; the tutorial uses its own on-this-page anchor list
  as the primary sidebar block (`primary_list: on_this_page` in
  frontmatter); reference and explanation pages render both the
  section-nav list and an on-this-page list.
- [x] Raw-HTML patterns used where CommonMark falls short: callouts
  (`<div class="callout">` / `<div class="callout-warn callout">`),
  prompt-styled code blocks (`<pre><code><span class="prompt">…`),
  definition lists (`<dl><dt><dd>`), the landing-page doc-cards
  grid, and a handful of inline `<code>&nbsp;--&nbsp;</code> spans
  that need entity references inside.  All of it round-trips through
  the semantic-DOM check to zero differences.
- [x] Automatic external-link attribute rewriting: the build script
  adds `target="_blank" rel="noopener"` to any `<a>` with an
  `http(s)` href that doesn't already carry `target`, so authors
  write plain `[label](url)` markdown.
- [x] One intentional normalisation: `howto-hooks.html` had a
  bespoke footer (`<strong>Cantrip</strong> — autonomous charm
  builder.`) while every other page used the shared footer
  (`Cantrip — free & open source`).  The rebuild normalises to the
  shared footer.  Committed `design/DOCS_REBUILD.md` under the
  "Intentional normalisations" section so future authors see why.
- [x] Committed HTML regenerated from markdown sources so the build
  output is now byte-identical to what lives in `docs/docs/` —
  `make docs` (once 54.3 lands) will be a no-op diff-wise and any
  future drift shows up immediately in `--check --strict`.
- [x] Diátaxis filename convention preserved: `tutorial.md`,
  `howto-*.md`, `reference-*.md`, `explanation-*.md`, `index.md`.
  Section metadata and page ordering live in `docs/src/_site.yaml`
  so section-nav derivation stays data-driven.

### 54.3 Medium — Set up a markdown-to-HTML build system ✓

- [x] Build system chosen and implemented: `docs/src/_build.py` —
  markdown-it-py + `mdit_py_plugins.attrs` + Jinja2 + PyYAML, per
  the decision in 54.1.  No heavyweight SSG; a ~280-line Python
  script that is small enough to read in one sitting.  `mdit-py-plugins`
  promoted from a transitive-of-textual to an explicit dependency in
  `pyproject.toml` since the build script imports it directly.
- [x] Output path preserved: the build emits HTML into `docs/docs/`
  with the exact filenames the committed site uses, so all external
  links and relative anchors keep working.
- [x] Styling and assets preserved: `docs/docs/docs.css`,
  `docs/tokens.css`, `docs/style.css`, `docs/favicon.png`, and the
  `logo-{light,dark}.png` pair are committed assets untouched by the
  build; the template references them with the same relative paths
  as the hand-authored HTML did.
- [x] `make docs` / `make docs-check` / `make docs-check-strict`
  targets added to the Makefile with help-text entries.  A new
  `docs` job in `.github/workflows/ci.yaml` runs
  `make docs-check-strict` on every push and PR, catching any drift
  between the markdown sources and the published HTML.  Ran both
  `make docs` and the strict check against the current tree — both
  are no-ops.

### 54.4 Low — Round-trip verification and retire the old HTML ✓

- [x] Full-tree round-trip is clean: `make docs` is a byte-for-byte
  no-op against the committed tree, and `make docs-check-strict`
  passes on all 20 pages.  Intentional formatting differences
  (`howto-hooks.html` footer normalisation, `&mdash;` in `<title>`
  tags, curly-vs-ASCII apostrophe policy) were catalogued in
  `design/DOCS_REBUILD.md` § *Intentional normalisations* during
  54.2 and remain the only non-zero diff against the hand-authored
  originals; everything else is the build's own output.
- [x] Hosting decision: **keep the HTML committed.**  `README.md`
  and `CLAUDE.md` cross-link into `docs/docs/*.html` via
  repo-relative paths, and the GitHub-rendered view of those links
  requires the HTML to exist at that path on `main`.  Moving to
  CI-only would silently break every cross-link.  The markdown
  under `docs/src/` is the source of truth; the HTML is a build
  artifact committed for hosting convenience; `make docs-check-strict`
  in CI prevents the two from drifting.  Recorded in
  `design/DOCS_REBUILD.md` § *Hosting model* (replaces the old
  *Open questions* block).
- [x] `CONTRIBUTING.md` updated with a new *Editing the Docs Site*
  section explaining the edit-markdown / `make docs` / commit-both
  loop, and the stale "docs/ — Landing page" line in *Project
  Structure* replaced with the real Diátaxis layout (`src/`
  sources, `_build.py`, `_site.yaml`, `_templates/`, generated
  `docs/`).

### What this phase is *not*

- Not a rewrite of the docs content.  The pages are good; we only
  change the authoring format.
- Not a migration to a new docs framework for the sake of it.  If
  pandoc + a small Makefile rule produces acceptable output, that is
  the right answer — resist the pull toward a heavyweight SSG.
- Not user-facing content work.  Any new pages or rewrites belong in
  a follow-up phase, once the authoring loop is fixed.

**Exit criteria:** `docs/src/*.md` exists with authored-markdown
sources for every current page.  `make docs` rebuilds `docs/docs/`
from `docs/src/` with output that matches the committed HTML closely
enough for the diff to be a sensible CI gate.  `design/DOCS_REBUILD.md`
records the conversion-tool choice and any manual-reconciliation
rules.  No authored HTML remains in the docs tree.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| HTML audit (54.1) | none | Pure investigation; first step |
| Conversion (54.2) | 54.1 | Needs the chosen tool + flavour |
| Build system (54.3) | 54.2 | Builds from the new markdown |
| Round-trip (54.4) | 54.3 | Final gate before committing to the new authoring flow |

---

## Phase 55: Patterns from awesome-copilot — Investigation

**Goal:** A survey of the `awesome-copilot` repository (read locally
from `../awesome-copilot` during the survey) surfaced a handful of
patterns that neighbouring agent projects use heavily.  Some overlap
with work Cantrip has already done (durable state, prompt templating);
others are net new.  This phase commits to *investigating* each one
end-to-end: read the reference implementation, decide whether it fits
Cantrip's architecture, and either write up the decision or land a
minimal prototype.  No item here is a commitment to adopt — the exit
criterion is a written recommendation per idea, not new production
code.  Any adoption work that falls out of the investigation is
proposed as its own follow-up phase.  A second-pass review of the
repo's Cantrip-specific list (`ralph_loop.py`, the agent-governance
skill, the ospo workflow, the acquire-codebase-knowledge scan script,
the Copilot agent-frontmatter spec) refined several items below and
added two new ones (55.7, 55.8).

### 55.1 Medium — Skill-as-folder convention ✓

- [x] Surveyed three representative awesome-copilot skills at
  revision 2026-04-24: ``pytest-coverage`` (single-file),
  ``agent-governance`` (long prose, still single-file), and
  ``acquire-codebase-knowledge`` (fully populated —
  ``assets/templates/``, ``references/``, ``scripts/``).  Folder
  shape catalogued in ``design/SKILLS.md`` § *Skill-as-folder
  convention*.
- [x] Mapped against Cantrip's current layout: all 30 bundled
  skills are single ``SKILL.md`` files, bodies range from ~100
  to ~500 lines, content is workflow guidance (when-to-use,
  decision tables, code snippets, done-criteria).  None ships a
  template file or executable helper.
- [x] Identified two loader gaps that stand between the current
  layout and useful sibling files: ``LoadSkillTool`` surfaces
  only the body text (no asset paths, no skill-root injection),
  and the ``read_file`` tool is sandboxed to the working tree
  (skills live elsewhere).  Documented the three possible
  fixes (rewrite relative links; prepend a ``Skill root:``
  header; add a dedicated ``load_skill_asset`` tool).
- [x] Deviation: did **not** ship a physical prototype on
  ``harness-migration``.  A half-conversion would need the
  loader change to be useful, and a SKILL.md + duplicate-
  reference-file layout would add cruft without a quality win.
  The recommendation below explains the call.
- [x] Recommendation: **keep the directory shell, defer the
  plumbing.**  The loader already tolerates siblings (they're
  silently ignored); none of today's skills has a concrete need
  for them.  The pattern becomes valuable only when a skill
  ships an executable helper (Phase 55.7's scan.py port is the
  first real candidate) or a copy-me-into-the-repo template
  (Phase 55.6's cookbook may surface one).  File the loader
  work as a prerequisite of whichever of those lands first,
  rather than as a standalone phase.  Full write-up in
  ``design/SKILLS.md``.

### 55.2 Medium — Frontmatter metadata on subagents and prompts ✓

- [x] Audited Cantrip's subagent metadata surface: allowed tools
  live in ``subagent.py::_CATEGORY_TOOLS`` (a
  ``dict[TaskCategory, frozenset[str]]``); model routing in
  ``_select_provider`` + ``_LIGHT_CATEGORIES``; guidance bodies in
  ``prompts/subagent/*.md`` (already markdown, no frontmatter);
  max rounds in ``MAX_SUBAGENT_ROUNDS`` / ``MAX_BUILD_ROUNDS``;
  timeouts in ``executor.py::_TASK_TIMEOUTS``; temperature in
  ``_SUBAGENT_TEMPERATURE``.  Four Python data structures plus
  one function, plus six markdown guidance files.  Full table in
  ``design/PROMPTS.md``.
- [x] Read ``awesome-copilot/instructions/agents.instructions.md``
  in full (998 lines — it's a spec for how to author
  ``.agent.md`` files) and sampled two concrete agents
  (``accessibility.agent.md``, ``address-comments.agent.md``)
  from ``agents/``.  Catalogued the frontmatter fields
  (``description``, ``name``, ``tools``, ``model``, ``target``,
  ``user-invocable``, ``disable-model-invocation``,
  ``handoffs``, ``mcp-servers``, ``metadata``).
- [x] **Main verdict on the frontmatter schema: propose and
  defer.**  A hybrid adoption (frontmatter on
  ``prompts/subagent/<cat>.md`` as source of truth, Python
  rebuilds the ``_CATEGORY_TOOLS`` / rounds / timeouts dicts at
  import time) is plausible.  The payoff is small for six
  categories that change a couple of times a year, and the
  costs are real: loss of cross-category comparison at a
  glance, executable-conditional routing in ``_select_provider``
  can't live in frontmatter, and stringly-typed frontmatter
  drops the enum type-safety on ``TaskCategory`` / ``ModelHint``.
  Re-evaluate when categories grow past ~10, when non-Python
  contributors start authoring subagents, or when Phase 53.5
  (prompts/skills design split) absorbs the migration.  Full
  shape sketch recorded in ``design/PROMPTS.md`` § *Frontmatter
  metadata on subagents (Phase 55.2) — proposed, deferred*.
- [x] **Handoffs — rejected.**  ``handoffs:`` in Copilot is a
  VSCode-UI feature for interactive "next step" buttons.
  Cantrip's equivalent is ``AgentTask.dependencies: list[str]``
  — already declarative, already driving automatic dispatch
  through the executor.  ``handoffs:`` buys the deterministic
  planner nothing new.  For user-facing "what's next" hints in
  the TUI/Web after a task completes, that's a UI surface, not
  prompt frontmatter; file under Phase 76 (copy-friendly chat)
  or Phase 65 (task-panel review), not here.
- [x] **Auto-approve sentinel — defer to Phase 68.2.**  Naming
  a mode without a behavioural difference is premature — the
  sentinel only carries weight once there's more than one mode.
  Phase 68.2 ("Declarative permission config") already scopes
  YAML ask/allow/deny rules per tool + source; when 68.2 lands
  it will introduce the ``PermissionMode`` enum naturally.
  Adding a single-value enum ahead of it is wasted motion.

### 55.3 Medium — Ralph-loop / disk-as-state comparison and per-goal budget ✓

- [x] Read ``awesome-copilot/cookbook/copilot-sdk/python/recipe/ralph_loop.py``
  (79 lines).  Control flow: one prompt file, loop ``max_iterations``
  times, create a fresh CopilotClient session each iteration
  (``PermissionHandler.approve_all``), ``send_and_wait`` with 600 s
  timeout, ``destroy()`` the session.  State between iterations
  carries on disk via plain markdown (``IMPLEMENTATION_PLAN.md``,
  ``AGENTS.md``, ``specs/*``).
- [x] Diffed against Cantrip's two-loop design: the overlap is
  large.  Cantrip's subagent-per-task pattern *is* the ralph
  fresh-session-per-iteration pattern, scaled up with a work
  queue, typed dependencies, parallel subagents under a
  concurrency semaphore, category-scoped tool allowlists, and
  (since Phase 52) step-level checkpoint replay.  Full mapping
  table in ``design/AGENT.md`` § *Prior art — the ralph loop*.
- [x] Delta identified: the single ralph primitive Cantrip is
  missing is a **hard per-goal iteration + token budget with a
  circuit breaker**.  Today the autonomous loop drains the work
  queue on its own schedule; a runaway planner could in principle
  spawn arbitrary follow-up tasks without an aggregate cap.
- [x] Scoped and sized the missing piece in ``design/AGENT.md``
  § *Per-goal budget (scoped follow-up — see ROADMAP Phase 55.3)*:
  new ``AgentState.goal_budget: GoalBudget | None`` with
  ``max_iterations`` / ``max_prompt_tokens`` /
  ``max_completion_tokens`` / ``started_at``; executor gate
  ``_budget_allows(task)`` before each spawn that queries
  ``SessionStore.get_usage_since(started_at)`` against the caps;
  tripped task → ``BLOCKED`` with ``budget_exceeded`` reason +
  ``goal_budget_exceeded`` event; recovery via ``/budget`` slash
  command, ``--max-iterations`` / ``--max-tokens`` CLI flags,
  and ``CANTRIP_MAX_*`` env vars.  Pairs with Phase 55.4's
  ``max_calls_per_request`` (tool-level version of the same
  circuit-breaker shape).
- [x] Sized: ~150 lines for the budget module + one event type
  + two CLI flags + three tests (gate trips / raise clears /
  resume honours the cap).  Investigation ends here —
  implementation deferred to a dedicated follow-up phase when
  autonomous runs routinely exceed ~20 tasks and the
  "run-until-done" default stops being adequate.

### 55.4 High — Policy composition for tool access ✓

- [x] Read ``awesome-copilot/skills/agent-governance/SKILL.md``
  in full (569 lines, six patterns): ``GovernancePolicy`` +
  ``compose_policies()``, semantic intent classification, the
  ``@govern`` decorator, trust scoring with temporal decay,
  JSONL audit trail, framework-integration examples.
- [x] Mapped Cantrip's current tool-gating: one layer —
  ``_filter_tools(tools, category)`` in ``subagent.py`` — keyed
  off ``TaskCategory.INFRA``-style enums.  Identified the three
  gaps a stacked-policy design closes: no global floor, no
  per-charm scoping, no in-code destructive gate for
  ``tools/juju.py::JujuDestroyModelTool``-style direct
  ``subprocess.run`` paths.
- [x] **Keep / defer / reject per primitive** (full table in
  ``design/TOOLS.md`` § *Policy composition for tool access
  (Phase 55.4)*):
  - ``GovernancePolicy`` + ``compose_policies`` — **keep**
  - Per-goal ``max_calls_per_request`` — **keep** (pairs with
    55.3)
  - JSONL audit trail — **keep** (streaming export alongside
    SQLite events)
  - Juju-aware destructive-command gate — **keep** (fills a
    real gap left by Phase 46 / 49)
  - Intent classification — **defer** (charm-building signal
    is tool surface, not prompt content)
  - Trust scoring — **reject** (Cantrip has no mutually-
    untrusted delegation)
- [x] Documented the relationship to Phases 46 / 49 / 55.3 / 55.5
  in ``design/TOOLS.md``: the five layers nest as
  *global budget > task safe-outputs > policy allowlist >
  user hook > sandbox*; any one can stop a tool call.  Phase
  55.4 + the new Phase 80 fill the fifth layer (policy
  allowlist).
- [x] **Filed Phase 80: Stacked Tool-Access Policies** (see
  entry in this roadmap) with five subphases for the kept
  primitives: 80.1 ``GovernancePolicy`` + ``compose_policies``,
  80.2 dispatcher wiring, 80.3 ``max_calls_per_request``, 80.4
  JSONL audit trail, 80.5 in-code destructive gate.  No tiny
  prototype of ``compose_policies`` against one task type —
  the phase proposal is where that lives.

### 55.5 Low — Markdown workflows versus Python orchestration ✓

- [x] Read three awesome-copilot workflow files: the 124-line
  ``ospo-release-compliance-checker.md`` (full frontmatter + 7
  numbered sections starting with an explicit *Trigger Guard*),
  the 23-line ``daily-issues-report.md`` (minimal frontmatter with
  ``safe-outputs: create-issue``), and the 64-line
  ``relevance-check.md`` (slash-command + GitHub-Actions-style
  ``${{ }}`` templating).
- [x] Identified ``plan_sprint_deploy`` as the closest Cantrip
  analogue and diffed: the awesome-copilot format conflates
  *dispatch* (triggers, permissions, side-effect caps) with
  *prompt body* (numbered step-by-step).  Cantrip already
  separates these — Python handles dispatch, Jinja2/markdown
  handles the body via ``task_prompts.render(...)``.  A markdown
  conversion would have to push dispatch into stringly-typed
  frontmatter and lose the typed ``AgentTask`` fields and the
  value-computing Python (``_host_ubuntu_version()``,
  ``_FAST_PATH_FRAMEWORKS`` membership, unique-id allocation,
  dependency chaining).
- [x] **Main verdict: reject the format for the deterministic
  planner.**  Keep Python for orchestration, keep Jinja2/markdown
  for prompt bodies (already the shape).  The fast-path, sprint,
  and one-shot recipes in ``deterministic.py`` do not benefit from
  a markdown conversion — the uniformity wins are small and the
  costs (stringly-typed frontmatter, lost dynamic behaviour) are
  real.
- [x] **Micro-pattern 1 lifted: explicit trigger guard as step 1 of
  every task template.**  ospo's section 1 reads "if X, proceed;
  otherwise, stop."  Cantrip task templates currently launch
  straight into instructions; a short "first, check X/Y/Z — stop
  and report if not satisfied" header on each template would
  short-circuit misrouted tasks before they burn tokens.  Filed
  as a drive-by improvement to apply when touching each template
  for other reasons (~8 templates in ``task_prompts/``, one
  paragraph each).  Not scoped to a roadmap phase yet.
- [x] **Micro-pattern 2 lifted: ``safe-outputs`` cap — declarative
  per-task side-effect limits.**  Sketched as a new
  ``AgentTask.safe_outputs: dict[str, int] | None`` field the
  subagent checks inside its tool dispatcher before each call;
  tripped cap → synthetic ``ToolResult(success=False,
  error="safe-outputs cap exceeded")`` + UI event.  Composes
  cleanly with 55.3's goal-level budget and 55.4's tool-level
  ``max_calls_per_request`` — goal > task > tool, same
  circuit-breaker shape at three layers.  Sized at ~100 lines +
  event type + tests; filed to pair with whichever of 55.3 / 55.4
  lands first so the event bus gets one structured shape instead
  of three similar-but-different ones.
- [x] Full write-up in ``design/PROMPTS.md`` § *Markdown-workflow
  format (Phase 55.5) — rejected, with micro-patterns lifted*.

### 55.6 Medium — Runnable cookbook ✓

- [x] Reviewed ``awesome-copilot/cookbook/copilot-sdk/python/recipe/``
  (seven recipes, 25-200 lines each, plus a 92-line README).  The
  recipes are *demonstration scripts*, not CI-enforced fixtures —
  they hit live models and expect the user to run them manually.
- [x] Enumerated six candidate recipes in ``cookbook/README.md`` with
  status columns: ``build-a-sprint-charm`` (✅ shipped),
  ``build-a-stateful-charm``, ``migrate-harness-to-scenario``,
  ``add-observability``, ``generate-a-terraform-module``,
  ``deploy-with-juju-and-cos`` (🗓️ proposed).  Proposed recipes
  are tracked here as follow-up items; a PR with a new
  ``cookbook/<name>/`` directory promotes one.
- [x] Shipped ``cookbook/build-a-sprint-charm/`` — deviation from
  the roadmap's "build-a-stateful-charm" suggestion because sprint
  mode is deterministic, has a clear published shape contract in
  ``_SPRINT_GUIDANCE``, and doesn't need a live Juju model to
  demonstrate.  Directory contents: ``README.md`` (walkthrough),
  ``prompts.md`` (copy-paste prompts for a live Cantrip session),
  ``verify.py`` (CLI + importable library that asserts the
  sprint-mode invariants — base ``ubuntu@24.04``, charm plugin,
  no ``build-snaps``, single ``ops>=3,<4`` requirement, no
  ``ops-tracing``/``ops-scenario``, ``src/charm.py`` present).
- [x] Wired one recipe into CI via
  ``tests/unit/test_cookbook_recipes.py`` (16 tests).  Two layers:
  **structure drift** (every recipe must carry README + prompts +
  verify.py, verify.py must be valid Python) via a parametrised
  sweep over ``cookbook/*/``, and **output drift** (verifier's
  happy path + every failure mode exercised against handwritten
  in-process fixtures).  Live Cantrip runs stay out of CI — too
  slow, too credentialled, too environment-dependent.
- [x] Cross-linked from ``CONTRIBUTING.md`` with a new *Cookbook
  recipes* section.  Docs-site cross-link is deferred to the
  docs-authoring pass for 55.6's proposed follow-up recipes
  (empty cookbook index doesn't warrant a dedicated docs page
  yet; adding one when the second recipe lands).
- [x] Shipped the ``make coverage`` micro-improvement:
  ``--cov-report=annotate:cov_annotate`` added to the ``coverage``
  target in ``Makefile`` with a comment explaining the ``!``-prefix
  convention, and ``cov_annotate/`` added to ``.gitignore``
  alongside the existing ``htmlcov/``.

### 55.7 Medium — Deterministic pre-scan for Path B custom apps ✓

- [x] Read ``awesome-copilot/skills/acquire-codebase-knowledge/scripts/scan.py``
  (712 lines): 60-entry manifest catalogue across 25+ languages,
  10 CI/CD platforms, Docker/k8s/Vagrant detection, SBOM +
  security-config scanning, lint-config detection, 40+ entry-point
  candidates, git churn, TODO search, code metrics.
- [x] Mapped against Cantrip's ``AnalyseFrameworkTool``: the two
  scans are complementary — upstream is breadth (25+ languages),
  ``analyse_framework`` is charm-specific depth (PaaS profile
  map, substrate suggestion, ROCKCRAFT_ENABLE_EXPERIMENTAL
  flagging).  Full comparison table in ``design/TOOLS.md`` §
  *Deterministic pre-scan for Path B*.
- [x] **Verdict: port.**  Vendor-as-is loses charm awareness
  (`charmcraft.yaml` would go undetected) and needs the Phase
  55.1 loader changes that were deferred.  Subprocess-invoke
  loses the structured-dict output that the checkpoint envelope
  (Phase 52.3) rewards.  A port to
  ``src/cantrip/agent/tools/_scan.py`` converges the two scans
  onto one source of truth with Cantrip-specific additions
  (``charmcraft.yaml`` / ``rockcraft.yaml`` / ``metadata.yaml``
  / ``.cantrip`` detection; ``CHARM_MARKERS`` signalling
  "existing charm, route to improvement path").
- [x] Shipped **stub** ``src/cantrip/agent/tools/_scan.py`` with:
  upstream data tables (``MANIFESTS``, ``ENTRY_CANDIDATES``,
  ``CI_CD_CONFIGS``, ``CONTAINER_FILES``, ``SECURITY_CONFIGS``,
  ``LINT_FILES``, ``ENV_TEMPLATES``, ``EXCLUDE_DIRS``) plus the
  Cantrip-local ``CHARM_MARKERS``; a frozen ``ScanResult``
  dataclass describing the output shape (JSON-friendly for the
  Phase 52.3 checkpoint envelope); a ``scan(path) ->
  ScanResult`` entry point that returns an empty result with
  TODO markers enumerating the nine detection passes.  MIT
  attribution in the file header.  Stub smoke-tested via
  ``uv run python -c "from cantrip.agent.tools import _scan; …"``.
- [x] Implementation deferred to a follow-up phase — the stub
  anchors the shape decision without committing to the ~400-500
  lines of detection-pass code.  File the implementation when a
  real Path B (custom app) user demonstrates the round-trip
  cost.

### 55.8 Low — Charm-design spec template ✓

- [x] Read
  ``awesome-copilot/skills/create-github-action-workflow-specification/SKILL.md``
  (276 lines): mermaid flow diagrams, Functional/Security/
  Performance requirements matrices with REQ-001-style IDs,
  input/output contracts, execution constraints, error-handling
  strategy, quality gates, monitoring/observability,
  compliance/governance, edge-case matrices, validation
  criteria, change management, version history.
- [x] Audited Cantrip's existing design surface: ``DesignProposal``
  in ``agent/design.py`` already carries structured fields
  (``substrate``, ``charm_path``, ``integrations``,
  ``companions``, ``config_options``, ``actions``,
  ``scaling_strategy``, ``operational_patterns``,
  ``questions_for_user``, ``security_surface``, ``sources``,
  ``raw_design_md``).  ``format_for_chat()`` renders it for
  user confirmation; ``to_design_md()`` threads the raw markdown
  into downstream subagents via ``SubagentContext.design_content``
  + the ``## Approved design`` block in the build subagent's
  system prompt.  The confirmation flow is fully implemented.
- [x] **Verdict: reject the template, lift two shape upgrades.**
  The awesome-copilot shape is for *reverse-engineering an
  existing CI/CD workflow* — requirements matrices + compliance
  sections + version history don't fit a *proposal* for a charm
  that doesn't exist yet.  Forcing that shape would turn the
  confirmation step into form-filling and duplicate source-of-
  truth artefacts (git, SQLite, ops-readiness skill).
- [x] Two bits worth lifting as drive-by improvements to
  ``design.py::DesignProposal.format_for_chat()``:
  - **Mermaid diagram of relation integrations** generated
    deterministically from ``integrations`` + ``companions``.
    Rendered by GitHub / mkdocs / future TUI work; degrades to
    readable text elsewhere.
  - **Table format for config options and actions** (currently
    bullet lists; a ``| name | type | purpose |`` table matches
    how charm authors document the same fields in
    ``config.yaml`` / ``actions.yaml``).
  Both are ``format_for_chat`` edits — neither scoped to a
  phase yet; file when revisiting the design-confirmation
  flow.
- [x] Full write-up in ``design/AGENT.md`` § *Design proposal as
  pre-build spec (Phase 55.8)*.  No code changes —
  investigation only.

### What this phase is *not*

- Not a commitment to adopt every pattern.  Several items plausibly
  end in "rejected, with reasoning recorded" — that is still a
  successful outcome.  55.4 in particular is expected to need more
  investigation than one pass can deliver; the phase closes when the
  recommendation is written, not when the refactor lands.
- Not a rebuild of the skills or planner subsystems.  Any net-new
  production work gets proposed as its own phase; this phase ends at
  the recommendation.
- Not a duplicate of Phase 52 (durable execution) or Phase 50 (skills
  interop).  Where those phases already cover the ground, the output
  here is a single paragraph crediting them and pointing readers at
  the reference implementation in awesome-copilot.
- Not Phase 56.  Publishing Cantrip's Juju knowledge as reusable
  Copilot / Claude Code assets is tracked separately so it is not
  held up behind the investigation items here.

**Exit criteria:** Each of 55.1 through 55.8 has a written decision or
prototype committed to the repo — as a section in an existing
`design/` doc, a follow-up phase proposal, or a working cookbook
recipe.  The survey notes from `../awesome-copilot` are captured in a
single `design/AWESOME_COPILOT_SURVEY.md` alongside the per-item
decisions, so a future maintainer can re-evaluate without re-reading
the upstream repo.  55.4 explicitly exits at "recommendation filed,"
not at "refactor complete."

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Skill-as-folder (55.1) | Phase 53.5 (`design/SKILLS.md`) | Extends the doc; can run in parallel, lands after |
| Subagent frontmatter (55.2) | Phase 53.5 (`design/PROMPTS.md`) | Same |
| Ralph-loop + per-goal budget (55.3) | Phase 52 | Needs the step-level durable design to diff against |
| Policy composition (55.4) | Phase 46, Phase 49, 55.3, 55.5 | Recommendation must place this relative to adjacent work and the micro-patterns from 55.3/55.5 |
| Markdown workflows (55.5) | Phase 53 | Reuses the planner split and template loader |
| Cookbook (55.6) | none | Independent; can land first |
| Pre-scan (55.7) | none | Independent; feeds into Path B discovery |
| Charm-design spec (55.8) | Phase 53 | Template lives under `prompts/design/` |

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

## Phase 80: Stacked Tool-Access Policies

**Goal:** Replace the single-level category allowlist
(``_filter_tools(tools, category)`` in
``src/cantrip/agent/subagent.py``) with a composable
policy-stack that layers **global** + **per-task-category** +
**per-charm** rules, plus a per-goal rate limit, a JSONL
audit trail, and Cantrip-side destructive-command gates.
Filed by the Phase 55.4 investigation — see that phase in the
roadmap + ``design/TOOLS.md`` § *Policy composition for tool
access (Phase 55.4)* for the analysis that scoped this work.

The design lifts the primitives worth keeping from awesome-
copilot's ``agent-governance`` skill while leaving behind
multi-agent trust scoring (Cantrip doesn't have mutually
untrusted delegation) and intent-classification regex (in a
charm-building context, the signal comes from the tool surface,
not prompt content).

This phase is **implementation**, not investigation — the 55.4
write-up already decided keep/defer/reject per primitive.

### 80.1 High — ``GovernancePolicy`` dataclass + ``compose_policies``

- [ ] Add ``src/cantrip/agent/policy.py`` with a frozen
  ``GovernancePolicy`` dataclass carrying
  ``allowed_tools: frozenset[str]``,
  ``blocked_tools: frozenset[str]``,
  ``require_human_approval: frozenset[str]``, and
  ``max_calls_per_request: int | None``.
- [ ] Implement ``compose_policies(*policies) ->
  GovernancePolicy`` with most-restrictive-wins semantics —
  allow-lists intersect, block-lists union, approval-lists
  union, rate limit is the minimum non-``None`` value.
- [ ] Load policies from YAML
  (``~/.config/cantrip/policies/*.yaml`` and
  ``<charm>/cantrip.policies.yaml``) via a small parser; ship
  three built-in policies (``org-wide``, ``category:<name>``,
  ``sprint``) as default-deny floors.
- [ ] Unit tests: composition is commutative for union fields
  and associative for all; compose of empty-set allow and
  non-empty-set allow keeps the non-empty; rate limit picks
  the strictest; YAML round-trips.

### 80.2 High — Wire policies into the subagent dispatcher

- [ ] Replace ``_filter_tools(tools, category)`` with a
  ``PolicyEnforcer`` helper that composes the active policy
  stack once per subagent run and exposes
  ``check_tool(name) -> PolicyAction``.
- [ ] The existing ``_tool_or_veto`` path in
  ``subagent.py`` gains a ``check_tool`` call before the
  PRE_TOOL_CALL hook fires.  Policy ``DENY`` produces a
  synthetic ``ToolResult(success=False, error="policy blocks
  ...")`` with the policy name in the error; ``REVIEW`` maps
  to a confirmation request (depends on Phase 68.2's
  declarative permission work; until that lands, ``REVIEW``
  degrades to ``DENY`` with a log line suggesting the user
  add an approval rule).
- [ ] Preserve the MCP-tool exception today's filter carries
  — MCP tools still pass through the per-server
  ``allowed_tools`` config (Phase 45.2) as the gate, not
  category policy.

### 80.3 Medium — ``max_calls_per_request`` per-goal rate limit

- [ ] A per-goal counter in the executor, keyed off the
  current ``AgentState.goal_budget`` (see Phase 55.3's sketch
  — the two pair naturally).  Each call to a non-MCP tool
  increments the counter; tripping the composed policy's
  ``max_calls_per_request`` marks the task ``BLOCKED`` with
  ``blocked_reason="policy rate limit exceeded"`` and emits
  a ``policy_rate_limited`` event on the bus.
- [ ] Compose cleanly with 55.3's goal-level budget
  (``max_iterations``) and 55.5's per-task ``safe_outputs``
  — three circuit breakers at goal > task > session-call
  granularity, all using the same blocked-reason string
  format so the TUI can render them uniformly.

### 80.4 Medium — JSONL audit trail

- [ ] Append-only ``<charm>/.cantrip-audit.jsonl`` with one
  line per policy decision (``allowed`` / ``denied`` /
  ``review-requested`` / ``rate-limited``).  Fields:
  ``timestamp`` / ``task_id`` / ``tool`` / ``action`` /
  ``policy_name`` / ``reason`` / ``arguments`` (redacted via
  the existing secret-scrubbing from Phase 50.2).
- [ ] ``cantrip audit`` CLI subcommand with
  ``list [--task-id X] [--action ACTION]`` and ``export
  [--format jsonl|csv]``.  Lightweight — wraps the existing
  SQLite event store path so there's one source of truth for
  "what did the agent actually do."
- [ ] The file is additive to the SQLite ``events`` table:
  SQLite stays as the primary store; the JSONL is a
  streaming, grep-friendly export that plays nicely with
  ``tail -f`` and off-the-shelf log aggregators.

### 80.5 Medium — Juju-aware destructive-command gate

- [ ] Add an inline gate inside ``tools/juju.py`` (at minimum
  ``juju_destroy_model``, ``juju_remove_application``,
  ``juju_remove_relation``) and ``tools/run_command.py`` (at
  minimum ``rm -rf``, ``git push --force``, ``git reset
  --hard``).  The gate fires **before** ``subprocess.run``
  so a vetoed call never touches the model or the shell.
- [ ] Gate decisions flow through the same policy stack —
  the destructive-command list becomes an implicit
  ``require_human_approval`` addition for the bundled
  ``org-wide`` policy.  Operators who want bypass
  capabilities (unattended ``cantrip --yolo`` or equivalent)
  set ``approve_destructive: true`` in a charm-local
  policy file.
- [ ] Covers the gap Phase 55.5 identified: user hooks
  (Phase 46) only fire at lifecycle events; the sandboxed
  shell (Phase 49) isolates subprocess execution *after*
  the call; neither catches a subagent that decides on its
  own to call ``juju destroy-model`` through
  ``tools/juju.py``.  This phase's in-code gate is the
  third layer.

### What this phase is *not*

- **Not trust scoring.**  The ``agent-governance`` skill's
  Pattern 4 (trust scores with temporal decay for multi-agent
  delegation) assumes untrusted agent-to-agent delegation —
  Cantrip's subagents all descend from one trusted operator.
  Explicitly rejected in 55.4.
- **Not intent classification.**  The skill's Pattern 2
  (regex threat scoring against prompt content) is deferred:
  in a charm-building context the signal comes from the tool
  surface (``juju destroy-*``, ``rm -rf``), not the prompt
  content.  Revisit if a real case emerges where a prompt-
  content regex would have caught something the tool-surface
  gate missed.
- **Not a replacement for Phase 46 user hooks or Phase 49
  sandboxing.**  The three layers are complementary: hooks
  run at lifecycle events (PRE/POST subagent, tool_call,
  compact); sandboxing isolates subprocess execution from
  the host FS/network; policy composition gates which tools
  the LLM is allowed to *request* in the first place.  A
  defence-in-depth implementation uses all three.

**Exit criteria:** Composing policies produces the expected
intersection/union; a subagent run with a restrictive policy
can't call blocked tools; per-goal rate limit trips the
expected circuit breaker; JSONL audit contains one line per
policy decision; ``juju destroy-model`` refuses in bundled-
policy mode without ``--yolo`` or an explicit charm-local
override.  New unit tests exercise compose semantics, YAML
parsing, dispatcher integration, and each of the three
circuit breakers (80.2 / 80.3 / 80.5).

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Policy dataclass (80.1) | none | Pure data module + YAML loader |
| Dispatcher wiring (80.2) | 80.1, Phase 46 (hook runner) | Policy check fires before pre-hooks |
| Rate limit (80.3) | 80.1, Phase 55.3 (goal_budget) | Shares the goal-scoped counter |
| Audit trail (80.4) | 80.1, existing SQLite events | Streaming export, not new store |
| Destructive gate (80.5) | 80.1, Phase 49 (sandbox) | Defence-in-depth third layer |

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

## Phase 67: Pi-Inspired Session and Scripting Features

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

### 67.1 High — Session tree: rewind and branch

- [ ] Audit ``src/cantrip/transcripts/`` (or the equivalent SQLite
  layer from Phase 14) for the assumptions that sessions are
  linear.  Likely candidates: resume logic in
  ``src/cantrip/agent/core.py`` that loads messages in insertion
  order, and any summariser that walks ``state.messages`` as a
  list.  Write the findings into the phase before changing code.
- [ ] Add a ``parent_turn_id`` column (nullable; ``NULL`` means
  "root") to the turn table.  Backfill existing rows to form a
  degenerate linear tree.  Add an index on ``(session_id,
  parent_turn_id)``.
- [ ] Add ``/branch [turn-id]`` — forks from the given turn (or
  the one before the last user message, if omitted) and makes
  the forked branch active.  ``state.messages`` is rebuilt from
  the new active path.
- [ ] Add ``/tree`` — opens a TUI modal that renders the session
  as an indented tree with timestamps and the first line of each
  user message; ``Enter`` activates a node.  Non-destructive —
  the original branch stays in the DB.
- [ ] Export already operates per-session; update
  ``export-transcript`` to take an optional ``--branch
  <turn-id>`` filter so a branched session exports only the
  active path (default: the currently active branch).
- [ ] ``@@`` prompt affordance (from Amp): typing ``@@`` in
  the TUI chat input opens a fuzzy search over the user's
  prior sessions and branches (title, first user message,
  date, active charm) and inserts a reference token
  ``@S-<session-id>`` or ``@T-<turn-id>`` into the message.
  On send, the referenced branch's last assistant summary
  (or a configurable window of messages) is prepended as a
  "cited-thread" block so the agent can draw on the prior
  context without the user copy-pasting.  Reuses the tree
  modal's picker widget — one UI, two entry points.
- [ ] ``tests/unit/test_transcript_branching.py`` — round-trip
  branch/rewind, assert the original branch is still reachable,
  resume picks the last active branch; ``@@`` inserts a
  reference token and the referenced context is materialised
  exactly once on send.

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

### 67.3 Medium — Non-interactive print mode

- [ ] Add ``cantrip run --print "<goal>"`` (or equivalent flag) to
  the existing ``run`` subparser.  Runs the autonomous loop
  without a TUI; prints the final agent summary and exits when
  the work queue drains or the goal is marked done.
- [ ] Add ``--json`` to stream the existing
  ``cantrip.ui.events`` payloads as newline-delimited JSON on
  stdout, one event per line.  Document the event schema in
  ``docs/docs/reference-cli.html`` — it becomes a supported
  public surface once we ship this.
- [ ] Decide how user confirmations behave in print mode: the
  existing CONFIRM tasks (Phase 64) need an ``--auto-approve``
  flag *or* the print-mode entrypoint refuses to run when
  unapproved confirmations exist.  Default to "refuse and exit
  non-zero with a list of the pending confirmations" so scripts
  don't accidentally deploy.
- [ ] ``tests/unit/test_cli_print_mode.py`` — fake provider, assert
  the JSON stream is well-formed, final exit code reflects
  task success/failure, pending confirmations block the run.

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

## Phase 68: OpenCode-Inspired Safety Rails — Undo, Plan Mode, Permissions, User Commands

**Goal:** OpenCode (``opencode.ai``, ~140k GitHub stars) is a
general-purpose open-source coding agent.  A walk of its docs
surfaces four safety/UX patterns that are absent from Cantrip and
that map cleanly onto existing infrastructure.  Charm authoring
is higher-stakes than typical coding (a bad change can tear down
a running model) so the recovery and guardrail features are a
particularly good fit.

Four candidates, in rough priority order:

1. **Snapshot-backed ``/undo`` and ``/redo``.**  OpenCode keeps an
   *internal* git repository that snapshots every file the agent
   touches before a turn.  ``/undo`` rewinds the last user
   message *plus every file change that came from it*;
   ``/redo`` re-applies.  Cantrip has worktree isolation for
   parallel subagents (Phase 44) and git_commit tools (Phase 30)
   but no per-turn file-level rollback in the user's tree.  When
   the agent makes a mess in ``src/charm.py``, the only recovery
   today is ``git stash`` / ``git restore`` by hand.  Phase 67.1
   addresses rewinding the *conversation*; this addresses
   rewinding the *working tree*.  The two compose.
2. **Declarative ask / allow / deny permission config.**
   OpenCode's ``permission:`` block in ``opencode.json`` takes
   glob patterns per tool, per bash command, and per agent:
   ``{"bash": {"*": "ask", "git *": "allow", "rm *": "deny"}}``.
   Cantrip has three relevant but distinct pieces: category tool
   allowlists (BUILD/TEST/RESEARCH), Phase 46 hooks (pre/post
   events), and Phase 49 subprocess sandboxing.  None of them
   is a user-editable permission config with three-way outcomes
   and glob patterns.  A permission layer sits between hooks
   and sandboxing and gives operators a readable policy file
   they can check into a charm repo.
3. **User-defined slash commands from markdown.**  OpenCode reads
   ``.opencode/commands/<name>.md`` with YAML frontmatter
   (``description``, ``agent``, ``model``, ``subtask``) and
   ``$ARGUMENTS`` / ``$1`` / ``$2`` placeholders; the markdown
   body is the prompt template.  Shell output (``!`cmd` ``) and
   file references (``@path``) interpolate at invocation time.
   Cantrip's slash commands are hardcoded in
   ``src/cantrip/agent/slash_commands.py``.  Opening them up
   lets a charm team drop ``/relation-check``,
   ``/upgrade-libs``, ``/triage`` into a repo without touching
   Cantrip source.
4. **Plan mode — a session-level "review before executing"
   toggle.**  OpenCode has two modes (Plan, Build), toggled with
   Tab.  In Plan mode the agent proposes actions but cannot
   edit, write, or run bash.  Cantrip's CONFIRM tasks
   (Phase 64) gate individual irreversible actions; Plan mode
   would gate *the whole session* so a user can walk through
   an entire build without any side effects, then flip to Build.
   Useful for demos, design reviews, and "what *would* you do?"
   conversations.

Four OpenCode features are explicitly **out of scope**:

- **Plugins in JS/TS with ``tool.execute.before/after`` hooks.**
  Cantrip is Python; a JS plugin runtime would be a heavy
  addition and Phase 46 already covers the hook niche.
- **Hosted session share at ``opncd.ai/s/<id>``.**  Phase 67.4
  already proposes ``/share`` via ``gh gist create``, which
  stays on infrastructure the user already trusts and doesn't
  require a Cantrip-run server.
- **ACP (Agent Client Protocol) support.**  Phase 39 already
  tracks this as a research item.  Reference here, don't
  duplicate.
- **LSP autoloading.**  Nice-to-have (pyright / ty for Python,
  yaml-language-server for ``charmcraft.yaml``) but non-trivial;
  out of scope for this phase.  If the idea has legs, it lives
  as its own follow-up phase.

### 68.1 High — Snapshot-backed undo/redo for file changes

- [ ] Audit which Cantrip tools mutate the working tree
  (``fs_write``, ``fs_edit``, ``fs_patch``, the various charm-
  init and pack tools, ``git_*`` tools).  List them in the
  phase before coding; this is the allowlist the snapshotter
  has to cover.
- [ ] Add a snapshot layer that, before a user turn completes,
  commits the relevant paths into a hidden git repo under
  ``.cantrip/snapshots/`` (or ``$XDG_STATE_HOME/cantrip/…``
  for the user's global path).  Use ``git`` directly — do not
  invent a new format.  Commit message is
  ``snapshot: turn <turn-id>``.
- [ ] ``/undo`` — walks back one user turn: restores files to
  the prior snapshot *and* removes that turn and its
  subsequent assistant messages from ``state.messages``.
  Running ``/undo`` repeatedly walks further back.
- [ ] ``/redo`` — re-applies the most recently undone turn if
  no new user turn has arrived since the undo.
- [ ] Clear boundary with Phase 44 (worktrees): worktrees
  isolate concurrent subagents; snapshots capture the main
  working tree across user turns.  Document the relationship
  in ``design/AGENT.md``.
- [ ] Disable flag for large monorepos: ``snapshot: false`` in
  ``cantrip.yaml`` (mirroring OpenCode's escape hatch).  When
  disabled, ``/undo`` prints a clear message and exits non-
  zero rather than silently doing nothing.
- [ ] ``tests/unit/test_snapshots.py`` — mutate a temp tree,
  undo, assert content restored; redo, assert mutation back;
  multi-level undo; disabled-mode message; snapshot skipped
  for paths outside the repo root.

### 68.2 High — Declarative permission config

- [ ] ``.cantrip/permissions.yaml`` (repo) and
  ``~/.config/cantrip/permissions.yaml`` (user), merged with
  repo taking precedence.  Three outcomes: ``allow``, ``ask``,
  ``deny``.  Glob patterns on tool name and on bash command
  string.  Last matching pattern wins (match OpenCode's rule
  so the config transfers).
- [ ] Sensible defaults shipped as a built-in fallback:
  ``bash: rm -rf *`` → ``deny``; ``.env`` reads → ``deny``;
  ``git push *`` → ``ask``; everything else → ``allow`` (i.e.
  today's behaviour).
- [ ] Enforcement sits *before* tool dispatch, *after* Phase 46
  pre-tool hooks.  A ``deny`` raises a tool-refused result to
  the agent; an ``ask`` prompts the user via the existing
  CONFIRM-task pathway (Phase 64) so the UX matches what the
  user already sees.
- [ ] Per-agent and per-subagent overrides: the policy block
  can be nested under ``agent: <name>`` to tighten or loosen
  rules for a specific (sub)agent.  Mirrors OpenCode's
  per-agent permission blocks.
- [ ] Emit a ``permission_decided`` event on the event bus so
  the transcript records *why* a call was blocked or approved;
  feeds the audit log from Phase 14.
- [ ] Document in ``docs/docs/howto-permissions.html`` (new
  page) and link from ``docs/docs/reference-cli.html``.
- [ ] ``tests/unit/test_permissions.py`` — last-match-wins,
  glob semantics, per-agent override merge, ``ask`` routes
  through CONFIRM task, default-safe fallbacks.

### 68.3 Medium — User-defined slash commands

- [ ] Loader that discovers ``.cantrip/commands/*.md`` (repo)
  and ``~/.config/cantrip/commands/*.md`` (user).  Filename
  → command name (``debug-relation.md`` → ``/debug-relation``).
  Repo beats user on name conflict.
- [ ] YAML frontmatter: ``description``, ``agent`` (one of the
  existing subagent names, or ``primary``), ``model`` (optional
  override), ``subtask`` (bool — route via the work queue
  instead of the primary agent).  Body is the prompt template.
- [ ] Placeholders in the body:
  - ``$ARGUMENTS`` — everything after the command verb as a
    single string
  - ``$1``, ``$2``, … — positional args
  - ``@path`` — substitute the contents of ``path`` (reject
    absolute paths and paths outside the repo unless the path
    is allowed by ``external_directory`` permission)
  - ``` !`shell cmd` ``` — run the shell command at expansion
    time and substitute its stdout.  Must flow through the
    Phase 68.2 permission layer so an unsafe command is
    blocked or asked about.
- [ ] Catalogue the loaded commands in
  ``src/cantrip/agent/slash_commands.py``'s registry so the
  Phase 61 autocomplete and help text pick them up for free.
- [ ] Document in ``docs/docs/howto-custom-commands.html`` with
  a working example (``/relation-check <charm>`` that runs
  ``juju show-unit`` and feeds the output back into the agent).
- [ ] ``tests/unit/test_custom_commands.py`` — frontmatter
  parse, placeholder substitution, repo-beats-user precedence,
  shell and file-ref expansion paths, permission gate
  respected.

### 68.4 Medium — Plan mode

- [ ] ``/plan`` and ``/build`` slash commands toggle session
  mode.  Default on startup is ``build`` (current behaviour).
  ``plan`` mode is sticky for the session.
- [ ] Plan mode implementation: enforce a narrow tool allowlist
  (``fs_read``, ``glob``, ``grep``, ``git_log``, ``git_diff``,
  Juju read-only tools, websearch, webfetch).  Everything else
  returns a tool-refused result with a clear "plan mode —
  switch to /build to execute" message.
- [ ] Reuse the Phase 68.2 permission layer rather than
  inventing a parallel gate — plan mode is just a stricter
  permission set pushed onto the stack for the duration.
- [ ] Status bar shows the current mode; plan mode uses a
  distinct theme colour so the user never mistakes one for the
  other.
- [ ] In plan mode, the agent's summary includes an explicit
  "Proposed changes" section listing file edits and commands
  it *would* run.  Flipping to ``/build`` re-sends that summary
  as context so the agent doesn't re-plan from scratch.
- [ ] Document in ``docs/docs/howto-plan-mode.html``.

### What this phase is *not*

- Not a replacement for Phase 46 hooks or Phase 49 subprocess
  sandboxing.  Hooks run external policy code; permissions
  declare policy inline; sandboxing is a kernel-level
  backstop.  All three layer.
- Not a conversation-branching feature.  That's Phase 67.1 —
  they are complementary (67.1 rewinds dialogue; 68.1 rewinds
  files).
- Not a JS/TS plugin runtime.  68.3 opens the door for user
  commands in markdown; a programmable plugin layer is a
  separate and much larger question.
- Not ACP / LSP.  Tracked elsewhere.
- Not "match OpenCode's UX".  Cantrip stays charm-focused; we
  cherry-pick the guardrails that fit.

**Exit criteria:** (a) ``/undo`` restores files to the state
before the last user turn and walks back further on repeat;
(b) ``permissions.yaml`` decides allow/ask/deny for every tool
call, with per-agent overrides and a documented rules-transfer
from OpenCode; (c) a markdown command in ``.cantrip/commands/``
shows up in ``/help``, autocompletes, and runs with
``$ARGUMENTS`` and file/shell interpolation; (d) ``/plan``
switches the session into a read-only stance with a coloured
status indicator and produces a concrete "Proposed changes"
summary that ``/build`` can resume from.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Snapshots (68.1) | Phase 14 (transcript), Phase 30 (git tools), Phase 44 (worktrees) | Composes with 67.1 — 67.1 rewinds messages, 68.1 rewinds files |
| Permissions (68.2) | Phase 46 (hooks order), Phase 49 (sandbox), Phase 64 (CONFIRM UX) | Sits between 46 and 49; reuses 64 for the ``ask`` prompt |
| Custom commands (68.3) | Phase 61 (slash autocomplete), 68.2 (permission gate on ``!`` and ``@``) | Loader independent; permission integration needs 68.2 landed |
| Plan mode (68.4) | 68.2 | Implemented as a permission preset, not a parallel code path |

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

### 69.1 High — Ralph Loop: bounded iterate-until-green

- [ ] Add a ``ralph`` config block to the existing session /
  run configuration with ``max_iterations`` (default 0 =
  disabled; ``-1`` = unlimited matching Kimi semantics) and
  ``convergence``:  a short string the agent must emit to
  declare the loop complete (default ``STOP``).
- [ ] Integrate at the *outer* loop boundary: after the work
  queue drains and ``make check`` + integration tests have
  been attempted, if a Ralph goal is active and neither the
  convergence signal nor the iteration cap has been reached,
  re-seed the queue from the original goal prompt plus a
  short "last iteration's results" summary and run again.
- [ ] Convergence detection: if two consecutive iterations
  produce the same test outcome, same failing test set, and
  the agent makes no file edits, surface a "Ralph stalled"
  event and exit the loop — don't burn tokens on no-ops.
  This mirrors what Kimi's convergence detection guards
  against.
- [ ] Wire into ``cantrip run --print`` (Phase 67.3) as
  ``--ralph N`` so unattended runs can iterate without
  prompting.  Interactive TUI gets ``/ralph <N>`` to enable
  mid-session.
- [ ] Emit ``ralph_iteration_started`` / ``ralph_converged`` /
  ``ralph_stalled`` / ``ralph_exhausted`` events so the TUI
  status bar and transcript audit trail show iteration N/M.
- [ ] ``tests/unit/test_ralph_loop.py`` — happy-path
  convergence, iteration cap trip, stall detection, re-seeding
  preserves the original user goal verbatim (don't corrupt
  the prompt across iterations).

### 69.2 High — ``/yolo`` and ``--yolo`` unattended mode

- [ ] ``--yolo`` / ``--auto-approve`` / ``-y`` flag on the CLI
  (both top-level and on the ``run`` subcommand) globally
  suppresses ``ask`` → CONFIRM prompts for the session.  Any
  rule that resolves to ``deny`` still blocks.
- [ ] ``/yolo`` slash command toggles the mode mid-session.
  When enabling, the TUI shows a prominent banner
  (``YOLO MODE — confirmations off``) in the same theme
  colour as plan mode (68.4) but distinct, so the state is
  unmistakable.
- [ ] Per-call overrides survive yolo: a tool that the
  Phase 68.2 config marks ``deny`` stays denied.  Only the
  ``ask`` outcomes flip to auto-allow.  Document the escape
  hatch explicitly — the point is CI runs, not a footgun.
- [ ] Audit log: every auto-approval emits a
  ``permission_auto_approved`` event with the rule that
  would otherwise have prompted.  Phase 14's transcript
  captures it.
- [ ] Document in ``docs/docs/howto-unattended.html`` (new
  page) alongside the Phase 67.3 print-mode guidance — both
  are pieces of the same "run Cantrip in CI" story.

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

### 70.2 High — Oracle: on-demand second-opinion model

- [ ] New primary-agent tool ``oracle_consult(question: str,
  context_hint: str = "")``.  When invoked, it spins up a
  one-shot provider call on a user-configured "oracle" model
  (default ``claude-opus-4-7`` with reasoning on, overridable
  via ``settings.oracle_model``), injects a compact context
  bundle (active task, last N messages, the question), and
  returns the raw answer plus token/cost accounting.  No
  tools are given to the oracle call — it's a pure reasoning
  query.
- [ ] The oracle call *does not* enter ``state.messages`` on
  the main session — it returns a tool result like any other
  tool, so the main context stays focused.  The transcript
  (Phase 14) captures the full oracle prompt+response as an
  annotated side event so nothing is lost for audit.
- [ ] Per-turn budget: a ``max_oracle_calls_per_turn`` config
  (default 1) and a ``max_oracle_cost_per_session`` cap
  (default $2).  Exceeding either returns a tool error the
  main agent sees and explains in its summary.  Avoids the
  "agent spams the expensive model" failure mode.
- [ ] Distinct from Phase 47 (best-of-N racing) and ``/arena``
  (A/B compare): Oracle is a *one prompt, one answer,
  continue* pattern.  Document the three in
  ``docs/docs/explanation-multi-model.html`` so users know
  which to reach for.
- [ ] Prompt guidance in ``src/cantrip/agent/prompts/system.py``
  tells the primary agent when to consult the oracle: charm
  architecture choices, security-relevant design, library
  vs. custom-code trade-offs, reactive-vs-ops migration
  heuristics.  Not: "what's the syntax of X" (docs do that
  for free).
- [ ] ``tests/unit/test_oracle.py`` — budget enforcement,
  transcript recording, no main-context contamination,
  stubbed provider so tests don't cost real money.

### 70.3 Medium — Glob-conditional guidance frontmatter

- [ ] Extend the loader for ``AGENTS.md`` / ``CLAUDE.md`` and
  Phase 33 skill frontmatter to recognise a ``globs:`` field.
  Accept a list of globs; guidance is included in the prompt
  only when at least one current-turn file path matches.
- [ ] "Current-turn file path" = the active task's file
  context (charm source files touched, files mentioned in
  the user message, files the agent has read in this turn).
  Define the predicate precisely in ``design/PROMPTS.md``.
- [ ] Backwards-compatible default: guidance without a
  ``globs:`` key stays unconditional (current behaviour).
- [ ] Examples shipped in ``AGENTS.md`` and in the charming
  skill library:
  - ``globs: [metadata.yaml, charmcraft.yaml]`` on the
    metadata-authoring guidance
  - ``globs: [tests/integration/**]`` on the Jubilant /
    no-harness reminder
  - ``globs: ["src/charm.py", "src/**/charm.py"]`` on the
    lifecycle-event guidance
- [ ] Observability: the transcript records which globs
  matched and which guidance blocks therefore loaded, so
  users can audit "why did this skill fire?".
- [ ] ``tests/unit/test_conditional_guidance.py`` — match,
  non-match, multiple-glob-one-match, backwards-compat,
  transcript annotation.
- [ ] Document in ``design/PROMPTS.md`` and in the skill
  authoring reference under ``design/SKILLS.md``.

### 70.4 Medium — Prompt-based review checks

- [ ] New file type: ``.cantrip/checks/*.md`` (repo) and
  ``~/.config/cantrip/checks/*.md`` (user).  YAML frontmatter:
  ``name``, ``description``, ``severity`` (low / medium /
  high / critical), ``globs`` (optional; scope to matching
  files), ``tools`` (optional; limit which tools the check
  subagent can call, defaults to read-only).
- [ ] Checks run during the review phase (Phase 10 existing-
  charm improvement, Phase 17 acceptance testing, and any
  user-invoked ``/review``) as prompt-driven subagent
  queries: each check is one LLM call against the matching
  files, returning ``{pass | fail, severity, message,
  evidence}``.
- [ ] Distinct from ``charmlint`` (Phase 24, deterministic
  AST rules): Checks handle judgment-based rules — "is the
  upgrade path coherent?", "does the charm narrative match
  what the code does?", "are action names user-friendly?".
  Document the boundary in ``design/CHECKS.md`` (new) so
  authors know which mechanism fits their rule.
- [ ] Precedence: repo checks override user checks with the
  same ``name``.  Never silently replace a built-in — surface
  a diagnostic so a team can see they've shadowed a default.
- [ ] Ship three built-in checks as examples: charm README
  coherence, action ergonomics, relation-data hygiene.
  Seed more via the Phase 34 Code Quality Skills work.
- [ ] Output aggregated into a single review report (reusing
  the Phase 24 text/JSON reporter shape) so charmlint output
  and Checks output share one summary view.
- [ ] ``tests/unit/test_prompt_checks.py`` — frontmatter
  parse, glob scoping, severity propagation, stubbed-LLM
  pass/fail paths, precedence rules.

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

## Phase 71: Aider-Inspired Engineering Hygiene — Repo-Map, Architect/Editor, Commit Discipline, Edit Loop

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

### 71.1 High — Repo-map with graph-ranked symbols

- [ ] New subsystem under ``src/cantrip/repomap/`` that parses
  a charm repo with ``tree-sitter`` (Python, YAML, TOML,
  Rockcraft/Charmcraft YAML via the generic YAML parser,
  plus Markdown for hook scripts) and extracts class,
  function, and top-level config-key symbols with their
  signatures.  Use the existing ``tree-sitter-languages``
  Python bindings — don't build our own parser.
- [ ] Build a reference graph: edges run from callers to
  callees, from config keys to their consumers, and from
  ``metadata.yaml`` interface names to the charmlibs that
  provide them.  Rank nodes with a PageRank pass (NetworkX
  is already available or trivial to add).  Cache to
  ``.cantrip/repomap.json``; invalidate on file mtime
  changes.
- [ ] Render as a compact text block (symbol + one-line
  signature, grouped by file) fitting a configurable token
  budget (default 1500 for charm-sized repos; Aider's 1000
  default is tuned for larger codebases but charms pull in
  charmlib interfaces and dashboards worth indexing).
- [ ] Inject into the system prompt on every turn, *under*
  the Phase 32 planner context so the agent sees the map
  consistently.  When a file is in the chat, its full text
  takes precedence — no need for a map entry to duplicate
  what's already in context.
- [ ] ``/map`` slash command prints the current map;
  ``/map-refresh`` forces a rebuild.  Transparency for
  "what does the agent think this repo looks like?"
- [ ] Dynamic sizing: when the chat context is tight
  (Phase 40 compaction threshold approaching), shrink the
  map budget.  When the chat is fresh, allow it to expand.
  Mirror Aider's behaviour.
- [ ] ``tests/unit/test_repomap.py`` — parse a fixture charm,
  assert symbol extraction, assert ranking order stable for
  a known graph, assert cache invalidates on file change.

### 71.2 High — Architect / Editor two-model split

- [ ] New session mode ``architect`` alongside the Phase 68.4
  plan/build modes.  In architect mode, every agent turn
  runs in two phases:
  1. *Architect pass* on the configured main model
     (``settings.architect.model``, default the session's
     current model): emits a structured proposal in plain
     prose — "change X in file Y because Z", no diffs.
  2. *Editor pass* on the editor model
     (``settings.architect.editor_model``, default
     ``claude-haiku-4-5`` or the provider's cheapest edit-
     capable model): consumes the architect's proposal plus
     the cited files and emits the concrete
     ``fs_edit`` / ``fs_write`` tool calls.
- [ ] ``/architect`` slash command toggles the mode.  CLI
  flag ``--architect`` sets it for the session.
- [ ] Cost accounting already splits by model name
  (``src/cantrip/cli.py`` ~line 581); ensure both passes
  surface in the per-model breakdown.  Transcript
  (Phase 14) records both passes as separate turn events so
  the architect's reasoning is auditable.
- [ ] Fall-through: if the editor model returns an
  unapplyable patch twice in a row, escalate that one turn
  back to the architect model as the editor.  Avoids a
  stuck loop where a weak model can't parse the proposal.
- [ ] Document the cost-vs-quality trade-off in
  ``docs/docs/howto-architect-mode.html``.  Compare to
  Phase 70.2 Oracle (on-demand one-shot) and Phase 47
  best-of-N (racing).
- [ ] ``tests/unit/test_architect_mode.py`` — stubbed two-
  model run emits correct tool calls, fall-through on
  repeated editor failure, cost tracked per pass.

### 71.3 Medium — Auto-commit-per-turn with dirty-commit separation

- [ ] ``settings.git.auto_commit`` (default true) — after
  each turn that made file edits, stage the changed files
  and commit with a message generated by the Phase 67.2
  light provider (``resolve_light_provider``) from the diff
  plus the user message.  Co-author line ``Co-Authored-By:
  Cantrip <noreply@canonical.com>`` matches the existing
  convention.
- [ ] Dirty-commit separation: before the agent touches
  anything, if ``git status`` shows uncommitted changes in
  files Cantrip is about to edit, commit those first with a
  message like ``chore(pre-cantrip): save in-progress work``.
  User's work stays distinct from the agent's.  Attribution
  only on committer (not author) in this pre-commit.
- [ ] ``/undo`` (new alias, separate from Phase 68.1 snapshot
  undo) runs ``git revert --no-commit`` of the last Cantrip
  commit.  Document the relationship: 68.1 is for file
  changes made *without* commits (granular, turn-level);
  71.3 ``/undo`` is for reverting a completed Cantrip
  commit.  Both coexist — different use cases.
- [ ] Opt-out: ``settings.git.auto_commit: false`` restores
  current batched-commit behaviour for users who dislike
  the per-turn cadence.
- [ ] ``tests/unit/test_autocommit.py`` — agent-only commit
  flow, dirty-separation flow, opt-out, commit-message
  generation hits the light provider, ``/undo`` reverts
  only Cantrip-authored commits.

### 71.4 Medium — Per-edit lint/test feedback loop

- [ ] After each ``fs_edit`` / ``fs_write`` that touches a
  Python file, run ``ruff check --output-format=json`` and
  ``ty check --output-format json`` on the touched paths
  (not the whole repo — incremental).  If either reports
  errors, feed them back as a tool result the agent can
  react to before the turn completes.
- [ ] For YAML files (``metadata.yaml``, ``charmcraft.yaml``,
  ``actions.yaml``, etc.), run ``charmlint`` on the touched
  files (Phase 24).  Same feedback path.
- [ ] For charm test files (``tests/**/*.py``), optionally
  run the touched test file with ``pytest --collect-only``
  to catch import errors cheaply before a full run.
- [ ] ``settings.auto_lint`` (default true) and
  ``settings.auto_test.collect_only`` (default true) —
  escape hatches.  A failing lint doesn't block the turn;
  the agent sees the diagnostics and may or may not
  choose to fix, same as Aider's UX.
- [ ] Distinct from Phase 12 red/green (goal-level test
  gating) and Phase 69.1 Ralph Loop (outer iterate-until-
  green).  This is a *within-turn* quality signal.
- [ ] ``tests/unit/test_auto_lint.py`` — touching a Python
  file surfaces ruff errors; touching ``metadata.yaml``
  surfaces a charmlint warning; opt-out skips the run.

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

- [ ] ``@problems`` context provider (registered in 72.2)
  runs, on expansion:
  - ``ruff check --output-format=json .`` (or just the
    charm's ``src/`` and ``tests/`` to keep it cheap)
  - ``ty check --output-format json .``
  - ``charmlint --format json`` (from Phase 24)
  and emits a compact block grouping issues by severity and
  file, capped at 1500 tokens (longer reports get
  summarised with a "N more issues suppressed; run
  ``cantrip lint`` for the full list").
- [ ] Caching: run results cached for 30 seconds so
  repeated ``@problems`` in the same turn doesn't re-run
  the linters.
- [ ] ``/diagnostics`` slash command for the same output
  without an inline context-provider mention — a focused
  "what's the state of things?" view.
- [ ] Autonomous-loop integration: when the planner
  (Phase 32) starts a new BUILD task, it calls the same
  diagnostics aggregator and includes the result in the
  task briefing — so the agent starts knowing what's
  broken.  Different entry point, same output format.
- [ ] ``tests/unit/test_diagnostics_context.py`` — JSON
  parse per linter, aggregation, truncation, cache TTL.

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

- [ ] New per-call option ``response_schema: dict`` on the
  primary-agent turn API and every subagent-dispatch call.
  When set, the provider is asked to return output
  conforming to the JSON schema (using Anthropic's
  structured output, OpenAI's ``response_format``, or the
  equivalent per provider).  Validation runs in Cantrip
  regardless — provider-native enforcement is an
  optimisation, not a security boundary.
- [ ] Built-in schemas shipped for common outputs:
  - ``cantrip.schemas.planner_briefing`` — what the
    planner returns to task dispatch
  - ``cantrip.schemas.check_result`` — Phase 70.4 Checks
    output (``pass | fail``, severity, evidence, message)
  - ``cantrip.schemas.oracle_answer`` — Phase 70.2 Oracle
    return shape
  - ``cantrip.schemas.acceptance_report`` — Phase 17
    acceptance-test report
- [ ] Recipes (73.1) surface the primitive via their
  ``response`` block.  Direct tool callers use
  ``response_schema=`` on the provider call.
- [ ] On validation failure after one provider retry,
  surface the malformed output plus the schema to the
  agent and ask for correction — a tool-result-shaped
  error the agent can react to.
- [ ] Document in ``docs/docs/reference-response-schemas.html``.
- [ ] ``tests/unit/test_structured_response.py`` — happy
  path, schema violation retry, final-failure shape,
  provider-native vs. Cantrip-side validation parity.

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

## Phase 74: Populated Charm Documentation — From Scaffold to Substance

**Goal:** Cantrip already generates a Diátaxis docs scaffold for
every charm it builds (``GenerateDocsTool`` in
``src/cantrip/agent/tools/publishing.py:1115``, archived under
Phase 7).  The output is a complete Sphinx + canonical-sphinx
build with ``tutorial/``, ``how-to/``, ``reference/``,
``explanation/``, ``Makefile``, ``conf.py``,
``.readthedocs.yaml``, and ``.custom_wordlist.txt`` — a
publishable site on day one.

The gap is *substance*: most pages are templated stubs derived
from ``charmcraft.yaml`` metadata, the tutorial uses a generic
``juju deploy <charm>`` invocation rather than the deploy
sequence we *know* works because we just ran it, the
explanation/architecture page doesn't capture the design
decisions the agent made during the build, and there's no
troubleshooting page even though the agent has a complete
record of every error it hit and how it resolved it.

Phase 13 (archived ✓) generates ``DEMO.md``, ``TUTORIAL.md``,
and ``architecture.md`` at the *charm root* via Showboat.
These don't currently flow into the ``docs/`` tree, so a charm
ends up with two parallel documentation surfaces.  74.1
bridges them; 74.2–74.4 mine the agent's own audit trail
(transcripts, acceptance-test runs, debug history) to fill
the rest.

Four candidates, in rough priority order:

1. **Bridge Phase 13's root files into the ``docs/`` tree.**
   ``TUTORIAL.md`` content belongs in
   ``docs/tutorial/getting-started.md``; ``architecture.md``
   in ``docs/explanation/architecture.md``; ``DEMO.md``
   command sequences in a new
   ``docs/how-to/deploy-and-verify.md``.  Today the
   scaffold's templated stubs co-exist with — and contradict
   — the Showboat-captured root files.  Bridging them means
   the docs site reflects what the agent actually did, not
   a generic placeholder.
2. **Populate tutorial and how-to with captured commands +
   output from Phase 17 acceptance tests.**  Acceptance
   testing (Phase 17, archived ✓) runs Jubilant integration
   tests against a real model.  Each test step is a
   command-output pair we can drop into a how-to page
   verbatim.  Tutorial gets the canonical happy-path:
   bootstrap → deploy → integrate → action → status.  How-to
   pages get focused recipes per relation/action.  All with
   real captured output, not placeholder stubs.
3. **Populate ``explanation/architecture.md`` from the
   transcript's design decisions.**  The transcript
   (Phase 14) records every architectural turn — "we chose a
   sidecar Pebble layer because the upstream OCI image
   doesn't include the metrics endpoint".  Mine the
   research-phase tasks (Phase 5) and the build-phase
   commits for the *why*, render as a chronological design
   log with citations to the transcript turn IDs.
   Distinct from the metadata-driven reference pages: this
   is the human-readable rationale.
4. **Generate a ``troubleshooting.md`` from the agent's
   debug history.**  Every time the agent hit an error
   during build/test and recovered, that's a candidate
   "common pitfall" entry: the symptom, the cause, the fix.
   Filter to errors that recurred or required non-trivial
   diagnosis (skip "typo, fixed it") so the page stays
   useful.  Lives at ``docs/how-to/troubleshooting.md``.

Three candidate ideas are explicitly **out of scope or
deferred**:

- **API-doc generation from the charm's Python source.**
  The ``ops`` library has its own published reference; the
  charm's classes are typically thin wrappers.  Sphinx
  autodoc is a one-flag addition to ``conf.py`` if a charm
  team wants it — not worth a roadmap bullet.
- **Charmhub listing copy as a separate document.**  The
  long-form description that lands on Charmhub is the same
  copy as the README's intro paragraph; ``GenerateReadmeTool``
  already produces it.  No second generator needed.
- **Multi-version docs.**  Charms publish to Charmhub
  channels (``latest/edge``, ``2/stable``…), but doc-
  versioning is a Sphinx/readthedocs concern.  Defer until
  a real demand surfaces.

### 74.1 High — Bridge root files into the Diátaxis tree ✓

- [x] ``generate_docs_scaffold`` gained a ``root_files``
  keyword.  When the caller hands it the contents of
  ``TUTORIAL.md`` / ``DEMO.md`` / ``architecture.md``, those
  override the metadata-derived stubs at
  ``docs/tutorial/getting-started.md`` and
  ``docs/explanation/architecture.md``, and add a new
  ``docs/how-to/deploy-and-verify.md`` page (with the
  how-to ``index.md`` toctree picking it up after
  ``deploy``).  ``GenerateDocsTool.execute`` is the only
  caller that reads from disk, keeping the scaffold
  function pure / unit-testable.
- [x] Bridging rewrites the first H1 to a docs-shaped
  title (``# Get started with <display-name>`` /
  ``# Deploy and verify <display-name>`` / ``# Architecture``)
  via ``_replace_first_h1`` so the Sphinx toctree
  resolves.  Markdown links and image references are
  rewritten by ``_rewrite_root_link``: cross-references
  between bridged files become ``../<other>`` links
  (``DEMO.md`` → ``../how-to/deploy-and-verify``); other
  root-relative paths get ``../../`` prepended to climb
  out of ``docs/<dir>/``; absolute URLs, anchors, and
  paths already starting with ``../`` are left alone.
- [x] After bridging, the original root file is replaced
  with a one-line stub (``# Moved`` + a link to the
  docs/-tree home) so existing in-repo links keep
  resolving.  Re-runs check the file content for the
  ``# Moved`` header before bridging, so the stub isn't
  fed back into ``docs/`` on subsequent runs.  The
  CONFIRM-prompt-and-delete variant is left for a
  follow-up — the simpler stub pattern keeps the bridge
  reversible and avoids dragging the Phase 64 CONFIRM
  flow into a publishing tool.
- [x] ``GenerateReadmeTool`` now prefers
  ``docs/tutorial/getting-started.md`` /
  ``docs/how-to/deploy-and-verify.md`` /
  ``docs/explanation/architecture.md`` when those exist,
  with the legacy root-file links kept as a fallback so
  charms that haven't run the bridge yet are
  unchanged.  Mixed states (one bridged, one not) are
  handled link-by-link.
- [x] ``tests/unit/test_docs_bridge.py`` covers all five
  surfaces — 38 tests total: ``_replace_first_h1`` (5),
  ``_rewrite_root_link`` (7), ``bridge_root_file`` (8),
  ``generate_docs_scaffold`` with ``root_files`` (9),
  ``GenerateDocsTool.execute`` end-to-end (6), and
  ``GenerateReadmeTool`` link-preference (4).
  ``tests/unit/test_publishing.py`` (72 cases) still
  passes — the ``root_files`` parameter is keyword-only
  with a default of ``None`` so existing callers are
  unaffected.

### 74.2 High — Populate tutorial and how-to from acceptance-test runs ✓

- [x] ``generate_docs`` now reads ``demo/juju-status.txt``,
  ``demo/actions/*.json`` (Phase 13's captured artefacts) and
  ``ACCEPTANCE.md`` (Phase 17's summary) via the new
  ``load_acceptance_artefacts()`` helper.  Two source surfaces
  combined cover the "test transcript" the roadmap called for:
  Phase 13's demo bundle has the rich captured data (sanitised
  ``juju status`` text, per-action JSON outputs); Phase 17's
  ``ACCEPTANCE.md`` is treated as a "did acceptance run"
  signal.  No new sidecar storage — both already land on disk.
- [x] When the artefact bundle is populated,
  ``generate_docs_scaffold`` overrides three pages with
  artefact-derived content via ``_populate_tutorial_from_artefacts``,
  ``_populate_actions_from_artefacts``, and
  ``_populate_deploy_and_verify_from_artefacts``:
  - ``docs/tutorial/getting-started.md`` — the canonical happy
    path with real captured ``juju status`` excerpt and the
    first action's captured output.
  - ``docs/how-to/deploy-and-verify.md`` — the same deploy
    sequence as a focused recipe (no narrative framing); also
    added to the how-to ``index.md`` toctree.
  - ``docs/how-to/actions.md`` — one section per action with
    the captured JSON output embedded under the
    ``juju run <unit> <action>`` invocation.
  Per-relation pages (``docs/how-to/<relation-name>.md``) are
  deferred — the existing ``docs/how-to/integrate.md`` already
  lists every relation with its ``juju integrate`` invocation,
  and per-relation pages would balloon the toctree without a
  corresponding richness payoff.  Re-open if/when there's
  per-relation captured output to embed.
- [x] When acceptance hasn't run, each affected page
  (``docs/tutorial/getting-started.md``, ``docs/how-to/deploy.md``,
  ``docs/how-to/integrate.md``, ``docs/how-to/actions.md``) gets a
  one-line HTML comment prepended noting the content is
  templated until tests run.  Bridged root files (74.1) still
  win over both — the ordering is
  ``templated stub  <  artefact-derived  <  bridged root files``.
- [x] Sanitisation is implemented in ``sanitise_capture()``:
  IPv4 addresses → ``<unit-ip>`` (octets restricted to 0–255 so
  version strings like ``999.999.999.999`` don't trip it),
  UUIDs → ``<model-uuid>``, ``*.svc.cluster.local`` hostnames
  → ``<svc-fqdn>``, ``sha256:…`` digests → ``<image-sha256>``.
  Sanitisation runs at load time so embedded content is always
  safe.  Phase 16's ``sanitise_body`` is targeted at
  secrets/charm paths and intentionally not reused — the
  acceptance-capture sanitiser handles cluster-shape data.
- [x] ``tests/unit/test_docs_from_acceptance.py`` — 25 tests
  covering ``sanitise_capture`` (6), ``load_acceptance_artefacts``
  (7), ``generate_docs_scaffold`` artefact population (8 — stub
  marker, tutorial replacement, deploy-and-verify, actions
  with captured output, toctree inclusion, bridge precedence,
  and the no-status-block edge case), and ``GenerateDocsTool``
  end-to-end (4 — no artefacts, demo artefacts drive tutorial,
  ACCEPTANCE.md alone signals populated, bridged tutorial wins
  over artefacts).  Existing 110 publishing + bridge tests
  still pass — the ``acceptance`` parameter is keyword-only
  with a default of ``None``.

### 74.3 Medium — Architecture explanation from transcript-extracted decisions ✓

- [x] ``ExtractDesignDecisionsTool`` (``extract_design_decisions``)
  added to ``src/cantrip/agent/tools/publishing.py`` and
  registered in the agent's tool list.  Reads the
  ``decisions`` table from the ``.cantrip`` SQLite store the
  agent already populates during the design phase
  (substrate, charm path, Charmhub recommendations).
  Optional ``db_path`` argument lets the tool target a
  sidecar store; defaults to ``<path>/.cantrip``.
  Build-phase ``feat:`` / ``refactor:`` commit mining and
  Phase-70.2 oracle-consult turns are deferred — the
  ``decisions`` table is the authoritative shipping
  source.  Re-open this part of the phase if/when there's
  a concrete request for the extra heuristics.
- [x] ``format_decision_log`` renders chronological
  ``### N. <Type>: <Choice>`` blocks with **Decision**,
  **Recorded**, **Citation**, and **Rationale** sub-fields.
  Empty inputs produce a placeholder explaining the
  section will fill in as decisions land — keeps the page
  well-formed when the tool runs early.  Decision-type
  labels are humanised (``charm_path`` → ``Charm Path``).
  Ordering uses ``timestamp, id`` so chronologically
  ordered output survives clock-skew on equal timestamps.
- [x] Intro fallback ladder via ``_resolve_architecture_intro``:
  ``docs/explanation/_intro.md`` wins outright; an
  existing ``architecture.md`` keeps everything above the
  ``<!-- cantrip-decisions-start -->`` marker; an
  ``architecture.md`` without the marker is treated as
  fully user-authored and preserved verbatim;
  otherwise the scaffold's mermaid-diagram intro is
  generated from ``charmcraft.yaml``.  The auto-generated
  decision log lands below the marker each run, so
  re-runs only refresh the decisions section.
- [x] ``tests/unit/test_extract_decisions.py`` — 22 tests
  covering ``_read_decisions`` (4: missing DB, missing
  table, chronological order, preserved fields),
  ``format_decision_log`` (4: placeholder, ordered output,
  rationale + citation, missing reason),
  ``_resolve_architecture_intro`` (4: ``_intro.md`` wins,
  marker preserves above content, marker-less arch
  preserved verbatim, scaffold fallback),
  ``_compose_architecture_page`` (3: marker placement,
  empty decisions still include marker, empty intro
  default heading), and ``ExtractDesignDecisionsTool``
  end-to-end (7: missing dir, no DB writes placeholder,
  decisions render, ``_intro.md`` preserved across run,
  re-run only refreshes below marker, hand-authored
  page preserved with marker appended, ``db_path``
  override).  Existing 4844 tests still pass.

### 74.4 Medium — Troubleshooting page from debug history ✓

- [x] ``ExtractTroubleshootingTool`` (``extract_troubleshooting``)
  added to ``publishing.py``.  Walks ``messages`` and
  ``subagent_messages`` chronologically (one stream at a
  time so diagnoses don't bleed across subagent task
  boundaries) and looks at every assistant message whose
  ``tool_results`` carry ``is_error=true``.  Each error
  result becomes a ``TroubleshootingEntry`` carrying the
  symptom (wrapper-stripped tool output, excerpted to 12
  lines), the agent's next text reply within five turns
  (the diagnosis), and the next successful tool call
  within eight turns (the resolution).  A
  ``<tool_result>`` envelope stripper handles the wrapper
  ``core.py`` adds around tool results, so the symptom
  excerpt is the actual error text.
- [x] Filter: errors that match a non-general category are
  always kept; general-bucket errors with fewer than
  ``_MIN_DIAGNOSTIC_LINES`` (5) of content are dropped as
  typo-shaped.  This catches the "drop typos" case the
  roadmap calls for without relying on a separate
  classifier.
- [x] Categoriser via ``_categorise_error``: regex over
  stderr keywords across eight buckets (image,
  observability, secret, relation, hook, network,
  storage, general).  Order is charm-stack-specific
  patterns first (image / observability / secret /
  relation / hook) so an error mentioning a stack
  component lands in the bucket the operator looks at
  first; transport-layer patterns (network / storage)
  come after.  No LLM call — pure regex.
- [x] ``format_troubleshooting_page`` groups entries by
  category in stable display order
  (``_CATEGORY_ORDER``) and emits ``### N. <symptom>``
  blocks with **Symptom** / **Cause** / **Resolution** /
  **See also** sub-fields (Cause and Resolution omitted
  when null so a minimal entry stays clean).  Empty
  buckets are skipped from the output entirely.
- [x] Charm-author intro preserved across re-runs via
  ``_resolve_troubleshooting_intro`` mirroring 74.3:
  marker in ``troubleshooting.md`` → preserve content
  above; no marker but file exists → preserve verbatim
  and append the marker; no file → default
  ``# Troubleshooting`` heading.  No CONFIRM dependency
  on Phase 64 — the marker pattern keeps the bridge
  reversible without dragging the confirmation flow into
  a publishing tool.
- [x] ``_ensure_troubleshooting_in_toctree`` patches
  ``docs/how-to/index.md`` to include ``troubleshooting``
  before the closing toctree fence when the index exists
  and doesn't already list the page.  No-op when the
  index is missing — the next ``generate_docs`` will
  rebuild it.  ``ToolResult.data["toctree_updated"]``
  reports whether the patch fired.
- [x] ``tests/unit/test_extract_troubleshooting.py`` —
  42 tests covering ``_categorise_error`` (13
  parametrised + invariants), ``_strip_tool_result_wrapper``
  (2), ``_read_transcript_pairs`` (7: missing DB, no
  tables, end-to-end pair extraction with diagnosis +
  resolution, trivial-general drop, short-categorised
  keep, long-general keep, subagent walk, non-error
  ignored), ``format_troubleshooting_page`` (5),
  ``_resolve_troubleshooting_intro`` (3),
  ``_ensure_troubleshooting_in_toctree`` (3), and
  ``ExtractTroubleshootingTool`` end-to-end (7: missing
  dir, no DB → placeholder, grouped output, intro
  preserved, marker-less existing page, toctree amended,
  ``db_path`` override).  All 4866 prior tests still
  pass.

### What this phase is *not*

- Not a redesign of the Diátaxis scaffold.  74 builds *on*
  ``generate_docs_scaffold`` (``publishing.py:680``); the
  layout and Sphinx config stay as they are.
- Not a replacement for ``GenerateReadmeTool``.  README is
  the project-root entry point; the docs site is the
  longer-form companion.  74.1 makes them point at each
  other consistently.
- Not API-doc / autodoc.  Out of scope above.
- Not a docs-writing LLM workflow with no charm context.
  Every populated page is grounded in something Cantrip
  *did* — an acceptance test, a design decision, a
  resolved error.  No hallucinated tutorials.
- Not a Charmhub-publishing surface.  Publishing the docs
  site to readthedocs / Charmhub is the user's choice;
  Cantrip generates the source tree and stops there.

**Exit criteria:** (a) running ``generate_docs`` after
Phase 17 acceptance tests have completed produces a
tutorial whose every command is one the agent actually
ran and whose every output block is what the agent
actually saw; (b) the ``docs/`` tree and the root
``TUTORIAL.md`` / ``DEMO.md`` / ``architecture.md`` no
longer disagree; (c) ``docs/explanation/architecture.md``
contains a chronological log of design decisions with
transcript citations; (d) ``docs/how-to/troubleshooting.md``
contains the agent's own resolved-error catalogue,
filtered to non-trivial pairs.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Bridge root files (74.1) | Phase 7 (``generate_docs``), Phase 13 (root files), Phase 64 (CONFIRM for delete) | Plumbing fix; lands first so 74.2–74.4 don't write into a tree that fights with the root files |
| From acceptance tests (74.2) | Phase 17 (acceptance results), Phase 16 (redaction) | Biggest substance win; needs Phase 17 output format documented |
| Architecture from transcript (74.3) | Phase 14 (transcript store), Phase 5 (research-phase task structure), Phase 70.2 (oracle exchange capture) | Mining work over existing data |
| Troubleshooting from debug history (74.4) | Phase 14 (transcript store), Phase 16 (error categorisation if it exists) | Same data source as 74.3, different filter |

---

## Phase 75: Inline Tool Blocks in the Chat

**Goal:** Stop hiding tool execution from the chat.  Today the
agent streams a preamble (``Let me check the file:``), runs a tool
*silently*, then streams the next message.  The user sees a line
that trails off on a colon with no follow-up — it reads like
broken speech.  Render each tool call as a compact block inline
with the chat so the user can see *what just happened* without
opening the transcript.

### 75.1 High — Caption field on ``ToolResult`` ✓

- [x] Added ``caption: str | None = None`` to
  ``cantrip.agent.tools.base.ToolResult``.  Tools that know the
  rich one-line summary of what they did populate it; everything
  else leaves it ``None`` and the agent-loop fallback synthesises
  ``tool_name(preferred_key=value)`` via the new
  ``build_tool_caption(tool_name, arguments, result)`` helper.
- [x] Deviation from the original plan: no per-tool caption
  population *yet*.  The fallback reads the first argument
  matching ``path`` / ``file_path`` / ``command`` / ``cmd`` /
  ``url`` / ``query`` / ``skill_name`` / ``name`` / … (a
  preferred-key list), truncates the value to 60 chars, and
  collapses newlines — covering ~90% of concrete tool shapes
  without touching every tool.  Populating captions is now
  incremental work tools can pick up as they're touched; the
  fallback keeps the chat readable until then.

### 75.2 High — ``TOOL_INVOKED`` UI event ✓

- [x] New ``EventType.TOOL_INVOKED`` on
  ``cantrip.ui.events`` carrying
  ``{tool_name, caption, success, duration_ms, source}``.
  ``source`` is one of ``main`` / ``main-stream`` /
  ``subagent`` so subscribers that care about context (a test
  harness, a filter on the bus) can route accordingly.
  ``duration_ms`` is ``None`` when unmeasured and otherwise an
  integer in milliseconds.
- [x] Emission wired into all three tool-call boundaries:
  ``core.py`` synchronous loop, ``core.py`` streaming loop,
  and ``subagent.py`` gather path.  Fires *after* the tool
  returns — vetoed pre-hook calls surface as ``success=False``
  so a blocked action is visible in the chat, not hidden.
  Subagent emission flows through a new
  ``Subagent.on_tool_invoked`` callback forwarded by
  ``BackgroundExecutor`` and bound on the agent layer so the
  same event bus serves both main-agent and subagent blocks.

### 75.3 High — TUI: render tool blocks ✓

- [x] ``ChatWidget.add_tool_block(caption, success, duration_ms)``
  and a new ``MessageRole.TOOL`` render a compact single-line
  block between chat messages.  Success uses the accent border
  and a ``🔧`` glyph; failure recolours to the error border and
  swaps in ``✗``.  Durations above the 500 ms attention
  threshold (``_TOOL_BLOCK_DURATION_THRESHOLD_MS``) appear
  parenthesised so fast calls don't clutter the chat.
  ``src/cantrip/tui/app.py`` subscribes to ``TOOL_INVOKED`` in
  the same place it subscribes to the memory / status-bar
  events.
- [x] Deviation from the original plan: kept the block inside
  ``MessageWidget`` rather than creating a separate
  ``ToolBlockWidget`` class.  Reusing the existing widget
  pipeline via ``MessageRole.TOOL`` was half the code and
  still leaves the CSS rule (``MessageWidget.tool`` /
  ``MessageWidget.tool-failed``) available for the Phase 76
  copy-chunk work to target.

### 75.4 High — Web: broadcast tool call over WebSocket ✓

- [x] No new ``_broadcast_tool_call`` helper needed: the
  existing wildcard bus forwarder
  (``_make_bus_forwarder``) already translates every
  bus event into a WebSocket message
  ``{type: "tool_invoked", data: <payload>}`` — same shape the
  JS dispatcher case handles.  New ``appendToolBlock`` function
  in ``cantrip.js`` renders the compact block; new
  ``.msg-tool`` / ``.msg-tool-failed`` CSS in ``style.css``
  mirrors the TUI treatment (accent border, muted text, mono
  font, error border on failure).
- [x] Shared rendering vocabulary between TUI and Web: same
  ``🔧`` / ``✗`` glyphs, same 500 ms duration threshold,
  so users moving between surfaces get an identical mental
  model.

### 75.5 Medium — Tests ✓

- [x] ``tests/unit/test_ui_events.py`` — new
  ``TestToolInvokedEvent`` with 4 cases (required fields,
  duration pass-through, subagent source tag, failure
  surfacing as ``success=False``).  The existing
  ``test_event_type_enum_covers_all_factories`` was extended
  so every new event type keeps being covered automatically.
- [x] ``tests/unit/test_agent.py`` — new
  ``TestToolInvokedEvent`` with 3 cases (sync-loop tool call
  emits event with correct payload + caption fallback,
  failure surfaces as ``success=False``, explicit caption
  wins over formulaic fallback).
- [x] ``tests/unit/test_tui.py`` — 4 new cases on
  ``TestTuiWidgets`` covering ``add_tool_block`` render
  (success, failure with ``tool-failed`` class, slow-call
  duration visible, fast-call duration hidden).
- [x] New ``tests/unit/test_tool_caption.py`` — 13 cases on
  ``build_tool_caption`` covering explicit-caption-wins, all
  preferred-key types (path / file_path / command / url),
  fallback to first non-preferred arg, empty / None / whitespace
  values, long-value truncation, newline collapsing,
  quote normalisation.
- [x] No dedicated ``_broadcast_tool_call`` test filed —
  removed the helper as part of the design change above; the
  existing wildcard-forwarder test in
  ``test_ui_events.py`` already exercises the path the
  front-end consumes.

### 75.6 Low — Populate rich captions on high-traffic tools ✓

Phase 75 shipped the framework and the formulaic fallback
(``tool_name(path=src/foo.py)``).  The fallback is readable but
tools can do better: a rich caption carries count / size /
destination information the formulaic shape can't.  This subphase
tracks the work so the improvement doesn't rot — the
exit-criterion categories have landed; remaining tools still
benefit from the fallback and can be filled in as drive-bys.

- [x] File-system tools: ``read_file`` (``"Read 47 lines from
  src/foo.py"``), ``write_file`` (``"Wrote 312 bytes to
  src/bar.py"``), ``edit_file`` (``"Edited src/foo.py (1
  replacement)"``), ``list_directory`` (``"Listed 12 entries in
  src/"``), ``grep`` (``"6 matches for 'HookEvent' across 3
  files"``; collapses to ``"No matches for 'X'"`` on empty),
  ``glob`` (``"4 files matching '*.py'"``).  All six tools
  populate ``ToolResult.caption`` on the success path.
- [x] Charm-tooling: ``charmcraft_pack`` (``"Packed →
  redis.charm (2.1 MB)"`` from the file size on disk),
  ``charmcraft_fetch_libs`` (``"Fetched 4 libs"`` counted
  from ``Fetched library`` lines in stdout, falls back to
  ``"Fetched libraries"`` when the count is zero),
  ``charm_validate`` (``"charm_validate: tests passed, pack
  passed → PASSED"``).
- [x] Git: ``git_clone`` (``"Cloned github.com/foo/bar"`` —
  protocol prefix, ``git@`` user, and trailing ``.git``
  stripped so HTTPS and SSH URLs yield the same caption),
  ``git_commit`` (``"Committed: 'Add a thing'"`` using just
  the first line of the message, truncated at 60 chars),
  ``git_push`` (``"Pushed → origin/main"``, falling back to
  the remote name when no branch is supplied).
- [ ] Shell: ``run_command`` — include exit code and a short
  output summary (first 40 chars, stripped) so a failing
  command shows its error in the caption.  *Deferred* — the
  exit criterion is met without it; pick this up as a drive-
  by next time ``run_command`` is touched.
- [ ] Juju: ``juju_deploy`` (``"Deployed redis to
  dev-model"``), ``juju_config`` (``"Set redis/0
  debug=true"``), ``juju_status`` (``"4 apps, 1 blocked"``),
  ``juju_integrate`` / ``juju_remove_relation``.  *Deferred*
  alongside the shell tool — same drive-by reasoning.
- [ ] Acceptance / test: ``run_charm_tests`` (``"12 passed, 1
  failed"``), ``charm_audit`` (``"2 issues"``),
  ``acceptance_report``.  *Deferred*.
- [x] 18 new tests in ``tests/unit/test_tool_captions.py``
  asserting caption shape across file-system (9), git (5), and
  charm-tooling (4) tools — including stub-driven cases for
  network operations (``git_clone``, ``git_push``) and
  subprocess-mocked cases for the charm tools.

**75.6 Exit criteria:** at least the file-system, git, and
charm-tooling categories populate captions; everything else still
falls back gracefully. ✓ — file-system, git, and charm-tooling
shipped; shell / juju / acceptance categories rely on the
``tool_name(arg=value)`` fallback and will be filled in as
drive-bys.

### What this phase is *not*

- Not a full collapse-by-default UI.  First pass is everything
  visible inline; compacting comes in Phase 76 alongside the
  copy-chunks work.
- Not a replacement for the transcript viewer.  The transcript
  still records the full tool I/O; the chat block is a summary,
  not the authoritative record.
- Not a new rendering engine in the TUI.  Mirror the existing
  system-message widget pattern; no new Textual wizardry.

**Exit criteria:** Every tool call — main-agent and subagent — is
visible in the TUI and Web chat as a one-line block between
messages; successes and failures are colour-distinguished; the
trailing-colon preambles no longer read as broken speech.  Unit
tests cover event emission, caption fallback, and both UI
rendering paths.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Caption field (75.1) | None | ``ToolResult`` dataclass change; every tool call falls back gracefully |
| Event emission (75.2) | Phase 15.1 event bus | Uses existing publisher, adds one event kind |
| TUI block (75.3) | Phase 15.1 event bus, Phase 4.4 TUI widgets | New widget subscribes to bus |
| Web broadcast (75.4) | Phase 15.2 web server | New WebSocket message kind, front-end rendering |
| Tests (75.5) | 75.1–75.4 | Regression cover for the four landing points |

---

## Phase 76: Copy-Friendly Chat — Toad-Inspired

**Goal:** Make it easy to copy chunks of the chat window — a
single agent message, a single tool block, a whole turn.  Today
the TUI relies on the terminal's own copy machinery (``Ctrl+Shift+
C`` in most terminals), which breaks when Cantrip is running
inside a multiplexer or when multiple surfaces are on screen.
Toad (Charm's AI agent) has well-regarded per-block copy
affordances — inspect what they do and adapt what fits.

**This is primarily an investigation phase.**  Ship one concrete
improvement if one reads as obviously right during the review;
otherwise document findings and move on without premature
design.

### 76.1 Research — What Toad does

- [ ] Install / read about Toad's per-block copy behaviour:
  what gestures, what clipboard formats (plain text, Markdown,
  rich), what scope (one message / one turn / selection range).
- [ ] Catalogue the friction points in Cantrip's current
  TUI-copy flow that real users hit (ghost terminal +
  tmux/screen + remote ssh all mangle different bits).

### 76.2 Design — What fits Cantrip

- [ ] Pick the subset of Toad's affordances that maps cleanly
  onto Textual.  Candidates: per-widget copy keybinding;
  visible ``[copy]`` affordance on hover / focus; a ``/copy
  last-message`` / ``/copy last-tool-result`` slash command;
  OSC 52 clipboard escape support for ssh/tmux.
- [ ] Decide the default Markdown-vs-plain-text policy — agent
  messages are typically Markdown, but the user probably wants
  plain text when pasting into Slack vs Markdown when pasting
  into an issue tracker.

### 76.3 Implement — The one thing worth shipping now

- [ ] Ship whichever affordance from 76.2 has the clearest
  win.  If nothing rises above the bar, write up findings in
  ``design/UI.md`` and close the phase without shipping.

**Exit criteria:** Either (a) a concrete copy affordance lands
and is documented, or (b) a written assessment in ``design/UI.md``
explains why the current flow is sufficient and what would
change that.  ``make check`` passes regardless.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Research (76.1) | None | Read-only |
| Design (76.2) | 76.1, Phase 75 (tool blocks as copyable units) | Tool blocks are new copy targets; wait until 75 lands |
| Implement (76.3) | 76.2 | Only if 76.2 surfaces a clear win |

---

## Phase 77: Surface `reasoning_content` From OpenAI-Compatible Models

**Goal:** Capture the ``reasoning_content`` streaming delta that
Kimi K2 (and some other open-weights models) emit alongside the
final ``content``.  Today ``OpenAICompatBase.stream`` only reads
``delta.content`` and silently drops ``delta.reasoning_content``,
so Kimi K2 on Fireworks burns completion tokens on chain-of-
thought that never reaches the user — short ``max_tokens``
budgets appear to return empty replies because reasoning
consumed the budget before any answer was emitted.

This affects any OpenAI-compatible endpoint that uses the
reasoning-delta convention (DeepSeek-R1 family via vLLM, GLM
reasoning variants, possibly MiniMax).  The non-streaming
``complete()`` path has the same gap — it reads
``message.content`` and drops ``message.reasoning_content``.

### 77.1 Capture and expose reasoning ✓

- [x] ``OpenAICompatBase.complete()`` and ``.stream()`` accumulate
  ``reasoning_content`` — the complete path sets
  ``Response.metadata["_thinking_content"]`` and the stream path
  carries accumulated reasoning on the final ``Chunk.metadata``.
  Same key Claude uses for extended thinking so renderers stay on
  one code path.
- [x] TUI: new ``ChatMessage.reasoning`` field;
  ``ChatWidget.add_assistant_message`` and ``set_reasoning``
  accept it; ``MessageWidget._render_body`` prepends a dim italic
  ``💭 thinking`` preamble (Rich-escaped so bracketed reasoning
  can't inject markup).  ``_process_agent_message`` in
  ``tui/app.py`` attaches reasoning after the text stream
  completes by walking the latest assistant message's metadata.
- [x] Web: ``_broadcast_chat`` carries a ``reasoning`` field;
  ``appendMessage`` in ``cantrip.js`` renders it as a collapsible
  ``<details>`` block before the message body; CSS
  (``.msg-reasoning`` / ``.msg-reasoning-body``) gives the block
  muted styling with a custom disclosure triangle.
  ``_messages_with_timestamps`` (used by ``/api/messages``)
  surfaces reasoning from persisted metadata on page reload.

### 77.2 Budget-aware defaults ✓

- [x] Updated the callout in ``docs/src/howto-provider.md`` with
  concrete numbers (``max_tokens=30`` → 30 reasoning tokens +
  empty reply; ~4 096 recommended floor for simple prompts,
  16 000+ for tool-using turns).
- [x] ``OpenAICompatBase._build_request_body`` now honours
  ``thinking_budget`` by raising ``max_tokens`` to at least
  ``thinking_budget + 4096`` (Claude's formula), applied
  provider-wide since every OpenAI-compat reasoning model spends
  reasoning tokens from the same budget.  Callers that don't pass
  ``thinking_budget`` are unaffected.

### 77.3 Tests and regression guard ✓

- [x] ``tests/unit/test_openai_compat.py::TestReasoningContent``
  — five streaming/complete fixtures plus three
  ``thinking_budget`` floor tests.  Covers reasoning-only turns,
  reasoning + content turns, no-reasoning turns, and the
  max_tokens bump in both ``max_tokens`` supplied and omitted
  cases.
- [x] ``tests/unit/test_chat_reasoning.py`` — TUI render path:
  reasoning renders before content, Rich markup escape guard,
  ``ChatWidget.set_reasoning`` behaviour.
- [x] ``tests/unit/test_web_server.py::TestBroadcastChat`` +
  ``TestTrailingReasoning`` — websocket payload carries the
  ``reasoning`` field, the helper walks back to the latest
  assistant turn.  Plus CSS/JS presence assertions.
- [x] Live smoke ran against Kimi K2 on Fireworks
  (``tests/live/test_llm_live.py::TestFireworksKimiReasoning``,
  gated on ``FIREWORKS_API_KEY``).  First run surfaced a real wire
  constraint — Fireworks rejects ``max_tokens > 4096`` on
  non-streaming requests, and the ``thinking_budget`` bump crosses
  that cap whenever callers signal reasoning headroom — so
  ``FireworksProvider.complete()`` now auto-delegates to
  ``stream()`` past the cap and reassembles a ``Response``.
  Second run: both smokes pass; reasoning round-trips and the
  ``thinking_budget`` leaves room for a real answer on a
  ``max_tokens=30`` caller.

**Exit criteria:** Kimi K2 on Fireworks shows reasoning in the
TUI/Web chat; ``max_tokens=30`` produces a visible answer (or a
documented reasoning-only turn); the provider surface stays
compatible with Claude's existing thinking rendering.  ``make
check`` passes with the new tests exercising both transports.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| 77.1 | Claude thinking surface on ``Response`` / ``Chunk`` | Match the existing shape rather than inventing a parallel one |
| 77.2 | 77.1 | Need the field before budgets can be tuned against it |
| 77.3 | 77.1, 77.2 | Live smoke needs ``FIREWORKS_API_KEY`` — mark skippable in CI |

**Discovered:** While adding the Fireworks.ai provider
(2026-04-24) — the Kimi K2 smoke test produced
``completion_tokens=30`` with an empty streamed string because
all 30 tokens went into ``reasoning_content`` frames that the
shared helper dropped.

---

## Phase 78: Provider Observability Hardening — April 23 Postmortem Lessons

**Goal:** Close the class of bug described in Anthropic's
`April 23 Claude Code postmortem
<https://www.anthropic.com/engineering/april-23-postmortem>`_:
a state-management flag that quietly cascaded across turns and
took a week to diagnose because cache-miss symptoms weren't
connected to the root cause.  Cantrip doesn't have the same bug,
but it has adjacent exposure surfaces — each addressed below.

### 78.1 Cache anomaly alerting ✓

Today cache metrics are extracted from Anthropic responses
(``src/cantrip/llm/claude.py:274-277``) and surfaced passively
in the TUI model bar (``modelbar.py:100-104``), the ``/info``
slash command (``slash_commands.py:393-396``), and the CLI
end-of-session summary (``cli.py:580-583``).  **There is no
logging or alert when cache behaviour turns pathological** —
if ``cache_creation_tokens`` started rising turn-after-turn (the
exact April 23 symptom) a user would only notice by actively
watching the model bar.

- [x] ``cantrip.agent.cache_monitor.CacheCascadeDetector`` is the
  rolling-window detector.  It watches per-turn
  ``cache_creation_input_tokens`` / ``cache_read_input_tokens``
  deltas and fires a one-shot warning when three consecutive
  creation-only turns follow a session that had previously been
  reading from the cache.  Fresh sessions (never-read baseline)
  and tool-only turns (no cache activity) don't trip the
  detector.  ``CantripAgent._check_cache_cascade`` wires the
  detector into ``_record_usage`` so every LLM turn observed.
- [x] Warning surfaces three ways: WARNING log, a SYSTEM
  conversation message appended to ``state.messages`` (so the
  transcript carries it), and a ``CHAT_MESSAGE`` UI event
  (``role=system``) so the TUI and Web chat show it in-band —
  passive metrics alone weren't enough in the April 23 case.
- [x] ``tests/unit/test_cache_monitor.py`` — eight unit tests
  covering the April 23 cascade, the one-shot latch, the
  fresh-session baseline, streak reset on a read turn, no-cache
  turns being ignored, missing/partial usage, and
  ``reset_warning``.  ``tests/unit/test_agent.py::
  TestCacheCascadeIntegration`` exercises the whole agent path
  — log + state message + bus event — against a replay of the
  cascade.

### 78.2 Web UI cache parity ✓

The TUI's ``ModelInfoBar`` shows ``cache: X% hit`` when
``cache_total > 0``.  Prior to this sub-phase a ``grep`` of
``src/cantrip/web/`` returned zero results for cache metrics —
Web users saw no cache information at all.

- [x] ``EventType.CACHE_METRICS_UPDATED`` on the shared UI
  event bus, with the ``cache_metrics_updated`` factory.
  ``CantripAgent._record_usage`` publishes the event on every
  turn whose usage dict carries either ``cache_*_input_tokens``
  field (providers without the fields never emit the event, so
  Gemini stays quiet).  The payload carries running totals for
  creation / read plus a pre-computed ``hit_pct`` so every
  consumer renders the same number without re-implementing
  the arithmetic.
- [x] Web header gains ``#cache-indicator`` — a muted badge
  that shows ``cache: NN% hit`` matching the TUI's wording.
  Hidden until the first cache-bearing turn arrives; the JS
  handler ``_updateCacheMetrics`` toggles visibility, updates
  the text, and sets ``title`` / ``aria-label`` so screen
  readers pick up the change via the ``aria-live="polite"``
  region.  Styled with ``--font-mono`` in ``style.css``
  alongside the existing ``--text-muted`` / border theme.
- [x] TUI modelbar subscribes to the same event via
  ``_on_bus_cache_metrics``, so the cache-hit readout moves in
  lockstep with the Web badge rather than relying solely on
  the 5-second polling timer.  Polling stays as the backup for
  the initial render and subagent-only turns.

### 78.3 Compaction corner-case tests + resume state ✓

Cantrip's compaction architecture is safer than Anthropic's
bug shape — it's a stateless threshold check
(``context.py:385-412``) with latched flags that *stop*
compaction rather than trigger it — but specific hazards
remained:

- ``_cycle_detected`` and ``_budget_exhausted`` reset to
  ``False`` on session resume; numeric counters survived but
  the boolean "stop" signals didn't.  A session already
  disabled could silently re-arm.
- No test asserted the one-shot semantic ("after compaction
  fires, ``should_compact()`` returns False on the very next
  turn").  The guarantee was implicit in the counter logic.

- [x] ``tests/unit/test_context_manager.py::
  TestCompactionSafety::test_should_compact_is_one_shot_after_compaction``
  walks the roadmap turn sequence: fill the context past the
  80% threshold, run ``compact()``, assert ``should_compact()``
  on the compacted output is False — no chance for the next
  turn to immediately re-trigger summarisation.
- [x] Schema v11 adds ``cycle_detected`` and ``budget_exhausted``
  boolean columns to ``session``; ``SessionStore.
  save_compaction_counters`` / ``load_compaction_counters``
  now persist and restore them; ``ContextManager.safety_state``
  / ``restore_safety_state`` round-trip both flags and
  ``CantripAgent._persist_compaction_state`` and the session-
  resume path in ``load_state`` are wired accordingly.  New
  tests cover the store round-trip, the ContextManager round-
  trip, and the "restored stop-flag blocks should_compact"
  assertion — the exact resume bug called out in the roadmap.
- [x] ``EventType.COMPACTION_STARTED`` /
  ``EventType.COMPACTION_COMPLETED`` added to the UI event bus
  with ``compaction_started`` / ``compaction_completed``
  factory helpers.  ``CantripAgent._run_compaction`` (new
  helper used by both the main and streaming conversation
  loops) publishes the events around the work and carries
  ``kind=compact|emergency`` in the completed payload so UIs
  can distinguish a successful summary from a fallback
  truncation.  ``TestContextManagement::
  test_compaction_emits_started_and_completed_events``
  exercises the whole pipeline end-to-end.

### 78.4 ``thinking_budget`` regression guard ✓

Claude (``claude.py:228-251``) and Gemini
(``gemini.py:80-108``) forward ``thinking_budget`` correctly to
their respective SDKs.  The four OpenAI-compatible providers
(inference-snap, fireworks, openrouter, openai-compatible) don't
forward a ``thinking`` block but *do* consume the budget: the
shared base bumps ``max_tokens`` to at least
``thinking_budget + 4096`` (Claude's formula) so reasoning tokens
don't starve the final answer (see Phase 77.2).  Before this
sub-phase **no test asserted the ``thinking`` block actually
reached the outgoing request** — a regression that dropped the
field would not fail any suite.

- [x] ``tests/unit/test_claude.py::TestClaudeProviderThinkingBudgetWire``
  patches ``client.messages.create`` / ``client.messages.stream``
  and asserts the kwargs contain
  ``thinking={"type": "enabled", "budget_tokens": <N>}`` when a
  non-None budget is passed, and that the field is absent
  otherwise.  Also pins ``temperature=1`` (required by extended
  thinking) and the ``max_tokens`` floor of
  ``budget + 4096``.
- [x] ``tests/unit/test_gemini.py::TestGemini3ThinkingConfig``
  gained three wire tests asserting
  ``ThinkingConfig(thinking_budget=<N>, include_thoughts=True)``
  lands in the ``config=`` kwarg of both
  ``generate_content`` and ``generate_content_stream``; when
  the budget is None, ``include_thoughts`` is False and
  ``thinking_budget`` is unset.
- [x] Decision: **no debug log needed** in the OpenAI-compat
  providers.  They're not silent no-ops — the budget raises
  ``max_tokens`` on the wire, which is observable in provider
  request logs and the model's cost report.  A debug log
  promising "ignored" would be actively misleading.

### 78.5 Exit criteria ✓

- [x] Cache cascade detector ships with unit test coverage.
- [x] Web UI shows cache-hit metrics at parity with the TUI.
- [x] Compaction one-shot semantic has an explicit test.
- [x] Compaction boolean stop-flags survive session resume.
- [x] ``thinking`` payload is asserted on the wire for Claude
  and Gemini.
- [x] ``make check`` green.  No behaviour change for users who
  weren't hitting any of these bugs.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| 78.1 | None | Additive detector in the existing per-turn usage path |
| 78.2 | Phase 60 (accessible Web UI) | Web updates should land against the WCAG-cleaned surface, not pre-cleanup |
| 78.3 | None | Tests + a small store migration |
| 78.4 | None | Pure test additions; optional debug log |

**Discovered:** Reviewing Anthropic's April 23 Claude Code
postmortem (2026-04-24).  Four parallel code audits confirmed
the gaps listed above against the current ``main`` branch.

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
| M48: Multimodal Debug | 48 | Providers accept images; Grafana/Tempo/Juju-status rendering tools return PNGs the agent reasons about |
| M49: Sandboxed Shell | 49 | Untrusted subprocesses run under PID/mount namespaces with deny-rule and syscall hardening |
| M50: Skills Interop | 50 | Standard-format skills import and export round-trip; MCP-aware skills resolve dependencies at load time |
| M51: Team Research | 51 | Written assessment of whether and how Cantrip should support teams working on a charm, with architecture sketches and a next-step recommendation |
| M52: Durable Subagents | 52 ✓ | Subagent LLM turns and tool calls checkpoint into SQLite; interrupted tasks resume from the last completed step instead of re-burning tokens |
| M53: Knowledge-in-Markdown | 53 | Planner prompts and task descriptions live in Jinja2 templates; `planner.py` split along the deterministic / LLM seam; dev design docs cover tools, skills, and prompts |
| M54: Authored Docs | 54 | `docs/docs/` site rebuilds from committed markdown sources through `make docs`; no hand-authored HTML remains in the docs tree |
| M55: Awesome-Copilot Survey | 55 | Eight awesome-copilot patterns investigated end-to-end; each has a committed decision, prototype, or recommendation |
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
| M67: Pi-Inspired Sessions | 67 | Session tree rewind/branch, mid-session ``/model``, ``cantrip run --print --json`` for scripts, and ``/share`` to secret gist — four gaps the Pi coding agent fills that charm authors also hit |
| M68: OpenCode Safety Rails | 68 | Snapshot-backed ``/undo``/``/redo`` for file changes, declarative ask/allow/deny permissions, markdown-defined user slash commands, and a session-level plan mode — four guardrails adopted from OpenCode that map onto Cantrip's existing subsystems |
| M69: Kimi Workflow Features | 69 | Bounded Ralph-Loop iterate-until-green, ``--yolo`` unattended switch, ``Ctrl-X`` shell mode, and Mermaid/D2 Flow skills — four Kimi CLI patterns that fit Cantrip's autonomous loop, skill system, and CI story |
| M70: Amp-Inspired Depth | 70 | Librarian subagent that searches Charmhub and Launchpad, Oracle tool for on-demand second-opinion reasoning, glob-conditional guidance in AGENTS.md / skills, prompt-based review Checks that layer on top of charmlint, and a Painter tool that generates a Charmhub-style ``icon.svg`` |
| M71: Aider Engineering Hygiene | 71 | Tree-sitter-backed repo-map with graph-ranked symbols, architect/editor two-model mode, auto-commit-per-turn with dirty-commit separation, and a per-edit ruff/ty/charmlint feedback loop |
| M72: Continue Context Providers | 72 | Indexed charm-ecosystem docs (``@docs juju|ops|charmcraft|rockcraft``), an ``@``-mention context-provider registry, ``embed`` and ``rerank`` model roles, and ``@problems`` diagnostics-as-pre-turn-context |
| M73: Goose Workflow Packaging | 73 | Parameterised retryable Recipes with sub-recipes, MCP Apps rendered as sandboxed iframes in the Web UI, JSON-schema-enforced structured responses, and declarative retry with shell validators |
| M74: Populated Charm Docs | 74 ✓ | Generated ``docs/`` tree is bridged with the Phase 13 root files, populated from real Phase 17 acceptance-test command/output capture, with an architecture page extracted from transcript design decisions and a troubleshooting page mined from the agent's resolved-error history |
| M75: Inline Tool Blocks | 75 ✓ | Every tool call renders as a one-line block in the TUI and Web chat with a success/failure colour cue, so trailing-colon preambles stop reading as broken speech |
| M76: Copy-Friendly Chat | 76 | Toad-inspired per-block copy affordances either ship (keybinding, slash command, OSC 52, or similar) or a written assessment in ``design/UI.md`` explains why the current flow is sufficient |
| M77: Reasoning Content Surfaced | 77 | OpenAI-compatible reasoning deltas (Kimi K2, DeepSeek-R1, GLM reasoning variants) are captured and rendered like Claude's extended thinking rather than silently dropped |
| M78: Observability Hardening | 78 ✓ | Cache cascades surface as visible warnings, Web UI shows cache metrics at parity with TUI, compaction stop-flags persist across session resume, and ``thinking`` payload is asserted on the wire for Claude + Gemini |
| M79: Eval Gates Prompt Changes | 79 | System-prompt edits trigger a per-provider LLM-in-loop smoke test that runs in CI against a cheap model, closing the "narrow eval missed a cross-model regression" gap described in Anthropic's April 23 postmortem |
| M80: Stacked Policies | 80 | `GovernancePolicy` + `compose_policies()` replace the single-level category filter; per-goal rate limit, JSONL audit trail, and in-code destructive-command gates ship together as the policy-allowlist layer in the defence-in-depth stack with Phases 46 / 49 / 55.3 / 55.5 |
| M43: Memory | 43 | Cantrip learns per-charm and cross-charm lessons with citations, revalidation, user controls, and skill export |
