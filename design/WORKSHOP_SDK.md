# Cantrip Workshop SDK — V1 and Later Plan

> Design and rollout plan for packaging Cantrip as an SDK for Canonical's
> Workshop — the snap-delivered, LXD-backed sandboxed development
> environment product.

> **Empirical validation (2026-05-28).** A separate Charm Tech evaluation
> exercised Workshop 0.9.0 + sdkcraft 0.1.14 + LXD 6.7 directly: built and
> launched draft `juju`, `tox`, `charmcraft`, and `pi` SDKs end-to-end,
> verified the mount and tunnel interface behaviour, and probed several
> "can we host the substrate inside a workshop?" topologies.  Their
> findings and analysis live at
> `~/charm-tech-workshop/docs/{findings,analysis}.md`.  This plan has been
> updated with concrete answers where they had hypotheticals; sections
> that cite empirical results carry "(verified)" markers.

## TL;DR

- **Yes, a Cantrip Workshop SDK makes sense** if v1 is framed as a
  **remote-controller-first charm authoring environment**, not as a fully
  self-contained local infrastructure stack.
- **V1 should optimise for authoring, review, unit tests, local charm
  edits, Cantrip memory/transcript persistence, and remote Juju-client
  workflows.**
- **V1 should not promise local controller bootstrap, nested LXD, or
  "real cluster inside the container" behaviour.**  The current Workshop
  interface model does not show a first-class path for that.
- **Later phases can expand** toward richer build/deploy flows, host-side
  service tunnelling, and possibly local-controller support if the
  underlying platform grows the required integration primitives.

## 1. Problem statement

Cantrip already has a strong fit for a containerised development
environment:

- it is terminal-first,
- it operates against a mounted project tree,
- it benefits from reproducible tooling,
- it carries user-specific state worth persisting across environment
  refreshes,
- and it becomes dramatically easier to adopt if "install the right
  tools in the right versions" becomes somebody else's problem.

Today, a new Cantrip user still has to assemble:

- Python and the project runtime,
- Cantrip itself,
- the surrounding CLI toolchain (`git`, `gh`, `uv`, etc.),
- provider credentials,
- and, for charm work, some subset of Juju and charm-build tooling.

A Workshop SDK is the natural way to collapse that setup into one
declared environment.

## 2. Constraints from the platform model

Workshop exposes a constrained but useful set of host/container
integration primitives, configured via simple YAML documents:

- **project mount** into the container, at the well-known path
  `/project` (verified — Workshop convention),
- **persistent host-backed mounts** for selected directories
  (verified — the workshop reports an auto-allocated host-source path
  under `~/.local/share/workshop/id/<id>/...` for each declared `mount`
  plug, no explicit slot binding needed),
- **device pass-through** for things like GPUs,
- **desktop GUI access** from the host,
- **manual SSH-agent access**,
- **network tunnelling** between host and container services
  (verified — and supports both TCP endpoints and unix sockets),
- and a small fixed interface catalogue (`camera / desktop / gpu /
  mount / ssh-agent / tunnel`) rather than arbitrary custom interfaces.

Workshop environments run as **unprivileged system containers** on
**LXD 6.8 or newer**, with `security.nesting=true` set by default
(verified by inspecting `internal/workshop/lxd/lxd_backend.go`) and
non-privileged defaults; the SDK should respect that posture rather
than expecting elevated host capabilities.  The container's single
`raw.lxc` slot is already pinned by Workshop (a tmpfs entry for
`/tmp`), so an SDK cannot append extra LXC config of its own.

Hook scripts run as **root** inside the container (verified).  Tooling
that's configured per-user (npm prefix, `uv tool`) must be invoked via
`sudo -iu workshop` so it lands in the workshop user's `$HOME`, not
root's.  Passwordless `sudo` works inside the workshop, so an action or
hook can shell out for ad-hoc package installs.

**Tunnel-slot gotcha:** `system`-SDK tunnel slots are deliberately not
auto-connected from a workshop's `connections:` block (security).  An
SDK that declares a `tunnel` plug for a host endpoint must either
document the manual `workshop connect <plug> <slot>` step, or wrap it
in a workshop action — putting the bind in `connections:` is silently
ignored.

Two constraints matter most for Cantrip:

### 2.1 Local "real controller inside the container" is not the starting point

Three of the four assumptions in this section have moved from
"speculative" to "tested":

- **Nested LXD works** (verified).  `snap install lxd` + `lxd init
  --auto` + `lxc launch ubuntu:24.04 inner` all succeed inside a
  workshop.  Good enough for `charmcraft pack` LXD-provider mode and
  for rockcraft.
- **`juju bootstrap localhost` does *not* work** (verified on LXD 5.21
  *and* 6.7).  The Juju controller machine ends up as an LXD container
  at nesting depth 2 (inside the workshop's own nested LXD); `snapd
  .service` does not come up there, so Juju cannot install the
  `juju-db` snap, and bootstrap fails with a `mongod`-install error.
  Inner-LXD profile tweaks do not fix it.  This is a hard "no" for v1.
- **Canonical Kubernetes also doesn't come up** (verified).  `k8s
  bootstrap` succeeds, but the kubelet won't start (`/dev/kmsg`
  missing — the workshop is an unprivileged user-namespaced
  container).  Even with the documented in-userns workarounds the CNI
  cannot start pods, so `juju add-k8s` against an in-workshop cluster
  isn't reachable either.
- **Host LXD socket pass-through** remains undocumented.

So the "full local controller in the Workshop" shape is not just
speculative, it is **demonstrated to be blocked** by a Workshop-level
container-capabilities choice (no privileged-container opt-in, the one
`raw.lxc` slot is taken).  The fix would have to land in Workshop
itself; until then, v1 stays remote-controller-first.

### 2.2 Remote-client workflows do fit

The current interface set *does* map well to a client-only Juju story:

- persistent client config via mounts,
- SSH identities via an agent socket,
- normal network access to remote controllers,
- and deterministic tool installation in the container.

That is enough for a meaningful Cantrip environment, provided the
product story is honest about the boundary.

## 3. Product goal

Ship a **Cantrip Workshop SDK** that gives a charm author a repeatable
environment for:

1. planning and editing a charm project with Cantrip,
2. running local repo checks and unit tests,
3. performing transcript and memory workflows,
4. using Juju as a **client** against an already-available controller,
5. and, where validated, performing at least some charm build/deploy
   steps without leaving the Workshop environment.

## 4. Non-goals for v1

V1 should explicitly *not* promise:

- local controller bootstrap inside the Workshop environment,
- nested container orchestration,
- local Kubernetes substrate management,
- full parity with a bespoke host machine used by an expert charm
  engineer,
- or every Cantrip tool working on day one.

This is important because a "mostly works" environment with crisp edges
is better than a "full charm lab" promise that fails on the first local
controller step.

## 5. Recommended v1 shape

### 5.1 V1 headline

**A single Cantrip SDK for remote-controller-first charm authoring.**

This is the best first version because it:

- has a simple user story,
- minimises cross-SDK coordination,
- makes installation easy to explain,
- and keeps the initial packaging/testing matrix small.

### 5.2 What the SDK should include

At minimum:

- **Cantrip itself**
- **Python runtime and package tooling** needed to run it
- **git**
- **gh**
- **uv**
- **rg** / equivalent fast-search tooling
- **curl** / **jq**-class utility CLIs

Strong v1 candidates, but subject to packaging validation:

- **juju client CLI**
- **charmcraft**

The key distinction is:

- **Cantrip + general dev CLI** are table stakes.
- **Juju client** is highly desirable for the value proposition.
- **Charmcraft packaging** is valuable but may have more runtime
  assumptions than the rest of the stack; it should be treated as a
  validated capability, not an assumption.

### 5.3 Persistent mounts

The SDK should declare persistent mounts for the user state that
benefits from surviving refreshes:

- Cantrip state and global memory
  - target: a directory under the user's config home
- Juju client state
  - target: Juju config/data directories
- GitHub CLI auth/config
  - target: the GitHub CLI config directory

Nice-to-have, but optional for v1:

- a dedicated cache directory for Cantrip/provider downloads,
- a shared docs-index cache if the retrieval surface benefits from it,
- and optional per-provider config directories.

The design should prefer **directory-level persistence** over bespoke
save/restore hooks when the Workshop mount model already solves the same
problem cleanly.

### 5.4 Connections and credentials

Recommended credential model for v1:

- **LLM provider keys:** supplied by environment variables at launch or
  shell time, not auto-persisted by the SDK.
- **SSH identities:** exposed only via the SSH-agent connection.
- **Juju auth:** either established inside the Workshop environment by
  normal CLI login, or recovered from the mounted Juju client state.

The principle is simple:

- persist what is naturally a config directory,
- but do not invent secret-handling semantics that the platform already
  has a simpler answer for.

### 5.5 Hooks

The Cantrip SDK likely needs four hook concerns.  (The hook names below
are working labels; align them with whatever names Workshop exposes in
the SDK schema once that surface is documented.)

#### setup-base

Responsibilities:

- install or expose the packaged CLIs,
- ensure shell profile / PATH wiring is correct,
- create any required target directories before auto-connected mounts,
- and place a small environment note in the image if that improves agent
  behaviour.

#### setup-project

Responsibilities:

- finalise user-level environment setup,
- attach any Cantrip-specific prompt/instruction note for the container,
- and perform lightweight first-run initialisation that assumes the
  project mount exists.

#### check-health

Responsibilities:

- verify the Cantrip binary is runnable,
- verify baseline companion CLIs are present,
- optionally verify that the Juju client is installed,
- but **not** fail the whole environment merely because the user is not
  yet authenticated to a controller.

The health model should separate:

- **environment is valid**, from
- **user has completed controller/provider login**.

Missing authentication is a user-readiness issue, not a broken SDK.

#### save-state / restore-state

Prefer **not** to use these in v1 unless a specific piece of Cantrip
state cannot be represented as a mounted directory.  Mounted directories
are simpler, more inspectable, and easier to reason about than custom
state migration hooks.

### 5.6 Workshop-specific Cantrip prompting

The SDK should ship a short environment note for the agent, similar to
other AI-agent SDKs in the Workshop catalogue (e.g. OpenCode, Ollama).

That note should teach Cantrip:

- the project lives at the mounted project path,
- persistent config lives in mounted user directories,
- local controller/bootstrap assumptions are unsafe,
- remote-controller workflows are the default,
- and any hardware or special host service must be checked explicitly
  before use.

This is valuable even if the first version does nothing more than reduce
bad assumptions.

## 6. V1 supported workflows

These are the workflows v1 should aim to support confidently.

### 6.1 Guaranteed

- open a project in the Workshop environment and run Cantrip against it,
- read/edit files,
- use Cantrip memory and transcript features across refreshes,
- run repo-local checks and tests,
- use Git and GitHub tooling,
- and use Juju as a client to inspect or operate against an existing
  controller when the user has authenticated it.

### 6.2 Nice to have in v1, but validate before promising

- charm packaging inside the Workshop environment,
- deploy / refresh from the Workshop environment,
- and end-to-end "author -> pack -> deploy -> inspect" flows without
  leaving the environment.

These are plausible, but they depend on the exact runtime expectations
of the charm toolchain and should be validated explicitly.

## 7. V1 open technical questions

These questions should be answered by short spikes before implementation
is declared final.

### 7.1 Can charm packaging run cleanly inside the Workshop environment? — *answered*

**Yes, with caveats** (verified — a draft `charmcraft` SDK ran
`charmcraft pack --destructive-mode` end-to-end and produced a valid
`.charm`).  The caveats:

- The workshop `base` must match the charm's `build-on` base.
  `--destructive-mode` packs *in* the current environment, so a
  ubuntu@24.04 workshop cannot pack a charm whose only `build-on` is
  ubuntu@22.04.  Multi-base charms either need the LXD provider (→ a
  nested-LXD SDK) or one workshop per base.
- The charm's declared `build-packages` and `build-snaps` must be
  pre-installed by a root setup hook.  Running as the `workshop` user,
  `charmcraft` itself cannot `apt`-install or `snap`-install them and
  fails with *"not running as superuser"*.  The Charm Tech `charmcraft`
  SDK does this in `setup-base` (apt update + apt-install the usual
  build deps + `snap install astral-uv`).
- For Cantrip's own SDK, this means: **do not** bundle `charmcraft`
  into the Cantrip SDK.  Compose: workshops that need packing declare
  both `cantrip` and `charmcraft` SDKs.

### 7.2 What exact Juju directories must persist? — *answered*

`~/.local/share/juju` is the right target (verified by the Charm Tech
`juju` SDK draft, mounted at exactly that path).  Workshop refresh
re-creates the container; the `mount` plug keeps the directory on a
host-backed source, so registrations, accounts, credentials, and
bootstrap config survive.  No additional Juju-side dirs need explicit
mounting for the client story.

The Cantrip SDK already declares this plug as `juju-config`.

### 7.3 Should Juju and charmcraft live in the same SDK? — *answered*

**No**, on two pieces of evidence:

- The Charm Tech proposal contributes `juju`, `tox`, `charmcraft` as
  separate SDKs to `canonical/sdks`.  Bundling them into ours would
  duplicate effort and freeze us to their release cadence.
- Both SDKs have very different build shapes — `juju` is a `dump` of
  the release tarball; `charmcraft` is `plugin: nil` + a snap install
  in `setup-base` (its PyPI deps overlap sdkcraft's own and the
  `python` part plugin refuses).  Bundling means choosing the messier
  shape.

So the **composition model** is:

- `cantrip` SDK (this plan) — agent + workshop-prompt + persistent
  config/data/juju/gh mounts.
- `juju` SDK (Charm Tech contribution) — the client binary,
  `juju-data` mount, `controller` tunnel.
- `charmcraft` SDK (Charm Tech contribution) — the snap, build deps,
  destructive-mode pack.

Users compose these in their `workshop.yaml`.  Our README's reference
workshop should show this composition.

### 7.4 What should health mean?

We should lock down a crisp contract:

- missing binary -> error,
- broken PATH wiring -> error,
- missing provider login -> okay with guidance,
- missing Juju login -> okay with guidance,
- unreachable remote controller -> probably okay unless the user asked
  for a controller-backed action.

## 8. Suggested implementation phases

## 8.1 Phase A — feasibility spikes

Before productising the SDK:

1. package Cantrip alone in a minimal Workshop environment — **done**
   (the `cantrip-sdk` repo at `github.com/tonyandrewmeyer/cantrip-sdk`
   ships an SDK that `workshop launch` brings to `Ready`; `cantrip
   --version` runs inside),
2. add persistent Cantrip config — **done** (four mount plugs:
   `cantrip-config`, `cantrip-data`, `juju-config`, `gh-config`; the
   tighter `check-health` verifies each is workshop-owned and
   writable),
3. add Juju client and validate state persistence — **answered by the
   Charm Tech `juju` SDK draft**: end-to-end verified, `juju-data`
   mount at `~/.local/share/juju` survives `workshop refresh`,
   `juju-data` source is host-backed.  Cantrip workshops will declare
   the Charm Tech `juju` SDK as a peer in their `workshop.yaml`
   rather than bundle the client.
4. test remote-controller login and status flows — see §11.2 below.
   The `juju:controller` tunnel + host-side controller pattern is
   plumbing-verified but the full `juju register` round-trip wasn't
   exercised in the Charm Tech run; this is the remaining open spike.
5. test charm packaging in-container — **done** (verified by the
   Charm Tech `charmcraft` SDK; see §7.1).
6. confirm what breaks and what is merely undocumented — **largely
   done**.  The hard "no" items are `juju bootstrap localhost` and
   Canonical K8s inside a workshop (both need a Workshop-level
   privileged-container opt-in); see §2.1 and §9.4.

Exit criterion: we know whether packaging/deploy belongs in v1 or v1.1.
**Provisional answer:** packaging belongs in v1 *as composition* (a
Cantrip workshop with both `cantrip` and `charmcraft` SDKs); deploy
belongs in v1 against a host-side controller, with bind-time setup
documented.

## 8.2 Phase B — v1 SDK

Build the first real SDK with:

- Cantrip,
- persistent Cantrip config,
- persistent Juju config,
- GitHub CLI config persistence,
- SSH-agent support,
- a Workshop-specific prompt note,
- and a health check that validates the environment without requiring
  live logins.

If packaging validation succeeded in Phase A, include charm packaging in
the supported story.  If not, keep the narrative to authoring, testing,
and remote-controller client operations.

## 8.3 Phase C — v1.1 hardening

After the first release:

- tighten the prompt/instruction note from real usage,
- refine mounts and auth guidance,
- add explicit docs for remote-controller setup,
- and, if feasible, promote pack/deploy from "experimental" to
  supported.

## 9. Later phases

### 9.1 Later: split into companion SDKs if the single bundle gets too heavy

Possible future decomposition:

- **Cantrip SDK** — agent, memory, transcripts, repo tooling
- **Juju Client SDK** — Juju CLI and controller-facing config
- **Charm Build SDK** — charmcraft and build-time dependencies

The single SDK is better for first adoption.  The split only becomes
worth it if image size, update cadence, or support burden becomes
painful.

### 9.2 Later: host-service tunnelling

If users want to reach host-local services from inside the Workshop
environment, tunnel support could power things like:

- a host-local inference endpoint,
- browser-facing local dashboards,
- or other operator-side helpers.

This should be a later refinement, not a prerequisite for v1.

### 9.3 Later: stronger team flows

Once the single-user SDK is stable, we can consider:

- shared Cantrip memory mounts,
- repo-scoped caches,
- and stronger defaults for reproducible team onboarding.

The right order is:

1. make the single-user story excellent,
2. then make the team story ergonomic.

### 9.4 Later: local-controller support if the platform grows the right primitive

This is the most important deferred future shape.

The Charm Tech evaluation isolated the specific blocker: workshop
containers run unprivileged and Workshop's single `raw.lxc` slot is
already pinned, so an SDK cannot grant itself the capabilities Juju
(`security.privileged: true` / a working depth-2 snapd) or Canonical
K8s (`/dev/kmsg` bind + apparmor unconfined + extra `raw.lxc`) need.
A `system`-SDK capability — analogous to `gpu` or `camera`, but
granting privileged(-ish) container semantics — would unblock both.

Revisit local-controller support only if Workshop gains that opt-in,
or an equivalent documented path: nested container orchestration with
working snapd, safe host LXD-daemon access, a first-class
local-controller integration, or another officially supported
mechanism that replaces those.

At that point, the Cantrip SDK could expand from:

- **remote-controller-first charm authoring**, to
- **full local build/deploy/test lab**.

Until then, designing around that future would distort v1.

## 10. Recommendation

Proceed with a **Cantrip Workshop SDK**, but do it with an explicit
v1 boundary:

- **yes** to Cantrip in a repeatable container environment,
- **yes** to persistent Cantrip and Juju client state,
- **yes** to remote-controller Juju workflows,
- **yes** to AI-agent-specific environment prompting,
- **maybe** to in-container charm packaging, pending a spike,
- **no** to local-controller promises until the platform says otherwise.

That gives Cantrip a strong entry point into the Workshop ecosystem
without tying the first release to the hardest, least-proven part of the
problem.

## 11. Concrete next steps — status

1. **Cantrip-only SDK boots and runs cleanly.** — **done.**
   `github.com/tonyandrewmeyer/cantrip-sdk` packs cleanly for amd64 +
   arm64; `workshop launch` reaches `Ready`; `cantrip --version`
   prints from inside.
2. **Juju client state survives refresh and can talk to a real remote
   controller.** — **done.**  Validated end-to-end (2026-05-28) in
   `/tmp/cantrip-juju-test/`:

   - A workshop composing `try-cantrip` + `try-juju` reaches `Ready`.
     The cantrip-sdk no longer declares `juju-config` (the upstream
     `juju` SDK owns `juju-data` at the same target — see §7.3); the
     two used to conflict on launch.
   - **Direct connectivity** from inside the workshop to the host's
     Juju controller at `10.168.35.165:17070` works on the default
     LXD bridge, with no tunnel plug or `workshop connect` step.  A
     `tunnel` plug is only needed when the controller is *not* on the
     same LXD bridge as the workshop.
   - `workshop remount cantrip-juju/juju:juju-data ~/.local/share/juju`
     (with `workshop stop` / `workshop start` around it) shares the
     host's Juju state.  Inside, `juju controllers` shows both host
     controllers (`concierge-lxd`, `concierge-k8s`) and `juju status
     -m concierge-lxd:testing` returns the live model state — full
     client round-trip.
   - Container rebuild via `workshop stop` + `workshop start` preserves
     state across the round-trip (controllers/models still visible,
     `juju status` still works).
   - **Caveat (upstream):** the Charm Tech `juju` SDK draft's
     `save-state` hook does `cp --archive` from the workshop user's
     `~/.local/share/juju`.  When that path is a remount of a host
     directory containing root-owned files (e.g. `lxd/` and
     `cookies/`), the unprivileged-with-idmap workshop can't read
     them and the hook exits 1.  Workshop refreshes cleanly roll
     back, so the workshop is never left broken — but this should be
     reported back to Charm Tech before their `juju` SDK ships
     (their `save-state` should `sudo -u workshop` the copy *or* skip
     when the mount is already a host-backed bind).
3. **Charm packaging either works in-container or is formally deferred
   out of v1.** — **done.**  Works with `--destructive-mode` when the
   workshop base matches `build-on` and the charm's build-packages /
   build-snaps are pre-installed by a root hook (the Charm Tech
   `charmcraft` SDK does this).  Multi-base charms still need either
   the nested-LXD provider or per-base workshops.  Cantrip workshops
   should *compose* the Charm Tech `charmcraft` SDK rather than bundle
   it (see §7.3).

All three v1 spikes are now answered.  The remaining loose ends are
status updates and minor doc work, not unknowns:

- a Cantrip-side `check-health` mount-target probe (**done** —
  shipped in `cantrip-sdk` commit `86b976e`),
- the Cantrip-side workshop-prompt consumption (**done** — shipped in
  the cantrip repo commit `d13812e`),
- a documented reference workshop in `cantrip-sdk/README.md` that
  composes `cantrip` + `juju` + `charmcraft` (**done** — verified and
  written up in the `cantrip-sdk` README after the §11.2 round-trip).
- the `cantrip-sdk` dropped its `juju-config` and `gh-config` mount
  plugs to align with §7.3's composition model and unblock
  `cantrip` + `juju` composition (`cantrip-sdk` commit `e356844`).
