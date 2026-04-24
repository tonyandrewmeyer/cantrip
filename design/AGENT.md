# Cantrip Agent Architecture

*Companion docs:*
[TOOLS.md](TOOLS.md) *(tool abstraction),*
[SKILLS.md](SKILLS.md) *(skill discovery & loading),*
[PROMPTS.md](PROMPTS.md) *(prompt layering & templates).*

## Overview

Two-loop autonomous architecture: a **conversation loop** handles user interaction
(confirmations, steering, domain expertise) while an **autonomous work loop** executes
tasks from a work queue via disposable subagents. The user describes what to charm;
the agent independently researches, designs, builds, deploys, tests, and debugs.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CantripAgent                                  │
│                                                                         │
│  ┌───────────────────────┐              ┌────────────────────────────┐  │
│  │   Conversation Loop   │    steer/    │    Autonomous Work Loop    │  │
│  │                       │◄────────────►│                            │  │
│  │  process_message()    │    notify    │  Executor picks tasks      │  │
│  │  User chat, proposals │              │  Spawns subagents          │  │
│  │  Decision collection  │              │  Records results           │  │
│  └───────────┬───────────┘              └─────────────┬──────────────┘  │
│              │                                        │                 │
│              └───────────► WorkQueue ◄────────────────┘                 │
│                                ▲                                        │
│                                │                                        │
│                           Watcher events                                │
│                           User steering                                 │
│                           Adaptive replanning                           │
└─────────────────────────────────────────────────────────────────────────┘
```

## Main Agent (Conversation Loop)

The main agent handles the user-facing conversation. It:
- Talks to the user (design proposals, status updates, questions)
- Collects decisions and records them in `AgentState`
- Steers the work queue (reprioritise, cancel, add tasks based on user input)
- Handles the existing `process_message()` / `process_message_streaming()` loops

### System Prompt Structure

The system prompt is rendered from a Jinja2 template (`prompts/system.md.j2`) with
context variables injected at runtime:

```
┌─────────────────────────────────────────────────────────────────┐
│                     SYSTEM PROMPT                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Identity & Purpose                                          │
│     "You are Cantrip, an autonomous agent that builds charms.   │
│      You work independently — research, design, build, deploy,  │
│      test, debug — with the user confirming key decisions."     │
│                                                                 │
│  2. Core Principles                                             │
│     - Research first, then propose, then build                  │
│     - Present grounded design proposals for confirmation        │
│     - Keep the task checklist moving autonomously               │
│     - Use observability (traces, logs) to debug                 │
│     - Showcase the Canonical ecosystem                          │
│                                                                 │
│  3. Charm Development Guidance                                  │
│     - Modern patterns (Scenario, Jubilant)                      │
│     - Library preferences (PyPI > Charmhub)                     │
│     - Three charm paths (12-factor, custom, infrastructure)     │
│                                                                 │
│  4. Skills Index                                                │
│     Lightweight list of available skills (loaded on demand)     │
│                                                                 │
│  5. Current Context (injected at runtime)                       │
│     - Active charm project (name, path, type, framework)        │
│     - Environment state (dev model, COS model)                  │
│     - Recent decisions                                          │
│     - Watcher status                                            │
│                                                                 │
│  6. Context Budget                                              │
│     Token usage, virtual files list (appended per turn)         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Work Queue

The `WorkQueue` (in `agent/queue.py`) is the central coordination mechanism.

### AgentTask

```python
@dataclass
class AgentTask:
    id: str
    title: str                          # Human-readable, shown in TUI checklist
    status: TaskStatus                  # pending, active, done, failed, blocked
    category: TaskCategory              # research, build, deploy, test, debug, infra
    description: str                    # Detailed instructions for the subagent
    dependencies: list[str]             # Task IDs that must complete first
    result: str | None                  # Summary of what the task produced
    blocked_reason: str | None          # Why it's blocked (e.g. "awaiting user confirmation")
```

### Task Lifecycle

```
pending ──► active ──► done
  │            │
  │            └──► failed
  │
  └──► blocked ──► pending (when unblocked)
```

Tasks enter `blocked` when they need user input (e.g. "confirm this design proposal").
The conversation loop unblocks them when the user responds.

### Task Sources

1. **Task planner** — LLM decomposes user intent into ordered tasks (initial plan)
2. **Adaptive replanning** — planner inserts/reorders tasks when context changes
3. **Watcher events** — status changes, hook failures, new relations create tasks
4. **User steering** — user can add, cancel, or reprioritise tasks via chat

## Task Planner

The `TaskPlanner` (in `agent/planner.py`) uses an LLM call to decompose user intent
into a structured task list.

### Planning Flow

```
User: "build a charm for Redis"
           │
           ▼
    ┌──────────────┐
    │ Classify      │  12-factor? Custom? Infrastructure?
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Plan tasks   │  LLM generates ordered AgentTask list
    └──────┬───────┘
           │
           ▼
    ┌──────────────────────────────────────────┐
    │  1. Set up environment (infra)           │
    │  2. Research workload (research)         │
    │  3. Survey Charmhub (research)           │
    │  4. Present design proposal (blocked)    │
    │  5. Scaffold charm (build)               │
    │  6. Deploy to dev model (deploy)         │
    │  7. Add observability (build)            │
    │  8. Run unit tests (test)                │
    │  9. Add integrations (build)             │
    │ 10. Run integration tests (test)         │
    │ 11. Validate (test)                      │
    └──────────────────────────────────────────┘
```

### Adaptive Replanning

When context changes mid-execution:
- **User override** ("skip Sentinel for now") → planner cancels/modifies relevant tasks
- **New context** ("it also needs Redis caching") → planner inserts research + build tasks
- **Watcher event** ("hook failed in redis-k8s/0") → planner inserts diagnostic task
- **Task failure** → planner may insert a retry or alternative task

## Background Executor

The `BackgroundExecutor` (in `agent/executor.py`) is an asyncio task that runs
alongside the conversation loop.

### Execution Loop

```python
# Simplified — actual implementation in agent/executor.py
async def run(self):
    while True:
        task = self.queue.next_ready()
        if task is None:
            await asyncio.sleep(1)
            continue

        self.queue.set_active(task)
        result = await self._execute_task(task)
        self.queue.set_done(task, result)
```

### Concurrency Model

- Initially sequential (one task at a time)
- Independent tasks (e.g. research + environment setup) can run in parallel later
- The executor pauses during user interactions that affect the work queue

### Prior art — the *ralph loop*

[awesome-copilot's ``ralph_loop.py``][ralph-loop] is the prior art
for what Cantrip does with subagents.  79 lines, one function: read
a single prompt file, loop ``max_iterations`` times, create a
**fresh session** each iteration (so the LLM always operates in the
"smart zone" of its context window), auto-approve permissions, send
the prompt, wait up to 600 s, destroy the session.  State carries
between iterations via plain markdown files the agent writes and
reads — ``IMPLEMENTATION_PLAN.md``, ``AGENTS.md``, ``specs/*``.

Cantrip's subagent pattern is the same idea scaled up:

| Ralph | Cantrip equivalent |
|-------|--------------------|
| Fresh session per iteration | Fresh ``Subagent`` per task (isolated LLM context, focused system prompt) |
| Auto-approve permissions | ``PRE_TOOL_CALL`` hooks run but don't gate by default inside the autonomous loop |
| 600 s per-iteration timeout | ``_TASK_TIMEOUTS`` + ``_DEFAULT_TASK_TIMEOUT`` in ``executor.py`` |
| Disk-as-state (markdown files) | ``.cantrip`` SQLite + the charm working tree |
| Single prompt file | ``prompts/system.md.j2`` + per-category guidance under ``prompts/subagent/`` |
| ``max_iterations`` hard cap | *Missing — see "Per-goal budget" below* |

The similarities vastly outweigh the differences.  Cantrip adds a
**work queue with typed dependencies**, **parallel subagents under
a concurrency semaphore**, **category-scoped tool allowlists**, and
(since Phase 52) **step-level checkpoint replay** so a rate-limited
turn resumes from the checkpoint instead of turn 1.  Those are
strict extensions of the ralph pattern, not alternatives to it.

### Per-goal budget (scoped follow-up — see ROADMAP Phase 55.3)

The one ralph primitive Cantrip is missing is the ``max_iterations``
circuit breaker.  Today the autonomous loop runs until the planner
declares done — there's no aggregate cap on "how many tasks / how
many tokens may this one user request consume before we stop and
ask?"  The work queue drains on its own schedule, and a runaway
planner could in principle spawn arbitrary follow-up tasks.

A concrete scope for the missing primitive, **sketched here and
deferred to a dedicated follow-up phase**:

- **A "goal"** is a user request that kicks off an autonomous run
  (the implicit root of the task DAG).  A new
  ``AgentState.goal_budget: GoalBudget | None`` is set when the
  goal starts and cleared on completion.
- **``GoalBudget`` fields:** ``max_iterations: int`` (tasks
  permitted for this goal), ``max_prompt_tokens: int | None``,
  ``max_completion_tokens: int | None``, ``started_at: datetime``.
  The token caps scope off the existing ``token_usage`` table via
  ``SessionStore.get_usage_since(goal_budget.started_at)`` — no new
  schema required.
- **Circuit breaker in the executor:** before ``_run_task`` spawns
  a subagent, a ``_budget_allows(task)`` gate checks both counters.
  If tripped, the task is marked ``BLOCKED`` with
  ``blocked_reason="budget exceeded"`` and a new
  ``goal_budget_exceeded`` event is published on the UI bus.
  In-flight subagents drain naturally (Phase 52.3's checkpoint
  wiring already makes resume cheap if the user later raises the
  budget).
- **Recovery surfaces:** a ``/budget`` slash command to show the
  current caps + burn-down, and (if tripped) raise them in-place;
  CLI flags ``--max-iterations`` / ``--max-tokens`` to set the
  defaults at startup; environment variables ``CANTRIP_MAX_ITERATIONS``
  / ``CANTRIP_MAX_PROMPT_TOKENS`` / ``CANTRIP_MAX_COMPLETION_TOKENS``
  for operator config.
- **Pairs with the tool-access policy work in Phase 55.4.**
  ``max_calls_per_request`` from the awesome-copilot
  ``agent-governance`` skill is the same circuit-breaker shape
  applied at the *tool* level instead of the *goal* level.  The
  two share the same event plumbing; build them together or pick
  the goal-level one first — it has broader blast radius.

Not scoped here: UI redesign, multi-goal budget sharing, or
budget rollover between resumed sessions.  Size: one module
(~150 lines) + one event type + two CLI flags + three tests
(gate trips / raise clears / resume honours the cap).  Worth a
dedicated phase when autonomous runs start routinely exceeding
~20 tasks; until then the current "run until done" behaviour is
adequate for supervised use.

[ralph-loop]: https://github.com/github/awesome-copilot/blob/main/cookbook/copilot-sdk/python/recipe/ralph_loop.py

## Subagent Pattern

Each background task runs as a **subagent**: a fresh LLM context with a focused system
prompt and a subset of tools. Subagents are created by the `Subagent` class (in
`agent/subagent.py`).

### Why Subagents

- **Clean context** — main agent's conversation history stays focused on user interaction
- **Focused prompts** — each subagent gets instructions tailored to its task category
- **Cost routing** — research and infra tasks use the light model; code writing uses primary
- **Parallel potential** — subagents run concurrently (bounded by semaphore) while the user chats

### Category guidance

Each category has a **markdown guidance file** in `prompts/subagent/` (plain markdown,
no Python knowledge needed to edit):

| Category | Guidance file | Model |
|----------|--------------|-------|
| Research | `prompts/subagent/research.md` | Light |
| Build | `prompts/subagent/build.md` | Primary |
| Deploy | `prompts/subagent/deploy.md` | Primary |
| Test | `prompts/subagent/test.md` | Primary |
| Debug | `prompts/subagent/debug.md` | Primary |
| Infra | `prompts/subagent/infra.md` | Light |

Additional overlays: `demo.md` (for demo generation tasks) and `acceptance.md`
(for acceptance testing tasks) are injected alongside the category guidance when
the task title matches.

Tool allowlists per category are defined in `_CATEGORY_TOOLS` in `subagent.py`.

### Shared infrastructure

Both the main conversation loop and subagents share:

- **`retry.py`** — `complete_with_retry()` handles rate limits and overload with
  linear backoff (3 retries, 30s base delay). Subagents coordinate via
  `ProviderThrottle` to avoid thundering-herd retries.
- **`tools/base.py`** — `execute_tool()` provides shared error handling for tool
  dispatch (unknown tool, bad arguments, unexpected exceptions).
- **`tools/__init__.py`** — `build_tools()` centralises tool construction so
  callers do not need to import individual tool classes.

### Context handoff

Subagents receive:
- Their focused system prompt (category-specific guidance from markdown)
- The task description from the AgentTask
- Result summaries from completed dependency tasks
- Charm context (name, path, type, framework, models)
- Approved design content (for build/deploy/test tasks)
- Decisions already confirmed by the user

Subagents return a text summary that is recorded as the task result and
passed to downstream dependent tasks.

## Conversation Flow Examples

### Autonomous Charm Building

```
User: "build a charm for redis"

[Task planner creates 11 tasks, visible in TUI checklist]

Agent (chat): "I'll build a Redis charm. Setting up the environment
and starting research — you'll see progress in the task list on the left."

[Executor runs tasks autonomously: setup → research → Charmhub survey]

Agent (chat): "I've researched how Redis is typically operated. Here's
my proposed design:

  • K8s charm (official redis:7 OCI image)
  • Primary/replica topology with Sentinel for failover
  • AOF persistence enabled by default
  • Config: maxmemory, maxmemory-policy, bind-address
  • Actions: backup (redis-cli BGSAVE), failover (Sentinel)
  • Integrations: COS (metrics + tracing), ingress (Traefik)

Sources: redis.io/docs/management, redis.io/docs/management/sentinel

Shall I proceed, or would you like to adjust anything?"

User: "looks good, but skip sentinel for now — keep it simple"

[Agent records decision, planner replans without Sentinel]

Agent (chat): "Got it — single-instance Redis without Sentinel.
Proceeding with build."

[Executor continues: scaffold → deploy → observability → tests → validate]
[All visible as checklist items completing in the TUI]
```

### User Steering Mid-Build

```
[Agent is autonomously building, currently on "Add integrations"]

User: "actually, it needs to support both Redis and KeyDB — they use
the same protocol but KeyDB has multithreading"

[Planner inserts research task for KeyDB, modifies build tasks]

Agent (chat): "Interesting — I'll research KeyDB compatibility and
adjust the charm to support both. I've added a research task to the queue."

[Research subagent runs, results feed back into build]
```

### Watcher-Driven Debugging

```
[Watcher detects: redis-k8s/0 entered error status]

[Planner creates task: "Diagnose hook failure in redis-k8s/0"]

[Debug subagent runs: queries Loki → reads traces → identifies root cause]

Agent (chat): "The watcher detected a hook failure in redis-k8s/0.
I've investigated — the install hook is failing because the redis.conf
template references a variable that isn't set yet. Fixing now."

[Build subagent fixes the code, deploy subagent redeploys]
[All visible in the task checklist]
```

## State and Persistence

### AgentState

```python
@dataclass
class AgentState:
    charm_name: str | None
    charm_path: Path | None
    charm_type: str | None              # "machine" or "k8s"
    framework: str | None

    dev_model: str | None
    cos_model: str | None

    environment_ready: bool             # Transient
    watcher_enabled: bool               # Transient
    test_results: TestResults | None    # Transient

    messages: list[Message]             # Conversation history
    decisions: list[Decision]           # Key decisions (always in context)
```

### SQLite Store (.cantrip)

The `.cantrip` SQLite file in the charm directory stores:
- Session state (charm name, path, type, models, decisions)
- Token usage per request
- Work queue tasks (status, results, dependencies)
- Conversation history (for session restore)

### Context Management

- **Virtual files** — large tool results (>10k tokens) are virtualised; only a preview
  is kept inline; the agent can read the full content on demand
- **Compaction** — when context exceeds 80% of the window, older messages are summarised
  (using the light model) and the original is saved as a virtual file
- **Budget tracking** — a transient system message shows token usage and virtual file list
- **Decisions always in context** — key decisions are never compacted away

## Tools

Tools are the agent's capabilities. All tools inherit from the abstract `Tool` class
with `name`, `description`, `parameters` (JSON Schema), and async `execute()` method.

### Tool Categories

| Category | Tools | Used by |
|----------|-------|---------|
| File operations | ReadFile, WriteFile, EditFile, ListDirectory | Build subagent, main agent |
| Charm operations | CharmcraftInit, CharmcraftPack, CharmValidate, CharmcraftFetchLibs, AnalyseFramework | Build subagent |
| Rockcraft | RockcraftInit, RockcraftPack, SkopeoRegistryPush | Build subagent |
| Juju operations | JujuStatus, JujuDeploy, JujuRefresh, JujuRelate, JujuSSH, JujuRunAction, JujuConfig, JujuWait, JujuAddModel, JujuDestroyModel, JujuOffer, JujuConsume, CharmSync, JujuDispatch | Deploy subagent, main agent |
| Observability | JujuDebugLog, TempoQuery, LokiQuery | Debug subagent |
| Registry | RegistrySearch, RegistryImageInfo | Research subagent |
| Charmhub | CharmhubSearch, CharmhubInfo | Research subagent |
| Git | GitClone, GitInit, GitStatus, GitDiff, GitLog, GitAdd, GitCommit, GitPush | Main agent |
| GitHub | GhRepoCreate, GhPrCreate, GhIssueList | Main agent |
| Web | WebFetch | Research subagent |
| Testing | RunCharmTests | Test subagent |
| Environment | ConciergePrepare, ConciergeStatus | Infra subagent |
| Skills | LoadSkill | Main agent |
| Context | VirtualFileRead, VirtualFileSearch | All agents |

Subagents receive only the tools relevant to their category. The main agent has
access to all tools for direct execution when needed.
