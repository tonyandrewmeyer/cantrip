### Demo generation

You are generating demo artefacts for a deployed, tested charm. Capture real output from the live deployment.

**Steps:**
1. Read `charmcraft.yaml` to discover the charm's actions, config options, and relation endpoints.
2. Read `WORKLOAD.md` and `DESIGN.md` (if they exist) for context.
3. Run `juju_status` and save the output to `demo/juju-status.txt`.
4. Run `juju_config` and save to `demo/config-reference.txt`.
5. For each action in the charm, run `juju_run_action` with sensible defaults and save JSON results to `demo/actions/<name>.json`.
6. Capture a `juju_debug_log` snippet (last 50 lines) to `demo/logs/event-log.txt`.
7. Write `DEMO.md` — an annotated walk-through interleaving real command output with explanations. Structure: overview, deployment, relations, configuration, actions, observability.
8. Write `demo.sh` — a self-contained bash script that reproduces the full deployment: deploy, relate, configure, verify. Include an optional `--cleanup` flag that destroys the model. Mark it executable.
9. Write `TUTORIAL.md` — a step-by-step guide covering: prerequisites, deploying the charm, verifying the deployment, exercising features (config, actions, scaling), observability, and troubleshooting. Include copy-pasteable commands.
10. Stage all files with `git_add` and commit with a descriptive message.

**Important:** draw on WORKLOAD.md and DESIGN.md to explain *why* certain config options matter and what the actions do operationally — not just how to run commands.
