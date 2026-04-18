//! Jujuignore pattern matching.
//!
//! Ported from charmcraft's jujuignore module.  Patterns follow gitignore-like
//! syntax: `*` matches within a directory, `**` matches across directories,
//! `!` inverts, and a trailing `/` restricts to directories.

use regex::Regex;
use std::path::Path;

/// Default patterns that Juju itself always applies.
const DEFAULT_IGNORES: &[&str] = &[
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    ".tox",
    "/build/",
    "/revision",
    "/venv",
    ".jujuignore",
];

/// Remove trailing whitespace that isn't escaped.
fn rstrip_unescaped(rule: &str) -> &str {
    let bytes = rule.as_bytes();
    let mut i = bytes.len();
    while i > 0 {
        let c = bytes[i - 1];
        if c == b'\n' || c == b'\r' {
            i -= 1;
        } else if c == b' ' {
            if i >= 2 && bytes[i - 2] == b'\\' {
                break;
            }
            i -= 1;
        } else {
            break;
        }
    }
    &rule[..i]
}

/// Unescape leading/trailing special characters.
fn unescape(rule: &str) -> String {
    let rule = rule.trim_start();
    let rule = rstrip_unescaped(rule);
    rule.replace(r"\!", "!")
        .replace(r"\ ", " ")
        .replace(r"\#", "#")
}

/// Convert a jujuignore rule to a regex pattern.
fn rule_to_regex(rule: &str) -> String {
    let chars: Vec<char> = rule.chars().collect();
    let n = chars.len();
    let mut i = 0;
    let mut res = String::new();

    while i < n {
        let c = chars[i];
        i += 1;
        match c {
            '*' => {
                if i < n && chars[i] == '*' {
                    i += 1;
                    res.push_str(".*");
                } else {
                    res.push_str("[^/]*");
                }
            }
            '?' => res.push_str("[^/]"),
            '[' => {
                let mut j = i;
                if j < n && chars[j] == '!' {
                    j += 1;
                }
                if j < n && chars[j] == ']' {
                    j += 1;
                }
                while j < n && chars[j] != ']' {
                    j += 1;
                }
                if j >= n {
                    res.push_str("\\[");
                } else {
                    let mut stuff: String = chars[i..j].iter().collect();
                    // Escape special regex chars inside character class.
                    stuff = regex::Regex::new(r"([&~|])")
                        .unwrap()
                        .replace_all(&stuff, r"\$1")
                        .to_string();
                    i = j + 1;
                    if stuff.starts_with('!') {
                        stuff = format!("^{}", &stuff[1..]);
                    } else if stuff.starts_with('[') {
                        stuff = format!("\\{stuff}");
                    }
                    res.push('[');
                    res.push_str(&stuff);
                    res.push(']');
                }
            }
            '/' => {
                // `/**/` can match a single `/`.
                if i < n && chars[i] == '*' {
                    let slice: String = chars[i - 1..std::cmp::min(i + 3, n)].iter().collect();
                    if slice == "/**/" {
                        i += 3;
                        res.push_str(".*/");
                    } else {
                        res.push('/');
                    }
                } else {
                    res.push('/');
                }
            }
            _ => {
                // Escape regex special characters.
                let s = c.to_string();
                res.push_str(&regex::escape(&s));
            }
        }
    }
    res.push_str(r"\z");
    res
}

/// A compiled ignore rule.
struct Matcher {
    invert: bool,
    only_dirs: bool,
    compiled: Regex,
}

impl Matcher {
    fn new(invert: bool, only_dirs: bool, regex: &str) -> Self {
        // Anchor at start to mirror Python's `re.match` semantics;
        // the `\z` in rule_to_regex already anchors the end.
        Self {
            invert,
            only_dirs,
            compiled: Regex::new(&format!("(?s)^{regex}")).unwrap(),
        }
    }

    fn matches(&self, path: &str, is_dir: bool) -> &'static str {
        if self.only_dirs && !is_dir {
            return "keep";
        }
        if self.compiled.is_match(path) {
            if self.invert {
                "forcekeep"
            } else {
                "skip"
            }
        } else {
            "keep"
        }
    }
}

/// Track a set of ignore patterns.
pub struct JujuIgnore {
    matchers: Vec<Matcher>,
}

impl JujuIgnore {
    /// Create a new JujuIgnore with default patterns.
    pub fn new(patterns: Option<&[String]>) -> Self {
        let mut ji = Self {
            matchers: Vec::new(),
        };
        let defaults: Vec<String> = DEFAULT_IGNORES.iter().map(|s| s.to_string()).collect();
        ji.extend(&defaults);
        if let Some(pats) = patterns {
            ji.extend(pats);
        }
        ji
    }

    /// Add more patterns to the ignore list.
    pub fn extend(&mut self, patterns: &[String]) {
        for rule in patterns {
            let rule = rule.trim_start().trim_end_matches(['\r', '\n']);
            if rule.is_empty() || rule.starts_with('#') {
                continue;
            }

            let mut invert = false;
            let mut rule = rule.to_string();
            if rule.starts_with('!') {
                invert = true;
                rule = rule.trim_start_matches('!').to_string();
            }
            rule = unescape(&rule);

            let mut only_dirs = false;
            if rule.ends_with('/') {
                only_dirs = true;
                rule = rule.trim_end_matches('/').to_string();
            }

            if !rule.starts_with('/') {
                rule = format!("**/{rule}");
            }

            let regex = rule_to_regex(&rule);
            self.matchers.push(Matcher::new(invert, only_dirs, &regex));
        }
    }

    /// Return true if `path` should be ignored.
    pub fn is_ignored(&self, path: &str, is_dir: bool) -> bool {
        let path = if path.starts_with('/') {
            path.to_string()
        } else {
            format!("/{path}")
        };

        let mut keep = true;
        for matcher in &self.matchers {
            let result = matcher.matches(&path, is_dir);
            match result {
                "skip" => keep = false,
                "forcekeep" => {
                    keep = true;
                    break;
                }
                _ => {}
            }
        }
        !keep
    }

    /// Load patterns from a `.jujuignore` file on top of the defaults.
    pub fn from_file(path: &Path) -> Self {
        let patterns = if path.exists() {
            std::fs::read_to_string(path)
                .unwrap_or_default()
                .lines()
                .map(|s| s.to_string())
                .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        Self::new(Some(&patterns))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ignore(patterns: &[&str]) -> JujuIgnore {
        let owned: Vec<String> = patterns.iter().map(|s| s.to_string()).collect();
        JujuIgnore::new(Some(&owned))
    }

    #[test]
    fn default_patterns_match_git_tox_build() {
        let ji = JujuIgnore::new(None);
        assert!(ji.is_ignored(".git", true));
        assert!(ji.is_ignored(".tox", true));
        assert!(ji.is_ignored("build", true));
        assert!(ji.is_ignored(".jujuignore", false));
    }

    #[test]
    fn venv_is_ignored_by_default() {
        let ji = JujuIgnore::new(None);
        assert!(ji.is_ignored("venv", true));
    }

    #[test]
    fn custom_glob_pattern_matches_extension() {
        let ji = ignore(&["*.pyc"]);
        assert!(ji.is_ignored("module.pyc", false));
        assert!(!ji.is_ignored("module.py", false));
    }

    #[test]
    fn negation_rescues_specific_filename() {
        let ji = ignore(&["*.log", "!important.log"]);
        assert!(!ji.is_ignored("important.log", false));
        assert!(ji.is_ignored("debug.log", false));
    }

    #[test]
    fn trailing_slash_restricts_match_to_directories() {
        let ji = ignore(&["cache/"]);
        assert!(ji.is_ignored("cache", true));
        assert!(!ji.is_ignored("cache", false));
    }

    #[test]
    fn doublestar_matches_across_directories() {
        let ji = ignore(&["**/__pycache__"]);
        assert!(ji.is_ignored("src/__pycache__", true));
        assert!(ji.is_ignored("deep/nested/__pycache__", true));
    }

    #[test]
    fn leading_slash_anchors_to_root() {
        let ji = ignore(&["/build/"]);
        assert!(ji.is_ignored("build", true));
        assert!(!ji.is_ignored("src/build", true));
    }

    #[test]
    fn blank_and_comment_lines_are_ignored() {
        // Only the *.tmp pattern should take effect.
        let ji = ignore(&["# comment", "", "   ", "*.tmp"]);
        assert!(ji.is_ignored("scratch.tmp", false));
        assert!(!ji.is_ignored("scratch.log", false));
    }

    #[test]
    fn from_file_reads_lines_and_skips_comments() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join(".jujuignore");
        std::fs::write(&path, "*.bak\n# comment\n\ntmp/\n").unwrap();
        let ji = JujuIgnore::from_file(&path);
        assert!(ji.is_ignored("foo.bak", false));
        assert!(ji.is_ignored("tmp", true));
    }

    #[test]
    fn from_file_handles_missing_path_via_defaults_only() {
        let tmp = tempfile::tempdir().unwrap();
        let ji = JujuIgnore::from_file(&tmp.path().join(".jujuignore"));
        assert!(ji.is_ignored(".git", true));
        assert!(!ji.is_ignored("src", true));
    }

    #[test]
    fn rule_to_regex_converts_single_star() {
        let r = rule_to_regex("*.py");
        assert!(r.contains("[^/]*"));
        assert!(r.ends_with(r"\z"));
    }

    #[test]
    fn rule_to_regex_converts_doublestar() {
        let r = rule_to_regex("**/foo");
        assert!(r.contains(".*"));
    }

    #[test]
    fn unescape_strips_leading_whitespace_and_escapes() {
        assert_eq!(unescape("  hello"), "hello");
        assert_eq!(unescape(r"\!bang"), "!bang");
        assert_eq!(unescape(r"with\ space"), "with space");
    }
}
