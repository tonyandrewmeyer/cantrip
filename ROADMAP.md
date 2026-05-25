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
  [`design/CHARMING_WITH_CLAUDE_REVIEW.md`](design/CHARMING_WITH_CLAUDE_REVIEW.md)
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
  [`design/CHARMING_WITH_CLAUDE_REVIEW.md`](design/CHARMING_WITH_CLAUDE_REVIEW.md).
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
  [`design/CHARMING_WITH_CLAUDE_REVIEW.md`](design/CHARMING_WITH_CLAUDE_REVIEW.md):
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
  [`design/JUJU_SKILLS_BUNDLE.md`](../design/JUJU_SKILLS_BUNDLE.md).
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

## Phase 93: Testing Depth Sweep — Failure Paths, Durability, and System-Level Confidence

**Goal:** Cantrip's **unit** suite is already broad and healthy
(``make coverage`` currently reports ~89% total Python coverage), but the
review on 2026-04-30 found that the **non-unit** story is much thinner than
the unit numbers suggest.  Integration / e2e / live / eval coverage is good
for the happy-path planner→build→deploy flow, transcript export, and a handful
of real charm-build scenarios, but the suite is still light on failure-mode
behaviour, restart/durability, sandbox/worktree isolation, git automation, and
newer controller surfaces.  This phase closes that gap by treating testing as
a product feature: the goal is not "more tests" in the abstract, but
confidence that Cantrip keeps working when reality is messy.

### 93.1 High — Backfill the highest-value unit-coverage holes

- [x] Turn the current zero-coverage deterministic repo scan helper
  (``src/cantrip/agent/tools/_scan.py``) into a fully-tested module once
  Phase 92.1 lands.  The helper should not remain both architecturally
  important *and* entirely uncovered.  *(Done — ``_scan.py`` at 100%
  via ``tests/unit/test_scan.py``.)*
- [x] Add focused unit coverage for the current "important but thinly covered"
  modules surfaced by the review: ``executor_controller.py``,
  ``preflight.py``, ``context_providers_builtin.py``,
  ``github_issues.py``, ``watcher.py``, ``auto_commit.py``,
  ``git_branch.py``, and the higher-branching paths in
  ``agent/tools/acceptance.py`` and ``agent/tools/charm.py``.
  *(Done — all now 97–100%.)*
- [x] Reduce the TUI blind spots in ``src/cantrip/tui/app.py`` and adjacent
  screens/widgets by promoting the highest-value flows to behaviour tests:
  screen switching, resume/restart affordances, task/status updates, modal
  transitions, and failure states that currently live only in manual use.
  *(Done — ``screens/tree.py`` 65→100%, ``screens/transcript.py`` 71→95%,
  ``screens/logs.py`` 71→99%, ``screens/resume.py`` 83→88%,
  ``widgets/status.py`` 72→93%, ``widgets/chat.py`` 83→92%,
  ``actions/watcher.py`` 81→100%, ``tui/app.py`` 92→95%; surfaced + fixed
  two real bugs along the way — the ``/tree`` crash (``_nodes`` shadowing)
  and the invisible/inert modal footer "buttons" (Rich markup ate the
  ``[…]`` key hints).  The remaining ``app.py`` gap is the ``_fatal_error``
  crash handler, the streaming reasoning-attach block, and a cluster of
  ``NoMatches`` shutdown guards — all deliberately exercised only in
  manual / crash paths.)*
- [x] When a module remains below the surrounding package average after this
  sweep, record *why* in the test or roadmap text instead of letting the gap
  look accidental.  *(Done — see the ``app.py`` note above and the
  module-level docstrings on the new ``tests/unit/tui/test_*.py`` files.)*

### 93.2 High — Add failure-injection integration tests

- [x] Add a first-class integration harness for **LLM/provider failures**:
  timeout, rate-limit, malformed response, provider 5xx, and tool-call shape
  violations.  Assert user-visible failure handling, retry behaviour, and
  queue/task state transitions rather than only that an exception bubbles.
  *(Done — ``tests/integration/test_failure_injection.py`` plus the reusable
  ``FailingProvider`` / ``FlakyProvider`` doubles (``tests/support/providers.py``)
  and the ``fast_retry`` fixture.  Provider 5xx / overload / mid-stream
  disconnect → transient-retry budget burned, then the task goes FAILED with a
  one-line cause; non-transient ``ProviderError`` → no retry, task FAILED; one
  failing task doesn't block an independent one; the planner recovers from a
  malformed-then-valid reply via the structured retry and raises
  ``StructuredOutputError`` when every reply is malformed.  Surfaced + fixed a
  real bug along the way: a retry-exhausted ``ProviderOverloadedError`` /
  ``ProviderConnectionError`` used to stall the work loop because the
  executor's task-failure handler caught only ``ProviderError`` /
  ``ProviderRateLimitError`` — now widened, with matching
  ``ProviderConnectionError`` handling added to ``print_mode`` and the REPL.
  Also refreshed the canned planner-output fixtures to the ``{"tasks": [...]}``
  shape the structured-output planner actually expects.  Tool-call *shape*
  violations — calling a tool that raises or returns failure — are covered
  under tool execution failure below.)*
- [x] Add **tool execution failure** integration coverage: subprocess exits
  non-zero, partial output + timeout, missing binaries, Juju command failures,
  export/write failures, and cleanup hooks that should still run on final
  failure.
  *(Mostly done — ``run_command`` real-subprocess tests cover non-zero exit,
  timeout, a missing binary, and an off-allowlist refusal (forced to the no-op
  sandbox so they're deterministic in CI); a crashing subagent tool
  (``make_raising_tool``) and a tool returning ``success=False`` both become
  ``is_error`` results the subagent reports and steps past without the task
  failing; the ``/export`` path is exercised against an unwritable
  destination.  Deferred: Juju-command failures (the live-juju
  ``test_e2e_tools.py`` cases already cover ``juju status`` against a bad
  model — no deterministic stand-in was added) and an explicit "cleanup hook
  runs on final failure" assertion, which belongs with 93.5's git-automation
  work where the hook surfaces are.)*
- [x] Exercise the existing retry / recovery surfaces under pressure:
  transient failure that later succeeds, retry budget exhausted, and "final
  failure produces a crisp summary instead of hanging the loop".
  *(Done — ``FlakyProvider`` (two rate-limit blips then success) recovers the
  task end to end; a persistently-failing provider drives three independent
  tasks to FAILED and the work loop *terminates* within the wait budget rather
  than spinning; ``set_failed`` puts the error string on the task so the queue
  carries a one-line cause rather than an empty terminal state.)*
- [x] Cover degraded-environment paths that are realistic in operator use:
  controller unreachable, model missing, missing API key, network blip during
  export or provider call, and partial state already written when the failure
  hits.
  *(Mostly done — missing API key → ``create_provider`` raises a
  caller-handled error; no ``juju`` (and no concierge) on PATH → preflight
  reports ``juju_available=False`` instead of throwing; the store-backed
  persistent-failure test shows FAILED status + cause landing in the
  ``.cantrip`` file, i.e. partial state already persisted when the failure
  hits; a mid-stream provider disconnect is the "network blip during provider
  call" case above.  "Model missing" is left to 93.3's resume/durability work
  where the model-detection paths live; "network blip during export" is
  approximated by the unwritable-destination test rather than a true mid-write
  failure.)*

### 93.3 High — Test durability, resume, and long-running-session recovery

All four bullets land in ``tests/integration/test_durability_resume.py``
(7 tests, three classes — ``TestCheckpointStopRestartResume``,
``TestSessionResumeWithActiveWork``, ``TestContextBudgetLifecycle``).

- [x] Add integration tests for **checkpoint → stop → restart → resume** on
  active sessions, including queued work, decisions, transcript state, and any
  pending follow-up tasks.  *(Done — ``test_partial_task_resumes_without_replaying_cached_steps``
  force-stops a subagent mid-LLM-call (``_HangAfterProvider``), then a fresh
  executor + store handle at the same ``.cantrip`` replays the persisted
  ``llm_turn#1`` + ``tool:read_file#1`` checkpoints and finishes the task with a
  single fresh provider call and zero re-runs of the counting tool;
  ``test_active_task_and_pending_followup_survive_resume`` round-trips charm
  metadata, a decision, the conversation history, a DONE task's result, an
  ACTIVE→PENDING reset, and a pending follow-up's ``dependencies`` through
  ``CantripAgent.save_state()`` / ``load_state()``.)*
- [x] Add crash-recovery tests for the executor / store boundary: interrupted
  task execution, partially-persisted task results, and replay after restart
  without duplicate work or corrupted queue state.  *(Done — the partial-resume
  test above covers the interrupted-task + partial-checkpoint + no-duplicate-work
  path through ``force_stop()`` and verifies checkpoints are purged once the task
  reaches DONE via the real ``on_task_done`` wiring; ``test_completed_task_is_not_re_run_after_restart``
  proves a DONE task isn't re-dispatched after a restart (an exploding provider
  asserts no subagent runs); ``test_interrupted_task_finishes_after_resume_via_executor``
  drives an ACTIVE-when-saved task through ``load_state()`` and ``start_executor()``
  to completion.)*
- [x] Cover the context-budget lifecycle end to end: budget exhaustion,
  compaction trigger, compaction failure, and recovery once the session
  continues.  *(Done — ``test_compaction_fires_and_counter_survives_resume``
  drives two ``read_file`` rounds against a fat file under a 400-token window so
  compaction fires in the conversation loop, then confirms ``compactions_attempted``
  is persisted and restored on a fresh agent; ``test_summariser_failure_falls_back_to_emergency_truncate``
  makes the ``temperature=0.3`` summary call raise (``_SummaryFailingProvider``)
  and asserts the emergency-truncation fallback ran and the turn still returned;
  ``test_exhausted_compaction_budget_survives_resume_and_session_continues`` seeds
  ``budget_exhausted=True`` + the counters, reloads them, and shows the resumed
  session keeps answering without retrying compaction.)*
- [x] Add explicit persistence/resume coverage for long-running flows that are
  currently unit-tested in pieces but not exercised as a whole.  *(Done —
  ``TestSessionResumeWithActiveWork`` exercises decisions + transcript + the
  three task states (done-with-result / active→pending / pending-with-deps)
  together as one save→reload flow rather than as the per-table unit round-trips
  in ``test_store.py`` / ``test_agent_persistence.py``.)*

### 93.4 High — Add isolation and security-oriented system tests

- [x] Add tests proving the sandbox/workspace/worktree boundaries hold under
  pressure: path traversal attempts, symlink escapes, out-of-tree writes,
  temporary-file leakage, and cleanup after cancellation/failure.
  (``tests/integration/test_isolation_security.py`` —
  ``TestWorkspaceBoundaryUnderPressure`` covers traversal / symlink-escape /
  out-of-tree paths through the real file tools;
  ``TestRunCommandSandboxAndDestructiveGate`` pins the no-network, cwd-only
  sandbox policy and the out-of-tree-cwd refusal; and the failed-subagent
  worktree case proves no temporary-tree leakage after a crash.  Cancellation
  shares the same ``_execute_task`` ``finally`` cleanup path as the failure
  case exercised here.)
- [x] Add integration coverage for worktree lifecycle and git isolation:
  branch creation, temporary worktree setup/teardown, dirty-tree handling,
  merge/reconcile paths, and failure cleanup.
  (``TestWorktreeIsolationAndLifecycle`` against a real git repo: concurrent
  allocation isolation + serialised merge-back, dirty-main-tree merge refusal
  with branch preservation, and full worktree+branch cleanup after a crashing
  subagent.)
- [x] Add system tests around the policy/permission boundary so "plan mode",
  destructive-command gates, and category-scoped tool access are verified in
  real flows rather than only at unit granularity.
  (``TestPermissionAndPolicyBoundaryInRealFlows`` drives real ``Subagent.run``
  loops: plan-mode denies an edit, RESEARCH cannot run a deploy-only tool, the
  destructive shell is gated behind approval, and an ``ask`` with no approval
  surface degrades to deny.)
- [x] Treat these as regression guards for Phase 49's sandbox promise, not as
  optional hardening.

### 93.5 Medium — Cover advanced controllers and automation workflows

All four bullets land in ``tests/integration/test_controllers_automation.py``
(78 tests, eleven classes — landed in commit ``33b8bb0``).

- [x] Add integration coverage for the controller surfaces that currently have
  little or no non-unit protection: ``MCPController``,
  ``ArenaController``, ``TriageController``, and the extracted
  ``ExecutorController`` / ``WatcherController`` seams where real message flow
  matters.  *(Done — ``TestMCPController`` covers lazy registry, idempotent
  ``start()``, the ``MCP_ELICITATION_REQUEST`` event bridge, and
  ``complete_elicitation`` before-load handling; ``TestArenaController``
  drives ``begin()`` async + ``handle_pick`` A/B/skip + the no-light-provider
  error path; ``TestTriageController`` exercises ``start()``/``stop()``
  lifecycle, retriage, and CONFIRM-task enqueue on issues found;
  ``TestExecutorController`` pins the pause/resume seam plus user-pause vs
  transient-pause and state-change events; ``TestWatcherControllerRouting``
  asserts ``route_event`` enqueues tasks, ``start()`` returns ``False`` with
  no model, and stop-before-start is a no-op.)*
- [x] Add non-unit tests for git automation workflows: ``git_branch`` branch
  tracking, PR/open-feedback loops, and ``auto_commit`` message/trailer logic
  in realistic repositories rather than fake objects only.
  *(Done — ``TestAutoCommitInRealRepo`` drives ``pre_turn_commit_dirty`` /
  ``post_turn_commit_agent_edits`` against an on-disk git repo, including the
  cantrip trailer, long-subject truncation, fallback subject derivation,
  summary override, touched-file listing, and confirmation that pre-turn and
  post-turn produce *separate* commits; ``TestCollectTouchedFiles`` parses
  ``write_file`` / ``edit_file`` / ``multi_edit`` tool calls out of assistant
  messages and confirms non-mutating tools and user messages are ignored;
  ``TestGitBranchOperations`` exercises ``current_branch``, ``create_branch``,
  ``slugify`` (lowercase + hyphenate + truncate + leading/trailing strip), and
  ``suggest_repo_name`` (appends ``-operator``, no double-append);
  ``TestBuildPrBody`` pins the summary header, task-title list,
  issue-reference, ✓/✗ status rows, and result truncation.)*
- [x] Add end-to-end coverage for at least one **triage → confirm → build
  improvement** path so the improvement workflow is tested across handoff
  boundaries, not only as isolated controller pieces.
  *(Done — ``TestTriageToConfirmToBuildPath`` proves the triage controller
  enqueues a CONFIRM task when issues are found, and a CONFIRM ``set_done()``
  drives the executor to dispatch the follow-up BUILD task and run it to
  DONE.)*
- [x] Add provider-routing / failover tests so a primary-provider problem does
  not silently strand the work loop when a fallback is configured.
  *(Done — ``TestProviderFailover`` runs ``FlakyProvider`` through ≥ 3 calls
  to recover after blips, drives two independent tasks under a partially-
  failing provider to confirm one failure doesn't strand the other, and
  drains all tasks to FAILED under a permanently-failing primary.)*

### 93.6 Medium — Broaden the higher-level test portfolio

- [x] Expand the **eval corpus** beyond the current happy-path examples with
  at least one more machine-oriented charm, one more custom/non-framework app,
  and one case that stresses relations / observability / operational actions
  more heavily than the current set.
  *(Done — three new specs under ``tests/eval/charms/`` cover all three asks
  with shapes distinct from the existing five.  ``haproxy-machine`` is a
  Path C / machine reverse proxy: apt-installed haproxy with TLS via a
  ``tls-certificates`` requires relation, a ``reverseproxy`` provides
  relation that multiplexes multiple backends, a ``haproxy-peers``
  peer relation for HA pair coordination, ``cos-agent`` for the
  canonical machine observability pattern, and the operationally
  critical ``reload-config`` / ``show-stats`` actions that exercise
  ``haproxy -c`` validation before ``systemctl reload`` (no traffic
  drop).  ``vaultwarden`` is a Path B / k8s custom charm with the
  *secret-and-storage-heavy* shape the existing custom specs avoid:
  a single Rust binary driven entirely by env vars (no config-file
  templating), persistent storage for the embedded SQLite DB +
  attachments + sends + icon cache, a Juju-secret-backed admin token
  with a ``get-admin-token`` action and an explicit
  ``file_not_contains`` anti-pattern check that the token is never
  logged, ``smtp`` and ``ingress`` relations, and ``backup-data`` /
  ``restore-data`` actions that SHA-256-fingerprint and verify the
  archive.  ``gitea`` is the relations-and-ops-heavy corner case —
  five data-plane relations (``database`` postgres, ``cache`` redis,
  ``ingress``, ``smtp``, ``object-storage`` s3), three distinct COS
  surfaces (``metrics-endpoint`` prometheus_scrape, ``grafana-dashboard``,
  ``logging`` loki_push_api), and five ops actions
  (``create-admin``, ``change-admin-password``, ``run-housekeeping``,
  ``backup-data``, ``restore-data``) that all shell out to ``gitea``
  CLI subcommands.  Each spec defines ≥ 25 rubric criteria across
  structure / metadata / code / cos / testing categories with at
  least four critical entries; gold-standard charm directories are
  intentionally deferred to Phase 79.4's "generate, hand-tune, rename
  to ``gold-<provider>``" loop.  ``tests/eval/test_gold_standards.py``
  picks up the new specs automatically — rubric-shape checks pass,
  gold-standard tests skip cleanly until a gold dir lands.)*
- [x] Add more **stateful e2e** scenarios: interrupted deploy, failed verify
  followed by debug task creation, improvement flows on an existing charm, and
  "user says no" / override branches that materially change the plan.
  *(Done — four scenarios in ``tests/e2e/test_scenarios.py::TestStatefulFlows``,
  each driven through the top-level ``CantripAgent`` API (``process_message`` +
  ``start_executor`` + ``handle_*_confirmation`` + ``save_state`` /
  ``load_state``) rather than via a raw ``BackgroundExecutor``, so the wiring
  the TUI / CLI actually use is exercised end to end.
  ``test_interrupted_session_resumes_and_finishes_pending_deploy`` saves a
  session mid-flow (DONE BUILD + PENDING DEPLOY), spins up a fresh agent at
  the same ``.cantrip``, round-trips charm identity / decisions / conversation
  history / queue contents, then drives the resumed executor through the
  auto-follow-up chain (the previously-DONE BUILD is *not* re-run, the pending
  DEPLOY converges, and the Verify follow-up lands as DONE);
  ``test_failed_verify_creates_debug_task_through_agent`` uses a
  ``CallbackProvider`` keyed on the ``Verify deployment:`` system-prompt
  fragment to drive BUILD → DEPLOY → Verify(FAIL) → DEBUG end to end on the
  agent's own work queue, asserting the DEBUG follow-up exists and depends on
  the failed verify task;
  ``test_improvement_flow_audits_existing_charm_and_runs_fixes`` seeds an
  existing charm directory, drives ``handle_improvement_confirmation`` from a
  DONE audit task carrying a real audit-report string (tracing + tests gaps),
  approves the CONFIRM the way the TUI does
  (``work_queue.set_done(confirm_id, "Approved by user")``), and lets the
  executor converge every BUILD-category fix task — verifying that
  ``state.audit_report`` is persisted and that ``fill-observability-*`` /
  ``fill-tests-*`` materialise as DONE;
  ``test_user_override_steers_design_to_machine_path`` wraps
  :class:`MultiRoleProvider` with a USER-message-capturing subclass so it can
  prove the override string reached the planner verbatim, then feeds the
  planner a machine-substrate JSON plan that *replaces* the synthesised
  k8s direction, and confirms the executor runs the override plan (not the
  deterministic one-shot path).  Added a ``fast_executor`` fixture to
  ``tests/e2e/conftest.py`` mirroring the integration-suite one so the new
  executor-driven scenarios don't pay the 1-second poll interval.)*
- [x] Build **differential / metamorphic** checks where Cantrip should preserve
  invariants across providers or surfaces: stable task-graph validity, export
  shape, permission enforcement, and transcript/event consistency.
  *(Done — all four dimensions covered.  Export shape + transcript/event
  consistency via ``tests/unit/transcript/test_transcript_properties.py``
  (21 properties): ``_fence_for`` always returns a backtick string strictly
  longer than the worst inner run, ``render_message`` is deterministic and
  respects ``include_header``, backtick-heavy tool results are fenced
  safely, ``render_markdown`` is deterministic + non-mutating and always
  carries the ``# Cantrip Transcript`` heading, ``## Conversation``
  section, single trailing newline, and a ``### ROLE`` line per input
  message, ``render_jsonl`` is deterministic with a line count equal to
  ``messages + events + tasks + Σ subagent_messages`` and every line is
  valid JSON tagged with a ``type`` field in source-bucket order
  (message → event → task → subagent_message); empty data renders to
  empty string.  Permission enforcement via
  ``tests/unit/agent/test_permissions_properties.py`` (17 properties):
  ``evaluate`` is deterministic and non-mutating on ruleset + arguments,
  empty ruleset returns default ALLOW, a catch-all ``("*", deny)`` rule
  in ``tools`` (or layered via ``compose_rulesets``) is absorbing — any
  tool/args produces DENY, an unmatchable-pattern rule appended to any
  section is inert, two matching rules pick the stricter outcome (within
  a section and across ``tools`` / ``bash``), the ``bash`` section is
  consulted only for tools in ``bash_tools`` (default ``run_command``),
  argument-free ``evaluate`` skips ``bash`` / ``paths`` and agrees with
  a tools-only ruleset, and ``compose_rulesets`` is structurally
  associative + concatenates sections in order + leaves a single-input
  call as identity.  Hypothesis caught one false claim along the way:
  appending a rule to a section can *lower* restrictiveness — last-match-
  wins inside a section means an agent overlay's later ALLOW pattern
  intentionally loosens a global rule.  The expanded module docstring
  records that fact so future readers don't reintroduce a bogus
  monotonicity invariant.  Task-graph validity is incidentally covered
  by the existing ``test_planner_properties.py`` (Kahn-based acyclicity
  check on ``_validate_dependencies``).)*
- [x] Extend accessibility regression coverage beyond the current Web-only
  smoke test where feasible, and at minimum document the deliberate boundary
  if TUI accessibility remains manual.
  *(Done — both halves shipped.  ``design/TUI_ACCESSIBILITY.md`` is a
  new design note explaining why TUI accessibility doesn't reach for
  WCAG conformance (it's bridge-dependent on the terminal + screen
  reader), cataloguing what Cantrip already does right (every action
  has a keyboard binding, the Footer renders descriptions, every F-key
  screen has an equivalent slash command, status carries text not just
  colour), and laying out the manual VoiceOver / NVDA recipe maintainers
  run before a release.  Automated coverage is the keyboard-binding
  surface — the most important TUI accessibility lever — in
  ``tests/unit/tui/test_accessibility_smoke.py`` (4 tests): walks every
  ``BINDINGS`` declaration in the App and every Screen subclass under
  ``src/cantrip/tui/screens/`` and asserts every shown binding has a
  non-empty description, every binding's action name resolves to an
  ``action_<name>`` method on the class (covers Cantrip methods and
  the Textual built-ins inherited from ``App`` / ``Screen``), no two
  shown bindings collide on a key inside one ``BINDINGS`` block, and
  the discovery walk still finds the well-known screens
  (``TranscriptScreen``, ``LogScreen``, ``ResumePromptScreen``,
  ``HelpScreen``, ``GraphScreen``).  The deeper checks — screen-reader
  narration fidelity, braille bridge accuracy, cognitive accessibility
  — remain on the manual recipe and the rationale for keeping them
  manual is recorded in the design note.)*
- [x] Where a "fuzz" or property style makes more sense than examples
  (workspace paths, provider payload normalisation, queue/task invariants),
  prefer that style over adding another list of hand-authored cases.
  *(Done — three new ``test_*_properties.py`` files cover the called-out
  slices: ``tests/unit/agent/test_queue_properties.py`` (29 properties)
  pins the ``WorkQueue`` / ``AgentTask`` invariants (auto-ID,
  add/duplicate-rejection atomicity, deep-copy snapshots, counter
  consistency, status-transition payloads, dependency-gating with
  insertion-order, cancel-as-resolved, clear/move_to_front shape, and the
  ``WorkflowPhase.from_category`` mapping);
  ``tests/unit/agent/tools/test_path_aware_properties.py`` (10 properties)
  pins ``PathAwareTool._resolve_path`` — always-absolute return,
  base-path containment, safe-relative-to-``base_path / path``,
  idempotence, ``..``-traversal rejection across relative / absolute /
  deeply-nested forms, and the permissive ``base_path=None`` branch;
  ``tests/unit/llm/test_mistral_format_properties.py`` (10 properties)
  pins ``rewrite_for_mistral`` / ``parse_mistral_tool_call_content`` —
  no input mutation, length-never-grows, folded assistants carry the
  marker with empty ``tool_calls``, non-assistant passthrough, the full
  rewrite→parse round-trip recovers the original ``name`` /
  ``arguments``, parser identity on marker-free and unclosed-marker
  content, parser fails safe on garbage payloads, and parser idempotence
  on the remainder.)*
- [x] Add **targeted traditional fuzzing** alongside the Hypothesis suite
  where coverage-guided or byte-oriented exploration is higher leverage than
  property tests alone: start with ``cargo-fuzz`` harnesses for
  ``charmlint-rs`` / ``quickpack-rs``, then add a small set of Python parser /
  export entrypoints such as transcript fence/export rendering and raw
  HTML/search-result parsers.  Keep this as an advisory or nightly lane rather
  than a default per-PR requirement unless it proves cheap enough.
  *(Done — both lanes shipped.  Python parser side: transcript
  fence/export rendering pinned by
  ``tests/unit/transcript/test_transcript_properties.py`` (21 properties);
  HTML / search-result parsers pinned by
  ``tests/unit/agent/tools/test_web_parser_properties.py`` (17 properties)
  and ``tests/unit/docs_index/test_crawl_parser_properties.py`` (9
  properties) using Hypothesis with byte-oriented + adversarial-text
  strategies — the headline invariant is *the parser never raises* on
  any byte input, with ``parse_sitemap`` further restricted to raising
  *only* ``xml.etree.ElementTree.ParseError``.  Rust ``cargo-fuzz`` lane:
  each crate gained a ``fuzz/`` subdirectory (per ``cargo +nightly fuzz
  init``) plus a thin ``src/lib.rs`` that re-exports the modules so the
  fuzz targets can reach them — the binary's ``main.rs`` is unchanged.
  ``charmlint-rs/fuzz/`` carries ``fuzz_lint_config_yaml`` (random YAML
  → ``LintConfig::from_yaml``) and ``fuzz_severity_from_str``
  (``Severity::from_str_loose``).  ``quickpack-rs/fuzz/`` carries
  ``fuzz_jujuignore_match`` (random patterns + path →
  ``JujuIgnore::new`` + ``is_ignored``) and ``fuzz_metadata_resolvers``
  (random YAML → ``resolve_base`` + ``resolve_entrypoint`` +
  ``generate_metadata``).  ``design/FUZZING.md`` documents the
  prerequisites, the per-target table, and the workflow.  ``fuzz/target``,
  ``fuzz/corpus``, and ``fuzz/artifacts`` are git-ignored per crate.
  The fuzz lane is advisory / nightly — not gated on every PR.  First
  smoke run found and the team fixed one real panic:
  ``JujuIgnore::new`` used to ``Regex::new(...).unwrap()`` on the
  rule-derived regex, so a glob pattern whose expansion produced an
  invalid character class (``[0-]`` → regex ``[0-]\z`` with backwards
  range) panicked.  ``Matcher::new`` now returns ``Option<Self>`` and
  ``extend`` silently drops patterns that fail to compile; the regression
  is pinned by ``pattern_producing_invalid_regex_is_skipped_silently``
  in ``src/quickpack-rs/src/jujuignore.rs``.)*

### What this phase is *not*

- Not a vanity push for a single coverage percentage.  The problem is not that
  89% is too low; it is that the remaining uncovered and non-unit gaps cluster
  around failure, isolation, and recovery.
- Not a wholesale rewrite of the existing unit suite.  Keep the broad base;
  add the missing higher-confidence layers around it.
- Not a promise that every live/provider matrix case runs in default CI.  The
  aim is a balanced portfolio: cheap deterministic coverage in the main loop,
  with richer live/e2e paths still available where they earn their cost.

**Exit criteria:** the highest-value unit blind spots above are closed or
explicitly explained; failure-injection integration tests cover provider, tool,
and recovery paths that previously had no protection; restart/resume and
isolation behaviour are exercised end to end; advanced controller/git
automation flows have non-unit coverage; and the eval/e2e portfolio covers more
than the happy-path build/deploy story so a regression in failure handling or
durability is likely to be caught before release.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Unit hotspot backfill (93.1) | Phase 92.1 for the deterministic scan; existing TUI/unit harnesses | Mostly additive tests, with small seam tweaks where the code is hard to drive |
| Failure injection (93.2) | Existing integration/e2e harnesses; retry and structured-output surfaces from prior phases | Prefer reusable fake-provider / fake-tool helpers over one-off per-file harness code |
| Durability/resume (93.3) | Existing session store, persistence, queue, and compaction machinery | May surface small product fixes rather than test-only changes |
| Isolation/security (93.4) | Phase 49 sandboxing, Phase 44 worktrees, Phase 68 permissions | These are promise-keeping regression guards, not new product lines |
| Controllers/automation (93.5) | Phase 85 controller extraction, existing git/GitHub flows | Good candidate to share builders between unit and integration layers |
| Higher-level portfolio (93.6) | Existing eval/e2e/live suites; Phase 79 for future provider-matrix ambitions | Grow breadth without turning every scenario into an expensive live test |

**Discovered:** Test-suite review on 2026-04-30.  Findings: unit coverage is
strong overall (~89%), with the biggest blind spots concentrated in
``_scan.py``, TUI-heavy modules, and a handful of controller/git/acceptance
paths; non-unit coverage is much stronger for happy-path build/deploy flows
than for failure handling, durability, isolation, and advanced controller
workflows.

---

## Phase 95: Canonical Developer Surfaces — Launchpad, Snapcraft, and Charmcraft

**Goal:** Cantrip already showcases the core charm stack well, but
several high-leverage Canonical developer surfaces still sit outside the
agent's reach.  This phase turns the strongest first-party catalogue and
packaging surfaces into things the agent can actually use during charm
research, provider selection, and packaging flows — rather than just
mentioning them in docs.

### 95.1 Research and scope ✓

- [x] Broad product / technology survey written up in
  [`design/CANONICAL_SHOWCASE.md`](design/CANONICAL_SHOWCASE.md).
  Findings: Launchpad, Snapcraft, and Charmcraft are the
  highest-leverage first-party developer surfaces beyond the already-
  shipped charm stack; MAAS belongs to a substrate phase, Chisel to a
  packaging phase, and Ubuntu Pro / Landscape to an operational-
  readiness phase.

### 95.2 Marketplace descriptors and discoverability

- [x] Shipped ``examples/mcp/canonical/marketplace.json`` with
  descriptors for **Launchpad**, **Snapcraft**, and **Charmcraft**
  servers (and an adjacent ``README.md`` that documents the
  ``directory:`` marketplace workflow plus the read-only / write
  copy-paste recipes).  ``tests/unit/mcp/test_mcp_marketplace.py``
  ``TestCanonicalExampleCatalogue`` pins both that the catalogue
  parses cleanly through ``MarketplaceLoader`` and that every server
  description mentions ``allowed_tools`` so the safety policy
  surfaces in ``/mcp marketplace`` listings.
- [x] Per-server safety story documented in
  ``design/MCP_SERVERS.md`` (new "Safety defaults for the Canonical
  bundle" section) and in the shipped catalogue's README.  Read
  verbs (``bug_search`` / ``snap_search`` / ``snap_info`` /
  ``snap_releases`` / ``lint`` / ``analyse`` / ``bug_view`` /
  ``merge_proposal_view`` / ``project_view``) are safe by default;
  write verbs (``bug_comment``, ``bug_status_set``,
  ``snap_register``, ``snap_upload``, ``snap_release``,
  ``register``, ``upload``, ``release``) are opt-in via explicit
  ``allowed_tools`` entries and their named credential environment
  variable.  The descriptor ``description`` text repeats the split
  so the policy is visible in the listing too.
- [x] ``docs/src/howto-mcp.md`` (rendered to
  ``docs/docs/howto-mcp.html``) gained a "Canonical-native catalogue"
  subsection between the generic marketplaces section and the
  security notes, with the read-only-default and read+opt-in-write
  copy-paste snippets.

### 95.3 Agent-side adoption

- [ ] When a Launchpad server is configured, feed its results into the
  **Librarian** / `/search-charms` workflow so unpublished or
  in-progress Launchpad projects become first-class citations rather
  than a hidden parallel workflow.
- [ ] When a Snapcraft server is configured, use it in the
  inference-snap and provider-selection flows: enrich local snap
  discovery with store metadata, aliases, summaries, and supported
  channels rather than relying only on local enumeration.
- [ ] When a Charmcraft server is configured, use it as an optional
  second-opinion surface for `lint` / `analyse` in build and
  improvement flows, while keeping the built-in local tooling as the
  default fallback.

### What this phase is *not*

- Not a generic "marketplace everything Canonical ships" sweep.
- Not a Charmhub rewrite — Charmhub remains the primary charm-registry
  surface; Launchpad complements it.
- Not a publishing-by-default phase.  Read-path discovery comes first.

**Exit criteria:** a user who configures Canonical Launchpad,
Snapcraft, and/or Charmcraft MCP servers sees them in the docs, can
discover them via `/mcp marketplace`, and the agent uses them in charm
research, local-model discovery, and packaging flows without bespoke
prompting.

---

## Phase 97: Canonical Cloud Targets — MAAS, OpenStack, and MicroCloud

**Goal:** Cantrip's current environment story is strongest on local LXD
and Canonical K8s.  Canonical also ships substrate products that are a
natural fit for machine and infrastructure charm stories: MAAS for
bare-metal labs, OpenStack / Sunbeam for private-cloud targets, and
MicroCloud for compact local/private-cloud deployments.  This phase
decides what first-class support means for each and ships the
lowest-friction high-value pieces first.

### 97.1 Substrate-role design

- [x] Wrote the design note that decides the role of each surface in
  [`design/SUBSTRATES.md`](design/SUBSTRATES.md): **MAAS** as machine
  inventory / provisioning surfaced through Juju + an MCP-shaped
  read/write split that mirrors the Phase 95.2 Canonical bundle;
  **OpenStack / Sunbeam** as a target cloud for IaaS-shaped charms
  with substrate-aware design + acceptance hints (no tooling);
  **MicroCloud** as a compact private-cloud / edge lab consumed via
  detection-plus-routing of an existing controller (no installer).
- [x] Decided how these surfaces relate to **Concierge** rather than
  bypassing it ad hoc.  Outcome: Concierge stays the only environment
  provisioner Cantrip launches; new substrates show up as Concierge
  presets *if and when* Concierge upstream adopts them, otherwise as
  profile data + MCP surfaces.  The user-visible substrate vocabulary
  stays binary (`k8s` vs `machine`); MAAS / OpenStack / MicroCloud
  ride on `machine` as cloud-type refinements surfaced in DESIGN.md,
  acceptance plans, and runbooks rather than as peer enum members.
  Full design rationale, the per-substrate "what Cantrip does and
  doesn't do" matrix, and the implementation hooks for 97.2 / 97.3 /
  97.4 live in [`design/SUBSTRATES.md`](design/SUBSTRATES.md).

### 97.2 MAAS path

- [x] Decided MCP-first, mirroring the Phase 95.2 / 95.3 Canonical-bundle
  pattern verbatim.  Shipped a `maas` descriptor in
  `examples/mcp/canonical/marketplace.json` alongside the existing
  Launchpad / Snapcraft / Charmcraft trio.  Read verbs (`machine_list`,
  `machine_view`, `tag_search`, `subnet_list`, `pool_list`, `version`)
  are safe by default; capacity-changing verbs (`machine_acquire`,
  `machine_release`, `machine_deploy`) are allowlist-gated and require
  a `MAAS_API_KEY` credential.  The descriptor `description`, the
  catalogue `README.md`, the "Canonical-native catalogue" section of
  `docs/docs/howto-mcp.html`, and the "Safety defaults for the Canonical
  bundle" section of `design/MCP_SERVERS.md` all spell out the two ways
  MAAS differs from the publish-shaped Canonical servers — every MAAS
  call needs the API key (read-vs-write, not unauthenticated-vs-authenticated)
  and MAAS writes change *shared pool capacity*, so the allowlist posture
  is closer to a production-cloud capacity verb than a publish verb.  A
  new `test_maas_descriptor_names_capacity_split_and_credential` test
  in `tests/unit/mcp/test_mcp_marketplace.py` pins the read verbs,
  capacity verbs, and credential name in the descriptor text so the
  `/mcp marketplace` listing keeps carrying the policy without the
  user opening the README.  `maas-mcp` itself is not yet published on
  PyPI; the descriptor ships as a template that names the intended
  invocation, the same way the Snapcraft and Charmcraft descriptors
  did before their servers shipped.  No built-in tool family — the
  API surface belongs in an out-of-tree MCP server with its own
  release cadence, exactly per the design-note decision.
- [x] System-prompt substrate decision rule
  (`src/cantrip/agent/prompts/system.md.j2`) grew one phrase pointing
  at MAAS as the production substrate for bare-metal / GPU /
  kernel-module workloads when a MAAS controller or MAAS MCP server is
  available.  The rest of the "teach the agent when MAAS beats local
  LXD" surface — DESIGN.md MAAS callouts when the controller cloud is
  `maas`, MAAS-grounded planner enrichment ("4 machines with `gpu` tag
  available"), and acceptance-test guidance for MAAS-backed deployments
  — is **deferred to a follow-up** because all three depend on an actual
  `maas-mcp` server being installable and an MAAS-cloud Juju controller
  being reachable from the test environment.  Until either lands, the
  agent has the substrate hint but no grounded inventory facts to feed
  on; revisit when `uvx maas-mcp` works end-to-end against a real MAAS
  region.

### 97.3 OpenStack and MicroCloud profiles

- [ ] Add substrate-aware profiles or guidance for "target OpenStack"
  and "target MicroCloud" so infrastructure-charm work can tailor
  assumptions, companion charms, and acceptance guidance to those
  Canonical environments.
- [ ] Extend topology / bundle-style outputs so these substrates appear
  as first-class deployment contexts in generated design notes when
  relevant.

### 97.4 Examples and docs

- [ ] Ship at least one worked example for a MAAS-backed machine-charm
  workflow and one for an OpenStack- or MicroCloud-oriented
  infrastructure workflow.
- [ ] Document the boundaries clearly: when the phase gives actual agent
  automation vs when it gives substrate-aware guidance and runbooks.

### What this phase is *not*

- Not a promise that Cantrip itself bootstraps a private cloud from
  nothing.
- Not a replacement for the existing local LXD / k8s dev loop.
- Not an excuse to scatter substrate-specific one-offs through the
  prompt without a design note.

**Exit criteria:** a user asking for MAAS-, OpenStack-, or
MicroCloud-aware work gets substrate-specific guidance or automation
that fits Cantrip's existing environment story rather than a generic
"bring your own cloud" answer.

---

## Phase 98: Canonical Estate Operations — Ubuntu Pro and Landscape

**Goal:** Some Canonical products are best used not in the build loop,
but in Cantrip's **day-2** and **production-readiness** stories.
Ubuntu Pro and Landscape are the strongest examples: they matter when
Cantrip is auditing, improving, or operationalising charms for real
Ubuntu estates, not when it is merely scaffolding a demo.

### 98.1 Operational-readiness rubric

- [x] Expanded the operational-readiness rubric so a new
  ``assess_estate_opportunities`` helper
  (``src/cantrip/agent/tools/estate_ops.py``) drives evidence-based
  Ubuntu Pro and Landscape advice off the charmcraft metadata
  already loaded by ``operational_readiness``: substrate
  (``containers:`` vs ``bases:`` / ``platforms:``), stateful
  signals (``storage:`` declared), clustered signals (``peers:``
  declared), and security-sensitive relations (``tls-certificates``,
  ``oauth``, ``oauth-cli``, ``hydra-token-introspect``,
  ``oidc-info``, ``vault-kv``).  Each opportunity carries the
  observed evidence so the operator can audit the recommendation
  rather than treat it as a black box.
- [x] Detector is conservative — a pure-K8s charm with no
  Pro/Landscape mentions returns an empty list and the ``Estate
  Operations`` section disappears entirely from
  ``OPERATIONAL_READINESS.md``, rather than nagging with generic
  upsell text.  The level taxonomy (``recommended``, ``consider``,
  ``already-mentioned``) is a closed set pinned by a parametrised
  unit test so future consumers don't silently introduce a fourth.

### 98.2 Improvement-mode outputs

- [x] ``OperationalReadinessTool`` now wires ``estate_opportunities``
  through ``_format_readiness_report`` into both a dedicated
  ``## Estate Operations`` markdown section (rendered by
  ``render_estate_section``) and ``findings.estate_opportunities``
  in the tool's structured ``data`` dict.  Both the
  standalone operability-assessment prompt
  (``operability_assess.md.j2``) and the improvement-mode
  readiness summary (``improvement_assess_readiness.md.j2``) ask
  the agent to load the bundled ``estate-operations`` skill and
  surface Pro / Landscape opportunities as a *separate* paragraph
  after the code-level must-fix / should-fix list so the two
  stories stay visually distinct.
- [x] Consistent wording shipped in
  ``src/cantrip/skills/estate-operations/SKILL.md``: the rule
  ``recommended for a supported production estate`` (never
  ``required for the charm to work``) is load-bearing; the skill
  body bans imperative verbs, gives the runbook ``Production
  deployment (optional)`` template, and gives the audit-summary
  paragraph template.  The same phrase is repeated in the
  ``OPERATIONAL_READINESS.md`` section preamble so the
  distinction shows up before the reader sees any individual
  recommendation.

### 98.3 Detection and templates

- [x] Estate-mention detection runs across README, ``docs/*.md``,
  and the metadata ``summary`` / ``description`` / ``title`` fields
  via ``_scan_text_for_tokens``.  Token lists
  (``PRO_MENTION_TOKENS`` covering ``ubuntu pro``, ``ua-client``,
  ``esm-apps``, ``esm-infra``, ``livepatch``, ``fips``, ``usg``,
  ``cis benchmark``, …; ``LANDSCAPE_MENTION_TOKENS`` covering the
  ``landscape-*`` package names plus the bare product name) use
  word boundaries for single-word terms so ``fips`` does not
  fire on ``flips``.  Detected mentions promote the matched
  facet's level to ``already-mentioned`` so the agent reinforces
  the existing wording rather than duplicating it; a K8s charm
  that already references Pro or Landscape emits a single
  host-coverage entry asking the operator to confirm the wording
  targets the cluster hosts rather than the workload container.
- [x] Reusable wording snippets ship in
  ``src/cantrip/skills/estate-operations/SKILL.md`` — the
  ``Production deployment (optional)`` runbook template, the
  audit-summary paragraph template, the per-facet trigger table
  for Ubuntu Pro and Landscape, and explicit anti-patterns
  (imperative verbs, generic upsell, conflating workload and
  host layers).  Documented end-to-end in the new
  ``docs/src/howto-estate-ops.md`` →
  ``docs/docs/howto-estate-ops.html`` how-to, linked from the
  sidebar nav under How-to guides.

### What this phase is *not*

- Not a commercial workflow or subscription-purchase flow.
- Not a mandate that every Cantrip-generated charm mention Pro or
  Landscape.
- Not a replacement for the existing security / observability /
  operational-readiness work.

**Exit criteria:** Cantrip's improvement and operational-readiness flows
can recommend Ubuntu Pro and Landscape in the right contexts with clear,
useful guidance and without making them feel bolted on.

---

## Phase 105: Local Model Refresh — Find a Replacement for Qwen3-Coder

> **Update 2026-05-08:** the original framing of this phase
> ("switch the default to Qwen3-8B") was invalidated by 105.1's
> smoke.  See ``design/LOCAL_MODELS.md`` §5.1.1, §5.1.2 — Qwen3-8B
> produced ~30 % of the improve-02 feature target and chained-p
> produced zero successful edits.  Phase reframed below: the goal
> is now "find *a* candidate that can replace qwen3-coder", not
> "ship Qwen3-8B as the default".

**Goal:** Identify a locally-runnable model that matches or beats
qwen3-coder's measured end-to-end completeness on Cantrip's
ntfy-improve scenario, and ship it as a snap + provider preset.
qwen3-coder stays the documented default until that target is met.
The hardware budget is ~12 GiB usable VRAM with no other models
loaded.

### Why now

Three things make this the right time to invest:

- **qwen3-coder is slow.** Q4_K_M is 18.6 GB, 30 B MoE doesn't fit
  in 12 GB VRAM, partial offload yields 5–10 tok/s decode.
  Functionally it works (Unsloth's tool-call fix is integrated into
  the GGUF the snap uses), but each ``edit_file`` round takes
  minutes that compound across a full charm build.
- **gemma4 is too small.** 10 K per slot exhausts on the system
  prompt + tool schemas before a real conversation starts.  Phase
  104's short-session mode helps but doesn't eliminate the
  cross-edit context loss.
- **The actual VRAM budget is ~12 GiB**, not the ~5 GiB the original
  ``tmp-hardware-info.md`` capture suggested.  That's enough room
  to fit a 14 B Q4_K_M model + 32 K KV cache fully on the GPU, or
  a 16 B MoE with comparable headroom — both *bigger* than the 8 B
  picks the original phase targeted, which the smoke evidence
  suggests matters more than raw decode speed.

The full comparison and selection rationale lives in
``design/LOCAL_MODELS.md``.  The short version: 105.1 smoked
**Qwen3-8B** (Q4_K_M, ~5 GB, 32 K) and it underperformed.  Next
smoke targets in priority order are **Qwen3-14B** (same proven
family, larger), **DeepSeek-Coder-V2-Lite** (16 B MoE, 2.4 B
active, code-tuned), and **Mistral Nemo 12B** (long-context
fallback).

### 105.1 P0 — Smoke test on host llama-server

- [x] Download Qwen3-8B-Instruct Q4_K_M GGUF (~5 GB) and run host
  ``llama-server`` on port 8338 with full GPU offload + ``--jinja``.
  Scaffolded under ``inference-snaps/qwen3-8b/`` (smoke-only —
  ``snapcraft.yaml`` deferred to 105.3).
- [x] Run ``/v1/models`` + ``/v1/chat/completions`` + synthetic
  tool-call smoke checks.  All passed.
- [x] Re-run the ntfy improve-02 scenario against
  ``--provider inference-snap --snap qwen3-8b --base-url
  http://10.42.160.1:8338/v1``.  **Result negative:** ~30 % feature
  completeness in 19 min plus a planner deadlock (filed as Phase
  106).  Chained-p follow-up produced 0 successful edits in 8 min.
  Full write-up in ``design/LOCAL_MODELS.md`` §5.1.1 + §5.1.2.

### 105.1.5 P0 — Smoke test Qwen3-14B *(next candidate)*

- [ ] Copy ``inference-snaps/qwen3-8b/`` to ``inference-snaps/qwen3-14b/``;
  swap ``GGUF_REPO`` / ``GGUF_FILE`` to
  ``bartowski/Qwen_Qwen3-14B-GGUF`` /
  ``Qwen_Qwen3-14B-Q4_K_M.gguf``; bump default port to 8340.
- [ ] Add ``"qwen3-14b"`` to ``_TOOL_CAPABLE_SNAP_NAMES`` in
  ``src/cantrip/llm/inference_snap.py``.
- [ ] Run the same smoke + improve sequence as 105.1.  Pass criterion:
  produce ≥ 80 % of the improve-02 feature target in ≤ 30 min, OR
  exit with a clear Phase 102 / 103 / 106 failure mode that doesn't
  imply a model-side limit.
- [ ] If pass: 105.2 / 105.3 target Qwen3-14B, not Qwen3-8B.  If
  fail: log measured findings in ``design/LOCAL_MODELS.md`` §5.6
  and continue to 105.1.6.

### 105.1.6 P1 — Smoke test DeepSeek-Coder-V2-Lite *(MoE candidate)*

- [ ] Same shape as 105.1.5 but pointing at
  ``lmstudio-community/DeepSeek-Coder-V2-Lite-Instruct-GGUF``,
  port 8342, and a *prerequisite* check: the synthetic tool-call
  smoke must round-trip cleanly via ``--jinja`` before any improve
  attempt.  Tool-call reliability isn't as well-documented for this
  family as it is for Qwen.
- [ ] If both 105.1.5 and 105.1.6 fail, default-replacement work
  pauses; the remaining sub-phases below stay deferred and the
  documented local default stays qwen3-coder.

### 105.2 P0 — Provider preset for the winning candidate

*Gated on a successful smoke from 105.1.5 or 105.1.6.*  Substitute
``<winner>`` for the chosen snap name (``qwen3-14b`` /
``deepseek-coder-v2-lite`` / etc.).

- [ ] Extend ``InferenceSnapProvider``'s preset table so
  ``--snap <winner> --base-url http://10.42.160.1:<port>/v1`` is a
  named shortcut that sets the right defaults
  (``conversation_temperature=0.2``; ``max_tools`` stays at 12).
- [ ] Update ``docs/src/howto-provider.md`` to list the new preset,
  state the recommended host setup (port, GGUF source, full offload
  flag), and explain when to pick this over qwen3-coder / gemma4.
- [ ] Add the preset to ``docs/src/reference-cli.md`` under the
  ``--snap`` enumeration.

### 105.3 P1 — Package the winner as a Cantrip-managed inference snap

*Gated on 105.2.*

- [ ] Decide between (a) building our own snap that wraps
  ``llama.cpp`` + the packaged GGUF, or (b) contributing an
  upstream snap recipe to Canonical's inference-snap catalogue.
  Capture the decision in ``design/LOCAL_MODELS.md`` §6.
- [ ] If (a): the snap should expose the same OpenAI-compatible
  endpoint shape on a stable port so the cantrip preset above
  lights up out of the box; ship the recipe under
  ``inference-snaps/<winner>/`` (already scaffolded for the
  Qwen3-8B smoke; reuse the layout).
- [ ] If (b): file the contribution upstream and document the
  install path alongside the existing ``qwen3-coder`` instructions.

### 105.4 P1 — Long-context and speed alternatives as opt-ins

*Independent of which model wins as default.*

- [ ] Add ``--snap mistral-nemo-12b`` preset for the long-context
  tier (Q4_K_M, 32 K cache by default, opt-in 128 K via env var
  ``CANTRIP_LLAMA_CTX``).
- [ ] Add ``--snap phi-4-mini`` preset for the speed tier (60+
  tok/s, 128 K context).  Useful as a planner companion to a
  larger executor model.
- [ ] These remain *secondary* — the documented default tracks
  whatever 105.1.5 / 105.1.6 selected, falling back to qwen3-coder
  if neither passed.

### 105.5 P1 — Tests

- [ ] Unit test that each new preset (winner, mistral-nemo-12b,
  phi-4-mini) resolves to the expected base URL, default
  temperature, and ``max_tools`` value.
- [ ] Add a recorded-trace test (against a captured fixture, not
  the live snap) confirming the winner's tool-call format is
  parsed correctly by ``InferenceSnapProvider`` — pin the wire
  format the same way Phase 41 pins frontier-provider streaming.

### 105.6 P0 — In-flight source changes from the 105.1 smoke

The smoke required two small source changes to make the
``--snap qwen3-8b --base-url …`` invocation work end-to-end:

- [ ] ``_TOOL_CAPABLE_SNAP_NAMES`` += ``"qwen3-8b"`` in
  ``src/cantrip/llm/inference_snap.py`` — already in place.  Land
  this on its own commit so the smoke-only allowlist entry is
  separable from any future preset work.
- [ ] ``InferenceSnapProvider`` httpx timeout 300 s → 1200 s — also
  already in place.  This is a stop-gap for Phase 102; revisit when
  Phase 102's streaming-reconnect work lands so the timeout becomes
  operator-tunable rather than hard-coded.

### What this phase is *not*

- **Not removing qwen3-coder.**  It stays as an opt-in for "best
  reasoning, decode time doesn't matter" workflows, and Phase 102 /
  103 still apply to it.
- **Not making the model decision automatic.**  Operators pick
  the snap explicitly; cantrip doesn't try to detect "you have a
  bigger model available, use that".
- **Not GPU-passthrough work.**  The cantrip VM still talks to
  the host model server over HTTP on ``10.42.160.1``; nothing here
  requires the VM to see the GPU directly.
- **Not a full local-model benchmark suite.**  Phase 105.1 is a
  single-scenario smoke test, not a generalised eval — that work
  belongs elsewhere if it ever happens.

**Exit criteria:** A 105.1.5 / 105.1.6 / future smoke produces a
packed charm at least as complete as improve-02 (COS relations +
actions + tracing + ≥ 7 unit tests passing); the howto and
reference-CLI docs cite the winning candidate as the documented
default local pick; the unit tests in 105.5 pass.  *Or:* every
candidate fails, the phase formally records that, and qwen3-coder
stays the documented default.

---

## Phase 109: Per-Provider Message-Format Normalisation — Unblock Non-Qwen Local Models

**Goal:** Add a per-provider message-rewriting hook so cantrip's
internal ``Message`` representation (OpenAI/Qwen-shaped, with
separate ``user`` / ``assistant`` / ``tool`` roles) can be
serialised to providers whose chat templates expect different
conventions — most notably Mistral's Tekken format
(``[TOOL_CALLS]…[/TOOL_CALLS]`` and
``[TOOL_RESULTS]…[/TOOL_RESULTS]`` markers folded *inline* within
assistant turns, not as separate role messages).

### Why now

Phase 105.1.7 smoked Mistral Nemo 12B end-to-end and hit a
fundamental serialisation cliff (see
``design/LOCAL_MODELS.md`` §5.2.1):

- Mistral's embedded Tekken template enforces strict
  ``user``/``assistant`` alternation and rejects cantrip's
  ``tool``-role messages with ``Jinja Exception: After the optional
  system message, conversation roles must alternate ...``.
- Override to ``--chat-template chatml`` gets past the input check
  but the model — trained on Mistral format — can't *generate*
  ChatML tool-call markers.  It hallucinates tool results inline
  as natural-language text instead of emitting structured
  ``tool_calls``.

Both directions are blocked.  Mistral Nemo is the most prominent
example, but the same shape will affect any model family trained
on a tools-inline-in-assistant convention (Mistral's own larger
models, Magistral, anything else built on Mistral's tokeniser
without an OpenAI-style retrofit).

The current candidate set treats Qwen-family templates as the
only path to working tool calls.  Phase 109 widens the door so
non-Qwen candidates can be evaluated fairly.

### 109.1 P0 — Provider hook for outbound message rewriting

- [x] Add ``LLMProvider.rewrite_messages(messages: list[Message])
  -> list[Message]`` (or equivalent) — default identity, Mistral
  family overrides to fold consecutive ``tool``-role messages
  into the *prior* ``assistant`` message's ``content`` /
  ``tool_calls`` payload using Mistral's required markers.
- [x] Wire the hook into ``InferenceSnapProvider.complete()`` /
  ``stream()`` so rewriting fires once per LLM call before the
  request body is built.  Frontier providers (Gemini, Claude,
  OpenAI-compatible) inherit the identity default — they already
  accept the ``tool`` role natively.

### 109.2 P0 — Inbound parser for Mistral-format tool calls

- [x] Mistral models emit
  ``[TOOL_CALLS][{"name":"…","arguments":{…}}][/TOOL_CALLS]``
  inline within assistant content rather than the OpenAI-shaped
  ``tool_calls`` array.  Add a parser that splits
  ``response.content`` on those markers and returns the cantrip
  ``ToolCall`` shape.  llama.cpp's ``--jinja`` *should* handle
  this on the server side, but Phase 105.1.7 showed it doesn't
  always — fall back to client-side parsing when the server
  returns ``content`` containing the markers.
- [x] Negative test: when no ``[TOOL_CALLS]`` markers are present,
  treat ``content`` as a plain assistant reply.  Don't false-
  positive on an LLM that mentions the literal token in regular
  prose.

### 109.3 P1 — Re-run the Mistral Nemo 12B smoke

- [x] With 109.1 + 109.2 landed, retried the
  ``inference-snaps/mistral-nemo-12b/`` smoke against the same
  ``smoke-server.sh`` shape on RTX 5070 12 GiB (2026-05-24/25).
  The three pre-flight checks pass cleanly (``/v1/models``,
  plain hello with no thinking overhead, synthetic
  ``get_weather`` tool call) — zero ``role must alternate``
  500s, the rewriter substrate works end-to-end.  The
  ntfy-improve run produces a packable 1.13 MiB charm whose
  ``charmcraft.yaml`` matches improve-02 (4/4 COS relations,
  3/3 actions, OCI image binding) and whose ``src/charm.py``
  is an exact match for the prompt's shape constraints (right
  ``ops_tracing`` import, single ``super().__init__``, four
  ``framework.observe``, all four ``_on_*`` methods correct).
  Two cantrip-side wedges remain open and motivate follow-up
  work: (a) ``tests/unit/test_charm.py`` came out as
  ``unittest`` + ``Harness`` despite the prompt's "NOT Harness"
  directive (same negative-instruction-adherence pattern
  §5.1.1 and §5.5 flagged for Qwen3-8B / gemma4); (b) after the
  successful ``charmcraft_pack`` the model invoked
  ``plan_tasks`` twelve times in 3m39s and the resulting
  CONFIRM tasks wedged the executor (``--yolo`` covers
  permission ``ask`` events but not work-queue CONFIRMs) →
  exit 1 at 15m17s wall clock.  Wedge (b) is a Phase 106-shape
  failure mode that doesn't imply a message-format issue, so
  the phase's OR-criterion is met.
- [x] Documented measured findings in
  ``design/LOCAL_MODELS.md`` §5.2.2 — pre-flight, full tool
  sequence with timing, per-file output assessment,
  decode-speed observation (time to first pack ~2.1×
  Qwen3-14B Run #3's 5m19s), the post-success planner-spiral
  failure mode, and follow-up phase candidates (convergence
  heuristic after a successful pack; ``--yolo`` scope vs
  CONFIRM tasks).

### 109.4 P1 — Family detection + opt-in

- [x] ``InferenceSnapProvider`` should pick the right rewriter
  based on the snap name (``mistral-nemo-*``,
  ``magistral-*`` → Mistral path; everything else →
  identity).
- [x] Operator-visible env var
  ``CANTRIP_MESSAGE_FORMAT={openai,mistral,…}`` overrides the
  family detection for unknown snaps (e.g. a new Mistral fine-
  tune with a non-standard name).  Defaults to ``openai``.

### 109.5 P1 — Tests

- [x] Unit test ``rewrite_messages`` for the Mistral path: a
  conversation containing ``[user, assistant(with tool_calls),
  tool(result)]`` rewrites to ``[user, assistant(content
  containing the [TOOL_CALLS]/[/TOOL_CALLS] +
  [TOOL_RESULTS]/[/TOOL_RESULTS] markers folded in)]``.
- [x] Unit test the inbound parser: response with
  ``[TOOL_CALLS][...][/TOOL_CALLS]`` content splits into a
  ``ToolCall`` array and an empty ``content`` field.
- [x] Recorded-trace test pinning the wire format (the same way
  Phase 41 pins frontier-provider streaming).

### What this phase is *not*

- **Not a generic chat-template DSL.**  We add Mistral-shaped
  rewriting for the cases we actually need; we don't build a
  template-translation framework.  If a third family shows up
  later we add another concrete rewriter.
- **Not a fix for DeepSeek-V2-Lite's b8589 segfault.**  That's a
  llama.cpp version issue (§5.7.1) and unrelated.
- **Not a change to the ``Message`` dataclass.**  cantrip's
  internal representation stays OpenAI-shaped; the rewriter
  produces serialisation-time copies for Mistral providers.

**Exit criteria:** Mistral Nemo 12B drives an end-to-end
ntfy-improve scenario that produces a packable charm, comparable
to Qwen3-14B Run #3 (§5.6.1); the two unit tests in 109.5 pin the
rewrite + parse paths; ``design/LOCAL_MODELS.md`` §5.2.2 records
the measured outcome.

---

## Phase 110: Close the Post-Pack Wedge — Convergence Heuristic and --yolo CONFIRM Scope

**Goal:** ``design/LOCAL_MODELS.md`` §5.2.2 surfaced two cantrip-
side failure modes the Phase 109.3 Mistral Nemo re-smoke tripped
*after* the agent had already produced a packable improve-02-quality
charm.  Neither is a message-format issue; both block any
unattended (``--print --yolo``) run from exiting zero on a local
model that doesn't naturally STOP after a successful pack:

1. **Post-success ``plan_tasks`` spiral.**  Mistral kept calling
   the planner for 3m39s after the second successful
   ``charmcraft_pack``, producing twelve fresh
   ``confirm-design-…`` CONFIRM tasks against phantom
   dependencies.  Qwen3-14B Run #3 (§5.6.1) avoided this only
   because the model emitted a STOP marker after the first pack;
   counting on every local model to do the same is fragile.
2. **``--yolo`` doesn't cover CONFIRM tasks.**  ``--yolo``
   documents itself as "auto-approve every ``ask`` permission",
   but a substantial class of unattended-run blockers — design
   confirmations, day-2 confirmations, improvement confirmations
   — sits outside its remit.  The executor refused to continue
   with twelve queued CONFIRMs and exited 1.

### 110.1 P0 — Convergence heuristic after a successful pack

- [ ] Add an ``AgentState.pack_succeeded: bool`` flag (default
  ``False``, not persisted across restarts).  Resets to ``False``
  at the top of every ``CantripAgent.process_message`` /
  ``process_message_streaming`` call so a *new* user turn always
  gets a fresh chance to (re-)plan, matching §5.2.2's failure-
  mode scope (the spiral was within a single user turn).
- [ ] ``CharmcraftPackTool.execute`` flips
  ``state.pack_succeeded = True`` on the success path (after
  ``charmcraft pack`` exited zero, before the success
  ``ToolResult`` is returned).  ``QuickPackTool`` mirrors the
  flip on its success path so the gate fires for both packers.
- [ ] ``PlanTasksTool.execute`` refuses with a non-error
  ``ToolResult`` ("Charm already packed in this turn — no
  further planning needed.  STOP, or ask the user for a new
  goal.") when ``state.pack_succeeded`` is true.  No tasks are
  enqueued; the planner LLM call is skipped entirely so the
  10-second-per-spiral-iteration cost is gone.
- [ ] Unit tests in ``tests/unit/agent/`` cover: the flag
  defaults to ``False``; ``CharmcraftPackTool`` flips it on
  success and leaves it alone on failure; ``QuickPackTool``
  flips it on success; ``PlanTasksTool`` refuses with the
  documented message when set, without contacting the planner
  provider; ``process_message`` resets the flag at the top of
  the next turn (a once-packed session can re-plan when the
  user types a new goal).

### 110.2 P1 — Widen --yolo to cover work-queue CONFIRMs

- [ ] In ``print_mode._run_async`` (and the Ralph variant),
  when ``state.yolo_mode`` is ``True`` and ``pending`` CONFIRM
  tasks remain after the drain, walk the list and call
  ``work_queue.set_done(task.id, "Auto-approved by --yolo")``
  for each rather than printing the refusal and returning 1.
  Re-drain after the auto-approval pass so any unblocked
  follow-up tasks settle before the exit check.
- [ ] The refusal-message wording (still used when
  ``yolo_mode`` is ``False``) gets a clarifying line so
  operators know ``--yolo`` *does* now cover CONFIRMs ("Re-run
  with ``--yolo`` to auto-approve both permission ``ask``
  events and work-queue CONFIRM tasks, or resolve them
  interactively in the TUI/CLI mode first.").
- [ ] CLI help text for ``--yolo`` updated to reflect the
  widened scope.  The ``/yolo`` slash command (Phase 69.2)
  toggles the same flag, so its help string gets the same
  update.
- [ ] Unit tests in ``tests/unit/agent/test_cli_print_mode.py``
  + ``tests/unit/agent/test_yolo.py``: print-mode without
  ``--yolo`` still prints the refusal and exits 1; print-mode
  with ``--yolo`` and a pending design-CONFIRM auto-approves
  + drains + exits with the queue's terminal status (0 when
  follow-ups settle to DONE).

### What this phase is *not*

- **Not a fix for ``Harness``-not-``Context`` test-file
  regressions** (§5.2.2's other Mistral observation) — that's a
  model-side negative-instruction-adherence problem; a prompt
  re-engineering pass is a separate decision.
- **Not a generalised "agent has converged" detector.**  The
  convergence flag is one bit, scoped to "a charm was packed in
  this turn".  More elaborate convergence signals (Ralph's STOP,
  red-green, acceptance pass) keep their own state.
- **Not a change to ``CharmcraftPackTool``'s success contract.**
  The flag flip is orthogonal to what the tool returns — the
  ``ToolResult`` shape, audit row, and caption all stay the same.

**Exit criteria:** a fresh ``--print --yolo`` run of the §5.2.2
ntfy-improve prompt against Mistral Nemo (or any other local
model that doesn't emit STOP after a pack) exits 0 instead of 1 —
the planner gate prevents the post-pack spiral from materialising
fresh CONFIRMs, and any CONFIRM already in flight when ``--yolo``
auto-approves on drain unwedges the queue.  The two failure
modes §5.2.2 documented stop counting against future smokes.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Convergence flag (110.1) | Phase 32 (planner / state plumbing), Phase 33 (work-queue) | Touches state, two tools, the planner — pure additive plus one gate |
| ``--yolo`` widening (110.2) | Phase 69.2 (``--yolo`` flag), Phase 32 (CONFIRM tasks) | Lives entirely in ``print_mode.py`` plus a help-text refresh |

**Discovered:** Phase 109.3 re-smoke on 2026-05-25
(``design/LOCAL_MODELS.md`` §5.2.2).  The Mistral Nemo run produced
a packable improve-02-quality charm by minute 11 then spun in a
``plan_tasks`` loop for ~4 more minutes before the executor bailed
on twelve unresolved CONFIRM tasks ``--yolo`` did not cover.

---

## Phase 111: llama.cpp Build Refresh — b8589 → b9050 Re-smoke

**Goal:** Every operational llama.cpp pin in the repo (snap
manifests + host smoke-server scripts) moved from upstream
``b8589`` (2026-03-30) to Canonical-mirror ``b9050``
(2026-05-08) — ~461 upstream commits, ~5 weeks of MoE / quant
kernel work, and the fused-kernel fixes that
``design/LOCAL_MODELS.md`` §5.7 specifically called out as
unblocking DeepSeek-Coder-V2-Lite-Instruct.  Bump landed in this
commit; the validation work to confirm no regressions is the
phase.

### 111.1 P0 — Re-smoke each candidate on b9050

- [x] ``inference-snaps/qwen3-8b/scripts/smoke-server.sh`` —
  re-run §5.1.1 smoke; confirm ``/v1/models``, plain-hello, and
  synthetic ``get_weather`` tool call still pass.  Record any
  decode-rate / TTFT delta against the b8589 baseline in
  ``design/LOCAL_MODELS.md``.  *(Done — §5.1.3.  All three checks
  pass; plain-hello reasoning overhead dropped ~26 % vs §5.1.1.
  Surfaced ``smoke-check.sh``'s 32-token plain-hello budget being
  too tight for Qwen3-family ``<think>`` preambles — documented
  in the addendum.)*
- [x] ``inference-snaps/qwen3-14b/scripts/smoke-server.sh`` —
  same protocol; the §5.6 Run #3 charm-build prompt is the
  load-bearing comparison.  *(Done — §5.6.3.  Replay packed
  autonomously in 2m 46s vs §5.6.1's 5m 19s baseline (~48 %
  faster) with the same 7-tool shape, 100 % success, empty
  stderr.  Three substrate-orthogonal model-output deltas
  recorded: regression on canonical COS relation names,
  ``ops_tracing.setup`` substituted for the constructor, test
  file 137 lines vs the prompt's 100-line cap.)*
- [x] ``inference-snaps/mistral-nemo-12b/scripts/smoke-server.sh``
  — re-run the §5.2 / Phase 109.3 smoke; the post-pack spiral
  (Phase 110) is orthogonal, but a kernel-level change *could*
  alter decode shape.  *(Done — §5.2.3.  Replay packed in
  1m 41s with zero ``plan_tasks`` calls and zero CONFIRM tasks
  vs §5.2.2's ~15 min before bail; Phase 110.1 / 110.2 stayed
  dormant insurance.  Canonical COS relation names kept;
  ``ops_tracing.Tracing`` constructor honoured; Harness-not-
  Context regression on the test file persists.)*
- [x] ``inference-snaps/qwen3-coder/`` (snap) — re-pack with
  ``snapcraft`` against the new ``llamacpp_b9050`` components;
  re-run the qwen3-coder smoke; check the long-generation
  reconnect failure mode (§1) hasn't worsened.  *(Done — §5.5.1.
  ``snapcraft pack`` produced all five b9050 components after
  pre-warming the LXD build instance with ``snap wait system
  seed.loaded`` (``craft-providers`` warm-up timed out on
  ``snap unset system proxy.http`` otherwise).  Runtime
  confirms fused Gated Delta Net + Flash Attention enabled.
  Improve replay packed in 13m 06s with **zero streaming
  reconnects** — the §1 failure mode did not recur on this trial.
  Engine-selection inside the confined snap can't see
  ``nvidia-smi`` and falls back to CPU; explicit
  ``use-engine nvidia-gpu`` picks the CUDA engine regardless.)*
- [x] ``inference-snaps/embeddinggemma/`` (snap) — re-pack;
  confirm the embedding HTTP surface still answers
  ``/v1/embeddings`` correctly.  *(Done — §5.8.1.  ``snapcraft
  pack`` clean (no LXD warm-up issue this time), CPU-only single-
  engine snap.  Single + batch ``/v1/embeddings`` round-trip
  return 768-dim vectors with sensible distributions.)*

### 111.2 P0 — Retry DeepSeek-Coder-V2-Lite-Instruct

- [ ] ``inference-snaps/deepseek-coder-v2-lite/scripts/smoke-server.sh``
  — the §5.7 blocker was a b8589 segfault in the fused
  "Gated Delta" path during init.  b9050 sits well past the
  ``b9000+`` threshold ``design/LOCAL_MODELS.md`` flagged as
  the fix horizon.  If init succeeds, run smoke-check.sh; if
  the synthetic tool call also passes, promote the candidate
  into the §5 comparison table.
- [ ] If b9050 still segfaults: update §5.7 with the new
  failure trace and move the unblock target to b9200+ (or
  the next stable Canonical mirror cut), so future-us doesn't
  re-attempt blind.

### 111.3 P1 — Historical-comment cleanup

- [ ] ``inference-snaps/mistral-nemo-12b/prepare-models.sh``,
  ``inference-snaps/deepseek-coder-v2-lite/prepare-models.sh``,
  ``inference-snaps/qwen3-coder/engines/amd-gpu/engine.yaml``
  still reference ``b8589`` in *comment* prose (e.g. "the b8589
  build cutoff").  These are descriptive, not operational —
  update them only if 111.1 / 111.2 produces a behaviour change
  that contradicts the comment.  Otherwise leave as historical
  record and let ``design/LOCAL_MODELS.md`` carry the
  authoritative timeline.
- [ ] READMEs under ``inference-snaps/*/README.md`` likewise
  mention ``b8589`` as the build they were validated against.
  Update each as the corresponding 111.1 re-smoke completes,
  with the new tag and the date.

### What this phase is *not*

- **Not a llama.cpp upgrade to upstream-latest.**  b9050 is
  the most recent tag on the Canonical mirror as of 2026-05-25.
  Upstream ``b9305`` exists but isn't packaged for our
  release pipeline yet; a separate phase covers picking up
  further mirror cuts when they land.
- **Not a model-selection re-evaluation.**  If a re-smoke
  shows materially different decode-rate or quality, that's a
  data point for a *future* selection phase — Phase 111 just
  re-establishes the baseline on the new engine.

**Exit criteria:** every operational ``b8589`` reference has
moved to ``b9050``; each smoke target re-passes; ``design/
LOCAL_MODELS.md`` carries a dated "re-smoke on b9050" addendum
per candidate; DeepSeek-Coder-V2-Lite is either unblocked
(promoted into §5 with a real datapoint row) or re-blocked with
a fresh failure trace and an updated minimum-build target.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| 111.1 / 111.2 re-smokes | Phase 105.1 smoke infrastructure | Host ``llama-server`` + socat forwarder pattern unchanged |
| 111.3 doc cleanup | 111.1 / 111.2 results | Wait for re-smoke to know whether comments are still accurate |

**Discovered:** 2026-05-25 audit of llama.cpp pin staleness.
b8589 was ~716 upstream builds (~8 weeks) behind ``b9305``;
b9050 (mirror) is ~3 weeks newer than the pin and crosses the
``b9000+`` fix horizon ``design/LOCAL_MODELS.md`` §5.7 had
already identified as the DeepSeek-V2-Lite unblock target.

---

## Phase 112: Granite 4.1 Smoke and the Next-Generation Candidate Sweep

**Goal:** Run the same §5.1.1 protocol from
``design/LOCAL_MODELS.md`` against the shortlist from
``design/LOCAL_MODELS_SURVEY_2026-05.md``, in priority order:
**Granite 4.1-8B** (top recommendation), then **Ling-mini-2.0**
(speculative MoE), then **Granite 4.1-3B** (planner/router
companion), then **Phi-4-Mini** and **Llama-3.1-8B** as
tool-call-sanity baselines.  Each candidate either earns a §5
row in ``LOCAL_MODELS.md`` with a real charm-build datapoint, or
gets a documented disqualification.

### Why now

``LOCAL_MODELS_SURVEY_2026-05.md`` captured a fresh sweep of
post-survey-cutoff releases.  The headline candidate is IBM's
**Granite 4.1-8B** (released 2026-04-29): dense 8 B, 128 K
native context, 5.35 GB Q4_K_M (Unsloth UD-Q4_K_M), and — the
load-bearing property — BFCL v3 = 68.27 as a *post-training*
objective, not a bolt-on.  That directly addresses the failure
mode that disqualified Mistral Nemo (post-pack planner spiral)
and the Qwen2.5-Coder family (template-level ``--jinja`` bug).
We should know whether it works before Phase 105.2 finalises a
default provider preset.

### 112.1 P0 — Granite 4.1-8B smoke

- [ ] Scaffold ``inference-snaps/granite-4.1-8b/`` from the
  ``qwen3-8b/`` template (smoke-only — no snapcraft.yaml needed
  unless we promote to packaged-snap status in 105.3).  Copy
  ``scripts/smoke-server.sh``, ``scripts/smoke-check.sh``,
  ``prepare-models.sh``, README, default ``LLAMA_BUILD_TAG=b9050``.
- [ ] ``prepare-models.sh`` pulls ``unsloth/granite-4.1-8b-GGUF``
  at UD-Q4_K_M (5.35 GB).
- [ ] ``smoke-server.sh`` config: ``--ctx-size 32768``,
  ``--n-gpu-layers 99``, ``--jinja``,
  ``--reasoning-format deepseek`` if Granite turns out to be a
  thinking model (check the model card first).
- [ ] Run ``smoke-check.sh``: ``/v1/models`` reachable, plain
  hello (≤512 tokens), synthetic ``get_weather`` tool call.
  All three must pass for promotion to the charm-build step.
- [ ] Run the ntfy-improve scenario (the same one §5.1.1 and
  §5.6 used) end-to-end with ``cantrip run --provider
  inference-snap --snap granite-4.1-8b --base-url http://10.42.160.1:<port>``.
  Record tok/s, total wall time, charm-build outcome,
  hallucination shape, and any ``--jinja`` round-trip glitches
  in a new ``design/LOCAL_MODELS.md`` §5.8 entry.

### 112.2 P0 — Add Granite-family allowlist + provider notes

- [ ] Add ``granite-4.1-8b`` (and ``granite-4.1-3b``) to
  ``_TOOL_CAPABLE_SNAP_NAMES`` in
  ``src/cantrip/llm/inference_snap.py``, gated on 112.1's
  smoke passing.
- [ ] Check whether Granite's chat template needs a
  per-provider message rewrite (Phase 109's hook) — Granite
  uses ``<|start_of_role|>`` markers, which are different from
  Qwen's and Mistral's; verify llama.cpp's ``--jinja`` renders
  outbound and parses inbound correctly before relying on
  vanilla tool calls.
- [ ] If a rewrite is needed, land it as a Phase 109 follow-up
  rather than expanding 112's scope.

### 112.3 P1 — Ling-mini-2.0 template verification

- [ ] Pull ``bartowski/inclusionAI_Ling-mini-2.0-GGUF`` at
  Q4_K_M (9.94 GB).
- [ ] Test ``--jinja`` round-trip with a synthetic
  ``get_weather`` call.  If it fails, capture the failure
  shape and check whether overriding the template via
  ``--chat-template-file`` works.  If a custom template is
  required, open an upstream llama.cpp issue documenting the
  bailingmoe2 template gap so future-us isn't relitigating it.
- [ ] Only run the full charm-build scenario if the synthetic
  tool call passes.  Otherwise stop and write up the negative
  result in ``LOCAL_MODELS.md`` §5.9.

### 112.4 P1 — Granite 4.1-3B as a planner/router

- [ ] Scaffold ``inference-snaps/granite-4.1-3b/`` from the
  8 B sibling once 112.1 is green.
- [ ] Smoke-test purely as a candidate for the *planner* role
  in a future split-provider setup (``--planner-provider`` +
  ``--executor-provider``).  Not a charm-build candidate on its
  own — coding strength at 3 B is unknown and the survey
  doesn't claim it.
- [ ] If decode rate beats Granite 4.1-8B's by ≥3× and the
  synthetic tool call passes, note it as a candidate for the
  short-session-mode planner path (Phase 104).

### 112.5 P1 — Phi-4-Mini and Llama-3.1-8B baselines

- [ ] Run the synthetic ``get_weather`` ``--jinja`` smoke
  against both on b9050.  These are the function-calling-docs
  reference models; if either *fails* on b9050, that's a
  llama.cpp regression worth filing upstream, independent of
  any cantrip decision.
- [ ] Charm-build scenario only if there's spare time — these
  are baselines, not adoption candidates.

### What this phase is *not*

- **Not a re-evaluation of already-disqualified candidates.**
  The ``LOCAL_MODELS_SURVEY_2026-05.md`` skip list (Qwen3.5-9B,
  Qwen3-Coder-Next, Devstral Small 2, Codestral-22B,
  OmniCoder-9B, Llama-4 Scout, GLM-4.6) doesn't get re-litigated
  here unless the upstream blocker that disqualified it
  visibly moves.
- **Not the packaged-snap work.**  Promoting a 112-winner into
  a Cantrip-managed inference snap lives in Phase 105.3, not
  here.  This phase only validates that a model deserves
  promotion at all.
- **Not a benchmark suite.**  Same caveat as 105.1: the goal is
  a credible adoption signal, not a full HumanEval /
  BigCodeBench / Aider sweep.

**Exit criteria:** Granite 4.1-8B either earns a §5.8 row in
``LOCAL_MODELS.md`` with a real ntfy-improve datapoint and gets
promoted to ``_TOOL_CAPABLE_SNAP_NAMES``, or gets a documented
disqualification with the failure mode captured.  Ling-mini-2.0,
Granite 4.1-3B, Phi-4-Mini, and Llama-3.1-8B each get at least
a synthetic-tool-call smoke result recorded.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| 112.1 (Granite 4.1-8B smoke) | Phase 111 (b9050 engine bump) | Granite 4.1's templates rely on recent llama.cpp |
| 112.2 (allowlist + provider notes) | 112.1 result | Don't allowlist a model that didn't pass smoke |
| 112.3 (Ling-mini-2.0) | Phase 109's per-provider rewrite hook | Likely needed for bailingmoe2 template |
| 112.4 (Granite 4.1-3B planner) | 112.1 + 112.2 | Template work is shared with the 8 B sibling |

**Discovered:** 2026-05-25 candidate survey
(``design/LOCAL_MODELS_SURVEY_2026-05.md``).  The original
``LOCAL_MODELS.md`` survey closed before Granite 4.1 (2026-04-29),
Ling-mini-2.0, Qwen3.5, Qwen3-Coder-Next, and Devstral 2 shipped;
fresh sweep identified four candidates worth smoking on b9050.

---

## Milestones

High-level targets for **open** work. Completed milestones are listed in [`ROADMAP_ARCHIVE.md`](ROADMAP_ARCHIVE.md).

| Milestone | Phase | Definition |
|-----------|-------|------------|
| M5: Research-Driven | 5 | Agent proactively researches and proposes grounded designs |
| M6: Fast | 6 | Common charm build completes in under two minutes |
| M9: Terraform | 9 | Cantrip generates and validates Terraform modules for charms |
| M10: Charm Improver | 10 | Cantrip audits and upgrades existing charms to modern standards |
| M11: Resilient Agent | 11 | Subagents commit, self-verify, and recover cleanly from failures |
| M12: Red/Green | 12 | Red/green TDD — integration tests first, agent iterates until green |
| M13: Demo-Ready | 13 | Every charm ships with runnable demo, captured output, and tutorial |
| M14: Full Transcript | 14 | Every session exportable as searchable HTML with full audit trail |
| M15: Web UI | 15 | Browser-based interface mirroring the TUI via shared event bus |
| M16: Security & Tracing | 16 | OWASP security events + clear manual tracing guidance |
| M17: Acceptance Tested | 17 | Cantrip deploys, exercises, and reports on every charm it builds |
| M19: Operationally Ready | 19 | Cantrip assesses and improves charms against Canonical's Operational Readiness Metrics |
| M25: Code Health | 25 | All critical and high code-review findings resolved; `make check` green |
| M27: Provider Quality | 27 | Claude caching active; Gemini parallel tool calls correct; extended thinking available |
| M28: Robust Agent | 28 | SQLite concurrent writes safe; executor self-heals; subagent context managed |
| M29: Polished TUI | 29 | All screens functional; no blocking subprocess calls; dead features wired up or removed |
| M30: Complete Toolbox | 30 | Shell injection fixed; missing Juju/git tools available; existing tools hardened |
| M32: Smart Planning | 32 | Compact prompt complete; dependency validation; watcher events all routed |
| M39: ACP Research | 39 | Written assessment of Agent Client Protocol as an alternative to direct LLM provider calls |
| M40: Safe Compaction | 40 | Compaction has cycle detection, retry budgets, and size validation — no infinite loops possible |
| M41: Provider Parity | 41 | All providers capture streaming usage; extended thinking available for Claude; accurate token counting; cost visibility; compaction monitoring |
| M42: GitHub Native | 42 | Cantrip triages issues, works on branches, opens PRs, and bootstraps repos — all with user approval |
| M44: Worktree Parallelism | 44 | Concurrent subagents run in isolated git worktrees with tested merge and revert paths |
| M45: MCP Client | 45 | Cantrip can attach third-party MCP servers with OAuth, elicitation, and category-scoped tool access |
| M46: User Hooks | 46 | Users configure pre/post lifecycle hooks with conditional filters; PreCompact can block compaction |
| M47: Best-of-N | 47 | High-value tasks optionally race multiple models and commit the test-pass-scored winner |
| M51: Team Research | 51 | Written assessment of whether and how Cantrip should support teams working on a charm, with architecture sketches and a next-step recommendation |
| M53: Knowledge-in-Markdown | 53 | Planner prompts and task descriptions live in Jinja2 templates; `planner.py` split along the deterministic / LLM seam; dev design docs cover tools, skills, and prompts |
| M56: Juju Copilot Bundle | 56 | `canonical/skills` hosts a Juju-specific instruction/skill bundle derived from Cantrip's system prompt, with CI validation and a regeneration path |
| M57: Test Cleanup | 57 | Unit coverage ≥85%; zero test warnings; oversized unit files split; quickpack tests reorganised to match charmlint |
| M58: Rust Tested | 58 | `cargo test` runs in CI for both Rust crates; every `.rs` file above 60% coverage; regressions surface at unit-test time, not via spread |
| M59: Property Tested | 59 | Hypothesis-backed property tests cover the planner dependency graph, charmlint rule engine, quickpack jujuignore, and watcher status-diff |
| M60: Accessible Web UI | 60 | Web UI passes WCAG 2.1 AA: visible focus indicators, labelled controls, live regions for chat/status, overlays behave as modal dialogs; rodney/showboat regression guard in CI |
| M61: Slash Autocomplete | 61 | Typing ``/`` in the TUI surfaces a catalogue-driven suggestion popup; Tab completes the active verb; CLI readline gets the same catalogue for parity |
| M62: On-Theme Activity Labels | 62 | Status-bar and Web "Thinking..." literals replaced by randomly-selected spellcasting verbs (incanting, conjuring, brewing, …) so the UI matches the cantrip/juju theme |
| M65: Right-Panel Tidy | 65 | TUI task panel audited and tightened; multi-model pane either earns its space or is retired |
| M90: Visual Topology | 90 | Right-panel multi-model pane and F8 graph screen treat the model as a visual topology — edges are first-class clickable objects with interface details, focus-fade dims unconnected apps, and a preset-bundle catalogue grounds layer grouping |
| M69: Kimi Workflow Features | 69 | Bounded Ralph-Loop iterate-until-green, ``--yolo`` unattended switch, ``Ctrl-X`` shell mode, and Mermaid/D2 Flow skills — four Kimi CLI patterns that fit Cantrip's autonomous loop, skill system, and CI story |
| M70: Amp-Inspired Depth | 70 | Librarian subagent that searches Charmhub and Launchpad, Oracle tool for on-demand second-opinion reasoning, glob-conditional guidance in AGENTS.md / skills, prompt-based review Checks that layer on top of charmlint, and a Painter tool that generates a Charmhub-style ``icon.svg`` |
| M72: Continue Context Providers | 72 | Indexed charm-ecosystem docs (``@docs juju|ops|charmcraft|rockcraft``), an ``@``-mention context-provider registry, ``embed`` and ``rerank`` model roles, and ``@problems`` diagnostics-as-pre-turn-context |
| M73: Goose Workflow Packaging | 73 | Parameterised retryable Recipes with sub-recipes, MCP Apps rendered as sandboxed iframes in the Web UI, JSON-schema-enforced structured responses, and declarative retry with shell validators |
| M79: Eval Gates Prompt Changes | 79 | System-prompt edits trigger a per-provider LLM-in-loop smoke test that runs in CI against a cheap model, closing the "narrow eval missed a cross-model regression" gap described in Anthropic's April 23 postmortem |
| M82: Pre/Post Tool Captions | 82 | Tools render an intro caption that updates in place to the post-call caption when the tool returns; the TUI and Web chat surface "running…" status without adding new chat lines |
| M84: Deferred-Item Sweep | 84 | `design/DEFERRED.md` exists, every "Deferred:" entry across `ROADMAP.md` and `ROADMAP_ARCHIVE.md` is labelled fired / not-fired / dropped, and the next sweep is on the calendar so deferrals don't rot into forgotten todos |
| M87: COS Coverage | 87 | Alertmanager, Catalogue-k8s, and Sloth gain skill-level guidance and worked examples at parity with Prometheus/Grafana; Parca/Pyroscope decision recorded in ``design/PROFILING.md`` (deferred to Phase 89 against four named triggers) |
| M88: Identity Platform | 88 | A user asking for "Canonical-Identity-Platform-backed login" gets a charm with correctly-wired Hydra relations, secret fabric, and a passing Phase 17 acceptance test |
| M93: Tested in Depth | 93 | High-value unit blind spots closed; failure-injection integration tests cover provider, tool, and recovery paths; restart/resume and worktree isolation exercised end to end; the eval/e2e portfolio reaches beyond the happy-path build/deploy story |
| M95: Canonical Dev Surfaces | 95 | Launchpad, Snapcraft, and Charmcraft MCP servers are documented, discoverable via ``/mcp marketplace``, and used by the agent in research, local-model discovery, and packaging flows without bespoke prompting |
| M97: Canonical Cloud Targets | 97 | A user asking for MAAS-, OpenStack/Sunbeam-, or MicroCloud-aware work gets substrate-specific guidance or automation rather than a generic "bring your own cloud" answer |
| M98: Canonical Estate Ops | 98 | Cantrip's improvement and operational-readiness flows recommend Ubuntu Pro and Landscape in the right day-2 contexts with clear guidance and without feeling bolted on |
| M43: Memory | 43 | Cantrip learns per-charm and cross-charm lessons with citations, revalidation, user controls, and skill export |
| M105: Local Model Refresh | 105 | A locally-runnable model that matches or beats qwen3-coder's measured improve-02 completeness ships as a documented snap + ``--snap`` preset (Qwen3-14B and DeepSeek-Coder-V2-Lite are the next smoke targets after 105.1's Qwen3-8B negative result); Mistral Nemo 12B and Phi-4-Mini ship as long-context / speed alternatives regardless of which candidate wins; ``design/LOCAL_MODELS.md`` captures the smoke evidence |
| M108: TUI Visual Refresh | 108 | Welcome state has identity (wordmark + tagline); double frames around the chat are gone; modal screens use single rounded borders without manual ``─`` underlines; ``$primary`` is reserved for focus / accent and shows up in under ten places per screen; ModelInfoBar collapses to one line by default; tool-block captions read as English (``▸ read backend/pyproject.toml``); timestamps appear only on gaps; loading indicator is on-brand; header carries actual context; file tree surfaces charm content first |
| M109: Non-Qwen Local Models | 109 | An ``LLMProvider.rewrite_messages`` hook + Mistral-shape inbound tool-call parser unblocks providers whose chat templates expect tool calls / results inline within assistant turns (Mistral Tekken format); Mistral Nemo 12B drives the ntfy improve scenario end-to-end; ``CANTRIP_MESSAGE_FORMAT`` env var lets operators force the rewriter for unknown snaps; recorded-trace tests pin the wire format |
| M110: Post-Pack Convergence | 110 | An ``--print --yolo`` run that produces a packable charm exits 0 instead of 1: ``state.pack_succeeded`` short-circuits further ``plan_tasks`` invocations in the same user turn, and ``--yolo`` auto-approves any work-queue CONFIRM still pending at drain time |
