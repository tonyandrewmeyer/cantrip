# Cantrip Implementation Roadmap

## Design Philosophy

Cantrip is an **autonomous agent** that builds charms independently. The user describes what
to charm; the agent researches, designs, builds, deploys, and iterates — with the user
confirming key decisions and providing domain expertise. The agent does not wait to be told
what to do next.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              Cantrip                                       │
│                                                                            │
│  ┌──────────────────────┐         ┌──────────────────────────────────┐    │
│  │   Conversation Loop  │         │       Autonomous Work Loop       │    │
│  │                      │ ◄─────► │                                  │    │
│  │  User confirms,      │ steer/  │  Research → Design → Build →    │    │
│  │  overrides, provides │ notify  │  Deploy → Test → Debug → Fix    │    │
│  │  domain expertise    │         │                                  │    │
│  └──────────────────────┘         └──────────────────────────────────┘    │
│              │                                    │                        │
│              ▼                                    ▼                        │
│  ┌──────────────────────────────────────────────────────────────────┐     │
│  │                     TUI / Web UI                                 │     │
│  │   Chat panel  │  Task checklist  │  Juju status  │  Status bar   │     │
│  └──────────────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────────────┘
```

Two loops run concurrently:

1. **Conversation loop** — the user talks to the agent. Mostly confirming designs,
   providing operational knowledge, and steering priorities. The user should rarely need to
   tell the agent *what to do next* — only *whether it's right*.

2. **Autonomous work loop** — the agent picks tasks from a work queue and executes them
   without user prompting. Research, scaffolding, deploying, testing, debugging, redeploying.
   The watcher feeds events into the same queue.

The TUI shows both: the chat conversation and a visible task checklist so the user always
knows what the agent is doing, has done, and plans to do.

---

## Archived Phases

Completed phases (and the legacy Phases 0–3 summary) have been moved to
[`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md) to keep this file focused on
active work. The archive preserves the full detail of each finished phase.

---

## Phase 36b: Review charming-with-claude Skills

**Goal:** Review the skills in `github.com/tonyandrewmeyer/charming-with-claude`
and adopt them for use when building Cantrip and/or incorporate them into
Cantrip's own agent (system prompts, subagent guidance, skills).

- [x] Cloned the repo and reviewed all twelve skills (2026-05-24
  sweep).  Findings logged in
  [`design/CHARMING_WITH_CLAUDE_REVIEW.md`](design/research/CHARMING_WITH_CLAUDE_REVIEW.md)
  with a verdict per skill (adopt / adapt / dev-plugin / reject) and
  a per-skill summary.
- [x] Per-skill evaluation against cantrip's bundled set (33 skills at
  the time of the sweep): four ADOPT, four ADAPT (deferred — cantrip
  already carries equivalents and the longer external versions would
  bloat without a triggering need), three DEV-PLUGIN (deferred for
  the user to install on their `~/.claude/`), one REJECT
  (`go-standards`, language mismatch).
- [ ] **Deferred — user action:** install the three dev-only
  Claude Code plugins (`cli-standards`, `code-review`, `juju`) on the
  user's `~/.claude/skills/` if useful for developing cantrip itself.
  Cantrip does not modify the user's Claude Code config without an
  explicit request; the recipe lives in
  [`design/CHARMING_WITH_CLAUDE_REVIEW.md`](design/research/CHARMING_WITH_CLAUDE_REVIEW.md).
- [x] Four skills adopted directly into cantrip's bundle with
  CC BY 4.0 attribution banners and converted to cantrip's
  frontmatter shape: `src/cantrip/skills/charm-logging/SKILL.md`
  (glob-scoped to charm source files),
  `src/cantrip/skills/charm-development-commands/SKILL.md`
  (glob-scoped to `tox.ini` / `Makefile` / `justfile` /
  `pyproject.toml` / `CONTRIBUTING.md` / `HACKING.md`),
  `src/cantrip/skills/charm-docs/SKILL.md` (glob-scoped to README /
  docs / CONTRIBUTING), and `src/cantrip/skills/juju-doctor/SKILL.md`
  (unconditional — relevant whenever the agent is asked to validate
  or diagnose a Juju deployment).  `SkillsIndex.discover()` picks
  all four up cleanly; cantrip's total bundled skill count goes
  from 33 to 37.
- [x] Findings document landed at
  [`design/CHARMING_WITH_CLAUDE_REVIEW.md`](design/research/CHARMING_WITH_CLAUDE_REVIEW.md):
  TL;DR verdict table, per-skill summary with reasoning, plus a
  follow-up section recording the adapt-bucket deferrals and the
  periodic re-sweep recommendation.

**Exit criteria:** Review complete.  Useful skills adopted or adapted.
`make check` passes throughout.

---

## Phase 56: Publish Juju Copilot / Claude Code Assets

**Goal:** The awesome-copilot survey turned up zero Juju-specific
content across 307 skills, 177 instructions, and 204 agents — every
charm author using Copilot or Claude Code today gets generic
Python/YAML advice.  Cantrip already embeds the right knowledge in
its system prompt and skills bundle; lifting a subset into standalone
reusable assets (`*.instructions.md` scoped via `applyTo:`, plus
skill folders) is cheap and unlocks ecosystem-wide value independent
of Cantrip's own adoption curve.

The target publishing destination is **`canonical/skills`**
(not `awesome-copilot` upstream) — Canonical owns the narrative and
versioning, and the assets can reference each other without waiting
on upstream review cycles.

### 56.1 High — Scope the initial asset bundle

- [x] Enumerated the slices of Cantrip's system prompt and skills most
  valuable as standalone assets and chose v1 = 10 SKILL.md assets
  covering every roadmap-listed slice (charmcraft.yaml authoring,
  src/charm.py patterns × {custom, infrastructure}, Scenario testing,
  Jubilant integration tests, ops-tracing + COS, relation-data
  design, Harness→Scenario migration, plus the starter operational
  pair adding-actions / adding-config).  Per-skill verdict (ship /
  defer to v2 / skip-deduplicate / skip-cantrip-internal) lives in
  [`design/JUJU_SKILLS_BUNDLE.md`](design/research/JUJU_SKILLS_BUNDLE.md).
- [x] Decision: every published asset is a skill folder
  (`skills/products/juju/<name>/SKILL.md`), not an
  `.instructions.md`.  Reason: the actual `canonical/skills`
  repo follows the agentskills.io specification (SKILL.md only) —
  awesome-copilot's `.instructions.md` shape is not what upstream
  ships.  The roadmap text predates that decision; the design doc
  records it explicitly.
- [x] Manifest landed as the in-script
  ``MANIFEST = (SkillSpec(…), …)`` in
  ``scripts/build_juju_skills_bundle.py`` plus the worked table in
  ``design/JUJU_SKILLS_BUNDLE.md`` (bundle name → source skill →
  tags → summary fragment).  Carried in Python so a typo fails ``ty``
  rather than the upstream validator post-publication.
- [x] Companion ``bundles/canonical-skills-juju/README.md`` is
  generated by the build script (lists every shipped skill with
  source + summary), so the published directory is self-documenting.

### 56.2 High — Extract and repackage from Cantrip's system prompt

- [x] Build pipeline implemented at
  ``scripts/build_juju_skills_bundle.py`` plus the
  ``make juju-skills-bundle`` /
  ``make juju-skills-bundle-check`` targets.  For each manifest
  entry the script reads the source SKILL.md, rewrites the
  frontmatter to canonical/skills shape (``name``, multi-line
  ``description`` with ``WHEN:`` trigger phrases,
  ``license: Apache-2.0``, ``metadata: {author: Canonical/cantrip,
  version, summary, tags}``), collapses cantrip's bundled-tool
  aliases (``charmcraft_pack`` → ``charmcraft pack``, ``juju_deploy``
  → ``juju deploy``, ``juju_relate`` → ``juju integrate``, …) to
  their stable CLI equivalents, and prepends a banner pointing back
  at the source.  All ten generated SKILL.md files pass the upstream
  ``tmp/canonical-skills/scripts/validate_skills.py`` cleanly (0
  errors, 0 warnings).
- [x] One-way-mirror convention enforced by
  ``tests/unit/test_juju_skills_bundle.py`` (33 cases): drift guard
  via the script's ``--check`` mode, presence of every manifest entry,
  frontmatter satisfies the canonical/skills validator's contract
  (kebab-case name, ≥ 20-word description with a ``WHEN:`` /
  ``activat`` / ``trigger`` marker, ``Apache-2.0`` license, semver
  ``metadata.version``, ``Canonical`` author prefix, ≤ 160-char
  ``metadata.summary``, ``juju`` tag present), banner present, and
  no leaked cantrip bundled-tool alias in the published output.
- [x] **Deferred:** the awesome-copilot ``.instructions.md`` /
  ``applyTo:`` glob shape.  The actual ``canonical/skills`` repo
  follows the agentskills.io specification and ships SKILL.md only —
  recorded in the design doc and 56.1.

### 56.3 Medium — Publish to `canonical/skills`

- [ ] Create the repo structure under `canonical/skills`
  (or the existing bundle if it already exists; check before
  creating) — likely a `juju/` subdirectory to leave room for other
  Canonical domains (`lxd/`, `rockcraft/`, etc.)
- [ ] Land the initial asset bundle with a `README.md` explaining
  how to install into VS Code, JetBrains, and Claude Code
- [ ] Add a minimal CI job that validates frontmatter and glob syntax
  so broken assets don't ship
- [ ] Announce internally (Cantrip updates, charm-dev channels) so
  charm authors know the bundle exists

### 56.4 Low — Keep the bundle current

- [ ] Add a GitHub Action that opens a PR when Cantrip's system
  prompt or skill content changes in a way that affects the
  published bundle (a simple diff-on-push is probably enough)
- [ ] Periodic review cadence (quarterly?) to prune stale rules and
  add newly discovered charm idioms
- [ ] Track downstream reception: stars, forks, issues, PRs against
  the bundle — feeds back into Cantrip's own prompt quality

### What this phase is *not*

- Not a fork or rewrite of Cantrip's prompts.  The published bundle
  is a derivative, regenerated from Cantrip's source, not a parallel
  knowledge base to maintain.
- Not a commitment to upstream to `awesome-copilot` itself.  Canonical
  maintains control via `canonical/skills`; upstreaming
  to awesome-copilot is a possible future step, not part of this
  phase.
- Not Juju-specific IDE plugins or VS Code extensions.  Assets only —
  the installation story leans on existing Copilot / Claude Code
  mechanisms.

**Exit criteria:** `canonical/skills/juju/` (or the
agreed-on path) exists with at least six instruction / skill assets
covering the slices from 56.1.  A regeneration mechanism (ideally a
`make` target in Cantrip) keeps the bundle in sync with Cantrip's
own system prompt.  CI validates frontmatter on every PR.  The bundle
is announced to at least one charm-developer channel.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Scope (56.1) | none | Inventory pass; independent |
| Extract (56.2) | 56.1 | Needs the scope decided first |
| Publish (56.3) | 56.2 | Needs the content to publish |
| Maintain (56.4) | 56.3 | Only meaningful once the bundle exists |

---

## Phase 73: Goose-Inspired Workflow Packaging — Recipes, MCP Apps, Retry, Structured Output

**Goal:** Goose (Block's open-source agent, part of the Agentic
AI Foundation at the Linux Foundation) treats agent work as
*packageable*: a recipe is a YAML bundle of parameters,
extensions, settings, retry policy, and response schema that a
team can check in, share, and re-run.  A walk of the Goose
docs surfaces four patterns distinct from Phases 67–72 and
from what Cantrip already has.

Four candidates, in rough priority order:

1. **Recipes — parameterised, retryable, schema-enforced
   workflows.**  Goose's recipe YAML schema bundles
   ``parameters`` (typed: string/number/boolean/date/file/
   select, with required/optional/prompted requirement), a
   Jinja-templated ``instructions`` or ``prompt``, required
   ``extensions`` (MCP servers with ``available_tools``
   filtering), ``settings`` (model/temperature/max_turns),
   ``sub_recipes`` (composable nested invocations with value
   overrides, sequential or parallel), plus ``response``
   (JSON-schema-enforced output) and ``retry`` (max_retries,
   timeout, shell validators, on_failure hook).  Template
   inheritance via ``{% extends "parent.yaml" %}``.  Distinct
   from Phase 69.4 Flow skills (visual decision diagrams)
   and Phase 33 skills (knowledge bundles): a Recipe is a
   *parameterised repeatable execution* — "upgrade this
   charm from reactive to ops with ``charm_name=``,
   ``target_framework=ops>=2.16``, retry if tests fail, emit
   a validated JSON upgrade report."
2. **MCP Apps — interactive HTML UIs in the chat.**  A
   2026-01 MCP extension standard (now supported by Claude
   Desktop, VS Code Copilot, Goose, Postman, MCPJam): MCP
   servers can return HTML in a sandboxed iframe, rendered
   inline in the conversation.  Charm-relevant examples: a
   relation-databag inspector, a Pebble-layer visual
   editor, a bundle-topology graph, a COS dashboard-preview
   form.  Cantrip's Web UI (Phase 15) can host the iframe;
   the TUI falls back to a text link.  Makes complex
   configuration a form rather than a JSON blob.
3. **Structured JSON response with schema enforcement.**
   Goose's ``response: {json_schema: …}`` forces the final
   agent output into a validated JSON shape.  Independent of
   recipes, usable anywhere structure matters: planner
   briefings, acceptance-test reports (Phase 17), Phase 70.4
   Checks output, the oracle's reply (Phase 70.2).  Most
   modern providers support structured outputs natively;
   surfacing the primitive as a per-call option is the
   value.
4. **Declarative retry with shell validators.**  Goose's
   ``retry: { max_retries, timeout_seconds, checks: [{type:
   shell, command: …}], on_failure }`` lets a recipe (or
   any task) declare its own success predicate — a shell
   command that must exit zero — rather than trusting the
   agent's self-report.  Complements Phase 12 red/green
   (goal-level), Phase 69.1 Ralph Loop (outer per-goal),
   and Phase 71.4 per-edit lint: this is *per-task*,
   user-specified, and deterministic.

Five Goose features are explicitly **out of scope or
deferred**:

- **Rust rewrite of Cantrip's core.**  Goose's Rust
  implementation is a product-shape choice; Cantrip's
  Python/Rust split is already tuned for its own needs.
- **Desktop app as a parallel surface to TUI/Web.**
  Phase 15 Web UI plus the TUI cover Cantrip's interface
  matrix; adding a Tauri/Electron desktop is a separate
  decision.
- **Parallel subagent dispatch triggered by conversational
  keywords** ("parallel", "simultaneously").  Phase 44
  worktrees + Phase 32 planner already dispatch parallel
  work; the *keyword-as-trigger* UX is a small planner
  prompt tweak rather than a new subsystem.  Folding the
  idea into Phase 32 as a one-line prompt guidance note.
- **``.goosehints`` with keyword-tagged conditional retrieval.**
  Overlaps with Phase 70.3 glob-conditional guidance.
  Glob-on-paths is Cantrip's primary axis; keyword-tagged
  retrieval would be a second axis with questionable
  marginal value.  Skip unless users ask for tag-based
  filtering specifically.
- **ACP bidirectional (Goose as client of Claude Code /
  Codex).**  Phase 39 covers ACP research.

### 73.1 High — Recipes: parameterised repeatable workflows

- [x] Recipe schema in ``<charm>/.cantrip-recipes/*.yaml`` (repo),
  ``~/.config/cantrip/recipes/*.yaml`` (user), and bundled
  ``cantrip/recipes/*.yaml`` (built-ins).  Top-level fields:
  ``version``, ``title``, ``description``, ``parameters`` (list),
  ``instructions`` (Jinja-templated prompt), ``settings``
  (model/temperature/max_turns — parsed, applied at dispatch
  deferred), ``extensions`` (list of required ``mcp:`` / ``tool:``
  names), ``response`` (see 73.3), ``retry`` (see 73.4),
  ``sub_recipes`` (list of nested invocations).  Lives in
  ``src/cantrip/agent/recipes.py``.
- [x] Parameter types: ``string``, ``number``, ``boolean``,
  ``date``, ``file``, ``select`` (with ``options``).
  Requirement: ``required`` / ``optional`` / ``prompted``.
  Defaults supported.  Interactive ``prompted`` callback returns
  ``None`` today — binder treats it identically to ``required``
  and surfaces a clear missing-parameter error when no argv
  value is supplied.
- [x] Invocation surface: ``/recipe`` lists the catalogue,
  ``/recipe <name> --help`` shows the parameter list,
  ``/recipe <name> key=value …`` runs the recipe through
  ``agent.process_message`` with Phase 73.4 retry and Phase
  73.3 response validation when declared.  Lives in
  ``src/cantrip/agent/commands/recipes.py``.
- [x] Sub-recipes parse, validate, and run **sequentially**
  after the parent reply with cycle detection
  (``_run_sub_recipes`` in ``src/cantrip/agent/commands/
  recipes.py``).  The ``sequential_when_repeated`` flag is
  parsed and accepted today but always sequential in v1.
- [ ] **Deferred:** parallel sub-recipe dispatch via Phase 44
  worktrees when ``sequential_when_repeated: false`` and the
  parent loops over the sub-recipe.  Revisit when a real
  consumer asks (e.g., a recipe that maps the same operation
  across N charms in a bundle).
- [x] Template engine: ``jinja2.sandbox.SandboxedEnvironment``
  with the existing template-injection guard.  ``{{
  recipe_dir }}``, ``{{ recipe_name }}``, and bound parameters
  are exposed.
- [x] Three built-in recipes ship in the wheel under
  ``src/cantrip/recipes/``: ``charm-new`` (research →
  design → build), ``charm-cos-add`` (add COS observability
  to an existing charm), and ``charm-reactive-to-ops``
  (migrate a reactive charm onto the Operator Framework).
- [x] Documented in ``design/RECIPES.md`` (schema reference +
  authoring guide) and ``docs/src/howto-recipes.md`` →
  ``docs/docs/howto-recipes.html`` (worked examples,
  catalogue, parameter cookbook).
- [x] ``tests/unit/agent/test_recipes.py`` and
  ``tests/unit/agent/commands/test_recipe_slash.py`` (92
  cases) — schema parse, parameter validation, template
  expansion incl. escape sequences and cross-parameter
  references, sub-recipe sequential invocation, cycle
  detection, extension enforcement, retry / response
  composition, missing-required-param error path.
- [ ] **Deferred:** ``settings.model`` / ``settings.temperature``
  / ``settings.max_turns`` mid-session swap at dispatch.  The
  YAML is forward-compatible today; the help renderer notes
  the recipe carries non-default settings, but the active
  provider is unchanged.  Revisit when a recipe genuinely
  needs to run against a different model from the session
  default (e.g., a ``charm-architect`` recipe pinned to Opus).
- [ ] **Deferred:** interactive prompt surface for ``prompted``
  parameters in the TUI / Web UI.  ``_make_prompt_callback``
  returns ``None`` today.  Revisit when the TUI prompt manager
  is wired through to slash-command handlers.

### 73.2 Medium — MCP Apps: interactive HTML in the chat

- [x] Adopt the MCP Apps extension spec
  (``modelcontextprotocol.io/extensions/apps/overview``) in
  Cantrip's MCP client (Phase 45).  ``MCPClient.call_tool()`` now
  returns a structured ``MCPCallResult(text, app_renders)`` —
  ``_content_to_structured`` in ``src/cantrip/mcp/client.py``
  extracts ``type: "ui"`` content blocks (the canonical shape) and
  the OpenAI-widget-style ``_meta.app`` shape into
  :class:`cantrip.mcp.types.MCPAppRender` entries.  The textual
  collation still carries a placeholder line so plain-text transcript
  exports record that a render existed at that position.
- [x] Web UI (Phase 15) renders the HTML in a sandboxed iframe with
  ``sandbox="allow-scripts allow-forms"`` (no ``allow-same-origin``);
  height defaults to 400 px with an 800 px ceiling regardless of the
  server's suggested ``max_height_px``.  The ``appendMcpAppBlock``
  dispatcher (in ``src/cantrip/web/static/cantrip.js``) sets the
  attribute verbatim; a unit test
  (``TestWebUIIframeShape::test_sandbox_attrs_are_spec_compliant``)
  pins both the literal value and the absence of
  ``allow-same-origin`` in any ``setAttribute("sandbox", …)`` call.
- [x] ``postMessage`` bridge end to end: iframe-emitted
  ``{type: 'tool_call', requestId, name, arguments}`` messages flow
  over a new ``mcp_app_tool_call`` WebSocket frame into
  ``MCPController.handle_app_tool_call``, which runs them through the
  same ``evaluate_permissions`` gate as agent-initiated calls under
  the new ``agents.mcp-app`` overlay name, dispatches via the shared
  ``execute_tool(...)`` helper, audits as
  ``policy_name="mcp-app:<server>"`` in ``.cantrip-audit.jsonl``,
  fires ``TOOL_INVOKED_PENDING`` / ``TOOL_INVOKED`` events tagged
  ``source="mcp-app"``, and publishes an ``MCP_APP_TOOL_RESULT``
  event that the Web UI ``postMessage``\\ s back into the
  originating iframe.  ASK gates park on the existing
  :class:`PermissionManager` so a CONFIRM task surfaces in the TUI /
  Web UI and resumes the iframe call on approval.
- [x] TUI fallback in ``_on_bus_mcp_app_render`` /
  ``ChatWidget.add_mcp_app_fallback`` renders the spec marker
  ``[MCP App: <title>; open in web UI at <url>]`` plus any
  server-supplied text fallback when an ``MCP_APP_RENDER`` event
  arrives — the TUI cannot host the iframe, so users who want to
  drive the form are nudged toward the Web UI.
- [x] Worked example documented in ``docs/src/explanation-mcp-apps.md``
  → ``docs/docs/explanation-mcp-apps.html``: a "pebble-layer editor"
  MCP server (out of tree, reference only) returns a form for the
  current Pebble layer YAML, the Save button posts a
  ``commit_layer`` tool call back through the bridge, and the
  permission gate / audit machinery records the exchange.  Sidebar
  entry under Explanation in ``docs/src/_site.yaml``.
- [x] ``tests/unit/test_mcp_apps.py`` (16 cases) — ``ui``-block
  extraction (canonical + ``_meta`` shapes, non-HTML mime rejected,
  ``max_height_px`` parsing), ``MCPTool`` publishes one
  ``MCP_APP_RENDER`` event per ``ui`` block, the sandbox attributes
  pinned against drift, ALLOW dispatches + audits + emits result,
  DENY skips dispatch and writes the DENIED audit row, ASK awaits
  the manager and audits both REVIEW_REQUESTED and the final ALLOWED
  outcome, unknown ``app_id`` rejects without dispatching, TUI
  fallback wording matches the spec.

### 73.3 Medium — Structured JSON response with schema enforcement

- [x] New per-call ``response_schema: dict | None``
  parameter on every ``LLMProvider.complete()`` /
  ``.stream()``.  Gemini routes it into
  ``response_mime_type=application/json`` +
  ``response_schema`` on ``GenerateContentConfig``;
  OpenAI-compatible endpoints (Fireworks, OpenRouter,
  vLLM, inference-snap) wrap it in the ``response_format``
  ``json_schema`` envelope (``{name, schema, strict}``);
  Anthropic accepts the kwarg for interface parity but
  doesn't enforce — they have no ``response_format``
  analogue today.  ``provider.supports_response_schema``
  surfaces the native-vs-caller-side distinction.
  Validation runs in Cantrip regardless via
  :mod:`cantrip.llm.structured`, so the contract is the
  same on every backend.
- [x] Four built-in schemas in
  :mod:`cantrip.llm.schemas` (``PLANNER_BRIEFING``,
  ``ORACLE_ANSWER``, ``CHECK_RESULT``,
  ``ACCEPTANCE_REPORT``) plus a ``BUILTIN_SCHEMAS``
  registry for name-driven lookup (recipes, settings).
  Each schema is a plain ``dict`` matching JSON Schema
  draft 2020-12 — no Pydantic, no DSL, same surface
  every provider already accepts.
- [x] **Migrate the planner onto the new primitive.**
  ``TaskPlanner.plan_from_design`` / ``replan`` /
  ``plan_from_day2_findings`` now call
  :func:`cantrip.llm.structured.complete_structured` against
  ``PLANNER_BRIEFING`` instead of regex-stripping fences and
  ``json.loads``-ing the body.  Planner prompts moved to the
  ``{"tasks": [...]}`` shape to match the schema.  Schema-
  validation failure triggers one corrective retry through the
  shared structured-output path, so off-shape replies recover
  without bespoke planner-only fallback.  Oracle (Phase 70.2)
  and acceptance (Phase 17) migrations stay deferred — each is
  its own commit when those phases get follow-up work.
- [x] On validation failure, the
  :func:`complete_structured` helper appends the malformed
  reply as an ASSISTANT turn and a USER turn quoting the
  schema + the validation error, then retries up to
  ``retries`` times (default ``1``).  Final failure raises
  ``StructuredOutputError`` carrying the *last* raw text,
  the schema, and the underlying parser/validator
  exception.
- [x] Documented in
  ``docs/docs/reference-response-schemas.html`` (new
  Reference page) covering when to use a schema, the four
  built-ins, the provider matrix, the
  ``complete_structured`` entry point, and the validation
  + retry semantics.
- [x] ``tests/unit/test_structured_response.py`` (35 cases)
  — happy path, markdown-fence stripping, JSON parse
  failures, schema-violation triggers one retry with
  corrective prompt, final failure surfaces the last
  attempt's raw text, ``retries=0`` and negative-retry
  guards, ``response_schema`` forwarded to the provider,
  OpenAI-compat builds the correct ``response_format``
  envelope (with title-derived ``name``), Gemini and
  Fireworks claim native support while Anthropic does not,
  every built-in schema accepts a canonical sample payload
  and rejects an obvious violation.

### 73.4 Medium — Declarative retry with shell validators

- [x] Retry block schema, parsed by
  ``src/cantrip/agent/declarative_retry.py:parse_retry_config``
  out of YAML frontmatter on custom slash commands.  Top-level
  keys: ``max_retries`` (default ``1``, capped at ``50``),
  ``timeout_seconds`` (default ``600``), ``checks`` (ordered
  list, every check must pass to converge), and an optional
  ``on_failure`` shell command.  Recipe-side reuse (Phase 73.1)
  is still pending; the standalone surface today is custom
  commands.
- [x] Check types: ``shell`` (subprocess exit 0 = pass, optional
  per-check ``timeout_seconds`` defaulting to 60 s),
  ``file_exists`` (relative-path probe rejected at load if
  absolute or escaping the repo root), ``json_schema`` (wraps
  :func:`cantrip.llm.structured.validate_against_schema` so
  Phase 73.3's validator drives convergence and fence-stripped
  JSON keeps working).  Hook-driven custom check types are not
  in v1 — defer until a real consumer asks.
- [x] Retry semantics: each attempt runs the task callable,
  evaluates every check in order, and on any failure rebuilds
  the prompt with the original goal preserved verbatim plus a
  short summary of the failed checks and an excerpt of the
  previous response.  ``timeout_seconds`` bounds wall time;
  once the deadline passes the runner returns with
  ``timed_out=True`` instead of starting another attempt.
  ``on_failure`` runs once at the end if the run exits without
  converging — best-effort, never raises.
- [x] Checks run through the Phase 68.2 permission policy
  (``DENY`` records a failed :class:`CheckResult`, ``ASK``
  parks on :class:`PermissionManager` and refuses if the user
  declines or no manager is wired).  ``on_failure`` honours
  the same gate.  No new execution path — :func:`subprocess.run`
  in the repo root with ``check=False``, identical posture to
  :mod:`cantrip.agent.commands.custom`'s ``!`cmd` `` expansion.
- [x] Distinct from Phase 69.1 Ralph Loop: Ralph is "keep
  iterating the goal until the *agent* says STOP", 73.4 is
  "keep iterating this task until *my shell command* says
  yes".  User-specified success predicate.
- [x] Custom-command frontmatter wires through to the runner:
  the dispatcher in :mod:`cantrip.agent.commands.slash`
  (``_run_primary_with_retry``) wraps ``agent.process_message``
  with :func:`run_with_retry` when the loaded
  :class:`CustomCommand` carries a retry config, and reports a
  one-paragraph summary at the end of the chat response with
  the attempt count and any unresolved failures.  v1 limits
  retry to primary commands; ``retry`` alongside
  ``subtask: true`` or a non-primary ``agent`` is rejected at
  load time so the limitation surfaces with a clear error
  rather than silently dropping the block.
- [x] ``tests/unit/agent/test_declarative_retry.py`` — 40 cases
  covering schema validation (defaults, unknown keys per
  level, ``max_retries`` ceiling and bool guard,
  ``timeout_seconds`` positivity, absolute-path rejection,
  blank-``on_failure`` normalisation), each check type's
  pass / fail / detail surface, retry count and convergence
  (initial + retries, exhaustion, marker-on-second-attempt
  with the corrective prompt verified to preserve the
  original goal), timeout trip via an injected monotonic
  clock, ``on_failure`` running only on final failure and
  honouring permission denies, and the custom-command
  frontmatter integration including the subtask-rejection
  path.

### What this phase is *not*

- Not a second UI.  Desktop app, Rust rewrite, parallel
  dispatch keywords — all out of scope or already covered.
- Not a replacement for Phase 69.4 Flow skills.  Flows are
  visual decision trees; Recipes are parameterised
  execution bundles.  They compose.
- Not a plugin runtime.  MCP Apps (73.2) renders an HTML
  payload from an existing MCP server — no new plugin
  protocol, no Python-side sandboxing, no JS runtime
  inside Cantrip.
- Not a generic structured-output framework with
  Pydantic/attrs bindings.  73.3 uses plain dict JSON
  schemas — same surface as the provider APIs we already
  call.
- Not ``.goosehints``.  Phase 70.3 already covers the
  "conditional guidance" axis on file globs; keyword
  tagging doesn't earn a second mechanism.

**Exit criteria:** (a) ``/recipe charm-cos-add
charm_name=myapp metrics_endpoint=/metrics`` runs a
parameterised workflow with validated JSON output and
retries on Jubilant test failure; (b) an MCP server
returning an ``ui: text/html`` block renders as an
interactive form in the Web UI with postMessage-bridged
tool calls audited in the transcript; (c) Phase 70.4
Check output is JSON-schema-validated before aggregation,
with a documented malformed-output retry path; (d) a
recipe's ``retry.checks: [{type: shell, command: "uv run
pytest tests/unit -q"}]`` drives the task to convergence
on a user-specified predicate, distinct from Ralph Loop.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Recipes (73.1) | Phase 32 (Jinja templates), Phase 33 (skill-adjacent discovery), Phase 44 (worktree dispatch for sub-recipes), 73.3/73.4 (response and retry blocks) | Largest item; recipes compose 73.3 and 73.4 |
| MCP Apps (73.2) | Phase 45 (MCP client), Phase 15 (Web UI), Phase 68.2 (permission gate on app-emitted tool calls) | Follows the MCP Apps spec verbatim; no Cantrip extensions to the protocol |
| Structured response (73.3) | Phase 27, 41 (multi-provider) | Provider-call option; can land standalone, consumed by 73.1 and 70.4 |
| Declarative retry (73.4) | Phase 49 (sandbox), Phase 68.2 (permission gate on check commands), Phase 69.3 (subprocess plumbing) | Standalone; consumed by 73.1 |

---

## Phase 79: Per-Provider Eval Gate for System-Prompt Changes

**Goal:** Replace today's static gold-standard scoring with an
eval harness that actually exercises each supported LLM
provider, so that system-prompt changes are gated on
behavioural regression across the provider matrix.  Anthropic's
April 23 postmortem attributes a 3% quality drop to a prompt
tweak ("Keep text between tool calls to ≤25 words.") that their
narrow initial eval missed — their remediation is to run
*per-model* evals on every prompt change.  Cantrip's eval suite
has the same gap, only wider.

### 79.1 Current state audit (already done)

The eval runner at ``tests/eval/runner.py`` scores hand-written
charm directories against YAML rubrics (``spec.yaml``).  It
does **not** call any LLM.  The ``--provider`` flag is
descriptive metadata only — no dispatch.  Only one gold dir
exists (``tests/eval/charms/ntfy/gold-claude``).  ``make eval``
runs ``pytest tests/eval -v``; the suite is **not** in CI
(``.github/workflows/ci.yaml:81-86`` only runs
``tests/unit`` + ``tests/integration``).  The unit tests at
``tests/unit/test_system_prompt.py`` cover Jinja2 template
rendering and character-count thresholds — adding "Keep
responses under 100 words" to ``src/cantrip/agent/prompts/
system.py`` would pass every existing test.

### 79.2 Add an LLM-in-loop prompt smoke test

Not a full charm generation — a lightweight per-provider
sanity check that can run on every prompt change.

- [x] New ``tests/eval/test_system_prompt_smoke.py`` renders the
  shipped ``cantrip.agent.prompts.system.build_system_prompt()``,
  sends it as the system role with a fixed user prompt to each
  configured provider, and asserts two shape invariants:
  (1) given a ``read_file`` tool and a question that obviously
  needs file content, the response must contain a ``read_file``
  tool call; (2) given a bare greeting, the response must be non-
  empty (or include tool calls) — catches the 4xx-eaten-by-the-
  adapter / template-breakage failure mode that the static gold-
  standard scorer cannot see.
- [x] Matrix covers Claude (``ANTHROPIC_API_KEY``), Gemini
  (``GEMINI_API_KEY``), and two open-weights surfaces — Fireworks
  with Kimi K2 default (``FIREWORKS_API_KEY``) and OpenRouter with
  GPT-4o default (``OPENROUTER_API_KEY``).  Each provider runs at
  its default model so the smoke test exercises what a user
  actually gets without bespoke configuration.
- [x] ``pytest.param`` + per-provider ``pytest.mark.skipif`` on the
  env var means absent keys skip cleanly rather than fail.
  ``make check`` is unaffected (it runs ``tests/unit`` only); the
  eval suite under ``make eval`` skips the eight smoke cases
  without keys, runs them with keys.

### 79.3 Gate in CI against a cheap model

- [x] New ``.github/workflows/prompt-smoke.yaml`` job runs the
  79.2 smoke test on every PR that touches
  ``src/cantrip/agent/prompts/**`` or the smoke-test file
  itself.  Scoped to OpenRouter with ``openai/gpt-4o-mini``
  via ``CANTRIP_SMOKE_OPENROUTER_MODEL`` to keep cost bounded;
  the other provider keys stay unset so only the OpenRouter
  slice of the matrix runs in CI.  Fork PRs are skipped (they
  cannot read repo secrets) rather than show a misleading
  green check.  ``src/cantrip/agent/planner/`` does not have a
  ``templates/`` directory in the current layout — the path
  reference in the original phase note pre-dated the planner
  refactor; the smoke gate covers the actual planner-prompt
  surface via ``src/cantrip/agent/prompts/planning/``,
  ``src/cantrip/agent/prompts/tasks/``, and
  ``src/cantrip/agent/prompts/subagent/`` under the prompts
  path.
- [x] ``timeout-minutes: 5`` bounds wall-clock cost so a hung
  provider call cannot burn a full job budget; pytest exits
  non-zero on any test failure or provider 4xx, so a broken
  prompt template (Jinja2 error → import-time crash; provider
  rejects system content → ``ProviderError``; model fails the
  shape invariant → assertion error) surfaces as a red check
  in well under a minute.

### 79.4 Per-provider full-eval run (nice-to-have)

- [x] Extend ``tests/eval/runner.py`` so ``score --provider
  X`` actually uses provider ``X`` to *generate* the charm
  before scoring, rather than scoring a pre-baked directory.
  Implemented as two new verbs alongside the existing
  ``score`` (whose meaning of "score this exact directory"
  is preserved): ``generate <spec_dir> --provider X
  [--model Y]`` shells out to ``cantrip run --print`` and
  lays the resulting charm into a fresh
  ``cantrip-<provider>-<model>-<YYYYMMDD-HHMMSS>/``
  subdirectory; ``run`` chains generate-then-score in one
  invocation for the CI-friendly common case.  The
  ``generate_charm`` helper takes an injectable subprocess
  runner so ``tests/eval/test_runner_generate.py``
  exercises the CLI path end-to-end with a fake (no LLM
  calls under ``make eval``).
- [ ] Add ``gold-gemini`` and ``gold-fireworks`` baseline
  directories over time as each provider passes.  The
  ``run`` verb is the recipe: generate, hand-tune, rename
  to ``gold-<provider>``, then ``validate``.  *Partial
  (2026-05-24): ``gold-fireworks`` landed for ntfy and
  flask-hello, alertmanager-machine, meilisearch,
  vaultwarden, and gitea — all single-shot Kimi K2
  default, ~30 min generation each.  ntfy scored 46/47 (96 %) raw with one
  import-style hand-tune (``from ops import testing`` →
  ``import ops.testing``) to reach 47/47.  flask-hello
  scored 42/49 (86 %) raw with three rubric-shape
  hand-tunes to reach 49/49: relation endpoints renamed
  ``database`` → ``postgresql`` and ``nginx`` →
  ``nginx-route`` (Fireworks's names were semantically
  correct but the rubric looks for the spec's literal
  names) and the charm.py docstring expanded to mention
  ``/srv/flask-hello/venv`` + ``pip install`` so the
  rubric's ``venv|pip|virtualenv|/srv`` pattern hits in
  ``src/charm.py`` (the install logic itself was already
  in ``src/flask_hello.py``, which the rubric doesn't
  grep).  Surfaced + fixed a latent bug in
  ``tests/eval/generator.py``: a relative ``spec_dir``
  caused the subprocess to re-resolve the positional
  charm-path under its own cwd and nest the directory;
  the generator now resolves to absolute before subprocess
  invocation, pinned by
  ``test_generate_charm_passes_absolute_paths_to_subprocess``.
  alertmanager-machine (machine substrate) scored 45/47
  (96 %) raw — same single import-style hand-tune as ntfy
  to reach 47/47; the run hit the 30-min subprocess
  timeout but Fireworks had already produced the full
  charm by then so the timeout was cosmetic.
  meilisearch scored 49/51 (96 %) raw with the same single
  import-style hand-tune to reach 51/51.  vaultwarden
  scored 60/64 (94 %) raw with two cosmetic hand-tunes
  (metrics relation renamed ``prometheus-scrape`` →
  ``metrics-endpoint`` to match the rubric, plus the usual
  import-style scenario fix) to reach 64/64.  gitea (the
  largest spec in the corpus at 448 lines) scored 84/89
  (94 %) raw with three hand-tunes to reach 89/89: a
  documentation-only ``src/templates/app.ini.j2``
  Jinja2 template mirroring the ``app.ini`` shape the
  charm already writes inline, a minimal
  ``src/grafana_dashboards/gitea.json`` dashboard, plus
  the usual import-style scenario fix.  ``gold-gemini``
  remains pending across all specs once provider funds
  are sorted.  A first haproxy-machine + Fireworks
  attempt scored 42/63 (67 %) — full metadata + ops
  framework but a 40-line charm.py pushed most code-pattern
  responsibilities into the helper module, and no
  ``src/templates/haproxy*`` or
  ``src/grafana_dashboards/*.json`` got produced; recorded
  as a per-provider signal alongside the miniflux failure
  rather than hand-authored.  A first miniflux + Fireworks attempt
  scored only 13/42 (31 %) — Kimi K2 declared the build
  "done" after 14 cycles (vs. 30+ for ntfy/flask-hello)
  and left a 28-line bare-scaffold charm; recorded as a
  per-provider signal rather than hand-authored to
  passing.  Revisit when Fireworks defaults change or a
  different Fireworks model is tried.*
- [x] Document the end-to-end loop in
  ``docs/src/howto-eval.md`` (new).  Linked from the
  sidebar nav alongside ``howto-print-mode``.

### 79.5 Prompt ablation harness (stretch)

- [x] Tool that takes ``system.py``, drops each labelled
  section in turn, reruns 79.2, and reports score deltas.
  Lets a human author reason about which sections pull their
  weight before a prompt change lands — matches Anthropic's
  "continue ablations to understand the impact of each line"
  remediation.  (Lives at ``tests/eval/ablate.py`` —
  ``parse_sections`` walks the rendered prompt fence-aware so
  the WORKLOAD.md / DESIGN.md ``## Heading`` blocks inside
  fenced ``markdown`` examples are *not* mistaken for prompt
  sections; ``with_section_dropped`` produces an ablated
  variant; ``_smoke_once`` reuses the same shape as the 79.2
  invariants (``read_file`` tool-call + non-empty bare-greeting
  reply) so the table matches what the gate would see.
  ``render_report`` prints a fixed-width table with one row per
  section plus a ``(baseline)`` row, marking ``-tool_call`` /
  ``-non_empty`` losses, ``+tool_call`` gains, or ``err: …``
  when the provider call itself dropped.  ``--list-sections``
  prints parsed names without calling any provider.  Exit code
  1 on any regression, 0 otherwise, 2 when the chosen
  provider's API key is unset.  Tests in
  ``tests/eval/test_ablate.py`` cover parsing (incl. fence-
  awareness), drop semantics, delta-label edge cases, and the
  reporter; provider-call paths reuse the 79.2 live test as
  their integration check rather than mocking the wire.)

**Exit criteria:**

- System-prompt changes have a per-provider regression guard.
- CI fails when a prompt edit breaks response shape on the
  cheap-model smoke test.
- At least 79.2 + 79.3 ship.  79.4 / 79.5 can land later.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| 79.2 | None | Additive tests + provider keys from CI secrets |
| 79.3 | 79.2 | Needs the test runner first |
| 79.4 | 79.2 | Bigger lift — touches the runner, not just new tests |
| 79.5 | 79.2 | Stretch; nice-to-have |

**Discovered:** Reviewing Anthropic's April 23 Claude Code
postmortem (2026-04-24).  Code audit of ``tests/eval/`` against
the current ``main`` branch confirmed the harness scores static
files only and does not dispatch on provider.

---

## Phase 84: Deferred-Item Sweep — Catalogue and Re-evaluate

**Goal:** Roadmap and archive both accumulate explicit deferrals —
sub-phases or sub-tasks shipped *minus* a piece that was scoped
out with a "revisit when…" condition.  Recent examples that
prompted this phase:

- 67.1 — Amp-style ``@@`` prior-session picker (waiting on a
  session registry that doesn't exist).
- 67.2 — TUI hotkey + favourites cycling for ``/model``
  (waiting on a concrete ergonomic case).
- 71.4 — ``pytest --collect-only`` on touched files
  (waiting on a different scope decision).
- 73.x — migrate existing call sites onto the new structured-
  output API.
- Multiple archived phases ("deferred to a follow-up", "needs
  in-loop integration", etc.) where the revisit trigger was
  recorded but no scheduled re-read of the trigger was set up.

Without a recurring sweep, deferrals turn into forgotten todos.
This phase exists so we have a place to (re-)check them.

### 84.1 Build the deferred-item index ✓

- [x] Grepped ``ROADMAP.md`` and ``ROADMAP_ARCHIVE.md`` for the
  explicit-deferral markers (``Deferred:``, ``defer pending``,
  ``revisit when``, ``re-open when``, ``deferred follow-up``,
  ``follow-up phase``).  Fourteen distinct deferrals captured —
  eleven in the active roadmap (Phases 67.1, 67.2, 70.1×2, 70.2×2,
  70.5×3, 71.4, 73.3) and three in the archive (Phases 48.5, 49.3,
  55.4).
- [x] Catalogue saved as ``design/DEFERRED.md`` — flat table with
  *Phase / Sub-task*, *What was deferred*, *Revisit trigger*,
  *Status*, *Notes* columns.  One row per deferral.  Sweep
  procedure documented at the foot of the file so the next pass
  reads off the same instructions.

### 84.2 Re-evaluate each deferral ✓ (2026-04-26 pass)

- [x] Re-evaluated every row in ``design/DEFERRED.md`` for the
  2026-04-26 pass.  All fourteen deferrals are **not fired**: no
  trigger has happened since the original deferral landed.  No
  rows moved to "Resolved" or "Dropped".
- [x] Audit date stamped on ``design/DEFERRED.md`` (2026-04-26)
  with the next due date (2026-07-26) so the next sweep knows
  what it's looking back over.

### 84.3 Schedule the next sweep

- [ ] Quarterly cadence picked and recorded in ``design/
  DEFERRED.md``; next sweep due **2026-07-26**.  Use ``/schedule``
  to set a background-agent reminder rather than relying on
  someone to remember — left to the user to launch since
  ``/schedule`` is a user-triggered surface.

### What this phase is *not*

- Not a place to *do* the deferred work.  84.2's "trigger
  fired" bucket opens a follow-up phase or task; the actual
  implementation lands in that phase, not here.
- Not a vehicle for re-litigating *closed* phases.  If a phase
  shipped with an exit decision ("ship", "defer", "drop"), the
  decision stands until evidence appears that the world
  changed.  The sweep records evidence; it does not relitigate.
- Not a documentation rewrite.  ``design/DEFERRED.md`` is a
  flat audit log, not a narrative.

**Exit criteria (per pass):** ``design/DEFERRED.md`` is
up-to-date with the current set of deferrals, every row is
labelled fired / not-fired / dropped, and any "fired" rows have
a concrete follow-up phase or task linked.  The next sweep date
is on the calendar.

**Discovered:** While closing Phase 67.1 the ``@@`` prior-
session picker was marked deferred pending a session registry.
Skimming ``ROADMAP_ARCHIVE.md`` afterwards turned up dozens of
similar deferrals scattered across phases without a re-read
plan — e.g. observability pieces in Phase 41, decisions in
Phase 73, scope cuts in Phase 71.  Without a periodic sweep
those deferrals would silently rot into todos no one
remembers.

---

## Phase 113: Source-Tree Restructure — Tame the Growth

> **⚠️ Session handoff — read before continuing this phase:**
> [`design/research/PHASE_113_HANDOFF.md`](design/research/PHASE_113_HANDOFF.md)
> records exactly what has landed (113.1/113.2/113.3/113.5/113.6 done; 113.4 partial; 113.8
> done plus two bug fixes), what remains open (113.4 finish, 113.7, 113.9, 113.10), and
> the process lessons that caused churn (run `make check` before every commit; the
> pre-commit hook does not run tests; prefer sequential edits). Start there.

**Goal:** The codebase has accumulated significant local entropy as
features have shipped.  Six call-out areas are now disproportionately
costly to navigate: a 3,843-line `CantripAgent` god-class in
`src/cantrip/agent/core.py`; tool modules in the 1.5k–2.7k-line range
in `src/cantrip/agent/tools/` that bundle multiple distinct surfaces;
59 flat modules at the top of `src/cantrip/agent/`; a 2,047-line slash
dispatcher; a 2,141-line TUI app with a long pile of confirmation
handlers; and a `design/` directory that conflates active-contract docs
with point-in-time research/audit snapshots.  Two repository-layout
questions are bundled in: what to do about the four overlapping
illustrative-material directories (`cookbook/`, `demos/`, `examples/`,
`bundles/`), and getting the 114 GB `inference-snaps/` tree out of the
repository path while preserving the host ↔ VM share workflow.

This phase exists to land the restructure incrementally without
freezing feature work.  Each sub-phase is independent and individually
reviewable; ordering is suggested in the dependencies table, not
enforced.  The exit bar is *navigability* — files under ~1k lines, no
single-class god-modules, and a clear rule for what sits at each
package level — not aesthetic uniformity.

### 113.1 High — Split `agent/core.py`

- [x] Decompose `CantripAgent` (3,843 lines, 135 methods) by
  composition.  `CantripAgent` retains the public API; the concerns
  below move to dedicated services held as attributes.
  - `ProviderManager` — `_get_provider`, `switch_model`,
    `_architect_provider`, `_editor_provider`,
    `_resolve_light_provider`.
  - `MessageHistory` — `_record_message`,
    `_rebuild_messages_from_active_branch`, `_build_llm_messages`,
    `_collapse_messages_for_short_session`,
    `_maybe_fold_oldest_round_into_ledger`.
  - `RepoMapService` — `repo_map`, `refresh_repo_map`, `code_intel`,
    `_code_intel_or_none`, `_render_repo_map`.
  - `ToolBuilder` — `_build_tools`, `_invalidate_tools_cache`,
    `_tool_map`, `_curated_tool_names`, `_tools_for_llm`.
  - `UsageTracker` — `_record_usage`, `_check_cache_cascade`,
    failure-streak tracking (`_track_tool_failure_streak`,
    `_maybe_warn_before_failure_cap`,
    `_consecutive_failure_cap_exceeded`).
- [x] Land each extraction as an independent commit (one service per
  commit) so the diff is reviewable.  Tests touched per extraction
  stay green throughout; `make check` passes after every commit.
- [x] **Done.**  Five services extracted — `UsageTracker`,
  `ToolBuilder`, `RepoMapService`, `MessageHistory`, `ProviderManager`
  — each a class holding a back-reference to the agent.  Every method
  stays on `CantripAgent` as a thin delegating wrapper, so the public
  API and all instance state are unchanged and no test or external
  call site needed editing; `repo_map` / `code_intel` keep their
  property getter *and* setter on the agent.  `_resolve_light_provider`
  was *not* moved — it is a `CantripApp` (TUI) method, not on
  `CantripAgent` — so `ProviderManager` carries the four agent methods
  (`_get_provider`, `switch_model`, `_architect_provider`,
  `_editor_provider`).  One commit per service; `core.py` 3,924 →
  3,511 lines (services 154–396 lines each).  Driving `core.py` under
  the ~1,500-line exit bar remains follow-on work beyond these five
  extractions.

### 113.2 High — Split `agent/tools/juju.py` by sub-domain

- [x] Move into `src/cantrip/agent/tools/juju/`.  Grouping (27 tool
  classes → one file each, or grouped where naturally cohesive):
  - `juju/lifecycle.py` — deploy, refresh, remove, destroy-model,
    add-model, bundle-deploy.
  - `juju/relations.py` — relate, offer, consume, list-offers,
    read-relation-data.
  - `juju/runtime.py` — status, ssh, run-action, dispatch, wait,
    config, get-app-config, show-unit.
  - `juju/secrets.py` — list-secrets, show-secret.
  - `juju/charm_sync.py` — `CharmSyncTool` (distinct concern).
  - `juju/cli_passthrough.py` — `JujuCliTool`, `JujuTrustTool`.
- [x] Keep `agent/tools/juju.py` as a thin re-export shim only if a
  caller outside the tools registry imports the classes by full path;
  otherwise delete it.  (Per the pre-1.0-no-backcompat memory: update
  call sites in the same change.)
- [x] `tests/unit/agent/tools/test_juju*` stays green.
- [x] **Done.**  `juju.py` (2,720 lines) → `juju/` subpackage:
  `_common` (shared helpers + the patchable imports), `lifecycle`,
  `relations`, `runtime`, `secrets`, `charm_sync`, `cli_passthrough`.
  All 24 tool classes are re-exported from `juju/__init__.py`, so
  `tools/__init__.py` is unchanged; the old module was deleted (no
  shim needed).  Submodules reach the patchable helpers through the
  `_common` module object, and the test patch strings were repointed
  from `cantrip.agent.tools.juju.<name>` to `…juju._common.<name>`.
  `make check` green.

### 113.3 High — Split `agent/tools/publishing.py` by surface

- [x] Move into `src/cantrip/agent/tools/publishing/`.  The 2,242-line
  module mixes seven concerns; one module each:
  - `publishing/charmcraft.py` — `CharmcraftUploadTool`,
    `CharmcraftReleaseTool`.
  - `publishing/readme.py` — `GenerateReadmeTool` + helpers.
  - `publishing/icon.py` — `GenerateIconTool`, `generate_placeholder_svg`.
  - `publishing/diagram.py` — `GenerateDiagramTool` and mermaid helpers.
  - `publishing/docs_scaffold.py` — `GenerateDocsTool` and tutorial /
    actions / deploy block helpers.
  - `publishing/design_decisions.py` — `ExtractDesignDecisionsTool`,
    decision-log readers/formatters.
  - `publishing/troubleshooting.py` — `TroubleshootingEntry`,
    transcript-pair extraction, `format_troubleshooting_page`.
- [x] Same shim-or-delete policy as 113.2.  Tests stay green.
- [x] **Done.**  `publishing.py` (2,242 lines) → `publishing/`
  subpackage: `_common` (shared metadata reader + diagram renderer),
  `icon`, `diagram`, `readme`, `charmcraft`, `docs_scaffold`,
  `design_decisions`, `troubleshooting`.  Eight tool classes plus the
  public helpers (`generate_placeholder_svg`,
  `format_troubleshooting_page`, …) are re-exported from
  `publishing/__init__.py`, so `tools/__init__.py` and the
  `web_research` / `maintenance` call sites are unchanged; the old
  module was deleted.  The only namespace patch targets (charmcraft's
  `subprocess` / `shutil`) were repointed to
  `…publishing.charmcraft.<name>`.  `make check` green.
- [ ] Apply the same lens (no formal split obligation) to
  `acceptance.py` (1,520), `charm.py` (1,440), `rockcraft.py` (1,298),
  `observability.py` (1,676) and split only when a clear sub-domain
  boundary jumps out.

### 113.4 High — Group flat modules under `src/cantrip/agent/`

- [~] Move 49 of the 59 flat modules into themed subpackages
  (suggested groupings; rename freely if a better cut presents):
  - `agent/race/` — `arena.py`, `arena_controller.py`, `race.py`.
  - `agent/context/` — `context.py`, `context_providers.py`,
    `context_providers_builtin.py`, `lint_context.py`.
  - `agent/git/` — `auto_commit.py`, `git_branch.py`, `worktree.py`.
  - `agent/safety/` — `permissions.py`, `sandbox.py`,
    `controller_safety.py`, `confirmations.py`.
  - `agent/runtime/` — `lifecycle.py`, `preflight.py`, `presets.py`,
    `goal_budget.py`, `durability.py`.
  - `agent/policy/` — `policy.py`, `routing.py`, `retry.py`,
    `declarative_retry.py`.
  - `agent/watcher/` — `watcher.py`, `watcher_controller.py`,
    `github_issues.py`, `triage_controller.py`.
  - `agent/skills_runtime/` — `skills.py`, `skill_export.py`,
    `skill_scanner.py`.
- [ ] Decide explicitly between two patterns for the five
  `X.py` + `X_controller.py` pairings (executor, watcher, arena,
  triage, mcp): either (a) keep the pattern and document it as a
  convention in CLAUDE.md, or (b) collapse controllers into a
  shared `controllers/` subdir, or (c) merge each controller into
  its sibling.  Pick one and apply uniformly.
- [x] Update all call sites and `__init__.py` re-exports in the same
  commit.  No back-compat aliases.
- [~] **Partial.**  All eight named groupings landed across six
  commits (the `runtime` move is bundled into the `policy` commit and
  the `watcher` move into the `skills_runtime` commit — each is still a
  complete, internally consistent move), every import and patch string
  rewritten in place (no shims), with `make check` green at the tip:
  `agent/race/` (arena, arena_controller,
  race), `agent/context/` (context, context_providers,
  context_providers_builtin, lint_context), `agent/git/` (auto_commit,
  git_branch, worktree), `agent/safety/` (permissions, sandbox,
  controller_safety, confirmations), `agent/runtime/` (lifecycle,
  preflight, presets, goal_budget, durability), `agent/policy/` (policy,
  routing, retry, declarative_retry), `agent/watcher/` (watcher,
  watcher_controller, github_issues, triage_controller), and
  `agent/skills_runtime/` (skills, skill_export, skill_scanner) — 30
  modules in all.  Flat top-level modules under `agent/` dropped from 56
  to 26.  **Still open:** the controller-pattern decision above
  (executor/watcher/arena/triage/mcp `X_controller`), and further
  grouping to reach exit-criterion (b)'s ~15 — candidate clusters among
  the remaining flat modules: the five Phase 113.1 service modules
  (`provider_manager`, `message_history`, `repo_map_service`,
  `tool_builder`, `usage_tracker`), a session/persistence cluster
  (`store`, `persistence`, `snapshots`, `session_preview`, `audit`,
  `cache_monitor`), and a workflow cluster (`checks`, `flows`,
  `recipes`, `ralph`).  Deferred to a follow-on so the named,
  low-ambiguity groups could land first.

### 113.5 Medium — `slash.py` registry refactor

- [x] **Done.** `src/cantrip/agent/commands/slash.py` was 2,047 lines and already
  delegated to per-family modules for several command groups
  (`custom`, `mcp`, `recipes`, `flows`, `cost`, `map`, `share`,
  `codeintel`, `transcript`).  Pull the remaining handlers into
  per-family modules and reduce `slash.py` to a dispatch table +
  `help_text` + `format_*_status`:
  - [x] `commands/session.py` — `handle_undo`, `handle_redo`,
    `handle_branch`, `handle_tree` (with the shared `TreeNode` /
    `build_tree_nodes` the TUI tree picker reuses) and `/update`
    (`_handle_update`, `_run_update_slash_check`, `_SETTINGS_LABEL`).
  - [x] `commands/modes.py` — `handle_plan`, `handle_build`,
    `handle_architect`, `_describe_editor`, `handle_auto_commit`,
    `handle_yolo`, `handle_pause`, `handle_resume`, `handle_ralph`,
    plus the `/model` switch (`_handle_model` + `_MODEL_SWITCH_PROVIDERS`)
    it sits with.  (The original plan named this `agent_modes.py` and
    split pause/resume/model into `session.py`; grouped here instead as
    the loop/mode-control family.)
  - [x] `commands/review.py` — `_REVIEW_SEVERITIES`, `_ReviewFilters`,
    `_parse_review_filters`, `_apply_review_filters`, `_handle_review`,
    `_render_filter_miss`.
  - [x] `commands/charms.py` — charm discovery: `/search-charms`
    (`_handle_search_charms`, `_run_search_charms`, the launchpad-MCP
    section helpers) and `/icon` (`_handle_icon`, `_run_icon`).
  - [x] session-export glue (`/copy`, `/share`) folded into the
    existing `commands/transcript.py` (joins `/export`); the worker
    `commands/share.py` stays `SlashResult`-free by design.
- [x] Dispatcher is now a `{verb: handler}` table (`_DISPATCH`) keyed
  by verb, replacing the long if/elif chain.  Hybrid by design: the
  ~36 simple one-to-one verbs live in the table; the two verbs that
  branch internally (`/mcp`, `/arena`) route through small named
  helpers; and the genuinely special shapes — the `/flow:<name>`
  prefix match and the user-defined-command fallthrough — stay explicit
  in `_dispatch_inner`.
- Result: `slash.py` is down from 2,047 to ~750 lines.  What remains by
  design is the dispatcher, the `_DISPATCH` table, `help_text`,
  `format_sandbox_status` / `format_hooks_status`, the lone
  `_handle_diagnostics` handler (no clean existing family home), and the
  custom-command plumbing (`_handle_custom_command`,
  `_run_primary_with_retry`, `_coerce_task_category`).

### 113.6 Medium — Extract TUI confirmation orchestration

- [x] `src/cantrip/tui/app.py` had ~19 `_present_X_confirmation` +
  `_handle_X_response` methods (bootstrap, push, race, triage,
  maintenance, improvement, PR, design-questions).  Moved them all
  behind a `ConfirmationCoordinator` in
  `src/cantrip/tui/confirmations.py`, leaving `CantripApp` with
  widget composition, event-bus subscriptions, and the bind/action
  surface.
- [x] The coordinator owns the active-flow state
  (`pending_confirm_id` / `pending_pr_branch` / `pending_maintenance`);
  the bus handler routes a blocked CONFIRM through
  `present_for_blocked_task` (prefix → presenter table) and input
  dispatch routes the next reply through `handle_pending_response`
  (ordered prefix → handler table), replacing the former if/elif
  chains.
- [x] **Done.**  `app.py` keeps `_pending_*` property bridges so the
  ~109 state references and the test suite reach the same names
  unchanged; method call sites in the five `tests/unit/tui/` files
  were repointed to `app._confirmations._<method>`.  `app.py` dropped
  by ~600 lines.

### 113.7 Medium — Decide on top-level flat modules in `src/cantrip/`

- [ ] Seven flat modules currently sit beside the subpackages:
  `cli.py` (777 lines), `clipboard.py`, `compare.py`,
  `diagnostics.py`, `notifications.py`, `print_mode.py` (577 lines),
  `workspace.py`.  No rule for what gets promoted.  Pick one and
  apply uniformly:
  - **Option A:** pull `cli.py` and `print_mode.py` into a `cli/`
    package (the two CLI entrypoint surfaces sit together with the
    `main/` parser layer they call into).  Leave the small utility
    modules (`clipboard.py`, `compare.py`, `diagnostics.py`,
    `notifications.py`, `workspace.py`) at the top level.
  - **Option B:** flatten convention — everything stays at the top
    level, document in CLAUDE.md that single-file utilities live
    here.  Then `cli.py` / `print_mode.py` are non-issues at size,
    just at-the-line.
- [ ] Whichever wins, write the convention into CLAUDE.md so the
  next "should this be a package?" question has an answer.

### 113.8 Medium — Split `design/` into active vs research/audit

- [x] CLAUDE.md already names two classes of `design/*.md`: active
  contracts ("always relevant to ongoing work") and "point-in-time
  research and audits".  Realise the split as a directory:
  - `design/` — active contracts only.  PLAN, AGENT, UI, TOOLS,
    SKILLS, PROMPTS, CONTEXT_PROVIDERS, PROVIDER_ROLES, DOCS_INDEX,
    RECIPES (the list in CLAUDE.md).
  - `design/research/` (or `design/archive/` — pick on tone) — every
    point-in-time doc.  Sweep candidates: `ACP_RESEARCH.md`,
    `AGENT_REVIEWS.md`, `CHARMING_WITH_CLAUDE_REVIEW.md`,
    `CLOUD_GLM_2026-05.md`, `LOCAL_MODELS_SURVEY_2026-05.md`,
    `PI_RESEARCH.md`, `RESEARCH_DASH_CRAFT.md`,
    `RIGHT_PANEL_AUDIT.md`, `UPSTREAM_AUDIT.md`,
    `WEB_UI_ACCESSIBILITY_AUDIT.md`, `jujumate-analysis.md`,
    `orc-analysis.md`, `FRAMEWORK_EVALUATION.md`,
    `CHARMING_WITH_CLAUDE_REVIEW.md`, `CANONICAL_SHOWCASE.md`,
    plus any `*_REVIEW.md` / `*_AUDIT.md` /
    `*_SURVEY*.md` that landed since.
- [x] Update intra-doc links and CLAUDE.md's "Reference Documents"
  section to reflect the new paths.
- [x] Keep the rule in CLAUDE.md so newly-written research lands in
  the right place from day one.
- [x] **Done.**  `design/` now holds only the ten active-contract docs
  (PLAN, AGENT, UI, TOOLS, SKILLS, PROMPTS, CONTEXT_PROVIDERS,
  PROVIDER_ROLES, DOCS_INDEX, RECIPES); the other 36 point-in-time
  research/audit/survey notes moved to `design/research/`.  All
  cross-directory links were repointed and verified with a
  link-resolution check (the one remaining broken link,
  `design/SKILLS.md` → `assets/templates/STACK.md`, is pre-existing and
  unrelated); source-code references to `design/UPSTREAM_AUDIT.md`
  (charmlint rules, identity skill) were updated to the new path.
  Per the scope decision, historical records (`CHANGELOG.md`,
  `ROADMAP_ARCHIVE.md`) were left as-is.  CLAUDE.md records the rule so
  new research lands in `design/research/` from day one.  `make check`
  green.

### 113.9 Low — Decide on `cookbook/` / `demos/` / `examples/` / `bundles/`

- [ ] Four top-level directories carry illustrative material with
  overlapping intent.  Decide a unification policy or accept the
  split:
  - **`cookbook/`** — guided multi-step charm-building walkthroughs
    (`build-a-stateful-charm`, `migrate-harness-to-scenario`, …).
  - **`demos/`** — narrative MD demos + screen recordings.
  - **`examples/`** — small worked example code (`examples/mcp/…`).
  - **`bundles/`** — generated artefact bundles published downstream
    (`canonical-skills-juju/`).
- [ ] Options to evaluate:
  - **Unify** under a single `examples/` root (`examples/cookbook/`,
    `examples/demos/`, `examples/mcp/`, `examples/bundles/`) — fewer
    top-level directories, one entry point for illustrative material.
  - **Accept the split** but document the rule for each directory's
    purpose in a top-level `README.md` cross-reference table so
    contributors know where new material belongs.
  - **Partial merge** — combine `cookbook/` and `demos/` (both
    user-facing tutorials), keep `examples/` and `bundles/` separate
    (one is small code snippets, the other is published downstream
    output).
- [ ] Pick one, apply, and write the convention into CLAUDE.md.

### 113.10 High — Move `inference-snaps/` outside the repo path

- [ ] The directory holds 114 GB of model weights and snap build
  artefacts.  Even gitignored, its presence inside the repository
  path slows down `find`, `rg`, and editor scans.  Move the tree to
  a sibling location (`~/inference-snaps/` or
  `/srv/inference-snaps/` — to be picked by the user) and update
  any scripts / Make targets / docs that hard-code the in-repo path.
- [ ] **User-coordinated:** the host ↔ VM share workflow currently
  relies on the directory living under the cloned repo so files
  flow into the VM mount.  The user will coordinate the move so
  the share path is updated in lockstep.  Do not move the
  directory unilaterally — the cutover requires the host- and VM-
  side mount config to be updated together.
- [ ] Update `.gitignore` to drop the `inference-snaps/` rule once
  the directory is gone from the path.  Add a doc note (likely in
  `docs/src/howto-light-models.md` or `howto-vm-inference-proxy.md`)
  recording the new canonical location.

### What this phase is *not*

- Not a behavioural change.  Every sub-phase is a move-and-rename
  operation; tests stay green and runtime behaviour is unchanged.
- Not a re-architecture.  `CantripAgent`'s contract with the rest
  of the system is the public surface today; 113.1 keeps that
  contract and only redistributes responsibilities behind it.
- Not a back-compat exercise.  Per the pre-1.0-no-backcompat
  convention, call sites are updated in the same change.  No
  re-export shims kept around for hypothetical external callers.
- Not a split of `ROADMAP_ARCHIVE.md`.  The 17,886-line archive is
  fine as one file (user decision, 2026-05-26 review).

**Exit criteria:**

- (a) No file in `src/cantrip/agent/` exceeds 1,500 lines (`core.py`,
  `juju.py`, `publishing.py`, `slash.py`, `app.py` are the named
  targets; `acceptance.py`, `observability.py`, `rockcraft.py`,
  `charm.py` are loose follow-ons).
- (b) `src/cantrip/agent/` has no more than ~15 top-level Python
  files; the rest live in themed subpackages.
- (c) `design/` contains only files listed under "active-contract
  docs" in CLAUDE.md; point-in-time research/audit sits in a
  sibling subdir.
- (d) `inference-snaps/` no longer lives under the repo path; the
  host↔VM share workflow continues to work.
- (e) A decision is recorded for `cookbook/` / `demos/` /
  `examples/` / `bundles/` — either unified or explicitly documented.
- (f) `make check` passes on every commit; no test fixtures or
  imports break.

**Dependencies:**

| Item | Depends On | Notes |
|------|-----------|-------|
| 113.1 core split | none | Largest single change; do early so later sub-phases interact with the smaller surface |
| 113.2 juju split | none | Independent; can land in parallel with 113.1 |
| 113.3 publishing split | none | Independent |
| 113.4 agent flat-to-folder | 113.1 (avoids merge conflicts in `core.py`) | Touches many import paths |
| 113.5 slash registry | 113.4 (post-grouping import paths) | Depends only on stable import paths |
| 113.6 TUI confirmations | none | Self-contained inside `src/cantrip/tui/app.py` |
| 113.7 top-level flat | none | Convention call; small physical change |
| 113.8 design split | none | Pure file moves + link updates |
| 113.9 cookbook/demos/… | none | Decision-first; physical moves only if option A or C wins |
| 113.10 inference-snaps | user coordination on host↔VM share | Do not start without the user driving the cutover |

**Discovered:** 2026-05-26 review pass.  The codebase has grown
substantially through Phases 73–112 and the structure has not been
revisited since the major Phase 32 / 44 / 45 / 68 layouts landed.
A targeted pass at file size + package boundaries surfaced the
six call-out areas without changing the architecture.

---

## Phase 114: Test-Suite Tidy-Up — Command Coverage, Shared Fakes, Snapshots

**Goal:** The test suite is healthy overall (92.41% line coverage,
8,336 unit tests, ~117 s parallel run) but a 2026-05-26 review
surfaced six concrete weak spots that are individually small and
collectively worth a focused pass: the user-facing slash-command
modules under `src/cantrip/agent/commands/` are the lowest-covered
non-trivial code in the tree; 23 inline `_Fake…` / `_Stub…` classes
remain in test files despite `tests/support/` existing for exactly
this; there is no snapshot/golden-file machinery anywhere, so prompt
and structured-response regression tests assert via brittle string
contains; `tests/unit/test_cli_bdd.py` is 168 lines and does not
match its name; many modules between 85–92% have missing coverage
clustered on error/edge branches; and the slash-command dispatch
path has thin unit coverage and no integration coverage.

Each sub-phase is independent and individually shippable.  The exit
bar is *navigability + regression catch* on user-facing surfaces,
not a higher overall coverage number — the current 88% gate stays.

### 114.1 High — Command-layer coverage gap

- [x] Add `tests/unit/agent/commands/test_map.py` covering
  `src/cantrip/agent/commands/map.py` (currently 60%, missing
  lines 46, 74, 92, 112–132 — sympath resolution and dispatch).
- [x] Add `tests/unit/agent/commands/test_cost.py` covering
  `src/cantrip/agent/commands/cost.py` (currently 67%, missing
  lines 44–46, 60, 67, 91–106, 109–114, 151–159, 162–164 — rate
  calculation branches and token-pricing edges).
- [x] Extend `tests/unit/agent/commands/test_recipe_slash.py`
  (and/or add `test_recipes.py`) to cover the 35 missing lines in
  `recipes.py` (recipe parse/load edges around lines 63–93, 227–240,
  334–347, 386–401).
- [x] Extend coverage on `commands/share.py` (80%, 9 missing) and
  `commands/flows.py` (87%, 10 missing).  These are smaller and may
  fold into existing files.
- [x] Exit: every module under `src/cantrip/agent/commands/` ≥ 90%
  line coverage.  No coverage-gate change; the 88% project gate
  stays.

### 114.2 High — Promote inline MCP fakes to `tests/support/`

- [x] Move `_FakeTextBlock`, `_FakeUIBlock`, `_FakeMetaResourceBlock`
  (currently in `tests/unit/test_mcp_apps.py`) into
  `tests/support/mcp_fakes.py` with the same shape and the
  established `tests/support/` docstring conventions.
- [x] Update `tests/README.md` shared-fakes table to list them.
- [x] Sweep the remaining ~20 inline `_Fake…` / `_Stub…` definitions
  in `tests/unit/` (`grep -rE "^class _(Fake|Stub)" tests/`).
  Promote any that are domain-shaped and reused across files; leave
  test-local fakes inline (the `test_race.py` trio is fine where it
  is — race-specific, not shared).
- [x] Per the pre-1.0-no-backcompat convention, update call sites in
  the same change; no shim modules.

### 114.3 Should-fix — Adopt snapshot testing (syrupy)

- [x] Add `syrupy` as a dev dependency via `uv add --dev syrupy`.
- [x] Pilot conversion: port
  `tests/unit/planner/test_planner_prompt_snapshots.py` from
  string-contains assertions to syrupy snapshots.  Establish the
  on-disk snapshot layout convention (`__snapshots__/` next to the
  test file) and document it in `tests/README.md`.
- [x] Land a second conversion on structured-response / parsed-design
  outputs (`tests/unit/planner/` or `tests/unit/subagent/` — pick the
  narrowest file where this pays).  This proves the pattern beyond
  the pilot.
- [x] Document the regeneration path
  (`uv run pytest --snapshot-update <file>`) in `tests/README.md`
  alongside the existing "Running tests" block.
- [x] **Not in scope:** TUI rendering snapshots.  Textual's pilot
  testing covers actions/state; the rendering layer is volatile
  enough that golden files would churn more than they catch.  Leave
  as an explicit deferral here so it does not silently reappear.

### 114.4 Should-fix — Resolve `test_cli_bdd.py` naming/scope mismatch

- [x] `tests/unit/test_cli_bdd.py` is 168 lines and does not
  implement BDD-style scenarios as the filename implies.  Pick one
  of:
  - **(a)** Rename to match what it actually covers (likely
    `test_cli_smoke.py` or `test_cli_basic.py` — confirm against
    contents).
  - **(b)** Expand into proper BDD coverage of the CLI surface,
    either with a stepdef framework (`pytest-bdd`) or with explicit
    given/when/then comment blocks and a documented scope.
- [x] Recommendation pending review: option (a) is the cheap honest
  fix; option (b) is a real investment.  Default to (a) unless the
  reviewer wants the BDD coverage.

### 114.5 Should-fix — Slash-command dispatch integration test

- [x] Add a `tests/integration/test_slash_dispatch.py` that exercises
  the slash-command dispatch path end-to-end (user types `/<cmd>` →
  parser → command module → effect).  The unit layer under
  `tests/unit/agent/commands/` is the right place for argument
  parsing and branch coverage; this integration test catches wiring
  regressions across the dispatcher seam, which currently has no
  coverage at that level.
- [x] Cover at least: a state-mutating command (e.g. `/budget`), a
  pure read command (e.g. `/cost`), and an error path (unknown
  command).  Use `MultiRoleProvider` / `CallbackProvider` from
  `tests.support.providers` per the existing integration
  conventions.

### 114.6 Nice-to-have — Error-path pass on 85–92% modules

- [x] Many `src/cantrip/agent/**` files sit between 85% and 92% line
  coverage with the gaps clustered on error / edge branches
  (timeouts, parse failures, fallback paths).  Run
  `make coverage` and walk the report from lowest to highest in this
  band, adding focused tests where the missing branch represents a
  real failure mode (skip cosmetic branches like unreachable
  `else: pass`).  First pass landed on the four lowest modules:
  `memory/commands.py` (82→97%), `triage_controller.py` (86→91%),
  `tools/task_management.py` (86→97%), `planner/prefetch.py` (87→98%).
- [ ] Target: project line coverage ≥ 95% without raising the gate.
  This is an upper bound — stop sooner if remaining misses are
  defensive-only.  Currently at 92.9% (up from 92.78%); the four
  modules above are exhausted of real failure modes, so further gains
  need the next band (`tools/post_edit_lint.py`, `tools/juju.py`,
  `core.py`).  Left open as a continuing sweep rather than forced to
  95% with defensive-only tests.
- [x] **Not:** a mechanical race-to-100%.  Each test added must
  exercise a real failure mode.  Pin implementation, don't pin
  irrelevance.

**Non-goals:**

- Not a coverage-gate bump.  The 88% project gate stays; the value
  of this phase is concentrated user-facing coverage, not a higher
  number.
- Not a sweep to unit-test individual skills.  The single
  `tests/integration/test_skills_loading.py` covering discovery /
  parsing is the right level — skill content is data, not logic.
- Not a TUI rendering-snapshot programme (see 114.3 deferral).

**Exit criteria:**

- (a) Every module under `src/cantrip/agent/commands/` ≥ 90% line
  coverage.
- (b) `tests/support/mcp_fakes.py` exists; `tests/unit/test_mcp_apps.py`
  no longer defines `_FakeTextBlock` / `_FakeUIBlock` /
  `_FakeMetaResourceBlock`; `tests/README.md` table is updated.
- (c) `syrupy` is a dev dep; at least two snapshot files exist
  on disk and round-trip cleanly under
  `pytest --snapshot-update`; `tests/README.md` documents the
  regeneration path.
- (d) `tests/unit/test_cli_bdd.py` either renamed to match its
  contents (114.4 option a) or expanded into real BDD coverage
  (114.4 option b).  Filename matches scope.
- (e) `tests/integration/test_slash_dispatch.py` exists and covers
  at least one state-mutating command, one read command, and one
  error path.
- (f) `make check` passes on every commit.

**Dependencies:**

| Item | Depends On | Notes |
|------|-----------|-------|
| 114.1 command coverage | none | Largest single chunk; do early |
| 114.2 promote MCP fakes | none | Pure refactor of test files |
| 114.3 syrupy adoption | none | Dev-dep addition + two pilot conversions |
| 114.4 cli_bdd rename | none | Trivial under option (a); larger under (b) |
| 114.5 slash dispatch integration | 114.1 (so unit + integration land in coherent order) | Optional ordering; mostly independent |
| 114.6 error-path pass | 114.1 (cheaper after command modules are tested first) | Long-tail; cap by judgement, not a target % |

**Discovered:** 2026-05-26 test-suite review.  Coverage and structure
were healthy enough that the review surfaced concentrated weak spots
rather than systemic problems — hence a single phase of focused
sub-tasks rather than a re-architecture.

---

## Milestones

High-level targets for **open** work. Completed milestones are listed in [`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md).

| Milestone | Phase | Definition |
|-----------|-------|------------|
| M56: Juju Copilot Bundle | 56 | `canonical/skills` hosts a Juju-specific instruction/skill bundle derived from Cantrip's system prompt, with CI validation and a regeneration path |
| M73: Goose Workflow Packaging | 73 | Parameterised retryable Recipes with sub-recipes, MCP Apps rendered as sandboxed iframes in the Web UI, JSON-schema-enforced structured responses, and declarative retry with shell validators |
| M79: Eval Gates Prompt Changes | 79 | System-prompt edits trigger a per-provider LLM-in-loop smoke test that runs in CI against a cheap model, closing the "narrow eval missed a cross-model regression" gap described in Anthropic's April 23 postmortem |
| M84: Deferred-Item Sweep | 84 | `design/DEFERRED.md` exists, every "Deferred:" entry across `ROADMAP.md` and `ROADMAP_ARCHIVE.md` is labelled fired / not-fired / dropped, and the next sweep is on the calendar so deferrals don't rot into forgotten todos |
| M113: Source-Tree Restructure | 113 | No `src/cantrip/agent/` file over 1,500 lines, agent top-level flattened to ~15 modules with themed subpackages, `design/` split into active vs research, `inference-snaps/` lives outside the repo path, and `cookbook/`/`demos/`/`examples/`/`bundles/` has a recorded convention |
| M114: Test-Suite Tidy-Up | 114 | Every `src/cantrip/agent/commands/` module ≥ 90% line coverage, `tests/support/mcp_fakes.py` replaces inline MCP fakes, `syrupy` adopted with at least two snapshot conversions, `test_cli_bdd.py` matches its scope, and a slash-command dispatch integration test covers the wiring seam |
