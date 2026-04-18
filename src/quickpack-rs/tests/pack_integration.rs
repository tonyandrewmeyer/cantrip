//! End-to-end integration tests — drive the `quickpack` binary against
//! prepared charm project directories and assert on its exit behaviour.
//!
//! Tests that require a full `uv venv + uv sync` run are left to the spread
//! suite; here we focus on argument parsing, error paths, and the helpers
//! that run before any subprocess is spawned.

use std::path::Path;
use std::process::Command;

fn quickpack_bin() -> &'static str {
    env!("CARGO_BIN_EXE_quickpack")
}

fn write(path: &Path, contents: &str) {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).unwrap();
    }
    std::fs::write(path, contents).unwrap();
}

fn run(charm_dir: &Path, extra_args: &[&str]) -> std::process::Output {
    Command::new(quickpack_bin())
        .arg(charm_dir)
        .args(extra_args)
        .output()
        .expect("run quickpack")
}

#[test]
fn missing_charmcraft_yaml_errors_cleanly() {
    let dir = tempfile::tempdir().unwrap();
    let output = run(dir.path(), &[]);
    assert!(!output.status.success(), "expected non-zero exit");
    let combined = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    assert!(
        combined.contains("charmcraft.yaml not found"),
        "unexpected output: {combined}",
    );
}

#[test]
fn parts_empty_triggers_descriptive_error() {
    let dir = tempfile::tempdir().unwrap();
    write(&dir.path().join("charmcraft.yaml"), "name: x\nparts: {}\n");
    let output = run(dir.path(), &[]);
    assert!(!output.status.success());
    let combined = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    assert!(
        combined.contains("No parts") || combined.contains("requires a part"),
        "unexpected output: {combined}",
    );
}

#[test]
fn unknown_plugin_rejected() {
    let dir = tempfile::tempdir().unwrap();
    write(
        &dir.path().join("charmcraft.yaml"),
        "name: x\nparts:\n  charm:\n    plugin: mysteriously-unknown\n",
    );
    let output = run(dir.path(), &[]);
    assert!(!output.status.success());
    let combined = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    assert!(
        combined.contains("mysteriously-unknown"),
        "unexpected output: {combined}",
    );
}

#[test]
fn missing_uv_part_reports_found_parts() {
    let dir = tempfile::tempdir().unwrap();
    write(
        &dir.path().join("charmcraft.yaml"),
        "name: x\nparts:\n  files:\n    plugin: dump\n    source: .\n",
    );
    let output = run(dir.path(), &[]);
    assert!(!output.status.success());
    let combined = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    assert!(
        combined.contains("requires a part with plugin: uv"),
        "unexpected output: {combined}",
    );
}

#[test]
fn nonexistent_path_exits_non_zero() {
    let output = Command::new(quickpack_bin())
        .arg("/definitely/does/not/exist/for-quickpack")
        .output()
        .expect("run quickpack");
    assert!(!output.status.success());
}
