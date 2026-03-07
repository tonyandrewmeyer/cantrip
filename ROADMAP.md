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
│  │                          TUI                                     │     │
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

## Phase 4: Autonomous Agent Core

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
- [ ] **Category grouping** — tasks grouped by phase (research, build, deploy, test)
  or shown as a flat ordered list — TBD based on what reads better in practice

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
- [ ] **Per-provider rate awareness** — respect provider rate limits; back off individual
  subagents rather than the whole executor

### 6.2 Fast Path for Simple Charms

The full research → synthesis → confirm → build pipeline is overkill for well-understood
workloads (Flask app, Django, FastAPI, Express, etc.). A streamlined path should skip or
compress the research phase.

- [ ] **Template-based design** — for known 12-factor frameworks, generate a design
  proposal from a template rather than doing full web research
- [ ] **Skip research when unnecessary** — if the workload is a standard framework with
  no source URL to analyse, go straight to design/confirm with a pre-built proposal
- [ ] **One-shot build mode** — for trivial cases, collapse scaffold + write code + pack
  into a single subagent invocation instead of separate tasks

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

- [ ] **Discuss** — evaluate whether the initial planning call should be replaced with a
  deterministic task template for common flows, reserving LLM planning for unusual or
  complex requests
- [ ] **Hybrid approach** — hardcode Phase 1 (research) tasks, use LLM planning only for
  Phase 3 (build) tasks which depend on the design proposal

### 6.5 Model Routing Review (to be considered)

Review which model is used for which task categories. Research tasks may not need the
primary model; coding tasks definitely should stay on the primary.

- [ ] **Audit current routing** — map out which model handles each task category today
  (research and infra already use light model; synthesis uses primary)
- [ ] **Evaluate quality trade-offs** — test whether light-model research produces
  sufficient quality for downstream synthesis, or whether certain research tasks
  (e.g. source analysis) benefit from the primary model
- [ ] **Per-task model override** — allow the planner or user to specify model preference
  per task, rather than only per category

**Exit criteria:** The common "build a 12-factor charm" flow completes in under two
minutes wall-clock time (excluding user confirmation and Juju deploy wait).

---

## Phase 7: Polish and Ecosystem

**Goal:** TUI enhancements, advanced testing, full ecosystem integration.

### 7.1 TUI Enhancements
- [ ] Visual model/app/integration graph
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
- [ ] Migration assistance (existing charm → improved charm)
- [ ] Upgrade testing (verify charm upgrades cleanly between revisions)

**Exit criteria:** Showcase-ready demo of the full Canonical ecosystem. Agent autonomously
builds, tests, and publishes charms with full observability and quality assurance.

**Note:** Phase 7 was previously Phase 6. Renumbered when the Speed phase was inserted.

---

## Phase 8: Terraform Support

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
| Terraform support (8.x) | Phase 5 design pipeline | Needs working charm build pipeline to generate modules from |

---

## Milestones

| Milestone | Phase | Definition |
|-----------|-------|------------|
| M0: Talking | 0 ✓ | CLI chat with Gemini + juju status |
| M1: First Charm | 1 ✓ | Flask app → running charm in 2 min |
| M2: Dev Loop | 2 ✓ | Fast iteration with trace debugging |
| M3: All Paths | 3 ✓ | 12-factor, custom, infra all working |
| M4: Autonomous | 4 | Agent works independently with visible task tracking |
| M5: Research-Driven | 5 | Agent proactively researches and proposes grounded designs |
| M6: Fast | 6 | Common charm build completes in under two minutes |
| M7: Showcase | 7 | Demo-ready with full ecosystem, testing, and publishing |
| M8: Terraform | 8 | Cantrip generates and validates Terraform modules for charms |
