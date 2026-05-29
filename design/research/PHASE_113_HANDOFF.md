# Phase 113 — Session Handoff

**Status as of this handoff** — branch `refactor/phase-113-1-split-core`, HEAD `b9fc001`,
working tree has exactly one untracked file: `src/cantrip/tui/confirmations.py` (a 700-line
draft for 113.6, not yet wired in). `app.py` is unmodified vs HEAD. The branch is
`make check`-green at HEAD.

> ⚠️ Before doing anything: run `git status` and `make check`. Confirm HEAD is `b9fc001`,
> the only dirty path is `?? src/cantrip/tui/confirmations.py`, and `make check` exits 0.
> If not, reconcile against this document before continuing.

---

## What landed this session (all committed, all green at the time)

The branch carries Phase 113 work on top of `main`. Commit subjects (hashes will differ if
the branch was rebased again):

- **113.1 — split `agent/core.py`** into 5 composed services, one commit each:
  `UsageTracker`, `ToolBuilder`, `RepoMapService`, `MessageHistory`, `ProviderManager`
  (modules `src/cantrip/agent/{usage_tracker,tool_builder,repo_map_service,message_history,provider_manager}.py`).
  Pattern: service holds `self._agent` back-reference; **state stays on `CantripAgent`**;
  each method remains on the agent as a thin delegating wrapper, so the public API and all
  tests are unchanged. `core.py` 3924 → ~3508 lines. (Partial against exit-criterion: core
  is still >1500 lines; only these 5 extractions were in scope.)
- **113.2 — split `agent/tools/juju.py`** (2720 lines) into `juju/` subpackage:
  `_common, lifecycle, relations, runtime, secrets, charm_sync, cli_passthrough`. All 24
  tool classes re-exported from `juju/__init__.py`; test patch strings repointed to
  `cantrip.agent.tools.juju._common.<name>`.
- **113.3 — split `agent/tools/publishing.py`** (2242 lines) into `publishing/` subpackage
  (`_common, icon, diagram, readme, charmcraft, docs_scaffold, design_decisions,
  troubleshooting`). 8 tool classes + public helpers re-exported; charmcraft
  `subprocess`/`shutil` patch strings repointed to `…publishing.charmcraft.<name>`.
- **113.4 — group flat `agent/` modules (PARTIAL)** — 8 named groups landed:
  `race, context, git, safety, runtime, policy, watcher, skills_runtime`. Top-level flat
  modules under `agent/` dropped 57 → 26. **Still open** (see below).
- **113.8 — split `design/`** — 10 active-contract docs stay in `design/`; 36 point-in-time
  research/audit/survey docs moved to `design/research/`. Cross-dir links + source-code refs
  to `design/UPSTREAM_AUDIT.md` repointed. CHANGELOG.md and ROADMAP_ARCHIVE.md left as-is
  (historical records). CLAUDE.md "Reference Documents" section updated.
- **2 bug fixes** found en route:
  - `fix(design)`: H1 document title was shadowing `##` content sections in
    `parse_design_from_result` (pre-existing on `main`; was failing a Hypothesis property
    test). Fix in `src/cantrip/agent/design.py` `_extract_heading_sections` — H1 is now a
    boundary, not a retrievable section.
  - `fix(skills)`: after the skills_runtime move, `_DEFAULT_SKILLS_DIR` in
    `agent/skills_runtime/skills.py` needed one more `.parent` (module went a level deeper);
    folded into the skills_runtime commit.

---

## IN PROGRESS: Phase 113.6 — TUI confirmation orchestration

**User explicitly chose the "full extraction" approach** (state moves into the coordinator,
not just method bodies; dispatch table replaces if/elif chains).

### What exists
`src/cantrip/tui/confirmations.py` (untracked, 700 lines, **lints clean, imports OK**) defines
`ConfirmationCoordinator(app)`. It already contains:
- State attributes: `pending_confirm_id`, `pending_pr_branch`, `pending_maintenance`.
- Routing entry points: `present_for_blocked_task(task)` (prefix→presenter dispatch) and
  `handle_pending_response(message)` (prefix→handler table, returns bool).
- All 19 cluster methods, moved verbatim from `app.py` with `self.` → `self._app.` for
  app-owned services and `self._pending_*` → `self.<state>`:
  `_present_design_questions, _on_questions_answered, _complete_design_confirmation,
  _offer_repo_bootstrap, _present_bootstrap_confirmation, _handle_bootstrap_response,
  _handle_pr_response, _offer_maintenance_continuation, _offer_retriage,
  _handle_maintenance_response, _handle_push_response, _present_push_confirmation,
  _present_race_confirmation, _handle_race_response, _handle_triage_response,
  _present_next_pending_triage, _present_triage_confirmation,
  _present_improvement_confirmation, _complete_improvement_confirmation`.

### The app.py wiring (was applied, then reset by the crash — REDO it)
The exact diff that was working before the crash (verified to apply cleanly). Re-apply these
edits to `src/cantrip/tui/app.py`:

1. **Remove** the now-unused import `from cantrip.agent.planner import IMPROVEMENT_CONFIRM_BASE`
   (it moves into confirmations.py). Keep `BOOTSTRAP_CONFIRM_PREFIX, PUSH_CONFIRM_PREFIX`,
   `RACE_CONFIRM_PREFIX`, `TRIAGE_CONFIRM_PREFIX` only if still referenced elsewhere in app.py
   after the cluster is removed — check with grep; if not, remove them too (ruff will flag
   unused).
2. **Add** import: `from cantrip.tui import confirmations` (alphabetical, before
   `from cantrip.tui.actions import chat as chat_actions`).
3. In `__init__`, **replace** the three state lines
   (`self._pending_confirm_id = None`, `self._pending_pr_branch = None`,
   `self._pending_maintenance = None`) with:
   ```python
   self._confirmations = confirmations.ConfirmationCoordinator(self)
   ```
   (keep `self._bootstrap_offered = False` — it stays on the app; coordinator reads it via
   `self._app._bootstrap_offered`).
4. **Add property bridges** right after `__init__` (before `_fatal_error`) so the 109 test
   references that read/set `app._pending_*` keep working:
   ```python
   @property
   def _pending_confirm_id(self) -> str | None:
       return self._confirmations.pending_confirm_id
   @_pending_confirm_id.setter
   def _pending_confirm_id(self, value: str | None) -> None:
       self._confirmations.pending_confirm_id = value
   # …same for _pending_pr_branch and _pending_maintenance
   ```
5. In `_on_bus_task_updated` (the CONFIRM+BLOCKED branch, ~line 827–850), **replace** the
   `self._pending_confirm_id = task_id` + if/elif presenter chain with:
   ```python
   task = self._agent.work_queue.get_task(task_id)
   if task is None:
       self._pending_confirm_id = task_id
       return
   self._confirmations.present_for_blocked_task(task)
   ```
   (Note: `present_for_blocked_task` sets `pending_confirm_id` itself.)
6. In `on_input_submitted` (~line 1692–1718), **replace** the 6-branch pending-confirmation
   if-chain with:
   ```python
   if self._confirmations.handle_pending_response(message):
       return
   ```
7. **Delete the 19-method cluster** from app.py: from the `# -- Design questions flow …`
   comment (currently ~line 989) through the end of `_complete_improvement_confirmation`
   (just before `# -- Watcher integration …`, ~line 1582). Keep the
   `# -- Watcher integration` comment and everything after.
8. **`_offer_repo_bootstrap`** has one external caller in app.py (`self._offer_repo_bootstrap()`,
   was ~line 2053). Repoint it to `self._confirmations._offer_repo_bootstrap()`.

### The test rewrites (this is the bulk of the "full extraction" work)
~203 references across 5 files: `tests/unit/tui/{test_tui_actions,test_tui_confirmations,
test_tui_dispatch,test_tui_input_dispatch,test_tui_pr_maintenance}.py`.

- **State reads/sets** (`app._pending_confirm_id` ×54, `_pending_maintenance` ×42,
  `_pending_pr_branch` ×13): these KEEP WORKING via the property bridges in step 4 — **do not
  rewrite them** unless you decide to drop the bridges (the user picked "full extraction" but
  the bridges are the pragmatic way to satisfy it without touching 109 sites; if a reviewer
  insists state access also move, rewrite `app._pending_X` → `app._confirmations.pending_X`).
- **Method calls** (`app._handle_*_response`, `app._present_*_confirmation`, etc. — ~80 refs):
  these WILL break because the methods no longer exist on the app. Rewrite
  `app._handle_maintenance_response(...)` → `app._confirmations._handle_maintenance_response(...)`,
  and likewise for every `_present_*`, `_handle_*`, `_offer_*`, `_on_questions_answered`,
  `_complete_*`. A mechanical sed per method name is safe (the names are distinctive).

### Verify
`make check` must pass. The TUI tests use Textual's `pilot`/`App.run_test()`; they construct
a real `CantripApp`, so the coordinator gets built in `__init__`. Watch for:
- Any test that monkeypatches `app._present_X` / `app._handle_X` (setattr) — those must now
  patch `app._confirmations._present_X`.
- `IMPROVEMENT_CONFIRM_BASE` routing: it's only used inside `present_for_blocked_task` now.

### COMMIT
One commit: `refactor(tui): extract ConfirmationCoordinator from app.py (Phase 113.6)`.
End the message with exactly:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
Then mark 113.6 done in ROADMAP.md (`### 113.6` checkboxes → `[x]` + a brief "Done." note
matching the style of the 113.1/113.2 completion notes already in the file).

---

## Phase 113 — what remains open

- **113.4 (finish)** — exit-criterion (b) wants ≤~15 top-level files under `agent/`; currently
  26. Candidate further groups: the 5 Phase-113.1 service modules; a session/persistence
  cluster (`store, persistence, snapshots, session_preview, audit, cache_monitor`); a workflow
  cluster (`checks, flows, recipes, ralph`). PLUS the **controller-pattern decision** (the
  `X.py`+`X_controller.py` pairings: executor, watcher, arena, triage, mcp — pick keep /
  collapse-to-`controllers/` / merge, apply uniformly, document in CLAUDE.md).
- **113.5 — `slash.py` registry refactor** (2047 lines → dispatch table + per-family handler
  modules `commands/session.py`, `commands/agent_modes.py`, `commands/review.py`).
- **113.6 — TUI confirmations** (in progress, see above).
- **113.7 — top-level flat modules in `src/cantrip/`** (decision: `cli/` package vs flat
  convention; document in CLAUDE.md). Decision-first, low churn.
- **113.9 — `cookbook/`/`demos/`/`examples/`/`bundles/`** unification policy. Decision-first.
- **113.10 — move `inference-snaps/` out of repo path.** USER-COORDINATED — do not start
  without the user driving the host↔VM mount cutover.

---

## Hard-won process lessons (READ THIS — they caused most of the churn)

1. **The pre-commit hook only lints staged files — it does NOT run tests.** A successful
   `git commit` does NOT mean `make check` passes. **Run `make check` (expect RC 0) before
   every commit.** I committed on a red tree three times this session by trusting the commit.
   (Saved as memory `feedback_precommit_not_full_suite.md`.)
2. **`bundles/canonical-skills-juju/**` is GENERATED** by
   `scripts/build_juju_skills_bundle.py` and guarded by `test_bundle_has_no_drift`. Never
   hand-edit it; edit the generator (or source skill) and run `make juju-skills-bundle`.
3. **Some failures are Hypothesis property tests** whose counterexample is found
   intermittently — a green run earlier doesn't guarantee a later green run. The design-parser
   bug surfaced this way.
4. **Prefer sequential single tool calls for edits.** Parallel Bash/Edit batches that share
   computed line numbers desync when an earlier call changes the file — this caused the crash
   recovery mess. Re-Read immediately before each Edit.
5. **For module-move refactors with test patch strings**, the working recipe was: `git mv`
   into the new package, then a two-pass rewrite script (pass 1: dotted
   `cantrip.agent.<mod>` → `cantrip.agent.<group>.<mod>` across all tracked .py; pass 2: split
   `from cantrip.agent import a, <mod>, b` grouped imports). Pass 1 MUST run before pass 2 so
   pass-2 output isn't re-mangled. Watch for a module name that equals its group name
   (`race`/`race`) — order longest-first and anchor the regex.
6. If a red commit slips onto an unpushed branch, fold the fix with `fixup!` +
   `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash <base>` (the user has OK'd
   non-interactive autosquash).
7. **Do not `git push`** — the user pushes (Claude lacks the SSH key). Don't change the git
   remote URL.

## Conventions (from CLAUDE.md — non-negotiable)
UK English; `import module` not `from module import name` (except type-only under
`TYPE_CHECKING`); modern `str | None`; dataclasses not Pydantic; type checker is `ty` not
mypy; never catch bare `Exception`; comments are full sentences explaining *why*; `make unit`
for the full suite (parallel), not raw `uv run pytest`.
