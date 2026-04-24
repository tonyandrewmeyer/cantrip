# Changelog

All notable changes to Cantrip are documented here. This project is pre-1.0; only significant features and changes are recorded.

## Unreleased

### Added
- **Policy stack wired into the subagent dispatcher (Phase 80.2).**
  ``Subagent.__init__`` now composes a ``PolicyEnforcer`` per run
  (org-wide + per-category + discovered YAML policies) and filters
  the LLM-visible tool list through it.  ``_tool_or_veto`` gains a
  call-time ``check_tool`` gate that fires **before** the
  PRE_TOOL_CALL hook: a policy ``DENY`` short-circuits to a
  synthetic ``ToolResult(success=False, error=<reason>)`` naming the
  composed stack, so a tool that became blocked mid-run (rate
  limit, per-charm overlay, hallucinated name) cannot reach the
  subprocess or juju code paths.  ``REVIEW`` degrades to ``DENY``
  with a log line until Phase 68.2's declarative approval prompts
  land.  POST_TOOL_CALL payloads gain ``policy_denied_by`` so Phase
  80.4's JSONL audit can trace each decision to the policy layer
  that caused it.  MCP tools (prefix ``mcp__``) bypass the stack
  entirely, preserving the per-server ``allowed_tools`` gate from
  Phase 45.2.  The old ``_filter_tools`` name survives as a thin
  shim over the new path for the small number of callers that
  don't construct a full ``SubagentContext``.

- **Stacked tool-access policy primitives (Phase 80.1).**  New
  ``src/cantrip/agent/policy.py`` ships a frozen
  ``GovernancePolicy`` dataclass (allow / block / require-review /
  rate-limit) and ``compose_policies(*policies)`` with
  most-restrictive-wins semantics: non-empty allow-lists intersect,
  block / review unions, rate limit picks the lowest non-``None``
  value.  ``check_tool(name)`` returns an ``ALLOW`` / ``DENY`` /
  ``REVIEW`` verdict with block > review > allow precedence.  A
  strict YAML loader discovers ``~/.config/cantrip/policies/*.yaml``
  and ``<charm>/cantrip.policies.yaml`` in sorted order and skips
  malformed files with a warning so one typo can't lock the
  operator out.  Two built-in policies ship: ``ORG_WIDE_POLICY``
  (review gate on ``juju_destroy_model`` / ``juju_destroy_controller``
  / ``juju_remove_*`` / ``run_command`` / ``git_push``) and
  ``SPRINT_POLICY`` (200-call rate limit for unattended runs).  The
  primitives are the foundation for Phase 80.2 (dispatcher wiring),
  80.3 (per-goal rate limit), 80.4 (JSONL audit trail), and 80.5
  (Juju-aware destructive-command gate) — none of which ship in this
  commit; the policy layer is not yet enforced by the subagent.

- **Web UI cache-hit indicator at parity with the TUI (Phase 78.2 —
  closes M78).**  New ``CACHE_METRICS_UPDATED`` event on the shared UI
  bus, published from ``CantripAgent._record_usage`` whenever the
  provider reports ``cache_*_input_tokens`` fields.  Payload carries
  running totals plus a pre-computed ``hit_pct`` so every consumer
  renders the same number.  Web header gains ``#cache-indicator`` — a
  muted badge that shows ``cache: NN% hit`` matching the TUI modelbar's
  wording, with ``title``/``aria-label``/``aria-live`` hooks so
  assistive tech announces the change.  The TUI modelbar subscribes
  to the same event via ``_on_bus_cache_metrics`` so its readout moves
  in lockstep with the Web badge rather than relying on the 5-second
  polling timer alone.  Providers without cache fields (Gemini today)
  never emit the event, so those UIs stay quiet and the badge stays
  hidden.

- **Compaction stop-flags survive session resume + one-shot guard +
  visible progress events (Phase 78.3).**  Previously the boolean
  ``_cycle_detected`` / ``_budget_exhausted`` latches inside
  ``ContextManager`` reset to ``False`` on every session resume, so a
  session that had already decided to stop compacting could silently
  re-arm the next run and re-enter an ineffective compaction loop.
  Schema v11 adds ``cycle_detected`` and ``budget_exhausted`` columns
  to ``session``; ``save_compaction_counters`` /
  ``load_compaction_counters`` carry them alongside the existing
  counters, and ``CantripAgent`` round-trips both flags across
  ``_persist_compaction_state`` and the resume path.  A new unit test
  asserts the one-shot semantic — after ``compact()`` runs,
  ``should_compact()`` returns False on the compacted output.  The
  UI event bus gains ``COMPACTION_STARTED`` / ``COMPACTION_COMPLETED``
  (fired from the new ``CantripAgent._run_compaction`` helper, which
  replaces the duplicated compact-with-fallback block in both the
  synchronous and streaming conversation loops) so chat panes can
  show an inline indicator while the summary turn runs — today
  users see a multi-second pause with no explanation.  The completed
  event carries ``kind=compact|emergency`` so listeners can word the
  two paths differently.

- **Prompt-cache cascade detector (Phase 78.1).**  New
  ``cantrip.agent.cache_monitor.CacheCascadeDetector`` watches the
  per-turn ``cache_creation_input_tokens`` / ``cache_read_input_tokens``
  deltas provided by caching providers (currently Claude) and fires a
  one-shot warning when three consecutive creation-only turns follow a
  session that had previously been reading from the cache — the exact
  symptom of the April 23 Claude Code incident.  The warning surfaces
  three ways: a WARNING log on ``cantrip.agent.core``, a SYSTEM
  conversation message in the transcript, and a ``CHAT_MESSAGE`` UI
  event so the TUI and Web chat show it in-band rather than leaving
  users to spot it in passive model-bar metrics.  Fresh sessions
  (never-read baseline) and tool-only turns (no cache activity in the
  usage dict) don't trip the detector, so routine prompt iteration is
  quiet.

- **`thinking_budget` wire-shape regression guard (Phase 78.4).**
  New ``tests/unit/test_claude.py::TestClaudeProviderThinkingBudgetWire``
  and three fixtures in
  ``tests/unit/test_gemini.py::TestGemini3ThinkingConfig`` pin the
  extended-thinking payload on the wire: Claude's
  ``messages.create`` / ``messages.stream`` kwargs must carry
  ``thinking={"type": "enabled", "budget_tokens": <N>}``,
  ``temperature=1``, and a ``max_tokens`` floor of
  ``budget + 4096`` when a non-None budget is passed; Gemini's
  ``generate_content`` / ``generate_content_stream`` config must
  carry ``ThinkingConfig(thinking_budget=<N>, include_thoughts=True)``
  in the same scenario; both providers must omit the field when no
  budget is requested.  Closes the gap identified in Anthropic's
  April 23 postmortem retrospective — a silently-dropped field can
  no longer cascade undetected.

- **Rich captions on file-system, git, and charm-tooling tools
  (Phase 75.6 — closes M75).**  ``ToolResult.caption`` now ships
  count / size / destination shaped one-liners for ``read_file`` /
  ``write_file`` / ``edit_file`` / ``list_directory`` / ``grep`` /
  ``glob`` / ``git_clone`` / ``git_commit`` / ``git_push`` /
  ``charmcraft_pack`` / ``charmcraft_fetch_libs`` / ``charm_validate``.
  The TUI/Web inline tool block displays the rich caption in
  preference to the formulaic ``tool_name(path=…)`` fallback, so
  ``Edited charm.py (1 replacement)`` reads naturally instead of
  ``edit_file(path="charm.py")``.  Shell / juju / acceptance tools
  still rely on the fallback and can be filled in as drive-bys —
  the framework remains additive.

- **`extract_troubleshooting` mines error→fix pairs from the session
  transcript (Phase 74.4).**  New tool that walks ``messages`` +
  ``subagent_messages`` chronologically, finds tool results with
  ``is_error: true``, classifies each via a regex on stderr keywords
  (``image`` / ``observability`` / ``secret`` / ``relation`` / ``hook``
  / ``network`` / ``storage`` / ``general``), and pairs each error
  with the agent's next text reply (the diagnosis) and the next
  successful tool call within five turns (the resolution).  Trivial
  errors (general category + fewer than five lines) are filtered;
  category-matched errors are kept regardless of length.  Output
  lands in ``docs/how-to/troubleshooting.md`` grouped by category
  with ``### N. <symptom>`` blocks carrying **Symptom** /
  **Cause** / **Resolution** / **See also** fields.  Charm-author
  intros above the ``<!-- cantrip-generated below -->`` marker are
  preserved across re-runs; a marker-less existing page is treated
  as fully user-authored and gets the marker appended.  The tool
  also amends ``docs/how-to/index.md`` to include ``troubleshooting``
  in the toctree when a how-to index exists.

- **`extract_design_decisions` builds an architecture log from the
  session transcript (Phase 74.3).**  New tool that opens the
  ``.cantrip`` SQLite store, reads the ``decisions`` table the agent
  already populates during the design phase (substrate, charm path,
  Charmhub recommendations), and renders them as a chronological
  ``## Design decisions`` section in
  ``docs/explanation/architecture.md``.  Each decision becomes a
  numbered ``### N. <Type>: <Choice>`` block with Decision / Recorded
  / Citation / Rationale fields.  Charm-author intros are preserved:
  ``docs/explanation/_intro.md`` wins outright; an existing
  ``architecture.md`` keeps everything above the
  ``<!-- cantrip-decisions-start -->`` marker; a hand-authored
  ``architecture.md`` without the marker is preserved verbatim and
  the marker is appended.  Re-runs only refresh the section below the
  marker.  Empty decisions tables still produce a well-formed page
  with a placeholder explaining the section will fill in.

- **`generate_docs` populates tutorial / how-to from acceptance artefacts
  (Phase 74.2).** When the agent has captured a Phase-13 demo bundle
  (``demo/juju-status.txt`` + ``demo/actions/*.json``) or written a
  ``ACCEPTANCE.md`` summary, ``generate_docs`` now overrides the
  metadata-derived stubs at ``docs/tutorial/getting-started.md``,
  ``docs/how-to/deploy-and-verify.md``, and ``docs/how-to/actions.md``
  with real captured commands and output — the tutorial reads as a
  reproducible walkthrough rather than a templated placeholder.
  Captured output is sanitised on read: IPv4 addresses become
  ``<unit-ip>``, UUIDs become ``<model-uuid>``, ``*.svc.cluster.local``
  hostnames become ``<svc-fqdn>``, and ``sha256:…`` digests become
  ``<image-sha256>``.  When acceptance hasn't run, each affected page
  carries a one-line HTML comment noting that the content is templated
  until tests run.  Bridged root files (Phase 74.1) still take
  precedence over artefact-derived content.

- **`generate_docs` bridges root TUTORIAL.md / DEMO.md / architecture.md
  into the Diátaxis tree (Phase 74.1).** The Phase-13 root files now
  become ``docs/tutorial/getting-started.md`` /
  ``docs/how-to/deploy-and-verify.md`` /
  ``docs/explanation/architecture.md`` instead of co-existing with —
  and contradicting — the metadata-derived stubs.  Top-level headings
  are rewritten so the Sphinx ``toctree`` still resolves; intra-charm
  Markdown links are rewritten to climb out of ``docs/<dir>/`` (so
  ``[WORKLOAD.md](WORKLOAD.md)`` becomes ``[WORKLOAD.md](../../WORKLOAD.md)``)
  and cross-references between bridged files become ``../<other>``
  links.  Each bridged root file is replaced with a one-line stub
  pointing into the docs/ tree so existing in-repo links don't 404,
  and re-runs detect the stub so the pointer isn't bridged back over
  the page it pointed to.  ``GenerateReadmeTool`` now prefers the
  bridged docs/ paths in its Architecture / Demo links, with the
  legacy root-file links kept as a fallback for charms that haven't
  run ``generate_docs`` yet.

- **Share a session as a secret gist via ``/share`` (Phase 67.4).**
  New slash command that exports the live session as an HTML
  transcript and uploads it via ``gh gist create``, returning the
  gist URL.  Runs as a background coroutine so the UI stays
  responsive.  When ``gh`` is missing or unauthenticated the
  transcript still lands on disk and the command prints a
  copy-pasteable ``gh gist create ...`` the user can run manually
  — the session is never blocked by a missing dependency.

- **Mid-session model switching via ``/model`` (Phase 67.2).** New
  slash command: ``/model`` prints the active provider + model (plus
  the light provider when configured); ``/model <provider>`` swaps to
  that provider's default model; ``/model <provider>/<model>`` swaps
  to a specific model (splitting on the first ``/`` only so Fireworks
  slugs like ``fireworks/accounts/fireworks/models/kimi-k2p6`` work).
  Atomic swap: ``CantripAgent.switch_model`` rebuilds the light
  provider with same-family routing, updates the context-window
  budget, invalidates caches that captured the old provider, and
  emits a ``model_switched`` event for listeners.  Cost accumulators
  survive the swap (they're session totals, not per-provider).
  Any cross-provider hybrid configured at startup is dropped in
  favour of same-family routing — restart the session to preserve a
  specific hybrid.

- **Reasoning / chain-of-thought surfaces in the TUI and Web (Phase 77).**
  OpenAI-compatible providers (Fireworks, OpenRouter, inference-snap,
  generic) now capture ``reasoning_content`` — the streaming delta
  Kimi K2 and DeepSeek-R1-family models emit alongside the final
  answer — and route it through the same
  ``Response.metadata["_thinking_content"]`` key Claude's extended
  thinking uses.  The TUI renders reasoning as a dim italic
  ``💭 thinking`` preamble above the answer; the Web renders it as
  a collapsible ``<details>`` block.  ``OpenAICompatBase`` also
  honours ``thinking_budget`` by raising ``max_tokens`` to at least
  ``thinking_budget + 4096`` so reasoning doesn't starve the reply
  on providers that spend both from one budget.  Closes the
  Fireworks smoke-test gotcha where ``max_tokens=30`` returned
  empty content while all 30 tokens went to dropped reasoning
  frames.

### Fixed
- **``FireworksProvider.complete()`` auto-streams past the 4 096-token
  non-streaming cap.**  Fireworks rejects non-streaming requests
  with ``max_tokens > 4096`` (``"Requests with max_tokens > 4096
  must have stream=true"``), which the Phase 77
  ``thinking_budget + 4096`` bump would trip the moment a caller
  signalled reasoning headroom.  ``complete()`` now delegates to
  ``stream()`` internally in that case and reassembles a
  ``Response`` from the chunks, keeping the non-streaming API
  usable for reasoning-capable models.

### Changed
- **Update-notice upgrade command uses ``uv pip`` for pip-installed
  Cantrip.**  ``upgrade_command`` previously emitted
  ``pip install --upgrade cantrip`` (and the ``--user`` variant) for
  the ``PIP_VENV`` / ``PIP_USER`` install methods.  The project's
  stance is uv-everywhere, so both strings now lead with ``uv pip``
  — the command still targets the same venv or ``--user`` site-
  packages as plain pip, so the upgrade lands in the right place
  regardless of which tool originally installed Cantrip.
  ``uv tool upgrade cantrip``, ``pipx upgrade cantrip`` and
  ``snap refresh cantrip`` are unchanged.  Docs
  (``docs/src/reference-cli.md`` + regenerated
  ``docs/docs/reference-cli.html``) and the parametrised test in
  ``tests/unit/test_update.py`` tracked the rename.

### Fixed
- **Parliament report renders as Markdown in the TUI.**  The
  ``/feelings`` command posts a Markdown document (headings, bold,
  italic) that was previously shown verbatim — users saw literal
  ``#``/``**`` characters in the chat pane.  ``ChatMessage`` gained a
  ``markdown`` flag; ``ChatWidget.add_system_message`` accepts a
  matching ``markdown=`` kwarg; ``MessageWidget._render_body`` returns
  a ``rich.console.Group`` containing the header line and a
  ``rich.markdown.Markdown`` body when the flag is set.  Search
  highlighting is skipped for Markdown messages because substituting
  Rich tags into Markdown source mangles the formatting — acceptable
  since the only current opt-in is the parliament report.  The
  ``_on_feelings_done`` handler in ``TUIApp`` is the sole call site
  flipping the flag on, so no other system messages change behaviour.

### Added
- **OpenRouter.ai provider.**  New ``--provider openrouter`` choice
  routes through OpenRouter's meta-API
  (``https://openrouter.ai/api/v1``), letting Cantrip reach OpenAI
  GPT, Anthropic Claude, Meta Llama, Mistral, Grok, DeepSeek and
  several hundred other models behind one ``OPENROUTER_API_KEY``.
  Default model ``openai/gpt-4o`` was chosen specifically because
  it sits outside the coverage of Cantrip's existing native
  providers — Anthropic/Google/Fireworks/inference-snap already
  cover their own lineups directly, so the default should extend
  rather than duplicate.  Cantrip probes OpenRouter's richer
  ``/models`` schema at init (``context_length`` at top level,
  ``architecture.input_modalities`` for vision, ``supported_
  parameters`` for tool use) and sends ``HTTP-Referer`` +
  ``X-Title`` headers so Cantrip appears on OpenRouter's public
  model-ranking dashboards.  ``--light-provider openrouter``
  works as a hybrid option.  New ``howto-provider.md`` section
  lands between Fireworks and the generic escape hatch, with
  guidance to prefer a dedicated provider when one exists — a
  routing hop and a small markup sit on top of whatever upstream
  serves the model.  Live smoke-tested against ``openai/gpt-4o``
  for both ``complete()`` and ``stream()`` paths.
- **Fireworks.ai and generic OpenAI-compatible providers.**  Two
  new ``--provider`` choices: ``fireworks`` (baked-in
  ``https://api.fireworks.ai/inference/v1`` base URL, reads
  ``FIREWORKS_API_KEY``, default model
  ``accounts/fireworks/models/kimi-k2p6`` — a 256k-context
  agentic Kimi K2 variant with native tool use and vision) and
  ``openai-compatible`` (escape hatch for Together, Groq,
  DeepInfra, vLLM, LiteLLM proxies, etc. — requires
  ``--base-url``, ``--model``, and ``OPENAI_COMPATIBLE_API_KEY``).
  Canonical's ``inference-snap`` remains the first-class local
  provider — ``fireworks`` and ``openai-compatible`` are
  additions, not replacements.  Under the hood, the OpenAI
  chat-completions wire format and SSE streaming logic moved out
  of ``inference_snap.py`` into a new
  ``cantrip.llm._openai_compat.OpenAICompatBase`` that all three
  providers extend; the inference-snap keeps its snap-discovery
  + ``/models`` probing.  New ``--base-url`` CLI flag overrides
  the default endpoint for any of the three OpenAI-compatible
  providers.  ``--light-provider`` gained ``fireworks`` as a
  hybrid option.  Env-var validation in ``main._run`` surfaces
  actionable errors when a key or flag is missing.  New unit
  tests cover the shared wire format plus factory wiring for
  both new providers.  Docs updated:
  ``docs/src/howto-provider.md`` (inference-snap still listed
  first) and ``docs/src/reference-cli.md`` (new provider names,
  ``--base-url`` flag, new env vars).  Known limitation: Kimi K2
  emits a ``reasoning_content`` delta stream that is currently
  dropped — it burns completion tokens without surfacing in the
  transcript, so set generous ``max_tokens`` when evaluating.
- **Inline tool blocks in the chat — Phase 75.**  Every tool
  invocation now renders as a compact one-line block in the TUI
  and Web chat so the agent's "Let me check the file:" preambles
  stop reading as broken speech — the colon is followed by a
  visible ``🔧 read_file(path=src/foo.py)`` block, then the
  agent's next narrative message.  ``ToolResult`` gained a
  ``caption: str | None`` field tools can populate with a rich
  one-line summary (``"Read 47 lines from src/foo.py"``); tools
  that leave it ``None`` get a formulaic
  ``tool_name(preferred_key=value)`` fallback from
  ``build_tool_caption`` (using a preferred-key list of ``path``
  / ``file_path`` / ``command`` / ``cmd`` / ``url`` / ``query``
  / ``skill_name`` / ``name`` / … ).  Values are truncated to
  60 chars and newlines are collapsed so the block stays on one
  line.  New ``TOOL_INVOKED`` UI event carries
  ``{tool_name, caption, success, duration_ms, source}``; fired
  from all three tool-call boundaries (main-agent sync loop,
  main-agent streaming loop, subagent ``asyncio.gather`` path)
  with the correct ``source`` tag (``main`` / ``main-stream``
  / ``subagent``).  TUI gets a new ``MessageRole.TOOL`` and
  ``ChatWidget.add_tool_block`` renderer; failure recolours the
  left border to error-red and swaps ``🔧`` for ``✗``; duration
  appears parenthesised only when it exceeds the 500 ms
  attention threshold so fast calls don't clutter the chat.
  Web gets a matching ``appendToolBlock`` renderer in
  ``cantrip.js`` with CSS in ``style.css`` — the existing
  wildcard bus forwarder already serves the event to the
  front-end, no new WebSocket message type needed.  Subagent
  wiring: ``Subagent`` accepts an ``on_tool_invoked`` callback;
  ``BackgroundExecutor`` forwards it from the agent layer so
  subagent tool calls surface in the chat with the same visual
  treatment as main-agent calls.  30 new tests: caption
  fallback (13 cases covering path / command / url /
  non-preferred-first / empty / None / long-truncate /
  newline-collapse / preferred-key-win / quote-normalise),
  ``TOOL_INVOKED`` event shape (4 cases), agent-level emission
  (3 cases — success / failure / caption-override), and TUI
  ``add_tool_block`` widget rendering (4 cases — success /
  failure / slow-call duration / fast-call duration hidden).
  Phase 76 filed as a follow-up to investigate Toad-style
  per-block copy affordances once the blocks have settled.

- **Policy-composition investigation + Phase 80 filed — Phase 55.4.**
  Closes Phase 55 entirely.  Read the 569-line awesome-copilot
  ``agent-governance`` skill (six patterns: ``GovernancePolicy``
  + ``compose_policies()``, intent classification, ``@govern``
  decorator, trust scoring, audit trail, framework integration)
  and mapped Cantrip's current single-level
  ``_filter_tools(tools, category)`` gating surface against
  them.

  **Keep / defer / reject per primitive:**
  - ``GovernancePolicy`` + ``compose_policies`` → **keep** (global
    + per-category + per-charm layers with most-restrictive-wins)
  - Per-goal ``max_calls_per_request`` rate limit → **keep**
    (pairs with 55.3's goal budget)
  - JSONL audit trail → **keep** (streaming export alongside
    the SQLite ``events`` table)
  - Juju-aware destructive-command gate → **keep** (fills the
    real gap: user hooks and the sandbox can't catch a subagent
    autonomously calling ``tools/juju.py::JujuDestroyModelTool``)
  - Intent classification → **defer** (charm-building signal is
    tool surface, not prompt content)
  - Trust scoring with temporal decay → **reject** (no
    mutually-untrusted delegation in Cantrip)

  Filed as **Phase 80: Stacked Tool-Access Policies** in the
  roadmap with five subphases for the kept primitives.  M80
  milestone row added to the table.  (Phases 57, 77, 78, 79
  were all already taken — Phase 57 by the archived
  "Test-Suite Cleanup" phase, 77-79 by the Reasoning Content
  Surfaced and April 23 postmortem follow-ups — so the new
  proposal moved to the next free integer above that ceiling.)

  Full analysis in ``design/TOOLS.md`` § *Policy composition
  for tool access (Phase 55.4)* — includes the keep/defer/reject
  table, the three gaps a stacked-policy design closes, and the
  five-layer defence-in-depth nesting (global budget > task
  safe-outputs > policy allowlist > user hook > sandbox).  No
  code changes — investigation only.

- **Charm-design spec shape investigation — Phase 55.8.**  Read
  awesome-copilot's
  ``create-github-action-workflow-specification`` template (276
  lines — mermaid flow diagrams, requirements matrices with
  REQ-IDs, compliance sections, version history) and compared
  against Cantrip's existing ``DesignProposal`` surface in
  ``agent/design.py``.

  **Verdict: reject the template, lift two shape upgrades.**  The
  awesome-copilot shape is for *reverse-engineering existing
  workflows*; Cantrip's design proposal is a *proposal for a
  charm that doesn't exist yet*.  Requirements matrices +
  compliance + version history don't fit the confirmation-step
  use-case — they'd turn it into form-filling and duplicate
  source-of-truth artefacts that already live in git, SQLite,
  and the ``operational-readiness`` skill.  The existing
  ``DesignProposal`` (structured fields for substrate, charm
  path, integrations, companions, config, actions, scaling,
  operational patterns, security surface, sources) already
  covers the ground that matters for a charm, and the
  confirmation flow already threads the raw markdown into
  downstream build subagents.

  Two bits worth lifting as drive-by improvements to
  ``design.py::DesignProposal.format_for_chat()``:

  1. **Mermaid diagram of relation integrations** generated
     deterministically from the ``integrations`` +
     ``companions`` lists.  GitHub / mkdocs render it; other
     surfaces see readable text.
  2. **Table format for config options and actions** — a
     ``| name | type | purpose |`` table instead of bullet
     lists; matches how charm authors write
     ``config.yaml`` / ``actions.yaml`` themselves.

  Neither is scoped to a phase yet; file when revisiting the
  design-confirmation flow.  Full write-up in
  ``design/AGENT.md`` § *Design proposal as pre-build spec
  (Phase 55.8)*.  No code changes — investigation only.

- **Deterministic pre-scan stub — Phase 55.7.**  Read the
  upstream ``awesome-copilot`` ``scan.py`` (712 lines, MIT) and
  compared against Cantrip's ``AnalyseFrameworkTool``: upstream
  is breadth (60 manifests across 25+ languages, 10 CI/CD
  platforms, container / SBOM / lint / env-template / entry-point
  detection, git churn); ``analyse_framework`` is charm-specific
  depth (PaaS profile map, substrate suggestion,
  ROCKCRAFT_ENABLE_EXPERIMENTAL flagging).

  **Verdict: port, not vendor or subprocess.**  Vendor loses
  charm awareness (``charmcraft.yaml`` goes undetected) and
  depends on the Phase 55.1 loader changes that were deferred;
  subprocess loses the structured-dict output the Phase 52.3
  checkpoint envelope rewards.  A port to
  ``src/cantrip/agent/tools/_scan.py`` converges both scans
  onto one source of truth with Cantrip-specific additions
  (``charmcraft.yaml`` / ``rockcraft.yaml`` / ``metadata.yaml``
  / ``.cantrip`` detection; ``CHARM_MARKERS`` signalling
  "existing charm, route to improvement").

  Shipped a **stub** (not an implementation): the file ports
  the upstream data tables (``MANIFESTS``, ``ENTRY_CANDIDATES``,
  ``CI_CD_CONFIGS``, ``CONTAINER_FILES``, ``SECURITY_CONFIGS``,
  ``LINT_FILES``, ``ENV_TEMPLATES``, ``EXCLUDE_DIRS``),
  adds ``CHARM_MARKERS``, and defines a frozen ``ScanResult``
  dataclass with the output shape.  ``scan(path)`` returns an
  empty result with TODO markers for each detection pass.
  MIT attribution in the file header.

  Implementation (~400-500 lines + ~150 lines of tests) deferred
  to a follow-up phase when a real Path B (custom app) user
  demonstrates the round-trip cost.  Full write-up in
  ``design/TOOLS.md`` § *Deterministic pre-scan for Path B*.

- **Subagent-frontmatter investigation — Phase 55.2.**  Audited
  Cantrip's subagent metadata surface against the awesome-copilot
  ``.agent.md`` frontmatter spec (998 lines — a full authoring
  standard).  Cantrip keeps allowed tools, model routing, max
  rounds, timeouts, and temperature in four Python data
  structures plus one function; guidance bodies already live in
  ``prompts/subagent/*.md``.  Three decisions:

  1. **Frontmatter schema — propose, defer.**  A hybrid
     adoption (YAML frontmatter on ``prompts/subagent/<cat>.md``
     as source of truth, Python rebuilds the aggregated dicts at
     import time) is plausible but the payoff is small for six
     categories that change a couple of times a year.  Real
     costs: loss of cross-category comparison at a glance,
     executable-conditional routing in ``_select_provider``
     can't move into frontmatter, stringly-typed keys drop the
     ``TaskCategory`` / ``ModelHint`` enum safety.  Re-evaluate
     when categories grow past ~10 or Phase 53.5 absorbs the
     migration.  Shape sketch recorded in ``design/PROMPTS.md``.
  2. **Handoffs — reject.**  ``handoffs:`` is a VSCode-UI feature
     for interactive "next step" buttons.  Cantrip's
     ``AgentTask.dependencies: list[str]`` already drives
     automatic dispatch; the deterministic planner needs nothing
     more.  For user-facing "what's next" hints after a task
     completes, that's UI work (Phase 76 / 65), not prompt
     frontmatter.
  3. **Auto-approve sentinel — defer to Phase 68.2.**  Naming a
     mode without a behavioural difference is premature.  Phase
     68.2 already scopes declarative permission config (YAML
     ask/allow/deny per tool + source) and will introduce
     ``PermissionMode`` naturally.  Adding a single-value enum
     ahead of it is wasted motion.

  Full write-up in ``design/PROMPTS.md`` § *Frontmatter metadata
  on subagents (Phase 55.2) — proposed, deferred*.  No code
  changes — investigation only.

- **Markdown-workflow format investigation — Phase 55.5.**  Read
  three awesome-copilot workflow files
  (``ospo-release-compliance-checker.md``, ``daily-issues-report.md``,
  ``relevance-check.md``) and compared against Cantrip's
  ``plan_sprint_deploy`` as the closest Python-orchestration
  analogue.  **Verdict: reject the format for the deterministic
  planner.**  The awesome-copilot shape conflates dispatch with
  prompt body; Cantrip already separates them cleanly (Python for
  dispatch, Jinja2/markdown for bodies), and a markdown
  conversion would push dispatch into stringly-typed frontmatter
  while losing the typed ``AgentTask`` fields and value-computing
  Python (``_host_ubuntu_version()``, ``_FAST_PATH_FRAMEWORKS``
  membership, unique-id allocation, dependency chaining).

  Two micro-patterns worth lifting independently:
  1. **Explicit trigger guard as step 1 of every task template** —
     short-circuits misrouted tasks before they burn tokens.
     Filed as a drive-by improvement to apply when touching each
     template for other reasons.
  2. **``safe-outputs`` cap as a declarative per-task
     side-effect limit** — sketched as a new
     ``AgentTask.safe_outputs: dict[str, int] | None`` field the
     subagent checks inside its tool dispatcher; tripped cap →
     synthetic failure + UI event.  Composes cleanly with Phase
     55.3's goal-level budget and 55.4's tool-level
     ``max_calls_per_request`` — goal > task > tool, same
     circuit-breaker shape at three layers.  Sized at ~100 lines +
     event type + tests; pair with whichever of 55.3 / 55.4 lands
     first so the event bus gets one structured shape instead of
     three similar-but-different ones.

  Full write-up in ``design/PROMPTS.md`` § *Markdown-workflow
  format (Phase 55.5) — rejected, with micro-patterns lifted*.  No
  code changes — investigation only.

- **Runnable cookbook, first recipe shipped — Phase 55.6.**
  New ``cookbook/`` top-level directory with its own ``README.md``
  (index, recipe format, candidate list).  Each recipe is a
  self-contained directory with a walkthrough ``README.md``, a
  copy-paste ``prompts.md``, and a CLI-and-library ``verify.py``
  that asserts the result matches the shape the recipe teaches.
  Inspired by awesome-copilot's recipe cookbook, adapted for
  Cantrip's charm-focused surface.

  First recipe shipped: ``cookbook/build-a-sprint-charm/``.
  Sprint mode is deterministic, has a published shape contract
  in ``_SPRINT_GUIDANCE``, and can be verified without a live
  Juju model — the right scope for the first recipe.  Deviation:
  the roadmap suggested ``build-a-stateful-charm/`` as the first
  candidate; that recipe would have needed a Scenario test suite
  + COS wiring + a full Juju model, so we picked the simpler
  sprint variant and filed ``build-a-stateful-charm`` (plus four
  other recipes) as proposed follow-ups in ``cookbook/README.md``.

  CI coverage via ``tests/unit/test_cookbook_recipes.py`` (16
  tests).  **Structure drift** (every recipe must carry README +
  prompts + verify.py, verify.py must be valid Python) via a
  parametrised sweep over ``cookbook/*/``.  **Output drift**
  (verifier's happy path + every failure mode) exercised against
  handwritten in-process fixtures.  Live Cantrip runs stay out of
  CI — the cookbook is documentation plus a shape contract, not
  an end-to-end integration harness.

  ``CONTRIBUTING.md`` gained a *Cookbook recipes* section
  pointing at ``cookbook/README.md`` and explaining how the
  verifiers double as regression tests.

  Micro-improvement out of the 55.6 review: ``make coverage`` now
  emits ``cov_annotate/`` with annotated source files where
  uncovered lines are prefixed ``!``.  Subagents can grep for
  coverage gaps without parsing the HTML report.  One-line
  Makefile change + ``.gitignore`` update; ``htmlcov/`` /
  ``term-missing`` behaviour unchanged.

- **Ralph-loop comparison + per-goal budget sketch — Phase 55.3.**
  Read ``awesome-copilot``'s 79-line ``ralph_loop.py`` and diffed
  the pattern against Cantrip's two-loop architecture.  The
  overlap is enormous: Cantrip's subagent-per-task model *is*
  the ralph fresh-session-per-iteration pattern, scaled up with a
  work queue, typed dependencies, parallel subagents under a
  concurrency semaphore, and (since Phase 52) step-level
  checkpoint replay.  A full mapping table ships in
  ``design/AGENT.md`` § *Prior art — the ralph loop*.

  The **single primitive Cantrip is missing** is a hard
  **per-goal iteration + token budget with a circuit breaker**.
  Today the autonomous loop drains the work queue on its own
  schedule; a runaway planner could spawn arbitrary follow-up
  tasks without an aggregate cap.  Sketched the follow-up in
  ``design/AGENT.md`` § *Per-goal budget*: new
  ``AgentState.goal_budget`` carrying ``max_iterations`` /
  ``max_prompt_tokens`` / ``max_completion_tokens`` /
  ``started_at``; executor gate ``_budget_allows(task)`` before
  each spawn that queries ``SessionStore.get_usage_since`` against
  the caps; tripped task → ``BLOCKED`` with ``budget_exceeded`` +
  ``goal_budget_exceeded`` UI event; recovery via ``/budget``
  slash command, ``--max-iterations`` / ``--max-tokens`` CLI
  flags, and ``CANTRIP_MAX_*`` env vars.  Sized at ~150 lines of
  code + one event type + three tests.  Pairs with Phase 55.4's
  tool-level ``max_calls_per_request`` work.  Implementation
  deferred to a dedicated follow-up phase; investigation ends at
  "scoped and sized" per the 55.3 exit criterion.  No code
  changes.

- **Skill-as-folder-convention investigation — Phase 55.1.**
  Surveyed three representative awesome-copilot skills
  (``pytest-coverage``, ``agent-governance``,
  ``acquire-codebase-knowledge``) at revision 2026-04-24 and
  catalogued the folder shape — ``SKILL.md`` +
  ``assets/templates/`` + ``scripts/`` + ``references/``.  Mapped
  against Cantrip's 30 bundled skills (all single ``SKILL.md``
  files today; no templates or scripts).  Identified two loader
  gaps that would need to close before siblings become useful:
  ``LoadSkillTool`` surfaces only the body text, and the
  ``read_file`` tool is sandboxed away from the skills tree.
  **Recommendation — keep the existing shell, defer the plumbing.**
  The loader already tolerates siblings; the pattern pays off only
  when a skill ships an executable helper (Phase 55.7's scan.py
  port is the first real candidate) or a template larger than a
  snippet (Phase 55.6's cookbook may surface one).  File the
  loader work as a prerequisite of whichever lands first, not as
  its own phase.  Full write-up in ``design/SKILLS.md`` §
  *Skill-as-folder convention*.  No code changes — investigation
  only.

- **Replay-cost accounting — Phase 52.6.**  Closes Phase 52
  entirely.  Two pieces:

  - **Rate-limit budget tracker is already correct.**  This half
    of the roadmap was satisfied by the 52.3 wiring: checkpoint
    hits short-circuit ``_complete_with_retry`` entirely, so
    ``on_usage`` (the callback that feeds the budget tracker and
    the ``token_usage`` table) is never invoked on a hit — no
    double-counting, no separate code path.  Documented.

  - **"Cached from checkpoint" line in ``/cost``.**  The 52.5
    ``checkpoint_hit`` event now stamps ``prompt_tokens`` /
    ``completion_tokens`` onto the event detail when the cached
    row is a ``KIND_LLM_RESPONSE`` (tool hits contribute
    nothing).  New ``SessionStore.get_replay_savings()`` sums
    those fields across the event log and returns
    ``{prompt_tokens, completion_tokens, request_count}``.  Both
    ``format_cost`` (TUI / Web ``/cost``) and
    ``cli._print_cost`` (CLI ``/cost``) append a
    ``"Cached from checkpoint: X tokens (Y prompt, Z
    completion, N replayed turn(s))"`` line when savings are
    non-zero; the line is omitted on fresh sessions so existing
    output is unchanged by default.

  ``TranscriptData`` grew a ``replay_savings: dict[str, int]``
  field populated by ``load_transcript`` so downstream exporters
  (HTML / JSONL / markdown) can surface the saved-token figure.
  9 new tests: 3 event-stamping cases (llm hit stamps / tool
  hit doesn't / empty usage stays clean), 2 ``get_replay_savings``
  sums, 1 transcript-data population, 1 positive ``format_cost``
  case + assertions in existing totals tests that the line stays
  absent on zero savings, 1 ``_print_cost`` positive case.

- **Checkpoint observability and inspection — Phase 52.5.**  Closes
  out the core of Phase 52 (52.6 cost-accounting remains as a
  low-priority follow-up).  Three user-facing surfaces on top of
  52.3's subagent wiring:

  - **Transcript viewer (F9) gained a fourth view, ``checkpoints``,**
    cycled via ``v``.  Per task: title + id + step count, then one
    line per row showing ``<step>#<ordinal>  <kind>
    <input_hash[:12]>  <created_at>``.  Full hash + decoded blob
    come from the CLI below.  Absorbs the Phase 52.4 inspection
    bullet.
  - **``cantrip checkpoints {list,show,delete}`` CLI** with
    ``--db PATH`` (default ``./.cantrip``).  ``list [--task-id X]``
    prints a per-task table.  ``show <task_id> <step_name>
    <ordinal>`` pretty-prints the decoded blob as JSON (or base64
    for ``KIND_BYTES``).  ``delete --task-id X [--yes]`` purges a
    task's checkpoints, prompting interactively unless ``--yes``.
  - **Hit / miss / invalidated events** land in the session store's
    event log (``checkpoint_hit`` / ``checkpoint_miss`` /
    ``checkpoint_invalidated``) with
    ``{task_id, step_name, ordinal, kind}`` and — for
    invalidation — ``stored_hash`` / ``current_hash``.  Recorded
    inside :func:`checkpoint` via a new
    ``CheckpointStore.record_event`` forwarder so the transcript
    viewer and any future watcher dashboard can plot replay
    efficiency without extra plumbing.

  ``TranscriptData`` grew a ``checkpoints: dict[str, list[dict]]``
  field populated by ``load_transcript``; blobs are *not* included
  (they can be large) — each row carries the metadata fields only,
  keeping the transcript load cheap.  17 new tests: 3 event-emission
  cases in ``test_durability.py``, 1 transcript-data population
  test, 10 CLI handler tests in ``test_checkpoints_cli.py`` (list /
  show / delete with empty-state, filters, missing rows, ``--yes``,
  interactive y/n), and 3 TUI ``_checkpoint_lines`` renders.
  ``docs/src/reference-cli.md`` documents the new ``checkpoints``
  subcommand alongside the existing subcommand catalogue.

- **Subagent resume UX — Phase 52.4.**  Two user-facing pieces
  on top of the 52.3 replay wiring: a ``CANTRIP_NO_RESUME=1``
  opt-out that disables checkpoint lookup for a debugging session
  (fresh writes still land in the store so the next run without
  the var sees a clean cache), and a "resuming from step N"
  signal that fires when a store-backed subagent starts and
  finds pre-existing checkpoints for its task.  The signal lands
  in three places so it can't be missed: an INFO log line
  (``"Subagent resuming task 'Build redis' from step 4 (3
  checkpoint(s) cached)"``), the transient ``subagent_phase`` on
  the task (``"resuming from step N"`` — visible in the TUI task
  pane), and a ``subagent_resume`` event in the session store's
  event log with ``task_id`` / ``task_title`` / ``prior_steps``
  / ``next_step`` for the transcript.  ``N = count_for_task + 1``
  (the next step the subagent will attempt).  The
  ``should_skip_resume`` helper in ``durability.py`` mirrors
  ``should_keep_checkpoints`` — same truthy-value parser (``1``
  / ``true`` / ``yes`` / ``on``).  Deviation: the original 52.4
  also called for a ``cantrip session inspect`` / TUI F-key
  surface to inspect cached checkpoints; that path folds into
  52.5, which already scopes the transcript "checkpoints" tab
  plus a ``cantrip checkpoints {list,show,delete}`` CLI.
  Shipping a parallel surface in 52.4 would double-work.  5 new
  subagent tests covering the opt-out and the resume signal, plus
  3 dedicated env-var tests in ``test_durability.py``.

- **Subagent loop checkpoints every LLM turn and tool call — Phase
  52.3.**  The final wiring piece of Phase 52: the subagent loop
  now routes every ``_complete_with_retry`` call through
  ``checkpoint(ctx, "llm_turn", ...)`` and every ``_execute_tool``
  call through ``checkpoint(ctx, f"tool:{name}", ...)``.  A
  rate-limited BUILD subagent that dies on turn 18 now resumes on
  turn 18 — the first 17 LLM completions and every tool result
  between them are served from the ``step_checkpoints`` table
  without hitting the provider or running tools again.  New
  ``Subagent._llm_turn`` helper spans provider + model name + the
  canonicalised message prefix + the canonicalised tool-schema
  list as the input hash, so a conversation that diverges between
  runs (new prompt template, model change, new tool registered)
  invalidates the stale row via Phase 52.2's hash-mismatch path
  rather than silently serving it.  New
  ``Subagent._execute_tool_with_checkpoint`` helper uses
  ``compute_input_hash(name, arguments)`` as the per-tool hash;
  called from inside ``_tool_or_veto`` so the ``asyncio.gather``-
  based concurrent tool-call path is preserved — ordinal
  allocation happens synchronously at the start of each
  ``checkpoint()`` call, before any ``await``, so parallel tool
  calls line up with the tool-call ordering deterministically
  across runs.  Vetoed calls are *not* checkpointed (the synthetic
  error is free to rebuild on replay); successful and failed tool
  results both persist — a deterministic tool error doesn't
  re-burn on resume, matching the roadmap's "negative checkpoints"
  intent without a separate code path.  New
  ``response_to_dict`` / ``response_from_dict`` and
  ``tool_result_to_dict`` / ``tool_result_from_dict`` helpers in
  ``durability.py`` round-trip the concrete ``llm.Response`` and
  ``agent.tools.base.ToolResult`` dataclasses through the JSON
  envelope; image bytes are base64-encoded.  Subagents constructed
  without a ``SessionStore`` (unit tests, synthetic harnesses)
  stay on the pre-52.3 code path entirely — ``ctx`` is ``None``
  and the helpers short-circuit.  9 new tests in
  ``tests/unit/subagent/test_checkpoint.py`` assert first-run
  records the expected step rows; replay short-circuits
  provider and tool execution (asserted with an "exploding"
  provider + tool that raise if called); partial-prior-run
  resumes from the correct turn; two-different-tools-in-one-round
  land on distinct step names; same-tool-twice-in-one-round walks
  ordinals 1→2; model-name-change invalidates the first turn and
  re-runs; tool-failure persists as ``success=False`` and replays
  without re-calling; no-store baseline preserves pre-52.3
  behaviour.  Plus 7 new serialiser tests in
  ``test_durability.py``.

- **Step-level checkpoint replay wrapper — Phase 52.2.**  Second
  piece of Phase 52: the ``async def checkpoint(ctx, step_name,
  fn, *, input_hash=None, kind=KIND_VALUE) -> T`` helper in
  ``cantrip.agent.durability`` that 52.3 will wrap around each
  LLM turn and tool call in the subagent loop.  Semantics mirror
  Armin Ronacher's *Absurd* ``ctx.step``: allocate the next
  ordinal from ``CheckpointCtx``'s monotonic per-step counter,
  look up the persisted row, return the decoded value on hit,
  otherwise ``await fn()`` and persist before returning.  The
  new ``CheckpointCtx`` dataclass closes over ``store`` +
  ``task_id`` with a private per-step ``_counters`` dict so
  repeated calls to ``checkpoint(ctx, "llm_turn", …)`` auto-
  number ``llm_turn#1``, ``llm_turn#2``, … without the caller
  tracking indices; ``next_ordinal(step_name)`` exposes the
  increment for callers that need it directly.  On replay, a
  fresh ctx starts at counter=0 and walks the same deterministic
  sequence of calls the original run produced, so the
  ``(step_name, ordinal)`` lookups line up with stored rows.
  Input-hash mismatch invalidates: when the caller passes an
  ``input_hash`` and the stored record differs, a ``WARNING``
  is logged ("checkpoint input-hash mismatch — invalidating …")
  and the wrapper falls through to re-run fn; ``INSERT OR
  REPLACE`` on the v10 UNIQUE constraint overwrites the stale
  row naturally.  Omitted ``input_hash`` (``None``) accepts any
  stored row and is recorded as ``""`` so a future opt-in hash
  will mismatch cleanly.  Uses PEP 695 generic syntax
  (``async def checkpoint[T]``) matching the codebase's
  ``mcp/token_storage._load_model[T]`` precedent.  13 new tests
  in ``test_durability.py`` split across ``TestCheckpointCtx``
  (counter start-at-1, per-step independence, monotonic
  increment) and ``TestCheckpointWrapper`` (miss-runs-fn-and-
  persists, hit-skips-fn, auto-numbered repeated calls, partial-
  prior-run replay, hash-mismatch-invalidates with log capture,
  matching-hash-hits, None-hash-accepts-stored, KIND_BYTES
  round-trip across two ctxs, step-name isolation, task-id
  isolation, empty-string-default input_hash).

- **Step-level durable-execution checkpoints — Phase 52.1.**  First
  piece of Phase 52's per-step resume story: a subagent task that
  rate-limits on LLM turn 18 should restart from turn 18, not
  turn 1.  Phase 52.1 lands the persistence layer — the replay
  wrapper and subagent wiring land in 52.2 / 52.3.  New
  ``step_checkpoints`` table added via schema v10 migration:
  ``(task_id, step_name, ordinal, input_hash, result_blob,
  result_kind, created_at)`` with ``UNIQUE(task_id, step_name,
  ordinal)`` and an ``ix_step_checkpoints_task`` index on
  ``task_id``.  Migration is idempotent so a partially migrated
  DB reopens cleanly.  New ``cantrip.agent.durability`` module
  exposes ``CheckpointStore`` (facade over ``SessionStore``)
  with the roadmap-named helpers ``record`` / ``get`` /
  ``next_ordinal`` plus ``list_for_task`` / ``count_for_task``
  / ``purge_task`` for the 52.5 debugging surface.  Serialisation
  is JSON with a ``KIND_BYTES`` raw-bytes escape hatch — the
  roadmap called for msgpack-with-JSON-fallback but msgpack
  isn't a current dep (no ``import msgpack`` anywhere in
  ``src/``), and JSON already covers every concrete 52.2 / 52.3
  value shape without adding blast radius.  The JSON encoder
  handles ``Path`` / ``datetime`` / ``set`` via ``default=`` so
  tool args don't need pre-stringifying.  New
  ``compute_input_hash(*parts)`` helper canonicalises mixed
  primitives / dicts / lists into a stable SHA-256 digest so
  dict-key ordering never changes the result.  GC: a new
  ``on_task_done`` hook on ``BackgroundExecutor`` fires
  ``CheckpointStore.on_task_done(task.id)`` — purging only
  when ``WorkQueue.set_done`` resolves (not on FAILED /
  BLOCKED).  ``$CANTRIP_KEEP_CHECKPOINTS`` (``1`` / ``true`` /
  ``yes`` / ``on``) flips the purge into a no-op and logs the
  retained row count at DEBUG so a stale-cache hunt can
  inspect the rows without a manual ``DELETE``.  30 new tests
  in ``test_durability.py`` cover the schema (fresh DB, v9→v10
  migration, unique constraint), the SessionStore helpers, the
  CheckpointStore facade (JSON round-trip, bytes round-trip +
  type-mismatch rejection, loud-failure on non-serialisable
  values, ``json_default`` coverage, next_ordinal delegation,
  env-var bypass), the GC path (purge by default, skip when
  env set, truthy / falsy recognition, cross-task isolation),
  and ``compute_input_hash`` (determinism, key-order
  invariance, ``repr()`` fallback for non-JSON types).

- **MCP-aware skills — Phase 50.4.**  A skill can now declare
  MCP server dependencies in its frontmatter (``mcp_servers:``,
  same shape as ``tools:`` — YAML list or comma-separated
  string).  ``SkillMetadata`` grew an ``mcp_servers: list[str]``
  field and ``_coerce_tools`` was generalised to
  ``_coerce_string_list`` shared between both fields.  At load
  time ``LoadSkillTool`` checks the session's configured
  ``MCPRegistry`` against the declared list and, when any
  server is missing, prepends a clear warning banner naming the
  unconfigured servers before returning the body.  Hard gating
  would silently hide skills the agent might still extract
  value from; a visible banner is the better failure mode.
  The prompt-level skill index
  (``<available_skills>``) also carries a
  ``<required_mcp_servers>`` child element per skill that
  declares deps, so the agent can pick an alternative when
  missing infrastructure would block a skill.  The registry is
  threaded from ``CantripAgent`` through ``build_tools()`` into
  ``LoadSkillTool``; passing ``None`` (e.g. from a test rig
  without MCP) treats every declared server as missing, so the
  warning is conservative by default.  Exports round-trip the
  new field: ``cantrip skill export`` emits ``mcp_servers:``
  when non-empty and omits it otherwise, matching the existing
  ``tools:`` behaviour.  13 new tests in ``test_skills.py``
  cover frontmatter parsing (YAML list / comma-string /
  missing / malformed), prompt-render of
  ``required_mcp_servers``, ``LoadSkillTool`` warning /
  silent-success / partial-missing / no-registry /
  no-deps-no-banner paths, and the export round-trip.
  ``docs/src/howto-skills.md`` gains an "MCP dependencies"
  section describing the frontmatter key, the warning
  behaviour, and how it composes with Phase 45's MCP config.
  Phase 50 closes with this change.

- **`gh skill install` discovery — Phase 50.3.**  Cantrip now
  discovers skills installed via GitHub CLI's ``gh skill install``
  at the directories the command actually writes to.  Research
  pinned the behaviour: there is no dedicated "gh skill"
  directory — the command writes into whichever agent-specific
  paths each target tool reads from (hard-coded table in
  ``cli/cli/internal/skills/registry/registry.go``, shipped in
  GitHub CLI v2.90 on 2026-04-16).  For Cantrip's users the two
  that matter are the ``universal`` user-scope bucket at
  ``~/.config/agents/skills/`` (shared by ``opencode`` /
  ``kimi-cli`` / ``warp`` / ``replit`` / ``universal``) and the
  project-scope default at ``<charm>/.agents/skills/`` +
  ``<charm>/.claude/skills/``.  ``_default_external_skill_dirs()``
  picked up the ``universal`` dir; a new
  ``_default_project_skill_dirs(project_root)`` helper returns
  the two project-scope paths; ``SkillsIndex`` gained a
  ``project_root=`` kwarg; ``CantripAgent`` threads the charm
  path through so project-scope skills are discovered end-to-end.
  Precedence follows *most-shared → most-specific*: universal →
  Claude → Cantrip-specific at user scope, then project-scope
  wins over user-scope on name conflicts (``gh skill install``
  into a repo always trumps a shared copy of the same skill).
  The existing 50.1 test pinning Claude-before-Cantrip order was
  renamed and expanded to assert the three-way ordering; 3 new
  tests cover ``project_root=`` discovery, project-wins-over-user
  override, and the absence of project paths when ``project_root``
  is omitted.  ``docs/src/howto-skills.md`` grew a user-scope /
  project-scope breakdown of all six directories plus an
  *Installing skills with `gh skill install`* section covering
  both default project-scope and opt-in user-scope invocations;
  ``README.md`` gained a two-paragraph skills callout linking
  through to the how-to.

- **Skill export CLI — Phase 50.2.**  ``cantrip skill export <name>
  <path>`` writes a discovered skill to a file in the same
  vendor-neutral SKILL.md shape Phase 50.1 imports from, completing
  the round-trip.  Works on bundled skills and on user-authored
  skills under ``~/.claude/skills/`` or
  ``~/.config/cantrip/skills/``.  ``path`` is honoured verbatim when
  it ends in ``.md`` (single-file layout) and expanded to
  ``<path>/<name>/SKILL.md`` otherwise (directory layout); parent
  directories are created as needed and ``--force`` is required to
  overwrite an existing target.  The exported body is scrubbed
  through ``memory_export.sanitise_body`` so the same rules that
  apply to ``/memory export`` also apply here: ``--charm-path DIR``
  replaces occurrences of that path with the literal
  ``<CHARM_PATH>`` placeholder, and high-confidence credential
  shapes (GitHub tokens, AWS keys, Bearer headers, ``password=…``
  pairs, Slack tokens) are replaced with ``[REDACTED]``.  The
  command prints the redaction count so the operator can see at a
  glance whether anything was scrubbed before sharing.  Frontmatter
  round-trips ``name``, ``description``, and ``tools`` (omitted
  when empty).  ``SkillsIndex`` grew a ``metadata_for(name)``
  accessor returning the stored ``SkillMetadata`` (or ``None``) so
  the exporter can re-emit frontmatter without re-parsing the
  file.  12 new tests in ``test_skills.py`` cover the core
  exporter (directory vs file target, force / refuse-to-overwrite,
  unknown-name error listing known skills, charm-path
  sanitisation, secret redaction + count, tools preservation,
  tools omission when empty, and a full export → clear → re-import
  round-trip through a fresh ``SkillsIndex``) plus CLI dispatch
  (happy-path exit 0 + target-written, unknown-skill exit 2).
  ``docs/src/howto-skills.md`` gains an "Exporting a skill" section
  and ``docs/src/reference-cli.md`` documents
  ``cantrip skill export`` alongside the existing subcommands.

- **User-authored skill directories — Phase 50.1.**  ``SkillsIndex``
  now discovers vendor-neutral skills in ``~/.claude/skills/`` and
  ``~/.config/cantrip/skills/`` alongside the bundled set.  The
  default constructor walks ``[bundled, ~/.claude/skills,
  ~/.config/cantrip/skills]`` in order, with later directories
  winning on name conflict — so a Cantrip-specific user skill trumps
  a shared Claude Code skill, which trumps the bundled default.
  Conflicts log at INFO level so the override is auditable.  Both
  on-disk layouts are accepted: ``<root>/<name>/SKILL.md`` (the
  Cantrip bundled + Claude Code convention) and ``<root>/<name>.md``
  (single-file style common in user skills).  ``SkillMetadata``
  grew a ``tools: list[str]`` field (accepting either a YAML list
  or Claude Code's comma-separated string; malformed entries fall
  back to an empty list so discovery never crashes) and a ``source``
  tag distinguishing ``bundled`` from ``external`` skills.
  ``docs/src/howto-skills.md`` documents the format, the three
  discovery locations, both on-disk layouts, and a
  troubleshooting section.  Test isolation: explicit
  ``SkillsIndex(tmp_path)`` no longer picks up host external dirs,
  and the bundled-skill tests now pass ``extra_dirs=[]`` so they
  stay deterministic.  10 new tests cover missing-dir silence,
  external + bundled co-existence, name-conflict override with INFO
  logging, single-file discovery, ``tools`` coercion (list / comma
  string / malformed), ``source`` tag propagation, and default-dir
  precedence.

- **``juju_status_render`` tool — Phase 48.4.**  New observability tool
  that fetches the current ``juju status`` via Jubilant and renders it
  as a coloured tree PNG.  Layout follows the TUI graph screen: apps
  grouped with their units using ``├─`` / ``└─`` / ``│`` glyphs; each
  app or unit carries a status-coloured indicator (● active, ○ waiting,
  ◌ blocked, ◐ maintenance, ✗ error) rendered in its status colour;
  app messages surface as child lines; a deduplicated relation list
  prints below as ``source:endpoint ── [interface] ──▸ target``.  PNGs
  save to ``~/.cache/cantrip/screenshots/juju-status-<model>-<timestamp>
  .png`` and the bytes attach to ``ToolResult.images`` so vision-capable
  providers (Phase 48.1 / 48.2b) see the image inline with a caption
  summarising app / unit / relation counts and naming any blocked or
  errored apps.  Uses the same Pillow-direct rendering pattern as the
  Tempo waterfall (48.3) so there's no new dependency.  Line-building
  (``_juju_status_tree_lines``) and relation deduplication
  (``_collect_relation_entries``) are split out from the Pillow drawing
  helper so the rendering logic is unit-testable without a PNG decoder.
  Rendered rows are capped at 140 so a 200-app model produces a
  reasonable-height image with a "… N more lines omitted" footer
  instead of a 4000-pixel one.  Registered in ``build_tools()`` and in
  the DEBUG subagent allowlist.  15 new unit tests across line
  building, relation deduplication, PNG rendering, and end-to-end
  tool execution.

- **Hook stdout-to-payload mutation — Phase 46.4b.**  A
  ``pre_tool_call`` hook can rewrite the pending tool arguments by
  printing a JSON envelope of the shape
  ``{"mutate": {"arguments": {...}}}`` to stdout; the object wholly
  replaces ``tc.arguments`` before the tool runs.  Chained hooks run
  sequentially so a later hook sees the previous hook's mutation on
  stdin and can refine it further — ``arguments.branch == "main"``
  filters evaluate against the running composed state.  Vetoing
  hooks' envelopes are ignored (the call won't run), non-JSON stdout
  is a non-mutating log line (existing hooks keep working), and
  malformed envelopes log at WARNING rather than breaking the call.
  ``post_tool_call`` and the session transcript record the
  **effective** arguments, so the audit trail reflects what actually
  ran.  Wired in all three ``pre_tool_call`` sites (main
  conversation loop, streaming loop, subagent gather).  Closes
  Phase 46 entirely.  See ``docs/docs/howto-hooks.html`` for a
  redact-secrets example.
- **Agent Client Protocol research findings — Phase 39.**
  `design/ACP_RESEARCH.md` records the protocol concepts (JSON-RPC
  over stdio, `session/prompt` turn flow, `tool_call` semantics,
  MCP crossover), candidate agents (Claude Code via
  `zed-industries/claude-agent-acp`, Gemini CLI, Codex CLI, Goose,
  the ACP Agent Registry), and three integration shapes with
  tradeoffs (ACP-as-`LLMProvider`, ACP-as-subagent-backend,
  Cantrip-as-ACP-agent).  Pivotal finding: ACP agents execute their
  own tools, so the original "ACPProvider implements `LLMProvider`"
  sketch breaks — the interesting shape is instead replacing a
  specific subagent's internal loop with an ACP session.  Verdict:
  interesting, not urgent — defer until a concrete trigger appears
  (user ask, subagent evaluation gap, or remote-transport
  stabilisation).  CLAUDE.md gains a reference entry pointing at
  the findings doc.  No code changes.
- **Docs authoring loop documented and hosting decision recorded —
  Phase 54.4.**  The full-tree round-trip is clean
  (`make docs-check-strict` passes on all 20 pages).  `docs/docs/*.html`
  stays committed rather than moving to CI-only, because `README.md`
  and `CLAUDE.md` cross-link into those paths via repo-relative
  URLs that must resolve on GitHub; the markdown sources under
  `docs/src/` are the true source and CI prevents drift.
  `CONTRIBUTING.md` gains an *Editing the Docs Site* section with
  the edit-markdown / `make docs` / commit-both workflow, and the
  *Project Structure* tree now shows the real `docs/src/` layout.
  `design/DOCS_REBUILD.md` replaces its *Open questions* block with
  a resolved *Hosting model* section.  Phase 54 is now complete.
- **`make docs` build target + CI gate — Phase 54.3.**  Wired
  `docs/src/_build.py` into the Makefile as `make docs` (rebuild),
  `make docs-check` (semantic-DOM diff), and `make docs-check-strict`
  (byte-for-byte diff).  Added a `docs` CI job that runs the strict
  check on every PR, so drift between `docs/src/*.md` and the
  committed `docs/docs/*.html` is caught immediately.  Promoted
  `mdit-py-plugins` from a transitive-of-textual to an explicit
  dependency since `_build.py` imports it directly.  `make docs` is
  a no-op against the current tree — the byte-for-byte check passes.
- **Authored-markdown sources for every docs page — Phase 54.2.**
  All 20 pages under `docs/docs/` now have markdown sources at
  `docs/src/*.md`: one tutorial, eight how-tos, two references,
  eight explanations, and the landing `index.html`.  The template
  gained two layout branches (no-sidebar for the landing page,
  on-this-page-as-primary for the tutorial) and a frontmatter flag
  `breadcrumb_label: ""` for pages whose breadcrumb has only the
  section label.  The build script automatically adds
  `target="_blank" rel="noopener"` to external `<a href="http…">`
  links.  The committed HTML under `docs/docs/` is now the
  regenerated build output — `--check --strict` passes byte-for-byte
  and any future drift (hand-edit, wrong regenerate path) surfaces
  immediately.  One one-off normalisation: `howto-hooks.html`'s
  bespoke footer was replaced with the shared footer that every
  other page uses.  Phase 54.3 (make-docs target + CI wiring)
  follows.
- **Docs rebuild groundwork — Phase 54.1.**  First step of
  reverse-engineering `docs/docs/*.html` into authored markdown.
  Chose markdown-it-py + `mdit_py_plugins.attrs` + Jinja2 + PyYAML
  (all already in the dependency tree) over pandoc, MkDocs-Material,
  and one-shot markdownify.  Landed: `design/DOCS_REBUILD.md` (audit
  findings, rationale, manual-reconciliation rules, entity handling,
  build behaviour), `docs/src/_build.py` (pure-Python builder with
  semantic-DOM `--check` mode that tolerates whitespace/wrapping
  differences but catches content drift), `docs/src/_templates/page.html.j2`,
  `docs/src/_site.yaml` (section nav / page order), and a pilot
  markdown source `docs/src/howto-export.md` that rebuilds to DOM-
  identical output against the committed `howto-export.html`.  Phase
  54.2 (convert the remaining 18 pages) follows.
- **Hook telemetry + `/hooks` command + `cantrip hooks test` — Phase 46.5.**
  Every hook execution now feeds a ``HookStats`` accumulator on the
  agent and writes a ``hook_invocation`` transcript event into the
  session store, so audit logs survive the session.  New ``/hooks``
  slash command (shared across CLI, TUI, Web) lists configured
  hooks grouped by event, shows ``if:`` filter source, flags
  veto-capable hooks, and displays per-hook counts (invocations,
  successes, failures, vetoes, timeouts) + average duration + last
  seen time.  New ``cantrip hooks test <event>`` argparse
  subcommand fires a synthetic event against the loaded config
  with an optional ``--payload JSON`` and prints per-hook results
  with exit code, duration, and stdout/stderr — useful while
  authoring hook configs without standing up a live agent session.
  ``HookRunner.set_listener`` drives the wiring; listener
  exceptions are swallowed so a broken telemetry sink can't abort
  the agent.
- **Hook veto semantics — Phase 46.4a.**  A ``pre_*`` hook with
  ``continue_on_error: false`` that exits non-zero (or times out)
  now vetoes the pending operation: the tool doesn't run, the
  compaction doesn't happen, the subagent doesn't start.  The LLM
  sees a synthesised error ``ToolResult`` naming the hook and its
  stderr so it can react (apologise, retry with different args).
  The 46.2 default (``continue_on_error: true``) is unchanged —
  failing lenient hooks log but don't block.  ``post_*`` hooks
  still fire for vetoed operations with ``success: false`` and a
  ``vetoed_by`` field so observability tooling sees every
  decision, including blocked ones.  New ``HookResult.vetoed``
  property and ``first_veto(results)`` helper;
  ``HookResult.veto_reason`` formats a one-line explanation from
  the hook name + last stderr line (or ``exit <code>`` / ``timed
  out after Ns``).  Wired in all three tool-call paths
  (main-agent sync, main-agent streaming, subagent gather),
  both compaction paths, and the subagent lifecycle.
  Stdout-to-payload mutation via JSON envelope is deferred to a
  focused 46.4b follow-up.
- **Conditional ``if:`` filters on hooks — Phase 46.3.**  Hook
  declarations gain an optional ``if:`` field that accepts a
  boolean expression evaluated against the event payload.  Only
  hooks whose filter is truthy fire for a given event — so you can
  say ``if: tool == "git_push"`` without writing shell guards in
  every ``run:``.  Expressions are parsed via Python's ``ast``
  module (no ``eval()``) with a strict allowlist: comparisons,
  boolean combinators, nested field access, subscripts, list /
  string / number literals.  Function calls, method calls,
  lambdas, imports, and comprehensions are rejected at
  config-load time.  Missing payload fields evaluate to a
  ``_Missing`` sentinel so ``if: task.category == "BUILD"`` on a
  ``pre_compact`` event silently skips instead of raising — handy
  when one config targets multiple event shapes.  Bad expressions
  surface a ``HookConfigError`` with the hook name, not a runtime
  crash.  Docs at ``docs/docs/howto-hooks.html`` have a new
  "Conditional filters" section.
- **User-configurable hooks — Phase 46.1 + 46.2.**  New
  ``cantrip.hooks`` module lets users declare shell commands that
  run at lifecycle events: ``pre_tool_call`` / ``post_tool_call``
  (main agent + subagent), ``pre_compact`` / ``post_compact``,
  ``pre_subagent`` / ``post_subagent``.  Config lives at
  ``~/.config/cantrip/hooks.yaml`` (user, overridable via
  ``$CANTRIP_HOOKS_USER_CONFIG``) and ``cantrip.hooks.yaml`` in
  the charm directory (repo wins on name collision) — same
  two-scope pattern as the MCP config.  Hooks run as subprocesses
  with a JSON payload on stdin.  Schema uses ``event:`` not ``on:``
  to dodge YAML 1.1's boolean-key trap.  Reserved event names
  (``pre_pack``, ``pre_push``, ``pre_pr``, ``on_task_complete``,
  ``on_session_end``) accept hook declarations today and start
  firing when later sub-phases wire them up.  Full docs at
  ``docs/docs/howto-hooks.html``.  The upcoming 46.3 adds ``if:``
  conditional filters; 46.4 upgrades non-zero exit from pre-hooks
  into a real veto.
- **Tempo trace waterfall rendering — Phase 48.3.**  New
  ``tempo_waterfall`` tool fetches a trace from Tempo (same in-unit
  SSH pattern as ``tempo_query``), flattens the OpenTelemetry
  ``batches[].scopeSpans[]`` — or the legacy
  ``instrumentationLibrarySpans`` shape — into spans, and renders a
  PNG waterfall with Pillow.  Each span is a horizontal bar
  positioned on a 1400×N canvas by start time and duration; the
  top-3 longest spans are highlighted so the eye lands on the
  bottleneck without reading every number.  Durations are
  formatted in ns / µs / ms / s depending on magnitude.  Caps the
  image at 80 spans — the highlight set is computed across the
  *full* list first so the warm-coloured bars stay the interesting
  ones.  PNG saved to ``~/.cache/cantrip/screenshots/`` and
  attached to ``ToolResult.images`` via the 48.2b pipeline so
  vision-capable providers see the waterfall inline.  Added
  ``pillow>=11.0`` as a dependency; registered in the DEBUG
  subagent allowlist; ``reference-tools.html`` updated.
- **Tool-result images threaded through to vision-capable providers —
  Phase 48.2b.**  Agent ``ToolResult`` and ``llm.ToolResult`` each
  grew an ``images: list[Image]`` field; the conversation loop
  (``core.py`` synchronous and streaming paths + ``subagent.py``)
  now forwards those images into the TOOL message.  Context
  virtualisation preserves attachments when it rewrites a giant
  text caption into a virtual-file pointer.  ``ClaudeProvider``
  renders a mixed image + text content list inside
  ``tool_result`` blocks — the model sees the visual before the
  caption.  ``GrafanaScreenshotTool`` now attaches the rendered
  PNG so an agent on Claude can reason about the panel visually
  end-to-end, not just get a file path.  Gemini and inference
  snaps drop images (their tool-role messages are text-only by
  spec) and rely on the caption, which always carries enough
  diagnostic context to be useful on its own.
- **Grafana screenshot tool — Phase 48.2a.** New
  ``grafana_screenshot`` tool renders a Grafana panel or dashboard
  as a PNG via Grafana's ``/render`` endpoint, using the same
  in-unit SSH-fetch pattern as ``tempo_query`` / ``loki_query``.
  Fetches the admin password via the ``get-admin-password`` action
  (degrades gracefully when it's unavailable), saves the PNG to
  ``~/.cache/cantrip/screenshots/`` with a deterministic filename,
  and returns a caption plus a structured ``data`` dict with the
  file path.  Registered in the DEBUG subagent allowlist.
  A follow-up sub-item (48.2b) will thread the PNG bytes into the
  tool-result message so vision-capable providers can reason about
  the panel visually; until then the caption + file path are the
  handoff.  Ships a reusable ``_ssh_fetch_binary`` helper for the
  PNG transport that Phase 48.3 / 48.4 will also use.
- **Image input across LLM providers — Phase 48.1.** ``Message`` grew
  an ``images: list[Image]`` field (with a new
  ``Image(data: bytes, mime: str)`` dataclass), and ``LLMProvider``
  grew a ``supports_vision`` property.  ``ClaudeProvider`` and
  ``GeminiProvider`` both advertise ``supports_vision = True`` and
  forward attachments as native image content (Anthropic ``image``
  blocks / Gemini ``Part.inline_data``) with per-image byte caps
  that match each vendor's limits (Claude 5 MB, Gemini 20 MB).
  ``InferenceSnapProvider`` now detects vision capability at
  runtime: a static allowlist (``qwen-vl``, ``gemma3``) seeds the
  flag, and a ``/models`` capability probe (``"vision"`` /
  ``"image"``) can upgrade a non-allowlisted snap to vision-capable
  — the static seed never gets downgraded.  Vision snaps build
  OpenAI multi-part ``image_url`` content with ``data:…;base64,…``
  URIs; non-vision snaps raise ``NotImplementedError`` with a
  message pointing to ``qwen-vl`` / ``gemma3`` instead of silently
  dropping the attachment.  Unblocks Phase 48.2–48.5 (Grafana,
  Tempo waterfall, Juju-status-tree, workload-screenshot tools).
- **macOS ``sandbox-exec`` + sandbox observability — Phase 49.4 + 49.5.**
  The ``SandboxedRunner`` now supports a ``"sandbox-exec"`` mechanism
  on macOS — detected via ``shutil.which`` and driven by a Lisp-like
  SBPL profile that denies everything by default and then allows
  ``process-exec`` / ``process-fork`` / ``sysctl-read`` / ``mach-lookup``
  / ``ipc-posix-sem``, ``file-read*`` on the standard system paths
  (``/usr``, ``/bin``, ``/System``, ``/Library``, ``/private/etc``,
  …), ``file-read*`` + ``file-write*`` on the working tree and any
  policy ``read_write_paths``, and ``network*`` gated on
  ``policy.network``.  Falls back to ``"none"`` with a one-shot warning
  when ``sandbox-exec`` is missing — future macOS releases may remove
  the Apple-deprecated tool entirely, which the warning anticipates.

  For observability, ``cantrip.agent.sandbox`` gained a module-level
  event-sink slot (``set_event_sink`` / ``get_event_sink``, thread-safe
  via a lock).  When a sink is registered, ``SandboxedRunner.run``
  emits a ``sandbox_policy`` event with the argv, mechanism, cwd,
  network setting, and bind-mount lists *before* the subprocess
  spawns.  ``CantripAgent._init_store`` installs a sink that routes
  into ``SessionStore.record_event`` so every sandbox decision is
  durably audit-logged alongside tool calls.  Sink exceptions are
  swallowed so a misbehaving sink can never break the run.

  A new ``/sandbox`` slash command reports the active mechanism
  (bwrap / unshare / sandbox-exec / none, each with a one-line
  summary including the upgrade path when relevant), the
  ``run_command`` default policy, and whether transcript logging is
  currently on.  Covered by 5 new ``TestSandboxExecWrap`` cases + 4
  ``TestEventSink`` cases + 4 ``TestSandbox`` dispatcher cases; the
  catalogue drift guards continue to hold.

  Phase 49.3 (per-tool seccomp-bpf allowlists) remains deferred —
  rolling hand-crafted BPF without a ``libseccomp`` dep is more
  risk than value, and the phase's own exit clause sanctions
  falling back to the namespace-only sandbox when seccomp is
  unavailable.  Re-open when a tool presents a concrete
  syscall-level attack surface.
- **``SandboxedRunner`` + ``run_command`` namespace isolation —
  Phase 49.1.**  New ``cantrip.agent.sandbox`` module wraps
  subprocess invocations with Linux user-namespace isolation so a
  hallucinated or compromised shell command can't reach files or
  processes outside its intended scope.  ``sandbox_available()``
  probes for ``bwrap`` (full filesystem + PID + network + namespace
  isolation, canonical) and falls back to ``unshare`` (PID +
  optional network isolation, no filesystem bind mounts — but the
  network block still blocks credential exfiltration).  On non-Linux
  or when neither tool is installed the runner logs a one-time
  warning and runs the command unchanged so tests and non-Linux
  users aren't locked out.  Per-invocation policy is a frozen
  ``SandboxPolicy`` dataclass (``network``, ``read_write_paths``,
  ``read_only_paths``) — callers describe what the command needs
  rather than juggling CLI flags.  ``bwrap`` binds ``/usr`` /
  ``/bin`` / ``/sbin`` / ``/lib*`` / ``/etc`` / ``/opt`` read-only
  (via ``--ro-bind-try`` so missing paths don't break the run),
  ``cwd`` read-write, each policy ``read_write_paths`` entry
  read-write, each ``read_only_paths`` entry read-only, and adds a
  tmpfs ``/tmp`` + fresh ``/proc`` / ``/dev`` + ``--new-session`` /
  ``--die-with-parent`` for blast-radius containment.
  ``RunCommandTool`` now runs every allowlisted command through the
  sandbox with ``network=False`` by default and ``cwd`` bound
  read-write — this is defence in depth on top of the existing
  allowlist + wrapper denylist + shell-metacharacter checks, so a
  prompt injection that bypassed every existing gate still can't
  reach the network.  Other subprocess tools (``JujuDeployTool``,
  git, charmcraft) keep their direct paths for now; the sandbox is
  additive and they can adopt it per-tool in follow-up work.
  Covered by 16 new sandbox-module tests (mechanism selection, bwrap
  and unshare argv construction, no-sandbox pass-through, one-shot
  warning, real-exec smoke test) plus 3 ``RunCommandTool`` sandbox
  wiring tests.
- **``charm-debug`` skill — Phase 33.5.**  New bundled skill that
  gives the agent a deterministic diagnostic workflow for stuck,
  misbehaving, or slow-to-reach-``active`` charms.  Shipped as a
  read-only skill (no CLI subcommand — the agent already has every
  tool it needs).  Prescribes a fixed five-step inspection
  (``juju_status`` → ``juju_debug_log`` → ``juju_read_relation_data``
  on endpoints status mentions → ``juju_get_app_config`` diffed
  against charmcraft defaults → ``juju_list_secrets`` /
  ``juju_show_secret`` for grants / rotation freshness) and a
  12-row symptom → likely-cause → next-action table that translates
  what the inspection finds into concrete tool calls.  Ends with a
  fixed report template so the user sees the same shape every time.
- **``benchmark`` skill — Phase 33.6.**  New bundled skill wrapping
  the existing ``hook_benchmark`` tool with interpretation guidance
  (what it measures, what it does not — actions, workload latency,
  cold-start CPU) and rules of thumb per hook type with "good
  enough" ceilings.  Documents the full before/after comparison
  pattern for optimisation work: baseline snapshot →
  ``tests/perf/baseline.json`` → optimisation commit → candidate
  snapshot → delta report with a 10% / 100 ms noise guard, table
  format spelled out.  For ``cantrip.workspace.yaml`` repos, run the
  comparison per-charm (cross-charm timings don't add up cleanly).
- **Multi-charm workspace manifest + ``workspace`` skill +
  ``workspace_info`` tool — Phase 33.3.**  Cantrip can now reason
  about monorepos that hold more than one related charm.  A new
  ``cantrip.workspace.yaml`` manifest declares the charms (name,
  path, optional description), the cross-charm relations (``provider``
  / ``requirer`` / ``interface``, with both endpoints validated
  against the charm list at load time), and any shared config values
  (log level, TLS mode, tenancy ids).  Parsing lives in a new
  ``cantrip.workspace`` module with frozen dataclasses and a
  round-trippable ``to_dict()``.  The ``workspace_info`` tool reads
  the manifest and returns both a human-readable summary and a
  structured payload; it walks upwards from the given directory (or
  cwd) so launching inside any charm subdirectory still finds the
  workspace root.  The ``workspace`` skill documents when to create a
  manifest, the provider / requirer / interface split for cross-charm
  relations (app databag vs unit databag vs Juju secret decision
  tree, interface naming conventions, delegation to ``charm-library``
  for the library itself), coordinated deploy (per-charm pack →
  ``juju_deploy`` → ``juju_relate`` → ``juju_wait``), and
  workspace-level Jubilant integration tests using
  ``juju.integrate(provider_side, requirer_side)``.  The skill refuses
  bundle authoring outright and points at ``terraform`` for reusable
  orchestration and ``bundle`` for legacy consumption.  The system
  prompt's "Default Integrations" section tells the agent to load the
  ``workspace`` skill and call ``workspace_info`` whenever the user is
  working across ≥2 charms.  Covered by 17 manifest-parsing tests, 5
  tool tests, and a skill-anchor pin that protects the manifest
  schema, cross-charm design guidance, and the anti-bundle stance.
- **``bundle`` skill + ``bundle_deploy`` tool — Phase 33.1.**  New
  bundled skill for working with **existing** Juju bundles: reading a
  `bundle.yaml` the user hands you, applying overlays to modify it,
  deploying via the new tool, and migrating a bundle-based deployment
  off the bundle onto individual `juju_deploy` / `juju_relate` calls
  (or a Terraform module).  The skill opens with a deprecation notice
  and ends with an explicit "do not create new bundles" section so the
  agent pushes back when asked to author one.  New `BundleDeployTool`
  wraps `jubilant.Juju.deploy()` with fail-fast validation of the
  bundle path and every overlay path, a 10-minute timeout suited to
  full-stack bundles, and structured output reporting the overlay
  count.  The system prompt's "Default Integrations" section now
  carries a "Multi-charm deployments — do not write new bundles"
  anchor that points at `juju_deploy` + `juju_relate` (or Terraform)
  for new work and at the `bundle` skill / `bundle_deploy` tool for
  legacy consumption.  `reference-tools.html` lists `bundle_deploy`
  with a "legacy consumption only" annotation.  Covered by six
  `TestBundleDeployTool` cases plus a new skill-pinning anchor test
  that protects the deprecation stance and the overlay documentation.
- **``charm-migration`` skill — Phase 33.2.**  New bundled skill that
  covers all four legacy-pattern migrations as a single umbrella
  workflow: reactive-framework → ops (decorator-to-``framework.observe``
  mapping plus the ``_reconcile()`` discipline that replaces
  flag-driven handler chains), ``StoredState`` → modern storage
  (decision tree between instance attributes, peer relation data, and
  Juju secrets — with worked examples of the peer-data and secret
  replacements), Harness → Scenario (delegates the per-file workflow
  to the existing ``harness-migration`` skill), and ``fetch-libs`` →
  PyPI (current ``charmlibs-*`` mapping table plus the authoring
  escape-hatch via ``charm-library``).  The skill maps every
  migration onto the charmlint rule IDs that detect it so the agent
  can walk the audit report straight into the relevant section.  A new
  charmlint rule ``DEP004`` (``uses-reactive-framework``) detects
  ``charms.reactive`` imports and the ``@when`` / ``@when_not`` /
  ``@when_any`` / ``@when_all`` / ``@hook`` decorators.  The
  ``--improve`` planner wires this through: the audit gap inferencer
  recognises reactive-framework keywords, ``plan_improvement_fixes``
  treats the new ``reactive_framework`` gap as a modernisation
  trigger, and the generated ``modernise-code`` task description now
  tells the agent to load the ``charm-migration`` skill first when any
  deprecated-API or reactive-framework gap fires.  Pinned by a new
  ``test_charm_migration_skill_covers_all_four_migrations`` anchor
  test plus unit coverage on the new rule, gap inference, and planner
  behaviour.
- **``charm-library`` skill — Phase 33.4.**  New bundled skill teaching
  the agent how to author a reusable charm library end-to-end: when to
  create one (relation interfaces and cross-charm helpers) vs keep code
  in-charm, the ``lib/charms/<charm>/v<N>/<library>.py`` path convention,
  the four mandatory module-level constants (``LIBID``, ``LIBAPI``,
  ``LIBPATCH``, ``PYDEPS``) and the rules for bumping each, provider /
  requirer class design (validated with Pydantic, emitting high-level
  events rather than raw relation events), a Scenario-based unit-test
  harness that drives the library through a minimal test-only charm,
  the module-docstring template Charmhub surfaces on the library page,
  publishing via ``charmcraft register-lib`` / ``publish-lib`` and
  consumption via ``charm-libs:`` or ``charmcraft fetch-libs``, and the
  modern PyPI alternative (``charmlibs-*`` under
  ``canonical/charmlibs``) for general-purpose helpers.  Pinned by a
  new ``test_charm_library_skill_covers_authoring`` test that checks a
  dozen required anchors are present so the skill can't drift away from
  the authoring flow.

- **Web UI design-quality pass — Phase 31.15.**  Applied the
  impeccable.style checklist (audit, critique, harden, clarify,
  distill, layout, polish) without the skills being invocable as
  slash commands — the SKILL.md reference material was applied
  manually.  Concrete fixes:
  a first-run empty state in the chat panel
  ("Ready when you are.") with an example prompt, hidden once any
  message arrives; charm name in the header now ellipses at 30ch so
  long names don't push the controls off-screen; Juju-app status
  messages display the full text via ``title`` but truncate visibly
  with CSS ellipsis instead of the old ``substring(0, 40)`` hard
  cut; header buttons grew to meet WCAG 2.5.5 touch-target guidance
  (min-width 2.25rem, min-height 1.75rem) and gain an
  ``aria-expanded="true"`` visual state; log-overlay and graph-overlay
  error strings now include the HTTP status code and a specific
  "is a dev model attached?" hint instead of generic "Failed to
  fetch"; help overlay documents Shift+Enter for newlines; footer
  hint lists Alt+R; "Start fresh" button gained a ``title`` tooltip
  explaining that the previous session is archived, not deleted.
  TUI palette (``cantrip.tcss``) reviewed and found aligned with
  impeccable's "tokens not hard-coded colours" principle — no
  changes needed since every colour already resolves through
  Textual theme variables.
- **Web UI chat UX — Phase 31.13 (Bundle B).**  Server-side Markdown
  rendering via ``markdown-it-py`` (with ``linkify``, ``table``, and
  ``strikethrough`` enabled) replaces the hand-rolled regex parser in
  ``cantrip.js`` — chat messages now support tables, proper nested
  lists, ``*`` bullets, links with ``javascript:`` URLs rejected,
  autolinked bare URLs, images, and strikethrough.  Every
  ``chat_message`` broadcast and ``/api/messages`` entry carries
  ``content`` (raw text), ``html`` (pre-rendered), and ``timestamp``
  (UTC ISO with ``Z`` suffix — per-turn time formatted HH:MM locally).
  User messages now render Markdown too (same pipeline, same CSS).
  Raw HTML is disabled in the renderer so ``<script>`` arrives as
  escaped text.
  A new Tool Activity indicator replaces the static "Thinking…"
  label: ``status_bar_changed`` bus events drive a per-round label
  update ("⟳ running: charmcraft_pack") so users can see which tool
  is in flight.  A floating scroll-to-bottom button appears when the
  user scrolls up, and the auto-scroll-on-new-message heuristic now
  respects their position — new messages don't yank the viewport
  back to the bottom while they're reading history.  The chat input
  switched from ``<input>`` to an auto-growing ``<textarea>`` with
  Shift+Enter for newlines.
- **Web UI polish — Phase 31.13 (Bundle A).** Several small gaps closed:
  ``--improve`` is now an explicit error in ``--web`` mode (exit 2 with
  a message pointing at the TUI/CLI path) instead of being silently
  dropped; the Juju Status panel grew a refresh button and ``Alt+R``
  now force-refreshes the status when no overlay is open (still
  refreshes the graph when the graph overlay is open); a new preflight
  panel in the right sidebar renders the five environment checks
  (Concierge, Environment, Juju CLI, Controller, COS) with animated
  running icons and auto-hides a few seconds after completion, fed by
  new ``preflight_started`` / ``preflight_updated`` /
  ``preflight_complete`` / ``preflight_failed`` WebSocket events that
  bridge the existing ``PreflightEvent`` callback to the browser; a
  Cancel button appears alongside the thinking indicator and posts a
  ``cancel_request`` WS message that ``task.cancel()``s the in-flight
  ``process_message`` (the read loop now dispatches turns as
  background tasks so cancel arrives while a turn is running instead
  of queuing behind it).
- **``cantrip compare`` subcommand — Phase 31.7 ✓.**  Diffs two
  charm implementations along four dimensions — directory structure,
  ``config.options``, relation endpoints
  (``provides``/``requires``/``peers``), actions, containers,
  extensions, and unit/integration test counts — then prints a human-
  readable report.  Parses modern ``charmcraft.yaml`` (4.x) as well as
  the legacy ``metadata.yaml`` / ``config.yaml`` / ``actions.yaml``
  split, merging the two so a hand-crafted charm using the old layout
  compares cleanly against a Cantrip-generated charm using the new
  one.  Invoke with ``cantrip compare CHARM_A/ CHARM_B/``.  Useful for
  evaluating Cantrip output against upstream or hand-crafted
  reference charms.

### Security
- **Wrapper-command denylist in ``RunCommandTool`` — Phase 49.2 ✓.**
  Defence-in-depth on top of the existing allowlist: ``env``, ``sudo``,
  ``doas``, ``watch``, ``nohup``, ``setsid``, ``timeout``, ``ionice``,
  ``nice``, ``chroot``, ``stdbuf``, ``script``, ``xargs``, ``exec``,
  and every common shell (``bash``/``sh``/``zsh``/``dash``/``ksh``/
  ``fish``) are now categorically rejected, even if an operator adds
  one to the allowlist for local debugging.  The error message is
  distinct from the allowlist-miss error so an LLM learns to drop the
  wrapper rather than retry.  Also rejects leading ``NAME=value`` env-
  var assignments (``FOO=bar make ...``) and shell metacharacters
  (``;``, ``&&``, ``||``, ``|``, backticks, ``$(...)``, ``>``, ``<``).
  The tool still runs with ``shell=False`` so metacharacters are
  inert today, but catching them at the source keeps a future
  ``shell=True`` refactor from inheriting a bypass, and makes the
  failure mode obvious to the agent.

### Added
- **``/cost`` per-category breakdown — Phase 31.4 ✓.**  The cost
  dashboard now groups token usage by task category (``research`` /
  ``build`` / ``deploy`` / ``test`` / ``debug``) in addition to the
  existing per-model table.  Main-conversation-loop turns and any
  legacy pre-v9 rows aggregate under ``conversation``.  Surfaces in
  the CLI ``/cost`` command, the ``/cost`` slash command (TUI + Web),
  and the backing ``SessionStore.get_usage_by_category(since=None)``
  helper.  Subagent turns stamp the active task category into
  ``response.metadata["_task_category"]`` so the executor records it
  through ``SessionStore.record_usage(..., category=...)``.  DB
  schema bumped to v9; existing databases add the ``category`` column
  on open (idempotent ALTER), with NULL for every historical row so
  totals stay correct.

### Changed
- **Repo-bootstrap offer moved to a CONFIRM task — Phase 64 ✓.**  When
  Cantrip finishes a build in a directory with no GitHub remote, the
  "create a repository?" prompt no longer appears as an inline system
  message that interrupts the conversation.  It is now emitted as a
  ``bootstrap-repo-<name>`` CONFIRM task in the work queue (same
  pattern as ``push-branch-*`` and ``triage-issue-*``), so it surfaces
  in the task panel and stays blocked until the user replies
  ``approve`` or ``skip``.  The chat still gets a framed
  "**Repo bootstrap:**" confirmation prompt; it no longer drifts off-
  screen behind unrelated output.  Default name follows the Canonical
  upstream convention: ``foo`` → ``foo-operator``; names already
  ending in ``-operator``, ``-charm``, ``-k8s``, or ``-machine`` are
  kept as-is.  Reply tokens: ``approve``, ``skip``, ``public``,
  ``name=my-repo``, ``org=canonical``, ``desc=My charm`` (combinable).
  New ``cantrip.agent.git_branch.suggest_repo_name()`` helper; new
  ``agent.build_repo_bootstrap_confirm_task()`` method; new
  ``BOOTSTRAP_CONFIRM_PREFIX``.  The old ``_pending_bootstrap`` flag
  is gone — the reply router now gates on
  ``_pending_confirm_id.startswith(BOOTSTRAP_CONFIRM_PREFIX)``.

### Fixed
- **Transcript, log, relation, and graph modals rendered blank — Phase 66 ✓.**
  The four ``ModalScreen`` subclasses wrapped their container in
  ``Center()``, whose ``height: auto`` caused the inner
  ``Vertical(height: 80%/90%)`` to resolve against a zero-height parent
  and collapse to a single row — so every modal looked empty even
  though ``on_mount`` had written content.  Dropped the redundant
  ``Center`` wrapper (``ModalScreen`` already centres its children via
  ``align: center middle``) in ``transcript.py``, ``logs.py``,
  ``relation.py``, and ``graph.py``.  Fixed a latent Textual markup
  error that surfaced once the transcript footer was actually painted:
  ``[/ Search]`` parsed as a closing tag; footer now renders with
  ``markup=False``.  New ``tests/unit/test_modal_heights.py`` pins the
  regression: asserts every modal's output widget has non-zero height
  and at least one rendered line.

### Documentation
- **Backfill docs for recent shipped features.**
  ``docs/docs/reference-cli.html`` now describes the
  [R]esume / [F]resh / [T]ranscript launcher prompt (was still claiming
  silent resume) and documents ``CANTRIP_NOTIFY=bell|desktop|both``.
  ``docs/docs/howto-export.html`` covers the ``/export`` slash command
  for mid-session transcript writes alongside the existing CLI
  subcommand.  New ``docs/docs/explanation-tui-screens.html`` catalogues
  every function-key modal (File detail, Logs with ``L``/``M``/``T``
  cycling, Graph with ``F`` status filter, Traces with Grafana
  deep-links) plus the Dev and COS status panes.
- **Racing and Arena explainer (Phase 47.6).**  New
  ``docs/docs/explanation-race.html`` covers the Best-of-N scoring
  rubric (charmlint 30 %, readiness 30 %, tests 25 %, diff 15 %) with
  per-signal decay functions, viability short-circuit for FAILED /
  NOOP runs, and tie-breaking on diff size.  Documents every
  ``RaceConfig`` knob (``enabled_categories``, ``max_candidates``,
  ``budget_tokens``, ``confirm_threshold_tokens``,
  ``baseline_tokens_per_run``, ``cancel_on_perfect``), the three-way
  RACE/CONFIRM/DOWNGRADE gate, the full ``/arena`` pick grammar, and
  every ``race_*`` transcript event with the
  ``parent__candidate`` join key for loser transcripts.  A callout
  flags that ``RaceConfig`` still has no CLI/env surface; the Limits
  section tracks the remaining gaps (no early cancellation, static
  baseline estimate, unit-only test scoring).  Linked from the index
  card grid, from every explanation-page sidebar, and from the Arena
  section of ``reference-cli.html``.

### Changed
- **Charmcraft + Rockcraft catch-up — Phase 37.5 ✓ (closes Phase 37).**
  Audited ``canonical/charmcraft`` (release v4.2.1, cutoff ``fae9862``)
  and ``canonical/rockcraft`` (release v1.18.0, cutoff ``e03ed9f``).
  Two real bugs caught:  (1) ``CharmcraftInitTool`` didn't set
  ``CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS`` for the four profiles
  still flagged experimental upstream (fastapi-, go-, express-,
  spring-boot-framework) — inits would have scaffolded successfully
  but ``charmcraft pack`` would have refused; fixed by gating on a
  new ``_CHARMCRAFT_EXPERIMENTAL_PROFILES`` frozenset.  (2)
  ``RockcraftInitTool`` only set
  ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS`` for a subset of profiles,
  but **every** rockcraft framework extension (including Flask and
  Django) is still flagged experimental upstream; fixed by setting
  the flag unconditionally (same shape as ``RockcraftPackTool``).
  Skill updates: **``twelve-factor``** skill table redone with a
  per-tool experimental column (Flask/Django stable in charmcraft,
  experimental in rockcraft; FastAPI / Go / Express / Spring Boot
  experimental everywhere); new HTTP proxy (``2d6022a``) and
  OpenID Connect (``2b6a9cf``) integration sections with
  ``charmcraft.yaml`` snippets; note that Flask / Django / FastAPI
  rocks now default to a bare base (``3fba20c``) — smaller images,
  no shell or apt; ``entrypoint-command`` field mentioned.
  **``charmcraft``** skill's profile list now names all six profiles
  explicitly with experimental flags and documents the
  ``src/workload.py`` split that the ``kubernetes`` / ``machine``
  templates scaffold.  Tests updated (rockcraft init now always sets
  the flag; Flask test asserts the flag is set rather than absent).
  ROADMAP §37.5 closed with per-item findings; Phase 37 header marked
  ✓.
- **Charm-library catch-up — Phase 37.4 ✓.**  Audited the PyPI
  ecosystem (including the `canonical/charmlibs` monorepo) and found
  that Cantrip's previous ``LIB001`` PyPI map was **mostly fictional**
  — names like ``loki-k8s-lib``, ``traefik-k8s-lib``,
  ``data-platform-libs``, and ``grafana-k8s-lib`` do not exist on
  PyPI, so the rule was telling users to install ghosts.  Both the
  Python (``src/charmlint/rules/libraries.py``) and Rust
  (``src/charmlint-rs/src/rules.rs``) charmlint rules are rewritten
  to match reality: ``operator_libs_linux`` now splits by submodule
  (``apt`` → ``charmlibs-apt``, ``snap`` → ``charmlibs-snap``,
  ``passwd`` / ``sysctl`` / ``systemd`` likewise), and TLS /
  certificate-transfer interface libs map to the
  ``charmlibs-interfaces-*`` PyPI packages.  LIB001 messages now
  include the new import hint (``from charmlibs.interfaces import
  tls_certificates`` etc.) so the port is a copy-paste; LIB002 is
  reframed as "no PyPI equivalent yet; continue using ``charmcraft
  fetch-libs``".  Python and Rust unit tests pin both paths
  (submodule-aware mapping, observability libs correctly staying on
  LIB002).  Skills updated: **``charmcraft``** gains a "Libraries on
  PyPI" table listing every current ``charmlibs-*`` /
  ``charmlibs-interfaces-*`` / ``cosl`` package with its import and
  a complementary "still need fetch-libs" list.
  **``observability``** rewrites the "fetch from PyPI first" bullet
  to name ``cosl`` and the Charmhub-only observability libs.
  **``ingress``** notes that ``traefik_k8s`` is not on PyPI.  System
  prompt's ``### Libraries`` block rewritten with the full accurate
  split.  One audit-tool test switched from a grafana-k8s example
  (now correctly LIB002) to a tls_certificates_interface example
  (still LIB001, with the correct PyPI name).
- **Concierge + Pebble catch-up — Phase 37.3 ✓.**  Audited
  ``canonical/concierge`` (v1.0.0 → main, cutoff ``aeda3bc``) and
  ``canonical/operator`` Pebble/ops.testing commits.  No Cantrip code
  changes to the preflight (``_WARMUP_CONFIG`` + ``--preset`` still
  compose against modern Concierge; its behaviour fixes apply
  transparently once the user's snap is current).  Skill updates:
  **``concierge``** — document ``--dry-run`` on ``prepare``/``restore``
  (``bebf251``), the per-provider ``image-registry`` block with
  ``$VAR`` interpolation for docker.io mirrors (``d844183``), and
  ``extra-bootstrap-args`` on the ``juju`` section (``4d6726c``).
  **``scenario-tests``** — plain ``breakpoint()`` is now usable inside
  ``testing.Context.run`` (``61e606e``, no more rebound
  ``sys.breakpointhook``); ``State.get_relation`` accepts a relation
  object with narrowed return type (``706b667``); Scenario autoloads
  charmcraft extension metadata so 12-factor tests Just Work
  (``55c41eb``).  **``iterate-fix``** — breakpoint-in-test added as
  the cheapest debug tool (no deploy), and a growing
  total-deferred-events count in ``juju debug-log`` (``5e752be``) now
  flagged as a Workload-bucket triage signal.  ``design/UPSTREAM_AUDIT.md``
  grows three rows: concierge, a Pebble/testing re-scan of operator, and
  an explicit note that the Concierge repo moved from
  ``jnsgruk/concierge`` to ``canonical/concierge``.
- **Jubilant catch-up — Phase 37.2 ✓.**  Audited
  ``canonical/jubilant`` through release v1.8.0 (cutoff ``e9923ec``,
  recorded in ``design/UPSTREAM_AUDIT.md``).  Two latent bugs in
  Cantrip's test-template output: ``generate_integration_tests`` and
  ``generate_load_test`` emitted ``juju.run_action(...)`` (removed
  from Jubilant — modern API is ``juju.run(unit, action, params)``
  returning a ``Task``) and the legacy ``wait(apps=…, status="active")``
  kwargs (replaced by predicate callables like
  ``jubilant.all_active``).  Both generators rewritten; the produced
  ``conftest.py`` no longer rolls its own ``juju`` fixture (pytest-jubilant
  supplies a module-scoped one) and the ``charm`` fixture resolves the
  packed ``.charm`` honouring ``CHARM_PATH``.  Status assertions now
  use ``status.apps[APP_NAME].is_active`` rather than the broken
  ``app.status.current`` (the actual attribute is ``app_status``).
  System prompt's integration-tests checklist updated.  Cantrip's
  Jubilant pin tightens from ``>=1.8.0`` to ``>=1.8,<2`` to lock in the
  API-stable 1.x major.  No changes to the ``jubilant-tests`` skill —
  §37.1 already brought it up to pytest-jubilant 2.0.
- **Upstream ecosystem catch-up — Phase 37.1 ✓.**  Refreshed Cantrip's
  charm-generation outputs against ``canonical/operator`` docs commits
  through April 2026.  Skills updated: ``scenario-tests`` (drop ``meta=``
  from ``Context``, ``get_filesystem`` for pushed files,
  ``dataclasses.replace`` for State sequences, ``collect_status`` via
  ``update_status`` with ``layers=``/``service_statuses=``,
  ``pytest.mark.parametrize`` for config validation), ``jubilant-tests``
  (full ``pytest-jubilant`` 2.0 adoption: drop hand-rolled ``juju``
  fixture, pin ``jubilant>=1.8,<2``/``pytest-jubilant>=2,<3``,
  ``--juju-dump-logs`` in CI, COS Lite cross-model pattern with
  ``JujuFactory``), ``observability`` (Pebble's Loki label is ``charm``
  not ``juju_charm``; cross-model COS smoke-test pointer),
  ``relation-data-design`` (secret IDs are opaque, secrets-over-CMR are
  granted only by the offering app), ``charmcraft`` (Charmcraft 4.2
  ``base:``/``platforms:``/``assumes:`` form, storage-event bracket
  notation, ``pathops``, Juju/Pebble version matrix), ``jhack`` /
  ``iterate-fix`` (``jhack scenario snapshot`` for live state capture,
  interactive debugging via ``Framework.breakpoint`` + ``debugpy`` +
  ``juju debug-code``).  Gold-standard charms (meilisearch, ntfy,
  miniflux) drop the ``meta=``/``_meta()``/``_config()`` placeholders,
  import the real charm class, and gain ``assumes: [juju >= 3.6,
  k8s-api]``.  ``GhRepoBootstrapTool``'s CI workflow stub now matches
  the upstream "set up CI for a charm" how-to (``permissions: {}``,
  pinned action SHAs, ``persist-credentials: false``,
  ``uv tool install tox --with tox-uv``, separate lint/unit jobs).
  System prompt: charm deps live in ``pyproject.toml`` (not
  ``requirements.txt``), and never put secrets in CLI arguments.  New
  ``design/UPSTREAM_AUDIT.md`` records the audit cutoff (operator
  ``df731e5``) and the procedure for re-running the sweep next quarter.
- **Close out Phase 41 (Provider Parity).**  The remaining subphases
  are either done or explicitly deferred: 41.3's "pad the system
  prompt to reach cache threshold" and 41.4's "API-driven context
  window fallback" stay deferred (current prompt already beats both
  thresholds; Anthropic's API doesn't expose window metadata); 41.6
  (cost display) is confirmed landed via ``/cost`` in CLI + shared
  slash dispatcher and the TUI model-info bar, with a new
  ``test_model_info_bar_shows_cache_hit_rate`` regression test that
  pins the ``cache: 80% hit`` render when Claude prompt caching is
  active; 41.8 (streaming chunk granularity) stays cosmetic/deferred.
  Phase 41 header now carries ``✓``.
- **Robust ops-tracing injection — Phase 25.10.**
  ``_inject_ops_tracing_into_charm_py`` in
  ``src/cantrip/agent/tools/charm.py`` now uses anchored multi-line
  regexes (``^import ops\r?$`` and a ``super().__init__(...)`` pattern
  that captures the leading indent) in place of literal
  ``str.replace`` calls.  Both anchors must match before the file is
  modified — previously the helper would insert ``import ops_tracing``
  without the paired ``ops_tracing.setup(self)`` call when the charm's
  ``__init__`` used a different argument name, leaving a ``NameError``
  at charm startup.  The injected setup line now matches the indent of
  the ``super().__init__`` call it follows (four-space charms no longer
  inherit the hardcoded eight-space indent).  Eight new unit tests
  pin the behaviour across argument-name variants, CRLF files,
  ``import ops.charm`` distraction, and multiple classes per file.
- **Tightened acceptance-failure detection — Phase 25.10.**
  ``_extract_acceptance_failures`` in ``src/cantrip/agent/autodeploy.py``
  anchors the area keyword with ``\b`` word boundaries and an optional
  plural, so ``actionable`` and ``relationship`` no longer pose as
  ``action``/``relation`` matches.  Bare ``error`` has been dropped
  from the prose alternation (it flagged "action executed without
  error" as a failure); ``fail*`` and ``broken`` remain as the
  explicit failure verbs.  A new negation guard discards prose matches
  like "no failures observed", "didn't fail", "never fail", and
  "without failures" — previously these falsely flagged the
  neighbouring area as failed and triggered a spurious acceptance-fix
  task.  Eight regression tests cover the new rejections.

### Added
- **Three new skills + CI scanner — Phase 34.3 + 34.4.**
  ``iterate-fix`` formalises the deploy-test-debug retry loop: when to
  run, how to triage failures by bucket (Environment / Deployment /
  Workload / Test) and severity, a three-attempt-per-failure budget,
  exit conditions, escalation triggers, and a structured
  ``[iterate-fix] attempt N/max`` end-of-iteration block.
  ``skill-writer`` documents how to author a new ``SKILL.md`` —
  frontmatter contract, depth gates (one subject per skill, split at
  500+ lines), ``EVAL.md`` scenarios, citation conventions, and
  prompt-injection hygiene.  ``skill-scanner`` describes the audit
  checks (prompt-injection phrases, unscoped authority, description
  drift, body length tiers, missing sections, bare external URLs,
  frontmatter validity).  The actual audit is implemented in
  ``src/cantrip/agent/skill_scanner.py`` and runs in CI via
  ``tests/unit/test_skill_scanner.py`` — any ``HIGH`` or ``MEDIUM``
  finding against a bundled skill fails the build.  19 unit tests
  cover the checks, and the ``operational-readiness`` description was
  shortened from 185 characters to ≤120 so the new CI guard starts
  green.
- **`main.py` project-identity constants — Phase 25.18.**  The two
  substrings that ``_is_cantrip_source_tree`` checks for in a
  ``pyproject.toml`` now live as named module constants
  (``_CANTRIP_PYPROJECT_NAME_MARKER``,
  ``_CANTRIP_PYPROJECT_ENTRY_MARKER``) with a comment explaining why
  *both* are required (a third-party package called ``cantrip`` would
  pass the first but not the second).
- **`gh_repo_bootstrap` tool — Phase 42.5.**  New agent tool that
  applies default repository settings after ``gh repo create``.  Writes
  ``.github/ISSUE_TEMPLATE/bug_report.md`` + ``feature_request.md`` and
  ``.github/workflows/ci.yaml`` stubs locally (existing files are
  skipped, not overwritten) and enables conservative branch protection
  on the default branch via ``gh api -X PUT
  repos/{slug}/branches/{branch}/protection``: one required approving
  review, force-pushes and deletions disabled, required-status-checks
  left null until CI has landed green.  Each step is independently
  opt-out (``branch_protection``, ``issue_templates``, ``ci_workflow``
  flags all default to ``True``); the repo slug is auto-detected via
  ``gh repo view`` when ``repo=`` is omitted.  API failures surface as
  warnings on the result rather than losing the local writes.  Closes
  the last open bullet on Phase 42.5.
- **`/update` slash command (Phase 63.5).**  A shared slash verb
  ``/update`` forces a cache-bypassing ``check_for_update`` and
  renders the verdict as a follow-up chat message — the three-line
  markdown notice (headline + PyPI link + installer-aware upgrade
  command) matches the exit-time prompt from Phase 63.4 and adds
  an explicit "restart Cantrip after upgrading" line so the user
  doesn't wonder why ``__version__`` hasn't moved mid-session.
  ``/update --no-check`` persists ``update_check_disabled = true``
  in ``~/.config/cantrip/settings.json`` via a new
  ``set_update_check_disabled`` helper that preserves unrelated
  keys; ``/update --check`` clears the opt-out.  Unknown flags or
  extra tokens render a two-line usage hint.  ``format_slash_notice``
  ships alongside the existing ``format_cli_notice`` so chat
  surfaces get markdown-styled output while piped CLI stdout stays
  compact.  ``/help`` (shared + CLI) lists the new verb; the
  ``design/UI.md`` Slash Commands section catalogues every
  cross-surface verb for the first time.  Backed by 15 new tests
  covering dispatch, toggle round-trip (including malformed-settings
  replacement and sibling-key preservation), usage hints, and all
  four follow-up branches (up-to-date / newer / disabled /
  OSError).  `COMMAND_CATALOGUE` entry and drift test mean the
  new verb surfaces in the TUI slash-autocomplete popup and the
  CLI readline Tab-completer without extra wiring.
- **Self-update notice in TUI, Web, and CLI (Phase 63.4).**  The
  three front-ends now surface a non-blocking "A newer cantrip is
  available" notice when the background PyPI check finds an upgrade.
  The TUI kicks the check off from ``on_mount`` as a Textual worker,
  stashes the verdict on the app, and prints a Rich panel from
  ``cantrip.main._run`` after the Textual screen tears down so the
  prompt never interrupts mid-session (matches ``toad``'s exit-time
  pattern).  The Web server runs the same helper once at startup,
  exposes the verdict via ``GET /api/update-status``, and broadcasts
  an ``update_available`` WebSocket event so reconnecting clients
  learn about it too; a dismissible banner at the top of the page
  remembers the dismissal per version in ``localStorage`` so a
  second dismissal isn't needed for the same release.  The
  ``--no-tui`` CLI starts the check as a background task in the
  REPL and prints a two-line notice (PyPI URL + installer-aware
  upgrade command) just before the REPL returns, keeping piped
  stdout short.  All three share
  ``~/.cache/cantrip/update.json`` so a user launching the TUI and
  then the Web UI ten minutes later doesn't double up on PyPI
  round-trips.  New ``format_cli_notice`` shared helper rides on
  ``upgrade_command`` / ``detect_install_method`` for parity across
  surfaces.  ``CANTRIP_NO_UPDATE_CHECK=1`` (env var) or
  ``update_check_disabled = true`` (``~/.config/cantrip/settings.json``)
  still opt out, as before.  Covered by 12 new tests across
  ``test_cli.py`` (post-REPL notice path, slow-check cancellation,
  no-update silence), ``test_main.py`` (``_print_update_panel`` /
  ``_truncate_notes`` / TUI dispatch handoff), ``test_web_server.py``
  (``/api/update-status`` payload shape, startup worker broadcasts
  for both available and null verdicts, error-path swallow), plus
  template + JS coverage that the banner DOM and dispatcher are
  wired up.  A tests-wide autouse fixture sets
  ``CANTRIP_NO_UPDATE_CHECK=1`` so unit tests never accidentally
  hit PyPI; the dedicated ``test_update.py`` suite re-enables the
  check per-test via its existing ``no_settings_optout`` fixture.
  ``docs/docs/reference-cli.html`` gains a "Self-update check"
  section plus entries for ``CANTRIP_NO_UPDATE_CHECK`` and
  ``CANTRIP_UPDATE_CACHE_DIR`` in the env-var table.
- **Changelog extraction + pre-release / yanked filter (Phase 63.2
  + 63.6).**  ``check_for_update`` now follows the version check
  with a fetch of ``CHANGELOG.md`` from
  ``raw.githubusercontent.com/<owner>/cantrip/v{latest}/CHANGELOG.md``.
  New ``fetch_changelog(version)`` returns the raw markdown body
  or ``None`` on 404 / HTTP failure (a pre-release that landed on
  ``main`` but wasn't tagged surfaces the version notice without
  inline notes).  The repo slug defaults to
  ``tonyandrewmeyer/cantrip`` and is overridable via
  ``CANTRIP_UPDATE_REPO`` for tests.  ``extract_release_notes(markdown,
  current, latest)`` walks ``## <version>`` headings line-by-line
  (no markdown-parser dependency), distinguishes ``## `` from
  ``### ``, accepts optional ``v`` prefixes, skips ``## Unreleased``,
  and returns ``[(version, body), ...]`` newest-first via
  ``packaging.version`` ordering.  ``UpdateInfo`` grows
  ``release_notes_markdown`` (concatenated, capped at 200 lines as
  a cache safety net) and ``installed_yanked`` (true when any file
  of the installed version is marked yanked on PyPI).
  ``include_release_notes=False`` skips the GitHub fetch when
  callers want a leaner payload.  Pre-release filter:
  ``_make_info_if_newer`` returns ``None`` when ``latest`` is a
  pre-release and ``current`` is stable — users on a stable don't
  get nagged about alphas, but pre-release users still see other
  pre-releases (and stable releases) since they've opted into the
  bleeding edge.  Cache shape extended to round-trip the new
  fields.  Covered by 24 new tests in
  ``tests/unit/test_update.py`` (72 in total): heading-walker
  edge cases (Unreleased skip, ``v``-prefix, range exclusivity,
  unparseable headings), changelog fetch happy / 404 / HTTP
  error / repo-slug override, end-to-end notes attachment +
  cache round-trip, pre-release filter in both directions,
  yanked detection with malformed-payload guards.
- **PyPI version-check + installer detection (Phase 63.1 + 63.3).**
  Library surface for the forthcoming "a newer Cantrip is available"
  notice.  New ``src/cantrip/update.py`` exposes
  ``async check_for_update(*, timeout=3.0, use_cache=True)`` which
  hits ``https://pypi.org/pypi/cantrip/json``, compares
  ``info.version`` to ``cantrip.__version__`` via
  ``packaging.version.parse``, and returns an ``UpdateInfo``
  dataclass (``current``, ``latest``, ``pypi_url``,
  ``release_timestamp``) or ``None`` when the user is current /
  opted out / a network call failed.  Results are cached at
  ``~/.cache/cantrip/update.json`` with a 24-hour TTL measured
  against the file's mtime, so the day-to-day startup path pays
  nothing.  Two opt-outs are honoured before any I/O:
  ``CANTRIP_NO_UPDATE_CHECK=1`` (accepts ``1`` / ``true`` / ``yes``
  / ``on`` case-insensitively) and ``update_check_disabled: true``
  in ``~/.config/cantrip/settings.json``.  Every failure path
  (``httpx.HTTPError``, DNS failure, timeout, JSON parse failure,
  unexpected PyPI schema, invalid version string, write-protected
  cache dir) degrades to ``None`` and logs at DEBUG only — the
  startup path can never trace out or be blocked by a slow PyPI.
  Companion ``detect_install_method()`` returns an ``InstallMethod``
  enum (``UV_TOOL`` / ``PIPX`` / ``PIP_USER`` / ``PIP_VENV`` /
  ``SNAP`` / ``UNKNOWN``) based on ``sys.executable`` heuristics,
  and ``upgrade_command(method)`` returns the copy-pasteable string
  (``uv tool upgrade cantrip`` etc.) or ``None`` for ``UNKNOWN`` so
  callers can fall through to the PyPI URL.  Fully library-only —
  no UI wiring yet; that lands in 63.2/63.4/63.5.  Covered by
  ``tests/unit/test_update.py`` (48 cases: version-comparison
  newer/equal/older/pre-release, every HTTP failure mode, both
  opt-outs in all their flavours, cache hit/miss/stale/corrupt,
  every installer heuristic with a pinned ``Path.home()`` fixture,
  and a "never crashes on weird paths" fuzz test).
- **On-theme activity labels (Phase 62).**  The status bar used to
  say ``⟳ Thinking...`` regardless of what the agent was up to; now
  it picks from a spellcasting-themed pool — *Conjuring…*,
  *Scrying…*, *Thumbing the grimoire…*, *Stirring the cauldron…*,
  *Casting bones on the table…* — so the UI matches the
  *cantrip*/*juju* naming.  New ``src/cantrip/ui/flavour.py`` holds
  the pool and a ``pick_activity_label(seed, category)`` helper;
  ``ActivityCategory`` splits divination (research) and forging
  (build) subsets out of the broad THINK default.  Wired into
  ``agent/core.py`` (both ``_publish_activity`` sites), ``agent/subagent.py``
  (both ``_set_phase`` re-entries to thinking), ``tui/app.py`` (the
  initial status-bar label on user send), and the Web UI's
  ``setThinking()`` handler.  ``⟳ Streaming...`` and ``⟳ running: …``
  stay literal — they describe output delivery and actual tool
  calls, not LLM cogitation.  Cadence: stable within a thinking
  phase, fresh pick every time the phase flips back to thinking
  (documented in ``design/UI.md``).  ``src/cantrip/web/static/cantrip.js``
  ships a JS mirror of the pool; a drift test in
  ``tests/unit/test_ui_flavour.py`` regexes the JS constant and
  diffs it against ``flavour.think_pool()`` so desynchronisation
  fails the build.
- **Blind A/B arena — ``/arena`` (Phase 47.5)** —
  new ``cantrip.agent.arena`` module runs two providers
  concurrently on the same prompt, shuffles the results into
  blinded ``A`` / ``B`` labels, and waits for the user to pick a
  winner.  ``/arena <prompt>`` is wired through the shared slash
  dispatcher with an async follow-up that awaits
  ``CantripAgent.begin_arena``; the follow-up's text is the blind
  A/B block.  All three surfaces (TUI, CLI, Web) intercept pending
  picks via ``agent.active_arena`` + ``handle_arena_pick`` before
  slash-dispatch or LLM routing — ``A`` / ``B`` / ``tie`` / ``skip``
  (and common synonyms like ``left`` / ``right`` / ``cancel``) are
  consumed, anything else falls through so users keep normal chat
  access while an arena waits for a verdict.  Recognised non-skip
  outcomes write a ``kind="fact"`` memory at ``scope="global"``
  with ``source="arena"`` — directional picks record "User
  preferred X over Y", ties record "User rated X and Y as
  equivalent"; every entry includes a 200-character prompt excerpt
  so the preference is attributable to a specific ask.  ``/help``
  lists the new command and ``COMMAND_CATALOGUE`` carries it for
  slash-autocomplete.  Covered by ``tests/unit/test_arena.py`` (38
  tests: pick parsing, blind shuffle determinism, duplicate-provider
  rejection, memory writes per outcome, reveal formatting),
  ``tests/unit/test_agent_arena.py`` (10 tests: begin/handle
  end-to-end against a real ``CantripAgent`` and ``MemoryManager``),
  and ``TestArena`` in ``tests/unit/test_slash_commands.py`` (2
  tests: bare-usage text and followup wiring).
- **Best-of-N racing — cost guardrails (Phase 47.4)** —
  ``RaceConfig`` grows a ``confirm_threshold_tokens`` soft gate and
  ``baseline_tokens_per_run`` estimate basis; the new
  ``RaceConfig.race_gate`` classifies a token estimate into one of
  three outcomes via ``RaceGate`` (``RACE`` / ``CONFIRM`` /
  ``DOWNGRADE``).  The executor's ``_dispatch_race_gate`` applies the
  classification: estimates below the threshold race silently,
  estimates between threshold and budget emit a
  ``race-confirm-<parent-id>`` CONFIRM task (blocking the parent
  pending user approval), and estimates above ``budget_tokens`` fall
  through to the single-subagent path with a ``race_downgraded``
  event.  ``CantripAgent.handle_race_confirmation`` resolves the
  CONFIRM, flips ``AgentTask.race_decision`` (``approved`` /
  ``declined``), and unblocks the parent so the second entry races
  or downgrades as the user chose.  TUI recognises the new prefix and
  maps yes/no / approve/decline / race/single replies through the
  handler.  Covered by ``TestRaceGate`` in ``tests/unit/test_race.py``
  (5 tests), ``TestDispatchRaceGate`` and
  ``TestExecuteTaskGateIntegration`` in
  ``tests/unit/test_executor_race.py`` (8 tests), and the new
  ``tests/unit/test_agent_race_confirm.py`` (3 tests covering approve,
  decline, and orphaned-CONFIRM graceful handling).
- **Best-of-N racing — executor wiring (Phase 47.3)** —
  ``BackgroundExecutor`` now dispatches race-eligible tasks to the
  coordinator.  A new ``_execute_race`` path builds candidate specs
  from the primary, light, and any ``extra_providers`` (deduped by
  model name), runs the race via the shared ``RaceCoordinator``, and
  merges the winner's worktree back into main via the existing
  ``_merge_worktree``.  Merge errors block the parent task and keep
  the branch for manual resolution; blocked / noop winners skip the
  merge.  Losing candidates' transcripts are preserved under composite
  ``{task_id}__{candidate_id}`` ids in ``subagent_messages``, and a
  ``race_candidate`` event per candidate ties the composite id back to
  the parent task so reviewers can find every candidate's trace.
  Opt-in via ``RaceConfig.enabled_categories`` — default config keeps
  the single-subagent path.  Covered by
  ``tests/unit/test_executor_race.py`` (18 tests: spec assembly and
  dedup, ``_should_race`` gate, merge-and-done, merge-error blocks,
  all-candidates-failed fail path, coordinator-raise fail path,
  blocked-winner no-merge, and factory transcript namespacing).
- **Best-of-N racing library (Phase 47.1 + 47.2 + 47.4 core)** — new
  ``cantrip.agent.race`` module with the scoring rubric, data types,
  and the ``RaceCoordinator`` needed to run N candidate subagents in
  parallel and pick a winner.  ``compute_score`` combines charmlint
  violations (weighted by severity, exponential decay),
  operational-readiness percentage, unit test pass ratio, and diff
  size into a single ``[0.0, 1.0]`` total; failed and no-op subagents
  score zero regardless of the other signals.  ``score_candidate``
  runs charmlint + readiness + ``git diff --numstat`` against a real
  worktree.  ``pick_winner`` picks the top viable candidate with
  deterministic tie-breaking (smaller diff, then candidate id).
  ``RaceCoordinator`` allocates per-candidate worktrees (composite
  ``task_id__candidate`` keys so they don't collide), spawns every
  candidate concurrently via a caller-supplied ``SubagentFactory``,
  scores outcomes, and releases losing worktrees while preserving the
  winner's branch for merge by the executor.  ``RaceConfig`` is
  opt-in — no category races by default; ``max_candidates`` clamps
  over-large pools; ``budget_tokens`` is surfaced for future CONFIRM
  gating.  The executor wiring and ``/arena`` slash command land in
  follow-up commits once the rubric is validated against real charm
  builds.  Covered by ``tests/unit/test_race.py`` (52 tests: subscore
  monotonicity, exit-state gating, tie-breaking, coordinator
  parallelism, worktree release policy, allocation-failure fallback,
  and one integration-style test that stands up a real git worktree).
- **Web UI resume banner** — parity with the CLI/TUI resume prompt.
  A banner across the top of the chat panel shows the prior-session
  summary with Resume / Start fresh / View transcript buttons.  The
  server defers ``load_state`` until the browser POSTs
  ``/api/session/decide`` so choosing Fresh leaves no polluted state
  behind.  New endpoints: ``GET /api/session/preview``,
  ``POST /api/session/decide`` (idempotent — second POST returns 409),
  ``GET /api/session/transcript?limit=N``.  The decision is shared
  across connected clients — first to pick wins.
- **Resume prompt on launch — CLI and TUI** — instead of silently
  loading whatever ``.cantrip`` file is on disk, Cantrip now asks
  [R]esume / [F]resh / [T]ranscript?  Fresh renames the old session to
  ``.cantrip.bak-<timestamp>`` so nothing is lost; Transcript shows the
  last 20 persisted messages inline before re-asking.  New helpers:
  ``CantripAgent.preview_session()`` peeks without mutating state,
  ``archive_session()`` handles the rename + store reset,
  ``transcript_tail(limit)`` returns the last N messages for review.
  The CLI uses a synchronous input prompt (falls back to silent-resume
  on non-TTY stdin so scripts keep working); the TUI shows a dedicated
  modal (``cantrip.tui.screens.resume.ResumePromptScreen``) pushed
  before the preflight / executor / watcher start, so choosing Fresh
  doesn't leave a polluted state behind.
- **TraceScreen shows real Grafana deep-links and honest reachability**
  — F4 no longer hard-codes ``...`` placeholders and a perpetual
  ``Status: Connected``.  A new ``cantrip.agent.cos_endpoints`` helper
  turns the watcher's cached COS status into a ``CosEndpoints`` value
  (Grafana URL lifted from the workload status message, Grafana-active
  flag, Tempo/Loki presence).  The screen builds Grafana Explore
  deep-links for Tempo and Loki with JSON ``left=`` panes preselecting
  the datasource, and renders a tri-state line: ``Not deployed`` /
  ``Unknown (no poll yet)`` / ``Reachable`` / ``Not reachable``.  When
  Grafana doesn't advertise a URL in its status message the screen
  falls back to ``http://localhost:3000`` and says so.  No new network
  calls — reachability is read from the existing watcher poll.
- **LogScreen dev/COS cycling** — ``m`` in the log viewer switches
  between the dev and COS models when both are bootstrapped.  No-op
  when only one is configured.  Title shows the active model.
- **GraphScreen status filter** — ``f`` in the integration graph
  cycles ``all → blocked → waiting → blocked+waiting`` so operators
  can zoom in on whichever apps need attention.  Edges that cross the
  filter boundary disappear and an explicit placeholder appears when
  the filter matches nothing.  The underlying ``build_graph()`` helper
  grew an optional ``status_filter`` kwarg.
- **Task-completion notifications** — opt-in terminal bell and desktop
  popups when a task reaches ``done`` or ``failed``.  Enable via
  ``CANTRIP_NOTIFY=bell|desktop|both`` (default ``off``); ``bell``
  writes ``\a`` to stderr, ``desktop`` shells out to ``notify-send`` on
  Linux and silently no-ops when ``notify-send`` isn't available.  The
  notifier dedupes by task id, so snapshot replays after reconnect
  don't stack beeps.  Wired into the TUI and CLI REPL; the web surface
  is deliberately unchanged (server-side notifications don't reach a
  browser).
- **`/export` slash command** — export the live session transcript
  without leaving Cantrip.  ``/export`` writes HTML to
  ``<charm>/transcript.html``; ``/export jsonl`` and
  ``/export markdown`` use the matching renderer; an optional trailing
  path argument overrides the destination.  Sits in the shared slash
  dispatcher, so the command is typeable in the TUI, CLI REPL, and Web
  surfaces and surfaces in the TUI's slash autocomplete popup.
- **Live-browser accessibility regression test** — new
  ``tests/integration/web/test_accessibility.py`` hosts the real
  aiohttp app on a thread and drives ``uvx rodney`` against it to
  assert the WCAG 2.1 AA invariants captured in
  ``design/WEB_UI_ACCESSIBILITY_AUDIT.md``: accessible names on the
  Send button and header buttons, ``role=log`` on the chat messages
  region, the chat input's programmatic label, the three overlays'
  dialog wiring (focus moves into the dialog on open and back to the
  trigger on Escape, ``aria-expanded`` flips, ``inert`` is applied to
  the backdrop), and computed white-on-accent-strong contrast ≥ 4.5:1
  for the Send button.  Complements the static template/CSS/JS checks
  in ``tests/unit/test_web_server.py::TestAccessibility`` by covering
  behaviours only a real browser can compute.  Self-skips when
  Chromium or ``uvx rodney`` isn't available, so CI collects the
  module without mandating either.

### Fixed
- **COS status pane clipped to one line when expanded** — the right
  column stacks ``#task-checklist`` + ``#charm-files`` + ``#juju-status``,
  and inside ``#juju-status`` the dev and COS sections render
  vertically.  Without ``overflow-y: auto`` on ``#juju-status``, an
  expanded COS section with more apps than fit in the pane's share of
  the column was clipped at the bottom: dev filled first, and cos got
  just enough room for the ``Model: cos (k8s)`` header before the rest
  was silently cut off.  Fix: ``overflow-y: auto`` on ``#juju-status``
  so the whole pane scrolls.  Regression guarded by a Textual pilot
  test that reads ``styles.overflow_y`` on the live widget.

### Changed
- **COS collapsed summary explains the numbers** — replaced the
  opaque ``Apps: 6  ○ 3/6`` form with a labelled breakdown that
  surfaces problem statuses first: e.g.
  ``6 apps · 1 blocked, 2 waiting, 3 active · 4 offers (click to expand)``.
  Every number is labelled (no bare fractions), error/blocked/waiting
  rank ahead of active so regressions don't hide, and the offers
  count hints that cross-model integrations are available.
- **COS offers listed in the expanded view** — ``JujuStatusWidget``
  now renders each ``status.offers`` entry as a one-liner
  ``<offer-name> (<app>) — <endpoint> (<interface>)`` below the app
  list.  In a Cantrip-managed COS model that's prometheus / loki /
  grafana / traefik-api endpoints, which answers the "what can my
  dev charm consume?" question at a glance.

### Fixed
- **Dev / COS status panes stayed empty** — the Always-On watcher was
  running and polling Juju correctly, but the event bus was never
  bound to the TUI's event loop.  With no bound loop, publishes from
  the same loop delivered synchronously on the UI thread, and the
  handlers' ``call_from_thread`` guard immediately raised
  ``RuntimeError``.  The error was swallowed by the bus's catch-all,
  so the status-poll ticks never made it to the widget.  Fix:
  ``on_mount`` now calls ``event_bus.bind_loop(asyncio.get_running_loop())``
  (matching ``cli.py`` and ``web/server.py``), and the six bus
  handlers drop their ``call_from_thread`` wrapping now that every
  publish is guaranteed to reach subscribers on the UI thread.  Also
  auto-detect a ``cos`` model alongside the dev model so the COS
  pane populates without requiring ``state.cos_model`` to be set by
  one of the narrow sprint-deploy code paths.

### Added
- **Syntax-highlighted file preview** — the content preview in the
  file detail modal now renders Python / YAML / TOML / JSON / Markdown
  / Rust / shell and every other Pygments-supported language with
  colour and Rich's line-number gutter.  Lexer is detected from the
  filename via ``Syntax.guess_lexer``; theme is ``ansi_dark`` so the
  highlight colours reuse the user's terminal palette and adapt across
  the Cantrip / Ubuntu / Monokai / Solarized-dark themes.  Binary and
  empty files still collapse to a plain dim notice.
- **Click a file in the charm tree to open a detail view** —
  selecting a file in the right-panel file tree now opens a
  ``FileDetailScreen`` modal instead of a one-line toast.  The
  modal shows size + modification time, a best-effort *purpose*
  summary (Python module docstring via AST, Markdown first H1 +
  paragraph, charmcraft/metadata YAML ``summary``/``description``,
  ``pyproject.toml`` ``[project].description``, or a short fallback
  line), the last five ``git log`` entries that touched the file
  (formatted with short SHA, relative age, author, subject), and a
  numbered content preview truncated to 120 lines / 32 KB.  Binary
  files are detected and previewed as a dim notice instead.  Press
  ``r`` to refresh or ``Esc`` to close.

### Changed
- **Phase 58 complete — Rust coverage wired into CI** — the
  ``rust-test`` matrix job now runs ``cargo llvm-cov --summary-only
  --json`` after ``cargo test``.  Per-file line coverage is compared
  against a 60% advisory threshold and emitted as
  ``::warning file=…`` annotations that show up inline on PRs but
  don't fail the build.  New ``make rust-coverage`` target mirrors
  the CI invocation locally (requires a one-time
  ``cargo install cargo-llvm-cov && rustup component add
  llvm-tools-preview``).  Baseline on landing: charmlint-rs 89.6%,
  quickpack-rs 78.0%, no file under 60%.
- **Phase 57 complete — total coverage 88%** — ``tui/themes.py``
  (the last file under the 50% floor) goes from 47% to 93% with a
  new ``tests/unit/test_themes.py`` covering the YAML theme loader,
  user-directory discovery, and bundled-theme registration.  All
  Phase 57 exit criteria now met: ≥85% total coverage, no file under
  50%, zero ``pytest tests/unit`` warnings, unit-test files
  organised to match source-file boundaries.
- **Core-agent coverage — 62% → 87%** — Phase 57.6 complete.
  Three new focused test files land alongside ``test_agent.py``:
  ``test_agent_github.py`` (37 tests: every PR / issue-triage /
  bootstrap helper with ``git_branch`` + ``github_issues`` patched so
  no ``gh`` / ``git`` subprocesses run), ``test_agent_confirmations.py``
  (8 tests: ``handle_design_confirmation`` / ``handle_day2_confirmation``
  happy paths and early-exit branches, planner mocked), and
  ``test_agent_lifecycle.py`` (22 tests: ``start_executor`` /
  ``stop_executor``, ``build_resume_summary``, ``load_state`` error
  and restoration branches, MCP registry / start / stop plumbing,
  ``_on_mcp_elicitation`` bridge).  No production-code changes.
- **TUI screen coverage — Pilot tests for the three thinnest screens**
  — Phase 57.5 landed.  ``tui/screens/relation.py`` goes from 0% to
  99% via a new ``tests/unit/test_relation_screen.py`` that drives
  mount / fetch / render with ``subprocess.run`` mocked (matching,
  no-match, symmetric, error, unparseable, refresh branches).
  ``tui/screens/questions.py`` goes from 30% to 100% via Pilot tests
  for suggestion clicks, free-form submission, skip/previous, escape
  cancel, and dismiss-on-last-question.  ``tui/app.py`` goes from 42%
  to 66% via a new ``tests/unit/test_tui_actions.py`` targeting
  F6–F9/Ctrl-F bindings, every bus handler (memory, status bar, task
  updated, watcher event), worker-completion branches for
  ``/feelings`` and MCP marketplace, every branch of the bootstrap /
  push / triage response handlers, the confirmation presenters,
  ``action_toggle_watcher``, and ``action_quit``.  No production-code
  changes.
- **Watcher is always on; dev model auto-detected** — removed the
  ``--watcher`` CLI flag.  The TUI now subscribes to watcher events at
  startup and tries to start the watcher immediately, falling back to
  the currently-active Juju model (via ``juju models``) when
  ``state.dev_model`` is still empty.  If no model exists yet, the TUI
  retries every 5 seconds so the Dev / COS status panes populate as
  soon as the agent provisions one — no more staying on
  "Not connected" / "Not deployed" for the whole session.  ``F5`` now
  pauses/resumes the already-running watcher.
- **Task pane is more informative during initial research** — the
  "Preparing environment" group collapses to a single
  ``✓ Preparing environment · ready`` line once all checks pass, a
  transient ``⟳ Planning tasks…`` row appears while the agent is
  deciding what to do before ``plan_tasks`` runs, and the active
  subagent's phase is mirrored into the status bar so live research
  activity (``⟳ title · searching web``, etc.) is visible without
  having to expand the task pane.
- **Tools unit tests reorganised** — the monolithic
  ``tests/unit/test_tools.py`` (1739 lines) folded per-tool: the file-
  tool tests were dropped as duplicates of ``test_file_tools.py``
  with the two unique cases (sibling-prefix path attack and
  read-only-directory write) preserved by lifting them into
  ``test_file_tools.py``; testing-helper tests
  (TestBuildPytestTarget, TestParseCoverageTotal) folded into
  ``test_testing_tools.py``; concierge / provisioning tests moved to
  a new ``test_environment_tools.py``; charm-tool tests split into
  ``tests/unit/charm_tools/`` (analyse framework, charmcraft init /
  pack, inject coverage / workflows).  No production-code changes;
  Phase 57.7 complete (all four oversized unit-test files now split
  to ≤600-line per-concern modules; the M57 unit-test cleanup
  milestone advances).
- **Subagent unit tests reorganised** — the monolithic
  ``tests/unit/test_subagent.py`` (1621 lines, 120 tests) split into
  seven per-concern files under ``tests/unit/subagent/`` mirroring
  the ``tests/unit/charmlint/``, ``tests/unit/quickpack/``,
  ``tests/unit/executor/``, and ``tests/unit/planner/`` layouts:
  ``test_context.py`` (SubagentContext / SubagentResult / exit
  signalling), ``test_helpers.py`` (filter / select-provider /
  tools-for-llm / parse-exit-state / truncate), ``test_prompt.py``
  (prompt builder, task instruction, research / design / red-green /
  commit / self-verification / demo guidance), ``test_run.py``
  (Subagent.run / retry / tool execution / max rounds / phase
  reporting), ``test_concurrency.py``, ``test_throttle.py``, and
  ``test_allowlists.py`` (per-category tool allowlists).  Shared
  helpers (``_make_tool``, ``_make_context``) moved to
  ``tests/unit/subagent/conftest.py``.  Each file ≤419 lines; no
  test content changed.  Phase 57.7 advances (three of four files
  done).
- **Planner unit tests reorganised** — the monolithic
  ``tests/unit/test_planner.py`` (1706 lines, 152 tests) split into
  nine per-concern files under ``tests/unit/planner/`` mirroring the
  ``tests/unit/charmlint/`` and ``tests/unit/quickpack/`` layouts:
  ``test_parsing.py`` (JSON extraction + task-list / merge helpers),
  ``test_paths.py`` (fast / sprint / one-shot / improvement path
  detection plus their deterministic plan helpers), ``test_planner.py``
  (TaskPlanner.plan / replan, unique IDs, PlanningContext fields),
  ``test_prompts.py`` (prompt builders), ``test_design.py``
  (PlanFromDesign + red/green build sequence), ``test_improvement.py``
  (PlanImprovementFixes), ``test_day2.py`` (day-2 ops phase /
  FindDay2Anchor / PlanFromDay2Findings), ``test_operability.py``
  (operability assessment + fixes), and ``test_tool.py``
  (PlanTasksTool).  Each file ≤283 lines; no test content changed.
  Phase 57.7 advances (two of four files done).
- **Executor unit tests reorganised** — the monolithic
  ``tests/unit/test_executor.py`` (1972 lines, 107 tests) split into
  six per-concern files under ``tests/unit/executor/`` mirroring the
  ``tests/unit/charmlint/`` and ``tests/unit/quickpack/`` layouts:
  ``test_lifecycle.py`` (start / stop / pause / resume / graceful
  shutdown), ``test_execution.py`` (build_context, execute_task,
  handle_confirm, category timeouts), ``test_run_loop.py`` (run loop,
  callbacks, concurrency), ``test_followup.py`` (followup tasks,
  design handoff, noop detection), ``test_git.py`` (uncommitted /
  precheck / snapshot / revert), and ``test_errors.py`` (exit-state /
  error-resilience / usage recording).  Shared helpers moved to
  ``tests/unit/executor/conftest.py``.  Each file ≤478 lines; no test
  content changed.  Phase 57.7 partially advanced (one of four files
  done).
- **Quickpack unit tests reorganised** — the monolithic
  ``tests/unit/test_quickpack.py`` (977 lines) split into per-module
  files under ``tests/unit/quickpack/`` mirroring the
  ``tests/unit/charmlint/`` layout: ``test_jujuignore.py``,
  ``test_metadata.py``, ``test_parts.py`` (with the attestation
  tests that exercise ``quickpack.parts``), ``test_pack.py``, and
  ``test_cli.py``.  The shared ``charm_project`` fixture moved to
  ``tests/unit/quickpack/conftest.py``.
  ``test_jujuignore_properties.py`` and
  ``test_quickpack_comparison.py`` moved under the same directory
  (``test_comparison.py``).  No test content changed; Phase 57.8
  complete.

### Added
- **Slash-command autocomplete in the TUI** — typing ``/`` in the chat
  input now surfaces a catalogue-driven popup above the input with
  every matching verb.  Up/Down move the highlight, Tab accepts the
  active suggestion (or the sole match if only one catalogue entry
  still matches), Escape dismisses, and Enter submits what you see.
  The shared ``COMMAND_CATALOGUE`` in ``cantrip.agent.slash_commands``
  is the single source of truth; the TUI extends it with ``/feelings``
  so the popup covers TUI-native verbs too. A unit test asserts the
  catalogue covers every verb the dispatcher handles, guarding
  against drift when new verbs land.
- **Slash-command Tab-completion in the CLI** — the REPL now wires
  Python's ``readline`` against the same catalogue (plus the CLI-only
  ``/tasks`` and ``/status`` verbs).  Typing ``/c`` and pressing Tab
  completes to ``/cost``; cycling through multiple matches via Tab
  works as usual.  Gracefully no-ops on systems without ``readline``
  (Windows, stripped containers) and picks the right parse-bind syntax
  for GNU readline vs. libedit.
- **Hypothesis-based property tests for the planner's dependency graph**
  — ``hypothesis`` is now a dev-dep with two registered profiles
  (``dev`` at 100 examples, ``ci`` at 500) selected via the
  ``CANTRIP_HYPOTHESIS_PROFILE`` env var.  A new
  ``tests/unit/test_planner_properties.py`` covers
  ``_validate_dependencies`` with six invariants: the task set is
  preserved, no phantom deps remain, the result is always acyclic,
  acyclic input with valid refs is passed through unchanged, the
  function is idempotent, and the result is always a sub-graph of the
  input (only edge stripping, never invention).
- **Hypothesis-based property tests for the watcher status-diff**
  — ``tests/unit/test_watcher_properties.py`` covers
  ``diff_snapshots`` with nine invariants: ``diff_snapshots(None, s)``
  is always empty, self-diff is empty, events always reference real
  apps/units, every event carries ``source="status"``, dedup keys are
  always populated, and swap-symmetry holds for add/remove event
  counts across apps, units, and cross-model offers.
- **Hypothesis-based property tests for quickpack's .jujuignore
  matcher** — ``tests/unit/quickpack/test_jujuignore_properties.py``
  covers ``JujuIgnore`` with six invariants: determinism, construction
  never raises on arbitrary patterns, default VCS ignores still bite
  regardless of user patterns, comments and blank lines are no-ops,
  ``[P, !P]`` un-ignores, and a later plain ``P`` does not override
  an earlier ``!P`` (``JujuIgnore.match``'s early-break semantics,
  distinct from gitignore's latest-rule-wins).
- **Hypothesis-based property tests for the charmlint rule engine**
  — ``tests/unit/charmlint/test_properties.py`` throws arbitrary
  structurally-valid ``charmcraft.yaml`` dicts at ``lint()`` and
  asserts three invariants: ``lint()`` never raises, its output is
  deterministic (sort-normalised diagnostic tuples match across
  repeated runs), and every ``Diagnostic`` has populated
  ``rule_id`` / ``severity`` / ``message`` fields (with ``line``
  never set without ``path``).  Completes Phase 59.

### Fixed
- **Gemini rate-limit errors show the retry hint and quota kind** —
  Gemini 429 responses carry a "Please retry in …" hint and a
  ``QuotaFailure`` detail naming the metric that tripped
  (per-minute vs. per-day).  Cantrip now parses both and includes
  them in the message surfaced to the chat, so users can tell a
  transient backoff from an exhausted daily quota.  The TUI agent
  worker also runs with ``exit_on_error=False`` so a provider raise
  lands as an in-chat error instead of taking the app down.
- **Main-agent tool activity visible in the status bar** — slow tools
  like ``charmcraft pack`` and ``juju deploy`` used to run silently
  while the bar showed "Thinking..." for minutes.  The main agent now
  publishes ``STATUS_BAR_CHANGED`` events around every tool call (in
  both the streaming and non-streaming conversation loops) and the TUI
  subscribes so the bar shows "⟳ running: charmcraft_pack" while the
  tool is in flight.
- **Model panes populate on first poll** — the TUI's multi-model status
  widget previously only refreshed when the watcher emitted a *diff*
  event, so on a stable system (or right after start-up) the dev and
  COS panes both showed "Not connected" / "Not deployed" even though
  the watcher was polling successfully.  The watcher now fires an
  ``on_status_poll`` callback after every dev/cos poll; the agent
  publishes it as ``JUJU_STATUS_CHANGED`` on the UI bus, and the TUI
  subscribes so the panes populate on the first successful poll.

### Added
- **`juju_trust` tool** — wraps ``jubilant.Juju.trust`` so the agent can
  grant (or revoke) cluster-scope trust when a deployed companion such
  as MongoDB blocks with *"Run `juju trust mongodb --scope=cluster`"*.
  The deploy subagent prompt now tells the agent to inspect blocked
  companions and follow actionable status messages (``juju_trust``,
  ``juju_relate``, ``juju_config``) before escalating.
- **Research-driven e2e test** — a new
  ``tests/e2e/test_research_charm_build.py`` hands the agent a
  minimal, user-style prompt (*"build a Kubernetes charm for Redis
  using the public redis:7-alpine image, deploy to this model"*) and
  leaves framework detection, planning, scaffolding, packing and
  deployment entirely to the agent.  Nudges are milestone-level
  (*"what's the next concrete step toward a packed .charm?"*) rather
  than tool-level so the test exercises the research and planning
  parts of the loop that the prescriptive PaaS tests bypass.
- **Bulked-out e2e charm-build suite** — the live Flask test that lived
  in ``tests/e2e/test_real_charm_build.py`` has been refactored into a
  reusable harness (``tests/e2e/harness.py``) and parametrised across
  Flask, Django, FastAPI, and Go (``test_paas_charm_build.py``).  A
  new ``test_machine_charm_build.py`` exercises the non-PaaS path by
  scaffolding with ``charmcraft init --profile machine`` and deploying
  to an LXD controller.  The Go case skips rockcraft and deploys with
  a pre-built public OCI image to keep the test quick.  Seed apps live
  in ``tests/e2e/seeds.py`` so adding a new framework is now a
  ~20-line change.
- **Shared slash-command dispatcher** — new
  ``cantrip/agent/slash_commands.py`` hosts a single ``dispatch()`` and
  ``SlashResult`` dataclass that all three surfaces (CLI, TUI, Web) now
  route through for ``/help``, ``/memory``, ``/remember``, ``/forget``,
  ``/mcp`` and ``/cost``.  Previously each surface duplicated its own
  dispatch logic, which left ``/memory``, ``/remember``, ``/forget`` and
  ``/mcp`` missing from the CLI; those now work there too.  Async
  follow-ups (e.g. ``/mcp marketplace``'s network fetch) are surfaced
  via ``SlashResult.followup`` so surfaces can show an immediate
  prelude and render the result once it arrives.  Surface-native
  commands with custom formatting or side effects (``/tasks``,
  ``/status``, ``/feelings``) stay on their original surface.

### Performance
- **Faster TUI startup** — ``cantrip/agent/tools/__init__.py`` previously
  imported all ~100 tool classes at package-import time, adding ~1.6s
  to every ``cantrip`` invocation even when the TUI never built an
  agent.  Tool-class imports are now deferred into ``build_tools()``
  (the only caller that needs them), and the seven TUI screen modules
  (``help``, ``logs``, ``graph``, ``traces``, ``relation``,
  ``transcript``, ``questions``) are imported lazily inside their
  action handlers instead of at ``cantrip.tui.app`` module scope.
  Importing ``cantrip.agent.tools`` drops from ~1.6s to ~75ms, and
  ``cantrip --help`` goes from ~1.3s to ~0.85s.

### Fixed
- **PaaS charms shipped without ``paas-charm`` in ``requirements.txt``**
  — when the agent co-located a 12-factor app's source with the
  scaffolded charm it sometimes overwrote ``requirements.txt`` (e.g.
  ``cp app.py requirements.txt flask-demo/``), wiping the charm-side
  ``ops`` and ``paas-charm`` lines that ``charmcraft init`` had
  generated.  The resulting ``.charm`` packed successfully but crashed
  at install with ``ModuleNotFoundError: No module named 'paas_charm'``.
  A new ``_ensure_paas_requirements`` guard in ``agent/tools/charm.py``
  re-asserts ``ops`` and ``paas-charm`` both after ``charmcraft_init``
  and before ``charmcraft_pack`` — app deps are preserved, no
  duplicates are introduced, and ``ops-tracing`` is no longer
  mis-identified as ``ops``.  The ``twelve-factor`` skill now
  documents the merge-don't-overwrite rule explicitly.
- **Slash commands were unreachable in the TUI** — pressing ``/`` in an
  empty chat input opened the search bar, which swallowed the leading
  character so ``/help``, ``/memory``, ``/mcp``, ``/feelings`` (and now
  ``/quit`` / ``/exit``) could never actually be typed.  The ``/``
  shortcut for search is gone; Ctrl+F still opens search, and ``/`` is
  now a normal character that starts a slash command.
- **Preflight COS creation failed when the model already existed on a
  separate K8s controller** — when the current controller was IAAS
  (LXD) but ``cos`` already existed on a sibling K8s controller (e.g.
  ``concierge-k8s``), the existence check ran against the LXD
  controller, raised ``CLIError``, and fell through to ``juju
  add-model cos -c concierge-k8s`` which then failed because the
  model was already there.  The runner now resolves the target
  controller up front and uses ``controller:model`` syntax for
  status, model creation, and offer setup.
- **Planner crashed on malformed LLM task items** — a single item
  missing a ``title`` (common with smaller Gemini flash responses)
  caused the whole replanning call to fail.  The parser now accepts
  ``name`` / ``task`` / ``summary`` as title fallbacks, skips
  individual malformed items with a warning, and logs the raw LLM
  content when the batch cannot be parsed.
- **Streaming sentences run together across tool-call rounds** — the
  agent's streaming conversation loop concatenated each round's text
  directly, so a round ending ``"Let me check the file."`` followed by
  a round starting ``"The file contains X."`` rendered as
  ``"file.The file contains"``.  A ``"\n\n"`` separator is now injected
  between rounds when the previous round produced non-whitespace text.
- **Inference-snap streaming crashed on empty-choices frames** — some
  OpenAI-compatible servers emit a usage-only final frame with
  ``"choices": []``; the streamer's ``[0]`` index raised
  ``IndexError``.  The access is now guarded so both missing-key and
  empty-list frames are tolerated.

### Added
- **``/quit`` and ``/exit`` slash commands** — both cleanly shut down
  the CLI REPL and TUI (the TUI delays the exit by one refresh tick
  so the goodbye message renders first).  ``SlashResult`` gained a
  ``quit`` flag that surfaces honour.  The Web surface ignores the
  flag — browser sessions aren't "quittable" in the same sense.
- **Live subagent phase in the task pane** — every in-flight task now
  shows a dim secondary line under its pinned row reporting what the
  subagent is currently doing ("thinking" or "running:
  charmcraft_init, juju_deploy") plus an elapsed counter.  Two new
  transient fields on ``AgentTask`` — ``subagent_phase`` and
  ``subagent_started_at`` — are updated by the subagent around each
  LLM call and tool round and surfaced via the existing
  ``TASK_UPDATED`` event; the TUI widget redraws every 0.5 s while a
  phase is live so the counter stays accurate.

### Changed
- **TUI welcome screen rewritten with better examples** — the landing
  text no longer suggests "charm a PostgreSQL deployment" (there's
  already an excellent postgres charm on Charmhub) and the help
  screen no longer suggests "add postgresql integration".  The
  welcome now has a clear title line, a one-sentence description,
  and four example prompts that showcase Cantrip's range: fresh
  workload ("my Flask app at ./backend"), a novel target (Overleaf),
  a source-URL build, and improve mode.  Styled with visible
  hierarchy (bold title, accent-coloured example bullets, muted
  shortcut footer) rather than a single block of muted text.
- **Task pane keeps the in-flight work visible** — active, failed, and
  blocked tasks are pinned to a top "In progress" section regardless
  of category order, and fully-completed category groups collapse to a
  single "✓ N tasks done (click to show)" row so a long finished phase
  no longer pushes the current work off-screen.
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
- **MCP marketplace discovery (Phase 45.5)** — closes Phase 45.  Cantrip
  can now pull MCP-server catalogues from user-supplied marketplaces in
  the Codex / Cursor / Claude Code format.  Three source kinds declared
  in a new top-level ``marketplaces:`` block in ``cantrip.mcp.yaml``:
  ``github: <owner>/<repo>``, ``directory: <path>``, ``url: <url>``.
  ``MarketplaceLoader`` caches at ``~/.cache/cantrip/marketplaces/``
  with a 24-hour TTL and skips failed sources rather than crashing.
  ``/mcp marketplace`` lists servers grouped by source with description,
  install hint, required env vars, and OAuth scopes; ``/mcp marketplace
  refresh`` bypasses the cache.  Cantrip never auto-installs — the user
  copies the descriptor into their own config after reviewing it.  New
  ``design/MCP_SERVERS.md`` documents authoring Charmhub / Launchpad /
  Grafana / Snapcraft / Charmcraft / MAAS MCP servers (Python SDK
  example, tool conventions, schema reference, authoring checklist,
  local-test recipe).  34 unit tests cover source parsing, the YAML
  loader, the cache layer, and the slash-command output for every
  shape and error path.
- **MCP OAuth 2.1 flow for HTTP servers (Phase 45.4b)** — closes Phase
  45.4.  HTTP MCP servers can now require OAuth and Cantrip walks the
  user through the full PKCE flow, with refresh tokens persisted to the
  Phase 45.4a ``FileTokenStorage``.  ``OAuthConfig`` on ``ServerConfig``
  (``client_name``, ``scopes``, ``redirect_port``, ``client_metadata_url``)
  with full YAML schema validation — non-mapping value, blank
  ``client_name``, non-integer/out-of-range ``redirect_port``, and
  ``oauth`` on a stdio server are all rejected with clear messages.
  ``cantrip.mcp.oauth`` provides the redirect handler (opens the URL via
  ``webbrowser``, falls back to a logged URL on headless systems) and
  the localhost callback listener (aiohttp on ``127.0.0.1:<port>``,
  captures one ``GET /callback?code=…&state=…``, tears down).  Every
  failure mode surfaces cleanly: OAuth error → ``OSError``, missing
  code → ``OSError``, port-in-use → ``OSError``, user-walks-away →
  ``TimeoutError``.  ``MCPClient`` builds the SDK's
  ``OAuthClientProvider`` and wires it through ``streamablehttp_client``
  whenever ``oauth`` is set; cross-field validation rejects ``oauth``
  on stdio at start time too.  25 unit tests cover YAML parsing,
  redirect handler, localhost callback (success / error / missing /
  timeout / bind failure), client metadata builder, and MCPClient
  wiring.
- **MCP elicitation routing (Phase 45.4c)** — server-driven mid-tool-call
  prompts now bridge to the UI event bus.  ``ElicitationManager`` per
  ``MCPClient`` parks each request on an ``asyncio.Future``, fires
  ``MCP_ELICITATION_REQUEST`` via the event bus, and waits for the UI
  to call ``agent.complete_mcp_elicitation(request_id, action, content)``.
  Bounded 600s timeout auto-declines runaway requests; ``cancel_all``
  on shutdown auto-declines everything pending so the SDK never hangs.
  ``MCPRegistry`` fans the callback out to every server and routes
  completion by request id across all servers.  Both ``form`` and
  ``url`` modes surface verbatim through the event payload.  14 unit
  tests cover round-trip accept/decline, timeout, unknown id, invalid
  action, callback-failure isolation, cross-server routing.  TUI/Web
  prompt rendering deferred — the event is emitted; building an
  interactive form widget for it is a follow-up.
- **MCP token storage with GPG opt-in (Phase 45.4a)** — file-backed
  ``FileTokenStorage`` implements the SDK's ``TokenStorage`` protocol
  with per-server JSON files under ``~/.config/cantrip/mcp_tokens/``.
  Per-server dirs at ``0700``, files at ``0600``, atomic ``rename``
  writes.  Optional ``CANTRIP_MCP_GPG_TOKENS=1`` opt-in runs
  ``gpg --batch --yes --symmetric`` on every write, matching the
  existing ``CANTRIP_GPG_SIGN`` pattern.  Malformed/unreadable files
  degrade to ``None`` so the SDK falls back to a fresh OAuth flow
  rather than crashing.  23 unit tests including a live GPG round-trip
  that verifies no plaintext leaks.  OAuth flow integration (browser
  redirect + localhost callback + OAuthClientProvider wiring) deferred
  to a focused follow-up.
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
- **``ROADMAP.md`` split into active + archive.** Completed phases (51 of
  them, plus the legacy Phases 0–3 summary) moved verbatim into a new
  ``ROADMAP_ARCHIVE.md``; ``ROADMAP.md`` now contains only open work
  (~2.5k lines vs. ~8.7k previously). Preamble, open phases, and the
  ``Dependencies and Blockers`` / ``Milestones`` sections stay in place.
  ``AGENTS.md`` and ``README.md`` updated to point at both files.

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
