.PHONY: format lint unit integration e2e tui live eval eval-validate test check all clean coverage rust-test rust-coverage

# Format code with ruff
format:
	uv run ruff format src tests

# Run all linting (ruff check + ruff format check + ty)
lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run ty check src

# Run unit tests (with coverage, parallel across cores via pytest-xdist).
# pytest-cov handles the coverage combine step automatically.
unit:
	uv run pytest tests/unit -n auto --cov=cantrip --cov-report=term-missing

# Run integration tests (real tools, no external services)
integration:
	uv run pytest tests/integration -v

# Run end-to-end tests (multi-turn scripted scenarios)
e2e:
	uv run pytest tests/e2e -v

# Run TUI tests
tui:
	uv run pytest tests/unit/test_tui.py -v

# Run gold-standard evaluation tests
eval:
	uv run pytest tests/eval -v

# Validate gold standards score 100%
eval-validate:
	uv run python -m tests.eval.runner validate

# Run live tests (require real Juju/LLM services)
live:
	uv run pytest tests/live -v

# Run all tests (unit + integration + e2e)
test:
	uv run pytest tests -v

# Run all checks (lint + unit tests + Rust crate tests)
check: lint unit rust-test

# Run everything (format + check)
all: format check

# Run unit tests with coverage report (parallel + HTML output)
coverage:
	uv run pytest tests/unit -n auto --cov=cantrip --cov-report=term-missing --cov-report=html

# Run cargo test for each Rust crate
rust-test:
	cd src/charmlint-rs && cargo test
	cd src/quickpack-rs && cargo test

# Run cargo-llvm-cov for each Rust crate (advisory — see Phase 58.4).
# Install once: cargo install cargo-llvm-cov && rustup component add llvm-tools-preview
rust-coverage:
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { \
		echo "cargo-llvm-cov not installed."; \
		echo "Install: cargo install cargo-llvm-cov && rustup component add llvm-tools-preview"; \
		exit 1; \
	}
	cd src/charmlint-rs && cargo llvm-cov --summary-only
	cd src/quickpack-rs && cargo llvm-cov --summary-only

# Clean build artifacts
clean:
	rm -rf .pytest_cache .ruff_cache .ty_cache .coverage .coverage.* htmlcov
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
	@echo "  tui         - Run TUI tests"
	@echo "  eval        - Run gold-standard evaluation tests"
	@echo "  eval-validate - Validate gold standards score 100%%"
	@echo "  live        - Run live tests (Juju, LLM APIs)"
	@echo "  test        - Run all tests (unit + integration + e2e)"
	@echo "  check       - Run lint + unit tests"
	@echo "  all         - Run format + check"
	@echo "  coverage    - Run unit tests with coverage report"
	@echo "  rust-test   - Run cargo test for charmlint-rs and quickpack-rs"
	@echo "  rust-coverage - Run cargo-llvm-cov summary for each Rust crate"
	@echo "  clean       - Remove build artifacts"
	@echo "  install     - Install dependencies"
