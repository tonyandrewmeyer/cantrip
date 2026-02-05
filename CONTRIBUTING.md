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
uv run pytest tests/unit -v

# With coverage
uv run pytest tests/unit -v --cov=cantrip --cov-report=term-missing

# Integration tests (requires Juju)
uv run pytest tests/integration -v
```

### Linting and Formatting

```bash
# Check linting
uv run ruff check src tests

# Auto-fix linting issues
uv run ruff check --fix src tests

# Check formatting
uv run ruff format --check src tests

# Auto-format
uv run ruff format src tests

# Type checking
uv run mypy src
```

### Running the Application

```bash
# With Gemini (default)
export GEMINI_API_KEY='your-key'
uv run cantrip

# With Claude
export ANTHROPIC_API_KEY='your-key'
uv run cantrip --provider claude

# CLI mode (no TUI)
uv run cantrip --no-tui
```

## Code Style

- **Language**: UK English for all user-facing text, comments, and documentation
- **Formatting**: Handled by ruff (line length 99)
- **Type hints**: Required for all functions
- **Docstrings**: Google style

### Example

```python
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
   uv run ruff check src tests
   uv run ruff format --check src tests
   uv run mypy src
   uv run pytest tests/unit -v
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
├── src/cantrip/
│   ├── main.py           # Entry point
│   ├── cli.py            # CLI mode
│   ├── tui/              # Textual TUI
│   ├── llm/              # LLM providers
│   ├── agent/            # Agent logic
│   ├── juju/             # Juju integration
│   └── charm/            # Charm scaffolding
├── tests/
│   ├── unit/             # Unit tests
│   └── integration/      # Integration tests (require Juju)
└── docs/                 # Documentation
```

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include reproduction steps for bugs
- Check existing issues before creating new ones

## Questions?

Feel free to open a discussion on GitHub or reach out to the maintainers.
