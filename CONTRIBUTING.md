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
# Parametrised over Flask, Django, FastAPI, Go, and a machine charm.
uv run pytest tests/e2e -m e2e -v

# Just one framework
uv run pytest tests/e2e/test_paas_charm_build.py -k django -v

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
└── docs/                        # Landing page
```

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include reproduction steps for bugs
- Check existing issues before creating new ones

## Questions?

Feel free to open a discussion on GitHub or reach out to the maintainers.
