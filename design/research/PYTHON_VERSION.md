# Python Version — Modernisation Findings

> Output of the `py315-modernise` worktree spike (May 2026).
> This is a research document, not a design.  It records the
> question (should Cantrip move off Python 3.12?), what a 3.13
> migration actually looked like in tree, and the verdict
> (skip 3.13; revisit when 3.14 or 3.15 is the target).

## TL;DR

- Cantrip currently pins `requires-python = ">=3.12"`.  Bumping to
  3.13 buys three concrete things: `pathlib.PurePath.full_match`
  (lets us delete two hand-rolled glob matchers), `asyncio.Queue.shutdown`
  (cleaner watcher teardown), and `itertools.batched(..., strict=...)`
  (a parameter, not a function — `batched` itself is 3.12).
- The total payoff is roughly **80 lines deleted** across
  `agent/checks.py` and `agent/skills.py`, plus a 3-line behaviour
  improvement in `agent/watcher.py`.  Nothing in that list fixes
  a bug or unblocks a feature on the roadmap.
- The cost is a floor bump for everyone running Cantrip itself
  (not the charms it generates — those follow the charmcraft base,
  unrelated).  Small cost, but small win on the other side.
- **3.14** is the version with features that would actually let us
  delete *machinery*, not just helpers: PEP 649 deferred annotations
  removes the `from __future__ import annotations` dance and makes
  `inspect.get_annotations()` cheap, and PEP 750 t-strings replace
  the prompt template-injection guard with a typed primitive.
- **3.15** brings free-threaded mode out of "officially supported but
  optional" into the default story, which matters if we ever take the
  watcher / subagent loop multi-threaded.
- Recommendation: hold the floor at 3.12 until either
  (a) we want PEP 649 / t-strings badly enough to require 3.14, or
  (b) free-threading becomes load-bearing and we jump to 3.15.
  A 3.13-only stop is not worth the ecosystem churn for the wins on
  offer.

## What the spike changed

Branch `worktree-py315-modernise` carries a working 3.13 migration.
The diff is small and confined to four source files plus config:

| File | Change | LOC |
|---|---|---|
| `pyproject.toml` | `requires-python` 3.12→3.13; ruff target `py312`→`py313`; ty `python-version` 3.12→3.13; classifiers gain 3.14 | +3/−2 |
| `.python-version` | `3.12` → `3.13` | +1/−1 |
| `src/cantrip/agent/checks.py` | Delete `_recursive_glob_match` (~50 LOC regex translator); `_matches_globs` calls `PurePosixPath.full_match` | +5/−59 |
| `src/cantrip/agent/skills.py` | Delete `_segments_match` (~25 LOC recursive helper); `_glob_matches` calls `PurePosixPath.full_match` with one zero-segment workaround for trailing `/**` | +9/−27 |
| `src/cantrip/agent/watcher.py` | Add `self._queue.shutdown()` to `EventWatcher.stop()` so concurrent `dequeue`/`get` waiters wake | +3/−0 |
| `src/cantrip/docs_index/index.py` | Replace local `_batched` helper with `itertools.batched(..., strict=False)` | +6/−12 |
| `tests/unit/agent/test_conditional_guidance.py` | Drop `_segments_match` import; one assertion rewritten via the public matcher | +5/−2 |
| `uv.lock` | cp312 wheel rows removed | −229 |

**Total source delta: ~80 LOC removed, ~25 added.**  None of the
removed code was buggy; the hand-rolled glob matchers had per-segment
unit tests that all kept passing against the `full_match` rewrite.
This is a cosmetic refactor, not a behaviour fix.

## Per-feature evaluation

### `pathlib.PurePath.full_match` (3.13+)

**What it does.** Glob-match a path against a pattern with full
`**` semantics (zero-or-more segments), so `tests/integration/**`
matches both `tests/integration/foo.py` and `tests/integration/`.
Same semantics zsh and git use.

**Where Cantrip needed it.** Two places.  `agent/checks.py` matches
file paths against scope globs to decide whether a check runs;
`agent/skills.py` matches against frontmatter `globs:` to decide
whether a skill is conditionally surfaced.  Both predate 3.13 and
hand-rolled their own segmenting (`agent/checks.py` translates the
pattern to a regex; `agent/skills.py` walks segments recursively).

**Verdict.** Real but small.  The hand-rolled implementations are
~80 LOC and well-tested.  Replacing them with stdlib reduces surface
area and makes the semantics canonical, but the bug rate on those
helpers has been zero.  Wait — they will retire themselves the
moment we cross to 3.13 for any other reason.

**Subtlety.** `full_match("a/**")` does *not* match the path `"a"`
itself (the trailing `**` requires at least one extra segment).
The `agent/skills.py` rewrite carries an explicit fallback for that
zero-segment case, which is what the old `_segments_match` got
right in two lines.  Net code removed shrinks by that fallback.

### `asyncio.Queue.shutdown` (3.13+)

**What it does.** Signals consumers blocked on `Queue.get` that the
producer is done; pending and future `get`s raise `QueueShutDown`
once the queue drains.

**Where Cantrip needed it.** `EventWatcher.stop()` cancels the Loki
poller but leaves any concurrent `dequeue`/`get` waiters parked
until the next event arrives or they're cancelled externally.
`shutdown()` lets `stop()` end the read side cleanly without the
caller needing a sentinel or a separate cancel signal.

**Verdict.** Genuine improvement — the only diff in the spike that
isn't a refactor.  Today the absence isn't a bug because the watcher
shuts down via task cancellation, but the explicit queue-close path
is the right primitive.  Three lines.  Doesn't justify a floor bump
on its own.

### `itertools.batched(..., strict=True)` (3.13+)

**What's new in 3.13.** `batched` itself shipped in 3.12; what 3.13
adds is the `strict=` keyword (raise on a partial trailing batch).
The spike uses `strict=False`, which is the existing 3.12 behaviour.

**Verdict.** Wash — we could call `itertools.batched(...)` today on
3.12 and get the identical runtime behaviour.  The spike's `strict=False`
is documentation, not a feature.  Drop this row from the case for
3.13.

### Things 3.13 ships that Cantrip doesn't use

- **`copy.replace()`** — generic shallow-replace.  Our dataclasses
  use `dataclasses.replace`, which already exists.
- **Improved REPL** — interactive only; doesn't reach a CLI agent.
- **Experimental JIT** — opt-in, off by default; would not affect
  Cantrip's runtime characteristics in any benchmark we have.
- **Free-threaded build (PEP 703)** — experimental in 3.13, supported
  in 3.14, not the default in either.  Not load-bearing yet.
- **Removed legacy modules** (`cgi`, `crypt`, `imghdr`, …) — Cantrip
  imports none of them.

## What 3.14 buys that 3.13 doesn't

Released October 2025; on PyPI as `python_requires=">=3.14"` since.

- **PEP 649 — deferred evaluation of annotations** is the headline.
  Cantrip's source is sprinkled with `from __future__ import annotations`
  to make type hints free at import time and to allow forward
  references.  PEP 649 makes that the default for all annotations
  *and* repairs `inspect.get_annotations()` so it returns real
  objects on demand instead of strings.  Concrete impact:
  - Drop the `from __future__ import annotations` boilerplate
    project-wide (~80 files).
  - Any reflective code that walks dataclass fields or function
    signatures (the tool-registration layer in `design/TOOLS.md`,
    the prompt-frontmatter loader in `design/PROMPTS.md`) stops
    needing `typing.get_type_hints` workarounds.
- **PEP 750 — template strings (t-strings)** is the second headline.
  `t"…{value}…"` produces a `string.templatelib.Template` carrying
  the literal segments separately from the interpolated values.
  Concrete impact for Cantrip:
  - The template-injection guard described in `design/PROMPTS.md`
    (which exists because Jinja2 prompt templates can be smuggled
    user content) becomes a typed primitive: literal segments come
    from us, interpolated segments come tagged with their source.
  - Same primitive helps any LLM/SQL/shell interpolation we add
    later, and gives ruff a real anchor to lint against.
- **PEP 765** — `return`/`break`/`continue` in `finally` is now a
  `SyntaxWarning` and on track for `SyntaxError`.  Costs nothing.
- **PEP 758** — bare `except`/`except*` without parens.  Minor
  ergonomics.
- **Free-threaded build officially supported** (PEP 779).  No longer
  flagged experimental, still not the default; means we can opt in
  without a compatibility caveat in the docs.
- **`asyncio` performance work** — typically 5–15 % wins on the
  event loop hot path; relevant to the watcher and the subagent
  scheduler.

3.14 is the version where the migration deletes machinery rather
than helpers.  That's the bar a floor bump should clear.

## What 3.15 adds on top

Scheduled for October 2026 (about five months out from the date on
this doc).  Most of what's on the menu is finishing work:

- **Free-threaded mode is the default story for new code.**  Wheels
  start shipping `cp315t` variants as a matter of course; library
  ecosystems consolidate around it.  If we ever take the
  watcher/subagent loop genuinely multi-threaded, this is the
  version that makes that a one-line change instead of a porting
  project.
- **Removals of long-deprecated APIs** — `asyncio.iscoroutinefunction`
  on partials, `EnumType.__call__` value coercion, etc.  Cantrip
  isn't on the list of casualties as far as the audit could tell.
- **Sub-interpreters mature** (PEP 734 landed in 3.13 stdlib; 3.15
  is when the surrounding tooling — debuggers, profilers, the
  monitoring API — catches up).  Possibly relevant if we ever
  isolate skill execution from the main loop.

3.15 is the version to skip to *if* free-threading is going to be
load-bearing for us.  If it isn't, 3.14 is the right stop.

## The cost side

A floor bump excludes anyone whose `python` is older than the floor,
full stop.  Three constituencies:

1. **Cantrip developers and CI.**  uv handles toolchain installs;
   GitHub Actions ships 3.13 and 3.14.  Negligible.
2. **End users running `cantrip` from their machine.**  Distros
   matter here.  Ubuntu 24.04 LTS ships 3.12, 26.04 LTS ships 3.14;
   Debian Trixie ships 3.13.  Bumping to 3.13 cuts off 24.04 LTS
   users (the largest installed base).  Bumping to 3.14 reaches
   parity with 26.04 LTS.  Bumping to 3.15 will cut off some of
   them again briefly.
3. **The charms Cantrip generates.**  Unrelated.  The charm's
   Python version is governed by the charmcraft base
   (`ubuntu@24.04` → 3.12, `ubuntu@26.04` → 3.14), not Cantrip's.
   Generated code is independent of the tool that generates it.

The user-side cost is the binding one.  Bumping to 3.13 *now* hits
the largest LTS cohort for benefits worth ~80 LOC and three lines
of behaviour change.  Bumping to 3.14 *later* hits a much smaller
cohort and unlocks PEP 649 + t-strings.  The payoff curve clearly
favours waiting.

## Recommendation

1. **Do not merge the `py315-modernise` spike as-is.**  Park the branch.
   Tag it so we can resurrect the glob and watcher diffs the day
   we cross the floor for an unrelated reason.
2. **Hold `requires-python = ">=3.12"`** until a feature on the
   roadmap actively wants 3.14 (most likely the prompt-template
   guard rewrite or a reflective tool-registration cleanup).
3. **When the bump happens, jump to 3.14, not 3.13.**  The 3.13
   wins fall out for free at that point; the 3.14 wins are the
   reason to move.
4. **Reassess 3.15 around its release** (October 2026) for
   free-threading specifically.  If by then the watcher or the
   subagent dispatcher is contention-bound, 3.15 is the right
   target; otherwise 3.14 stays the floor for another cycle.

## Reusable bits in the spike branch

If we do bump later, these patches drop in unchanged:

- `agent/checks.py::_matches_globs` → `PurePosixPath.full_match`
  rewrite, removing `_recursive_glob_match`.
- `agent/skills.py::_glob_matches` → `PurePosixPath.full_match`
  rewrite (with the trailing-`/**` zero-segment fallback),
  removing `_segments_match`.
- `agent/watcher.py::EventWatcher.stop` → add `self._queue.shutdown()`.
- `docs_index/index.py` → swap `_batched` for `itertools.batched`.
  This one we can do today on 3.12; pull it out of the branch and
  ship it independently.

The `pyproject.toml`, `.python-version`, and `uv.lock` parts of the
spike are throwaway; recreate from scratch when the floor moves.
