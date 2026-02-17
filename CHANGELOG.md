# Changelog

All notable changes to Cantrip are documented here. This project is pre-1.0; only significant features and changes are recorded.

## Unreleased

### Added
- **Subagent runner** — `Subagent` executes a single `AgentTask` in an isolated LLM context with a focused system prompt and category-filtered tool subset; supports six task categories (research, build, deploy, test, debug, infra) with per-category tool allowlists and guidance; research/infra tasks route to the light model for cost savings; capped at 12 tool-call rounds with rate-limit retry
- **Task planner** — `plan_tasks` tool decomposes charm-building intent into an ordered task list; the LLM generates concrete tasks (research, design, build, deploy, test) with dependencies; supports adaptive replanning when context changes; tasks are added to the work queue for autonomous execution
- **Work queue** — `AgentTask` dataclass and `WorkQueue` for autonomous task scheduling; tasks have status lifecycle (pending/active/done/failed/blocked), category-based routing, dependency tracking, and an optional change callback; SQLite persistence via `save_tasks`/`load_tasks` on `SessionStore`

### Changed
- **Gemini 3 provider** — default model upgraded from `gemini-2.0-flash` to `gemini-3-flash-preview`; dynamic thinking enabled with thought signature round-trip for function calling; temperature forced to 1.0 for Gemini 3 models (lower values cause looping); Gemini 2 continues to work when passed explicitly via `--model`

### Added
- **Event-driven watcher** — the agent can now autonomously react to Juju events in the development model without waiting for user prompts; a status-diffing poller detects hook failures, status changes, new/removed applications, new relations, and unit scaling; a Loki poller catches application log errors when COS is available (degraded mode uses status-only when COS is absent); events are deduplicated within a 5-minute window and queued for the agent to investigate, diagnose, and act on; toggle with F5 in the TUI or `--watcher` CLI flag; the watcher only activates when a development model is set — never in production
- **Light model for internal tasks** — a cheaper "light" provider is used for context compaction (summarisation), reducing cost on premium models; auto-detected from the main model (e.g. Opus → Sonnet, Sonnet → Haiku, Pro → Flash) with `--light-model` CLI override; purpose-based routing via `_get_provider()` makes it easy to direct future internal operations to the light model
- **OCI image discovery** — `registry_search` and `registry_image_info` tools for querying Docker Hub (search images, inspect tags/architectures/sizes); system prompt includes OCI image strategy heuristics (official, recent, specific tag, right architecture); `custom-charm` and `infrastructure-charm` skills updated with image selection workflows
- **Path C: Infrastructure Charms** — `charmhub_search` and `charmhub_info` tools for querying the Charmhub API (search for existing charms, inspect relations/config/storage); `infrastructure-charm` skill with decision workflow (use existing, fork/extend, or build new), operational pattern templates (primary/replica, leader election, backup/restore, clustering, failover), and testing guidance; system prompt expanded with Path C tool usage, decision logic, and example interaction
- **Path B: Custom Applications** — `custom-charm` skill with end-to-end workflow for building ops-framework charms (K8s and machine); `analyse_framework` now detects Dockerfiles, systemd service files, and configuration patterns for custom workloads; system prompt includes substrate decision heuristics and a custom app example interaction
- **Git push confirmation** — `git_push` requires explicit user confirmation before executing; the agent shows the remote, branch, and commits then asks the user to approve
- **Test results in status bar** — unit and integration test pass/fail/skip counts appear in the TUI status bar after the agent runs tests or validates a charm
- **Integration test generation** — system prompt now instructs the agent to generate Jubilant integration tests (`tests/integration/conftest.py` and `test_charm.py`) after scaffolding a charm; integration tests run on request, not included in `charm_validate`
- **Completion validation** — `charm_validate` tool runs unit tests and charmcraft pack as a pre-completion checklist; system prompt requires calling it before declaring a charm done
- **Fast dev cycle** — `charm_sync` tool pushes local Python source directly to a running unit (skipping pack+refresh); `juju_dispatch` fires charm events to trigger the new code; system prompt guides the agent to use the fast path for source changes and the full path for dependency or metadata changes
- **TUI improvements** — F1 help screen modal with quick start, keyboard shortcuts, and links; custom status bar replacing Textual's default Footer, with reactive task/COS/test segments; header subtitle showing model info and F1 hint; F4 debug binding (stub)
- **Automatic pre-commit hooks** — `charmcraft_init` now injects a `.pre-commit-config.yaml` that delegates to the `format`, `lint`, and `unit` tox environments scaffolded by charmcraft; runs `pre-commit install` automatically when the binary is available
- **Charm test runner** — `run_charm_tests` tool executes unit or integration tests inside a charm directory, preferring tox when available and falling back to pytest; parses the pytest summary line for pass/fail/error/skipped counts; system prompt now instructs the agent to generate and run Scenario unit tests after scaffolding or modifying a charm
- **Context compaction** — agent manages context window growth using the virtual files algorithm: large tool results and messages are virtualised with inline previews; token budget is tracked and shown to the LLM; conversations are automatically compacted (summarised) when usage exceeds 80% of the context window; `virtual_file_read` and `virtual_file_search` tools let the agent access virtualised content; LLM providers now expose `context_window_tokens` and improved `count_tokens` covering tool calls and results
- **TUI, live, and Spread test suites** — Textual headless tests for widget rendering and key bindings; live Juju tests against a real controller; live LLM tests that guard against prompt regressions; Spread smoke test for system-level verification; nightly CI workflow for e2e and live tests; PR CI now runs integration tests alongside unit tests
- **Automatic ops-tracing injection** — `charmcraft_init` now injects ops-tracing into scaffolded charms: for standard profiles (`kubernetes`/`machine`) it adds the dependency, tracing relation, and setup call; for PaaS framework profiles it adds the tracing relation to `charmcraft.yaml`
- **Observability query tools** — `juju_debug_log` retrieves Juju debug log output (no COS needed), `tempo_query` searches Tempo for distributed traces, and `loki_query` queries Loki for logs; the agent now debugs charm failures using real observability data instead of guessing
- **Conversational iteration** — `juju_config` tool to get/set application configuration, `juju_wait` tool to block until an app reaches active/idle (saves tool-call rounds vs polling `juju_status`), and `juju_refresh` now accepts `resources` for 12-factor re-deploys; system prompt includes step-by-step guidance for the edit-pack-refresh cycle
- **Workload research** — agent proactively clones and analyses application source code before scaffolding, producing a `WORKLOAD.md` summary; `.source/` directory automatically gitignored
- **Eager environment preparation** — runs the full `concierge prepare` (snaps + controller bootstrap + COS) in a background worker on startup with a default k8s preset, so the environment is ready by the time the user finishes describing their charm; re-bootstraps only if the user picks a different substrate
- **Git tools** — `git_clone`, `git_init`, `git_status`, `git_diff`, `git_log`, `git_add`, `git_commit`, `git_push` for version control without a general-purpose shell; push and clone detect authentication failures and guide the user to configure credentials; commits skip GPG signing so they work without key setup
- **GitHub CLI tools** — `gh_repo_create`, `gh_pr_create`, `gh_issue_list` for repository management and collaboration via the `gh` CLI; all commands pre-check `gh auth status` and prompt the user to run `gh auth login` if not authenticated
- **Test suite expansion** — Gemini provider unit tests, system prompt rendering tests, integration tests (file tools, state persistence, skills loading), and end-to-end multi-turn scenario tests; shared `FakeProvider` in `tests/conftest.py`; `make integration` and `make e2e` targets
- **12-factor PaaS charm path** — `rockcraft_init`, `rockcraft_pack`, and `skopeo_registry_push` tools for the full build-push-deploy pipeline; `twelve-factor` skill with end-to-end workflow instructions
- **Resource-aware deploy** — `juju_deploy` now accepts `resources` (OCI images) and `trust` (cloud credentials) parameters
- **Expanded framework detection** — `analyse_framework` detects Express and Spring Boot, returns profile names and experimental flag for all six 12-factor frameworks
- **Environment setup tools** — `concierge_prepare` and `concierge_status` tools provision charm development environments via Concierge (LXD or Kubernetes)
- **Juju model management tools** — `juju_add_model` and `juju_destroy_model` for creating and tearing down Juju models
- **Cross-model relation tools** — `juju_offer` and `juju_consume` for wiring applications across models (e.g. connecting a dev model to COS-lite)
- **Skills infrastructure** — agent skills following the agentskills.io format; 11 bundled charm development skills loaded on demand via the `load_skill` tool; includes charmcraft workflows, concierge environment provisioning, jhack debugging utilities, scenario tests, jubilant integration tests, relation data design, observability, ingress, actions, and config
- **Charm CLAUDE.md generation** — agent writes a tailored `CLAUDE.md` into the charm directory on startup, giving Claude Code context about Juju charm development
- **SQLite session store** — replaced `.cantrip/session.json` with a single `.cantrip` SQLite file; tracks LLM token usage per request
- **Web fetch tool** — agent can retrieve content from URLs (documentation, Charmhub, PyPI, GitHub) with automatic HTML-to-text conversion
- **Thinking indicators** — TUI shows visual feedback while the agent is processing
- **TUI layout improvements** — better split-view arrangement for status and chat
- **K8s context** — agent understands that k8s/K8s means Kubernetes; 12-factor apps always target Kubernetes
- **Rate-limit and API error handling** — provider errors are caught and reported gracefully instead of crashing
- **Source-tree guard** — cantrip refuses to run from inside its own source tree

### Changed
- **Faster startup** — agent initialisation defers skills discovery, tool creation, session store opening, and Jinja2 template loading until first use; entry-point imports are branch-local so CLI mode skips Textual and vice versa
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
