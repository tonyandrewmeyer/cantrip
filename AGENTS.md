# AGENTS.md

## Project Overview

Cantrip is an AI-powered autonomous agent that builds Juju charms independently. See `design/PLAN.md` for architecture and `design/AGENT.md` for the two-loop agent design.

## Package Manager

Use **uv** exclusively — never `pip`, `pipx`, or `--break-system-packages`.

```bash
uv sync --dev          # Install dependencies
uv run <tool>          # Run project tools
uvx <tool>             # Run one-off tools
```

## Commands

```bash
make format    # Format with ruff
make lint      # Ruff check + ty type checker
make unit      # Run unit tests
make check     # lint + unit tests
make all       # format + check
make coverage  # Unit tests with coverage report
```

## File-Scoped Commands

| Task | Command |
|------|---------|
| Lint | `uv run ruff check path/to/file.py` |
| Format | `uv run ruff format path/to/file.py` |
| Test file | `uv run pytest tests/unit/test_tools.py -v` |
| Test function | `uv run pytest tests/unit/test_tools.py::test_name -v` |

## Key Conventions

- **UK English** throughout: colour, behaviour, organisation, analyse
- **Type checker is `ty`**, not mypy
- Python 3.12+
- `dataclasses` from stdlib — do NOT use Pydantic
- Modern types: `str | None` not `Optional[str]`
- Import modules, not names: `import datetime` not `from datetime import datetime`
  - Exception: imports only for type annotations
- Comments explain *why*, not *how* — comments are rare; docstrings are essential
- Comments are full sentences ending with punctuation.
- Never catch bare `Exception` — always be specific
- Minimise code inside try/except blocks

## Charm Development Context

Key rules are embedded in the system prompt (`src/cantrip/agent/prompts/system.py`):

- Use **Scenario** (`ops.testing`) for unit tests, NOT Harness
- Use **Jubilant** for integration tests, NOT pytest-operator
- Always include **ops-tracing** and **COS integration**
- Prefer **PyPI versions** of charm libraries over charmcraft fetch-libs
- Three paths: **A** (12-Factor PaaS), **B** (Custom Apps), **C** (Infrastructure)

## Workflow

- **Commit at appropriate times.** Commit after each logical, self-contained piece of work. Each commit should leave the tree in a working state (`make check` passes).
- **Keep `CHANGELOG.md` up to date.** Add entries under `## Unreleased` for significant changes. Small fixes don't need entries.
- **Maintain test coverage.** New code should include tests; coverage should not decrease.

## Reference Documents

- `design/PLAN.md` — Architecture decisions, philosophy, detailed design
- `design/AGENT.md` — Agent architecture (two-loop design, subagents, work queue, tools)
- `design/UI.md` — Shared UI design (TUI + Web), event bus contract, layout, shortcuts
- `ROADMAP.md` — Implementation phases
- `CHANGELOG.md` — Notable changes (keep updated)
