---
name: charm-migration
description: Migrating legacy charms (reactive framework, StoredState, Harness, fetch-libs) to modern ops patterns
---

# Charm Migration

Use this skill when modernising an existing charm whose code still relies on
any of the pre-ops legacy patterns: the reactive framework, `StoredState`,
`ops.testing.Harness`, or `charmcraft fetch-libs` for libraries that now live
on PyPI. This skill is the umbrella workflow; the `harness-migration` skill
covers the test-file half in depth, and the `charm-library` skill covers
authoring a new library (useful when a `charmlibs-*` package doesn't yet
exist for something you need to replace).

## When to load

- The `charm_audit` tool reports `DEP001` (StoredState), `DEP002` (Harness),
  `DEP004` (reactive framework), or `LIB001`/`LIB002` (fetch-libs imports).
- You are running under `cantrip run --improve <legacy-charm>/` and the
  modernise-code task has started.
- A user asks "migrate this reactive charm to ops" or "drop StoredState".

For a charm that only needs Harness → Scenario in the tests and no other
migration, load the more focused `harness-migration` skill instead.

## Inventory before editing

Run `charm_audit` first — it delegates to charmlint and returns the exact
set of migration types that apply. The diagnostic IDs map onto this skill
as follows:

| Rule ID | What it flags | Section below |
| --- | --- | --- |
| `DEP001` | `StoredState` usage | StoredState → modern storage |
| `DEP002` | `from ops.testing import Harness` | Harness → Scenario |
| `DEP003` | `self.framework.breakpoint()` | Small replacement (see section) |
| `DEP004` | `charms.reactive` import or `@when` / `@when_not` / `@when_any` / `@when_all` / `@hook` decorator | Reactive → ops |
| `LIB001` | fetch-libs import with a known PyPI replacement | fetch-libs → PyPI |
| `LIB002` | fetch-libs import with no PyPI replacement yet | fetch-libs → PyPI (stay-put case) |

If you can't run the tool, grep for the four anchors yourself:

```
\bStoredState\b|\bfrom\s+ops\.testing\s+import\s+Harness\b|from\s+charms\.reactive\b|@(?:when|when_not|when_any|when_all|hook)\(
```

Migrate one pattern (and ideally one file) at a time; re-run the audit or
grep between changes so you can see the list shrink.

## Reactive → ops

The reactive framework (`charms.reactive`) is a layer-based style that
predates ops. It expresses handler execution via **flags** — decorators
like `@when('db.available')` run when all named flags are set, and
handlers `set_flag(...)` / `clear_flag(...)` to drive other handlers.
Reactive charms usually have a `reactive/` directory, a `wheelhouse.txt`,
and a `layer.yaml`.

The ops framework instead exposes a single `CharmBase` subclass that
observes Juju events directly via `framework.observe(...)`.

### Mapping decorators to observations

| Reactive | ops replacement |
| --- | --- |
| `@when('config.changed')` | `framework.observe(self.on.config_changed, self._on_config_changed)` |
| `@when('db.available')` | `framework.observe(self.on.db_relation_changed, ...)` + a `can_connect`-style guard in the handler |
| `@when_not('leadership.is_leader')` | Guard the handler body with `if not self.unit.is_leader(): return` |
| `@hook('install')` | `framework.observe(self.on.install, self._on_install)` |
| `set_flag('configured')` | Store the fact in peer-relation data (for leader-visible state) or a plain instance attribute reconstructed on every hook (for derived state) |
| `clear_flag(...)` | Delete the relation-data key or let the next reconciliation recompute |

Reactive's implicit "re-run handlers until the flag set stops changing"
pattern is replaced by an explicit `_reconcile()` method that you call
from every event handler. `_reconcile()` should be idempotent: it reads
the current config, relation data, container state, and secrets, decides
what the workload should look like, and issues the Pebble layer update
or status change needed to get there.

### Per-file workflow

1. Read `metadata.yaml` / `charmcraft.yaml` to list events the charm
   must observe (one observer per relation endpoint plus install,
   start, config-changed, stop, update-status).
2. Write `src/charm.py` with a `CharmBase` subclass, `framework.observe`
   calls in `__init__`, and a `_reconcile()` method.
3. Port each reactive handler's body into the matching event handler.
   Flags that gated the old handler become early `return` conditions on
   the new one (`if not relation.app: return`).
4. Port `when_any` / `when_all` decorators by calling `_reconcile()` from
   every contributing event handler — `_reconcile()` checks all the
   pre-conditions in one place.
5. Drop `reactive/`, `wheelhouse.txt`, `layer.yaml`. Add `src/` and a
   standard `pyproject.toml` — see the `custom-charm` skill for the
   modern repository layout.
6. Delete handlers for events the charm no longer cares about
   (`upgrade-charm` almost always collapses into `_reconcile()`).
7. Run the audit again — `DEP004` should drop off the report.

### Testing the rewrite

A reactive charm typically has no useful unit tests. Pair this migration
with new Scenario tests (see the `scenario-tests` skill) that cover:

- Each observed event reaching `_reconcile()`.
- Relation-changed with and without remote data.
- Leader vs. non-leader paths.
- Pebble not ready (for sidecar charms).

## StoredState → modern storage

`StoredState` persists attribute values across hook invocations by writing
them to the unit's local state directory. It has subtle bugs with types
other than primitives, doesn't survive pod replacement on Kubernetes
sidecar charms in all cases, and is difficult to test. Do not use it in
new code.

### The decision tree

Replace each `StoredState` attribute based on what the value **is**:

| What the value represents | Replace with |
| --- | --- |
| Derived state computable from config, relation data, and workload state on every hook | Plain instance attribute computed in `__init__` or `_reconcile()` — no persistence needed |
| Shared state other units need (e.g. "the leader has configured the shared password") | **Peer relation data** on the app databag (leader-writable, all-units-readable) |
| Shared state written by a non-leader unit (unit-visible but not leader-controlled) | Peer relation data on the unit databag |
| Sensitive state that must not appear in `juju show-unit` | **Juju secret** (created with `self.app.add_secret(...)` — see the `relation-data-design` skill for the full pattern) |
| Opaque data the charm caches for performance (e.g. a parsed manifest) | Instance attribute plus a recompute on `upgrade-charm` — don't persist |

### Example: peer relation data replacement

Old:

```python
class MyCharm(ops.CharmBase):
    _stored = StoredState()

    def __init__(self, framework):
        super().__init__(framework)
        self._stored.set_default(cluster_id=None)
```

New:

```python
class MyCharm(ops.CharmBase):
    @property
    def _peer_relation(self) -> ops.Relation | None:
        return self.model.get_relation("cluster")

    @property
    def cluster_id(self) -> str | None:
        rel = self._peer_relation
        if rel is None:
            return None
        return rel.data[self.app].get("cluster-id")

    def _set_cluster_id(self, value: str) -> None:
        rel = self._peer_relation
        if rel is None or not self.unit.is_leader():
            return
        rel.data[self.app]["cluster-id"] = value
```

Declare the peer relation in `charmcraft.yaml`:

```yaml
peers:
  cluster:
    interface: cluster-peers
```

### Example: Juju secret replacement

```python
def _ensure_admin_password(self) -> str:
    rel = self._peer_relation
    if rel is None:
        return ""
    secret_id = rel.data[self.app].get("admin-secret-id")
    if secret_id:
        return self.model.get_secret(id=secret_id).get_content(refresh=True)["password"]
    if self.unit.is_leader():
        password = _generate_password()
        secret = self.app.add_secret({"password": password}, label="admin")
        rel.data[self.app]["admin-secret-id"] = secret.id
        return password
    return ""
```

### Per-file workflow

1. List every `self._stored.<attr>` access — that set is the migration
   surface.
2. Classify each attribute against the decision tree above.
3. Replace writes first, then reads, one attribute at a time. Run
   `charm_validate` between each so unit tests catch regressions early.
4. Remove `_stored = StoredState()` and the `StoredState` import. Re-run
   the audit — `DEP001` should drop off.

## Harness → Scenario

This migration is covered in depth by the `harness-migration` skill —
load it and follow the per-file workflow there. The short form:

- `Harness(MyCharm)` → `ops.testing.Context(MyCharm)`.
- `harness.set_leader(True)` / `update_config(...)` / `add_relation(...)`
  → `ops.testing.State(leader=True, config={...}, relations={...})`.
- `harness.charm.on.<event>.emit(...)` → `ctx.run(ctx.on.<event>(...), state_in)`.
- `harness.run_action(...)` → `ctx.run(ctx.on.action(...), state)` and
  read `ctx.action_results`.
- `ops[testing]` replaces `ops-scenario`; clean up `pyproject.toml`.

Audit rule: `DEP002`. The harness-migration skill has the full detector
and event-by-event recipes.

## fetch-libs → PyPI imports

Canonical has been lifting widely-used charm libraries into PyPI under
the `charmlibs-*` namespace. When a library exists on PyPI, prefer the
PyPI version — it's tested in CI, version-pinned via `pyproject.toml`,
and does not require `charmcraft fetch-libs` to fire before every pack.

### What the audit tells you

- `LIB001` — the import has a known PyPI replacement. The diagnostic
  message quotes the PyPI package name and the new import path.
- `LIB002` — no PyPI replacement yet. Keep using fetch-libs for this
  one; the entry is informational.

### Mapping imports

Examples from the audit map (April 2026 cutoff):

| Old import | New dependency | New import |
| --- | --- | --- |
| `from charms.tls_certificates_interface.v3.tls_certificates import ...` | `charmlibs-interfaces-tls-certificates` | `from charmlibs.interfaces import tls_certificates` |
| `from charms.certificate_transfer_interface.v1.certificate_transfer import ...` | `charmlibs-interfaces-certificate-transfer` | `from charmlibs.interfaces import certificate_transfer` |
| `from charms.operator_libs_linux.v0.apt import ...` | `charmlibs-apt` | `from charmlibs import apt` |
| `from charms.operator_libs_linux.v0.snap import ...` | `charmlibs-snap` | `from charmlibs import snap` |
| `from charms.operator_libs_linux.v0.sysctl import ...` | `charmlibs-sysctl` | `from charmlibs import sysctl` |
| `from charms.operator_libs_linux.v0.systemd import ...` | `charmlibs-systemd` | `from charmlibs import systemd` |

For submodules of `operator_libs_linux` not listed above, re-check the
audit report — the list is maintained in charmlint and updated as
Canonical publishes new `charmlibs-*` packages.

### Per-import workflow

1. Add the PyPI package to `pyproject.toml` under the runtime dependency
   group (`[project.dependencies]` or the charm's equivalent).
2. Rewrite the import at the top of the consuming Python file.
3. Delete the old `lib/charms/<prefix>/v<N>/<submodule>.py` file — it
   will be re-fetched only if you leave it out of `.gitignore` and run
   `charmcraft fetch-libs` again, which is what we're trying to avoid.
4. Remove the `charm-libs:` entry for that library from
   `charmcraft.yaml` (only if it was declared there).
5. Run `uv sync` and `charm_validate` to make sure the pack still works
   and the library surface is unchanged.

For libraries with no PyPI alternative (LIB002), keep the `lib/charms/...`
layout — nothing to migrate until Canonical publishes the package. If
you maintain the charm yourself and the library is general-purpose,
consider publishing it to PyPI yourself (see the `charm-library` skill
for the publisher workflow).

## Removed: framework.breakpoint

`self.framework.breakpoint()` was removed from ops. Replace with
`breakpoint()` from the standard library (or a conditional debugger
import that only fires when running outside Juju). Audit rule: `DEP003`.

## Done criteria

- Running `charm_audit` again shows no `DEP001`, `DEP002`, `DEP003`,
  `DEP004`, or `LIB001` diagnostics (LIB002 may remain where no PyPI
  replacement exists).
- `charm_validate` passes with unit-test coverage at or above the 80%
  floor from the improvement pipeline.
- The charm packs cleanly with `charmcraft pack` (or the faster
  `quickpack` tool) with no warnings about missing libraries or
  deprecated imports.
- New or updated Scenario tests cover every event handler that was
  touched during the reactive rewrite or StoredState replacement.

## References

- `harness-migration` skill — test-file migration workflow in depth.
- `charm-library` skill — authoring a new library for fetch-libs
  replacements that need to go to PyPI.
- `relation-data-design` skill — peer relation data patterns used in
  the StoredState replacement section.
- `scenario-tests` skill — writing tests for the rewritten charm.
- Canonical documentation:
  [Migrate from the reactive framework](https://documentation.ubuntu.com/ops/latest/howto/legacy/migrate-from-reactive/),
  [Migrate unit tests from Harness](https://documentation.ubuntu.com/ops/latest/howto/legacy/migrate-unit-tests-from-harness/).
