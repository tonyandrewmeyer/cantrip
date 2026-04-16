//! Core data models for charmlint.

use serde::Serialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Diagnostic severity level.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Error,
    Warning,
    Info,
}

impl Severity {
    pub fn from_str_loose(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "error" => Some(Self::Error),
            "warning" => Some(Self::Warning),
            "info" => Some(Self::Info),
            _ => None,
        }
    }

    pub fn label(&self) -> &'static str {
        match self {
            Self::Error => "error",
            Self::Warning => "warning",
            Self::Info => "info",
        }
    }

    /// Numeric order: Error=0, Warning=1, Info=2.
    pub fn order(&self) -> u8 {
        match self {
            Self::Error => 0,
            Self::Warning => 1,
            Self::Info => 2,
        }
    }
}

/// A single lint finding.
#[derive(Debug, Clone, Serialize)]
pub struct Diagnostic {
    pub rule_id: String,
    pub severity: Severity,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fix_hint: Option<String>,
}

impl Diagnostic {
    pub fn format_text(&self, charm_dir: Option<&Path>) -> String {
        let mut location = self.path.clone().unwrap_or_default();
        if let (Some(dir), Some(p)) = (charm_dir, &self.path) {
            if let Ok(rel) = Path::new(p).strip_prefix(dir) {
                location = rel.to_string_lossy().to_string();
            }
        }
        if let Some(line) = self.line {
            location = format!("{location}:{line}");
        }
        let prefix = if location.is_empty() {
            String::new()
        } else {
            format!("{location}: ")
        };
        format!("{prefix}{} {}", self.rule_id, self.message)
    }
}

/// All the data a rule needs, loaded once by the linter engine.
pub struct CharmContext {
    pub charm_dir: PathBuf,
    pub metadata: BTreeMap<String, serde_yaml::Value>,
    pub actions: BTreeMap<String, serde_yaml::Value>,
    pub config_options: BTreeMap<String, serde_yaml::Value>,
    pub python_files: Vec<PathBuf>,
    pub python_sources: BTreeMap<PathBuf, String>,
    pub readme_content: String,
    pub has_tests_unit: bool,
    pub has_tests_integration: bool,
}

/// Aggregated lint results.
#[derive(Debug, Serialize)]
pub struct LintReport {
    pub charm_dir: String,
    pub total: usize,
    pub errors: usize,
    pub warnings: usize,
    pub info: usize,
    pub diagnostics: Vec<Diagnostic>,
}

impl LintReport {
    pub fn new(charm_dir: &Path, diagnostics: Vec<Diagnostic>) -> Self {
        let errors = diagnostics
            .iter()
            .filter(|d| d.severity == Severity::Error)
            .count();
        let warnings = diagnostics
            .iter()
            .filter(|d| d.severity == Severity::Warning)
            .count();
        let info = diagnostics
            .iter()
            .filter(|d| d.severity == Severity::Info)
            .count();
        let total = diagnostics.len();
        Self {
            charm_dir: charm_dir.to_string_lossy().to_string(),
            total,
            errors,
            warnings,
            info,
            diagnostics,
        }
    }

    pub fn summary_line(&self) -> String {
        if self.total == 0 {
            return "No issues found.".to_string();
        }
        let mut parts = Vec::new();
        if self.errors > 0 {
            let s = if self.errors == 1 { "" } else { "s" };
            parts.push(format!("{} error{s}", self.errors));
        }
        if self.warnings > 0 {
            let s = if self.warnings == 1 { "" } else { "s" };
            parts.push(format!("{} warning{s}", self.warnings));
        }
        if self.info > 0 {
            parts.push(format!("{} info", self.info));
        }
        let s = if self.total == 1 { "" } else { "s" };
        format!("Found {} issue{s} ({})", self.total, parts.join(", "))
    }
}
