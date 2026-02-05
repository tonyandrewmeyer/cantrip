# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cantrip is an AI-powered agent that helps developers build Juju charms through natural conversation. It demonstrates the Canonical ecosystem (Juju, Charmcraft, Rockcraft, Ops, Jubilant, Concierge, COS).

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
- Python 3.11+

## Architecture

```
src/cantrip/
├── main.py              # CLI entry point
├── agent/
│   ├── core.py          # CantripAgent - conversation loop, tool execution
│   ├── tools/           # Agent tools (file ops, charm ops, juju ops)
│   └── prompts/         # System prompts with context injection
├── llm/
│   ├── base.py          # Abstract LLMProvider interface
│   └── gemini.py        # Google Gemini implementation
├── tui/
│   ├── app.py           # Main Textual app (CantripApp)
│   └── widgets/         # Status, chat widgets
└── juju/
    └── status.py        # Juju status parsing
```

### Key Patterns

**Tool Pattern:** Tools inherit from abstract `Tool` class with `name`, `description`, `parameters` (JSON Schema), and async `execute()` method.

**LLM Provider Pattern:** Abstract base with `complete()` and `stream()` methods. Messages use `Role` enum (SYSTEM, USER, ASSISTANT, TOOL).

**Agent Loop:** LLM returns tool_calls → execute each → collect results → call LLM again until response has no tool calls.

**State:** Saved to `.cantrip/session.json` in charm directory. Tracks charm_name, charm_path, charm_type, framework, models, decisions.

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

## Reference Documents

- `PLAN.md` - Architecture decisions, philosophy, detailed design
- `ROADMAP.md` - Implementation phases
- `TUI.md` - UI/UX design with ASCII mockups
