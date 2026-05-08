# Recipes

Recipes are parameterised, repeatable, optionally retryable workflows
that a charm team checks into the repo (or keeps in their personal
``~/.config/cantrip/recipes/`` directory) so a complex sequence of
agent steps can be invoked deterministically: ``/recipe charm-cos-add
charm_name=ntfy scrape_path=/metrics`` runs a Jinja-templated prompt
with declared parameters and gets the same wiring every time.

This document covers the recipe schema, where recipes live on disk,
the dispatch path through the slash command, and how recipes compose
with neighbouring features (skills, flows, structured output, retry).
The implementation lives in ``src/cantrip/agent/recipes.py``; the
slash dispatcher glue lives in ``src/cantrip/agent/commands/recipes.py``.

## When to reach for a recipe

Cantrip already ships several primitives for repeatable work:

- **Skills** (``src/cantrip/agent/skills/``) — knowledge bundles the
  agent reads when context demands it.  Authoring a skill writes
  *what the agent should know* about a topic.
- **Flow skills** (Phase 69.4) — visual decision diagrams the agent
  walks step by step.  Authoring a flow describes *which branch of a
  decision tree applies*.
- **Custom commands** (``.cantrip/commands/*.md``) — a single-shot
  prompt template with positional / file / shell expansions.
  Authoring a custom command captures *one frequently-used prompt*.
- **Recipes** (``.cantrip-recipes/*.yaml``) — typed parameters,
  Jinja-templated instructions, optional schema-validated output,
  optional shell-validator-driven retry.  Authoring a recipe captures
  *a parameterised execution* — "do this exact thing, with these
  inputs, until these checks pass".

A custom command becomes a recipe when the team starts:

- repeating the same ``$ARGUMENTS`` placeholder dance,
- needing typed parameters with defaults and validation,
- caring whether the final output matches a JSON shape, or
- wanting "rerun until ``make check`` is green".

Until then, the simpler custom command is the right home.  Recipes
are deliberately heavier — the YAML schema and the typed parameter
list are the cost of a reproducible execution surface.

## Discovery

Two roots, in precedence order (later wins on name collision):

| Path | Scope |
|------|-------|
| ``~/.config/cantrip/recipes/*.yaml`` | User-personal recipes |
| ``<charm>/.cantrip-recipes/*.yaml`` | Repo-shared recipes |

The repo path is a sibling of the SQLite session file at
``<charm>/.cantrip``.  Cantrip cannot use ``<charm>/.cantrip/recipes/``
because a single path can't be both a regular file and a directory —
Phase 51b documents the same collision for shared memory.

Both ``.yaml`` and ``.yml`` extensions are recognised.  Malformed
files log a warning and are skipped: a single bad recipe never
prevents the rest of the catalogue loading.  Filenames must match
``[a-z0-9][a-z0-9_-]*``; the lowercased stem becomes the recipe name
that ``/recipe <name>`` invokes.

## Schema

A recipe is a single YAML mapping at the file's top level.  Unknown
keys raise on load — typos surface immediately rather than silently
falling back to a default.

```yaml
version: 1
title: Add COS to a charm
description: Wire Prometheus, Grafana, and Loki integrations into an existing charm.

parameters:
  - name: charm_name
    type: string
    requirement: required
    description: Charm directory under cwd.
  - name: scrape_path
    type: string
    requirement: optional
    default: /metrics
  - name: tier
    type: select
    options: [free, pro, enterprise]
    default: pro

settings:                  # optional
  model: claude-opus-4-7   # recorded but not yet honoured at dispatch
  temperature: 0.4
  max_turns: 25

extensions:                # optional — recorded but enforcement deferred
  - mcp:charmhub
  - tool:juju_status

instructions: |
  Add COS observability to {{ charm_name }}.
  Tier: {{ tier }}; scrape: {{ scrape_path }}.
  …

response:                  # optional
  schema_name: check_result
  # OR:
  # json_schema: { type: object, properties: { … }, required: [ … ] }

retry:                     # optional
  max_retries: 2
  timeout_seconds: 600
  checks:
    - type: shell
      command: make check
  on_failure: git restore --source=HEAD .

sub_recipes:               # optional — recorded but orchestration deferred
  - name: charm-cos-add
    values: { charm_name: gateway, tier: pro }
    sequential_when_repeated: true
```

### Top-level keys

| Key | Type | Notes |
|-----|------|-------|
| ``version`` | string \| integer | Defaults to ``"1"``.  Unused today; reserved for schema migrations. |
| ``title`` | non-empty string | Catalogue label; rendered in ``/recipe`` and ``/help``. |
| ``description`` | non-empty string | One-paragraph rationale; shown in ``/recipe <name> --help``. |
| ``parameters`` | list of mappings | See *parameters* below. |
| ``instructions`` | non-empty string | Jinja2 template body. |
| ``settings`` | mapping (optional) | ``model`` / ``temperature`` / ``max_turns``. |
| ``extensions`` | list of strings (optional) | Required tool / MCP-server identifiers. |
| ``response`` | mapping (optional) | Schema-validated output (see *structured output*). |
| ``retry`` | mapping (optional) | Declarative retry block (Phase 73.4 schema). |
| ``sub_recipes`` | list of mappings (optional) | Composed recipes. |

### Parameters

Each parameter is a mapping:

| Field | Type | Notes |
|-------|------|-------|
| ``name`` | matches ``[a-z0-9][a-z0-9_-]*`` | Used both as the argv key (``key=value``) and as the Jinja scope name. |
| ``type`` | one of ``string``, ``number``, ``boolean``, ``date``, ``file``, ``select`` | See *type coercion* below. |
| ``requirement`` | one of ``required``, ``optional``, ``prompted`` | Defaults to ``required``. |
| ``default`` | type-specific scalar | Coerced at load time so dispatch doesn't re-parse. |
| ``description`` | string | Surfaced in ``/recipe <name> --help``. |
| ``options`` | non-empty list (only for ``select``) | The allowed values; the binder enforces membership. |

**Requirement semantics.**  ``required`` errors out when missing
without a default.  ``optional`` binds ``None`` when absent.
``prompted`` defers binding to a caller-supplied callback so an
interactive surface can ask the user; when no callback is wired,
``prompted`` is treated identically to ``required`` and raises a
clear "missing required parameter" error.

**Type coercion.**  YAML scalars and CLI-style ``key=value`` strings
both run through the same coercer:

- ``string`` — accepts strings or stringifies scalars.
- ``number`` — parses floats; rejects booleans (which are ``int``
  subclasses but not numbers in this context).
- ``boolean`` — accepts ``true``/``yes``/``1``/``on`` and the inverse
  set.  Anything else raises rather than silently coerce.
- ``date`` — ISO 8601 (``YYYY-MM-DD``); also accepts a YAML-native
  ``datetime.date`` literal.
- ``file`` — passes the path string through verbatim.  v1 does not
  validate existence here; the recipe's ``instructions`` template
  decides what to do with the path.
- ``select`` — must equal one of ``options``.  Strings and
  numbers compare via ``str()`` so YAML ``options: [1, 2, 3]`` and
  CLI ``size=2`` both bind.

### Instructions (Jinja2)

Instructions render through a sandboxed Jinja2 environment with
``StrictUndefined``:

- Bound parameters are exposed under their names.  ``{{ charm_name }}``,
  ``{{ tier }}``.
- ``{{ recipe_dir }}`` is the directory the recipe file lives in,
  useful for ``{% include %}``-style references in a follow-up
  landing.
- The sandbox blocks ``__class__`` / ``__bases__`` /
  ``__subclasses__`` and similar attribute paths that would let a
  template escape into module internals.
- String-typed parameter values are scrubbed of Jinja syntax
  characters (``{``, ``}``, ``%``) before reaching the renderer so a
  user-supplied value cannot smuggle ``{{ … }}`` into the rendered
  prompt.  Mirrors the same scrub
  ``cantrip.agent.prompts.system`` applies to untrusted inputs.

A missing parameter, a sandbox block, or a syntax error all surface
as :class:`RecipeError` with the recipe name prefixed so the
dispatcher can render a clear failure.

### Structured output (``response``)

When ``response`` is set, the recipe's final assistant text is
validated against a JSON Schema after ``process_message`` returns:

- ``response.schema_name`` looks up a Phase 73.3 built-in schema
  (``planner_briefing``, ``oracle_answer``, ``check_result``,
  ``acceptance_report``).
- ``response.json_schema`` carries an inline schema mapping.

Exactly one must be set.  Validation is *advisory* by default — the
text reply is always returned to the user, with a one-paragraph
"⚠ Response schema validation failed" note appended on mismatch.  To
make the recipe re-run until validation passes, declare a
``json_schema`` check inside ``retry``.

The dispatcher does not switch to ``complete_structured`` for
recipes today: a recipe that expects to call tools (most charm work)
needs the regular conversation loop.  Native provider enforcement
via ``response_schema`` is reserved for the no-tools case and is a
follow-up item.

### Retry (``retry``)

Recipes reuse the Phase 73.4 ``retry`` block verbatim — same
schema, same checks, same evaluation rules — so a recipe author who
already knows custom-command retry knows recipe retry.  Mechanics:

- ``max_retries`` (default 1) caps initial-plus-retry attempts at
  ``max_retries + 1``.
- ``timeout_seconds`` bounds wall time across all attempts.
- ``checks`` is a list of ``shell`` / ``file_exists`` /
  ``json_schema`` predicates; every check must pass for the
  recipe to converge.
- ``on_failure`` runs once at the end if the run exits without
  converging (best-effort, never raises).
- Shell checks gate through the Phase 68.2 permission policy, so a
  ``deny`` rule cannot be smuggled in via a recipe.

A recipe with both ``response`` and a ``json_schema`` check inside
``retry`` is the canonical pattern for *enforce* the output schema:
the retry block drives convergence and the response block surfaces
validation status.

### Settings (``settings``)

Recorded at load time so the schema is complete, but **not yet
honoured** at dispatch in v1:

- ``model`` — would swap the active provider for the recipe's
  duration.  Mid-session model swap is a follow-up landing.
- ``temperature`` — would override the conversation temperature.
- ``max_turns`` — would cap the conversation loop.

The dispatcher emits an explicit advisory note in the recipe's help
output so users know the field is recorded-but-not-applied.

### Extensions (``extensions``)

Recorded as a tuple of strings so the schema captures the intent:
``mcp:<server>`` declares an MCP server requirement;
``tool:<name>`` declares a built-in tool requirement.

Enforcement (refuse to invoke if a required server isn't connected)
is a follow-up landing.  Listing extensions today is forward-
compatible — when the dispatcher learns to enforce them, no recipe
rewrite is needed.

### Sub-recipes (``sub_recipes``)

Recorded so the schema is complete, but orchestration is deferred:

- Default semantics will be parallel via Phase 44 worktrees when
  the parent runs them in a loop, sequential when invoked once.
- ``sequential_when_repeated`` overrides the loop default.
- The dispatcher today ignores ``sub_recipes`` and runs only the
  parent's top-level instructions.  Help output flags this so
  authors don't expect cross-recipe composition before the
  follow-up landing.

## Dispatch flow

```
/recipe                       → catalogue listing
/recipe help                  → catalogue listing
/recipe <name> --help         → per-recipe parameter list
/recipe <name>                → bind() + render() + process_message()
/recipe <name> key=value …    → as above with bound parameters
```

The dispatcher returns a :class:`SlashResult` with the recipe-
execution coroutine in ``followup`` so the surface (TUI, Web, CLI)
can render a ``Running /recipe <name>…`` prelude immediately and
append the real result when the conversation loop returns.

## Testing

Unit-test coverage lives in
``tests/unit/agent/test_recipes.py`` (loader, binding, rendering)
and ``tests/unit/agent/commands/test_recipe_slash.py`` (catalogue,
help paths, invocation, schema validation, dispatcher integration).

## Deferred

Tracked under Phase 73.1 and follow-up landings:

- Sub-recipe orchestration (parallel via Phase 44 worktrees,
  sequential, cycle detection).
- ``settings.model`` / ``settings.temperature`` / ``settings.max_turns``
  applied at dispatch.
- ``extensions`` enforcement (refuse to invoke when an MCP server
  or tool is missing).
- Three built-in recipes (``charm-new``, ``charm-cos-add``,
  ``charm-reactive-to-ops``).
- Interactive prompt callback for ``requirement: prompted``
  parameters wired into the TUI / Web prompt manager.
- ``docs/src/howto-recipes.md`` user-facing how-to.
- Native provider enforcement via ``response_schema`` for recipes
  that don't call tools.
