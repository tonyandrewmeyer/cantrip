# Contributing to Cantrip

We welcome contributions to Cantrip! This document explains how to get involved.

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/cantrip
   cd cantrip
   ```
3. Install dependencies:
   ```bash
   uv sync --dev
   ```
4. Install pre-commit hooks:
   ```bash
   uv run pre-commit install
   ```

## Development Workflow

### Running Tests

```bash
# Unit tests
make unit

# With coverage
make coverage

# Run a single test
uv run pytest tests/unit/test_tools.py -v
uv run pytest tests/unit/test_tools.py::test_function_name -v

# Integration tests (requires Juju)
uv run pytest tests/integration -v

# End-to-end charm-build tests (requires Juju + GEMINI_API_KEY)
# Parametrised over Flask, Django, FastAPI, Go, a machine charm,
# plus a research-driven test that starts from a user-style prompt.
uv run pytest tests/e2e -m e2e -v

# Just one framework
uv run pytest tests/e2e/test_paas_charm_build.py -k django -v

# Just the research-driven path (agent plans the whole thing from scratch)
uv run pytest tests/e2e/test_research_charm_build.py -v

# Switch the e2e provider (default: gemini). Handy when one provider's
# daily quota is exhausted.
CANTRIP_E2E_PROVIDER=claude uv run pytest tests/e2e -m e2e -v

# All checks (lint + unit)
make check
```

### Linting and Formatting

```bash
# Format and check everything
make all

# Or individually:
make format     # ruff format
make lint       # ruff check + ty type checker

# Or by hand:
uv run ruff check src tests
uv run ruff format src tests
uv run ty check src
```

### Editing the Docs Site

User-facing docs live under `docs/` and are authored as markdown in
`docs/src/*.md`. The build script `docs/src/_build.py` renders them
to `docs/docs/*.html` via markdown-it-py + Jinja2; the HTML is
committed so that `README.md` cross-links like
`docs/docs/howto-memory.html` resolve on GitHub.

```bash
# Edit the markdown source, not the HTML.
$EDITOR docs/src/howto-memory.md

# Rebuild the HTML.
make docs

# Commit both files together.
git add docs/src/howto-memory.md docs/docs/howto-memory.html
```

CI runs `make docs-check-strict` on every push and PR, which
rebuilds into a temp dir and fails on any byte-level diff against
the committed HTML. If the check fails locally, run `make docs`,
inspect the diff, and commit the regenerated output.

Authoring conventions (curly quotes, entity handling, raw-HTML
escape hatches for callouts / prompt-styled code blocks / the
landing-page doc-cards grid) are documented in
[`design/DOCS_REBUILD.md`](design/DOCS_REBUILD.md).

### Cookbook recipes

Runnable charm-building recipes live under
[`cookbook/`](cookbook/README.md). Each recipe is a self-contained
directory with a walkthrough `README.md`, copy-paste `prompts.md`,
and a `verify.py` that asserts the resulting charm matches the
shape the recipe teaches. The verifiers double as regression
tests — `tests/unit/test_cookbook_recipes.py` runs each verifier
in CI against hand-written fixtures, so a recipe can't be merged
with a broken format or drift from its promised output.

Live Cantrip runs (LLM + charmcraft + juju) are deliberately
**not** part of CI. To add a new recipe, copy
`cookbook/build-a-sprint-charm/` as a template and update the
verifier to match your recipe's guarantees.

### Running the Application

```bash
# With Gemini (default)
export GEMINI_API_KEY='your-key'
uv run cantrip

# With Claude
export ANTHROPIC_API_KEY='your-key'
uv run cantrip --provider claude

# With local inference snap (no API key)
uv run cantrip --provider inference-snap --snap gemma3

# CLI mode (no TUI)
uv run cantrip --no-tui

# Web UI
uv run cantrip --web
```

## Code Style

- **Language**: UK English for all user-facing text, comments, and documentation (colour, behaviour, analyse)
- **Formatting**: Handled by ruff (line length 99)
- **Type checker**: `ty`, not mypy
- **Type hints**: Required; use modern style (`str | None` not `Optional[str]`)
- **Imports**: Always at top of module; import modules, not classes/methods (`import datetime` not `from datetime import datetime`)
- **Comments**: Explain *why*, not *how* — rare, full sentences, ending with punctuation
- **Docstrings**: Essential; Google style
- **Error handling**: Never catch bare `Exception` — always be specific; minimise code inside try/except blocks
- **Data structures**: Use `dataclasses` from stdlib, not Pydantic

### Example

```python
import datetime


def parse_status(data: dict[str, Any]) -> ModelStatus:
    """Parse Juju status from JSON.

    Args:
        data: Raw JSON data from `juju status --format=json`.

    Returns:
        Parsed model status.

    Raises:
        ValueError: If the data is malformed.
    """
    ...
```

## Pull Request Process

1. Create a branch for your changes:
   ```bash
   git checkout -b feature/my-feature
   ```

2. Make your changes and commit:
   ```bash
   git add .
   git commit -m "Add my feature"
   ```

3. Ensure all checks pass:
   ```bash
   make check
   ```

4. Push and create a pull request:
   ```bash
   git push origin feature/my-feature
   ```

5. Fill in the PR template with:
   - Description of changes
   - Related issues
   - Testing performed

## Project Structure

```
cantrip/
├── src/
│   ├── cantrip/
│   │   ├── main.py              # Entry point, arg parsing
│   │   ├── cli.py               # CLI mode (no TUI)
│   │   ├── agent/
│   │   │   ├── core.py          # Conversation loop, tool execution
│   │   │   ├── state.py         # AgentState and Decision dataclasses
│   │   │   ├── store.py         # SQLite-backed session store
│   │   │   ├── queue.py         # Work queue, task scheduling
│   │   │   ├── planner.py       # Task planner (LLM decomposition)
│   │   │   ├── executor.py      # Background executor (subagent dispatch)
│   │   │   ├── subagent.py      # Isolated LLM context per task
│   │   │   ├── tools/           # Agent tools (40+ tools across domains)
│   │   │   └── prompts/         # System prompts and subagent guidance
│   │   ├── llm/                 # LLM providers (Gemini, Claude, inference snap)
│   │   ├── tui/                 # Textual TUI (app, screens, widgets, themes)
│   │   ├── web/                 # Web UI (server, templates, static assets)
│   │   ├── transcript/          # Session transcript export (HTML, JSONL, Markdown)
│   │   ├── juju/                # Juju integration via Jubilant
│   │   ├── charm/               # Charm project templates
│   │   ├── skills/              # Skill definitions (SKILL.md per skill)
│   │   └── ui/                  # Shared event bus for TUI/Web/CLI
│   └── charmlint/               # Standalone charm linter (35 rules, 10 categories)
├── tests/
│   ├── unit/                    # Unit tests
│   └── integration/             # Integration tests (require Juju)
├── design/                      # Architecture docs (PLAN.md, AGENT.md, UI.md)
└── docs/                        # User docs site — landing page + Diátaxis tree
    ├── src/                     # Authored markdown sources (edit these)
    │   ├── _build.py            # markdown-it-py + Jinja2 renderer
    │   ├── _site.yaml           # Section nav / page ordering
    │   └── _templates/          # Shared page.html.j2 chrome
    └── docs/                    # Built HTML (run `make docs` to regenerate)
```

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include reproduction steps for bugs
- Check existing issues before creating new ones

## Questions?

Feel free to open a discussion on GitHub or reach out to the maintainers.
