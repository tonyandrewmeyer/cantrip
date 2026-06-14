# Cantrip CLI Overview

*2026-04-18T10:05:05Z by Showboat 0.6.1*
<!-- showboat-id: 16dc2b73-95a1-4fbc-b925-8012a71307db -->

Cantrip is an AI-powered autonomous agent that builds production-quality Juju charms. Describe your workload, and Cantrip researches it, designs the charm, writes the code, deploys it, tests it, and debugs it.

This demo introduces the top-level CLI and the sibling tools shipped in the same package: `charmlint` and `quickpack`.

## Version and top-level help

```bash
uv run cantrip --version
```

```output
cantrip 0.1.0
```

```bash
uv run cantrip --help
```

```output
usage: cantrip [-h] [--version] {run,export-transcript} ...

A small spell for building Juju charms

positional arguments:
  {run,export-transcript}
    run                 Run cantrip agent
    export-transcript   Export a session transcript

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
```

## Subcommand: `cantrip run`

The primary workflow — start an agent on a charm directory. Providers include Gemini, Claude, and a local inference snap.

```bash
uv run cantrip run --help
```

```output
usage: cantrip run [-h] [--provider {gemini,claude,inference-snap}]
                   [--model MODEL] [--snap SNAP] [--light-model LIGHT_MODEL]
                   [--light-snap LIGHT_SNAP]
                   [--light-provider {gemini,claude,inference-snap}]
                   [--no-tui] [--web] [--web-port WEB_PORT] [--watcher]
                   [--concurrency CONCURRENCY] [--improve CHARM_PATH]
                   [--theme THEME]
                   [path]

positional arguments:
  path                  Path to charm project (default: current directory)

options:
  -h, --help            show this help message and exit
  --provider {gemini,claude,inference-snap}
                        LLM provider to use (default: gemini)
  --model MODEL         Specific model to use (provider-dependent)
  --snap SNAP           Inference snap name when using --provider inference-
                        snap (default: gemma3)
  --light-model LIGHT_MODEL
                        Cheaper model for internal tasks like compaction
                        (auto-detected if omitted)
  --light-snap LIGHT_SNAP
                        Lighter inference snap for internal tasks (e.g.
                        nemotron-3-nano)
  --light-provider {gemini,claude,inference-snap}
                        Use a different provider for light tasks (enables
                        hybrid mode)
  --no-tui              Run in CLI mode without TUI
  --web                 Run with a browser-based Web UI instead of the TUI
  --web-port WEB_PORT   Port for the Web UI (default: 8471)
  --watcher             Start the event watcher on launch (monitors dev model
                        for changes)
  --concurrency CONCURRENCY
                        Maximum concurrent subagent tasks (default: 3)
  --improve CHARM_PATH  Improve an existing charm at the given path (audit,
                        fix, redeploy)
  --theme THEME         TUI colour theme (cantrip, ubuntu, monokai, solarized-
                        dark, light)
```

Notable flags:

- `--provider` — Gemini (default), Claude, or a local `inference-snap`. Hybrid mode uses a cheaper provider for internal tasks like compaction.
- `--improve` — audit an existing charm and fix issues rather than starting from scratch.
- `--web` — serve a browser UI instead of the terminal TUI.
- `--watcher` — monitor the dev model for changes and react to them.
- `--theme` — Ubuntu, Monokai, Solarized-dark, Light, or the default Cantrip theme.

## Sibling tools

The same package installs two standalone helpers that Cantrip uses internally but can be run on their own:

```bash
uv run charmlint --help | head -20
```

```output
usage: charmlint [-h] [--format {text,json}] [--select SELECT]
                 [--ignore IGNORE] [--severity {error,warning,info}]
                 [--config CONFIG] [--strict] [--no-colour]
                 [path]

Lint a Juju charm for best practices, observability, testing, and more.

positional arguments:
  path                  Path to the charm directory (default: current
                        directory)

options:
  -h, --help            show this help message and exit
  --format {text,json}  Output format (default: text)
  --select SELECT       Comma-separated list of rule categories to enable
                        (e.g. COS,META)
  --ignore IGNORE       Comma-separated list of rule IDs or categories to skip
  --severity {error,warning,info}
                        Minimum severity to report
  --config CONFIG       Path to .charmlint.yaml config file
```

```bash
uv run quickpack --help
```

```output
usage: quickpack [-h] [--output-dir OUTPUT_DIR] [--quiet]
                 [--verify-attestations]
                 [charm_dir]

Fast local charm packing for development workflows.

positional arguments:
  charm_dir             Path to the charm project directory (default: current
                        directory).

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR, -o OUTPUT_DIR
                        Directory to write the .charm file to (default: charm
                        directory).
  --quiet, -q           Suppress progress output.
  --verify-attestations
                        Require a PEP 740 PyPI attestation for every installed
                        dependency. Must-have packages (ops, ops-scenario,
                        ops-tracing, jubilant, charmlibs-*) are always
                        enforced even without this flag.
```

See `demos/02-charmlint.md` and `demos/03-quickpack.md` for full walkthroughs of each tool.
