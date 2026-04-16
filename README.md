# Cantrip

*A small spell for building Juju charms*

Cantrip is an AI-powered **autonomous agent** that builds production-quality [Juju charms](https://juju.is/) independently. Describe your workload, and Cantrip researches it, designs the charm, writes the code, deploys it, tests it, and debugs it — with you confirming key decisions and providing domain expertise.

```
> build a charm for Redis

Researching Redis operational requirements...
✓ Design proposed — 4 integrations, 3 actions, backup/restore support
  Waiting for your confirmation...

> looks good, go ahead

Planning tasks...
  ├─ ✓ Write integration tests (Jubilant)
  ├─ ✓ Scaffold charm with ops framework
  ├─ ✓ Implement charm code (red/green iteration)
  ├─ ✓ Pack and deploy to dev model
  ├─ ✓ Run acceptance tests (actions, relations, config)
  ├─ ✓ Wire COS observability
  ├─ ● Operational readiness assessment...
  └─   Generate demo and docs

Status: active | 3 subagents working
```

## Features

- **Autonomous**: Two concurrent loops — you steer, the agent drives. Subagents handle research, build, deploy, test, and debug tasks in parallel
- **Research-driven**: Analyses workloads via web search, Charmhub, and documentation before proposing a design with companion charms
- **Test-first**: Integration tests written before charm code; acceptance tests exercise every action, relation, config option, and endpoint
- **Observable**: COS integration baked in — traces, metrics, logs, and dashboards via ops-tracing, Prometheus, Loki, and Grafana; multi-controller COS auto-detected
- **Improvement mode**: Audit existing charms, modernise deprecated APIs, add tests, fill observability gaps, check operational readiness
- **Day-2 aware**: Researches backup/restore, scaling, HA, upgrades, and security hardening after initial build
- **Quickpack**: Ultra-fast local charm packing — 20-100x faster than `charmcraft pack`, skipping LXD, linting, and analysis. Optional Rust backend with ~50 ms startup for tight build-test loops
- **Charm linting**: Standalone `charmlint` tool with 35 deterministic rules across 10 categories
- **Ecosystem showcase**: Juju, Charmcraft, Rockcraft, Ops, Jubilant, Concierge, Scenario, Showboat

## Installation

```bash
# Clone the repository
git clone https://github.com/canonical/cantrip
cd cantrip

# Install with uv
uv sync

# Set your API key
export GEMINI_API_KEY='your-key-here'

# Run
uv run cantrip
```

## Usage

```bash
# Start the TUI in current directory
cantrip

# Start with a specific charm path
cantrip /path/to/my-charm

# Use the Web UI instead
cantrip --web

# Improve an existing charm (audit, fix, redeploy)
cantrip --improve /path/to/existing-charm

# Use Claude instead of Gemini
cantrip --provider claude

# Use a local inference snap (no API key needed)
cantrip --provider inference-snap --snap gemma3

# CLI mode (no TUI)
cantrip --no-tui

# Choose a colour theme
cantrip --theme ubuntu

# Export a session transcript
cantrip export-transcript /path/to/my-charm --format html --page-size 50
```

## Development

```bash
# Install dev dependencies
uv sync --dev

# Format, lint, and test
make all        # format + lint + unit tests

# Or individually:
make format     # ruff format
make lint       # ruff check + ty type checker
make unit       # pytest unit tests
make coverage   # unit tests with coverage report
```

## Documentation

- [PLAN.md](design/PLAN.md) — Architecture decisions and design philosophy
- [AGENT.md](design/AGENT.md) — Agent architecture (two-loop design, subagents, work queue)
- [UI.md](design/UI.md) — Shared UI design (TUI + Web), event bus, layout, shortcuts
- [ROADMAP.md](ROADMAP.md) — Implementation phases
- [CHANGELOG.md](CHANGELOG.md) — Notable changes

## Licence

Apache 2.0
