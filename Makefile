.PHONY: format lint unit integration e2e test check all clean

# Format code with ruff
format:
	uv run ruff format src tests

# Run all linting (ruff check + ty)
lint:
	uv run ruff check src tests
	uv run ty check src

# Run unit tests
unit:
	uv run pytest tests/unit -v

# Run integration tests (real tools, no external services)
integration:
	uv run pytest tests/integration -v

# Run end-to-end tests (multi-turn scripted scenarios)
e2e:
	uv run pytest tests/e2e -v

# Run all tests (unit + integration + e2e)
test:
	uv run pytest tests -v

# Run all checks (lint + unit tests)
check: lint unit

# Run everything (format + check)
all: format check

# Clean build artifacts
clean:
	rm -rf .pytest_cache .ruff_cache .ty_cache
	rm -rf dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Install dependencies
install:
	uv sync --dev

# Show help
help:
	@echo "Available targets:"
	@echo "  format      - Format code with ruff"
	@echo "  lint        - Run ruff check and ty type checker"
	@echo "  unit        - Run unit tests"
	@echo "  integration - Run integration tests (real tools, no external services)"
	@echo "  e2e         - Run end-to-end scenario tests"
	@echo "  test        - Run all tests (unit + integration + e2e)"
	@echo "  check       - Run lint + unit tests"
	@echo "  all         - Run format + check"
	@echo "  clean       - Remove build artifacts"
	@echo "  install     - Install dependencies"
