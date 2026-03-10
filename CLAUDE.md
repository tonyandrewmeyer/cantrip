# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cantrip is an AI-powered **autonomous agent** that builds Juju charms independently — researching workloads, designing charms, writing code, deploying, testing, and debugging — with the user confirming key decisions and providing domain expertise. It demonstrates the Canonical ecosystem (Juju, Charmcraft, Rockcraft, Ops, Jubilant, Concierge, COS).

## Commands

```bash
make format    # Format with ruff
make lint      # Ruff check + ty type checker
make unit      # Run unit tests
make check     # lint + unit tests
make all       # format + check
uv sync --dev  # Install dependencies
```

Run a single test:
```bash
uv run pytest tests/unit/test_tools.py -v
uv run pytest tests/unit/test_tools.py::test_function_name -v
```

## Important Conventions

- **UK English** throughout: colour, behaviour, organisation, analyse (not color, behavior, organization, analyze)
- **Type checker is `ty`**, not mypy
- Line length: 99 characters
- Python 3.12+

### Code Style (Critical)

**Comments & docstrings:**
- Comments explain *why*, not *how* - if *how* is needed, refactor the code
- Comments are rare; docstrings are essential
- Comments are full sentences ending with punctuation.

**Imports:**
- Always at top of module - no lazy imports, no conditional imports
- Import modules, not classes/methods/variables: `import datetime` not `from datetime import datetime`
- Exception: importing only for type annotations is acceptable

**Types:**
- Modern style: `str | None` not `Optional[str]`

**Error handling:**
- Never catch bare `Exception` - always be specific
- Minimise code inside try/except blocks

**Data structures:**
- Use `dataclasses` from stdlib
- Do NOT use Pydantic

## Architecture

Two concurrent loops: a **conversation loop** (user confirms/steers) and an **autonomous work loop** (agent executes tasks from a work queue via subagents). See PLAN.md for the full architecture diagram.

```
src/cantrip/
├── main.py              # Entry point, arg parsing
├── cli.py               # CLI mode (no TUI)
├── agent/
│   ├── core.py          # CantripAgent — conversation loop, tool execution
│   ├── state.py         # AgentState and Decision dataclasses
│   ├── store.py         # SQLite-backed session store
│   ├── skills.py        # Skills index and loading
│   ├── context.py       # Context compaction, virtual file store
│   ├── design.py        # Design document generation
│   ├── preflight.py     # Pre-flight environment checks
│   ├── autodeploy.py    # Automatic deploy after charm build
│   ├── watcher.py       # Event-driven watcher (status diffing, Loki polling)
│   ├── queue.py         # WorkQueue, AgentTask — autonomous work scheduling
│   ├── planner.py       # Task planner — LLM decomposes intent into tasks
│   ├── executor.py      # Background executor — picks tasks, runs subagents
│   ├── subagent.py      # Subagent runner — isolated LLM context per task
│   ├── tools/           # Agent tools (file ops, charm ops, juju, git, web)
│   └── prompts/         # System prompts (Jinja2 templates + builders)
├── llm/
│   ├── base.py          # Abstract LLMProvider interface
│   ├── gemini.py        # Google Gemini implementation
│   ├── claude.py        # Anthropic Claude implementation
│   └── inference_snap.py # Canonical inference snap (local models)
├── charm/
│   └── templates/       # Charm project templates
├── skills/              # Skill definitions (SKILL.md per skill)
├── tui/
│   ├── app.py           # Main Textual app (CantripApp)
│   ├── cantrip.tcss     # Textual CSS
│   ├── screens/         # TUI screens
│   └── widgets/         # Task checklist, status, chat, status bar
└── juju/                # Juju integration via Jubilant
```

### Key Patterns

**Tool Pattern:** Tools inherit from abstract `Tool` class with `name`, `description`, `parameters` (JSON Schema), and async `execute()` method.

**LLM Provider Pattern:** Abstract `LLMProvider` base with `complete()`, `stream()`, and `count_tokens()` methods. Messages use `Role` enum (SYSTEM, USER, ASSISTANT, TOOL).

**Conversation Loop:** User message → LLM → tool_calls → execute → LLM again → until text response. Also handles steering (reprioritising tasks, providing context).

**Autonomous Work Loop:** Picks next ready task from WorkQueue → spawns a subagent (isolated LLM context + focused tools) → records result → unblocks dependents → picks next task. Runs concurrently with the conversation loop.

**Work Queue:** Central coordination. AgentTask objects with status (pending/active/done/failed/blocked), dependencies, and category-based cost routing (research → light model, code writing → primary model).

**State:** Saved to a `.cantrip` SQLite file in the charm directory. Tracks charm_name, charm_path, charm_type, framework, models, decisions, tasks, and per-request LLM token usage.

## Charm Development Context

The system prompt in `src/cantrip/agent/prompts/system.py` contains embedded charm development expertise. Key rules:

- Use **Scenario** (`ops.testing`) for unit tests, NOT Harness
- Use **Jubilant** for integration tests, NOT pytest-operator
- Always include **ops-tracing** for observability
- Always add **COS integration**
- Prefer **PyPI versions** of charm libraries over charmcraft fetch-libs
- Query **Charmhub dynamically**, not static lists

### Three Charm Paths

1. **Path A (12-Factor PaaS):** Flask, Django, Go, FastAPI → uses paas-charm base, generates rockcraft.yaml
2. **Path B (Custom Applications):** Full ops framework charm, analyse requirements
3. **Path C (Infrastructure Software):** Databases, caches → check Charmhub first, complex operational logic

## Workflow

- **Commit at appropriate times.** Don't wait until the end of a large task — commit after each logical, self-contained piece of work (e.g. after finishing a feature, fixing a bug, or completing a refactor). Each commit should leave the tree in a working state (`make check` passes).
- **Keep `CHANGELOG.md` up to date.** When adding a significant feature or making a notable change, add an entry under the `## Unreleased` section. Small fixes and trivial refactors don't need changelog entries — use judgement. The changelog is for users, not developers.

## Reference Documents

- `PLAN.md` - Architecture decisions, philosophy, detailed design
- `AGENT.md` - Agent architecture (two-loop design, subagents, work queue, tools)
- `ROADMAP.md` - Implementation phases
- `TUI.md` - UI/UX design with ASCII mockups
- `CHANGELOG.md` - Notable changes (keep updated)
