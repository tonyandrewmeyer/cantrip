---
name: iterate-fix
description: Deploy-test-debug retry strategy — triage failures, bound retries, escalate when stuck
---

# Iterate-Fix

A formalised retry loop for the deploy → verify → test → fix cycle.  Cantrip's
autodeploy helpers already produce follow-up tasks after a failed
``BUILD``, ``DEPLOY``, or ``TEST`` run (``[Red/Green retry]``,
``[Acceptance fix]``, ``Diagnose deployment failure:``, and
``[Watcher]`` tasks).  This skill tells you *how* to handle the feedback
you receive in those follow-ups — what to fix first, when to stop, and
when to ask for help.

## When to use

Run this skill at the start of a follow-up task whose title begins with
any of:

- ``[Red/Green retry]`` — partial integration-test progress
- ``[Acceptance fix]`` — acceptance test produced a FAIL verdict
- ``Diagnose deployment failure:`` — verify-after-deploy failed
- ``[Watcher]`` — the watcher surfaced a runtime event

Or any time you are about to start a BUILD/DEBUG task that references a
prior failure.  Skip for fresh RESEARCH / PLAN / DESIGN work.

## Triage — before fixing anything

Never jump straight to code changes.  Spend the first tool call on
reading the signal.

### 1. Categorise the failure

Source each failure into exactly one bucket:

- **Environment** — concierge not ready, Juju controller missing, LXD
  not available, network flake.  These aren't charm bugs.  Check
  ``juju_status`` on the controller model (``juju status -m controller``
  when available) before touching charm code.
- **Deployment** — ``juju deploy`` failed, relation hook errored,
  ``WaitingStatus`` after five minutes.  Check ``juju_debug_log`` and
  ``juju_show_unit`` before assuming the charm code is wrong.
- **Workload** — charm deployed but workload crash-loops, HTTP 5xx,
  ``ActiveStatus`` but wrong behaviour.  Check ``loki_query`` for the
  workload logs; check ``juju_ssh`` / ``pebble`` state for container
  services.  Also scan ``juju_debug_log`` at DEBUG level for lines
  logging how many deferred events are in the queue — ops now emits a
  total-deferred count per hook.  A growing backlog (dozens, hundreds)
  almost always points at a deferred handler that never makes
  progress; fix that before chasing surface symptoms.
- **Test** — integration or acceptance tests failed.  Read the pytest
  summary, then the actual assertion, then the charm code the assertion
  exercises.  Don't edit the test.

### 2. Rank by severity

Within a category, fix in this order:

1. **Blockers** — anything leaving the unit in ``ErrorStatus`` or
   ``BlockedStatus`` (nothing else can proceed until this is gone).
2. **Crash-loops** — workload repeatedly restarting.  Fix before chasing
   less-urgent log warnings.
3. **Test failures with a clear assertion message** — concrete signal,
   usually local to one piece of code.
4. **Intermittent failures** — if something failed once but passed on
   the next run, check the retry budget before re-investigating.
5. **Warnings / cosmetic issues** — defer until the higher tiers are
   green.

## When logs aren't enough — interactive debugging

For Workload-bucket failures where ``juju_debug_log`` and
``loki_query`` leave the root cause unclear, fall back to interactive
debugging tools before guessing at fixes:

- **``ops.Framework.breakpoint()``** drops the running charm into pdb
  on the next hook firing.  Add the call in the suspect handler, fire
  the event with ``jhack utils fire`` (or wait for the natural
  trigger), then ``juju debug-code <unit>`` attaches your terminal to
  the pdb session.  Remove the breakpoint when done.
- **``debugpy``** lets you attach a remote VS Code / IDE debugger
  instead of a CLI pdb.  Add ``debugpy.listen()`` early in
  ``__init__``, set the wait flag if you want the charm to pause on
  startup, and forward the port from the unit.  See the upstream
  ops debugging how-to for the exact wiring.
- **``jhack scenario snapshot <unit>``** captures the live state
  (relations, config, secrets) so you can reproduce the failure as a
  Scenario unit test offline — often faster than re-running the full
  deployment.
- **Plain ``breakpoint()`` in a Scenario test.** ``ops.testing`` no
  longer rebinds ``sys.breakpointhook`` during ``Context.run``, so you
  can drop a ``breakpoint()`` into the charm handler and
  ``uv run pytest -s tests/unit/test_charm.py`` lands you in pdb at
  the offending line.  No deploy needed — this is the fastest
  iteration loop once the snapshot is captured.

These tools cost a deploy iteration each (except the last, which is
local) but *eliminate* guesswork — prefer them over a fourth
speculative fix attempt.

## Retry budgets

Infinite loops are the biggest risk in autonomous iteration.  Cantrip's
autodeploy helpers already prevent trivial chains (``_RETRY_PREFIX``
checks stop a retry from spawning another retry), but the strategy
inside each retry is on you.

### Per-failure attempt tracking

If the same test, hook, or status message has already failed on two
prior attempts *with fixes applied between attempts*, stop.  The next
step is not a third try with a new guess — it's asking the user.

Signals you've used your budget:

- The same pytest test ID appears as ``FAILED`` in a retry task's
  ``[Previous result (excerpt):]`` block.
- ``juju status`` shows the same unit in the same ``BlockedStatus``
  message across two consecutive attempts.
- ``loki_query`` returns the same traceback signature after a fresh
  deploy.

### Bounded overall retry count

For a *single* originating failure, never run more than three fix
attempts in an unbroken chain.  If you're on attempt four, escalate:
add a ``CONFIRM`` task asking the user what to try next.

## Exit conditions

Finish the iterate-fix cycle when *any* of these are true:

- ``juju status`` reports every app as ``active/idle`` **and** the
  originating test suite passes.
- The failure is environmental and not a charm bug (report it to the
  user and stop).
- You've hit the retry budget (three attempts on the same failure).
- The failure reproduces only intermittently and you've confirmed the
  charm code is correct on at least two consecutive green runs.

## Escalation — when to ask for help

Don't ask too early; don't press on too long.  Good triggers:

- Three attempts on the same failure with no new hypotheses.
- The failure changes shape each attempt (different tracebacks, no
  convergent pattern) — more hands help.
- A charm-library bug outside your scope (``ops``, ``jubilant``,
  ``charmcraft``) — surface the reproducer and move on.
- The fix would require modifying integration tests themselves.  The
  user owns that contract; don't renegotiate it silently.

## Structured feedback for the next iteration

When you stop — whether successful or escalating — emit a short block
the next subagent can read without re-reading the whole transcript:

```
[iterate-fix] attempt <N>/<max>: <outcome>

What failed first: <one-line summary of the earliest failure>
What I tried: <bullet list of fixes applied>
What's still broken: <what's left, if anything>
Next step (if not done): <specific tool call or user question>
```

If the loop succeeded (green status, tests pass, no warnings):

```
[iterate-fix] green on attempt <N>
```

## What this skill is *not*

- Not a replacement for ``find-bugs`` / ``security-review``.  Run those
  on any new code you write *during* the iteration.
- Not licence to ignore the user.  If they asked a question during the
  loop, answer it before continuing.
- Not a generic exception handler.  Real root-cause analysis beats
  "retry and hope" every time.
