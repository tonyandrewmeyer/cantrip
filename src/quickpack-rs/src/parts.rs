//! Parts processing for quick pack.
//!
//! Supports `uv`, `dump`, and `nil` plugins.

use crate::jujuignore::JujuIgnore;
use serde_yaml::Value;
use std::collections::BTreeMap;
use std::path::Path;
use walkdir::WalkDir;

/// Copy a directory tree, creating parents as needed.
fn copy_tree(src: &Path, dest: &Path) -> Result<(), String> {
    if !src.is_dir() {
        return Ok(());
    }
    for entry in WalkDir::new(src).follow_links(true) {
        let entry = entry.map_err(|e| format!("Walk error: {e}"))?;
        let rel = entry
            .path()
            .strip_prefix(src)
            .map_err(|e| format!("Strip prefix error: {e}"))?;
        let target = dest.join(rel);
        if entry.file_type().is_dir() {
            std::fs::create_dir_all(&target)
                .map_err(|e| format!("mkdir error: {e}"))?;
        } else {
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent)
                    .map_err(|e| format!("mkdir error: {e}"))?;
            }
            std::fs::copy(entry.path(), &target)
                .map_err(|e| format!("copy error: {e}"))?;
        }
    }
    Ok(())
}

/// Check whether `path` is included by a craft-parts fileset.
fn match_fileset(path: &str, patterns: &[String]) -> bool {
    let inclusions: Vec<&str> = patterns
        .iter()
        .filter(|p| !p.starts_with('-'))
        .map(|s| s.as_str())
        .collect();
    let exclusions: Vec<&str> = patterns
        .iter()
        .filter(|p| p.starts_with('-'))
        .map(|s| &s[1..])
        .collect();

    for exc in &exclusions {
        if glob_match(path, exc) {
            return false;
        }
    }

    if inclusions.is_empty() {
        return true;
    }

    inclusions.iter().any(|inc| glob_match(path, inc))
}

/// Simple fnmatch-style glob matching.
fn glob_match(path: &str, pattern: &str) -> bool {
    glob::Pattern::new(pattern)
        .map(|p| p.matches(path))
        .unwrap_or(false)
}

/// Helper to extract a string from YAML mapping.
fn get_str<'a>(map: &'a serde_yaml::Mapping, key: &str) -> Option<&'a str> {
    map.get(Value::String(key.into()))
        .and_then(|v| v.as_str())
}

/// Helper to extract a string list from YAML mapping.
fn get_str_list(map: &serde_yaml::Mapping, key: &str) -> Vec<String> {
    map.get(Value::String(key.into()))
        .and_then(|v| v.as_sequence())
        .map(|seq| {
            seq.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

/// Process a UV plugin part: copy src/lib and install deps.
fn process_uv_part(
    charm_dir: &Path,
    prime_dir: &Path,
    part_config: &serde_yaml::Mapping,
) -> Result<(), String> {
    let source = get_str(part_config, "source").unwrap_or(".");
    let source_dir = charm_dir.join(source).canonicalize().map_err(|e| format!("Resolve source: {e}"))?;

    // Copy only src/ and lib/.
    let src_dir = source_dir.join("src");
    let lib_dir = source_dir.join("lib");
    if src_dir.is_dir() {
        copy_tree(&src_dir, &prime_dir.join("src"))?;
    }
    if lib_dir.is_dir() {
        copy_tree(&lib_dir, &prime_dir.join("lib"))?;
    }

    // Install Python dependencies via uv.
    let venv_dir = prime_dir.join("venv");

    let status = std::process::Command::new("uv")
        .args([
            "venv",
            "--relocatable",
            "--python",
            "python3",
            venv_dir.to_str().unwrap(),
        ])
        .current_dir(charm_dir)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|e| format!("Failed to run uv venv: {e}"))?;
    if !status.success() {
        return Err("uv venv failed".to_string());
    }

    let mut sync_cmd = vec![
        "sync".to_string(),
        "--no-dev".to_string(),
        "--no-editable".to_string(),
        "--reinstall".to_string(),
        "--no-install-project".to_string(),
    ];

    // Pass extras and groups from part config.
    let mut extras = get_str_list(part_config, "uv-extras");
    extras.sort();
    for extra in &extras {
        sync_cmd.push("--extra".to_string());
        sync_cmd.push(extra.clone());
    }
    let mut groups = get_str_list(part_config, "uv-groups");
    groups.sort();
    for group in &groups {
        sync_cmd.push("--group".to_string());
        sync_cmd.push(group.clone());
    }

    let status = std::process::Command::new("uv")
        .args(&sync_cmd)
        .current_dir(charm_dir)
        .env("UV_PROJECT_ENVIRONMENT", venv_dir.to_str().unwrap())
        .env("UV_FROZEN", "true")
        .env("UV_PYTHON_DOWNLOADS", "never")
        .env("UV_COMPILE_BYTECODE", "1")
        .env("VIRTUAL_ENV", venv_dir.to_str().unwrap())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|e| format!("Failed to run uv sync: {e}"))?;
    if !status.success() {
        return Err("uv sync failed".to_string());
    }

    // Clean up venv: remove everything in bin/ except activate.
    let venv_bin = venv_dir.join("bin");
    if venv_bin.is_dir() {
        for entry in std::fs::read_dir(&venv_bin).map_err(|e| format!("Read venv/bin: {e}"))? {
            let entry = entry.map_err(|e| format!("Read entry: {e}"))?;
            if entry.file_name() != "activate" {
                let _ = std::fs::remove_file(entry.path());
                let _ = std::fs::remove_dir_all(entry.path());
            }
        }
    }

    // Remove lib64 symlink.
    let venv_lib64 = venv_dir.join("lib64");
    if venv_lib64.is_symlink() {
        let _ = std::fs::remove_file(&venv_lib64);
    }

    Ok(())
}

/// Process a dump plugin part: copy files with organize/stage/prime rules.
fn process_dump_part(
    charm_dir: &Path,
    prime_dir: &Path,
    part_config: &serde_yaml::Mapping,
) -> Result<(), String> {
    let source = get_str(part_config, "source").unwrap_or(".");
    let source_dir = charm_dir.join(source);
    let source_dir = source_dir
        .canonicalize()
        .unwrap_or(source_dir);

    if !source_dir.is_dir() {
        return Ok(());
    }

    // Extract organize rules.
    let organize: Vec<(String, String)> = part_config
        .get(Value::String("organize".into()))
        .and_then(|v| v.as_mapping())
        .map(|m| {
            m.iter()
                .filter_map(|(k, v)| {
                    Some((k.as_str()?.to_string(), v.as_str()?.to_string()))
                })
                .collect()
        })
        .unwrap_or_default();

    let stage_patterns = get_str_list(part_config, "stage");
    let prime_patterns = get_str_list(part_config, "prime");

    // Load jujuignore for filtering.
    let ignore = JujuIgnore::from_file(&charm_dir.join(".jujuignore"));

    // Walk the source directory.
    for entry in WalkDir::new(&source_dir).follow_links(true) {
        let entry = entry.map_err(|e| format!("Walk error: {e}"))?;
        let rel = entry
            .path()
            .strip_prefix(&source_dir)
            .map_err(|e| format!("Strip prefix: {e}"))?;
        let rel_str = rel.to_string_lossy().to_string();

        if rel_str.is_empty() {
            continue;
        }

        if entry.file_type().is_dir() {
            if ignore.is_ignored(&rel_str, true) {
                // WalkDir doesn't support in-place filtering the same way,
                // so we rely on checking each file. Directories that are ignored
                // will have their files skipped below.
            }
            continue;
        }

        if ignore.is_ignored(&rel_str, false) {
            continue;
        }

        // Check if the parent directory is ignored.
        let mut parent_ignored = false;
        if let Some(parent) = rel.parent() {
            let parent_str = parent.to_string_lossy().to_string();
            if !parent_str.is_empty() && ignore.is_ignored(&parent_str, true) {
                parent_ignored = true;
            }
        }
        if parent_ignored {
            continue;
        }

        // Apply organize rules.
        let mut dest_path = rel_str.clone();
        for (src_pattern, dst_pattern) in &organize {
            if glob_match(&rel_str, src_pattern) {
                dest_path = dst_pattern.clone();
                break;
            }
        }

        // Apply stage fileset filter.
        if !stage_patterns.is_empty() && !match_fileset(&dest_path, &stage_patterns) {
            continue;
        }

        // Apply prime fileset filter.
        if !prime_patterns.is_empty() && !match_fileset(&dest_path, &prime_patterns) {
            continue;
        }

        let dst_file = prime_dir.join(&dest_path);
        if let Some(parent) = dst_file.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("mkdir error: {e}"))?;
        }
        std::fs::copy(entry.path(), &dst_file)
            .map_err(|e| format!("copy error: {e}"))?;
    }

    Ok(())
}

/// Strip comment lines from an override-build script.
fn strip_comments(script: &str) -> String {
    script
        .lines()
        .filter(|line| !line.trim_start().starts_with('#'))
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string()
}

/// Handle recognised override-build patterns.
///
/// Returns `Ok(())` for recognised safe patterns, `Err` for unrecognised ones.
fn handle_override_build(
    charm_dir: &Path,
    prime_dir: &Path,
    part_name: &str,
    override_script: &str,
) -> Result<(), String> {
    let stripped = override_script.trim();

    // Pattern 1: craftctl default + git describe --always > $CRAFT_PART_INSTALL/version
    let git_version_re = regex::Regex::new(
        r"(?m)^craftctl\s+default\s*\n\s*git\s+describe\s+--always\s*>\s*\$CRAFT_PART_INSTALL/version\s*$"
    ).unwrap();
    if git_version_re.is_match(stripped) {
        let output = std::process::Command::new("git")
            .args(["describe", "--always"])
            .current_dir(charm_dir)
            .output()
            .map_err(|e| format!("Failed to run git describe: {e}"))?;
        let version = if output.status.success() {
            String::from_utf8_lossy(&output.stdout).trim().to_string()
        } else {
            "unknown".to_string()
        };
        std::fs::write(prime_dir.join("version"), format!("{version}\n"))
            .map_err(|e| format!("Write version: {e}"))?;
        return Ok(());
    }

    // Pattern 2: rustup default stable + craftctl default
    let rustup_re = regex::Regex::new(
        r"(?m)^rustup\s+default\s+stable\s*\n\s*craftctl\s+default\s*$"
    ).unwrap();
    if rustup_re.is_match(stripped) {
        let status = std::process::Command::new("rustc")
            .arg("--version")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .map_err(|e| format!("Failed to check rustc: {e}"))?;
        if !status.success() {
            return Err(format!(
                "Part {part_name:?} requires Rust (override-build runs \
                 'rustup default stable') but rustc is not available."
            ));
        }
        return Ok(());
    }

    // Pattern 3: just craftctl default (possibly with comments).
    let no_comments = strip_comments(stripped);
    let craftctl_only_re = regex::Regex::new(
        r"(?m)^craftctl\s+default\s*$"
    ).unwrap();
    if craftctl_only_re.is_match(&no_comments) {
        return Ok(());
    }

    Err(format!(
        "Part {part_name:?} has an override-build that quick pack cannot \
         handle safely.  Override content:\n{stripped}"
    ))
}

/// Process a nil plugin part (no-op).
fn process_nil_part(
    part_name: &str,
    part_config: &serde_yaml::Mapping,
) -> Result<(), String> {
    if let Some(Value::String(override_script)) =
        part_config.get(Value::String("override-build".into()))
    {
        let no_comments = strip_comments(override_script.trim());
        let craftctl_only_re = regex::Regex::new(
            r"(?m)^craftctl\s+default\s*$"
        ).unwrap();
        if !no_comments.is_empty() && !craftctl_only_re.is_match(&no_comments) {
            return Err(format!(
                "Part {part_name:?} (nil plugin) has an override-build that \
                 quick pack cannot handle safely.  Override content:\n{}",
                override_script.trim()
            ));
        }
    }
    Ok(())
}

/// Process all parts defined in the project.
pub fn process_parts(
    charm_dir: &Path,
    prime_dir: &Path,
    project: &BTreeMap<String, Value>,
) -> Result<(), String> {
    let parts = match project.get("parts") {
        Some(Value::Mapping(m)) => m,
        _ => {
            return Err(
                "No parts found in charmcraft.yaml.  Quick pack requires at least \
                 one part with plugin: uv."
                    .to_string(),
            )
        }
    };

    if parts.is_empty() {
        return Err(
            "No parts found in charmcraft.yaml.  Quick pack requires at least \
             one part with plugin: uv."
                .to_string(),
        );
    }

    let mut found_uv = false;

    for (name, part_value) in parts {
        let part_config = match part_value.as_mapping() {
            Some(m) => m,
            None => continue,
        };

        let name_str = name.as_str().unwrap_or("unknown");

        let plugin = get_str(part_config, "plugin").unwrap_or(name_str);

        match plugin {
            "uv" => {
                if found_uv {
                    return Err("Quick pack supports only one UV plugin part.".to_string());
                }
                // Handle override-build before the main UV processing.
                if let Some(Value::String(override_script)) =
                    part_config.get(Value::String("override-build".into()))
                {
                    handle_override_build(charm_dir, prime_dir, name_str, override_script)?;
                }
                process_uv_part(charm_dir, prime_dir, part_config)?;
                found_uv = true;
            }
            "dump" => {
                process_dump_part(charm_dir, prime_dir, part_config)?;
            }
            "nil" => {
                process_nil_part(name_str, part_config)?;
            }
            _ => {
                return Err(format!(
                    "Quick pack only supports 'uv', 'dump', and 'nil' plugins, \
                     got {plugin:?} in part {name_str:?}."
                ));
            }
        }
    }

    if !found_uv {
        let part_names: Vec<&str> = parts
            .keys()
            .filter_map(|k| k.as_str())
            .collect();
        return Err(format!(
            "Quick pack requires a part with plugin: uv.  Found parts: {}",
            part_names.join(", ")
        ));
    }

    Ok(())
}
