# Changelog

All notable changes to Cantrip are documented here. This project is pre-1.0; only significant features and changes are recorded.

## Unreleased

### Changed
- **Parallel unit tests with pytest-xdist + pytest-cov** — ``make unit``
  and ``make coverage`` now fan out across CPU cores via
  ``pytest -n auto``; pytest-cov handles per-worker coverage combining
  automatically.  The 2970-test suite drops from ~60 s serial to
  ~25 s with coverage (~3.5–4× on the dev machine).  ``[tool.coverage.run]``
  gains ``parallel = true`` and ``concurrency = ["multiprocessing"]``
  so each xdist worker writes its own ``.coverage.<host>.<pid>`` which
  pytest-cov combines at session end.  Two new dev dependencies —
  ``pytest-xdist`` and ``pytest-cov``.  CI (``ci.yaml``) switched to
  ``pytest -n auto --cov``; nightly and live jobs unchanged.  The suite
  is already hermetic so no tests broke under parallel execution.

### Added
- **MCP client foundation (Phase 45.1–45.3)** — Cantrip can now consume
  third-party Model Context Protocol servers.  ``cantrip.mcp`` wraps the
  official ``mcp`` 1.27.0 SDK with a long-lived ``MCPClient`` (stdio +
  streamable HTTP transports, dedicated background-task lifecycle to
  satisfy the SDK's anyio same-task rule, bounded reconnect on transient
  failure).  ``MCPRegistry`` owns the configured set, parallelises
  ``start_all()`` so a misconfigured server never blocks healthy ones,
  and surfaces a status snapshot.  YAML loader reads
  ``cantrip.mcp.yaml`` (repo) and ``~/.config/cantrip/mcp.yaml`` (user,
  override via ``CANTRIP_MCP_USER_CONFIG``) with repo winning on a
  server-name conflict.  ``MCPTool`` wraps each remote tool as a
  Cantrip ``Tool`` with the ``mcp__<server>__<tool>`` naming convention
  so the LLM sees them alongside the built-ins; subagent ``_filter_tools``
  passes ``mcp__*`` through every category gate (the per-server
  ``allowed_tools`` config is the authoritative MCP gate).  TUI and Web
  both auto-start MCP at boot and dispatch ``/mcp`` (overview),
  ``/mcp tools <server>``, and ``/mcp help`` through a shared
  ``cantrip.agent.mcp_commands`` module.  Adds ``mcp`` 1.27.0 + 14
  transitive dependencies.  64 new unit tests against an in-tree stub
  MCP server cover the client (lifecycle, allowlist, reconnect),
  config loader (every shape, merge precedence), registry (partial
  failure, status transitions), tool wrapper (descriptor fidelity,
  execution failure modes, build_tools integration), and the subagent
  passthrough.  OAuth/elicitation (45.4) and marketplace awareness
  (45.5) tracked as deferred follow-ups.
- **Memory export/import with sanitisation (Phase 43.4)** — closes Phase
  43.  ``export_to_skill`` bundles memories as a discoverable SKILL.md
  (frontmatter + ``## Memory: <title>`` sections); ``export_to_markdown``
  produces a directory of one ``.md`` per memory.  ``import_from_path``
  reads either format and merges into a target scope, skipping duplicates
  unless ``overwrite=True``.  Both directions sanitise: charm paths are
  replaced with ``<CHARM_PATH>`` (resolved + raw forms substituted), and
  five conservative secret patterns are scrubbed (GitHub tokens, AWS
  access keys, Bearer tokens, ``password=…`` assignments, Slack tokens).
  ``ExportResult.redactions`` surfaces the count so the slash-command
  response notes "(N secret redactions)" before the user shares.  Three
  new ``/memory`` subcommands wire it into TUI and Web:
  ``/memory export <name> <path> [scope]``,
  ``/memory export-md <dir> [scope]``,
  ``/memory import <path> [target_scope]``.  30 unit tests cover each
  pattern, both export formats, round-trip imports, duplicate handling,
  and the slash-command dispatchers.
- **Memory slash commands (Phase 43.3)** — three user-facing memory
  commands shared by TUI and Web: ``/memory [scope]`` lists,
  ``/remember <kind> [scope] -- <title> -- <body>`` writes (the ` -- `
  separator allows any punctuation in titles and bodies),
  ``/forget <title> [scope]`` deletes (with shlex-quoted multi-word
  titles, and refusing ambiguous deletes when the same title exists in
  both scopes).  All three run inline (no LLM round) for instant
  feedback.  Logic lives in ``cantrip.agent.memory_commands`` so both
  surfaces share parsing and formatting.  22 unit tests.
- **Memory auto-writer with citations, revalidation, TTL, and inline notices
  (Phase 43.2)** — Cantrip now opportunistically captures durable lessons
  from the conversation.  A user message that matches a conservative
  correction regex (sentence-initial "no/actually/wait/stop", "don't
  <verb>", "that's wrong", "instead", "always/never <verb>") schedules a
  background ``AutoWriter`` LLM call after the response.  The writer's
  prompt enforces a "would this save ≥5 minutes next time?" gate, so
  most events correctly skip; clean proposals persist via
  ``MemoryManager.write`` with SHA-256 citations harvested from recent
  ``read_file``/``write_file``/``edit_file``/``multi_edit`` tool calls.
  ``MemoryManager.revalidate`` re-reads each citation and quarantines
  entries on drift; ``revalidate_all`` and ``memory_revalidate`` drive
  bulk sweeps.  ``sweep_stale`` archives memories untouched for 60 days
  (``CANTRIP_MEMORY_SOFT_EXPIRY_DAYS``); ``list_due_for_purge`` surfaces
  candidates archived for 180 days (``CANTRIP_MEMORY_HARD_EXPIRY_DAYS``);
  ``memory_sweep`` and ``memory_purge_check`` agent tools wrap both.
  New ``MEMORY_WRITTEN`` / ``MEMORY_RECALLED`` event types emit on every
  write or recall via callbacks on ``MemoryManager``, with TUI chat
  rendering inline system messages and the Web frontend handling them
  through the existing dispatch.  ~120 unit tests added (revalidation,
  sweep, auto-writer JSON parsing, citation collection, correction
  regex, callback isolation, end-to-end trigger fire).  The
  tool-failure-retry and task-complete triggers, plus full CONFIRM-task
  auto-creation at 180 days, are tracked as deferred follow-ups.
- **Memory primitives and storage (Phase 43.1)** — Cantrip gains a
  learned-lesson layer with two complementary scopes.  Charm-scope memories
  live in a new `memory` table (schema v8) inside ``.cantrip``; global-scope
  memories live under ``~/.config/cantrip/memory/`` (overridable via
  ``CANTRIP_MEMORY_DIR``) as Markdown files with YAML frontmatter, fronted
  by an always-loaded ``MEMORY.md`` index rebuilt on every write.  Six
  agent tools — ``memory_list``, ``memory_read``, ``memory_search``,
  ``memory_write``, ``memory_update``, ``memory_forget`` — route through a
  unified ``MemoryManager`` that lets tools treat both scopes identically
  and picks charm-scope over global-scope when titles collide.  The system
  prompt gains a Memory Index section after Available Skills, carrying the
  global MEMORY.md contents and charm-scope titles only (bodies are loaded
  on demand).  40 unit tests cover the v7→v8 migration, SQLite and
  filesystem round-trips, all six tool paths, and the prompt-injection
  sanitisation.  Auto-writer, UI controls, and export/import follow in
  Phases 43.2–43.4.
- **Worktree configuration and limits (Phase 44.5)** — three defensive
  knobs on ``_DefaultWorktreeAllocator``.  ``CANTRIP_MAX_WORKTREES``
  caps concurrent worktrees (``0`` disables allocation entirely as an
  escape hatch).  ``min_free_bytes`` (default 200 MB) refuses allocation
  when ``shutil.disk_usage`` reports less free space than the threshold.
  ``reap_disk_orphans(base_path, active_task_ids)`` enumerates
  ``git worktree list`` under ``.cantrip-worktrees/`` and removes any
  worktree whose task id isn't in the live queue — user-created
  worktrees elsewhere are left alone.  The executor calls this at the
  top of ``_run_loop`` on startup, excluding terminal-state tasks from
  the active set so their worktrees are also reaped.  10 new unit tests
  cover the cap, env var parsing, disk-space guard, and orphan reaper.
- **Worktree visibility in TUI and Web (Phase 44.3/44.4)** — each task now
  surfaces its active worktree path in the UI while the subagent is
  running and clears it on release.  ``AgentTask`` grew a transient
  ``worktree_path`` field (not persisted — worktrees don't survive
  sessions); the executor sets it on allocate, clears it on release, and
  re-fires the queue's change callback via a new ``WorkQueue.notify_task``
  helper so both UIs stay in sync.  ``task_updated`` events carry a new
  ``worktree_path`` field, the TUI task detail panel renders a
  ``Worktree:`` line, and the web UI appends a small monospace
  ``worktree: <path>`` beneath the task title (server-rendered on first
  load and live-updated via the WebSocket).  Revert-on-failure (Phase
  11.4) now runs only in the non-git fallback path — worktree'd failures
  are cleaned up by dropping the worktree, which discards every
  partial write at once.  Phase 11.1 commit-after-build still applies
  per-worktree; the merge pass auto-commits anything a subagent forgot
  to commit.  6 new unit tests cover the executor bookkeeping, the TUI
  detail panel, the ``task_updated`` payload, and the ``/api/state`` JSON
  shape.
- **Worktree-isolated subagents (Phase 44.2)** — the ``BackgroundExecutor``
  now allocates a per-task git worktree at subagent spawn time, passes the
  worktree path as the subagent's ``charm_path``, and ``git merge --no-ff``
  merges the ephemeral branch back into the main charm branch on success.
  ``--no-ff`` preserves the subagent's commits on the main graph;
  uncommitted worktree files are auto-committed before merging so bare file
  writes still propagate.  Merges are serialised behind an
  ``asyncio.Lock`` so concurrent subagents cannot race on the main tree.
  Conflicts trigger ``git merge --abort``, mark the task ``BLOCKED``, and
  preserve the branch (``keep_branch=True``) for manual resolution; an
  uncommitted main tree similarly skips the merge and retains the branch so
  the user's in-progress work is never stomped.  Failures and timeouts drop
  the worktree without touching main — the pre-existing snapshot/revert
  path still handles BUILD/DEBUG failures when the allocator falls back to
  the main tree (non-git charms).  The allocator additionally writes
  ``/.cantrip-worktrees/`` to ``.git/info/exclude`` so the nested worktree
  doesn't appear as untracked work in the main repo's ``git status``.
- **Worktree allocator primitive (Phase 44.1)** — new
  ``src/cantrip/agent/worktree.py`` introduces ``WorktreeAllocator`` (a
  ``Protocol`` in ``services.py``) and ``_DefaultWorktreeAllocator``, which
  wraps ``git worktree add`` under ``.cantrip-worktrees/<task-id>/`` on an
  ephemeral ``cantrip/wt/<task-id>`` branch taken from the current HEAD.
  Non-git charm paths and repos without a HEAD commit fall back to ``None``
  so the allocator is always safe to call.  ``allocate`` / ``release`` /
  ``get`` / ``all_worktrees`` / ``reap_orphans`` cover the full lifecycle;
  ``release`` prunes leftover git metadata when the worktree directory was
  removed out-of-band.  19 unit tests drive the lifecycle against a real
  git repo (``pytest`` ``tmp_path``) and skip cleanly if ``git`` is absent.
  Phase 44.2 layers the executor wiring on top of this primitive.
- **Web-server WebSocket lifecycle coverage (Phase 57.4)** —
  ``src/cantrip/web/server.py`` moved from 24% to 99% line coverage
  via 44 new tests in ``tests/unit/test_web_server.py``.  Covers the
  full ``_websocket_handler`` lifecycle (connect, disconnect,
  ``chat_input`` round-trip with broadcast fan-out, invalid JSON,
  empty-content guard, and every exception branch —
  ``ProviderRateLimitError``, ``ProviderOverloadedError``,
  ``ProviderError``, and the generic ``OSError``/``ValueError``/
  ``RuntimeError`` path), the ``/api/logs-stream`` tailer
  (no-model / no-CLI, happy-path streaming, invalid-level
  normalisation, mid-stream OSError), every branch of the REST
  handlers, and ``_create_app`` / ``run_web`` dispatch.  Uses
  ``aiohttp.test_utils.TestClient`` with ``ws_connect``, per the
  roadmap's suggested pattern.  Small production change: migrated
  ``chat_lock`` / ``jinja_env`` / ``port`` from string keys to typed
  ``web.AppKey`` instances (``CHAT_LOCK_KEY``, ``JINJA_ENV_KEY``,
  ``PORT_KEY``), silencing ``NotAppKeyWarning`` and matching the
  existing ``AGENT_KEY`` / ``WS_CLIENTS_KEY`` style.
- **Entry-point coverage (Phase 57.2)** — three modules that were at
  0% are now thoroughly tested: ``cantrip/cli.py`` (0% → 97%),
  ``cantrip/main.py`` (0% → 99%), and ``cantrip/juju/log_stream.py``
  (0% → 100%).  85 new tests across
  ``tests/unit/test_{cli,main,log_stream}.py``.  The CLI-mode REPL is
  driven by a canned ``asyncio.to_thread(input, ...)`` side-effect
  queue so every command (``/help`` / ``/tasks`` / ``/status`` /
  ``/cost`` / ``exit``) and error branch (``ProviderRateLimitError``,
  ``ProviderOverloadedError``, ``ProviderError``, ``ValueError``,
  ``KeyboardInterrupt``) is exercised without launching an agent.
  ``main.py`` tests cover every ``parse_args`` path (including the
  "bare path" / "bare flag" shortcuts), every dispatch branch in
  ``_run``, and every transcript format in ``_export_transcript``
  (including paginated HTML).  ``log_stream`` tests use AsyncMock
  processes to cover EOF, ``max_lines``, timeout, ``ProcessLookupError``
  cleanup, and invalid-UTF-8 replacement.  Full suite:
  ``2970 passed, 5 skipped`` in 58 s.
- **Tool ``execute()`` coverage (Phase 57.3)** — four subprocess-wrapping
  tools moved from the 20–28% range to ≥97%: ``scaling.py`` (20% →
  100%), ``upgrade.py`` (21% → 99%), ``charmlint_tool.py`` (24% →
  99%), ``chaos.py`` (28% → 97%).  65 new tests across the four
  ``tests/unit/test_{scaling,upgrade,charmlint,chaos}_tool.py`` files,
  each following the established pattern from ``test_git_tools.py``:
  stub ``juju_subprocess.run_juju`` / ``wait_for_app`` (or
  ``subprocess.run`` for charmlint) to cover the happy path, the
  non-zero-exit branch, stderr-only output, timeouts (via
  ``subprocess.TimeoutExpired``), and each disruption / fallback
  switch (IAAS-vs-CAAS scale fallback, Rust-vs-Python charmlint
  backend).  No production-code change; ``2885 passed, 5 skipped``.

### Changed
- **Zero pytest warnings (Phase 57.1)** — ``make check`` now runs
  cleanly.  Three fixes: (1) ``_make_fake_process`` helpers in
  ``tests/unit/test_observability_tools.py`` and ``tests/unit/test_tools.py``
  now override ``proc.kill`` with a ``MagicMock()`` so the sync method
  doesn't inherit AsyncMock's async-by-default behaviour and leak an
  unawaited coroutine down the timeout path.  A new ``_raise_timeout``
  side-effect helper closes ``proc.communicate()``'s pending coroutine
  before raising, plugging the second leak that
  ``mock.patch("asyncio.wait_for", side_effect=TimeoutError)`` caused.
  (2) ``src/cantrip/web/server.py`` now exports typed ``AGENT_KEY`` and
  ``WS_CLIENTS_KEY`` (``web.AppKey[T]``) and the call sites and tests
  use them, eliminating ``NotAppKeyWarning``.  (3) The broad
  ``ignore::RuntimeWarning:unittest.mock`` entry in ``pyproject.toml``
  is replaced with a narrow ``ignore:unclosed event loop:ResourceWarning``
  that targets only pytest-asyncio 1.3.0's auto-mode event-loop leak
  (third-party, not our code).  ``2820 passed, 5 skipped in 55s`` with
  zero warnings.

### Added
- **Web UI accessibility — WCAG 2.1 AA remediation (Phase 60)** — the
  web UI now satisfies every high- and medium-severity finding from the
  audit in ``design/WEB_UI_ACCESSIBILITY_AUDIT.md``.  The Send button
  sits on the darker ``--accent-strong`` so its label clears 4.5:1
  contrast; a global ``:focus-visible`` outline plus an explicit white
  ring on the Send button give keyboard users visible focus at all
  times; the chat input carries a visually-hidden ``<label>`` and the
  chat message list is a ``role="log"`` live region so assistant replies
  are announced; the thinking indicator toggles via ``hidden`` (not
  ``display:none``) inside a ``role="status"`` wrapper so the state
  change reaches assistive tech; the three overlays are real
  ``role="dialog" aria-modal="true"`` containers that capture
  ``document.activeElement`` on open, focus the heading, mark
  ``<header>``/``<main>``/``<footer>`` ``inert``, trap Tab/Shift-Tab,
  and restore focus on close; the three header buttons gained
  ``type="button"``, ``aria-label``, and ``aria-expanded`` /
  ``aria-controls`` that flip with the overlay state; the connection
  status dot now carries ``role="status"`` plus an ``aria-label`` that
  tracks state; global keyboard shortcuts are gated behind ``Alt`` (and
  escape routes through the dialog helpers so focus is restored
  correctly); the keyboard-shortcuts table is a ``<dl>``; the three
  ``<section>``s carry accessible names; twenty new ``TestAccessibility``
  cases lock every invariant into the unit suite.  Deferred: the
  low-priority AAA muted-text contrast bump (finding 13) and the CI
  regression guard (60.9).
- **Rust crate unit tests (Phase 58)** — the ``charmlint-rs`` and
  ``quickpack-rs`` crates now have ``#[cfg(test)] mod tests`` blocks on
  every module (73 unit tests for charmlint-rs, 60 for quickpack-rs)
  plus integration tests driving each compiled binary against fixture
  charm directories (8 tests for charmlint, 5 for quickpack).  ``make
  rust-test`` runs both crates' ``cargo test`` locally; CI runs the
  same via a matrixed ``rust-test`` job.  Surfaced and fixed a latent
  bug in ``quickpack-rs/src/jujuignore.rs`` where ``Matcher`` used
  Rust regex's unanchored ``is_match`` instead of Python's anchored
  ``re.match``, causing leading-slash patterns like ``/build/`` to
  incorrectly ignore ``src/build`` as well.

### Changed
- **Planner prompts extracted to Jinja2 templates (Phase 53.1)** — the
  three triple-quoted planner prompt constants that lived in
  ``cantrip.agent.planner`` (``_PLANNING_PROMPT``,
  ``_DESIGN_TO_BUILD_PROMPT``, ``_DAY2_TO_BUILD_PROMPT``, ~380 lines
  total) now live as ``.md.j2`` files under
  ``src/cantrip/agent/prompts/planning/``, alongside the existing
  ``system.md.j2``.  A new snapshot test freezes the rendered output
  against a canonical context so accidental template edits surface in
  CI.  No behaviour change — byte-identical output for all four
  builders (full, design→build, day2→build, replanning).
- **Task descriptions extracted to templates (Phase 53.2)** — every
  multi-line ``AgentTask.description`` f-string in the deterministic
  planner generators (``plan_sprint_deploy``, ``plan_fast_path``,
  ``plan_one_shot_build``, ``plan_improvement_phase``,
  ``plan_improvement_fixes``, ``plan_operability_assessment``,
  ``plan_operability_fixes``, ``plan_research_phase``,
  ``plan_day2_ops_phase``) now renders through ``.md.j2`` templates
  under ``src/cantrip/agent/prompts/tasks/`` — 30 templates covering
  every piece of charm-building guidance that used to live in
  ``planner.py``.  ``planner.py`` drops from 1620 to 1195 lines, 425
  lines lighter, focused on control flow.  Byte-identical output
  verified for every description; the 2774-test unit suite is
  unchanged.
- **``planner.py`` split into a package (Phase 53.3)** — the now-
  1195-line ``cantrip.agent.planner`` module is now a package with
  the natural deterministic / LLM seam surfaced as modules:
  ``planner/context.py`` (the shared ``PlanningContext`` dataclass),
  ``planner/deterministic.py`` (the nine ``plan_*`` generators plus
  path classifiers and task-prefix constants), and
  ``planner/llm.py`` (``TaskPlanner``, the three prompt builders,
  the JSON parser, ``_merge_tasks``).  ``planner/__init__.py``
  re-exports the existing public API so no caller needs to change.
- **Compaction prompt extracted to markdown** — the conversation-
  summarisation prompt used by ``ContextManager.compact_history()``
  was the last hardcoded LLM prompt in the ``cantrip.agent`` tree.
  It now lives in ``src/cantrip/agent/prompts/compaction.md``,
  loaded lazily by ``prompts.compaction.load_compaction_prompt()``.
  Byte-identical output; no behaviour change.  Small follow-up to
  Phase 53 rather than a numbered sub-item.
- **Dev design docs for tools, skills, and prompts (Phase 53.5)** —
  three new `design/` documents make the previously-implicit
  contracts explicit:
  - `design/TOOLS.md` — the `Tool` ABC, `build_tools()` factory
    pattern, how to add or remove a tool, naming conventions, error-
    handling contract.
  - `design/SKILLS.md` — `SkillsIndex` discovery, frontmatter
    schema, lazy load-on-demand flow, system-prompt injection, how
    to add or remove a skill.
  - `design/PROMPTS.md` — prompt layering across system / subagent
    / planning / tasks / compaction / skills, Jinja2 conventions
    (`StrictUndefined`, trailing-newline policy, lazy caching), the
    `_JINJA_SYNTAX` sanitisation guard and why it exists.
  Cross-linked from `CLAUDE.md` "Reference Documents" and from
  `design/AGENT.md`.
- **Tools registry module renamed (Phase 53.4)** —
  ``cantrip.agent.tools.registry`` → ``cantrip.agent.tools.oci_registry``.
  The module holds Docker Hub / OCI image-search tools, not a tool-
  registration mechanism; the old name was misleading.

### Added
- **Web UI accessibility audit (design doc)** — `design/WEB_UI_ACCESSIBILITY_AUDIT.md`
  captures a WCAG 2.1 AA audit of the browser UI (5 high-, 5 medium-,
  4 low-severity findings) with reproducible evidence gathered via
  ``rodney`` + ``showboat``.  Screenshots in
  ``design/images/accessibility-audit/``.  Remediation tracked in
  ROADMAP Phase 60 (visible focus indicators, Send-button contrast,
  chat-input label, live regions for chat/thinking/status, overlays as
  modal dialogs, plus medium/low polish).
- **`harness-migration` skill** — dedicated skill for rewriting deprecated
  `ops.testing.Harness` unit tests as state-transition (Scenario) tests.
  Covers the Harness→Scenario mapping table, event-specific recipes
  (actions, relation-changed, pebble-ready, collect-status), a grep
  pattern for inventorying remaining Harness usage, and per-file
  workflow with done criteria. Adapted from the upstream
  [canonical/copilot-collections](https://github.com/canonical/copilot-collections)
  `migrate-harness-tests-to-state-transition-test` skill (revision
  `a4e2d1d`) with UK English and cantrip tool names; the `charm-improvement`
  skill now cross-references it.
- **PyPI attestation checks for charm dependencies** — a shared
  ``pypi_attest`` helper consults the PyPI simple-index v1 API to
  determine whether a release carries a PEP 740 attestation uploaded
  via a trusted publisher.
  - **Charmlint** gains two new rules: ``ATT001`` (must-have package
    missing a PyPI attestation — *error*) and ``ATT002`` (any other
    dependency missing one — *info*).  Must-have packages are ``ops``,
    ``ops-scenario``, ``ops-tracing``, ``jubilant`` and ``charmlibs-*``.
    Dependencies are read from ``pyproject.toml``'s
    ``[project].dependencies`` and from ``requirements.txt``.
  - **Quickpack** gains a ``--verify-attestations`` flag.  Must-have
    packages are always enforced (pack fails with exit 2 when unsigned);
    the flag extends the enforcement to every installed dependency.
  Network or PyPI errors fail open (warnings only) so offline builds and
  linters remain usable.  Unit tests mock the PyPI responses; new spread
  tests exercise the behaviour end-to-end against real PyPI.
- **Chat search and navigation (Phase 31.1)** — the TUI chat and the
  transcript viewer are now searchable. In the chat, `/` (when the input is
  empty) or `Ctrl+F` opens a search bar above the history; typing filters
  matches across all messages with a live `1/N` counter, Enter jumps to the
  next match, and Escape closes the bar and returns focus to the chat input.
  The transcript screen (F9) gets the same bindings over its conversation,
  tasks, and events views. Matches are highlighted (bright yellow for the
  active one, reverse-video for the rest); the match-finding logic is
  case-insensitive and escapes Rich markup in user/assistant text so
  highlight never collides with pre-existing bracket content.
- **Token cost estimates (Phase 31.4 — partial)** — new `cantrip.llm.pricing`
  module captures per-million-token rates for the Claude 4 family
  (Opus/Sonnet/Haiku), Gemini 2.5/3 tiers, and inference-snap (free).  The
  TUI `ModelInfoBar` now appends an "est. $X.XX" figure to the session and
  all-time lines, pricing each model individually via a new
  `SessionStore.get_usage_by_model_since()` helper.  Claude's cache-read
  (10%) and cache-write (125%) modifiers are applied to the agent's
  session-level cache counters.  The CLI `/cost` command grew a per-model
  cost column and an overall estimated total.  Category breakdown is
  deferred — it requires tagging each `token_usage` row with the
  originating task, which is a larger plumbing change.
- **Token-level streaming in the TUI (Phase 31.2)** — the TUI now renders assistant
  text as chunks arrive from the LLM instead of waiting for the full response.
  `_process_agent_message` iterates `process_message_streaming`; a new
  `MessageWidget.append_content` method grows the in-progress message and
  `ChatWidget.append_streaming_chunk` keeps the scroll pinned. The status bar
  flips from "⟳ Thinking..." to "⟳ Streaming..." on the first non-empty chunk,
  so users see both the pre-stream wait and the ongoing activity. Cancellation
  (`Ctrl+C`) propagates through the async generator and preserves partial
  content. Completes 28.6 (the TUI half that was outstanding).

### Fixed
- **Context budget message echoed by smaller models** — `ContextManager.build_budget_message`
  now wraps the "[Context Budget] … tokens used" line in a `<system_note>` tag with an
  explicit "do not echo it in your reply" preamble. Without this, `gemini-3-flash-preview`
  would sometimes verbatim include the budget text at the end of its response (reproduced
  with a short prompt where the model read the budget message as part of the instruction).
  `gemini-3-pro-preview` (the default) was unaffected; the wrapper defends the flash path
  and any future small/fast models without altering the budget data the model sees.

### Changed
- **Phase 25 cleanup** — `tui/app.py` widget/screen imports converted to module-level
  aliases (`from cantrip.tui.widgets import chat as chat_widget`) per CLAUDE.md's
  "import modules, not names" rule. `"confirm-improvements"` / `"confirm-design"` /
  `"confirm-day2"` / `"confirm-operability"` magic strings extracted to
  `*_CONFIRM_BASE` constants in `planner.py`. `GitCommitTool` GPG signing is now
  opt-in via the `CANTRIP_GPG_SIGN` environment variable (truthy values: `1`,
  `true`, `yes`, `on`); default behaviour is unchanged (`--no-gpg-sign`).

### Added
- **Inner Parliament (experimental)** — five emotion subagents (Joy, Fear, Anger, Disgust, Sadness) review the current charm through distinct review lenses and emit structured suggestions. Invoked on-demand via `/feelings` in the TUI; default pair is `joy` + `fear`, or pass any subset (`/feelings anger disgust`). Runs in parallel on the light provider with no tools and no work-queue writes — output is a markdown report. Each emotion is scoped to avoid overlap (Anger = user-visible friction, Disgust = code taste; Fear = risk, Sadness = graceful degradation). Includes how-to and explanation documentation under `docs/docs/`.
- **Quickpack Rust backend** — alternative Rust implementation of quickpack (`src/quickpack-rs/`) with ~5x faster startup (43 ms vs 215 ms) and ~2x faster end-to-end packing. The `quick_pack` agent tool automatically uses the Rust binary when available, falling back to the Python library transparently. Includes spread test suite and explanation documentation.
- **Charmlint Rust backend** — alternative Rust implementation of charmlint (`src/charmlint-rs/`) with all 40+ rules across 12 categories. ~7x faster than the Python version (27 ms vs 181 ms full lint run). The `charmlint` agent tool automatically uses the Rust binary when available, falling back to the Python library transparently. Includes spread test suite (43 tests) and explanation documentation.
- **GitHub remote detection (Phase 42.1)** — on startup, Cantrip detects GitHub origin remotes (HTTPS and SSH URLs) and exposes `github_repo` on `AgentState`; the detected `owner/repo` is shown in the TUI header subtitle, model info bar, and CLI banner
- **Issue triage background worker (Phase 42.2)** — when a GitHub remote is detected, a background worker fetches open issues via `gh issue list`, ranks them by actionability (labels, body length, comment count), and presents the top candidates as CONFIRM tasks; the user can approve to generate a research → build → test task chain, or skip to dismiss
- **Branch-per-change workflow (Phase 42.3)** — when a GitHub remote is detected and the agent works on a triage issue or improvement, a `cantrip/<description>` feature branch is created automatically; after all work tasks complete, a push-confirmation CONFIRM task prompts the user to push or leave the branch local
- **Open pull requests (Phase 42.4)** — after pushing a feature branch, the user is offered to open a PR (or draft PR) via `gh pr create`; the PR title references the originating issue, the body includes task summaries and a collapsible agent work details section; requires explicit user confirmation
- **Repository bootstrap (Phase 42.5)** — when no GitHub remote is configured and `gh` is available, Cantrip offers to create a repository after a charm is built; handles git init, initial commit, `gh repo create` (public/private, with optional org and description), and push; re-detects the remote on success so subsequent GitHub features activate
- **Issue-driven maintenance loop (Phase 42.6)** — after a PR is created, the user can **comment** on the originating issue, check for **next** issues, or **done** to stop; `retriage_issues()` re-runs triage preserving already-examined issues; `check_upstream_diverged()` warns when the default branch is behind origin; `gh_issue_comment()` posts resolution notes on issues
- **PR feedback loop (Phase 42.7)** — after opening a PR, the user can reply **review** to fetch PR status and review comments via `gh pr view --json`; when changes are requested, reply **fix** to generate a BUILD task addressing the feedback, followed by a push-confirm; supports the full reviewer requests change → agent fixes → user approves → push cycle
- **Compaction safety: cycles, budgets, size validation (Phase 40)** — `ContextManager` now caps per-session compactions (default 20) and emergency truncations (default 5) so a runaway session can't loop on compact→expand forever. A sliding-window cycle detector trips when 3 compactions within 60s all leave the post-count above threshold — at that point, compaction disables itself and a SYSTEM message warns the user to start a new session or reduce output verbosity. `compact()` now validates that its output is actually smaller than the input and falls back to `emergency_truncate()` immediately if the summary bloated things (rather than letting the next `should_compact()` check re-invoke the same broken path). Counters are persisted on the `session` table (schema v7) so budgets survive session resume, and are restored in `load_state()`.
- **Quick Pack wired into the dev loop (Phase 38.2/38.3)** — sprint-build and deploy-improved planner flows now instruct the agent to prefer `quick_pack` and fall back to `charmcraft_pack` only when quick_pack can't apply. Sprint-build keeps the scaffolded `uv` plugin (no more swap to the slower `charm` plugin) and adds a `uv lock` step so quick_pack can run. System and compact prompts now describe three distinct dev-cycle paths — `charm_sync` (fastest, .py-only, already deployed — but skips Juju's deploy/refresh so wrong for initial deploys and upgrade tests), `quick_pack` (initial deploy / upgrade testing), and `charmcraft_pack` (fallback when quick_pack can't apply or before declaring done). BUILD and DEPLOY subagent guidance and the `infrastructure-charm` skill updated to match. Quick Pack now raises a clear error when a part uses `override-build`/`override-stage`/`override-prime`/`override-pull` rather than silently ignoring them, so the fallback to charmcraft fires cleanly for charms like tempo, loki, and traefik-k8s.
- **Charm self-review skills (Phase 34.1/34.2)** — two new bundled skills, `security-review` and `find-bugs`, adapted from the getsentry/skills patterns for charm-specific risks (shell injection, Juju secrets vs config, relation-data trust, SSRF, path traversal) and bugs (missing status updates, wrong observer registration, Pebble layer merging, leader-only relation writes, secrets/storage/upgrade handling). BUILD subagent guidance now instructs self-review via `load_skill` before finishing, with HIGH-confidence findings surfaced to the user and MEDIUM ones fixed silently.
- **Supply-chain hardened scaffolding (Phase 35)** — `charmcraft_init` now drops secure-by-default `.github/workflows/ci.yaml`, `security.yaml`, and `release.yaml` into new charms, plus `.github/dependabot.yml` (with 14-day cooldowns) and a `SECURITY.md` that documents recommended branch/tag rulesets. All action `uses:` lines are pinned to full commit SHAs; workflow-level `permissions:` are empty and broadened per-job; every `actions/checkout` sets `persist-credentials: false`; `release.yaml` uses `workflow_dispatch` + a `charmhub` deployment environment (manual approval + scoped `CHARMHUB_TOKEN`) and creates the git tag via the GitHub API only after a successful Charmhub upload. System-prompt `Dependencies` section guides subagents toward stdlib-first, hash-pinned, and checksum-embedded dependencies.
- **Missing Juju tools (Phase 30.2)** — new `juju_remove_application` and `juju_show_unit` tools; added `channel` param to deploy/refresh and `base` param to deploy; capped `juju_ssh` output at 8000 chars to prevent context overflow
- **Missing git tools (Phase 30.3)** — new `git_branch` (create/list), `git_checkout`, `git_stash` (push/pop/list) tools; added `branch` and `file_path` params to `git_log`; added `draft` param to `gh_pr_create`; new `gh_pr_list` and `gh_pr_view` tools; all wired into subagent allowlists
- **Claude 4.6/4.7 and Gemini streaming usage (Phase 41.1/41.4/41.10)** — added `claude-sonnet-4-6` and `claude-opus-4-7` to the context window map and light-model routing table (Opus 4.7 → Sonnet 4.6; Sonnet 4.6 → Haiku 4.5). `GeminiProvider.stream()` now captures `usage_metadata` from the streamed chunks (previously returned empty usage), with a `None` guard so a malformed response degrades to empty usage rather than crashing — matching the Claude streaming behaviour.
- **Provider quality monitoring and tuning (Phase 41.3/41.7/41.9)** — `ClaudeProvider` now logs a one-time warning when the system prompt is below Anthropic's prompt-caching minimum (1024 tokens for Sonnet/Haiku, 2048 for Opus), so operators can see when `cache_control` is being silently ignored. `ContextManager.compact()` now logs the compression ratio on every fire and warns when the post/pre ratio exceeds 0.9 — catching ineffective compaction before it escalates into a cycle. The shared retry helper picks a Claude-specific base delay of 15s (down from 30s) since Anthropic typically recovers faster than other providers; other providers are unchanged.
- **Concierge guardrails: preset match + concurrent process** — `_is_already_provisioned()` is now preset-aware: it returns `(True, None)` only when an existing Juju controller's cloud matches the requested preset (K8s for `preset=k8s`, non-K8s for `preset=machine`). A mismatched controller returns `(False, <cloud>)` and callers refuse to run `concierge prepare` — previously, an LXD controller would mask a K8s request (or vice versa) and concierge was skipped silently, leaving the user without the substrate they asked for. A new `_concierge_already_running()` check (via `pgrep -x concierge`) also refuses to launch when another concierge process is live, to avoid two concurrent `prepare` runs trampling the environment. Both guardrails are wired into `ConciergePrepareTool`, `PreflightRunner.prepare()`, `PreflightRunner.bootstrap()`, and `PreflightRunner.warm_up()`.
- **Extended thinking for planner calls (Phase 41.2)** — `TaskPlanner`'s three LLM-backed methods (`plan_from_design`, `replan`, `plan_from_day2_findings`) now pass a 4000-token `thinking_budget`, so Claude/Gemini 3 can allocate structured reasoning to task decomposition. Providers that don't support extended thinking (inference-snap) ignore the parameter transparently.
- **Accurate token counting via provider API (Phase 41.5)** — new `LLMProvider.count_tokens_accurate()` async method sits alongside the existing sync heuristic. The default implementation just returns the heuristic so callers can always `await` it; `ClaudeProvider` overrides it to call Anthropic's `/v1/messages/count_tokens` endpoint, falling back to the heuristic on `APIError`/`APIConnectionError` or an unexpected response shape. Wired into `ContextManager.compact()` so the post-compaction cycle-detection counts and effectiveness-ratio log use real tokens; hot paths (budget checks on every turn) keep using the sync heuristic.

### Changed
- **Extended thinking support (Phase 27.4)** — added `thinking_budget` parameter to `LLMProvider.complete()` and `stream()` across all providers; Claude passes `thinking` config with automatic `temperature=1` and expanded `max_tokens`; Gemini sets `include_thoughts=True` with budget; thinking blocks captured in response metadata; `ModelInfoBar` now shows thinking indicator for Claude Sonnet 4+ and Opus 4+ models
- **CLI REPL improvements (Phase 31.10)** — added `/help`, `/tasks`, `/status`, and `/cost` commands; spinner label now updates dynamically based on task phase (Researching, Writing code, Deploying, Testing, etc.); Ctrl+C during agent processing now drains the executor cleanly

### Fixed
- **Session resume loads conversation history (Phase 31.11)** — `load_state()` now calls `store.load_messages()` and restores prior conversation into `state.messages`, so the LLM retains context across sessions; `build_resume_summary` uses SYSTEM role instead of USER to avoid breaking alternating-role patterns
- **Web UI session persistence (Phase 31.12)** — web server now calls `load_state()` on startup and `save_state()` after each chat turn; added `/api/messages` endpoint for conversation history on page reload; replaced duplicated light-provider resolution with `resolve_light_provider()`; `ProviderRateLimitError` now shows a distinct "temporarily unavailable" message instead of generic error
- **Watcher event coverage gaps (Phase 32.3)** — `databag_change` events now create DEBUG tasks; `new_offer`, `removed_offer`, and `offer_connection_change` events now create INFRA tasks; Loki URL is configurable via `WatcherConfig.loki_url` instead of hardcoded `localhost:3100`
- **Design gap inference scoped to sentences (Phase 32.4)** — `_infer_gaps_from_audit` now matches keywords within the same sentence/list-item instead of across the entire document; eliminates false positives like "Good tracing setup" + "missing" in an unrelated section; added `absent` and `not configured` as negative keywords
- **Compaction summary preserves more context (Phase 32.6)** — tool result truncation increased from 500 to 1000 chars (2000 for errors); compaction summary placed as SYSTEM message instead of USER to avoid breaking role alternation
- **Web UI input validation (Phase 31.14)** — `/api/logs` `lines` parameter clamped to `[1, 5000]`; `level` parameter validated against allowed log levels in both `/api/logs` and `/api/logs-stream`, preventing arbitrary strings from reaching subprocess calls
- **GraphScreen refresh fetches live status (Phase 29.7)** — pressing `R` in the graph screen now calls `juju status` in a background thread instead of re-rendering stale data
- **Modal title CSS layout (Phase 29.9)** — replaced manual space-padding in modal screen titles with `Horizontal` layout (title left, key hint right via CSS)
- **DesignQuestionsScreen back button (Phase 29.11)** — added "Previous" button and `Left`/`p` keybindings; Escape now returns `None` (cancelled) instead of the questions list (finished)
- **File tree click shows path (Phase 29.12)** — clicking a file in the charm tree widget now shows the file path in a toast notification instead of silently discarding the event
- **Inference snap streaming usage (Phase 27.6)** — `InferenceSnapProvider.stream()` now requests `stream_options: {"include_usage": true}` and captures `prompt_tokens`/`completion_tokens` from the final SSE chunk; previously streaming calls reported empty usage

- **User documentation** — Diataxis-structured documentation site under `docs/docs/`: a tutorial (build your first charm), four how-to guides (choose an LLM provider, improve an existing charm, export transcripts, configure light models), two reference pages (CLI reference, agent tools), and three explanation pages (architecture, charm paths, observability). Linked from the marketing site navigation.

- **Quick Pack tool** — new standalone `quickpack` package (`src/quickpack/`) that produces valid `.charm` files without charmcraft's full lifecycle. Supports the `uv` plugin (plus `dump` parts), builds locally for the host architecture, and skips LXD, linting, and analysis. Available as a CLI (`quickpack`), a Python API (`quickpack.pack.quick_pack()`), and a cantrip agent tool (`quick_pack`). Includes jujuignore pattern matching, charmcraft.yaml → metadata.yaml generation, and dispatch script creation. Comparison tests verify output matches `charmcraft pack` and speed is significantly better.
- **Claude prompt caching (Phase 27.1)** — system prompt is now sent as a content block with `cache_control: {"type": "ephemeral"}`, enabling Anthropic's prompt caching for multi-turn conversations; `cache_creation_input_tokens` and `cache_read_input_tokens` are captured in usage metrics

- **Concurrent tool execution in subagents (Phase 28.5)** — tool calls within each subagent round now execute concurrently via `asyncio.gather()` instead of sequentially, improving throughput for rounds that batch multiple independent tool calls
- **Subagent context window management (Phase 28.4)** — subagent messages are truncated when estimated tokens exceed 80% of the context window; older tool results are replaced with previews while recent rounds are preserved; BUILD tasks get 12 rounds (up from 8)
- **Compaction error recovery (Phase 28.7)** — if context compaction fails (rate limit, timeout), the conversation falls back to emergency truncation instead of crashing; `emergency_truncate()` drops oldest non-system messages to fit within budget
- **Category-specific task timeouts (Phase 28.12)** — RESEARCH tasks fail fast (300s), BUILD/DEPLOY get more time (900s), TEST/DEBUG keep the default (600s)

### Changed
- **`max_tokens` configurable (Phase 27.2)** — `LLMProvider.complete()` and `stream()` accept `max_tokens` parameter; Claude default raised from 4096 to 8192; callers (retry helper, subagent runner) can override for long-output tasks
- **Gemini unique tool call IDs (Phase 27.3)** — when Gemini returns multiple calls to the same tool in one response, each `ToolCall` now gets a unique ID (`name_0`, `name_1`, …) instead of sharing the function name; `_convert_tool_message` strips the suffix before sending results back
- **Model routing map cleanup (Phase 27.5)** — removed obsolete `gemini-2.0-flash` from context window map; added `claude-opus-4-6-20250917` entry
- **Retry jitter (Phase 27.7)** — `complete_with_retry()` now adds random jitter to the backoff delay, preventing thundering-herd retries when multiple subagents hit rate limits simultaneously
- **Unique task IDs (Phase 28.2)** — planner appends uuid suffix to all task IDs; `WorkQueue.add_task()` rejects duplicates with `ValueError`
- **Executor resilience (Phase 28.3)** — widened exception catch to `Exception` with error logging, 5s cooldown, consecutive error tracking, and `healthy` property
- **Revert cleans untracked files (Phase 28.11)** — `revert_to_clean` now runs `git clean -fd` after `git checkout .` to remove files created by failing BUILD subagents
- **SQLite upsert for tasks (Phase 28.1)** — `save_tasks` now uses `INSERT ... ON CONFLICT DO UPDATE` instead of delete-all/re-insert, reducing contention under concurrent access
- **Noop count persisted (Phase 28.8)** — `AgentTask.noop_count` is now stored in SQLite and survives session restarts
- **Work queue deep copies (Phase 28.10)** — `all_tasks()` returns deep copies; `asyncio.Lock` exposed for callers needing atomic multi-step queue operations

### Fixed
- **Shell injection in observability tools (Phase 30.1)** — `TempoQueryTool` and `LokiQueryTool` no longer embed Python scripts directly in shell strings via `juju.ssh()`; scripts are now base64-encoded, preventing command injection through crafted query parameters
- **Blocking subprocess calls in TUI (Phase 29.2)** — `LogScreen._fetch_logs()` and `RelationDetailScreen._fetch_data()` now run `subprocess.run()` in a background thread via `run_worker(thread=True)` instead of blocking the Textual event loop for up to 15 seconds
- **Chat timestamps (Phase 29.10)** — `ChatMessage.timestamp` is now rendered in the message header as `[HH:MM]`
- **Progress updates invisible (Phase 29.6)** — `MessageWidget.update_progress()` now updates the inner `Static` widget's content instead of calling `self.refresh()`, which had no visible effect
- **Dead CSS selectors (Phase 29.9)** — removed `.user-message`, `.agent-message`, `#status-content`, `.progress-indicator`, `.success-indicator`, `.error-indicator` from `cantrip.tcss`; fixed `dismiss_screen` → `dismiss` naming inconsistency in `DesignQuestionsScreen`
- **Claude streaming usage crash (Phase 41.10)** — `ClaudeProvider.stream()` now guards against `final_message.usage` being `None`, degrading to empty usage instead of crashing with `AttributeError`

### Changed
- **Deduplicated `_juju_available()` (Phase 30.8)** — moved identical helper from `juju.py` and `observability.py` to `juju_subprocess.py`
- **CONFIRM tasks no longer block unrelated work (Phase 32.5)** — `route()` now prefers non-CONFIRM ready tasks, only returning `WAIT_FOR_CONFIRMATION` when all ready tasks are CONFIRM type
- **ReadFileTool line range support (Phase 30.4)** — `read_file` tool now accepts optional `start_line` and `end_line` parameters for reading file sections without loading the entire file
- **ListDirectoryTool shows file sizes (Phase 30.4)** — `list_directory` output now includes file sizes in bytes, trailing `/` for directories, and symlink targets
- **Graph screen scrollable (Phase 29.7)** — `GraphScreen` body is now a `RichLog` instead of a `Static`, allowing long integration graphs to scroll
- **Help screen responsive layout (Phase 29.4)** — help container uses percentage-based width (`80%` with `max-width: 80`) instead of fixed 70-cell, and content is wrapped in a `ScrollableContainer` for small terminals
- **Cache hit rate in ModelInfoBar (Phase 27.1)** — when using Claude, the session token line now shows prompt cache hit rate (e.g. `cache: 85% hit`)
- **GrepTool max results fix (Phase 30.5)** — `--max-count` is per-file in ripgrep, not global; raised per-file cap to `max_results * 5` and rely on client-side truncation for the global limit
- **RunCommandTool cwd validation (Phase 30.7)** — `cwd` parameter is now validated against the project tree when a `base_path` is set, preventing the agent from running commands in arbitrary directories
- **Planning dependency validation (Phase 32.2)** — LLM-generated task plans are now validated for non-existent dependency IDs (stripped with warning) and dependency cycles (broken by removing intra-cycle edges)
- **Compact prompt retains critical context (Phase 32.1)** — `system_compact.md.j2` now includes `environment_ready`, `cos_model`, `watcher_enabled`, `skills_index`, and `recent_decisions`, preventing the agent from losing awareness after context compaction

### Added
- **COS model status display (Phase 29.5)** — the TUI now polls the COS model for `juju status` alongside the dev model; the COS section in the status panel shows a collapsed health summary (app count + active/total) and expands to a full status view on click
- **Ctrl+C agent cancellation (Phase 29.8)** — pressing Ctrl+C now cancels the running agent response worker; the status bar shows "⏹ Cancelling..." during cancellation and a "Operation cancelled." system message confirms completion; input is re-enabled immediately
- **RelationDetailScreen wired up (Phase 29.1)** — clicking a relation line in the Juju status widget now opens the `RelationDetailScreen` modal, which was previously fully implemented but unreachable; added `on_relation_line_selected` handler in `CantripApp`

### Fixed
- **Claude streaming missing usage data** — `ClaudeProvider.stream()` now calls `stream.get_final_message()` after consuming events to capture `prompt_tokens`, `completion_tokens`, and cache hit/creation counts in the final `Chunk.usage` dict; previously streaming calls reported empty usage, so token costs from streamed conversations were not tracked
- **Subagent usage recorded under wrong model** — when the executor's subagent used the light provider (e.g. Haiku for RESEARCH tasks), token usage was incorrectly attributed to the primary model (e.g. Sonnet); the subagent now stamps the actual provider name and model into `response.metadata` and the executor reads it from there, falling back to the primary provider when metadata is absent
- **Haiku missing from context window map** — added `claude-haiku-4-5-20251001` to `_CONTEXT_WINDOWS` in the Claude provider so that Haiku-based light providers report the correct 200k context window instead of relying on the fallback default
- **Streaming not actually streaming (Phase 28.6)** — `process_message_streaming` previously called the non-streaming conversation loop and yielded the entire response as a single chunk; it now uses `provider.stream()` directly and yields text chunks as they arrive from the LLM, enabling true token-level streaming for the conversation loop
- **Design proposal lost on restart (Phase 28.9)** — `state.design_proposal` is now persisted to SQLite as raw Markdown and re-parsed on session resume; previously it was transient and the executor's `_build_context()` would produce `design_content=None` after a crash or restart
- **Executor exception catch too narrow (Phase 28.3)** — `_run_loop` now catches all `Exception` subclasses (not just `KeyError`, `RuntimeError`, `OSError`), preventing unexpected errors from silently killing the autonomous work loop. Adds ERROR-level logging, a 5-second cooldown between retries, a consecutive-error counter that stops the loop after 10 failures, and a `healthy` property for monitoring
- **Status filter crash on None message** — `_app_matches_filter` in the TUI status widget no longer crashes with `AttributeError` when `app_status.message` or `workload_status.message` is `None`
- **SQLite busy timeout** — added `PRAGMA busy_timeout=5000` to the session store, preventing `SQLITE_BUSY` crashes when the executor and conversation loop write concurrently
- **Concierge status race** — `ConciergePrepareTool` no longer crashes when Juju is healthy but Concierge is not installed; the concierge status call is now wrapped in a try/except
- **EditFileTool error message** — the "string not found" error no longer appends `...` unconditionally when the search string is shorter than 50 characters
- **Help screen missing shortcuts** — added F5 (Watcher), F6 (Files), F7 (Model info), F8 (Integration graph), and F9 (Transcript) to the help overlay
- **CLI banner shows wrong path in improve mode** — banner now displays the `--improve` path instead of the default positional path argument
- **Deprecated `asyncio.get_event_loop()` in CLI** — replaced with `asyncio.get_running_loop()` in `_drain_executor`
- **Store not re-initialisable after corrupt session** — `_store_initialised` flag is now reset when `load_state` fails, allowing the store to be re-opened with a fresh database

### Added
- **Web UI playwright testing** — verified 17/18 test cases pass (page load, overlays, keyboard shortcuts, WebSocket connection, API endpoints, mobile viewport); identified frontend improvements (Markdown renderer, multiline input, tool call visibility, preflight status)
- **Roadmap Phases 27–33** — seven new phases covering LLM provider hardening (prompt caching, extended thinking, max_tokens fix), agent core robustness (SQLite safety, executor resilience, subagent context management), TUI polish (dead features wired up, blocking subprocess fixes), tool completeness (missing Juju/git tools, shell injection fix), UX improvements (streaming, chat search, cost tracking), planning quality (compact prompt, dependency validation), and new capabilities (bundles, charm migration, multi-charm workspaces)

- **Juju snap confinement (Phase 23.1)** — `JujuDeployTool` and `JujuRefreshTool` now copy `.charm` files from outside `$HOME` to `~/snap/juju/common/` before deploying, working around Juju snap strict confinement that prevented deploys from `/tmp` and other restricted paths; temp copies are cleaned up regardless of success or failure
- **Bare `Exception` catches (Phase 25.1)** — replaced every bare `except Exception` with specific exception types across 11 locations (tools/base.py, cli.py, inference_snap.py, scorer.py, test_real_charm_build.py, test_juju_live.py, web/server.py, ui/events.py, tui/screens/logs.py), per the project style guide
- **Shell injection in watcher (Phase 25.2)** — Loki polling via SSH now passes the URL as a `shlex.quote()`-escaped argument instead of interpolating it into a Python script string, preventing injection via crafted URLs
- **Ruff target version (Phase 25.3)** — `pyproject.toml` `target-version` updated from `py311` to `py312` to match `requires-python = ">=3.12"`

### Added
- **Multi-edit and run_command tools (Phase 26.5, 26.6)** — new `multi_edit` tool applies multiple edits to a single file atomically with rollback on failure; new `run_command` tool executes shell commands in a sandboxed working directory with timeout and output limits
- **PR review tools (Phase 26.4)** — new `pr_review_comments` and `pr_review_reply` tools for fetching and replying to GitHub PR review comments via the `gh` CLI
- **llms.txt awareness (Phase 26.3)** — `web_fetch` tool now auto-discovers and fetches `/llms.txt` when available, providing LLM-friendly site summaries
- **File pattern matching tool (Phase 26.2)** — new `GlobTool` (`glob`) finds files by glob pattern with optional exclusions; added to RESEARCH, BUILD, TEST, and DEBUG subagent allowlists
- **Content search tool (Phase 26.1)** — new `GrepTool` (`grep`) wraps ripgrep (with GNU grep fallback) for regex content search across the codebase; supports glob filters, context lines, case sensitivity, and max results; added to RESEARCH, BUILD, TEST, and DEBUG subagent allowlists; 29 unit tests
- **Unknown-field detection (CC005, CC006)** — charmlint now warns on unrecognised top-level and per-base fields in `charmcraft.yaml`
- **Agent tooling roadmap (Phase 26)** — six new tool items tracked in ROADMAP.md: grep, glob, llms.txt, PR review, multi-edit, scoped command runner
- **Code health roadmap (Phase 25)** — 20-item technical debt and code-review findings tracked in ROADMAP.md with severity tiers (critical/high/medium/low)

### Changed
- **Shared juju subprocess helper (Phase 25.4)** — extracted identical `_run_juju()` and `_wait_for_app()` from four tool modules (acceptance, chaos, scaling, upgrade) into `juju_subprocess.py`
- **Shared system prompt extraction (Phase 25.5)** — moved identical `_get_system_prompt()` from claude.py and gemini.py to `LLMProvider` base class
- **Shared light provider resolution (Phase 25.6)** — extracted identical three-mode provider resolution from `tui/app.py` and `cli.py` into `resolve_light_provider()` in `cantrip.llm`
- **Deduplicated conversation loop (Phase 25.7)** — extracted common logic from `process_message()` and `process_message_streaming()` into `_run_conversation_loop()`; also fixed streaming path missing `<tool_result>` wrapper
- **Data-driven terraform variables (Phase 25.8)** — replaced 150-line repetitive `_generate_variables_tf()` with 45-line data-driven approach
- **Import style fixes (Phase 25.9)** — replaced LLM type aliases with qualified `llm.Tool`/`llm.ToolResult` in core.py; moved local imports to module top in subagent.py, context.py, planning.py, audit.py
- **Fragile hook-failure matching (Phase 25.10)** — watcher now uses compiled `\bhook failed\b` regex instead of substring match
- **Encapsulation fixes (Phase 25.12)** — added public `compaction_threshold` property and `store` property so TUI no longer reaches into private members
- **Terraform error handling (Phase 25.14)** — `generate_terraform_module()` now catches YAML parse errors and validates required `name` key
- **Split executor exceptions (Phase 25.15)** — LLM provider errors now handled separately from general code errors
- **Clearer failure logging (Phase 25.16)** — `handle_*_confirmation()` methods now log at ERROR instead of WARNING when task/result not found
- **Dead code removal (Phase 25.17)** — removed unused reactive `messages` attribute from chat widget
- **TUI watcher boilerplate (Phase 25.11)** — replaced 13+4 identical `watch_*` methods with programmatic generation from attribute lists
- **Long function decompositions (Phase 25.8)** — `diff_snapshots` (~200→15 lines, three per-entity helpers), `_build_subagent_prompt` (133→20 lines, section builders + constants), `_execute_task` (134→40 lines, `_fail_task` + `_handle_result`), `_generate_variables_tf` (150→45 lines, data-driven specs), `_ensure_cos` (107→20 lines, `_check_cos_model` + `_create_cos_model` + `_deploy_cos_lite` + `_create_cos_offers`), `_convert_messages` (75→20 lines, per-role converters)
- **Charm linter (Phase 24)** — new standalone `charmlint` package (`src/charmlint/`) with 35 deterministic lint rules across 10 categories (metadata, observability, testing, deprecated APIs, libraries, actions, config quality, status reporting, security, structure); runs independently via `charmlint /path/to/charm` CLI with ruff-style text or JSON output; supports `.charmlint.yaml` config for per-rule severity overrides, category selection, and rule ignoring; zero Cantrip dependencies — only requires `pyyaml`; registered as `charmlint` console script in pyproject.toml; 58 unit tests covering all rules, config, linter engine, and CLI
- **E2E integration tests (Phase 23.2)** — tests exercise real tools against the live Juju environment: `juju_status` against real controllers, file CRUD operations, preflight warm-up and multi-controller discovery, snap confinement copy behaviour, and session state persistence round-trips; tests skip gracefully when `juju` is unavailable
- **Web UI integration graph (Phase 15.5)** — new `G` key overlay showing all deployed apps as status-coloured cards with unit breakdowns and a relations section; `R` refreshes, `Esc` closes; reuses the existing `/api/juju-status` endpoint
- **UI feature parity (Phase 15.6)** — `UI.md` replaces `TUI.md` with shared architecture diagram, event contract table, and implementation notes for both interfaces; `test_ui_events.py` verifies the event contract (all event types serialise correctly, status values match CSS classes, wildcard bus covers all types)
- **Shared UI event bus (Phase 15.1)** — `src/cantrip/ui/events.py` provides an async publish/subscribe `EventBus` with typed events, sync/async subscribers, wildcard subscriptions, and thread-safe cross-thread publishing; the TUI, web server, and CLI all subscribe to the bus for task and watcher updates instead of using direct callbacks; every event carries a JSON-serialisable payload via factory functions; `start_executor` no longer takes an `on_task_changed` callback
- **COS on multi-controller environments (Phase 22)** — preflight now detects K8s controllers when the active controller is IAAS (LXD) and deploys COS there automatically; cross-model offers are created for grafana, prometheus, loki, and tempo endpoints; PreflightResult reports all controllers, which hosts COS, and cross-controller status; system prompt, observability skill, and build guidance updated with offer/consume patterns for LXD+K8s dual-controller setups
- **Agent framework evaluation complete (Phase 18)** — surveyed 8 frameworks (Claude Agent SDK, LangGraph, CrewAI, OpenAI Agents SDK, AutoGen, Pydantic AI, smolagents, DSPy); shortlisted 3; mapped Cantrip's 12 core components against each; recommendation: stay bespoke — the two-loop architecture is Cantrip's competitive advantage and no framework replicates the work queue + concurrent subagent pattern; hybrid options identified for tool schema generation (Pydantic AI pattern) and future Claude Agent SDK migration path; full analysis in FRAMEWORK_EVALUATION.md
- **Deep Juju introspection complete (Phase 20)** — offer topology tracking in the watcher (new/removed offers, connection count changes); relation databag diffing (opt-in key-set snapshots with `databag_change` events); real-time log streaming via `juju debug-log --tail` with new `juju_stream_logs` agent tool and `/api/logs-stream` WebSocket endpoint; TUI subordinate unit tree, clickable relation detail panel with asymmetry highlighting, inline `/` search filtering across status, and YAML-based theming with 5 bundled themes and `--theme` CLI flag
- **Pure state machine for work queue routing (Phase 21.1)** — routing decisions are now made by a pure `route()` function over a frozen `WorkQueueState` snapshot; the executor's `_run_loop` delegates to `route()` for every scheduling decision; cross-check tests verify agreement with the real work queue; BFS deadlock-freedom verification proves every non-terminal state has a path to progress
- **Protocol-based service injection for executor (Phase 21.2)** — new `services.py` defines Protocol interfaces (`GitService`, `StateService`, `EnvironmentChecker`, `FollowupPlanner`) for all external dependencies; the executor accepts optional service implementations via constructor injection; fake implementations in `conftest.py` enable full executor testing without subprocess calls, real LLM providers, or filesystem access; full backward compatibility when no services are injected
- **Juju introspection tools (Phase 20.1, 20.2, 20.4)** — new `juju_read_relation_data` tool reads relation databags via `juju show-unit` with endpoint filtering and asymmetry detection; new `juju_get_app_config` tool reads deployed config with source tracking (default/user-set); new `juju_list_offers` tool lists cross-model offers with connection counts; all added to relevant subagent allowlists
- **Deeper acceptance testing (Phase 17.2, 17.3, 17.5)** — relation smoke tests now verify databag data flow (not just settle status); acceptance guidance includes functional probes (SSH-based workload exercising); new `config_under_load_test` tool applies config changes while probing a health endpoint for downtime
- **Two-stage graceful shutdown (Phase 21.4)** — new `drain()` method stops scheduling new tasks and waits for in-flight subagents to finish; new `force_stop()` cancels all in-flight tasks immediately; ACTIVE tasks are automatically reset to PENDING on startup and force-stop so interrupted work is retried
- **Structured subagent exit contracts (Phase 21.5)** — subagents now return a `SubagentResult` with an `ExitState` enum (`completed`, `blocked`, `failed`, `noop`) instead of a plain string; the subagent prompt requires every response to end with an `[EXIT: state]` tag; the executor handles each state appropriately (block task, fail task, trigger noop counter, or mark done); exit state and round count recorded in the session store
- **Noop detection (Phase 21.3)** — the executor now captures a git fingerprint before and after each subagent run; if no observable change occurred, the task is retried automatically; after 2 consecutive noops the task is blocked and escalated to the user for guidance
- **Juju secrets inspection (Phase 20.5)** — new `juju_list_secrets` tool lists all secrets in a model with owner, rotation, and access grants; new `juju_show_secret` tool inspects a specific secret with optional content reveal; both added to RESEARCH and DEBUG subagent allowlists
- **Code modernisation checks (Phase 10.4)** — charm audit now checks for type annotations (return-type hints on functions) and modern Ops framework patterns (holistic status reconciliation, config-changed handling, relation-changed handling, Pebble readiness checks); gaps feed into the `modernise-code` improvement task with specific remediation guidance
- **Operational readiness assessment (Phase 19)** — new `operational_readiness` tool evaluates charms against Canonical's Operational Readiness Metrics across five pillars (Best Practices, Documentation, Reliability, Maintainability, Security); deterministic checks cover status reporting, operational actions, config quality, documentation, backup/restore, COS integration, TLS, and secrets management; produces scored OPERATIONAL_READINESS.md and structured data; new `operational-readiness` skill provides implementation patterns for subagents; assessment runs automatically after acceptance testing and generates fix tasks for confirmed gaps
- **Acceptance test feedback loop** — when acceptance tests find failures (broken actions, non-functional relations, dead config options), the autodeploy pipeline now automatically creates a targeted BUILD fix task with the failing areas and remediation steps; the charm iterates until acceptance tests pass; loop guard prevents infinite chains
- **Day-2 operations research** — after the initial build and deploy, the agent automatically researches day-2 operational concerns (backup/restore, scaling, HA, upgrades, security hardening, monitoring, disaster recovery) using web search and training data, then presents findings to the user for a focused discussion; confirmed operational areas drive additional charm features (actions, config options, relations); the user's operational expertise is solicited but research-based defaults are used when the user is unsure
- **Web search tool** — new `web_search` tool using DuckDuckGo for open-ended web research; available to RESEARCH subagents alongside the existing `web_fetch` tool; returns structured results (title, URL, snippet) that subagents can follow up with `web_fetch`
- **Paginated HTML transcripts (Phase 14)** — `cantrip export-transcript --page-size N` splits long HTML transcripts into multiple files with previous/next navigation; tasks and events on page 1; each page is self-contained with inline CSS and search
- **Complete demo generation (Phase 13)** — demo guidance now covers Showboat-driven DEMO.md with relation wiring, action and config showcases (falling back to `write_file` when Showboat is unavailable); trace capture via `tempo_query` to `demo/traces/` with span summary; Grafana dashboard export and screenshot via Rodney to `demo/dashboards/` and `demo/screenshots/`; web UI screenshot for web-facing charms; quick-start section at top of TUTORIAL.md; demo validation step; `GenerateReadmeTool` now links DEMO.md, TUTORIAL.md, and architecture.md in the README and embeds `demo/juju-status.txt` in a collapsible block; `tempo_query` added to BUILD tool allowlist

### Changed
- **Refactored file tools** — extracted `PathAwareTool` base class in `tools/files.py` to eliminate four identical copies of `_resolve_path()` across `ReadFileTool`, `WriteFileTool`, `ListDirectoryTool`, and `EditFileTool`
- **Refactored git tools** — extracted `_run_git()` helper in `tools/git.py` to consolidate the repeated pattern of git-not-found check, subprocess execution, timeout handling, and exit code inspection across all eight git tool classes
- **Shared retry logic** — extracted `complete_with_retry()` into `agent/retry.py`, used by both the main conversation loop and subagent runners; eliminates duplicated retry-with-backoff implementations
- **Shared tool execution** — extracted `execute_tool()` into `tools/base.py`, shared by `core.py` and `subagent.py`; consolidates error handling for unknown tools, bad arguments, and unexpected exceptions
- **Centralised tool construction** — added `build_tools()` factory in `tools/__init__.py`, replacing 80+ individual class imports in `core.py` with a single function call
- **Category guidance as markdown** — moved subagent category guidance (research, build, deploy, test, debug, infra) from inline Python strings to plain markdown files in `prompts/subagent/`; these can be maintained without Python knowledge; also moved demo and acceptance guidance to markdown files

### Added
- **Acceptance testing (Phase 17)** — five new tools exercise a deployed charm like a real operator: `action_exerciser` runs every action and verifies results (skipping destructive actions by default); `relation_smoke_test` deploys well-known partner charms for each relation endpoint and verifies both sides settle; `workload_endpoint_test` discovers HTTP/TCP endpoints from charm metadata and probes them with health checks; `config_variation_test` sets each config option to a non-default value, waits for settle, and resets; `acceptance_report` consolidates all results into `ACCEPTANCE.md`. The build pipeline now chains TEST → acceptance → demo (previously TEST → demo directly). Planner guidance updated to include acceptance testing as a standard phase.
- **Charm pairs** — design proposals now identify companion charms (databases, caches, ingress) needed at deploy time; companions are parsed into structured `CompanionCharm` data, shown to the user for confirmation, and flow into planner and deploy subagent guidance so they are automatically deployed and related alongside the primary charm
- **Migration assistance** — `cantrip run --improve /path/to/charm` launches improvement mode: audits the existing charm, presents findings, and generates fix tasks for observability, tests, deprecated APIs, and listing readiness; wires the full audit → confirm → fix → validate → deploy → review pipeline end-to-end
- **Placeholder icon generation** — `GenerateIconTool` (`generate_icon`) creates a simple SVG icon (coloured circle with the charm's initial letter) for charms missing `icon.svg`, unblocking Charmhub publishing; colour is deterministically derived from the charm name; the listing-readiness improvement task now includes icon generation
- **Documentation generation** — `GenerateDocsTool` (`generate_docs`) creates a `docs/` directory with Diátaxis-structured documentation (tutorial, how-to, reference, explanation) using the Canonical starter pack; content populated from `charmcraft.yaml` metadata; includes Makefile, conf.py, .readthedocs.yaml for building with Sphinx
- **Dependency updates audit** — charm audit now detects `charmcraft fetch-libs` imports (`from charms.<lib>.v<N>`) and maps them against a table of known PyPI equivalents (data-platform-libs, grafana-k8s-lib, etc.); known replacements appear as should-fix, unknown libs as nice-to-have
- **Integration test template generation** — `GenerateTestsTool` (`generate_tests`) produces Jubilant-based integration test templates from `charmcraft.yaml`: conftest fixtures, deploy test, plus per-relation, per-action, and per-config tests in separate files; BUILD subagent guidance updated to use `generate_tests` as the first step of the red/green cycle
- **Architecture diagram** — `GenerateDiagramTool` (`generate_diagram`) generates a Mermaid diagram from `charmcraft.yaml` showing requires/provides/peers relations and containers; also embedded in the generated docs explanation section
- **Load test generation** — `GenerateLoadTestTool` (`generate_load_test`) produces Jubilant-based load tests measuring action throughput, config settling time, and scaling behaviour; for web-facing charms, also generates a k6 HTTP load test script with ramp stages and thresholds
- **Showboat integration** — `ShowboatTool` (`showboat`) wraps the Showboat CLI for building demo documents by running real commands and capturing output inline; supports init, note, exec, image, pop, verify subcommands
- **Rodney integration** — `RodneyTool` (`rodney`) wraps the Rodney CLI for headless browser automation; supports navigation, screenshots, element interaction, and JavaScript execution; available to BUILD and TEST subagents for visual capture and web UI verification

### Fixed
- **Gemini streaming crash** — `stream()` did not `await` the `generate_content_stream()` coroutine, causing `TypeError: 'async for' requires an object with __aiter__ method`; streaming was completely broken for Gemini
- **Gemini safety-filter crash** — `complete()` accessed `response.candidates[0].content.parts` without guarding against `content` being `None` (happens when Gemini safety-filters the response); now returns an empty response instead of crashing
- **Gemini usage metadata crash** — `complete()` accessed `response.usage_metadata.prompt_token_count` without checking `usage_metadata` for `None`; now defaults to zero
- **Gemini None function-call args crash** — `dict(None)` raised `TypeError` when Gemini returned a function call with `args=None`; now defaults to empty dict
- **Companion endpoint backticks** — design parser kept Markdown backticks in companion charm endpoint names; regex now strips optional backticks
- **Web server event loop blocking** — `/api/juju-status` and `/api/logs` called blocking `juju.status()` and `subprocess.run()` synchronously in async handlers; now use `asyncio.to_thread()`
- **Web server query parameter crash** — `/api/logs?lines=abc` crashed with `ValueError`; now catches and defaults to 100
- **Corrupt JSON in events/subagent messages** — `load_events()` and `load_subagent_messages()` crashed on malformed JSON; now handle gracefully (matching existing `load_messages()` pattern)
- **Blocking juju.status in preflight** — `_ensure_cos()` called `juju.status()` synchronously in an async method; now uses `asyncio.to_thread()`
- **Incomplete container port detection** — `_detect_http_port()` had a stub loop that never detected container ports from charmcraft.yaml; now parses `ports[].target` entries
- **Unit name validation** — `_agent_charm_dir()` crashed with a cryptic unpacking error on malformed unit names; now validates format explicitly
- **CLI drain hang** — `_drain_executor()` could loop forever waiting for blocked CONFIRM tasks that require user confirmation; now times out after 60 seconds and only waits for pending/active tasks
- **Task persistence lost on save** — `save_state()` persisted charm metadata and messages but not the work queue; tasks were only saved by the background executor's internal `_persist()` loop, so CLI-mode sessions lost all tasks on restart
- **COS deployment crashes on LXD controller** — preflight tried to deploy `cos-lite` (K8s-only charms) into a model on an IAAS/LXD cloud, always failing; now detects the cloud type and skips COS gracefully (full multi-controller COS support planned in ROADMAP Phase 22)
- **Forward-referenced constants in autodeploy** — `_DEMO_PREFIX` and `_RETRY_PREFIX` were defined after their first use, causing `NameError` at runtime when `tasks_after_test()` or `tasks_after_build_failure()` was called
- **WebSocket broadcast fire-and-forget** — `_broadcast()` used `asyncio.ensure_future` without error handling; disconnected clients would raise unhandled exceptions; now uses `contextlib.suppress` for connection errors
- **Gemini empty candidates crash** — `complete()` accessed `response.candidates[0]` without checking the list was non-empty; now raises a clear `ProviderError` instead of `IndexError`
- **Command injection in `juju_dispatch`** — event name was interpolated unsanitised into a shell command; now validated against `[a-z0-9_-]+` before use
- **Command injection in `charm_sync`** — remote file paths were interpolated unsanitised into `mkdir -p` and `tee` commands; now escaped with `shlex.quote()`
- **Decision timestamps lost on reload** — `load_session()` did not SELECT the `timestamp` column from the decisions table, so every reload silently replaced original timestamps with the current time
- **Corrupt JSON crashes session load** — `load_tasks()` and `load_messages()` called `json.loads()` without error handling; a single malformed row would crash the entire load; now skips corrupt rows with a warning
- **Unsafe URL schemes in web fetch** — `WebFetchTool` accepted any URL scheme (`file://`, `data://`, etc.); now restricted to `http://` and `https://`
- **Failed dependency deadlock** — when a task failed, all downstream tasks that depended on it would remain stuck in `pending` status forever; `all_ready()` now treats both `done` and `failed` dependencies as resolved
- **Terraform tool crash on empty YAML** — `GenerateTerraformTool` raised `TypeError` when `charmcraft.yaml` was empty or contained only comments; now caught alongside `KeyError` and `YAMLError`
- **Empty YAML frontmatter crash in skills** — `yaml.safe_load()` returning `None` for empty frontmatter was not handled; now guarded with explicit `None` check
- **Corrupt base64 thought signatures crash Gemini provider** — malformed base64 in session metadata caused `binascii.Error` when restoring Gemini thought signatures; now suppressed gracefully
- **Shell injection in Tempo/Loki query tools** — user-provided parameters were interpolated into a Python script executed via SSH without escaping; trace IDs are now validated as hex, and all URLs have single quotes escaped to prevent breakout
- **Inference snap crash on non-JSON response** — `resp.json()` in the `complete()` method had no error handling; now raises `ProviderError` with response preview
- **Inference snap crash on empty snap list lines** — `line.split()[0]` raised `IndexError` on empty lines from `snap list` output; now skips empty lines
- **Lazy imports in helpers** — moved lazy `import json` / `import subprocess` to module level in `preflight.py` and `environment.py` to comply with project conventions
- **Charmhub tools crash on non-JSON response** — `response.json()` in both `CharmhubSearchTool` and `CharmhubInfoTool` was called outside error handling; now catches `JSONDecodeError` and returns a graceful error
- **Terraform module generation crash on empty YAML** — `generate_terraform_module()` crashed with `TypeError` when `charmcraft.yaml` was empty; now validates the parsed YAML is a non-empty mapping before accessing fields
- **Duplicate tool declarations** — `HookBenchmarkTool` and `FuzzTestTool` were registered twice in the tool list, causing Gemini API errors (`Duplicate function declaration found: hook_benchmark`)
- **Web UI crash on startup** — `_create_app` called `WorkQueue.set_callback()` which does not exist; removed the redundant call since `start_executor` already wires the callback
- **Subprocess leak on timeout** — `_run_concierge` and `JujuDebugLogTool` did not kill the subprocess when `asyncio.wait_for` timed out, leaking orphan processes
- **`_ensure_claude_md` crash** — writing `CLAUDE.md` would raise `FileNotFoundError` if the charm directory did not yet exist
- **Bare `Exception` catches in file tools** — `ReadFileTool`, `WriteFileTool`, `ListDirectoryTool`, and `EditFileTool` now catch specific exceptions (`OSError`, `UnicodeDecodeError`, `ValueError`) instead of bare `Exception`
- **Path traversal via directory prefix** — file tools used `str.startswith()` for path restriction, which allowed access to sibling directories with matching name prefixes (e.g. `/tmp/charm-evil/` when base_path is `/tmp/charm`); now uses `Path.is_relative_to()`
- **Web UI concurrent message corruption** — multiple browser tabs could send chat messages simultaneously, corrupting conversation state; messages are now serialised through an `asyncio.Lock`
- **Subagent tool crash propagation** — unexpected exceptions from tool execution in subagents would abort the entire task instead of returning an error result to the LLM; now matches the core agent's defensive error handling
- **TUI click crash** — clicking on empty areas in the task checklist could raise `NoWidget` from Textual's `get_widget_at()`; now caught gracefully
- **TUI preflight index overflow** — `update_preflight()` did not bounds-check group and item indices, risking `IndexError` if preflight events arrived out of order
- **Juju tools block event loop indefinitely** — all Jubilant calls (status, deploy, refresh, ssh, etc.) were synchronous, blocking the entire asyncio event loop when the Juju controller was slow or unresponsive; now wrapped in `asyncio.to_thread` with timeouts (120s default, 300s for deploy, 900s for wait)
- **Session resume never wired** — `save_state()`, `load_state()`, and `build_resume_summary()` existed but were never called by any entry point; CLI and TUI now persist session state after each conversation turn and load it on restart
- **Cancelled tasks block downstream forever** — cancelling a task via `manage_tasks cancel` removed it from the queue, but downstream tasks whose dependencies referenced the cancelled task would never become ready; `all_ready()` now treats missing dependencies as satisfied
- **Cannot approve pending CONFIRM tasks** — when the conversation LLM short-circuited research by doing it inline, the CONFIRM task stayed `pending` (executor never picked it up to set it `blocked`); `manage_tasks approve` now accepts both pending and blocked CONFIRM tasks
- **Corrupt `.cantrip` file crashes application** — a non-SQLite `.cantrip` file caused an unhandled `sqlite3.DatabaseError` on startup; now caught gracefully with a warning, disabling persistence for the session

### Added
- **Operational readiness assessment (Phase 19)** — new roadmap phase for evaluating charms against Canonical's Operational Readiness Metrics standard; includes an assessment tool (`operational_readiness`) that scores charms across five pillars (Best Practices, Documentation, Reliability, Maintainability, Security), an `operational-readiness` skill with implementation patterns for health checks, pause/resume, backup/restore, diagnostics, and upgrade pre-flight, and planner integration that autonomously closes gaps after build+test
- **Web UI** — `cantrip --web` launches a browser-based interface at `http://127.0.0.1:8471` (configurable via `--web-port`); server-rendered Jinja2 template with vanilla CSS and minimal JavaScript (no React/Vue/Angular — inspired by server-first Datastar/htmx philosophy); two-column layout with: scrollable chat panel with inline Markdown rendering (headings, bold, code, code blocks, lists) for assistant messages, coloured role indicators, and thinking animation; live task checklist with status icons, category badges, and dynamic WebSocket updates; Juju status panel showing app boxes with status indicators, unit counts, and messages (polled every 15s via `/api/juju-status`); modal log viewer (`L` key) fetching `juju debug-log` via `/api/logs`; help overlay (`?` key) with keyboard shortcuts; `cantrip.js` WebSocket client with auto-reconnect (exponential backoff), incremental DOM updates, optimistic chat input, and `/api/state` resync; aiohttp backend with four API endpoints (`/`, `/ws`, `/api/state`, `/api/juju-status`, `/api/logs`)
- **Upgrade testing tool** — new `upgrade_test` tool refreshes a deployed charm with a new `.charm` file and verifies it returns to active/idle; captures pre/post status, checks debug-log for hook failures during upgrade, detects status regressions, and reports a detailed PASS/FAIL verdict; supports resource attachments; added to TEST tool allowlist
- **Test report tool** — new `test_report` tool runs unit and integration tests, aggregates results into a Markdown report with pass/fail counts, failure output excerpts, and an overall PASS/FAIL verdict; added to TEST tool allowlist
- **Chaos testing tool** — new `chaos_test` tool performs destructive operations on a deployed charm (kill-unit, remove-relation, scale-down, config-reset) and waits for recovery to active/idle; produces a Markdown report with pre/post status; added to TEST tool allowlist
- **Scaling test tool** — new `scaling_test` tool scales an application up to a target unit count, waits for settlement, optionally scales back; verifies peer relations and leader election survive scaling; added to TEST tool allowlist
- **Hook benchmark tool** — new `hook_benchmark` tool analyses `juju debug-log` output to extract hook execution times, computes per-hook statistics (min/max/avg/count), and flags hooks exceeding a configurable threshold (default 5 s); produces a structured Markdown report; added to TEST tool allowlist
- **Fuzz testing tool** — new `fuzz_charm` tool reads charm config options and action parameters, generates randomised test cases with boundary values, type mismatches, injection strings (SQL, XSS, path traversal, JNDI), and edge cases; supports reproducible output via seed parameter; produces a Markdown fuzz test plan; added to TEST and BUILD tool allowlists
- **Charm demo generation** — successful TEST tasks now automatically spawn a demo generation BUILD task via `tasks_after_test()` in `autodeploy.py`; the demo subagent captures live deployment output (`juju_status`, `juju_run_action`, `juju_config`, `juju_debug_log` — all added to the BUILD tool allowlist) and writes `DEMO.md` (annotated walk-through with real output), `demo.sh` (self-contained deployment script with `--cleanup`), `TUTORIAL.md` (step-by-step guide), and `demo/` artefacts (status, config, action results, logs); `_DEMO_GUIDANCE` in subagent provides detailed 10-step instructions injected for demo-titled BUILD tasks; `_DESIGN_TO_BUILD_PROMPT` updated to include demo generation in LLM-planned build sequences; loop guard via `_DEMO_PREFIX` prevents infinite task chains
- **Filtered transcript export** — `cantrip export-transcript` gains `--task <id>`, `--phase research|build|deploy|test`, and `--since <timestamp>` flags for narrowing exports to specific tasks, pipeline phases, or time ranges; filters compose and apply to all output formats (HTML, JSONL, Markdown)
- **TUI transcript screen (F9)** — new `TranscriptScreen` modal with three switchable views (conversation, tasks, events) accessed via the `v` key; shows messages with role indicators and tool call summaries, task status with subagent conversation counts, and typed events with detail fields; loaded from the `.cantrip` SQLite session file
- **Existing charm improvement (deepened)** — observability fill task now instructs generating Grafana dashboard JSON, Prometheus alert rules, metrics endpoint, and Loki log forwarding; test fill task now includes detailed Jubilant integration test patterns (deploy, relate, actions, config) and iterates until green; improvement pipeline extended with `deploy-verify-improvements` DEPLOY task (pack, deploy, relate, `juju_wait`) and `diff-review` RESEARCH task (git log/diff summary grouped by category); full pipeline with all gaps: 4 fixes → validate → deploy-verify → diff-review (7 tasks)
- **Existing charm improvement** — new `charm_audit` tool performs deterministic checks on an existing charm directory: COS integration gaps (tracing, metrics, logging, dashboards), ops-tracing setup, test coverage (unit + integration), deprecated API usage (StoredState, Harness, fetch-libs imports), metadata completeness for Charmhub listing (display-name, summary, description, docs, issues, source, tags), README, LICENSE, and icon; produces a structured AUDIT.md grouped by severity (must-fix, should-fix, nice-to-have) plus machine-readable gap data; new `plan_improvement_phase` deterministic task template generates audit → confirm → fix flow; `plan_improvement_fixes` generates conditional BUILD tasks (observability fill, test fill, code modernisation, listing readiness) based on audit findings, each committed separately; `AgentState` gains `mode` ("build"/"improve") and `audit_report` fields; `PlanningContext` gains `existing_charm_path`; new `charm-improvement` skill with detailed guidance on COS integration, Scenario/Jubilant test patterns, Harness migration, deprecated API replacements, and listing requirements; system prompt updated to recognise improvement intent and route to audit flow
- **Red/green charm building** — the build pipeline now follows an integration-tests-first approach: BUILD subagents write Jubilant integration tests from the approved design *before* writing charm code, then iterate until tests pass; `_DESIGN_TO_BUILD_PROMPT` and `plan_one_shot_build` reordered to scaffold → write integration tests (red) → write charm code (green) → iterate → write unit tests for edge cases; `run_charm_tests` gains an optional `pattern` parameter for selective test execution (file names, `file::function`, or `-k` expressions), enabling faster red/green iteration on specific failures; TEST guidance updated to run both unit and integration tests as a combined validation gate; failed BUILD tasks with partial test progress (some passing, some failing) now spawn a targeted retry BUILD task instead of a generic DEBUG task, keeping the red/green iteration loop going (bounded to one retry to prevent infinite chains)
- **Session transcript recording** — all conversation-loop messages (user, assistant, tool calls/results) are persisted to SQLite via write-through recording in `CantripAgent`; subagent conversations are captured with full tool-call detail linked to their parent task; significant events (session start/resume, task status changes, design confirmation, watcher events, errors) recorded in an `events` table; schema bumped to v4
- **Transcript export** — `cantrip export-transcript <path>` CLI command produces a self-contained HTML transcript with dark/light mode, collapsible tool calls, subagent threads nested under tasks, event timeline, token usage summary, and full-text search; also supports `--format jsonl` (newline-delimited JSON for programmatic analysis) and `--format markdown` (lightweight text format); CLI restructured with subcommands (`run`, `export-transcript`) while preserving backwards compatibility
- **Security event logging guidance (SEC0045)** — the agent now assesses workload security surface during design (authentication, credential management, access control, data audit) and guides BUILD subagents to generate a `src/log_security.py` helper emitting structured OWASP-format events (JSON with datetime, appid, type, event, level, description); system prompt, observability skill, and subagent guidance all include SEC0045-aligned event types, emission points, and the critical rule against logging sensitive data; design proposals include `security_surface` and `security_event_types` fields; Loki LogQL query examples for filtering security events added to skill documentation
- **Tracing instrumentation guidance** — system prompt and observability skill now include clear rules on what ops-tracing instruments automatically (hooks, Pebble, relations, status, secrets) versus what requires manual OpenTelemetry spans (long-running operations, external API calls, fallback decision logic, deferred event processing); includes code examples using `trace.get_tracer()` / `start_as_current_span()`
- **Commit-after-build** — BUILD and DEBUG subagents are now instructed to `git_add` + `git_commit` their changes before finishing; `git_add` and `git_commit` added to the DEBUG tool allowlist; the executor logs a warning if uncommitted changes remain after a BUILD/DEBUG task completes
- **Build self-verification** — `charm_validate` and `run_charm_tests` added to the BUILD tool allowlist; BUILD guidance instructs subagents to validate before finishing and attempt one fix if validation fails
- **Session resume** — `build_resume_summary()` injects prior session context (charm info, decisions, task progress) into the conversation on restart; stale ACTIVE tasks from crashed sessions are automatically reset to PENDING
- **Git-revert-on-failure** — the executor snapshots `git HEAD` before BUILD/DEBUG tasks; on failure, captures `git diff` as diagnostics and runs `git checkout .` to restore the working tree to a known-good state
- **Pre-task environment checks** — DEPLOY tasks fail fast if no dev model or charm path is set (auto-queuing an INFRA fix task); TEST tasks fail fast if no packed `.charm` file exists
- **Terraform module generation (CC008)** — `generate_terraform` tool deterministically produces a standard four-file Terraform module (`main.tf`, `variables.tf`, `outputs.tf`, `terraform.tf`) from `charmcraft.yaml` following the CC008 specification; uses `model_uuid` (not `model`), `application` output (full object), `null` defaults for `base`/`constraints`, alphabetical variable and output ordering; `validate_terraform` tool runs `terraform fmt --check` and `terraform validate` (gracefully skips if CLI absent); `terraform` skill with full workflow guidance; system prompt suggests Terraform after successful build+deploy
- **Inference snap robustness** — context window auto-detection from `/models` metadata (`n_ctx_train`, `context_length`, `max_model_len`); connection health checks with actionable error messages when a snap server is unreachable; graceful degradation for models that don't support tool calling (tools omitted from requests based on capabilities metadata); `list_inference_snaps` agent tool for discovering installed snaps and their status
- **Multi-snap routing** — `--light-snap` flag routes research and infrastructure tasks to a lighter inference snap while the primary snap handles code writing
- **Hybrid mode** — `--light-provider` flag enables cross-provider task routing (e.g. `--provider claude --light-provider inference-snap --light-snap gemma3`), combining cloud model quality for code generation with local model cost savings for research tasks
- **Task checklist category grouping** — tasks in the TUI checklist are now grouped under category headers (Research, Build, Deploy, Test, Debug, Infrastructure, Confirm) instead of a flat list; empty categories are omitted
- **Local inference snap provider** — new `--provider inference-snap` option runs Cantrip on local models served by Canonical's [inference snaps](https://documentation.ubuntu.com/inference-snaps/); supports chat completions, streaming, and tool calling via the OpenAI-compatible API with no API key required; use `--snap gemma3` (default) to select which installed snap to use; auto-discovers the snap's endpoint URL and model name
- **Parallel subagent execution** — the background executor now runs independent tasks concurrently (up to a configurable limit, default 3) using a semaphore-bounded async pattern; `WorkQueue.all_ready()` returns all tasks whose dependencies are met; `--concurrency` CLI flag controls the cap
- **Subagent efficiency prompts** — all subagent categories now include batch-tool-call guidance, prescriptive step sequences, and early-termination encouragement; max subagent rounds reduced from 12 to 8 to discourage sprawling exploration
- **Deterministic research planning** — the initial `plan_tasks` call for "build a charm for X" no longer requires an LLM round-trip; `plan_research_phase()` generates the standard research → synthesis → confirm task sequence from templates, skipping source-analysis when no source URL is given; LLM planning is reserved for replanning and build-phase task generation
- **Integration graph (F8)** — modal screen showing a visual graph of deployed applications with status-coloured panels, per-unit breakdowns, and a deduplicated relation section; highlights the user's charm with a star marker; accessible via the F8 keybinding
- **Per-provider rate awareness** — shared `ProviderThrottle` coordinates rate-limit back-off across concurrent subagents; when one subagent hits a rate limit, it signals the throttle so other subagents using the same provider wait before retrying, preventing thundering-herd retries
- **One-shot build mode** — for known 12-factor frameworks (Flask, Django, FastAPI, Go, Express, Spring Boot), `plan_one_shot_build()` generates a single BUILD task that scaffolds, writes charm code, writes tests, and packs in one subagent pass instead of 3–5 separate tasks; activated automatically after design confirmation when no user overrides are present
- **Per-task model routing override** — `ModelHint` enum (`primary` / `light`) on `AgentTask` lets the planner or user override category-based model selection; `_select_provider()` checks the hint first; persisted via SQLite schema v3 migration
- **Fast path for 12-factor charms** — when the framework is a known 12-factor type (Flask, Django, FastAPI, Go, Express, Spring Boot) and no source URL needs analysis, `plan_fast_path()` produces just 2 tasks (design + confirm) instead of the full 4-5 task research pipeline, cutting the pre-build phase significantly
- **Interactive design questions** — when the synthesis task produces design questions, the TUI now presents them one at a time in a modal screen with suggested answer buttons and a free-form input option; answers are collected and fed back as overrides for design confirmation, replacing the previous wall-of-markdown approach
- **Charmhub publishing tools** — `charmcraft_upload` uploads a `.charm` file to Charmhub (parses revision number, requires user confirmation), `charmcraft_release` releases a revision to a channel with optional resource attachments (requires user confirmation), `generate_readme` reads `charmcraft.yaml`, `WORKLOAD.md`, and `DESIGN.md` to produce a structured README with usage, configuration, actions, and integrations sections
- **Log viewer (F3)** — modal screen showing `juju debug-log` output with log-level filtering (cycle through WARNING/INFO/DEBUG/ERROR with `l` key) and manual refresh (`r` key); fetches the most recent 200 lines from the development model
- **Trace viewer (F4)** — modal screen showing COS endpoint URLs, Grafana links, and port-forwarding instructions for accessing observability dashboards
- **Multi-model status** — the TUI right panel now uses `MultiModelStatusWidget`, showing dev and COS model status side-by-side; watcher events feed the latest Juju status into the widget for real-time updates
- **Performance skill** — identifies common charm performance pitfalls (blocking I/O in hooks, expensive status polling, oversized relation data, unoptimised Pebble interactions), provides Tempo-based profiling guidance, hook execution benchmarks, and caching best practices
- **Publishing skill** — step-by-step Charmhub upload and release workflow, channel promotion strategy (edge → beta → candidate → stable), resource handling for OCI images, and versioning best practices
- **Publishing workflow in system prompt** — the system prompt now includes a "Publishing to Charmhub" section guiding the agent through validate → README → pack → upload → release with user confirmation at each stage
- **Research-driven charm design** — the task planner now generates a research-first task sequence (source-analysis, web-research, charmhub-survey → operational-discovery → confirm-design); research subagents receive structured guidance with cite-sources requirements, `[UNKNOWN]` gap markers, and operational story questions (storage, clustering, health, config, failure modes, integrations, observability, scaling, backup); operational-discovery tasks route to the primary model for quality since their output is user-facing; research subagents can now write WORKLOAD.md via the `write_file` tool
- **Design proposals** — `DesignProposal` dataclass captures structured fields parsed from synthesis results (substrate, charm path, Charmhub recommendation, integrations, config options, actions, scaling, operational patterns, questions); `format_for_chat()` renders proposals as Markdown for user review; `parse_design_from_result()` extracts structure from heading-based Markdown
- **Design confirmation flow** — after the user approves a design, `handle_design_confirmation()` records key decisions, stores the proposal on agent state, and generates build/deploy/test tasks via `plan_from_design()`; the `manage_tasks` tool gains an `approve` action for unblocking CONFIRM tasks; design content is passed through the executor into subagent contexts so build subagents know what was approved
- **User steering** — `manage_tasks` tool lets the conversation LLM list, cancel, reprioritise, and inspect tasks on behalf of the user; the background executor pauses automatically while handling user messages and resumes after, ensuring steering takes priority over autonomous work
- **Expandable task detail** — clicking a task row in the TUI checklist toggles a detail panel showing result summary, category, status, description, and blocked reason; collapsed by default to keep the list compact
- **Auto-deploy after build** — successful BUILD tasks automatically queue a DEPLOY follow-up, closing the build → deploy → verify → diagnose feedback loop; the full autonomous chain is now: build → deploy → verify → (on failure) diagnose
- **Queue reprioritisation** — `WorkQueue.move_to_front()` lets pending tasks be moved to the head of the queue so the executor picks them up next
- **Auto-deploy loop** — closes the autonomous feedback loop: successful DEPLOY tasks automatically queue a verification task (juju_status + juju_wait); failed verifications queue a COS-driven diagnostic task (juju_debug_log, loki_query, tempo_query); watcher events (hook failures, status changes, topology changes) now create tasks in the work queue instead of being injected as chat messages, letting the executor prioritise and batch them; deploy subagents gain access to fast-path tools (charm_sync, juju_dispatch); the TUI no longer polls for watcher events — the agent routes them automatically
- **Task checklist widget** — `TaskChecklistWidget` displays the work queue as a live checklist in the TUI right panel; uses thread-safe dirty-flag polling (0.5 s timer) so the executor callback can notify from any thread; status indicators (`○` pending, `⟳` active, `✓` done, `✗` failed, `◌` blocked) with per-status colour classes; posts `TasksAvailable` to reveal the right panel on first task; titles truncated at 40 characters for narrow panels
- **Executor wiring** — `CantripAgent` gains `start_executor()` / `stop_executor()` lifecycle methods mirroring the watcher pattern; the TUI starts the executor on mount and stops it on quit; `load_state()` now restores persisted tasks into the work queue so tasks survive restarts; the executor's task-change callback feeds the checklist widget for real-time updates
- **Background executor** — `BackgroundExecutor` orchestrates autonomous task execution: polls the work queue for ready tasks, runs each in an isolated `Subagent` context with timeout enforcement (10 min), records results/failures back on the queue, persists state via `SessionStore`, and routes CONFIRM tasks to the conversation loop; runs concurrently with the conversation loop as a background `asyncio.Task`; fires callbacks on task completion/failure for TUI coordination
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
