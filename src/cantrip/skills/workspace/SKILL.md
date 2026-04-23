---
name: workspace
description: Working across multiple related charms — manifest format, cross-charm relation design, and coordinated Jubilant integration testing
---

# Multi-Charm Workspaces

Use this skill when the user is building, improving, or operating
**more than one** related charm at once — for example a producer/
consumer pair for a new relation interface, a microservice suite
where each service has its own charm, or an infrastructure stack
bundled for reuse. Load it alongside per-charm skills (`custom-charm`,
`twelve-factor`, `infrastructure-charm`) rather than instead of them.

For deploying multiple charms into a Juju model, the payoff is a
series of individual `juju_deploy` + `juju_relate` calls. Do not
write a new `bundle.yaml` — bundles are deprecated (see the `bundle`
skill if the user hands you an existing one).

## The workspace manifest

A workspace is a directory containing a `cantrip.workspace.yaml`
file that enumerates the charms, their cross-charm relations, and any
shared config. The manifest is optional — the agent works fine
without one — but when the manifest is present, the `workspace_info`
tool gives you a cheap structured view of the whole layout.

Minimum useful manifest:

```yaml
workspace: my-platform
description: API tier plus workers, sharing a work-queue interface.
charms:
  - name: my-api
    path: ./my-api-operator
    description: HTTP frontend, 12-factor Flask charm.
  - name: my-worker
    path: ./my-worker-operator
    description: Background worker; scales horizontally.

relations:
  - provider: my-api:workers
    requirer: my-worker:coordinator
    interface: worker-coordination
    description: API emits job manifests; worker pulls and acks.

shared_config:
  log_level: info
```

Schema rules (enforced by :mod:`cantrip.workspace`):

- `workspace` — non-empty name, used as the human-readable label.
- `charms` — at least one entry; every entry needs `name` and `path`.
  Charm names must be unique inside the workspace.
- `relations` (optional) — each endpoint uses `charm-name:endpoint`;
  both sides must name a charm listed above. Mark the provider and
  the requirer explicitly so the agent knows which side authors the
  databag schema.
- `shared_config` (optional) — free-form key/value pairs. Use this
  for values that should match across charms (log levels, TLS modes,
  tenancy identifiers).

Paths are resolved relative to the manifest's directory, so check
the manifest into the workspace root (alongside the first charm's
directory, typically).

## When to create a manifest

Opt in when the user tells you they're working on two or more charms
that share code, relations, or deployment lifecycle. Concrete
triggers:

- A new relation interface requires a provider and a requirer — the
  workspace captures the contract, so both sides evolve together.
- A microservice fan-out (one API charm, several worker charms).
- A monorepo containing multiple publishable charms whose CI should
  run integration tests across all of them.

Do **not** add a manifest for a single-charm repo that just happens
to have a second *directory* (for example a docs site) — the
manifest should carry work, not paperwork.

## Reading a workspace in practice

Call `workspace_info` at the start of any conversation that touches
more than one charm. The tool walks upwards from the current working
directory looking for the manifest, so it works whether the user
launches Cantrip from the workspace root or from inside a charm
subdirectory.

```
workspace_info()
# → Workspace: my-platform
#   Charms (2):
#     - my-api @ /repos/my-platform/my-api-operator
#     - my-worker @ /repos/my-platform/my-worker-operator
#   Cross-charm relations (1):
#     - my-api:workers → my-worker:coordinator (interface: worker-coordination)
```

Use the returned charm paths verbatim with the file tools (`read_file`,
`edit_file`, `grep`, `glob`) — they are already absolute. Each charm
keeps its own `charmcraft.yaml`, `src/`, `tests/`; the workspace is
purely metadata on top.

## Designing cross-charm relations

Two charms integrate through a **relation interface**. The workspace
manifest lists the provider and requirer; your job is to make them
agree on the databag schema before you write a line of Python.

### Interface naming

- Prefer hyphenated lowercase: `worker-coordination`, `http-api`,
  `shared-secret`. This matches Charmhub convention.
- Pick a name descriptive enough that a third charm couldn't
  plausibly claim it for unrelated semantics.
- If the interface already exists on Charmhub (`tls-certificates`,
  `ingress`, `tracing`, `prometheus_scrape`, …) use the existing
  name and its documented databag contract rather than inventing a
  new one.

### Databag shape discipline

- **App databag** (app → app): leader-written, visible everywhere.
  Use for the contract the provider and requirer have actually
  negotiated (e.g. endpoints, TLS mode, interface version).
- **Unit databag** (unit → app): each unit writes its own; useful
  for scaling-aware data such as per-unit addresses.
- **Juju secret** references: for credentials, the leader creates
  the secret and puts the secret id on the app databag; the
  consuming side calls `get_secret(id=...)`. Never put plaintext
  credentials in relation data.

Validate every inbound field with `pydantic` or a plain `dataclass`
so a misbehaving partner charm fails loud, not silent.

### Provider / requirer split

- **Provider** owns the schema: it publishes a relation library
  under `lib/charms/<provider>/vN/<interface>.py` that both sides
  import. See the `charm-library` skill for the authoring flow.
- **Requirer** consumes the library and emits high-level events
  (`MyInterfaceReady`, `MyInterfaceChanged`) instead of observing
  raw `relation_changed`.
- Both sides use `ops.framework.observe` on these higher-level
  events; the library hides the databag protocol.

Document the contract in the workspace manifest's
`relations:[].description` so anyone scanning the file sees what the
interface carries without having to read the library.

## Coordinated integration tests

Integration tests live in exactly one of two places:

1. **Under each charm** — cover the charm's side of every relation
   it declares, deploying a partner from Charmhub when possible.
2. **Under the workspace root** — for end-to-end tests that deploy
   more than one of the charms in the workspace together.

Both use Jubilant (see the `jubilant-tests` skill for the base
patterns). Workspace-level tests add:

```python
import jubilant

def test_api_and_worker_handshake(juju: jubilant.Juju):
    # Pack each charm (or rely on a CI step that does it once).
    juju.deploy("./my-api-operator/my-api_amd64.charm", app="my-api")
    juju.deploy("./my-worker-operator/my-worker_amd64.charm", app="my-worker")
    juju.integrate("my-api:workers", "my-worker:coordinator")

    juju.wait(apps=["my-api", "my-worker"], status="active")

    # Exercise the workflow that uses the relation.
    juju.run("my-api/0", "submit-job", {"payload": "hello"})
    # Check worker state via its action, its logs, or a query endpoint.
```

Points worth calling out:

- Deploy each charm **once**, with `app=` set to the workspace name
  so the test asserts against the same identifier the user would
  use. Different `app=` values for the same charm kind (e.g. two
  workers) reveal scaling bugs in the interface library.
- `juju.integrate(provider_side, requirer_side)` is the explicit
  form; always pass `charm:endpoint` so the test documents which
  endpoint is which.
- Prefer charm actions over SSH-into-unit for assertions. Actions
  have deterministic output and run under Juju's user.
- Put a tear-down `juju.destroy_model()` or pytest fixture in place
  if the test leaves state behind — cross-charm suites are large
  and clean teardown keeps CI cheap.

## Coordinated deploy workflow

When the user wants to stand the whole workspace up on a live model,
sequence the operations explicitly rather than reaching for a bundle:

1. `juju_add_model` (if the target model doesn't exist).
2. For each charm: `charmcraft_pack` (or `quick_pack`) → `juju_deploy`.
3. For each relation in the manifest: `juju_relate(app1=provider, app2=requirer)`.
4. `juju_wait` blocks until every charm reports `active`.
5. If the manifest declares `shared_config`, apply each key across
   the relevant charms with `juju_config` (the skill reader knows
   which keys belong to which charm).

This sequence is deterministic, scriptable, and easy to revert —
all the things bundles aren't. For a reusable deployment, capture
the same sequence in a Terraform module (see the `terraform` skill).

## Planning work across a workspace

Cantrip's `plan_tasks` is still single-charm-scoped; it does not know
how to split work across a workspace automatically. The right pattern
is to:

1. Call `workspace_info` first so you see the charm list.
2. Ask the user which charm the next piece of work belongs to.
3. Call `plan_tasks` with that specific charm's path as the working
   directory so the generated tasks target one charm at a time.
4. Record cross-charm follow-ups in the workspace manifest's
   `relations` section or in a shared design note checked in at
   the workspace root.

This keeps the agent's planning loop honest — one plan, one charm,
one set of commits — while the workspace manifest carries the
connective tissue.

## Do not

- **Do not write a new `bundle.yaml`** to express the workspace.
  Bundles are deprecated; use this manifest plus a Terraform module
  (or a shell script of individual `juju` commands) instead. If an
  existing bundle is in play, load the `bundle` skill for the
  consumption-only workflow.
- **Do not inline cross-charm Python code between charms.** Ship
  shared helpers as a charm library (`charm-library` skill) or a
  PyPI package under `charmlibs-*` (`charm-migration` skill has the
  modern map).
- **Do not add the manifest if there is only one charm.** The
  single-charm flow assumes an absent workspace and is faster
  without one.

## References

- `charm-library` skill — authoring the relation library that
  carries the cross-charm contract.
- `jubilant-tests` skill — base patterns for Jubilant integration
  tests.
- `terraform` skill — long-term replacement for bundle-based
  orchestration.
- `bundle` skill — consumption workflow for legacy bundles.
- `charmcraft` skill — per-charm packaging reference used by every
  charm in the workspace.
