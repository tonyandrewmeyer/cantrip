### Acceptance testing

You are running acceptance tests on a deployed charm. Exercise it the way a real Juju operator would.

**Steps:**
1. Run `action_exerciser` to test all charm actions.
2. Run `relation_smoke_test` to verify integrations with partner charms. The tool now also checks that relation databags contain meaningful data (not just address fields).
3. Run `workload_endpoint_test` to probe the workload's HTTP/TCP endpoints.
4. **Functional probes** — if the workload has a web interface, database, API, or queue, go beyond health checks. Use `juju_ssh` to exercise the workload: fetch a landing page, run a SQL query via the database client, call an API endpoint, or publish/consume a test message. Keep probes non-destructive.
5. Run `config_variation_test` to verify config options take effect.
6. If a health endpoint exists, run `config_under_load_test` to verify that changing a config option does not cause downtime.
7. Run `scaling_test` to test scaling behaviour.
8. Run `acceptance_report` to consolidate all results into ACCEPTANCE.md.

**Efficiency**: run `action_exerciser` and `workload_endpoint_test` in a single round (they are independent). Run `relation_smoke_test` separately as it deploys new charms. Collect all Markdown outputs and pass them to `acceptance_report` at the end.

**Verdict**: at the end of your response, state the verdict for each area explicitly:

```
Actions: PASS (3/3)
Relations: FAIL (1/2) — mysql endpoint timed out
Endpoints: PASS (1/1)
Config: FAIL (2/5) — log-level and port had no effect
Scaling: PASS
```

Use exactly "PASS" or "FAIL" for each area. If an area has failures, include a brief reason. Do not attempt fixes — failures become follow-up tasks automatically.
