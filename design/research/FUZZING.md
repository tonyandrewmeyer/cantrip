# Fuzzing

Cantrip's Hypothesis property tests under `tests/unit/**/*_properties.py`
are the default coverage layer for parser invariants — they ship as
part of `make unit` and run on every PR.  Hypothesis is good at
shrinking failures to minimal counter-examples, but it's a relatively
shallow random search.  For the Rust parsers in `charmlint-rs` and
`quickpack-rs` we layer **`cargo-fuzz`** on top so coverage-guided,
byte-oriented exploration can keep digging.

This lane is **advisory / nightly** — not gated on every PR.  Run it
locally before a release, after touching parser code, or when
investigating a suspected adversarial input.

## What's set up

Each Rust crate carries a `fuzz/` subdirectory with one
`fuzz_targets/*.rs` file per parser entry point.  The targets all
follow the same shape: take an arbitrary byte slice, feed it through
the function under test, and let libFuzzer record the panic if one
fires.

### `charmlint-rs/fuzz/`

| Target | Function exercised |
| --- | --- |
| `fuzz_lint_config_yaml` | `LintConfig::from_yaml` — random YAML → `serde_yaml::Value` → config walk |
| `fuzz_severity_from_str` | `Severity::from_str_loose` — random UTF-8 → severity |

### `quickpack-rs/fuzz/`

| Target | Function exercised |
| --- | --- |
| `fuzz_jujuignore_match` | `JujuIgnore::new` + `is_ignored` — random newline-split patterns + path |
| `fuzz_metadata_resolvers` | `resolve_base` + `resolve_entrypoint` + `generate_metadata` over arbitrary YAML mappings |

## Prerequisites

- Rust **nightly** (required by libFuzzer instrumentation):
  ```sh
  rustup toolchain install nightly --profile minimal
  ```
- `cargo-fuzz`:
  ```sh
  cargo install cargo-fuzz
  ```

## Running a target

From a crate directory:

```sh
cd src/charmlint-rs
cargo +nightly fuzz run fuzz_lint_config_yaml -- -max_total_time=60
```

The `-max_total_time=N` flag caps the run at N seconds; without it the
fuzzer runs until a crash or until Ctrl-C.  Typical smoke runs are
15–60 seconds; nightly soak runs can be hours.

A crash is dumped to
`fuzz/artifacts/<target>/crash-<hash>`.  Reproduce it directly with:

```sh
cargo +nightly fuzz run <target> fuzz/artifacts/<target>/crash-<hash>
```

## What goes back into the unit suite

When the fuzzer finds a crash, the fix lands with a small regression
test in the crate's existing `#[cfg(test)] mod tests` block that
exercises the same shape.  The first crash this lane found —
`JujuIgnore::new` panicking on a glob pattern whose regex expansion
produced an invalid character class (`[0-]`) — is pinned by
`pattern_producing_invalid_regex_is_skipped_silently` in
`src/quickpack-rs/src/jujuignore.rs`.  The crash artefact is then
discardable: `cargo test --lib` is enough to catch a regression.

## What's not committed

`fuzz/target/`, `fuzz/corpus/`, and `fuzz/artifacts/` are git-ignored
per crate.  Build output is regenerated on demand, the corpus is
specific to the local libFuzzer run (and grows by megabytes), and
crash artefacts encode the now-fixed bug rather than the fix — the
regression test is the durable record.

## Adding a new target

```sh
cd src/<crate>
cargo +nightly fuzz add fuzz_<name>
# Then edit fuzz/fuzz_targets/fuzz_<name>.rs to call your function.
```

The new target needs a matching `[[bin]]` entry in
`fuzz/Cargo.toml`; `cargo fuzz add` writes that block for you.
