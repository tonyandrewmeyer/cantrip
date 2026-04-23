---
title: "Quickpack Rust backend — Cantrip"
description: "Why quickpack has a Rust implementation, how Cantrip selects it, and measured performance."
h1: "Quickpack Rust backend"
subtitle: "A compiled alternative to the Python quickpack that reduces packing overhead and startup latency."
section: explanation
breadcrumb_label: "Quickpack Rust backend"
on_this_page:
  - { anchor: "background", label: "Background" }
  - { anchor: "architecture", label: "Architecture" }
  - { anchor: "selection", label: "How the backend is selected" }
  - { anchor: "performance", label: "Performance" }
  - { anchor: "building", label: "Building from source" }
  - { anchor: "testing", label: "Running the tests" }
---

{#background}
## Background

**Quickpack** is Cantrip's fast, local-only alternative to
`charmcraft pack`.  It skips LXD builds, linting, and
analysis, producing a valid `.charm` file suitable for
development deploys and upgrade testing.  The original implementation
is written in Python and lives in `src/quickpack/`.

Because the agent packs charms frequently during its
build–test–debug loop, even small latency reductions
compound.  The Rust implementation (`src/quickpack-rs/`)
eliminates the Python interpreter startup cost and handles file I/O
and ZIP compression natively, while producing byte-compatible output.

{#architecture}
## Architecture

The Rust binary mirrors the Python package module-for-module:

| Python module | Rust module | Responsibility |
|---|---|---|
| `cli.py` | `main.rs` | CLI argument parsing (clap) |
| `pack.py` | `pack.rs` | Orchestration, dispatch script, ZIP creation |
| `parts.py` | `parts.rs` | UV and dump plugin processing |
| `metadata.py` | `metadata.rs` | YAML parsing, metadata/manifest generation |
| `jujuignore.py` | `jujuignore.rs` | Gitignore-style pattern matching |

Both implementations share the same command-line interface:

```
quickpack [charm_dir] [--output-dir DIR] [--quiet]
```

The Rust version does *not* expose a Python importable API
— it is a standalone binary only.  Both versions shell out to
`uv venv` and `uv sync` to build the charm's
virtual environment; that subprocess call is identical in both cases
and dominates the total wall-clock time.

{#selection}
## How the backend is selected

When the agent's `quick_pack` tool is invoked, it checks
for the Rust binary in two locations, in order:

1. `quickpack-rs` on `$PATH` — this is
   the installed name, useful when the binary has been placed in
   `/usr/local/bin` or similar.
2. The in-tree build artefact at
   `src/quickpack-rs/target/release/quickpack`, relative
   to the cantrip package directory.

If neither is found, the tool falls back to the Python
`quickpack` library transparently.  The
`backend` field in the tool result data indicates which
implementation was used (`"rust"` or
`"python"`).

{#performance}
## Performance

Benchmarks on an Ubuntu 24.04 machine (x86_64), packing a minimal
charm with one `ops` dependency:

| Metric | Rust | Python | Speedup |
|---|---|---|---|
| Startup (`--help`) | ~43 ms | ~215 ms | **5×** |
| Full pack (incl. `uv sync`) | ~0.31 s | ~0.63 s | **~2×** |

The full-pack speedup is bounded by `uv sync`, which
accounts for the majority of wall-clock time in both
implementations.  The Rust advantage is most visible in the
non-`uv` overhead: file copying, YAML
serialisation, ZIP compression, and process startup.

For charms with large dependency trees or slow networks, the relative
speedup shrinks because `uv sync` dominates further.  For
charms with few or no dependencies, the ~5× startup advantage
is more visible.

{#building}
## Building from source

The Rust toolchain (1.70+) is required.  From the repository root:

```
cd src/quickpack-rs
cargo build --release
```

The binary is written to
`src/quickpack-rs/target/release/quickpack`.  Cantrip
will find it automatically at this location.  To install system-wide:

```
sudo cp src/quickpack-rs/target/release/quickpack /usr/local/bin/quickpack-rs
```

{#testing}
## Running the tests

The Rust implementation has its own spread test suite at
`tests/spread/quickpack-rs/task.yaml`.  It runs the same
24 functional tests as the Python version (the
<code>python&nbsp;-m&nbsp;quickpack</code> test is excluded as
Python-specific).  To run locally:

```
spread tests/spread/quickpack-rs
```

The Python test suite remains the canonical source of truth.  The
Rust suite verifies output compatibility: both implementations must
produce structurally identical `.charm` archives.

See also:

- [How Cantrip works](explanation-architecture.html)
- [Agent tools](reference-tools.html)
