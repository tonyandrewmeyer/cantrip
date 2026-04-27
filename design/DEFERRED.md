# Deferred-Item Sweep Log

Flat audit log of explicit deferrals scattered across `ROADMAP.md` and
`ROADMAP_ARCHIVE.md`.  Each row is one piece of work that was scoped
out of its parent phase with a "revisit when…" condition rather than
dropped outright.  See Phase 84 in `ROADMAP.md` for the procedure;
this file is the artefact each sweep reads and re-stamps.

**Current cadence:** quarterly.

**Last audit:** 2026-04-26.

**Next audit due:** 2026-07-26 — set a `/schedule` reminder when this
file is next opened so the cadence does not rely on someone
remembering.

## Status legend

- **Not fired** — the original revisit trigger has not happened; the
  deferral stands.
- **Fired** — the trigger has happened; a follow-up phase or task is
  linked in the *Notes* column.  Move the row to a "Resolved"
  section once the follow-up lands.
- **Dropped** — the underlying need disappeared.  Delete the row in
  the next sweep with a one-line note.

## Active deferrals

| Phase / Sub-task | What was deferred | Revisit trigger | Status (2026-04-26) | Notes |
|---|---|---|---|---|
| 67.1 (Pi sessions) | Amp-style `@@` cross-session prompt picker | A session registry (e.g. `~/.config/cantrip/sessions.json`) exists, **or** a concrete user report of "wish I could quote that branch I had two days ago" arrives | Not fired | No session registry shipped; in-session `@T-<id>` would mis-set expectations on its own |
| 67.2 (Pi sessions) | TUI hotkey + favourites cycling for `/model` | A concrete ergonomic case beyond the slash command surfaces | Not fired | `Ctrl+L` is already `clear_chat`; rebinding would surprise users |
| 70.1 (Librarian) | Post-fetch `src/charm.py` / ops-vs-reactive filter on `charmhub_fetch` | The Librarian sees real use and the manual `read_file` + `glob` workaround stops being enough | Not fired | Agent can do this manually today via existing tools |
| 70.1 (Librarian) | Charm-tarball download via Charmhub `download` URL | A concrete need to read the *built* artefact (manifest, packed wheels) emerges | Not fired | Source-via-git remains the right surface for read-source use cases |
| 70.2 (Oracle) | `settings.oracle_model` config-file surface | A generic settings layer lands — Phase 68.2 (permissions YAML) is the closest analogue | Not fired | Phase 68.2 shipped permissions YAML, but no generic settings file yet; runtime `state.*` overrides cover the sticky-per-session use case |
| 70.2 (Oracle) | `/oracle off` slash command | A user wants to toggle the per-turn cap from chat | Not fired | Cap of zero already disables; only the slash-command surface is missing |
| 70.5 (Painter) | Auto-invocation at BUILD completion via a CONFIRM task | A real user reports "I keep forgetting to paint an icon before publishing" | Not fired | Needs Phase 64 confirmation-task plumbing to wire cleanly |
| 70.5 (Painter) | Reference-image input (up to three reference PNGs) | A charm team asks for brand-consistent iteration | Not fired | Abstraction supports `bytes` extras; prompt path needs the additional surface |
| 70.5 (Painter) | True vectorisation via `potrace` / `svgtrace` / `vtracer` | The embedded-PNG path earns concrete user complaints | Not fired | `potrace` adds a heavy C-library dependency |
| 71.4 (Aider edit loop) | `pytest --collect-only` on touched test files | A concrete case where the `ruff` / `ty` pair misses an import-typo failure surfaces | Not fired | `state.auto_test_collect_only` not yet wired |
| 73.3 (Goose structured) | Migrate existing call sites onto the structured-output primitive | Each consumer phase opens its own follow-up work | Not fired | Planner (32) still uses regex + `json.loads`; Oracle (70.2) returns text; Acceptance (17) takes pre-assembled markdown |
| 48.5 (Multimodal) | `workload_screenshot` headless-browser tool | (a) A concrete case shows the agent needs to *see* a workload UI to debug it, **or** (b) Playwright lands as a transitive dep elsewhere | Not fired | Phase 17.3 `workload_endpoint_test` already exercises HTTP endpoints functionally without screenshots |
| 49.3 (Sandbox) | Seccomp-bpf allowlists for tools with constrained syscall needs | A tool presents a concrete syscall-level attack surface, **or** a `libseccomp` binding becomes a transitive dep | Not fired | `bwrap` namespace layer already covers the exit-clause requirements; seccomp-without-libseccomp is error-prone |
| 55.4 (Governance) | Intent classification — regex threat scoring against prompt content | A real case emerges where a prompt-content regex would have caught something the tool-surface gate missed | Not fired | In the charm-building context the signal comes from the tool surface (`juju destroy-*`, `rm -rf`), not the prompt content |
| Claude prompt caching | 1-hour cache TTL via the `extended-cache-ttl-2025-04-11` beta header (`cache_control: {"type": "ephemeral", "ttl": "1h"}`) | Long-running paths (sprint deploy, autonomous overnight runs) report cache misses on multi-minute pauses (e.g. `charmcraft pack`, `juju wait`) — visible as `cache_read_input_tokens` collapsing partway through a run | Not fired | Default 5 min TTL covers interactive use; 1 h costs 2× on write but ~10% of base on read so it pays back fast for runs that pause mid-loop |
| 87.1 (Alertmanager) | Phase 17 acceptance test for "production-grade alerting" charm | A real session asks for production-grade alerting and the agent picks up the new skill content end-to-end | Not fired | Skill body covers the alert-rule + routing path; test wiring follows when an end-to-end case appears |
| 87.4 (Sloth) | Phase 17 acceptance test for "production-grade reliability monitoring" charm | A real session asks for SLO-managed reliability and the agent drops a working `slos.yaml` end-to-end | Not fired | Skill body covers the SLI / objective / burn-rate alert path; harness wiring follows when an end-to-end case appears, mirroring 87.1's deferral shape |
| 36 (Claude Code best practices) | Programmatic Tool Calling (PTC) for Cantrip's Anthropic provider | (a) Anthropic publishes PTC pricing/latency benchmarks against agentic workloads, **or** (b) a second LLM provider implements an equivalent (Gemini `code_execution`, OpenAI Responses-API-with-tools), **or** (c) a Cantrip user reports concrete latency frustration with a multi-tool research/audit phase | Not fired | Tying load-bearing flows to one provider conflicts with Phase 21's provider-abstraction goal; cost/latency win unproven against Cantrip's actual tool catalogue. See `design/CLAUDE_CODE_BEST_PRACTICES.md` §4.2.1 |
| 36 (Claude Code best practices) | Tool-search-tool with `defer_loading: true` for Cantrip's tool catalogue | Top-level typed-tool count passes ~60 (we are at ~35) **or** tool definitions exceed 10 % of typical session context **or** Phase 89 lands with `tempo_waterfall_tool` + `parca_query_tool` + `pyroscope_query_tool` | Not fired | Existing `juju \| git \| gh \| memory` bundling already provides much of the win.  See `design/CLAUDE_CODE_BEST_PRACTICES.md` §4.2.2 |
| 36 (Claude Code best practices) | Re-run the source-repo review | Anthropic ships a feature Cantrip's harness genuinely cannot replicate (e.g. cross-session multi-agent collaboration with shared write surface — Agent Teams maturing out of experimental), **or** a Cantrip user reports concrete frustration mapping onto a recommendation rejected in Phase 36 | Not fired | Source repo (`shanraisshan/claude-code-best-practice`) updates often; current recommendations triaged April 2026 |
| 72.3 (Provider roles) | Quantified benchmark of local EmbeddingGemma snap vs Voyage on the cantrip docs index, deciding whether to default the local snap or keep it a power-user opt-in | Target run 2026-05-11 (snap has bedded in ~2 weeks), **or** a user reports cost concerns with Voyage on a real `@docs` workload, **or** Voyage rate-limit / outage forces an opt-in fallback path | Not fired | Script lives at `scripts/embed_benchmark.py`; emits `design/EMBED_BENCHMARK.md`. Default-to-local trigger: top-3 URL overlap ≥ 70% AND wall-clock within 3× of Voyage. Token counts not captured today — would need `--json` on `cantrip docs index` first |

## Resolved deferrals

*(none yet — move "fired" rows here when the follow-up phase lands,
keep one line per row for traceability.)*

## Sweep procedure

1. Re-grep `ROADMAP.md` and `ROADMAP_ARCHIVE.md` for the markers
   listed in Phase 84.1: `Deferred:`, `defer pending`, `revisit when`,
   `re-open when`, `deferred follow-up`, `follow-up phase`.  Diff the
   hits against the table above and add any new rows.
2. For each existing row, re-evaluate the trigger column.  Three
   buckets: *trigger fired* (open a follow-up phase or task; link it
   in *Notes*; move the row to "Resolved"), *trigger not fired*
   (refresh the trigger wording if stale), *no longer relevant*
   (delete the row with a one-line note in this section).
3. Stamp the *Last audit* and *Next audit due* dates at the top of
   this file.
4. Confirm or refresh the `/schedule` reminder for the next sweep.
