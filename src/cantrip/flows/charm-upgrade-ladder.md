---
name: charm-upgrade-ladder
type: flow
description: Walk a charm author through the SUPPORTED → DEPRECATED → REMOVED upgrade ladder for breaking changes, including the rollback branch.
---

# Charm upgrade ladder

When a charm needs to break a contract — rename a relation, drop
a config option, change a default — the right answer is rarely a
single release.  The ladder is three releases (or more) with
explicit deprecation periods so operators upgrading from N-2 land
on documented warnings rather than silent breakage.

This flow walks the decision tree for a single breaking change.
Run it once per change; multiple breaking changes in the same
release are independent decisions on the same ladder.

```mermaid
flowchart TD
    classify[Classify the breaking change]
    severity{High operator impact?}
    deprecation{Already on N-1?}
    n_minus_1[Ship N-1 with deprecation warning]
    n[Ship N with the breaking change]
    rollback{Rollback path safe?}
    document_rollback[Document the rollback procedure]
    block_n[Block N — no rollback path]
    n_minus_2_check{Operators on N-2?}
    extend[Extend deprecation by one release]
    publish[Publish release notes + migration guide]
    monitor[Monitor for upgrade reports]
    fail(Refuse — needs author input)
    done(Done — change shipped)

    classify --> severity
    severity -->|yes| deprecation
    severity -->|no| n
    deprecation -->|yes| rollback
    deprecation -->|no| n_minus_1
    n_minus_1 --> n_minus_2_check
    n_minus_2_check -->|yes| extend
    n_minus_2_check -->|no| rollback
    extend --> n_minus_1
    rollback -->|yes| document_rollback
    rollback -->|no| block_n
    document_rollback --> n
    block_n --> fail
    n --> publish
    publish --> monitor
    monitor --> done

    %% classify: Describe the breaking change in one sentence. Capture what changes, what operators need to do, and whether downstream charms in the ecosystem depend on the old behaviour.
    %% severity: Is the change visible to operators (CLI flags, config, relation interfaces, action shapes)? Pick "yes" for any user-visible contract change; "no" for purely internal refactors.
    %% deprecation: Has a previous release shipped with a deprecation warning for this change? Pick "yes" if the warning has been live for at least one stable release; "no" if this is the first release to flag the change.
    %% n_minus_1: Ship the next release with a deprecation warning logged on every charm hook that hits the affected path. The warning must name the upgrade ladder explicitly so operators see when the breaking change lands.
    %% n_minus_2_check: Use Charmhub metrics or operator surveys to check whether any tracked deployment is still on N-2 (two releases behind). Pick "yes" if the metric is non-zero; "no" if the floor has rolled forward.
    %% extend: Defer the breaking change for one more release. The deprecation warning continues to ship; N-2 operators get another release cycle to upgrade.
    %% rollback: Check whether an operator who upgrades and hits the breaking change can roll back to the previous version cleanly. Stateful charms with on-disk data migrations often cannot.
    %% document_rollback: Write the rollback procedure into the release notes and a docs/upgrade-from-N-1.md page. Include the exact juju refresh --revision command.
    %% block_n: Refuse to ship the breaking change in this release. A change without a rollback path needs the rollback engineered first; revisit when the data migration is reversible.
    %% n: Ship the release with the breaking change applied. The deprecation warning becomes an error path; the affected hooks fail loudly if operators didn't upgrade.
    %% publish: Publish release notes, the migration guide, and (if the change is wide enough) a discourse post on the Juju forum. The migration guide must list every command an operator runs to upgrade.
    %% monitor: Watch the operator reports for one release cycle. If multiple operators report the same migration friction, prioritise an N+1 release with documentation fixes.
    %% fail: Refuse — the change cannot ship safely on this ladder. Loop back when the rollback path is engineered or the breaking change is broken into safer sub-steps.
    %% done: The breaking change is on Charmhub, the migration guide is published, and the deprecation warning has been removed from N-1 / N-2 codepaths.
```
