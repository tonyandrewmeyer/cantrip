# Charm Building Agent - Project Plan

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

An AI-powered agent specialised in building, deploying, and iterating on Juju charms. The agent encapsulates operational knowledge and makes charm development accessible through natural conversation.

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

The agent proves that with this foundation, charm development is accessible. The infrastructure does the heavy lifting; the agent just makes it conversational.

```
┌─────────────────────────────────────────────────────────────────┐
│                         This Agent                              │
│                    (conversational layer)                       │
├─────────────────────────────────────────────────────────────────┤
│  Juju │ Jubilant │ Charmcraft │ Rockcraft │ Ops │ Concierge    │
│                    (durable foundation)                         │
└─────────────────────────────────────────────────────────────────┘
```

The agent is thin. The ecosystem is the star.

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
| Juju Control | Jubilant | |
| Environment Setup | Concierge | LXD for machine, "k8s" preset for K8s (Canonical K8s, not MicroK8s) |
| LLM (primary) | Gemini | Canonical preference, available tokens |
| LLM (secondary) | Claude | Best performance |
| LLM (future) | TBD | Figure out when we get there |
| Multi-agent? | TBD | See Architecture section |

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

### Common Steps (All Paths)

```
    │
    ▼
┌─────────────────────────────┐
│  Auto-deploy locally        │
│     - concierge setup env   │
│     - jubilant deploy       │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  Background tasks           │
│     - Add tests             │
│     - Add observability     │
│     - Infrastructure setup  │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  Interactive iteration      │
│     - Add actions           │
│     - Add config options    │
│     - Add integrations      │
│     - Debug issues          │
└─────────────────────────────┘
```

## TUI Design (Textual)

```
┌─────────────────────────────────────────────────────────────────┐
│  Cantrip                                          [model: lxd]  │
├─────────────────────────────────────────────────────────────────┤
│                           │                                     │
│   Juju Status             │   Chat                              │
│   ─────────────           │   ────                              │
│                           │                                     │
│   Model: dev              │   > build a charm for postgres      │
│   ┌─────────┐             │                                     │
│   │ my-app  │────────┐    │   Creating postgres-charm...        │
│   │ active  │        │    │   ✓ Scaffolded charm structure      │
│   └─────────┘        │    │   ✓ Deploying to lxd model          │
│        │             │    │   ⟳ Adding observability...         │
│        │ db          │    │                                     │
│        ▼             │    │                                     │
│   ┌─────────┐        │    │                                     │
│   │postgres │        │    │                                     │
│   │ active  │        │    │                                     │
│   └─────────┘        │    │                                     │
│        │             │    │                                     │
│        │ metrics     │    │                                     │
│        ▼             │    │                                     │
│   ┌─────────┐        │    │                                     │
│   │ grafana │◄───────┘    │                                     │
│   │ active  │  dashboard  │                                     │
│   └─────────┘             │                                     │
│                           │                                     │
├───────────────────────────┴─────────────────────────────────────┤
│ [F1 Help] [F2 Status] [F3 Logs] [F4 Debug]           [q Quit]   │
└─────────────────────────────────────────────────────────────────┘
```

## The "2-Minute Charm" Definition

**Goal:** From "build a charm for X" to seeing this in the TUI:
- Charm packed successfully
- Deployed to local model
- Status: **active**
- Workload: **running**

That's it. That's success. Everything else happens *after* in the iterative conversation:
- Health checks
- Config options
- Actions
- Integrations
- Observability
- Tests

**Philosophy:** Get something real running fast, then improve it through conversation.

## Key Features

### Must Have (MVP)
- [ ] **Path A: 12-factor PaaS** (primary focus)
- [ ] Pack and deploy to local environment (LXD/Canonical K8s)
- [ ] Achieve active/running status
- [ ] Juju status display in TUI
- [ ] Conversational iteration (add actions, config)
- [ ] Gemini API integration
- [ ] Multi-model management (dev + COS)

### Rapid Follow-on (not Stage 2 - move fast)
- [ ] Path B: Custom applications
- [ ] Path C: Infrastructure software

### Should Have
- [ ] Visual model/app/integration graph
- [ ] Observability integration (see below)
- [ ] Debug mode with log viewing
- [ ] Machine charm support
- [ ] K8s charm support
- [ ] Test generation (Scenario for unit, Jubilant for integration)
- [ ] Cross-model relations (especially for COS)

### Stage 2
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

## User/Agent Division of Labor

```
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│           USER                  │    │           AGENT                 │
├─────────────────────────────────┤    ├─────────────────────────────────┤
│                                 │    │                                 │
│  • Describe what to charm       │    │  • Scaffold the charm           │
│  • Provide operational knowledge│    │  • Write the code               │
│    - How should it scale?       │    │  • Debug issues (using traces)  │
│    - What needs backup?         │    │  • Write tests                  │
│    - Failure modes?             │    │  • Add integrations             │
│  • Approve/reject agent choices │    │  • Query observability          │
│  • Guide priorities             │    │  • Iterate until working        │
│                                 │    │                                 │
│  "It should have 3 replicas     │    │  (looks at Tempo traces)        │
│   with automatic failover"      │    │  "I see the replica sync is     │
│                                 │    │   failing, fixing..."           │
└─────────────────────────────────┘    └─────────────────────────────────┘
```

**Philosophy:** User is the domain expert (knows how the app should operate). Agent is the implementation expert (knows how to make Juju do that).

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

## Architecture: Single vs Multi-Agent

### Option A: Single Agent

```
┌─────────────────────────────────────────────┐
│              Main Agent                     │
│                                             │
│  • Handles all conversation                 │
│  • Scaffolds charms                         │
│  • Debugs issues                            │
│  • Writes tests                             │
│  • Manages integrations                     │
│  • Everything in one context                │
│                                             │
└─────────────────────────────────────────────┘
```

**Pros:**
- Simpler to implement
- Full context always available
- No coordination overhead
- Easier to debug the agent itself
- One set of prompts to maintain

**Cons:**
- Context window fills up on complex charms
- Can't parallelise (user waits while agent debugs)
- System prompt becomes massive
- Hard to use different models for different tasks

### Option B: Multi-Agent (Specialised)

```
┌─────────────────────────────────────────────┐
│           Orchestrator Agent                │
│         (talks to user, coordinates)        │
└───────────────────┬─────────────────────────┘
                    │
        ┌───────────┼───────────┬─────────────┐
        │           │           │             │
        ▼           ▼           ▼             ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
   │Scaffold │ │ Debug   │ │  Test   │ │Research │
   │ Agent   │ │ Agent   │ │ Agent   │ │ Agent   │
   └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

**Pros:**
- Specialised prompts per task
- Can run in parallel (test while chatting)
- Cleaner separation of concerns
- Can use cheaper models for simple tasks
- Scales better as complexity grows

**Cons:**
- Coordination complexity
- Context handoff between agents
- More infrastructure to build
- Debugging agent interactions is hard

### Option C: Hybrid ✓ CHOSEN

```
┌─────────────────────────────────────────────┐
│              Main Agent                     │
│                                             │
│  • Handles conversation                     │
│  • Simple tasks directly                    │
│  • Spawns sub-agents for complex tasks      │
│                                             │
└───────────────────┬─────────────────────────┘
                    │ (when needed)
        ┌───────────┴───────────┐
        ▼                       ▼
   ┌──────────────┐      ┌──────────────┐
   │ Background   │      │ Background   │
   │ Debug Agent  │      │ Test Agent   │
   │ (async)      │      │ (async)      │
   └──────────────┘      └──────────────┘
```

**Pros:**
- Simple path for simple tasks
- Background work doesn't block user
- Main agent keeps full context
- Sub-agents are disposable workers

**Cons:**
- Still need coordination logic
- When does main agent hand off?

### Key Questions for Architecture

1. **What tasks benefit from parallelism?**
   - Running tests while user continues chatting? YES
   - Debugging while user adds more requirements? MAYBE
   - Research while scaffolding? YES

2. **What tasks need full conversation context?**
   - Understanding user requirements: YES (main agent)
   - Writing charm code: SOMEWHAT
   - Running tests: NO (just needs the charm)
   - Debugging: SOMEWHAT (needs to know intent)

3. **Where do we want to use cheaper models?**
   - Research/search: Could use Haiku-equivalent
   - Test running: Could use Haiku-equivalent
   - Core charm writing: Needs best model

### Decision: Hybrid

**Main agent** handles:
- Conversation with user
- Writing charm code
- Architectural decisions
- Coordinating background work

**Background agents** handle:
- Running tests
- Querying Charmhub
- Querying Tempo/Loki for traces
- Research tasks

User never waits for background work to complete.

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
└── .cantrip/                  # Cantrip session data
    ├── session.json           # Conversation state
    ├── context.md             # Summarised context for LLM
    └── decisions.yaml         # Key decisions made
```

When user runs `cantrip` in a charm directory:
1. Detect `.cantrip/` folder
2. Load previous session context
3. Resume where they left off

### Context Management

LLM context windows are finite. Strategy:
- Summarise older conversation turns
- Keep recent turns verbatim
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
- [ ] Multiple LLM providers
- [ ] Rock building for OCI images
- [ ] Charm library suggestions
- [ ] Auto-integration recommendations

### Explicitly Out of Scope
- Bundles (deprecated)
- pytest-operator / python-libjuju (use Jubilant instead)
- Harness (use Scenario instead)

## Open Questions

See QUESTIONS.md for items needing clarification.

## File Structure (Proposed)

```
cantrip/
├── pyproject.toml
├── uv.lock
├── src/
│   └── cantrip/
│       ├── __init__.py
│       ├── main.py           # Entry point
│       ├── tui/
│       │   ├── __init__.py
│       │   ├── app.py        # Main Textual app
│       │   ├── widgets/
│       │   │   ├── juju_status.py
│       │   │   ├── chat.py
│       │   │   └── model_graph.py
│       │   └── screens/
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── core.py       # Main agent logic
│       │   ├── tools/        # Agent tools
│       │   │   ├── scaffold.py
│       │   │   ├── deploy.py
│       │   │   ├── debug.py
│       │   │   └── test.py
│       │   └── prompts/      # System prompts, templates
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py       # Abstract LLM interface
│       │   ├── gemini.py
│       │   └── ...           # Other providers
│       ├── juju/
│       │   ├── __init__.py
│       │   ├── status.py     # Status parsing/display
│       │   └── integration.py
│       └── charm/
│           ├── __init__.py
│           ├── templates/    # Charm templates
│           ├── scaffolder.py
│           └── analyser.py   # Analyse existing charms
├── tests/
├── docs/
└── .github/
    └── workflows/
```
