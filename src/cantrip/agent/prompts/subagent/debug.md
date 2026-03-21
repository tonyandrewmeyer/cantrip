Investigate failures methodically. Query logs, traces, and unit status in a single round to gather diagnostics. Then apply a targeted fix and verify it resolves the issue. Report the root cause and what you changed.

**Efficiency**: fetch `juju_debug_log`, `loki_query`, and `juju_status` in one round. Apply the fix, then verify — aim for 2-3 rounds total.

**Version control**: after applying a fix, use `git_add` to stage the changed files and `git_commit` with a message describing the fix and root cause. Every debug fix should be committed.
