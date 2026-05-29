# Kubernetes / kubectl Tool — Research Findings

> Output of Phase 86.  This is a research document, not a design.  It
> records the question (should the agent grow first-class `kubectl`
> support?), the surface gap a kubectl tool would close, the sandbox
> and kubeconfig findings that constrain any implementation, and the
> verdict.

## TL;DR

- **Cantrip has zero `kubectl` references in source today.**  The
  agent's substrate surface is entirely `juju`-driven (28 typed
  Juju tools plus a `juju_cli` escape hatch); the sole bare-metal
  diagnostic skill, `fix-broken-juju-k8s`, prescribes `journalctl`,
  `snap services`, `snap changes`, and `concierge restore` and
  never reaches for `kubectl`.
- **The phase prompt names the gap precisely:** "the charm is
  healthy from juju's perspective but broken at the Kubernetes
  layer (CrashLoopBackOff, OOM, pulled-image fails, PVC stuck
  pending, RBAC mis-binding, etc.)".  Juju surfaces the unit as
  `error` / `lost` but the *reason* is on the pod, the events
  stream, or the PVC.  `juju debug-log` and `juju ssh` don't
  cross that boundary.
- **The natural verb shortlist is six commands**, all read-only:
  `kubectl describe pod`, `kubectl get events`, `kubectl get pods`,
  `kubectl logs ... --previous`, `kubectl describe pvc`,
  `kubectl top pod`.  Writes (`apply`, `delete`, `exec`, `patch`)
  stay out of scope — they'd duplicate `juju`'s side of the
  contract or open a destructive surface neither the dev box nor
  the user has asked for.
- **Sandbox finding: `kubectl` itself is *not* snap-confined the
  way `juju` is** (no transient-scope dbus call), but the bwrap
  sandbox unsets `HOME` and binds nothing under `~/.kube/`, so
  `kubectl` inside `run_command` would read kubeconfig from a
  vanished path and fail.  Any first-class kubectl tool would
  follow the `juju.py` pattern of bypassing `SandboxedRunner` and
  calling `subprocess.run` directly with `KUBECONFIG=~/.kube/config`
  passed in the environment.
- **Verdict: skill-expansion now, defer the typed tool.**  The
  shortlist lands as a new "Looking *underneath* Juju" section in
  `fix-broken-juju-k8s` so the agent surfaces the verbs to the
  user via the existing escalation pattern.  No production code
  change.  Open a Phase 86b implementation phase only when a
  concrete user case shows the agent reaching the gap
  autonomously and wanting to act, not just prescribe.

The rest of this document walks the evidence.

## 1. The gap Juju leaves

### 1.1 What Juju covers

The 28 typed `juju_*` tools cover everything the charm *interface*
exposes:

- **Status / units / models** — `juju_status`, `juju_show_unit`,
  `juju_list_offers`, `juju_get_app_config`.
- **Logs** — `juju_debug_log` (controller-side message log) and
  `juju_stream_logs` (agent + workload, follows).
- **Workload reach-in** — `juju_ssh` lands a shell in the unit's
  container.
- **Relation / config / secrets** — `juju_read_relation_data`,
  `juju_config`, `juju_list_secrets`, `juju_show_secret`.
- **Lifecycle** — `juju_deploy`, `juju_refresh`, `juju_relate`,
  `juju_run_action`, `juju_dispatch`, `juju_destroy_model`.

For a healthy charm with a misbehaving workload, this is enough.

### 1.2 Where it ends

Juju does *not* surface:

| Symptom | Juju view | Pod-layer view |
|---|---|---|
| `CrashLoopBackOff` | unit `error`, no reason | container exit code, restart count, `lastState.terminated.reason` |
| `ImagePullBackOff` | unit `waiting`, "agent initialising" | event "Failed to pull image …: ErrImagePull / 401 Unauthorized" |
| OOM kill | unit `lost` then `active` | container `lastState.terminated.reason: OOMKilled` |
| PVC stuck `Pending` | unit `blocked`, "waiting for storage" | PVC status, storage-class events |
| RBAC missing | unit `error`, hook traceback | API-server denied verb on resource |
| Resource pressure | unit slow, no signal | `kubectl top pod` numbers |

Each row above is a charm-debug failure mode the
`fix-broken-juju-k8s` skill currently escalates to the user with
no copy-paste shape — the user has to remember `kubectl describe
pod -n <model>` themselves.

## 2. The verb shortlist

Six read-only verbs cover every row in §1.2.  They are intentionally
charm-specific — generic kubectl wrapping (`get nodes`, `cluster-info
dump`, `auth can-i`) is out of scope.

| # | Verb | What it answers | Substitutable by Juju? |
|---|---|---|---|
| 1 | `kubectl describe pod -n <model> <pod>` | Why is this pod restarting / pending / failing? | No |
| 2 | `kubectl get events -n <model> --sort-by=.metadata.creationTimestamp` | What just happened in the namespace? | No |
| 3 | `kubectl get pods -n <model>` | Pod-level status across the model | Partially (juju shows units, not pods) |
| 4 | `kubectl logs -n <model> <pod> -c <container> --previous` | What did the *crashed* container print before it died? | No (`juju ssh` lands in the *current* container) |
| 5 | `kubectl describe pvc -n <model>` | Storage-class events, volume binding, capacity | No |
| 6 | `kubectl top pod -n <model>` | Resource pressure (when metrics-server is on) | No |

The model name is the namespace by convention on Juju-K8s.

## 3. Sandbox and kubeconfig findings

Two things matter for any future typed tool:

### 3.1 `kubectl` is not snap-confined like `juju`

The reason `juju` is *off* the `run_command` allowlist
(`tools/run_command.py:14-20`) is the snap transient-scope dbus
call: snap-packaged `juju` invokes `systemd-run` to put the child
in a transient scope, which fails inside bwrap's PID namespace
("Process 1 is a manager process, refusing.").  The typed
`tools/juju.py` wrappers dodge this by calling Jubilant, which
calls `subprocess.run` directly without sandbox wrapping.

`kubectl` does not have that problem.  On the dev box it lives at
`/snap/bin/kubectl` (snap-installed) but it *does not* shell out
through `systemd-run` — it just opens an HTTPS connection to the
API server.  Probed on this dev box: `kubectl version --client`
runs cleanly outside any sandbox; inside `bwrap --unshare-pid
--unshare-net` it would fail on the network unshare, but with
`network=True` it would still fail on `~/.kube/config` not being
visible.

### 3.2 Kubeconfig visibility under bwrap

`SandboxedRunner._wrap_bwrap` (sandbox.py:241-303) sets up:

- A fresh user namespace (caller mapped to root inside).
- `--unshare-net` unless `policy.network=True`.
- `/proc`, `/dev`, `/tmp` provided by bwrap.
- `cwd` and `policy.read_write_paths` bound read-write.
- `policy.read_only_paths` bound read-only.
- **`HOME` unset** — explicit choice (line 259) so commands don't
  leak into the real home.

The default kubeconfig location (`$HOME/.kube/config`, fallback
`$KUBECONFIG`) therefore vanishes inside the sandbox.  Any
kubectl tool inside `run_command` would have to either:

1. Pass `--kubeconfig=<absolute path>` and add `~/.kube/config`
   to `policy.read_only_paths`, with `network=True` so the API
   server is reachable.
2. Or — better — bypass the sandbox entirely, mirroring the
   `tools/juju.py` pattern (subprocess.run with explicit
   `KUBECONFIG` in env).  The destructive-command gate in
   `agent/policy.py` stays the third layer in the
   defence-in-depth stack (Phase 80).

Option (2) is what a typed tool would do.  Option (1) is what
adding `kubectl` to the `run_command` allowlist would require —
and would still depend on the agent assembling the right
arguments by hand, which is the value the typed tool would
provide.

### 3.3 Kubeconfig presence is not assumed

On a fresh Cantrip dev box without the canonical k8s snap, there
may be no kubeconfig at all — `concierge prepare` only writes one
when its preset includes `k8s` or `microk8s`.  Any tool has to
detect "no kubeconfig" cleanly and surface it as a pre-flight
failure, not a 30-second timeout.  Mirror the `_juju_available()`
probe pattern (juju.py:2511) with a `_kubeconfig_present()` check
on `~/.kube/config` plus `$KUBECONFIG`.

## 4. Tool vs. skill — the trade-off

| Dimension | Typed tool | Skill expansion |
|---|---|---|
| Agent autonomy | Agent runs the verb itself, parses output, decides next step | Agent prescribes the verb to the user; user runs it; agent reads pasted output |
| Token cost | Structured `ToolResult` is cheap to digest | Pasted `kubectl describe pod` output can run 60+ lines of YAML-ish text |
| Implementation cost | ~6 tool classes + tests + sandbox-bypass plumbing + kubeconfig probe + caption strings + post-edit-lint compatibility | ~50 lines of markdown |
| Risk surface | New subprocess path, read-only by construction but still touches the cluster | None — read-only by user policy |
| Triggers needed to justify | Several incidents where the agent reached the gap autonomously and wanted to act | The phase prompt itself ("CrashLoopBackOff, OOM, pulled-image fails…") |

The skill expansion ships the charm-relevant know-how *now*.  The
typed tool ships agent autonomy *later*, gated on evidence the
autonomy is wanted.

## 5. Verdict

**Ship the skill expansion.  Defer the typed tool.**

What lands in this phase:

- This document (`design/K8S_TOOL.md`).
- A new "Looking *underneath* Juju" section appended to
  `src/cantrip/skills/fix-broken-juju-k8s/SKILL.md` covering the
  six verbs from §2 with copy-pasteable shapes per Juju model.
- The existing skill's "Things you must NOT do" section gains a
  one-liner reminder that `kubectl delete`, `kubectl exec`, and
  `kubectl apply` are user-driven, not agent-driven, while the
  read paths above are safe to suggest.

What does **not** land:

- No new `Tool` subclass, no `tools/kubectl.py`, no `build_tools`
  registration, no `run_command` allowlist change.
- No `kubectl_*` permission entries — there's nothing to permit.
- No kubeconfig probe in `agent/preflight.py` — the skill prose
  surfaces the "is there a cluster?" question to the user when
  needed.

## 6. Revisit triggers

Open Phase 86b — typed kubectl tool — when *any* of the following
fire:

1. **Autonomy signal.**  The agent independently reaches the
   "Juju says active, pod is in CrashLoopBackOff" gap on a real
   charm session and the transcript shows it asking the user to
   run `kubectl describe pod` rather than answering the
   question itself.
2. **Skill-prescription frequency.**  The
   `fix-broken-juju-k8s` skill loads frequently with the new
   §1.2 content, and the agent spends multiple turns walking the
   user through manual kubectl invocations that the typed tool
   would absorb in one call.
3. **Acceptance / observability gap.**  The Phase 17 acceptance
   harness or the COS-aware tooling in `tools/observability.py`
   needs pod-level state that Juju doesn't expose — e.g. a
   smoke test wants to assert "no PVC stuck Pending" before
   declaring the deploy healthy.
4. **A user asks for it.**  The smallest possible trigger:
   someone using Cantrip on a substrate-bug-prone deployment
   wants the agent to *act* on the diagnostic, not just
   describe it.

When any of those fire, the implementation phase opens with the
verb shortlist from §2 as the deliverable scope, the
sandbox-bypass pattern from §3 as the architecture, and the
kubeconfig-presence probe from §3.3 as the pre-flight.

## 7. What this phase is *not*

- **Not a `kubectl apply` story.**  Writing manifests against the
  cluster is an entirely different blast radius and the dev-box
  policy ("rebuild beats surgery") already covers the recovery
  paths a charm developer should take.
- **Not a microk8s feature parity exercise.**  The microk8s
  built-in registry / dashboard story stays in `concierge` and
  `tools/rockcraft.py`; this phase only touches diagnostic
  read paths.
- **Not a generic Kubernetes tool.**  Cantrip builds *charms*; a
  general-purpose `kubectl` wrapper would invite the agent to
  use it for non-charm work and dilute the substrate
  abstraction.
- **Not a replacement for `fix-broken-juju-k8s`'s rebuild
  flow.**  The §1.2 verbs add a layer *above* "purge and
  rebuild" — they answer "what's broken?" before the user
  decides whether to escalate to a rebuild.
