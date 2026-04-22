---
name: charm-library
description: Authoring, versioning, testing, and publishing reusable charm libraries
---

# Authoring Reusable Charm Libraries

A **charm library** is a single Python module, shipped inside a charm, that other charms depend on — typically to implement one side of a relation interface, or to expose a common helper. When another charm runs `charmcraft fetch-libs` (or declares the lib in `charm-libs:` in `charmcraft.yaml`), Charmhub serves the file from the publishing charm's latest matching major version.

## When To Create a Library

Create a library when:

- **Two or more charms need to speak a relation interface.** The requirer side is almost always a library so consumers don't re-derive the protocol. The provider side is usually a library too, so the producing charm owns the schema.
- **You are exposing a reusable helper** that shouldn't be a full PyPI package — for example, a thin wrapper around an action, a shared topology label builder, or a status-aggregation helper.

Do **not** create a library when:

- The code is used only by one charm. In-charm code is easier to evolve.
- The helper has no Juju-specific surface. Publish it to PyPI as a normal package. The modern ecosystem is moving helpers into `charmlibs-*` PyPI packages — see "Publishing" below.

## Anatomy of a Charm Library

One library is exactly one `.py` file. The path encodes the publishing charm, the major API version, and the library name:

```
lib/charms/<publishing_charm_underscored>/v<N>/<library_name>.py
```

Example: `postgresql-k8s` publishes `postgres_client` at API version 0. The file is:

```
lib/charms/postgresql_k8s/v0/postgres_client.py
```

Note that the charm name has hyphens converted to underscores in the path (Python import compatibility), but the `charmcraft.yaml` `name:` field keeps the hyphens.

### Required Metadata

Every library file must define four module-level constants near the top:

```python
"""Postgres client relation library.

Short description of what this library does.
"""

LIBID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"  # UUID4, assigned by `charmcraft register-lib`.
LIBAPI = 0   # Major version — bump only on breaking changes.
LIBPATCH = 7  # Patch — increment on every change, including additive ones.

PYDEPS = ["pydantic>=2", "cryptography>=42"]  # PyPI deps the library imports.
```

- **`LIBID`** is stable for the lifetime of the library. Never change it. `charmcraft register-lib` generates it the first time.
- **`LIBAPI`** matches the `v<N>` directory. Bumping it means a new file at `v<N+1>/...` — old consumers keep using the old file.
- **`LIBPATCH`** is the consumer-facing version selector when pinning: `charm-libs: [{lib: postgresql_k8s.postgres_client, version: "0.7"}]`.
- **`PYDEPS`** lists the PyPI packages the library needs at runtime. `charmcraft pack` merges these into every consuming charm's `requirements.txt`. Keep this minimal and pin loosely.

## Step 1: Create the Library

Run `charmcraft create-lib` from the charm's top-level directory:

```bash
charmcraft create-lib postgres_client
```

This creates `lib/charms/<your_charm>/v0/postgres_client.py` with a stub `LIBID`, `LIBAPI = 0`, `LIBPATCH = 1`, and an empty `PYDEPS`. Fill in the docstring and implementation.

The library name (`postgres_client`) must be a valid Python identifier: lowercase, underscores, no leading digit.

## Step 2: Design the Public API

A relation-interface library typically exposes a **provider** class (for the charm that owns the data) and a **requirer** class (for the charm that consumes it). Each class:

- Takes the `CharmBase` instance and the relation endpoint name in `__init__`.
- Observes the relation lifecycle events (`relation_created`, `relation_changed`, `relation_broken`).
- Emits high-level events the consumer charm cares about (for example, `DatabaseReady`, `CredentialsChanged`).
- Exposes a typed accessor for the current relation data.

```python
import ops
import pydantic


class DatabaseReady(ops.EventBase):
    """Emitted when the database is ready and credentials are available."""


class PostgresClientEvents(ops.ObjectEvents):
    database_ready = ops.EventSource(DatabaseReady)


class _DatabaseSchema(pydantic.BaseModel):
    """Schema for the databag on the provider side."""

    model_config = pydantic.ConfigDict(extra="forbid")
    host: str
    port: int
    database: str
    username: str
    password: pydantic.SecretStr


class PostgresClient(ops.Object):
    """Client-side helper for the ``postgres_client`` relation interface."""

    on = PostgresClientEvents()

    def __init__(self, charm: ops.CharmBase, relation_name: str = "database"):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self.framework.observe(
            charm.on[relation_name].relation_changed,
            self._on_relation_changed,
        )

    def _on_relation_changed(self, event: ops.RelationChangedEvent):
        try:
            _DatabaseSchema.model_validate(dict(event.relation.data[event.app]))
        except pydantic.ValidationError:
            return  # Remote end isn't ready yet; ignore silently.
        self.on.database_ready.emit()

    def connection_info(self) -> _DatabaseSchema | None:
        """Return the current database connection info, or ``None``."""
        relation = self._charm.model.get_relation(self._relation_name)
        if relation is None or relation.app is None:
            return None
        try:
            return _DatabaseSchema.model_validate(dict(relation.data[relation.app]))
        except pydantic.ValidationError:
            return None
```

Design principles:

1. **Consumer code should never touch `event.relation.data`.** Wrap it in a typed accessor — `connection_info()` above — so breaking schema changes are caught at library boundaries, not in every consumer.
2. **Emit high-level events, not raw relation events.** `database_ready` is more useful than `relation_changed`.
3. **Validate remote data.** Never trust what the other charm wrote. Use Pydantic (preferred) or dataclass-level validation. See the `relation-data-design` skill.
4. **Fail closed on malformed data.** Return `None`, don't emit the ready event, and log — don't raise out of an observer.
5. **No charm-framework-in-charm-framework.** The library manipulates events and relation data; it does not reach into the charm's own state. Store nothing on the `Object` subclass across hooks — Juju re-instantiates the charm every dispatch.

## Step 3: Write Unit Tests With Scenario

Library tests live in the publishing charm's `tests/unit/`. Exercise the library through a minimal test-only charm that uses it, then fire relation events with Scenario. This catches both library bugs and contract regressions.

```python
import ops
from ops import testing

from charms.postgresql_k8s.v0.postgres_client import PostgresClient


class _TestCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.client = PostgresClient(self)
        self.framework.observe(
            self.client.on.database_ready,
            self._on_ready,
        )
        self._ready_seen = False

    def _on_ready(self, _event):
        self._ready_seen = True


def test_emits_database_ready_on_valid_data():
    ctx = testing.Context(_TestCharm, meta={"name": "c", "requires": {"database": {"interface": "postgresql_client"}}})
    relation = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="db",
        remote_app_data={
            "host": "10.0.0.1",
            "port": "5432",
            "database": "app",
            "username": "app",
            "password": "s3cret",
        },
    )
    state_in = testing.State(relations={relation})
    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)
    # Emission is observable via a spy on the test charm, or via ctx.emitted_events.
    assert any(isinstance(e, type(ctx.emitted_events[-1])) for e in ctx.emitted_events)


def test_connection_info_returns_none_on_invalid_data():
    ctx = testing.Context(_TestCharm, meta={"name": "c", "requires": {"database": {"interface": "postgresql_client"}}})
    relation = testing.Relation(
        endpoint="database",
        remote_app_data={"host": "10.0.0.1"},  # Missing fields.
    )
    state_in = testing.State(relations={relation})
    with ctx(ctx.on.relation_changed(relation), state_in) as mgr:
        state_out = mgr.run()
        assert mgr.charm.client.connection_info() is None
```

The `scenario-tests` skill covers Scenario patterns in depth. Key rule: never use Harness — it is deprecated.

## Step 4: Document the Library

The module docstring is the library's public documentation. Charmhub surfaces it on the library page. Cover:

- What the library does in one sentence.
- Which relation interface it implements (if any), and which side (provider/requirer).
- A minimal usage example that drops into `src/charm.py`.
- The events it emits and what triggers them.
- Breaking-change history, if any (what changed at `v1`).

```python
"""Postgres client relation library.

Implements the *requirer* side of the ``postgresql_client`` relation interface.

Usage::

    from charms.postgresql_k8s.v0.postgres_client import PostgresClient

    class MyCharm(ops.CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.db = PostgresClient(self)
            self.framework.observe(self.db.on.database_ready, self._start_app)

        def _start_app(self, _event):
            info = self.db.connection_info()
            assert info is not None  # database_ready guarantees this.
            ...

Events:

- ``database_ready`` — remote app databag parses cleanly and contains a
  valid connection. Not re-emitted for identical data.

Version history:

- ``v0.1`` — initial release.
- ``v0.7`` — ``port`` accepted as string or int; password now in ``SecretStr``.
"""
```

## Step 5: Versioning Rules

- **Increment `LIBPATCH` on every change** — even a docstring fix. Consumers pin on `"<major>.<patch>"` and pulling an unchanged patch is always safe.
- **Never remove or rename a public name in a `v<N>` file.** Adding new optional fields, new methods, new event sources — all fine, bump patch. Removing, renaming, changing a signature, or tightening a validator is breaking.
- **For a breaking change, create a new `v<N+1>/` file.** Keep the old file on disk so existing consumers keep fetching it. Deprecate in the old module's docstring and point at the new path.
- **Shared state between versions** (for example a constants table) lives in a non-versioned helper under `lib/charms/<charm>/<helper>.py` imported by each `v<N>/<library>.py`. Charmcraft ships every file under `lib/charms/<charm>/` into consumers, not just the library file itself.

## Step 6: Publish to Charmhub

First time only — register the library name:

```bash
charmcraft register-lib charms.postgresql_k8s.v0.postgres_client
```

This assigns a `LIBID` (update the file) and reserves the name.

Every release:

```bash
charmcraft publish-lib charms.postgresql_k8s.v0.postgres_client
```

Charmhub checks that `LIBPATCH` has been incremented since the last publish and rejects the upload otherwise. Commit and tag the `LIBPATCH` bump.

### Consumer side

Another charm depends on the library either by fetching the file into its own tree:

```bash
charmcraft fetch-libs
```

after adding to its `charmcraft.yaml`:

```yaml
charm-libs:
  - lib: postgresql_k8s.postgres_client
    version: "0"           # Track the latest patch of major 0.
  - lib: tls_certificates_interface.tls_certificates
    version: "3.17"        # Pin to a specific patch.
```

Fetched files land at `lib/charms/postgresql_k8s/v0/postgres_client.py` in the consumer. Commit them — they are vendored, not pulled at build time.

### Modern alternative: publish on PyPI

An increasing number of libraries ship as PyPI packages under the `charmlibs-*` namespace, owned by the `canonical/charmlibs` monorepo. This is preferred where applicable: versioned, hash-pinnable, no `charmcraft fetch-libs` step, works with `uv lock`.

If your library is general-purpose (not tied to a specific charm's schema), consider upstreaming to `canonical/charmlibs` rather than publishing via Charmhub. The `charmcraft` skill lists the current PyPI libraries and their import paths.

## Common Pitfalls

- **Forgetting to bump `LIBPATCH`.** `charmcraft publish-lib` will refuse the upload. Always bump in the commit that changes the file.
- **Breaking change shipped as a patch.** If a consumer's tests break after `charmcraft fetch-libs`, the change was breaking. Roll back, bump `LIBAPI`, move the new code to `v<N+1>/`.
- **`PYDEPS` lists a package the library doesn't actually import.** Dead deps bloat every consumer. Lint the library against `PYDEPS` — every import of an external package should appear.
- **Mutable module-level state.** Juju re-imports the library on every hook; any module-level `dict` or `list` that's written to during a hook is lost. Store state on the relation or on `ops.StoredState`.
- **Over-eager schema validation.** A `relation_changed` event fires before the remote end has finished writing. Accept an empty or incomplete databag silently. Only raise when data is present and malformed.
- **Calling `charm.model.*` from the library's `__init__`.** The charm may not be fully constructed. Do it inside event handlers instead.
- **Exposing Juju relation objects.** If the library returns `ops.Relation`, the consumer becomes coupled to ops internals. Return plain dataclasses or Pydantic models.
