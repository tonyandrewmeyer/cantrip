//! Core packing logic — builds a `.charm` file from a charm project.

use crate::metadata;
use crate::parts;
use std::collections::BTreeMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use walkdir::WalkDir;
use zip::write::SimpleFileOptions;

/// The modern dispatch template (from charmcraft's dispatch.py).
const DISPATCH_TEMPLATE: &str = r#"#!/bin/sh
dispatch_path="$(dirname $(realpath $0))"
venv_bin_path="${dispatch_path}/venv/bin"
python_path="${venv_bin_path}/python"
if [ ! -e "${python_path}" ]; then
    mkdir -p "${venv_bin_path}"
    ln -s $(which python3) "${python_path}"
fi

export PYTHONPATH="${dispatch_path}/lib:${dispatch_path}/src"
export LD_LIBRARY_PATH="${dispatch_path}/usr/lib:${dispatch_path}/lib:${dispatch_path}/usr/lib/$(uname -m)-linux-gnu"

exec "${python_path}" "${dispatch_path}/ENTRYPOINT"
"#;

/// Entries that should always be in .jujuignore.
const REQUIRED_IGNORES: &[&str] = &["*.charm", ".cantrip"];

/// Ensure `.jujuignore` contains our required entries.
fn ensure_jujuignore(charm_dir: &Path) -> Result<(), String> {
    let path = charm_dir.join(".jujuignore");
    let existing = if path.exists() {
        std::fs::read_to_string(&path).unwrap_or_default()
    } else {
        String::new()
    };

    let missing: Vec<&&str> = REQUIRED_IGNORES
        .iter()
        .filter(|entry| !existing.contains(**entry))
        .collect();

    if !missing.is_empty() {
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .map_err(|e| format!("Failed to open .jujuignore: {e}"))?;

        if !existing.is_empty() && !existing.ends_with('\n') {
            writeln!(file).map_err(|e| format!("Write error: {e}"))?;
        }
        for entry in missing {
            writeln!(file, "{entry}").map_err(|e| format!("Write error: {e}"))?;
        }
    }

    Ok(())
}

/// Write the `dispatch` script into the prime directory.
fn write_dispatch(prime_dir: &Path, entrypoint: &str) -> Result<(), String> {
    let dispatch = prime_dir.join("dispatch");
    let content = DISPATCH_TEMPLATE.replace("ENTRYPOINT", entrypoint);
    std::fs::write(&dispatch, &content).map_err(|e| format!("Write dispatch: {e}"))?;

    // Set executable bit.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&dispatch, std::fs::Permissions::from_mode(0o755))
            .map_err(|e| format!("chmod dispatch: {e}"))?;
    }

    Ok(())
}

/// Create a `.charm` ZIP archive from the prime directory.
fn build_zip(zip_path: &Path, prime_dir: &Path) -> Result<(), String> {
    let file = std::fs::File::create(zip_path)
        .map_err(|e| format!("Create zip: {e}"))?;
    let mut zip = zip::ZipWriter::new(file);

    let options = SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    for entry in WalkDir::new(prime_dir)
        .follow_links(true)
        // Skip __pycache__ directories to match charmcraft behaviour.
        .into_iter()
        .filter_entry(|e| e.file_name() != "__pycache__")
    {
        let entry = entry.map_err(|e| format!("Walk error: {e}"))?;
        if entry.file_type().is_dir() {
            continue;
        }
        let path = entry.path();
        // Skip .pyc files.
        if path.extension().is_some_and(|ext| ext == "pyc") {
            continue;
        }
        let arcname = path
            .strip_prefix(prime_dir)
            .map_err(|e| format!("Strip prefix: {e}"))?
            .to_string_lossy()
            .to_string();

        // Preserve executable bit in zip external attributes.
        #[cfg(unix)]
        let options = {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(path)
                .map(|m| m.permissions().mode())
                .unwrap_or(0o644);
            options.unix_permissions(mode)
        };

        zip.start_file(&arcname, options)
            .map_err(|e| format!("Zip start_file: {e}"))?;
        let data = std::fs::read(path).map_err(|e| format!("Read file: {e}"))?;
        zip.write_all(&data)
            .map_err(|e| format!("Zip write: {e}"))?;
    }

    zip.finish().map_err(|e| format!("Zip finish: {e}"))?;
    Ok(())
}

/// Pack a charm directory into a `.charm` file.
pub fn quick_pack(
    charm_dir: &Path,
    output_dir: Option<&Path>,
) -> Result<PathBuf, String> {
    let charm_dir = charm_dir
        .canonicalize()
        .map_err(|e| format!("Resolve charm dir: {e}"))?;
    let output_dir = match output_dir {
        Some(p) => p
            .canonicalize()
            .unwrap_or_else(|_| p.to_path_buf()),
        None => charm_dir.clone(),
    };

    let project = metadata::parse_charmcraft_yaml(&charm_dir)?;
    let entrypoint = metadata::resolve_entrypoint(&project);
    let arch = metadata::local_arch()?;

    ensure_jujuignore(&charm_dir)?;

    let tmp = tempfile::TempDir::new().map_err(|e| format!("Create tmpdir: {e}"))?;
    let prime_dir = tmp.path().join("prime");
    std::fs::create_dir_all(&prime_dir).map_err(|e| format!("mkdir prime: {e}"))?;

    // Process parts (uv deps + dump file copies).
    parts::process_parts(&charm_dir, &prime_dir, &project)?;

    // Generate dispatch script.
    write_dispatch(&prime_dir, &entrypoint)?;

    // Generate metadata.yaml.
    let meta = metadata::generate_metadata(&project);
    write_yaml(&prime_dir.join("metadata.yaml"), &meta)?;

    // Generate manifest.yaml.
    let manifest = metadata::generate_manifest(&project, &arch);
    write_yaml(&prime_dir.join("manifest.yaml"), &manifest)?;

    // Write optional actions.yaml and config.yaml.
    metadata::write_optional_yaml(&project, "actions", "actions.yaml", &charm_dir, &prime_dir)?;
    metadata::write_optional_yaml(&project, "config", "config.yaml", &charm_dir, &prime_dir)?;

    // Create the .charm zip.
    let filename = metadata::charm_filename(&project, &arch);
    std::fs::create_dir_all(&output_dir).map_err(|e| format!("mkdir output: {e}"))?;
    let charm_path = output_dir.join(&filename);
    build_zip(&charm_path, &prime_dir)?;

    Ok(charm_path)
}

/// Helper to write a BTreeMap as YAML.
fn write_yaml(path: &Path, data: &BTreeMap<String, serde_yaml::Value>) -> Result<(), String> {
    let content = serde_yaml::to_string(data).map_err(|e| format!("YAML serialize: {e}"))?;
    std::fs::write(path, content).map_err(|e| format!("Write YAML: {e}"))?;
    Ok(())
}
