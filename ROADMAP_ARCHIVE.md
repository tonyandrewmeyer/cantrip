# Cantrip Roadmap Archive

Completed phases from [`ROADMAP.md`](ROADMAP.md). This file is the
long-form historical record — each phase is preserved with its original
goals, acceptance criteria, and sub-task detail. See `ROADMAP.md` for
active work.

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

## Phase 25: Code Health ✓

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
- [x] `charm.py` — string replacement for code injection is brittle —
  ``_inject_ops_tracing_into_charm_py`` now uses anchored multi-line
  regexes (``^import ops\r?$`` and ``^(?P<indent>[ \t]*)super\(\)\.__init__\([^)]*\)[ \t]*\r?$``)
  and requires *both* anchors to match before patching.  The old
  ``str.replace`` version would silently insert ``import ops_tracing``
  without the paired setup call, leaving a NameError at charm startup.
  Captures the init line's indent and reuses it for the injected
  ``ops_tracing.setup(self)``, so a four-space charm no longer inherits
  the hardcoded eight-space indent.  Eight unit tests in
  ``TestInjectOpsTracingIntoCharmPy`` cover ``super().__init__(*args,
  **kwargs)``, ``super().__init__()``, ``import ops.charm`` (which no
  longer spoofs a match), missing-anchor refusal, custom indent, CRLF
  files, and multiple-class first-occurrence semantics.
- [x] `autodeploy.py` — loose keyword matching in free-form text —
  ``_ACCEPTANCE_VERDICT_RE`` / ``_ACCEPTANCE_PROSE_FAIL_RE`` anchor
  the area keyword with ``\b`` word boundaries and an optional plural
  (``\b(action|relation|...)s?\b``), so ``actionable`` and
  ``relationship`` no longer match.  Bare ``error`` has been dropped
  from the prose alternation — it caused false positives on "action
  executed without error" — leaving ``fail*`` / ``broken`` as the
  explicit failure verbs.  A new ``_NEGATED_FAIL_IN_SNIPPET_RE``
  disqualifies prose matches that contain negation phrases
  (``no failures``, ``not failing``, ``didn't fail``, ``never fail``,
  ``without failures``), so "no failures observed" near ``actions``
  stops flagging actions.  Eight regression tests in
  ``TestExtractAcceptanceFailures`` pin the new behaviour
  (``actionable``/``relationship`` rejection, bare-``error`` rejection,
  three flavours of negation, mixed-line passthrough, and plural
  keywords).

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
- [x] `main.py` — magic string checks for project identity —
  extracted ``_CANTRIP_PYPROJECT_NAME_MARKER`` and
  ``_CANTRIP_PYPROJECT_ENTRY_MARKER`` module constants so the
  source-tree detection logic reads as a named invariant instead of
  two anonymous substring checks.
- [~] Status indicators, CSS classes, log levels scattered throughout
  TUI widgets — deferred.  The highest-value offenders already have
  module-level constants: ``tui/screens/logs.py`` defines
  ``_LOG_LEVELS``; ``tui/widgets/status.py`` defines ``_STATUS_ORDER``
  and the icon/class mappings.  Remaining scattered literals
  (``"blocked"``, ``"waiting"``, ``"active"``, and their Textual CSS
  class counterparts across ``tui/screens/transcript.py``,
  ``tui/screens/graph.py``, and the chat widget) are mostly
  self-documenting in their local context; extracting them would
  require coordinating a shared ``JujuStatusLabel`` enum across
  widgets and their CSS, which is out of proportion for a "Low"
  cosmetic cleanup.  Revisit if these values start drifting or if a
  future phase wants typed status objects end-to-end.

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

## Phase 28: Agent Core Robustness ✓

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

## Phase 31: User Experience Improvements ✓

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

### 31.3 Medium — Session Resume UX ✅

- [x] On launch, if a `.cantrip` file exists with unfinished tasks, offer to resume
  rather than starting fresh — new ``CantripAgent.preview_session()``
  peeks at the store without mutating state.  CLI shows a synchronous
  ``[R]esume / [F]resh / [T]ranscript`` prompt; TUI pushes a dedicated
  ``ResumePromptScreen`` modal; the Web UI renders a banner across the
  top of the chat panel with three buttons and a collapsible transcript
  tail.  All three surfaces share the same preview helper.
- [x] Show a summary of what was in progress when the session ended —
  ``SessionPreview.summary()`` renders charm name, task counts
  (pending/done/failed), message count, and the last save time in a
  single line.  The transcript option expands the last 20 messages
  inline via the new ``agent.transcript_tail(limit)`` helper.
- [x] Let the user choose: resume, start fresh, or review transcript first
  — Fresh renames ``.cantrip`` to ``.cantrip.bak-<timestamp>`` via
  ``archive_session()`` so nothing is destroyed; Resume loads state as
  before; Transcript shows the tail and re-prompts.  Web endpoints:
  ``GET /api/session/preview``, ``POST /api/session/decide``,
  ``GET /api/session/transcript``.

### 31.4 Medium — Token Cost Dashboard ✓

- [x] Show cumulative token usage and estimated cost in the `ModelInfoBar` —
  new `cantrip.llm.pricing` module with per-model rates (Claude 4 family,
  Gemini 2.5/3, inference-snap free); `session_cost_usd` and
  `alltime_cost_usd` reactives on the bar; session cost applies Claude's
  cache-read (10%) and cache-write (125%) modifiers to the agent's session
  accumulators; `/cost` CLI command grew a per-model cost column and an
  overall estimated total
- [x] Break down by category (research, build, deploy, test, debug) —
  schema bumped to v9 with a nullable ``category`` column on
  ``token_usage`` (idempotent ALTER so existing DBs migrate on open).
  The subagent stamps ``response.metadata["_task_category"]`` so the
  executor's ``_record_usage`` plumbs it through ``StateService``
  into ``SessionStore.record_usage(..., category=...)``; main-loop
  turns and legacy rows pass NULL and aggregate under ``conversation``
  in the new ``get_usage_by_category(since=None)`` helper.  Both the
  CLI ``_print_cost`` path and the ``/cost`` slash command render a
  **By category** block below the **By model** one.  Cache cost is
  not attributed per category — it's still reported as a global
  adjustment on the overall total.
- [x] Show cache hit rate when using Claude — already implemented earlier
  (Phase 27.1); confirmed still working alongside the new cost line

### 31.5 Medium — Log Screen Model Selector ✓

- [x] `LogScreen` always shows the dev model — add a dropdown or binding to switch
  to COS model logs — ``m`` binding cycles between dev and COS when
  both are configured; no-op when only one model is set so the key
  can't put the screen into a broken "None" state.  ``action_logs``
  in the TUI now passes both ``dev_model`` and ``cos_model`` to the
  screen; the legacy positional ``model=`` kwarg is preserved for
  direct callers.  Title bar shows the active model and level, wrapped
  in ``Content`` so arbitrary model-name characters can't be
  mistaken for Textual markup.
- [x] `GraphScreen` should support filtering by app status (show only
  blocked/waiting) — ``f`` binding cycles the filter through
  ``all → blocked → waiting → blocked+waiting``.  ``build_graph()``
  gained an optional ``status_filter`` set; filtered edges (pairs
  where one end is hidden) are dropped so the relation section stays
  honest, and a "No applications matching filter" placeholder replaces
  an empty panel section so the user knows the screen hasn't broken.
  Title bar shows the active filter label.

### 31.6 Medium — Trace Screen with Real URLs ✅

- [x] `TraceScreen` has placeholder `...` URLs for Tempo/Loki — generate real
  deep-link URLs from the COS model endpoint addresses — new
  ``cantrip.agent.cos_endpoints`` helper parses the watcher's cached COS
  status into a ``CosEndpoints`` value carrying the Grafana URL (lifted
  from the workload status message), Grafana-active flag, and Tempo/Loki
  presence.  ``TraceScreen`` receives these and builds Grafana Explore
  deep-links for Tempo and Loki (JSON ``left=`` blob pre-selecting the
  datasource).  When the status message doesn't advertise a URL, the
  screen falls back to ``http://localhost:3000`` and says so.
- [x] Actually check COS reachability instead of always showing "Connected"
  — status line is now tri-state: ``Not deployed`` (no COS model),
  ``Unknown (no poll yet)`` (watcher hasn't fired yet), ``Reachable``
  (Grafana present and all units ``active``), or ``Not reachable``
  (Grafana present but not active).  No new network calls — reachability
  is read from the watcher's cached status.

### 31.7 Low — Charm Comparison Mode ✓

- [x] New ``cantrip compare CHARM_A/ CHARM_B/`` subcommand (chose
  a dedicated subcommand over a ``--compare`` flag on ``run`` so
  invoking it doesn't risk triggering the agent loop).
- [x] Diff surfaces: directory structure (landmark files and
  directories), ``config.options`` (added/removed/changed, with
  left+right values on changes), relation endpoints
  (``provides``/``requires``/``peers``), actions, containers,
  extensions, unit-test count, integration-test count, base, charm
  name.  Identical sections render as ``(identical — same X)`` so
  the reader's eye can skip straight to drift.
- [x] New ``cantrip.compare`` module — pure-function design, frozen
  dataclasses (``CharmSnapshot``, ``DictDiff``, ``ComparisonReport``)
  — so the core logic is unit-testable without any CLI scaffolding.
- [x] Parses both modern ``charmcraft.yaml`` (4.x) and the legacy
  ``metadata.yaml`` / ``config.yaml`` / ``actions.yaml`` split,
  merging the two so a hand-crafted charm on the old layout still
  compares cleanly against a Cantrip-generated one on the new
  layout.
- [x] 18 unit tests for the core module + 4 CLI-entry tests
  exercising argparse dispatch, path validation, and the printed
  report.

### 31.8 Low — Export Running Session ✓

- [x] Allow exporting the transcript while the session is still running (not just
  after exit via `export-transcript` subcommand)
- [x] Add `F10` binding or `/export` chat command — shared slash dispatcher
  gained `/export [html|jsonl|markdown] [path]`, so the command is typeable
  in the TUI, CLI REPL, and Web surfaces without leaving the session

### 31.9 Low — Notification Sounds / Desktop Notifications ✓

- [x] Long-running builds can take minutes — notify the user when a task completes
  or needs confirmation — opt-in via ``CANTRIP_NOTIFY`` env var; a
  ``TaskNotifier`` subscribes to ``TASK_UPDATED`` and fires at most once
  per task when it first reaches ``done``/``failed`` (non-terminal
  status changes stay silent)
- [x] Use terminal bell (`\a`) for simple notification — ``CANTRIP_NOTIFY=bell``
  writes ``\a`` to stderr; ``both`` combines bell + desktop
- [x] Optional desktop notification via `notify-send` on Linux —
  ``CANTRIP_NOTIFY=desktop`` shells out to ``notify-send`` with a
  "Cantrip task completed/failed" summary and the task title; silently
  no-ops when ``notify-send`` isn't on the PATH (macOS, stripped Docker
  images), so enabling desktop mode never crashes a session

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

### 31.13 Medium — Web UI Frontend Improvements ✓

- [x] Markdown renderer is basic — no support for tables, links, images, nested lists,
  or `*` bullet lists (only `- ` is handled); consider using a proper Markdown library
  (marked.js or similar) instead of regex-based rendering — rendered server-side
  via ``markdown-it-py`` with ``linkify`` + ``table`` + ``strikethrough`` and
  ``html=False`` so ``<script>`` escapes to text.
- [x] No Markdown rendering for user messages — user sees raw text while assistant
  messages get rendered HTML; apply the same renderer to user messages — same
  pipeline, same CSS (``.msg-body`` applies to every role now).
- [x] No message timestamps displayed (same issue as TUI) — every chat message
  carries a UTC ISO timestamp; browser formats HH:MM per-locale in a ``<time>``
  tag.
- [x] No visual indication of which tool calls the agent is making — the "Thinking..."
  indicator has no detail about what the agent is actually doing —
  ``status_bar_changed`` bus events now feed a ``#thinking-label`` span so users
  see "⟳ running: charmcraft_pack" mid-turn.
- [x] No scroll-to-bottom button when viewing long chat history — floating button
  appears when the user scrolls more than one screenful above the latest row;
  auto-scroll-on-new-message respects their position.
- [x] Chat input has no multiline support (single `<input>` instead of `<textarea>`)
  — now an auto-growing ``<textarea>`` (Enter submits, Shift+Enter newline, cap 200px).
- [x] No way to cancel an in-flight request from the web UI — Cancel button on
  the thinking indicator posts ``cancel_request``; server dispatches turns as
  background tasks so the cancel arrives while the turn is running.
- [x] Juju status polling interval is hardcoded at 15s with no way to force refresh
  (except via the Graph overlay's `R` key) — refresh button on the panel and
  ``Alt+R`` now always refreshes (still refreshes the graph when graph is open).
- [x] `--improve` flag is silently ignored when using `--web` mode — now an
  explicit error (exit 2) pointing at the TUI/CLI path.
- [x] No preflight status shown in the web UI — the user has no visibility into
  environment preparation progress — dedicated preflight panel renders five
  checks (Concierge, Environment, Juju CLI, Controller, COS) with animated
  running icons and auto-hides after completion.

### 31.14 Low — Web UI Input Validation ✅

- [x] `/api/logs` `lines` parameter has no upper bound — clamp to `max(1, min(lines, 5000))`
- [x] `/api/logs` and `/api/logs-stream` `level` parameter passed unsanitised to
  subprocess — validate against `{"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}`

### 31.15 Medium — Web UI and TUI Design Quality Pass ✓

Use the impeccable.style skills (now installed as a Claude Code plugin) to
systematically raise the design quality of both the Web UI and TUI.
The impeccable skills aren't currently invocable as slash commands in the
Claude Code session, so the SKILL.md reference docs were applied manually
(audit, critique, harden, clarify, distill, layout, polish — each
reviewed and its concrete checklist applied).

- [x] Run `/impeccable teach` on the cantrip project — reference docs read
  directly from the plugin cache at
  ``~/.claude/plugins/cache/impeccable/impeccable/2.1.1/.trae-cn/skills/impeccable/reference/``;
  no persistent ``.impeccable.md`` committed (the existing ``:root`` CSS
  variables + ``cantrip.tcss`` theme variables already encode the design
  context the file would have held).
- [x] `/audit` the Web UI — touch targets on header buttons brought up to
  WCAG 2.5.5 (min 2.25rem × 1.75rem); ``aria-expanded="true"`` now has a
  visible style; pre-rendered HTML injection is XSS-safe via renderer
  config (no raw HTML, ``javascript:`` URLs rejected); previous Phase 60
  findings (Send button contrast, focus ring, live regions, modal
  dialogs) remain in place.
- [x] `/critique` the Web UI against Nielsen's heuristics — chat panel,
  task checklist, Juju status panel each reviewed.  Surfaces requiring
  change: footer hint missed Alt+R, "Start fresh" button lacked an
  explanation of what it does (now carries a ``title`` describing the
  archive behaviour), tool-call activity invisible mid-turn (now shown
  via ``#thinking-label``).
- [x] `/harden` the Web UI — chat gets a welcome empty state ("Ready
  when you are.") with an example prompt; charm name ellipses at 30ch
  so long names don't break the header; Juju app messages keep the
  full text in ``title`` and truncate visibly with CSS ellipsis instead
  of the old ``substring(0, 40)`` hard cut; log-overlay error states
  now surface the HTTP status code and a "is a dev model attached?"
  hint instead of generic "Failed to fetch".
- [x] `/clarify` all user-facing copy — error strings include HTTP
  codes and actionable context; help overlay documents Shift+Enter for
  newlines; footer hint lists Alt+R; ``--improve`` in web mode now
  errors with a message pointing at the TUI path (landed in 31.13).
- [x] `/distill` the Web UI layout — already tight: three right-sidebar
  panels (preflight, tasks, Juju) with preflight auto-hiding after
  completion, minimal chrome, tokens-only colours.  No further trim
  needed.
- [x] `/layout` review — spacing uses a 4-/8-/12-/16-/24-px rhythm
  (0.25–1.5rem at 14px base), responsive breakpoint at 700px stacks the
  sidebar, header uses flex with ``gap`` for rhythm.  No structural
  change needed.
- [x] `/polish` final pass on both UIs before any release milestone —
  completed alongside the other impeccable bundles above; focus rings
  (``:focus-visible`` at global level), hover transitions, and the
  rotate-on-active panel button all sized and timed per impeccable's
  motion guidance.
- [x] Review TUI colour palette and widget spacing — ``cantrip.tcss``
  already resolves every colour through Textual theme variables
  (``$primary``, ``$success``, ``$warning``, ``$error``, ``$surface``),
  which aligns with impeccable's "tokens not hard-coded colours"
  principle.  No change needed; the per-phase theme work (Phase 29,
  65) covers widget-level polish.

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

## Phase 33: New Skills and Capabilities ✓

**Goal:** Expand what Cantrip can do beyond basic charm building — charm migration,
existing bundle management, and deeper ecosystem integration.

### 33.1 Medium — Existing Bundle Management ✓

**Note:** Juju bundles are deprecated — new bundles should not be created. However,
many existing deployments use bundles, so Cantrip should be able to work with them.

- [x] New `bundle` skill (`src/cantrip/skills/bundle/SKILL.md`) covering
  how to read an existing `bundle.yaml`, lay on overlays, deploy the
  result, and migrate a bundle-based deployment to individual
  `juju_deploy` + `juju_relate` (or Terraform) commands.  The skill
  opens by explaining why bundles are deprecated and ends with an
  explicit "do not create new bundles" section so the agent pushes
  back on bundle-authoring requests.
- [x] `bundle_deploy` tool (`src/cantrip/agent/tools/juju.py::BundleDeployTool`):
  wraps `jubilant.Juju.deploy(bundle_path, overlays=[...])` with
  early fail-fast validation of the bundle path and every overlay
  path, a 10-minute timeout suited to bundle deploys, and
  structured output reporting how many overlays applied.  Surfaces
  `jubilant.CLIError` / `TaskError` as unsuccessful ToolResults.
  Registered in `build_tools` next to `JujuDeployTool`.
- [x] Overlay syntax: the `bundle` skill documents precedence rules
  (scalar replace, relation add, `null` removal, last-overlay-wins
  for scalar collisions) with worked examples for channel/scale
  pinning, removing an upstream app, and adding a cross-model offer.
- [x] Multi-charm deployments use `juju_deploy` + `juju_relate`
  (or Terraform) instead of writing bundles — the system prompt's
  "Default Integrations" section carries a new "Multi-charm
  deployments — do not write new bundles" note that names the
  `bundle` skill and `bundle_deploy` tool as the legacy-consumption
  escape hatch.
- [x] Test coverage: six `TestBundleDeployTool` cases pin the
  not-installed path, missing-bundle / missing-overlay fail-fast
  behaviour, successful dispatch, overlay + trust passthrough, and
  `CLIError` surfacing.  A new `test_bundle_skill_covers_*` pin
  protects the skill's "do not create new bundles" stance, its
  tool/structure anchors, and the overlay section.  `reference-tools.html`
  lists `bundle_deploy` with a "legacy consumption only" annotation.

### 33.2 High — Charm Migration Skill ✓

- [x] New `charm-migration` skill for migrating legacy charms to modern
  patterns — covers reactive-framework → ops, StoredState → modern
  storage, Harness → Scenario, fetch-libs → PyPI as one umbrella
  workflow, with per-migration decision trees and recipes.  Delegates
  the test-file half to the existing `harness-migration` skill and the
  PyPI-authoring half to `charm-library`.
- [x] Detect and replace: all four migrations are detectable from
  charmlint diagnostics.  `DEP001` covers StoredState, `DEP002` covers
  Harness, `LIB001`/`LIB002` cover fetch-libs; added new `DEP004`
  (``uses-reactive-framework``) that flags ``charms.reactive`` imports
  and ``@when`` / ``@when_not`` / ``@when_any`` / ``@when_all`` /
  ``@hook`` decorators.
- [x] Integrate with `--improve` mode: `_infer_gaps_from_audit` now
  recognises the reactive-framework keywords in the audit report;
  `plan_improvement_fixes` treats the new `reactive_framework` gap as
  a modernisation trigger and prepends an explicit
  "Load the `charm-migration` skill first" step to the modernise-code
  task description whenever any deprecated-API or reactive-framework
  gap is set.
- [x] Test coverage:
  `tests/unit/test_skills.py::test_charm_migration_skill_covers_all_four_migrations`
  pins a dozen required anchors (every audit rule ID, reactive-framework
  patterns, StoredState decision-tree keywords, Harness delegation,
  fetch-libs / charmlibs anchors).  `TestDeprecatedRules` gains two
  tests for DEP004 (import form + bare decorator form).
  `TestInferGapsFromAudit` gains tests for both reactive-framework
  keyword branches.  `TestPlanImprovementFixes` gains tests that the
  modernise task actually names the `charm-migration` skill and the
  ``framework.observe`` anchor whenever reactive-framework gaps fire.

### 33.3 Medium — Multi-Charm Workspace ✓

- [x] Support working on multiple related charms simultaneously — new
  `cantrip.workspace.yaml` manifest format declares the charms, their
  paths, cross-charm relations, and any shared config; parsed by a new
  `cantrip.workspace` module (pure-function design, frozen
  dataclasses, round-trippable `to_dict()`).  `workspace_info` tool
  reads the manifest and reports it to the agent; it walks upwards
  from the given directory (or cwd) so launching inside any charm
  subdirectory still finds the workspace root.  No AgentState churn
  — per-charm flows keep working unchanged and the workspace is
  additive metadata.
- [x] Shared design document covering cross-charm relations and
  config — the manifest's `relations:` list captures the
  provider/requirer/interface triple (endpoints validated against the
  charm list at load time) and `shared_config:` captures values that
  should match across charms (log levels, TLS modes).  The new
  `workspace` skill documents the provider/requirer split, interface
  naming conventions, the app-databag / unit-databag / Juju-secret
  decision tree, and delegates the library authoring to
  `charm-library`.
- [x] Coordinate deploy and integration testing across charms — the
  `workspace` skill walks through coordinated deploy (per-charm pack
  → per-charm `juju_deploy` → per-relation `juju_relate` → single
  `juju_wait`) and Jubilant integration tests that deploy multiple
  charms, use `juju.integrate(provider_side, requirer_side)` for
  explicit endpoint pairing, and prefer charm actions over SSH for
  assertions.  The skill closes by ruling out bundle authoring
  (pointing at the `bundle` skill for legacy consumption and the
  `terraform` skill for reusable orchestration).
- [x] System prompt integration: the "Default Integrations" section
  gained a "Multi-charm deployments" paragraph telling the agent to
  load the `workspace` skill and call `workspace_info` whenever the
  user is working across ≥2 related charms.
- [x] Test coverage: `tests/unit/test_workspace.py` (17 tests)
  covers happy-path parsing, the full-manifest round-trip, missing /
  malformed / empty-charm / duplicate-name / unknown-charm /
  missing-colon / missing-interface error paths, `find_manifest`
  walking upwards, and the dataclass `frozen=True` invariant.
  `tests/unit/test_workspace_tool.py` (5 tests) covers missing-manifest
  error, malformed-manifest error, full-output rendering,
  walk-up-from-nested-path behaviour, and the cwd default.  A new
  `test_workspace_skill_covers_multi_charm_work` anchor test in
  `test_skills.py` pins the manifest schema, cross-charm design, and
  coordination sections plus the anti-bundle stance.
  `reference-tools.html` lists `workspace_info` under the internal
  tools section.

### 33.4 Medium — Charm Library Authoring

- [x] New `charm-library` skill for creating reusable charm libraries —
  covers when to create a library vs in-charm code, the
  `lib/charms/<charm>/v<N>/<library>.py` path convention, and the
  publisher/consumer workflow end-to-end
- [x] Generate `lib/charms/<charm>/v0/<library>.py` with proper versioning —
  skill documents the four mandatory module-level constants (`LIBID`,
  `LIBAPI`, `LIBPATCH`, `PYDEPS`) and the rules for bumping each
  (patch every change, major only on breaking changes, new `v<N+1>/`
  file for breakage so old consumers keep fetching the old file)
- [x] Include unit tests and documentation — skill shows a Scenario
  test harness for exercising a requirer library through a minimal
  test-only charm, and defines the module-docstring template Charmhub
  surfaces on the library page
- [x] Publish via charmcraft — skill covers
  `charmcraft register-lib` (first-time only, assigns `LIBID`),
  `charmcraft publish-lib` (every release, requires `LIBPATCH` bump),
  and the consumer's `charm-libs:` declaration; also points at the
  modern PyPI alternative (`charmlibs-*` under
  `canonical/charmlibs`) for general-purpose helpers
- [x] Test coverage: new `test_charm_library_skill_covers_authoring`
  check in `tests/unit/test_skills.py` pins a dozen required anchors
  (LIBID/LIBAPI/LIBPATCH/PYDEPS, every `charmcraft` subcommand,
  the on-disk path, Scenario, and the PyPI alternative)

### 33.5 Low — Interactive Debugging Mode ✓

- [x] Connect to a running deployment and investigate issues
  interactively — shipped as a new `charm-debug` skill that channels
  the agent's existing Juju read-only tools (`juju_status`,
  `juju_debug_log`, `juju_stream_logs`, `juju_read_relation_data`,
  `juju_get_app_config`, `juju_list_secrets`, `juju_show_secret`)
  into a deterministic five-step inspection.  No new CLI subcommand:
  the skill activates on diagnostic phrasing ("stuck", "crashloop",
  "relation not working", …) and the agent already has every tool
  it needs.  Skill advertises itself as read-only so the agent won't
  accidentally mutate state during diagnosis.
- [x] Automatically check status, logs, relation data, config, and
  secrets — the skill's inspection order is literal: status first
  (including the charm's own status message, which encodes the
  author's self-diagnosis), then logs, then relation data for the
  endpoints status mentions, then config vs. defaults, then secret
  ownership / grants / revision freshness.
- [x] Propose fixes based on observed symptoms — a 12-row
  symptom → likely-cause → next-action table maps common
  inspection findings onto concrete tool calls or code-level
  directions, and a structured report template pins the agent's
  write-up so the user sees the same shape every time.

### 33.6 Low — Charm Benchmarking ✓

- [x] New `benchmark` skill for measuring charm performance —
  covers when to load, what `hook_benchmark` measures (and does
  not measure — actions, workload latency, cold-start CPU), and
  interpretation rules of thumb per hook type with ceilings for
  "good enough".
- [x] Hook execution time profiling via `juju_dispatch` timing —
  the existing `hook_benchmark` tool reads `juju debug-log`,
  parses the `ran "<hook>" hook (<ms>ms)` lines, and reports
  per-hook count/min/max/avg with a threshold callout.  The skill
  documents how to exercise every hook with `juju_dispatch`
  before sampling (`update-status` on demand is the canonical
  example).
- [x] Comparison across charm versions (before/after optimisation)
  — the skill prescribes the baseline → optimise → candidate →
  delta-report pattern with a 10% / 100 ms noise guard, a
  Markdown table format for the write-up, and a durable
  `tests/perf/baseline.json` pattern for charms that want to guard
  against regressions in CI.  For workspaces, run the comparison
  per-charm (cross-charm timings don't add up cleanly).
- [x] Skill anchor tests: `test_charm_debug_skill_covers_diagnostic_workflow`
  pins the six read-only tools the skill sequences, the diagnostic
  vocabulary ("symptom", "likely cause", "next action", "pebble"),
  and the read-only advertisement.
  `test_benchmark_skill_covers_hook_benchmark_and_comparison`
  pins the `hook_benchmark` / `threshold_ms` / `data.timings`
  anchors, the before/after vocabulary (`baseline`, `candidate`,
  `delta`), and the hook names the skill prescribes exercising.

**Exit criteria:** Existing bundle management working. Migration skill handles
the three most common legacy patterns. `make check` passes throughout.

---

## Phase 34: Code Quality Skills for Charm Generation ✓

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

### 34.3 Low — Iterative CI Fix Loop ✓

Adapt the getsentry/skills `iterate-pr` pattern for Cantrip's deploy-test-debug
cycle — the autonomous loop that pushes fixes until `juju status` is healthy and
integration tests pass.

- [x] Formalise the existing watcher-driven retry loop into a skill with explicit
  exit conditions (max retries, ask-for-help escalation, stop if environment is
  broken) — new ``iterate-fix`` skill under
  ``src/cantrip/skills/iterate-fix/SKILL.md`` covers when to run (follow-up
  tasks whose titles start with ``[Red/Green retry]``, ``[Acceptance fix]``,
  ``Diagnose deployment failure:``, or ``[Watcher]``), the exit conditions
  (green status + originating suite passes, environment-only failure,
  retry budget exhausted, confirmed intermittent), and the escalation
  triggers (three attempts with no new hypothesis, shape-shifting
  failures, out-of-scope charm-library bugs, integration-test contracts
  needing renegotiation).
- [x] Structured feedback triage: categorise Juju status errors, Loki log errors,
  and test failures by severity before deciding which to fix first — the
  skill's *Triage* section routes each failure into Environment / Deployment
  / Workload / Test, then ranks within-bucket by blockers → crash-loops →
  concrete test-assertion messages → intermittents → warnings.
- [x] Track attempts per failure to avoid infinite loops on the same issue —
  the *Retry budgets* section defines a three-attempt ceiling per
  originating failure and lists the signals that the budget is spent
  (same pytest ID in two retry excerpts, same ``BlockedStatus`` message
  two attempts running, same Loki traceback signature after a fresh
  deploy).  Structured end-of-iteration block — ``[iterate-fix] attempt
  N/max: <outcome>`` — makes the attempt count legible to the next
  subagent.

### 34.4 Low — Skill Authoring and Scanning ✓

Use the getsentry/skills `skill-writer` and `skill-scanner` patterns to improve
Cantrip's own skill quality.

- [x] Adapt `skill-writer` workflow for creating new Cantrip skills: source
  synthesis, depth gates, evaluation prompts (EVAL.md) — new
  ``src/cantrip/skills/skill-writer/SKILL.md`` covers frontmatter
  requirements (``name`` == directory, ``description`` ≤120 chars and
  non-keyword-soup), body structure (intro + When-to-use + guidance +
  structured output + scope limit), depth gates (one subject per skill,
  split at 500+ lines), the ``EVAL.md`` scenario contract, source-material
  citation conventions, prompt-injection hygiene, and naming rules.
- [x] Adapt `skill-scanner` to audit Cantrip's existing skills for prompt injection
  risks, excessive scope, and instruction drift — new
  ``src/cantrip/skills/skill-scanner/SKILL.md`` documents the checks
  (prompt-injection phrases, unscoped authority, description drift,
  body length tiers, missing sections, bare external URLs, user-like
  text, frontmatter validity).  The *actual* audit is implemented in
  ``src/cantrip/agent/skill_scanner.py`` so it can run from pytest and
  from a future CLI; the module exposes ``scan_skill``, ``scan_all``,
  and ``format_findings`` plus a ``Finding`` dataclass.  Fenced code
  blocks and HTML comments are stripped before injection/URL checks so
  the scanner can describe the patterns it detects without triggering
  itself, and known reference-section headings (``## References``,
  ``## Resources``, ``## Further reading``, etc.) exempt URLs from the
  bare-URL check.
- [x] Run skill-scanner as a CI check when skills are added or modified —
  ``tests/unit/test_skill_scanner.py::TestBundledSkillsAreClean::test_every_bundled_skill_scans_clean``
  runs ``scan_all`` against ``src/cantrip/skills/`` and fails the build
  on any ``HIGH`` or ``MEDIUM`` finding.  19 scanner tests in total,
  covering the frontmatter checks (``name`` mismatch, empty
  ``description``, description-too-long), the four parametrised
  injection phrases, structural section detection, length tiers,
  URL-in-checks vs URL-in-references, and the formatter.  One bundled
  skill (``operational-readiness``) had an over-long description; it
  was shortened as part of this change so the new CI guard starts
  green.

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

## Phase 37: Upstream Ecosystem Catch-Up ✓

**Goal:** Review recent changes (last ~3 months) in the core charm ecosystem
libraries and adjust Cantrip's code generation, skills, system prompts, and
tool wrappers to stay current.

### 37.1 High — ops Documentation Corrections (from Dec 2024–Apr 2026 commits) ✓

Review of `canonical/operator` docs commits identified concrete patterns that
Cantrip's code generation, gold-standard charms, skills, and prompts need to
adopt. Items marked with a source commit hash. The audit cutoff and procedure
for re-running it live in `design/UPSTREAM_AUDIT.md`.

**Unit test generation (ops.testing / Scenario):**

- [x] Stop passing `meta=` to `testing.Context()` — Context now reads metadata
  automatically from `charmcraft.yaml`. Just use `testing.Context(MyCharm)`.
  Fix gold-standard charms that still use `meta=` (`tests/eval/charms/meilisearch/`,
  `tests/eval/charms/ntfy/`). (0d9e557)
- [x] Use `get_filesystem(ctx)` for testing pushed files instead of mount-based
  testing — simpler, no mount setup needed. Update skills and prompts. (0d9e557)
- [x] Use `dataclasses.replace()` for modifying State between events in
  multi-event test sequences — State objects are immutable. Update
  `scenario-tests` skill. (6ef2b00)
- [x] Adopt status testing pattern: test `collect_status` via
  `ctx.on.update_status()` with `layers=` and `service_statuses=` kwargs on
  `testing.Container`. Use `== testing.ActiveStatus()` equality assertions,
  not `isinstance`. (8520d82)
- [x] Use `pytest.mark.parametrize` for config validation tests in generated
  charms. (8520d82)
- [x] Use `pebble_ready` event (not `start`) for container file operation
  tests. (fe85d4a)

**Integration test generation (Jubilant):**

- [x] Call `.resolve()` on charm paths in the `charm` fixture. (e1692c4)
- [x] Pass path object directly: `juju.deploy(charm)` not
  `juju.deploy(f"./{charm}")`. (e1692c4)
- [x] Adopt the recommended comprehensive `juju` fixture from the migration
  guide: `keep_models` CLI option, `wait_timeout=10*60`, debug log dump on
  test failure — superseded by adopting `pytest-jubilant`, which bundles
  all of these. (1198db8)
- [x] Use `pytest-jubilant` in generated charms — it provides the `juju`
  fixture (with automatic model creation/teardown, `wait_timeout`, and debug
  log collection on failure) and the `charm` fixture (build + `.resolve()`)
  out of the box. Update the `jubilant-tests` skill, system prompt, and
  `conftest.py` generation to use `pytest-jubilant` instead of hand-rolling
  fixtures. Add `pytest-jubilant` to the generated `pyproject.toml` test
  dependencies.

**Charm code generation:**

- [x] Use `self.on["storage-name"].storage_attached` bracket notation for
  storage events (not attribute notation). Update system prompt. (6d20276)
- [x] Storage handling differs by charm type: K8s charms support only a single
  instance (`cache[0]`), machine charms get a list. Update guidance. (6d20276)
- [x] Get K8s workload mount path from
  `self.meta.containers["name"].mounts["storage"].location`. (6d20276)
- [x] Consider referencing `pathops` library for file operations in storage
  handling. (6d20276)
- [x] Use `pyproject.toml` for charm dependencies, not `requirements.txt`.
  Use `charmcraft init --profile kubernetes` as scaffolding base. (51cdf22)
- [x] Never pass sensitive data in CLI arguments — use environment variables
  or config files instead. Update security guidance in prompts. (06aba0a)
- [x] Secret identifiers are opaque strings — do not assume Xid format or
  20-character length. (a620797)
- [x] Secrets over CMR: only the offering application can grant access.
  Update relation-data-design skill. (1424fad)

**Observability:**

- [x] Loki label in Grafana dashboards: use `{charm="app-name"}` not
  `{juju_charm="app-name"}`. Update observability skill and any dashboard
  generation. (807be80)

**Reference material:**

- [x] Note Juju/Pebble/ops version matrix for `assumes` block guidance:
  Juju 3.6 → Pebble 1.19.2, Juju 4.0 → Pebble 1.26.0. (9392220)
- [x] Mention `jhack scenario snapshot` in debugging/testing skills as a way
  to capture live relation databags for regression tests. (34f12be)
- [x] Reference the new debugging how-to (`ops.Framework.breakpoint()`,
  `debugpy` setup, `juju debug-code`) in Cantrip's debugging guidance. (4bff400)

**Charmcraft 4.2 / Ubuntu 24.04 base (added Apr 2026):**

- [x] Update generated `charmcraft.yaml` and gold-standard charms to use
  `base: ubuntu@24.04` (was 22.04). Affects every charm template and any
  workload-version assumption derived from the base. (df731e5)
- [x] Emit an `assumes:` block in K8s charm templates with at least
  `juju >= 3.6` and `k8s-api`, matching the new Charmcraft 4.2 K8s profile.
  (df731e5)
- [x] Drop generated `tox.ini` files where pyproject `[dependency-groups]`
  cover the same surface — gold-standard charms already pyproject-only;
  Cantrip never *generates* `tox.ini` itself, it inherits whatever
  ``charmcraft init`` produces. (df731e5)

**pytest-jubilant 2.0 official (added Apr 2026):**

- [x] Pin integration deps in generated `pyproject.toml` to
  `jubilant>=1.8,<2` and `pytest-jubilant>=2,<3`. Strengthens the existing
  pytest-jubilant item with concrete version floors. (7331ddd)
- [x] Stop generating a hand-rolled `juju` fixture in `conftest.py` — the
  `pytest-jubilant` plugin registers a module-scoped one automatically with
  temp-model creation, teardown, and debug-log dump on failure. The `charm`
  fixture stays (build + `.resolve()`). Update the `jubilant-tests` skill
  and `conftest.py` generation. (7331ddd)
- [x] Use `tox -e integration -- --juju-dump-logs <dir>` for log capture in
  CI rather than ad-hoc debug-log printing in the fixture. (7331ddd)

**CI bootstrap alignment (added Apr 2026):**

- [x] `gh_repo_bootstrap`'s CI workflow stub (`.github/workflows/ci.yaml`)
  should match the new how-to: `permissions: {}` at top level,
  `actions/checkout@v6` with `persist-credentials: false`,
  `astral-sh/setup-uv@<v8 sha>`, `uv tool install tox --with tox-uv`,
  separate `lint`/`unit` jobs.  Integration job + Concierge + upload-artifact
  deferred to a follow-up since the bootstrap stub deliberately stays
  minimal (most bootstrapped charms add integration tests later). (bbaff04)
- [ ] Reference the new "set up CI" how-to from Cantrip's documentation
  guidance and from any `ci-workflow` skill — no `ci-workflow` skill
  exists yet; covered briefly in the `charmcraft` skill. Re-evaluate when
  Cantrip ships a dedicated CI skill. (bbaff04)

**COS Lite integration test pattern (added Apr 2026):**

- [x] Teach the `jubilant-tests` and `observability` skills the cross-model
  COS pattern: spin a second Juju via `pytest_jubilant.JujuFactory.get_juju
  (suffix="cos")`, deploy `cos-lite` (trust=True, allow ~10 min), and use
  `cos.offer("loki", endpoint="logging")` plus
  `juju.integrate(APP_NAME, f"{cos.model}.loki")` for the cross-model
  relation. (0df3895)
- [x] Document the Traefik-action-then-HTTP-API verification pattern (run
  `traefik/0` `show-proxied-endpoints`, parse the JSON, hit
  `/loki/api/v1/label/juju_application/values` to assert the charm's logs
  arrive). Useful template for any post-deploy COS smoke test. (0df3895)

### 37.2 High — Jubilant Changes ✓

- [x] Review `canonical/jubilant` changelog — new helpers, changed APIs,
  deprecations.  Audit cutoff `e9923ec` (release `2c389a6` / v1.8.0)
  recorded in `design/UPSTREAM_AUDIT.md`.  Notable: breaking change to
  `offer()` (respects `self.model`) doesn't affect Cantrip Python code;
  `add_cloud`/`update_cloud`/`model_constraints`/`destroy_model` kwargs
  surfaced as new methods Cantrip doesn't currently use.
- [x] Update Cantrip's Jubilant wrapper (`src/cantrip/juju/`) and integration
  test generation guidance — `generate_integration_tests` and
  `generate_load_test` were emitting `run_action(...)` (removed from
  Jubilant) and the legacy `wait(apps=…, status=…)` form; both are
  rewritten to use `juju.run(unit, action, params)` and
  `juju.wait(jubilant.all_active, …)`.  Generated `conftest.py` no
  longer rolls its own `juju` fixture (pytest-jubilant supplies one)
  and the `charm` fixture resolves the packed `.charm` honouring
  `CHARM_PATH`.  System prompt's integration-tests checklist updated
  to match.
- [x] Update the `jubilant-tests` skill if new Jubilant patterns are available
  — already done in §37.1 (pytest-jubilant 2.0, COS Lite cross-model
  pattern).  No further skill changes warranted.
- [x] Bump Cantrip's own Jubilant floor in `pyproject.toml` if needed —
  pinned to `jubilant>=1.8,<2` (was `>=1.8.0` with no ceiling) to lock
  in the API-stable 1.x major and avoid silent breakage on a future v2.

### 37.3 Medium — Concierge and Pebble Changes ✓

- [x] Review `canonical/concierge` for new features or changed deployment
  patterns.  Audit cutoff `aeda3bc` recorded in `design/UPSTREAM_AUDIT.md`.
  Repo moved from `jnsgruk/concierge` → `canonical/concierge`; always
  clone the canonical one now.  The behaviour fixes since Cantrip's last
  sweep (`0ddf24c` — scoped `/run/containerd` wipe; `86b1b21` — treat
  non-active snaps as installed; `6307920` — merge provider credentials)
  apply transparently to Cantrip's preflight.  Three features worth
  surfacing to users (not Cantrip code): `--dry-run` on
  `prepare`/`restore` (`bebf251`), per-provider `image-registry` block
  with `$VAR` interpolation (`d844183`), and `extra-bootstrap-args` on
  the `juju` section (`4d6726c`) — now documented in the `concierge`
  skill.
- [x] Review Pebble client changes (bundled with ops) — new layer options,
  check types, notice handling, file push/pull changes.  Very little churn
  in `ops/pebble.py` itself (`0ce8a0f`, `379d013` are transparent fixes).
  The live-impact changes are in `ops.testing` (Scenario): `61e606e`
  enables plain `breakpoint()` inside `testing.Context.run` (zero-deploy
  debug loop); `55c41eb` autoloads charmcraft extension metadata so
  12-factor PaaS charms Just Work in Scenario; `706b667` lets
  `State.get_relation` accept a relation object.  `5e752be` in `ops`
  proper now logs the total deferred-event count per hook — a backlog
  signal worth flagging during Workload-bucket triage.
- [x] Update Cantrip's Concierge integration (`src/cantrip/agent/preflight.py`)
  and Pebble layer generation guidance — no code changes to preflight
  warranted (the `_WARMUP_CONFIG` + `--preset` path still composes
  correctly against modern Concierge); the new Concierge surfaces land
  in the `concierge` skill rather than Cantrip's runtime.  Scenario
  changes land in the `scenario-tests` skill (breakpoint section, new
  `get_relation` ergonomic, charmcraft-extension autoload) and
  `iterate-fix` skill (breakpoint as the cheapest debug tool, deferred
  backlog as a Workload-bucket triage signal).

### 37.4 Medium — Charm Libraries (charmlibs) Changes ✓

- [x] Review recent releases of key charm libraries: `data-platform-libs`,
  `observability-libs`, `traefik-k8s`, `grafana-agent`, `loki-k8s`,
  `prometheus-k8s`, `catalogue-k8s`.  Audit recorded in
  `design/UPSTREAM_AUDIT.md`.  None of these have moved to PyPI —
  they still require `charmcraft fetch-libs`.
- [x] Check for new PyPI-published versions that replace `charmcraft fetch-libs`
  — the `canonical/charmlibs` monorepo publishes `charmlibs-pathops`,
  `charmlibs-{apt,snap,passwd,sysctl,systemd}` (replacing
  `operator_libs_linux` submodules), `charmlibs-nginx-k8s`, and the
  `charmlibs-interfaces-*` family (TLS, certificate-transfer, OTLP,
  MCP, SLOTH, k8s-backup-target, gateway-metadata).  `cosl` publishes
  COS topology + logging utilities.  **Major correction:** Cantrip's
  previous LIB001 PyPI map named ghosts (`loki-k8s-lib`,
  `traefik-k8s-lib`, `data-platform-libs`, `grafana-k8s-lib` etc. do
  not exist on PyPI).  Both Python (`src/charmlint/rules/libraries.py`)
  and Rust (`src/charmlint-rs/src/rules.rs`) rewrites land accurate
  mappings and split `operator_libs_linux` by submodule.  LIB001's
  message now includes the new import path so the user can port
  without guessing; LIB002's message is reframed as "no PyPI
  equivalent yet; continue using `charmcraft fetch-libs`".
- [x] Update the `observability` and `relation-data-design` skills if
  integration patterns have changed — `observability` skill's
  "fetch libraries from PyPI first" bullet rewritten to enumerate
  what's actually on PyPI and what still needs fetch-libs.
- [x] Update system prompt guidance on which libraries to use and how —
  `### Libraries` block rewritten to name the `charmlibs-*` /
  `charmlibs-interfaces-*` / `cosl` packages explicitly and flag the
  Charmhub-only set (loki, grafana, prometheus, traefik, tempo,
  catalogue, observability-libs, data-platform-libs).
- [x] Skill coverage table for PyPI libraries added to the `charmcraft`
  skill (`### Libraries on PyPI (charmlibs-*)` + `### Libraries that
  still need charmcraft fetch-libs`).  Ingress skill's fetch-lib
  example gains an explicit "traefik_k8s is not on PyPI" note.

### 37.5 Low — Charmcraft and Rockcraft Changes ✓

- [x] Review `canonical/charmcraft` changelog — new `charmcraft.yaml` fields,
  changed pack behaviour, new commands.  Audited against release v4.2.1
  (cutoff `fae9862`, recorded in `design/UPSTREAM_AUDIT.md`).  **Real bug
  caught**: ``CharmcraftInitTool`` didn't set
  ``CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS`` for the four
  still-experimental profiles (fastapi, go, express, spring-boot), so
  those inits would have failed at `charmcraft pack` time.  Fixed by
  gating on a new ``_CHARMCRAFT_EXPERIMENTAL_PROFILES`` frozenset.
  Other findings surfaced as skill/prompt updates — HTTP proxy /
  OpenID Connect integrations in 12-factor, `src/workload.py` in
  K8s/machine scaffolding, the `simple` → `kubernetes` profile
  rename (already compliant), and the Ubuntu 25.10 stable / 26.04
  devel base picture.
- [x] Review `canonical/rockcraft` changelog — new `rockcraft.yaml`
  features, changed base images, new extensions.  Audited against
  release v1.18.0 (cutoff `e03ed9f`).  **Second real bug**:
  ``RockcraftInitTool`` only set
  ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS`` for a subset of profiles
  — but every framework extension in rockcraft (including Flask and
  Django) is still flagged experimental upstream, so Flask / Django /
  Spring Boot inits would have errored out.  Fixed by setting the
  flag unconditionally (matching `RockcraftPackTool`).  Notable new
  surface: Flask/Django/FastAPI extensions default to a **bare** base
  (`3fba20c`) — smaller rocks, no shell / apt; `entrypoint-command`
  field available (`0f919f9`); uv/poetry plugins disabled on 25.10+
  until usrmerge-ready.
- [x] Update charm and rock template generation if schemas have changed
  — ``twelve-factor`` skill table rewritten to reflect the per-tool
  experimental status (Flask/Django stable in charmcraft, experimental
  in rockcraft; FastAPI / Go / Express / Spring Boot experimental
  everywhere).  HTTP proxy and OpenID Connect sections added with
  ``charmcraft.yaml`` snippets.  Bare-base note added to the rockcraft
  step of the workflow.  ``charmcraft`` skill's profile list expanded
  to name all six profiles explicitly and flag which need the
  experimental env var; workload module pattern documented.
  ``rockcraft.py`` + ``charm.py`` tests updated; 19 rockcraft +
  55 charm-tools tests still pass.

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

## Phase 41: Claude Provider Quality and Multi-Provider Parity ✓

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
- [~] Consider padding the system prompt to meet the minimum threshold when
  it is close (e.g. adding the skills index or context summary) — deferred.
  The current system prompt already exceeds both the Sonnet (1024) and
  Opus (2048) cache thresholds in every tested configuration, so synthetic
  padding would be dead weight.  Revisit only if a provider tightens the
  threshold or the system prompt shrinks below it.

### 41.4 Claude model ID updates ✅

- [x] The `_CONTEXT_WINDOWS` map in `claude.py` only lists two model IDs;
  update it as new Claude models are released (Opus 4.6 is listed with its
  dated ID, but Haiku 4.5 is missing)
- [x] Add Haiku 4.5 (`claude-haiku-4-5-20251001`) to the context window map
  (context window: 200k tokens)
- [x] Add Sonnet 4.6 (`claude-sonnet-4-6`) and Opus 4.7 (`claude-opus-4-7`)
  to the context window map and light-model routing (Sonnet 4.6 → Haiku 4.5;
  Opus 4.7 → Sonnet 4.6)
- [~] Consider a fallback that queries the API for context window metadata
  rather than hard-coding model-specific values — deferred.  Anthropic's
  ``/v1/messages`` endpoint doesn't advertise context-window metadata in
  the response, and ``/v1/models`` returns per-model info that we already
  track in ``_CONTEXT_WINDOWS``.  Adding a bootstrap fetch would replace
  one hard-coded table with another plus a network round-trip; not worth
  it until a model ships whose context window we don't know at build
  time.

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

### 41.6 Conversation loop cost display ✅

- [x] During live testing, multi-turn conversations with tool use consumed
  significant tokens (350+ prompt tokens per turn, growing with history) but
  the CLI mode provides no visibility into cumulative cost — addressed by
  the items below, which both landed during Phase 31.4's ``/cost`` rollout
  and Phase 27.1's cache-rate surfacing.
- [x] Add a periodic cost summary to the CLI banner or a `/cost` command
  that shows total tokens, estimated cost, and cache hit rate — ``/cost``
  ships in both the CLI REPL (``cli._print_cost``) and the shared slash
  dispatcher (``format_cost`` in ``agent.slash_commands``, surfaced as a
  chat follow-up in TUI + Web).  Output includes per-model token counts,
  request counts, estimated USD, and the Claude cache read/write rate
  when non-zero.
- [x] The TUI model bar already shows some usage info — verify it updates
  correctly with Claude's usage metrics including cache fields — the
  reactive pipeline (``CantripAgent.cache_creation_tokens`` /
  ``cache_read_tokens`` → ``_update_model_info`` → ``ModelInfoBar``) is
  wired and now regression-tested by
  ``test_model_info_bar_shows_cache_hit_rate`` (200 write + 800 read →
  ``cache: 80% hit`` rendered on the second info-bar line).

### 41.7 Compaction effectiveness monitoring ✅

- [x] During testing, compaction with Haiku only reduced a 5-message
  conversation from 1587 to 1518 tokens (4% reduction) when the content
  was repetitive — the summary was nearly as long as the original
- [x] Add a post-compaction metric: log the compression ratio
  (tokens_after / tokens_before) so operators can monitor effectiveness
- [x] If compression ratio exceeds 0.9 (less than 10% reduction), log a
  warning suggesting the conversation may need manual reset
- [x] This feeds into Phase 40 (compaction safety)

### 41.8 Streaming chunk granularity ✅ (deferred)

- [x] The Claude streaming test revealed that very short responses may arrive
  as a single chunk rather than token-by-token streaming, which means the
  spinner-to-streaming transition in the CLI may appear to jump —
  acknowledged; the provider streams on whatever granularity the API
  delivers and we don't want to hold back chunks for cosmetic smoothing.
- [~] Consider adding a brief delay or transition indicator in the CLI/TUI
  when switching from spinner to streamed output — deferred.  The TUI
  already flips ``⟳ Thinking...`` → ``⟳ Streaming...`` on the first
  chunk (Phase 31.2), which is sufficient visual signal; adding an
  artificial delay would only make short responses feel slower.
- [x] This is cosmetic — low priority — accurate self-assessment;
  closing the subphase.

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

## Phase 42: GitHub Integration ✓

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
- [x] Optionally configure basic repository settings: default branch protection,
  issue templates, CI workflow stub — new ``GhRepoBootstrapTool``
  (``gh_repo_bootstrap``) applies each step independently.  Branch
  protection is a ``gh api -X PUT
  repos/{slug}/branches/{branch}/protection`` call with a conservative
  payload (one required approving review, force-pushes and deletions
  disabled, required-status-checks left null until CI has had a chance
  to land green).  Issue templates are markdown stubs under
  ``.github/ISSUE_TEMPLATE/`` (``bug_report.md`` +
  ``feature_request.md``); the CI workflow stub lives at
  ``.github/workflows/ci.yaml`` and runs ``uv`` / ``ruff`` / ``pytest
  tests/unit`` on push + PR.  Existing files are skipped rather than
  overwritten; the repo slug is auto-detected via ``gh repo view`` when
  ``repo=`` is omitted.  Failures surface as warnings on the result
  rather than blowing up the caller (``test_protection_failure_is_warning``
  proves the branch-protection API failing doesn't lose the local
  writes).  Ten unit tests in ``TestGhRepoBootstrapTool`` cover auth
  gating, selective steps, slug auto-detection, and the custom-branch
  path.

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

## Phase 46: User-Configurable Hooks ✓

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

## Phase 47: Best-of-N Multi-Model Racing for High-Value Tasks ✓

**Goal:** For tasks with objective success criteria (BUILD, DESIGN,
RED/GREEN), optionally run N models in parallel and pick the winner. Cursor
`/best-of-n` and Windsurf Arena Mode shipped this pattern in the window, and
charm building is an unusually good fit — success is measurable via unit tests,
integration tests, `charmlint` output, and operational-readiness score. Gated
by cost and off by default; opt-in per task category.

### 47.1 High — Scoring rubric ✅

- [x] Define a scoring function that combines: unit test pass count,
  integration test pass count, `charmlint` violations (weighted by severity),
  operational-readiness score delta, and diff size (penalising large
  unnecessary changes) — ``cantrip.agent.race.compute_score`` composes
  four subscores (charmlint 30 %, readiness 30 %, tests 25 %, diff
  15 %) with exponential-decay weighting on charmlint severity
- [x] Scoring runs against each candidate's worktree (depends on Phase 44)
  — ``score_candidate`` runs ``charmlint`` + ``operational_readiness``
  + ``git diff --numstat`` against the worktree; measurement order
  keeps the uncommitted readiness report out of the diff count
- [x] Scores are comparable across candidates even when tests have different
  counts — ``_score_tests`` normalises to ``pass / total`` in ``[0, 1]``;
  the other signals are naturally bounded, so pool totals are directly
  comparable.  Integration test counts are a follow-up (the baseline
  single-model path doesn't surface them yet)
- [x] Unit tests cover tie-breaking, empty test suites, and degenerate
  candidates (build failure scored as worst) — ``tests/unit/test_race.py``
  covers tie-breaking on diff size, empty test suites, failed / no-op
  / crashed candidates, and readiness-unavailable charms (44 tests)

### 47.2 High — Parallel execution harness ✅

- [x] A `RaceCoordinator` in `src/cantrip/agent/race.py` spawns N candidate
  subagents against the same task, each in its own worktree and with a
  different `provider`/`model` pairing — coordinator uses
  ``asyncio.gather`` over a caller-supplied ``SubagentFactory`` so the
  race layer does not need to know about tool construction.  Worktree
  keys are composite (``{task_id}__{candidate_id}``) so candidates for
  the same task don't collide
- [x] Candidates share the same system prompt, task, and scoped tool access;
  they differ only by model — the factory receives a ``CandidateSpec``
  (carrying the provider pair) and the worktree path; the executor
  wires the same ``SubagentContext`` + tool list for every candidate
  when it adopts this harness
- [~] Cancellation: once a candidate achieves a perfect score, the coordinator
  cancels the others (opt-in — some users want to see all results) —
  ``CandidateScore.is_perfect`` and ``RaceConfig.cancel_on_perfect``
  are in place but early cancellation is not yet implemented; the
  coordinator waits for all candidates today.  Acceptable for the
  initial rubric-validation pass; revisit once races are actually
  running

### 47.3 Medium — Result selection and commit ✅

- [x] After all candidates finish (or one wins early), the coordinator picks
  the highest-scored candidate's worktree and merges it into the charm branch
  via Phase 44.2 — ``BackgroundExecutor._execute_race`` calls
  ``_merge_worktree`` on the winner's ``WorktreeHandle``; merge failures
  block the parent task and preserve the branch for manual resolution,
  matching the single-subagent merge-error path
- [x] Losing candidates' worktrees are torn down via Phase 44.3 —
  ``RaceCoordinator._release_losers`` calls the allocator with
  ``keep_branch=False`` for every non-winning candidate
- [x] Transcript records all candidates' output per Phase 14.2 so reviewers
  can see the losers too — the executor's race subagent factory builds
  each candidate with a shadow task whose id is
  ``{parent_id}__{candidate_id}``, so every candidate's
  ``subagent_messages`` land in their own partition; a ``race_candidate``
  event per candidate records the composite transcript id for lookup

### 47.4 Medium — Cost guardrails ✅

- [x] Configuration gates Best-of-N per category: `race.enable = ["BUILD",
  "DESIGN"]`, `race.max_candidates = 3`, `race.budget_tokens = 500_000`
  — ``RaceConfig`` models all three knobs; ``should_race`` gates entry
  and ``clamp_candidates`` enforces the max
- [x] Pre-race cost estimate surfaced as a CONFIRM task when the estimated
  cost exceeds a threshold — ``RaceConfig.race_gate`` classifies the
  ``estimate_race_tokens`` output into ``RACE`` / ``CONFIRM`` /
  ``DOWNGRADE`` against ``confirm_threshold_tokens`` and
  ``budget_tokens``.  ``BackgroundExecutor._dispatch_race_gate`` reads
  the classification and, on ``CONFIRM``, emits a
  ``race-confirm-<task-id>`` task and blocks the parent; the TUI
  recognises the new prefix and ``CantripAgent.handle_race_confirmation``
  flips ``AgentTask.race_decision`` so re-entry races or downgrades
  based on the user's answer
- [x] Budget exhaustion during the race downgrades gracefully to single-model
  — the gate returns ``DOWNGRADE`` when the estimate exceeds
  ``budget_tokens`` (or when the user declined the CONFIRM), and the
  executor falls through to the single-subagent path rather than
  failing.  A ``race_downgraded`` event is recorded so the reason
  (``over_budget`` / ``user_declined``) is visible in the session
  transcript.  Mid-flight budget accounting is deferred until
  streaming-usage aggregation lands in Phase 41.6

### 47.5 Low — Blind A/B arena mode ✅

- [x] `/arena` slash command runs two candidates blind and asks the user to
  pick the winner for a one-off preference capture, mirroring Windsurf Arena
  — new ``cantrip.agent.arena`` module runs ``provider_a`` and
  ``provider_b`` concurrently via ``asyncio.gather``, shuffles the
  two responses into labels ``A`` and ``B``, and returns an
  ``ArenaSession``.  ``/arena <prompt>`` in the shared slash
  dispatcher emits a ``SlashResult`` with a follow-up that awaits
  ``CantripAgent.begin_arena``; the follow-up's text is the blind
  A/B block rendered by ``arena.format_blind_arena``.  TUI, CLI,
  and Web intercept pending picks before routing a reply to the LLM
  via ``agent.active_arena`` + ``handle_arena_pick``; recognised
  replies (``A``, ``B``, ``tie``, ``skip`` and common synonyms)
  consume the session and render ``arena.format_reveal`` to unmask
  the models.  Unrecognised replies fall through so the user is
  not locked out of normal chat
- [x] Preference outcomes feed into memory (Phase 43) as facts about which
  models the user prefers for which task categories —
  ``arena.record_preference`` writes a ``kind="fact"`` entry at
  ``scope="global"`` with ``source="arena"`` and tags
  ``["arena", "model-preference"]``.  Directional picks record
  "User preferred X over Y"; ties record "User rated X and Y as
  equivalent"; every entry includes a 200-character prompt excerpt
  so the preference is attributable to a specific ask.  Title is
  ``arena-preference-<8-hex>`` so repeated arenas produce
  disambiguated entries that ``/memory`` can list and ``/forget``
  can remove

### 47.6 Low — Publish user-facing docs for racing ✅

- [x] Once 47.4 and 47.5 land a user-facing surface (config keys,
  CONFIRM prompts, ``/arena``), add a docs page covering Best-of-N
  to ``docs/docs/`` — either a new ``explanation-race.html`` or a
  section in ``reference-cli.html``.  Cover the scoring rubric
  (charmlint 30 %, readiness 30 %, tests 25 %, diff 15 %),
  ``RaceConfig.enabled_categories``, ``max_candidates``,
  ``budget_tokens``, and how to interpret the ``race_candidate``
  events in the transcript — ``docs/docs/explanation-race.html``
  covers the rubric (per-signal decay, viability short-circuit,
  tie-breaking), every ``RaceConfig`` knob, the three-way
  RACE/CONFIRM/DOWNGRADE gate, the full ``/arena`` pick grammar,
  and every ``race_*`` transcript event including how to join a
  loser's ``subagent_messages`` partition by
  ``transcript_task_id``.  A callout warns that ``RaceConfig`` has
  no CLI/env surface yet; the Limits section tracks the remaining
  follow-ups (no early cancellation, static baseline estimate,
  unit-only test scoring).  Linked from the index card grid, from
  every explanation page's sidebar, and from the Arena section of
  ``reference-cli.html``.

**Exit criteria:** Best-of-N races run for configured categories, score by
measurable outcomes, merge the winner via the worktree merge path, and respect
cost budgets. Blind arena mode is available behind `/arena`. User-facing
docs exist once there is a user-facing surface. `make check` passes throughout.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Scoring rubric (47.1) | Phase 24 charmlint, Phase 19 readiness score | Combines existing signals |
| Parallel execution (47.2) | Phase 44 worktree isolation | Each candidate needs its own worktree |
| Selection and commit (47.3) | 47.2, Phase 44.2 merge | Uses the worktree merge strategy |
| Cost guardrails (47.4) | Phase 41.6 cost display | Shares the cost-accounting plumbing |
| Arena mode (47.5) | 47.2, Phase 43 memory | Writes user preference into memory |

---

## Phase 48: Multimodal Observability Diagnostics ✓
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

### 48.5 Low — Headless browser integration (deferred)

- [ ] Optional `workload_screenshot` tool that spawns headless Chromium
  against a workload endpoint discovered by Phase 17.3 and returns the
  rendered page as PNG.  **Deferred** — Playwright / pyppeteer pulls
  in a Chromium binary the size of the rest of Cantrip's runtime
  combined, and 48.2 / 48.3 / 48.4 already cover the operationally
  important visual surfaces (Grafana panels, Tempo waterfalls, Juju
  status trees).  Workload web UIs are the long tail; the cost-benefit
  isn't there until a charm author asks for it.  Phase 17.3's
  `workload_endpoint_test` already exercises HTTP endpoints
  functionally without screenshots.  Re-open when (a) a concrete
  case shows the agent needs to *see* a workload UI to debug it, or
  (b) Playwright lands as a transitive dep elsewhere.

**Exit criteria:** Providers support image input, the observability tools
return diagnostically useful PNGs alongside text captions, and subagents can
reason about Grafana/Tempo/Juju-status visually. `make check` passes
throughout.  **Met:** 48.1–48.4 ship; 48.5 is explicitly deferred above.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Provider image input (48.1) | None | SDK-level feature already available |
| Grafana screenshot (48.2) | Phase 22 cross-model COS | Uses existing Grafana config |
| Tempo waterfall (48.3) | Phase 2.2 COS integration | Reads traces from Tempo |
| Juju status render (48.4) | Phase 0.3 Juju integration | Renders existing status output |
| Headless browser (48.5) | Phase 17.3 endpoint testing | Optional; large dependency footprint |

---

## Phase 49: Subprocess Sandboxing Hardening ✓
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
`sandbox-exec`. `make check` passes throughout.  **Met:** 49.1 / 49.2 /
49.4 / 49.5 ship; 49.3 is explicitly deferred above (the namespace-only
sandbox covers the exit clause's "fall back" fallback).

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| PID/mount namespaces (49.1) | Phase 25.2 shell-injection fix | Builds on cleaned-up command handling |
| Deny-rule hardening (49.2) | 49.1 | Extends command inspection |
| Syscall allowlists (49.3) | 49.1 | Layered on the namespace sandbox |
| macOS hardening (49.4) | 49.1 | Parallel platform implementation |
| Observability (49.5) | Phase 14.1 transcript | Emits sandbox events |

---

## Phase 50: Skills Ecosystem Interop ✓
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

## Phase 52: Step-Level Durable Execution for Subagent Loops ✓
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

## Phase 53: Organisation Cleanup — Prompts, Planner, Dev Docs ✓

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

### 53.1 High — Extract planner prompts to `.md.j2` templates ✅

- [x] Create `src/cantrip/agent/prompts/planning/` with three templates:
  `full.md.j2` (was `_PLANNING_PROMPT`), `design_to_build.md.j2`, and
  `day2_to_build.md.j2`
- [x] Add a small loader next to `prompts/system.py` that lazy-loads
  these templates with the same `StrictUndefined` + sanitisation shape
  as the system prompt
- [x] Replace the Python constants in `planner.py` with calls into the
  loader; keep the existing `{categories}` / `{context_block}` variable
  substitution semantics
- [x] Unit tests verify the rendered output is byte-identical to the
  pre-extraction prompts for a fixed set of inputs (freezes behaviour)
  — covered by ``tests/unit/test_planner_prompt_snapshots.py`` and
  ``tests/unit/planner/test_prompts.py``

### 53.2 High — Extract task-description guidance to templates ✅

- [x] Create `src/cantrip/agent/prompts/tasks/` with one `.md.j2` per
  deterministic task generator that currently builds a multi-line
  description: `sprint_build.md.j2`, `sprint_deploy.md.j2`,
  `fast_path_design.md.j2`, `one_shot_build.md.j2`, `improvement_*`,
  `operability_*`, `research_*`, `day2_*` — 28 templates in total
- [x] Add a helper `render(name, **vars)` that picks the right
  template and renders it with the planner's per-task context
  (workload, ubuntu version, profile, design text, …).  Named
  ``render`` rather than ``render_task_description`` so the call site
  reads ``task_prompts.render("sprint_build", …)``
- [x] `AgentTask.description` is populated from the helper; no
  multi-line per-task f-strings remain in the planner (the two remaining
  inline descriptions — "Present the design proposal for user approval."
  and the improvement confirm blurb — are single short sentences,
  not multi-line guidance)
- [x] Snapshot tests lock in the rendered text for a canonical input
  set — protects against accidental drift during the extraction

### 53.3 Medium — Split `planner.py` along the deterministic / LLM seam ✅

- [x] Introduce `src/cantrip/agent/planner/` package; move the
  deterministic generators into `planner/deterministic.py` and the
  LLM-driven code path (`TaskPlanner`, prompt loaders, JSON parser,
  dependency validator) into `planner/llm.py`
- [x] Keep `planner/__init__.py` re-exports stable so existing
  `from cantrip.agent.planner import …` imports do not break
- [~] Classifier helpers (`is_fast_path`, `is_sprint`, `is_improvement`,
  `is_one_shot_build`) stayed in ``planner/deterministic.py`` rather
  than moving to ``planner/routing.py`` — the roadmap offered this as
  an "or" option.  They classify against a ``PlanningContext`` and
  are only used by the deterministic path, so they live next to their
  caller.  The top-level ``agent/routing.py`` (which does something
  different — task → subagent dispatch) is left untouched
- [x] No functional change — behaviour is covered by the existing
  planner unit tests plus the snapshot tests from 53.1 and 53.2

### 53.4 Low — Rename `tools/registry.py` → `tools/oci_registry.py` ✅

- [x] `src/cantrip/agent/tools/registry.py` currently holds Docker
  Hub / OCI image-search tools, not a tool-registration mechanism —
  renamed to `oci_registry.py` to match its contents
- [x] Update the single import in `tools/__init__.py`
- [x] Grep-verify no other code references the old module name —
  only historical mentions in ``CHANGELOG.md`` and this roadmap remain

### 53.5 Medium — Add dev design docs for the three subsystems ✅

- [x] `design/TOOLS.md` — the `Tool` ABC contract, the `build_tools()`
  factory pattern, how to add and remove a tool, where tool schemas
  come from, conventions for naming and file layout, how tools
  interact with `PathAwareTool` and the virtual-file store
- [x] `design/SKILLS.md` — `SKILL.md` discovery via `SkillsIndex`,
  frontmatter schema, lazy-load-on-demand flow, the skill index injected
  into the system prompt, interop with Phase 50 standard-format skills
- [x] `design/PROMPTS.md` — the prompt layering (system full / system
  compact / subagent / planning / task descriptions / skills loaded on
  demand), Jinja2 conventions (`StrictUndefined`, trailing newlines),
  the `_JINJA_SYNTAX` sanitisation regex and why it exists, extension
  points for new prompt types
- [x] Cross-link the three docs from `design/PLAN.md` so the
  architecture index points at them — new "Related Design Documents"
  section at the top of ``PLAN.md`` links ``AGENT``, ``TOOLS``,
  ``SKILLS``, ``PROMPTS``, ``UI``, and ``TERRAFORM``

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

## Phase 54: Reverse-Engineer `docs/docs/` from HTML to Markdown ✓
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

## Phase 55: Patterns from awesome-copilot — Investigation ✓
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
- [x] **Implementation shipped** (after the deferred follow-up was
  unblocked by Phase 80.1–80.5's defence-in-depth stack).
  ``src/cantrip/agent/goal_budget.py`` ships ``GoalBudget``
  (iteration / prompt / completion caps + ``started_at``),
  ``measure_usage`` / ``check_budget`` (query the store for
  usage-since and return a block reason), and ``from_cli_args``
  that reads ``--max-iterations`` / ``--max-tokens`` with
  ``CANTRIP_MAX_ITERATIONS`` / ``CANTRIP_MAX_TOKENS`` env-var
  fallback.  ``started_at`` uses SQLite's ``datetime('now')``
  shape (``%Y-%m-%d %H:%M:%S`` UTC) so the ``WHERE timestamp
  >= ?`` comparison against the ``token_usage`` table works
  lexicographically — mixing Python's ``isoformat`` with
  SQLite's space-separated format compares wrong.
  ``AgentState.goal_budget`` carries the optional dataclass.
  ``BackgroundExecutor`` gate ``_check_goal_budget`` fires
  before each spawn in ``_run_loop``; a tripped budget blocks
  the task with ``Goal budget exceeded: …`` and invokes the
  new ``on_budget_exceeded`` callback, which the core wires to
  a ``GOAL_BUDGET_EXCEEDED`` UI event plus a SYSTEM chat
  message so the stop lands in the transcript.  ``/budget``
  slash command shows the ``used / cap`` summary, raises any
  individual cap in place, and clears the budget entirely with
  ``--clear``; raising a cap moves every budget-blocked task
  back to ``pending`` so the executor picks them up on the
  next poll.  CLI + env wiring threaded through ``run_cli``,
  ``CantripApp.__init__``, and ``_run_web``.
  ``tests/unit/test_goal_budget.py`` (24 tests), plus 6 in
  ``tests/unit/executor/test_budget.py`` covering the gate-
  trips / raise-clears / store-less paths end-to-end, plus 8
  in ``tests/unit/test_slash_commands.py::TestBudget`` for
  the slash surface including the unblock-on-raise
  invariant.

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

## Phase 57: Test-Suite Cleanup — Organisation, Coverage, Warnings ✓

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

### 57.5 Medium — TUI screen Pilot tests ✓

Textual's ``Pilot`` lets tests drive an app programmatically.  Three
screens were under 40%:

- [x] ``tui/screens/relation.py`` (0% → 99%) — new
  ``tests/unit/test_relation_screen.py`` drives the mount → fetch →
  render pipeline with ``subprocess.run`` mocked.  Covers the
  matching-relation render (with databags + asymmetry section),
  no-match / symmetric / subprocess-error / unparseable-JSON branches,
  and the ``action_refresh`` re-issue path, plus the pure
  ``_fetch_data_blocking`` helper (five branches)
- [x] ``tui/screens/questions.py`` (30% → 100%) — Pilot tests added
  to ``tests/unit/test_questions_screen.py`` for suggestion clicks,
  free-form submission (ignoring whitespace-only), skip/previous
  buttons, escape cancel, and dismiss-on-last-question.  Buttons are
  driven via ``Button.press()`` because ``pilot.click`` on
  modal-overlay widgets didn't register
- [x] ``tui/app.py`` (42% → 66%) — targeted branches in a new
  ``tests/unit/test_tui_actions.py``: F6/F7/F8/F9/Ctrl-F bindings,
  every bus handler (memory written/recalled, status bar, task
  updated, watcher event), worker-completion branches for
  ``/feelings`` and MCP marketplace (success / cancelled / error /
  non-terminal), every branch of ``_handle_bootstrap_response`` /
  ``_handle_push_response`` / ``_handle_triage_response`` (including
  unrelated-message returns-false), the confirmation presenters,
  ``action_toggle_watcher`` running / stopped / no-agent,
  ``_refresh_subagent_status_bar``, ``on_relation_line_selected``,
  and ``action_quit`` with services running.  ``call_from_thread`` is
  patched with a synchronous passthrough so in-test direct invocation
  of bus handlers works

### 57.6 Medium — Core-agent branch coverage ✓

``src/cantrip/agent/core.py`` was at 62%; now at 87% with
``test_agent_github.py``, ``test_agent_confirmations.py``, and
``test_agent_lifecycle.py`` added alongside the existing
``test_agent.py``.

- [x] Targeted unit tests with ``FakeProvider`` streaming responses —
  the existing ``test_agent.py`` streaming tests stand; this phase
  layered 67 new tests that mock git/gh/planner calls rather than
  streaming
- [x] Mocked ``gh`` tool results for the triage helpers —
  ``test_agent_github.py`` patches every ``cantrip.agent.core.*`` name
  imported from ``git_branch`` / ``github_issues`` so no ``gh``
  subprocess runs: ``handle_push_confirmation`` / ``handle_pr_creation``
  / ``handle_repo_bootstrap`` / ``handle_triage_confirmation`` /
  ``create_pr_fix_tasks`` / ``comment_on_issue`` /
  ``_create_feature_branch`` / ``check_upstream`` /
  ``check_pr_feedback`` / ``should_offer_bootstrap``, plus the
  ``start_issue_triage`` / ``stop_issue_triage`` / ``retriage_issues``
  worker lifecycle
- [x] Target 80% on this one file — **87% achieved** (119 tests; new
  files cover design/day-2 confirmations, executor start/stop,
  build_resume_summary, load_state error + restoration branches, MCP
  registry plumbing, and the ``_on_mcp_elicitation`` bridge)

### 57.7 Medium — Split oversized unit-test files

Four unit-test files top 1500 lines:

- [x] ``tests/unit/test_executor.py`` (1972 lines) — split by
  concern into ``tests/unit/executor/`` mirroring the
  ``tests/unit/charmlint/`` layout: ``test_lifecycle.py`` (start /
  stop / pause / resume / graceful shutdown), ``test_execution.py``
  (build_context, execute_task, handle_confirm, category timeouts),
  ``test_run_loop.py`` (run loop, callbacks, concurrency),
  ``test_followup.py`` (followup tasks, design handoff, noop
  detection), ``test_git.py`` (uncommitted/precheck/snapshot/revert),
  and ``test_errors.py`` (exit-state / error-resilience / usage
  recording).  Shared helpers (``_make_tool``, ``_make_executor``)
  moved to ``tests/unit/executor/conftest.py``.  All 107 tests still
  pass; each file ≤478 lines
- [x] ``tests/unit/test_planner.py`` (1705 lines) — split by
  concern into ``tests/unit/planner/``: ``test_parsing.py`` (JSON
  extraction + task-list / merge helpers), ``test_paths.py`` (fast /
  sprint / one-shot / improvement path detection plus their
  deterministic plan helpers), ``test_planner.py`` (TaskPlanner.plan /
  replan, unique IDs, PlanningContext fields), ``test_prompts.py``
  (prompt builders), ``test_design.py`` (PlanFromDesign + red/green
  build sequence), ``test_improvement.py`` (PlanImprovementFixes),
  ``test_day2.py`` (day-2 ops phase / FindDay2Anchor /
  PlanFromDay2Findings), ``test_operability.py`` (operability
  assessment + fixes), and ``test_tool.py`` (PlanTasksTool).  All
  152 tests still pass; each file ≤283 lines
- [x] ``tests/unit/test_subagent.py`` (1621 lines) — split by
  concern into ``tests/unit/subagent/``: ``test_context.py``
  (SubagentContext / SubagentResult / exit signalling),
  ``test_helpers.py`` (filter / select-provider / tools-for-llm /
  parse-exit-state / truncate), ``test_prompt.py`` (prompt builder,
  task instruction, research / design / red-green / commit /
  self-verification / demo guidance), ``test_run.py`` (Subagent.run
  / retry / tool execution / max rounds / phase reporting),
  ``test_concurrency.py``, ``test_throttle.py``, and
  ``test_allowlists.py`` (per-category tool allowlists).  Shared
  helpers (``_make_tool``, ``_make_context``) moved to
  ``tests/unit/subagent/conftest.py``.  All 120 tests still pass;
  each file ≤419 lines
- [x] ``tests/unit/test_tools.py`` (1739 lines) — folded per-tool:
  the file-tool tests (TestReadFileTool / TestWriteFileTool /
  TestListDirectoryTool / TestEditFileTool, ~16 tests) were
  duplicates of ``test_file_tools.py`` and dropped, with the two
  unique cases (sibling-prefix path attack;
  ``test_write_to_read_only_directory``) lifted into
  ``test_file_tools.py``.  Testing helpers (TestBuildPytestTarget,
  TestParseCoverageTotal) folded into ``test_testing_tools.py``.
  Concierge / provisioning tests moved to a new
  ``test_environment_tools.py``.  Charm-tool tests split into a
  ``tests/unit/charm_tools/`` subdirectory:
  ``test_analyse_framework.py``, ``test_charmcraft_init.py``
  (gitignore / ops-tracing / paas requirements / pre-commit
  injection), ``test_charmcraft_pack.py``, and ``test_inject.py``
  (coverage threshold + GitHub workflows).  All 160 tests still
  pass; each file ≤546 lines.  Phase 57.7 complete

Each target file ≤600 lines.

### 57.8 Low — Reorganise quickpack unit tests ✓

- [x] Moved ``tests/unit/test_quickpack.py`` (977 lines, 83 tests)
  and ``tests/unit/test_quickpack_comparison.py`` into
  ``tests/unit/quickpack/`` matching the ``tests/unit/charmlint/``
  layout.  The flat file split into ``test_jujuignore.py``,
  ``test_metadata.py``, ``test_parts.py`` (with the attestation
  tests, which also live in ``quickpack.parts``), ``test_pack.py``,
  and ``test_cli.py`` matching the ``src/quickpack/`` module
  boundaries.  The shared ``charm_project`` fixture moved to
  ``tests/unit/quickpack/conftest.py``.  ``test_jujuignore_properties.py``
  (from Phase 59.4) also moved under the new directory.

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

**Status — all exit criteria met:**
- Total coverage: **88%** (was 77%)
- Lowest file: ``tui/themes.py`` at **93%** (was 47% before a
  ``tests/unit/test_themes.py`` pass on 2026-04-20 covering the
  YAML theme loader and user-directory discovery)
- ``pytest tests/unit`` reports zero warnings
- All four oversized unit-test files split; quickpack tests reorganised

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

## Phase 58: Rust Crate Unit Tests ✓

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

### 58.4 Low — Coverage instrumentation ✓

- [x] Wire ``cargo-llvm-cov`` into the CI job — the ``rust-test``
  matrix job now runs ``cargo llvm-cov --summary-only --json`` after
  ``cargo test``.  Per-file line coverage is extracted with ``jq`` and
  compared against the 60% advisory threshold.  Baseline on
  2026-04-20: charmlint-rs 89.6% total (lowest file ``main.rs`` 75%),
  quickpack-rs 78.0% total (lowest ``parts.rs`` 64%).  No file below
  60% at baseline, so zero annotations emitted
- [x] Set an advisory threshold (not blocking): warn if any Rust
  file drops below 60% — emitted via GitHub Actions ``::warning
  file=…`` annotations so they appear inline on the PR but don't
  fail the check.  Also added a ``make rust-coverage`` target that
  runs the same ``cargo llvm-cov --summary-only`` locally after a
  one-time ``cargo install cargo-llvm-cov && rustup component add
  llvm-tools-preview``

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

- [x] ``tests/unit/quickpack/test_jujuignore_properties.py`` — pattern
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

## Phase 60: Web UI Accessibility ✓

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

- [x] Add a ``tests/integration/web/test_accessibility.py`` that
  hosts the real aiohttp app on a thread, drives ``uvx rodney``
  against it, and asserts the key accessible-name / role / contrast
  invariants — covers findings 1–8 (Send button name + focus ring,
  chat-input programmatic label, chat-messages ``role=log``,
  connection-status accessible name, help/logs/graph overlay
  ``role=dialog`` with ``aria-modal``, header buttons' names) plus
  the dynamic behaviours the static test in
  ``tests/unit/test_web_server.py::TestAccessibility`` can't reach
  (``aria-expanded`` toggling, ``inert`` backdrop, focus moving into
  the dialog on open and back to the trigger on Escape, computed
  contrast ≥ 4.5:1).  The module self-skips when Chromium or
  ``uvx rodney`` isn't available, so CI collects it without mandating
  the dependency
- [~] Alternatively, run a headless axe-core scan via rodney's ``js``
  subcommand — deferred; the targeted assertions above cover the
  numbered findings directly, and axe would duplicate them with
  less-specific failure messages.  The option remains open if a
  broader sweep is ever needed

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

## Phase 62: On-Theme Activity Labels — "Spellcasting" Instead of "Thinking" ✓

**Goal:** Cantrip is named after the *cantrip* — a small, quickly-cast
spell — and the product it builds charms for is called *juju*.  Both
names lean into a spellcasting theme that every other piece of status
copy ignores: today the TUI and Web surfaces say ``⟳ Thinking...``,
``⟳ Streaming...``, and ``⟳ Running...`` in perfectly literal English.
Replace the literal labels with randomly-selected synonyms (or close
relations) for spellcasting so the UI matches the name.

Candidate verbs: *incanting*, *invoking*, *conjuring*, *weaving*,
*chanting*, *divining*, *scrying*, *summoning*, *murmuring*,
*channelling*, *enchanting*, *binding*, *hexing*, *charming*,
*brewing*, *consulting the oracle*.  The agent is still literally
thinking; the label is just theme-matching flavour text.

### 62.1 Medium — Pick a synonym pool and helper ✅

- [x] Add ``src/cantrip/ui/flavour.py`` (or a module under
  ``cantrip.agent``) with a vetted list of spellcasting verbs — not a
  free-for-all thesaurus; short, present-continuous, UK-English
  friendly, and non-offensive (drop *hexing* if it reads too sinister
  out of context) — ``src/cantrip/ui/flavour.py`` carries a 26-entry
  ``_THINK_POOL`` mixing single verbs (*Conjuring*, *Scrying*) and
  short phrases (*Thumbing the grimoire*, *Stirring the cauldron*,
  *Casting bones on the table*).  Hexing and cursing are dropped as
  the ROADMAP suggested
- [x] Public helper ``pick_activity_label(seed: int | str | None = None,
  category: ActivityCategory = ActivityCategory.THINK) -> str`` that
  returns a label.  The ``seed`` argument makes it deterministic for
  tests; production calls pass ``None`` for true randomness.  The
  ``category`` hint lets us reserve some verbs for specific phases
  (e.g. *scrying* for research, *brewing* for build, *weaving* for
  code generation) rather than one bag for everything — still random
  within a category, so the same user sees variety — ``ActivityCategory``
  has ``THINK`` (default, broad pool), ``RESEARCH`` (12 divination-
  flavoured entries), and ``BUILD`` (12 forging-flavoured entries).
  Unknown categories fall back to THINK rather than raising
- [x] Unit tests cover: deterministic seeding, per-category uniqueness
  (no overlap across categories unless intentional), and that every
  returned label passes a simple ``str.isprintable`` + length sanity
  check — ``tests/unit/test_ui_flavour.py`` asserts determinism,
  per-category subset membership, no duplicates, printable, non-empty,
  ≤40 chars, no trailing ellipsis, no whitespace cuffs, and capitalised
  first letter (33 cases across the three parametrised pools)

### 62.2 Medium — Wire the helper into existing ``Thinking...`` call sites ✅

- [x] ``src/cantrip/agent/core.py`` — the two
  ``self._publish_activity("⟳ Thinking...")`` call sites become
  ``self._publish_activity(f"⟳ {flavour.pick_activity_label()}...")``
  — both sites (post-tool in the sync and streaming branches) now
  produce a fresh themed label per tool-completion re-entry
- [x] ``src/cantrip/agent/subagent.py`` — ``self._set_phase("thinking")``
  (both call sites) picks from the pool.  Note: ``Subagent._set_phase``
  is also used for ``running:`` labels, which stay literal (those
  describe tool calls, not LLM thought) — both thinking sites call
  ``flavour.pick_activity_label()``; ``running:`` labels stay literal;
  ``test_phase_sequence_during_run`` updated to assert pool membership
- [x] ``src/cantrip/tui/app.py`` — the ``⟳ Thinking...`` literals
  become ``⟳ {flavour.pick_activity_label()}...``.  Status-bar
  streaming and phase-change paths pass through the same helper —
  the initial status-bar label on user send now draws from the pool;
  ``⟳ Streaming...`` stays literal (output delivery, not thought);
  the subagent_phase fed into ``#task-checklist`` inherits the flavour
  via subagent.py above
- [x] ``src/cantrip/web/server.py`` — the ``_broadcast(request.app,
  "thinking", ...)`` event type stays ``"thinking"`` (it's the
  protocol name, not user-visible), but the Web frontend maps it to a
  rotating flavour label on the client side — server untouched; event
  name is the protocol contract, not the user-visible label
- [x] ``src/cantrip/web/static/cantrip.js`` — in the ``case "thinking"``
  handler, swap the hard-coded "Thinking..." text for a client-side
  random pick from the same verb pool (ship the pool as a small
  constant at the top of the file; keep the Python and JS pools in
  sync via a unit test that diffs them) — JS ``FLAVOUR_POOL`` mirrors
  ``flavour.think_pool()``; ``setThinking(true)`` preserves the
  animated dots span and appends a freshly-picked label;
  ``TestJsPoolDrift`` in ``test_ui_flavour.py`` regexes the JS and
  asserts list equality so drift fails the build

### 62.3 Low — Refresh cadence ✅

- [x] Decide whether each new turn picks a fresh label (so a long
  turn doesn't just read *conjuring…* forever) or whether a label is
  stable per turn.  Stable-per-turn is simpler and avoids flicker;
  per-turn re-roll adds charm at the cost of test determinism.
  Recommendation: stable per turn, but pick a new one every time the
  phase flips back to "thinking" (so a turn that runs tools, returns
  to thinking, then runs more tools gets two different labels across
  its two thinking phases) — adopted the recommendation: every
  transition *into* thinking (``_set_phase`` in subagent, the
  post-tool ``_publish_activity`` in core, and the JS ``setThinking(true)``
  re-roll) calls the picker fresh, so a long turn reads a different
  verb after each tool round while the within-phase label stays stable
- [x] Write up the decision in ``design/UI.md`` alongside the
  ``Thinking...`` → flavour-label changeover so future contributors
  understand the intent — ``design/UI.md`` gets an "Activity Flavour
  Labels" section under Implementation Notes covering pool location,
  cadence, what stays literal, and category hints

### What this phase is *not*

- Not a rewrite of the status-bar layout.  Only the label text
  changes; icons, colour, and positioning stay as they are
- Not an ``i18n`` pass.  UK English only, consistent with the project
  conventions in ``CLAUDE.md``
- Not a gameification layer.  The label is flavour; we don't add XP
  bars or spellcasting progress rings

**Exit criteria:** No ``"Thinking..."`` string literal survives in the
user-visible code paths listed above; the flavour helper has unit
test coverage; the Python and JS verb pools are kept in sync by a
drift test; a short note in ``design/UI.md`` records the decision.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Helper + pool (62.1) | none | Pure Python; land first |
| Call-site wiring (62.2) | 62.1 | Touches TUI, Web, core, subagent |
| Refresh cadence (62.3) | 62.2 | Polish; can follow |

---

## Phase 63: Self-Update Check — "A Newer Cantrip Is Available" ✅

**Goal:** When Cantrip starts, check PyPI in the background for a newer
release of the ``cantrip`` distribution.  If one exists, surface a
non-blocking notice in every front-end (TUI, Web, CLI) that shows the
new version number, the relevant ``CHANGELOG.md`` entries between the
installed version and the latest, and concrete upgrade instructions
tailored to how Cantrip was installed (``uv tool``, ``pipx``, ``pip``,
or the snap once it exists).

Will McGugan's ``toad`` is the reference for UX: a background ``httpx``
worker fires at startup, the prompt is shown **after the main UI
exits** rather than interrupting the session, and the panel points at
an upgrade path rather than trying to self-upgrade in place (which
falls apart across installer choices).  Cantrip diverges in two ways —
we query PyPI's JSON API directly (the source of truth for a published
Python package) instead of a maintainer-hosted TOML, and we splice in
the committed ``CHANGELOG.md`` so the user sees real release notes
rather than a free-form marketing blurb.

References:
- ``toad`` update logic: https://github.com/batrachianai/toad
  — ``src/toad/version.py`` (version check), ``src/toad/app.py``
  (Textual worker + exit panel)
- PyPI JSON API: ``https://pypi.org/pypi/cantrip/json`` — ``info.version``
  for latest, ``releases`` for the version list
- Cantrip's own ``CHANGELOG.md`` and ``src/cantrip/__init__.py``
  (``__version__``) are the installed-side truths to compare against

### 63.1 Medium — PyPI version-check helper ✅

- [x] Add ``src/cantrip/update.py`` with ``async def
  check_for_update(*, timeout: float = 3.0) -> UpdateInfo | None``.
  Uses ``httpx.AsyncClient`` against
  ``https://pypi.org/pypi/cantrip/json``; parses ``info.version``;
  compares to ``cantrip.__version__`` via
  ``packaging.version.parse``; returns an ``UpdateInfo`` dataclass
  (``current``, ``latest``, ``pypi_url``, ``release_timestamp``) or
  ``None`` if we're already current — surface matches the spec; the
  module also accepts ``use_cache=False`` for the eventual
  ``/update`` slash command in 63.5; ``UpdateInfo.pypi_url`` points
  at ``https://pypi.org/project/cantrip/<latest>/`` so the user can
  click straight through to the release page
- [x] Any ``httpx.HTTPError``, DNS failure, timeout, or parse failure
  returns ``None`` — we never surface a stack trace or block startup
  because PyPI is slow.  Log at DEBUG only — handled by a single
  ``except (httpx.HTTPError, ValueError)`` around the JSON fetch.
  Field-shape guards (``_extract_latest_and_timestamp``) treat any
  unexpected payload shape as "no update visible" rather than
  raising; ``packaging.version.InvalidVersion`` on the latest string
  also returns ``None``
- [x] Cache the result on disk at ``~/.cache/cantrip/update.json``
  with a 24-hour TTL so normal day-to-day startups don't hit PyPI at
  all; honour ``CANTRIP_NO_UPDATE_CHECK=1`` and a
  ``settings.update_check_disabled`` flag to skip entirely.  Corporate
  networks that block ``pypi.org`` need a painless opt-out — TTL via
  the cache file's mtime keeps the on-disk format minimal (just
  ``latest`` + ``release_timestamp``); upgrading to the latest
  release naturally invalidates the "newer version" verdict on the
  next launch.  ``DISABLE_ENV`` accepts ``1`` / ``true`` / ``yes`` /
  ``on`` (case-insensitive); ``_settings_disabled`` reads
  ``~/.config/cantrip/settings.json`` leniently — missing or
  malformed file means "no opt-out" so a corrupted settings file
  cannot silently hide upgrade prompts

### 63.2 Medium — Changelog extraction and formatting ✅

- [x] Fetch ``CHANGELOG.md`` for the latest version from the GitHub
  raw URL at the matching tag (e.g.
  ``https://raw.githubusercontent.com/<owner>/cantrip/v{latest}/CHANGELOG.md``)
  via the same ``httpx`` client.  Fall back gracefully when the tag
  doesn't exist yet (pre-release landed on ``main`` but wasn't
  tagged) — surface the version number without notes — new
  ``fetch_changelog(version, *, timeout=3.0)`` returns the raw
  markdown body or ``None`` on 404 / HTTP error / timeout.  Repo
  slug defaults to ``tonyandrewmeyer/cantrip`` from
  ``pyproject.toml`` and is overridable via ``CANTRIP_UPDATE_REPO``
  for tests
- [x] Parse the markdown with a tiny heading-walker (no new dep);
  collect every ``## <version>`` section strictly between the
  installed version and the latest, newest first.  Skip
  ``## Unreleased`` — users upgrading to a tagged release don't
  need to see post-release churn — ``extract_release_notes(markdown,
  *, current, latest)`` walks the file line-by-line, distinguishes
  ``## `` from ``### ``, accepts optional ``v`` prefixes, and
  returns ``[(version, body), ...]`` newest-first via
  ``packaging.version`` ordering.  ``## Unreleased`` and any
  unparseable heading body close the prior section without
  starting a new one so churn never bleeds into a real release's
  body
- [~] Render the collected sections inside a Rich ``Panel`` for the
  TUI/CLI exit prompt; render as HTML via ``markdown-it-py`` (already
  a likely transitive dep — confirm before adding) for the Web
  banner.  Cap the rendered block at 30 lines with a "…
  full notes at {pypi_url}" trailer so four releases of backlog
  don't swamp the screen — rendering belongs in the UI surfaces and
  lands with 63.4.  ``markdown-it-py`` is confirmed available
  (4.0.0 transitive); ``UpdateInfo.release_notes_markdown`` ships
  the concatenated markdown ready for either renderer.  Library
  applies a 200-line safety cap (``_RELEASE_NOTES_LINE_CAP``) so a
  pathological CHANGELOG can't bloat the on-disk cache; the UI
  layer applies its own (30-line) cap when rendering — also part
  of 63.4

### 63.3 Medium — Installer detection and upgrade instructions ✅

- [x] ``src/cantrip/update.py`` gains ``detect_install_method() ->
  InstallMethod`` — an enum of ``UV_TOOL``, ``PIPX``, ``PIP_USER``,
  ``PIP_VENV``, ``SNAP``, ``UNKNOWN``.  Heuristics, cheapest first:
  check if ``sys.executable`` lives under ``~/.local/share/uv/``
  (uv tool), ``~/.local/pipx/venvs/`` (pipx), ``/snap/``
  (snap), a user-site dir (pip --user), or a generic venv (pip).
  ``UNKNOWN`` when nothing matches — heuristics ordered: ``/snap/``
  prefix (snap), ``/.local/share/uv/`` or ``/share/uv/tools/``
  (uv tool), ``/.local/pipx/`` or ``/.local/share/pipx/`` or
  ``/pipx/venvs/`` (pipx), ``sys.prefix != sys.base_prefix``
  (generic venv — runs *before* the user-site check so a venv
  created under ``~/.local/share/`` is correctly tagged as
  ``PIP_VENV`` rather than ``PIP_USER``), then ``~/.local/`` prefix
  (pip --user)
- [x] Map each method to a copy-pasteable command: ``uv tool upgrade
  cantrip``, ``pipx upgrade cantrip``, ``pip install --user --upgrade
  cantrip``, ``pip install --upgrade cantrip``, ``snap refresh
  cantrip``.  For ``UNKNOWN``, fall back to the PyPI URL and let the
  user decide — matches toad's "visit-URL" philosophy for
  ambiguous installs — ``upgrade_command(method)`` returns the
  string for known methods and ``None`` for ``UNKNOWN`` so callers
  can fall through to the PyPI URL.  ``method=None`` calls
  ``detect_install_method()`` for the user's installer
- [x] Unit tests cover each detection branch by monkey-patching
  ``sys.executable`` and the ``os.path.exists`` probe.  A final
  "we never crash on weird paths" fuzz test feeds random path
  strings and asserts we always return an ``InstallMethod`` (even
  if it's ``UNKNOWN``) — ``tests/unit/test_update.py``
  ``TestDetectInstallMethod`` parametrises every detection branch
  (with a pinned ``Path.home()`` so user-site heuristics don't
  depend on whoever runs the suite); ``test_never_crashes_on_weird_paths``
  feeds the helper empty strings, paths with newlines, paths with
  spaces, leading-dot paths, and "snap-but-not-quite" strings and
  asserts it always returns *some* ``InstallMethod`` (48 update
  tests in total)

### 63.4 Medium — Wire the check into all three front-ends ✅

- [x] **TUI** (``src/cantrip/tui/app.py``): kick off
  ``check_for_update()`` in an ``asyncio.Task`` from ``on_mount``.
  Result stashed on the app.  On ``action_quit`` / ``on_exit``,
  if an update is available, print a Rich panel to stdout **after**
  the Textual screen tears down.  Don't interrupt mid-session — the
  user should finish their work first.  Matches toad's exit-time
  prompt exactly — ``_start_update_check`` runs a Textual worker
  on mount; ``pending_update_info`` is read from ``cantrip.main._run``
  once ``app.run()`` returns and rendered by the new
  ``_print_update_panel`` helper (Rich ``Panel`` + ``Markdown`` body
  capped at 30 lines via ``_truncate_notes`` so four releases of
  backlog don't swamp the terminal).  Yanked-installed versions
  get a sharper title; ``UNKNOWN`` installers fall back to "Upgrade
  via your usual installer."
- [x] **Web UI** (``src/cantrip/web/server.py`` +
  ``templates/index.html.j2``): the server runs the same helper
  once at app-startup; the result is exposed via ``GET
  /api/update-status`` and via a ``"update-available"`` SSE event
  so reconnecting clients learn about it too.  The frontend shows
  a dismissible banner at the top of the page (reuses the
  resume-prompt banner pattern from Phase 31.3); dismissal is
  remembered in ``localStorage`` keyed on the version number so
  a second dismissal isn't needed for the same release — landed
  as a WebSocket ``update_available`` broadcast rather than SSE
  to reuse the existing ``/ws`` fan-out (the rest of the Web UI
  already streams over WebSockets; introducing SSE just for this
  would have fragmented the client transport).  ``UPDATE_STATE_KEY``
  holds the verdict; ``_run_update_check`` fills it in and
  broadcasts on completion (both for "newer available" and the
  explicit null case so a reconnecting client sees a definitive
  answer).  ``_update_info_payload`` serialises with the
  installer-aware ``upgrade_command`` already resolved so the JS
  renderer doesn't have to replicate the mapping.  Dismissal key
  is ``cantrip.update.dismissed = <latest>`` in ``localStorage``.
- [x] **CLI** (``src/cantrip/cli.py``): after the REPL exits (before
  the final ``sys.exit``), print a single-line notice pointing at
  the PyPI URL, followed by the upgrade command for the detected
  install method.  The full changelog is *not* printed — the CLI
  is often scripted, so keep stdout to one line and let the user
  open the URL for detail — ``_repl`` starts the check as a
  background ``asyncio.Task`` at the top of the REPL (so the
  result is warm by the time the user quits); ``_print_update_notice``
  awaits the task with a 1-second cap and prints the two-line
  ``format_cli_notice(info)`` output (headline + PyPI URL, then
  upgrade command).  The cap is deliberately tight so a stuck
  check can't delay the user's next prompt — the next launch will
  hit the populated cache anyway.
- [x] All three front-ends share the same helper and the same cache
  file — no duplicated HTTP calls when a user runs the TUI, then
  launches the Web UI ten minutes later — everything routes through
  ``cantrip.update.check_for_update()``, which honours the 24-hour
  mtime cache at ``~/.cache/cantrip/update.json`` regardless of
  which surface called it first.  A tests-wide autouse fixture
  (``tests/conftest.py::_disable_pypi_update_check``) sets
  ``CANTRIP_NO_UPDATE_CHECK=1`` so unit tests never accidentally
  touch the live endpoint; the existing ``test_update.py`` suite
  deletes the env via ``no_settings_optout`` to re-enable the
  check.

### 63.5 Low — ``/update`` slash command for on-demand checks ✅

- [x] Slash command ``/update`` forces a cache-bypassing check and
  prints the result (or "You're on the latest version.")
  immediately.  Useful when a user just ran ``uv tool upgrade`` and
  wants to confirm the session picked up the new release — though
  the *running* process is obviously still on the old code; the
  command makes that explicit — wired through
  ``cantrip.agent.slash_commands.dispatch`` as a ``SlashResult`` with
  a follow-up coroutine (``_run_update_slash_check``) that hits
  ``check_for_update(use_cache=False)`` and renders via the new
  ``format_slash_notice`` helper.  The notice carries an explicit
  "restart Cantrip after upgrading" line so the user doesn't wonder
  why ``__version__`` hasn't moved.
- [x] ``/update --no-check`` writes ``update_check_disabled = true``
  to ``settings.json`` so the user doesn't have to edit the file by
  hand.  ``/update --check`` re-enables it.  Mention both in the
  ``/help`` output and in ``design/UI.md`` — new
  ``update.set_update_check_disabled(bool)`` helper writes
  ``~/.config/cantrip/settings.json`` and preserves any sibling
  keys the user may have added.  Malformed JSON is replaced rather
  than left in place — the user just asked for a toggle, so the
  sensible thing is a clean file.  Extra tokens or an unknown flag
  render a two-line usage hint instead of executing anything.
  ``/help`` (shared + CLI ``_HELP_TEXT``) carries the verb, and
  ``design/UI.md`` gained a Slash Commands section that catalogues
  every shared verb plus a note that ``CANTRIP_NO_UPDATE_CHECK``
  env var shadows the settings-file toggle for the session.
  15 new unit tests in ``test_slash_commands.py`` /
  ``test_update.py`` cover dispatch shape, toggle round-trip,
  usage-hint paths, malformed-settings replacement, and the
  follow-up coroutine's four branches (up-to-date, newer, disabled,
  network error).

### 63.6 Low — Pre-release and yanked-version handling ✅

- [x] Filter out pre-releases (``1.2.0rc1``) unless the *installed*
  version is itself a pre-release — users on a stable don't want
  to be nagged about alphas — ``_make_info_if_newer`` checks
  ``latest_parsed.is_prerelease and not current_parsed.is_prerelease``
  and returns ``None`` in that case.  A user already on a
  pre-release sees other pre-releases (they've opted into the
  bleeding edge); a pre-release user upgrading to a stable
  release also gets nagged correctly
- [x] Honour PyPI's ``yanked`` flag: if the currently installed
  version is yanked, the notice shifts in tone ("Your installed
  version has been yanked; upgrading to {latest} is recommended"),
  and we skip changelog filtering since there's no guarantee of a
  clean linear history between a yanked release and the next good
  one — ``_is_version_yanked(payload, version)`` walks
  ``releases[version]`` and returns True if any file is yanked.
  ``UpdateInfo.installed_yanked`` carries the bool through the
  cache; the UI layer (63.4) consumes it to switch the prompt's
  tone.  The yanked-skips-changelog-filtering note is documented
  for the UI layer; the library still ships notes for normal
  upgrades because callers may want to show *some* context even
  to a yanked-version user
- [x] ``packaging.version.parse`` is already a transitive dep via
  ``httpx``/``pip`` — confirm and pin; we are not adding ``pip``
  as a runtime dep just for this — confirmed available (26.0)
  via the existing dep tree; no change to ``pyproject.toml``
  required

### What this phase is *not*

- Not an auto-upgrader.  We never run ``uv tool upgrade`` on the
  user's behalf — the installer mix is too heterogeneous and the
  consequences of a half-upgraded session are worse than a manual
  copy-paste
- Not a telemetry channel.  The only outbound request is to
  ``pypi.org`` (and GitHub raw for the changelog); we don't phone
  home to a Cantrip-operated server
- Not a version-pinning story.  Users who want to stay on a specific
  release set ``update_check_disabled = true`` and move on; we don't
  ship a "subscribe to major-only" flag until there's demand
- Not a migration tool.  If ``0.x`` → ``1.0`` needs a config
  migration, the changelog says so and the user runs it manually

**Exit criteria:** launching any of the three UIs on a version older
than the PyPI latest surfaces a non-blocking notice with version
number, filtered changelog, and a copy-pasteable upgrade command
matching the detected installer; the check completes in under 3s in
the happy path and never blocks startup longer than the timeout; a
user on the latest version sees no extra output in any UI; unit tests
cover version comparison, changelog filtering, installer detection,
cache TTL, and every opt-out; ``/update`` and the
``CANTRIP_NO_UPDATE_CHECK`` env var are documented in
``design/UI.md``.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Version helper (63.1) | none | Pure Python + ``httpx``; land first |
| Changelog fetch (63.2) | 63.1 | Reuses the same ``httpx`` client |
| Installer detection (63.3) | none | Independent; can land in parallel |
| UI wiring (63.4) | 63.1–63.3 | TUI/Web/CLI pick up the finished helpers |
| ``/update`` command (63.5) | 63.4 | Polish; on-demand variant of the same path |
| Pre-release handling (63.6) | 63.1 | Small filter on top of the version check |

---

## Phase 64: Repo Bootstrap Prompt — UX Fixes ✓

**Goal:** The "No GitHub remote detected. Would you like to create a
repository?" offer currently drops into the main chat after a message
turn completes (``_offer_repo_bootstrap`` in ``src/cantrip/tui/app.py``
around line 723) and suggests a repository named after the bare
charm name (e.g. ``grafana`` instead of ``grafana-operator``).  Two
complaints: (1) the prompt interrupts the conversation at annoying
moments, so move it into a dedicated question/answer surface rather
than inline chat; (2) the suggested name should follow the Canonical
convention of ``<workload>-operator`` so users don't have to correct
it manually.

### 64.1 Medium — Suggest ``<workload>-operator`` as the default repo name ✓

- [x] New ``cantrip.agent.git_branch.suggest_repo_name()`` helper
  appends ``-operator`` unless the charm name already ends in one
  of ``-operator``, ``-charm``, ``-k8s``, or ``-machine``.  Empty
  / whitespace names pass through unchanged so callers can fall
  back to their own placeholder.
- [x] ``handle_repo_bootstrap`` unchanged — it already accepted the
  name as a parameter.  The default name now rides on the CONFIRM
  task's ID (``bootstrap-repo-<name>``) so a bare ``approve`` picks
  it up without re-parsing.  A ``name=my-custom-repo`` token in
  the user's reply overrides the default.
- [x] Seven unit tests in ``tests/unit/test_agent_github.py::
  TestSuggestRepoName`` pin the suffix logic: plain ``foo`` →
  ``foo-operator``, each suffix is preserved, empty input is
  passthrough, hyphenated workloads still get the suffix.

### 64.2 Medium — Move the offer out of the main chat ✓

- [x] ``_offer_repo_bootstrap`` now enqueues a ``bootstrap-repo-*``
  CONFIRM task via ``agent.build_repo_bootstrap_confirm_task()``
  instead of calling ``chat.add_system_message``.  The shared
  CONFIRM+BLOCKED routing in ``_on_bus_task_status_changed``
  dispatches to a new ``_present_bootstrap_confirmation`` that
  prints a framed ``**Repo bootstrap:**`` prompt — consistent with
  ``_present_triage_confirmation`` / ``_present_push_confirmation``.
  The task stays visible in the task panel until the user replies.
- [x] Offer still fires after the LLM worker settles (same trigger
  point as before), which means the work queue has at least drained
  the current conversation turn.  Because it's now a CONFIRM task
  with no dependencies, the executor picks it up, blocks it, and
  presents it — so nothing interrupts an in-progress task.
- [x] ``_bootstrap_offered`` is kept as the session-scoped dismissal
  flag (flipped to ``True`` when the task is queued, never reset
  within the session).  The ``_pending_bootstrap`` boolean was
  replaced by gating ``_handle_bootstrap_response`` on
  ``_pending_confirm_id.startswith(BOOTSTRAP_CONFIRM_PREFIX)`` — same
  shape as the other CONFIRM handlers.  No session-store flag was
  added; the phase brief marked it as "consider", and the existing
  in-memory behaviour is fine (restart creates a new session so the
  question is relevant again).
- [x] Web UI mirror: the Web UI had no bootstrap path at all, so
  there was nothing to regress; the CONFIRM task will naturally
  surface through the shared task widget whenever Web UI picks up
  CONFIRM presentation.

### 64.3 Low — Documentation ✓

- [x] Added a new ``#confirmations`` section to
  ``docs/docs/explanation-tui-screens.html`` that explains the
  CONFIRM task pattern, calls out the repo-bootstrap offer as the
  most common prompt, and lists every reply token
  (``approve``/``skip``/``public``/``name=``/``org=``/``desc=``).
  The ``<workload>-operator`` default and its suffix-preserving
  exceptions are documented there.

### What this phase is *not*

- Not a rewrite of the underlying ``gh_repo_create`` /
  ``gh_repo_bootstrap`` tools — those already work.  This phase
  is purely about *when* and *how* the offer is surfaced and
  *what name* it suggests.
- Not a full form/wizard for all repo options.  Public/private,
  org, description can stay as ``key=value`` tokens in the
  reply; the point is to get the question out of the chat log.

**Exit criteria:** launching Cantrip against a charm with no
GitHub remote surfaces the create-repo question outside the main
chat transcript; the suggested name ends in ``-operator`` by
default; dismissing the offer once keeps it dismissed for the
session; unit tests pin the name-suffixing behaviour.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Name default (64.1) | none | Pure string logic; land first |
| Surface move (64.2) | 64.1 | Reuse the CONFIRM-task pattern if possible |
| Docs (64.3) | 64.2 | Follows the shipped UI |

---

## Phase 66: Transcript and Debug-Log Modals Show Nothing ✓

**Goal:** Users report that opening the transcript window
(``F8`` / ``action_transcript``) and the Juju debug-log window
(``action_logs``) both display empty panes.  The ``CharmTreeWidget``
had a similar "content but no visible rows" bug that was fixed by
pinning ``height: 1fr; max-height: 50%;`` on ``#charm-files`` in
``cantrip.tcss`` — the same CSS height-computation edge case may be
biting the ``RichLog`` widgets inside ``TranscriptScreen``
(``#transcript-output``, currently ``height: 1fr``) and
``LogScreen`` (``#log-output``, currently ``height: 1fr``), since
both are nested inside ``Center → Vertical`` containers that the
filetree widget is not.

### 66.1 High — Reproduce and diagnose ✓

- [x] Repro on a session with a known-good transcript database
  (``.cantrip/`` directory with events).  Confirm whether the
  problem is (a) ``RichLog`` receiving no lines, (b)
  ``RichLog`` receiving lines but having zero rendered height,
  or (c) the modal container collapsing so the output is
  clipped off-screen.  **Root cause was (c):** a 100×40 pilot
  showed ``#transcript-container`` and ``#log-container`` both
  resolving to ``height=0`` because their outer ``Center()``
  wrapper has ``height: auto`` and the inner ``Vertical`` asked
  for ``height: 80%``/``90%`` of a zero-height parent.  The
  ``RichLog`` then rendered at the 1-row minimum.
- [x] Same check for ``LogScreen`` — same diagnosis; ``on_mount``
  was writing ``"Fetching logs…"`` / ``"No development model
  connected."`` correctly, the lines just had nowhere to go.
  ``RelationDetailScreen`` and ``GraphScreen`` have the same
  latent bug (also fixed in this phase).

### 66.2 High — Fix the height ✓

- [x] Dropped the redundant ``Center()`` wrapper from
  ``transcript.py``, ``logs.py``, ``relation.py``, and
  ``graph.py``.  ``ModalScreen`` already centres its children
  via its own ``align: center middle``, so the outer ``Center``
  was never needed — it was silently forcing the percentage
  heights to resolve against zero.  Container heights on a
  100×40 pilot now go from 0 → 28–32 rows, and the ``RichLog``
  widgets from 1 → 26–30 rows.  Uncovered a latent Textual
  markup error in the transcript footer (``[/ Search]`` parsed
  as a closing tag once the footer was actually being painted);
  footer now renders with ``markup=False``.
- [x] ``tests/unit/test_modal_heights.py`` — one Pilot test per
  modal mounts it with fixture data and asserts the container
  has non-zero height, the output widget has ``height > 1``,
  and at least one line was rendered.  Six tests, all passing.

### 66.3 Medium — Surface an empty-state message ✓

- [x] Empty-state messages were already in place — they were
  just invisible.  Transcript writes ``"No .cantrip session
  file found."`` when the DB is absent and ``"No conversation
  messages recorded."`` / ``"No tasks recorded."`` / ``"No
  events recorded."`` per view.  ``LogScreen`` pre-fills with
  ``"[dim]Fetching logs…[/dim]"`` before the worker runs and
  writes ``"No log entries at level {level}."`` on the
  ``EMPTY:`` branch.  All now visible once 66.2 landed.

### What this phase is *not*

- Not a redesign of either modal's search / filter / streaming
  UX.  Those keep working as they are.
- Not a refactor of the transcript data layer — this is purely
  about getting the existing content on screen.

**Exit criteria:** pressing the transcript binding shows either
real events or a clear empty-state string; pressing the log
binding shows either ``juju debug-log`` output or an empty-state
string; both are proven by a smoke test; the underlying cause
(heights, container sizing, or worker plumbing) is documented
in the commit message.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Diagnosis (66.1) | none | Must run first |
| Height fix (66.2) | 66.1 | Small CSS / container change |
| Empty-state (66.3) | 66.1 | Independent of 66.2 |
## Phase 68: OpenCode-Inspired Safety Rails — Undo, Plan Mode, Permissions, User Commands ✓
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

### 68.1 High — Snapshot-backed undo/redo for file changes ✓

- [x] Audit replaced with a tree-wide approach: ``git add -A``
  honours the user's ``.gitignore`` plus a built-in
  ``info/exclude`` for ``.cantrip/`` and ``.cantrip-worktrees/``,
  so every mutating tool (``fs_write``, ``fs_edit``,
  ``charmcraft_init``, ``charmcraft_pack``, ``git_*``, etc.) is
  covered automatically without an allowlist that could rot.
- [x] Snapshot layer in ``src/cantrip/agent/snapshots.py``
  commits the whole charm working tree before each user turn
  into a hidden git repo at
  ``$XDG_STATE_HOME/cantrip/snapshots/<sha>/`` (out of the
  user's tree so ``git status`` doesn't see it).  Commit
  message is ``snapshot: turn <turn-id>``.  Empty initial
  commit anchors the history so ``reset --hard`` always has
  a target.
- [x] ``/undo`` slash command (``handle_undo`` in
  ``slash_commands.py``) takes a pre-restore snapshot of the
  current dirt (so ``reset --hard`` cleanly removes anything
  the agent created mid-turn), restores to the user-message's
  snapshot SHA, truncates ``state.messages`` from that user
  message onward, and deletes the matching SQLite rows via
  the new ``SessionStore.delete_messages_from``.
- [x] ``/redo`` re-applies the most recently undone turn from
  an in-memory stack; clears the moment a new user turn
  arrives.  Re-recording assigns fresh DB IDs so a follow-up
  ``/undo`` finds the right rows.
- [x] Two new UI events (``SNAPSHOT_CREATED`` /
  ``SNAPSHOT_RESTORED``) carry SHA, paths-changed and
  direction so the transcript records every move.
- [x] Phase 44 vs 68.1 boundary documented in
  ``design/AGENT.md``: worktrees isolate concurrent
  subagents, snapshots capture the main tree across user
  turns; snapshots ignore ``.cantrip-worktrees/``.
- [x] Disable flag landed as the ``--no-snapshots`` CLI flag
  + ``CANTRIP_SNAPSHOTS=false`` env var (deferred the
  ``cantrip.yaml`` parser to a future phase since none
  exists yet).  Disabled mode short-circuits ``/undo`` and
  ``/redo`` with a clear "snapshots disabled" message.
- [x] ``tests/unit/test_snapshots.py`` covers snapshot
  capture, undo restore (modification / deletion / creation /
  unsnapshotted dirt), redo round-trip, redo clearing on a
  new user turn, disabled mode short-circuit, gitignored and
  ``.cantrip/`` exclusions, and the env/CLI resolver.
  25 tests, all passing.

### 68.2 High — Declarative permission config ✓

- [x] ``.cantrip/permissions.yaml`` (repo) and
  ``~/.config/cantrip/permissions.yaml`` (user), merged with
  repo taking precedence.  Three outcomes: ``allow``, ``ask``,
  ``deny``.  Ordered glob maps per section (``tools`` / ``bash``
  / ``paths``); last matching pattern wins within a section,
  most-restrictive (``deny`` > ``ask`` > ``allow``) wins across
  sections.  OpenCode rule shapes transfer one-for-one.
- [x] Sensible defaults shipped as a built-in fallback
  (``BUILTIN_PERMISSIONS``): ``bash: rm -rf *`` → ``deny``,
  ``rm -fr *`` → ``deny``, ``sudo *`` → ``ask``, ``git push *``
  → ``ask``; ``paths: .env`` / ``*/.env`` / ``*.env`` →
  ``deny``; everything else defaults to ``allow``.
- [x] Enforcement lives in ``Subagent._apply_permission_gate``
  inside the per-tool-call ``_tool_or_veto`` closure — runs
  *after* the Phase 46 ``PRE_TOOL_CALL`` hook (on the
  post-mutation arguments) and *before*
  ``_execute_tool_with_checkpoint``.  A ``deny`` returns a
  synthetic ``ToolResult`` naming the matched rule; an ``ask``
  parks the call on the new ``PermissionManager`` (``asyncio
  .Future`` + timeout auto-deny), surfaced via the CONFIRM-task
  id convention ``permission-confirm-<request-id>``.
- [x] Per-agent overrides land as an ``agents:`` sub-map keyed
  by the subagent's category value (``research`` / ``build`` /
  …); overlays compose on top of the global sections and then
  feed the same cross-section "most restrictive wins" merge.
- [x] ``PERMISSION_DECIDED`` event type + ``permission_decided``
  factory added to ``cantrip.ui.events``; emitted by the
  executor's ``on_permission_decided`` callback for every
  non-allow verdict plus the user's ``ask`` resolution.
- [x] Documented in ``docs/docs/howto-permissions.html`` (new
  page) with schema, defaults, per-agent examples, and an
  OpenCode rule-transfer note; linked from the how-to sidebar
  on every existing how-to page, from ``docs/docs/index.html``,
  and from the ``cantrip hooks`` entry in
  ``docs/docs/reference-cli.html``.
- [x] ``tests/unit/test_permissions.py`` — 37 tests covering
  glob semantics, last-match-wins, most-restrictive-wins
  cross-section resolution, per-agent overlay merge, YAML
  loader + error shapes, ``discover_permissions`` layer
  ordering (repo beats user), built-in default behaviour, the
  async ``PermissionManager`` (approve / deny / timeout /
  cancel_all), and a subagent-integration smoke for the gate
  helper's deny / allow / ask paths.

### 68.3 Medium — User-defined slash commands ✓

- [x] Loader in ``src/cantrip/agent/custom_commands.py``
  discovers ``.cantrip/commands/*.md`` (repo) and
  ``~/.config/cantrip/commands/*.md`` (user).  Filename →
  command name (``debug-relation.md`` → ``/debug-relation``),
  validated against ``[a-z0-9][a-z0-9_-]*``.  Repo beats user
  on name conflict; malformed files log + skip rather than
  halting discovery.
- [x] YAML frontmatter fields ``description``, ``agent``
  (default ``primary``; any ``TaskCategory`` value routes via
  the work queue), ``model`` (optional override), ``subtask``
  (bool).  Unknown frontmatter keys raise so typos surface
  immediately.  Body is the prompt template.
- [x] Placeholder substitution in ``expand()``:
  - ``$ARGUMENTS`` — everything after the verb.
  - ``$1``, ``$2``, … — :mod:`shlex`-split positionals; unset
    indexes expand to the empty string.
  - ``@path`` — repo-local file contents, with absolute paths
    and ``..`` traversal outside the repo root rejected.
  - ``` !`shell cmd` `` — ``sh -c`` stdout (+ labelled
    ``[stderr]`` and ``[exit N]``), bounded to 10 s / 10 000
    chars, routed through the Phase 68.2 permission gate so a
    ``deny`` refuses and an ``ask`` parks on the
    :class:`PermissionManager` via ``PermissionManager.request``.
- [x] ``CantripAgent.custom_commands`` loads at construction
  and is exposed as a ``CustomCommandRegistry``.  The slash
  dispatcher falls through to it when no built-in verb matches;
  ``catalogue_for(agent)`` composes built-in + user commands so
  Phase 61 autocomplete and ``/help`` pick them up without
  per-surface work.  ``help_text(agent)`` also lists them under
  a "**User commands**" heading.
- [x] Dispatch path renders a "Running `/verb`…" prelude and
  attaches an async ``followup`` that expands + dispatches:
  ``agent: primary`` feeds the expanded prompt into
  ``agent.process_message``; a subagent category (or
  ``subtask: true``) queues an :class:`AgentTask` of that
  category instead.
- [x] Documented in
  ``docs/docs/howto-custom-commands.html`` with a working
  ``/relation-check`` example, full schema, placeholder
  reference, and the permission-gate interaction; linked from
  every how-to sidebar, ``docs/docs/index.html``, and the
  ``cantrip hooks`` entry in ``docs/docs/reference-cli.html``.
- [x] ``tests/unit/test_custom_commands.py`` — 30 tests
  covering frontmatter parse + error shapes, filename → verb
  validation, repo-beats-user precedence, malformed-file
  skip, ``$ARGUMENTS`` / positional substitution including
  quoted args, ``@path`` include with absolute + traversal
  rejection, ``!`cmd` `` shell expansion under ALLOW / DENY /
  ASK / no-manager, failed-command exit-code formatting,
  registry lookup, and dispatcher integration (unknown verb
  fall-through, catalogue / help-text inclusion).

### 68.4 Medium — Plan mode ✓

- [x] ``/plan`` and ``/build`` slash commands toggle
  ``AgentState.plan_mode`` (default ``False``, sticky per
  session).  Added to ``COMMAND_CATALOGUE`` + ``SHARED_VERBS``
  so autocomplete and ``/help`` pick them up.  Calling either
  while already in that mode is a no-op with a clear status
  line.
- [x] Narrow read-only allow-list ships as
  :data:`cantrip.agent.permissions.PLAN_MODE_ALLOWED_TOOLS`
  (file reads, ``git_*`` history reads, Juju introspection,
  ``memory_list``/``read``/``search``, ``web_search`` /
  ``web_fetch``).  Everything else returns a refused
  ``ToolResult`` with the ``plan_mode_message`` phrasing.
  ``mcp__``-prefixed tools bypass (per-server gated).
- [x] Implemented as a permission preset, not a parallel
  code path: :data:`PLAN_MODE_OVERLAY` is a
  :class:`PermissionRuleset` with ``"*": DENY`` plus literal
  ``ALLOW`` for every read-only tool.  The executor's
  ``_effective_permissions`` composes the overlay onto the
  discovered base ruleset whenever ``state.plan_mode`` is
  ``True`` and passes the composed ruleset to every Subagent
  it constructs (single and race paths).  The main-agent
  conversation loop and streaming loop gate via
  ``_plan_mode_refusal`` before ``_execute_tool`` for the same
  effect on typed user messages.
- [x] TUI status bar gained a ``mode`` reactive + literal
  "plan mode" badge, a dedicated ``-plan-mode`` CSS class
  backed by ``$warning-darken-2``, and a ``mode`` payload
  handler in ``app._on_bus_status_bar``.  ``/plan`` / ``/build``
  publish ``STATUS_BAR_CHANGED`` events with the
  ``mode={plan,build}`` field so every surface tints in
  lockstep.
- [x] System prompt grows a short ``## Plan mode`` appendix
  while the flag is on, asking for a ``Proposed changes``
  section.  ``_extract_proposed_changes`` captures the body
  case-insensitively at any heading depth and stashes it on
  ``state.plan_summary``; ``/build`` splices the captured
  summary back as an assistant-role message so the follow-up
  turn resumes from the plan instead of re-planning.
- [x] Documented in
  ``docs/docs/howto-plan-mode.html`` (new page) with the
  read-only allow-list, the ``Proposed changes`` contract, the
  status-indicator story, and the interaction with
  permissions, hooks, ``/undo``, and custom commands.  Linked
  from every how-to sidebar, ``docs/docs/index.html``, and a
  new Plan-mode section in ``docs/docs/reference-cli.html``.
- [x] ``tests/unit/test_plan_mode.py`` — 22 tests covering
  the overlay allow/deny matrix, base+overlay composition,
  ``/plan`` / ``/build`` toggle + event emission + summary
  splice, double-toggle no-op, ``help_text`` + catalogue drift,
  the main-agent ``_plan_mode_refusal`` helper (allow / deny /
  MCP bypass / off), the ``_extract_proposed_changes`` regex
  (capture, case-insensitivity, heading boundary, miss),
  plan-summary capture across a turn, and the system-prompt
  appendix toggle.

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

## Phase 74: Populated Charm Documentation — From Scaffold to Substance ✓
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

## Phase 75: Inline Tool Blocks in the Chat ✓
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
  command shows its error in the caption.  *Deferred → tracked
  in Phase 81.*
- [ ] Juju: ``juju_deploy`` (``"Deployed redis to
  dev-model"``), ``juju_config`` (``"Set redis/0
  debug=true"``), ``juju_status`` (``"4 apps, 1 blocked"``),
  ``juju_integrate`` / ``juju_remove_relation``.  *Deferred →
  tracked in Phase 81.*
- [ ] Acceptance / test: ``run_charm_tests`` (``"12 passed, 1
  failed"``), ``charm_audit`` (``"2 issues"``),
  ``acceptance_report``.  *Deferred → tracked in Phase 81.*
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

## Phase 77: Surface `reasoning_content` From OpenAI-Compatible Models ✓
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

## Phase 78: Provider Observability Hardening — April 23 Postmortem Lessons ✓
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

## Phase 80: Stacked Tool-Access Policies ✓
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

### 80.1 High — ``GovernancePolicy`` dataclass + ``compose_policies`` ✓

- [x] ``src/cantrip/agent/policy.py`` ships the frozen
  ``GovernancePolicy`` dataclass with ``allowed_tools``,
  ``blocked_tools``, ``require_human_approval``,
  ``max_calls_per_request``, and a ``name`` field that
  composition carries through so audit events (80.4) can show
  which stack produced a decision.  ``check_tool(name)``
  returns a :class:`PolicyAction` (``ALLOW`` / ``DENY`` /
  ``REVIEW``) with block > review > allow precedence — the
  strictest rule always wins.
- [x] ``compose_policies(*policies)`` implements
  most-restrictive-wins: non-empty allow-lists intersect
  (empty allow means "no allow opinion"), block and
  approval unions, rate limit picks the lowest non-``None``
  value.  Associative and commutative for the relevant
  fields.
- [x] YAML loader (``policy_from_dict`` /
  ``load_policy_file`` / ``discover_policies``) scans
  ``~/.config/cantrip/policies/*.{yaml,yml}`` and
  ``<charm>/cantrip.policies.yaml`` in sorted order so
  composition is deterministic; malformed files log a
  warning and are skipped so one broken policy doesn't lock
  the operator out.  Strict parser rejects unknown keys,
  non-integer rate limits, and bool-as-int.
- [x] Two built-in policies: ``ORG_WIDE_POLICY`` (review gate
  on ``juju_destroy_model`` / ``juju_destroy_controller`` /
  ``juju_remove_*`` / ``run_command`` / ``git_push``) and
  ``SPRINT_POLICY`` (200-call rate limit for unattended
  sessions).  The per-category layer comes from the
  ``category_policy()`` factory — Phase 80.2 wires it into
  the dispatcher by reading ``subagent._CATEGORY_TOOLS``.
- [x] ``tests/unit/test_policy.py`` — 44 unit tests covering
  commutativity, associativity, the empty-allow preservation
  rule, rate-limit min semantics, YAML round-trip, discovery
  ordering, malformed-file skipping, and a full three-layer
  stack composing to the expected defence-in-depth verdicts
  from ``design/TOOLS.md`` §55.4.

### 80.2 High — Wire policies into the subagent dispatcher ✓

- [x] ``Subagent.__init__`` now composes a
  :class:`PolicyEnforcer` once per run via the new
  ``_build_policy_enforcer(category, charm_path)`` helper.
  The stack layers the org-wide floor, a per-category
  allow-list (derived from ``_CATEGORY_TOOLS`` via
  ``category_policy``), and anything discovered from
  ``~/.config/cantrip/policies/`` plus
  ``<charm>/cantrip.policies.yaml``.  The LLM-visible tool
  list is now ``enforcer.filter_tools(tools)`` rather than
  the bare ``_filter_tools`` lookup.  ``_filter_tools`` is
  kept as a thin shim for callers that don't build a full
  ``SubagentContext`` (used by a handful of existing tests).
- [x] ``_tool_or_veto`` gains a call-time policy check that
  fires **before** the PRE_TOOL_CALL hook chain.  A policy
  ``DENY`` short-circuits to a synthetic ``ToolResult(
  success=False, error=<reason>)`` naming the composed
  policy stack; the PRE_TOOL_CALL hook does not fire for a
  denied call because the call never had a chance of running.
  ``REVIEW`` verdicts degrade to ``DENY`` with a log line
  suggesting the user add an approval rule (Phase 68.2 will
  route these through a confirmation prompt instead).  The
  POST_TOOL_CALL hook payload gains ``policy_denied_by``
  stamping the composed policy name so Phase 80.4's audit
  trail can trace each decision.
- [x] MCP-tool exception preserved: ``PolicyEnforcer.
  check_tool`` short-circuits ``ALLOW`` for names starting
  ``mcp__``, matching the old ``_filter_tools`` carve-out.
  MCP gating stays owned by the per-server
  ``allowed_tools`` config from Phase 45.2.
- [x] Unknown categories (e.g. ``CONFIRM``, which never had an
  entry in ``_CATEGORY_TOOLS``) preserve the historical "zero
  tools" behaviour via a sentinel allow-list that no real
  tool name can match.
- [x] ``tests/unit/subagent/test_policy_wiring.py`` — 18 tests
  covering enforcer composition, list-time filter, call-time
  gate with an LLM-driven integration case, deny-reason
  formatting, per-charm overlays, MCP bypass, unknown-
  category deny-all, and the "per-charm file cannot loosen
  the org-wide review list" defence-in-depth invariant.
  Existing ``test_helpers.py`` / ``test_allowlists.py`` /
  ``test_mcp_tool.py`` still pass via the ``_filter_tools``
  shim.

### 80.3 Medium — ``max_calls_per_request`` per-goal rate limit ✓

- [x] ``BackgroundExecutor`` composes the stack
  (``ORG_WIDE_POLICY`` + ``discover_policies(charm_path)``)
  once at construction, reads ``max_calls_per_request`` off
  the composed policy, and stores it as ``_rate_limit_cap``
  alongside an in-memory ``_tool_calls_made`` counter.  The
  policy-name survives composition so audit / UI consumers
  see which layer caused the cap.
- [x] The constructor wraps the caller's ``on_tool_invoked``
  through ``_wrap_tool_invoked``: every non-MCP call bumps
  the counter before forwarding to the inner callback, so
  MCP tools stay gated by the per-server ``allowed_tools``
  config (Phase 45.2) rather than the policy stack and UI
  events still reach the chat unchanged.
- [x] Spawn-time gate ``_check_rate_limit`` fires in
  ``_run_loop`` right after the goal-budget gate.  Tripping
  the cap blocks the task with ``"Policy rate limit
  exceeded: N tool calls (cap: M)…"`` and invokes the new
  ``on_rate_limited`` callback.  The core wires that
  callback to a ``POLICY_RATE_LIMITED`` UI event (``task_id``
  / ``tool_calls_made`` / ``cap`` / ``policy_name``) plus a
  SYSTEM transcript message so the stop lands in the chat
  — same shape as Phase 55.3's ``GOAL_BUDGET_EXCEEDED``.
- [x] Composes cleanly with the two sister circuit breakers:
  goal > task > session-call, all using ``<Reason> exceeded:
  …``-shaped ``blocked_reason`` strings so the TUI renders
  each uniformly.
- [x] ``tests/unit/executor/test_rate_limit.py`` — 11 tests
  covering the "no policy file → no cap" and "per-charm file
  sets cap" paths, the wrapper-increments-non-MCP-only
  invariant, the inner callback still firing, the gate
  trip-at-cap / clear-below-cap / never-without-cap matrix,
  and the end-to-end "rate-limited task blocks + raising
  counter unblocks" flow.  Plus a factory test for the
  ``POLICY_RATE_LIMITED`` event shape in
  ``test_goal_budget.py::TestEventFactory``.

### 80.4 Medium — JSONL audit trail ✓

- [x] ``src/cantrip/agent/audit.py`` ships the
  ``AuditEntry`` dataclass (``timestamp`` / ``task_id`` /
  ``tool`` / ``action`` / ``policy_name`` / ``reason`` /
  ``arguments``), the ``AuditAction`` enum (``allowed`` /
  ``denied`` / ``review-requested`` / ``rate-limited``), and
  an ``AuditWriter`` that serialises one JSON line per call
  under a thread-lock so concurrent subagents don't
  interleave partial writes.  Argument scrubbing reuses
  ``memory_export.sanitise_body`` — secrets stay in one
  place.  The file lives at ``<charm>/.cantrip-audit.jsonl``.
- [x] ``Subagent._record_audit`` fires on every policy
  decision in the dispatcher: allowed, denied, and
  review-requested (``rate-limited`` lands with Phase 80.3
  but the action value is already in the enum).  A missing
  charm_path produces no writer so tests / headless runs
  don't leave stray files in ``$CWD``.  Write failures log
  a warning rather than aborting the tool-call loop — the
  SQLite events table is the canonical record and the JSONL
  is additive (per the Phase 80.4 design).
- [x] ``cantrip audit`` CLI subcommand ships with
  ``list [--task-id X] [--action ACT] [--tool T]`` (prints
  one JSONL line per match — composes with ``grep`` /
  ``jq``) and ``export [--format jsonl|csv]`` (csv path
  JSON-encodes the ``arguments`` dict into the last column
  so the row stays rectangular even when different tools
  carry different argument shapes).
- [x] ``tests/unit/test_audit.py`` (20 tests), two
  integration tests in ``test_policy_wiring.py``, and six
  ``_audit`` CLI tests in ``test_main.py`` cover the
  round-trip, secret scrubbing, thread safety (two 50-entry
  bursts producing 100 non-interleaved lines), malformed-
  line tolerance, filter chain, and the end-to-end
  subagent → file → CLI path.

### 80.5 Medium — Juju-aware destructive-command gate ✓

- [x] ``GovernancePolicy`` gained ``approve_destructive: bool``
  with OR composition — the one field where a more-permissive
  layer wins, because the flag exists specifically to let an
  operator accept the blast radius ahead of time.  YAML loader
  accepts the key; ``policy_to_dict`` round-trips it.
- [x] ``cantrip.agent.policy.destructive_gate(tool_name,
  charm_path=None)`` returns ``(approved, reason)``.  A tool
  not in :data:`DESTRUCTIVE_TOOLS` is always approved; for a
  listed tool the gate composes ``ORG_WIDE_POLICY`` with any
  discovered user / per-charm policies and lets the call
  through only when ``approve_destructive`` is ``True``.
  Refusal reason names the composed policy stack so the Phase
  80.4 audit can trace it.
- [x] ``JujuDestroyModelTool.execute`` and
  ``JujuRemoveApplicationTool.execute`` call the gate **before**
  checking ``_juju_available()`` or running the CLI — so a
  denied call never touches the controller even when juju is
  installed.  ``juju_remove_relation`` is listed in
  :data:`DESTRUCTIVE_TOOLS` for future coverage but the tool
  class doesn't exist yet; noted so a future wrapper
  automatically inherits the gate.
- [x] ``RunCommandTool.execute`` gained
  :func:`destructive_command_check` — an argv-shape detector
  that catches ``rm -rf <path>`` (flag-order insensitive —
  ``-rf``, ``-fr``, ``-r -f``, ``--recursive --force`` all
  trip), ``git push --force`` / ``-f`` /
  ``--force-with-lease``, and ``git reset --hard``.  The gate
  consults the same policy stack; denial produces a clear
  error pointing at ``approve_destructive`` in a YAML file.
  A plain ``rm <file>`` without ``-r`` or ``-f`` still runs
  so benign single-file deletes aren't blocked.
- [x] ``tests/unit/test_destructive_gate.py`` — 10 integration
  tests covering the juju gate (blocks by default, unblocks
  with per-user opt-in, names the tool in refusals) and the
  run_command gate (all three destructive shapes blocked
  without approval, ``rm <file>`` passes the shape gate and
  actually deletes the file, ``rm -rf`` with opt-in succeeds
  end-to-end).  ``tests/unit/test_policy.py`` adds 13 tests
  covering the OR composition, the ``approve_destructive``
  YAML round-trip, and the argv shape detector across every
  destructive form.  Existing ``TestJujuDestroyModelTool``
  gains a gate-blocks-by-default case plus an
  ``_approve_destructive`` fixture so the legacy success
  paths still exercise the underlying juju logic.

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

## Phase 87: Observability Stack Follow-On — Alertmanager, Catalogue, Profiling ✓

**Goal:** Close the observability gaps that Phase 7.3 surfaced when
that phase was tied off.  Five components in the Canonical
Observability Stack are well-supported today (Prometheus, Grafana,
Loki, Tempo, Traefik) but four are not, and two distinct kinds of
gap need separate treatment:

* **Alertmanager** and **Catalogue-k8s** — both already documented
  in ``src/cantrip/skills/observability/SKILL.md`` but neither has
  integration examples, deployment guidance, or tooling.
  Alertmanager is "configure routing + a relation"; Catalogue is
  "expose a service entry on the landing page".  Both are small
  and matter for production charms.
* **Sloth (SLO management)**, **Parca**, and **Pyroscope**
  (continuous profiling) — not referenced anywhere in the
  codebase.  Larger surface; profiling in particular needs an
  agent-side reasoning story (how should the agent interpret a
  flame graph?) before any tool is useful.

### 87.1 Medium — Alertmanager guidance and tests ✓

- [x] **Alert-rules subsection added to Step 2** (publishing
  alert rules via ``MetricsEndpointProvider``'s
  ``alert_rules_path`` — the path 99% of charm authors take).
  The subsection explains that alert rules ride along the
  ``metrics-endpoint`` relation and the COS bundle wires
  Prometheus → Alertmanager automatically; charms don't relate
  to Alertmanager themselves to *publish* rules.  Worked
  example: ``src/prometheus_alert_rules/charm_health.yaml``
  with two rules (``HighWorkloadErrorRate``,
  ``HookExecutionSlow``) using the auto-injected ``juju_*``
  topology labels.
- [x] **New "Alertmanager — Routing and Receivers" section**
  added between the smoke-test pattern and the debugging
  workflow.  Covers the alert-flow diagram (rules →
  Prometheus → Alertmanager → Karma / Slack / PagerDuty), the
  ``alertmanager-k8s`` config-file shape with grouping /
  routing / receivers, Karma as the dashboard frontend, and
  the rare ``alertmanager-dispatch`` consumer side (charms
  that want to *receive* alerts — typically notification
  meta-charms).  Production routing tips section captures
  ``juju_application`` grouping, ``severity`` label
  conventions, and inhibit-rule guidance.
- [ ] **Acceptance test deferred.**  The Phase 17 harness wiring
  is non-trivial and the skill content matters first.  Open
  the acceptance-test follow-up when a real session asks for
  "production-grade alerting" and the agent picks up the new
  skill content end-to-end; the missing piece is then the
  bundle test, not the skill body.

### 87.2 Medium — Catalogue integration ✓

- [x] **Catalogue-k8s subsection added** to
  ``src/cantrip/skills/observability/SKILL.md`` between Sloth and
  the debugging workflow.  Covers what Catalogue is (the COS
  landing page), the four-field entry schema (``name``,
  ``description``, ``url``, ``icon``), the ``charmcraft.yaml``
  ``provides: catalogue`` block, and the ``CatalogueConsumer`` /
  ``CatalogueItem`` wiring.  Also added to the Key Components
  table at the top.
- [x] **Worked example included inline:** a charm that pulls its
  ``url`` from ``self._ingress.url`` (Traefik-fronted external
  URL from the ``ingress`` relation), so the Catalogue entry
  stays in sync when Traefik re-issues the route.  Re-publish
  guidance via ``_catalogue.update_item(...)`` from the ingress
  relation-changed handler is in the section.
  ``charms.catalogue_k8s.*`` flagged as not on PyPI (fetch-libs
  required).
- [x] **F8 integration graph badge.**  ``_has_catalogue_relation``
  added to ``tui/screens/graph.py``; apps with a relation on the
  ``catalogue`` interface get a ``[cat]`` suffix on their panel
  title, composing with the ``★`` highlight marker.  Two unit
  tests in ``tests/unit/test_graph.py`` cover the badge and its
  combination with the current-app highlight.

### 87.3 Low — Profiling and SLO research ✓

- [x] **Sloth fits as a skill subsection, not a tool.**  Agent's
  role is *generation at deploy time*: when a user adds
  observability, the agent also drops a small ``slos.yaml``
  covering hook-success-rate, p95 hook duration, and
  workload-availability SLOs.  Existing ``write_file`` +
  ``charmcraft.yaml`` editing tools cover it; no new ``Tool``
  needed.  The ``charmlibs-interfaces-sloth`` PyPI package
  (already documented in ``design/UPSTREAM_AUDIT.md``) is the
  schema source of truth.  Lands as new sub-phase **87.4**
  below.
- [x] **Parca / Pyroscope are tool-shaped but speculative.**  The
  natural shape mirrors :class:`TempoWaterfallTool`
  (``agent/tools/observability.py:1111``): fetch flame graph,
  render to PNG, return image + top-3-hot-path caption.  But
  charms are event-driven; profiling is rarely the bottleneck;
  the Tempo + Prometheus pair already surfaces the signals the
  agent acts on.  Defer to standalone **Phase 89** opened
  against four named triggers (charm-perf debug case, SLO
  breach, user request, or COS adoption).
- [x] Decision recorded in
  [`design/PROFILING.md`](design/PROFILING.md): tool/skill
  split, agent's role per subsystem, Phase placement, revisit
  triggers.

### 87.4 Low — Sloth skill subsection ✓

- [x] **Sloth subsection added** to
  ``src/cantrip/skills/observability/SKILL.md`` between the
  Alertmanager section and the debugging workflow.  Covers: the
  alert-flow diagram (charm → Sloth → Prometheus rules →
  Alertmanager via the same path Step 2 already wires);
  default-SLO table per workload type (12-factor: HTTP
  availability + p95 latency; infrastructure: hook-success-rate
  + p95 hook duration; custom: workload-availability with a
  tunable target); ``charmcraft.yaml`` relation block (interface
  ``slos`` per ``charmlibs-interfaces-sloth``); ``slos.yaml``
  skeleton with `{{.window}}` templating annotated; relation-
  handler stub using ``from charmlibs.interfaces import sloth``.
  Composition note explains how the burn-rate alerts route
  through the same Alertmanager ``severity`` tree from 87.1, and
  flags the retire-the-hand-written-rule pattern when an SLO
  takes over.
- [x] **Worked example** included inline: a 12-factor charm
  with two SLOs (``requests-availability`` at 99.5% / 30d and
  ``requests-latency`` at 99% / 30d), both keyed off the
  ``juju_application`` topology label so they reuse the metrics
  Step 2 already exposes.  Production tips section captures
  objective-picking, the page-vs-ticket burn-rate split, and
  the ``src/slos.yaml`` storage convention mirroring
  ``src/grafana_dashboards/``.
- [ ] **Acceptance test deferred.**  Same pattern as 87.1 — the
  Phase 17 harness wiring is non-trivial and the skill content
  matters first.  Open the acceptance follow-up when a real
  session asks for "production-grade reliability monitoring"
  end-to-end and the agent picks up the new skill content; the
  missing piece is then the bundle test, not the skill body.
  Tracked in ``design/DEFERRED.md``.

### What this phase is *not*

- Not a rewrite of the existing observability skill — Prometheus
  / Grafana / Loki / Tempo / Traefik integrations stay as they
  are.  This is additive coverage.
- Not a new TUI screen.  Alertmanager and Catalogue surface in
  prompts, skills, and (for Catalogue) the F8 graph; not in
  their own modal.

**Exit criteria:** A charm asked for "alerting + landing-page
registration + reliability monitoring" picks up Alertmanager,
Catalogue, *and* Sloth without further prompting; all three
interfaces have skill-level coverage matching the Prometheus /
Grafana baseline.  Profiling decision is recorded in
``design/PROFILING.md``; standalone Phase 89 opens against the
four triggers there if continuous profiling becomes a real need.

---

## Phase 46b: Operator Identity in Hook Payloads ✓

**Goal:** Add an optional ``operator`` field to Phase 46 hook
payloads so role-aware policy is expressible by future hook
scripts, and so adding the field is not a breaking change to
existing scripts later.  See
[`design/TEAM_COLLABORATION.md`](design/TEAM_COLLABORATION.md)
§8.2 for context.

A small forward-compatibility patch.  Existing hook scripts that
don't read ``operator`` keep working unchanged; new scripts can
branch on it (e.g. ``if: operator.email == "ada@example.org"``).

- [x] Extended the ``HookRunner.fire`` payload with an
  ``operator`` field — ``{"name": ..., "email": ...}`` populated
  from ``git config user.name`` / ``user.email``, or ``null``
  when neither is set.  Resolved via ``-C repo_root`` so the
  lookup targets the charm's repo (not the agent's CWD), and
  cached on the runner so we don't shell out twice on every tool
  call.
- [x] Field documented in ``docs/src/howto-hooks.md`` (rebuilt
  HTML committed alongside) inside the existing "Payload shape"
  section.
- [x] Tests cover: field present when git is configured, ``null``
  when unset, hooks that don't reference the field still work,
  ``if: operator.email == ...`` filters route correctly,
  resolution happens once per runner, and the real ``git config``
  pipeline runs against an isolated ``GIT_CONFIG_GLOBAL`` tmp
  config.

**Exit criteria met:** ``operator`` field documented and tested.
Existing hooks unaffected.  ``make check`` passes.  CHANGELOG
entry under "Unreleased".

---

## Phase 92: Deterministic Helpers for Existing Skills ✓

**Goal:** Phase 91 showed that deterministic helper scripts —
the kind canonical/skills ships next to its 12-factor skills —
turn LLM-reasoning loops into one-shot tool calls and remove a
slice of token cost and context pressure.  The four ports
landed against the ``twelve-factor`` skill specifically.  This
phase audits the rest of Cantrip's bundled skills and lifts
the work each one currently asks the agent to do *by reading
files and reasoning* into deterministic code where the answer
is mechanical.

The audit walked all 31 skills under
``src/cantrip/skills/`` and asked each one: is there grep-style
search, file-shape validation, schema cross-reference, or
per-rule recitation that a few hundred lines of Python would
do faster, cheaper, and without context cost?  Six skills
yielded clear "yes" answers.  The phase ships those six as
either new ``charmlint`` rule modules (the natural home for
charm-shaped lint diagnostics) or standalone Cantrip tools
(when the work is more inventory than diagnostic).

The architectural call is per-item: charmlint already covers
this sort of work for narrower rules (actions metadata
descriptions, fetch-libs PyPI presence), so extending its rule
catalogue keeps every new check on the same reporter, cache,
and CI gate.  Standalone tools earn their keep only when the
output shape (an inventory, a coverage report, a migration
checklist) does not naturally compose with charmlint's
file-by-file lint loop.

### 92.1 Charmlint extensions — handler / metadata coverage

- [x] **Action handler coverage** (extend
  ``src/charmlint/rules/actions.py``).  Every action declared
  in ``charmcraft.yaml`` should have an observer registered
  in ``src/charm.py``'s ``__init__``, and every handler should
  end in ``event.set_results(...)`` or ``event.fail(...)``.
  Today the ``adding-actions`` skill recites these rules; the
  agent then reads ``charmcraft.yaml`` and ``src/charm.py``
  every time and compares them by hand.  AST walk for the
  handler list, YAML scan for the action set, ``set_results``
  / ``fail`` regex pass over each handler body — one rule
  module, ~80 LoC, per-skill diagnostics replace per-turn
  reasoning.  Shipped as ``ACT006`` (missing observer) and
  ``ACT007`` (handler does not terminate); the ``adding-actions``
  skill body's pitfall list now points at the rules.
- [x] **Config option coverage** (extend
  ``src/charmlint/rules/config_quality.py``).  Every option in
  ``charmcraft.yaml::config.options`` should be read by
  ``self.config.get(...)`` somewhere in ``src/charm.py``;
  every config-driven path should set ``BlockedStatus`` when
  the value is invalid.  Today the ``adding-config`` skill
  guides the agent through the same checks.  YAML option set
  vs source-code regex sweep, ~100 LoC.  Shipped as
  ``CFG004`` (option declared but never read) and ``CFG005``
  (config options exist but no ``BlockedStatus`` reference);
  the ``adding-config`` skill body's pitfall list now points
  at the rules.  CFG005 is intentionally a floor (any
  ``BlockedStatus`` reference satisfies it) rather than per-
  path validation, which would need dataflow we do not have.

### 92.2 Charmlint extensions — library and relation hygiene

- [x] **Charm-library semver validator** (new
  ``src/charmlint/rules/library_versions.py``).  Walk
  ``lib/charms/*/v*/*.py``; verify ``LIBID`` / ``LIBAPI`` /
  ``LIBPATCH`` are present and shaped right; flag ``LIBPATCH``
  decreases between git history points; detect breaking
  changes (removed / renamed public names) between versioned
  files in the same library.  ``charmlint``'s existing
  ``libraries.py`` only covers PyPI fetch-libs concerns
  (``LIB001``); the metadata + semver gap is real.  AST walk
  for module-level names, ~150 LoC.  Cross-references the
  ``charm-library`` skill's authoring rules.  Shipped as
  ``LIB003`` (metadata shape — present, typed, and ``LIBAPI``
  matches the ``v<N>`` directory) and ``LIB004`` (public name
  dropped between sibling versioned files).  ``LIBPATCH``-
  decrease detection across git revisions is intentionally
  out of scope — charmlint is a static linter, and the
  ``charm-library`` skill body keeps that one as an LLM-side
  check.
- [x] **Relation-data missing-guard detector** (new
  ``src/charmlint/rules/relation_data.py``).  Every relation
  event handler that reads ``event.relation.data[event.app]``
  / ``event.relation.data[event.unit]`` should guard with an
  ``is None`` / ``in`` check, and writes to peer or app
  databags should be inside an ``is_leader`` guard.  The
  ``relation-data-design`` skill describes these rules; the
  agent currently grep-and-reasons over each handler.
  Per-handler regex over the relation-event functions, ~60
  LoC.  Shipped as ``REL001`` (subscript read without a
  ``None`` guard) and ``REL002`` (write to ``self.app``
  databag without ``is_leader()``); the
  ``relation-data-design`` skill body's pitfall list now
  points at the rules.

### 92.3 Charmlint extensions — Pebble layer validation

- [x] **Pebble layer rule module** (new
  ``src/charmlint/rules/pebble.py``).  K8s charms call
  ``container.add_layer(name, layer, combine=True)``,
  ``container.replan()``; layer dictionaries declare services
  with required keys (``override``, ``command``, ``startup``,
  ``user`` for non-root); restarts should be guarded by
  ``container.can_connect()``.  The ``custom-charm`` skill
  recites these rules in its K8s subsection — they all map
  cleanly to deterministic checks.  Pebble layer parser +
  call-site detector, ~130 LoC.  Shipped as ``PEB001``
  (``add_layer`` missing ``combine=True``), ``PEB002``
  (Pebble call without ``can_connect()`` guard, with
  ``pebble_ready`` handlers exempt), and ``PEB003`` (service
  dict missing ``override`` / ``command`` / ``startup``).
  ``user`` is intentionally not checked — the skill says "for
  non-root", which is not statically derivable.  The
  ``custom-charm`` skill body's pitfall list now points at
  the rules.

### 92.4 Standalone tools — inventory and migration

- [x] **Harness-call inventory tool** (new
  ``src/cantrip/agent/tools/harness_inventory.py``,
  ``harness_inventory`` tool).  Walk ``tests/unit/``, run the
  Harness-call regex pattern the
  ``src/cantrip/skills/harness-migration`` skill already
  spells out, return a per-file checklist of remaining
  Harness usages plus a per-file count of mixed-imports
  (``ops.testing.Harness`` and ``scenario`` imported in the
  same module).  Output shape: ``{files: [{path, harness:
  N, scenario: M, mixed: bool}], total_remaining: int}``.
  ~50 LoC.  This is *not* a lint rule because the deliverable
  is a migration checklist, not a per-file pass / fail.
  Shipped; the ``harness-migration`` skill body's "Inventory
  first" section now points at the tool.
- [x] **Scenario-test coverage probe** (new
  ``src/cantrip/agent/tools/scenario_coverage.py``,
  ``scenario_coverage`` tool).  Map every observer
  registration in ``src/charm.py`` (every
  ``self.framework.observe(self.on.<X>, self._on_<X>)``) to
  the test functions in ``tests/unit/`` that exercise it;
  return the unexercised-handler list plus an
  unexercised-event-shape list (every charm should have at
  least one test where ``container.can_connect=False`` and at
  least one where a relation is ``relation-broken``).  AST
  walk + grep, ~120 LoC.  ``pytest-cov`` measures *line*
  coverage; this measures *event-shape* coverage, which
  pytest-cov cannot see — a charm with 100% line coverage can
  still ship without a single relation-broken test.  Shipped;
  the ``scenario-tests`` skill body grew an "Auditing test
  coverage" section that points at the tool.

### What this phase is *not*

- **Not** a wholesale rewrite of charmlint.  Every new rule
  module slots into the existing rule registry; the reporter,
  cache, CI gate, and ``charmlint_tool`` agent surface stay
  as they are.
- **Not** a port from canonical/skills.  These are Cantrip-
  authored deterministic helpers derived from Cantrip's own
  skill bodies — no upstream Apache-2.0 attribution needed.
  The *philosophical* origin (Phase 91 demonstrated the
  pattern's value) belongs in the phase intro and the per-rule
  module docstring.
- **Not** a replacement for the LLM workflow guide.  Each
  helper deletes one mechanical pass the agent currently
  does; the surrounding skill body stays as the reasoning
  scaffold for *which* checks to consult and *how* to act on
  the results.
- **Not** the long tail.  The audit dismissed ``charm-debug``
  (workflow already efficient), ``observability`` (only ~3
  mechanical checks; LLM spots them in a readthrough),
  ``find-bugs`` (scope already broad enough),
  ``infrastructure-charm`` (primary / replica patterns vary
  too widely between charms to validate deterministically),
  ``performance`` (needs Tempo / Loki data, not static
  validation), ``security-review`` (human judgment), and the
  meta skills (``skill-scanner``, ``skill-writer``,
  ``iterate-fix``).  Revisit if a concrete trigger fires on
  any of those — e.g. a real infrastructure-charm pattern
  ships often enough to need its own rule.

### Per-rule module conventions

- New rule modules under ``src/charmlint/rules/`` follow the
  existing ``Rule`` subclass shape and rule-code namespace
  (``ACT###`` for actions, ``CFG###`` for config, ``LIB###``
  for library, ``REL###`` for relation, ``PEB###`` for
  Pebble).  Reuse a free code if the rule fits a category;
  add a new prefix only when the topic is genuinely new.
- Rules ship with golden-file unit tests under
  ``tests/unit/charmlint/`` covering pass and fail fixtures.
- Each rule's docstring cites the source skill section so
  future readers can trace the rule back to its prose
  origin.
- Charmlint's CI gate (``make charmlint``) keeps the new
  rules at the same severity as the existing ones — no rule
  is allowed to break the gate without being prove-ably high
  signal.

### What success looks like

When the agent enters a charm-improvement or charm-build
session, it runs ``charmlint`` once, gets every new
diagnostic alongside the existing ones, and acts on the
report without needing to re-derive any of the rules from
the skill bodies.  The ``harness-migration`` skill's
checklist becomes a one-tool invocation; the same for
``scenario-tests`` coverage probing.  Six skills shed their
"and now please grep for X across every Y" passages —
those passages either become rule-module docstrings or get
deleted.

### What shipped

All six items shipped across four commits.  Ten new
``charmlint`` rules — ``ACT006`` / ``ACT007`` (actions),
``CFG004`` / ``CFG005`` (config), ``LIB003`` / ``LIB004``
(libraries), ``REL001`` / ``REL002`` (relation data), and
``PEB001`` / ``PEB002`` / ``PEB003`` (Pebble) — plus two
new agent tools: ``harness_inventory`` and
``scenario_coverage`` (registered in
``tools/__init__.py``, surfaced in
``docs/src/reference-tools.md``).  Seven ``SKILL.md`` bodies
trimmed (``adding-actions``, ``adding-config``,
``charm-library``, ``relation-data-design``, ``custom-charm``,
``harness-migration``, ``scenario-tests``) — every "rule
recitation" passage replaced with a "run charmlint to
check" or "run ``<tool>`` to check" pointer.  38 new tests
(137 charmlint + 16 tool); ruff and ty clean.

Out-of-scope items called out and deferred at the per-item
level: ``LIBPATCH``-decrease detection across git revisions
(charmlint is static; the ``charm-library`` skill keeps that
one as an LLM-side check); ``CFG005`` as a floor rather
than per-path validation (no dataflow analysis available);
Pebble service ``user`` key (not statically derivable as
"non-root"); delegated handlers in ACT007/REL001/REL002
(handler-resolved-elsewhere returns a skip rather than a
false-positive flag).

**Exit criteria met:** all six items shipped as either a new
``charmlint`` rule module (with golden-file tests, registered
in the rule catalogue, surfaced through ``charmlint_tool``)
or a new standalone Cantrip tool (with attribution-style
docstring citing the source skill, ``ToolResult.caption``,
unit tests covering happy and gap paths, registration in
``tools/__init__.py``).  Each affected skill body has its
rule-recitation passages either deleted or trimmed to a
one-line "run ``X`` to check" pointer.  ``CHANGELOG.md``
records each helper.

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

## Phase 51b: Team Sync — Shared Memory, Decisions, Attribution ✓

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

## Phase 85: Structure and Style Sweep — Tame the Giants, Mirror the Layout ✓

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

## Phase 89: TUI File Pane — Repo Stats Sidebar ✓

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

## Phase 99: User-Facing Goal Lifecycle — Pause/Resume, Persistent Budget, Objective String ✓

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

## Phase 100: ``wait_for`` Tool — Typed Predicates Over Generic Stream Monitoring ✓

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

## Phase 101: ops-tracing Recipe Refresh — Stop Teaching the Stale ``setup`` Shorthand ✓

**Goal:** Bring Cantrip's system prompt and skill bodies up to date
with the modern ``ops-tracing>=4`` API so charms the agent writes
actually import and run, instead of failing at module load with
``AttributeError: module 'ops_tracing' has no attribute 'setup'``.

### Why now

Run-final2 + the improve-01/improve-02 enhancement passes both
emitted ``ops_tracing.setup(self)`` in ``__init__`` because the
system prompt taught that idiom verbatim:

> ops-tracing (``ops_tracing.setup(self)``) automatically instruments
> the ops framework.

The current public API in ``ops-tracing>=4`` is the ``Tracing``
class:

```python
import ops_tracing

class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self._tracing = ops_tracing.Tracing(self, "tracing")
```

The shorthand ``setup`` doesn't exist, hasn't existed for several
``ops-tracing`` releases, and the charm refuses to import.  Every
charm Cantrip writes today carries a load-time crash on the first
hook unless the operator manually rewrites the line.

### 101.1 P0 — Update the system prompt

- [x] Edit ``src/cantrip/agent/prompts/system.md.j2`` (and the
  ``system_compact.md.j2`` companion) so the tracing recipe quotes
  the ``Tracing(charm, "<relation_name>")`` constructor, not
  ``setup(self)``.  Mention that the relation name must match the
  ``tracing:`` entry under ``requires:`` in ``charmcraft.yaml``.
  (``system_compact.md.j2`` has no tracing snippet to update; the
  observability / custom-charm / charm-improvement / identity-platform /
  find-bugs skills were updated in the same pass.)
- [x] Audit subagent guidance under
  ``src/cantrip/agent/prompts/subagent/`` (``build.md``, ``demo.md``,
  ``infra.md``) for the same stale snippet and fix in place.
  (Only ``build.md`` mentions tracing and it does not quote ``setup``;
  no fix needed.)
- [x] Audit ``src/cantrip/agent/prompts/tasks/`` for any sprint /
  one-shot template that injects ``ops_tracing.setup`` text and fix
  in the same patch.  (Updated ``sprint_build.md.j2`` and
  ``improvement_fill_observability.md.j2``.)

### 101.2 P0 — Update the charmcraft injection helpers

- [x] ``_inject_ops_tracing`` in ``src/cantrip/agent/tools/charm.py``
  appends ``ops_tracing.setup(self)`` to scaffolded ``src/charm.py``
  files.  Rewrite to insert
  ``self._tracing = ops_tracing.Tracing(self, "tracing")`` instead;
  keep the ``import ops_tracing`` line as-is.
- [x] Unit tests in
  ``tests/unit/charm_tools/test_charmcraft_init.py`` that load the
  injected module under a real ``ops-tracing>=4`` import to catch a
  future API drift the same way.  (Test landed in
  ``tests/unit/charm_tools/test_ops_tracing_recipe.py`` alongside the
  Scenario-based regression test from 101.3 — the helper-output import
  check exercises the same drift.)

### 101.3 P1 — Pin the API in a regression test

- [x] One Scenario-based unit test that constructs a minimal charm,
  imports ``ops_tracing``, instantiates ``Tracing``, and runs a
  ``pebble_ready`` event — guarantees the recipe in the system prompt
  matches what ``ops-tracing`` currently exposes on PyPI.  Skip the
  test gracefully when ``ops-tracing`` isn't installed so it doesn't
  block the rest of the suite on stripped CI images.  (Lives in
  ``tests/unit/charm_tools/test_ops_tracing_recipe.py``; uses
  ``pytest.importorskip`` for ``ops-tracing`` and ``ops-scenario`` so
  stripped CI images skip cleanly.  Drives a ``start`` event rather
  than ``pebble_ready`` so the charm meta stays minimal — same
  contract guarantee.)

**Exit criteria:** A fresh sprint build under any provider produces
a charm whose ``src/charm.py`` imports cleanly under the latest
``ops-tracing`` PyPI release, the regression test in 101.3 fails
when the system prompt drifts back to ``setup``, and the relevant
charm and rock skills cite the modern constructor.

---
