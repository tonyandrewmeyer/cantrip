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

- [ ] Clone the repo and review all available skills
- [ ] Evaluate each skill for (a) use as a Claude Code plugin when developing
  Cantrip itself, and (b) incorporation into Cantrip's own skill system for
  charm generation
- [ ] Install as a Claude Code plugin if useful for development
- [ ] For skills relevant to charm building, either adopt directly or adapt
  into Cantrip's agentskills.io-format skills
- [ ] Document findings: what was adopted, what was rejected (and why)

**Exit criteria:** Review complete. Useful skills adopted or adapted.
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

- [ ] Enumerate the slices of Cantrip's system prompt and skills most
  valuable as standalone assets: `charmcraft.yaml` authoring,
  `src/charm.py` patterns, Scenario testing (not Harness), Jubilant
  integration tests (not pytest-operator), ops-tracing integration,
  COS integration, relation-data design, the 12-factor / custom /
  infrastructure path split
- [ ] Decide per-slice whether it ships as an `.instructions.md`
  (applies to files matching a glob) or a skill folder (triggers on
  an explicit user ask): instructions for style/lint-adjacent rules,
  skills for multi-step processes like "migrate Harness to Scenario"
- [ ] Draft a manifest file (`README.md` + index) listing the
  bundle's contents, compatibility matrix, and versioning policy

### 56.2 High — Extract and repackage from Cantrip's system prompt

- [ ] For each instruction asset, extract the relevant block from
  `src/cantrip/agent/prompts/system.md.j2` (plus the skills under
  `src/cantrip/agent/skills/`) and rewrite for the standalone
  audience.  The Cantrip prompt assumes the autonomous-loop
  context; the published assets are read by humans and other agents
- [ ] Add YAML frontmatter matching awesome-copilot's conventions
  (`description`, `applyTo`, etc.) so the assets drop cleanly into
  any existing Copilot / Claude Code setup
- [ ] Keep a one-way-mirror convention: Cantrip's system prompt is
  the source of truth; the published assets are derived.  Document
  how they stay in sync (ideally a `make` target that regenerates
  the published bundle from the Jinja2 sources)

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

- [ ] Recipe schema in ``.cantrip/recipes/*.yaml`` (repo) and
  ``~/.config/cantrip/recipes/*.yaml`` (user).  Top-level
  fields: ``version``, ``title``, ``description``,
  ``parameters`` (list), ``instructions`` (Jinja-templated
  prompt), ``settings`` (provider/model/temperature/
  max_turns, all optional — inherit session defaults),
  ``extensions`` (list of required MCP servers or Phase 30
  tool names), ``response`` (see 73.3), ``retry`` (see
  73.4), ``sub_recipes`` (list of nested invocations).
- [ ] Parameter types: ``string``, ``number``, ``boolean``,
  ``date``, ``file``, ``select`` (with ``options``).
  Requirement: ``required`` / ``optional`` / ``prompted``
  (interactive ask-at-invocation).  Defaults supported.
- [ ] Invocation surface: ``/recipe <name> [key=value …]``
  slash command.  Unknown required params trigger an
  interactive prompt (or fail with a clear list in print
  mode, Phase 67.3).  Sub-recipes invoke the same way from
  within a parent's template.
- [ ] Sub-recipes support ``sequential_when_repeated`` like
  Goose; default is parallel when the parent runs them in a
  loop, sequential when invoked once.  Uses Phase 44
  worktree dispatch for parallel sub-recipes.
- [ ] Template engine: reuse Cantrip's existing Jinja2
  integration (Phase 32 planner / Phase 53 prompt templates)
  with the same template-injection guard.  ``{{
  recipe_dir }}`` and the parent's scope available.
- [ ] Ship three charm-relevant built-in recipes:
  - ``charm-new`` — parameterised "create a new charm for
    workload X" wrapping the Phase 1 research→scaffold flow
  - ``charm-cos-add`` — adds COS observability to an
    existing charm
  - ``charm-reactive-to-ops`` — upgrades a reactive charm
    to ops (overlaps with Phase 69.4 Flow skill; they
    compose — the Flow diagram is the decision tree,
    the Recipe is the parameterised execution)
- [ ] Document in ``docs/docs/howto-recipes.html`` and
  ``design/RECIPES.md`` (new — recipe schema reference,
  authoring guide, worked examples).
- [ ] ``tests/unit/test_recipes.py`` — schema parse,
  parameter validation, template expansion (including
  escape sequences), sub-recipe invocation, interactive-
  prompt path, failure on missing required param.

### 73.2 Medium — MCP Apps: interactive HTML in the chat

- [ ] Adopt the MCP Apps extension spec
  (``modelcontextprotocol.io/extensions/apps/overview``) in
  Cantrip's MCP client (Phase 45).  When a tool result
  includes an ``ui`` block with ``mime: text/html``, route
  it to the UI layer as an app-render event.
- [ ] Web UI (Phase 15) renders the HTML in a sandboxed
  iframe with ``sandbox="allow-scripts allow-forms"`` (no
  ``allow-same-origin`` — must communicate only via
  ``postMessage``).  Size constraints, no parent-DOM
  access, no cookie/storage access — match the MCP Apps
  security model verbatim.
- [ ] ``postMessage`` bridge: the app can emit structured
  events (``{type: 'tool_call', name, arguments}``) that
  Cantrip routes back through the agent's tool pipeline
  (with the Phase 68.2 permission layer gating them
  normally).  App events are audited in the transcript.
- [ ] TUI fallback: an MCP-App tool result renders as a
  one-line summary (``[MCP App: <title>; open in web UI
  at <url>]``) plus the text-form of any fallback content
  the server provides.
- [ ] Document one worked example — a "pebble-layer
  editor" MCP server (out of tree, reference only) that
  takes a layer YAML, renders a form in the Web UI, and
  returns the edited YAML.  Belongs in
  ``docs/docs/explanation-mcp-apps.html``.
- [ ] ``tests/unit/test_mcp_apps.py`` — sandbox attrs
  correct, postMessage round-trip, permission gate
  applied to emitted tool calls, TUI fallback.

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
  to ``gold-<provider>``, then ``validate``.
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

## Phase 92: Review Follow-Ups — Deterministic Scan, Validation Hardening, and Docs Discoverability

**Goal:** A broad April 2026 project review turned up four clusters of
follow-up work that are individually small-to-medium but collectively
important: one deferred-but-user-visible product gap (the unfinished
deterministic repo scan for custom apps), a handful of correctness and
validation hardening fixes in ``charmlint`` / ``quickpack``, several
test-suite reliability gaps, and documentation / onboarding surfaces
that ship features without making them easy to discover.  The phase is
explicitly a **follow-up sweep**: close the sharp edges the review
identified rather than opening a new product line.

### 92.1 High — Finish the deterministic pre-scan for non-PaaS repos

- [x] Turn ``src/cantrip/agent/tools/_scan.py`` from the current
  documented stub into the real implementation sketched in
  ``design/TOOLS.md``: filesystem walk with ``EXCLUDE_DIRS`` pruning,
  manifest expansion, entry-point probing, CI/CD detection, container /
  security / lint-config / env-template detection, charm-marker
  detection, and recent-git-churn summary.
- [x] Wire ``AnalyseFrameworkTool.execute()`` to call the scan helper so
  custom-application routing stops re-deriving deterministic facts ad
  hoc.  Keep the existing user-facing return shape
  (``framework``, ``language``, ``profile``, ``workload_hints``,
  ``candidates``, ``notes``) and layer the scan output underneath it
  rather than widening every downstream caller.
- [x] Add focused unit tests for the scan passes under
  ``tests/unit/test_scan.py`` using tiny synthetic repo fixtures:
  manifests-only, CI-only, entry-point-only, existing-charm marker,
  mixed Docker/systemd hints, and a pathological excluded-directory
  case so the walk budget stays bounded.
- [x] Record whether the scan should also feed future UI surfaces
  (repo-stats sidebar, onboarding summary, print-mode preamble) so the
  helper becomes the single source of truth for "what kind of repo is
  this?" rather than a planner-only utility.

### 92.2 High — Validation hardening in ``charmlint`` and ``quickpack``

- [x] Replace the current ``charmlint`` category extraction
  (``rule_id.rstrip("0123456789")``) with an explicit parser so
  category-level ``select`` / ``ignore`` / severity overrides cannot
  mis-handle edge-case rule IDs.  Add regression tests for category
  matching rather than relying on naming convention alone.
- [x] Remove the lazy rule-registration bootstrap in
  ``src/charmlint/linter.py`` in favour of an explicit, import-at-module-
  top registration path that keeps the rule set deterministic and
  easier to reason about under tests and future concurrency.
- [x] Harden ``quickpack``'s generated dispatch script: fail fast on
  missing interpreters, tighten shell quoting / error handling, and
  surface launcher problems as clear pack-time failures instead of
  delayed deploy-time breakage.
- [x] Validate ``quickpack`` metadata inputs earlier: reject invalid or
  out-of-tree entrypoints, validate ``charmcraft.yaml`` fields that the
  pack path depends on, and add tests covering malformed metadata so the
  failures stay crisp.
- [x] Audit the remaining broad ``except Exception`` sites touched by
  the review and either narrow them or document the boundary in the
  established ``# noqa: BLE001 — <reason>`` style where the broad catch
  is intentional.

### 92.3 High — Test reliability, coverage, and evaluation depth

- [x] Replace the fixed sleeps in the executor and e2e harnesses with
  polling / signalling helpers.  ``tests/support/wait.py`` exposes a
  shared ``wait_until`` predicate poller plus ``wait_for_task_status``,
  ``wait_for_queue_state``, and ``wait_for_value`` helpers.  Migrated
  ``tests/unit/executor/test_run_loop.py``, ``test_budget.py``,
  ``test_rate_limit.py``, and ``tests/integration/test_work_loop.py``
  off the previous ``asyncio.sleep(0.05–0.2)`` / fixed 2 s waits.
  The integration ``wait_for_queue_state`` shim now re-exports from
  ``tests.support.wait`` so existing call sites keep importing from
  ``tests.integration.conftest``.  The remaining ``time.sleep(5/10)``
  calls in ``tests/e2e/harness.py`` are already inside polling loops
  (Jubilant ``juju status`` reads with deadline-bounded loops) — they
  set the polling cadence rather than acting as fixed timing
  assumptions, so they are not in the "structurally flaky" bucket.
- [x] Add a lightweight executor-test harness that waits on explicit
  queue / task state transitions rather than timing assumptions, then
  migrate ``tests/unit/executor/test_run_loop.py`` and similar files.
  Done as part of the shared wait helpers above; the executor unit
  tests now wait on task/queue state directly via
  ``wait_for_task_status`` and ``wait_for_queue_state``.
- [x] Enforce Python coverage in the main developer loop.  ``make unit``
  already collects coverage; add a ``fail_under`` threshold and wire it
  into ``make check`` so coverage regressions are visible before merge.
  ``[tool.coverage.report].fail_under = 88`` is set in ``pyproject.toml``
  (current baseline ~88.77%, leaves a 1pp margin for xdist noise);
  pytest-cov consumes the threshold during ``make unit``, which
  ``make check`` already invokes, so any drop below 88% fails the
  developer loop and CI.
- [ ] Expand the eval corpus beyond the current minimal set of gold
  charms: cover more substrates (machine + k8s), at least one custom /
  non-framework application path, and more relation / observability
  shapes so prompt or planner regressions are easier to detect.
- [ ] Add CI wiring for the eval work that is cheap enough to run
  regularly: keep the full provider-matrix ambition in Phase 79, but
  make the static gold-standard / rubric path and any cheap smoke path
  first-class rather than manual-only.
- [x] Reduce test-maintenance drag in the heaviest files and fixtures.
  - [x] Split the monolithic ``tests/unit/agent/test_agent.py`` into
    feature-scoped modules.  ~1.5 kloc went into eight new siblings —
    ``test_agent_core.py``, ``test_agent_models.py``,
    ``test_agent_cache.py``, ``test_agent_persistence.py``,
    ``test_agent_context.py``, ``test_agent_tooling.py``,
    ``test_agent_watcher.py``, and ``test_agent_improvement.py`` —
    matching the existing ``test_agent_<feature>.py`` convention used by
    ``test_agent_arena.py`` / ``test_agent_github.py`` /
    ``test_agent_lifecycle.py``.  The duplicated ``TestInferGapsFromAudit``
    class (a strict subset of the canonical copy in
    ``test_audit_gap_inference.py``) was dropped rather than re-housed.
  - [x] Centralise reusable fakes/builders so unit / integration / e2e
    layers stop growing parallel infrastructure by accident.  Five new
    modules under ``tests/support/``:  ``providers.py`` (``RecordingProvider``,
    ``CallbackProvider``, ``MultiRoleProvider`` — the latter two moved out
    of ``tests/integration/conftest.py``), ``tools.py`` (``make_stub_tool``,
    replacing five inline ``_StubTool`` / ``_make_tool`` definitions plus
    the integration-conftest variant), ``worktrees.py`` (a single
    ``FakeAllocator`` + ``AllocCall`` / ``ReleaseCall`` dataclasses,
    replacing three near-duplicate ``FakeAllocator`` / ``_FakeAllocator``
    classes across ``test_executor_worktree.py``, ``test_executor_race.py``,
    and ``test_race.py``), and ``roles.py`` (``StubEmbed`` / ``StubRerank``,
    replacing three inline ``_StubEmbed`` definitions).  Inline
    ``RecordingProvider`` subclasses in ``test_run.py``, ``test_day2.py``,
    and ``test_design.py`` (5 occurrences) collapsed onto the shared one.
  - [x] Document the fixture hierarchy.  ``tests/README.md`` lays out the
    unit / integration / e2e / eval rings, the conftest layering rules,
    and a catalogue of every shared fake plus the protocol it stands in
    for; ``CLAUDE.md`` carries a pointer to it from the test-suite section
    so future contributors find the catalogue before reaching for an
    inline ``_StubX``.
- [x] Add a small audit of exception-path coverage in high-value modules
  (provider adapters, executor loop, juju/log plumbing, structured
  output, persistence) and backfill the missing regression tests the
  review called out.  Audit drove from the annotated coverage report
  (``cov_annotate/``) and landed seventeen focused regression tests:
  ``ClaudeProvider.complete()`` rate-limit / 5xx / generic-API-error
  mappings (and the matching ``stream()`` paths), ``GeminiProvider``
  ``ServerError`` / generic ``APIError`` mappings on both ``complete()``
  and ``stream()``, ``BackgroundExecutor._on_permission_decided``
  swallowing ``TypeError`` and ``RuntimeError`` from a broken UI hook
  without crashing the loop, ``preview_session`` falling through to an
  empty preview when the ``.cantrip`` file is corrupt or
  ``peek_session`` raises, and ``capture_databag_snapshot`` degrading
  to an empty ``DatabagSnapshot()`` when the ``juju`` CLI is missing,
  hangs, or returns malformed JSON.  Total coverage moved 88.76 → 88.88%.

### 92.4 Medium — Docs and discoverability sweep

- [x] Fix command discoverability in ``docs/src/reference-cli.md``:
  add ``cantrip audit`` and ``cantrip permissions`` to the
  ``on_this_page`` list, make sure every implemented subcommand appears
  in the reference navigation, and add brief prose explaining when a
  user reaches for each command.
- [x] Rework the README opening so it distinguishes **end-user install**
  from **contributor checkout** immediately.  The current clone+``uv
  sync`` path is correct for development but obscures the simpler
  install flow for users who just want the tool.
- [x] Add docs for the two underexplained interface surfaces:
  **Web UI** and **CLI/REPL mode** (``--web`` and ``--no-tui``).  Cover
  when to use each surface, any feature-parity caveats, and the
  workflows that are easier there than in the TUI.
- [x] Expand ``howto-print-mode`` with concrete CI / automation
  examples, and surface print mode, permissions, and audit from the docs
  landing page instead of leaving them buried in the CLI reference.
- [x] Add a short "Start here" path to the docs landing page:
  install, choose TUI/Web/CLI, build a new charm vs improve an existing
  one, then link to the relevant how-tos.  The current card grid is rich
  but gives new users no ordering signal.
- [x] Consolidate environment-variable guidance so setup is not repeated
  piecemeal across README, tutorial, provider how-to, and CLI reference.
  ``howto-provider.md`` gained an ``{#env-vars}`` section that owns the
  setup walk-through (per-provider exports, persistence guidance, embed
  / rerank keys); ``reference-cli.md#env-vars`` keeps the comprehensive
  table and now leads with a one-paragraph cross-reference to the
  how-to; README and ``tutorial.md`` collapse the duplicated
  ``export GEMINI_API_KEY`` step into a single example with explicit
  links to the consolidated env-var page.
- [x] Sweep user-facing docs for stray internal phase-language
  references and remove them.  ``grep -rn "Phase [0-9]"`` against
  ``docs/src/`` and ``docs/docs/`` returned zero matches; remaining
  ``phase`` mentions are the four user-facing workflow phases
  (research / build / deploy / test) which CLAUDE.md explicitly keeps.
  Nothing to remove — bullet closed by audit.

### What this phase is *not*

- Not a new architecture initiative.  The point is to finish deferred
  or rough-edged pieces already implied by the current design.
- Not a wholesale test-suite rewrite.  The target is the high-value
  reliability and maintenance problems the review surfaced first.
- Not a docs-platform rewrite.  The existing Markdown → HTML pipeline
  stands; this phase improves content structure and discoverability
  inside it.

**Exit criteria:** the deterministic scan is implemented and used by
``analyse_framework``; the ``charmlint`` / ``quickpack`` fixes above
land with regression tests; the flaky fixed-sleep cases are gone from
the reviewed executor/e2e paths and coverage is enforced in ``make
check``; the docs surface ``audit``, ``permissions``, Web UI, CLI mode,
print mode, onboarding, and env-var setup clearly enough that a new
user can find them without prior project knowledge.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Deterministic pre-scan (92.1) | Phase 91 framework-detection port, design/TOOLS.md Phase 55.7 stub note | Finishes the deferred implementation rather than inventing a new surface |
| Validation hardening (92.2) | Existing ``charmlint`` / ``quickpack`` test suites | Mostly surgical correctness work |
| Test reliability (92.3) | Phase 79 eval work for provider-matrix follow-ons | Coverage / gold standards can land independently of full provider-in-loop eval |
| Docs sweep (92.4) | Existing docs build pipeline | Source edits under ``docs/src/`` + regenerated HTML |

**Discovered:** Project-wide review on 2026-04-30 covering code,
tests, docs, and UX surfaces.  The strongest themes were the unfinished
deterministic repo scan, a handful of correctness hardening fixes, flaky
test timing, thin eval/discoverability coverage, and user-facing
features that exist but are too hard to find.

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

- [ ] Add tests proving the sandbox/workspace/worktree boundaries hold under
  pressure: path traversal attempts, symlink escapes, out-of-tree writes,
  temporary-file leakage, and cleanup after cancellation/failure.
- [ ] Add integration coverage for worktree lifecycle and git isolation:
  branch creation, temporary worktree setup/teardown, dirty-tree handling,
  merge/reconcile paths, and failure cleanup.
- [ ] Add system tests around the policy/permission boundary so "plan mode",
  destructive-command gates, and category-scoped tool access are verified in
  real flows rather than only at unit granularity.
- [ ] Treat these as regression guards for Phase 49's sandbox promise, not as
  optional hardening.

### 93.5 Medium — Cover advanced controllers and automation workflows

- [ ] Add integration coverage for the controller surfaces that currently have
  little or no non-unit protection: ``MCPController``,
  ``ArenaController``, ``TriageController``, and the extracted
  ``ExecutorController`` / ``WatcherController`` seams where real message flow
  matters.
- [ ] Add non-unit tests for git automation workflows: ``git_branch`` branch
  tracking, PR/open-feedback loops, and ``auto_commit`` message/trailer logic
  in realistic repositories rather than fake objects only.
- [ ] Add end-to-end coverage for at least one **triage → confirm → build
  improvement** path so the improvement workflow is tested across handoff
  boundaries, not only as isolated controller pieces.
- [ ] Add provider-routing / failover tests so a primary-provider problem does
  not silently strand the work loop when a fallback is configured.

### 93.6 Medium — Broaden the higher-level test portfolio

- [ ] Expand the **eval corpus** beyond the current happy-path examples with
  at least one more machine-oriented charm, one more custom/non-framework app,
  and one case that stresses relations / observability / operational actions
  more heavily than the current set.
- [ ] Add more **stateful e2e** scenarios: interrupted deploy, failed verify
  followed by debug task creation, improvement flows on an existing charm, and
  "user says no" / override branches that materially change the plan.
- [ ] Build **differential / metamorphic** checks where Cantrip should preserve
  invariants across providers or surfaces: stable task-graph validity, export
  shape, permission enforcement, and transcript/event consistency.
- [ ] Extend accessibility regression coverage beyond the current Web-only
  smoke test where feasible, and at minimum document the deliberate boundary
  if TUI accessibility remains manual.
- [ ] Where a "fuzz" or property style makes more sense than examples
  (workspace paths, provider payload normalisation, queue/task invariants),
  prefer that style over adding another list of hand-authored cases.
- [ ] Add **targeted traditional fuzzing** alongside the Hypothesis suite
  where coverage-guided or byte-oriented exploration is higher leverage than
  property tests alone: start with ``cargo-fuzz`` harnesses for
  ``charmlint-rs`` / ``quickpack-rs``, then add a small set of Python parser /
  export entrypoints such as transcript fence/export rendering and raw
  HTML/search-result parsers.  Keep this as an advisory or nightly lane rather
  than a default per-PR requirement unless it proves cheap enough.

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

## Phase 94: Go Kubernetes Diagnostics Binary — Pod-Layer Insight for Charm Debugging

**Goal:** Implement the Kubernetes diagnostic gap identified in
[`design/K8S_TOOL.md`](design/K8S_TOOL.md) as a small, read-only **Go**
binary and wire it into Cantrip as a first-class typed tool.  The new
design document [`design/K8S_DIAGNOSTICS_BINARY.md`](design/K8S_DIAGNOSTICS_BINARY.md)
is the source of truth for scope, command shape, JSON contract, safety
boundary, and Python integration.

### 94.1 High — Ship the Go binary itself

- [ ] Add a new Go module under ``src/cantrip-kdiag/`` with a small,
  explicit package layout (`cmd/`, `internal/cli`, `internal/kube`,
  `internal/collect`, `internal/summarise`, `internal/output`) matching
  the design doc.
- [ ] Implement the three v1 commands from the design:
  ``summary``, ``pod``, and ``preflight``.
- [ ] Support kubeconfig/context loading, namespace selection, and
  bounded targeting by exact pod, Juju app, or Juju unit.
- [ ] Collect the initial read-only diagnostic set only: pods, container
  statuses, warning events, PVC state, previous log tails for crashed
  containers, and pod metrics when the metrics API is present.
- [ ] Emit deterministic JSON with an explicit schema version and crisp,
  documented exit codes for usage error, kubeconfig/context failure, API
  reachability failure, target-not-found, metrics unavailable, and
  internal error.

### 94.2 High — Integrate the binary into the Python tool layer

- [ ] Add a typed Python wrapper in ``src/cantrip/agent/tools/`` (likely
  ``k8s.py``) that invokes ``cantrip-kdiag`` via ``subprocess.run``,
  parses the JSON output, and returns a structured ``ToolResult`` with a
  concise caption plus the full report in ``data``.
- [ ] Register the new tool in ``build_tools()`` and scope its
  description/schema so the agent reaches for it only when Juju does not
  explain a pod-layer problem.
- [ ] Mirror the existing Juju-tool pattern for environment handling:
  bypass the subprocess sandbox, thread through ``KUBECONFIG`` /
  explicit context inputs, and fail clearly when the binary is missing.
- [ ] Decide whether v1 uses a single ``k8s_diagnostics`` tool with a
  mode parameter or a thin pair (summary vs pod drilldown); keep the
  external contract aligned with the Go commands rather than inventing a
  Python-only abstraction.

### 94.3 Medium — Teach the agent when to use it

- [ ] Update the Kubernetes diagnostic guidance so the agent prefers the
  typed tool over prescribing raw ``kubectl`` when the binary is
  available, while keeping the existing `fix-broken-juju-k8s` skill for
  substrate-rebuild flows and manual fallback.
- [ ] Add or update the relevant prompt/skill/tool guidance so the tool
  is used specifically for the documented gap cases:
  ``CrashLoopBackOff``, ``ImagePullBackOff``, ``OOMKilled``, PVC binding
  failures, and namespace-event clues that Juju does not surface.
- [ ] Keep the scope charm-focused and read-only; do not expose a raw
  generic Kubernetes command runner or write-path surface.

### 94.4 Medium — Validation, tests, and packaging hygiene

- [ ] Add Go tests for target resolution, warning synthesis, output
  shape, and the read-only collectors using fake clients where practical.
- [ ] Add Python unit tests for the wrapper tool covering happy path,
  missing binary, malformed JSON, non-zero exit codes, and missing
  kubeconfig/context.
- [ ] Decide the developer and CI build path for the binary (including
  where the built executable lives during tests) and document that path
  alongside the new subsystem rather than leaving it implicit.
- [ ] Add user/developer docs for the new tool surface only where the
  feature becomes externally visible; keep internal implementation notes
  in the design doc.

### What this phase is *not*

- Not a generic ``kubectl`` wrapper.
- Not a write path to the cluster (`apply`, `delete`, `patch`, `exec`,
  `port-forward`).
- Not a rewrite of other Cantrip native helpers in Go.
- Not a requirement to replace Juju-native debugging with Kubernetes
  debugging; the binary fills the specific gap where Juju's view stops.

**Exit criteria:** Cantrip can diagnose the common pod-layer failure modes
called out in ``design/K8S_TOOL.md`` through a first-class typed tool
powered by ``cantrip-kdiag``; the binary stays read-only and bounded; the
Python wrapper surfaces crisp structured output and failures; and tests
cover both the Go report contract and the Python integration.

**Dependencies:**
| Item | Depends On | Notes |
|------|-----------|-------|
| Go binary (94.1) | `design/K8S_DIAGNOSTICS_BINARY.md`; Kubernetes client-go ecosystem | Keep the initial command set small and the contract explicit |
| Python integration (94.2) | 94.1; existing `Tool` / `ToolResult` conventions in `design/TOOLS.md` | Mirror Juju-tool subprocess patterns rather than shelling out through `run_command` |
| Agent guidance (94.3) | 94.2; existing Kubernetes skill content | Prefer typed-tool guidance without deleting the manual fallback story |
| Validation/docs (94.4) | 94.1 + 94.2 | Tests should lock the JSON contract and error handling in place |

**Discovered:** Follow-up design work on 2026-04-30 after reviewing
Cantrip's current features, planned features, and native-helper pattern
(``quickpack-rs`` / ``charmlint-rs``).  Verdict: Kubernetes pod-layer
diagnostics is the highest-value feature that is distinctly well suited to
a Go binary.

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

- [ ] Ship documented marketplace / descriptor examples for
  **Launchpad**, **Snapcraft**, and **Charmcraft** MCP servers so a
  user can enable Canonical-native servers without reading design docs
  or inventing YAML from scratch.
- [ ] Decide the default exposure / safety story per server.  Search,
  info, and lint / analyse verbs should be read-only by default;
  publishing verbs (if exposed at all) require explicit allowlisting
  and the same confirmation posture as other destructive or external
  operations.
- [ ] Update the MCP docs so the Canonical servers are a first-class
  example alongside the generic Grafana / GitHub-style examples.

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

## Phase 96: Chiselled Rocks — Chisel-Aware Rockcraft Output

**Goal:** Cantrip already generates rocks for OCI-backed charms, but it
does not yet understand Canonical's chiselled-Ubuntu packaging story.
This phase teaches the agent when a workload is a good chiselled
candidate, how to generate that Rockcraft shape safely, and when to stay
with a fuller Ubuntu base for debugging or runtime reasons.

### 96.1 Eligibility rules

- [ ] Write the deterministic "is chiselled a good fit?" rubric:
  12-factor or otherwise simple container workloads, no shell-dependent
  runtime, no apt-at-runtime behaviour, package slices available, and a
  workable debug / support story.
- [ ] Record explicit blockers: workloads that expect a shell or
  ad-hoc OS utilities in production, opaque vendor install scripts,
  packages without the needed slices, or charm logic that would make the
  minimised filesystem shape too brittle.
- [ ] Decide whether the eligibility logic lives purely in skill /
  prompt guidance or deserves a small deterministic helper next to the
  existing Rockcraft tooling.

### 96.2 Generation and escape hatches

- [ ] Extend Rockcraft generation guidance so Cantrip can emit
  chiselled-rock examples when the workload passes the rubric, including
  a short explanation to the user about *why* the smaller base is safe
  here.
- [ ] Preserve a clear escape hatch back to ordinary Ubuntu bases when
  the workload needs shell tooling, the user prioritises operability
  over footprint, or the chiselled build fails for a slice-availability
  reason.
- [ ] Ensure the generated charm and rock wiring still compose cleanly
  with Pebble plans, health checks, and the existing 12-factor /
  custom-app flows.

### 96.3 Validation and user-facing docs

- [ ] Add tests / fixtures proving Cantrip's chiselled output still
  launches correctly and keeps the expected runtime files, entrypoints,
  and libraries.
- [ ] Update the relevant user-facing docs and examples so
  "Cantrip can build smaller, tighter rocks when appropriate" is a
  visible feature rather than an invisible prompt tweak.

### What this phase is *not*

- Not a blanket switch making every rock chiselled by default.
- Not a replacement for quickpack or charmcraft packaging paths.
- Not a packaging-minification contest detached from charm operability.

**Exit criteria:** for workloads that fit the rubric, Cantrip can
generate and explain a chiselled-Rockcraft path; for workloads that do
not, it cleanly falls back to the existing fuller-base path.

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

- [ ] Write the design note that decides the role of each surface:
  **MAAS** as machine inventory / provisioning, **OpenStack / Sunbeam**
  as a target cloud for infra charms and demos, and **MicroCloud** as a
  compact private-cloud / edge lab.
- [ ] Decide how these surfaces relate to **Concierge** rather than
  bypassing it ad hoc.  The outcome may be extra presets, extra profile
  data, or documented MCP / tool integration — but not a second,
  conflicting environment abstraction.

### 97.2 MAAS path

- [ ] Decide whether the first MAAS surface is a built-in tool family,
  an MCP-first story, or a hybrid.  Start with safe read / prepare
  flows: list machines, inspect availability, and acquire / release
  capacity with explicit confirmation on any destructive step.
- [ ] Teach machine-charm workflows when MAAS is a better fit than local
  LXD and how to say so in design proposals, test plans, and runbooks.

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

- [ ] Expand the operational-readiness guidance so the agent can ask
  whether a workload or deployment story should mention **Ubuntu Pro**
  (security maintenance, compliance posture, long-term patching) and/or
  **Landscape** (fleet management, patching, access management) when
  those are actually relevant.
- [ ] Keep the recommendations evidence-driven.  They should show up
  where the workload, substrate, or operator environment makes them a
  sensible Canonical recommendation — not as generic upsell text.

### 98.2 Improvement-mode outputs

- [ ] Add "Ubuntu Pro / Landscape opportunities" to the audit /
  improvement output alongside existing observability, backup, HA, and
  security findings when those Canonical products would materially
  improve the charm's production story.
- [ ] Provide consistent wording that distinguishes **recommended for a
  supported production estate** from **required for the charm to work**.

### 98.3 Detection and templates

- [ ] Where safe and cheap, detect hints that the operator already lives
  in a Pro / Landscape world (repo docs, deployment notes, packaging
  assumptions, estate-management references) and use that context in the
  generated runbooks.
- [ ] Add reusable templates or guidance snippets for charms that need
  production-hardening recommendations but no direct integration code.

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

- [ ] Add ``LLMProvider.rewrite_messages(messages: list[Message])
  -> list[Message]`` (or equivalent) — default identity, Mistral
  family overrides to fold consecutive ``tool``-role messages
  into the *prior* ``assistant`` message's ``content`` /
  ``tool_calls`` payload using Mistral's required markers.
- [ ] Wire the hook into ``InferenceSnapProvider.complete()`` /
  ``stream()`` so rewriting fires once per LLM call before the
  request body is built.  Frontier providers (Gemini, Claude,
  OpenAI-compatible) inherit the identity default — they already
  accept the ``tool`` role natively.

### 109.2 P0 — Inbound parser for Mistral-format tool calls

- [ ] Mistral models emit
  ``[TOOL_CALLS][{"name":"…","arguments":{…}}][/TOOL_CALLS]``
  inline within assistant content rather than the OpenAI-shaped
  ``tool_calls`` array.  Add a parser that splits
  ``response.content`` on those markers and returns the cantrip
  ``ToolCall`` shape.  llama.cpp's ``--jinja`` *should* handle
  this on the server side, but Phase 105.1.7 showed it doesn't
  always — fall back to client-side parsing when the server
  returns ``content`` containing the markers.
- [ ] Negative test: when no ``[TOOL_CALLS]`` markers are present,
  treat ``content`` as a plain assistant reply.  Don't false-
  positive on an LLM that mentions the literal token in regular
  prose.

### 109.3 P1 — Re-run the Mistral Nemo 12B smoke

- [ ] With 109.1 + 109.2 landed, retry the
  ``inference-snaps/mistral-nemo-12b/`` smoke (server scaffold
  already in place).  Pass criterion: produce ≥ 80 % of the
  improve-02 feature target in ≤ 30 min, OR exit cleanly with a
  Phase 102 / 103 / 106 / 107 failure mode that doesn't imply a
  message-format issue.
- [ ] Document measured findings in
  ``design/LOCAL_MODELS.md`` §5.2.2.

### 109.4 P1 — Family detection + opt-in

- [ ] ``InferenceSnapProvider`` should pick the right rewriter
  based on the snap name (``mistral-nemo-*``,
  ``magistral-*`` → Mistral path; everything else →
  identity).
- [ ] Operator-visible env var
  ``CANTRIP_MESSAGE_FORMAT={openai,mistral,…}`` overrides the
  family detection for unknown snaps (e.g. a new Mistral fine-
  tune with a non-standard name).  Defaults to ``openai``.

### 109.5 P1 — Tests

- [ ] Unit test ``rewrite_messages`` for the Mistral path: a
  conversation containing ``[user, assistant(with tool_calls),
  tool(result)]`` rewrites to ``[user, assistant(content
  containing the [TOOL_CALLS]/[/TOOL_CALLS] +
  [TOOL_RESULTS]/[/TOOL_RESULTS] markers folded in)]``.
- [ ] Unit test the inbound parser: response with
  ``[TOOL_CALLS][...][/TOOL_CALLS]`` content splits into a
  ``ToolCall`` array and an empty ``content`` field.
- [ ] Recorded-trace test pinning the wire format (the same way
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

## Phase 110: Phase-Aware Tool Curation — Replace the Static Core-Tools Keep-List

**Goal:** Replace ``CantripAgent._CORE_TOOL_NAMES`` (a fixed 11-name
``set``) with a *curator* that picks the right tool slice for the
agent's active workflow phase (research / build / debug / deploy
/ demo).  Inference-snap providers cap the LLM's tool array at
12 — the static keep-list silently drops load-bearing tools
(``quick_pack``, ``charmlint``, ``run_command``) when those tools
are exactly what the current phase needs, and keeps tools the
phase doesn't need (``analyse_framework``, ``web_fetch``) just
because they're "always useful in some scenario".

### Why now

Phase 105.1.5 dry runs surfaced two concrete losses from the
static list:

- ``quick_pack`` is dropped, so even when sprint mode's recipe
  explicitly says *"prefer ``quick_pack``"*, the model can only
  call ``charmcraft_pack`` (slower, no LXD-free path).
- ``charmlint`` is dropped, so when ``charmcraft_pack`` fails
  with a YAML structure error, the model has no way to *see*
  what's wrong — the demo dry run oscillated between two
  near-identical broken YAMLs for 5 minutes because the
  feedback loop was pack-fail / guess / pack-fail.

Meanwhile ``analyse_framework`` (only useful when scaffolding a
fresh charm from a host directory) and ``web_fetch`` (a context
trap — bit the same demo dry run with a 41 KB payload that blew
the 16 K context budget) are kept by default.

A surgical short-term swap landed alongside this phase
(``analyse_framework`` + ``web_fetch`` out, ``quick_pack`` +
``charmlint`` in, same 11 names).  That helps the demo but
doesn't solve the underlying problem: the keep-list isn't aware
of *what the agent is doing right now*.

This isn't a duplicate of Phase 104.5 (shipped) — that sub-phase
added a phase-scoped tool set (``CantripAgent._SHORT_SESSION_PHASE_TOOLS``,
keyed on the active queue task's category) that fires *only* in
short-session mode (provider context window < 16 K).  Phase 110
generalises the same idea to *all* inference-snap providers
(Qwen3-14B at 16 K is also tight on context budget), promotes the
ad-hoc dict into a proper ``WorkflowPhase`` enum + curator, and
replaces the static ``_CORE_TOOL_NAMES`` fallback — building on
104.5's table rather than re-doing it.

### 110.1 P0 — Phase enum + tool-set table

- [x] Define a small enum ``WorkflowPhase`` with values
  ``research`` / ``build`` / ``debug`` / ``deploy`` / ``demo``.
  Map the existing planner task categories
  (``BUILD`` / ``RESEARCH`` / ``DEPLOY`` / ``TEST`` /
  ``DEBUG`` / ``INFRA`` / ``CONFIRM`` / ``LIBRARIAN``) onto this
  enum.  *(Done — ``WorkflowPhase`` + ``WorkflowPhase.from_category``
  in ``cantrip/agent/queue.py``; ``TEST → debug``, ``INFRA → deploy``,
  ``CONFIRM → build``, ``LIBRARIAN → research``.  ``DAY2`` isn't a
  real category — the actual eight are mapped instead.)*
- [x] In ``cantrip/agent/core.py``, replace
  ``_CORE_TOOL_NAMES: set[str]`` with
  ``_CORE_TOOLS_BY_PHASE: dict[WorkflowPhase, set[str]]``.
  Each phase's set lives at ≤ 11 names so the inference-snap
  cap can fit one MCP tool / extension if any are loaded.
  Tables shipped (the suggested ones, verbatim):
  - **build**: ``read_file write_file edit_file list_directory
    charmcraft_init quick_pack charmcraft_pack charmlint
    plan_tasks run_charm_tests run_command``
  - **debug**: ``read_file edit_file list_directory juju
    charmlint juju_debug_log juju_status_render run_command
    plan_tasks run_charm_tests web_fetch``
  - **deploy**: ``juju concierge_prepare juju_status_render
    juju_debug_log wait_for relation_smoke_test charmcraft_pack
    run_command list_directory plan_tasks``
  - **research**: ``read_file list_directory web_fetch
    web_search analyse_framework code_definition
    code_references oracle_consult plan_tasks
    extract_design_decisions``
  - **demo**: build, with ``charmlint`` swapped out for
    ``manage_tasks``.
  *(``_SHORT_SESSION_PHASE_TOOLS`` from Phase 104.5 folded into this
  one table.)*

### 110.2 P0 — Hook the curator into ``_tools_for_llm``

- [x] When the work queue's active task has a category, map it
  to a phase and use that phase's tool set.  Otherwise (no
  active task — the conversation is at idle) default to
  ``WorkflowPhase.build`` so the first interaction picks
  build-shaped tools.  *(Done — ``CantripAgent.workflow_phase``
  property + ``_curated_tool_names``; ``_tools_for_llm`` curates
  whenever short-session mode is on **or** the provider's
  ``max_tools`` cap is overshot, and serves the full toolset
  otherwise.)*
- [x] Re-fire ``invalidate_tools_cache`` ... when the active task
  transitions.  *(Moot — ``_tools_for_llm`` is recomputed from live
  work-queue state at the top of every turn, so a transition is
  picked up on the next LLM call with no cache to bust.)*

### 110.3 P1 — Operator override

- [x] Env var ``CANTRIP_TOOL_PHASE={research|build|debug|
  deploy|demo}`` forces a phase regardless of work-queue state.
  Useful for operators driving cantrip in unusual flows (e.g. a
  documentation pass through the codebase that needs
  research-tier tools throughout).  *(Done — read in
  ``CantripAgent.workflow_phase``; unrecognised values log a warning
  and are ignored.  Documented in ``docs/src/reference-cli.md``.)*
- [x] Surface the active phase + its tool count in the TUI
  status bar / Web UI badge so operators can see what's been
  curated for the current turn.  *(Done — ``CantripAgent.tool_phase_badge()``
  returns ``"build · 11"``-style text when curation is active and
  ``""`` otherwise; TUI ``StatusBar.tool_phase`` chip (primed on
  mount, refreshed on every task-update event), Web ``#tool-phase-badge``
  header chip primed from ``/api/state``, and a ``/cost`` line that
  names the phase.  Live Web push on task transitions is left for a
  follow-up — the badge refreshes on page load / reconnect.)*

### 110.4 P1 — Tests

- [x] Unit test: ``_tools_for_llm()`` with a build-category
  active task returns the build set.
- [x] Unit test: ``CANTRIP_TOOL_PHASE=research`` overrides the
  active-task category.
- [x] Unit test: when an active-task category transitions
  (e.g. build → debug because a test failed), the next call to
  ``_tools_for_llm()`` picks the new phase's set.
- [x] ~~Recorded-trace test~~ — covered by the direct
  ``_tools_for_llm`` / ``workflow_phase`` assertions across phases
  in ``tests/unit/agent/test_tool_curation.py`` (24 cases) plus the
  table-invariant tests (every phase has a ≤ 11-name table; build
  carries ``charmlint`` + ``quick_pack``); a recorded LLM trace
  would add wire-format coverage but no behavioural coverage the
  unit tests don't already give.

### What this phase is *not*

- **Not a generic plug-in framework for tool curation.**  We
  ship five hand-curated phases; we don't build a registry that
  third-party packages plug new phases into.
- **Not a change to ``InferenceSnapProvider.max_tools``.**  The
  12-tool cap stays.  This phase is about picking the *right*
  ≤12 tools, not lifting the cap.
- **Not a tool-routing / sub-agent feature.**  The autonomous
  loop still has access to all phases over time as the work-
  queue task category shifts.  This phase is just the per-turn
  filter.

**Exit criteria:** ``_CORE_TOOL_NAMES`` is gone; the build /
debug / deploy / research / demo phases are defined and tested;
the demo dry run that oscillated on YAML errors no longer does
because ``charmlint`` is in the build set; ``CANTRIP_TOOL_PHASE``
override works; ``/cost`` (or equivalent) shows the active phase.

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
| M92: Skill-derived Lint Rules | 92 | Six deterministic helpers — action-handler coverage, config-option coverage, charm-library semver, relation-data missing-guards, Pebble layer validation, harness-call inventory plus scenario-test event-shape coverage — ship as charmlint rule modules or standalone Cantrip tools, derived from existing skill bodies; affected skills shed their rule-recitation passages |
| M93: Tested in Depth | 93 | High-value unit blind spots closed; failure-injection integration tests cover provider, tool, and recovery paths; restart/resume and worktree isolation exercised end to end; the eval/e2e portfolio reaches beyond the happy-path build/deploy story |
| M94: K8s Diagnostics Binary | 94 | A read-only ``cantrip-kdiag`` Go binary powers a first-class typed tool that diagnoses the common pod-layer failure modes, with tests locking the JSON report contract and the Python integration |
| M95: Canonical Dev Surfaces | 95 | Launchpad, Snapcraft, and Charmcraft MCP servers are documented, discoverable via ``/mcp marketplace``, and used by the agent in research, local-model discovery, and packaging flows without bespoke prompting |
| M96: Chiselled Rocks | 96 | Cantrip recognises when a workload suits a chiselled-Ubuntu rock, generates and explains that path, and cleanly falls back to the fuller-base path when it does not |
| M97: Canonical Cloud Targets | 97 | A user asking for MAAS-, OpenStack/Sunbeam-, or MicroCloud-aware work gets substrate-specific guidance or automation rather than a generic "bring your own cloud" answer |
| M98: Canonical Estate Ops | 98 | Cantrip's improvement and operational-readiness flows recommend Ubuntu Pro and Landscape in the right day-2 contexts with clear guidance and without feeling bolted on |
| M43: Memory | 43 | Cantrip learns per-charm and cross-charm lessons with citations, revalidation, user controls, and skill export |
| M105: Local Model Refresh | 105 | A locally-runnable model that matches or beats qwen3-coder's measured improve-02 completeness ships as a documented snap + ``--snap`` preset (Qwen3-14B and DeepSeek-Coder-V2-Lite are the next smoke targets after 105.1's Qwen3-8B negative result); Mistral Nemo 12B and Phi-4-Mini ship as long-context / speed alternatives regardless of which candidate wins; ``design/LOCAL_MODELS.md`` captures the smoke evidence |
| M108: TUI Visual Refresh | 108 | Welcome state has identity (wordmark + tagline); double frames around the chat are gone; modal screens use single rounded borders without manual ``─`` underlines; ``$primary`` is reserved for focus / accent and shows up in under ten places per screen; ModelInfoBar collapses to one line by default; tool-block captions read as English (``▸ read backend/pyproject.toml``); timestamps appear only on gaps; loading indicator is on-brand; header carries actual context; file tree surfaces charm content first |
| M109: Non-Qwen Local Models | 109 | An ``LLMProvider.rewrite_messages`` hook + Mistral-shape inbound tool-call parser unblocks providers whose chat templates expect tool calls / results inline within assistant turns (Mistral Tekken format); Mistral Nemo 12B drives the ntfy improve scenario end-to-end; ``CANTRIP_MESSAGE_FORMAT`` env var lets operators force the rewriter for unknown snaps; recorded-trace tests pin the wire format |
| M110: Phase-Aware Tool Curation | 110 | The static ``_CORE_TOOL_NAMES`` keep-list is replaced by a curator that picks the right tool slice for the active workflow phase (build / debug / deploy / research); inference-snap providers no longer need to drop ``quick_pack`` / ``charmlint`` / ``run_command`` to fit the 12-tool budget when they're load-bearing for the current phase; an env-var override lets operators pin a custom set; tests pin each phase's expected tool list |
