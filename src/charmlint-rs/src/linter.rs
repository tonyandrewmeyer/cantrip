//! Core linter engine — loads context, runs rules, applies filters.

use crate::config::LintConfig;
use crate::context;
use crate::models::{Diagnostic, LintReport, Severity};
use crate::rules;
use std::path::Path;

/// Extract category from rule ID (strip trailing digits).
fn rule_category(rule_id: &str) -> String {
    rule_id.trim_end_matches(|c: char| c.is_ascii_digit()).to_string()
}

/// Check whether a rule should run given the config.
fn should_run_rule(rule_id: &str, config: &LintConfig) -> bool {
    let category = rule_category(rule_id);

    // Explicit disable via severity override.
    if config.severity_overrides.get(rule_id).map(|s| s.as_str()) == Some("off") {
        return false;
    }
    if config
        .severity_overrides
        .get(&category)
        .map(|s| s.as_str())
        == Some("off")
    {
        return false;
    }

    // If select is set, only run rules in those categories.
    if !config.select.is_empty() && !config.select.contains(&category) {
        return false;
    }

    // If ignore contains this specific rule or category, skip it.
    !config.ignore.contains(&rule_id.to_string()) && !config.ignore.contains(&category)
}

/// Resolve the effective severity for a rule, applying config overrides.
fn effective_severity(rule_id: &str, config: &LintConfig) -> Option<Severity> {
    if let Some(override_val) = config.severity_overrides.get(rule_id) {
        if override_val != "off" {
            return Severity::from_str_loose(override_val);
        }
    }
    None
}

/// Run all enabled rules against a charm directory.
pub fn lint(charm_dir: &Path, config: &LintConfig) -> LintReport {
    let ctx = context::build_context(charm_dir);

    if ctx.metadata.is_empty() {
        return LintReport::new(
            charm_dir,
            vec![Diagnostic {
                rule_id: "FATAL".to_string(),
                severity: Severity::Error,
                message:
                    "No charmcraft.yaml or metadata.yaml found — is this a charm directory?"
                        .to_string(),
                path: None,
                line: None,
                fix_hint: None,
            }],
        );
    }

    let all_diagnostics = rules::run_all(&ctx);

    // Filter and transform diagnostics.
    let mut filtered = Vec::new();
    for d in all_diagnostics {
        if !should_run_rule(&d.rule_id, config) {
            continue;
        }

        // Apply severity overrides.
        let d = if let Some(sev) = effective_severity(&d.rule_id, config) {
            Diagnostic {
                severity: sev,
                ..d
            }
        } else {
            d
        };

        // Filter by minimum severity.
        if let Some(min_sev) = &config.min_severity {
            if d.severity.order() > min_sev.order() {
                continue;
            }
        }

        filtered.push(d);
    }

    LintReport::new(charm_dir, filtered)
}
