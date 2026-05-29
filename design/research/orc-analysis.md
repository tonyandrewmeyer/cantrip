# Lessons from orc for Cantrip

**Source:** [github.com/PietroPasotti/orc](https://github.com/PietroPasotti/orc) — a
multi-agent orchestrator that turns product visions into code. Written by Pietro
Pasotti (Canonical). Analysed 2026-03-18.

---

## What orc is

orc reads high-level feature descriptions ("visions"), breaks them into tasks,
assigns them to AI agents (planner → coder → QA), and merges the results — all
on a separate `dev` branch. It is stateless: on every cycle it reads a YAML
kanban board and git state, applies a dispatch table, and acts. Agents run as
sandboxed subprocesses (GitHub Copilot CLI or Anthropic Claude CLI) in isolated
git worktrees, communicating with the board exclusively through a per-agent MCP
server.

Key architecture:
- **Board-driven workflow** — a YAML kanban board is the single source of truth
- **Parallel squads** — configurable agent counts per role, each in its own worktree
- **Git-native** — every decision is a commit; full audit trail in the repo
- **Sandboxed by default** — agents run in `confined` mode with explicit tool allow-lists
- **Backend-agnostic** — works with GitHub Copilot CLI or Anthropic Claude CLI

---

## Lessons

### 1. Pure State Machine with Formal Proofs

orc's routing logic (`route()` in `state_machine.py`) is a **pure function**
that takes a `WorldState` dataclass and returns the next action — zero I/O,
zero side effects. The implementation (`_derive_task_state`) delegates to this
same function, ensuring a single source of truth. Tests use BFS to prove
deadlock-freedom exhaustively, and parametrised cross-check tests verify the
formal model matches the real implementation.

**Relevance to Cantrip:** The work queue and task planner could benefit from
extracting the "what happens next" decision into a pure function over a data
snapshot. A formal model would catch edge cases (stuck loops, blocked tasks that
never unblock) and serve as living documentation. The cross-check test pattern
(run both the model and the implementation, assert they agree) is especially
valuable.

### 2. Board-Driven, Stateless Orchestration

orc is intentionally stateless between cycles. On every poll cycle it reads the
board YAML and git state fresh, derives what to do, and acts. No in-memory state
machine accumulates; the board file + git branches *are* the state. This makes
crash recovery trivial — just restart and the board tells you where you are.
`clear_all_assignments()` on startup and a `CLOSE_BOARD` sentinel for crash
recovery handle edge cases cleanly.

**Relevance to Cantrip:** Cantrip uses SQLite state, which is good for
durability, but the pattern of deriving the next action purely from observable
state (rather than remembering in-memory transitions) is worth adopting. If the
agent crashes mid-task, can it recover cleanly by re-reading the store?

### 3. Protocol-Based Service Injection

The `Dispatcher` accepts five `Protocol`-typed services (`BoardService`,
`WorktreeService`, `MessagingService`, `WorkflowService`, `AgentService`). The
dispatcher owns zero domain logic — it only orchestrates. Tests use simple fakes
(`FakeBoard`, `FakeWorkflow`, etc.) that are trivially swappable.

**Relevance to Cantrip:** `CantripAgent` in `core.py` mixes orchestration with
domain logic. Extracting domain operations behind Protocol interfaces would make
the executor/subagent system far easier to test without mocking LLMs or Juju.
The `make_services()` + `make_dispatcher()` conftest helper pattern is worth
copying.

### 4. Git Worktree Isolation for Parallel Agents

Each coder agent gets its own git worktree on a feature branch. The planner
works in a dev worktree. Agents are sandboxed to their worktree — they cannot
touch `main` or each other's branches. Merges are handled exclusively by the
orchestrator after QA passes.

**Relevance to Cantrip:** When subagents work in parallel (e.g. research + code
writing), worktree isolation prevents conflicts. The `Git.ensure_worktree()`
helper and merge-after-QA pattern would work well for the auto-deploy flow.

### 5. MCP Server as Agent–Board Interface

Agents interact with the board exclusively through MCP tools served via a
FastAPI server on a Unix domain socket. Each agent role sees only its own tools
(planner gets `create_task`/`close_vision`, coder gets `close_task`, QA gets
`review_task`). Agents are told never to touch `.orc/` files directly.

**Relevance to Cantrip:** Instead of giving subagents direct file access to
shared state, expose a scoped MCP server where each subagent can only perform
its designated operations (e.g. a "research" subagent can only write to the
context store, a "code" subagent can only modify the charm directory). The
role-based tool filtering is clean and simple.

### 6. Noop Detection

Before spawning an agent, the dispatcher takes a `BoardSnapshot` (task statuses,
pending visions, routing token). After the agent exits successfully, it takes
another snapshot. If they are identical, the agent is flagged as a noop and the
dispatch loop aborts — preventing infinite loops where agents consume compute
without producing useful work.

**Relevance to Cantrip:** Directly applicable. If a subagent completes without
changing any state (no files modified, no decisions recorded, no tasks resolved),
that is a bug or environment problem. Cantrip should detect it rather than
looping. Especially important for the autonomous work loop.

### 7. Configurable Squad Profiles with Permission Sandboxing

Squad YAML files define agent counts, models per role, tool permissions, and QA
review thresholds. Permissions cascade: orc defaults → squad-level → role-level.
There is a `confined` mode (explicit allow-lists) and a `yolo` mode
(unrestricted).

**Relevance to Cantrip:** The cost routing (research → light model, code →
primary model) could be extended into a proper "squad profile" concept. Being
able to configure parallelism, models, and tool access per task category without
code changes would make Cantrip more flexible.

### 8. Agent Context Building: Compact but Complete

The context passed to each agent is compact — only live runtime data (branch
names, worktree paths, pending visions, blocked tasks, TODOs). Static
documentation (README, CONTRIBUTING) is referenced by file path; the agent reads
it itself. This keeps context small while giving agents everything they need.

**Relevance to Cantrip:** The system prompt already embeds substantial charm
expertise. Pointing agents at files rather than inlining everything would help
manage context window budget as more charm paths and frameworks are added.

### 9. Structured Agent Exit States

Every agent role has explicit `exit-states.md` documentation. Agents must signal
their exit state (done/blocked/stuck) through MCP tools, never just exit
silently. Shared instructions enforce "never emit a bare text response while work
is pending" — every response must include a tool call until the agent is done.

**Relevance to Cantrip:** Subagents should have similarly well-defined exit
contracts. The "tool-call discipline" rule prevents the common failure mode
where an LLM agent narrates what it would do instead of doing it.

### 10. Test Infrastructure: 100% Coverage, Strict TDD

`fail_under = 100` in coverage config. Tests never make real network calls —
httpx, dotenv, and subprocess are stubbed at module import time in conftest.py.
The conftest provides reusable fakes and fixtures rather than ad-hoc mocking.

**Relevance to Cantrip:** The conftest pattern of stubbing external dependencies
at import time (rather than per-test monkeypatching) is robust. Reusable fake
classes that mirror Protocol interfaces make tests read like specifications.

### 11. Two-Stage Graceful Shutdown

First SIGINT/SIGTERM enters "drain mode" (no new agents, running agents finish).
Second signal force-kills all agents and exits with code 130. All tasks are
unassigned before exit so the next run starts clean.

**Relevance to Cantrip:** The watcher and autonomous work loop should handle
shutdown gracefully — stop scheduling, let in-flight subagents finish, clean up.

### 12. Merge Conflict Resolution via Agent Delegation

When `git merge --no-ff` hits a conflict, orc spawns a coder agent to resolve
it, then verifies the merge/rebase completed successfully. If the agent fails,
it aborts the operation and marks the task as stuck.

**Relevance to Cantrip:** For auto-deploy scenarios where charm code might
conflict with upstream changes, delegating conflict resolution to a subagent
rather than failing hard is a resilient pattern.

---

## Summary: Priority Matrix

| Priority | Idea | Cantrip Impact |
|----------|------|----------------|
| High | Pure state machine with formal cross-checks | Eliminates routing bugs in work queue |
| High | Protocol-based service injection | Makes executor/subagent testable without LLM calls |
| High | Noop detection (snapshot before/after) | Prevents infinite subagent loops |
| Medium | MCP server for agent–board scoping | Clean subagent isolation |
| Medium | Squad profiles (counts, models, permissions) | Configurable parallelism without code changes |
| Medium | Compact context with file references | Better context budget management |
| Low | Git worktree isolation | Parallel charm modifications |
| Low | Structured exit states with tool-call discipline | More reliable subagent behaviour |

---

## Key Code References in orc

| Module | What it does |
|--------|-------------|
| `src/orc/engine/state_machine.py` | Pure `route()` function, `WorldState` dataclass, `LastCommit`/`BlockState` enums |
| `src/orc/engine/dispatcher.py` | Poll-based parallel scheduler, noop detection, graceful shutdown |
| `src/orc/engine/services.py` | Protocol interfaces (`BoardService`, `WorkflowService`, etc.) |
| `src/orc/engine/pool.py` | `AgentPool` — subprocess lifecycle management |
| `src/orc/engine/workflow.py` | `_derive_task_state`, merge/conflict resolution, worktree management |
| `src/orc/coordination/board/_manager.py` | `FileBoardManager` — YAML board CRUD with file locking |
| `src/orc/coordination/state.py` | `BoardStateManager` — thread-safe wrapper with `RLock` |
| `src/orc/coordination/server.py` | FastAPI on Unix domain socket for agent MCP communication |
| `src/orc/mcp/server.py` | Role-filtered MCP tool registration |
| `src/orc/mcp/tools.py` | MCP tool implementations (get_task, close_task, review_task, etc.) |
| `src/orc/ai/backends.py` | Backend abstraction (Copilot/Claude CLI), permission flag translation |
| `src/orc/squad.py` | Squad profile loading, permission cascading, `SquadConfig` |
| `src/orc/git.py` | Thin git CLI wrapper (`Git` class) |
| `tests/conftest.py` | Import-time stubs, `FakeBoard`/`FakeWorkflow`/etc., `make_services()` |
| `tests/test_state_machine.py` | Deadlock-freedom proofs, cross-check tests |
| `.orc/agents/` | Agent role definitions — `_main.md`, `exit-states.md`, `permissions.md` per role |
| `docs/adr/0002-state-machine.md` | ADR documenting the formal state machine design |
