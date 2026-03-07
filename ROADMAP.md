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
- [ ] **Load testing** — generate k6 or Locust workloads; deploy multiple units and
  measure throughput/latency under load
- [ ] **Benchmark harness** — timed hook execution via debug-log + Tempo traces; flag
  hooks exceeding a threshold
- [ ] **Fuzz testing** — randomised relation data, config values, and action parameters
  via Scenario and Jubilant
- [ ] **Chaos testing** — kill units, remove relations, revoke storage; verify recovery
- [ ] **Scaling tests** — add/remove units under load; verify peer-relation handling,
  leader election, data replication
- [ ] **Test report** — aggregated results for the agent to reason over and present
  in the TUI

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
- [ ] Charm pairs (app + database deployed and related together)
- [ ] Migration assistance (existing charm → improved charm) — see Phase 10
- [ ] Upgrade testing (verify charm upgrades cleanly between revisions)

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

## Phase 9: Terraform Support

**Goal:** Understand how Cantrip should support Terraform for Juju-deployed charms. Charms
increasingly ship a Terraform module so that operators can deploy them declaratively via
`terraform apply` rather than (or alongside) `juju deploy`. Cantrip should be able to
generate, validate, and maintain these modules.

### 8.1 Research

Understand the Terraform ecosystem for Juju charms and determine what Cantrip needs to do.

- [ ] **Study the standard specification** — read and internalise the
  [Terraform standard specification for charms](https://discourse.canonical.com/t/terraform-standard-specification-for-charms/7037),
  which defines how charm Terraform modules should be structured
- [ ] **Survey existing modules** — examine published Terraform modules for existing charms
  (e.g. in the `canonical/terraform-juju-*` repos) to understand patterns, conventions, and
  common pitfalls
- [ ] **Study the charmkeeper-terraform agent spec** — read and internalise the
  [charmkeeper-terraform agent](https://github.com/seb4stien/charmkeeper/blob/main/.github/agents/charmkeeper-terraform.md),
  which codifies practical standards for Terraform modules in charms (versions, linting,
  test structure, CI workflows, renovate configuration)
- [ ] **Identify scope** — determine which of the following Cantrip should support:
  - Generating a Terraform module for a newly built charm
  - Generating a Terraform plan that deploys a charm with its integrations
  - Validating a generated module against the standard specification
  - Testing the module (plan + apply in a clean environment)
  - Maintaining the module as the charm evolves (new config, new integrations)

### 8.2 Design Decisions (TBD after research)

- [ ] **When to generate** — should Cantrip always generate a Terraform module alongside the
  charm, or only when the user requests it?
- [ ] **Module structure** — follow the standard specification; determine how much of the
  module can be inferred from the charm's `charmcraft.yaml` (config, integrations, resources)
- [ ] **Integration with the build pipeline** — where in the autonomous task flow does
  Terraform module generation sit? After charm pack? After first successful deploy?
- [ ] **Validation tooling** — can Cantrip run `terraform validate` and `terraform plan`
  as part of its quality checks?

**Exit criteria:** Clear design document for Terraform support, grounded in the standard
specification and real-world module patterns, with a concrete implementation plan.

---

## Phase 10: Existing Charm Improvement

**Goal:** Use Cantrip not just to build new charms, but to bring existing charms up to
modern standards. The user points Cantrip at an existing charm ("here's my charm, make it
great") and Cantrip audits it, identifies gaps, and autonomously adds COS integration,
tests, best-practice fixes, and everything needed for a public Charmhub listing.

### 10.1 Charm Audit

Analyse an existing charm and produce a comprehensive gap analysis.

- [ ] **Ingest existing charm** — accept a local path or Git URL to an existing charm
  project; parse `charmcraft.yaml`, `metadata.yaml` (legacy), `src/charm.py`, `config.yaml`,
  `actions.yaml`, tests, and any existing documentation
- [ ] **Best-practices checklist** — evaluate the charm against Canonical's
  [best practices list](https://juju.is/docs/sdk/styleguide) and common conventions:
  - Ops framework usage (modern patterns, no deprecated APIs)
  - Event handling (correct observe patterns, idempotent handlers)
  - Status management (meaningful status messages, not just `ActiveStatus`)
  - Config validation and defensive handling
  - Secret management (Juju secrets vs. config for sensitive data)
  - Resource handling (OCI images, attached resources)
  - Peer relation data patterns (leader-only writes, databag hygiene)
  - Pebble layer management (for K8s charms)
  - Logging practices (structured, appropriate levels)
- [ ] **Public listing requirements** — check against Charmhub listing requirements:
  - README with badges, description, usage, configuration, integrations, and contributing
  - `charmcraft.yaml` with proper display-name, summary, description, docs URL, issues URL,
    source URL, and tags
  - Icon (SVG in the correct location)
  - Documentation on Discourse or in-tree
  - License file
  - Clean `charmcraft pack` with no warnings
- [ ] **Audit report** — produce a structured report (`AUDIT.md`) summarising findings,
  grouped by severity (must-fix, should-fix, nice-to-have), with specific recommendations
  and references to documentation

### 10.2 Observability Gap Fill

Add COS integration and ops-tracing if missing or incomplete.

- [ ] **COS integration audit** — check for existing COS relations (grafana-dashboard,
  loki-push-api, metrics-endpoint) and assess completeness
- [ ] **Add ops-tracing** — integrate the ops-tracing library if absent; instrument charm
  with tracing support following the guidance in Phase 16.2 (what to instrument manually
  vs what ops-tracing covers automatically)
- [ ] **Add metrics** — add Prometheus metrics endpoint if missing; generate a basic
  Grafana dashboard JSON covering key operational metrics
- [ ] **Add log forwarding** — add Loki push API relation and structured logging if missing
- [ ] **Alert rules** — generate basic Prometheus alert rules for common failure conditions
  (unit blocked, hook failures, resource exhaustion)

### 10.3 Test Gap Fill

Add or improve tests to match the standard Cantrip would apply to a new charm.

- [ ] **Test coverage audit** — analyse existing test suite (if any); identify untested
  events, config changes, actions, and relation lifecycle
- [ ] **Scenario unit tests** — generate Scenario-based unit tests for all observed events,
  covering happy paths and error cases; do NOT use the deprecated Harness
- [ ] **Migrate from Harness** — if existing tests use the deprecated Harness, offer to
  rewrite them using Scenario
- [ ] **Jubilant integration tests** — generate integration tests using Jubilant, covering
  deploy, relate, config changes, actions, and scale-up/down
- [ ] **Test validation** — run the generated tests and fix any failures before presenting
  the result

### 10.4 Code Modernisation

Bring the charm code up to current Ops framework standards.

- [ ] **Deprecated API migration** — identify and replace deprecated Ops APIs
  (e.g. `StoredState` patterns, old relation APIs, legacy hook tools)
- [ ] **Type annotations** — add type hints where missing
- [ ] **Modern patterns** — apply current idiomatic patterns:
  - Holistic status handling
  - Config-changed reconciliation pattern
  - Relation-created / relation-changed best practices
  - Proper Pebble readiness checks
- [ ] **Dependency updates** — update charm library dependencies to latest versions;
  flag any libraries fetched via `charmcraft fetch-libs` that have PyPI equivalents

### 10.5 Listing Readiness

Prepare the charm for a polished Charmhub listing.

- [ ] **README generation** — generate or rewrite README.md with standard sections:
  description, deployment, configuration reference, integrations, contributing guide
- [ ] **Metadata completion** — fill in missing `charmcraft.yaml` fields (display-name,
  summary, description, docs, issues, source URLs, tags)
- [ ] **Documentation** — generate or update Discourse-format documentation covering
  getting started, configuration, integrations, and troubleshooting
- [ ] **Icon check** — verify an SVG icon exists; warn if missing (Cantrip doesn't
  generate artwork, but flags the gap)
- [ ] **Licence check** — verify a LICENSE file exists; suggest Apache-2.0 if missing

### 10.6 Validation and Presentation

Verify all improvements work together and present the result.

- [ ] **Full build** — `charmcraft pack` succeeds cleanly with no warnings
- [ ] **Test suite green** — all generated tests pass (Scenario unit + Jubilant integration)
- [ ] **Deploy and verify** — deploy the improved charm to a dev model; verify it reaches
  active/idle; verify COS relations work
- [ ] **Diff review** — present the user with a summary of all changes made, grouped by
  category (observability, tests, code quality, listing), with before/after comparisons
- [ ] **Incremental commits** — each category of improvement is committed separately with
  clear commit messages, so the user can review and revert individual changes

**Exit criteria:** User points Cantrip at an existing charm. Cantrip audits it, adds COS
integration, writes Scenario and Jubilant tests, modernises code, prepares listing metadata,
and presents a clean diff — bringing the charm to the same standard as one built from scratch.

---

## Phase 11: Long-Running Agent Resilience

**Goal:** Make the autonomous work loop more robust across long sessions and restarts.
Inspired by [Anthropic's engineering guidance on effective harnesses for long-running
agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents),
these changes ensure subagents commit their work, verify their output, recover cleanly
from failures, and resume gracefully after interruption.

### 11.1 Commit-After-Build

Build subagents should commit their changes before declaring success, so each task's
output is independently recoverable via git.

- [ ] **Build guidance update** — add explicit instruction to `_CATEGORY_GUIDANCE[BUILD]`
  telling subagents to `git_add` + `git_commit` with a descriptive message before
  finishing; similarly for DEBUG subagents that apply fixes
- [ ] **Commit verification** — after a BUILD/DEBUG subagent completes, the executor
  checks `git_status` for uncommitted changes and logs a warning if any remain

### 11.2 Lightweight Self-Verification

Build subagents should run a basic sanity check before declaring success, catching
obvious errors before the dedicated TEST task.

- [ ] **Build self-check** — add `charm_validate` and `run_charm_tests` (unit only) to
  the BUILD tool allowlist; update BUILD guidance to run validation before finishing
- [ ] **Fail-fast on validation** — if `charm_validate` fails inside a build subagent,
  the subagent should attempt a fix (one retry) rather than reporting a false success

### 11.3 Session Resume Protocol

When Cantrip starts with an existing `.cantrip` file, it should reconstruct context
from prior work before planning new tasks — not start from scratch.

- [ ] **Progress summary** — on startup with an existing session, load completed tasks,
  decisions, and the last few git commits; inject a structured summary into the
  conversation as initial context
- [ ] **Environment health check** — verify the charm path exists, the Juju model is
  responsive, and the last-known charm status before accepting new instructions
- [ ] **Stale task recovery** — tasks left in ACTIVE status from a prior session (due to
  crash or interruption) should be reset to PENDING with a note that they need re-running

### 11.4 Git-Revert-on-Failure

When a BUILD or DEBUG subagent fails, partial file writes may leave the working tree in
a broken state. Clean up automatically so retries start from a known-good baseline.

- [ ] **Snapshot before execution** — the executor records the current git HEAD before
  launching a BUILD/DEBUG subagent
- [ ] **Revert on failure** — if the subagent fails, the executor runs `git checkout .`
  to restore the working tree to the pre-task state (only for tracked files)
- [ ] **Preserve diagnostics** — before reverting, capture a summary of the changes
  (via `git diff`) and attach it to the task's failure result so the next attempt or
  the user can see what went wrong

### 11.5 Pre-Task Environment Health Checks

Before launching deploy or test subagents, verify that the environment is in a usable
state — catching stale models, broken controllers, or missing charms early.

- [ ] **Deploy pre-check** — before DEPLOY tasks, verify the Juju model exists and the
  controller is reachable; if not, queue an INFRA task to fix it rather than letting
  the deploy subagent fail opaquely
- [ ] **Test pre-check** — before TEST tasks, verify the charm is packed and the
  application is deployed; skip if prerequisites are clearly not met and report why

**Exit criteria:** Subagents commit their work, verify their output with a quick
validation pass, and the executor cleans up failed attempts. Restarting Cantrip on an
existing session resumes smoothly with full context.

---

## Phase 12: Red/Green Charm Building

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

- [ ] **Update `_DESIGN_TO_BUILD_PROMPT`** — change the "typical build sequence" to:
  1. Scaffold the charm (`charmcraft init`, write metadata)
  2. Write integration tests from the design (deploy, relations, actions, config)
  3. Write charm code to make the tests pass
  4. Pack, deploy, and run integration tests
  5. Fix and iterate until tests pass
  6. Write unit tests (Scenario) for edge cases and error paths
  7. Commit and offer next steps
- [ ] **New task category or tag** — distinguish "write integration tests" (a BUILD task
  that produces test files) from "run integration tests" (a TEST task that executes them),
  so the planner can sequence them correctly with dependencies

### 12.2 Integration Test Generation from Design

The approved design contains enough information to write integration tests before any
charm code exists — the design specifies integrations, actions, config options, and
expected behaviour.

- [ ] **Design-to-test extraction** — parse the approved DESIGN.md to identify testable
  contracts:
  - Each relation endpoint → test that deploying + relating reaches active/idle
  - Each action → test that running the action succeeds and returns expected keys
  - Each config option → test that setting it does not break the charm
  - COS integration → test that Grafana/Loki/Prometheus relations work
- [ ] **Test template generation** — produce `tests/integration/test_charm.py` from the
  design using the `jubilant-tests` skill patterns; tests should be runnable (and failing)
  before any charm code is written
- [ ] **Incremental test files** — for complex charms, split integration tests into
  focused files (`test_deploy.py`, `test_relations.py`, `test_actions.py`) so subagents
  can target specific failures

### 12.3 Red/Green Build Subagent

Update the BUILD subagent to use the red/green cycle as its feedback loop.

- [ ] **Add `run_charm_tests` to BUILD tools** — build subagents can run integration
  tests directly, without waiting for a separate TEST task; this lets them iterate
  within a single subagent invocation
- [ ] **BUILD guidance update** — update `_CATEGORY_GUIDANCE[BUILD]` to instruct the
  subagent:
  1. Read the existing integration tests (written by a prior task)
  2. Write charm code targeting the test expectations
  3. Pack the charm and run integration tests
  4. If tests fail, read the output, fix the code, and re-run
  5. Finish only when tests pass (or max rounds exhausted)
- [ ] **Test-result-driven iteration** — when a build subagent reports "3/7 integration
  tests passing", the executor can spawn a follow-up BUILD task focused on the remaining
  failures rather than a generic DEBUG task

### 12.4 Incremental Feature Addition

When the user asks to add a feature to an existing charm ("add PostgreSQL integration"),
the same red/green cycle applies: write the integration test first (red), then implement
until it passes (green).

- [ ] **Feature test first** — when replanning for a new feature, the planner generates
  a "write integration test for X" task before the "implement X" task
- [ ] **Regression safety** — the new test is added alongside existing tests; running
  the full integration suite after implementation catches regressions
- [ ] **Selective test execution** — allow `run_charm_tests` to accept a specific test
  file or test name pattern (e.g. `test_postgresql_relation`) so the build subagent
  can iterate quickly on one test without running the entire suite

### 12.5 Unit Tests as a Second Pass

Unit tests (Scenario) remain valuable for edge cases, error paths, and fast iteration,
but they come after the integration tests establish the external contract.

- [ ] **Unit test task after integration green** — the planner sequences "write unit
  tests" after integration tests pass, so unit tests can cover internal details the
  subagent discovered during implementation
- [ ] **Unit tests for error paths** — guide the unit test subagent to focus on cases
  that integration tests cannot easily cover: missing relations → BlockedStatus,
  invalid config → error handling, Pebble not ready → WaitingStatus
- [ ] **Combined validation gate** — `charm_validate` runs both unit and integration
  tests as the final success check before declaring the charm complete

**Exit criteria:** User says "build a charm for X". After design approval, the agent
writes integration tests first (deploy, relate to PostgreSQL, run backup action, etc.),
then writes charm code and iterates until all integration tests pass. The agent has a
clear, automated signal for "this feature works" at every step.

---

## Phase 13: Charm Demo Generation

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

- [ ] **`showboat` agent tool** — thin wrapper around Showboat CLI commands (`init`,
  `note`, `exec`, `image`, `pop`, `verify`); added to the BUILD tool allowlist so
  demo subagents can construct Markdown documents by running real commands
- [ ] **`rodney` agent tool** — thin wrapper around Rodney CLI commands (`start`,
  `stop`, `open`, `js`, `click`, `screenshot`); added to the BUILD tool allowlist
  for visual capture tasks
- [ ] **Dependency check** — the demo task checks for Showboat and Rodney availability
  at the start; if missing, falls back to manual file writing (graceful degradation)
- [ ] **Rodney for integration tests** — expose Rodney to TEST subagents for verifying
  web-facing charms visually (does the ingress actually serve the app?), complementing
  Jubilant's API-level checks

### 13.2 Demo Document Generation

Use Showboat to build a demo document by running real commands against a live deployment
and capturing the output inline.

- [ ] **`DEMO.md` via Showboat** — after a successful deploy, the demo subagent uses
  `showboat init` / `showboat exec` / `showboat note` to build a document that
  interleaves annotated explanations with real command output:
  - `showboat exec` for `juju status`, `juju run`, `juju config`, etc.
  - `showboat note` for explanations drawn from WORKLOAD.md and DESIGN.md
  - `showboat image` for screenshots captured via Rodney
- [ ] **Relation wiring** — the demo document shows deploying all required relations
  (database, ingress, COS) so the charm is shown in its full operational context
- [ ] **Action showcase** — for each action the charm exposes, `showboat exec` runs it
  with example parameters and the output is captured inline
- [ ] **Config showcase** — demonstrates setting key config options with before/after
  status captured via `showboat exec`
- [ ] **Fallback path** — if Showboat is unavailable, the subagent writes the Markdown
  directly using `write_file`, capturing command output via juju tools and formatting
  it manually

### 13.3 Captured Artefacts

Save standalone artefacts alongside the demo document for reference and reuse.

- [ ] **`juju status` snapshot** — save a clean `juju status --relations` to
  `demo/juju-status.txt` showing all units active/idle with addresses and relations
- [ ] **Action results** — save JSON results to `demo/actions/` (e.g.
  `demo/actions/backup.json`, `demo/actions/get-password.json`)
- [ ] **Log snippets** — capture a curated excerpt of `juju debug-log` showing the charm
  handling a key event cleanly; save to `demo/logs/`
- [ ] **Trace capture** — query Tempo for a representative trace and save trace data
  plus a human-readable span summary to `demo/traces/`
- [ ] **Config reference** — dump the effective config with descriptions to
  `demo/config-reference.txt`
- [ ] **`demo.sh` script** — generate a self-contained bash script that reproduces the
  full deployment (deploy, relate, configure, verify) with an optional `--cleanup` flag;
  validated by running it in a clean model

### 13.4 Visual Assets

Use Rodney to capture visual proof of observability integration and deployment health.

- [ ] **Grafana dashboard export** — export the dashboard JSON to `demo/dashboards/`
  so users can import it directly
- [ ] **Dashboard screenshot** — use Rodney to open the Grafana dashboard URL, wait for
  data to render, and capture a screenshot; save as `demo/screenshots/grafana-dashboard.png`
  and embed in `DEMO.md` via `showboat image`
- [ ] **Web UI screenshot** — for web-facing charms, use Rodney to capture the
  application's own UI through the ingress; proves the workload is actually serving
- [ ] **Architecture diagram** — generate a Mermaid diagram showing the charm's relations
  and integrations; embed in README and save to `demo/architecture.md`

### 13.5 Demo Tutorial

Generate a guided walk-through that explains the charm's features in context.

- [ ] **`TUTORIAL.md` generation** — a step-by-step guide covering:
  1. Prerequisites (controller, model, cloud substrate)
  2. Deploying the charm and its relations
  3. Verifying the deployment (what to look for in `juju status`)
  4. Exercising key features (config, actions, scaling)
  5. Observability (where to find dashboards, what metrics to watch)
  6. Troubleshooting common issues
- [ ] **Copy-pasteable commands** — every step includes the exact command to run, with
  expected output shown alongside (drawn from Showboat captures where possible)
- [ ] **Annotations from research** — draw on WORKLOAD.md and DESIGN.md to explain
  *why* certain config options matter, what the actions do operationally, and how the
  integrations work — not just *how* to run commands
- [ ] **Quick-start vs. full tutorial** — a short "just deploy it" section at the top
  for experienced users, followed by the detailed walk-through

### 13.6 Demo as a Pipeline Stage

Make demo generation an automatic part of every charm build, not an afterthought.

- [ ] **Planner integration** — `_DESIGN_TO_BUILD_PROMPT` includes a "generate demo"
  task after successful deploy + test, with dependencies on both completing successfully
- [ ] **Demo BUILD task** — a dedicated task (category: build) that generates all demo
  artefacts: Showboat document, captured output, visual assets, tutorial, and script
- [ ] **Demo validation** — run `demo.sh` in a clean model to verify it works end-to-end;
  use `showboat verify` to check the demo document is well-formed
- [ ] **README integration** — update the generated README to link to `DEMO.md`,
  embed the architecture diagram, include the `juju status` snapshot, and point to
  the tutorial
- [ ] **Git commit** — demo artefacts are committed as a separate "Add demo and tutorial"
  commit so they can be reviewed independently from the charm code

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

- [ ] **Messages table** — add a `messages` table to the SQLite schema: `id`, `role`
  (system/user/assistant/tool), `content`, `tool_calls` (JSON), `tool_results` (JSON),
  `metadata` (JSON), `timestamp`. Schema version bump
- [ ] **Write-through recording** — in `CantripAgent.process_message()` and
  `process_message_streaming()`, write each message to the store as it is appended to
  the in-memory list; writes should be non-blocking (batched or async) so they don't
  slow the conversation loop
- [ ] **Tool call detail** — for each tool call, record the tool name, full arguments,
  and the full result (output + error + success flag); truncate very large results
  (e.g. file contents over 50 KB) with a note that the full content is available in
  the virtual file store

### 14.2 Subagent Conversation Recording

Capture the full internal conversation of every subagent run, not just the final summary.

- [ ] **Subagent messages table** — add a `subagent_messages` table: `task_id` (foreign
  key to tasks), `message_index`, `role`, `content`, `tool_calls` (JSON),
  `tool_results` (JSON), `timestamp`
- [ ] **Recording in `Subagent.run()`** — after each LLM completion and tool execution
  round, write the messages to the store; the executor passes a store reference to the
  subagent for this purpose
- [ ] **Link to task** — each subagent conversation is associated with its `AgentTask`,
  so the transcript can show "Task: Research PostgreSQL documentation" followed by the
  full LLM ↔ tool conversation that produced the result

### 14.3 Event Log

Record significant agent events beyond LLM conversations for a complete audit trail.

- [ ] **Events table** — add an `events` table: `id`, `event_type`, `detail` (JSON),
  `timestamp`. Event types include:
  - `session_start`, `session_resume` — with provider, model, charm name
  - `task_status_change` — task id, old status, new status
  - `decision_made` — type, choice, reason (mirrors decisions table but timestamped
    in the event stream)
  - `design_confirmed`, `design_overridden` — with the override details
  - `watcher_event` — status change, hook failure, Loki alert
  - `error` — provider errors, tool failures, timeouts
- [ ] **Watcher event recording** — the watcher already detects status changes and hook
  failures; record these as events so the transcript shows what triggered diagnostic
  tasks
- [ ] **Token usage in context** — link token usage records to the specific message or
  subagent round that consumed them, so the transcript can show cost per task

### 14.4 HTML Export

Generate a polished, human-readable HTML transcript from the recorded data.

- [ ] **Export command** — `cantrip export-transcript` CLI command that reads the
  `.cantrip` SQLite file and produces a self-contained HTML file (or directory of
  paginated HTML files for long sessions)
- [ ] **Jinja2 templates** — HTML output generated via Jinja2 templates (consistent
  with the existing prompt templating pattern) with clean CSS styling; templates are
  bundled in `src/cantrip/transcript/templates/`
- [ ] **Conversation view** — user messages, assistant responses, and tool calls
  rendered as a chat-style timeline with clear visual distinction between roles;
  tool calls shown as collapsible blocks with name, arguments, and result
- [ ] **Subagent threads** — each subagent conversation rendered as a nested,
  collapsible thread under its parent task; the task title and status are shown as
  a header so the reader can see what the subagent was trying to do
- [ ] **Task timeline** — a sidebar or top-level view showing the task checklist with
  status transitions and timestamps; clicking a task scrolls to its subagent thread
- [ ] **Event stream** — significant events (decisions, status changes, errors)
  interleaved in the timeline at the correct chronological position
- [ ] **Search** — full-text search across all messages, tool outputs, and events
- [ ] **Pagination** — long sessions split across multiple pages with navigation;
  each page covers a logical chunk (e.g. research phase, build phase, deploy phase)
- [ ] **Self-contained** — CSS and any JavaScript inlined in the HTML so the file
  can be shared without external dependencies

### 14.5 Additional Export Formats

Support other output formats for different use cases.

- [ ] **JSONL export** — `cantrip export-transcript --format jsonl` dumps every message,
  event, and subagent conversation as newline-delimited JSON; useful for programmatic
  analysis and piping into other tools
- [ ] **Markdown export** — `cantrip export-transcript --format markdown` produces a
  single Markdown file with the conversation, tool calls as code blocks, and task
  summaries; lighter-weight than HTML for embedding in documentation
- [ ] **Filtered export** — `--task <task-id>` exports only a specific task and its
  subagent conversation; `--phase research|build|deploy|test` exports all tasks in
  a phase; `--since <timestamp>` exports from a point in time

### 14.6 Live Transcript in TUI

Surface the transcript in the TUI for real-time inspection.

- [ ] **Transcript screen** — new TUI screen (e.g. F5) showing the full conversation
  and subagent activity in a scrollable, searchable view; more detailed than the chat
  panel, which shows only the user-facing conversation
- [ ] **Subagent drill-down** — from the task checklist widget, select a task and view
  its full subagent conversation inline; useful for understanding why a task failed or
  what the agent decided

**Exit criteria:** After a Cantrip session, `cantrip export-transcript` produces a
polished HTML file showing the full conversation, every subagent's internal reasoning
and tool use, task status transitions, decisions, and events — all in a searchable,
paginated, human-readable format. Nothing is lost.

---

## Phase 15: Web UI

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

- [ ] **Server module** — `src/cantrip/ui/web/server.py` using `aiohttp` (already
  async-compatible with the existing event loop). Serves static files and exposes a
  WebSocket at `/ws`. Binds to `127.0.0.1` only — no network exposure
- [ ] **CLI flag** — `cantrip --web` starts the web server alongside (or instead of) the
  TUI; `cantrip --web --no-tui` runs headless with web only. Port defaults to `8471`,
  configurable via `--web-port`
- [ ] **Initial state endpoint** — `GET /api/state` returns the full current state (tasks,
  chat history, Juju status, status bar) as JSON so the browser can render immediately on
  connect rather than waiting for incremental updates
- [ ] **WebSocket bridge** — subscribes to the shared event bus and forwards every event
  to all connected WebSocket clients as JSON messages. Also receives user input (chat
  messages, task interactions) from the browser and injects them into the conversation loop

### 15.3 Static Frontend — Layout and Panels

Build the three-panel layout using vanilla HTML, CSS, and JavaScript.

- [ ] **Static assets** — `src/cantrip/ui/web/static/` containing `index.html`,
  `style.css`, and `cantrip.js`. Bundled into the Python package and served by aiohttp.
  No build step, no transpilation, no bundler
- [ ] **Three-panel layout** — CSS Grid replicating the TUI layout: task checklist (left),
  Juju status (centre), chat (right). Responsive breakpoints matching the TUI behaviour:
  two-panel below 900px, stacked below 600px
- [ ] **Task checklist panel** — renders task list with the same status indicators
  (`✓` done/green, `⟳` active/blue, `○` pending/grey, `◌` blocked/yellow, `✗` failed/red).
  Clicking a task expands its result summary. New tasks appear dynamically via WebSocket
- [ ] **Juju status panel** — renders app boxes, unit counts, status indicators, and
  relation lines using HTML/CSS (styled `<div>` elements and CSS connectors, not
  `<canvas>`). Same colour scheme as the TUI
- [ ] **Chat panel** — scrollable message history with user messages visually distinct from
  agent messages. Input area at the bottom with Enter-to-send. Supports inline progress
  indicators and Markdown rendering (minimal — bold, code, lists — via a small inline
  parser, no library)

### 15.4 Real-Time Updates

Wire the frontend to the WebSocket for live state updates.

- [ ] **WebSocket client** — `cantrip.js` opens a WebSocket connection on load, reconnects
  automatically on disconnect with exponential backoff. Dispatches incoming events to the
  appropriate panel update functions
- [ ] **Incremental DOM updates** — each event type maps to a targeted DOM mutation (e.g.
  `TaskUpdated` finds the task element by ID and updates its status class and text;
  `ChatMessage` appends a new message element). No virtual DOM, no full re-renders
- [ ] **User input** — chat messages sent as WebSocket frames; the server injects them into
  the agent's conversation loop identically to TUI input
- [ ] **Connection status** — a small indicator in the header showing connected/reconnecting
  state. If disconnected, fetches full state from `/api/state` on reconnect to avoid
  missing updates

### 15.5 Alternative Views

Mirror the TUI's alternative views in the browser.

- [ ] **Logs view** — a full-width log viewer (replacing the three-panel layout when active)
  showing unit logs with level and unit filters. Equivalent to the TUI's F3 view
- [ ] **Model graph view** — expanded topology view showing all apps, relations, and
  cross-model integrations. Uses CSS positioning for the graph layout (not canvas)
- [ ] **Help overlay** — modal overlay showing keyboard shortcuts and quick-start guide,
  equivalent to TUI's F1 screen
- [ ] **Keyboard shortcuts** — `?` for help, `1`/`2`/`3` to focus panels, `L` for logs,
  `Escape` to return to main view. Documented in the help overlay

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

## Phase 16: Security Event Logging and Tracing Instrumentation Guidance

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

- [ ] **Identify security-relevant charms** — during the design phase, the agent assesses
  whether the workload has a security surface that warrants event logging. Indicators:
  - Authentication or authorisation (login services, LDAP, OAuth providers)
  - Secret or credential management (vaults, certificate authorities, key stores)
  - Network access control (firewalls, proxies, ingress controllers)
  - Data access (databases, object stores, file servers)
  - System administration (backup tools, monitoring agents, config management)
  If the workload has none of these characteristics, security event logging is skipped
- [ ] **Security event helper** — for charms that need it, generate a small helper
  function (in `src/log_security.py` or similar) that wraps `ops.log._log_security_event`
  or reimplements the same structured JSON format. The helper should:
  - Accept OWASP event type, level, event name, and description
  - Include the charm's application ID automatically
  - Use UTC ISO 8601 timestamps
  - Log at Juju TRACE level (security events are structured data for consumption by
    collectors, not operator-facing messages)
- [ ] **Workload-specific event types** — extend the OWASP vocabulary with events
  appropriate to the charm's workload. Common patterns:
  - `authn_fail` / `authn_success` — for charms wrapping services with login
  - `authz_fail` / `authz_grant` / `authz_revoke` — for access control changes
  - `secret_rotate` / `secret_access` — for credential lifecycle beyond Juju secrets
  - `config_change` — for security-relevant config changes (TLS mode, allowed networks)
  - `data_export` / `data_delete` — for charms wrapping data stores with audit requirements
  - `sys_monitor_disabled` / `sys_monitor_enabled` — if the charm manages health checks
- [ ] **Where to emit events** — guide the agent to emit security events at the right
  points in charm code:
  - Secret lifecycle hooks (`secret-changed`, `secret-rotate`, `secret-expired`)
  - Relation changes that affect access (new database clients, revoked access)
  - Action handlers that perform privileged operations (backup, restore, password reset)
  - Config changes that affect the security posture (TLS settings, network restrictions)
  - Workload log parsing (if the workload logs auth failures, surface them as security events)
- [ ] **Never log sensitive data** — the agent must ensure security event descriptions
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

- [ ] **Long-running workload operations** — if the charm orchestrates a multi-step
  workload process (database migration, backup to object storage, cluster join), wrap
  the sequence in a span so traces show the duration and which step failed. Example:
  a database charm's `_run_backup()` method that shells out to `pg_dump`, uploads to S3,
  and verifies the upload
- [ ] **External API calls** — if the charm calls external services beyond Pebble (cloud
  APIs, web hooks, DNS providers), span these calls to capture latency and errors.
  ops-tracing only covers the Juju/Pebble boundary, not arbitrary HTTP requests
- [ ] **Decision logic with fallback** — if the charm has non-trivial decision logic
  (e.g. "try primary endpoint, fall back to secondary, fall back to degraded mode"),
  span the decision to make the chosen path visible in traces
- [ ] **Async or deferred work** — if the charm defers an event and processes it later,
  span the deferred handler separately so traces show the gap between deferral and
  execution

**What should NOT be manually instrumented:**

- Simple event handlers that just call Pebble (already traced)
- Config-changed handlers that update a Pebble layer (already traced)
- Relation-changed handlers that read databag values (already traced)
- Status setting (already traced)
- Any operation that completes in under 100ms with no external calls

- [ ] **Update system prompt** — add tracing instrumentation guidance to the system prompt
  (`system.md.j2`) so the agent applies these rules when writing charm code. The guidance
  should be concise — a short "instrument / don't instrument" checklist, not a tracing
  tutorial
- [ ] **Update observability skill** — extend the observability skill (`SKILL.md`) with
  the manual instrumentation patterns, including a code example showing `get_tracer()` /
  `start_as_current_span()` usage in a charm context
- [ ] **Template support** — for charm templates that include a long-running operation
  (e.g. the database backup pattern), include a manual span in the template code as
  a concrete example

### 16.3 Security Event Collection via COS

Security events logged at Juju TRACE level need to be collected and made queryable.

- [ ] **Loki collection** — security events are forwarded to Loki via the existing
  `loki-push-api` relation. Add a LogQL query example to the generated Grafana dashboard
  that filters for `type="security"` events
- [ ] **Grafana dashboard panel** — for charms with security event logging, add a
  "Security Events" panel to the generated Grafana dashboard showing a table of recent
  security events with timestamp, level, event type, and description
- [ ] **Alert rules for critical events** — generate Prometheus/Loki alert rules for
  `CRITICAL`-level security events (e.g. repeated `authn_fail` suggesting brute force,
  `authz_fail` suggesting misconfiguration)

### 16.4 Integration with Charm Audit (Phase 10)

When auditing existing charms (Phase 10), assess security logging completeness.

- [ ] **Security logging audit** — as part of the 10.1 best-practices checklist, assess
  whether the charm's workload has a security surface and whether appropriate events are
  being logged
- [ ] **Tracing audit** — check whether ops-tracing is integrated, and whether any
  long-running or external-call operations lack manual spans
- [ ] **Remediation tasks** — if the audit identifies missing security logging or tracing
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

- [ ] **Discover actions** — after deploy, introspect the charm's `actions.yaml` (or the
  equivalent metadata) to enumerate all available actions with their parameters and
  descriptions
- [ ] **Generate action invocations** — for each action, the agent constructs a plausible
  invocation using the parameter schema. For actions with required parameters, the agent
  infers reasonable test values from the parameter descriptions, types, and defaults.
  For destructive-sounding actions (e.g. `delete-data`, `factory-reset`), flag them to the
  user and skip unless explicitly approved
- [ ] **Run and verify** — execute each action via `juju run`, capture stdout/stderr and the
  action result (success/failure/status). Verify that successful actions return the
  documented output schema. Record timing for each action
- [ ] **Report** — produce a summary table of all actions: name, parameters used, result
  status, duration, and any unexpected output. Flag actions that failed, timed out, or
  returned undocumented fields

### 17.2 Relation Smoke Tests

Deploy commonly related charms and verify the integrations actually work.

- [ ] **Identify relation endpoints** — from the charm's metadata, enumerate all `requires`,
  `provides`, and `peers` endpoints with their interface types
- [ ] **Select relation partners** — for each endpoint, identify a suitable charm to relate
  to. Use well-known defaults: `mysql` or `postgresql` for `mysql_client`/`pgsql`
  interfaces, `grafana-agent` for `cos-agent`, `traefik` or `nginx-ingress-integrator`
  for `ingress`, etc. Query Charmhub dynamically for less common interfaces
- [ ] **Deploy and relate** — deploy each partner charm, add the relation, and wait for
  both units to settle to active/idle. Record which relations succeeded and which caused
  errors or blocked status
- [ ] **Verify data flow** — where possible, verify the relation actually does something:
  check that database credentials appeared in the databag, that the ingress proxy routes
  traffic, that COS scrape targets registered. This goes beyond "the relation hook didn't
  crash" to "the integration is functioning"
- [ ] **Report** — summarise all relations tested: endpoint, partner charm, final status,
  and any issues. Flag relations that left units in error or blocked state

### 17.3 Workload Endpoint Testing

Actually use the deployed workload the way a real user would.

- [ ] **Discover endpoints** — from the charm's design document, config, and workload
  metadata, identify how a user would interact with the running service: HTTP endpoints,
  database ports, API URLs, CLI tools, web UIs. If the charm exposes an ingress relation,
  use the ingress URL; otherwise use the unit's direct address
- [ ] **Health checks** — hit health/readiness endpoints if they exist. Verify HTTP services
  return 200. Check that database ports accept connections. Verify TLS if configured
- [ ] **Functional probes** — go beyond health checks to actually exercise the workload:
  - For web applications: fetch the landing page, submit a form, check the response
  - For databases: connect, create a test table, insert and query a row, clean up
  - For APIs: call a representative endpoint, verify the response schema
  - For queue systems: publish and consume a test message
  - For storage: write and read back a test object
  The agent designs these probes based on what it learnt about the workload during the
  research phase. Probes should be non-destructive and use test/temporary data
- [ ] **Report** — summarise what was tested, what worked, and what didn't. Include response
  times and any unexpected behaviour. This report goes directly to the user as a
  confidence check: "I deployed your charm, related it to PostgreSQL, hit the web UI,
  and confirmed it serves pages correctly"

### 17.4 Config Variation Testing

Exercise the charm's configuration options to verify they actually take effect.

- [ ] **Enumerate config options** — from `config.yaml`, list all configuration options with
  their types, defaults, and descriptions
- [ ] **Generate test values** — for each config option, generate at least one non-default
  value that should be valid. For boolean options, toggle them. For string options with
  documented valid values, try each. For port numbers, try an alternative port. Skip
  options that would break the deployment irreversibly (e.g. storage paths on a running
  system)
- [ ] **Apply and verify** — set each config value via `juju config`, wait for the charm to
  settle, and verify the change took effect: check the workload's actual configuration
  (via Pebble exec, API calls, or behaviour change), not just that the charm didn't crash
- [ ] **Reset and continue** — restore each option to its default before testing the next,
  to avoid cascading interactions. Record any options that cause the charm to enter
  error/blocked state
- [ ] **Report** — summarise config options tested, which took effect as expected, which had
  no visible effect (potential dead config), and which caused problems

### 17.5 Upgrade and Lifecycle Testing

Verify the charm handles lifecycle operations gracefully.

- [ ] **Scale up/down** — add a second unit, wait for it to settle, verify the workload
  functions with two units (e.g. both serve traffic, data replicates). Then remove the
  extra unit and verify the remaining unit still works
- [ ] **Config change under load** — if a health endpoint exists, change a config value
  while periodically hitting the endpoint, and report whether there was downtime or errors
  during the reconfiguration
- [ ] **Refresh** — if the charm was built from a local path, rebuild it, refresh the
  deployed charm to the new revision, and verify the workload still functions after upgrade
- [ ] **Report** — summarise lifecycle operations tested and their outcomes. Flag any
  operations that caused downtime, data loss, or stuck states

### 17.6 Acceptance Test Report

Consolidate all acceptance testing into a single report for the user.

- [ ] **ACCEPTANCE.md** — generate a Markdown report in the charm directory summarising all
  acceptance tests performed: actions exercised, relations tested, endpoints probed, config
  options verified, lifecycle operations checked. Each section includes pass/fail status,
  timing, and notes on any issues found
- [ ] **User presentation** — present a concise summary in the chat: "I've put your charm
  through its paces — ran 5 actions, tested 3 relations, verified the web UI responds,
  toggled 8 config options, and scaled to 2 units. Everything passed except [specific
  issue]. Full report in ACCEPTANCE.md"
- [ ] **Feed back into build** — if acceptance tests reveal problems (broken actions,
  non-functional relations, dead config options), automatically create fix tasks in the
  work queue and iterate. The charm isn't done until acceptance tests pass
- [ ] **Planner integration** — add acceptance testing as a standard phase in the build
  pipeline, after integration tests pass. The planner generates acceptance test tasks
  based on the charm's metadata (actions, relations, config options, workload type)

**Exit criteria:** After building a charm, Cantrip deploys it, runs every action, relates
it to appropriate partners, hits the workload endpoints, toggles config options, and tests
lifecycle operations — then reports the results to the user. Issues found during acceptance
testing feed back into the build loop as fix tasks. The user gets a concrete "I used your
charm and it works" confirmation, not just "the tests passed".

---

## Phase 18: Agent Framework Evaluation — Build vs. Adopt

**Goal:** Investigate whether Cantrip would benefit from adopting an established agent
framework (e.g. LangGraph, CrewAI, Claude Agent SDK, AutoGen, or similar) rather than
continuing to build its own agent infrastructure from scratch. The current architecture
(two-loop design, work queue, subagents, tool dispatch) is hand-rolled; this phase evaluates
whether an existing framework would give us better primitives, reduce maintenance burden, or
unlock capabilities we'd struggle to build ourselves — or whether the control and simplicity
of our bespoke approach remains the right trade-off.

### 18.1 Landscape Survey

Map the current agent framework ecosystem and identify viable candidates.

- [ ] **Identify candidates** — survey the major agent frameworks available as of the
  evaluation date: Claude Agent SDK, LangGraph, CrewAI, AutoGen, DSPy, Semantic Kernel,
  Haystack Agents, and any others with meaningful traction. Focus on frameworks that
  support multi-step tool-using agents with some form of task orchestration
- [ ] **Feature matrix** — for each candidate, document: supported LLM providers, tool/
  function-calling model, memory/state management, multi-agent orchestration, streaming
  support, observability/tracing, error recovery, Python support, licence, community
  activity, and maturity level
- [ ] **Disqualify early** — eliminate candidates that are fundamentally incompatible with
  Cantrip's requirements (e.g. locked to a single LLM provider we don't use, no async
  support, abandoned/unmaintained, restrictive licence)

### 18.2 Architecture Mapping

Map Cantrip's current architecture onto each shortlisted framework to understand fit.

- [ ] **Component mapping** — for each surviving candidate, map Cantrip's core components
  to the framework's equivalents: conversation loop → ?, work queue → ?, subagents → ?,
  tool dispatch → ?, state persistence → ?, context management → ?. Identify components
  with clean mappings, awkward mappings, and no mapping at all
- [ ] **Gap analysis** — identify what Cantrip currently does that the framework doesn't
  support out of the box (e.g. Juju-specific tool patterns, charm template generation,
  TUI integration, SQLite session store). Estimate the effort to bridge each gap
- [ ] **Gain analysis** — identify what the framework provides that Cantrip doesn't
  currently have and would benefit from (e.g. built-in RAG, better context management,
  automatic retries, structured output parsing, agent-to-agent communication protocols)

### 18.3 Proof of Concept

Build a small spike with the most promising candidate(s).

- [ ] **Select top 1–2 candidates** — based on the mapping exercise, pick the most
  promising framework(s) for a hands-on evaluation
- [ ] **Spike implementation** — reimplement a representative slice of Cantrip's
  functionality using the candidate framework. The slice should cover: a multi-turn
  conversation with tool calls, a background task that runs autonomously, and a subagent
  that performs a focused piece of work (e.g. researching a workload). This need not be
  production-quality — it's a feasibility test
- [ ] **Evaluate ergonomics** — assess how natural the framework feels for Cantrip's
  patterns. Is the tool definition model compatible? Does the orchestration model fit our
  two-loop design? Can we still control prompts precisely? Is debugging straightforward?
- [ ] **Measure overhead** — compare token usage, latency, and code complexity between the
  spike and the equivalent Cantrip code. Frameworks add abstraction; quantify the cost

### 18.4 Decision and Recommendation

Synthesise findings into a clear recommendation.

- [ ] **Write FRAMEWORK_EVALUATION.md** — a decision document covering: candidates
  surveyed, architecture mapping results, spike findings, and a clear recommendation
  (adopt framework X / stay bespoke / hybrid approach). Include trade-off analysis:
  - *Control*: how much flexibility do we lose over prompts, tool dispatch, and state?
  - *Maintenance*: how much agent infrastructure code do we stop maintaining?
  - *Velocity*: does the framework accelerate future roadmap items?
  - *Lock-in*: how coupled would we become to the framework's abstractions?
  - *Migration cost*: what would it take to adopt, and can it be incremental?
- [ ] **Identify hybrid options** — even if full adoption isn't recommended, are there
  specific components worth borrowing? (e.g. adopt a framework's tool-calling protocol
  but keep our own orchestration, or use a framework's memory system but keep our own
  conversation loop)
- [ ] **Present to user** — summarise the recommendation in the chat with a clear rationale
  and proposed next steps

**Exit criteria:** A written evaluation document with a clear, evidence-based recommendation
on whether to adopt an agent framework, stay with the bespoke approach, or take a hybrid
path. If adoption is recommended, the document includes a migration sketch. If staying
bespoke, the document articulates what we'd be giving up and why that's acceptable.

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
| M18: Framework Decision | 18 | Evidence-based recommendation on build-vs-adopt for agent infrastructure |
