---
name: charm-review
description: Review Cantrip agent code for correctness and project conventions
allowed-tools: Read Grep Glob
---

Review the changed code for issues specific to this project. Focus on:

**Project conventions:**
- UK English spelling throughout (colour, behaviour, analyse, organisation, etc.)
- Comments explain *why*, not *how*; docstrings are present on public APIs
- Imports are at the top of the module — no lazy or conditional imports
- Import modules, not individual classes/methods (e.g. `import datetime` not `from datetime import datetime`)
- Modern type syntax: `str | None` not `Optional[str]`
- No bare `Exception` catches — always use specific exception types
- Use stdlib `dataclasses`, never Pydantic

**Charm development patterns:**
- Unit tests must use Scenario (ops.testing), never Harness
- Integration tests must use Jubilant, never pytest-operator
- Charm code should include COS integration and ops-tracing for observability

**Architecture:**
- Tools inherit from abstract `Tool` class with `name`, `description`, `parameters`, and async `execute()`
- LLM providers implement `LLMProvider` with `complete()`, `stream()`, and `count_tokens()`
- State is persisted to SQLite via the session store

For each issue found, report:
- What the specific problem is
- Why it matters (convention violation, potential bug, etc.)
- A concrete fix
