### Demo generation

You are generating demo artefacts for a deployed, tested charm. Capture real output from the live deployment.

**Steps:**

1. Read `charmcraft.yaml` to discover the charm's actions, config options, and relation endpoints.
2. Read `WORKLOAD.md` and `DESIGN.md` (if they exist) for context on why things matter.

#### Capture data

3. Run `juju_status` and save to `demo/juju-status.txt`.
4. Run `juju_config` and save to `demo/config-reference.txt`.
5. For each action, run `juju_run_action` with sensible defaults and save JSON results to `demo/actions/<name>.json`.
6. Capture `juju_debug_log` (last 50 lines) to `demo/logs/event-log.txt`.
7. **Trace capture** — run `tempo_query` with the charm's `service_name` (limit 3). If traces are returned, save the JSON output to `demo/traces/recent-traces.json`. If a trace ID is available, fetch the full trace with `tempo_query(trace_id=...)` and save to `demo/traces/<trace_id>.json`. Write a human-readable span summary to `demo/traces/README.md` listing trace ID, service, duration, and span count. If Tempo is unavailable or no traces are found, skip this step and note it in DEMO.md.

#### Visual assets (if Rodney is available)

8. **Grafana dashboard screenshot** — if COS is deployed, use `rodney` to capture the Grafana dashboard:
   - `rodney start`
   - `rodney open <grafana_url>` (derive from COS model relations or `juju_status`)
   - `rodney waitstable`
   - `rodney screenshot demo/screenshots/grafana-dashboard.png`
   - `rodney stop`
   Save the dashboard JSON to `demo/dashboards/` if accessible via the Grafana HTTP API.
9. **Web UI screenshot** — for web-facing charms (those with an HTTP port in `charmcraft.yaml`), use `rodney` to capture the application's own UI through ingress:
   - `rodney start` (if not already running)
   - `rodney open <app_url>`
   - `rodney waitstable`
   - `rodney screenshot demo/screenshots/web-ui.png`
   - `rodney stop`

If Rodney is not installed or the URLs are unavailable, skip visual asset capture — the demo is still valid without screenshots.

#### Build DEMO.md

10. **Prefer Showboat** when the `showboat` tool is available:
    - `showboat init DEMO.md "Demo: <charm-name>"`
    - `showboat note` for each narrative section (overview, deployment, relations, configuration, actions, observability)
    - `showboat exec` for each live command (`juju status`, `juju run`, `juju config`, etc.) to capture real output inline
    - `showboat image` for any screenshots captured via Rodney
    - `showboat verify` at the end to validate the document

    **Structure DEMO.md as:**
    - **Overview** — what the charm does, drawn from WORKLOAD.md
    - **Deployment** — `juju deploy` + all required relations, showing each `juju relate` command
    - **Relations** — for each relation endpoint: what it connects to, why it matters, the `juju relate` command and resulting status
    - **Configuration** — for each key config option: what it does, the `juju config` command, before/after status
    - **Actions** — for each action: what it does operationally, the `juju run` command with example parameters, captured output
    - **Observability** — COS integration: dashboard link, key metrics, sample trace (if captured), log query examples
    - **Screenshots** — embed any Grafana or web UI screenshots captured via Rodney

    **If Showboat is unavailable**, write `DEMO.md` directly using `write_file`, interleaving the captured command output from steps 3–7 with explanations.

#### Build demo.sh

11. Write `demo.sh` — a self-contained bash script that reproduces the full deployment:
    - Deploy the charm and all companion/relation charms
    - Establish all relations (`juju relate`)
    - Apply key configuration (`juju config`)
    - Wait for active/idle (`juju wait-for`)
    - Run a representative action to verify
    - Include an optional `--cleanup` flag that destroys the model
    - Mark it executable

#### Build TUTORIAL.md

12. Write `TUTORIAL.md` with two sections:

    **Quick start** (at the top) — a short "just deploy it" section for experienced users:
    - 5–10 lines: `juju add-model`, `juju deploy`, essential `juju relate`, `juju wait-for`, one verification command
    - No explanations — just the commands someone needs to copy-paste

    **Full tutorial** (below) — a detailed step-by-step guide:
    - Prerequisites (controller type, model, cloud substrate)
    - Deploying the charm and its relations (with explanations of what each relation provides)
    - Verifying the deployment (what to look for in `juju status`)
    - Exercising key features (config changes with before/after, actions with explanations)
    - Observability (where to find dashboards, what metrics to watch, how to query logs)
    - Troubleshooting common issues (common error states, how to recover)

    Include copy-pasteable commands with captured output from the live deployment. Draw on WORKLOAD.md and DESIGN.md to explain *why* config options matter and what actions do operationally.

#### Validate and commit

13. **Validate demo.sh** — if possible, run key commands from `demo.sh` (like `juju status`) to verify they still work. Note any issues in DEMO.md.
14. Stage all files with `git_add` and commit with a descriptive message.

**Important:** draw on WORKLOAD.md and DESIGN.md to explain *why* — not just *how*. The demo should convince a reviewer that the charm works and is well-integrated, not just list commands.
