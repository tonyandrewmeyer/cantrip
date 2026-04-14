# Cantrip

*A small spell for building Juju charms*

Cantrip is an AI-powered agent that helps you build production-quality [Juju charms](https://juju.is/) through natural conversation.

```
> build a charm for my Flask app

Creating a 12-factor charm for your Flask application...
✓ Detected Flask 2.3
✓ Generated rockcraft.yaml
✓ Building rock...
✓ Deployed to dev model
✓ Status: active

Your charm is running! What would you like to add?
- Database integration (PostgreSQL, MySQL)
- Ingress (Traefik)
- Observability (COS)
```

## Features

- **Fast start**: Get a working charm in minutes, then iterate
- **Conversational**: Describe what you want in plain English
- **Observable**: Built-in COS integration, agent uses traces to debug
- **Ecosystem showcase**: Integrates with Juju, Charmcraft, Rockcraft, Jubilant, Concierge

## Installation

```bash
# Clone the repository
git clone https://github.com/tonyandrewmeyer/cantrip
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
# Start in current directory
cantrip

# Start with a specific charm path
cantrip /path/to/my-charm

# Use Claude instead of Gemini
cantrip --provider claude
```

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Lint
uv run ruff check src tests

# Type check
uv run mypy src
```

## Documentation

- [PLAN.md](design/PLAN.md) - Project decisions and architecture
- [ROADMAP.md](ROADMAP.md) - Implementation phases
- [UI.md](design/UI.md) - UI design
- [AGENT.md](design/AGENT.md) - Agent architecture

## Licence

Apache 2.0
