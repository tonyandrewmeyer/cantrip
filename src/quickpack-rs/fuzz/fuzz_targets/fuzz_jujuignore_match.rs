//! Fuzz target: arbitrary patterns + path → `JujuIgnore::is_ignored`.
//!
//! Splits the input bytes into a leading set of newline-separated
//! patterns followed by a final path string.  The patterns feed
//! `JujuIgnore::new`, which compiles them into regexes; the path
//! goes through `is_ignored`.  Asserts the parser-plus-matcher chain
//! is *total*: any byte sequence either compiles to a working
//! `JujuIgnore` (and matches return a bool) or is silently rejected
//! via the existing empty-line / comment skip — never panics.
#![no_main]

use libfuzzer_sys::fuzz_target;
use quickpack_rs::jujuignore::JujuIgnore;

fuzz_target!(|data: &[u8]| {
    let Ok(text) = std::str::from_utf8(data) else {
        return;
    };
    // Split the input on the *last* newline so most of the payload
    // becomes patterns and the tail becomes the candidate path.
    let (patterns_blob, path) = match text.rsplit_once('\n') {
        Some((head, tail)) => (head, tail),
        None => (text, ""),
    };
    let patterns: Vec<String> = patterns_blob
        .split('\n')
        .map(|s| s.to_string())
        .collect();
    let ji = JujuIgnore::new(Some(&patterns));
    // Probe both file and dir paths; matchers may apply either form.
    let _ = ji.is_ignored(path, false);
    let _ = ji.is_ignored(path, true);
});
