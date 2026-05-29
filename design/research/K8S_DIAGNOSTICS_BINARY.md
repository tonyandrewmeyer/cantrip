# Go Kubernetes Diagnostics Binary (`cantrip-kdiag`)

> Design for a small, read-only Kubernetes diagnostics helper that gives
> Cantrip first-class pod-layer visibility when Juju's model view is not
> enough.

## TL;DR

- **Problem:** Cantrip can diagnose Juju-layer failures well, but when a
  charm is broken at the Kubernetes layer (`CrashLoopBackOff`,
  `ImagePullBackOff`, `OOMKilled`, PVC binding failure, namespace event
  storm), the agent currently falls back to prescribing `kubectl`
  commands rather than answering the question itself.
- **Decision:** Ship a **small Go binary**, `cantrip-kdiag`, that talks to
  the Kubernetes API directly via `client-go`, gathers a bounded set of
  read-only diagnostics, and returns **structured JSON** that a typed
  Python tool can surface to the agent.
- **Why Go:** Kubernetes is a Go-first ecosystem; `client-go` is the
  canonical client, static binaries are easy to ship, streaming and JSON
  handling are straightforward, and the binary becomes an isolated,
  testable unit rather than spreading kube-specific plumbing throughout
  the Python codebase.
- **Initial scope:** namespace/pod/PVC/event/metrics inspection only.  No
  writes, no `exec`, no `port-forward`, no generic `kubectl` wrapper.

## 1. Context

[`design/K8S_TOOL.md`](K8S_TOOL.md) recorded the gap and explicitly
deferred a typed implementation until a real trigger appeared.  That
trigger has now fired: a user asked for a valuable feature that would be
well suited to a Go binary, and the Kubernetes diagnostic gap is the best
fit.

The existing state:

- Cantrip already has strong **Juju-native** tooling.
- The `fix-broken-juju-k8s` skill now documents the right `kubectl`
  read-only verbs.
- `tools/preflight.py` can probe whether `kubectl` exists and whether the
  chosen context is configured.
- There is **no first-class pod-layer diagnostic tool** in the agent.

The binary proposed here closes that gap without turning Cantrip into a
general Kubernetes shell.

## 2. Goals

### 2.1 Primary goals

1. Let the agent answer "**what is broken at the pod layer?**" without
   asking the user to run `kubectl` manually.
2. Keep the surface **read-only, bounded, and charm-focused**.
3. Return **structured JSON**, not scraped terminal text.
4. Make the helper useful both to **the agent** and to a human operator
   debugging from a terminal.
5. Keep the implementation small enough to be a realistic first Go
   subsystem in Cantrip.

### 2.2 Non-goals

- Not a `kubectl` replacement.
- Not a write path (`apply`, `delete`, `patch`, `exec`, `scale`).
- Not a cluster-admin observability suite.
- Not a generic multi-cluster fleet debugger.
- Not a second orchestration backend that bypasses Juju for ordinary charm
  work.

## 3. Why a binary, and why Go

Three implementation shapes were plausible:

| Shape | Pros | Cons | Verdict |
|---|---|---|---|
| Python tool calling `kubectl` | Smallest initial change | Text parsing, kubeconfig/process quirks, poor structure, shells out repeatedly | Reject |
| Python tool using Kubernetes Python client | Single-language implementation | Adds heavy Python-side dependency and kube API plumbing to the main app; weaker fit to the ecosystem | Reject |
| **Go binary using `client-go`** | Canonical K8s client, easy static build, crisp JSON contract, strong separation | Introduces a second implementation language | **Keep** |

Go is the best fit here because the hard part is not UI or prompt logic;
it is **bounded cluster inspection**.  The Kubernetes ecosystem has
already solved that in Go.

## 4. Product shape

`cantrip-kdiag` is a command-line program that:

1. Loads kubeconfig / context.
2. Queries a namespace and optional charm-scoped target.
3. Collects a small, fixed set of diagnostics.
4. Emits a deterministic JSON report.
5. Exits with a small, documented exit-code set.

Cantrip's Python layer will then wrap that binary in one or more typed
tools.

## 5. Initial command surface

The first release should stay deliberately small.

### 5.1 Commands

#### `summary`

The main entry point.  Returns a one-shot namespace or workload summary.

Example:

```bash
cantrip-kdiag summary \
  --namespace dev \
  --app redis-k8s \
  --previous-logs 80 \
  --events 40 \
  --format json
```

Responsibilities:

- list matching pods
- report restart counts and readiness
- surface waiting / terminated reasons
- include recent warning events
- include PVC state for matching workloads
- include a metrics snapshot when available
- include bounded `previous` log tails for crashed containers

#### `pod`

Narrow, pod-specific drilldown.

Example:

```bash
cantrip-kdiag pod --namespace dev --pod redis-k8s-0 --previous-logs 120
```

Responsibilities:

- return one pod's detailed state
- include container statuses
- include relevant events
- include previous logs per crashed container

#### `preflight`

Cheap readiness check for the Python side and for humans.

Example:

```bash
cantrip-kdiag preflight --context my-cluster --format json
```

Responsibilities:

- confirm kubeconfig exists and is readable
- confirm selected context exists
- confirm API server is reachable
- report whether metrics API is available

### 5.2 Shared flags

All commands should support:

- `--kubeconfig <path>`
- `--context <name>`
- `--namespace <name>` where applicable
- `--format json|text` (`json` authoritative; `text` human convenience)
- `--timeout <duration>` (default short and explicit)

`summary` should additionally support:

- `--app <juju-app-name>`
- `--unit <juju-unit-name>`
- `--pod <pod-name>` as an exact filter
- `--events <N>`
- `--previous-logs <N>`
- `--include-metrics`

## 6. Data collection model

The binary should collect only the six read-only diagnostic categories
already justified by `design/K8S_TOOL.md`:

1. **Pods** — phase, readiness, restarts, node, owner references.
2. **Container states** — waiting reason, terminated reason, exit code,
   last termination, image.
3. **Events** — recent namespace events, prioritising warnings.
4. **PVCs** — claim phase, storage class, capacity/binding signals.
5. **Previous logs** — bounded tail for previously crashed containers.
6. **Metrics** — pod CPU/memory only when the metrics API is present.

### 6.1 Targeting rules

The binary should not assume every pod name matches the Juju unit name
cleanly.  The target resolver should therefore accept three levels:

1. **Exact pod** (`--pod`) — strongest signal.
2. **Juju app / unit** (`--app`, `--unit`) — use labels / owner refs where
   possible, then fall back to name-prefix heuristics.
3. **Whole namespace** (`summary --namespace dev`) — for broad triage.

The Python wrapper can translate Juju concepts into the right filter
inputs for the binary.

## 7. Output contract

JSON is the real interface; text mode is a rendering of the same data.

### 7.1 Top-level summary shape

```json
{
  "schema_version": 1,
  "generated_at": "2026-04-30T11:00:00Z",
  "context": {
    "kubeconfig": "/home/user/.kube/config",
    "context": "dev-cluster",
    "namespace": "dev"
  },
  "query": {
    "app": "redis-k8s",
    "unit": null,
    "pod": null
  },
  "metrics_available": true,
  "pods": [],
  "pvcs": [],
  "events": [],
  "warnings": [],
  "summary": {
    "pod_count": 1,
    "ready_pods": 0,
    "restarting_pods": 1,
    "warning_event_count": 3,
    "pvc_pending_count": 0
  }
}
```

### 7.2 Pod shape

Each pod entry should include enough detail for the agent to explain the
problem without another tool call:

```json
{
  "name": "redis-k8s-0",
  "phase": "Running",
  "ready": false,
  "restart_count": 6,
  "node": "worker-0",
  "owner_kind": "StatefulSet",
  "owner_name": "redis-k8s",
  "labels": {
    "app.kubernetes.io/name": "redis"
  },
  "containers": [
    {
      "name": "redis",
      "image": "ghcr.io/example/redis:1.2.3",
      "ready": false,
      "restart_count": 6,
      "state": "waiting",
      "waiting_reason": "CrashLoopBackOff",
      "terminated_reason": "Error",
      "last_exit_code": 1,
      "previous_log_tail": [
        "Fatal: invalid configuration file"
      ]
    }
  ]
}
```

### 7.3 Warning synthesis

The binary should emit a small `warnings` array with deterministic,
machine-friendly summaries such as:

- `pod redis-k8s-0 container redis waiting: CrashLoopBackOff`
- `pod redis-k8s-0 container redis last termination: OOMKilled`
- `pvc data-redis-k8s-0 phase Pending`
- `warning event FailedScheduling for pod redis-k8s-0: 0/1 nodes available`

This is not an LLM narrative.  It is a stable shortlist that helps the
Python tool produce a concise caption.

## 8. Error handling and exit codes

The binary should fail crisply and early.

Suggested exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `2` | Invalid CLI usage / flag validation |
| `3` | Kubeconfig missing or unreadable |
| `4` | Context missing / invalid |
| `5` | API server unreachable / auth failure |
| `6` | Namespace or target not found |
| `7` | Metrics requested but unavailable |
| `10` | Internal error |

JSON mode should still emit a structured error object on failures the
caller can recover from:

```json
{
  "schema_version": 1,
  "error": {
    "code": "context_not_found",
    "message": "Context 'dev-cluster' not found in kubeconfig."
  }
}
```

## 9. Safety model

The safety boundary is the whole point of this design.

Rules:

- **Read-only API calls only.**
- No SPDY / exec sessions.
- No mutations.
- No arbitrary resource kind parameter.
- No "run raw kubectl args" escape hatch.
- Bounded logs and events by count.
- Short default timeouts.

This keeps the binary aligned with Cantrip's existing "diagnose, do not
freelance surgery" posture for Kubernetes problems.

## 10. Integration with Cantrip

### 10.1 Python wrapper tool

The implementation phase should add a new Python tool module, likely
`src/cantrip/agent/tools/k8s.py`, with a typed wrapper such as:

- `k8s_diagnostics`
- optionally later `k8s_pod_diagnostics`

The wrapper should:

1. Resolve kubeconfig/context inputs.
2. Invoke `cantrip-kdiag` directly via `subprocess.run` rather than the
   bwrap sandbox, following the same pattern used for Juju-native tools.
3. Parse the JSON.
4. Convert the report into a `ToolResult` with:
   - concise `output`
   - full structured `data`
   - `success=False` on recoverable diagnostic failures

### 10.2 Skill and prompt wiring

The existing `fix-broken-juju-k8s` skill should remain the broader
substrate-recovery playbook.  The new tool is for the narrower "pod layer
is unhealthy but the cluster is up" case.

Prompt/skill guidance should teach the agent:

- use Juju tools first for ordinary charm diagnosis
- call `k8s_diagnostics` when Juju does not explain pod-level failure
- prefer the typed tool over prescribing raw `kubectl` when the binary is
  available

### 10.3 Preflight

`tools/preflight.py` already knows how to probe kubeconfig/context via
`kubectl`.  That remains acceptable for generic environment checks, but a
follow-up can add a `cantrip-kdiag preflight` path so the same binary
contract is exercised end to end.

That preflight integration is desirable but **not required for v1**.

## 11. Repository layout

To mirror the existing native-helper pattern:

```text
src/
  cantrip-kdiag/
    go.mod
    cmd/
      cantrip-kdiag/
        main.go
    internal/
      cli/
      kube/
      collect/
      summarise/
      output/
```

Suggested package responsibilities:

- `internal/cli` — Cobra command setup and flag validation.
- `internal/kube` — client creation, kubeconfig/context loading.
- `internal/collect` — pods/events/PVCs/logs/metrics fetchers.
- `internal/summarise` — warning synthesis and report shaping.
- `internal/output` — JSON/text encoders.

## 12. Implementation notes for a first Go subsystem

This is a good learning-sized Go project because it touches the language's
strengths without demanding a giant architecture.

Suggested implementation choices:

- **CLI:** `cobra`
- **Kubernetes client:** `client-go`
- **JSON:** stdlib `encoding/json`
- **Tests:** stdlib `testing` + fake clients where practical
- **Contexts/timeouts:** `context.WithTimeout`
- **Log tails:** use the pod log API with `TailLines`

Keep the code explicit rather than clever.  The design value is in the
clear contract and bounded behaviour, not in abstracting every collector.

## 13. Rollout plan

### 13.1 v1

- `summary`, `pod`, `preflight`
- JSON output contract
- pods/events/PVCs/previous logs/metrics
- one Python wrapper tool
- skill/prompt guidance update

### 13.2 Plausible later extensions

- watch mode for live triage
- screenshots or richer rendered summaries in the TUI/Web UI
- namespace event diffing over time
- richer Juju-to-pod correlation helpers

These are explicitly out of scope for the first implementation phase.

## 14. Test strategy

The implementation phase should cover three layers:

1. **Go unit tests** for targeting, warning synthesis, and output shape.
2. **Go fake-client tests** for pods/events/PVC/metrics collection.
3. **Python tool tests** that mock subprocess output and validate
   `ToolResult` shaping, error propagation, and missing-binary handling.

The important regressions are:

- mis-targeting the wrong pod
- silently widening scope beyond read-only
- unstable JSON shape
- bad handling of missing kubeconfig or context
- previous-log collection exploding on healthy pods

## 15. What this design is not

- Not a plan to rewrite other Cantrip subsystems in Go.
- Not an argument against the existing Rust helpers.
- Not a generic "native backends everywhere" push.
- Not a requirement that every operator install Go; the implementation
  phase will decide packaging/distribution details.

## 16. Phase hook

The implementation work should land as a dedicated roadmap phase:

- binary implementation in Go
- Python typed-tool integration
- skill/prompt updates
- tests and docs

That phase should treat this document as its source of truth and
`design/K8S_TOOL.md` as the earlier research rationale.
