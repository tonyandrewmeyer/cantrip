Run the test suite and report results clearly. If tests fail, include the failure output so debug tasks can act on it.

**Combined validation**: run both unit tests and integration tests as a combined gate. Run unit tests first (faster feedback), then integration tests. Report pass/fail counts for each.

**Efficiency**: run `run_charm_tests` for unit and integration in successive rounds (unit first, then integration). Report pass/fail counts and stop — do not attempt fixes (that is a debug task).
