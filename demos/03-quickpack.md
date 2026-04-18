# quickpack: Ultra-fast local charm packing

*2026-04-18T10:06:32Z by Showboat 0.6.1*
<!-- showboat-id: 088d9c3a-f8f3-4f43-8c0c-ede3b3aedbf5 -->

`quickpack` is a drop-in replacement for `charmcraft pack` aimed at the build-test loop. It skips LXD, linting, and analysis — producing a usable `.charm` file in **20–100× less time** than charmcraft on most projects. An optional Rust backend brings startup to around 50 ms for the tightest red/green iterations.

This demo shows the CLI surface; actual packing needs the full charm build toolchain available on the host.

## CLI

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

## How it works

The implementation lives in a handful of small modules:

```bash
ls src/quickpack/ | grep -v __
```

```output
cli.py
jujuignore.py
metadata.py
pack.py
parts.py
```

| Module | Responsibility |
|--------|----------------|
| `cli.py` | Argparse entry point, flags, and exit handling |
| `pack.py` | Orchestrates the pack — reads metadata, assembles parts, writes the ZIP |
| `parts.py` | Builds each part (charm source, libraries, dispatch, hooks) |
| `metadata.py` | Parses `charmcraft.yaml`/`metadata.yaml` |
| `jujuignore.py` | Filters files via `.jujuignore` and built-in excludes |

## Supply-chain safety

Cantrip cares about where dependencies come from. With `--verify-attestations`, `quickpack` requires a PEP 740 PyPI attestation for every installed dependency. Even without the flag, the core packages (`ops`, `ops-scenario`, `ops-tracing`, `jubilant`, `charmlibs-*`) are always enforced — so they can't silently be swapped for a malicious copy.

## Typical usage

From the root of a charm directory:

```bash
# Pack the current directory, write .charm to its root
quickpack

# Pack a specific charm, write to a build dir
quickpack --output-dir build/ path/to/my-charm

# Strict supply-chain mode
quickpack --verify-attestations
```

See `demos/06-agent-architecture.md` for how the agent invokes `quickpack` during the build loop.
