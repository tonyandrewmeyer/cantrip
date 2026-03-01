---
name: performance
description: Identifying and fixing common charm performance issues
---

# Charm Performance

This skill covers identifying, diagnosing, and fixing common performance issues in Juju charms.

## Common Performance Pitfalls

### 1. Blocking I/O in Hook Handlers

**Problem:** Synchronous network calls, disk I/O, or database queries in event handlers block the Juju agent, causing hook timeouts and degraded responsiveness.

**Symptoms:**
- Hook executions exceeding 5 seconds (visible in Tempo traces)
- `juju debug-log` showing slow hook completions
- Unit agent status stuck in `executing`

**Fix:**
- Use `subprocess.run` with timeouts for external calls
- Set reasonable connect and read timeouts on HTTP clients
- For long-running operations, use Juju actions instead of config-changed hooks
- Consider breaking large operations into multiple events using deferred events

### 2. Expensive Status Polling

**Problem:** The `update-status` hook runs every 5 minutes by default. If it performs expensive checks (HTTP requests, database queries, subprocess calls), it wastes resources.

**Symptoms:**
- High CPU/memory usage correlating with 5-minute intervals
- Tempo traces showing slow `update-status` executions
- Loki logs showing repeated connection attempts

**Fix:**
- Cache status check results with a TTL
- Use lightweight health checks (TCP connect vs full HTTP request)
- Avoid querying external services in `update-status` — rely on Pebble checks instead
- For K8s charms, configure Pebble health and readiness checks rather than polling manually

### 3. Oversized Relation Data

**Problem:** Storing large data blobs in relation data bags causes slow relation-changed events and increases memory usage across all related units.

**Symptoms:**
- Slow `relation-changed` hook executions
- High memory usage on units with many relations
- Juju debug-log showing large data transfers

**Fix:**
- Keep relation data under 1 KB per key
- Store large data externally (S3, database) and share only references via relations
- Use `relation.data[self.unit]` for unit-specific data, not app-level data
- Compress data if it must be in the relation bag

### 4. Large Hook Payloads

**Problem:** Hooks that read or write large files, process large configs, or generate large outputs slow down the charm lifecycle.

**Symptoms:**
- Slow `config-changed` or `install` hooks
- Tempo traces showing long file I/O spans
- High disk I/O during hook execution

**Fix:**
- Stream large files instead of reading them entirely into memory
- Use Pebble file push/pull for container file operations
- Validate config size limits before processing
- Write files incrementally rather than all at once

### 5. Unoptimised Pebble Interactions

**Problem:** Excessive Pebble API calls (plan updates, file pushes, service restarts) in every hook execution.

**Symptoms:**
- Frequent unnecessary container restarts
- Tempo traces showing many Pebble API calls per hook
- Workload instability from repeated restarts

**Fix:**
- Check the current Pebble plan before updating — only push if it changed
- Batch file pushes into a single operation
- Use `container.replan()` instead of `stop()` + `start()`
- Guard service restarts with `container.get_service(name).is_running()`

## Profiling with Tempo

Use `tempo_query` to identify slow hook executions:

```
tempo_query(
    cos_model="cos",
    service_name="<charm-name>",
    min_duration="2s"
)
```

This finds all hook executions taking longer than 2 seconds. Look for:
- Which hooks are slowest (install, config-changed, relation-changed, update-status)
- Which spans within a hook take the most time
- Whether slow hooks are consistent or intermittent

## Hook Execution Benchmarks

| Hook | Acceptable | Warning | Critical |
|------|-----------|---------|----------|
| `install` | < 30s | 30-60s | > 60s |
| `start` | < 5s | 5-15s | > 15s |
| `config-changed` | < 5s | 5-15s | > 15s |
| `update-status` | < 2s | 2-5s | > 5s |
| `relation-changed` | < 5s | 5-15s | > 15s |
| `pebble-ready` | < 10s | 10-30s | > 30s |
| Actions | < 30s | 30-120s | > 120s |

## Timing Analysis with Debug Log

Use `juju_debug_log` to analyse hook timing:

```
juju_debug_log(model="<dev_model>", unit="<unit_name>", level="DEBUG", lines=200)
```

Look for patterns:
- Time between "running hook" and "hook completed" entries
- Repeated error messages indicating retry loops
- Long gaps between log entries (indicating blocking operations)

## Pebble Check Performance

For K8s charms, configure efficient health checks:

```python
# Good: lightweight TCP check
"health": {
    "override": "replace",
    "level": "alive",
    "tcp": {"port": 8080},
    "period": "30s",
}

# Good: fast HTTP endpoint
"ready": {
    "override": "replace",
    "level": "ready",
    "http": {"url": "http://localhost:8080/health"},
    "period": "30s",
    "timeout": "5s",
}
```

Avoid:
- Health checks that query databases or external services
- Checks with periods shorter than 10 seconds
- Checks without explicit timeouts

## Best Practices Summary

1. **Measure first** — use Tempo and debug-log to identify actual bottlenecks
2. **Cache expensive results** — avoid repeating work across hook invocations
3. **Keep relation data small** — store references, not payloads
4. **Guard against unnecessary restarts** — check before acting
5. **Use appropriate hooks** — long operations belong in actions, not config-changed
6. **Set timeouts everywhere** — network calls, subprocess calls, Pebble operations
7. **Profile regularly** — hook performance degrades as charms grow in complexity
