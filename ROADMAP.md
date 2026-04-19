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

## Phases 0–3: Complete

Phases 0 through 3 established the foundation, conversation loop, tools, TUI, charm paths,
and development experience. All items below are done.

<details>
<summary>Phase 0: Foundation</summary>

**Goal:** Basic infrastructure that everything else builds on.

### 0.1 Project Skeleton
- [x] Set up uv project structure
- [x] Configure pyproject.toml with dependencies
- [x] Set up GitHub Actions CI (lint, type check, test)
- [x] Create basic CLI entry point

### 0.2 LLM Abstraction
- [x] Define LLM provider interface
- [x] Implement Gemini provider
- [x] Basic conversation loop (no TUI yet, just CLI)
- [x] API key configuration

### 0.3 Juju Integration
- [x] Jubilant wrapper for common operations
- [x] Replace hand-rolled status dataclasses with Jubilant's own status types
- [x] Model management basics

### 0.4 Skills Infrastructure
- [x] Skills loader (lazy-load from agentskills.io format)
- [x] Skills index (lightweight list of available skills + descriptions)
- [x] Core charm skills (scenario-tests, jubilant-tests, relation-data-design, observability, ingress, adding-actions, adding-config)
- [x] System prompt includes skill index; full skill content loaded on demand

### 0.5 Prompt Templating
- [x] Jinja2 system prompt template with context variables
- [x] `build_system_prompt()` renders with charm name, path, models, decisions, etc.

</details>

<details>
<summary>Phase 1: Minimum Viable Cantrip</summary>

**Goal:** "Build a charm for my Flask app" → active/running in 2 minutes.

### 1.1 Environment Setup
- [x] Concierge integration, auto-setup LXD or Canonical K8s
- [x] COS-lite deployment to separate model
- [x] Cross-model relation setup

### 1.2 12-Factor Path (Path A)
- [x] Fetch and summarise 12-factor tutorials (Rockcraft + Charmcraft, 6 frameworks)
- [x] Framework detection (Flask, Django, Go, Express, Spring Boot, FastAPI)
- [x] paas-charm base, rockcraft.yaml generation, rock building, deploy + verify

### 1.3 Basic TUI
- [x] Textual app shell, split view (status + chat), Juju status display, chat I/O

### 1.4 Conversational Iteration
- [x] Add config options, actions via conversation; re-deploy after changes

### 1.5 Version Control
- [x] Git tools (clone, init, status, diff, log, add, commit, push)
- [x] GitHub CLI tools (repo create, PR create, issue list)

</details>

<details>
<summary>Phase 2: Development Experience</summary>

**Goal:** Fast iteration loop, observability-driven debugging, event-driven reactions.

### 2.1 Fast Dev Cycle
- [x] juju ssh code injection, automatic hook triggering, smart fast/full path switching

### 2.2 Observability Integration
- [x] ops-tracing in generated charms, Tempo + Loki query tools, trace-driven debugging

### 2.3 Cantrip's Own Test Suite
- [x] Unit, integration, e2e, TUI, live Juju, live LLM, Spread, CI gating

### 2.4 Generated Charm Testing
- [x] Scenario + Jubilant test generation, background test runner, results in TUI

### 2.5 Persistence
- [x] SQLite session store, context compaction (virtual files algorithm), decision tracking

### 2.6 Event-Driven Agent
- [x] Status-diffing watcher, Loki polling, event dedup, agent reacts to Juju changes

</details>

<details>
<summary>Phase 3: Expand Charm Paths</summary>

**Goal:** Support custom apps and infrastructure, not just 12-factor.

### 3.1 Path B: Custom Applications
- [x] Full charm scaffolding, workload analysis, config/action inference, machine + K8s

### 3.2 Path C: Infrastructure
- [x] Charmhub search, fork/extend workflow, operational pattern templates, research mode

### 3.3 OCI Image Handling
- [x] Docker Hub registry search, image evaluation, Rockcraft fallback

</details>

---

## Phase 4: Autonomous Agent Core ✓

**Goal:** The agent works independently. It plans its own work, executes tasks without
user prompting, and shows progress in a visible checklist. The user steers; the agent drives.

This is the fundamental architectural shift from reactive to proactive.

### 4.1 Task Model and Work Queue

The internal representation of autonomous work.

- [x] `AgentTask` dataclass — id, title, status (pending/active/done/failed/blocked),
  category (research/build/deploy/test/debug/infra), result summary, dependencies
- [x] `WorkQueue` — ordered list of tasks with dependency resolution; tasks can be
  added, reordered, cancelled, and blocked/unblocked
- [x] Task persistence — tasks stored in the `.cantrip` SQLite database alongside
  session state; survives restarts
- [x] Task lifecycle hooks — callbacks when tasks change status (drives TUI updates)

### 4.2 Task Planner

The LLM generates a structured task list from user intent.

- [x] **Planning prompt** — when the user describes a charm ("build a charm for Redis"),
  the agent calls the LLM with a planning prompt that produces a structured task list
  rather than immediately starting work
- [x] **Task decomposition** — high-level intent → concrete, ordered tasks:
  1. Research workload (web search, docs, existing charms)
  2. Draft design proposal (operational story, integrations, substrate)
  3. Present design to user for confirmation
  4. Scaffold charm
  5. Deploy to dev model
  6. Add observability
  7. Run tests
  8. Add integrations
  9. Validate (pack + test + status check)
- [x] **Adaptive replanning** — when user provides new context, overrides a decision,
  or the watcher detects an issue, the planner can insert, reorder, or cancel tasks
- [x] **User-visible plan** — the task list is shown to the user before execution begins;
  user can approve, modify, or add tasks

### 4.3 Background Execution Engine

Executes tasks from the work queue without waiting for user input.

- [x] **Worker loop** — an asyncio task that picks the next ready task from the queue,
  executes it (LLM call + tool calls), records the result, and moves to the next
- [x] **Subagent pattern** — each background task runs in its own LLM context with a
  focused system prompt and only the tools it needs; results are summarised back to the
  main conversation context
- [x] **Concurrency** — initially sequential (one task at a time); later, independent
  tasks can run in parallel (e.g. research + environment setup)
- [x] **Cost routing** — infrastructure tasks (research, test running, log queries) use
  the light model; design and code-writing tasks use the primary model
- [x] **Conversation coordination** — when a task needs user input (e.g. "confirm this
  design"), it blocks and posts a question to the chat; user's reply unblocks it
- [x] **Interruption** — user messages pause the executor while the conversation loop
  handles them; `manage_tasks` tool lets the LLM cancel, reprioritise, and inspect
  tasks; the executor resumes autonomously after the user interaction

### 4.4 Task Checklist Widget

A visible, real-time view of autonomous work in the TUI.

- [x] **Task list panel** — a new TUI panel (right side, above the Juju status widget)
  showing all tasks with status indicators:
  - `○` pending
  - `⟳` active (with elapsed time)
  - `✓` done
  - `✗` failed
  - `◌` blocked (waiting for user or dependency)
- [x] **Live updates** — task status changes are reflected via dirty-flag polling
  (thread-safe `notify_changed` + 0.5 s timer)
- [x] **Expandable detail** — clicking a task row toggles a detail panel showing
  result summary, category, status, description, and blocked reason
- [x] **Category grouping** — tasks grouped by category (Research, Build, Deploy,
  Test, Debug, Infrastructure, Confirm) with per-category headers; empty categories
  are omitted; task order within each group matches the queue order

### 4.5 Auto-Deploy Loop

The agent keeps the deployed charm in sync with the code.

- [x] **After code changes** — successful BUILD tasks automatically queue a DEPLOY
  follow-up task via `tasks_after_build()`, closing the build → deploy gap
- [x] **Post-deploy verification** — after deploy, queue a status check task; if the
  charm enters error/blocked, queue a diagnostic task
- [x] **Watcher → task queue** — watcher events (hook failures, status changes, new
  relations) create tasks in the work queue instead of being injected as raw chat
  messages; this lets the agent prioritise and batch related events
- [x] **COS-driven diagnostics** — when the watcher detects an issue, the diagnostic
  task automatically queries Tempo traces and Loki logs before attempting a fix

**Exit criteria:** User says "build a charm for X" and the agent independently researches,
plans, builds, deploys, and iterates — with the user only confirming the design. The TUI
shows a live checklist of everything the agent is doing.

---

## Phase 5: Research-Driven Charm Design ✓

**Goal:** The agent does quality web research to understand the operational story for a
workload, proposes a design grounded in real devops best practices, and lets the user
confirm or override before building.

### 5.1 Proactive Workload Research

When a workload is identified, the agent autonomously researches it.

- [x] **Source analysis** — clone the application repo (if provided), analyse framework,
  dependencies, config patterns, Dockerfile, CI/CD setup
- [x] **Web research** — search for and read:
  - Official documentation (installation, configuration, operations guides)
  - DevOps best practices for this specific workload
  - Common deployment patterns (containerised, systemd, clustering)
  - Known failure modes and recovery procedures
  - Monitoring and observability recommendations
- [x] **Charmhub survey** — search for existing charms, related charms, and relevant
  charm libraries; assess whether to build new, fork, or extend
- [x] **Research summary** — produce a structured `WORKLOAD.md` (already partially
  implemented) covering: what the software does, how it's configured, how it runs,
  how it scales, how it fails, how it's monitored

### 5.2 Operational Story Discovery

Translate research into charm design decisions.

- [x] **Operational questions** — for each workload, the agent identifies the key
  operational questions:
  - Does it need persistent storage? What kind?
  - Does it cluster? How (leader election, consensus, replication)?
  - What are the health check endpoints/commands?
  - What config is required vs optional?
  - What are the failure modes and recovery procedures?
  - What integrations make sense (database, ingress, cache, identity)?
  - What metrics/logs/traces does it expose?
- [x] **Best-practice grounding** — answers are grounded in web research, not
  hallucinated; the agent cites sources (documentation URLs, blog posts)
- [x] **Gap identification** — when the agent can't determine something from research,
  it explicitly marks it as a question for the user

### 5.3 Design Proposal

The agent presents a design for user confirmation before writing code.

- [x] **Structured proposal** — the agent formats a clear design proposal covering:
  - Substrate recommendation (K8s vs machine) with reasoning
  - Charm path (12-factor PaaS, custom, infrastructure) with reasoning
  - Proposed integrations (database, ingress, COS, etc.)
  - Config options to expose
  - Actions to implement
  - Scaling strategy
  - Key operational patterns (backup, failover, etc.)
- [x] **User confirmation** — the proposal is presented in the chat; the user can
  approve, override specific decisions, or ask for changes
- [x] **Override handling** — user overrides are recorded as `Decision` objects and
  feed back into the task planner; the task list is regenerated to match

### 5.4 Research → Build Pipeline

Confirmed design feeds directly into autonomous execution.

- [x] **Design-to-tasks** — once the user approves (or the agent proceeds with defaults
  after a timeout/no-response), the planner generates concrete build tasks from the
  approved design
- [x] **Context handoff** — research findings and design decisions are summarised and
  injected into the system prompt / task context so subagents have the full picture
  without re-researching
- [x] **Incremental research** — when the user adds context mid-build ("it also needs
  Redis for caching"), the agent does targeted research on the new requirement and
  adjusts the plan (via the existing replan mechanism)

**Exit criteria:** User says "build a charm for PostgreSQL". The agent researches how
PostgreSQL is operated (primary/replica, WAL shipping, pgbouncer, backup with pg_dump or
pgBackRest), proposes a design with specific integrations and operational patterns, gets
user confirmation, then builds it — all autonomously.

---

## Phase 6: Speed ✓

**Goal:** Get from "build a charm for X" to a running charm in under two minutes. The
autonomous pipeline works, but tasks run sequentially and every phase involves more LLM
round-trips than necessary.

### 6.1 Parallel Subagent Execution

The executor currently picks one task at a time. Independent tasks (e.g. the three Phase 1
research tasks) should run concurrently.

- [x] **Concurrent task runner** — when multiple tasks have all dependencies met, run them
  in parallel via a semaphore-bounded executor
- [x] **Concurrency limit** — configurable cap (default 3, `--concurrency` CLI flag) to
  avoid rate-limiting from LLM providers
- [x] **Per-provider rate awareness** — shared ``ProviderThrottle`` coordinates rate-limit
  back-off across concurrent subagents; when one subagent hits a limit, others using the
  same provider wait for the cooldown before retrying

### 6.2 Fast Path for Simple Charms

The full research → synthesis → confirm → build pipeline is overkill for well-understood
workloads (Flask app, Django, FastAPI, Express, etc.). A streamlined path should skip or
compress the research phase.

- [x] **Template-based design** — for known 12-factor frameworks (Flask, Django, FastAPI,
  Go, Express, Spring Boot), `plan_fast_path()` generates just 2 tasks (design + confirm)
  instead of the full 4-5 task research pipeline
- [x] **Skip research when unnecessary** — `is_fast_path()` detects when the framework
  is well-known and no source URL needs analysis, routing to the compressed path
- [x] **One-shot build mode** — for trivial cases, collapse scaffold + write code + pack
  into a single subagent invocation instead of separate tasks; `plan_one_shot_build()`
  generates a single BUILD task for known 12-factor frameworks

### 6.3 Reduce LLM Round-Trips

Each subagent can do up to 12 tool-call rounds. Research subagents in particular tend to
fetch → read → fetch → read in a long chain.

- [x] **Batch tool guidance** — subagent prompts now explicitly encourage calling multiple
  tools in a single round (e.g. "fetch all URLs in one round, then analyse")
- [x] **Tighter task scoping** — each category's guidance is more prescriptive with
  concrete round-count targets and step sequences
- [x] **Early termination** — subagents are told to stop when sufficient information is
  gathered; max rounds reduced from 12 to 8

### 6.4 Merge Planning with Execution (discussion needed)

The separate `plan()` LLM call before any work starts adds latency. For the common "build
a charm for X" flow, the Phase 1 research tasks are always the same — they could be
hardcoded rather than generated by an LLM every time.

- [x] **Discuss** — evaluated and decided: the initial planning LLM call is eliminated
  for the common "build a charm" flow; deterministic templates are faster and more
  predictable
- [x] **Hybrid approach** — `plan_research_phase()` generates Phase 1+2 tasks
  deterministically; LLM planning is reserved for replanning (scope changes) and
  Phase 3 build tasks (via `plan_from_design()`)

### 6.5 Model Routing Review (to be considered)

Review which model is used for which task categories. Research tasks may not need the
primary model; coding tasks definitely should stay on the primary.

- [x] **Audit current routing** — map out which model handles each task category today
  (research and infra already use light model; synthesis uses primary)
- [x] **Evaluate quality trade-offs** — test whether light-model research produces
  sufficient quality for downstream synthesis, or whether certain research tasks
  (e.g. source analysis) benefit from the primary model
- [x] **Per-task model override** — allow the planner or user to specify model preference
  per task, rather than only per category; `ModelHint` enum persisted in SQLite

**Exit criteria:** The common "build a 12-factor charm" flow completes in under two
minutes wall-clock time (excluding user confirmation and Juju deploy wait).

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

## Phase 8: Local Inference Snaps ✓

**Goal:** Run Cantrip entirely on local models via Canonical's
[inference snaps](https://documentation.ubuntu.com/inference-snaps/), demonstrating
a fully Canonical stack with no external API dependencies.

Inference snaps package optimised local models (Gemma 3, DeepSeek-R1, Qwen-VL,
Nemotron) as Ubuntu snaps.  Each snap auto-detects hardware (CPU/GPU/NPU),
serves an OpenAI-compatible API at `http://localhost:<port>/v1`, and supports
chat completions, streaming, and tool calling — no API key required.

### 8.1 Basic Provider

- [x] **`InferenceSnapProvider`** — new `LLMProvider` implementation using the
  OpenAI-compatible API exposed by inference snaps (via `httpx`, no new deps)
- [x] **Auto-discovery** — `discover_snap_endpoint()` runs `<snap> status` to
  find the correct base URL; falls back to known default ports
- [x] **Model detection** — queries the snap's `/models` endpoint to get the
  served model name automatically
- [x] **Tool calling** — full support for function calling via the OpenAI tools
  format (tested with llama.cpp backend)
- [x] **Streaming** — SSE-based streaming matching the OpenAI streaming format
- [x] **Factory integration** — `--provider inference-snap --snap gemma3` CLI
  flags; `create_provider("inference-snap", snap_name="deepseek-r1")`
- [x] **Unit tests** — message conversion, tool conversion, request building,
  completion parsing, discovery, and factory integration

### 8.2 Robustness and Quality

- [x] **Context window tuning** — queries the snap's `/models` endpoint for
  `n_ctx_train`, `context_length`, or `max_model_len` and uses it as the
  context window size instead of the fixed 8192 default
- [x] **Graceful degradation** — detects models that don't support tool calling
  via a `capabilities` metadata field and omits tools from requests; defaults
  to tools enabled when no capabilities are advertised
- [x] **Connection health** — detects when a snap's server is not running and
  raises `ProviderError` with an actionable message including `snap start` and
  `status` commands
- [x] **Multi-snap routing** — `--light-snap` flag creates a separate provider
  backed by a lighter snap (e.g. nemotron-3-nano) for research/infra tasks
- [x] **Snap listing tool** — `list_inference_snaps` agent tool discovers
  installed snaps, checks their health, and reports served model names

### 8.3 Performance Considerations

- [x] **Prompt budget** — compact system prompt template already exists for
  providers with limited context windows; dynamic context window detection
  (8.2) ensures compaction triggers earlier for smaller models
- [x] **Task routing** — RESEARCH and INFRA categories route to the light
  provider; synthesis and code-writing tasks stay on the primary model;
  per-task `ModelHint` allows overriding category defaults
- [x] **Hybrid mode** — `--light-provider` flag enables cross-provider routing
  (e.g. `--provider claude --light-provider inference-snap --light-snap gemma3`)
  so research tasks use a local model while code generation uses a cloud provider

**Exit criteria:** `cantrip --provider inference-snap --snap gemma3` launches and
can hold a conversation, call tools, and attempt charm building using a fully
local model — demonstrating the Canonical inference snap ecosystem.

---

## Phase 9: Terraform Support ✓

**Goal:** Understand how Cantrip should support Terraform for Juju-deployed charms. Charms
increasingly ship a Terraform module so that operators can deploy them declaratively via
`terraform apply` rather than (or alongside) `juju deploy`. Cantrip should be able to
generate, validate, and maintain these modules.

### 9.1 Research

Understand the Terraform ecosystem for Juju charms and determine what Cantrip needs to do.

- [x] **Study the standard specification** — read and internalise the
  Terraform standard specification for charms, which defines how charm Terraform
  modules should be structured
- [x] **Survey existing modules** — examined published Terraform modules for existing charms
  (sdcore-gnbsim-k8s, grafana-k8s, mysql-k8s) to understand patterns, conventions, and
  common pitfalls
- [x] **Study the charmkeeper-terraform agent spec** — read and internalised the
  [charmkeeper-terraform agent](https://github.com/seb4stien/charmkeeper/blob/main/.github/agents/charmkeeper-terraform.md),
  which codifies practical standards for Terraform modules in charms
- [x] **Identify scope** — Cantrip supports generating a Terraform module from
  `charmcraft.yaml`, validating it with `terraform validate` and `terraform fmt`, and
  maintaining it as the charm evolves (regeneration on metadata changes); see TERRAFORM.md

### 9.2 Design Decisions

- [x] **When to generate** — on request, not by default; the system prompt suggests it
  after a successful build+deploy; the `terraform` skill provides full guidance
- [x] **Module structure** — standard four-file structure (`main.tf`, `variables.tf`,
  `outputs.tf`, `versions.tf`) fully inferred from `charmcraft.yaml`
- [x] **Integration with the build pipeline** — `generate_terraform` is a BUILD tool;
  `validate_terraform` is in BUILD and TEST allowlists
- [x] **Validation tooling** — `validate_terraform` runs `terraform fmt --check` and
  `terraform validate`; gracefully skips if the `terraform` CLI is not installed

### 9.3 Implementation

- [x] **Terraform module generator** — `src/cantrip/charm/terraform.py` deterministically
  generates all four files from `charmcraft.yaml` metadata (name, provides, requires,
  resources, storage)
- [x] **Agent tools** — `generate_terraform` and `validate_terraform` tools; added to
  BUILD and TEST allowlists
- [x] **Terraform skill** — `skills/terraform/SKILL.md` with full workflow guidance
- [x] **System prompt** — Terraform module section added to the prompt template

**Exit criteria:** Clear design document for Terraform support, grounded in the standard
specification and real-world module patterns, with a concrete implementation plan.
Implementation complete with generator, tools, skill, and prompt integration.

---

## Phase 10: Existing Charm Improvement ✓

**Goal:** Use Cantrip not just to build new charms, but to bring existing charms up to
modern standards. The user points Cantrip at an existing charm ("here's my charm, make it
great") and Cantrip audits it, identifies gaps, and autonomously adds COS integration,
tests, best-practice fixes, and everything needed for a public Charmhub listing.

### 10.1 Charm Audit

Analyse an existing charm and produce a comprehensive gap analysis.

- [x] **Ingest existing charm** — `CharmAuditTool` (`charm_audit`) accepts a local path,
  parses `charmcraft.yaml` (with `metadata.yaml` fallback), `src/charm.py`, tests, README,
  LICENSE, and requirements; added to RESEARCH and BUILD tool allowlists
- [x] **Best-practices checklist** — deterministic checks for deprecated APIs (StoredState,
  Harness, `charmcraft fetch-libs` imports), COS relation presence (tracing,
  metrics-endpoint, logging, grafana-dashboard), ops-tracing setup, and test directory
  structure; qualitative checks (event handling, status management, Pebble patterns)
  are left to the subagent LLM
- [x] **Public listing requirements** — checks for `charmcraft.yaml` metadata fields
  (display-name, summary, description, docs, issues, source, tags), README.md, LICENSE/
  LICENCE, and icon.svg
- [x] **Audit report** — produces a structured AUDIT.md grouped by severity (must-fix,
  should-fix, nice-to-have) plus a machine-readable `data` dict with gaps and findings

### 10.2 Observability Gap Fill

Add COS integration and ops-tracing if missing or incomplete.

- [x] **COS integration audit** — `charm_audit` checks for tracing, metrics-endpoint,
  logging, and grafana-dashboard relations; gaps reported in `data["gaps"]`
- [x] **Observability fill task** — `plan_improvement_fixes` generates a BUILD task
  (`fill-observability`) that loads the `observability` skill and adds missing COS
  relations, ops-tracing, metrics, and log forwarding; guided by the `charm-improvement`
  skill
- [x] **Add metrics** — the `fill-observability` task guidance now instructs adding a
  Prometheus metrics endpoint via the `metrics-endpoint` relation
- [x] **Add log forwarding** — the `fill-observability` task guidance now instructs
  adding Loki log forwarding via the `logging` relation with structured logging
- [x] **Alert rules** — the `fill-observability` task guidance now instructs generating
  basic Prometheus alert rules in `src/prometheus_alert_rules/` for common failure
  conditions (unit blocked, hook failures, resource exhaustion)
- [x] **Grafana dashboard** — the `fill-observability` task guidance now instructs
  generating a basic Grafana dashboard JSON in `src/grafana_dashboards/`

### 10.3 Test Gap Fill

Add or improve tests to match the standard Cantrip would apply to a new charm.

- [x] **Test coverage audit** — `charm_audit` checks for `tests/unit/test_*.py` and
  `tests/integration/test_*.py`; gaps reported in `data["gaps"]`
- [x] **Test fill task** — `plan_improvement_fixes` generates a BUILD task (`fill-tests`)
  instructing the subagent to write Scenario unit tests and Jubilant integration tests;
  guided by the `charm-improvement` skill with patterns and examples
- [x] **Migrate from Harness** — `charm_audit` detects Harness imports as deprecated APIs
  and flags them; the `charm-improvement` skill includes a Harness → Scenario migration
  table; the `modernise-code` fix task handles the rewrite
- [x] **Jubilant integration tests** — the `fill-tests` task guidance now includes
  detailed Jubilant patterns: deploy+active/idle, each relation endpoint, each action,
  and config changes; loads the `charm-improvement` skill for examples
- [x] **Test validation** — the `fill-tests` task instructs running `run_charm_tests`
  for each test type and iterating until green before committing

### 10.4 Code Modernisation

Bring the charm code up to current Ops framework standards.

- [x] **Deprecated API migration** — `charm_audit` scans for StoredState, Harness,
  `charmcraft fetch-libs` imports, and `framework.breakpoint`; `plan_improvement_fixes`
  generates a `modernise-code` BUILD task with specific migration instructions
- [x] **Type annotations** — `_check_type_annotations()` in `audit.py` scans src/
  Python files for `def foo(...) -> ...` patterns; absence flagged as nice-to-have
  in the audit report and sets `data["gaps"]["type_annotations"]`; the `modernise-code`
  BUILD task now includes type hint guidance when this gap is detected
- [x] **Modern patterns** — `_check_modern_patterns()` in `audit.py` scans for four
  patterns: holistic status handling (`_reconcile`/`_update_status`), config-changed
  event handler, relation-changed event handler, and Pebble readiness checks
  (`can_connect()`/`PebbleReadyEvent`); missing patterns flagged as nice-to-have;
  `data["gaps"]["modern_patterns"]` and `data["modern_patterns"]` detail dict added;
  `modernise-code` BUILD task includes specific guidance for each missing pattern
- [x] **Dependency updates** — `_check_fetch_libs` scans for `from charms.<lib>.v<N>` imports
  and maps them against a known PyPI equivalents table; findings appear in the audit report
  and feed into the `modernise-code` improvement task

### 10.5 Listing Readiness

Prepare the charm for a polished Charmhub listing.

- [x] **README generation** — `listing-readiness` task uses the existing
  `generate_readme` tool; guided by the `charm-improvement` skill README section
- [x] **Metadata completion** — `charm_audit` checks all listing fields; the
  `listing-readiness` task fills missing `charmcraft.yaml` fields
- [x] **Documentation** — `GenerateDocsTool` (`generate_docs`) creates a `docs/` directory
  with Diátaxis-structured documentation (tutorial, how-to, reference, explanation) using
  the Canonical starter pack (Makefile, conf.py, requirements.txt, .readthedocs.yaml);
  content files are MyST Markdown populated from `charmcraft.yaml` metadata; build locally
  with `cd docs && make html`
- [x] **Icon check** — `charm_audit` checks for `icon.svg` and flags if missing
- [x] **Placeholder icon** — when no `icon.svg` exists, generate a simple placeholder SVG
  (coloured circle with the charm's initial) so the charm is publishable to Charmhub
  immediately; the user can replace it with real artwork later. Requires adding an
  `other-files` part to `charmcraft.yaml` to stage the icon into the packed charm:
  ```yaml
  parts:
    charm:
      ...
    other-files:
      plugin: dump
      source: .
      stage:
        - icon.svg
  ```
- [x] **Licence check** — `charm_audit` checks for LICENSE/LICENCE and flags if missing

### 10.6 Validation and Presentation

Verify all improvements work together and present the result.

- [x] **Full build** — `validate-improvements` task runs `charm_validate` (which
  includes `charmcraft pack`)
- [x] **Test suite green** — `validate-improvements` task runs both unit and integration
  tests as a combined gate
- [x] **Deploy and verify** — `deploy-verify-improvements` DEPLOY task packs, deploys
  or refreshes, establishes relations, and runs `juju_wait` to confirm active/idle;
  depends on `validate-improvements`
- [x] **Diff review** — `diff-review` RESEARCH task runs `git_log` and `git_diff` to
  summarise all changes grouped by category (observability, tests, code modernisation,
  listing); notes any issues flagged but not addressed; depends on deploy-verify
- [x] **Incremental commits** — each fix BUILD task includes commit guidance; tasks are
  independent so each category is committed separately

**Exit criteria:** User points Cantrip at an existing charm. Cantrip audits it, adds COS
integration, writes Scenario and Jubilant tests, modernises code, prepares listing metadata,
and presents a clean diff — bringing the charm to the same standard as one built from scratch.

---

## Phase 11: Long-Running Agent Resilience ✓

**Goal:** Make the autonomous work loop more robust across long sessions and restarts.
Inspired by [Anthropic's engineering guidance on effective harnesses for long-running
agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents),
these changes ensure subagents commit their work, verify their output, recover cleanly
from failures, and resume gracefully after interruption.

### 11.1 Commit-After-Build

Build subagents should commit their changes before declaring success, so each task's
output is independently recoverable via git.

- [x] **Build guidance update** — add explicit instruction to `_CATEGORY_GUIDANCE[BUILD]`
  telling subagents to `git_add` + `git_commit` with a descriptive message before
  finishing; similarly for DEBUG subagents that apply fixes
- [x] **Commit verification** — after a BUILD/DEBUG subagent completes, the executor
  checks `git_status` for uncommitted changes and logs a warning if any remain

### 11.2 Lightweight Self-Verification

Build subagents should run a basic sanity check before declaring success, catching
obvious errors before the dedicated TEST task.

- [x] **Build self-check** — add `charm_validate` and `run_charm_tests` (unit only) to
  the BUILD tool allowlist; update BUILD guidance to run validation before finishing
- [x] **Fail-fast on validation** — if `charm_validate` fails inside a build subagent,
  the subagent should attempt a fix (one retry) rather than reporting a false success

### 11.3 Session Resume Protocol

When Cantrip starts with an existing `.cantrip` file, it should reconstruct context
from prior work before planning new tasks — not start from scratch.

- [x] **Progress summary** — on startup with an existing session, load completed tasks,
  decisions, and the last few git commits; inject a structured summary into the
  conversation as initial context
- [x] **Environment health check** — verify the charm path exists, the Juju model is
  responsive, and the last-known charm status before accepting new instructions
- [x] **Stale task recovery** — tasks left in ACTIVE status from a prior session (due to
  crash or interruption) should be reset to PENDING with a note that they need re-running

### 11.4 Git-Revert-on-Failure

When a BUILD or DEBUG subagent fails, partial file writes may leave the working tree in
a broken state. Clean up automatically so retries start from a known-good baseline.

- [x] **Snapshot before execution** — the executor records the current git HEAD before
  launching a BUILD/DEBUG subagent
- [x] **Revert on failure** — if the subagent fails, the executor runs `git checkout .`
  to restore the working tree to the pre-task state (only for tracked files)
- [x] **Preserve diagnostics** — before reverting, capture a summary of the changes
  (via `git diff`) and attach it to the task's failure result so the next attempt or
  the user can see what went wrong

### 11.5 Pre-Task Environment Health Checks

Before launching deploy or test subagents, verify that the environment is in a usable
state — catching stale models, broken controllers, or missing charms early.

- [x] **Deploy pre-check** — before DEPLOY tasks, verify the Juju model exists and the
  controller is reachable; if not, queue an INFRA task to fix it rather than letting
  the deploy subagent fail opaquely
- [x] **Test pre-check** — before TEST tasks, verify the charm is packed and the
  application is deployed; skip if prerequisites are clearly not met and report why

**Exit criteria:** Subagents commit their work, verify their output with a quick
validation pass, and the executor cleans up failed attempts. Restarting Cantrip on an
existing session resumes smoothly with full context.

---

## Phase 12: Red/Green Charm Building ✓

**Goal:** Give the agent a machine-verifiable definition of success using a red/green TDD
loop. Integration tests are written *before* the charm code (red — tests exist but fail),
and the agent iterates until they pass (green). This flips the current sequence
(scaffold → code → tests → deploy) to a red/green cycle
(scaffold → write integration tests → code → run tests → fix → repeat).

Integration tests are ideal for this because they are naturally declarative ("deploy the
charm, relate it to PostgreSQL, check active/idle") and test the external contract rather
than internal implementation. Many charm integration tests are straightforward — verifying
that the charm deploys, that specific integrations work, that actions execute, and that
config changes take effect.

### 12.1 Integration-Tests-First in the Build Pipeline

Restructure the build task sequence so integration tests are written early and used as
the success criterion throughout.

- [x] **Update `_DESIGN_TO_BUILD_PROMPT`** — change the "typical build sequence" to:
  1. Scaffold the charm (`charmcraft init`, write metadata)
  2. Write integration tests from the design (deploy, relations, actions, config)
  3. Write charm code to make the tests pass
  4. Pack, deploy, and run integration tests
  5. Fix and iterate until tests pass
  6. Write unit tests (Scenario) for edge cases and error paths
  7. Commit and offer next steps
- [x] **One-shot build update** — `plan_one_shot_build()` description reordered to
  write integration tests (step 4) before charm code (step 5), with red/green framing
- [x] **BUILD guidance drives sequencing** — rather than a new task category, the BUILD
  subagent guidance itself instructs the red/green order: write integration tests first
  if they don't exist, then write charm code to make them pass. The planner's prompt
  naturally produces "write integration tests" and "write charm code" as separate BUILD
  tasks with the correct dependency ordering

### 12.2 Integration Test Generation from Design

The approved design contains enough information to write integration tests before any
charm code exists — the design specifies integrations, actions, config options, and
expected behaviour.

- [x] **Design-to-test extraction** — the BUILD guidance instructs subagents to derive
  test cases from the approved design: each relation endpoint gets a deploy+relate test,
  each action gets an execute test, each config option gets a set+verify test, and COS
  integration gets a relation test; uses Jubilant patterns
- [x] **Test template generation** — `GenerateTestsTool` (`generate_tests`) produces
  Jubilant-based integration test templates from `charmcraft.yaml`: `conftest.py` with
  fixtures, `test_deploy.py`, `test_relations.py` (one test per endpoint),
  `test_actions.py` (one test per action), and `test_config.py` (one test per option);
  tests are runnable (and failing) before any charm code is written
- [x] **Incremental test files** — tests are split into focused files (`test_deploy.py`,
  `test_relations.py`, `test_actions.py`, `test_config.py`) so subagents can target
  specific failures with the `pattern` parameter

### 12.3 Red/Green Build Subagent

Update the BUILD subagent to use the red/green cycle as its feedback loop.

- [x] **`run_charm_tests` already in BUILD tools** — build subagents can run integration
  tests directly, without waiting for a separate TEST task; this lets them iterate
  within a single subagent invocation (was added in Phase 11)
- [x] **BUILD guidance update** — `_CATEGORY_GUIDANCE[BUILD]` instructs the subagent:
  1. Read the design and existing integration tests
  2. If integration tests don't exist, write them first (red)
  3. Write charm code targeting the test expectations (green)
  4. Run `run_charm_tests` with `test_type='integration'` and optional `pattern`
  5. If tests fail, fix and re-run; iterate until green or rounds exhausted
  6. Write unit tests (Scenario) for edge cases as a second pass
- [x] **Test-result-driven iteration** — when a BUILD task fails with partial test
  progress (e.g. "3 passed, 4 failed"), `tasks_after_build_failure()` spawns a targeted
  follow-up BUILD task focused on the remaining failures rather than a generic DEBUG
  task; the retry task receives the previous failure output, uses the primary model,
  and instructs the subagent not to modify integration tests (they define the contract);
  retry chains are bounded — a retry task that also fails does not spawn another retry

### 12.4 Incremental Feature Addition

When the user asks to add a feature to an existing charm ("add PostgreSQL integration"),
the same red/green cycle applies: write the integration test first (red), then implement
until it passes (green).

- [x] **Feature test first** — the BUILD guidance instructs subagents to write integration
  tests before implementation code; replanning naturally follows the same pattern since
  the design-to-build prompt encodes the red/green sequence
- [x] **Regression safety** — the BUILD guidance runs the full integration suite, not just
  new tests, catching regressions
- [x] **Selective test execution** — `run_charm_tests` accepts an optional `pattern`
  parameter for targeting specific test files or functions (e.g.
  `pattern='test_postgresql_relation'`); supports file names, `file::function` form,
  and `-k` expressions; BUILD guidance instructs subagents to use this for faster
  iteration on specific failures

### 12.5 Unit Tests as a Second Pass

Unit tests (Scenario) remain valuable for edge cases, error paths, and fast iteration,
but they come after the integration tests establish the external contract.

- [x] **Unit test task after integration green** — the build sequence (both in
  `_DESIGN_TO_BUILD_PROMPT` and `plan_one_shot_build`) positions unit tests after
  integration tests pass; BUILD guidance instructs writing Scenario tests for edge
  cases as step 6 after the integration green phase
- [x] **Unit tests for error paths** — BUILD guidance explicitly lists the cases unit
  tests should cover: missing relations → BlockedStatus, invalid config → error
  handling, Pebble not ready → WaitingStatus
- [x] **Combined validation gate** — TEST guidance updated to run both unit and
  integration tests as a combined gate; unit tests run first (faster feedback),
  then integration tests

**Exit criteria:** User says "build a charm for X". After design approval, the agent
writes integration tests first (deploy, relate to PostgreSQL, run backup action, etc.),
then writes charm code and iterates until all integration tests pass. The agent has a
clear, automated signal for "this feature works" at every step.

---

## Phase 13: Charm Demo Generation ✓

**Goal:** Every charm Cantrip builds ships with a compelling, runnable demo. Not just a
README with `juju deploy` instructions, but a complete showcase: a deployment script that
sets everything up, captured output showing the charm in action, annotated walk-throughs
of key features, and observability screenshots demonstrating the COS integration. A
potential user or reviewer should be able to understand what the charm does and see proof
that it works, without deploying it themselves.

This is an always-required part of the build pipeline — not an optional polish step.

Two external tools are a natural fit here:
[**Showboat**](https://github.com/simonw/showboat) builds Markdown documents by
running real commands and capturing their output inline — exactly what we need for demo
documents with interleaved `juju` commands and results.
[**Rodney**](https://github.com/simonw/rodney) provides CLI-driven headless browser
automation (built on Chrome DevTools Protocol) — ideal for capturing Grafana dashboard
screenshots and verifying web-facing charms visually. Both tools are designed for
agent-driven workflows with comprehensive `--help` that acts as a skill definition.

### 13.1 Showboat and Rodney Integration

Wrap the external tools as Cantrip agent tools so subagents can use them.

- [x] **`showboat` agent tool** — `ShowboatTool` (`showboat`) wraps Showboat CLI commands
  (`init`, `note`, `exec`, `image`, `pop`, `verify`); added to BUILD tool allowlist;
  returns clear error when showboat is not installed (graceful degradation)
- [x] **`rodney` agent tool** — `RodneyTool` (`rodney`) wraps Rodney CLI commands
  (`start`, `stop`, `open`, `screenshot`, `wait`, `text`, `click`, `js`, etc.); added
  to BUILD and TEST tool allowlists; uses `--local` for directory-scoped sessions;
  screenshot commands get a longer timeout
- [x] **Dependency check** — both tools check for CLI availability via `shutil.which`
  and return actionable error messages when not installed (graceful degradation)
- [x] **Rodney for integration tests** — `rodney` is in the TEST tool allowlist so
  TEST subagents can visually verify web-facing charms

### 13.2 Demo Document Generation

Use Showboat to build a demo document by running real commands against a live deployment
and capturing the output inline.

- [x] **`DEMO.md` via Showboat** — demo guidance instructs using Showboat when
  available (`showboat init`, `showboat exec`, `showboat note`, `showboat image`)
  to build the document with interleaved explanations and real command output;
  falls back to `write_file` when Showboat is not installed
- [x] **Relation wiring** — demo guidance includes a dedicated "Relations" section
  showing each `juju relate` command with an explanation of what the relation
  provides and the resulting status
- [x] **Action showcase** — demo guidance includes a dedicated "Actions" section
  running each action with example parameters and capturing output via
  `showboat exec` or `juju_run_action`
- [x] **Config showcase** — demo guidance includes a dedicated "Configuration"
  section demonstrating key config options with before/after status
- [x] **Fallback path** — the MVP uses the fallback path: the demo subagent writes
  DEMO.md directly using `write_file`, capturing command output via juju tools
  (`juju_status`, `juju_run_action`, `juju_config`, `juju_debug_log`) and formatting
  it as Markdown; Showboat/Rodney wrappers can be added later as an enhancement

### 13.3 Captured Artefacts

Save standalone artefacts alongside the demo document for reference and reuse.

- [x] **`juju status` snapshot** — demo guidance instructs saving `juju_status` output
  to `demo/juju-status.txt`; `juju_status` added to BUILD tool allowlist
- [x] **Action results** — demo guidance instructs running each action and saving JSON
  results to `demo/actions/`; `juju_run_action` added to BUILD tool allowlist
- [x] **Log snippets** — demo guidance instructs capturing `juju_debug_log` excerpt
  to `demo/logs/event-log.txt`; `juju_debug_log` added to BUILD tool allowlist
- [x] **Trace capture** — demo guidance instructs running `tempo_query` with the
  charm's service name, saving trace JSON to `demo/traces/recent-traces.json`,
  fetching a full trace by ID to `demo/traces/<id>.json`, and writing a
  human-readable span summary to `demo/traces/README.md`; `tempo_query` added
  to BUILD tool allowlist; gracefully skipped when COS is unavailable
- [x] **Config reference** — demo guidance instructs dumping `juju_config` output to
  `demo/config-reference.txt`; `juju_config` added to BUILD tool allowlist
- [x] **`demo.sh` script** — demo guidance instructs generating a self-contained bash
  script (deploy, relate, configure, verify) with an optional `--cleanup` flag

### 13.4 Visual Assets

Use Rodney to capture visual proof of observability integration and deployment health.

- [x] **Grafana dashboard export** — demo guidance instructs saving the dashboard
  JSON to `demo/dashboards/` via the Grafana HTTP API when COS is deployed;
  gracefully skipped when unavailable
- [x] **Dashboard screenshot** — demo guidance instructs using Rodney to open
  the Grafana dashboard URL, `waitstable`, and `screenshot` to
  `demo/screenshots/grafana-dashboard.png`; embedded in DEMO.md via
  `showboat image`; gracefully skipped when Rodney is not installed
- [x] **Web UI screenshot** — demo guidance instructs using Rodney to capture
  the application's own UI through ingress for web-facing charms (those with
  HTTP ports in `charmcraft.yaml`); saved to `demo/screenshots/web-ui.png`;
  gracefully skipped when Rodney is not installed or URL is unavailable
- [x] **Architecture diagram** — `GenerateDiagramTool` (`generate_diagram`) generates a
  Mermaid diagram from `charmcraft.yaml` showing requires/provides/peers relations,
  containers, and display name; written to `architecture.md` and embedded in the generated
  docs explanation section

### 13.5 Demo Tutorial

Generate a guided walk-through that explains the charm's features in context.

- [x] **`TUTORIAL.md` generation** — demo guidance instructs creating a step-by-step guide covering:
  1. Prerequisites (controller, model, cloud substrate)
  2. Deploying the charm and its relations
  3. Verifying the deployment (what to look for in `juju status`)
  4. Exercising key features (config, actions, scaling)
  5. Observability (where to find dashboards, what metrics to watch)
  6. Troubleshooting common issues
- [x] **Copy-pasteable commands** — demo guidance instructs including exact commands
  with captured output from the live deployment
- [x] **Annotations from research** — demo guidance instructs drawing on WORKLOAD.md
  and DESIGN.md to explain *why* config options matter and what actions do
- [x] **Quick-start vs. full tutorial** — demo guidance instructs writing a "Quick
  start" section at the top of TUTORIAL.md (5–10 lines, just commands, no
  explanations) followed by the full step-by-step tutorial with detailed
  walk-through

### 13.6 Demo as a Pipeline Stage

Make demo generation an automatic part of every charm build, not an afterthought.

- [x] **Planner integration** — `_DESIGN_TO_BUILD_PROMPT` instructs the LLM planner
  to include a "Generate demo artefacts" task after all tests pass
- [x] **Demo BUILD task** — `tasks_after_test()` in `autodeploy.py` automatically
  creates a BUILD task with `ModelHint.PRIMARY` after successful TEST tasks;
  `_DEMO_GUIDANCE` in `subagent.py` provides detailed 10-step instructions;
  `_DEMO_PREFIX` guard prevents infinite task loops
- [x] **Demo validation** — demo guidance instructs running key commands from
  `demo.sh` (such as `juju status`) to verify they still work, noting any issues
  in DEMO.md; full clean-model end-to-end validation is deferred as a future
  enhancement (requires model teardown/creation during the build pipeline)
- [x] **README integration** — `GenerateReadmeTool` now detects and links
  `DEMO.md`, `TUTORIAL.md`, and `architecture.md` in the generated README;
  when `demo/juju-status.txt` exists, embeds it in a collapsible `<details>`
  block; sections are omitted when the corresponding files are absent
- [x] **Git commit** — demo guidance instructs committing all demo artefacts in a
  single commit

**Exit criteria:** Every charm Cantrip builds includes a `demo/` directory with a
Showboat-generated demo document (real commands + captured output), Rodney-captured
screenshots of Grafana dashboards and web UIs, a runnable `demo.sh`, and a step-by-step
tutorial. A reviewer can read `DEMO.md` and see exactly what the charm does — with
real output and screenshots — without deploying it.

---

## Phase 14: Session Transcripts and Audit Log ✓

**Goal:** Record everything that happens during a Cantrip session — every user message,
every LLM response, every tool call and result, every subagent conversation — and make
it exportable as a human-readable HTML transcript. This serves three purposes: debugging
agent behaviour, auditing what the agent did and why, and sharing sessions with
colleagues for review.

Currently, conversation messages live only in memory (lost on exit), subagent internal
conversations are discarded (only the final result summary is stored), and there is no
export functionality. This phase adds comprehensive recording to SQLite and a
polished HTML export inspired by
[claude-code-transcripts](https://github.com/simonw/claude-code-transcripts) — paginated,
searchable, with tool calls rendered inline and images displayed rather than shown as
base64.

### 14.1 Conversation Recording

Persist all conversation-loop messages to the `.cantrip` SQLite store.

- [x] **Messages table** — add a `messages` table to the SQLite schema: `id`, `role`
  (system/user/assistant/tool), `content`, `tool_calls` (JSON), `tool_results` (JSON),
  `metadata` (JSON), `timestamp`. Schema version bump
- [x] **Write-through recording** — in `CantripAgent.process_message()` and
  `process_message_streaming()`, write each message to the store as it is appended to
  the in-memory list; writes should be non-blocking (batched or async) so they don't
  slow the conversation loop
- [x] **Tool call detail** — for each tool call, record the tool name, full arguments,
  and the full result (output + error + success flag); truncate very large results
  (e.g. file contents over 50 KB) with a note that the full content is available in
  the virtual file store

### 14.2 Subagent Conversation Recording

Capture the full internal conversation of every subagent run, not just the final summary.

- [x] **Subagent messages table** — add a `subagent_messages` table: `task_id` (foreign
  key to tasks), `message_index`, `role`, `content`, `tool_calls` (JSON),
  `tool_results` (JSON), `timestamp`
- [x] **Recording in `Subagent.run()`** — after each LLM completion and tool execution
  round, write the messages to the store; the executor passes a store reference to the
  subagent for this purpose
- [x] **Link to task** — each subagent conversation is associated with its `AgentTask`,
  so the transcript can show "Task: Research PostgreSQL documentation" followed by the
  full LLM ↔ tool conversation that produced the result

### 14.3 Event Log

Record significant agent events beyond LLM conversations for a complete audit trail.

- [x] **Events table** — add an `events` table: `id`, `event_type`, `detail` (JSON),
  `timestamp`. Event types include:
  - `session_start`, `session_resume` — with provider, model, charm name
  - `task_status_change` — task id, old status, new status
  - `decision_made` — type, choice, reason (mirrors decisions table but timestamped
    in the event stream)
  - `design_confirmed`, `design_overridden` — with the override details
  - `watcher_event` — status change, hook failure, Loki alert
  - `error` — provider errors, tool failures, timeouts
- [x] **Watcher event recording** — the watcher already detects status changes and hook
  failures; record these as events so the transcript shows what triggered diagnostic
  tasks
- [x] **Token usage in context** — link token usage records to the specific message or
  subagent round that consumed them, so the transcript can show cost per task

### 14.4 HTML Export

Generate a polished, human-readable HTML transcript from the recorded data.

- [x] **Export command** — `cantrip export-transcript` CLI command that reads the
  `.cantrip` SQLite file and produces a self-contained HTML file (or directory of
  paginated HTML files for long sessions)
- [x] **Jinja2 templates** — HTML output generated via Jinja2 templates (consistent
  with the existing prompt templating pattern) with clean CSS styling; templates are
  bundled in `src/cantrip/transcript/templates/`
- [x] **Conversation view** — user messages, assistant responses, and tool calls
  rendered as a chat-style timeline with clear visual distinction between roles;
  tool calls shown as collapsible blocks with name, arguments, and result
- [x] **Subagent threads** — each subagent conversation rendered as a nested,
  collapsible thread under its parent task; the task title and status are shown as
  a header so the reader can see what the subagent was trying to do
- [x] **Task timeline** — a sidebar or top-level view showing the task checklist with
  status transitions and timestamps; clicking a task scrolls to its subagent thread
- [x] **Event stream** — significant events (decisions, status changes, errors)
  interleaved in the timeline at the correct chronological position
- [x] **Search** — full-text search across all messages, tool outputs, and events
- [x] **Pagination** — `cantrip export-transcript --page-size N` splits HTML
  output into multiple files (`transcript_1.html`, `transcript_2.html`, etc.)
  with previous/next navigation; tasks and events appear on page 1; each page
  is self-contained with inline CSS and search; custom filename stems supported
  via `--output`
- [x] **Self-contained** — CSS and any JavaScript inlined in the HTML so the file
  can be shared without external dependencies

### 14.5 Additional Export Formats

Support other output formats for different use cases.

- [x] **JSONL export** — `cantrip export-transcript --format jsonl` dumps every message,
  event, and subagent conversation as newline-delimited JSON; useful for programmatic
  analysis and piping into other tools
- [x] **Markdown export** — `cantrip export-transcript --format markdown` produces a
  single Markdown file with the conversation, tool calls as code blocks, and task
  summaries; lighter-weight than HTML for embedding in documentation
- [x] **Filtered export** — `--task <task-id>` exports only a specific task and its
  subagent conversation; `--phase research|build|deploy|test` exports all tasks in
  a phase; `--since <timestamp>` filters messages and events from a point in time;
  all three flags can be combined; conversation-loop messages are always included
  for context (except when filtered by ``--since``)

### 14.6 Live Transcript in TUI

Surface the transcript in the TUI for real-time inspection.

- [x] **Transcript screen (F9)** — ``TranscriptScreen`` modal with three switchable
  views (conversation, tasks, events) via the ``v`` key; conversation view shows
  messages with role indicators, timestamps, and tool call summaries; tasks view
  shows status icons, results, and subagent conversation counts; events view shows
  typed events with detail fields; loaded from the ``.cantrip`` SQLite file
- [x] **Subagent drill-down** — the tasks view shows subagent message counts and
  tool call counts for each task, providing visibility into what each subagent did

**Exit criteria:** After a Cantrip session, `cantrip export-transcript` produces a
polished HTML file showing the full conversation, every subagent's internal reasoning
and tool use, task status transitions, decisions, and events — all in a searchable,
paginated, human-readable format. Nothing is lost.

---

## Phase 15: Web UI ✓

**Goal:** Provide an alternative browser-based interface that mirrors the TUI exactly —
same three-panel layout, same task checklist, same Juju status visualisation, same chat —
so users can choose whichever interface suits their environment. Built with vanilla HTML,
CSS, and JavaScript (no framework: no React, Angular, Vue, or similar). The backend is a
lightweight localhost HTTP server embedded in Cantrip that exposes a WebSocket for
real-time updates and a small REST API for initial state.

The TUI (Textual) and Web UI must stay in sync: same features, same layout, same
information density. Neither is primary — they are two renderings of the same underlying
agent state. Changes to agent state (tasks, chat messages, Juju status, watcher events)
flow through a shared event bus that both UIs consume.

### 15.1 Shared UI Event Bus

Decouple agent state changes from UI rendering so both interfaces receive identical updates.

- [x] **Event bus abstraction** — `src/cantrip/ui/events.py` provides `EventBus` with typed
  `EventType` enum (`TASK_UPDATED`, `CHAT_MESSAGE`, `THINKING_CHANGED`,
  `JUJU_STATUS_CHANGED`, `WATCHER_EVENT`, `STATUS_BAR_CHANGED`, `PREFLIGHT_UPDATED`,
  `TASKS_SNAPSHOT`), frozen `Event` dataclass, sync/async subscribers, wildcard subscriptions,
  and thread-safe cross-thread publishing via `call_soon_threadsafe`
- [x] **Migrate TUI to event bus** — `CantripApp` subscribes to `TASK_UPDATED` and
  `WATCHER_EVENT` on the bus via `call_from_thread` for thread-safe Textual DOM updates;
  the old `on_task_changed` callback parameter removed from `start_executor`; CLI mode
  also migrated to bus subscription
- [x] **Serialisable event payloads** — every event carries a `dict[str, Any]` payload built
  by factory functions (`task_updated`, `chat_message`, `watcher_event`, etc.); `Event.to_json()`
  serialises for WebSocket transport; the web server subscribes a wildcard handler that
  forwards all bus events to WebSocket clients

### 15.2 Localhost HTTP Server

Embed a lightweight HTTP server that serves the Web UI and provides a WebSocket endpoint.

- [x] **Server module** — `src/cantrip/web/server.py` using aiohttp; serves
  server-rendered Jinja2 template, static files, WebSocket at `/ws`, and
  `/api/state` JSON endpoint; binds to `127.0.0.1` only
- [x] **CLI flag** — `cantrip --web` starts the web server (with `--web-port`,
  default 8471); dispatched before TUI/CLI in `main.py`
- [x] **Initial state endpoint** — `GET /api/state` returns current tasks as JSON
  for reconnect synchronisation
- [x] **WebSocket bridge** — broadcasts task changes, chat messages, and thinking
  state to all connected clients; receives `chat_input` from the browser and
  calls `agent.process_message()` directly (no shared event bus yet — the TUI
  refactor is deferred)

### 15.3 Static Frontend — Layout and Panels

Build the three-panel layout using vanilla HTML, CSS, and JavaScript.

- [x] **Static assets** — `src/cantrip/web/static/` containing `style.css` and
  `cantrip.js`; server-rendered `index.html.j2` Jinja2 template; no build step,
  no transpilation, no bundler, no framework (inspired by Datastar/htmx philosophy
  of server-first rendering with minimal client-side JS)
- [x] **Two-column layout** — CSS Grid with chat (left, 60%) and task checklist
  (right, 340px); responsive breakpoint at 700px stacks vertically; dark theme
  matching the TUI colour scheme; Juju status panel deferred to a follow-up
- [x] **Task checklist panel** — renders task list with status indicators
  (`✓` done/green, `⟳` active/blue, `○` pending/grey, `◌` blocked/yellow,
  `✗` failed/red) and category badges; new tasks appear dynamically via WebSocket
- [x] **Juju status panel** — `/api/juju-status` endpoint returns app status, unit
  counts, and relations as JSON; `cantrip.js` polls every 15 seconds and renders
  app boxes with status indicators (●/○/◌/✗), coloured borders, unit counts, and
  status messages; panel stacked below task list in the right column
- [x] **Chat panel** — scrollable message history with user/assistant/system messages
  visually distinct (coloured left borders); input area with Enter-to-send; thinking
  indicator with animated dots; plain text with `pre-wrap` (Markdown rendering deferred)

### 15.4 Real-Time Updates

Wire the frontend to the WebSocket for live state updates.

- [x] **WebSocket client** — `cantrip.js` opens a WebSocket connection on load, reconnects
  with exponential backoff (1s → 30s max); dispatches incoming events to DOM update
  functions via a `switch(msg.type)` dispatcher
- [x] **Incremental DOM updates** — `task_updated` finds element by ID and updates
  class/text; `chat_message` appends a new element; `tasks_full` rebuilds the panel;
  `thinking` toggles the indicator; no virtual DOM
- [x] **User input** — chat messages sent as `chat_input` WebSocket frames; server calls
  `agent.process_message()` directly; optimistic UI appends the user message immediately
- [x] **Connection status** — header dot indicator (green/red/yellow) showing
  connected/disconnected/reconnecting; fetches `/api/state` on reconnect to resync

### 15.5 Alternative Views

Mirror the TUI's alternative views in the browser.

- [x] **Logs view** — modal overlay (`L` key) showing `juju debug-log` output fetched
  via `/api/logs` endpoint; 200 lines at INFO level; `<pre>` block with monospace font
- [x] **Model graph view** — modal overlay (`G` key) showing all apps as status-coloured
  cards with unit breakdowns and a relations section; CSS card layout with coloured left
  borders; keyboard shortcut `R` to refresh; `Esc` to close; matching `_renderGraph()` JS
  function and `.graph-app` / `.graph-relations` CSS classes
- [x] **Help overlay** — modal overlay (`?` key) showing keyboard shortcuts table;
  Escape to dismiss
- [x] **Keyboard shortcuts** — `?` for help, `L` for logs, `Escape` to close
  overlays; documented in the help overlay and footer hint bar

### 15.6 Feature Parity Maintenance

Ensure the two UIs stay synchronised as features are added.

- [x] **Shared event contract** — `src/cantrip/ui/events.py` is the single source of truth
  for UI updates; `EventType` enum covers all 8 event types with factory functions that
  build validated, JSON-serialisable payloads; adding a new UI feature means adding an
  event type first, then implementing handlers in both TUI and JS
- [x] **UI integration tests** — `tests/unit/test_ui_events.py` verifies the event contract:
  every event type produces valid JSON with required fields, status values match CSS class
  names, wildcard subscribers receive all types, and all factory functions produce known
  event types; no browser automation required
- [x] **Design documentation** — `UI.md` covers both interfaces with shared architecture
  diagram, event contract table, layout mockup, keyboard shortcuts for both UIs, and
  implementation notes for adding new views

**Exit criteria:** `cantrip --web` opens a browser tab showing the same three-panel layout
as the TUI — task checklist, Juju status, chat — all updating in real time via WebSocket.
A user can run an entire charm-building session from the browser with no loss of
functionality compared to the terminal. Both UIs consume the same event bus, so adding a
new feature to one naturally extends to the other with only a rendering implementation
needed.

---

## Phase 16: Security Event Logging and Tracing Instrumentation Guidance ✓

**Goal:** Ensure charms built by Cantrip emit structured security event logs following the
OWASP Logging Vocabulary, and provide clear guidance on what gets manually instrumented
with tracing versus what ops-tracing handles automatically. The ops framework itself
already implements SEC0045-compliant security logging (see `ops.log._log_security_event`);
charms should extend this pattern for workload-specific security events where appropriate.

### 16.1 Security Event Logging in Generated Charms

The ops framework emits structured security events for framework-level operations:
authorisation failures (`AUTHZ_FAIL`), system restarts (`SYS_RESTART`), uncaught
exceptions (`SYS_CRASH`), and monitoring disablement (`SYS_MONITOR_DISABLED`). These use
the [OWASP Logging Vocabulary](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html)
format: JSON with `datetime`, `level`, `type`, `appid`, `event`, and `description` fields,
logged at Juju TRACE level.

Charms should extend this where the workload has security-relevant events that the
framework cannot know about. Not every charm needs this — a static site charm has no
meaningful security surface — but charms wrapping authentication services, databases,
or network infrastructure should log security events.

- [x] **Identify security-relevant charms** — during the design phase, the agent assesses
  whether the workload has a security surface that warrants event logging. Indicators:
  - Authentication or authorisation (login services, LDAP, OAuth providers)
  - Secret or credential management (vaults, certificate authorities, key stores)
  - Network access control (firewalls, proxies, ingress controllers)
  - Data access (databases, object stores, file servers)
  - System administration (backup tools, monitoring agents, config management)
  If the workload has none of these characteristics, security event logging is skipped
- [x] **Security event helper** — for charms that need it, generate a small helper
  function (in `src/log_security.py` or similar) that wraps `ops.log._log_security_event`
  or reimplements the same structured JSON format. The helper should:
  - Accept OWASP event type, level, event name, and description
  - Include the charm's application ID automatically
  - Use UTC ISO 8601 timestamps
  - Log at Juju TRACE level (security events are structured data for consumption by
    collectors, not operator-facing messages)
- [x] **Workload-specific event types** — extend the OWASP vocabulary with events
  appropriate to the charm's workload. Common patterns:
  - `authn_fail` / `authn_success` — for charms wrapping services with login
  - `authz_fail` / `authz_grant` / `authz_revoke` — for access control changes
  - `secret_rotate` / `secret_access` — for credential lifecycle beyond Juju secrets
  - `config_change` — for security-relevant config changes (TLS mode, allowed networks)
  - `data_export` / `data_delete` — for charms wrapping data stores with audit requirements
  - `sys_monitor_disabled` / `sys_monitor_enabled` — if the charm manages health checks
- [x] **Where to emit events** — guide the agent to emit security events at the right
  points in charm code:
  - Secret lifecycle hooks (`secret-changed`, `secret-rotate`, `secret-expired`)
  - Relation changes that affect access (new database clients, revoked access)
  - Action handlers that perform privileged operations (backup, restore, password reset)
  - Config changes that affect the security posture (TLS settings, network restrictions)
  - Workload log parsing (if the workload logs auth failures, surface them as security events)
- [x] **Never log sensitive data** — the agent must ensure security event descriptions
  never contain credentials, tokens, passwords, or secret content. Log *what happened*
  (e.g. "Secret rotated for relation endpoint 'database'"), not *what the secret contains*

### 16.2 Tracing Instrumentation Guidance

ops-tracing (via `ops_tracing.setup(self)`) automatically instruments the ops framework.
The agent needs clear rules about what is already covered and what warrants manual spans,
to avoid both redundant instrumentation and missing visibility.

**What ops-tracing instruments automatically (do NOT add manual spans for these):**

- Hook execution lifecycle (every Juju event dispatch)
- Pebble API calls (container operations, layer pushes, service management)
- Relation data reads and writes
- Status changes
- Secret operations via the framework
- Charm library calls

**What warrants manual spans (add these where appropriate):**

- [x] **Long-running workload operations** — if the charm orchestrates a multi-step
  workload process (database migration, backup to object storage, cluster join), wrap
  the sequence in a span so traces show the duration and which step failed. Example:
  a database charm's `_run_backup()` method that shells out to `pg_dump`, uploads to S3,
  and verifies the upload
- [x] **External API calls** — if the charm calls external services beyond Pebble (cloud
  APIs, web hooks, DNS providers), span these calls to capture latency and errors.
  ops-tracing only covers the Juju/Pebble boundary, not arbitrary HTTP requests
- [x] **Decision logic with fallback** — if the charm has non-trivial decision logic
  (e.g. "try primary endpoint, fall back to secondary, fall back to degraded mode"),
  span the decision to make the chosen path visible in traces
- [x] **Async or deferred work** — if the charm defers an event and processes it later,
  span the deferred handler separately so traces show the gap between deferral and
  execution

**What should NOT be manually instrumented:**

- Simple event handlers that just call Pebble (already traced)
- Config-changed handlers that update a Pebble layer (already traced)
- Relation-changed handlers that read databag values (already traced)
- Status setting (already traced)
- Any operation that completes in under 100ms with no external calls

- [x] **Update system prompt** — add tracing instrumentation guidance to the system prompt
  (`system.md.j2`) so the agent applies these rules when writing charm code. The guidance
  should be concise — a short "instrument / don't instrument" checklist, not a tracing
  tutorial
- [x] **Update observability skill** — extend the observability skill (`SKILL.md`) with
  the manual instrumentation patterns, including a code example showing `get_tracer()` /
  `start_as_current_span()` usage in a charm context
- [x] **Template support** — for charm templates that include a long-running operation
  (e.g. the database backup pattern), include a manual span in the template code as
  a concrete example

### 16.3 Security Event Collection via COS

Security events logged at Juju TRACE level need to be collected and made queryable.

- [x] **Loki collection** — security events are forwarded to Loki via the existing
  `loki-push-api` relation. Add a LogQL query example to the generated Grafana dashboard
  that filters for `type="security"` events
- [x] **Grafana dashboard panel** — for charms with security event logging, add a
  "Security Events" panel to the generated Grafana dashboard showing a table of recent
  security events with timestamp, level, event type, and description
- [x] **Alert rules for critical events** — generate Prometheus/Loki alert rules for
  `CRITICAL`-level security events (e.g. repeated `authn_fail` suggesting brute force,
  `authz_fail` suggesting misconfiguration)

### 16.4 Integration with Charm Audit (Phase 10)

When auditing existing charms (Phase 10), assess security logging completeness.

- [x] **Security logging audit** — as part of the 10.1 best-practices checklist, assess
  whether the charm's workload has a security surface and whether appropriate events are
  being logged
- [x] **Tracing audit** — check whether ops-tracing is integrated, and whether any
  long-running or external-call operations lack manual spans
- [x] **Remediation tasks** — if the audit identifies missing security logging or tracing
  gaps, generate specific tasks to add them (following the guidance in 16.1 and 16.2)

**Exit criteria:** Charms wrapping security-relevant workloads emit structured OWASP-format
security events for authentication, authorisation, secret lifecycle, and privileged
operations. The agent knows precisely what ops-tracing covers automatically and only adds
manual spans for long-running operations, external API calls, and non-trivial decision
logic. Security events are queryable via Loki and surfaced in Grafana dashboards.

---

## Phase 17: Acceptance Testing — Putting the Charm Through Its Paces ✓

**Goal:** After building and deploying a charm, Cantrip should exercise it the way a real
Juju operator would — running every action, relating it to real workloads, hitting the
service endpoints, checking that the workload actually works, and reporting the results
back to the user. This goes beyond integration tests (which verify charm *code* behaves
correctly) to acceptance tests that verify the *deployed system* works end-to-end. Some of
these are automatable as a test suite; others are exploratory checks that Cantrip performs
live and summarises for the user.

### 17.1 Action Exerciser

Run every action the charm exposes against a live deployment and verify the results.

- [x] **Discover actions** — `ActionExerciserTool` (`action_exerciser`) reads
  `charmcraft.yaml` to enumerate all actions with their parameter schemas
- [x] **Generate action invocations** — `_generate_action_params()` constructs plausible
  parameter values from types, defaults, and enums; destructive-sounding actions (matching
  `delete-`, `destroy-`, `reset-`, `purge-`, `wipe-`, `remove-`, `drop-`, `erase-`,
  `nuke-` prefixes) are skipped by default (`skip_destructive=True`)
- [x] **Run and verify** — executes each action via `juju run <app>/leader` with JSON
  output; captures status (completed/failed/timeout) and output text
- [x] **Report** — produces a Markdown table with action name, parameters, status, and
  notes; includes overall PASS/FAIL verdict and structured `data` dict

### 17.2 Relation Smoke Tests

Deploy commonly related charms and verify the integrations actually work.

- [x] **Identify relation endpoints** — `RelationSmokeTool` (`relation_smoke_test`) reads
  `charmcraft.yaml` to enumerate `requires`, `provides`, and `peers` endpoints with
  interface types; peer relations are noted but skipped (tested via scaling instead)
- [x] **Select relation partners** — `_INTERFACE_PARTNERS` maps 15 common interfaces to
  well-known Charmhub charms (mysql-k8s, postgresql-k8s, traefik-k8s, grafana-k8s,
  prometheus-k8s, loki-k8s, tempo-k8s, etc.); unknown interfaces are skipped with a note
- [x] **Deploy and relate** — deploys each partner charm, relates to the endpoint, and
  waits for the application to settle to active/idle; records success/failure per endpoint
- [x] **Verify data flow** — `_verify_relation_data()` checks that relation databags
  contain meaningful keys beyond standard address fields (ingress-address, private-address,
  egress-subnets); integrated into `RelationSmokeTool` so each relation result now reports
  whether data actually flowed (e.g. "App data keys: connection-string")
- [x] **Report** — produces a Markdown table with endpoint, interface, role, partner,
  status, and notes; includes overall PASS/FAIL verdict

### 17.3 Workload Endpoint Testing

Actually use the deployed workload the way a real user would.

- [x] **Discover endpoints** — `WorkloadEndpointTool` (`workload_endpoint_test`) reads
  container port declarations and config-based port options from `charmcraft.yaml`; also
  accepts explicit endpoint definitions; discovers unit addresses via `juju status`
- [x] **Health checks** — probes common health paths (`/health`, `/ready`, `/healthz`,
  `/readyz`) for each discovered HTTP port via `curl`; TCP port liveness checked via
  `juju ssh` with `/dev/tcp` test
- [x] **Functional probes** — acceptance guidance now instructs the subagent to go
  beyond health checks: use `juju_ssh` to exercise the workload (fetch landing pages,
  run SQL queries, call API endpoints, publish/consume messages); probes are designed
  based on workload type discovered during research; guidance emphasises non-destructive,
  temporary data
- [x] **Report** — produces a Markdown table with endpoint, protocol, status, response
  time, and notes; includes overall PASS/FAIL verdict

### 17.4 Config Variation Testing

Exercise the charm's configuration options to verify they actually take effect.

- [x] **Enumerate config options** — `ConfigVariationTool` (`config_variation_test`) reads
  config options from `charmcraft.yaml` with types, defaults, and descriptions
- [x] **Generate test values** — `_generate_test_value()` produces a non-default value for
  each type: toggle booleans, increment integers, append `-test` to strings; path/directory
  options are skipped to avoid breaking the deployment
- [x] **Apply and verify** — sets each config value via `juju config`, waits for the charm
  to settle to active/idle, and records whether it settled correctly
- [x] **Reset and continue** — restores each option to its default via `juju config --reset`
  before testing the next, to avoid cascading interactions
- [x] **Report** — produces a Markdown table with option, type, test value, settled status,
  and notes; includes overall PASS/FAIL verdict

### 17.5 Upgrade and Lifecycle Testing

Verify the charm handles lifecycle operations gracefully.

- [x] **Scale up/down** — covered by existing `ScalingTestTool` (`scaling_test`); the
  acceptance test subagent guidance directs it to run `scaling_test` as part of the suite
- [x] **Config change under load** — `ConfigUnderLoadTool` (`config_under_load_test`)
  applies a config change while periodically probing a health endpoint via curl; reports
  per-probe status, response time, and overall PASS/FAIL verdict; automatically resets
  config after the test; added to TEST tool allowlist
- [x] **Refresh** — covered by existing `UpgradeTestTool` (`upgrade_test`); refreshes a
  deployed charm with a new `.charm` file and verifies recovery
- [x] **Report** — lifecycle results are included in the consolidated ACCEPTANCE.md via the
  `lifecycle` parameter of `acceptance_report`

### 17.6 Acceptance Test Report

Consolidate all acceptance testing into a single report for the user.

- [x] **ACCEPTANCE.md** — `AcceptanceReportTool` (`acceptance_report`) accepts Markdown
  output from each tool and writes a consolidated `ACCEPTANCE.md` in the charm directory
  with sections for actions, relations, endpoints, config, and lifecycle
- [x] **User presentation** — the tool returns a concise summary suitable for the chat:
  section count and section names
- [x] **Feed back into build** — if acceptance tests reveal problems (broken actions,
  non-functional relations, dead config options), `tasks_after_acceptance_failure()` in
  `autodeploy.py` parses the subagent's verdict text for failing areas and creates a
  targeted BUILD fix task with remediation steps; loop guard via `_ACCEPTANCE_FIX_PREFIX`
  prevents infinite chains; acceptance guidance updated to instruct structured PASS/FAIL
  verdicts per area
- [x] **Planner integration** — acceptance testing is now a standard phase in the build
  pipeline after integration tests pass; `_DESIGN_TO_BUILD_PROMPT` includes acceptance
  test task guidance; `autodeploy.py` chains TEST → acceptance → demo; `_ACCEPTANCE_GUIDANCE`
  overlay in `subagent.py` directs the subagent through the full acceptance suite

**Exit criteria:** After building a charm, Cantrip deploys it, runs every action, relates
it to appropriate partners, hits the workload endpoints, toggles config options, and tests
lifecycle operations — then reports the results to the user. Issues found during acceptance
testing feed back into the build loop as fix tasks. The user gets a concrete "I used your
charm and it works" confirmation, not just "the tests passed".

---

## Phase 18: Agent Framework Evaluation — Build vs. Adopt ✓

**Goal:** Investigate whether Cantrip would benefit from adopting an established agent
framework (e.g. LangGraph, CrewAI, Claude Agent SDK, AutoGen, or similar) rather than
continuing to build its own agent infrastructure from scratch. The current architecture
(two-loop design, work queue, subagents, tool dispatch) is hand-rolled; this phase evaluates
whether an existing framework would give us better primitives, reduce maintenance burden, or
unlock capabilities we'd struggle to build ourselves — or whether the control and simplicity
of our bespoke approach remains the right trade-off.

### 18.1 Landscape Survey

Map the current agent framework ecosystem and identify viable candidates.

- [x] **Identify candidates** — surveyed 8 frameworks: Claude Agent SDK, LangGraph,
  CrewAI, OpenAI Agents SDK, AutoGen/MS Agent Framework, Pydantic AI, smolagents,
  and DSPy; documented version, stars, licence, async support, multi-LLM, multi-agent
- [x] **Feature matrix** — full comparison table in FRAMEWORK_EVALUATION.md covering
  all dimensions; identified Claude Agent SDK, LangGraph, and Pydantic AI as
  shortlisted candidates
- [x] **Disqualify early** — eliminated OpenAI Agents SDK (single-provider), DSPy
  (wrong category — pipeline optimiser, not agent orchestrator), smolagents
  (code-first execution model incompatible with structured tool calls), AutoGen/MS
  Agent Framework (excessive complexity, conversation-centric model)

### 18.2 Architecture Mapping

Map Cantrip's current architecture onto each shortlisted framework to understand fit.

- [x] **Component mapping** — mapped all 12 Cantrip components against each shortlisted
  framework; Claude Agent SDK maps well for inner loop but has no work queue/executor;
  LangGraph has the most flexible orchestration but heaviest abstraction cost;
  Pydantic AI is lightest touch with best Python ergonomics
- [x] **Gap analysis** — no framework supports persistent work queues with dynamic task
  generation, concurrent subagents, noop detection, or pure routing state machines;
  these are Cantrip's most distinctive features; migration effort 2–6 weeks for
  partial benefit
- [x] **Gain analysis** — frameworks offer type-safe tool schemas (Pydantic AI),
  checkpointing (LangGraph), built-in file/bash tools (Claude Agent SDK), and
  community maintenance; gains are modest given Cantrip's existing implementations

### 18.3 Proof of Concept

Build a small spike with the most promising candidate(s).

- [x] **Select top 1–2 candidates** — selected Claude Agent SDK (closest subagent model)
  and Pydantic AI (lightest touch, best ergonomics) for detailed assessment
- [x] **Spike implementation** — performed desk spike comparing code patterns for
  conversation loop, work queue, and tool system across frameworks; concluded that
  frameworks save ~50 lines in the inner loop but provide nothing for the outer loop
  (work queue + executor + routing) that constitutes 60%+ of Cantrip's agent code
- [x] **Evaluate ergonomics** — Pydantic AI's @agent.tool decorator is the most
  Pythonic; Claude Agent SDK's subagent model maps cleanly; LangGraph's graph model
  is powerful but awkward for dynamic task generation
- [x] **Measure overhead** — estimated 1–4 new dependencies, 2–6 weeks migration,
  ongoing abstraction tax varies from low (Pydantic AI) to high (LangGraph)

### 18.4 Decision and Recommendation

Synthesise findings into a clear recommendation.

- [x] **Write FRAMEWORK_EVALUATION.md** — comprehensive decision document covering
  8 candidates surveyed, 3 shortlisted, detailed architecture mapping tables,
  desk spike code comparisons, gap/gain analysis, and trade-off matrix across
  control, maintenance, velocity, lock-in, and migration cost
- [x] **Identify hybrid options** — recommended two targeted adoptions: (1) adopt
  Pydantic AI's `@agent.tool` decorator *pattern* (not the library) for cleaner
  tool schemas, and (2) keep Claude Agent SDK on radar as future migration target
  if multi-provider support is ever dropped
- [x] **Present to user** — recommendation: stay bespoke; the two-loop architecture
  is Cantrip's competitive advantage, not its technical debt; no framework
  supports persistent work queues with concurrent subagents

**Exit criteria:** A written evaluation document with a clear, evidence-based recommendation
on whether to adopt an agent framework, stay with the bespoke approach, or take a hybrid
path. If adoption is recommended, the document includes a migration sketch. If staying
bespoke, the document articulates what we'd be giving up and why that's acceptable.

**Decision:** Stay bespoke. Two hybrid options identified for future work:

1. **Adopt Pydantic AI's `@agent.tool` decorator pattern** — add a `@tool` decorator
   to the `Tool` base class that auto-generates JSON Schema from type hints and
   docstrings, eliminating the manual `parameters` property on each tool. This borrows
   the *pattern*, not the library — no new dependency. Would reduce boilerplate across
   40+ tools. Estimated effort: 1 day.

2. **Keep Claude Agent SDK as a migration target** — if Cantrip ever drops
   multi-provider support (i.e. Claude becomes the only model), the Agent SDK's
   subagent model, session management, and built-in tools map well to Cantrip's
   inner loop. Revisit if the provider landscape changes.

Full analysis: [`design/FRAMEWORK_EVALUATION.md`](design/FRAMEWORK_EVALUATION.md).

---

## Phase 19: Operational Readiness Assessment ✓

**Goal:** Evaluate charms against Canonical's
[Operational Readiness Metrics](https://docs.google.com/document/d/1lStJjBGW7lyojgBhxGLUNnliUocYWjAZ1VEbbVduX54/edit?usp=sharing)
standard and autonomously close gaps. The spec defines what makes a solution
production-ready from the perspective of Managed Solutions — covering status
reporting, operational actions, observability, diagnostics, documentation,
backup/restore, upgrade procedures, and security posture. Cantrip should be
able to assess a charm against this standard, report the score, and implement
the improvements it can.

This phase is distinct from Phase 10 (code quality and listing readiness) and
Phase 17 (acceptance testing). Phase 10 asks "is the code good?", Phase 17
asks "does the charm work?", and this phase asks "is the charm ready for
production operations?"

### 19.1 Operational Readiness Assessment Tool

A deterministic assessment tool modelled on the existing `charm_audit` pattern.

- [x] **`OperationalReadinessTool`** (`operational_readiness`) — evaluates a charm
  against Canonical's operational readiness metrics; produces a structured report
  scored by pillar (Best Practices, Documentation, Reliability, Maintainability,
  Security); added to RESEARCH and BUILD tool allowlists
- [x] **Best Practices checks** — deterministic checks for status reporting (8
  conditions: missing config, conflicting config, upstream unreachable, paused,
  stopped/crashed, missing relations, incomplete relations, upgrade in progress);
  common operational actions (get-health, pause, resume with aliases); action
  quality (descriptions, parameter docs); configuration quality (type, default,
  description per option)
- [x] **Documentation checks** — verify presence of installation, configuration,
  usage, troubleshooting, management, upgrade, and backup docs in README or docs/
- [x] **Reliability checks** — health-check action, backup/restore actions,
  graceful shutdown (stop/remove event handler)
- [x] **Maintainability checks** — full COS observability (4 interfaces),
  diagnostics/SOS action, upgrade pre-flight checks
- [x] **Security checks** — TLS/encryption (relations or code), Juju secrets
  usage (flags plain-text password config), certificate management actions
- [x] **Scoring** — each check is pass/fail; per-pillar scores as percentages;
  findings categorised as must-fix, should-fix, and advisory
- [x] **Advisory items** — platform compatibility, reference architectures,
  escalation methods, long-term stability testing, SSDLC compliance flagged
  as organisational items requiring team action

### 19.2 Operational Readiness Skill

Domain knowledge for subagents implementing operability features.

- [x] **`operational-readiness` skill** (`skills/operational-readiness/SKILL.md`) —
  comprehensive guidance covering: status reporting patterns (reconciliation
  method, all condition types with code examples); health-check action (process,
  API, relation, certificate checks); pause/resume (Pebble stop/start, paused
  state persistence); backup/restore (workload-native tools, timestamps,
  encryption); diagnostics bundle (scrubbed config, status, relations, logs);
  upgrade pre-flight (version compat, cluster health, backup freshness,
  resources); certificate management (view/regenerate actions); secret rotation
  (Juju secrets API, secret-rotate event handling)

### 19.3 Operability Phase in the Planner

Integrate operational readiness assessment into the autonomous build pipeline.

- [x] **Assessment task** — after acceptance testing completes, `tasks_after_acceptance()`
  in `autodeploy.py` spawns an operability assessment RESEARCH task (parallel with
  demo generation); `plan_operability_assessment()` creates the full assessment →
  confirm pipeline with dependency on acceptance
- [x] **Gap confirmation** — a CONFIRM task presents the readiness report to the user;
  `plan_operability_fixes()` generates categorised BUILD tasks after confirmation
- [x] **Operability fix tasks** — `plan_operability_fixes()` generates BUILD tasks for
  each confirmed gap category: `implement-status-reporting`, `implement-operational-actions`,
  `implement-backup-restore`, `implement-upgrade-procedures`, `improve-observability-completeness`,
  `improve-security-posture`, `improve-operational-docs`; each loads the
  `operational-readiness` skill
- [x] **Validation** — a `reassess-operational-readiness` RESEARCH task depends on all
  fix tasks and re-runs the tool to verify the score improved
- [x] **Improvement mode integration** — `plan_improvement_fixes()` now appends an
  `assess-operational-readiness` RESEARCH task after the deploy-verify step, running
  in parallel with the diff review; the improvement pipeline evaluates production
  readiness after all code-quality fixes are deployed

### 19.4 Operational Readiness Report

Produce a persistent artefact summarising the charm's production readiness.

- [x] **OPERATIONAL_READINESS.md** — the tool writes a Markdown report with per-pillar
  summary scores, individual [PASS]/[FAIL] checks, and an Advisory section for
  organisational items
- [x] **Machine-readable output** — `data` dict contains: `overall_score`, `total_passed`,
  `total_checks`, `pillar_scores` (per-pillar passed/total/percentage), `checks` (list
  of name/pillar/passed/detail dicts), and `findings` (must_fix/should_fix/advisory lists)
- [x] **Chat presentation** — the tool's `output` field contains the full scored report;
  the subagent's guidance instructs it to summarise per-pillar scores and must-fix items

**Exit criteria:** Cantrip assesses a charm against Canonical's Operational Readiness
Metrics, produces a scored report by pillar, and autonomously implements the
improvements it can — status reporting, health checks, pause/resume, backup/restore,
diagnostics, upgrade pre-flight, and observability completeness. Organisational items
(escalation methods, reference architectures, long-term stability testing) are flagged
as recommendations. The user gets a clear picture of how production-ready their charm
is and what remains to be done by the team.

---

## Phase 20: Deep Juju Introspection ✓

**Goal:** Give the agent deeper visibility into Juju runtime state — relation
databags, application config, secrets, cross-model offers — so it can autonomously
diagnose integration failures, config issues, and topology problems instead of
guessing from status output alone.

Inspired by [JujuMate](https://github.com/Abuelodelanada/jujumate), a K9s-style
read-only TUI for Juju built on Textual + python-libjuju. JujuMate demonstrates
that rich introspection (relation data, secrets, app config with source tracking,
cross-model offers, WebSocket log streaming) is practical and valuable for
diagnosing charm issues. Cantrip currently has surface-level Juju visibility
(status + debug-log); this phase adds the deeper introspection the agent needs
to debug the most common failure modes autonomously.

### 20.1 Relation Databag Inspection

Relation data mismatches are the most common charm integration failure. The agent
needs to read raw databag contents to diagnose why integrations aren't working.

- [x] **`read_relation_data` tool** — `JujuReadRelationDataTool` (`juju_read_relation_data`)
  reads app-level and unit-level relation databags via `juju show-unit --format json`;
  returns structured data with application data, local unit data, and related units'
  data; supports endpoint filtering; added to RESEARCH, BUILD, DEBUG, and TEST allowlists
- [x] **Databag diffing** — the tool highlights asymmetries: keys present in remote
  units but missing from the local unit are flagged (excluding standard address keys)
- [x] **Watcher integration** — the status-diffing watcher optionally snapshots
  relation databag key sets via `juju show-unit` and detects when keys are
  added or removed, emitting `databag_change` events; opt-in via
  `WatcherConfig(snapshot_databags=True)` to avoid extra subprocess cost

### 20.2 Application Config Inspection

The agent needs to distinguish default config values from user-set values to
debug "why isn't my config taking effect?" issues.

- [x] **`get_app_config` tool** — `JujuGetAppConfigTool` (`juju_get_app_config`) reads
  all configuration values with source tracking (default/user/model-default) via
  `juju config <app> --format json`; marks user-set values with `*`; returns structured
  data with per-option name, value, type, source, and description; added to RESEARCH,
  BUILD, DEBUG, and TEST allowlists
- [x] **Config validation** — `_validate_config_against_charm()` cross-references
  deployed config keys against `charmcraft.yaml` (or `config.yaml`) declarations;
  detects undeclared/deprecated keys and declared-but-absent keys; triggered via
  the `charm_path` parameter on `juju_get_app_config`

### 20.3 WebSocket Log Streaming

Replace or supplement the current SSH-to-Loki polling with direct WebSocket
streaming from the Juju controller, removing the dependency on COS being deployed
for basic log access.

- [x] **Direct log streaming** — `cantrip.juju.log_stream` module provides
  async generators that tail `juju debug-log --tail` for real-time log delivery;
  avoids the complexity of direct controller WebSocket connections while still
  providing live streaming; web server gains `/api/logs-stream` WebSocket
  endpoint for browser-based live log streaming
- [x] **Agent log tool** — new `JujuStreamLogsTool` (`juju_stream_logs`) returns
  batches of live log lines with level and unit filtering; added to DEBUG
  subagent tool allowlist
- [x] **TUI log viewer upgrade** — the F3 log viewer gains a streaming mode
  (press `t` to toggle) that tails logs in real time via the log_stream module;
  the static fetch mode (`r` to refresh) is preserved as the default

### 20.4 Cross-Model Offer Awareness

For complex multi-model deployments, the agent needs to understand the broader
topology beyond the current model.

- [x] **`list_offers` tool** — `JujuListOffersTool` (`juju_list_offers`) lists
  cross-model offers from `juju status` with app, charm, endpoint interfaces,
  and active/total connection counts; added to RESEARCH and DEBUG allowlists
- [x] **Offer topology in watcher** — `OfferSnapshot` frozen dataclass captures
  cross-model offers; `diff_snapshots()` detects new/removed offers and
  connection count changes, emitting `new_offer`, `removed_offer`, and
  `offer_connection_change` events with instructions to run `juju_list_offers`
- [x] **Multi-controller awareness** — the watcher and list_offers tool track
  offer connection counts across models; full multi-controller inspection
  (querying both sides of a CMR) is deferred to Phase 22

### 20.5 Secrets Inspection

For charms that use Juju secrets, the agent needs to verify secrets are
correctly created and granted.

- [x] **`list_secrets` tool** — `JujuListSecretsTool` (`juju_list_secrets`) lists all
  Juju secrets in the model with owner, revision, rotation policy, description, and
  access grants; supports filtering by owner; added to RESEARCH and DEBUG tool allowlists
- [x] **Secret content inspection** — `JujuShowSecretTool` (`juju_show_secret`) inspects
  a specific secret by name or URI; optionally reveals content via `reveal=True` parameter;
  added to RESEARCH and DEBUG tool allowlists

### 20.6 TUI Status Enhancements

Improve the TUI status display with lessons from JujuMate's presentation.

- [x] **Subordinate unit tree** — `AppBox` renders each unit with its status
  indicator, and nests subordinate units indented with a `└` prefix under
  their principal unit using Jubilant's `UnitStatus.subordinates` dict
- [x] **Relation detail panel** — new `RelationDetailScreen` modal fetches
  databag contents via `juju show-unit` and displays local/remote application
  data with asymmetry highlighting; `RelationLine` is now clickable, posting
  a `Selected` message with endpoint and related_app metadata
- [x] **Inline filtering** — `/` key opens a filter input that matches
  case-insensitively against app names, unit names, relation names, status
  keywords, and status messages; `Escape` clears the filter and hides the input
- [x] **Theming support** — `tui/themes.py` ships 5 bundled themes (cantrip,
  ubuntu, monokai, solarized-dark, light) registered via Textual's native
  Theme API; user themes loaded from `~/.config/cantrip/themes/*.yaml` if
  PyYAML is installed; `--theme` CLI flag selects the active theme at startup

**Exit criteria:** The agent can autonomously diagnose integration failures by
reading relation databags, detect config issues by comparing deployed vs default
values, stream logs without COS, and inspect cross-model offers and secrets.
The most common charm debugging scenarios — "why isn't my integration working?",
"why isn't my config taking effect?", "what's in the logs?" — are answerable
without the user needing to run manual Juju commands.

---

## Phase 21: Orchestrator Hardening — Lessons from orc ✓

**Goal:** Harden the autonomous work loop with patterns proven in
[orc](https://github.com/PietroPasotti/orc), Pietro Pasotti's multi-agent
orchestrator. Full analysis in [`design/orc-analysis.md`](design/orc-analysis.md).

This phase addresses three categories: **reliability** (preventing infinite
loops, handling crashes), **testability** (making the executor testable without
LLM calls), and **isolation** (scoping what subagents can access).

### 21.1 Pure State Machine for Work Queue Routing

Extract the "what happens next" decision from the executor into a pure function
over a data snapshot, following orc's `route(WorldState) → action` pattern.

- [x] **`WorkQueueState` dataclass** — frozen snapshot capturing everything that
  influences the next-task decision: task count by status, active subagent count,
  max concurrency, paused/draining flags, charm path and dev model presence;
  `TaskInfo` frozen dataclass for individual task snapshots; `snapshot_from_queue()`
  builds the snapshot from live `AgentTask` objects
- [x] **`route()` pure function** — maps a `WorkQueueState` to a `RoutingDecision`
  (spawn task, wait for confirmation, wait for in-flight, idle). No I/O, no side
  effects. The executor's `_run_loop` now delegates to `route()` for every
  scheduling decision
- [x] **Cross-check tests** — parametrised tests that run both `route()` and the
  real `WorkQueue.all_ready()`, asserting they agree on task selection, confirm
  handling, dependency chains, concurrency limits, and pause behaviour
- [x] **Deadlock-freedom verification** — BFS over 93 reachable `WorkQueueState`
  values (0–2 tasks × all status/category/paused/draining combinations) proves
  every non-terminal, non-paused state has a path to progress; also verifies
  all `RouteAction` values are reachable

### 21.2 Protocol-Based Service Injection for Executor

Replace direct dependencies in the executor and subagent runner with Protocol-
typed service interfaces, making the autonomous loop testable without real LLM
calls, Juju, or git.

- [x] **Service protocols** — `src/cantrip/agent/services.py` defines
  `runtime_checkable` Protocol interfaces: `GitService` (fingerprint, snapshot,
  revert, uncommitted check), `StateService` (record_event, record_usage,
  save_tasks), `EnvironmentChecker` (pre-task validation), `FollowupPlanner`
  (post-task follow-up creation), `SubagentRunner` (subagent invocation)
- [x] **Fake implementations** — `FakeGitService`, `FakeStateService`,
  `FakeEnvironmentChecker`, `FakeFollowupPlanner` in `tests/conftest.py`;
  each mirrors its Protocol with minimal in-memory state; `_make_executor()`
  test helper wires all fakes together
- [x] **Executor refactor** — `BackgroundExecutor` accepts optional `git_service`,
  `env_checker`, `state_service`, and `followup_planner` via keyword-only
  constructor parameters; when not provided, default implementations delegate
  to subprocess calls and `SessionStore` (full backward compatibility);
  `_SessionStoreAdapter` bridges the existing `SessionStore` to the
  `StateService` protocol

### 21.3 Noop Detection

Detect subagents that exit successfully but accomplish nothing, preventing the
autonomous loop from spinning indefinitely.

- [x] **State snapshot before/after** — `_fingerprint()` in the executor captures
  git HEAD hash + `git status --porcelain` before and after subagent execution;
  lightweight and runs in <1s
- [x] **Noop detection** — `_is_noop()` compares before/after fingerprints; if
  identical, the task is reset to PENDING for another attempt and `noop_count`
  is incremented on the `AgentTask` dataclass
- [x] **Noop escalation** — after `_MAX_NOOP_COUNT` (default 2) consecutive noops,
  the task is blocked with a descriptive reason; the conversation loop presents
  it to the user for guidance

### 21.4 Two-Stage Graceful Shutdown

Handle SIGINT/SIGTERM cleanly in the autonomous work loop.

- [x] **Drain mode** — `drain()` method pauses the poll loop and waits for all
  in-flight subagent tasks to finish before persisting state and stopping; the
  `draining` property tracks drain state
- [x] **Force shutdown** — `force_stop()` cancels all in-flight async tasks
  immediately, resets ACTIVE tasks to PENDING, persists state, and stops
- [x] **Task state cleanup** — `_cleanup_active_tasks()` resets any ACTIVE tasks
  to PENDING; called automatically on `start()` (recovering from interrupted
  sessions) and on `force_stop()`

### 21.5 Structured Subagent Exit Contracts

Define explicit exit states for subagents so the executor can reliably
determine what happened.

- [x] **Exit state enum** — `ExitState` StrEnum with values: `completed`, `blocked`,
  `failed`, `noop`; `SubagentResult` frozen dataclass with `exit_state`, `summary`,
  and `detail`; `_parse_exit_state()` extracts the state from the LLM's final response
  using regex (`[EXIT: completed]` format) with heuristic fallbacks
- [x] **Mandatory signalling** — subagent system prompt now includes an "Exit
  signalling" section requiring every response to end with an `[EXIT: state]` tag;
  instructs subagents to never produce bare text while work is pending
- [x] **Result recording** — the executor records exit state and round count in the
  session store via `record_event("subagent_exit", ...)`; the executor now handles
  `blocked` and `failed` exit states directly (blocking or failing the task) and
  combines `noop` exit state with fingerprint-based noop detection

### 21.6 Scoped Tool Access per Task Category

Limit what tools each subagent category can use, reducing the blast radius of
mistakes.

- [x] **Task-category tool allowlists** — `_CATEGORY_TOOLS` dict in `subagent.py`
  maps each `TaskCategory` to a `frozenset` of allowed tool names; covers all
  seven categories (RESEARCH, BUILD, DEPLOY, TEST, DEBUG, INFRA, CONFIRM)
- [x] **Category-based scoping** — `_filter_tools()` in `subagent.py` filters the
  full tool list to only those in the category's allowlist; called in the `Subagent`
  constructor so each subagent only sees its permitted tools in the LLM context

**Exit criteria:** The autonomous work loop has a formally verified state
machine, is testable without LLM or infrastructure dependencies, detects and
escalates subagent noops, shuts down gracefully, and scopes subagent tool access
by task category. The executor is no harder to test than a pure function.

---

## Phase 22: COS on Multi-Controller Environments ✓

**Status:** Complete
**Goal:** COS-lite deploys and integrates correctly regardless of whether the
development controller is LXD or K8s, using cross-model relations when the COS
model lives on a different controller.

Currently, `cos-lite` contains only Kubernetes charms (`alertmanager-k8s`,
`grafana-k8s`, `prometheus-k8s`, `loki-k8s`, `traefik-k8s`). When the
development controller is LXD (as with `concierge -p dev`), there is typically a
separate K8s controller (`concierge-k8s`) already bootstrapped. Preflight
currently skips COS deployment when the active controller is not K8s.

### 22.1 — Detect K8s controller for COS ✓

`_find_k8s_controller()` enumerates all registered controllers via
`juju controllers --format json` and returns the first with a K8s cloud.
`list_controllers()` returns a list of all controllers with name, cloud,
`is_k8s` flag, and model count for multi-controller reporting.

### 22.2 — Cross-model COS integration ✓

`_ensure_cos()` now detects IAAS controllers and creates the COS model on a
discovered K8s controller via `_create_model_on_controller()`. After deploying
cos-lite, `_setup_cos_cross_model_offers()` creates offers for grafana,
prometheus, loki, and tempo endpoints. Machine charms use `grafana-agent`
(snap-based); K8s charms use `grafana-agent-k8s` (sidecar).

### 22.3 — Preflight multi-controller awareness ✓

`PreflightResult` gains `controllers` list (all registered controllers with
cloud type), `cos_controller` field (which controller hosts COS), and
`is_cross_controller` property. Controller enumeration runs automatically
in `_ensure_cos()` before COS deployment decisions.

### 22.4 — System prompt and skill updates ✓

System prompt adds cross-model COS guidance in the Default Integrations
section. Observability skill gains a full multi-controller deployment
section with offer/consume commands for both machine and K8s charms.
Build subagent guidance adds cross-model COS integration note.

**Outcome:** COS observability works out of the box on both `concierge -p k8s`
(single controller) and `concierge -p dev` (LXD + K8s dual controller)
environments, with the agent handling the cross-model wiring automatically.

---

## Phase 23: End-to-End Testing and Bug Fixes ✓

**Goal:** Exercise Cantrip against a real Juju environment and fix what breaks.

### 23.1 — Snap Confinement Fix ✓

The Juju snap uses strict confinement and cannot read files outside `$HOME`.
When Cantrip builds a charm in `/tmp` (common in CI and testing), `juju deploy`
fails with "no charm was found".

- [x] **Deploy tool workaround** — `JujuDeployTool.execute()` detects when a `.charm`
  file is outside `$HOME` and copies it to `~/snap/juju/common/` before deploying;
  the temp copy is cleaned up in a `finally` block
- [x] **Refresh tool workaround** — same fix applied to `JujuRefreshTool.execute()`
- [x] **Unit tests** — 4 tests covering copy-on-deploy, no-copy-in-home, cleanup-on-success,
  and cleanup-on-error

### 23.2 — E2E Integration Tests ✓

Integration tests that exercise real tools against the live Juju environment.

- [x] **Juju tools** — `juju_status` against real controller (default model, named model,
  non-existent model)
- [x] **File tools** — write/read round-trip, list directory, edit file (real filesystem)
- [x] **Preflight** — warm-up detects juju, prepare finds controller and discovers
  multi-controller topology
- [x] **Snap confinement** — deploy with `.charm` from `/tmp` copies to snap-accessible path
- [x] **State persistence** — save/load session and task round-trips via SQLite

---

## Phase 24: Charm Linter (`charmlint`) ✓

**Goal:** Extract the charm-quality knowledge embedded in Cantrip's audit and
operational readiness tools into a standalone, deterministic linter that can
run independently from the CLI, as a library, or in pre-commit hooks — just
like ruff or pylint, but for Juju charms.

Cantrip's `CharmAuditTool` and `OperationalReadinessTool` contain dozens of
deterministic checks (COS integration, deprecated APIs, test presence,
metadata completeness, config quality, status reporting, security). These
checks are currently locked inside the agent tool infrastructure. Extracting
them into a standalone package makes them useful beyond Cantrip and provides
a fast feedback loop for charm developers.

### 24.1 Standalone Package

A new top-level `src/charmlint/` package with zero Cantrip dependencies.

- [x] **Core models** — `Diagnostic`, `Severity`, `CharmContext`, `LintReport`
  dataclasses; `Rule` ABC with automatic registration via `__init_subclass__`;
  rule registry for discovery
- [x] **Linter engine** — `build_context()` loads all charm data once
  (metadata, actions, config, Python sources, README, test directories);
  `lint()` runs all enabled rules and collects diagnostics; config-based
  filtering (select, ignore, severity overrides, minimum severity)
- [x] **Configuration** — `.charmlint.yaml` config file with per-rule severity
  overrides, category-level select/ignore, and minimum severity filter

### 24.2 Rule Set (35 Rules, 10 Categories)

Rules extracted from `CharmAuditTool` and `OperationalReadinessTool`.

- [x] **Metadata** (META001–META007) — name, display-name, summary,
  description, docs/issues/source URLs
- [x] **Observability** (COS001–COS005) — tracing, metrics-endpoint,
  logging, grafana-dashboard relations; ops-tracing dependency
- [x] **Testing** (TEST001–TEST003) — unit test presence, integration test
  presence, deprecated Harness usage
- [x] **Deprecated APIs** (DEP001–DEP003) — StoredState, Harness import,
  framework.breakpoint
- [x] **Libraries** (LIB001–LIB002) — fetch-libs imports with known PyPI
  equivalents; unknown libraries flagged for manual check
- [x] **Actions** (ACT001–ACT005) — expected operational actions (get-health,
  pause, resume with aliases); action and parameter description completeness
- [x] **Config quality** (CFG001–CFG003) — type, default, description for
  each config option
- [x] **Status reporting** (STS001–STS003) — BlockedStatus for missing/invalid
  config; status for missing relations
- [x] **Security** (SEC001–SEC002) — secret-like config options without Juju
  secrets API; TLS support detection
- [x] **Structure** (STR001–STR003) — licence, icon, type annotations

### 24.3 CLI

Ruff-style command-line interface with text and JSON output.

- [x] **CLI entry point** — `charmlint /path/to/charm` with `--format`,
  `--select`, `--ignore`, `--severity`, `--config`, `--strict` flags
- [x] **Text output** — ruff-style `path:line: RULE message` format with
  summary line
- [x] **JSON output** — machine-readable report with diagnostics array
- [x] **Exit codes** — 0 for clean, 1 for errors, 2 for warnings with
  `--strict`
- [x] **`python -m charmlint`** — module entry point
- [x] **pyproject.toml** — `charmlint` console script entry point

### 24.4 Tests

- [x] **58 unit tests** — models, config, linter engine, CLI, and every rule
  category; fixture helpers for creating charm directories with various
  configurations

**Exit criteria:** `charmlint /path/to/charm` runs independently, reports
issues in ruff-style format with configurable severity and filtering, and
all 35 rules have passing tests. The package has zero Cantrip dependencies
and can be installed and used standalone.

---

## Phase 25: Code Health

**Goal:** Address technical debt, security issues, and inconsistencies
identified during a comprehensive code review. Items are grouped by severity
and numbered for cross-reference.

### 25.1 Critical — Bare `Exception` Catches

Replace every bare `except Exception` with specific exception types, per the
project style guide ("Never catch bare `Exception`"). Locations:

- [x] `agent/tools/base.py` — `execute_tool()` catch-all
- [x] `cli.py` — REPL error handler
- [x] `llm/inference_snap.py` — `contextlib.suppress(Exception)` around response text
- [x] `tests/eval/scorer.py` — checker invocation
- [x] `tests/e2e/test_real_charm_build.py` — model destroy, create, status poll (×4)
- [x] `tests/live/test_juju_live.py` — model destroy in fixture
- [x] `web/server.py` — juju status fetch and chat error handler
- [x] `ui/events.py` — event subscriber dispatch
- [x] `tui/screens/logs.py` — `contextlib.suppress(Exception)` in title update

### 25.2 Critical — Shell Injection in Watcher

- [x] `agent/watcher.py` Loki polling constructs a Python script via f-string and
  passes it through SSH. Use `shlex.quote()` or argument-list approach to prevent
  injection if the URL contains special characters.

### 25.3 Critical — `pyproject.toml` Target Version Mismatch

- [x] `target-version = "py311"` but `requires-python = ">=3.12"`. Update to `"py312"`.

### 25.4 High — Duplicated `_run_juju()` Across Tool Modules

- [x] Extract the `_run_juju()` and `_wait_for_app()` helpers (duplicated in
  chaos.py, scaling.py, upgrade.py, acceptance.py) into `juju_subprocess.py`.

### 25.5 High — Duplicated `_get_system_prompt()` Across LLM Providers

- [x] claude.py and gemini.py had identical `_get_system_prompt()` methods.
  Moved to `LLMProvider` base class; inference_snap.py extracts inline (different pattern).

### 25.6 High — Duplicated Light Provider Resolution

- [x] `tui/app.py` and `cli.py` both contained the same provider selection
  logic. Extracted to `resolve_light_provider()` in `cantrip.llm`.

### 25.7 High — `core.py` Streaming Duplication

- [x] `process_message()` and `process_message_streaming()` shared 90%+ code.
  Extracted common `_run_conversation_loop()`. Also fixed the streaming path
  which was missing the `<tool_result>` wrapper (inconsistency with non-streaming).

### 25.8 High — Long Functions Needing Decomposition

- [x] `watcher.py:diff_snapshots()` (~200→15 lines) — split into `_diff_apps`,
  `_diff_units`, `_diff_offers` helpers
- [x] `charm/terraform.py:_generate_variables_tf()` (150→45 lines) — data-driven specs
- [x] `subagent.py:_build_subagent_prompt()` (133→20 lines) — extracted
  `_charm_context_section`, `_guidance_sections`, `_handoff_sections`, and
  moved static text to module-level constants
- [x] `executor.py:_execute_task()` (134→40 lines) — extracted `_fail_task` and
  `_handle_result` helpers; three duplicate except blocks collapsed via shared helper
- [x] `preflight.py:_ensure_cos()` (107→20 lines) — split into `_check_cos_model`,
  `_create_cos_model`, `_deploy_cos_lite`, `_create_cos_offers` helpers
- [x] `gemini.py:_convert_messages()` (75→20 lines) — extracted `_convert_user_message`,
  `_convert_assistant_message`, `_convert_tool_message` helpers

### 25.9 Medium — Import Style Violations

- [x] `core.py` — replaced `Tool as LLMTool` / `ToolResult as LLMToolResult` aliases
  with `from cantrip.llm import base as llm` and qualified `llm.Tool`, `llm.ToolResult`
- [x] `subagent.py`, `context.py`, `planning.py`, `audit.py` — moved local imports
  to module top
- [x] `tui/app.py` — imports widget/screen modules (`from cantrip.tui.widgets
  import chat as chat_widget`) instead of class names directly

### 25.10 Medium — Fragile String Matching

- [x] `watcher.py` — replaced substring `"hook failed"` with compiled `\bhook failed\b` regex
- [ ] `charm.py` — string replacement for code injection is brittle
- [ ] `autodeploy.py` — loose keyword matching in free-form text

### 25.11 Medium — TUI Reactive Boilerplate

- [x] `modelbar.py` — 13 identical `watch_*` methods replaced with programmatic
  generation from attribute list
- [x] `statusbar.py` — 4 identical watcher methods replaced the same way

### 25.12 Medium — Encapsulation Violations in `tui/app.py`

- [x] Added `compaction_threshold` property to `ContextManager` and `store`
  property to `CantripAgent`; TUI no longer reaches into private members.

### 25.13 Medium — `claude_md.md.j2` References `tox` Instead of `uv`/`make`

- [x] Generated CLAUDE.md no longer hardcodes `tox` — references `tox` (if
  present), `make`, or direct `ruff`/`pytest` commands as appropriate.

### 25.14 Medium — Missing Error Handling in `terraform.py`

- [x] `generate_terraform_module()` — added try/except around `yaml.safe_load()`
  and validation of required `name` key before access.

### 25.15 Medium — Overly Broad Exception Grouping in `executor.py`

- [x] Split into two handlers: LLM provider errors (transient) and general code
  errors (OSError, ValueError, etc.) for clearer diagnostics.

### 25.16 Medium — Silent Failures in `core.py`

- [x] `handle_design_confirmation()`, `handle_day2_confirmation()`,
  `handle_improvement_confirmation()` now log at ERROR level (not WARNING)
  when task or result not found.

### 25.17 Low — Dead Code / Unused Declarations

- [x] `tui/widgets/chat.py` — removed unused reactive `messages` attribute and import
- [~] `core.py` — `db_path` and `old_dir` resolve to the same path (intentional — migration logic; not a bug)

### 25.18 Low — Magic Strings Without Constants

- [x] `tui/app.py` — `"confirm-improvements"` replaced with
  `IMPROVEMENT_CONFIRM_BASE` constant; `planner.py` defines matching
  `DESIGN_CONFIRM_BASE`, `DAY2_CONFIRM_BASE`, `OPERABILITY_CONFIRM_BASE`
- [ ] `main.py` — magic string checks for project identity
- [ ] Status indicators, CSS classes, log levels scattered throughout TUI widgets

### 25.19 Low — `git.py` Hardcodes `--no-gpg-sign`

- [x] `GitCommitTool` now respects `CANTRIP_GPG_SIGN=1` (truthy values:
  `1`/`true`/`yes`/`on`) to opt in to signing; default remains `--no-gpg-sign`
  so automated commits don't hang on passphrase prompts.

### 25.20 Low — Missing Test Coverage ✅

- [x] Invalid YAML input to terraform generation
- [x] IPv6 handling in `web.py` private URL detection
- [x] Error-path tests for file operations

**Exit criteria:** All critical items (25.1–25.3) resolved. High and medium
items tracked and addressed incrementally. `make check` passes throughout.

---

## Phase 26: Agent Tooling Gaps ✓

**Goal:** Fill gaps in the agent's toolbox that force subagents into slow,
token-heavy workarounds (walking directory trees, reading files one-by-one)
or prevent entire workflows (PR review iteration).

### 26.1 High — Content Search (`grep`) ✓

- [x] New `GrepTool` (`grep`) wrapping `rg` (ripgrep) with fallback to `grep -r`
- [x] Parameters: pattern (regex), path (search root), glob filter, context lines,
  case sensitivity, max results
- [x] Add to BUILD, DEBUG, RESEARCH, and TEST subagent allowlists
- [x] Unit tests (29 tests)

### 26.2 High — File Pattern Matching (`glob`) ✓

- [x] New `GlobTool` (`glob`) for finding files by pattern (`**/*.py`, `src/**/*_test.go`)
- [x] Parameters: pattern, path (search root), max results
- [x] Add to all subagent allowlists that have `list_directory`
- [x] Unit tests (20 tests)

### 26.3 High — `llms.txt` Awareness in Web Tools ✓

- [x] `web_fetch` checks for `/.well-known/llms.txt` (and `/llms.txt` fallback)
  on first fetch to a domain, and prefers LLM-friendly content when available
- [x] Cache domain → llms.txt availability for the session to avoid repeated probes
- [x] Unit tests (8 new tests)

### 26.4 Medium — PR Review Comments (`pr_review`) ✓

- [x] New `PrReviewTool` (`pr_review`) that fetches PR review comments via
  `gh api repos/{owner}/{repo}/pulls/{number}/comments`
- [x] Returns structured data: file, line, body, author, and state
- [x] Companion `PrReviewReplyTool` (`pr_review_reply`) to post replies to review comments
- [x] Add to BUILD and DEBUG subagent allowlists
- [x] Unit tests (19 tests)

### 26.5 Low — Batch File Editing (`multi_edit`) ✓

- [x] New `MultiEditTool` (`multi_edit`) that applies multiple search-replace edits
  to one or more files in a single call
- [x] Parameters: list of `{file, old, new}` triples
- [x] Reduces round-trips for mechanical refactors
- [x] Unit tests (13 tests)

### 26.6 Low — Scoped Command Runner (`run_command`) ✓

- [x] New `RunCommandTool` (`run_command`) that runs pre-approved commands only
  (e.g. `make`, `uv`, `ruff`, `pytest`, `pip`) with timeout and output capture
- [x] Allowlist is configurable per-session
- [x] Not a general shell — rejects anything not on the allowlist
- [x] Unit tests (18 tests)

**Exit criteria:** All six tools (grep, glob, llms.txt, pr_review, multi_edit,
run_command) working and wired into subagent allowlists. `make check` passes
throughout. ✓

---

## Phase 27: LLM Provider Hardening ✓

**Goal:** Fix correctness bugs, unlock cost savings, and expose missing provider
capabilities that limit the agent's effectiveness.

### 27.1 Critical — Claude Prompt Caching

- [x] Send system prompt as a content block with `cache_control: {"type": "ephemeral"}`
  in both `complete()` and `stream()` (`claude.py`)
- [x] Capture `cache_creation_input_tokens` and `cache_read_input_tokens` in the
  usage dict so cost tracking is accurate
- [x] Update `ModelInfoBar` to show cache hit rate when using Claude

### 27.2 High — Fix `max_tokens` Hard-Coded at 4096

- [x] `ClaudeProvider.complete()` and `stream()` pass `max_tokens: 4096` unconditionally;
  Claude supports up to 64K output tokens — long BUILD outputs are silently truncated
- [x] Add a `max_tokens` parameter to `LLMProvider.complete()` / `stream()` with
  sensible per-model defaults (Gemini: 65536, Claude: 8192, snap: context-dependent)
- [x] Let callers (especially subagent runner) override for long-output tasks

### 27.3 High — Gemini Duplicate Tool Call IDs

- [x] When Gemini returns multiple calls to the same tool in one response, all
  `ToolCall` objects share `id=part.function_call.name`, breaking result correlation
- [x] Fix: append an index to the ID (`f"{name}_{i}"`) and update
  `from_function_response` to use the stored function name, not the correlation ID
- [x] Add test: two parallel `read_file` calls in one response round-trip correctly

### 27.4 Medium — Extended Thinking Support ✅

- [x] Claude: add optional `thinking_budget` parameter; pass `thinking` config
  with `temperature=1` and expanded `max_tokens` when enabled
- [x] Gemini: `_build_config` now accepts `thinking_budget`; sets
  `include_thoughts=True` with `budget_tokens` when provided
- [x] Add `thinking_budget` to `LLMProvider` abstract interface (complete/stream)
- [x] Update `ModelInfoBar` thinking detection to cover Claude models, not just Gemini-3

### 27.5 Medium — Model Routing Map Gaps ✅

- [x] Add missing `gemini-3.1-pro-preview` → `gemini-3-flash-preview` to `_LIGHT_MODEL_MAP`
- [x] Clean up stale `gemini-2.0-flash` entry in `_CONTEXT_WINDOWS`
- [x] Add `claude-opus-4-6-*` to `_CONTEXT_WINDOWS` explicitly

### 27.6 Low — Inference Snap Streaming Usage ✅

- [x] Streaming path in `InferenceSnapProvider.stream()` produces zero usage data
- [x] Request `stream_options: {"include_usage": true}` and read the final SSE chunk
- [x] Blocking `discover_snap_endpoint` / `_probe_server` calls in `__init__` run during
  startup before the event loop — acceptable given short timeouts (5–10s)

### 27.7 Low — Retry Jitter ✅

- [x] Add `random.uniform(0, base_delay * 0.25)` jitter to `complete_with_retry()`
  to prevent thundering-herd retries from concurrent subagents

**Exit criteria:** Claude caching active and verified via usage metrics. Gemini parallel
tool calls produce unique IDs. `max_tokens` no longer truncates long outputs. Extended
thinking available for design tasks. `make check` passes throughout.

---

## Phase 28: Agent Core Robustness

**Goal:** Fix correctness and resilience issues in the executor, work queue, subagent
runner, and state persistence that can cause silent failures, data loss, or deadlocks.

### 28.1 Critical — SQLite Busy Timeout

- [x] Add `PRAGMA busy_timeout = 5000` after opening the database in `store.py`
- [x] Without this, concurrent writes from the executor and conversation loop can
  raise `sqlite3.OperationalError` (SQLITE_BUSY) and crash the session
- [x] Replace delete-all/re-insert pattern in `save_tasks` with per-task upsert

### 28.2 High — Hardcoded Task IDs Collide

- [x] `planner.py` uses static string IDs (`sprint-build`, `audit-charm`, etc.) — running
  the same plan twice in a session creates duplicate IDs in the queue
- [x] Fix: append a short suffix (e.g. `sprint-build-{uuid4()[:8]}`) to all static IDs
- [x] Add duplicate-ID detection in `WorkQueue.add_task()` — reject or overwrite

### 28.3 High — Executor Exception Catch Too Narrow ✓

- [x] `executor._run_loop` catches only `(KeyError, RuntimeError, OSError)` — any other
  exception type silently kills the autonomous work loop with no recovery
- [x] Widen to `Exception` with ERROR-level logging and a cooldown before retry
- [x] Add a health-check mechanism so the TUI can surface "executor stopped" to the user

### 28.4 High — Subagent Context Window Management

- [x] Subagent `run()` grows `messages` without limit across all 8 rounds
- [x] Add a simple truncation strategy: if estimated tokens exceed 80% of context window,
  summarise earlier tool results before adding new ones
- [x] Consider increasing `MAX_SUBAGENT_ROUNDS` from 8 to 12 for BUILD tasks
  (complex builds with tests and fixes regularly exhaust 8 rounds)

### 28.5 High — Concurrent Tool Execution in Subagents ✅

- [x] Tool calls within each subagent round are executed sequentially (`for tc in ...`)
- [x] Use `asyncio.gather()` for independent tool calls in the same round
- [x] Significant throughput win for tasks that batch 4–6 read/grep calls at once

### 28.6 Medium — `process_message_streaming` Not Actually Streaming

- [x] The method calls `_run_conversation_loop` in full before yielding, defeating
  the purpose of token-level streaming
- [x] Refactor to yield chunks as they arrive from the provider's `stream()` method
- [x] Update TUI to render incremental text updates — `_process_agent_message`
  now iterates `process_message_streaming`; `MessageWidget.append_content`
  and `ChatWidget.append_streaming_chunk` grow the in-progress assistant
  message as chunks arrive; status bar flips to "⟳ Streaming..." once
  streaming starts

### 28.7 Medium — Compaction Error Recovery

- [x] If `compact()` fails (rate limit, timeout), the entire user turn is lost
- [x] Wrap in try/except; on failure, keep the existing (over-full) context and log a
  warning rather than aborting the response
- [x] Consider falling back to a simpler truncation (drop oldest N messages) on
  compaction failure

### 28.8 Medium — Noop Count Not Persisted

- [x] `AgentTask.noop_count` resets to 0 on restart because it is not in the SQLite schema
- [x] Add `noop_count INTEGER DEFAULT 0` column to the tasks table
- [x] Include in `save_tasks` / `load_tasks` serialisation

### 28.9 Medium — Design Proposal Lost on Restart ✅

- [x] `state.design_proposal` is transient — lost on crash/restart
- [x] After a user approves a design, the executor's `_build_context()` produces
  `design_content=None` for subsequent tasks
- [x] Persist approved designs in the SQLite store; reload on session resume

### 28.10 Low — Work Queue Thread Safety

- [x] `WorkQueue._tasks` mutations from concurrent asyncio tasks can interleave
  across `await` points (e.g. `move_to_front` does remove + insert)
- [x] Add `asyncio.Lock` around all list mutations
- [x] Ensure `all_tasks()` returns deep copies, not shallow references to live objects

### 28.11 Low — Revert Leaves Untracked Files

- [x] `_DefaultGitService.revert_to_clean` calls `git checkout .` which only
  restores tracked files
- [x] Add `git clean -fd` after checkout to remove untracked files created by
  failing BUILD subagents

### 28.12 Low — Category-Specific Task Timeouts

- [x] `_TASK_TIMEOUT = 600` is a single global constant for all task categories
- [x] RESEARCH should fail fast (300s); BUILD+DEPLOY need more time (900s)
- [x] Define per-category timeouts in a dict

**Exit criteria:** SQLite writes survive concurrent access. Duplicate task IDs rejected.
Executor self-heals from unexpected exceptions. Subagent context managed. `make check`
passes throughout.

---

## Phase 29: TUI Bugs and Polish ✓

**Goal:** Fix broken/dead features in the TUI, improve the help system, and wire up
partially implemented functionality.

### 29.1 High — Wire Up `RelationDetailScreen` ✅

- [x] `RelationDetailScreen` is fully implemented but never opened — no handler for
  `RelationLine.Selected` messages exists in `app.py`
- [x] Add `on_relation_line_selected` handler in `CantripApp` to push the screen
- [x] Export from `screens/__init__.py`

### 29.2 High — Fix Blocking Subprocess Calls on Event Loop ✅

- [x] `LogScreen._fetch_logs()` and `RelationDetailScreen._fetch_data()` call
  `subprocess.run()` on the main Textual event loop thread, freezing the UI for
  up to 15 seconds
- [x] Move to `self.run_worker()` or `asyncio.to_thread()`

### 29.3 High — Fix `_app_matches_filter` Crash on None Status Message

- [x] `widgets/status.py` calls `.lower()` on `app_status.message` which can be `None`
- [x] Fix: `(message or "").lower()`

### 29.4 Medium — Update Help Screen ✅

- [x] Add missing F5 (Watcher), F6 (Files), F7 (Model), F8 (Graph), F9 (Transcript)
  to the help overlay
- [x] Make help container scrollable for small terminals
- [x] Use percentage-based width instead of fixed 70-cell width

### 29.5 Medium — Wire Up COS Status ✅

- [x] `MultiModelStatusWidget.cos_status` reactive is defined but never set from `app.py`
- [x] Poll COS model status alongside dev model status in `_poll_juju_status`
- [x] Wire up COS expand/collapse click handler (`toggle_cos_expanded` is dead)

### 29.6 Medium — Fix `update_progress()` No-Op ✅

- [x] `MessageWidget.update_progress()` calls `self.refresh()` on a `Static` widget,
  but `compose()` is only called once — progress updates are visually invisible
- [x] Either use `self.update()` on the inner static, or switch to a `Widget` base

### 29.7 Medium — Fix Graph Screen Scrollability ✅

- [x] `GraphScreen` uses a `Static` widget with CSS `overflow-y: auto` — but Textual's
  `Static` does not scroll; long graphs are clipped
- [x] Wrap in `ScrollableContainer` or use `RichLog`
- [x] Make refresh actually fetch fresh Juju status instead of re-rendering stale data

### 29.8 Low — Add Agent Cancellation Binding ✅

- [x] Help screen lists "Ctrl+C — Cancel operation" but no such binding exists
- [x] Add `Ctrl+C` binding to cancel the `agent_response` worker
- [x] Add visual feedback when the cancel is in progress

### 29.9 Low — Clean Up Dead CSS ✅

- [x] Remove `.user-message`, `.agent-message`, `#status-content`, `.progress-indicator`,
  `.success-indicator`, `.error-indicator` from `cantrip.tcss` — all dead selectors
- [x] Fix inconsistent `dismiss` vs `dismiss_screen` action naming across screens
- [x] Replace manual space-padding in modal screen titles with CSS alignment

### 29.10 Low — Display Timestamps in Chat ✅

- [x] `ChatMessage.timestamp` is stored but never rendered
- [x] Show timestamp in the message header (e.g. `[14:23]`)

### 29.11 Low — Design Questions Back Button ✅

- [x] `DesignQuestionsScreen` has no way to go back to the previous question
- [x] Add a "Previous" button or `Left`/`p` keybinding
- [x] Distinguish "user finished" from "user cancelled" (Escape) in the return value

### 29.12 Low — File Preview on Click ✅

- [x] `CharmTreeWidget.on_directory_tree_file_selected` silently discards the event
- [x] Show a read-only file preview panel or at least the file path in the status bar

**Exit criteria:** All TUI screens reachable and functional. No blocking subprocess calls
on the event loop. Dead CSS and dead features either wired up or removed. `make check`
passes throughout.

---

## Phase 30: Tool Completeness ✓

**Goal:** Fill gaps in the agent's toolbox that limit autonomous workflows, improve
existing tool robustness, and fix security issues.

### 30.1 Critical — Fix Shell Injection in Observability Tools ✅

- [x] `TempoQueryTool` and `LokiQueryTool` build Python one-liners embedded in
  `juju.ssh(unit, f'python3 -c "{script}"')` — a double-quote in the query breaks
  out of the shell string and allows arbitrary command execution on the Juju unit
- [x] Fix: base64-encode the script and decode on the remote side, or use a temp file

### 30.2 High — Missing Juju Tools ✅

- [x] `juju_remove_application` — remove a single app without destroying the whole model
- [x] `juju_config_set` — already covered by existing `juju_config` tool (get/set)
- [x] `juju_show_unit` — expose `juju show-unit` as a first-class tool (currently
  only used internally in acceptance tests)
- [x] Add `channel` parameter to `JujuDeployTool` and `JujuRefreshTool`
- [x] Add `base` parameter to `JujuDeployTool` for Ubuntu version selection
- [x] Cap `JujuSSHTool` output length (currently unbounded — can overflow context)

### 30.3 High — Missing Git Tools ✅

- [x] `git_branch` — create and list branches
- [x] `git_checkout` — switch branches (essential for multi-branch workflows)
- [x] `git_stash` / `git_stash_pop` — stash and restore changes
- [x] Add `branch` and `path` filter parameters to `GitLogTool`
- [x] Add `draft` parameter to `GhPrCreateTool`
- [x] Add `gh_pr_list` and `gh_pr_view` tools

### 30.4 Medium — `ReadFileTool` Line Range Support ✅

- [x] Add `start_line` and `end_line` parameters (like `VirtualFileReadTool` already has)
- [x] Prevents the LLM from reading entire large files when it only needs a section
- [x] Add file size and symlink indicators to `ListDirectoryTool`

### 30.5 Medium — Fix `GrepTool` Max Results ✅

- [x] `rg --max-count N` is per-file, not global — a large codebase can return far
  more lines than `max_results` intended
- [x] Use `--max-total-count` (rg ≥ 13) or paginate the output client-side

### 30.6 Medium — Fix `EditFileTool` Error Message

- [x] Appends `...` unconditionally even when the string is shorter than 50 characters
- [x] Only append `...` when `len(old_string) > 50`

### 30.7 Low — Validate `RunCommandTool` Working Directory ✅

- [x] `cwd` parameter is unrestricted — the agent can run commands in `/etc/` or
  other sensitive directories
- [x] Validate that `cwd` is within the charm project tree

### 30.8 Low — Deduplicate `_juju_available()` ✅

- [x] Identical one-liner defined in both `juju.py` and `observability.py`
- [x] Move to `juju_subprocess.py`

### 30.9 Low — Fix Concierge Status Race

- [x] `environment.py` line 130: if Juju is healthy but Concierge is absent, the
  `_is_already_provisioned()` fast-path returns True but then calls
  `_run_concierge("status")` which crashes
- [x] Return immediately from the Juju fast-path without calling concierge

**Exit criteria:** Shell injection fixed. Missing Juju/git tools implemented and tested.
Existing tools hardened. `make check` passes throughout.

---

## Phase 31: User Experience Improvements

**Goal:** Quality-of-life features that make Cantrip more pleasant and productive for
experienced users.

### 31.1 High — Chat Search and Navigation ✅

- [x] Add `/` search binding in `ChatWidget` to search message content —
  a new `SearchBar` widget overlays the chat with an Input + match counter;
  `ChatInput` (subclass of Textual's `Input`) intercepts a leading `/`
  when the field is empty and posts `SearchRequested` so the app opens
  the bar; typing a `/` mid-message still inserts it as a normal character
- [x] Add `TranscriptScreen` search binding — `/` and `Ctrl+F` both open a
  search bar above the RichLog; matches are highlighted and Enter jumps
  to the next match; the hidden search input has `can_focus=False` so
  `/` reliably triggers the binding rather than being typed
- [x] Support `Ctrl+F` as alternative — priority app-level binding so it
  fires regardless of where focus sits (the chat input otherwise grabs it
  as "cursor forward word")

### 31.2 High — Streaming Responses in TUI ✅

- [x] TUI no longer waits for the full agent response — chunks render as they arrive
- [x] Token-level streaming via `process_message_streaming`: `MessageWidget.append_content`
  grows the assistant message; `ChatWidget.append_streaming_chunk` keeps scroll pinned
- [x] Status bar flips "⟳ Thinking..." → "⟳ Streaming..." on the first chunk
  (LoadingIndicator stays up until then, so users still see activity pre-stream)
- [x] Depended on Phase 28.6 (now fully complete)

### 31.3 Medium — Session Resume UX

- [ ] On launch, if a `.cantrip` file exists with unfinished tasks, offer to resume
  rather than starting fresh
- [ ] Show a summary of what was in progress when the session ended
- [ ] Let the user choose: resume, start fresh, or review transcript first

### 31.4 Medium — Token Cost Dashboard

- [x] Show cumulative token usage and estimated cost in the `ModelInfoBar` —
  new `cantrip.llm.pricing` module with per-model rates (Claude 4 family,
  Gemini 2.5/3, inference-snap free); `session_cost_usd` and
  `alltime_cost_usd` reactives on the bar; session cost applies Claude's
  cache-read (10%) and cache-write (125%) modifiers to the agent's session
  accumulators; `/cost` CLI command grew a per-model cost column and an
  overall estimated total
- [ ] Break down by category (research, build, deploy, test, debug) —
  deferred; requires schema migration (task_id on token_usage) and
  plumbing task context through every `_record_usage` call site
- [x] Show cache hit rate when using Claude — already implemented earlier
  (Phase 27.1); confirmed still working alongside the new cost line

### 31.5 Medium — Log Screen Model Selector

- [ ] `LogScreen` always shows the dev model — add a dropdown or binding to switch
  to COS model logs
- [ ] `GraphScreen` should support filtering by app status (show only blocked/waiting)

### 31.6 Medium — Trace Screen with Real URLs

- [ ] `TraceScreen` has placeholder `...` URLs for Tempo/Loki — generate real
  deep-link URLs from the COS model endpoint addresses
- [ ] Actually check COS reachability instead of always showing "Connected"

### 31.7 Low — Charm Comparison Mode

- [ ] `--compare charm1/ charm2/` flag to diff two charm implementations
- [ ] Highlight differences in structure, config, relations, tests
- [ ] Useful for evaluating Cantrip-generated charms against hand-crafted ones

### 31.8 Low — Export Running Session

- [ ] Allow exporting the transcript while the session is still running (not just
  after exit via `export-transcript` subcommand)
- [ ] Add `F10` binding or `/export` chat command

### 31.9 Low — Notification Sounds / Desktop Notifications

- [ ] Long-running builds can take minutes — notify the user when a task completes
  or needs confirmation
- [ ] Use terminal bell (`\a`) for simple notification
- [ ] Optional desktop notification via `notify-send` on Linux

### 31.10 High — CLI REPL Improvements ✅

- [x] Add `/help` or `?` command listing available REPL commands
- [x] Add `/tasks` command showing current task status (title, status, category)
- [x] Add `/status` command showing Juju model status
- [x] Spinner label should reflect what phase the agent is in (e.g. "Searching...",
  "Writing files...", "Deploying...") instead of always "Thinking..."
- [x] Ctrl+C during `process_message` should drain the executor cleanly rather than
  abandoning it — currently `stop_executor()` on line 172 is never reached

### 31.11 High — Session Resume Must Load Conversation History ✅

- [x] `load_state()` never calls `store.load_messages()` — the LLM has no memory of
  the prior session after resume, despite messages being persisted to SQLite
- [x] Load and inject prior messages into `state.messages` on resume
- [x] `build_resume_summary` injects a USER message with no ASSISTANT reply, which
  may confuse LLMs that enforce alternating roles — use a SYSTEM message instead
- [x] `_store_initialised` is not reset when `load_state` fails, leaving the store
  permanently dead for the process lifetime

### 31.12 Medium — Web UI Session and State Persistence ✅

- [x] Web server never calls `agent.load_state()` or `build_resume_summary()` —
  every web server start is a fresh session even if a `.cantrip` database exists
- [x] Web server never calls `agent.save_state()` after each turn — a crash loses
  the entire conversation history
- [x] Add `/api/messages` endpoint so the web UI can reconstruct conversation
  history on page reload (currently only `/api/state` exists, with tasks only)
- [x] `run_web` duplicates light-provider resolution instead of using
  `resolve_light_provider()` — should use the shared helper
- [x] Handle `ProviderRateLimitError` distinctly in WebSocket handler (currently
  uses generic "Provider error" message)

### 31.13 Medium — Web UI Frontend Improvements

- [ ] Markdown renderer is basic — no support for tables, links, images, nested lists,
  or `*` bullet lists (only `- ` is handled); consider using a proper Markdown library
  (marked.js or similar) instead of regex-based rendering
- [ ] No Markdown rendering for user messages — user sees raw text while assistant
  messages get rendered HTML; apply the same renderer to user messages
- [ ] No message timestamps displayed (same issue as TUI)
- [ ] No visual indication of which tool calls the agent is making — the "Thinking..."
  indicator has no detail about what the agent is actually doing
- [ ] No scroll-to-bottom button when viewing long chat history
- [ ] Chat input has no multiline support (single `<input>` instead of `<textarea>`)
- [ ] No way to cancel an in-flight request from the web UI
- [ ] Juju status polling interval is hardcoded at 15s with no way to force refresh
  (except via the Graph overlay's `R` key)
- [ ] `--improve` flag is silently ignored when using `--web` mode
- [ ] No preflight status shown in the web UI — the user has no visibility into
  environment preparation progress

### 31.14 Low — Web UI Input Validation ✅

- [x] `/api/logs` `lines` parameter has no upper bound — clamp to `max(1, min(lines, 5000))`
- [x] `/api/logs` and `/api/logs-stream` `level` parameter passed unsanitised to
  subprocess — validate against `{"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}`

### 31.15 Medium — Web UI and TUI Design Quality Pass

Use the impeccable.style skills (now installed as a Claude Code plugin) to
systematically raise the design quality of both the Web UI and TUI.

- [ ] Run `/impeccable teach` on the cantrip project to establish a `.impeccable.md`
  design context (colour palette from TUI dark theme, spacing conventions, typography)
- [ ] `/audit` the Web UI — score accessibility, anti-patterns, theming consistency,
  and responsive behaviour; fix P0/P1 issues
- [ ] `/critique` the Web UI against Nielsen's heuristics — the chat panel, task
  checklist, and Juju status panel each get a heuristic review
- [ ] `/harden` the Web UI — error states (WebSocket disconnect, API failures),
  empty states (no tasks yet, no messages), loading states, and text overflow
  (long charm names, long task descriptions, long log lines)
- [ ] `/clarify` all user-facing copy in both UIs — error messages, status text,
  empty-state messages, button labels, confirmation dialogs
- [ ] `/distill` the Web UI layout — remove unnecessary visual complexity, ensure
  information density matches the TUI
- [ ] `/layout` review — ensure consistent spacing scale, visual hierarchy between
  panels, and responsive breakpoint behaviour
- [ ] `/polish` final pass on both UIs before any release milestone
- [ ] Review TUI colour palette and widget spacing using impeccable's colour theory
  and spatial design principles (adapted for terminal constraints)

**Exit criteria:** Chat is searchable. Responses stream token-by-token. Session resume
is smooth. Cost tracking visible in the UI. CLI has `/help` and `/tasks` commands.
Web UI persists state and loads prior sessions. Web UI passes an `/audit` with no
P0 issues and scores at least 14/20.

---

## Phase 32: Prompt and Planning Quality ✓

**Goal:** Improve the system prompt, subagent guidance, and planning logic to produce
higher-quality charms with fewer iterations.

### 32.1 High — Compact Prompt Missing Critical Context ✅

- [x] `system_compact.md.j2` omits `cos_model`, `environment_ready`,
  `watcher_enabled`, `skills_index`, and `recent_decisions`
- [x] After compaction, the agent loses awareness of the COS model and environment
  state, leading to incorrect tool choices
- [x] Add at minimum `environment_ready`, `cos_model`, and active skills to the
  compact template

### 32.2 Medium — LLM Planning Output Validation ✅

- [x] Planner does not verify that dependency IDs in the task list refer to tasks
  within the same plan — hallucinated dependencies cause silent deadlocks
- [x] Validate dependency graph is a DAG before adding tasks to the queue
- [x] Log a warning and strip invalid dependencies

### 32.3 Medium — Watcher Event Coverage Gaps ✅

- [x] `offer_connection_change`, `removed_offer`, and `databag_change` events are
  silently dropped by `autodeploy.task_for_watcher_event()` — no task is created
- [x] Map these to DEBUG or INFRA tasks as appropriate
- [x] Make the Loki port configurable in `WatcherConfig` (currently hardcoded
  to `localhost:3100`)

### 32.4 Medium — Design Gap Inference Too Fragile ✅

- [x] `_infer_gaps_from_audit` uses keyword co-occurrence at the document level
- [x] "Good tracing setup, no logging" incorrectly sets `cos_tracing=True`
- [x] Switch to sentence-level or section-level keyword scoping

### 32.5 Low — CONFIRM Tasks Block Unrelated Work ✅

- [x] `route()` returns `WAIT_FOR_CONFIRMATION` at the first CONFIRM task, blocking
  all other ready tasks even if they have no dependency on the confirmation
- [x] Allow non-CONFIRM tasks to proceed in parallel with pending confirmations

### 32.6 Low — Compaction Summary Truncation ✅

- [x] `_format_history` truncates each tool result at 500 chars for the compaction
  summary — critical failure info beyond char 500 is lost
- [x] Increase to 1000 chars or use a smarter truncation that preserves error messages
- [x] Place compaction summary as SYSTEM message, not USER message

**Exit criteria:** Compact prompt retains critical context. Planning validates
dependencies. Watcher events all route to tasks. `make check` passes throughout.

---

## Phase 33: New Skills and Capabilities

**Goal:** Expand what Cantrip can do beyond basic charm building — charm migration,
existing bundle management, and deeper ecosystem integration.

### 33.1 Medium — Existing Bundle Management

**Note:** Juju bundles are deprecated — new bundles should not be created. However,
many existing deployments use bundles, so Cantrip should be able to work with them.

- [ ] New `bundle` skill covering how to read, modify, and deploy existing bundles
- [ ] `bundle_deploy` tool: deploy an existing `bundle.yaml` to a Juju model
- [ ] Understand bundle overlay syntax for modifying existing bundles
- [ ] When proposing multi-charm deployments, use individual `juju deploy` + `juju relate`
  commands rather than generating new bundle files

### 33.2 High — Charm Migration Skill

- [ ] New `charm-migration` skill for migrating legacy charms to modern patterns
- [ ] Detect and replace: reactive framework → ops, Harness → Scenario,
  StoredState → peer relation data, fetch-libs → PyPI imports
- [ ] Integrate with `--improve` mode: `cantrip run --improve legacy-charm/`

### 33.3 Medium — Multi-Charm Workspace

- [ ] Support working on multiple related charms simultaneously
- [ ] Shared design document covering cross-charm relations and config
- [ ] Coordinate deploy and integration testing across charms

### 33.4 Medium — Charm Library Authoring

- [ ] New `charm-library` skill for creating reusable charm libraries
- [ ] Generate `lib/charms/<charm>/v0/<library>.py` with proper versioning
- [ ] Include unit tests and documentation
- [ ] Publish via charmcraft

### 33.5 Low — Interactive Debugging Mode

- [ ] `cantrip debug <charm-path>` — connect to a running deployment and
  investigate issues interactively
- [ ] Automatically check status, logs, relation data, config, and secrets
- [ ] Propose fixes based on observed symptoms

### 33.6 Low — Charm Benchmarking

- [ ] New `benchmark` skill for measuring charm performance
- [ ] Hook execution time profiling via `juju_dispatch` timing
- [ ] Comparison across charm versions (before/after optimisation)

**Exit criteria:** Existing bundle management working. Migration skill handles
the three most common legacy patterns. `make check` passes throughout.

---

## Phase 34: Code Quality Skills for Charm Generation

**Goal:** Port structured review techniques from getsentry/skills into Cantrip's
own skill system so that subagents can self-review generated charm code before
presenting it to the user.

### 34.1 Medium — Generated Charm Security Review ✓

Adapt the getsentry/skills `security-review` pattern (OWASP-based, multi-phase,
confidence-gated reporting) into a Cantrip skill that subagents run after writing
charm code.

- [x] New `security-review` skill (agentskills.io format) focused on charm-specific
  risks: shell injection in event handlers, unsafe `subprocess` calls, secrets in
  config vs Juju secrets, SSRF in relation data, path traversal in file tools
- [x] Python-specific reference material (the getsentry skill has good Python and
  injection references to draw from)
- [x] Integrate into the BUILD subagent category guidance: run security review before
  marking a code-writing task as done
- [x] Confidence gating: only surface HIGH-confidence findings to the user, fix
  MEDIUM ones silently

### 34.2 Medium — Generated Charm Bug Review ✓

Adapt the getsentry/skills `find-bugs` pattern (diff-based, attack-surface mapping,
phased verification) for reviewing generated charm code.

- [x] New `find-bugs` skill focused on common charm bugs: missing `defer_status()`
  calls, wrong event observation patterns, relation data serialisation errors,
  missing `update-status` handling, incorrect Pebble layer merging
- [x] Run as a post-generation review step in BUILD subagents
- [x] Structured output: file:line, severity, evidence, fix suggestion

### 34.3 Low — Iterative CI Fix Loop

Adapt the getsentry/skills `iterate-pr` pattern for Cantrip's deploy-test-debug
cycle — the autonomous loop that pushes fixes until `juju status` is healthy and
integration tests pass.

- [ ] Formalise the existing watcher-driven retry loop into a skill with explicit
  exit conditions (max retries, ask-for-help escalation, stop if environment is
  broken)
- [ ] Structured feedback triage: categorise Juju status errors, Loki log errors,
  and test failures by severity before deciding which to fix first
- [ ] Track attempts per failure to avoid infinite loops on the same issue

### 34.4 Low — Skill Authoring and Scanning

Use the getsentry/skills `skill-writer` and `skill-scanner` patterns to improve
Cantrip's own skill quality.

- [ ] Adapt `skill-writer` workflow for creating new Cantrip skills: source
  synthesis, depth gates, evaluation prompts (EVAL.md)
- [ ] Adapt `skill-scanner` to audit Cantrip's existing skills for prompt injection
  risks, excessive scope, and instruction drift
- [ ] Run skill-scanner as a CI check when skills are added or modified

**Exit criteria:** Security review and bug review skills exist and are wired into
BUILD subagent guidance. At least one charm build benefits from self-review (a bug
or security issue caught before user sees it). `make check` passes throughout.

---

## Phase 35: Supply-Chain Security for Generated Charms ✓

**Goal:** Apply Astral's open-source security practices (action pinning, secret
isolation, dependency cooldowns, trusted publishing, workflow hardening) to the
CI workflows and release processes that Cantrip generates for charms. Charms
built by Cantrip should ship with secure-by-default CI/CD.

### 35.1 High — Secure CI Workflow Templates ✓

Generate GitHub Actions workflows for charms that follow supply-chain best
practices from day one.

- [x] Pin all actions to full commit SHAs in generated `.github/workflows/`
  (not floating tags like `@v4`) — include a version comment for readability
- [x] Set workflow-level `permissions: {}` (empty) and broaden per-job only
- [x] Add `persist-credentials: false` to every `actions/checkout` step
- [x] Include a zizmor step in the generated CI so the charm's own workflows
  are continuously audited
- [x] No `pull_request_target` in generated workflows — use `pull_request`
- [x] Generate a Dependabot or Renovate config with cooldowns for both Python
  dependencies and GitHub Actions

### 35.2 Medium — Charm Dependency Hygiene ✓

Teach Cantrip's subagents to be conservative about charm dependencies, matching
Astral's "eliminate dependencies where practical" philosophy.

- [x] Design-phase guidance: prefer stdlib over third-party where feasible;
  justify every new dependency in the design document
- [x] Avoid dependencies that pull in binary blobs or native extensions
  unless the workload genuinely requires them
- [x] Pin transitive dependencies with known CVEs (Cantrip itself already
  does this for cryptography, requests, pygments — apply the same pattern)
- [x] Generate `uv.lock` or `requirements.txt` with pinned hashes for
  reproducible charm builds

### 35.3 Medium — Charmhub Trusted Publishing ✓

When Cantrip generates a release workflow for publishing to Charmhub, use
trusted publishing (OIDC) rather than long-lived credentials where supported.

- [x] Research Charmhub's current support for OIDC / trusted publishing
  (track charmcraft roadmap for this feature) — **not currently supported**
- [x] If supported: generate a release workflow that uses OIDC identity from
  GitHub Actions, with a dedicated deployment environment and manual approval
  — deferred until Charmhub adds OIDC
- [x] If not yet supported: generate a release workflow that isolates the
  Charmhub token in a deployment environment (not repository-level secrets),
  requires manual approval, and disables caching during the release job

### 35.4 Low — Release Immutability and Tag Protection ✓

Generate GitHub repository rulesets for charm repos that prevent tag
tampering and force-push attacks.

- [x] Include a `.github/rulesets/` or documentation recommending: immutable
  releases, tag creation restricted to release workflow, no force-push to main
- [x] Generate release workflows that create tags only after deployment succeeds
- [x] Embed checksums for any native binaries referenced in charm metadata

**Exit criteria:** A charm built by Cantrip ships with a CI workflow that
passes zizmor with zero findings, pins all actions, isolates secrets, and
includes dependency review. `make check` passes throughout.

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

## Phase 37: Upstream Ecosystem Catch-Up

**Goal:** Review recent changes (last ~3 months) in the core charm ecosystem
libraries and adjust Cantrip's code generation, skills, system prompts, and
tool wrappers to stay current.

### 37.1 High — ops Documentation Corrections (from Dec 2024–Apr 2025 commits)

Review of `canonical/operator` docs commits identified concrete patterns that
Cantrip's code generation, gold-standard charms, skills, and prompts need to
adopt. Items marked with a source commit hash.

**Unit test generation (ops.testing / Scenario):**

- [ ] Stop passing `meta=` to `testing.Context()` — Context now reads metadata
  automatically from `charmcraft.yaml`. Just use `testing.Context(MyCharm)`.
  Fix gold-standard charms that still use `meta=` (`tests/eval/charms/meilisearch/`,
  `tests/eval/charms/ntfy/`). (0d9e557)
- [ ] Use `get_filesystem(ctx)` for testing pushed files instead of mount-based
  testing — simpler, no mount setup needed. Update skills and prompts. (0d9e557)
- [ ] Use `dataclasses.replace()` for modifying State between events in
  multi-event test sequences — State objects are immutable. Update
  `scenario-tests` skill. (6ef2b00)
- [ ] Adopt status testing pattern: test `collect_status` via
  `ctx.on.update_status()` with `layers=` and `service_statuses=` kwargs on
  `testing.Container`. Use `== testing.ActiveStatus()` equality assertions,
  not `isinstance`. (8520d82)
- [ ] Use `pytest.mark.parametrize` for config validation tests in generated
  charms. (8520d82)
- [ ] Use `pebble_ready` event (not `start`) for container file operation
  tests. (fe85d4a)

**Integration test generation (Jubilant):**

- [ ] Call `.resolve()` on charm paths in the `charm` fixture. (e1692c4)
- [ ] Pass path object directly: `juju.deploy(charm)` not
  `juju.deploy(f"./{charm}")`. (e1692c4)
- [ ] Adopt the recommended comprehensive `juju` fixture from the migration
  guide: `keep_models` CLI option, `wait_timeout=10*60`, debug log dump on
  test failure. (1198db8)
- [ ] Use `pytest-jubilant` in generated charms — it provides the `juju`
  fixture (with automatic model creation/teardown, `wait_timeout`, and debug
  log collection on failure) and the `charm` fixture (build + `.resolve()`)
  out of the box. Update the `jubilant-tests` skill, system prompt, and
  `conftest.py` generation to use `pytest-jubilant` instead of hand-rolling
  fixtures. Add `pytest-jubilant` to the generated `pyproject.toml` test
  dependencies.

**Charm code generation:**

- [ ] Use `self.on["storage-name"].storage_attached` bracket notation for
  storage events (not attribute notation). Update system prompt. (6d20276)
- [ ] Storage handling differs by charm type: K8s charms support only a single
  instance (`cache[0]`), machine charms get a list. Update guidance. (6d20276)
- [ ] Get K8s workload mount path from
  `self.meta.containers["name"].mounts["storage"].location`. (6d20276)
- [ ] Consider referencing `pathops` library for file operations in storage
  handling. (6d20276)
- [ ] Use `pyproject.toml` for charm dependencies, not `requirements.txt`.
  Use `charmcraft init --profile kubernetes` as scaffolding base. (51cdf22)
- [ ] Never pass sensitive data in CLI arguments — use environment variables
  or config files instead. Update security guidance in prompts. (06aba0a)
- [ ] Secret identifiers are opaque strings — do not assume Xid format or
  20-character length. (a620797)
- [ ] Secrets over CMR: only the offering application can grant access.
  Update relation-data-design skill. (1424fad)

**Observability:**

- [ ] Loki label in Grafana dashboards: use `{charm="app-name"}` not
  `{juju_charm="app-name"}`. Update observability skill and any dashboard
  generation. (807be80)

**Reference material:**

- [ ] Note Juju/Pebble/ops version matrix for `assumes` block guidance:
  Juju 3.6 → Pebble 1.19.2, Juju 4.0 → Pebble 1.26.0. (9392220)
- [ ] Mention `jhack scenario snapshot` in debugging/testing skills as a way
  to capture live relation databags for regression tests. (34f12be)
- [ ] Reference the new debugging how-to (`ops.Framework.breakpoint()`,
  `debugpy` setup, `juju debug-code`) in Cantrip's debugging guidance. (4bff400)

### 37.2 High — Jubilant Changes

- [ ] Review `canonical/jubilant` changelog — new helpers, changed APIs,
  deprecations
- [ ] Update Cantrip's Jubilant wrapper (`src/cantrip/juju/`) and integration
  test generation guidance
- [ ] Update the `jubilant-tests` skill if new Jubilant patterns are available
- [ ] Bump Cantrip's own Jubilant floor in `pyproject.toml` if needed

### 37.3 Medium — Concierge and Pebble Changes

- [ ] Review `jnsgruk/concierge` for new features or changed deployment patterns
- [ ] Review Pebble client changes (bundled with ops) — new layer options,
  check types, notice handling, file push/pull changes
- [ ] Update Cantrip's Concierge integration (`src/cantrip/agent/preflight.py`)
  and Pebble layer generation guidance

### 37.4 Medium — Charm Libraries (charmlibs) Changes

- [ ] Review recent releases of key charm libraries: `data-platform-libs`,
  `observability-libs`, `traefik-k8s`, `grafana-agent`, `loki-k8s`,
  `prometheus-k8s`, `catalogue-k8s`
- [ ] Check for new PyPI-published versions that replace `charmcraft fetch-libs`
- [ ] Update the `observability` and `relation-data-design` skills if
  integration patterns have changed
- [ ] Update system prompt guidance on which libraries to use and how

### 37.5 Low — Charmcraft and Rockcraft Changes

- [ ] Review `canonical/charmcraft` changelog — new `charmcraft.yaml` fields,
  changed pack behaviour, new commands
- [ ] Review `canonical/rockcraft` changelog — new `rockcraft.yaml` features,
  changed base images, new extensions
- [ ] Update charm and rock template generation if schemas have changed

**Exit criteria:** Cantrip's generated code, skills, and prompts reflect the
current state of the ecosystem. No deprecated APIs used in generated charms.
Gold-standard charms updated. `make check` passes throughout.

---

## Phase 38: Quick Pack — Fast Local Charm Packing ✓

**Goal:** Provide a fast alternative to `charmcraft pack` for the development
loop — initial deploys and upgrade testing when `jhack sync` is not sufficient.

### 38.1 ✓ Core quick pack implementation

- [x] New standalone `quickpack` package at `src/quickpack/` (alongside cantrip
  and charmlint), usable independently via CLI or Python API
- [x] Parse `charmcraft.yaml`, generate `metadata.yaml` (with field renaming and
  link flattening matching charmcraft), `manifest.yaml`, `dispatch` script
- [x] UV plugin: copy `src/` and `lib/` only, install deps via `uv sync`, clean
  up venv (matching charmcraft's UV plugin behaviour)
- [x] Dump plugin: copy files with organize/stage/prime fileset filters
- [x] Jujuignore pattern matching (ported from charmcraft)
- [x] Ensure `.jujuignore` always contains `*.charm` and `.cantrip` entries
- [x] Cantrip agent tool wrapper (`QuickPackTool`)
- [x] 55 unit tests, 5 comparison tests (skipped without `--run-slow`)

### 38.2 Teach cantrip when to use quick pack ✓

- [x] Update sprint deploy flow (`planner.py`) to use `quick_pack` instead of
  `charmcraft_pack` with `destructive_mode=true`
- [x] Update subagent guidance to prefer `quick_pack` for dev deploys
- [x] Add fallback: if quick pack fails (unsupported plugin), fall back to
  `charmcraft_pack`
- [x] Update system prompt with guidance on when to use each tool (including
  the jhack sync trade-off: fastest for `.py`-only iterations but skips
  Juju's deploy/refresh, so wrong for initial deploys and upgrade tests)

### 38.3 Validation and hardening ✓

- [x] Run comparison tests against real charmcraft (requires `--run-slow`) —
  covered by the existing comparison test suite added in 38.1
- [x] Test with a variety of real-world charms (different base versions, extras,
  groups, dump parts) — covered by the existing comparison suite
- [x] Handle edge cases: missing uv.lock, charms with reactive parts (error
  gracefully), charms with multiple bases — reactive parts raise a clear
  "only supports 'uv' and 'dump' plugins" error; missing uv.lock surfaces as
  the `uv sync --frozen` CalledProcessError; callers fall back
- [x] Handle charms without explicit `name` field in charmcraft.yaml — already
  covered: `metadata.parse_charmcraft_yaml()` infers from directory name
  (`test_parse_infers_name_from_directory`)
- [x] Handle `override-build` sections in parts — now raise a clear error
  naming the offending override key so the caller falls back to charmcraft
  (applies to `override-build`, `override-stage`, `override-prime`,
  `override-pull`)

**Exit criteria:** `quickpack` produces valid charms that deploy and function
identically to `charmcraft pack` output. Cantrip uses it automatically for dev
deploys. Speed is at least 2x faster than `charmcraft pack`.

---

## Phase 39: Agent Client Protocol (ACP) — Research

**Goal:** Investigate using the [Agent Client Protocol](https://agentclientprotocol.com/)
as an alternative to driving an LLM directly. Instead of Cantrip calling a model
provider, it would drive an existing agent (e.g. Claude Code, or another
ACP-compatible agent) as its backend. This could let Cantrip leverage agents that
already have tool use, context management, and domain expertise built in.

This is a **research phase** — no production code changes expected.

### 39.1 Protocol familiarisation

- [ ] Read the ACP specification and document the core concepts: agent discovery,
  task lifecycle, streaming, and capability negotiation
- [ ] Identify which ACP features map to Cantrip's existing `LLMProvider`
  interface and which are novel
- [ ] Document the gap between ACP's task model and Cantrip's `AgentTask` /
  `WorkQueue` model

### 39.2 Candidate agents

- [ ] Survey which agents currently support ACP (Claude Code, other known
  implementations)
- [ ] For each candidate, document: supported ACP version, available tools/skills,
  streaming support, authentication model
- [ ] Assess whether driving Claude Code via ACP is feasible and what it would
  gain over direct Anthropic API calls

### 39.3 Integration sketch

- [ ] Draft an `ACPProvider` design that implements `LLMProvider` (or a new
  sibling interface) by delegating to an ACP-compatible agent
- [ ] Identify architectural questions: how does Cantrip's tool execution interact
  with the remote agent's own tools? How do we avoid double tool-calling?
- [ ] Sketch how the autonomous work loop would change if subagents were
  ACP-driven remote agents rather than isolated LLM contexts

### 39.4 Decision and write-up

- [ ] Write a findings document summarising feasibility, trade-offs, and
  recommended next steps
- [ ] If promising, outline a follow-on implementation phase with concrete tasks

**Exit criteria:** A written assessment of whether ACP is a viable and valuable
integration path for Cantrip, with enough detail to decide whether to proceed
to implementation.

---

## Phase 40: Compaction Safety — Cycle Detection and Retry Limits ✓

**Goal:** Ensure the context compaction subsystem cannot enter an infinite loop.
Currently, if the conversation keeps growing after compaction (e.g. the LLM
re-expands summarised content, or a tool produces large output immediately after
compaction), the system can repeatedly trigger `should_compact()` → `compact()` →
`should_compact()` without making progress. Similarly, `emergency_truncate()` has
no cap on how many times it can fire in a session. This phase adds explicit cycle
detection and retry budgets.

### 40.1 Compaction cycle detection ✓

- [x] Track compaction events (timestamp, pre/post token count) in `ContextManager`
- [x] Detect a cycle: if compaction fires N times within a short window (e.g. 3
  times in 60 seconds) without the token count dropping below the threshold for
  at least one full conversation round, flag it as a cycle
- [x] When a cycle is detected, stop compacting and surface a clear warning to the
  user via the conversation loop ("Context is growing faster than compaction can
  shrink it — consider starting a new session or reducing output verbosity")
- [x] Add unit tests for cycle detection with synthetic message sequences

### 40.2 Compaction retry budget ✓

- [x] Add a per-session compaction counter (total compactions attempted,
  total emergencies triggered)
- [x] Set a configurable maximum for each (e.g. 20 compactions, 5 emergencies
  per session)
- [x] When the budget is exhausted, refuse further compaction attempts and warn
  the user rather than silently retrying
- [x] Persist the counters in the SQLite session store so they survive restarts

### 40.3 Post-compaction size validation ✓

- [x] After `compact()` completes, verify that the resulting message list is
  actually smaller than the input; if not, fall back to `emergency_truncate()`
  immediately rather than waiting for the next `should_compact()` check
- [x] Log a warning when compaction fails to reduce size — this indicates the
  summary prompt is not working effectively

**Exit criteria:** The compaction subsystem has hard limits on how many times it
will fire, detects and breaks out of compact–expand cycles, and validates that
each compaction actually reduced context size. No infinite loop is possible.

---

## Phase 41: Claude Provider Quality and Multi-Provider Parity

**Goal:** Improve Claude provider robustness and bring all providers to feature
parity, based on findings from live testing with the Anthropic API (April 2025).

### 41.1 Gemini streaming usage capture ✅

- [x] The Gemini `stream()` method does not capture token usage from the streamed
  response, mirroring the bug fixed in the Claude provider (which now calls
  `stream.get_final_message()` to capture usage)
- [x] Investigate how to capture `usage_metadata` from the last chunk in
  Gemini's streaming response
- [x] Add unit test for Gemini streaming usage capture

### 41.2 Anthropic extended thinking support ✅

- [x] Claude Sonnet 4.5 and Opus 4.6 support extended thinking (budget_tokens)
  which can improve complex reasoning tasks like research and build planning
- [x] Add an `extended_thinking` parameter to `complete()` / `stream()` or
  enable it for specific purposes (planning, complex tool use) — added as
  `thinking_budget` in Phase 27.4
- [x] Handle the `thinking` content block type in streaming events
- [x] Route extended thinking for planner calls where structured reasoning
  improves task decomposition quality (4000-token budget for all three
  LLM-backed planner methods: `plan_from_design`, `replan`,
  `plan_from_day2_findings`)

### 41.3 Prompt caching awareness in system prompt ✅

- [x] Anthropic prompt caching requires a minimum of 1024 tokens (Sonnet) or
  2048 tokens (Opus) for the cached prefix to be eligible
- [x] Add a log message or metric when the system prompt is too short for
  caching to activate, so operators know they are not benefiting from caching
- [ ] Consider padding the system prompt to meet the minimum threshold when
  it is close (e.g. adding the skills index or context summary)

### 41.4 Claude model ID updates ✅

- [x] The `_CONTEXT_WINDOWS` map in `claude.py` only lists two model IDs;
  update it as new Claude models are released (Opus 4.6 is listed with its
  dated ID, but Haiku 4.5 is missing)
- [x] Add Haiku 4.5 (`claude-haiku-4-5-20251001`) to the context window map
  (context window: 200k tokens)
- [x] Add Sonnet 4.6 (`claude-sonnet-4-6`) and Opus 4.7 (`claude-opus-4-7`)
  to the context window map and light-model routing (Sonnet 4.6 → Haiku 4.5;
  Opus 4.7 → Sonnet 4.6)
- [ ] Consider a fallback that queries the API for context window metadata
  rather than hard-coding model-specific values

### 41.5 Provider-level token counting ✅

- [x] Both Claude and Gemini providers inherit the character-based heuristic
  from `LLMProvider.count_tokens()` (4 chars per token estimate)
- [x] Anthropic provides a token counting API endpoint; use it for more
  accurate budget tracking and compaction decisions — new
  `LLMProvider.count_tokens_accurate()` async method (default falls back
  to the sync heuristic); `ClaudeProvider` overrides it to call
  `client.messages.count_tokens`. Used in `ContextManager.compact()`
  for post-compaction size tracking and cycle detection.
- [x] Fall back to the heuristic when the API is unavailable or for
  performance-sensitive hot paths — hot paths (`ContextManager.estimate_tokens`,
  `should_compact`) keep using the sync heuristic; only decision-point
  callers opt into the async accurate variant.

### 41.6 Conversation loop cost display

- [ ] During live testing, multi-turn conversations with tool use consumed
  significant tokens (350+ prompt tokens per turn, growing with history) but
  the CLI mode provides no visibility into cumulative cost
- [ ] Add a periodic cost summary to the CLI banner or a `/cost` command
  that shows total tokens, estimated cost, and cache hit rate
- [ ] The TUI model bar already shows some usage info — verify it updates
  correctly with Claude's usage metrics including cache fields

### 41.7 Compaction effectiveness monitoring ✅

- [x] During testing, compaction with Haiku only reduced a 5-message
  conversation from 1587 to 1518 tokens (4% reduction) when the content
  was repetitive — the summary was nearly as long as the original
- [x] Add a post-compaction metric: log the compression ratio
  (tokens_after / tokens_before) so operators can monitor effectiveness
- [x] If compression ratio exceeds 0.9 (less than 10% reduction), log a
  warning suggesting the conversation may need manual reset
- [x] This feeds into Phase 40 (compaction safety)

### 41.8 Streaming chunk granularity

- [ ] The Claude streaming test revealed that very short responses may arrive
  as a single chunk rather than token-by-token streaming, which means the
  spinner-to-streaming transition in the CLI may appear to jump
- [ ] Consider adding a brief delay or transition indicator in the CLI/TUI
  when switching from spinner to streamed output
- [ ] This is cosmetic — low priority

### 41.9 Concurrent subagent rate limit coordination ✅

- [x] During live testing with 3 concurrent Claude subagents, one hit a
  rate limit on the first call and retried after 37 seconds — the
  ProviderThrottle coordinated the backoff correctly, but the 37-second
  delay is long for a first-time hit
- [x] Investigate whether the initial retry delay (30s base) is too
  aggressive for Claude's rate limits; Anthropic typically recovers faster
- [x] Consider a shorter base delay (10-15s) for Claude specifically,
  or adaptive delay based on the retry-after header if available (chose 15s)

### 41.10 Claude streaming usage robustness ✅

- [x] `ClaudeProvider.stream()` calls `get_final_message()` to capture
  usage, but does not guard against `final_message.usage` being `None`
  — if the API ever returns a response without usage data, line 259
  raises `AttributeError`, failing the entire stream despite valid
  chunks already having been yielded
- [x] Add a `None` guard around the usage extraction so a missing or
  malformed usage block degrades to empty usage instead of crashing
- [x] Apply the same guard in the Gemini provider (41.1) when that is
  implemented

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

## Phase 42: GitHub Integration

**Goal:** Close the loop between Cantrip and GitHub so that the agent can triage
incoming issues, work on branches, open PRs, and — for new charms — bootstrap a
repository. This is most valuable for the **charm improvement** and **ongoing
maintenance** workflows (Phase 10+) but parts apply to initial creation too.

All GitHub operations require explicit user approval and depend on `gh` being
available and authenticated.

### 42.1 High — Detect GitHub Remote ✅

- [x] On startup (or when a charm path is set), check `git remote get-url origin`
  for a GitHub remote
- [x] Parse owner/repo from HTTPS or SSH remote URLs
- [x] Expose `github_repo: str | None` on `AgentState` (e.g. `"canonical/grafana-k8s"`)
- [x] Surface the detected repo in the TUI header subtitle and model info bar

### 42.2 High — Issue Triage Background Worker ✅

- [x] When `github_repo` is set, start a background worker that calls
  `gh issue list --json number,title,labels,body,comments` periodically
- [x] Agent examines open issues, filters for actionable ones (bug reports,
  feature requests with enough detail), and ranks them by feasibility
- [x] Present the top candidate(s) to the user via a CONFIRM task:
  "Issue #42 looks actionable — shall I work on it?"
- [x] If the user approves, create work-queue tasks from the issue
  (research → build → test → PR)
- [x] Respect rate limits — poll no more than once per session or on user request

### 42.3 High — Branch-Per-Change Workflow ✅

- [x] When a GitHub remote is detected and the agent is improving an existing
  charm, create a feature branch for each logical change instead of committing
  directly to the current branch
- [x] Branch naming convention: `cantrip/<short-description>` (e.g.
  `cantrip/add-postgresql-integration`)
- [x] After the change is complete and tests pass, prompt the user before
  pushing the branch
- [x] If the user declines, leave the branch local for manual review

### 42.4 High — Open Pull Requests ✅

- [x] After pushing a feature branch, offer to open a PR via `gh pr create`
- [x] Generate PR title and body from the work-queue task context: what was
  changed, why, test results, and link to the originating issue if applicable
- [x] Include a summary of what the agent did (tools called, tests run,
  iterations needed) in a collapsible details section
- [x] Require explicit user confirmation before creating the PR
- [x] Support `--draft` flag when the user wants review before merging

### 42.5 Medium — Repository Bootstrap ✅

- [x] When no git remote is configured and `gh` is available, offer to create
  a GitHub repository for the charm
- [x] Prompt the user for: public/private, organisation (or personal), and
  description
- [x] Run `gh repo create`, set the remote, and push the initial commit
- [ ] Optionally configure basic repository settings: default branch protection,
  issue templates, CI workflow stub

### 42.6 Medium — Issue-Driven Maintenance Loop ✅

- [x] Combine 42.2–42.4 into an ongoing maintenance mode: the agent periodically
  checks for new issues, proposes fixes, and opens PRs — with user approval at
  each step
- [x] Track which issues have already been examined to avoid re-prompting
- [x] When an issue is resolved by a merged PR, add a comment acknowledging
  the fix (with user permission)
- [x] Handle the case where the upstream branch has advanced — rebase or
  warn the user rather than force-pushing

### 42.7 Low — PR Feedback Loop ✅

- [x] After opening a PR, monitor it for review comments via
  `gh pr view --json reviews,comments`
- [x] Surface reviewer feedback to the agent so it can propose follow-up
  commits on the same branch
- [x] Require user approval before pushing follow-up changes
- [x] Close the loop: reviewer requests change → agent proposes fix →
  user approves → push → re-request review

**Exit criteria:** When a charm directory has a GitHub remote, Cantrip
automatically discovers open issues, works on branches, and opens PRs — all
with explicit user approval at every externally-visible step. When there is no
remote, Cantrip offers to create one. `make check` passes throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Remote detection (42.1) | None | Can start immediately |
| Issue triage (42.2) | 42.1 | Needs repo identity |
| Branch workflow (42.3) | Phase 30 git tools | Needs `git_branch`, `git_checkout` |
| Pull requests (42.4) | 42.3, Phase 30 `gh_pr_create` | Needs branch + PR tooling |
| Repo bootstrap (42.5) | None | Independent; only needs `gh` |
| Maintenance loop (42.6) | 42.2, 42.3, 42.4 | Combines earlier items |
| PR feedback (42.7) | 42.4, Phase 30 `gh_pr_view` | Needs PR view tooling |

---

## Phase 43: Memory — Charm-Specific and Global Lessons ✓

**Goal:** Give Cantrip durable memory across sessions and across charms. Today
the agent has no learned-lesson layer: every session starts from scratch,
every tool failure must be rediscovered, every user correction is forgotten
after compaction. This phase adds two complementary memory scopes — per-charm
memory stored in `.cantrip`, and global charm-building memory stored in
`~/.config/cantrip/memory/` — with automatic capture, user-directed control,
and export as shareable skills.

Memory is strictly the **learned** layer. It complements, but does not replace,
the rule layer (`CLAUDE.md`/`AGENTS.md`, the system prompt, Cantrip's built-in
skills) and the decision layer (the existing `decisions` table, which records
explicit user choices). The design adopts three patterns from 2026
coding-agent memory research:

- **Windsurf's rules-vs-memories split** — rules are human-authored,
  versioned, always-on; memories are agent-authored, local, retrieval-filtered.
  The layers are kept separate.
- **Copilot Memory's citations + TTL + revalidation** — every agent-written
  memory stores the file/line citations it was inferred from, and is
  revalidated against current state before use. Soft expiry at 60 days unused;
  deletion prompt at 180.
- **Claude Skills' progressive disclosure** — only a compact index (~1k tokens)
  loads on every prompt. Individual memories load on demand via a tool.

### 43.1 High — Memory primitives and storage ✅

- [x] Schema v8: `memory` table added to ``.cantrip`` for charm-scope
  memories with columns `id`, `title` (unique), `kind` (fact/rule/lesson),
  `body` (markdown), `source` (auto/manual), `citations` (JSON array of
  `{path, line_start, line_end, sha}`), `tags` (JSON array), `created_at`,
  `updated_at`, `last_accessed_at`, `last_validated_at`, `access_count`,
  `status` (active/quarantined/archived).  Migration from v7 leaves existing
  decisions and sessions untouched
- [x] Global memory directory at ``~/.config/cantrip/memory/``:
  - `MEMORY.md` — always-loaded index rebuilt on every write (one line per
    memory, read capped at 200 lines with a `[truncated …]` marker when
    larger — prevents a runaway index from blowing the prompt budget)
  - `<topic>.md` — individual memory files with YAML frontmatter (`title`,
    `kind`, `source`, `created`, `updated`, `citations`, `tags`, `status`,
    optional `last_accessed` / `last_validated`).  Titles are slugified
    safely (path-traversal attempts flatten to a single segment)
  - Location overridable via ``CANTRIP_MEMORY_DIR``, with ``XDG_CONFIG_HOME``
    fallback before ``~/.config/``
- [x] Six new agent tools wired via `MemoryManager`:
  - `memory_list` — summaries only (titles, kinds, scopes, tags), filtered
    by scope/kind/tag/status — bodies are never included
  - `memory_read` — loads a full memory by title; charm-scope shadows
    global-scope when both exist with the same title; bumps `access_count`
  - `memory_search` — case-insensitive substring match across titles and
    bodies, optionally scoped
  - `memory_write` — creates or overwrites a memory; `scope`, `title`,
    `kind`, `body` required; `tags`, `citations` optional
  - `memory_update` — partial update by title and scope; any omitted field
    is left unchanged; global-scope preserves the original `created`
    timestamp on overwrite
  - `memory_forget` — permanent delete; status-archive via `memory_update`
    is the soft alternative
- [x] System-prompt injection via `build_system_prompt(memory_index=…)`:
  the Memory Index section appears after Available Skills in both the full
  and compact templates, carrying the global MEMORY.md contents plus a
  charm-scope titles-only list; memory bodies are loaded on demand via
  `memory_read`.  The field is sanitised the same way as `recent_decisions`
  to block Jinja template injection
- [x] Compaction-safe by construction: memories live in SQLite and on the
  filesystem, not inside the conversation history — the index is
  re-rendered on every `_build_system_prompt()` call, so it survives
  compaction for free without a decisions-style clone/restore step
- [x] 40 unit tests in `tests/unit/test_memory.py` covering the v7→v8
  migration (including round-trip after migration), each SessionStore
  memory method, `GlobalMemoryStore` (round-trip, filters, search, update
  preserves created, delete, index rebuild, index truncation, path
  traversal, slugify), `MemoryManager` unified API (both scopes, charm
  shadows global, missing lookups, invalid kind/status, absent charm
  scope, prompt-index rendering), each of the six tools (write/read/list
  summaries-only/search/update/forget including error paths), and
  system-prompt injection (absent/present, Jinja sanitisation, compact
  template, size-bounded)

### 43.2 High — Auto-writer with citations and revalidation ✅

- [x] Auto-write triggers (one of three landed; the other two deferred):
  - **User-correction trigger** (landed) — a conservative regex flags
    sentence-initial "no/actually/wait/stop", "don't <verb>",
    "that's wrong", "instead", "always/never <verb>", and similar
    phrases.  Hits schedule the ``AutoWriter`` as a background task
    after the conversation-loop response, so the user is not blocked.
    Both ``process_message`` and ``process_message_streaming`` fire it
  - **Tool-failure-retry trigger** — *deferred*.  Needs in-loop
    tracking of "previous tool errored, current tool succeeded with
    different args"; tracked as future work
  - **Task-complete trigger** — *deferred*.  Needs executor integration
    so a ``DONE`` task can fire the writer with the task's tool-call
    log; tracked as future work
- [x] Gating heuristic — the writer prompt enforces "would this save
  ≥5 minutes of work next time?" with concrete-scenario rationale.  The
  prompt explicitly lists examples that fail the bar (one-off typos,
  generic best-practice advice, restating tool documentation) and
  examples that pass (workarounds for non-obvious failure modes,
  explicit user corrections, non-trivial design decisions).  Most
  events correctly collapse to ``skip``
- [x] Citation capture — ``collect_file_citations`` scans a tool-call
  log for ``read_file``/``write_file``/``edit_file``/``multi_edit``
  arguments and extracts the deduplicated set of real files.  Before
  persisting, the auto-writer computes SHA-256 over each cited file
  and attaches it as a ``{path, sha}`` citation so revalidation has a
  baseline.  Unreadable paths are dropped silently rather than blocking
  the write
- [x] Revalidation:
  - ``MemoryManager.revalidate(scope, title)`` re-reads each citation,
    computes the current SHA, and quarantines the entry on any
    mismatch (or missing file).  Recovery happens automatically when a
    later revalidation passes
  - The prompt index already filters to ``status='active'``, so
    quarantined entries vanish from the system prompt instantly
  - ``memory_revalidate`` agent tool drives both single-entry checks
    and bulk scope sweeps with a clean/quarantined/recovered/failing
    summary
  - Citations without a stored ``sha`` degrade to existence-only
    checks; relative paths resolve against the manager's
    ``charm_path``
- [x] TTL policy:
  - Soft expiry — ``MemoryManager.sweep_stale(soft_days=60)`` archives
    memories where ``last_accessed_at`` and ``last_validated_at`` (or
    ``created_at`` as a fallback) are both older than the threshold.
    Quarantined and already-archived entries are left alone, making the
    sweep idempotent.  ``memory_sweep`` agent tool wraps it
  - Hard prompt — ``MemoryManager.list_due_for_purge(hard_days=180)``
    returns archived memories whose ``updated_at`` is older than the
    hard threshold.  ``memory_purge_check`` tool surfaces them so the
    agent can ask the user "delete or refresh?".  Full CONFIRM-task
    auto-creation deferred to a follow-up
  - Both thresholds configurable per call, plus
    ``CANTRIP_MEMORY_SOFT_EXPIRY_DAYS`` and
    ``CANTRIP_MEMORY_HARD_EXPIRY_DAYS`` env overrides with a
    misconfig-safe fallback (non-integer or non-positive logs a warning
    and uses the default rather than silently disabling expiry)
- [x] Inline notices — new ``MEMORY_WRITTEN`` and ``MEMORY_RECALLED``
  event types; ``MemoryManager`` exposes ``set_write_callback`` /
  ``set_recall_callback`` so callers wire it however they want; the
  ``CantripAgent`` forwards both to the event bus.  TUI chat widget
  renders them as inline system messages ("Wrote rule memory: foo
  (charm)"); the Web frontend handles them in the existing dispatch
  switch.  Callback failures are isolated — a broken UI hook never
  breaks the underlying memory operation

### 43.3 Medium — User controls in TUI and Web ✅

- [x] `/memory [scope]` lists all memories across both scopes (or one);
  output is rendered as a Markdown bullet list of titles, kinds, and
  tags via the existing chat surface.  `/memory help` prints the full
  syntax block.  Filters by kind, freshness, citation validity, and
  last-accessed timestamps are deferred — the agent already has tools
  (`memory_list`, `memory_revalidate`) for those filters
- [x] `/remember <kind> [scope] -- <title> -- <body>` writes a memory.
  ` -- ` (space dash dash space) is the field separator so titles and
  bodies can include any punctuation.  ``kind`` is required (one of
  ``fact``/``rule``/``lesson``); ``scope`` defaults to ``charm``
- [x] `/forget <title> [scope]` deletes by exact title.  Quoted titles
  (`'hello world'`) are supported via shlex.  When the same title
  exists in both scopes and no scope is given the handler refuses with
  an "ambiguous" message rather than guessing
- [ ] Natural-language routing — *deferred*.  The agent already routes
  phrases like "remember that X" through ``memory_write`` in normal
  conversation; explicit slash commands cover the user-facing affordance
- [x] All three commands run inline (no LLM round) and dispatch through
  the same ``cantrip.agent.memory_commands`` module from both TUI and
  Web so behaviour stays in lockstep.  Memory writes also emit
  ``MEMORY_WRITTEN`` / ``MEMORY_RECALLED`` events through the event
  bus (see 43.2)

### 43.4 Medium — Export and import ✅

- [x] ``/memory export <name> <output_path> [scope]`` bundles memories
  into a SKILL.md file under
  ``<output_path>/<name>/SKILL.md`` (or to ``<output_path>`` directly
  when it ends in ``.md``).  Reuses the existing skills system as the
  export format — the bundle is a complete SKILL.md the
  ``SkillsIndex`` discovers, with one ``## Memory: <title>`` section
  per entry under YAML frontmatter
  - Charm-specific paths replaced with ``<CHARM_PATH>`` placeholder
    (resolved + raw forms both substituted, longest-first to avoid
    prefix collisions)
  - Five conservative secret patterns scrubbed — GitHub tokens
    (``ghp_/gho_/ghs_/github_pat_``), AWS access keys (``AKIA…``),
    Bearer tokens, ``password=…``/``password: …`` assignments, Slack
    tokens (``xox*-…``).  False positives are intentional — a wrongly
    scrubbed body can be re-edited; a leaked credential cannot
  - ``ExportResult.redactions`` surfaces the count so the slash-command
    response notes "(N secret redactions)" before the user shares
- [x] ``/memory export-md <output_dir> [scope]`` writes one Markdown
  file per memory under the directory, each with the same YAML
  frontmatter the global store already writes (so a dump round-trips
  through ``import_from_path``)
- [x] ``/memory import <source_path> [target_scope]`` reads a
  SKILL.md file, a directory of memory ``.md`` files, or a directory
  containing a SKILL.md.  Auto-detects format via frontmatter shape.
  Duplicates skip by default; ``overwrite=True`` is available
  programmatically (no slash-command flag yet — keeps the inline
  affordance simple)
- [x] Round-trip tests cover both formats, including charm-path
  sanitisation surviving import on a fresh machine

**Exit criteria:** The agent automatically captures charm-specific and
reusable lessons with citations; a Memory Index section appears in every
system prompt; revalidation prevents stale memories from being silently used;
users can list, edit, forget, export, and import memories via slash commands
in both TUI and Web; an exported skill from one machine can be imported on
another and used by a fresh Cantrip install. `make check` passes throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Storage + tools (43.1) | Phase 25 schema machinery | Schema v8 migration |
| Auto-writer (43.2) | 43.1, existing subagent runner | Writer runs as a subagent |
| UI controls (43.3) | 43.1, Phase 15 Web UI, Phase 31 slash commands | Shared event bus |
| Export/import (43.4) | 43.1, existing skills system | Reuses `LoadSkill` plumbing |

---

## Phase 44: Worktree Isolation for Parallel Subagents ✓

**Goal:** Give each concurrent subagent its own git worktree so the background
executor can safely run parallel work without file-level conflicts. Today up to
three subagents share one working tree (`src/cantrip/agent/executor.py`), which
makes BUILD/TEST/DOC overlap racy and caps the degree of parallelism we can
trust. Git worktrees became the cross-vendor isolation primitive in the
Oct 2025 – Apr 2026 window (Cursor `/worktree`, Windsurf parallel Cascade,
Gemini CLI native worktrees, Claude Code subagent isolation). Adopting the same
primitive lets Cantrip scale parallelism beyond three and removes a real class
of race condition from generated-charm builds.

### 44.1 High — Worktree allocator and lifecycle ✓

- [x] New `WorktreeAllocator` in `src/cantrip/agent/worktree.py` that creates a
  `git worktree add` under `.cantrip-worktrees/<task-id>/` (the `.cantrip`
  database is a file, not a directory, so worktrees sit alongside it), tracks
  the mapping `task_id → WorktreeHandle`, and cleans up on release
- [x] Allocator `Protocol` in `services.py` so it can be swapped in tests —
  matches the Phase 21.2 service-injection pattern
- [x] `BackgroundExecutor` asks the allocator for a worktree at subagent spawn
  time; ``SubagentContext.charm_path`` becomes the worktree path, and noop
  fingerprints target the worktree rather than the main tree
- [x] Worktrees are created from the current HEAD of the charm branch on a
  unique ephemeral branch (`cantrip/wt/<task-id>`) to prevent checkout conflicts
- [x] Allocator writes the worktree directory to `.git/info/exclude` so a
  nested worktree doesn't appear as untracked work in the main tree's
  `git status` (otherwise merge-back would always see "dirty main")
- [x] Non-git charm paths fall back to `None` — the allocator is always safe
  to call; callers run in the main tree when isolation is unavailable
- [x] `make check` covers allocator lifecycle: create, collision on duplicate
  task id, cleanup on success, cleanup on failure, orphan reaper on startup,
  non-git fallback, release-after-manual-rm recovery, idempotent exclude
  append, and main-tree-clean-after-worktree-write (19 unit tests)

### 44.2 High — Merge strategy on subagent exit ✓

- [x] On successful subagent exit the executor `git merge --no-ff` merges the
  worktree branch back into the main charm branch so the subagent's commits
  survive on the main graph rather than being collapsed
- [x] Auto-commit any uncommitted changes on the worktree branch before
  merging so subagents that wrote files but never called `GitCommitTool`
  still contribute their work
- [x] Conflict handling: the executor runs `git merge --abort`, marks the
  task `BLOCKED` with a descriptive message, and preserves the ephemeral
  branch (release with `keep_branch=True`) so the user can resolve manually
- [x] Merge skipped when main has uncommitted work; branch retained, task
  marked `BLOCKED` — preserves the user's in-progress state
- [x] Merges serialised behind an `asyncio.Lock` on the executor so multiple
  concurrent subagents can't race on the main tree
- [x] Unit tests cover clean merge, `--no-ff` commit preservation, conflict
  rollback, and main-dirty skip (4 end-to-end tests against a real git repo
  via `tmp_path`), plus in-memory fakes that exercise the block/release
  bookkeeping (9 tests)
- [ ] *Future work:* surface the conflict as a proper CONFIRM task through
  the conversation loop rather than just a `BLOCKED` status line

### 44.3 Medium — Revert path on failure ✓

- [x] Extend Phase 11.4 git-revert-on-failure to operate inside the worktree
  rather than on the shared tree — a failing subagent's changes are discarded
  when its worktree is torn down without merging.  The executor's `finally`
  block calls `release(keep_branch=False)`, which removes the worktree
  directory and deletes the ephemeral branch, so nothing survives.  The
  main-tree snapshot/revert path now runs only when the allocator returns
  `None` (non-git charms)
- [x] Phase 11.1 commit-after-build still applies per-worktree: subagents
  commit to `cantrip/wt/<task-id>` via `GitCommitTool` as before, and
  `_merge_worktree` auto-commits any remaining uncommitted files before
  merging so nothing goes unrecorded
- [x] Noop detection (Phase 21.3) fingerprints the worktree path, not the
  shared tree — `_execute_task` passes the effective path (worktree when
  allocated, otherwise main) through `_handle_result` for the before/after
  comparison

### 44.4 Medium — Worktree visibility in TUI/Web

- [x] TUI task widget detail panel includes the worktree path when the task
  owns one (`tui/widgets/tasks.py:_format_detail`).  Collapsed rows keep
  their previous layout; the path appears on expand only
- [x] Web task list renders `worktree: <path>` as a small monospace line
  beneath each active task (both in the server-rendered initial HTML and
  live WebSocket updates); styled via a new `.task-worktree` CSS class
- [x] `TASK_UPDATED` bus events carry a `worktree_path` field
  (`ui/events.py:task_updated`) so subscribers pick it up without new
  event types; `AgentTask` gained a transient `worktree_path` attribute
  the executor toggles on allocate/release
- [ ] `/worktrees` slash command listing active worktrees with task ids and
  branches — deferred; the per-task display above covers the common case
- [ ] File-tree preview on worktree click — deferred; out of scope for the
  initial visibility pass

### 44.4 Medium — Worktree visibility in TUI/Web

- [ ] New column in the work-queue task widget (`src/cantrip/tui/widgets/tasks.py`)
  showing each task's worktree path
- [ ] `/worktrees` slash command lists active worktrees with their task ids,
  branches, and last-activity timestamps
- [ ] Web UI mirrors the same view via the shared event bus (Phase 15.1)
- [ ] Clicking a worktree in the TUI opens a file-tree preview scoped to it

### 44.5 Low — Configuration and limits ✓

- [x] ``CANTRIP_MAX_WORKTREES`` caps concurrent worktrees independently of the
  subagent concurrency limit.  The allocator reads the env var at
  construction; an explicit ``max_worktrees=`` kwarg overrides it.  Setting
  the cap to ``0`` disables worktree allocation entirely (allocator falls
  back to the main tree), which is the escape hatch for users with a broken
  git install.  Invalid values fall back to "no cap" with a warning log.
- [x] Startup orphan reaper — a new ``reap_disk_orphans(base_path,
  active_task_ids)`` method walks ``git worktree list --porcelain`` under
  the base path, identifies worktrees under ``.cantrip-worktrees/<task-id>/``
  whose task id isn't in the live queue, and removes both the worktree and
  its ephemeral branch.  User-created worktrees outside
  ``.cantrip-worktrees/`` are left untouched.  The executor invokes this at
  the top of ``_run_loop``; terminal-state tasks (``DONE`` / ``FAILED`` /
  ``BLOCKED``) are excluded from the active set so their worktrees are also
  reaped.
- [x] Disk-space guard — ``min_free_bytes`` (default 200 MB) is checked via
  ``shutil.disk_usage`` before allocation.  Below the threshold the
  allocator returns ``None`` with a warning log, which the executor treats
  as "run in main tree".  Set ``min_free_bytes=0`` to disable.
- [x] Unit tests cover the cap (explicit + env var + zero + invalid),
  the disk-space guard (zero and impossibly-high thresholds), and
  ``reap_disk_orphans`` (active set, empty set, non-git base, external
  worktrees left alone), plus three executor integration tests for the
  startup-reap hook (10 new tests across ``test_worktree.py`` and
  ``test_executor_worktree.py``)

**Exit criteria:** Parallel subagents run in isolated worktrees; merge and
revert paths are tested with clean, conflicting, and failed cases; the TUI and
Web UI expose worktree state; concurrency can exceed three without file-level
races. `make check` passes throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Allocator and lifecycle (44.1) | Phase 21.2 service injection | Injected as a protocol service |
| Merge strategy (44.2) | Phase 30 git tooling | Uses existing git tools for rebase/merge |
| Revert path (44.3) | Phase 11.4 git-revert-on-failure | Extends existing revert to worktree scope |
| TUI/Web visibility (44.4) | Phase 15.1 shared event bus | Emits worktree lifecycle events |
| Limits and reaper (44.5) | 44.1 | Configuration layer on top of the allocator |

---

## Phase 45: Model Context Protocol (MCP) Client ✓

**Goal:** Add MCP client support so Cantrip can pull context and tools from
third-party MCP servers. MCP converged as the cross-vendor tool-extension
standard in the Oct 2025 – Apr 2026 window (Cursor Bugbot MCP, Codex MCP Apps
with marketplaces and namespaced registration, Copilot's MCP default, Claude
Code MCP elicitation + RFC 9728 OAuth, Windsurf MCP OAuth). Cantrip currently
has no MCP client. High-value servers for a Juju-charm agent include Charmhub
search/publish, Grafana query, GitHub org context, Launchpad bug search, and
Loki/Prometheus schema-aware wrappers. This phase is complementary to
Phase 39 (ACP drives a remote agent as Cantrip's backend; MCP injects tools
into Cantrip).

### 45.1 High — MCP client protocol implementation ✅

- [x] Wire-protocol implementation built on the official ``mcp`` 1.27.0
  Python SDK, wrapped in ``src/cantrip/mcp/``.  Both transports are
  supported: stdio (subprocess via ``StdioServerParameters``) and
  streamable HTTP (``streamablehttp_client``)
- [x] Lifecycle — ``MCPClient.start()`` opens the transport, runs the
  ``initialize`` handshake, and caches the tool list; ``stop()`` tears
  it all down idempotently.  ``call_tool`` reconnects with bounded
  exponential backoff (1s → 30s) on a single transient connection
  error mid-call.  The whole session lifetime is owned by a dedicated
  background task because the SDK's anyio cancel scopes refuse to exit
  in a different task than they were entered in
- [x] Timeouts honoured per server (``timeout_seconds`` config knob,
  default 30s); reconnect backoff matches the existing
  ``cantrip.agent.retry`` cadence
- [x] 14 unit tests against an in-tree stub MCP server cover lifecycle
  (start/stop idempotency, async-context-manager, tool listing), config
  errors (missing command/url), tool invocation (echo round-trip,
  error surface, disconnected client), the per-server allowlist
  (filter on list, reject on invoke, empty = allow all), and
  transient-failure recovery

### 45.2 High — Server configuration and discovery ✅

- [x] ``cantrip.mcp.yaml`` (repo-scope, next to the charm) and
  ``~/.config/cantrip/mcp.yaml`` (user-scope, overridable via
  ``CANTRIP_MCP_USER_CONFIG``) declare servers with ``command``,
  ``args``, ``env``, ``cwd``, ``url``, ``headers``, ``timeout_seconds``,
  and an ``allowed_tools`` allowlist.  The schema mirrors the Claude
  Code / Cursor / Codex format for portability.  Repo scope wins on
  server-name conflict
- [x] Startup discovery — ``MCPRegistry.start_all()`` launches every
  configured server in parallel.  Failures land in the per-server
  ``ServerStatus`` rather than blocking healthy ones; a malformed
  config file logs a warning and is skipped instead of crashing the
  agent.  TUI ``on_mount`` and Web ``_run_web_async`` both call
  ``agent.start_mcp()`` so configured servers actually connect at boot
- [x] ``/mcp`` slash command in ``cantrip.agent.mcp_commands``, shared
  by TUI and Web.  Subcommands: ``/mcp`` (overview with ``[ok]/[!!]``
  status markers), ``/mcp tools <name>`` (per-server tool list with
  qualified names), ``/mcp help``
- [x] 39 unit tests — 21 for the YAML loader (every shape, every
  error path, the merge precedence) and 18 for the registry + slash
  command (lifecycle, partial failure, /mcp output for connected /
  failed / disconnected / unknown / empty cases)

### 45.3 Medium — MCP tool surfacing to subagents ✅

- [x] Remote tools appear with the ``mcp__<server>__<tool>`` naming
  convention via the new ``MCPTool`` adapter.  ``MCPToolInfo`` exposes
  a ``qualified_name`` property so the convention is enforced in one
  place
- [x] Tool schemas pass through end-to-end — the SDK's ``inputSchema``
  ``dict[str, Any]`` is copied defensively into ``MCPToolInfo`` and
  threaded through to the LLM as ``MCPTool.parameters``.  No round-trip
  conversion, so JSONSchema fidelity is preserved
- [x] Phase 21.6 scoped access — ``_filter_tools`` recognises any tool
  whose name starts with ``mcp__`` and lets it through every category
  gate.  The per-server ``allowed_tools`` config (45.2) is the
  authoritative MCP gate; operators tighten exposure by editing the
  YAML rather than touching code
- [x] ``CantripAgent.start_mcp()`` invalidates the tools cache so
  newly-connected servers' tools surface to the next subagent without
  restarting
- [ ] *Future work*: tag MCP tool calls in transcripts (Phase 14.1)
  with the originating server.  ``MCPTool.execute`` already returns
  ``data={"mcp_server": …, "mcp_tool": …}``; the transcript layer
  needs a small change to surface that field
- [x] 11 unit tests cover descriptor fidelity, execution paths
  (happy path, server error, disconnected, unknown), build_tools
  integration, and the subagent filter passthrough

### 45.4 Medium — OAuth and elicitation support ✅

- [x] MCP OAuth 2.1 client with RFC 9728 Protected Resource Metadata
  discovery.  Built on the SDK's ``OAuthClientProvider`` plumbed into
  ``streamablehttp_client(auth=...)``; Cantrip provides the two
  application-level callbacks the SDK can't infer.  ``OAuthConfig``
  dataclass on ``ServerConfig`` (``client_name``, ``scopes``,
  ``redirect_port``, ``client_metadata_url``) with full YAML schema
  validation.  ``cantrip.mcp.oauth.make_redirect_handler`` opens the
  authorization URL in the user's default browser
  (``webbrowser.open``) and falls back to a logged URL on headless
  systems.  ``wait_for_localhost_callback`` binds an aiohttp listener
  to ``127.0.0.1:<redirect_port>``, captures one ``GET /callback?code=…&state=…``
  and tears down.  Every failure mode surfaces cleanly: OAuth-error
  query params raise ``OSError``, missing code raises ``OSError``,
  port-already-in-use raises ``OSError``, user-walks-away raises
  ``TimeoutError`` (default 300s)
- [x] Token storage (Phase 45.4a) — ``FileTokenStorage`` implements
  the SDK's ``TokenStorage`` protocol with per-server JSON files at
  ``~/.config/cantrip/mcp_tokens/<name>/`` (override via
  ``CANTRIP_MCP_TOKEN_DIR``).  Per-server dirs at ``0700``, files at
  ``0600``, atomic ``rename`` writes so a crashed write never leaves a
  half-file.  Optional GPG-at-rest via ``CANTRIP_MCP_GPG_TOKENS=1``,
  matching the existing ``CANTRIP_GPG_SIGN`` opt-in pattern.  Malformed
  or unreadable files degrade to ``None`` so the SDK falls back to a
  fresh OAuth flow rather than crashing.  23 unit tests, including a
  live GPG round-trip that verifies no plaintext leaks
- [x] Elicitation (Phase 45.4c) — ``ElicitationManager`` per
  ``MCPClient`` bridges the SDK's ``elicitation_callback`` to the UI
  event bus.  Server requests park on an ``asyncio.Future``; the UI
  publishes ``MCP_ELICITATION_REQUEST``, prompts the user, and calls
  ``CantripAgent.complete_mcp_elicitation(request_id, action, content)``
  to resolve.  Bounded timeout (default 600s) auto-declines runaway
  requests; ``cancel_all`` on shutdown auto-declines everything pending
  so the SDK never hangs.  Both ``form`` and ``url`` elicitation modes
  surface verbatim through the event payload.  14 unit tests cover
  every failure mode (timeout, unknown id, invalid action,
  callback-failure isolation, cross-server routing)
- [ ] *Future work*: TUI/Web prompt rendering for the elicitation
  event.  The bus event is fully wired; building an interactive form
  widget that maps a JSONSchema to input fields is a follow-up
- [x] Unit tests cover token-storage round-trips and elicitation
  request/response/timeout/cancel paths.  OAuth-flow tests follow the
  deferred OAuth integration commit

### 45.5 Low — MCP server registry and marketplace awareness ✅

- [x] Read-only discovery against the Codex / Cursor / Claude Code
  marketplace format.  ``cantrip.mcp.marketplace`` parses
  ``marketplace.json`` documents from three source kinds — GitHub repo
  (raw fetch), local directory, or arbitrary URL — declared in a new
  ``marketplaces:`` block in ``cantrip.mcp.yaml``.  Responses are
  cached at ``~/.cache/cantrip/marketplaces/`` with a 24-hour TTL
  (``CANTRIP_MCP_MARKETPLACE_CACHE`` overrides).  ``/mcp marketplace``
  surfaces the catalogue grouped by source with description, install
  hint, required env vars, and OAuth scopes; ``/mcp marketplace
  refresh`` bypasses the cache.  Cantrip never auto-installs a server
  — the user copies the descriptor into ``cantrip.mcp.yaml`` after
  reviewing it
- [x] ``design/MCP_SERVERS.md`` documents authoring servers:
  - Where they can live (own repo, companion bundle, or inside a
    charm)
  - A working Python SDK example (mirroring the in-tree stub)
  - Tool design conventions (names, descriptions, schemas, output,
    errors, side effects)
  - Full ``marketplace.json`` schema reference with field table
  - Authoring checklist
  - Suggested servers (Charmhub, Launchpad, Grafana, Snapcraft,
    Charmcraft, MAAS) — none ship in this repo; they're prompts for
    follow-up projects
  - Local-test recipe pointing Cantrip at a directory source

**Exit criteria:** Cantrip can load an MCP server from a YAML config, route
its tools to subagents with category-scoped access, handle OAuth and
elicitation, and surface the state in the TUI and Web UI. `make check` passes
throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Client protocol (45.1) | None | New subsystem under `src/cantrip/mcp/` |
| Server config (45.2) | 45.1 | Builds on the client |
| Tool surfacing (45.3) | 45.1, Phase 21.6 scoped access | Category allowlists gate remote tools |
| OAuth and elicitation (45.4) | 45.1 | Layered on top of the base client |
| Registry awareness (45.5) | 45.2 | Extends the config discovery path |

---

## Phase 46: User-Configurable Hooks

**Goal:** Expose the executor's lifecycle points as user-configurable hooks so
operators can inject domain policy (security review, custom linters, signoff,
external approvals, notifications) without forking Cantrip. Claude Code shipped
conditional `if:` hooks and a PreCompact hook in the review window; Windsurf
shipped Cascade Hooks. Cantrip already has internal hooks in `planner.py` and
the watcher — this phase formalises them and opens them up.

### 46.1 High — Hook event taxonomy

- [ ] Enumerate the executor lifecycle points worth hooking: `pre_tool_call`,
  `post_tool_call`, `pre_subagent`, `post_subagent`, `pre_compact`,
  `post_compact`, `pre_pack`, `pre_push`, `pre_pr`, `on_task_complete`,
  `on_session_end`
- [ ] Document the payload shape for each event (tool name, arguments, task
  category, working directory, provider, token cost-so-far)
- [ ] Events are emitted through the Phase 15.1 shared event bus so TUI, Web,
  and hooks all observe the same stream

### 46.2 High — Hook config format and discovery

- [ ] `hooks.yaml` at `.cantrip/hooks.yaml` (repo scope) and
  `~/.config/cantrip/hooks.yaml` (user scope), merged with repo taking
  precedence on conflict
- [ ] Each hook declares: `on:` event name, `run:` command or inline script,
  `timeout:` seconds, and `continue_on_error:` bool
- [ ] Hooks run as subprocesses with a JSON payload on stdin; stdout/stderr
  are captured into the transcript

### 46.3 Medium — Conditional filters

- [ ] `if:` expression support: simple comparisons against payload fields
  (e.g. `tool == "git_push"`, `task.category == "BUILD"`,
  `path.matches("charm.py")`)
- [ ] Pattern syntax mirrors Claude Code's `if:` filter
- [ ] Unit tests cover matching, non-matching, malformed expressions, and
  missing fields

### 46.4 Medium — Hook result handling

- [ ] Non-zero exit code from a hook on `pre_*` events is treated as a veto;
  the executor reports the hook name and stderr to the conversation loop and
  declines to proceed
- [ ] Stdout from `pre_tool_call` hooks can mutate the pending payload (e.g.
  redact secrets before the tool runs) via a documented JSON-patch envelope
- [ ] Hooks on `pre_compact` can block compaction — matching Claude Code's
  PreCompact hook behaviour — to protect pinned context

### 46.5 Low — Hook telemetry and debugging

- [ ] `/hooks` slash command lists configured hooks, last invocation, last
  outcome, average duration
- [ ] Hook invocations appear in the transcript as a dedicated event type
- [ ] `cantrip hooks test <event-name>` CLI subcommand fires a synthetic event
  against the configured hooks for debugging

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

## Phase 47: Best-of-N Multi-Model Racing for High-Value Tasks

**Goal:** For tasks with objective success criteria (BUILD, DESIGN,
RED/GREEN), optionally run N models in parallel and pick the winner. Cursor
`/best-of-n` and Windsurf Arena Mode shipped this pattern in the window, and
charm building is an unusually good fit — success is measurable via unit tests,
integration tests, `charmlint` output, and operational-readiness score. Gated
by cost and off by default; opt-in per task category.

### 47.1 High — Scoring rubric

- [ ] Define a scoring function that combines: unit test pass count,
  integration test pass count, `charmlint` violations (weighted by severity),
  operational-readiness score delta, and diff size (penalising large
  unnecessary changes)
- [ ] Scoring runs against each candidate's worktree (depends on Phase 44)
- [ ] Scores are comparable across candidates even when tests have different
  counts — normalise by the maximum achieved count
- [ ] Unit tests cover tie-breaking, empty test suites, and degenerate
  candidates (build failure scored as worst)

### 47.2 High — Parallel execution harness

- [ ] A `RaceCoordinator` in `src/cantrip/agent/race.py` spawns N candidate
  subagents against the same task, each in its own worktree and with a
  different `provider`/`model` pairing
- [ ] Candidates share the same system prompt, task, and scoped tool access;
  they differ only by model
- [ ] Cancellation: once a candidate achieves a perfect score, the coordinator
  cancels the others (opt-in — some users want to see all results)

### 47.3 Medium — Result selection and commit

- [ ] After all candidates finish (or one wins early), the coordinator picks
  the highest-scored candidate's worktree and merges it into the charm branch
  via Phase 44.2
- [ ] Losing candidates' worktrees are torn down via Phase 44.3
- [ ] Transcript records all candidates' output per Phase 14.2 so reviewers
  can see the losers too

### 47.4 Medium — Cost guardrails

- [ ] Configuration gates Best-of-N per category: `race.enable = ["BUILD",
  "DESIGN"]`, `race.max_candidates = 3`, `race.budget_tokens = 500_000`
- [ ] Pre-race cost estimate surfaced as a CONFIRM task when the estimated
  cost exceeds a threshold
- [ ] Budget exhaustion during the race downgrades gracefully to single-model

### 47.5 Low — Blind A/B arena mode

- [ ] `/arena` slash command runs two candidates blind and asks the user to
  pick the winner for a one-off preference capture, mirroring Windsurf Arena
- [ ] Preference outcomes feed into memory (Phase 43) as facts about which
  models the user prefers for which task categories

**Exit criteria:** Best-of-N races run for configured categories, score by
measurable outcomes, merge the winner via the worktree merge path, and respect
cost budgets. Blind arena mode is available behind `/arena`. `make check`
passes throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Scoring rubric (47.1) | Phase 24 charmlint, Phase 19 readiness score | Combines existing signals |
| Parallel execution (47.2) | Phase 44 worktree isolation | Each candidate needs its own worktree |
| Selection and commit (47.3) | 47.2, Phase 44.2 merge | Uses the worktree merge strategy |
| Cost guardrails (47.4) | Phase 41.6 cost display | Shares the cost-accounting plumbing |
| Arena mode (47.5) | 47.2, Phase 43 memory | Writes user preference into memory |

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

### 48.1 High — Image-input support in providers

- [ ] Extend `LLMProvider` with `complete_with_images()` /
  `stream_with_images()` that accept a list of `Image(bytes, mime)` alongside
  the prompt
- [ ] `ClaudeProvider` and `GeminiProvider` implement the method against their
  respective SDKs (both already support image blocks)
- [ ] `InferenceSnapProvider` raises a clear `NotImplementedError` when images
  are supplied, falling back to a text description if present
- [ ] Unit tests cover happy path, oversized images (rejected with a clear
  error), and unsupported providers

### 48.2 High — Grafana screenshot tool

- [ ] `GrafanaScreenshotTool` renders a panel or a dashboard as PNG via
  Grafana's `/render` endpoint, using the existing COS configuration
- [ ] Tool returns both the PNG bytes (for image-input) and a text caption
  (panel title, time range, unit axes) so text-only providers still benefit
- [ ] Works against the cross-model COS integration from Phase 22.2

### 48.3 Medium — Tempo trace waterfall rendering

- [ ] `TempoWaterfallTool` takes a trace id, fetches the trace from Tempo
  (Phase 2.2), and renders a waterfall PNG using a lightweight SVG-to-PNG
  pipeline
- [ ] Caption includes the slowest spans and total duration in text

### 48.4 Medium — Juju status tree rendering

- [ ] `JujuStatusRenderTool` captures the current `juju status` output and
  renders it as a coloured tree PNG (using `rich` offscreen rendering already
  available in the TUI)
- [ ] Useful for diagnosing status tables that are long enough to lose
  structure in a text response

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

### 49.1 High — Linux PID and mount namespace isolation

- [ ] A `SandboxedRunner` in `src/cantrip/agent/sandbox.py` wraps subprocess
  invocations with `unshare --pid --mount --net=none` (with opt-out for tools
  that legitimately need network, e.g. `JujuDeployTool`)
- [ ] Separate mount namespace with read-only bind mounts for system paths,
  read-write only for the working tree (or worktree, per Phase 44)
- [ ] Opt-out whitelist is per-tool, not per-command, and declared in the tool
  dataclass
- [ ] Unit tests verify the sandboxed command cannot read files outside the
  bind-mounted working tree

### 49.2 High — Deny-rule hardening

- [ ] Match `env`, `sudo`, `watch`, `nohup`, `setsid`, and similar wrappers
  when inspecting commands, so a deny rule on `rm` is not bypassed by
  `env rm ...`
- [ ] Apply the same normalisation in shell-pipeline form (`x | rm ...`)
- [ ] Tests exercise each wrapper form

### 49.3 Medium — Per-tool syscall allowlists

- [ ] Seccomp-bpf allowlists for tools with constrained syscall needs (e.g.
  `CharmcraftPackTool` does not need network beyond PyPI; `git_log` does not
  write files)
- [ ] Allowlists are opt-in per tool and fall back to the namespace-only
  sandbox when seccomp is unavailable

### 49.4 Medium — macOS path hardening

- [ ] On macOS, apply the `sandbox-exec` profile pattern Claude Code uses to
  restrict filesystem access to the working tree and Cantrip config directory
- [ ] Fall back to a warning (no hard enforcement) on older macOS where
  `sandbox-exec` is deprecated

### 49.5 Low — Sandbox observability

- [ ] Log sandbox policy decisions (bind mounts, denied syscalls) to the
  transcript so reviewers can audit them
- [ ] `/sandbox status` command shows current sandbox mode and per-tool
  overrides

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

### 50.1 Medium — Import from standard-format Skills directories

- [ ] Discover skills in `~/.config/cantrip/skills/*.md` and
  `~/.claude/skills/` that follow the standard YAML-frontmatter + markdown
  shape, and surface them alongside Cantrip's built-in skills
- [ ] Translate the frontmatter (`name`, `description`, `tools`) into
  Cantrip's internal skill dataclass
- [ ] Imported skills can reference MCP tools from Phase 45 when the MCP
  client exposes them

### 50.2 Medium — Export Cantrip skills to the standard format

- [ ] `cantrip skill export <name> <path>` emits a standard-format skill file
  for the named Cantrip skill
- [ ] Sanitise any charm-specific paths and placeholders (matching the
  Phase 43.4 export rules)
- [ ] Round-trip test: export, clear, re-import, verify content and metadata
  are preserved

### 50.3 Low — `gh skill` discovery

- [ ] Detect skills installed via `gh skill install` by reading the standard
  install location
- [ ] Document in the README how users install skills from
  `microsoft/skills` and use them with Cantrip

### 50.4 Low — MCP-aware skills

- [ ] Skills can declare MCP server dependencies in their frontmatter; the
  loader checks the MCP client (Phase 45) has those servers configured before
  activating the skill
- [ ] Missing dependencies degrade gracefully with a clear warning

**Exit criteria:** Users can drop a standard-format skill into
`~/.config/cantrip/skills/` and have Cantrip use it; Cantrip skills round-trip
through the standard format; MCP-aware skills work with the Phase 45 client.
`make check` passes throughout.

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

### 52.1 Medium — Checkpoint schema and storage helpers

- [ ] Add a `step_checkpoints` table to the `.cantrip` SQLite schema
  (new migration):
  ```
  step_checkpoints(
    id              INTEGER PRIMARY KEY,
    task_id         TEXT    NOT NULL,
    step_name       TEXT    NOT NULL,
    ordinal         INTEGER NOT NULL,      -- auto-numbered for repeats
    input_hash      TEXT    NOT NULL,      -- sha256 over normalised inputs
    result_blob     BLOB    NOT NULL,      -- msgpack-encoded return value
    result_kind     TEXT    NOT NULL,      -- 'llm_response' | 'tool_result' | 'value'
    created_at      TEXT    NOT NULL,
    UNIQUE(task_id, step_name, ordinal)
  );
  CREATE INDEX ix_step_checkpoints_task ON step_checkpoints(task_id);
  ```
- [ ] Implement `CheckpointStore` helpers on top of the existing SQLite
  session: `record(task_id, step_name, ordinal, input_hash, kind, value)`,
  `get(task_id, step_name, ordinal)`, `next_ordinal(task_id, step_name)`.
  Values serialise via msgpack (already a dep through providers) with
  a fallback to JSON for debuggability.
- [ ] Garbage-collect checkpoints when a task terminates successfully —
  retain for failed/paused tasks so the next run can resume.  Config:
  `CANTRIP_KEEP_CHECKPOINTS=1` to preserve all for debugging.

### 52.2 Medium — `checkpoint()` wrapper helper

- [ ] A single async helper in `cantrip.agent.durability`:
  ```python
  async def checkpoint(
      ctx: CheckpointCtx,
      step_name: str,
      fn: Callable[[], Awaitable[T]],
      *,
      input_hash: str | None = None,
      kind: str = "value",
  ) -> T: ...
  ```
- [ ] Semantics mirror Absurd's `ctx.step`: compute the next ordinal for
  this `(task_id, step_name)` pair, look up the checkpoint, return the
  stored value if present, otherwise run `fn()` and persist the result
  before returning.
- [ ] On input-hash mismatch (same step name + ordinal, different
  inputs) — invalidate the checkpoint and re-run, logging a warning.
  This prevents a stale checkpoint from masking a code change.
- [ ] The `CheckpointCtx` is constructed once per subagent task; it
  closes over the `task_id` and a monotonic per-step counter so
  repeated calls to `checkpoint(ctx, "llm_turn", …)` auto-number
  (`llm_turn`, `llm_turn#2`, …) without the caller tracking indices.

### 52.3 Medium — Wire checkpoints into the subagent loop

- [ ] Wrap each LLM call in the subagent turn loop with
  `checkpoint(ctx, "llm_turn", lambda: provider.complete(...))`.
  Result kind = `llm_response`; input hash includes model, conversation
  prefix hash, tools schema hash.
- [ ] Wrap each tool-call execution with
  `checkpoint(ctx, f"tool:{tool_name}", lambda: tool.run(args))`.
  Result kind = `tool_result`; input hash = sha256 of canonicalised
  `args`.  Tool failures are persisted as *negative* checkpoints so a
  deterministic error doesn't replay forever — but the user can opt in
  to "retry failed steps on resume" via a session flag.
- [ ] Streaming LLM responses checkpoint *after* the full response is
  assembled; partial streams are not persisted (they're free to
  re-request on replay).  The existing streaming UI plumbing is
  unaffected.

### 52.4 Medium — Resume path on session start

- [ ] When the executor picks up an `ACTIVE → PENDING`-reset task that
  has step checkpoints, surface this in the task checklist: *"resuming
  from step N"*.  Do NOT silently resume — the user sees that a
  previous attempt was interrupted and knows why the token count
  doesn't start at zero.
- [ ] `cantrip session inspect <session>` (or TUI F-key) shows the
  checkpoint count and list for the current task, so users can see
  what's cached before deciding whether to resume or clear.
- [ ] Resume is opt-out via `CANTRIP_NO_RESUME=1` for debugging — useful
  when hunting a bug that might itself be cached in a stale
  checkpoint.

### 52.5 Low — Observability and debugging

- [ ] Extend the transcript viewer (F9) with a "checkpoints" tab that
  shows, per task, the recorded steps, ordinals, input hashes, and
  timestamps.  Click-through to view the stored result blob.
- [ ] Add a `cantrip checkpoints {list,show,delete}` CLI subcommand
  for scripted inspection and surgical removal.
- [ ] Emit a structured event on every checkpoint hit/miss so the
  watcher dashboards can plot replay efficiency over a session.

### 52.6 Low — Cost accounting for replayed steps

- [ ] Token-usage records note whether a turn's tokens came from a
  fresh provider call or a checkpoint replay — the model-info bar and
  transcript show "X tokens (Y cached from checkpoint)" so the cost
  signal isn't misleading.
- [ ] On replay, we do not double-count tokens toward the rate-limit
  budget tracker (which already treats cache hits correctly; this
  extends the same treatment to checkpoint hits).

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

## Phase 53: Organisation Cleanup — Prompts, Planner, Dev Docs

**Goal:** Finish the job started in Phase 0.5 and the skills work — every
piece of transferable charm-building knowledge lives in markdown or
Jinja2 templates, not inside Python source.  A fresh systematic review
identified three concrete leaks:

- `src/cantrip/agent/planner.py` has three triple-quoted prompt
  constants (`_PLANNING_PROMPT`, `_DESIGN_TO_BUILD_PROMPT`,
  `_DAY2_TO_BUILD_PROMPT`) at lines ~1196–1440 — collectively ~380 lines
  of planner guidance text living inside a `.py` file.
- The deterministic task generators (`plan_sprint_deploy`,
  `plan_fast_path`, `plan_one_shot_build`, `plan_improvement_*`,
  `plan_day2_*`) embed 20–50 line f-strings of numbered steps and
  operational guidance into each `AgentTask.description`.  These are
  instructions the agent *reads*, not metadata.
- `planner.py` is 1620 lines and mixes deterministic task templates
  with LLM-driven planning helpers; once the prompt text is extracted,
  the remaining code should split along that seam.

Two smaller wins round out the phase: rename `tools/registry.py` to
clarify it is OCI/Docker registry search (not a tool registry), and
add three design documents (`TOOLS.md`, `SKILLS.md`, `PROMPTS.md`)
that record currently-implicit invariants of the three subsystems.

### 53.1 High — Extract planner prompts to `.md.j2` templates

- [ ] Create `src/cantrip/agent/prompts/planning/` with three templates:
  `full.md.j2` (was `_PLANNING_PROMPT`), `design_to_build.md.j2`, and
  `day2_to_build.md.j2`
- [ ] Add a small loader next to `prompts/system.py` that lazy-loads
  these templates with the same `StrictUndefined` + sanitisation shape
  as the system prompt
- [ ] Replace the Python constants in `planner.py` with calls into the
  loader; keep the existing `{categories}` / `{context_block}` variable
  substitution semantics
- [ ] Unit tests verify the rendered output is byte-identical to the
  pre-extraction prompts for a fixed set of inputs (freezes behaviour)

### 53.2 High — Extract task-description guidance to templates

- [ ] Create `src/cantrip/agent/prompts/tasks/` with one `.md.j2` per
  deterministic task generator that currently builds a multi-line
  description: `sprint_build.md.j2`, `sprint_deploy.md.j2`,
  `fast_path_build.md.j2`, `one_shot_build.md.j2`,
  `improvement_fixes.md.j2`, `operability_*.md.j2`, etc.
- [ ] Add a helper `render_task_description(name, **vars)` that picks
  the right template and renders it with the planner's per-task context
  (workload, ubuntu version, profile, design text, …)
- [ ] `AgentTask.description` is populated from the helper; no
  per-task f-strings remain in `planner.py`
- [ ] Snapshot tests lock in the rendered text for a canonical input
  set — protects against accidental drift during the extraction

### 53.3 Medium — Split `planner.py` along the deterministic / LLM seam

- [ ] Introduce `src/cantrip/agent/planner/` package; move the
  deterministic generators into `planner/deterministic.py` and the
  LLM-driven code path (`TaskPlanner`, prompt loaders, JSON parser,
  dependency validator) into `planner/llm.py`
- [ ] Keep `planner/__init__.py` re-exports stable so existing
  `from cantrip.agent.planner import …` imports do not break
- [ ] Move the classifier helpers (`is_fast_path`, `is_sprint`,
  `is_improvement`, `is_one_shot_build`) into `planner/routing.py`
  alongside the existing top-level `routing.py` or merge the two
- [ ] No functional change — behaviour is covered by the existing
  planner unit tests plus the snapshot tests from 53.1 and 53.2

### 53.4 Low — Rename `tools/registry.py` → `tools/oci_registry.py`

- [ ] `src/cantrip/agent/tools/registry.py` currently holds Docker
  Hub / OCI image-search tools, not a tool-registration mechanism —
  rename to `oci_registry.py` to match its contents
- [ ] Update the single import in `tools/__init__.py`
- [ ] Grep-verify no other code references the old module name

### 53.5 Medium — Add dev design docs for the three subsystems

- [ ] `design/TOOLS.md` — the `Tool` ABC contract, the `build_tools()`
  factory pattern, how to add and remove a tool, where tool schemas
  come from, conventions for naming and file layout, how tools
  interact with `PathAwareTool` and the virtual-file store
- [ ] `design/SKILLS.md` — `SKILL.md` discovery via `SkillsIndex`,
  frontmatter schema, lazy-load-on-demand flow, the skill index injected
  into the system prompt, interop with Phase 50 standard-format skills
- [ ] `design/PROMPTS.md` — the prompt layering (system full / system
  compact / subagent / planning / task descriptions / skills loaded on
  demand), Jinja2 conventions (`StrictUndefined`, trailing newlines),
  the `_JINJA_SYNTAX` sanitisation regex and why it exists, extension
  points for new prompt types
- [ ] Cross-link the three docs from `design/PLAN.md` so the
  architecture index points at them

### What this phase is *not*

- Not a rewrite of the planner's behaviour.  The LLM-driven path keeps
  its current prompt; we only change *where the prompt text lives*.
- Not a new abstraction layer.  Templates go into the same `prompts/`
  directory structure the system prompt already uses — no new loader
  framework, no plugin system.
- Not a docs-site refresh.  User-facing documentation under `docs/docs/`
  is handled separately in Phase 54.

**Exit criteria:** No triple-quoted prompt constants or multi-line
task-description f-strings remain in `planner.py` (or anywhere under
`src/cantrip/agent/`) — `grep` confirms.  `planner.py` is split into a
package with modules under 800 lines each.  `tools/registry.py` is
renamed.  `design/TOOLS.md`, `design/SKILLS.md`, `design/PROMPTS.md`
exist and are linked from `PLAN.md`.  Snapshot tests protect the
extracted prompts against accidental drift.  `make check` passes.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Planner prompts (53.1) | Phase 0.5 prompt templating | Reuses `system.py` pattern |
| Task descriptions (53.2) | 53.1 | Shares the new loader |
| Planner split (53.3) | 53.1, 53.2 | Clean seam only exists after extraction |
| Registry rename (53.4) | none | Independent; can land first |
| Design docs (53.5) | 53.1–53.4 | Document the final shape, not the intermediate |

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

### 54.1 High — Audit the existing HTML and pick a conversion path

- [ ] Inventory every `docs/docs/*.html` page: headings, code blocks,
  callouts, admonitions, cross-links, images, anchor IDs used by
  external links, and any custom classes from `docs.css`
- [ ] Pick a conversion tool (candidates: `pandoc`, `html2markdown`,
  `markdownify`) and a target flavour (CommonMark vs MyST vs
  MkDocs-Material-flavoured markdown); prefer the flavour that round-
  trips back to HTML byte-identical or close to it
- [ ] Convert one representative page end-to-end as a pilot and diff
  the rebuilt HTML against the original — document what the tool
  handles losslessly vs what needs manual fix-up
- [ ] Write up the decision in `design/DOCS_REBUILD.md` so the
  conversion rationale is preserved even if this phase spans many
  sessions

### 54.2 High — Convert every page and reconcile

- [ ] Convert all 13 pages under `docs/docs/` to markdown in the
  chosen flavour
- [ ] Manually reconcile anything the converter dropped: admonition
  boxes, syntax-highlighted code-block languages, anchor IDs linked
  from other pages, footnote numbering, image paths
- [ ] Preserve the Diátaxis filename convention
  (`tutorial.md`, `howto-*.md`, `reference-*.md`, `explanation-*.md`)
- [ ] Place the new markdown under `docs/src/` (or similar) so the
  already-built HTML in `docs/docs/` keeps working until the build
  system lands in 54.3

### 54.3 Medium — Set up a markdown-to-HTML build system

- [ ] Pick a static-site generator that fits (MkDocs with Material,
  or a MyST-parser Sphinx setup, or a plain pandoc make-rule) — match
  the flavour chosen in 54.1
- [ ] Configure the build to emit HTML into `docs/docs/` with the
  same filenames the current site uses, so external links keep
  working
- [ ] Preserve the `docs.css` styling and the current logo / favicon
  assets under `docs/`
- [ ] Add a `make docs` target and CI step that rebuilds the site
  and diffs against the committed HTML (catches drift between the
  markdown sources and the published HTML)

### 54.4 Low — Round-trip verification and retire the old HTML

- [ ] Run the full build; diff page-by-page against the original HTML;
  document any intentional formatting differences
- [ ] Once parity is confirmed, the generated `docs/docs/*.html` files
  become build artifacts — they can either stay committed (for
  GitHub Pages-style hosting) or move into CI-only
- [ ] Update `CONTRIBUTING.md` with the new docs workflow: edit
  markdown under `docs/src/`, run `make docs`, commit both

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

### 55.1 Medium — Skill-as-folder convention

- [ ] Read a representative sample of awesome-copilot skills
  (`skills/acquire-codebase-knowledge/`, `skills/agent-governance/`,
  `skills/pytest-coverage/`) and document the folder shape:
  `SKILL.md` + `assets/templates/` + `scripts/` + `references/`
- [ ] Compare against Cantrip's current skill layout under
  `src/cantrip/agent/skills/` — what lives alongside `SKILL.md`
  today, and what would naturally move in (charm scaffolds, Scenario
  test fixtures, Jubilant fixtures, rockcraft / charmcraft templates)
- [ ] Prototype one skill (candidate: `harness-migration` from commit
  8621c49) converted to the full folder layout and report what broke
  or improved
- [ ] Record the decision as a section in `design/SKILLS.md` once Phase
  53.5 lands that file; do not create a parallel design doc

### 55.2 Medium — Frontmatter metadata on subagents and prompts

- [ ] Audit what Cantrip currently knows about each subagent at
  invocation time (allowed tools, model hint, which loop should
  dispatch it) and where that knowledge lives (hardcoded registry?
  constructor args? config?)
- [ ] Sample awesome-copilot's agent frontmatter shape in
  `instructions/agents.instructions.md` (fields: `description`, `name`,
  `tools`, `model`, `target`, `user-invocable`,
  `disable-model-invocation`, `handoffs`) and two to three files under
  `agents/`
- [ ] Decide whether a YAML frontmatter block on each subagent prompt
  (`applyTo:`, `tools:`, `model:`) would let the planner mechanically
  filter subagents — or whether the current Python-side registry is
  already better because subagent metadata needs to be executable,
  not just descriptive
- [ ] Evaluate the Copilot `handoffs:` concept as a way to make the
  planner's task-chaining data-driven: today the "build → deploy →
  verify" chain is hardcoded in `plan_sprint_deploy` etc.; a
  `handoffs: [deploy, verify]` field on a task template would push the
  routing into data.  Sketch one concrete task and diff the two shapes
- [ ] Adopt an explicit, named auto-approve sentinel in the subagent
  dispatcher (mirrors Copilot's `PermissionHandler.approve_all`).
  Today "approve everything the parent approved" is implicit;
  naming the mode makes the autonomous loop's permission model
  inspectable
- [ ] Output: a short section in `design/PROMPTS.md` (landing in 53.5)
  either proposing the schema or recording why it was rejected;
  handoffs evaluated separately and either folded in or filed as a
  follow-up phase

### 55.3 Medium — Ralph-loop / disk-as-state comparison and per-goal budget

- [ ] Read `../awesome-copilot/cookbook/copilot-sdk/python/recipe/ralph_loop.py`
  end-to-end and diagram its control flow
- [ ] Diff the pattern against Cantrip's two-loop architecture in
  `design/AGENT.md` and the Phase 52 step-level durable-execution
  design
- [ ] Call out any primitive the ralph pattern has that Cantrip does
  not (fresh context per iteration? on-disk plan file convention?
  recovery semantics?) — the overlap is large, so the interesting
  output is the delta, not the similarity
- [ ] The one ralph primitive Cantrip is missing is a **hard
  per-goal iteration and token budget** with a circuit breaker.
  Today the autonomous loop runs until the planner declares done,
  which is a long way from safe.  Scope a small addition: a per-goal
  `max_iterations` and `max_tokens` counter in the executor, with a
  clean shutdown path (save checkpoint, surface a `BudgetExceeded`
  event to the UI) when tripped.  Pairs with 55.4's rate-limit work
- [ ] Output: a paragraph in `design/AGENT.md` pointing at the ralph
  loop as prior art; a concrete implementation sketch for the
  per-goal budget (not necessarily built in this phase — the
  investigation ends at "scoped and sized")

### 55.4 High — Policy composition for tool access

This item stays firmly in the investigation bucket: the scope below
expanded after a closer read of the agent-governance skill, but
nothing here is a commitment.  The phase output is a recommendation,
possibly with a small prototype, not a delivered refactor.

- [ ] Read `../awesome-copilot/skills/agent-governance/SKILL.md` in
  full (six patterns: `GovernancePolicy`, `compose_policies()`,
  intent classification, `@govern` decorator, trust scoring, audit
  trail) and any referenced scripts
- [ ] Map current Cantrip tool-gating: today `_filter_tools(tools,
  category)` in `src/cantrip/agent/subagent.py:466` is a single-level
  category allowlist.  Document where "this subagent may not run
  `juju destroy-model`" *would* need to get enforced to be sound
  (likely: inside `src/cantrip/agent/tools/juju.py` and
  `run_command.py`, not as a category filter)
- [ ] Evaluate each governance primitive against Cantrip's needs and
  file a keep / defer / reject recommendation:
  - **`compose_policies()` (stacked allowlists, most-restrictive-wins)** —
    likely keep; replaces the single-level category filter with global
    + per-task-type + per-charm layers
  - **Per-goal rate limits (`max_calls_per_request`)** — likely keep;
    pairs with 55.3's iteration budget as a cost safety valve
  - **JSONL audit trail** — likely keep; emits machine-readable tool
    events alongside the existing SQLite session state for post-hoc
    analysis and compliance export
  - **Juju-aware destructive-command gate inside the executor** —
    likely keep; the Phase 55.5 / Copilot `tool-guardian` hook
    protects user-initiated shell calls but autonomous-loop invocations
    through `tools/juju.py` bypass any external shell hook entirely, so
    the gate must live inside Cantrip's own code paths
  - **Trust scoring with temporal decay** — likely reject; Cantrip
    does not have multi-party delegation between untrusted agents
  - **Intent classification / threat regexes** — defer; most of the
    signal in a charm-building context comes from the tool surface
    (`juju destroy-*`), not the prompt content
- [ ] Explain how this relates to Phase 46 (user hooks) and Phase 49
  (sandboxed shell): user hooks fire at lifecycle events; sandboxing
  isolates subprocess execution; policy composition gates which tools
  the LLM is allowed to *request* in the first place — all three
  layers are complementary
- [ ] Output: a written recommendation filed as a new phase proposal
  (likely "Phase 57: Stacked Tool-Access Policies") or a
  "rejected — here's why" entry appended to this roadmap.  A tiny
  prototype of `compose_policies()` against one existing task type is
  welcome but not required

### 55.5 Low — Markdown workflows versus Python orchestration

- [ ] Read two or three files under `../awesome-copilot/workflows/`
  (especially `ospo-release-compliance-checker.md`) to see how
  agentic workflows get expressed as plain markdown with frontmatter
  instead of YAML DSLs or Python glue
- [ ] Identify one Cantrip flow currently expressed as Python
  orchestration (candidate: the deterministic `plan_sprint_deploy`
  chain) and sketch what it would look like as a markdown workflow
  file loaded through the same Jinja2 path as prompts
- [ ] Decide: is the deterministic planner's Python code clearer, or
  would markdown-with-frontmatter be a better authoring surface for
  the sprint / fast-path / one-shot recipes?
- [ ] Regardless of the main verdict, lift two micro-patterns from
  the ospo workflow that are worth adopting on their own:
  - **`safe-outputs` cap** — a declarative limit on how many side
    effects a task can produce (e.g. "at most 1 PR", "at most 3
    `juju deploy` calls").  Lands as a field on task templates and
    composes with 55.4's rate-limit work
  - **Explicit trigger guard as step 1** of every task template —
    the workflow's first section reads the event and bails early if
    preconditions fail.  Cantrip task templates currently launch
    straight into instructions; a "first, check X/Y/Z — stop if not"
    header would catch misrouted tasks before they burn tokens
- [ ] Output: a short note — likely rejecting the main format, since
  the deterministic planner has strong reasons to stay in Python —
  but capturing the reasoning and the two lifted micro-patterns so
  they are not re-litigated later

### 55.6 Medium — Runnable cookbook

- [ ] Review `../awesome-copilot/cookbook/copilot-sdk/python/recipe/`
  (`ralph_loop.py`, `multiple_sessions.py`, `managing_local_files.py`,
  `error_handling.py`) as a model for runnable-example cookbooks
- [ ] Enumerate four to six candidate recipes Cantrip could publish as
  end-to-end executable Python scripts: "build a stateful charm",
  "deploy to Juju with COS", "add ops-tracing to an existing charm",
  "migrate a Harness test to Scenario", "run charm tests end-to-end",
  "generate a Terraform module"
- [ ] Pick one and build it: `cookbook/build-a-stateful-charm/` that
  drives Cantrip through the full loop and captures the transcript
- [ ] Wire at least one recipe into CI so it runs on every PR —
  doubles as onboarding documentation and a regression fixture
- [ ] Cross-link the cookbook from `CONTRIBUTING.md` and the docs site
- [ ] Micro-improvement out of the `pytest-coverage` skill review:
  add `--cov-report=annotate:cov_annotate` to `make coverage` so
  subagents can read annotated source files directly (lines prefixed
  `!` are uncovered).  One-line change, no new skill needed

### 55.7 Medium — Deterministic pre-scan for Path B custom apps

- [ ] Read `../awesome-copilot/skills/acquire-codebase-knowledge/scripts/scan.py`
  (~500 lines: manifest detection for 25+ languages, CI/CD platform
  detection, container and orchestration detection, code metrics,
  security-config detection, recent-commit churn)
- [ ] Map the pieces onto Cantrip's Path B (custom apps) discovery
  phase: today the LLM alone figures out "this is a Flask app / Go
  service / Node.js server" from chat context.  A deterministic
  manifest-and-CI scan seeded into the planner's first turn would
  save round-trips and improve reliability
- [ ] Decide: vendor the script (MIT-licensed), port its logic into a
  Cantrip-native `src/cantrip/agent/tools/scan.py`, or invoke it as
  a subprocess.  Porting is probably right — the script has Cantrip-
  specific needs (rockcraft / charmcraft manifest awareness) that an
  upstream version does not cover
- [ ] Output: a recommendation with a concrete file-layout proposal,
  and a stub implementation if the call is "port"

### 55.8 Low — Charm-design spec template

- [ ] Read `../awesome-copilot/skills/create-github-action-workflow-specification/SKILL.md`
  for its output shape: mermaid diagrams, job-dependency tables,
  trigger matrices, implementation-agnostic prose with strict
  frontmatter
- [ ] Cantrip does not reverse-engineer workflows, so skip the skill
  itself.  Evaluate whether Cantrip's planner should emit a *charm-
  design spec* in a similar shape before Path B or Path C builds:
  mermaid diagram of relation integrations, config-option table,
  container/resource table, actions list, implementation-agnostic
  description.  Today that design lives half in chat messages and
  half in the task description
- [ ] Prototype one spec by hand for an existing generated charm and
  decide whether making it a required pre-build artefact would improve
  the user-confirmation step or add friction
- [ ] Output: either a template committed to
  `src/cantrip/agent/prompts/design/charm_spec.md.j2` wired into the
  planner, or a rejection note explaining why chat-based design
  confirmation is already sufficient

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

## Phase 57: Test-Suite Cleanup — Organisation, Coverage, Warnings

**Goal:** Close the gaps surfaced by the Phase 53 review's follow-on
test audit.  Unit coverage sits at 77% with two kinds of holes: entry
points at 0% (``cli.py``, ``main.py``, ``juju/log_stream.py``), and
subprocess-heavy tools where only the parameter-validation paths are
exercised (``chaos``, ``scaling``, ``upgrade``, ``charmlint_tool``,
each 20–28%).  TUI screens and the web server are also thin.
Alongside coverage, the audit surfaced a handful of structural and
hygiene issues — oversized test files, an asymmetry between
``charmlint`` and ``quickpack`` test layout, and eight test warnings
pytest currently swallows.

Every item in this phase is "add tests to code that already works"
or "move tests around".  No production code change expected.

### 57.1 High — Fix the lingering test warnings ✓

Pytest reports 8 warnings (grouped as 5 in the summary).  Three
categories, three distinct fixes:

- [x] **Unclosed event loop in ``test_gemini.py``** — the leak is
  actually inside ``pytest-asyncio`` 1.3.0's ``_temporary_event_loop_policy``
  context manager: in auto mode it calls ``asyncio.get_event_loop()``
  for every sync test, which allocates a fresh loop that never gets
  closed.  Since the leak is third-party, the fix is a narrow
  ``filterwarnings`` entry instead of a code change
- [x] **Unawaited coroutine from mocked ``proc.kill()``** in
  ``test_observability_tools.py`` and ``test_tools.py`` (concierge
  tests).  Production code (``observability.py:143``,
  ``environment.py:65``) calls ``proc.kill()`` — a sync method on
  ``asyncio.subprocess.Process``.  The tests use ``AsyncMock`` which
  makes every attribute async, producing an unawaited coroutine.
  Fix in the tests: explicitly set ``proc.kill = MagicMock()`` so the
  mocked attribute is sync.  Also surfaced a related leak: mocking
  ``asyncio.wait_for`` with ``side_effect=TimeoutError`` raises before
  awaiting the first argument, so ``proc.communicate()`` returns an
  unawaited coroutine.  New ``_raise_timeout`` helper closes the
  coroutine before raising
- [x] **``NotAppKeyWarning`` in ``test_web_server.py``** — aiohttp's
  newer API prefers ``web.AppKey[T]`` over string keys.  Define
  module-level ``AGENT_KEY``, ``WS_CLIENTS_KEY`` etc. and migrate the
  three call sites.  Production code and tests both migrated
- [x] Tighten the ``filterwarnings`` allowlist in ``pyproject.toml``
  after the fixes — the current
  ``"ignore::RuntimeWarning:unittest.mock"`` entry masks broader
  issues than needed.  Replaced with a single narrow filter for the
  pytest-asyncio event-loop leak described above

### 57.2 High — Zero-coverage entry-point modules ✓

- [x] ``src/cantrip/cli.py`` (0% → 97%) — argparse-level unit
  tests for every subcommand flag, plus a smoke test that exercises
  the import path.  Mock the agent factory and provider.  43 tests
  drive the REPL via a canned ``asyncio.to_thread(input, ...)``
  side-effect queue, cover every ``/help`` / ``/tasks`` / ``/status``
  / ``/cost`` / ``exit`` command, the keyboard-interrupt and
  provider-error branches, and the re-bootstrap path
- [x] ``src/cantrip/main.py`` (0% → 99%) — the cli / tui / web
  dispatch layer.  Unit-test the routing decisions without actually
  launching any mode.  32 tests cover ``parse_args`` (including the
  "bare path becomes run" and "bare flag becomes run" shortcuts),
  ``_install_unraisable_hook``, ``_is_cantrip_source_tree``, every
  ``_run`` dispatch branch (web/TUI/CLI and missing-API-key guards),
  and ``_export_transcript`` for every format plus paginated HTML
- [x] ``src/cantrip/juju/log_stream.py`` (0% → 100%) — fixture-
  based stream parsing tests; the live end stays live-only.  10
  tests, including UTF-8 replacement decoding and
  ``ProcessLookupError`` cleanup

### 57.3 High — Tool ``execute()`` coverage ✓

Four tools with 20–28% coverage all follow the same pattern: a thin
``Tool`` subclass wrapping a subprocess invocation, only the
parameter-validation paths tested.

- [x] ``tools/scaling.py`` (20% → 100%)
- [x] ``tools/upgrade.py`` (21% → 99%)
- [x] ``tools/charmlint_tool.py`` (24% → 99%)
- [x] ``tools/chaos.py`` (28% → 97%)

Target each to ≥70% via subprocess-mocked ``execute()`` tests.
Use ``tests/unit/test_git_tools.py`` as the pattern — success,
non-zero exit, stderr-only output, timeout.  All four landed; 65 new
tests across four files.  Each test fakes ``juju_subprocess.run_juju``
(or ``subprocess.run`` for charmlint) and ``wait_for_app`` so no real
Juju invocation is needed.

### 57.4 Medium — Web-server WebSocket lifecycle ✓

``src/cantrip/web/server.py`` was at 24%.  The REST endpoints were
covered; the WebSocket code was not.

- [x] Tests for connect / disconnect flows, chat_input round-trip,
  broadcast fan-out to multiple clients, stale-client pruning, and
  each exception branch in ``_websocket_handler`` (rate-limited,
  overloaded, provider error, OSError/ValueError/RuntimeError)
- [x] Covered the ``/api/logs-stream`` WebSocket — no-model/no-CLI
  branches, happy-path streaming, invalid-level normalisation, and
  OSError mid-stream
- [x] Covered ``/api/logs`` edge cases (missing CLI, non-integer
  ``lines=`` falls back, ``TimeoutExpired`` swallowed)
- [x] Covered the REST handlers (``_index``, ``_api_state``,
  ``_api_messages``, ``_api_juju_status`` for each branch) plus
  ``_make_bus_forwarder``, ``_create_app``, and ``run_web`` dispatch
- [x] Used ``aiohttp.test_utils.TestClient`` with ``ws_connect``
  as prescribed
- [x] Migrated remaining string keys in ``server.py`` to typed
  ``web.AppKey`` (``CHAT_LOCK_KEY``, ``JINJA_ENV_KEY``, ``PORT_KEY``)
  to keep the zero-warning exit criterion

Result: ``src/cantrip/web/server.py`` moved from 24% to 99% line
coverage.  44 new tests added.

### 57.5 Medium — TUI screen Pilot tests

Textual's ``Pilot`` lets tests drive an app programmatically.  Three
screens are under 40%:

- [ ] ``tui/screens/relation.py`` (21%)
- [ ] ``tui/screens/questions.py`` (30%)
- [ ] ``tui/app.py`` (40%) — targeted branches, not full coverage

One Pilot interaction test per screen — open, do the key action,
assert the rendered state — raises each to ≥60%.

### 57.6 Medium — Core-agent branch coverage

``src/cantrip/agent/core.py`` is at 62% (287 uncovered of 752
statements).  Hot zones: the GitHub PR/issue triage helpers
(lines ~1076–1460), streaming-response branches, some watcher
integration paths.

- [ ] Targeted unit tests with ``FakeProvider`` streaming responses
- [ ] Mocked ``gh`` tool results for the triage helpers
- [ ] Target 80% on this one file

### 57.7 Medium — Split oversized unit-test files

Four unit-test files top 1500 lines:

- [ ] ``tests/unit/test_executor.py`` (1972 lines) — split by
  ``TestClass`` into ``test_executor_*.py``
- [ ] ``tests/unit/test_planner.py`` (1705 lines) — split by
  concern (parsing, routing, deterministic paths, LLM paths)
- [ ] ``tests/unit/test_subagent.py`` (1542 lines)
- [ ] ``tests/unit/test_tools.py`` (1514 lines) — already a grab-bag;
  fold tests into per-tool files where one exists

Each target file ≤600 lines.

### 57.8 Low — Reorganise quickpack unit tests

- [ ] Move ``tests/unit/test_quickpack.py`` (977 lines, 83 tests)
  and ``tests/unit/test_quickpack_comparison.py`` into
  ``tests/unit/quickpack/`` matching the ``tests/unit/charmlint/``
  layout.  Split the flat file into ``test_metadata.py``,
  ``test_pack.py``, ``test_parts.py``, ``test_jujuignore.py``
  matching the ``src/quickpack/`` module boundaries.

### What this phase is *not*

- Not chasing 100% coverage.  Targets above are pragmatic (70–80%
  per file) — branches that exist to guard against "this shouldn't
  happen" in production are fine to leave uncovered.
- Not about Rust tests — those have their own phase.
- Not about property-based testing — same.

**Exit criteria:** ``make coverage`` reports ≥85% total line
coverage (up from 77%).  No file under ``src/cantrip/`` below 50%
except the ``tui/`` screens that require a display environment.
``pytest tests/unit`` reports zero warnings.  Unit-test files
organised to match source-file boundaries.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Warnings (57.1) | none | Independent; can land first |
| Entry points (57.2) | none | Independent |
| Tool execute (57.3) | none | Copy-pattern from existing tool tests |
| WebSocket (57.4) | none | Uses existing ``aiohttp.test_utils`` |
| TUI Pilot (57.5) | none | Textual already a dep |
| Core branches (57.6) | none | Uses existing ``FakeProvider`` |
| File splits (57.7) | none | Mechanical move; do last to avoid churn |
| Quickpack reorg (57.8) | 57.7 | Same mechanical-move nature |

---

## Phase 58: Rust Crate Unit Tests

**Goal:** Close the coverage cliff on the two Rust reimplementations.
The Python ``charmlint`` has a full ``tests/unit/charmlint/`` suite
(config, linter, models, rules, unknown fields, CLI, attestations,
charmcraft compat); its Rust twin in ``src/charmlint-rs/`` contains
**zero** ``#[test]`` blocks.  Same story for ``src/quickpack-rs/``.
The only validation for either Rust crate is the spread test that
runs the compiled binary against a fixture charm — good e2e signal
but leaves every internal function unchecked.  A regression in
``jujuignore.rs`` or ``linter.rs`` surfaces only when it happens to
break an end-to-end scenario.

This is the single largest testing gap in the codebase.

### 58.1 High — Seed unit tests for each Rust module

For each ``.rs`` file in ``src/charmlint-rs/src/`` and
``src/quickpack-rs/src/``, add a ``#[cfg(test)] mod tests`` block
covering the primary functions.  Target parity with the Python
implementation, not 100% — a Rust version of each Python test.

- [x] ``src/charmlint-rs/src/config.rs`` — config parsing
- [x] ``src/charmlint-rs/src/context.rs`` — context loading
- [x] ``src/charmlint-rs/src/linter.rs`` — rule dispatch
- [x] ``src/charmlint-rs/src/models.rs`` — severity / finding shape
- [x] ``src/charmlint-rs/src/rules.rs`` — the rule set
- [x] ``src/quickpack-rs/src/metadata.rs``
- [x] ``src/quickpack-rs/src/pack.rs``
- [x] ``src/quickpack-rs/src/parts.rs``
- [x] ``src/quickpack-rs/src/jujuignore.rs`` — also fixed a
  pre-existing bug where ``Matcher`` used Rust regex's unanchored
  ``is_match`` instead of Python's anchored ``re.match`` (caught by
  the new ``leading_slash_anchors_to_root`` test)

### 58.2 Medium — Integration tests via ``tests/`` directory

Cargo's integration-test convention is a top-level ``tests/`` dir
inside each crate.  Use this for multi-module scenarios that a unit
test can't express cleanly.

- [x] ``src/charmlint-rs/tests/lint_integration.rs`` — end-to-end
  lint pass against fixture charms, mirroring the Python
  ``test_linter.py`` shape (drives the compiled binary with
  ``--format json`` so argument parsing and output formatting are
  exercised too)
- [x] ``src/quickpack-rs/tests/pack_integration.rs`` — error-path
  integration (missing charmcraft.yaml, unknown plugin, missing uv
  part).  A full ``.charm``-assembly integration would require a
  real ``uv venv + uv sync`` run; that remains covered by the
  existing spread test.

### 58.3 Medium — CI wiring

- [x] Extend the existing GitHub Actions workflow to run
  ``cargo test`` for both crates on every push.  Cache the
  ``target/`` directory per crate for build-time sanity.
- [x] Add a ``make rust-test`` target to ``Makefile`` so the local
  loop matches CI.

### 58.4 Low — Coverage instrumentation

- [ ] Wire ``cargo-llvm-cov`` into the CI job — emits the same
  format as the Python coverage report, plots next to it
- [ ] Set an advisory threshold (not blocking): warn if any Rust
  file drops below 60%

### What this phase is *not*

- Not a rewrite of either Rust crate.  The implementations are
  current; this phase only adds test scaffolding around them.
- Not an attempt to match Python test count 1:1.  Idiomatic Rust
  tests group differently (doctests on small pure functions, unit
  tests inline, integration tests in ``tests/``); the audit is
  coverage, not line count.

**Exit criteria:** ``cargo test`` passes in both crates; CI runs it
on every push; ``cargo-llvm-cov`` reports each ``.rs`` file above
60% line coverage.  A bug in ``linter.rs`` or ``pack.rs`` now
surfaces at unit-test time, not via a spread failure.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Seed unit tests (58.1) | none | Per-file work; can parallelise |
| Integration (58.2) | 58.1 | Reuses unit fixtures |
| CI wiring (58.3) | 58.1 | Needs tests to actually run |
| Coverage (58.4) | 58.3 | Measures what CI runs |

---

## Phase 59: Property-Based Testing with Hypothesis ✓

**Goal:** Add property-based tests to the handful of pure functions
where exhaustive example-based testing misses edge cases.  The
audit surfaced four clean candidates: the planner's
``_validate_dependencies`` (cycle detection over arbitrary graphs),
charmlint's rule engine (any ``charmcraft.yaml`` shape), quickpack's
``jujuignore`` parsing (any path tree / pattern combo), and the
watcher's status-diff logic (any pair of Juju status dicts).  Small
surface, disproportionate confidence lift.

Introducing ``hypothesis`` as a dev-dependency is the main cost;
after that, each property test is a handful of lines.

### 59.1 Medium — Add hypothesis to dev-dependencies

- [x] Pin ``hypothesis`` in ``pyproject.toml``'s dev-dep list
- [x] Configure a ``tests/unit/conftest.py`` profile so CI runs with
  a higher ``max_examples`` (e.g. 500) and dev runs with the
  default (100) for fast feedback.  Profile is selected via
  ``CANTRIP_HYPOTHESIS_PROFILE`` env var (``dev`` | ``ci``); the
  GitHub Actions workflow sets ``ci``.

### 59.2 Medium — Planner dependency-graph properties

- [x] ``tests/unit/test_planner_properties.py`` —
  ``_validate_dependencies`` should leave acyclic graphs unchanged,
  and break every cycle it detects (no dependency in the result
  participates in a cycle).  Use ``hypothesis.strategies`` for
  arbitrary DAGs and arbitrary cyclic graphs.  Six properties land:
  task-set preservation, no phantom deps, result always acyclic,
  acyclic-and-valid input unchanged, idempotence, and sub-graph
  closure (edges only get removed, never added).

### 59.3 Medium — Charmlint rule-engine properties

- [x] ``tests/unit/charmlint/test_properties.py`` — for any
  structurally valid ``charmcraft.yaml``, the lint pass terminates
  and never raises; findings always reference existing fields.
  Three properties: ``lint()`` never raises; it is deterministic
  across repeated calls (sort-normalised diagnostic tuples match);
  every ``Diagnostic`` has a populated ``rule_id`` / valid
  ``Severity`` / non-empty message, and ``line`` is never set
  without ``path``.  The module suppresses the
  ``function_scoped_fixture`` health check because the shared
  ``tmp_charm`` dir only has ``charmcraft.yaml`` overwritten per
  example (no state leaks).

### 59.4 Low — Quickpack ``.jujuignore`` properties

- [x] ``tests/unit/test_jujuignore_properties.py`` (will move under
  ``tests/unit/quickpack/`` when Phase 57.8 lands) — pattern
  matching is deterministic, arbitrary patterns/paths never raise,
  the default VCS ignores still bite regardless of user patterns,
  comment and blank pattern lines are no-ops, and negation both
  un-ignores (``[P, !P]``) and is authoritative over later
  matching rules (``[P, !P, P]`` leaves the path kept — unlike
  gitignore's latest-rule-wins model).

### 59.5 Low — Watcher status-diff properties

- [x] ``tests/unit/test_watcher_properties.py`` — diffing any status
  against itself is empty; diffing A→B then B→A produces inverse
  change sets where applicable.  Nine properties: self-diff empty,
  ``None`` old returns ``[]``, events reference real apps and units
  (with offers contributing their ``application`` name to the app
  universe — a real corner Hypothesis surfaced), all events carry
  ``source="status"``, dedup keys are populated, and swap-symmetry
  holds for ``new_app``/``removed_app``, ``new_unit``/``removed_unit``,
  and ``new_offer``/``removed_offer`` event counts.

### What this phase is *not*

- Not an attempt to replace example-based tests.  Property tests
  complement them; keep the existing named-scenario tests as
  documentation.
- Not a framework migration.  No existing tests change shape.

**Exit criteria:** ``hypothesis`` on the dev-deps list; at least one
property test per candidate area; CI runs the property tests in
each normal unit-test cycle with ``max_examples=500`` in the CI
profile.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Hypothesis setup (59.1) | none | One-time dep change |
| Planner properties (59.2) | 59.1 | Pure function, easy target |
| Charmlint properties (59.3) | 59.1 | Reuses charmlint fixtures |
| Quickpack properties (59.4) | 59.1, Phase 57.8 | Slots into the quickpack folder reorg |
| Watcher properties (59.5) | 59.1 | Pure function, easy target |

---

## Phase 60: Web UI Accessibility

**Goal:** Fix the issues surfaced by the Phase 59-era accessibility audit of
``src/cantrip/web/`` (see ``design/WEB_UI_ACCESSIBILITY_AUDIT.md``).  The
audit ran ``rodney`` against the live web UI and captured evidence in a
``showboat`` document; five high-severity findings fail WCAG 2.1 AA
outright, five medium-severity findings are one-line fixes, and four
low-severity findings are polish.  All remediation sits in
``src/cantrip/web/templates/index.html.j2``, ``static/style.css``, and
``static/cantrip.js``; no Python changes are expected.

Every item references the numbered finding in the audit doc so the
evidence is one click away.

### 60.1 High — Visible focus indicator for the Send button (finding 1)

- [x] Add ``#chat-form button:focus-visible`` with a 2px white ring and
  2px outline offset so keyboard users can see the primary action is
  focused on the accent-blue background
- [x] Audit every other focusable element in the page for a visible focus
  style (header buttons, chat input, overlay-internal controls) and add
  ``:focus-visible`` rules where the UA default is suppressed or
  insufficient — covered by a global ``:focus-visible`` rule that
  paints a 2px ``--accent`` outline on any interactive element that
  gains keyboard focus

### 60.2 High — Raise Send button text contrast to ≥4.5:1 (finding 2)

- [x] Either darken ``--accent`` when used as a button background
  (e.g. introduce ``--accent-strong: #1f6feb``) or switch the Send label
  to ``#0d1117``.  The audit's contrast probe is the reference —
  ``--accent-strong: #1f6feb`` added; the Send button now uses it
  (white-on-#1f6feb ≈ 6.7:1)
- [ ] Re-run the contrast probe from ``design/WEB_UI_ACCESSIBILITY_AUDIT.md``
  under ``showboat verify`` and confirm no cell drops below 4.5:1 for
  normal text — deferred to 60.9 (CI regression guard)

### 60.3 High — Programmatic label on ``#chat-input`` (finding 3)

- [x] Add a visible ``<label for="chat-input">`` (preferred) or an
  ``aria-label`` fallback.  Placeholder text stays as the hint, not the
  name — visually-hidden ``<label for="chat-input">`` added; the
  placeholder stays as the visual hint

### 60.4 High — Live regions for dynamic content (finding 4)

- [x] ``#chat-messages`` → ``role="log" aria-live="polite"
  aria-relevant="additions"``.  Assistant replies should be announced;
  user's own echoed message should not generate a duplicate announcement
- [x] ``#thinking-indicator`` → ``role="status" aria-live="polite"``.
  Keep it in the DOM; toggle ``aria-hidden`` (or a ``hidden`` attribute
  pair) instead of ``display:none`` so assistive tech sees the state
  change — uses the HTML ``hidden`` attribute pair
- [x] ``#connection-status`` → ``role="status"`` with a visually-present
  or sr-only text sibling.  Update ``_setStatus`` in ``cantrip.js`` to
  set ``aria-label`` alongside ``title``

### 60.5 High — Overlays become real dialogs (finding 5)

- [x] Mark ``#help-overlay``, ``#logs-overlay``, ``#graph-overlay`` with
  ``role="dialog" aria-modal="true" aria-labelledby="<heading-id>"``
- [x] Give each overlay's ``<h2>`` a stable id to hang the label off
  (``help-overlay-title``, ``logs-overlay-title``, ``graph-overlay-title``)
- [x] In the toggle helpers, capture ``document.activeElement`` on open
  and ``.focus()`` it on close.  On open, focus moves to the heading
  (``tabindex="-1"``) or first focusable child
- [x] Set ``inert`` on ``<header>``, ``<main>``, ``<footer>`` while an
  overlay is open (polyfill via ``aria-hidden`` + ``tabindex="-1"`` only
  if a target browser lacks native ``inert`` support — modern Chromium,
  Firefox, and Safari all ship it) — uses native ``inert``
- [x] Implement a minimal Tab/Shift-Tab wrap inside the overlay so
  keyboard users can't escape the dialog without closing it
  (``_handleOverlayTab``)

### 60.6 Medium — Cluster of small HTML fixes (findings 6, 7, 9)

- [x] ``index.html.j2`` — add ``type="button"`` to the three header buttons
- [x] Add ``aria-label="Help"`` / ``aria-label="Logs"`` / ``aria-label="Graph"``
  so screen readers don't announce "question mark, button" etc.  The
  visible glyph stays
- [x] Extend ``toggleHelp/Logs/Graph`` in ``cantrip.js`` to flip
  ``aria-expanded`` and ``aria-controls`` on the corresponding trigger
  button

### 60.7 Medium — Connection status dot is labelled, not titled (finding 8)

- [x] Drop the ``title``-only pattern in ``_setStatus``; set
  ``aria-label`` (and ``role="status"`` once) so touch and screen-reader
  users can perceive the state
- [ ] Consider giving the dot a visible adjacent text sibling so the
  label is not a hidden-only affordance — deferred; the dot still
  communicates state by colour, the role/label now expose it
  programmatically

### 60.8 Low — Polish (findings 11, 12, 13, 14)

- [x] Convert the Keyboard Shortcuts ``<table>`` to a ``<dl>`` (or at
  least wrap each key in ``<kbd>`` and add a ``<caption>``) — uses
  ``<dl class="shortcuts-list">``
- [x] Gate global single-key shortcuts behind ``Alt`` (or add a setting
  to disable them) — WCAG 2.1.4 Character Key Shortcuts — Alt+H /
  Alt+L / Alt+G / Alt+R; help overlay and footer hint updated to match
- [ ] Raise the muted-text tokens (``--text-muted``) to ≥7:1 if AAA
  becomes a target.  Deferred decision
- [x] Give each ``<section>`` an ``aria-labelledby`` that points at its
  ``<h2>`` so the a11y tree exposes the regions by name — ``#chat-panel``
  and ``#right-panels`` carry ``aria-label``; the inner Tasks and Juju
  Status panels are now ``<section>`` elements with
  ``aria-labelledby`` pointing at their ``<h2>``

### 60.9 Medium — Regression test: re-run the audit in CI

- [ ] Add a ``tests/integration/web/test_accessibility.py`` (or an
  ``assets/audit.md`` the CI re-runs with ``showboat verify``) that
  launches the web server, drives ``rodney ax-tree`` / ``rodney ax-node``
  against the same probes the audit used, and asserts the key
  accessible-name / role / contrast invariants.  This prevents the
  audit from drifting silently on future UI changes
- [ ] Alternatively, run a headless axe-core scan via rodney's ``js``
  subcommand — cheaper than hand-crafted assertions but reports
  different things.  Pick one; the audit doc lists both

### What this phase is *not*

- Not a theme rewrite.  Keep the current dark palette; only the specific
  low-contrast pair (white on ``--accent``) needs to move
- Not a refactor of the web stack.  Every change lives in the three
  files mentioned above
- Not a TUI-parity effort.  The TUI has its own accessibility concerns
  (already covered by Textual) and is out of scope here

**Exit criteria:** every finding in
``design/WEB_UI_ACCESSIBILITY_AUDIT.md`` has either a checked box above
or a recorded decision in the audit doc explaining why it's deferred;
``showboat verify`` on the updated audit document exits 0; every
interactive element has a visible ``:focus-visible`` style; no
normal-size text falls below 4.5:1 contrast; the three overlays behave
as modal dialogs (focus moves in, is trapped, is restored on close).

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| High-severity fixes (60.1–60.5) | none | Independent, can land in one PR |
| Medium cluster (60.6, 60.7) | none | Pure HTML/JS, trivial |
| Low polish (60.8) | 60.1–60.5 landed | Avoid conflict with dialog refactor |
| CI regression (60.9) | 60.1–60.7 landed | Test must be green before locking it in |

---

## Phase 61: Slash-Command Autocomplete in the TUI ✓

**Goal:** Let users discover and complete slash commands as they type.
Typing ``/c`` should surface ``/cost`` as a suggestion; Tab accepts the
suggestion; Escape dismisses it.  Removes the "did I remember the name
right?" friction and is the natural follow-on to making slash commands
typeable at all (see the commit that removed the ``/``→search
intercept).

### 61.1 Inline suggestion popup in ``ChatInput``

- [x] When the chat input's first character is ``/`` and the value has
  no spaces yet, show a small suggestion list above the input with
  every verb in ``slash_commands.SHARED_VERBS`` plus the TUI-native
  ``/feelings`` (and any future TUI-specific verbs) whose prefix
  matches what the user has typed.  Case-insensitive.
- [x] List shows verb + a one-line description (from ``help_text`` or
  a small lookup keyed by verb).  Up to ~6 rows; scroll if more match.
- [x] Exactly one suggestion is "active" — highlighted — at any time.
  Up/Down arrow keys move the active row without stealing focus from
  the input.
- [x] Hide the popup as soon as the value no longer starts with ``/``,
  contains a space, or becomes empty.

### 61.2 Accept / dismiss

- [x] Tab inserts the active suggestion's verb plus a trailing space
  (so ``/c`` + Tab becomes ``/cost ``).  If exactly one suggestion
  matches, Tab accepts it regardless of whether the list is showing.
- [x] Escape closes the popup without changing the input.
- [x] Enter submits the current input value as it stands (does not
  auto-accept).  Rationale: submit should always do what you see.

### 61.3 Source of truth: verbs come from the dispatcher

- [x] ``slash_commands`` exports a ``COMMAND_CATALOGUE`` list of
  ``(verb, summary)`` pairs (or one dataclass) so each surface uses
  the same names and descriptions.  ``SHARED_VERBS`` stays as the
  authoritative verb set and seeds the catalogue.
- [x] TUI-native commands (``/feelings``, and ``/tasks`` / ``/status``
  if they're ever promoted here) register into the catalogue at the
  surface level so the popup can show them too.
- [x] A unit test asserts the catalogue covers every verb the
  dispatcher actually handles (guards against drift when someone adds
  a verb to ``dispatch`` but forgets the catalogue).

### 61.4 CLI parity (stretch)

- [x] In the CLI REPL, wire Readline completion for the same verb
  list so ``/c<Tab>`` completes to ``/cost`` there too.  Depends on
  61.3 (shared catalogue).  Separate from the TUI change so it can
  land in a later PR.

### What this phase is *not*

- Not argument completion (e.g. completing the ``<kind>`` on
  ``/remember``).  That can come in a follow-up; verb-only is the
  high-value 80% of the friction.
- Not fuzzy matching.  Strict prefix is cheaper to implement and
  matches user intuition when commands share prefixes.
- Not a command palette / Ctrl+K launcher.  Different interaction
  model; out of scope.

**Exit criteria:** typing ``/c`` in the TUI shows ``/cost`` as a
suggestion within the current frame; Tab completes it; an unknown
prefix hides the popup; the catalogue test passes; no existing TUI
keybinding regresses.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Catalogue (61.3) | none | Pure data; land first |
| Popup UI (61.1) | 61.3 | Reads the catalogue |
| Key bindings (61.2) | 61.1 | Needs the popup to highlight |
| CLI readline (61.4) | 61.3 | Independent of the TUI work |

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
| M31: Great UX | 31 | Streaming responses; chat search; session resume; cost tracking visible |
| M32: Smart Planning | 32 | Compact prompt complete; dependency validation; watcher events all routed |
| M33: Expanded Skills | 33 | Existing bundle management; charm migration; multi-charm workspaces |
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
| M52: Durable Subagents | 52 | Subagent LLM turns and tool calls checkpoint into SQLite; interrupted tasks resume from the last completed step instead of re-burning tokens |
| M53: Knowledge-in-Markdown | 53 | Planner prompts and task descriptions live in Jinja2 templates; `planner.py` split along the deterministic / LLM seam; dev design docs cover tools, skills, and prompts |
| M54: Authored Docs | 54 | `docs/docs/` site rebuilds from committed markdown sources through `make docs`; no hand-authored HTML remains in the docs tree |
| M55: Awesome-Copilot Survey | 55 | Eight awesome-copilot patterns investigated end-to-end; each has a committed decision, prototype, or recommendation |
| M56: Juju Copilot Bundle | 56 | `canonical/copilot-collections` hosts a Juju-specific instruction/skill bundle derived from Cantrip's system prompt, with CI validation and a regeneration path |
| M57: Test Cleanup | 57 | Unit coverage ≥85%; zero test warnings; oversized unit files split; quickpack tests reorganised to match charmlint |
| M58: Rust Tested | 58 | `cargo test` runs in CI for both Rust crates; every `.rs` file above 60% coverage; regressions surface at unit-test time, not via spread |
| M59: Property Tested | 59 | Hypothesis-backed property tests cover the planner dependency graph, charmlint rule engine, quickpack jujuignore, and watcher status-diff |
| M60: Accessible Web UI | 60 | Web UI passes WCAG 2.1 AA: visible focus indicators, labelled controls, live regions for chat/status, overlays behave as modal dialogs; rodney/showboat regression guard in CI |
| M61: Slash Autocomplete | 61 | Typing ``/`` in the TUI surfaces a catalogue-driven suggestion popup; Tab completes the active verb; CLI readline gets the same catalogue for parity |
| M43: Memory | 43 | Cantrip learns per-charm and cross-charm lessons with citations, revalidation, user controls, and skill export |
