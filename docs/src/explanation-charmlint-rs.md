---
title: "Charmlint Rust backend — Cantrip"
description: "Why charmlint has a Rust implementation, how Cantrip selects it, and measured performance."
h1: "Charmlint Rust backend"
subtitle: "A compiled alternative to the Python charmlint that completes a full lint run in under 30&nbsp;ms."
section: explanation
breadcrumb_label: "Charmlint Rust backend"
on_this_page:
  - { anchor: "background", label: "Background" }
  - { anchor: "architecture", label: "Architecture" }
  - { anchor: "selection", label: "How the backend is selected" }
  - { anchor: "performance", label: "Performance" }
  - { anchor: "building", label: "Building from source" }
  - { anchor: "testing", label: "Running the tests" }
  - { anchor: "limitations", label: "Limitations" }
---

{#background}
## Background

**Charmlint** is Cantrip's deterministic charm linter.
It checks charms against 40+ rules across 12 categories —
metadata completeness, COS integration, testing, deprecated APIs,
actions, config quality, security, structure, documentation,
libraries, charmcraft compatibility, and status reporting.

Unlike quickpack, charmlint is a pure CPU tool with no subprocess
calls.  All the work is YAML parsing, regex matching, and file
traversal — exactly the kind of workload where Rust excels.
The Rust implementation (`src/charmlint-rs/`) delivers
the full speedup with no bottleneck to cap it.

{#architecture}
## Architecture

The Rust binary mirrors the Python package:

| Python module | Rust module | Responsibility |
|---|---|---|
| `cli.py` | `main.rs` | CLI argument parsing (clap), output formatting |
| `linter.py` | `linter.rs` | Rule filtering, severity overrides, min-severity |
| `rules/*.py` | `rules.rs` | All 40+ rules (single file, grouped by category) |
| `models.py` | `models.rs` | Diagnostic, Severity, CharmContext, LintReport |
| `config.py` | `config.rs` | `.charmlint.yaml` loader |
| — | `context.rs` | Charm context builder (YAML, Python sources, tests) |

Both implementations share the same command-line interface:

```
charmlint [path] [--format text|json] [--select CATS] [--ignore RULES]
         [--severity LEVEL] [--config PATH] [--strict] [--no-color]
```

The Rust version produces identical JSON output structure, identical
rule IDs and messages, and identical exit codes (0&nbsp;=&nbsp;clean,
1&nbsp;=&nbsp;errors, 2&nbsp;=&nbsp;warnings in strict mode).

{#selection}
## How the backend is selected

When the agent's `charmlint` tool is invoked, it checks
for the Rust binary in two locations:

1. `charmlint-rs` on `$PATH`.
2. The in-tree build artefact at
   `src/charmlint-rs/target/release/charmlint`.

If found, the tool invokes the binary with `--format json`,
parses the output, and returns it to the agent.  If neither location
has a binary, it falls back to the Python `charmlint`
library transparently.  The `backend` field in the tool
result data indicates which implementation was used.

The `charm_audit` tool always uses the Python library
directly because it needs to inspect individual
`Diagnostic` objects for structured report generation.

{#performance}
## Performance

Benchmarks on an Ubuntu 24.04 machine (x86_64), linting a minimal
charm project:

| Metric | Rust | Python | Speedup |
|---|---|---|---|
| Startup (`--help`) | ~33 ms | ~177 ms | **5.4×** |
| Full lint (all rules) | ~27 ms | ~181 ms | **6.7×** |

The full lint run in Rust is actually faster than Python’s
startup alone.  Since charmlint is a pure CPU tool — YAML
parsing, regex matching, and filesystem stat calls — there is
no subprocess bottleneck to limit the speedup.

In the agent's build–test–debug loop, charmlint typically
runs after every code change.  At 27&nbsp;ms, it adds negligible
latency to the iteration cycle.

{#building}
## Building from source

The Rust toolchain (1.70+) is required.  From the repository root:

```
cd src/charmlint-rs
cargo build --release
```

The binary is written to
`src/charmlint-rs/target/release/charmlint`.  Cantrip
will find it automatically at this location.  To install system-wide:

```
sudo cp src/charmlint-rs/target/release/charmlint /usr/local/bin/charmlint-rs
```

{#testing}
## Running the tests

The Rust implementation has its own spread test suite at
`tests/spread/charmlint-rs/task.yaml`.  It runs 43 of
the 45 tests from the Python suite (excluding the
<code>python&nbsp;-m&nbsp;charmlint</code> test).  To run locally:

```
spread tests/spread/charmlint-rs
```

{#limitations}
## Limitations

- The `charm_audit` tool still uses the Python library
  because it processes `Diagnostic` objects directly.
  This means audit runs do not benefit from the Rust speedup.
- The Rust binary does not expose a library API — it is a
  standalone CLI tool only.
- New rules added to the Python version must be ported manually to
  the Rust implementation.

See also:

- [Quickpack Rust backend](explanation-quickpack-rs.html)
- [How Cantrip works](explanation-architecture.html)
- [Agent tools](reference-tools.html)
