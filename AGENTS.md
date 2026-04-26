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

**Always use `make unit` for the full suite.** It runs `pytest -n auto` via `pytest-xdist` for ~4× parallel speedup. Direct `uv run pytest tests/unit/` runs serially and takes 4+ minutes instead of <1 minute. The file/function commands below are only for single-target runs.

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
- **Consider user-facing docs when closing a task.** Before marking work done, ask whether the change affects anything a user sees: a CLI flag, slash command, env var, TUI screen, config key, or behaviour documented in `docs/docs/`. If so, update the relevant page in the same commit (or an adjacent one). Defer only when the feature has no user-facing surface yet — in that case, add a ROADMAP follow-up item so the docs debt is tracked rather than forgotten.
  - `docs/docs/reference-cli.html` — CLI flags, env vars, session-file behaviour, slash-command catalogue
  - `docs/docs/howto-*.html` — task-oriented guides (export, memory, MCP, providers, etc.)
  - `docs/docs/explanation-*.html` — subsystem explanations (architecture, observability, TUI screens, Rust backends)
  - `docs/docs/tutorial.html` — launch-to-first-charm walk-through
  - `docs/docs/reference-tools.html` — tool catalogue surfaced to subagents

## Reference Documents

- `design/PLAN.md` — Architecture decisions, philosophy, detailed design
- `design/AGENT.md` — Agent architecture (two-loop design, subagents, work queue, tools)
- `design/UI.md` — Shared UI design (TUI + Web), event bus contract, layout, shortcuts
- `design/TOOLS.md` — Tool abstraction, registration pattern, how to add/remove a tool
- `design/SKILLS.md` — Skill discovery, frontmatter schema, load-on-demand flow
- `design/PROMPTS.md` — Prompt layering, Jinja2 conventions, template-injection guard
- `design/WEB_UI_ACCESSIBILITY_AUDIT.md` — WCAG 2.1 AA audit of the Web UI with findings and evidence (see ROADMAP Phase 60)
- `design/UPSTREAM_AUDIT.md` — Bookkeeping for the upstream-ecosystem sweep (cutoff commits per repo, re-run procedure; pairs with ROADMAP Phase 37)
- `design/ACP_RESEARCH.md` — Phase 39 findings: Agent Client Protocol concepts, Cantrip integration shapes evaluated, verdict and revisit triggers
- `design/DEFERRED.md` — Phase 84 deferred-item sweep log: every "Deferred:" entry across the roadmap with revisit triggers, audit cadence, and next sweep date
- `design/K8S_TOOL.md` — Phase 86 findings: should the agent grow first-class `kubectl` diagnostics? Verdict (skill expansion now, typed tool deferred), verb shortlist, sandbox/kubeconfig finding, revisit triggers
- `design/PAUSE_AND_EDIT.md` — Phase 83 findings: should Cantrip soften its hard-cancel into a pausable, editable mid-turn affordance? Verdict (defer; queue-next-instruction is the smaller follow-up shape if a trigger fires), peer-interrupt survey, message-flow shapes, three revisit triggers for Phase 83b
- `design/PROFILING.md` — Phase 87.3 findings: Sloth fits as a skill subsection (lands as new sub-phase 87.4), Parca/Pyroscope tooling defers to standalone Phase 89 against four named triggers; mirrors `TempoWaterfallTool` if it ships
- `ROADMAP.md` — Implementation phases (active/open work only)
- `ROADMAP_ARCHIVE.md` — Completed phases, full detail, historical record
- `CHANGELOG.md` — Notable changes (keep updated)
- `docs/docs/` — Published HTML user docs (tutorial, how-to, reference, explanation). Source of truth for user-facing behaviour — update alongside shipped features.
