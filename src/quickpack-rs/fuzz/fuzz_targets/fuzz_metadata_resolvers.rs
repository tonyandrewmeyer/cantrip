//! Fuzz target: arbitrary YAML → `resolve_base` + `resolve_entrypoint` +
//! `generate_metadata`.
//!
//! These three helpers walk an opaque `BTreeMap<String, serde_yaml::Value>`
//! and pull out specific shapes (the modern `base:` field, the legacy
//! `bases:` sequence, `parts.<part>.charm-entrypoint`, the direct-copy
//! metadata keys, etc.).  The fuzz target feeds any YAML that
//! `serde_yaml` can parse into a top-level mapping through every one of
//! them.  The invariant: regardless of the shapes inside the mapping,
//! none of the helpers panics.
#![no_main]

use libfuzzer_sys::fuzz_target;
use quickpack_rs::metadata::{generate_metadata, resolve_base, resolve_entrypoint};
use serde_yaml::Value;
use std::collections::BTreeMap;

fuzz_target!(|data: &[u8]| {
    let Ok(value) = serde_yaml::from_slice::<Value>(data) else {
        return;
    };
    let Value::Mapping(mapping) = value else {
        return;
    };
    // The resolvers expect a BTreeMap<String, Value>.  Skip any
    // non-string keys (they can't reach this surface in practice
    // because the loader rejects them earlier).
    let mut project: BTreeMap<String, Value> = BTreeMap::new();
    for (k, v) in mapping {
        if let Value::String(key) = k {
            project.insert(key, v);
        }
    }
    let _ = resolve_base(&project);
    let _ = resolve_entrypoint(&project);
    let _ = generate_metadata(&project);
});
