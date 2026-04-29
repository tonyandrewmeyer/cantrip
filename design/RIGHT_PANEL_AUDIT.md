# Right-Panel Audit (Phase 65)

This is the audit pass that Phase 65.1 / 65.2 of `ROADMAP.md` asks
for.  It walks the three widgets on the TUI right panel —
`TaskChecklistWidget` (`#task-checklist`), `CharmTreeWidget`
(`#charm-files`), and `MultiModelStatusWidget` (`#juju-status`) —
across every state transition the user actually sees, and lists the
specific things to fix.

The findings are *grounded*: a Pilot harness at
`tmp/audit_phase65/drive_right_panel.py` constructs each scenario,
captures both an SVG screenshot and a flat dump of every rendered
`Static` (with classes and content) under
`tmp/audit_phase65/scenarios/`.  Re-run the harness with
`uv run python tmp/audit_phase65/drive_right_panel.py` to refresh.

## Scenarios captured

| Scenario | Widget under test | Notes |
|---|---|---|
| `01_empty` | right panel | Just-mounted state, no preflight, no tasks |
| `02_preflight_running` | task-checklist | Preflight mid-run with mixed PENDING/PASSED/RUNNING |
| `03_preflight_done` | task-checklist | All preflight checks PASSED |
| `04_mid_build` | task-checklist | Preflight done + queue with ACTIVE/PENDING/DONE/FAILED/BLOCKED across categories |
| `05_mid_build_expanded` | task-checklist | Same as 04, FAILED test row expanded |
| `06_all_done` | task-checklist | Every category fully DONE — collapsed-group rows everywhere |
| `07_mm_empty` | juju-status | No dev model, no COS — "Not connected / Not deployed" |
| `08_mm_dev_only` | juju-status | Dev model attached, no COS |
| `09_mm_dev_cos_collapsed` | juju-status | Dev model + COS collapsed to one-line summary |
| `10_mm_dev_cos_expanded` | juju-status | Dev model + COS expanded |

## Findings

### A. ~~`TaskChecklistWidget` accumulates stale children on every refresh~~ — **withdrawn**

The first revision of this audit claimed `_refresh_display`'s
mismatched `remove_children` (async) + `mount` (sync) pair leaked
stale rows.  **This was a false alarm.**

Re-running the harness with the bug suspect reverted, the dump for
`04_mid_build` shows clean output:

```
<Static [task-collapsed.task-done.task-row]> '✓ Preparing environment · ready'
<Static [task-header]> 'In progress'
…
```

The "duplicate" group rendering came from the harness adding a second
`add_preflight_group("Preparing environment", …)` on top of the one
the app's `_start_prepare` registers in its own `on_mount`.  The
widget was correctly rendering both groups.

The reason there is no real leak: Textual's `Vertical.mount` is
synchronous against `self.children` (the new widget is in the list
immediately) but the layout/CSS work is queued.  The next
`remove_children` call walks `self.children` and detaches every node
present — including any newly-mounted ones whose layout hasn't
caught up.  Order is preserved through the message queue, so the
final state converges to whichever refresh ran last.

The harness is fixed (`tmp/audit_phase65/drive_right_panel.py`
calls a `_eager_idx` helper that reuses
`pilot.app._prepare_group_idx`) so this finding does not recur on
re-runs.

### B. `_format_detail` double-indents under `.task-detail`

`_format_detail` prefixes every line with two spaces (`  Category:
…`), and the CSS class `task-detail` already sets `margin-left: 2`.
Net effect: 4-column indent for the detail block, while the parent
row sits at 0.  In `05_mid_build_expanded`:

```
<_TaskRow [task-failed.task-row]> '✗ Test · Run scenario unit tests'
<Static [task-detail]> "  Category: test\n  Status: failed\n  …"
```

Drop the leading two spaces from `_format_detail` and let the CSS
margin do the work.

### C. Pinned section is visually indistinguishable from a category section

The "In progress" header uses the same `task-header` class and the
same divider as "Research", "Build", etc.  Reading top-to-bottom, the
user has no signal that the first block is the *important* live one;
it just looks like another category.  In `04_mid_build` the pinned
block ends and "Research" begins with the same visual weight.

**Fix:** add a distinct CSS hint for the pinned header.  Either
heavier emphasis (e.g. `color: $accent` + reverse style on the
header), or replace the header+divider with a single emphasised
"In progress" row that doesn't look like a category divider.

### D. Pinned rows include `Category · ` prefix; category rows don't

In the pinned section a row reads `⟳ Build · Generate charmcraft.yaml`,
but the same task in its category section reads `⟳ Generate
charmcraft.yaml`.  The category prefix in pinned is *needed* because
otherwise you can't tell which sub-system is active — but the form
collides if a future change moves a task in/out of pinned.

**Fix:** drop the `Category · ` prefix from pinned rows, and instead
make the pinned section header carry the active-category set
(e.g. `In progress · Build, Deploy, Test`).  Single source of truth
for category context, single rendering rule for rows.

Alternative: lean the other way and *always* show category in row
text.  Worse, because the category-section header already says it.

### E. Collapsed-group rows duplicate the category header

For a fully-DONE category we currently render:

```
<Static [task-header]> 'Research'
<Static [task-divider]> '────────────────────'
<_CollapsedGroupRow> '✓ 2 tasks done (click to show)'
```

Three lines — header, divider, summary — for one piece of
information.  The summary already says nothing about *which*
category it belongs to.

In `06_all_done` (every category done) this turns the entire pane
into 5 × 3 = 15 lines of mostly-decoration.

**Fix:** when a category collapses, replace the header + divider +
summary with a single self-describing row:

```
<_CollapsedGroupRow> '✓ Research · 2 tasks done'
```

— no header, no divider, no parenthesised "(click to show)" hint
(the pointer cursor / hover state can carry that affordance, and the
parenthetical adds noise on every line).

### F. `MultiModelStatusWidget.cos_expanded` is a reactive without a watcher

`cos_expanded` is declared as `reactive[bool]` but the widget has no
`watch_cos_expanded`.  The only place expansion repaints is
`toggle_cos_expanded`, which sets the attribute *and* calls
`_refresh_display` directly.  Setting the attribute by any other
path is a silent no-op — the existing test
`test_cos_status_click_toggles_expansion` happens to call
`toggle_cos_expanded`, so the gap is not caught.

**Fix:** add `watch_cos_expanded` that calls `_refresh_display`,
and let `toggle_cos_expanded` rely on the watcher (single source of
truth) — or drop the reactive in favour of a plain attribute.

### G. Multi-model pane wastes 1fr when no model is connected

`07_mm_empty.tree.txt`:

```
<Static [section-title]> 'Dev Model'
<Static [collapsed-summary]> 'Not connected'
<Static [section-title]> 'COS Model'
<Static [collapsed-summary]> 'Not deployed'
```

In the right-panel layout `#juju-status` claims `height: 1fr` —
which gets the entire bottom half of the panel even when the only
content is "Not connected / Not deployed".  Combined with finding A
above, the empty-state right panel feels mostly empty.

This is the Phase 65.2 question: what should this pane *show*?

**Decision** (proposed):

- **No models connected** → hide the pane entirely.  The status bar
  already carries `● COS healthy` / dev-model name when the user
  cares; the right-panel block does not need to repeat "Not
  connected" with vertical real estate.
- **Dev only** → keep current expanded view (the dev model is the
  primary work surface; users want to see app/unit health here).
- **Dev + COS** → keep the collapsed-COS form with its
  one-line summary (`6 apps · 1 blocked, 1 waiting, 4 active · 4
  offers`).  The summary is genuinely informative now.  Click to
  expand on demand.
- **COS expanded** → identical to today.

Implementation shape:

1. `MultiModelStatusWidget` becomes invisible (`display: False`)
   while `dev_status` and `cos_status` are both `None`.
2. Once a model attaches, the pane becomes visible; once a model
   disconnects (back to all-None), it goes back to hidden.
3. Drop the "Dev Model / Not connected" / "COS Model / Not
   deployed" rows entirely — they only ever appeared in
   pre-connect mode, which we now hide outright.
4. Add a watcher on `cos_expanded` (finding F) so the click handler
   is the only call site mutating it.

This is a *trim* rather than a retire.  The full retire ("move all
detail to /status modal, replace with a one-line strip") is a
larger redesign; the trim above is enough to make the pane earn its
space without rebuilding.  If the trimmed version still feels
empty after a few real sessions, the retire path is the next step.

### H. Indent strategy is inconsistent across the widget

Three different indent strategies coexist in `tasks.py`:

- `_format_detail` — leading `  ` literal spaces in the string.
- `_subagent_line` — leading `  ` literal spaces in the string.
- `.task-detail` — `margin-left: 2` in CSS (and the lines also have
  leading spaces, see B).

A future widget refactor should pick one — almost certainly CSS
margins — and remove the leading-spaces hack.  This is followup
cleanup; not a separate fix-now finding.

## Out of scope for Phase 65

- The **CharmTreeWidget** is fine as-is.  It refreshes on a 3 s
  timer, hides noise directories, and a click opens the file detail
  screen.  No action.
- The right panel's task data model (categories, statuses, pinned
  rules) stays as it is — Phase 65 is a review-and-fix on rendering
  only.
- A **Web-UI counterpart** of these fixes follows in a later phase
  once the TUI answers settle.

## Phase 65.3 — CSS notes (after the widget fixes land)

Rather than design CSS now, jot what to look at after findings A–G
ship:

- `#task-checklist { max-height: 50% }` is currently fighting
  `TaskChecklistWidget { max-height: 50% }` (DEFAULT_CSS).  Pick
  one home.
- `#charm-files { height: 1fr; max-height: 50% }` — the `1fr` is
  redundant when `max-height` already caps it.
- `#juju-status { height: 1fr }` may want to shrink to `auto` once
  finding G lands (the pane only takes the space its content needs;
  empty-pane case is hidden, not zero-height).
- The dividers between right-panel blocks are currently
  `border-bottom: solid $primary` on every block but `#juju-status`
  — once that pane is occasionally hidden, the previous block ends
  up with a dangling bottom border.  Sweep accordingly.

## Plan

Order of fixes, one commit each:

1. **E** — collapse-row simplification (biggest visual win).
2. **D** + **C** — pinned-section format and emphasis (related;
   ship as one commit).
3. **B** — `_format_detail` indent.
4. **F** — `watch_cos_expanded` watcher.
5. **G** — auto-hide multi-model pane while no models connected,
   delete dead `Not connected` / `Not deployed` rendering.
6. **65.3** — CSS sweep against the bullet list above.

Finding **A** is withdrawn (see above).
