# Coding-Agent Reviews Log

Cantrip is one of many coding agents in active development. Other teams
solve similar problems differently, and some of their ideas transplant
cleanly onto Cantrip's charm-specific focus. This file is the running
log of which agents we've walked end-to-end looking for adoptable
patterns, which phase captured the findings, and which agents we've
considered but deferred (with reasoning, so a future sweep doesn't
re-ask the same question).

ROADMAP captures the *findings* as numbered phases; this file captures
the *bookkeeping*.

## Review cadence

Run a sweep whenever a notable agent ships a major release, or when a
user mentions a pattern from elsewhere that looks relevant. Each sweep:

1. Walk the agent's landing page, README, and docs. Enumerate features,
   commands, configuration surfaces, extension points.
2. Filter against what Cantrip already has (ROADMAP, `docs/docs/`) and
   against patterns already adopted from earlier reviews — no point
   rediscovering the same gap twice.
3. Pick the three-to-five adoptions that are genuinely charm-relevant
   and land as their own ROADMAP phase, numbered sequentially.
   Follow the Phase 67 template: goal paragraph, candidates in
   priority order, explicit out-of-scope list with reasoning,
   sub-phases with checklists, exit criteria, dependency table.
4. Log the review in the table below: what date, what source, what
   phase the findings landed in.
5. If an agent is considered and skipped, record it in the *Deferred*
   section with a one-sentence reason.

## Reviews completed

| Agent | Reviewed | Source | Landed as | One-liner on what we took |
|-------|----------|--------|-----------|--------------------------|
| Pi (`pi.dev`) | 2026-04-23 | [pi.dev](https://pi.dev) | Phase 67 (M67) | Session tree rewind/branch, mid-session `/model`, `cantrip run --print --json`, `/share` to secret gist |
| OpenCode | 2026-04-23 | [opencode.ai/docs](https://opencode.ai/docs/) | Phase 68 (M68) | Snapshot-backed `/undo`/`/redo`, declarative ask/allow/deny permissions, markdown user slash commands, session-level plan mode |
| Kimi Code CLI | 2026-04-23 | [github.com/MoonshotAI/kimi-cli](https://github.com/MoonshotAI/kimi-cli), [moonshotai.github.io/kimi-cli](https://moonshotai.github.io/kimi-cli/en/) | Phase 69 (M69) | Bounded Ralph-Loop iterate-until-green, `--yolo` unattended mode, `Ctrl-X` shell mode, Mermaid/D2 Flow skills |
| Amp | 2026-04-23 | [ampcode.com/manual](https://ampcode.com/manual) | Phase 70 (M70) | Librarian subagent for Charmhub/Launchpad, Oracle second-opinion tool, glob-conditional guidance in AGENTS.md, prompt-based review Checks, Painter for charm icons |
| Aider | 2026-04-23 | [aider.chat](https://aider.chat), [docs](https://aider.chat/docs/) | Phase 71 (M71) | Tree-sitter repo-map with PageRank-ranked symbols, architect/editor two-model mode, auto-commit-per-turn with dirty-commit separation, per-edit ruff/ty/charmlint feedback loop |
| Continue.dev | 2026-04-23 | [docs.continue.dev](https://docs.continue.dev), [config reference](https://docs.continue.dev/reference) | Phase 72 (M72) | Indexed charm-ecosystem docs (`@docs`), `@`-mention context-provider registry, `embed`/`rerank` model roles, `@problems` diagnostics-as-pre-turn-context |
| Goose | 2026-04-23 | [goose-docs.ai](https://goose-docs.ai), [recipe reference](https://goose-docs.ai/docs/guides/recipes/recipe-reference), [MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview) | Phase 73 (M73) | Parameterised retryable Recipes with sub-recipes, MCP Apps as sandboxed iframes in the Web UI, JSON-schema-enforced structured responses, declarative retry with shell validators |

**Note:** completed phases (marked ✓) may move from `ROADMAP.md`
to `ROADMAP_ARCHIVE.md` over time. When looking for a past phase's
detail, check both files.

## Reviews planned

| Agent | Why next | Target phase |
|-------|----------|--------------|
| _(none currently planned)_ | Sweep cycle complete. Add a new candidate here when something distinctive ships or a user surfaces a pattern not already captured in Phases 67–73. | — |

## Deferred — considered and skipped with reason

These agents were surveyed briefly and set aside. Revisit if a request
surfaces or a major release lands.

| Agent | Reason for deferring |
|-------|----------------------|
| Cline / Roo Code | VS Code-native; "approve every diff before apply" UX and checkpoint model overlap heavily with Phase 68.1 (file snapshots) and Phase 64 (CONFIRM). Worth a pass *after* 68.1 ships, to see if their diff-review UX has ideas for the CONFIRM flow. |
| Cursor Agent / Composer | Product-shape-specific (IDE-native agent inside Cursor). Of the distinct ideas — `.cursorrules`, `@Docs` / `@Web` / `@Codebase`, shadow workspace — most overlap with Continue.dev (Phase 72 candidate) or Amp (Phase 70 Librarian). Likely duplicative; revisit only if a specific affordance surfaces. |
| Devin / Replit Agent / Factory | Higher-autonomy, longer-horizon agents. Different operating point from Cantrip; the interesting patterns (task decomposition, self-verification) are more relevant to Phase 32 (planning quality) or Phase 52 (durable subagents) than to a standalone ecosystem-scan phase. Fold findings into those phases if they come up. |
| Codex CLI (OpenAI) | Three-tier approval model (`read-only`, `auto-edit`, `full-auto`) is worth contrasting with Phase 68.2 (permissions) and Phase 69.2 (`--yolo`), but the gap is narrow — one row in the 68.2 permissions follow-up rather than a new phase. |
| Claude Code | We *are* Claude Code (invoked from it) and read the best-practices doc during Phase 36. New findings land in Phase 36 follow-ups, not a new phase. |
| GitHub Copilot Chat / Workspaces | Deep IDE integration, little in the way of primitives that don't appear in Cursor/Continue/Cline. Skipped for overlap. |

## What this log is *not*

- Not a substitute for the ROADMAP phases themselves. The phases are
  where adoption *decisions* live; this file is the index.
- Not a competitive analysis. We aren't tracking feature parity — only
  adoptable ideas. Many excellent agent features are skipped here
  because they don't fit Cantrip's charm focus, not because they're
  bad.
- Not a list of upstream charm-ecosystem changes. That's
  `UPSTREAM_AUDIT.md`.
