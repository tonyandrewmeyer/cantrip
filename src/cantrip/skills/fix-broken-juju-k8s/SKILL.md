---
name: fix-broken-juju-k8s
description: Diagnose and recover a wedged Juju controller, k8s/microk8s cluster, or stuck concierge environment on a dev machine
---

# Fix Broken Juju or Kubernetes

Recovery playbook for the development machine when Juju, the k8s
snap, microk8s, LXD, or concierge stops responding.  The dev
environment is intentionally cheap to rebuild — purging is almost
always the right call here, and `concierge prepare` puts everything
back in a few minutes.

## When to use

Load this skill when *any* of the following are true:

- `juju status` returns "cannot connect to k8s api server", "cannot
  connect to controller", "no current controller" on a machine that
  used to have one, or hangs for more than ~30 seconds.
- `juju controllers` shows a controller that exists but is
  unreachable (`--refresh` doesn't help).
- `concierge prepare` fails, hangs, or reports a stuck change.
- `snap services k8s` shows core services (`containerd`,
  `kube-apiserver`, `kubelet`, `kube-proxy`) as `inactive` or
  flapping.
- `microk8s status` / `sudo k8s status` reports the cluster is not
  ready and waiting for a check that never completes.
- Any "another concierge process is running" error that persists
  after the expected runtime.

Skip this skill when the failure is a **charm** problem (hook errors,
relation failures, workload bugs).  Those belong in
`iterate-fix` — only reach here when the *substrate* is broken.

## Core principle: this is a dev machine

The user has explicitly stated that purging is fine — losing the dev
controller, models, workloads, and OCI images is acceptable when the
alternative is a wedged cluster.  Don't try heroic surgical fixes
when a clean rebuild is faster and more reliable.

What this means in practice:

- Don't spend more than ~5 minutes on diagnostics before deciding
  whether to rebuild.
- Don't try to "preserve" half a broken cluster.  If `containerd` is
  deadlocked, there is no clean state to keep.
- Do tell the user what you saw and what you did, so they can decide
  whether to follow with `sudo concierge prepare` themselves or have
  you trigger it.

## Diagnostic sweep — first 60 seconds

Run these in parallel before deciding on a fix.  Most don't require
sudo; the agent can do them via `juju_status` for ``juju status`` and
``juju_cli`` (the Jubilant escape hatch) for ``juju controllers`` and
similar.  Anything that needs `sudo` you'll have to escalate to the
user — quote the exact command.

| Check | Command | What it tells you |
|---|---|---|
| Juju reachable? | `juju status` | "cannot connect..." → controller-side issue |
| Controllers known? | `juju controllers --refresh` | Lists registered controllers + cloud |
| K8s snap state | `snap services k8s` | Which subservices are inactive |
| Stuck snap changes | `snap changes` | Look for status `Doing`, `Do`, or `Abort` |
| K8s cluster status | `sudo k8s status` (or `microk8s status`) | Whether the cluster reports ready |
| Recent service logs | `sudo journalctl -u snap.k8s.containerd -n 30 --no-pager` | Often shows boltdb/lock errors |
| Core processes | `ps -ef \| grep -E '(k8sd\|kube\|containerd)' \| grep -v grep` | Is anything actually running? |
| Listening ports | `ss -tlnp \| grep -E ':(6443\|16443\|2379\|10250)'` | API server / etcd up? |
| Disk space | `df -h /` | <10% free is a frequent root cause |
| Free memory | `free -h` | OOM-killed services tend to flap |
| Other containerd? | `dpkg -l \| grep -E '^ii\s+(docker\|containerd)'` | Conflicts with k8s snap (see below) |

## Common failure shapes and the fix

### 1. System Docker / apt containerd conflicts with the k8s snap

**Signal.**  Both `dpkg -l | grep -E 'docker|containerd'` shows
`docker.io` or `containerd` installed, **and** `snap services k8s`
shows `containerd` inactive, **and** `journalctl -u
snap.k8s.containerd` mentions boltdb open / lock contention.

**Cause.**  The k8s snap's containerd and apt's containerd both
target `/run/containerd/containerd.sock` and
`/var/lib/containerd` — they deadlock on the boltdb metadata
store, and kube-apiserver / kubelet never start.

**Fix.**  Purge the apt containerd / docker.  This is the user's
explicit policy: Docker should never be installed on the dev
machine.

```bash
sudo systemctl stop docker.socket docker.service containerd.service
sudo apt-get purge -y docker.io docker-ce containerd containerd.io
sudo apt-get autoremove -y
sudo rm -rf /var/lib/containerd /var/lib/docker /etc/containerd
```

Then proceed to step 4 (rebuild) below.  The agent itself MUST
NOT install Docker for any reason — `run_command` rejects it
explicitly.

### 2. Stuck `snap changes` "Doing" / "Do" entry

**Signal.**  `snap remove --purge k8s` returns `error: snap "k8s"
has "service-control" change in progress`, and `snap changes`
shows a `Doing` row for "Running service command" that never
finishes (often hours old).

**Cause.**  snapd is in a 5-minute restart loop trying to bring up
a service that can't start (usually because of #1 above or a
corrupt boltdb).

**Fix.**  Abort the change, stop the unit files directly, then
purge.

```bash
# Find the stuck change ID.
snap changes | grep -E '(Doing|Do\s)'

# Abort it (use the ID from the previous output).
sudo snap abort <id>

# If abort says "nothing pending" but the lock persists, kill the
# underlying processes first.
sudo pkill -9 -f '/snap/k8s/.*/bin/k8sd'
sudo pkill -9 -f '/snap/k8s/.*/bin/containerd'

# Stop all the snap-managed unit files explicitly.
sudo systemctl stop 'snap.k8s.*'

# Now the purge will succeed.
sudo snap remove --purge k8s
```

### 3. Disk full (<10% free on `/`)

**Signal.**  `df -h /` shows usage above 85%, kubelet
`ImageGCFailed` events, `containerd` failing to write to
`/var/lib/containerd`.

**Fix.**  Free space *before* trying to restart anything.

```bash
# Old snap revisions consume gigabytes on a busy dev box.
sudo snap set system refresh.retain=2
sudo journalctl --vacuum-size=200M

# Container images and volumes — both safe to nuke on a dev box.
sudo rm -rf /var/lib/containerd /var/lib/docker /var/lib/kubelet

# Charmcraft / rockcraft caches live in ~/.local/state.
rm -rf ~/.local/state/charmcraft/cache ~/.local/state/rockcraft/cache

# LXD container caches.
sudo lxc image list -f csv | awk -F, '{print $2}' | xargs -I {} sudo lxc image delete {}
```

If the freed space is still under 5GB, escalate — the rebuild needs
~10GB headroom.

### 4. Rebuild with `concierge restore` + `concierge prepare`

The reliable, low-effort path once diagnostics confirm a wedged
substrate.  Concierge's own restore knows how to undo what prepare
did, including stopping stuck snap services it set up — much safer
than hand-removing things.

```bash
# Clean slate.  Removes Juju, LXD, k8s, and any registered
# controllers concierge created.
sudo concierge restore

# Verify nothing concierge-managed is left.
snap list | grep -E '(k8s|juju|lxd|microk8s|concierge)'
ps -ef | grep -iE '(k8s|juju|lxd|kube|containerd)' | grep -v grep

# Rebuild.  ``--preset dev`` matches the user's standard env;
# adjust to ``machine`` or ``k8s`` if they prefer a leaner one.
sudo concierge prepare -p dev
```

The agent has the `concierge_restore` and `concierge_prepare` tools
for steps that don't need extra arguments — use them when
`approve_destructive: true` is in the active policy.  When destructive
approval isn't enabled, surface the exact `sudo concierge ...`
command and ask the user to run it.

### 5. Concierge itself behaves oddly

**Signal.**  `concierge status` reports `failed` repeatedly,
`concierge prepare` exits with a non-actionable error, or there are
multiple `concierge` processes in `ps`.

**Fix.**

```bash
# Kill any stale concierge processes (concurrent prepares can
# deadlock the snap and apt locks).
sudo pkill -9 -f /snap/concierge/

# Reinstall concierge from a clean revision.
sudo snap remove --purge concierge
sudo snap install --classic concierge
```

Then resume at step 4.

### 6. LXD-only failure (no LXD bridge, profile missing)

**Signal.**  `juju bootstrap` to LXD reports "no networks", or
`lxc list` errors with "no such bridge".

**Fix.**  LXD's `init` is idempotent and re-creates the default
bridge.  Easier than hand-editing the network.

```bash
sudo lxd init --auto
sudo snap restart lxd
juju bootstrap localhost lxd-controller
```

If `lxd init --auto` errors out, reinstall: `sudo snap remove
--purge lxd` then back to step 4.

### 7. Microk8s wedged (legacy installs only)

The current default substrate is the `k8s` snap, not `microk8s`,
but older dev machines may still have microk8s on them.  If
`microk8s status` hangs:

```bash
sudo microk8s stop
sudo microk8s reset --destroy-storage
# If reset hangs, fall back to:
sudo snap remove --purge microk8s
```

Then rebuild via concierge as in step 4.

## Looking *underneath* Juju — pod-layer diagnostics

The substrate above is *broken*; this section is for the inverse case
where the substrate is healthy but a charm's workload is misbehaving
in a way Juju's view doesn't explain.  Symptoms: unit shows `error`
or `lost` but the *reason* lives on the pod, the namespace events,
or the PVC.

**Reach for these only when**:

- Juju says the unit is `error` / `lost` and `juju debug-log`
  doesn't surface a hook traceback that explains why.
- A workload container is restarting in a loop and `juju ssh` lands
  in a *fresh* container (the previous one's logs are gone).
- A unit is stuck in `waiting` / `blocked` with a "waiting for
  storage" or "agent initialising" message that doesn't clear.

**Skip them when** Juju is showing a clean hook traceback (use
`iterate-fix`), or when the substrate itself is wedged (use the
sweep above).

The Juju model name is the Kubernetes namespace by convention — so
`juju status -m dev` and `kubectl get pods -n dev` see the same
deployment.

| Question | Command | What it tells you |
|---|---|---|
| Why is this pod restarting / pending / failing? | `kubectl describe pod -n <model> <pod>` | Container statuses, `lastState.terminated.reason` (OOMKilled / Error / ImagePullBackOff), recent events |
| What just happened in the namespace? | `kubectl get events -n <model> --sort-by=.metadata.creationTimestamp` | Time-ordered cluster signals — image pulls, scheduling failures, eviction notices |
| Pod-level status across the model | `kubectl get pods -n <model>` | Which pods are `Running` / `Pending` / `CrashLoopBackOff`; restart counts |
| What did the *crashed* container print before it died? | `kubectl logs -n <model> <pod> -c <container> --previous` | The previous container's stdout/stderr — gone from `juju ssh`, present in kubectl |
| Is storage stuck? | `kubectl describe pvc -n <model>` | PVC status, storage-class events, capacity / binding state |
| Resource pressure? | `kubectl top pod -n <model>` | Live CPU / memory per pod (requires metrics-server; on the canonical k8s snap it's an addon) |

These are **read paths only**.  None of them mutate the cluster.  The
agent surfaces them to the user via the Escalation script shape below
— hand the user a copy-paste block and resume work once they paste
back the output.

When the binary `cantrip-kdiag` is available (built from `src/cantrip-kdiag/`
or on PATH), prefer calling `k8s_diagnostics` directly rather than prescribing
raw `kubectl` commands to the user.  `k8s_diagnostics` surfaces pod/PVC/event/
metrics data in structured JSON and produces a concise summary — use it for:

- `CrashLoopBackOff` or `OOMKilled` — call `k8s_diagnostics(namespace=..., app=..., mode="summary")`
- Single-pod drilldown — call `k8s_diagnostics(namespace=..., pod=..., mode="pod")`
- Connectivity check — call `k8s_diagnostics(namespace=..., mode="preflight")`

The `kubectl` verbs below are still the right fallback when `cantrip-kdiag` is
absent or when the read paths above don't cover a specific question.  All reads
remain user-driven; write verbs (`kubectl delete`, `exec`, `apply`, `patch`)
are never agent-driven.

## Things you must NOT do

- **Never install Docker** (`apt install docker.io`, `snap install
  docker`, etc.).  The dev machine's policy is explicit: Docker
  conflicts with the k8s snap's bundled containerd and breaks the
  cluster.  `run_command` blocks all of these by package name.
- **Don't `kill -9` the bare `k8sd` or `containerd` process while
  snapd thinks they're healthy** — snapd will fight you.  Either
  abort the snap change first, or use `systemctl stop 'snap.k8s.*'`
  which goes through snapd's own service control.
- **Don't re-run `concierge prepare` without `restore` first** when
  there's already a half-broken provider.  Prepare isn't fully
  idempotent; it can make things worse.
- **Don't change the user's git remote URL** (the user's standing
  rule — they use SSH, and `gh` commands sometimes silently rewrite
  it to HTTPS).
- **Don't hand-edit `/etc/kubernetes/...` config** to recover a
  broken cluster.  On a dev box, rebuild beats surgery every time.
- **Don't run `kubectl delete`, `kubectl apply`, `kubectl exec`, or
  `kubectl patch`** as part of debugging a charm.  The pod-layer
  read paths above (`describe`, `logs --previous`, `get events`,
  `get pods`, `describe pvc`, `top`) are safe to suggest; writes
  duplicate Juju's contract and risk lying to the controller about
  what the cluster looks like.  Escalate write-shaped recoveries
  to the user the same way `sudo` steps escalate.

## Escalation script

If the agent can't run a step (sudo is required, or the destructive
policy isn't approved), give the user a copy-pasteable block instead
of a vague description.  The transcript shape that works:

> **What I found:** k8s snap's containerd is deadlocked on boltdb
> open (see `journalctl -u snap.k8s.containerd`), apt-installed
> docker.io is fighting it for `/run/containerd/containerd.sock`,
> and snap change 4595 has been stuck in `Doing` for ~6 hours.
>
> **What needs to happen:** purge the apt docker, kill the stuck
> snap change, remove the k8s snap cleanly, then rebuild.
>
> **Run these (sudo required):**
>
> ```bash
> sudo systemctl stop docker.socket docker.service containerd.service
> sudo apt-get purge -y docker.io containerd
> sudo apt-get autoremove -y
> sudo rm -rf /var/lib/containerd /var/lib/docker
> sudo concierge restore
> sudo concierge prepare -p dev
> ```
>
> I'll resume work as soon as `juju status` returns cleanly.

## After the rebuild — sanity checks

Once `concierge prepare` finishes, verify the substrate is healthy
before resuming charm work:

```bash
juju controllers           # at least one healthy controller
juju status                # in the default model: model exists, no errors
juju add-model dev         # (or whatever name the user uses)
df -h /                    # should be back below 50% on a fresh box
```

If any of those still fail, loop back to the diagnostic sweep — the
rebuild should not be a guess-and-check operation.

## What this skill is *not*

- Not a charm-debug guide.  Use `iterate-fix` when the substrate is
  fine and an individual charm is misbehaving.
- Not a production runbook.  These are dev-machine recoveries; on
  production, surgical fixes and proper change control matter and
  this playbook is too aggressive.
- Not a Docker how-to.  Docker is explicitly off-limits on the dev
  machine; the agent never installs it.
