# Standalone charm LSP — plan

> A design plan for a **separate, standalone tool** that reuses the
> deterministic knowledge already developed in Cantrip to improve
> non-agentic coding inside an IDE.  This is **not** a plan to embed an
> LSP inside Cantrip itself.

## TL;DR

- **Yes, a standalone LSP is worth building**, but the right first
  product is a **small charm-focused language server**, not "Cantrip in
  server mode".
- The best reusable Cantrip components are **`charmlint`**,
  **diagnostics normalisation** (`ruff` + `ty` + `charmlint` into one
  typed shape), **repo-map** for symbol/workspace features, and
  optionally **docs-search** for a retrieval-backed hover/command
  surface.
- The first release should focus on **deterministic editor help**:
  diagnostics, workspace symbols, charm-aware file intelligence, and a
  few code actions.  **Do not** start with chat, planning, background
  agents, or prompt orchestration.
- The cleanest product shape is a **new repository** with a thin LSP
  adapter layer and a handful of shared modules copied or spun out from
  Cantrip as needed.
- Suggested working name: **`charmls`**.

## 1. Problem statement

Cantrip already contains a substantial amount of **structured,
deterministic charm expertise**:

- `charmlint` knows common charm mistakes and emits machine-readable
  diagnostics.
- The post-edit and project-wide diagnostics code already normalises
  findings from `ruff`, `ty`, and `charmlint` into one common shape.
- Repo-map already parses Python and charm metadata and ranks files and
  symbols.
- Docs search already provides retrieval over Canonical charm-ecosystem
  documentation.

Today those capabilities are used to brief an **agent**.  The gap is a
different audience and workflow: a developer working in Zed, VS Code,
Neovim, JetBrains, or another editor who wants **IDE feedback without
invoking an autonomous agent**.

The question is therefore not "should Cantrip grow an LSP surface
internally?" but:

> Can the deterministic knowledge Cantrip already has become a
> standalone language server that improves everyday charm authoring in an
> editor?

The answer is **yes**, with scope discipline.

## 2. Product thesis

Build a **separate charm language server** whose job is to provide:

1. **Fast diagnostics** for charm projects.
2. **Charm-aware navigation and symbols**.
3. **A small number of deterministic quick fixes / actions**.
4. **Optional documentation lookup** tied to Canonical sources.

This is deliberately narrower than Cantrip:

- No autonomous task execution.
- No planner.
- No background subagents.
- No prompt assembly or multi-model orchestration.
- No attempt to expose the entire Cantrip tool system over LSP.

The LSP should feel closer to **Pyright + Ruff + YAML schema support for
charm projects** than to an editor-hosted coding agent.

## 3. Why a standalone tool instead of extending Cantrip

Three reasons:

### 3.1 Different runtime model

LSP servers are **incremental, always-on, editor-driven** processes.
Cantrip is an **agent runtime** organised around prompt turns, tool
invocations, permissions, and subagents.  Reusing the deterministic
engines makes sense; reusing the agent loop does not.

### 3.2 Different UX contract

An IDE wants:

- `publishDiagnostics`
- `workspace/symbol`
- hover/completion/code-action responses
- low latency under frequent file edits

Cantrip's context providers, prompt checks, and tool briefings are
optimised for LLM consumption, not for editor protocol responses.

### 3.3 Product-boundary clarity

Cantrip's roadmap explicitly treats IDE/LSP work as **out of scope until
Cantrip itself has an IDE surface**.  A separate tool avoids conflating
"Cantrip the agent" with "editor assistance built from Cantrip's
deterministic subsystems".

## 4. Reusable building blocks from Cantrip

### 4.1 `charmlint` — highest-value starting point

`charmlint` is the strongest candidate for reuse because it already has
most of the properties an LSP diagnostics engine needs:

- deterministic rules
- structured diagnostics
- rule IDs
- severity levels
- file/line attribution
- fix hints on some diagnostics
- a fast Rust backend

### Natural LSP mapping

| `charmlint` data | LSP surface |
|---|---|
| `rule_id` | `Diagnostic.code` |
| `severity` | `Diagnostic.severity` |
| `message` | `Diagnostic.message` |
| `path`, `line` | `Diagnostic.range` + URI |
| `fix_hint` | `CodeAction` / `Diagnostic.data` |

### MVP use

- Run on save, on open, and on relevant file changes.
- Publish charm-specific diagnostics for:
  - `charmcraft.yaml`
  - `metadata.yaml`
  - `actions.yaml`
  - `config.yaml`
  - related Python/test files where rules point there

### Important constraint

The current Rust backend is a **CLI**, not a stable library API.
Version 1 of `charmls` should therefore shell out to the binary or the
Python library rather than depending on an unstable internal Rust crate
boundary.

### 4.2 Unified diagnostics shape — nearly ready-made

Cantrip's post-edit/project diagnostics code already normalises
`ruff`, `ty`, and `charmlint` into one `FileDiagnostic` structure with:

- tool
- file
- severity
- code
- message
- line
- column

That shape is almost exactly what the LSP server needs internally before
converting to protocol diagnostics.  This should be reused directly or
ported with minimal changes.

### Immediate payoff

The standalone server can publish:

- Python style/lint findings (`ruff`)
- Python type findings (`ty`)
- charm-specific findings (`charmlint`)

as **one coherent diagnostic stream** instead of three disconnected
tools.

### 4.3 Repo-map — strong secondary feature

Repo-map is useful, but not for the first release's core value
proposition.  It becomes interesting for:

- `workspace/symbol`
- `documentSymbol`
- charm-aware "important files" views
- navigation aids for metadata-defined entities:
  - actions
  - config options
  - relations
  - resources
  - storage

The existing parser already understands both Python and charm metadata,
which makes it a good basis for **charm-aware symbol indexing**.

### Constraint

Repo-map today is optimised for **prompt rendering** and ranking, not
for full LSP symbol/query semantics.  Reuse the parsing/indexing core;
do not reuse the prompt-rendering layer.

### 4.4 Docs search — optional, not day one

Docs search is promising for editor UX, but it is not a core LSP need.
The best shapes are:

- a command like "Search charm docs"
- hover enrichment for known charm concepts
- "open canonical docs" links

This should be a **phase 2+** feature because it adds:

- embedding provider configuration
- local index lifecycle
- ranking/UX questions

before the server has even proven its basic diagnostics value.

### 4.5 What should not be reused

Do **not** carry over the following as part of the initial standalone
tool:

- prompt templates
- planner/subagent machinery
- agent tool registration model
- permission/confirmation flows
- context-provider `@mention` expansion
- chat-oriented output formatting

Those are Cantrip-agent concerns, not language-server concerns.

## 5. Proposed product shape

Create a new repository, tentatively:

`github.com/<owner>/charmls`

with a structure along these lines:

```text
charmls/
  pyproject.toml
  src/charmls/
    server.py
    lsp_types.py              # thin wrappers/helpers if needed
    workspace.py
    diagnostics/
      model.py
      runner.py
      charmlint_backend.py
      ruff_backend.py
      ty_backend.py
      convert.py
    symbols/
      index.py
      python_parser.py
      charm_metadata_parser.py
    actions/
      quickfixes.py
    docs/
      search.py               # optional later
    settings.py
  tests/
```

### Language choice

**Python first** is the right default:

- maximises direct reuse from Cantrip
- keeps iteration cheap
- matches existing parsing and diagnostics code
- is sufficient for an LSP whose heavy charm lint is already available
  via a Rust binary

A Rust rewrite can be reconsidered later only if the Python server
itself proves too slow.

## 6. MVP scope

The MVP should be intentionally small and obviously useful.

### 6.1 Must ship

1. **Workspace detection**
   - recognise a charm project from `charmcraft.yaml` and/or
     `metadata.yaml`
   - determine project root cleanly

2. **Diagnostics**
   - run `charmlint`
   - run `ruff`
   - run `ty`
   - merge all findings
   - publish them with stable source labels and codes

3. **Basic symbol support**
   - `workspace/symbol`
   - `documentSymbol` for Python and charm metadata concepts

4. **A small code-action set**
   - safe, deterministic fixes only
   - start with actions driven by explicit `fix_hint` or obviously
     mechanical edits

5. **Configuration**
   - enable/disable each backend
   - on-save vs debounced-on-change behaviour
   - severity thresholds
   - charmlint select/ignore passthrough

### 6.2 Must not ship in MVP

- AI chat
- LLM completions
- inline agent execution
- deployment/model control
- remote cluster inspection
- whole-docs retrieval UI
- speculative auto-fix of complex charm architecture issues

## 7. LSP surface by phase

### 7.1 Phase 1 — diagnostics-first

Methods/events:

- `initialize`
- `initialized`
- `textDocument/didOpen`
- `textDocument/didChange`
- `textDocument/didSave`
- `workspace/didChangeConfiguration`
- `textDocument/publishDiagnostics`

Goal: make the server useful purely as a **charm diagnostics daemon**.

### 7.2 Phase 2 — symbols/navigation

Methods:

- `workspace/symbol`
- `textDocument/documentSymbol`
- optionally `textDocument/definition` for metadata-linked entities if
  symbol resolution becomes reliable

Goal: make charm projects more navigable than generic Python+YAML
support can.

### 7.3 Phase 3 — code actions

Methods:

- `textDocument/codeAction`
- optionally `codeAction/resolve`

Goal: turn the most obvious `charmlint` findings into one-click fixes.

Examples of plausible first actions:

- insert missing `summary` or `description` stubs
- canonicalise known relation interface names where the rule already
  knows the expected spelling
- scaffold a missing unit-test directory or file when a rule is highly
  deterministic

Only ship actions that are:

- local
- mechanical
- reversible
- easy to preview

### 7.4 Phase 4 — docs integration

Possible methods:

- custom command for doc search
- hover enrichment
- `textDocument/codeLens` links to Canonical docs

This is the first phase where embeddings/index configuration enters the
picture.  Keep it optional.

## 8. Internal architecture

### 8.1 Workspace model

Each workspace should maintain:

- project root
- detected charm files
- cached diagnostics per backend
- debounce state for dirty files
- symbol index
- configuration/settings

The server should prefer **coarse but robust invalidation** at first:
re-run affected diagnostics when relevant files change, rather than
trying to be perfectly incremental too early.

### 8.2 Diagnostics pipeline

Recommended flow:

1. Detect whether the workspace is charm-shaped.
2. Determine affected targets from the changed file.
3. Run the relevant backends:
   - Python file changed -> `ruff`, `ty`
   - charm YAML changed -> `charmlint`
   - broad project change -> all
4. Normalise into one internal diagnostic model.
5. Group by URI.
6. Publish diagnostics per file.

### Caching

Carry over the spirit of Cantrip's current TTL/cache work, but adapt it
to editor semantics:

- debounce rapid edits
- avoid duplicate concurrent runs
- cancel stale in-flight work when a newer edit arrives

### 8.3 Symbols/indexing

Reuse the existing parsing ideas from repo-map:

- Python AST for classes/functions/methods
- YAML parsing for:
  - config options
  - actions
  - relations
  - resources
  - storage

Index symbols in a form suited to direct LSP responses, not prompt
rendering.

### 8.4 Code actions

Treat code actions as a separate layer above diagnostics:

- diagnostics identify issues
- quick-fix resolvers decide whether a safe edit exists

Do not bake editing logic into the linters themselves.  The server
should own edit construction so fixes remain editor-previewable.

## 9. Concrete reuse plan from Cantrip

There are three possible reuse strategies.

### 9.1 Copy first, stabilise later — recommended

Start by copying the relevant deterministic modules into the new repo:

- diagnostic model and merge logic
- repo-map parsers/index builders
- charmlint invocation helpers

Advantages:

- fastest path to a working standalone tool
- no cross-repo packaging work up front
- freedom to reshape APIs for LSP needs

Cost:

- temporary duplication

This is the right trade-off for v1.

### 9.2 Shared library extraction — later

Once the standalone tool proves useful, consider extracting a small
shared package for:

- charm metadata parsing
- diagnostic normalisation
- `charmlint` invocation contracts

Do this only when duplication becomes painful in practice.

### 9.3 Direct dependency on Cantrip internals — not recommended

Do **not** make `charmls` import Cantrip internals directly as a hard
runtime dependency.  That would couple:

- release cadence
- packaging
- API stability
- editor-server startup/runtime complexity

too tightly to an agent product with different goals.

## 10. Risks and mitigations

### 10.1 `charmlint` output stability

Risk: the CLI JSON format changes or differs subtly between Python and
Rust backends.

Mitigation:

- treat the JSON output as an explicit compatibility surface in
  `charmls`
- add golden tests for both backends
- prefer one backend deterministically when possible

### 10.2 Too much scope, too early

Risk: the project becomes "a coding agent in LSP clothing".

Mitigation:

- keep MVP deterministic
- ban chat/LLM features from v1
- ship diagnostics before any retrieval or generation feature

### 10.3 Editor-performance regressions

Risk: full-project runs on every keystroke make the server feel slow.

Mitigation:

- on-change debounce
- on-save full pass
- per-backend scheduling
- cancellation of stale work

### 10.4 Unclear code-action safety

Risk: quick fixes silently make bad charm changes.

Mitigation:

- only ship actions that are previewable and mechanical
- require an explicit rule-to-fix mapping
- start with a very small allowlist

## 11. Phased implementation plan

### Phase A — bootstrap

- create new repository
- choose LSP framework (`pygls` is the simplest likely fit)
- implement project-root detection
- implement settings model
- wire logging and test harness

**Exit criterion:** server starts in an editor and recognises a charm
workspace.

### Phase B — diagnostics MVP

- port/copy the unified diagnostic model
- implement `charmlint` backend
- implement `ruff` backend
- implement `ty` backend
- merge and publish diagnostics
- add debounce/cancellation

**Exit criterion:** editing a charm shows one coherent diagnostics stream
in the editor.

### Phase C — symbols MVP

- port/copy repo-map parsing core
- expose `workspace/symbol`
- expose `documentSymbol`
- add charm-metadata symbol kinds

**Exit criterion:** charm-specific entities appear in symbol search and
document outline.

### Phase D — first code actions

- define quick-fix contract
- map a small set of rules to edits
- implement `textDocument/codeAction`

**Exit criterion:** at least a few common `charmlint` findings offer safe
editor actions.

### Phase E — docs integration (optional)

- decide whether docs index is local-only or externally managed
- add a command/hover surface
- test UX with large workspaces and no configured embed provider

**Exit criterion:** documentation lookup adds value without becoming a
dependency for the rest of the server.

## 12. Recommendation

Build **`charmls` as a separate Python repository**, starting with:

1. `charmlint` diagnostics
2. merged `ruff`/`ty`/`charmlint` diagnostics
3. repo-map-derived symbol support

Treat docs search as a later enhancement and **keep all agentic features
out of scope**.

The key insight is:

> The most valuable Cantrip knowledge for an IDE is the
> **deterministic, structured substrate beneath the agent**, not the
> agent loop itself.

That substrate is already good enough to justify a standalone language
server, provided the product is kept small, charm-focused, and editor
native.
