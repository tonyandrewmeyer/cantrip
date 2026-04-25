Write clean, well-structured code following ops framework conventions. Include COS integration, and follow the charm type path (PaaS, custom, or infrastructure) as appropriate.

**Red/green cycle**: follow an integration-tests-first approach.
1. Read the design and any existing files (including integration tests if they already exist) in one round.
2. If integration tests do not exist yet, run `generate_tests` to scaffold Jubilant-based integration tests from charmcraft.yaml, then customise them to match the design. Alternatively, write them from scratch — derive test cases from the approved design: each relation endpoint gets a deploy+relate test, each action gets an execute test, each config option gets a set+verify test, and COS integration gets a relation test. Use Jubilant patterns. These tests define the external contract and are expected to fail initially (red).
3. Write charm code (src/charm.py, Pebble layers, integrations, config) targeting the integration tests (green).
4. Run `run_charm_tests` with `test_type='integration'` to check progress. Use the `pattern` parameter to target specific failing tests for faster iteration (e.g. `pattern='test_deploy'`).
5. If tests fail, read the output, fix the code, and re-run. Iterate until integration tests pass or you exhaust your rounds.
6. Write unit tests using Scenario (ops.testing) for edge cases and error paths that integration tests cannot easily cover: missing relations → BlockedStatus, invalid config → error handling, Pebble not ready → WaitingStatus.

**Efficiency**: write multiple files in a single round when they are independent. Do not re-read files you just wrote.

**Packing during iteration**: when you need a fresh `.charm` to run integration tests or exercise install/upgrade hooks, prefer `quick_pack` (skips LXD, linting, analysis — 2–5× faster).  Fall back to `charmcraft_pack` if the charm uses a plugin other than `uv`/`dump`, any `override-*` part key, or lacks a `uv.lock`.  `charm_validate` (below) invokes `charmcraft pack` itself, so you don't need a separate full pack before finishing.

**Version control**: before finishing, use `git_add` to stage your changes and `git_commit` with a descriptive message summarising what was built. Every build task should leave a clean commit.

**Self-check**: before finishing, run `charm_validate` to verify the charm packs and tests pass. If validation fails, fix and re-validate; if it still fails after a second attempt, stop and report the failure with what you tried — do not loop a third time. Do not report success if validation fails.

**Self-review**: before finishing, also call `load_skill` twice — once for `security-review` and once for `find-bugs` — and walk the checks against the files you wrote or modified in this task. Apply HIGH-confidence fixes yourself and re-run `charm_validate`; surface HIGH findings in your output so the user sees them. Skip this for trivial edits (docstring-only, renames) and for any non-code tasks. Do not double-report issues that `charm_validate` or `charmlint` already flagged.

**Security event logging**: if the design identifies a security surface, generate a `src/log_security.py` helper that emits structured OWASP-format security events (JSON with datetime, appid, type, event, level, description). Call it from charm event handlers at the appropriate points (secret hooks, relation changes, action handlers). Never log sensitive data.

**Tracing**: ops-tracing handles hook/Pebble/relation spans automatically. Only add manual spans for long-running workload operations (backups, migrations), external API calls, and decision logic with fallback paths. Do not span simple Pebble or relation handlers.

**Cross-model COS**: when COS is on a separate controller (LXD dev + K8s COS), use `juju_offer` and `juju_consume` to wire observability across models. For machine charms, deploy `grafana-agent` (snap-based) locally; for K8s charms, use `grafana-agent-k8s` (sidecar). Integration tests should verify COS relations settle even in cross-model setups.
