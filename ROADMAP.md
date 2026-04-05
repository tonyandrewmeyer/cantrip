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

## Phase 6: Speed

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

## Phase 10: Existing Charm Improvement (in progress)

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

## Phase 14: Session Transcripts and Audit Log

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

## Phase 15: Web UI (in progress)

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

- [ ] **Event bus abstraction** — an async publish/subscribe bus in `src/cantrip/ui/events.py`
  that emits typed events: `TaskUpdated`, `ChatMessage`, `JujuStatusChanged`,
  `WatcherEvent`, `StatusBarChanged`. Both the TUI widgets and the WebSocket handler
  subscribe to the same bus
- [ ] **Migrate TUI to event bus** — refactor existing Textual widgets (`TaskListWidget`,
  `ChatWidget`, `JujuStatusWidget`, `StatusBar`) to consume events from the bus instead of
  polling or direct state access. Existing behaviour must be preserved — this is a pure
  refactor with no visible changes
- [ ] **Serialisable event payloads** — every event carries a JSON-serialisable payload so
  the WebSocket handler can forward events to the browser without transformation

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
- [ ] **Model graph view** — expanded topology view showing all apps, relations, and
  cross-model integrations. Uses CSS positioning for the graph layout (not canvas)
- [x] **Help overlay** — modal overlay (`?` key) showing keyboard shortcuts table;
  Escape to dismiss
- [x] **Keyboard shortcuts** — `?` for help, `L` for logs, `Escape` to close
  overlays; documented in the help overlay and footer hint bar

### 15.6 Feature Parity Maintenance

Ensure the two UIs stay synchronised as features are added.

- [ ] **Shared event contract** — `src/cantrip/ui/events.py` serves as the single source of
  truth for what the UI can display. Adding a new UI feature means adding an event type
  first, then implementing handlers in both the Textual widget and the JS frontend
- [ ] **UI integration tests** — a test suite that verifies both UIs render the same
  information given the same event sequence. Uses the event bus directly (no browser
  automation) — asserts that TUI widget state and the JSON payloads sent over WebSocket
  are equivalent
- [ ] **Design documentation** — update `TUI.md` to `UI.md`, covering both interfaces with
  shared layout diagrams and per-interface implementation notes

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

## Phase 17: Acceptance Testing — Putting the Charm Through Its Paces

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

Full analysis: [`FRAMEWORK_EVALUATION.md`](FRAMEWORK_EVALUATION.md).

---

## Phase 19: Operational Readiness Assessment

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
orchestrator. Full analysis in [`.source/orc-analysis.md`](.source/orc-analysis.md).

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

## Phase 22: COS on Multi-Controller Environments

**Status:** Planned
**Goal:** COS-lite deploys and integrates correctly regardless of whether the
development controller is LXD or K8s, using cross-model relations when the COS
model lives on a different controller.

Currently, `cos-lite` contains only Kubernetes charms (`alertmanager-k8s`,
`grafana-k8s`, `prometheus-k8s`, `loki-k8s`, `traefik-k8s`). When the
development controller is LXD (as with `concierge -p dev`), there is typically a
separate K8s controller (`concierge-k8s`) already bootstrapped. Preflight
currently skips COS deployment when the active controller is not K8s.

### 22.1 — Detect K8s controller for COS

When the current controller is IAAS, discover the K8s controller (e.g.
`concierge-k8s`) and target COS model creation there. This requires either
Jubilant controller-targeting support or direct `juju add-model -c <controller>`
subprocess calls.

### 22.2 — Cross-model COS integration

When COS is on a different controller than the charm, set up cross-model
relations using `juju offer` and `juju consume`. The charm still integrates with
`grafana-agent` locally, but the agent forwards to COS across the model
boundary. Investigate whether the integration pattern differs for LXD vs K8s
charms (e.g. `grafana-agent` snap on machines vs `grafana-agent-k8s` sidecar).

### 22.3 — Preflight multi-controller awareness

Extend `PreflightRunner` to understand multi-controller environments: enumerate
available controllers, pick the right one for COS, and report status for each.
The TUI/CLI should show which controller hosts COS and whether cross-model
relations are healthy.

### 22.4 — System prompt and skill updates

Update the system prompt's COS integration guidance and the relevant skills to
handle the cross-model case. The agent needs to know when to use `juju offer` /
`juju consume` and how to configure `grafana-agent` for cross-model forwarding.

**Outcome:** COS observability works out of the box on both `concierge -p k8s`
(single controller) and `concierge -p dev` (LXD + K8s dual controller)
environments, with the agent handling the cross-model wiring automatically.

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
| M22: Multi-Controller COS | 22 | COS observability works on both single-controller (K8s) and dual-controller (LXD + K8s) environments |
