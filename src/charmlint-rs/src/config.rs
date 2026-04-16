//! Configuration loader for charmlint.

use crate::models::Severity;
use std::collections::BTreeMap;
use std::path::Path;

/// Resolved lint configuration.
#[derive(Debug, Default)]
pub struct LintConfig {
    pub severity_overrides: BTreeMap<String, String>,
    pub select: Vec<String>,
    pub ignore: Vec<String>,
    pub min_severity: Option<Severity>,
}

impl LintConfig {
    pub fn from_yaml(data: &serde_yaml::Value) -> Self {
        let mut config = Self::default();

        if let Some(mapping) = data.as_mapping() {
            // Parse rules section.
            if let Some(serde_yaml::Value::Mapping(rules)) =
                mapping.get(serde_yaml::Value::String("rules".into()))
            {
                for (k, v) in rules {
                    if let (Some(key), Some(val)) = (k.as_str(), v.as_str()) {
                        config
                            .severity_overrides
                            .insert(key.to_string(), val.to_lowercase());
                    }
                }
            }

            // Parse select.
            if let Some(serde_yaml::Value::Sequence(seq)) =
                mapping.get(serde_yaml::Value::String("select".into()))
            {
                for item in seq {
                    if let Some(s) = item.as_str() {
                        config.select.push(s.to_string());
                    }
                }
            }

            // Parse ignore.
            if let Some(serde_yaml::Value::Sequence(seq)) =
                mapping.get(serde_yaml::Value::String("ignore".into()))
            {
                for item in seq {
                    if let Some(s) = item.as_str() {
                        config.ignore.push(s.to_string());
                    }
                }
            }

            // Parse severity.
            if let Some(serde_yaml::Value::String(sev)) =
                mapping.get(serde_yaml::Value::String("severity".into()))
            {
                config.min_severity = Severity::from_str_loose(sev);
            }
        }

        config
    }
}

/// Load configuration from a `.charmlint.yaml` file.
pub fn load_config(charm_dir: &Path, config_path: Option<&Path>) -> LintConfig {
    let path = match config_path {
        Some(p) => p.to_path_buf(),
        None => charm_dir.join(".charmlint.yaml"),
    };

    if !path.exists() {
        return LintConfig::default();
    }

    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return LintConfig::default(),
    };

    let data: serde_yaml::Value = match serde_yaml::from_str(&content) {
        Ok(d) => d,
        Err(_) => return LintConfig::default(),
    };

    LintConfig::from_yaml(&data)
}
