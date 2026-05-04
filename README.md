# Cantrip

*A small spell for building Juju charms*

> **⚠ Experimental, pre-1.0 software — run inside a VM only.**
>
> Cantrip is early, exploratory work. Interfaces, on-disk layouts, slash
> commands, tool surfaces, and defaults will change without notice, and
> there is no API or behavioural stability guarantee until 1.0. Treat it
> accordingly.
>
> Cantrip is an autonomous agent: it executes shell commands, edits
> files, packs and deploys charms, and talks to Juju controllers and
> Kubernetes substrates on your behalf. Steps have been taken to keep
> it well-behaved — sandboxed tool execution, an allow-listed command
> surface, confirmation prompts for risky actions, scoped file access —
> but **you should only run Cantrip inside a disposable virtual machine
> or dedicated test environment**, never against production systems,
> personal home directories, or controllers you cannot afford to lose.
> Use a fresh VM, point it at a throwaway Juju model, and assume any
> mistake the agent makes can affect the entire machine it runs on.

Cantrip is an AI-powered **autonomous agent** that builds production-quality [Juju charms](https://juju.is/) independently. Describe your workload, and Cantrip researches it, designs the charm, writes the code, deploys it, tests it, and debugs it — with you confirming key decisions and providing domain expertise.

**Quick start**

- **Just use Cantrip:** `uv tool install juju-cantrip`
- **Contribute to Cantrip:** clone this repo and run `uv sync --dev`

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
- **Charm linting**: Standalone `charmlint` tool with 40+ deterministic rules across 12 categories. Optional Rust backend completes a full lint in under 30 ms
- **Durable memory**: Persistent lessons across sessions and charms — user corrections are auto-captured as rules, hard-won workarounds become lessons with SHA-256 citations that self-quarantine when the source drifts. Manage with `/memory`, `/remember`, `/forget`
- **MCP-extensible**: Plug in third-party tools via the Model Context Protocol — stdio or HTTP servers, OAuth 2.1, token storage, mid-task elicitation, and marketplace discovery
- **Ecosystem showcase**: Juju, Charmcraft, Rockcraft, Ops, Jubilant, Concierge, Scenario, Showboat

## Install to use Cantrip

```bash
# Install the CLI
uv tool install juju-cantrip

# Set your API key
export GEMINI_API_KEY='your-key-here'

# Run
cantrip
```

See [`docs/docs/howto-provider.html`](docs/docs/howto-provider.html) for
other provider setups and [`docs/docs/howto-interface.html`](docs/docs/howto-interface.html)
for choosing between the TUI, Web UI, CLI REPL, and print mode.

## Contributor checkout

```bash
# Clone the repository
git clone https://github.com/tonyandrewmeyer/cantrip
cd cantrip

# Install dev dependencies
uv sync --dev

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

In the chat itself, slash commands let you drive persistent memory and
inspect configured MCP servers without leaving the conversation:

```
/memory                 # list every remembered lesson
/remember lesson -- uv-lock-stale -- Run `uv lock` before charmcraft pack.
/forget uv-lock-stale

/mcp                    # list configured MCP servers and their status
/mcp tools charmhub     # list tools a particular server exposes
/mcp marketplace        # browse server catalogues you've subscribed to
```

See [`docs/docs/howto-memory.html`](docs/docs/howto-memory.html) and
[`docs/docs/howto-mcp.html`](docs/docs/howto-mcp.html) for full
workflows.

Skills authored for the vendor-neutral ecosystem (Claude Code,
`gh skill install`, Cursor, Codex, Gemini CLI, Windsurf) work with
Cantrip unchanged — drop a standard SKILL.md into
`~/.claude/skills/`, `~/.config/agents/skills/`, or
`~/.config/cantrip/skills/`, or install via GitHub CLI:

```bash
gh skill install microsoft/skills/harness-migration   # project-scope, into <charm>/.agents/skills/
```

`cantrip skill export NAME PATH` writes any discovered skill back
out in the same format, sanitising charm paths and secrets. See
[`docs/docs/howto-skills.html`](docs/docs/howto-skills.html).

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
- [ROADMAP.md](ROADMAP.md) — Implementation phases (active work); [ROADMAP_ARCHIVE.md](ROADMAP_ARCHIVE.md) for completed phases
- [CHANGELOG.md](CHANGELOG.md) — Notable changes

## Licence

Apache 2.0
