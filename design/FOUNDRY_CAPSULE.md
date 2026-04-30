# Cantrip Foundry Capsule — V1 and Later Plan

> This is a design and rollout plan for packaging Cantrip into a
> containerised development environment product that is still under wraps.
> It intentionally uses temporary code words so the document can live in
> tree before the external naming freeze.

## Temporary terminology

Use these placeholders throughout this document:

| Placeholder | Meaning | Replace later with |
|---|---|---|
| **Foundry** | The external container-based development environment product | Real product name |
| **Capsule** | A packaged environment layer installed into a Foundry | Real package type name |

The goal is that a later rename pass can swap terminology mechanically
without changing the plan itself.

## TL;DR

- **Yes, a Cantrip Foundry Capsule makes sense** if v1 is framed as a
  **remote-controller-first charm authoring environment**, not as a fully
  self-contained local infrastructure stack.
- **V1 should optimise for authoring, review, unit tests, local charm
  edits, Cantrip memory/transcript persistence, and remote Juju-client
  workflows.**
- **V1 should not promise local controller bootstrap, nested LXD, or
  "real cluster inside the container" behaviour.**  The current Foundry
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

A Foundry Capsule is the natural way to collapse that setup into one
declared environment.

## 2. Constraints from the platform model

The current Foundry model appears to provide a constrained but useful set
of host/container integration primitives:

- **project mount** into the container,
- **persistent host-backed mounts** for selected directories,
- **manual SSH-agent access**,
- **network tunnelling** between host and container services,
- and a small fixed interface catalogue rather than arbitrary custom
  interfaces.

Two constraints matter most for Cantrip:

### 2.1 Local "real controller inside the container" is not the starting point

The current evidence does **not** show a documented path for:

- nested LXD,
- host LXD socket pass-through,
- local controller bootstrap inside the Foundry,
- or a first-class Juju-specific integration surface.

That makes a "full local controller in the Foundry" shape speculative.
It may eventually be possible, but it should not define v1.

### 2.2 Remote-client workflows do fit

The current interface set *does* map well to a client-only Juju story:

- persistent client config via mounts,
- SSH identities via an agent socket,
- normal network access to remote controllers,
- and deterministic tool installation in the container.

That is enough for a meaningful Cantrip environment, provided the
product story is honest about the boundary.

## 3. Product goal

Ship a **Cantrip Foundry Capsule** that gives a charm author a repeatable
environment for:

1. planning and editing a charm project with Cantrip,
2. running local repo checks and unit tests,
3. performing transcript and memory workflows,
4. using Juju as a **client** against an already-available controller,
5. and, where validated, performing at least some charm build/deploy
   steps without leaving the Foundry.

## 4. Non-goals for v1

V1 should explicitly *not* promise:

- local controller bootstrap inside the Foundry,
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

**A single Cantrip Capsule for remote-controller-first charm authoring.**

This is the best first version because it:

- has a simple user story,
- minimises cross-Capsule coordination,
- makes installation easy to explain,
- and keeps the initial packaging/testing matrix small.

### 5.2 What the Capsule should include

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

The Capsule should declare persistent mounts for the user state that
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
save/restore hooks when the Foundry mount model already solves the same
problem cleanly.

### 5.4 Connections and credentials

Recommended credential model for v1:

- **LLM provider keys:** supplied by environment variables at launch or
  shell time, not auto-persisted by the Capsule.
- **SSH identities:** exposed only via the SSH-agent connection.
- **Juju auth:** either established inside the Foundry by normal CLI
  login, or recovered from the mounted Juju client state.

The principle is simple:

- persist what is naturally a config directory,
- but do not invent secret-handling semantics that the platform already
  has a simpler answer for.

### 5.5 Hooks

The Cantrip Capsule likely needs four hook concerns.

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

Missing authentication is a user-readiness issue, not a broken Capsule.

#### save-state / restore-state

Prefer **not** to use these in v1 unless a specific piece of Cantrip
state cannot be represented as a mounted directory.  Mounted directories
are simpler, more inspectable, and easier to reason about than custom
state migration hooks.

### 5.6 Foundry-specific Cantrip prompting

The Capsule should ship a short environment note for the agent, similar
to the other AI-agent Capsules.

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

- open a project in the Foundry and run Cantrip against it,
- read/edit files,
- use Cantrip memory and transcript features across refreshes,
- run repo-local checks and tests,
- use Git and GitHub tooling,
- and use Juju as a client to inspect or operate against an existing
  controller when the user has authenticated it.

### 6.2 Nice to have in v1, but validate before promising

- charm packaging inside the Foundry,
- deploy / refresh from the Foundry,
- and end-to-end "author -> pack -> deploy -> inspect" flows without
  leaving the environment.

These are plausible, but they depend on the exact runtime expectations
of the charm toolchain and should be validated explicitly.

## 7. V1 open technical questions

These questions should be answered by short spikes before implementation
is declared final.

### 7.1 Can charm packaging run cleanly inside the Foundry?

This is the biggest unknown.

Questions to answer:

- Can `charmcraft pack` run in the container without extra host
  integration?
- If not, is there a workable destructive-mode or direct-build path that
  covers the Cantrip use case?
- If not, should packaging move out of v1 and become a later phase?

### 7.2 What exact Juju directories must persist?

We should identify the minimum stable set of Juju client paths needed for:

- controller definitions,
- cached credentials,
- SSH materials if any,
- and normal CLI behaviour after refresh.

### 7.3 Should Juju and charmcraft live in the same Capsule?

The default recommendation is **yes for v1** because it keeps the user
story simple.  But a quick spike should still answer:

- does this make the image too large,
- does it complicate support,
- and would a split produce meaningfully better failure isolation?

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

Before productising the Capsule:

1. package Cantrip alone in a minimal Foundry,
2. add persistent Cantrip config,
3. add Juju client and validate state persistence,
4. test remote-controller login and status flows,
5. test charm packaging in-container,
6. confirm what breaks and what is merely undocumented.

Exit criterion: we know whether packaging/deploy belongs in v1 or v1.1.

## 8.2 Phase B — v1 Capsule

Build the first real Capsule with:

- Cantrip,
- persistent Cantrip config,
- persistent Juju config,
- GitHub CLI config persistence,
- SSH-agent support,
- a Foundry-specific prompt note,
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

### 9.1 Later: split into companion Capsules if the single bundle gets too heavy

Possible future decomposition:

- **Cantrip Capsule** — agent, memory, transcripts, repo tooling
- **Juju Client Capsule** — Juju CLI and controller-facing config
- **Charm Build Capsule** — charmcraft and build-time dependencies

The single Capsule is better for first adoption.  The split only becomes
worth it if image size, update cadence, or support burden becomes
painful.

### 9.2 Later: host-service tunnelling

If users want to reach host-local services from inside the Foundry,
tunnel support could power things like:

- a host-local inference endpoint,
- browser-facing local dashboards,
- or other operator-side helpers.

This should be a later refinement, not a prerequisite for v1.

### 9.3 Later: stronger team flows

Once the single-user Capsule is stable, we can consider:

- shared Cantrip memory mounts,
- repo-scoped caches,
- and stronger defaults for reproducible team onboarding.

The right order is:

1. make the single-user story excellent,
2. then make the team story ergonomic.

### 9.4 Later: local-controller support if the platform grows the right primitive

This is the most important deferred future shape.

Revisit local-controller support only if Foundry gains a documented path
for one of:

- nested container orchestration,
- safe host daemon access,
- a first-class local-controller integration,
- or another officially supported mechanism that replaces those.

At that point, the Cantrip Capsule could expand from:

- **remote-controller-first charm authoring**, to
- **full local build/deploy/test lab**.

Until then, designing around that future would distort v1.

## 10. Recommendation

Proceed with a **Cantrip Foundry Capsule**, but do it with an explicit
v1 boundary:

- **yes** to Cantrip in a repeatable container environment,
- **yes** to persistent Cantrip and Juju client state,
- **yes** to remote-controller Juju workflows,
- **yes** to AI-agent-specific environment prompting,
- **maybe** to in-container charm packaging, pending a spike,
- **no** to local-controller promises until the platform says otherwise.

That gives Cantrip a strong entry point into the Foundry ecosystem
without tying the first release to the hardest, least-proven part of the
problem.

## 11. Concrete next steps

If this plan is accepted, the next practical step is a short
implementation spike outside the Cantrip repo to answer the three
highest-risk unknowns:

1. **Cantrip-only Capsule boots and runs cleanly.**
2. **Juju client state survives refresh and can talk to a real remote
   controller.**
3. **Charm packaging either works in-container or is formally deferred
   out of v1.**

Those three answers are enough to turn this document into an execution
plan.
