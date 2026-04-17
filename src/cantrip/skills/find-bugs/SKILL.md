---
name: find-bugs
description: Review newly written charm code for common charm bugs before finishing a BUILD task
---

# Find Bugs

A bug-hunting pass over charm code you just wrote.  Focused on the mistakes
that recur across charms — not a general code review.  Run this alongside
`security-review` before declaring a BUILD task done.

## How to use

1. Identify the files you added or modified in this task.
2. Walk each check below against those files only (not the whole charm).
3. Report findings in the structured format at the end.  Fix HIGH issues
   before finishing; note MEDIUM and LOW.
4. Do not re-report things `charm_validate` or `ruff` already caught —
   focus on semantics, not style.

## Severity

- **HIGH** — charm will misbehave at runtime (missing status update,
  wrong hook observed, data loss).  Fix before finishing.
- **MEDIUM** — degraded behaviour or brittle logic.  Note for the user.
- **LOW** — minor correctness concerns worth flagging.

## Checks

### 1. Status handling

Every charm must end each hook in a defined status.  The common bug is a
code path that returns without updating `self.unit.status` or
`self.app.status`.

Checklist:
- [ ] `self.unit.status` is set before each `return` in a hook handler.
- [ ] `BlockedStatus` is used for missing relations / bad config, not
  `ErrorStatus`.
- [ ] `ActiveStatus` is only set when the workload is actually ready
  (Pebble service running for K8s, systemd unit active for machine).
- [ ] `MaintenanceStatus` is set at the start of long operations and
  cleared at the end.

### 2. Event observation

- [ ] Every observer is registered in `__init__`, not in a hook handler
  (observers registered at hook time fire on the *next* hook, not this one).
- [ ] No `self.framework.observe(self.on.install, self._on_install)` inside
  a method other than `__init__`.
- [ ] Config-changed handlers are idempotent — they must be safe to call
  repeatedly with the same config.
- [ ] Relation handlers check `relation.app` for None (happens briefly
  during relation-broken).

### 3. Pebble layer merging (K8s charms)

- [ ] `container.add_layer(layer_name, layer, combine=True)` — `combine`
  must be `True` if you're updating an existing layer.
- [ ] Layer changes followed by `container.replan()`, not `container.restart()`
  (replan handles both first-time start and subsequent restarts).
- [ ] Plan-diff check before `add_layer`: compare the current plan to the
  desired one and skip the add_layer if unchanged (avoids churn).

### 4. Relation data

- [ ] Writes to `relation.data[self.app]` are guarded by
  `self.unit.is_leader()` — non-leaders cannot write to app databag.
- [ ] Reads from `relation.data[relation.app]` handle the empty-dict case
  (data not yet published).
- [ ] Serialisation: non-string values must be `json.dumps`'d.  A common
  bug is `relation.data[self.app]['units'] = 3` (fails; must be `'3'`).
- [ ] Relation-broken handler does not touch `relation.data` (may be gone).

### 5. Secrets handling

- [ ] Secrets observers (`secret_changed`, `secret_rotate`,
  `secret_expired`, `secret_remove`) are registered if the charm uses
  secrets.
- [ ] `secret.get_content(refresh=True)` is called in `secret_changed`,
  otherwise you read stale data.
- [ ] `owner="app"` (not `"unit"`) for secrets that survive unit churn.

### 6. Storage

- [ ] `storage-attached` / `storage-detaching` handlers exist if
  `charmcraft.yaml` declares storage.
- [ ] Storage paths are obtained via `self.model.storages['name']`, not
  hardcoded (`/var/lib/mycharm`).
- [ ] Long-lived state goes to storage, not container ephemeral paths.

### 7. Update-status

- [ ] `update-status` exists if the charm has any state that can drift
  (workload health, peer connectivity).
- [ ] It does not perform expensive checks every 5 minutes — see the
  `performance` skill.
- [ ] It sets status based on actual probes, not cached assumptions.

### 8. Actions

- [ ] Action handlers call `event.set_results(...)` (not `event.results = ...`).
- [ ] `event.fail(msg)` is called on failure; no bare raise.
- [ ] Action logs use `event.log(msg)`, visible to the user running the action.
- [ ] Long actions call `event.log` periodically so the user sees progress.

### 9. Upgrade and refresh

- [ ] `upgrade-charm` handler exists if the charm's internal state shape
  can change between versions.
- [ ] Data migrations in `upgrade-charm` are idempotent (can re-run on
  retry).
- [ ] Pebble layer changes in `upgrade-charm` use `combine=True` so they
  merge with the running layer.

### 10. Integration with COS

- [ ] `tracing` relation present on PaaS / Path B / Path C.
- [ ] `ops_tracing.setup(self)` called from `__init__` (after `super().__init__`).
- [ ] `loki-push-api` relation consumer wired up for machine charms.
- [ ] Cross-model COS: `juju offer` declared in design, not hardcoded to
  same controller.

### 11. Defensive patterns that are actually bugs

- `except Exception: pass` in a hook handler — silently swallows hook
  failures and leaves the status stale.
- `try: self.container.push(...) except ChangeError: pass` — hides
  Pebble failures; the user sees "active" while the workload is
  misconfigured.
- Catching `ops.framework.UncaughtException` — if you're catching the
  framework's own signal, you're working around a bug rather than fixing it.

### 12. Async and concurrency

- Charms are single-threaded per hook.  If you use `asyncio`, you are
  probably wrong — ops already handles the event loop.
- Do not `threading.Thread` for background work inside a hook.  The hook
  must complete within ~30 seconds; threads leak between hooks.

## Output format

```
[find-bugs] <N> HIGH, <M> MEDIUM, <K> LOW

HIGH: src/charm.py:87 — missing status update on config-changed error path
  Evidence: the `except ValueError` branch returns without setting status,
    so the unit stays in the prior status (probably Active) even though
    config is invalid.
  Fix: set BlockedStatus("invalid config: ...") before returning.

MEDIUM: src/charm.py:142 — relation data written without leadership check
  Evidence: self.relation.data[self.app]["count"] = str(n)
  Fix: guard with `if self.unit.is_leader():`.
```

If you find nothing:

```
[find-bugs] no findings
```

## When to skip

- RESEARCH or DEBUG tasks.
- Edits under 10 lines where no new control flow was introduced.
- Files that are purely tests (run the tests instead — the test output
  is a better review).

Otherwise, run it.  These bugs are the ones that reach the user as
"charm just went into Blocked and I don't know why".
