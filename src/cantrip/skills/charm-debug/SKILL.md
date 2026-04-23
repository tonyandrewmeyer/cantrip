---
name: charm-debug
description: Systematic diagnosis of a running charm — status, logs, relation data, config, and secrets — followed by a symptom-to-fix table
---

# Charm Debugging

Use this skill when the user reports that a deployed charm is stuck,
misbehaving, or not doing what they expect. It prescribes a fixed
inspection order so you always gather the same evidence before
proposing a fix — and a symptom → likely-cause → next-action table so
your first response after the inspection is already pointed at
something concrete.

This is a **read-only** skill. It does not touch the charm's code,
the deployment, or the user's git tree. If you want to change
anything after diagnosis, hand back to the normal build/improve flow.

## When to load

- The user says "my charm is stuck", "pods keep crashing",
  "relation not working", "nothing happens after config change", or
  similar diagnostic phrasing.
- `juju_status` shows a unit in `blocked`, `waiting`, `error`, or
  `maintenance` for longer than a typical reconcile cycle.
- You are asked to "investigate", "look at", or "diagnose" an
  existing deployment.

If the user asks you to *fix* something without diagnosing first,
still do one inspection pass — the fix is usually different depending
on what the evidence shows.

## The five-step inspection

Do these in order. Later steps depend on what the earlier ones
produce, so do not skip around.

### 1. Status

Call `juju_status`. Note for each application:

- Workload status (`active`, `blocked`, `waiting`, `maintenance`,
  `error`) and the **message** beside it (the charm's own string).
- Agent status (`executing`, `idle`, `error`).
- Unit count vs. expected scale; any missing units.
- For K8s charms: container statuses — `waiting`, `running`,
  `not-ready`.

The status *message* is the single highest-signal datum. Charms
encode their own diagnosis into it ("waiting for database relation",
"bad TLS cert", "config 'log-level' must be one of …"). Read it
literally before looking at anything else.

### 2. Logs

Call `juju_debug_log` (or `juju_stream_logs` if the issue is
currently recurring) scoped to the affected unit. Scan for:

- `ERROR` or `CRITICAL` lines.
- Uncaught Python exceptions (`Traceback`, `raise`).
- Repeated hook failures — Juju retries failed hooks; a loop of
  `ran "install" hook` failures is a diagnostic in itself.
- Pebble errors on K8s (`pebble: unable to connect`, `service …
  exited`).
- Relation-changed hooks firing with empty databags (often means the
  partner charm is the broken side, not this one).

When the issue is intermittent, use `juju_stream_logs` with a narrow
include filter and reproduce it.

### 3. Relation data

For any relation the status message mentions (or any relation you
suspect is empty/stale): call `juju_read_relation_data` for both
sides.

Check:

- The databag you expect to exist actually exists. A missing
  endpoint in status usually means the user forgot
  `juju integrate`; empty databag with both sides integrated means
  the provider never wrote.
- App databag is written by the **leader only**; confirm which unit
  is leader (`juju_status` shows `*` on the leader) before blaming
  "app data is empty".
- JSON-encoded values parse. Garbage in the databag means a partner
  charm is writing the wrong shape; escalate to the partner's log.
- Secret references (`secret://…` or `secret:id=…`) resolve —
  dangling ids mean the owning charm rotated and didn't update the
  databag.

### 4. Config

Call `juju_get_app_config`. Compare against:

- The `charmcraft.yaml` `config.options` defaults — a value
  equalling the default usually means the user forgot to set it.
- Any value mentioned in the status message ("bad config: X") —
  confirm the live value actually differs from the default.
- Cross-charm coherence (workspace charms): check the
  `shared_config` section of `cantrip.workspace.yaml` if present.
  A mismatch between two charms on `log_level` or `tls_mode` is a
  classic cross-charm bug.

### 5. Secrets

Call `juju_list_secrets` and, for any secret the relation data
references, `juju_show_secret`. Check:

- Ownership — the charm that wrote a databag reference to a secret
  should be the secret's owner.
- `latest-revision` vs. the one named in the databag — if the
  secret rotated but the databag still references the old
  revision, the consuming charm will 403 on read.
- Grant lists — a grant-less secret cannot be read by relation
  partners.

## Symptom → cause → action

Use this table after inspection to translate what you saw into your
first fix proposal. If the evidence matches more than one row,
propose the cheaper fix first.

| Symptom (from inspection) | Likely cause | Next action |
| --- | --- | --- |
| Status `blocked`, message names a relation | Missing or broken `juju integrate` | Confirm the relation exists; if missing, `juju_relate`; if present, jump to the partner charm's side |
| Status `waiting` with "for Pebble" | K8s container crashloop or image pull failure | `juju_ssh` / check Pebble services; inspect the OCI image tag in `juju_status` |
| Status `active` but workload not working | Charm's `_on_collect_status` is too permissive | Read `src/charm.py` — find the status-setting path and check whether it gates on workload reachability |
| `error` status with exception in log | Hook raised uncaught; Juju retries | Read the traceback; if it's a config-validation error, fix config; otherwise flag as a charm bug |
| Repeating `update-status` failures | Long-running workload check, Pebble timeout | Look for Pebble `exec` calls without a timeout; recommend the fix in the `find-bugs` skill |
| Relation data empty on both sides | Provider never wrote; often not leader | Check which unit is leader; confirm leader-elected event fired; look for "not leader" guards in the writer |
| Relation data populated but partner doesn't act | Consumer's library hasn't been bumped | Check `lib/charms/<provider>/vN/<library>.py` version on consumer side |
| Secret reference in databag fails to read | Rotation without databag update, or no grant | Check `juju_show_secret` grants; if rotation is the cause, recommend re-emitting the databag value |
| `maintenance` status persisting | Long-running install or upgrade; or a dropped status update | Check the log for the expected `ActiveStatus` that didn't fire; often a raised exception mid-hook |
| Config change "does nothing" | Charm has no `_on_config_changed`, or the handler early-returns | Grep `src/` for `config_changed`; check the reconciliation path |
| Workload status is wrong on K8s sidecar after pod restart | Status not recomputed on `pebble_ready` | Confirm `_on_pebble_ready` calls `_reconcile()` or sets status explicitly |

## Inspection report format

Summarise your findings in this shape before proposing fixes:

```
## Inspection of <app>/<unit>

**Status:** <workload status>/<agent status> — "<charm message>"
**Scale:** <actual>/<expected> units
**Most recent error in log:** <quoted line or 'none'>
**Relation health:**
- <endpoint>: <populated | empty | missing | error>
**Config divergence from defaults:** <list, or 'none'>
**Secret health:** <ok | grant missing | stale revision | n/a>

## Likely cause

<one or two sentences pointing at the row of the symptom table>

## Proposed next action

<a specific tool call or user step, not generic advice>
```

Keep each line under 100 characters — this goes into chat, not a
dashboard.

## References

- `find-bugs` skill — the bug classes you find during inspection
  map onto the checks there.
- `observability` skill — for deployments with COS, follow traces
  (Tempo) and log queries (Loki) alongside `juju_debug_log`.
- `relation-data-design` skill — the shape databags *should* have;
  diagnose divergence from that shape.
- `charm-improvement` skill — if the diagnosis motivates a broader
  rewrite, hand back to the improvement flow instead of fixing ad
  hoc.
- `juju_status`, `juju_debug_log`, `juju_read_relation_data`,
  `juju_get_app_config`, `juju_list_secrets`, `juju_show_secret`,
  `juju_stream_logs` — the read-only tools this skill sequences.
