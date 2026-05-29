# Claude Code Best Practices Review — Findings

> Output of Phase 36.  This is a research document, not a design.  It
> records the question (what does the community-curated repo at
> [`shanraisshan/claude-code-best-practice`](https://github.com/shanraisshan/claude-code-best-practice)
> recommend, and which recommendations should Cantrip adopt — for
> (a) working *on* Cantrip with Claude Code, and (b) Cantrip's own
> agent design — and the verdict.

## TL;DR

- **Repo scope is overwhelmingly Angle A** (how a developer uses Claude
  Code on a project): CLAUDE.md structure, `.claude/settings.json`,
  hook events, slash commands, skills, subagent frontmatter, MCP
  servers, terminal/voice/focus modes, `/loop` and `/schedule`.
  Cantrip already practises most of the load-bearing items —
  CLAUDE.md is 94 lines (well under the 200-line guideline), the
  test/lint/commit conventions are documented, the repo uses
  `uv` exclusively, etc.
- **The one concrete Angle-A gap** is the team-shared
  `.claude/settings.json` allow-list, which covers the read-only
  Bash and `gh` commands but not the documented `make` /
  `uv run pytest` / `uv run ruff` / `uv run ty` developer loop.
  Every Phase touches those commands hundreds of times and the
  permission prompts are pure friction.  **Adopted.**
- **Angle B (Cantrip's own agent design)** lands almost entirely
  in already-implemented territory.  Subagents-as-context-isolation,
  research → synthesis → confirm → build, "don't use prompts for
  control flow", "build for the model six months from now",
  "skill descriptions are written for the model" — all already in
  Cantrip's two-loop architecture, the planner, the system prompt,
  and the `agentskills.io` SKILL.md format.  No production code
  change.
- **Two watch-this items for Angle B** with named revisit
  triggers: Anthropic's
  [Programmatic Tool Calling](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/programmatic-tool-calling)
  (PTC) and the
  [tool-search-tool / `defer_loading`](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/tool-search-tool)
  pattern.  Both are Anthropic-API features; Cantrip's
  `LLMProvider` abstraction would need an opt-in capability flag
  to use them and the cost/latency wins are unproven against
  Cantrip's tool catalogue.  Phase numbers are not yet allocated.
- **Verdict: thin adopt-list, no new phase.** One settings-file
  edit (Phase 36 itself), three "keep an eye on this" entries
  added to the deferred-items log, and a reviewed punch list of
  ~120 community recommendations cross-referenced against
  Cantrip's current state.

The rest of this document walks the evidence.

## 1. What the source repo is

The repo at
[`shanraisshan/claude-code-best-practice`](https://github.com/shanraisshan/claude-code-best-practice)
(cloned April 2026) is a 17-folder, ~8.7 kloc reference repository
plus presentation assets.  Six content areas drive the actionable
advice:

| Folder | What it is | Lines |
|---|---|---|
| `best-practice/` | Eight reference docs: `claude-cli-startup-flags`, `claude-commands`, `claude-mcp`, `claude-memory`, `claude-power-ups`, `claude-settings` (1043 lines), `claude-skills`, `claude-subagents` | 2336 |
| `reports/` | Ten analysis reports: agent-vs-command-vs-skill, agent memory, advanced tool use (PTC, tool search), SDK-vs-CLI system prompts, day-to-day degradation, why-harness-is-important, etc. | 2742 |
| `tips/` | Nine boris-cherny / thariq tip lists summarised from videos | 1339 |
| `videos/` | Six Boris/Cat/Dex video summaries | 1801 |
| `implementation/` | Five practical examples (agent teams, commands, skills, subagents, scheduled-tasks) | 462 |
| `development-workflows/` | Two: cross-model and "research-plan-implement" (RPI) | (small) |

The dominant authorship is Boris Cherny (Claude Code lead), Cat Wu,
Dex (MLOps Community), and Thariq.  Most evidence either originates
at Anthropic or rests on Anthropic public posts.

## 2. What Cantrip already has

For a fair comparison, the punch list was triaged against the
actual state of `/home/ubuntu/cantrip`:

| Cantrip area | Current state |
|---|---|
| `CLAUDE.md` | 94 lines.  Documents `uv`-only, `make` targets (`format`, `lint`, `unit`, `check`, `all`, `coverage`), file-scoped lint/format/test commands, UK English, `ty` (not mypy), 3.12+, dataclasses (no Pydantic), `str \| None`, `import datetime`, no bare `except`, charm-development conventions, three paths (A/B/C), workflow ("commit at appropriate times"), and a `Reference Documents` index pointing at `design/PLAN.md` etc. |
| `.claude/settings.json` | 50 lines.  Allow-list of read-only Bash (`ls`, `pwd`, `find`, `file`, `stat`, `wc`, `head`, `tail`, `cat`, `tree`), read-only `git` (`status`, `log`, `diff`, `show`, `branch`, `remote`, `tag`, `stash list`, `rev-parse`), read-only `gh` (`pr view`, `pr list`, `pr checks`, `pr diff`, `issue view`, `issue list`, `run view`, `run list`, `run logs`, `repo view`, `api`), `python --version` / `python3 --version` / `uv pip list` / `uv tree`, `make --version` / `make -n`, and two `WebFetch` domains.  No deny rules.  No hooks. |
| `.claude/settings.local.json` | Personal: more `WebFetch` domains, `WebSearch`, one specific `cantrip-test` invocation. |
| `.claude/commands/` | Does not exist. |
| `.claude/agents/` | Does not exist. |
| `.claude/skills/` | Does not exist (Cantrip's *own* skills under `src/cantrip/skills/` are agent-side, not Claude Code skills). |
| `.claude/hooks/` | Does not exist. |
| `.claude/rules/` | Does not exist; CLAUDE.md is single-file. |
| Cantrip system prompt | `src/cantrip/agent/prompts/system.md.j2` — 737-line Jinja2 template.  Already structured around Cantrip's business: purpose, principles, tool bundles, planner pattern, three paths, OCI strategy, libraries, dependency hygiene, integrations, dev cycle, completion checklist, Terraform, security event logging, tracing, debugging-with-observability, workload research, DESIGN.md/WORKLOAD.md formats, three example interactions, watcher behaviour. |
| Cantrip subagents | Nine: `acceptance`, `build`, `day2`, `debug`, `demo`, `deploy`, `infra`, `librarian`, `research`, `test` (3–90 lines each).  Composed in `core.py`; not Claude-Code subagents. |
| Cantrip tool catalogue | 30+ Python tools under `src/cantrip/agent/tools/` — typed registration via `base.py`, bundled families (`juju`, `git`, `gh`, `memory`) so the schema is discoverable. |
| Cantrip skills | 30+ `agentskills.io`-style SKILL.md files under `src/cantrip/skills/` and `.agents/skills/` — load-on-demand via the `load_skill` tool. |
| Cantrip memory | First-class subsystem: `memory_writer.md.j2`, four scopes (user, charm, global, plus auto-memory under `~/.claude/projects/<hash>/memory/`).  Cross-session by design. |

## 3. The Angle-A punch list — what we adopted

This is the table I walked the recommendations against.  Items are
keyed by topic, not by source file.  Concrete, actionable, novel
(not already in Cantrip) items go on top.

### 3.1 Adopted: expand `.claude/settings.json` allow-list

**Source:** `tips/claude-boris-12-tips-12-feb-26.md` ("Pre-approve
common permissions"), plus the
[`fewer-permission-prompts`](https://github.com/anthropics/skills)
skill that ships with Claude Code.

**Gap:** Cantrip's CLAUDE.md tells the assistant to run `make check`,
`make unit`, `make format`, `make lint`, `make coverage`, `make all`,
`uv run pytest <path>`, `uv run ruff check`, `uv run ruff format`,
and `uv sync --dev` routinely.  None of those match the existing
`.claude/settings.json` patterns.  Every run currently triggers a
permission prompt — pure friction with no safety win, since these
are sandboxed dev-loop commands.

**Change:** add the documented developer-loop commands to the
team-shared allow-list, scoped narrowly enough that arbitrary
`uv run <thing>` doesn't slip through:

```jsonc
// addenda to .claude/settings.json
"Bash(make check:*)",
"Bash(make unit:*)",
"Bash(make format:*)",
"Bash(make lint:*)",
"Bash(make coverage:*)",
"Bash(make all:*)",
"Bash(uv run pytest:*)",
"Bash(uv run ruff check:*)",
"Bash(uv run ruff format:*)",
"Bash(uv run ty:*)",
"Bash(uv run python -c:*)",
"Bash(uv sync --dev:*)"
```

`uv run python -c` is included because tiny one-shot Python
inspections (e.g. `uv run python -c 'import cantrip.x; print(...)'`)
recur in the docs and in past transcripts; arbitrary `uv run python
<file>` is *not* on the list because it could exec untrusted scripts.

### 3.2 Already in place — no change needed

| Recommendation | Cantrip state |
|---|---|
| CLAUDE.md under 200 lines | 94 lines ✓ |
| Iteratively grow CLAUDE.md from corrections | Auto-memory under `~/.claude/projects/-home-ubuntu-cantrip/memory/` already does this on a separate plane; CLAUDE.md is for durable team-shared rules ✓ |
| Document `uv`-only / no `pip`/`pipx` | Explicit in CLAUDE.md ✓ |
| Document file-scoped lint/format/test commands | Table in CLAUDE.md ✓ |
| Reference design docs from CLAUDE.md | `Reference Documents` section indexes 13 design docs + ROADMAP + CHANGELOG ✓ |
| Use commands for inner-loop workflows | `make` already covers this — `make check` *is* the inner loop |
| `/compact` at ~50% context | Claude Code-side; user discipline, not a settings change |
| `/rewind` over corrections | Same — keyboard ergonomics, not a Cantrip artefact |
| Plan mode for big tasks | The `Plan` agent exists; CLAUDE.md guidance "consider in 2-3 sentences with tradeoffs" already nudges this for exploratory questions |
| Two-tier settings (team vs `.local.json`) | Both files exist ✓ |
| `WebFetch(domain:…)` allow-listing for trusted docs | Already practised in `.local.json` ✓ |

### 3.3 Considered and rejected for now

| Recommendation | Reason for rejection / deferral |
|---|---|
| Split CLAUDE.md into `.claude/rules/*.md` with `paths:` frontmatter | Overhead exceeds benefit at 94 lines.  Revisit if CLAUDE.md grows past ~250 lines. |
| Add project slash commands under `.claude/commands/` (`/run-checks`, `/coverage`, `/upstream-sweep`) | `make check` and `make coverage` are already one-keystroke; a slash command wrapper is layering for layering's sake.  The `/upstream-sweep` idea is real but is already ROADMAP Phase 37 / `design/UPSTREAM_AUDIT.md`. |
| Add project subagents under `.claude/agents/` | Would duplicate Cantrip's *own* subagent catalogue (`build`, `debug`, `acceptance`, etc.) which is the system Cantrip is *building*.  Splitting attention between two parallel agent catalogues confuses the codebase. |
| Add project skills under `.claude/skills/` | Same reason — Cantrip already has 30+ agentskills.io skills under `src/cantrip/skills/`.  Mixing Claude-Code skills and Cantrip skills in the same repo would invite version skew. |
| `.claude/hooks/` for PostToolUse → `make format` | The CLAUDE.md instruction "format with ruff" runs via `make format` on demand; an automatic hook would re-format every Edit, including in-progress code, slowing iteration without preventing the eventual `make check` pass.  The deterministic-blocking value (PreToolUse hooks reject `rm -rf` etc.) is genuine but not currently a problem in this repo. |
| Worktree symlink directories / sparse-checkout | Repo is small enough that worktree creation is fast.  Revisit if total worktree disk usage starts to bother anyone. |
| Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) | Experimental; Cantrip's own work loop is the comparable feature for the agent.  When developing on the codebase, `Explore` + `general-purpose` subagents already cover parallelism. |
| Voice (`/voice`), focus mode (`/focus`), status line (`/statusline`), terminal-setup, `/powerup` lessons | Personal ergonomics; not codebase artefacts. |
| `/loop` and `/schedule` for routines | Already used (autonomous loop infrastructure exists in `cantrip schedule`).  No Cantrip change. |
| `/batch` for fan-out changesets | None of Cantrip's foreseen work fans out to "dozens of worktrees".  Watch if a sweep ever genuinely calls for it. |
| `--dangerously-skip-permissions` | Memory `feedback_uv_only` and the workflow rules in CLAUDE.md already constrain side-effecting commands; auto-mode classification is harmless on top.  Skip-permissions is a footgun. |
| Boris's "single commit per file" rule | Cantrip's CLAUDE.md and memory `feedback_commit_all_together` say the *opposite* — bundle drift into one commit.  Adopting Boris's rule would contradict an explicit user feedback memory. |

### 3.4 Settings keys that exist but Cantrip doesn't use

The 1043-line `claude-settings.md` documents many keys.  None are
worth adopting today:

- `attribution.commit` / `attribution.pr` — Cantrip's commit
  attribution is already covered by harness defaults.
- `alwaysThinkingEnabled` — per-session toggle is fine; setting
  it globally trades cost for marginal quality.
- `worktree.symlinkDirectories` / `worktree.sparsePaths` — see
  §3.3, repo too small.
- `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS` — we *want* the built-in
  git workflow.
- `--init-only` / `--init` — no per-startup setup needed beyond
  what Claude Code does on its own.

## 4. The Angle-B punch list — Cantrip's own agent design

Three things to note up front:

1. The repo is mostly written from the *outside* of Anthropic's
   harness looking in.  Many "Angle B" recommendations are about
   how the harness itself works, which Cantrip can read as
   reference architecture but cannot directly adopt — Cantrip is
   its own harness.
2. Cantrip's two-loop architecture (`design/AGENT.md`) and the
   research → synthesis → confirm → build planner pattern
   (`src/cantrip/agent/prompts/planning/`) already implement most
   of the principles the videos discuss.
3. The two genuinely novel API-side capabilities — Programmatic
   Tool Calling and the tool-search-tool — are recent enough
   (≤6 months) that no Cantrip phase has evaluated them yet.

### 4.1 Already in place

| Principle | Where Cantrip implements it |
|---|---|
| Subagents = context isolation, not just delegation | `Subagent.run()` runs in its own context; the parent only sees the final result.  `core.py` orchestrates. |
| Multiple uncorrelated context windows for hard problems | Used in research subagent dispatch (parallel fan-out). |
| Don't use prompts for control flow — use control flow | Cantrip's planner *is* control flow.  Phases are state-machine nodes, not prompt instructions. |
| Vertical slicing: end-to-end first, layer up | `Get to active/running fast` is principle #1 in the system prompt; the build subagent targets a deployable charm before adding tests/observability. |
| Skill descriptions are written for the model | `agentskills.io` SKILL.md frontmatter `description:` already addresses the model.  See `design/SKILLS.md`. |
| Cross-session memory | `memory_writer` + `~/.claude/projects/<hash>/memory/` pattern already in use. |
| Build for the model six months from now | Cantrip explicitly bets on better models (Path A 12-factor, oracle escape hatch, no over-engineered scaffolding). |
| Hide research from main context | Research subagent runs in a forked context; the parent gets the synthesised DESIGN.md, not the raw research notes. |
| "Gotchas" sections in skills | Most Cantrip skills already follow this pattern (`charmcraft`, `jhack`, `concierge`, `iterate-fix`, etc.).  Audit pending — see §6. |
| Plan-mode workflow | Mapped onto the planner's research → synthesis → **confirm** phase, where the user approves before build. |
| Day-to-day model variance is real (±8–14 %) | Cantrip's two-loop design with retries-after-validation is naturally tolerant; the oracle escape hatch handles judgement-shaped questions on bad days. |

### 4.2 Watch-this items (no phase opened)

#### 4.2.1 Programmatic Tool Calling (PTC)

**What it is:**  An Anthropic API feature where the model emits
Python that orchestrates several tool calls in a single
code-execution sandbox round-trip, instead of the usual N-round
back-and-forth.  Intermediate tool results stay in the sandbox;
only the final `stdout` re-enters the model's context.

**Where it could land in Cantrip:**  The `provider.anthropic`
backend in `src/cantrip/llm/`, with an opt-in capability flag.
Three obvious candidate flows:

- **Planner research fan-out.**  Today's parallel research tasks
  each consume a full inference round.  PTC could batch
  `charmhub_search` + `web_fetch` + `analyse_framework` into a
  single round.
- **Audit sweep.**  `charm_audit` walks several read-only tools
  (charmlint, file scans, COS-relation check, test-existence
  check).  These are ordered and side-effect-free.
- **Validate-after-fix loops.**  `charm_validate` + selective
  test reruns currently use multiple inference rounds.

**Why it's deferred:**  The cost/latency win on a real Cantrip
phase is unproven; the wrong tools to expose to PTC could
introduce harder-to-debug failure modes (one stack trace
covering five tool calls).  The Anthropic provider is the only
LLM provider with PTC; tying load-bearing flows to one provider
breaks Phase 21's provider-abstraction goal.

**Revisit triggers:**

- A Cantrip user reports concrete latency frustration with
  multi-tool research/audit phases.
- Anthropic publishes PTC pricing/latency benchmarks against
  agentic-tool-call workloads (not just LLM-eval benchmarks).
- A second LLM provider implements an equivalent (Gemini's
  `code_execution` already approaches this; OpenAI's
  Responses-API-with-tools partially overlaps).
- Phase 86b or another follow-on phase adds a new typed tool
  whose value clearly compounds when called in batches.

#### 4.2.2 Tool Search Tool (`defer_loading`)

**What it is:**  Anthropic API feature (also surfaced in Claude
Code as `ENABLE_TOOL_SEARCH=auto:N`) that defers loading
infrequently-used tool schemas until the model explicitly
searches for them.  Quoted ~85 % reduction in tool-definition
tokens for catalogues with many rare tools.

**Where it could land in Cantrip:**  The
`build_tools_schema()` path in the agent core, gated by a
provider capability flag.  Cantrip exposes 30+ typed tools, plus
roughly that many sub-tools through the four `juju|git|gh|memory`
bundles (already a manual form of deferral).

**Why it's deferred:**

1. The bundling already gives much of the win — the
   `juju` tool description includes a sub-command schema, but
   the model only sees one top-level tool entry.
2. The remaining ~30 top-level entries fit comfortably under
   10 % of a 200K context window.
3. Implementing this on the provider boundary requires a new
   `LLMProvider` capability and at least Anthropic-specific
   wire-format support; the engineering cost vastly exceeds
   the savings on today's catalogue.

**Revisit triggers:**

- Cantrip's tool catalogue passes ~60 typed top-level tools
  (we are at ~35 today).
- A capacity-test or provider-cost-report shows tool definitions
  exceeding 10 % of typical session context.
- An observability-dashboard skill adds a typed
  `tempo_waterfall_tool` plus a typed `parca_query_tool` plus a
  typed `pyroscope_query_tool` — Phase 89's natural surface area.

#### 4.2.3 Day-to-day model variance (±8–14 %)

**What it is:**  Scale AI / Anthropic-published evidence that
identical prompts produce up to ±14 % quality variance day-to-day
because of MoE batch composition, hardware heterogeneity (TPU /
GPU / Trainium), and infrastructure bugs.  See
`reports/llm-day-to-day-degradation.md`.

**Where it could land in Cantrip:**  Nowhere directly — it's a
constraint, not a feature.  But it has two implications worth
recording:

- **Don't tune Cantrip prompts to a single observed regression.**
  A bad day for one provider isn't a bug in Cantrip's prompt.
  The two-loop architecture's retry-with-validation is the
  correct mitigation.
- **The oracle escape hatch is the right shape.**  When a
  judgement-shaped question goes badly, the oracle re-rolls on a
  stronger model — a fresh context with a different routing,
  which is exactly what `/compact` and `/clear` do for
  interactive sessions.

No code change.  Filed as guidance for prompt-debugging triage.

### 4.3 Considered and rejected for Angle B

| Recommendation | Reason |
|---|---|
| Modular system prompt (110+ fragments, conditional on tool / file / mode) | Cantrip's `system.md.j2` is already conditionally rendered (skills_index, repo_map, memory_index, watcher_enabled, current-context block).  Going from "5 conditional sections" to "110 fragments" is over-engineering for an agent with a single product purpose. |
| Per-skill model overrides (`model: haiku` on cheap skills) | Cantrip exposes `oracle_consult` for the deliberate dial-up; routine skills already use the session model.  Per-skill model dispatch would add billing surprises for the user without commensurate quality wins. |
| Per-skill effort overrides (`effort: high`) | Same — already covered by oracle escape and the global `/effort` setting. |
| Worktree-isolation subagents | Cantrip's subagents already context-isolate; physical worktrees are an extra layer Cantrip doesn't need. |
| Memory scopes per subagent | Cantrip's memory subsystem is already richer (4 scopes, with revalidate / sweep / forget verbs). |
| `/code-review` Code Review feature | Cantrip already has `pr_review` and a `find-bugs` skill; the Claude Code Code Review feature is a parallel (Anthropic-hosted) channel for the same outcome.  No reason to bind to it. |
| RPI workflow (Research-Plan-Implement) with seven dedicated agents | Functionally equivalent to Cantrip's `research → synthesis → confirm → build` pattern with fewer named roles.  Adopting their roles wholesale would require reorganising `prompts/subagent/` against current named subagents. |
| Cross-model workflow (one agent for plan, another for code) | Cantrip's `oracle_consult` is the targeted version of this.  No need to install a heavier fan-out for routine tasks. |

## 5. Verdict

Adopt one settings change.  Open no new phase.  Record three
watch-this items in `design/DEFERRED.md` so Phase 84's deferred-item
sweep picks them up at the next audit cadence.  Re-run this review
when:

- Anthropic publishes a benchmarked Programmatic-Tool-Calling case
  study against agentic workloads (not pure eval suites).
- Cantrip's typed tool catalogue passes ~60 entries.
- Claude Code ships a feature that Cantrip's harness genuinely
  cannot replicate (e.g. cross-session multi-agent collaboration
  with shared write surface — Agent Teams maturing out of
  experimental).
- A Cantrip user reports concrete latency frustration that maps
  onto a recommendation rejected above.

## 6. Follow-on housekeeping (out of scope for Phase 36)

These items surfaced during the review but belong to other phases
or to routine maintenance:

- **Audit the "Gotchas" section in every Cantrip skill** (`§4.1`).
  Source repo treats this as the highest-signal slot.  A small
  sweep across `src/cantrip/skills/*/SKILL.md` would confirm
  whether any are missing one.  Suggested cadence: opportunistic
  while writing/reviewing skills, not a dedicated phase.
- **Memory cross-check.**  `tips/claude-thariq-tips-17-mar-26.md`
  recommends `${CLAUDE_PLUGIN_DATA}` for skill data.  Cantrip's
  skills don't carry persistent data files today; if they ever
  do (e.g. a per-skill cache of charmhub query results), this
  is the right pattern to copy.
- **Tool documentation pass.**  Source repo's
  `claude-skills-implementation.md` recommends very explicit
  trigger phrases in skill descriptions.  Cantrip's skill
  descriptions are good but not always model-tuned.  A pass
  against `description:` strings could marginally improve skill
  auto-discovery.  Combine with the Gotchas audit.
