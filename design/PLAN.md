# Charm Building Agent - Project Plan

## Related Design Documents

This file covers project-level decisions: conventions, workflow, the
two-loop architecture sketch, and the overall file structure.
Subsystem-level contracts live in dedicated docs:

- [AGENT.md](AGENT.md) — the two-loop agent architecture (conversation
  loop, autonomous loop), subagents, work queue, and core tools.
- [TOOLS.md](TOOLS.md) — the `Tool` ABC contract, how tools register
  and execute, `PathAwareTool` and the virtual-file store, and how to
  add or remove a tool.
- [SKILLS.md](SKILLS.md) — `SkillsIndex` and the `SKILL.md`
  frontmatter schema, the two-tier lazy-load flow, and how the skill
  index is surfaced to the LLM.
- [PROMPTS.md](PROMPTS.md) — prompt layering (system / compact /
  subagent / planning / task descriptions / skills), Jinja2
  conventions (`StrictUndefined`, template-injection guard), and
  where to add a new prompt.
- [UI.md](UI.md) — the shared TUI + Web UI event bus, layout, and
  keyboard shortcuts.
- [TERRAFORM.md](TERRAFORM.md) — Terraform module generation design.

## Project Conventions

- **Language:** UK English for all docs, variable names, comments, UI text
  - colour not color
  - behaviour not behavior
  - organisation not organization
  - analyse not analyze
  - etc.

### Code Style

**Comments:**
- Comments explain *why*, not *how*
- If you need a *how* comment, the code is probably too complex - refactor instead
- Comments are rare; docstrings are essential
- Comments are full sentences ending with punctuation.

**Imports:**
- Imports always at top of module - no lazy imports
- No conditional imports (we control dependencies)
- Import modules, not classes/methods/variables: `import datetime` not `from datetime import datetime`
- Exception: importing only for type annotations is fine

**Type annotations:**
- Modern style: `str | None` not `Optional[str]`
- Use `from __future__ import annotations` for forward references

**Error handling:**
- Never catch bare `Exception` - be specific
- Minimise code inside try/except blocks

**Data structures:**
- Prefer `dataclasses` from stdlib
- Avoid Pydantic

## Project Overview

An AI-powered **autonomous agent** specialised in building, deploying, and iterating on Juju
charms. The agent independently researches workloads, designs charms, writes code, deploys,
tests, and debugs — with the user confirming key decisions and providing domain expertise.

### Why This Project Exists

**Primary Goal:** Demonstrate how easy it is to build charms.

**Secondary Goal:** Showcase the Juju ecosystem infrastructure:
- **Juju** - The orchestration engine
- **Jubilant** - Python control of Juju
- **Charmcraft** - Charm packaging
- **Rockcraft** - OCI image building
- **Ops** - The charm framework
- **Concierge** - Environment setup
- **COS** - Observability stack

The agent proves that with this foundation, charm development is accessible. The infrastructure
does the heavy lifting; the agent drives the workflow autonomously.

```
┌────────────────────────────────────────────────────────────────────┐
│                          This Agent                                │
│              (autonomous orchestration layer)                      │
│                                                                    │
│   ┌─────────────────────┐       ┌────────────────────────────┐    │
│   │  Conversation Loop  │◄─────►│   Autonomous Work Loop     │    │
│   │  (user confirms,    │ steer/│   (research, build, deploy,│    │
│   │   overrides, guides)│ notify│    test, debug, redeploy)  │    │
│   └─────────────────────┘       └────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────┤
│  Juju │ Jubilant │ Charmcraft │ Rockcraft │ Ops │ Concierge │ COS │
│                      (durable foundation)                          │
└────────────────────────────────────────────────────────────────────┘
```

The agent is the driver. The ecosystem is the engine. The user is the navigator.

## Name

# Cantrip

*A cantrip is a small, simple spell - perfect for "quick charm in 2 minutes"*

```
   ██████╗ █████╗ ███╗   ██╗████████╗██████╗ ██╗██████╗
  ██╔════╝██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██║██╔══██╗
  ██║     ███████║██╔██╗ ██║   ██║   ██████╔╝██║██████╔╝
  ██║     ██╔══██║██║╚██╗██║   ██║   ██╔══██╗██║██╔═══╝
  ╚██████╗██║  ██║██║ ╚████║   ██║   ██║  ██║██║██║
   ╚═════╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝
```

**Tagline ideas:**
- "Small spells, big charms"
- "Conjure charms with a word"
- "Cast your charm"

## Tech Stack

| Component | Choice | Notes |
|-----------|--------|-------|
| Language | Python | |
| Package Management | uv | |
| CI | GitHub Actions | |
| TUI Framework | Textual | |
| Web UI | Vanilla HTML/CSS/JS | No framework; served from localhost via aiohttp + WebSocket (Phase 15) |
| Juju Control | Jubilant | |
| Environment Setup | Concierge | LXD for machine, "k8s" preset for K8s (Canonical K8s, not MicroK8s) |
| LLM (primary) | Gemini | Canonical preference, available tokens |
| LLM (secondary) | Claude | Best performance |
| LLM (light) | Auto-detected | Cheaper model for research/test/compaction tasks |
| Architecture | Two-loop + subagents | Conversation loop + autonomous work loop; see Architecture section |

## Core Workflow

### Step 0: Classification

The agent must first identify which charm path applies:

```
User: "build a charm for X"
           │
           ▼
    ┌──────────────┐
    │ Classify X   │
    └──────┬───────┘
           │
     ┌─────┼─────────────────┐
     │     │                 │
     ▼     ▼                 ▼
┌────────┐ ┌──────────┐ ┌─────────────┐
│12-factor│ │ Custom   │ │Infrastructure│
│  PaaS   │ │   App    │ │  (MariaDB,  │
│(Flask,  │ │          │ │  Redis...)  │
│Django,  │ │          │ │             │
│Go...)   │ │          │ │             │
└────┬────┘ └────┬─────┘ └──────┬──────┘
     │           │              │
     ▼           ▼              ▼
  FAST PATH   MEDIUM PATH    COMPLEX PATH
  Use paas-   Full custom    Needs ops
  charm base  scaffolding    knowledge
```

### Machine vs K8s Decision

If user doesn't specify:

```
┌─────────────────────────────┐
│  Analyse workload           │
│  - Existing OCI image?      │
│  - Cloud-native design?     │
│  - Needs bare metal/GPU?    │
│  - Legacy dependencies?     │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Agent makes recommendation │
│  with reasoning             │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  "I'd suggest K8s because   │
│   there's an official OCI   │
│   image. Confirm?"          │
└─────────────────────────────┘
```

Agent decides based on workload characteristics, asks user to confirm.

### Environment Setup (Concierge)

| Charm Type | Concierge Preset | Notes |
|------------|------------------|-------|
| Machine | LXD | Default for machine charms |
| K8s | `k8s` | Canonical K8s, NOT MicroK8s |

Agent uses concierge to set up the appropriate environment automatically.

### Multi-Model Management

Cantrip manages multiple Juju models - user doesn't do setup:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cantrip-managed models                      │
│                                                                 │
│  ┌─────────────────────┐      ┌─────────────────────┐          │
│  │   dev model         │      │   cos model         │          │
│  │                     │      │                     │          │
│  │  ┌─────────────┐    │      │  ┌─────┐ ┌─────┐   │          │
│  │  │ charm under │────┼──────┼──│Tempo│ │Loki │   │          │
│  │  │ development │    │traces│  └─────┘ └─────┘   │          │
│  │  └─────────────┘    │ logs │  ┌─────┐ ┌─────┐   │          │
│  │                     │metrics  │Prom │ │Graf │   │          │
│  └─────────────────────┘      │  └─────┘ └─────┘   │          │
│                               └─────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

Cross-model relations handle observability data flow.

### Path A: 12-Factor PaaS Apps (Fast Path)

Supported frameworks: Flask, Django, Go, FastAPI(?), others TBD

```
┌─────────────────────────────────────┐
│  1. Detect framework from codebase  │
│  2. Use paas-charm base             │
│  3. Generate rockcraft.yaml         │
│  4. Build rock + deploy             │
└─────────────────────────────────────┘
```

*Details on 12-factor charm system to be provided*

### K8s OCI Image Strategy

```
Need OCI image for K8s charm
          │
          ▼
┌──────────────────────┐
│ Search for existing  │
│ (Docker Hub, GHCR,   │
│  upstream registry)  │
└──────────┬───────────┘
           │
     ┌─────┴─────┐
     │           │
   Found?     Not found
     │           │
     ▼           │
┌─────────┐      │
│ Test it │      │
└────┬────┘      │
     │           │
  ┌──┴──┐        │
Works? Broken/   │
  │   needs      │
  │   changes    │
  │      │       │
  ▼      └───┬───┘
 USE IT      │
             ▼
      ┌─────────────┐
      │ Build rock  │
      │ (rockcraft) │
      └─────────────┘
```

**Agent needs:**
- Search OCI registries (Docker Hub, GHCR, Quay, upstream)
- Evaluate image suitability (right version, maintained, security)
- Rockcraft knowledge for building rocks when needed

### Path B: Custom Application

```
┌─────────────────────────────────────┐
│  1. Analyse app requirements        │
│     - How does it run?              │
│     - What does it need?            │
│     - Config, ports, storage?       │
│  2. Full charm scaffolding          │
│  3. Iterative refinement            │
└─────────────────────────────────────┘
```

### Path C: Infrastructure Software

```
┌─────────────────────────────────────┐
│  1. Research the software           │
│     - Docs, best practices          │
│     - Clustering, HA patterns       │
│  2. Check for existing charms       │
│     - Maybe extend/fork?            │
│  3. Complex operational logic       │
│     - Backups, scaling, failover    │
└─────────────────────────────────────┘
```

### Common Steps (All Paths) — Autonomous Task Pipeline

Once the charm path is identified, the agent autonomously plans and executes
a task pipeline. The user sees a live checklist in the TUI and confirms key
decisions (e.g. the design proposal) but does not drive each step.

```
User: "build a charm for X"
           │
           ▼
    ┌──────────────┐
    │ Task Planner │  LLM decomposes intent into ordered tasks
    └──────┬───────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Work Queue (visible as checklist in TUI)                        │
│                                                                  │
│  ✓ Set up environment (concierge prepare)                        │
│  ✓ Clone and analyse source code                                 │
│  ✓ Research workload (web search, docs, best practices)          │
│  ✓ Survey Charmhub for existing charms / libraries               │
│  ◌ Present design proposal ← blocks on user confirmation         │
│  ○ Scaffold charm                                                │
│  ○ Deploy to dev model                                           │
│  ○ Add observability (COS integration)                           │
│  ○ Run unit tests                                                │
│  ○ Add integrations (database, ingress, etc.)                    │
│  ○ Run integration tests                                         │
│  ○ Validate (pack + full test suite + status check)              │
│                                                                  │
│  Legend: ✓ done  ⟳ active  ○ pending  ◌ blocked  ✗ failed        │
└──────────────────────────────────────────────────────────────────┘
           │
           │  Background executor picks next ready task,
           │  runs it (LLM + tools), records result, repeats.
           │
           │  Watcher events insert new tasks (e.g. "hook failed → diagnose")
           │  User messages can reprioritise, cancel, or add tasks.
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Auto-deploy loop                                                │
│                                                                  │
│  Code changed → pack/sync → deploy → verify status               │
│       ▲                                        │                 │
│       │              ┌───────────┐             │                 │
│       └──── fix ◄────│  Watcher  │◄── detect ──┘                 │
│                      │  (events) │                               │
│                      └───────────┘                               │
└──────────────────────────────────────────────────────────────────┘
```

## TUI Design (Textual)

The TUI has three panels: task checklist (what the agent is doing), Juju status
(current state of the deployment), and chat (conversation with the user). The
task checklist is the primary way the user understands agent activity.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Cantrip v0.1.0                                [dev:k8s] [cos:k8s] [F1 Help]│
├──────────────────────┬──────────────────┬───────────────────────────────────┤
│                      │                  │                                   │
│  Tasks               │  Juju Status     │  Chat                             │
│  ─────               │  ───────────     │  ────                             │
│                      │                  │                                   │
│  ✓ Set up environ.   │  Model: dev (k8s)│  > build a charm for redis       │
│  ✓ Clone + analyse   │  Apps: 1         │                                   │
│  ✓ Research Redis    │                  │  Researching Redis operational    │
│    operations        │  ┌────────────┐  │  patterns...                      │
│  ✓ Survey Charmhub   │  │ redis-k8s  │  │                                   │
│  ✓ Design proposal   │  │ ⟳ waiting  │  │  I've researched how Redis is     │
│  ✓ Scaffold charm    │  │ 1 unit     │  │  typically operated. Here's my    │
│  ⟳ Deploy to dev     │  └─────┬──────┘  │  proposed design:                 │
│  ○ Add observability │        │ cos     │                                   │
│  ○ Run unit tests    │        ▼         │  • K8s charm (official OCI image) │
│  ○ Add integrations  │  ┌────────────┐  │  • Primary/replica with Sentinel  │
│  ○ Integration tests │  │ COS (6)    │  │  • AOF persistence by default     │
│  ○ Validate          │  │ ● healthy  │  │  • Backup action via redis-cli    │
│                      │  └────────────┘  │  • COS + ingress integrations     │
│                      │                  │                                   │
│                      │                  │  Shall I proceed with this, or     │
│                      │                  │  would you like to adjust?         │
│                      │                  │                                   │
│                      │                  │  [Type your message...]            │
│                      │                  │                                   │
├──────────────────────┴──────────────────┴───────────────────────────────────┤
│  [⟳ Deploying redis-k8s] [● COS healthy] [👁 Watching]                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## The "2-Minute Charm" Definition

**Goal:** From "build a charm for X" to the agent autonomously working through the full
pipeline — research, design, build, deploy, test, observe — with the user only confirming
the design proposal.

Success looks like:
- Agent researched the workload and proposed a grounded design
- User confirmed (or adjusted) the design
- Charm packed, deployed, and reaching **active/running**
- Observability wired up
- Tests passing
- All visible as a completed checklist in the TUI

The user's involvement: one sentence to start, one confirmation to approve the design,
optional steering if something looks wrong. The agent does the rest.

**Philosophy:** The agent drives. The user navigates.

## Key Features

### Done (Phases 0–3)
- [x] **All three charm paths** — 12-factor PaaS, custom applications, infrastructure
- [x] Pack and deploy to local environment (LXD/Canonical K8s)
- [x] Juju status display in TUI
- [x] Conversational iteration (add actions, config)
- [x] Gemini + Claude LLM providers with cost-routed light model
- [x] Multi-model management (dev + COS) with cross-model relations
- [x] Observability integration (ops-tracing, Tempo, Loki queries)
- [x] Test generation (Scenario unit, Jubilant integration)
- [x] Event-driven watcher (status diffing + Loki polling)
- [x] Fast dev cycle (juju ssh sync + full pack/refresh)
- [x] Context compaction (virtual files algorithm)
- [x] Git + GitHub tools, skills infrastructure, session persistence

### Done (Phase 4: Autonomous Core)
- [x] **Work queue and task planner** — LLM decomposes user intent into ordered tasks
- [x] **Background executor** — tasks run autonomously via subagents
- [x] **Task checklist widget** — live TUI panel showing all task status with expandable detail
- [x] **Auto-deploy loop** — build → deploy → verify → diagnose, automatically
- [x] **Watcher → task queue** — events create tasks, not raw messages
- [x] **User steering** — executor pauses during user interaction; manage_tasks tool for cancel/reprioritise

### Then (Phase 5: Research-Driven Design)
- [ ] **Proactive workload research** — web search for devops best practices
- [ ] **Operational story discovery** — how does this software run, scale, fail, recover?
- [ ] **Design proposals** — agent presents grounded design, user confirms/overrides
- [ ] **Research → build pipeline** — confirmed design feeds into task planner

### Later (Phase 6: Polish)
- [ ] Visual model/app/integration graph
- [ ] Log viewer, trace viewer
- [ ] Advanced testing (load, fuzz, chaos, scaling)
- [ ] Charmhub publishing

## Observability Strategy

**Key insight:** The agent doesn't just add observability - it *uses* observability to develop the charm. Traces help the agent understand what's happening.

### Minimum (Always)
- **ops-tracing** for the charm itself
- Agent can query traces to debug charm behaviour
- Ideally trace the workload too

### Full Stack (COS/COS-lite)
Deploy to local environment, agent uses it during development:

| Component | Purpose |
|-----------|---------|
| Tempo | Distributed tracing - agent queries this |
| Loki | Log aggregation |
| Prometheus | Metrics collection |
| Grafana | Visualisation |
| Alertmanager | Alert routing |
| catalogue-k8s | Service catalog |

### Development Workflow with Observability

```
┌─────────────────────────────────────────────────────────┐
│                    Local Environment                     │
│  ┌─────────────┐      ┌─────────────────────────────┐   │
│  │ Charm under │─────▶│         COS-lite            │   │
│  │ development │traces│  ┌─────┐ ┌────┐ ┌──────┐   │   │
│  │             │logs  │  │Tempo│ │Loki│ │Prom  │   │   │
│  │ (ops-tracing│metrics  └──┬──┘ └─┬──┘ └──┬───┘   │   │
│  │  integrated)│      │     │      │       │       │   │
│  └─────────────┘      │     └──────┴───────┘       │   │
│                       │            │               │   │
│                       │      ┌─────▼─────┐         │   │
│                       │      │  Grafana  │         │   │
│                       │      └───────────┘         │   │
│                       └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │   Agent queries   │
                    │   Tempo/Loki to   │
                    │   understand charm│
                    │   behaviour        │
                    └───────────────────┘
```

### Setup & Usage

- **Auto-deploy COS-lite** as part of local environment setup (not optional)
- **Query Tempo/Loki** for traces and logs (primary debugging method)
- **Fallback to debug-log** via jubilant when needed
- **Link to Grafana** for visualisation - don't replicate in TUI initially
- Agent uses observability *internally* to debug - user doesn't need to look at traces

*Links and skills for COS to be provided later*

## User/Agent Division of Labour

```
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│           USER                  │    │           AGENT                 │
├─────────────────────────────────┤    ├─────────────────────────────────┤
│                                 │    │                                 │
│  • Name the workload            │    │  • Research the workload        │
│    "build a charm for Redis"    │    │    (web search, docs, Charmhub) │
│                                 │    │  • Discover operational story   │
│  • Confirm or override design   │    │    (best practices, failure     │
│    "yes, but skip Sentinel      │    │     modes, scaling patterns)    │
│     for now"                    │    │  • Propose a design             │
│                                 │    │  • Scaffold the charm           │
│  • Provide domain expertise     │    │  • Write the code               │
│    when asked                   │    │  • Deploy and redeploy          │
│    "we use pgBackRest for       │    │  • Debug issues (using traces)  │
│     backups, not pg_dump"       │    │  • Write and run tests          │
│                                 │    │  • Add integrations             │
│  • Steer priorities             │    │  • React to watcher events      │
│    "focus on HA before          │    │  • Iterate until working        │
│     backup actions"             │    │  • Keep the checklist moving    │
│                                 │    │                                 │
└─────────────────────────────────┘    └─────────────────────────────────┘
```

**Philosophy:** The agent is both the researcher and the implementer. It proactively
discovers how the workload should be operated (via web research and ecosystem knowledge),
proposes a grounded design, and builds it. The user confirms, overrides, and provides
domain expertise that the agent can't find online. The user should rarely need to say
"now do X" — the agent's task queue handles sequencing.

## Integration Discovery

When the agent needs to suggest integrations (database, ingress, observability, etc.):

```
┌─────────────────────────────────────┐
│  Query Charmhub                     │
│  (via API or charmcraft, not HTTP)  │
│                                     │
│  • Always current                   │
│  • No stale curated lists           │
│  • Discovers new charms             │
└─────────────────────────────────────┘
```

**Why Charmhub API/charmcraft:**
- Stay current without updating the agent
- Discover newly published charms
- Get accurate compatibility info
- Avoid maintaining a curated list that goes stale

### Default Integrations

**Philosophy:** Show off the Canonical ecosystem. Add all integrations that make sense for the workload.

| Integration | When | Notes |
|-------------|------|-------|
| **Observability (COS)** | Always | Grafana, Prometheus, Loki, Tempo, Alertmanager |
| **Database** | Almost always | Support multiple if workload does (e.g., both MySQL and PostgreSQL) |
| **Ingress** | K8s, almost always | Typically Traefik |
| **Sloth** | When relevant | SLO management |
| **Parca** | When relevant | Continuous profiling |
| **Pyroscope** | When relevant | Profiling |
| **Identity** | When workload needs auth | Identity management |
| **Litmus** | For testing | Chaos testing |

If workload supports multiple options (e.g., mysql OR postgresql), charm should support all of them automatically.

## Architecture: Two-Loop Autonomous Agent

### Design Decision

Phases 0–3 built a reactive single-agent architecture: user sends a message, agent responds.
This worked for proving out tools and conversation, but does not match the product vision
where the agent works independently and the user mostly confirms.

The architecture is now **two concurrent loops** sharing a work queue, with **subagents**
executing background tasks.

### Runtime Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CantripAgent                                  │
│                                                                         │
│  ┌───────────────────────┐              ┌────────────────────────────┐  │
│  │   Conversation Loop   │    steer/    │    Autonomous Work Loop    │  │
│  │                       │◄────────────►│                            │  │
│  │  Handles user chat    │    notify    │  Picks tasks from queue    │  │
│  │  Presents proposals   │              │  Spawns subagents          │  │
│  │  Collects decisions   │              │  Records results           │  │
│  └───────────┬───────────┘              └─────────────┬──────────────┘  │
│              │                                        │                 │
│              │         ┌──────────────────┐            │                 │
│              └────────►│   Work Queue     │◄───────────┘                 │
│                        │                  │                              │
│                        │  AgentTask list  │◄──── Watcher events          │
│                        │  with deps and   │◄──── User steering           │
│                        │  status tracking │◄──── Adaptive replanning     │
│                        └────────┬─────────┘                              │
│                                 │                                        │
│              ┌──────────────────┼──────────────────┐                    │
│              ▼                  ▼                   ▼                    │
│  ┌───────────────────┐ ┌──────────────┐ ┌────────────────────┐         │
│  │ Research Subagent │ │Build Subagent│ │ Test/Debug Subagent│         │
│  │                   │ │              │ │                    │         │
│  │ Focused prompt,   │ │ Full charm   │ │ Runs tests, reads │         │
│  │ web + Charmhub    │ │ writing with │ │ traces/logs, fixes│         │
│  │ tools, light model│ │ all tools,   │ │ issues, light     │         │
│  │                   │ │ primary model│ │ model              │         │
│  └───────────────────┘ └──────────────┘ └────────────────────┘         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Work Queue

The `WorkQueue` is the central coordination mechanism. It holds `AgentTask` objects with:
- **id** — unique identifier
- **title** — human-readable, shown in the TUI checklist
- **status** — pending, active, done, failed, blocked
- **category** — research, build, deploy, test, debug, infra
- **dependencies** — list of task IDs that must complete first
- **result** — summary of what the task produced (for context handoff)

The task planner (an LLM call) generates the initial task list from user intent. Tasks can
be added, reordered, or cancelled at any time — by the planner (adaptive replanning), by the
watcher (events create new tasks), or by the user (steering via chat).

### Subagent Pattern

Each background task runs as a **subagent**: a fresh LLM context with a focused system prompt
and a subset of tools. Subagents are disposable — they execute one task, return a result
summary, and are discarded.

**Why subagents, not the main agent?**
- Main agent context stays clean for conversation and design decisions.
- Subagents get focused context (just the task, relevant files, prior results).
- Different tasks can use different models (research on light, code on primary).
- Subagents can run while the user is chatting with the main agent.

**Cost routing:**

| Task category | Model | Rationale |
|---------------|-------|-----------|
| Research (web search, Charmhub) | Light | High volume, low complexity |
| Test running, log queries | Light | Structured output, doesn't need creativity |
| Charm code writing | Primary | Needs best reasoning |
| Design proposal | Primary | User-facing, needs quality |
| Context compaction | Light | Already implemented |

### Conversation ↔ Work Queue Coordination

The two loops coordinate through the work queue:

1. **Task needs user input** — the task enters `blocked` status and the conversation loop
   posts a question in the chat. User's reply unblocks the task.
2. **User sends a message** — if it's steering ("skip database integration for now"), the
   conversation loop updates the work queue (cancels/reorders tasks). If it's new context
   ("it also needs Redis caching"), the planner inserts new tasks.
3. **Watcher detects an issue** — a new task is created in the queue (e.g. "diagnose hook
   failure in redis-k8s/0"). The executor picks it up when ready.
4. **Task completes** — result summary is stored; dependent tasks unblock; TUI updates.

### Migration from Current Architecture

The current `process_message()` loop (reactive, single-agent) continues to handle
conversation. The new work loop runs alongside it. The watcher, which currently injects
raw event text into `process_message()`, is migrated to create tasks in the queue instead.

Existing tools and skills are reused — subagents call the same `Tool` instances.
The `ContextManager` and virtual file store are shared (subagents can virtualise large
results). The `SessionStore` gains a `tasks` table for persistence.

## No Shell Access

Cantrip deliberately does **not** provide a general-purpose shell or bash tool. Every capability the agent has is exposed through a purpose-built tool with typed parameters, structured output, and scoped permissions. This is a conscious safety and design choice:

- **Prompt-injection containment.** Without a shell escape hatch, a prompt-injection attack cannot escalate to arbitrary command execution. The agent can only do what its tools allow.
- **Domain scoping.** Cantrip is a charm-building agent, not a general coding assistant. Its tools cover file operations, charm operations, Juju, Rockcraft, Git, and GitHub — everything needed for the charm development workflow, nothing more.
- **Auditability.** Every action the agent takes is a named tool call with typed arguments, making it straightforward to log, review, and restrict.

When a new CLI capability is needed (e.g. `git`, `gh`, `charmcraft`), the correct approach is always to add a dedicated tool — never to introduce a general-purpose shell.

## Testing Strategy

### Unit Tests: Scenario

Use `ops.testing` (Context, State, etc.) - the modern approach.

```python
from ops import testing


def test_start():
    ctx = testing.Context(MyCharm)
    state = testing.State()
    out = ctx.run(ctx.on.start(), state)
    assert out.unit_status == testing.ActiveStatus()
```

**NOT:** Harness (legacy, deprecated)

### Integration Tests: Jubilant

Use Jubilant for real Juju integration tests.

**NOT:** pytest-operator, python-libjuju

### Setup

`charmcraft init` scaffolds the test structure. Agent runs this as part of charm creation.

*Links to Scenario and Jubilant docs to be added*

## Development Cycle

### Fast Path (via juju ssh)

For rapid iteration, agent can update charm code directly on the unit:

```
┌─────────────────────────────────────────────┐
│  Edit code locally                          │
│          │                                  │
│          ▼                                  │
│  juju ssh <unit> "cat > /path/to/charm.py"  │
│          │                                  │
│          ▼                                  │
│  Trigger hook (juju run, config change)     │
│          │                                  │
│          ▼                                  │
│  See result immediately                     │
└─────────────────────────────────────────────┘
```

**Use for:** Quick iterations, debugging, experimenting

### Full Path (pack + refresh)

```
┌─────────────────────────────────────────────┐
│  charmcraft pack                            │
│          │                                  │
│          ▼                                  │
│  juju refresh --path ./charm.charm          │
│          │                                  │
│          ▼                                  │
│  Wait for upgrade                           │
└─────────────────────────────────────────────┘
```

**Use for:**
- Validating the full build process works
- Testing charmcraft.yaml changes
- Before committing/publishing
- Periodically to ensure charm packs correctly

### Agent Strategy

Agent should:
1. Default to fast path during active development
2. Periodically do full pack+refresh to catch issues
3. Always do full path before declaring "done"
4. Switch to full path when changing metadata/config/actions

## Charm Libraries

### Strategy

1. **Prefer PyPI versions** where libraries have migrated from Charmhub
   - List of migrated libraries to be provided
   - Add to pyproject.toml / requirements.txt

2. **Charmhub libraries** for those still there
   - Add to `charmcraft.yaml` lib section
   - Run `charmcraft fetch-libs`

3. **Auto-fetch common interface libs**
   - database interfaces
   - ingress
   - observability (tracing, metrics, logging)
   - etc.

### Workflow

```
Agent identifies needed integration
          │
          ▼
┌─────────────────────────┐
│ Is there a PyPI version?│
└───────────┬─────────────┘
            │
      ┌─────┴─────┐
      │           │
     YES          NO
      │           │
      ▼           ▼
  Add to      Add to
  pyproject   charmcraft.yaml
  .toml       + fetch-libs
```

*List of PyPI-available libraries to be provided*

## Persistence

### Auto-persistence within charm folder

```
my-charm/
├── src/
├── tests/
├── charmcraft.yaml
├── ...
└── .cantrip                   # SQLite database (session, decisions, token usage)
```

When user runs `cantrip` in a charm directory:
1. Detect `.cantrip` database
2. Load previous session context
3. Resume where they left off

### Context Management

LLM context windows are finite. Strongly considering the "virtual files" compaction algorithm
from [Will Larson's write-up](https://lethain.com/agents-context-compaction/):

1. **Token budget tracking** — after every user message (including tool responses), inject a
   system message showing consumed vs available tokens and the current list of "virtual files".

2. **Large-message virtualisation** — any user message or tool response over 10,000 tokens is
   stored as a virtual file; only the first 1,000 tokens are kept inline. The agent uses file
   manipulation tools to read the rest on demand.

3. **Base tools** — a set of always-available internal tools, including virtual file read/search,
   so that every agent can operate with mostly-invisible internal tooling.

4. **Compaction at 80 %** — when a message pushes the context past 80 % of the model's window
   (configurable), run a compaction prompt (the one Reddit attributes to Claude Code is a
   reasonable starting point). After compacting, save the prior context window as a virtual file
   so the agent can retrieve lost detail.

5. **`file_regex` tool** — let the agent run regex searches against files, including the saved
   prior-context virtual file, to recover specific information after compaction.

Additional principles (retained from earlier design):
- Track key decisions separately (always in context)
- Background agents get focused context (just what they need)

## Knowledge Sources

### Primary Reference
- https://github.com/tonyandrewmeyer/charming-with-claude
  - `claude-instructions/` - reusable guidance, commands, skills, settings
  - `CLAUDE.md` - detailed charm development guidance
  - `experiments/` - documented lessons learned
  - Incorporate into Cantrip's system prompts

### Additional (to be provided)
- Scenario documentation
- Jubilant documentation
- 12-factor PaaS charm system details
- COS integration patterns
- List of PyPI-migrated libraries
- Best practices from Canonical charm tech team

### Domain Expert
User works on the Charm Tech team at Canonical - responsible for docs and tools. Will provide guidance throughout development.

## Skills Architecture

Use the [Agent Skills](https://agentskills.io/home) pattern for modular, lazy-loaded knowledge.

### Design Principles

1. **Lightweight index always loaded** - Agent knows what skills exist (name + brief description) without loading full content
2. **Full skill loaded on demand** - Only fetch complete skill document when actually needed
3. **Interoperability** - Skills can be shared with other agent systems; we can use external skills, others can use ours

### Example Skills

| Skill | Description |
|-------|-------------|
| `relation-data-design` | How to design and implement relation data bags |
| `scenario-tests` | Writing unit tests with ops.testing (Scenario) |
| `jubilant-tests` | Writing integration tests with Jubilant |
| `spread-tests` | Writing spread tests for multi-substrate testing |
| `observability` | Adding COS integration, ops-tracing, metrics |
| `ingress` | Configuring ingress with Traefik |
| `adding-actions` | Implementing charm actions properly |
| `adding-config` | Config options with validation |
| `machine-charms` | Machine charm specific patterns |
| `k8s-charms` | Kubernetes charm specific patterns |
| `rockcraft` | Building OCI images with Rockcraft |

### Benefits

- **Context efficiency** - Don't bloat system prompt with everything
- **Easy updates** - Update a skill without touching agent core
- **Shareable** - Other teams/agents can use our charm skills
- **Extensible** - Add new skills as patterns emerge

### Could Have
- [x] Multiple LLM providers (Gemini + Claude, done)
- [x] Rock building for OCI images (done)
- [ ] Charm library suggestions (PyPI vs Charmhub, partially in prompt)
- [ ] Auto-integration recommendations (partially in prompt, needs research-driven grounding)

### Explicitly Out of Scope
- Bundles (deprecated)
- pytest-operator / python-libjuju (use Jubilant instead)
- Harness (use Scenario instead)

## Open Questions

See `QUESTIONS.md` (in this directory) for items needing clarification.

## File Structure

```
cantrip/
├── pyproject.toml
├── uv.lock
├── src/
│   └── cantrip/
│       ├── __init__.py
│       ├── main.py               # Entry point, arg parsing
│       ├── cli.py                # CLI mode (no TUI)
│       ├── agent/
│       │   ├── core.py           # CantripAgent — conversation loop, tool execution
│       │   ├── state.py          # AgentState, Decision, TestResults dataclasses
│       │   ├── store.py          # SQLite-backed session store
│       │   ├── skills.py         # Skills index and loading
│       │   ├── context.py        # Context compaction, virtual file store
│       │   ├── preflight.py      # Pre-flight environment checks (Concierge)
│       │   ├── watcher.py        # Event-driven watcher (status diffing, Loki polling)
│       │   ├── queue.py          # ← NEW: WorkQueue, AgentTask, task lifecycle
│       │   ├── planner.py        # ← NEW: Task planner (LLM decomposes intent → tasks)
│       │   ├── executor.py       # ← NEW: Background executor (picks tasks, runs subagents)
│       │   ├── subagent.py       # ← NEW: Subagent runner (isolated LLM context per task)
│       │   ├── tools/            # Agent tools (file ops, charm ops, juju, git, web)
│       │   └── prompts/          # System prompts (Jinja2 templates + builders)
│       ├── llm/
│       │   ├── base.py           # Abstract LLMProvider interface
│       │   ├── gemini.py         # Google Gemini implementation
│       │   └── claude.py         # Anthropic Claude implementation
│       ├── charm/
│       │   └── templates/        # Charm project templates
│       ├── skills/               # Skill definitions (SKILL.md per skill)
│       ├── tui/
│       │   ├── app.py            # Main Textual app (CantripApp)
│       │   ├── cantrip.tcss      # Textual CSS
│       │   ├── screens/          # TUI screens (help, etc.)
│       │   └── widgets/
│       │       ├── chat.py       # Chat panel
│       │       ├── status.py     # Juju status panel
│       │       ├── statusbar.py  # Bottom status bar
│       │       └── tasklist.py   # ← NEW: Task checklist widget
│       └── juju/                 # Juju integration via Jubilant
├── tests/
├── docs/
└── .github/
    └── workflows/
```
