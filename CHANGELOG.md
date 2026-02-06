# Changelog

All notable changes to Cantrip are documented here. This project is pre-1.0; only significant features and changes are recorded.

## Unreleased

### Added
- **SQLite session store** — replaced `.cantrip/session.json` with a single `.cantrip` SQLite file; tracks LLM token usage per request
- **Web fetch tool** — agent can retrieve content from URLs (documentation, Charmhub, PyPI, GitHub) with automatic HTML-to-text conversion
- **Thinking indicators** — TUI shows visual feedback while the agent is processing
- **TUI layout improvements** — better split-view arrangement for status and chat
- **K8s context** — agent understands that k8s/K8s means Kubernetes; 12-factor apps always target Kubernetes
- **Rate-limit and API error handling** — provider errors are caught and reported gracefully instead of crashing
- **Source-tree guard** — cantrip refuses to run from inside its own source tree

### Changed
- **Jinja prompt templating** — system prompt is now a Markdown Jinja template (`system.md.j2`) instead of a Python string
- **Charmcraft init** — removed defunct `simple` profile; default is now `kubernetes`
- **Juju tools** — Jubilant is now imported directly (hard dependency); tools check for the `juju` CLI instead
- **Jubilant status types** — replaced hand-rolled `juju/status.py` dataclasses with `jubilant.statustypes`; TUI and tools now use upstream types directly
- Migrated Gemini provider from deprecated `google-generativeai` to `google-genai` SDK

## 0.0.1 — Phase 0

### Added
- **Project skeleton** — uv project structure, pyproject.toml, CI, Makefile
- **LLM abstraction** — provider interface with Gemini and Claude implementations
- **Agent core** — conversation loop with tool-call execution (max 20 rounds)
- **Agent tools** — file operations (read, write, list, edit), charm operations (init, pack, fetch-libs, analyse), Juju operations (status, deploy, refresh, relate, SSH, run-action)
- **System prompt** — charm development expertise with context injection
- **TUI** — Textual app with split-view status and chat widgets
- **CLI** — asyncio REPL entry point
- **Juju status parsing** from JSON
- **Session persistence** — state saved to `.cantrip/session.json`
