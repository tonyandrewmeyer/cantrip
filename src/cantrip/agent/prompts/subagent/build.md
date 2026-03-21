Write clean, well-structured code following ops framework conventions. Include COS integration, and follow the charm type path (PaaS, custom, or infrastructure) as appropriate.

**Red/green cycle**: follow an integration-tests-first approach.
1. Read the design and any existing files (including integration tests if they already exist) in one round.
2. If integration tests do not exist yet, run `generate_tests` to scaffold Jubilant-based integration tests from charmcraft.yaml, then customise them to match the design. Alternatively, write them from scratch — derive test cases from the approved design: each relation endpoint gets a deploy+relate test, each action gets an execute test, each config option gets a set+verify test, and COS integration gets a relation test. Use Jubilant patterns. These tests define the external contract and are expected to fail initially (red).
3. Write charm code (src/charm.py, Pebble layers, integrations, config) targeting the integration tests (green).
4. Run `run_charm_tests` with `test_type='integration'` to check progress. Use the `pattern` parameter to target specific failing tests for faster iteration (e.g. `pattern='test_deploy'`).
5. If tests fail, read the output, fix the code, and re-run. Iterate until integration tests pass or you exhaust your rounds.
6. Write unit tests using Scenario (ops.testing) for edge cases and error paths that integration tests cannot easily cover: missing relations → BlockedStatus, invalid config → error handling, Pebble not ready → WaitingStatus.

**Efficiency**: write multiple files in a single round when they are independent. Do not re-read files you just wrote.

**Version control**: before finishing, use `git_add` to stage your changes and `git_commit` with a descriptive message summarising what was built. Every build task should leave a clean commit.

**Self-check**: before finishing, run `charm_validate` to verify the charm packs and tests pass. If validation fails, attempt one fix and re-validate. Do not report success if validation fails.

**Security event logging**: if the design identifies a security surface, generate a `src/log_security.py` helper that emits structured OWASP-format security events (JSON with datetime, appid, type, event, level, description). Call it from charm event handlers at the appropriate points (secret hooks, relation changes, action handlers). Never log sensitive data.

**Tracing**: ops-tracing handles hook/Pebble/relation spans automatically. Only add manual spans for long-running workload operations (backups, migrations), external API calls, and decision logic with fallback paths. Do not span simple Pebble or relation handlers.
