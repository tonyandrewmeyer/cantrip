//! Charm context loader — reads all data rules need.

use crate::models::CharmContext;
use serde_yaml::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

fn load_yaml(path: &Path) -> BTreeMap<String, Value> {
    if !path.exists() {
        return BTreeMap::new();
    }
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return BTreeMap::new(),
    };
    let data: Value = match serde_yaml::from_str(&content) {
        Ok(d) => d,
        Err(_) => return BTreeMap::new(),
    };
    match data {
        Value::Mapping(m) => {
            let mut result = BTreeMap::new();
            for (k, v) in m {
                if let Value::String(key) = k {
                    result.insert(key, v);
                }
            }
            result
        }
        _ => BTreeMap::new(),
    }
}

fn collect_python_files(charm_dir: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for subdir in &["src", "lib"] {
        let d = charm_dir.join(subdir);
        if d.is_dir() {
            for entry in WalkDir::new(&d).follow_links(true).sort_by_file_name() {
                if let Ok(e) = entry {
                    if e.file_type().is_file()
                        && e.path().extension().map_or(false, |ext| ext == "py")
                    {
                        files.push(e.path().to_path_buf());
                    }
                }
            }
        }
    }
    files
}

fn read_python_sources(files: &[PathBuf]) -> BTreeMap<PathBuf, String> {
    let mut sources = BTreeMap::new();
    for path in files {
        if let Ok(content) = std::fs::read_to_string(path) {
            sources.insert(path.clone(), content);
        }
    }
    sources
}

fn check_tests(charm_dir: &Path) -> (bool, bool) {
    let unit_dir = charm_dir.join("tests").join("unit");
    let integration_dir = charm_dir.join("tests").join("integration");

    let has_unit = unit_dir.is_dir()
        && std::fs::read_dir(&unit_dir)
            .map(|entries| {
                entries
                    .flatten()
                    .any(|e| {
                        e.file_name()
                            .to_string_lossy()
                            .starts_with("test_")
                            && e.path().extension().map_or(false, |ext| ext == "py")
                    })
            })
            .unwrap_or(false);

    let has_integration = integration_dir.is_dir()
        && std::fs::read_dir(&integration_dir)
            .map(|entries| {
                entries
                    .flatten()
                    .any(|e| {
                        e.file_name()
                            .to_string_lossy()
                            .starts_with("test_")
                            && e.path().extension().map_or(false, |ext| ext == "py")
                    })
            })
            .unwrap_or(false);

    (has_unit, has_integration)
}

/// Extract a BTreeMap<String, Value> from a YAML value that should be a mapping.
fn value_to_map(v: &Value) -> BTreeMap<String, Value> {
    match v {
        Value::Mapping(m) => {
            let mut result = BTreeMap::new();
            for (k, val) in m {
                if let Value::String(key) = k {
                    result.insert(key.clone(), val.clone());
                }
            }
            result
        }
        _ => BTreeMap::new(),
    }
}

pub fn build_context(charm_dir: &Path) -> CharmContext {
    let charm_dir = charm_dir
        .canonicalize()
        .unwrap_or_else(|_| charm_dir.to_path_buf());

    // Load metadata.
    let mut metadata = load_yaml(&charm_dir.join("charmcraft.yaml"));
    if metadata.is_empty() {
        metadata = load_yaml(&charm_dir.join("metadata.yaml"));
    }

    // Load actions.
    let actions = if let Some(a) = metadata.get("actions") {
        let m = value_to_map(a);
        if m.is_empty() {
            value_to_map(
                &serde_yaml::to_value(load_yaml(&charm_dir.join("actions.yaml")))
                    .unwrap_or(Value::Null),
            )
        } else {
            m
        }
    } else {
        let data = load_yaml(&charm_dir.join("actions.yaml"));
        let mut result = BTreeMap::new();
        for (k, v) in data {
            result.insert(k, v);
        }
        result
    };

    // Load config options.
    let config_options = if let Some(config_section) = metadata.get("config") {
        let config_map = value_to_map(config_section);
        if let Some(opts) = config_map.get("options") {
            value_to_map(opts)
        } else if !config_map.is_empty() {
            config_map
        } else {
            let data = load_yaml(&charm_dir.join("config.yaml"));
            if let Some(opts) = data.get("options") {
                value_to_map(opts)
            } else {
                data.into_iter().map(|(k, v)| (k, v)).collect()
            }
        }
    } else {
        let data = load_yaml(&charm_dir.join("config.yaml"));
        if let Some(opts) = data.get("options") {
            value_to_map(opts)
        } else {
            data.into_iter().map(|(k, v)| (k, v)).collect()
        }
    };

    let python_files = collect_python_files(&charm_dir);
    let python_sources = read_python_sources(&python_files);

    let readme_content = std::fs::read_to_string(charm_dir.join("README.md")).unwrap_or_default();

    let (has_tests_unit, has_tests_integration) = check_tests(&charm_dir);

    CharmContext {
        charm_dir,
        metadata,
        actions,
        config_options,
        python_files,
        python_sources,
        readme_content,
        has_tests_unit,
        has_tests_integration,
    }
}
