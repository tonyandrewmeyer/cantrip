//! Generate metadata files for a charm from `charmcraft.yaml`.

use serde_yaml::Value;
use std::collections::BTreeMap;
use std::path::Path;

/// Maps `uname -m` values to Juju architecture labels.
pub fn local_arch() -> Result<String, String> {
    let machine = std::env::consts::ARCH;
    match machine {
        "x86_64" => Ok("amd64".to_string()),
        "aarch64" => Ok("arm64".to_string()),
        "arm" => Ok("armhf".to_string()),
        "powerpc64" => Ok("ppc64el".to_string()),
        "s390x" => Ok("s390x".to_string()),
        "riscv64" => Ok("riscv64".to_string()),
        _ => Err(format!("Unsupported architecture: {machine}")),
    }
}

/// Load and return the parsed `charmcraft.yaml`.
pub fn parse_charmcraft_yaml(charm_dir: &Path) -> Result<BTreeMap<String, Value>, String> {
    let path = charm_dir.join("charmcraft.yaml");
    if !path.exists() {
        return Err(format!(
            "charmcraft.yaml not found in {}",
            charm_dir.display()
        ));
    }
    let content =
        std::fs::read_to_string(&path).map_err(|e| format!("Failed to read charmcraft.yaml: {e}"))?;
    let data: Value =
        serde_yaml::from_str(&content).map_err(|e| format!("Invalid YAML: {e}"))?;
    match data {
        Value::Mapping(m) => {
            let mut result = BTreeMap::new();
            for (k, v) in m {
                if let Value::String(key) = k {
                    result.insert(key, v);
                }
            }
            // Infer name from directory if missing (matches charmcraft behaviour).
            if !result.contains_key("name") {
                if let Some(dir_name) = charm_dir.file_name().and_then(|n| n.to_str()) {
                    result.insert("name".to_string(), Value::String(dir_name.to_string()));
                }
            }
            Ok(result)
        }
        _ => Err("charmcraft.yaml must be a YAML mapping".to_string()),
    }
}

/// Determine the (distro, series) base from the project config.
pub fn resolve_base(project: &BTreeMap<String, Value>) -> (String, String) {
    // Modern `base:` field (e.g. `base: "ubuntu@24.04"`).
    if let Some(Value::String(base_str)) = project.get("base") {
        if let Some((distro, series)) = base_str.split_once('@') {
            return (distro.to_string(), series.to_string());
        }
    }

    // `platforms:` keys (e.g. `ubuntu@24.04:amd64`).
    if let Some(Value::Mapping(platforms)) = project.get("platforms") {
        for key in platforms.keys() {
            if let Value::String(key_str) = key {
                if key_str.contains('@') {
                    let label = key_str.split(':').next().unwrap_or(key_str);
                    if let Some((distro, series)) = label.split_once('@') {
                        return (distro.to_string(), series.to_string());
                    }
                }
            }
        }
    }

    // Legacy `bases:` format.
    if let Some(Value::Sequence(bases)) = project.get("bases") {
        for base_entry in bases {
            if let Value::Mapping(entry) = base_entry {
                if let Some(Value::Sequence(run_ons)) = entry.get(Value::String("run-on".into())) {
                    for run_on in run_ons {
                        if let Value::Mapping(ro) = run_on {
                            let name = ro
                                .get(Value::String("name".into()))
                                .and_then(|v| v.as_str())
                                .unwrap_or("ubuntu");
                            let channel = ro
                                .get(Value::String("channel".into()))
                                .map(|v| match v {
                                    Value::String(s) => s.clone(),
                                    _ => format!("{v:?}"),
                                })
                                .unwrap_or_else(|| "24.04".to_string());
                            return (name.to_string(), channel);
                        }
                    }
                }
            }
        }
    }

    ("ubuntu".to_string(), "24.04".to_string())
}

/// Determine the charm entrypoint from the parts config.
pub fn resolve_entrypoint(project: &BTreeMap<String, Value>) -> String {
    if let Some(Value::Mapping(parts)) = project.get("parts") {
        for part in parts.values() {
            if let Value::Mapping(part_map) = part {
                if let Some(Value::String(ep)) =
                    part_map.get(Value::String("charm-entrypoint".into()))
                {
                    return ep.clone();
                }
            }
        }
    }
    "src/charm.py".to_string()
}

/// Build the `metadata.yaml` content from a parsed `charmcraft.yaml`.
pub fn generate_metadata(project: &BTreeMap<String, Value>) -> BTreeMap<String, Value> {
    let mut metadata = BTreeMap::new();

    // Direct-copy fields.
    let direct_copy = [
        "name",
        "summary",
        "description",
        "assumes",
        "containers",
        "devices",
        "extra-bindings",
        "peers",
        "provides",
        "requires",
        "resources",
        "storage",
        "subordinate",
        "terms",
    ];
    for key in direct_copy {
        if let Some(val) = project.get(key) {
            metadata.insert(key.to_string(), val.clone());
        }
    }

    // Rename `title` -> `display-name`.
    if let Some(val) = project.get("title") {
        metadata.insert("display-name".to_string(), val.clone());
    }

    // Flatten `links` into top-level metadata fields.
    if let Some(Value::Mapping(links)) = project.get("links") {
        if let Some(v) = links.get(Value::String("documentation".into())) {
            metadata.insert("docs".to_string(), v.clone());
        }
        if let Some(v) = links.get(Value::String("contact".into())) {
            let contact = match v {
                Value::String(s) => Value::Sequence(vec![Value::String(s.clone())]),
                _ => v.clone(),
            };
            metadata.insert("maintainers".to_string(), contact);
        }
        if let Some(v) = links.get(Value::String("issues".into())) {
            metadata.insert("issues".to_string(), v.clone());
        }
        if let Some(v) = links.get(Value::String("website".into())) {
            metadata.insert("website".to_string(), v.clone());
        }
        if let Some(v) = links.get(Value::String("source".into())) {
            metadata.insert("source".to_string(), v.clone());
        }
    }

    metadata
}

/// Build the `manifest.yaml` content.
pub fn generate_manifest(
    project: &BTreeMap<String, Value>,
    arch: &str,
) -> BTreeMap<String, Value> {
    let (distro, series) = resolve_base(project);
    let now = chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true);

    let mut manifest = BTreeMap::new();
    manifest.insert(
        "charmcraft-version".to_string(),
        Value::String(format!("quickpack-{}", env!("CARGO_PKG_VERSION"))),
    );
    manifest.insert("charmcraft-started-at".to_string(), Value::String(now));

    let mut base_entry = serde_yaml::Mapping::new();
    base_entry.insert(Value::String("name".into()), Value::String(distro));
    base_entry.insert(Value::String("channel".into()), Value::String(series));
    base_entry.insert(
        Value::String("architectures".into()),
        Value::Sequence(vec![Value::String(arch.to_string())]),
    );

    manifest.insert(
        "bases".to_string(),
        Value::Sequence(vec![Value::Mapping(base_entry)]),
    );

    let mut analysis = serde_yaml::Mapping::new();
    analysis.insert(
        Value::String("attributes".into()),
        Value::Sequence(vec![]),
    );
    manifest.insert("analysis".to_string(), Value::Mapping(analysis));

    manifest
}

/// Determine the platform label for the charm filename.
fn resolve_platform_label(project: &BTreeMap<String, Value>, arch: &str) -> String {
    if let Some(Value::Mapping(platforms)) = project.get("platforms") {
        for key in platforms.keys() {
            if let Value::String(key_str) = key {
                if key_str == arch {
                    return arch.to_string();
                }
                if key_str.ends_with(&format!(":{arch}"))
                    || key_str.ends_with(&format!("-{arch}"))
                {
                    return key_str.replace(':', "-");
                }
            }
        }
        // Use the first platform key if none matched explicitly.
        if let Some(Value::String(first)) = platforms.keys().next() {
            return first.replace(':', "-");
        }
    }

    let (distro, series) = resolve_base(project);
    format!("{distro}@{series}-{arch}")
}

/// Return the standard charm filename, e.g. `myapp_amd64.charm`.
pub fn charm_filename(project: &BTreeMap<String, Value>, arch: &str) -> String {
    let name = project
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("charm");
    let label = resolve_platform_label(project, arch);
    format!("{name}_{label}.charm")
}

/// Write `actions.yaml` or `config.yaml` into prime_dir.
///
/// Prefers copying the source file from charm_dir if it exists on disk,
/// otherwise generates it from the project dict.
pub fn write_optional_yaml(
    project: &BTreeMap<String, Value>,
    field: &str,
    filename: &str,
    charm_dir: &Path,
    prime_dir: &Path,
) -> Result<(), String> {
    let source = charm_dir.join(filename);
    let dest = prime_dir.join(filename);

    if source.is_file() {
        std::fs::copy(&source, &dest)
            .map_err(|e| format!("Failed to copy {filename}: {e}"))?;
    } else if let Some(val) = project.get(field) {
        if !val.is_null() {
            let content =
                serde_yaml::to_string(val).map_err(|e| format!("Failed to serialize {field}: {e}"))?;
            std::fs::write(&dest, content)
                .map_err(|e| format!("Failed to write {filename}: {e}"))?;
        }
    }

    Ok(())
}
