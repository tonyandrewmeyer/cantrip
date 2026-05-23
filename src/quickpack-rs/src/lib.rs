//! quickpack library entry point.
//!
//! The binary at `src/main.rs` remains the user-facing CLI; this
//! `lib.rs` exists only so the public modules can be reached from
//! external test and fuzz crates (notably `fuzz/`).  Each module
//! also keeps its `mod` declaration in `main.rs`, so the binary
//! continues to build independently of the library.
pub mod jujuignore;
pub mod metadata;
pub mod pack;
pub mod parts;
