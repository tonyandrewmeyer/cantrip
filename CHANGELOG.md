# Changelog

All notable changes to Cantrip are documented here. This project is pre-1.0; only significant features and changes are recorded.

## Unreleased

### Added
- **Workload research** — agent proactively clones and analyses application source code before scaffolding, producing a `WORKLOAD.md` summary; `.source/` directory automatically gitignored
- **Eager environment preparation** — runs the full `concierge prepare` (snaps + controller bootstrap + COS) in a background worker on startup with a default k8s preset, so the environment is ready by the time the user finishes describing their charm; re-bootstraps only if the user picks a different substrate
- **Git tools** — `git_clone`, `git_init`, `git_status`, `git_diff`, `git_log`, `git_add`, `git_commit` for version control without a general-purpose shell
- **GitHub CLI tools** — `gh_repo_create`, `gh_pr_create`, `gh_issue_list` for repository management and collaboration via the `gh` CLI
- **Test suite expansion** — Gemini provider unit tests, system prompt rendering tests, integration tests (file tools, state persistence, skills loading), and end-to-end multi-turn scenario tests; shared `FakeProvider` in `tests/conftest.py`; `make integration` and `make e2e` targets
- **12-factor PaaS charm path** — `rockcraft_init`, `rockcraft_pack`, and `skopeo_registry_push` tools for the full build-push-deploy pipeline; `twelve-factor` skill with end-to-end workflow instructions
- **Resource-aware deploy** — `juju_deploy` now accepts `resources` (OCI images) and `trust` (cloud credentials) parameters
- **Expanded framework detection** — `analyse_framework` detects Express and Spring Boot, returns profile names and experimental flag for all six 12-factor frameworks
- **Environment setup tools** — `concierge_prepare` and `concierge_status` tools provision charm development environments via Concierge (LXD or Kubernetes)
- **Juju model management tools** — `juju_add_model` and `juju_destroy_model` for creating and tearing down Juju models
- **Cross-model relation tools** — `juju_offer` and `juju_consume` for wiring applications across models (e.g. connecting a dev model to COS-lite)
- **Skills infrastructure** — agent skills following the agentskills.io format; 7 bundled charm development skills (scenario-tests, jubilant-tests, relation-data-design, observability, ingress, adding-actions, adding-config) loaded on demand via the `load_skill` tool
- **Charm CLAUDE.md generation** — agent writes a tailored `CLAUDE.md` into the charm directory on startup, giving Claude Code context about Juju charm development
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
