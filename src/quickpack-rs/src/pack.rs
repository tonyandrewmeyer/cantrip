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

/// Compile `.py` files to bytecode (legacy layout, `.pyc` next to `.py`).
fn compile_bytecode(prime_dir: &Path) -> Result<(), String> {
    let status = std::process::Command::new("python3")
        .args([
            "-m",
            "compileall",
            "-q",
            "-f",
            "-b",  // Legacy layout: .pyc next to .py.
            prime_dir.to_str().unwrap(),
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|e| format!("Failed to compile bytecode: {e}"))?;
    if !status.success() {
        // Non-fatal: bytecode compilation failure should not block packing.
        eprintln!("Warning: bytecode compilation returned non-zero exit code");
    }
    Ok(())
}

/// Create a `.charm` ZIP archive from the prime directory.
///
/// Includes `.pyc` files compiled next to their `.py` sources (legacy
/// layout) to match charmcraft's behaviour.  Excludes `__pycache__`
/// directories.
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

    // Compile bytecode next to source files (legacy layout).
    compile_bytecode(&prime_dir)?;

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

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;
    use std::io::Read;

    // ── ensure_jujuignore ──────────────────────────────────────

    #[test]
    fn ensure_jujuignore_creates_file_when_missing() {
        let dir = tempfile::tempdir().unwrap();
        ensure_jujuignore(dir.path()).unwrap();
        let content = std::fs::read_to_string(dir.path().join(".jujuignore")).unwrap();
        for entry in REQUIRED_IGNORES {
            assert!(content.contains(entry), "missing {entry} in {content}");
        }
    }

    #[test]
    fn ensure_jujuignore_appends_missing_entries() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join(".jujuignore"), "*.bak\n").unwrap();
        ensure_jujuignore(dir.path()).unwrap();
        let content = std::fs::read_to_string(dir.path().join(".jujuignore")).unwrap();
        assert!(content.contains("*.bak"));
        for entry in REQUIRED_IGNORES {
            assert!(content.contains(entry), "missing {entry}");
        }
    }

    #[test]
    fn ensure_jujuignore_is_idempotent() {
        let dir = tempfile::tempdir().unwrap();
        ensure_jujuignore(dir.path()).unwrap();
        ensure_jujuignore(dir.path()).unwrap();
        let content = std::fs::read_to_string(dir.path().join(".jujuignore")).unwrap();
        for entry in REQUIRED_IGNORES {
            let count = content.matches(entry).count();
            assert_eq!(count, 1, "{entry} appears {count} times");
        }
    }

    // ── write_dispatch ─────────────────────────────────────────

    #[test]
    fn write_dispatch_writes_executable_script() {
        let dir = tempfile::tempdir().unwrap();
        write_dispatch(dir.path(), "src/charm.py").unwrap();
        let script = std::fs::read_to_string(dir.path().join("dispatch")).unwrap();
        assert!(script.contains("src/charm.py"), "entrypoint not substituted");
        assert!(script.starts_with("#!/bin/sh"), "missing shebang");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(dir.path().join("dispatch"))
                .unwrap()
                .permissions()
                .mode();
            assert!(mode & 0o111 != 0, "dispatch not executable: {mode:o}");
        }
    }

    // ── write_yaml helper ──────────────────────────────────────

    #[test]
    fn write_yaml_round_trips_through_parser() {
        let dir = tempfile::tempdir().unwrap();
        let mut data = BTreeMap::new();
        data.insert(
            "name".to_string(),
            serde_yaml::Value::String("my-charm".into()),
        );
        let path = dir.path().join("out.yaml");
        write_yaml(&path, &data).unwrap();
        let parsed: serde_yaml::Value =
            serde_yaml::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(parsed["name"].as_str(), Some("my-charm"));
    }

    // ── build_zip ──────────────────────────────────────────────

    #[test]
    fn build_zip_packs_files_and_skips_pycache() {
        let prime = tempfile::tempdir().unwrap();
        std::fs::write(prime.path().join("dispatch"), "#!/bin/sh\n").unwrap();
        std::fs::create_dir(prime.path().join("src")).unwrap();
        std::fs::write(prime.path().join("src/charm.py"), "print('hi')\n").unwrap();
        // __pycache__ should be excluded.
        std::fs::create_dir(prime.path().join("__pycache__")).unwrap();
        std::fs::write(
            prime.path().join("__pycache__/charm.cpython-312.pyc"),
            [0u8; 4],
        )
        .unwrap();

        let zip_dir = tempfile::tempdir().unwrap();
        let zip_path = zip_dir.path().join("out.charm");
        build_zip(&zip_path, prime.path()).unwrap();

        let file = std::fs::File::open(&zip_path).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        let entries: HashSet<String> =
            (0..archive.len()).map(|i| archive.by_index(i).unwrap().name().to_string()).collect();
        assert!(entries.contains("dispatch"));
        assert!(entries.contains("src/charm.py"));
        assert!(
            !entries.iter().any(|n| n.contains("__pycache__")),
            "pycache leaked: {entries:?}",
        );

        // Confirm content round-trips.
        let mut charm_entry = archive.by_name("src/charm.py").unwrap();
        let mut buf = String::new();
        charm_entry.read_to_string(&mut buf).unwrap();
        assert_eq!(buf, "print('hi')\n");
    }

    #[test]
    fn build_zip_preserves_executable_bit_on_dispatch() {
        let prime = tempfile::tempdir().unwrap();
        let dispatch = prime.path().join("dispatch");
        std::fs::write(&dispatch, "#!/bin/sh\n").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&dispatch, std::fs::Permissions::from_mode(0o755)).unwrap();
        }

        let zip_dir = tempfile::tempdir().unwrap();
        let zip_path = zip_dir.path().join("out.charm");
        build_zip(&zip_path, prime.path()).unwrap();

        #[cfg(unix)]
        {
            let file = std::fs::File::open(&zip_path).unwrap();
            let mut archive = zip::ZipArchive::new(file).unwrap();
            let entry = archive.by_name("dispatch").unwrap();
            let mode = entry.unix_mode().expect("unix mode recorded");
            assert!(mode & 0o111 != 0, "executable bit lost: {mode:o}");
        }
    }
}
