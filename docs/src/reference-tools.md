---
title: "Agent tools reference — Cantrip"
description: "Complete reference of all tools available to the Cantrip agent, grouped by category."
h1: "Agent tools"
subtitle: "All tools available to the Cantrip agent, grouped by category. These tools are used by both the main conversation loop and background subagents."
section: reference
breadcrumb_label: "Agent tools"
on_this_page:
  - { anchor: "file-ops", label: "File operations" }
  - { anchor: "charm-dev", label: "Charm development" }
  - { anchor: "juju-ops", label: "Juju operations" }
  - { anchor: "testing", label: "Testing" }
  - { anchor: "observability", label: "Observability" }
  - { anchor: "git-github", label: "Git and GitHub" }
  - { anchor: "web", label: "Web and search" }
  - { anchor: "publishing", label: "Publishing" }
  - { anchor: "rockcraft", label: "Rockcraft and OCI" }
  - { anchor: "environment", label: "Environment" }
  - { anchor: "memory", label: "Memory" }
  - { anchor: "mcp", label: "MCP-sourced tools" }
  - { anchor: "internal", label: "Internal" }
---

<div class="callout">
  <p>
    You do not call these tools directly. The agent selects and uses
    them autonomously based on the current task. This reference is for
    understanding what the agent can do.
  </p>
</div>

{#file-ops}
## File operations

| Tool | Description |
|---|---|
| `read_file` | Read a file's contents |
| `write_file` | Create or overwrite a file |
| `edit_file` | Replace a specific string in a file |
| `multi_edit` | Apply multiple edits to one or more files atomically |
| `list_directory` | List files and directories |
| `grep` | Search file contents with regex |
| `glob` | Find files matching a glob pattern |

{#charm-dev}
## Charm development

| Tool | Description |
|---|---|
| `charmcraft_init` | Scaffold a new charm project |
| `charmcraft_pack` | Pack a charm into a `.charm` file |
| `quick_pack` | Fast packing without charmcraft's full lifecycle (no LXD) |
| `charm_validate` | Validate charm metadata and structure |
| `charmcraft_fetch_libs` | Fetch charm libraries from Charmhub |
| `analyse_framework` | Detect application framework and suggest charm path |
| `charm_audit` | Comprehensive charm quality audit |
| `charmlint` | Run 35+ deterministic lint rules |
| `operational_readiness` | Evaluate against Canonical's Operational Readiness Metrics |

{#juju-ops}
## Juju operations

| Tool | Description |
|---|---|
| `juju_status` | Get current model status |
| `juju_deploy` | Deploy a charm |
| `bundle_deploy` | Deploy an existing Juju bundle.yaml (with optional overlays). Legacy consumption only; prefer `juju_deploy` + `juju_relate` for new deployments |
| `juju_refresh` | Refresh a deployed charm to a new revision |
| `juju_relate` | Create a relation between applications |
| `juju_config` | Set application configuration |
| `juju_get_app_config` | Read current application configuration |
| `juju_run_action` | Run a charm action |
| `juju_ssh` | SSH into a unit |
| `juju_wait` | Wait for a unit to reach a target status |
| `juju_dispatch` | Dispatch a custom event to a unit |
| `juju_add_model` | Create a new Juju model |
| `juju_destroy_model` | Destroy a Juju model |
| `juju_offer` | Create a cross-model relation offer |
| `juju_consume` | Consume a cross-model relation offer |
| `juju_list_offers` | List available cross-model offers |
| `juju_list_secrets` | List Juju secrets |
| `juju_show_secret` | Show secret contents |
| `juju_read_relation_data` | Read relation data bags |
| `charm_sync` | Sync charm source to a deployed unit |

{#testing}
## Testing

| Tool | Description |
|---|---|
| `run_charm_tests` | Run unit or integration tests |
| `generate_tests` | Generate test scaffolding |
| `test_report` | Generate a test results report |
| `hook_benchmark` | Benchmark hook execution times |
| `fuzz_test` | Fuzz test charm event handlers |
| `chaos_test` | Run chaos testing scenarios |
| `scaling_test` | Test scaling behaviour |
| `upgrade_test` | Test charm upgrade paths |
| `generate_load_test` | Generate load test scripts |

### Acceptance testing

| Tool | Description |
|---|---|
| `action_exerciser` | Exercise every charm action with valid inputs |
| `relation_smoke` | Smoke-test all relation endpoints |
| `workload_endpoint` | Verify workload endpoints respond |
| `config_variation` | Test config option variations |
| `config_under_load` | Test config changes under load |
| `acceptance_report` | Generate an acceptance test summary |

{#observability}
## Observability

| Tool | Description |
|---|---|
| `juju_debug_log` | Read Juju debug log |
| `juju_stream_logs` | Stream Juju logs in real time |
| `tempo_query` | Query distributed traces from Tempo |
| `loki_query` | Query logs from Loki |
| `grafana_screenshot` | Render a Grafana panel or dashboard as a PNG (via `/render`); saves the image to `~/.cache/cantrip/screenshots/` and returns a caption plus the file path |
| `tempo_waterfall` | Render a Tempo trace as a waterfall PNG — one bar per span along a time axis, slowest spans highlighted; vision-capable providers see the image alongside the caption |
| `juju_status_render` | Render the current `juju status` as a coloured tree PNG — apps grouped with their units, status glyphs per node, relations listed below; saves to `~/.cache/cantrip/screenshots/` and attaches the image for vision-capable providers |

{#git-github}
## Git and GitHub

| Tool | Description |
|---|---|
| `git_clone` | Clone a repository |
| `git_init` | Initialise a new git repository |
| `git_status` | Show working tree status |
| `git_diff` | Show file diffs |
| `git_log` | Show commit history |
| `git_add` | Stage files for commit |
| `git_commit` | Create a commit |
| `git_push` | Push commits to remote |
| `gh_repo_create` | Create a GitHub repository |
| `gh_repo_bootstrap` | Apply default repo settings (branch protection, issue templates, CI workflow stub) |
| `gh_pr_create` | Create a pull request |
| `gh_issue_list` | List GitHub issues |
| `pr_review` | Review a pull request |
| `pr_review_reply` | Reply to PR review comments |

{#web}
## Web and search

| Tool | Description |
|---|---|
| `web_search` | Search the web |
| `web_fetch` | Fetch and extract content from a URL |
| `charmhub_search` | Search Charmhub for charms |
| `charmhub_info` | Get detailed info about a Charmhub charm |
| `registry_search` | Search Docker registries for images |
| `registry_image_info` | Get image metadata from a registry |

{#publishing}
## Publishing

| Tool | Description |
|---|---|
| `charmcraft_upload` | Upload a charm to Charmhub |
| `charmcraft_release` | Release a charm revision to a channel |
| `generate_readme` | Generate a README for the charm |
| `generate_icon` | Generate a charm icon |
| `generate_docs` | Generate charm documentation; bridges root `TUTORIAL.md` / `DEMO.md` / `architecture.md` into the Diátaxis tree when present, and populates tutorial / how-to from `demo/` and `ACCEPTANCE.md` artefacts when acceptance tests have run |
| `generate_diagram` | Generate architecture or integration diagrams |
| `extract_design_decisions` | Refresh `docs/explanation/architecture.md` with a chronological design-decision log mined from the session transcript; preserves charm-author intro |
| `extract_troubleshooting` | Mine error→fix pairs from the session transcript and write `docs/how-to/troubleshooting.md` grouped by category (relation / hook / secret / image / network / storage / observability / general); preserves charm-author intro |
| `generate_terraform` | Generate Terraform module for the charm |
| `validate_terraform` | Validate a generated Terraform module |

{#rockcraft}
## Rockcraft and OCI

| Tool | Description |
|---|---|
| `rockcraft_init` | Scaffold a rockcraft project |
| `rockcraft_pack` | Pack a rock (OCI image) |
| `skopeo_registry_push` | Push an OCI image to a registry |

{#environment}
## Environment

| Tool | Description |
|---|---|
| `concierge_prepare` | Prepare the development environment (Juju, LXD, MicroK8s) |
| `concierge_status` | Check environment readiness |
| `list_inference_snaps` | List available local inference snaps |
| `run_command` | Run a shell command |

{#memory}
## Memory

Durable learning tools. The agent calls these when the auto-writer
needs to persist a lesson, or when the user drives a
`/memory`, `/remember`, or
`/forget` slash command. See the
[memory how-to](howto-memory.html) for workflow.

| Tool | Description |
|---|---|
| `memory_list` | Summaries-only listing across charm + global scopes, filterable by kind/tag/status |
| `memory_read` | Load one memory’s full body by title; charm-scope shadows global-scope when titles collide |
| `memory_search` | Case-insensitive substring search across titles and bodies |
| `memory_write` | Create or overwrite a memory (kind, scope, body, tags, citations) |
| `memory_update` | Partial update by title; any omitted field is left unchanged |
| `memory_revalidate` | Re-check citation SHAs and quarantine entries whose source has drifted |
| `memory_sweep` | Archive entries untouched for 60+ days (soft-expiry TTL) |
| `memory_purge_check` | Surface archived entries older than 180 days as deletion candidates |
| `memory_forget` | Permanently delete a memory |

{#mcp}
## MCP-sourced tools

When servers are declared in `cantrip.mcp.yaml`,
Cantrip registers each of their tools with the qualified name
`mcp__<server>__<tool>`. The agent calls
them exactly like a built-in tool; the MCP client handles the
wire protocol, OAuth, elicitation, and reconnects. The per-server
`allowed_tools` list in the YAML is the authoritative
gate on which names surface.

Since the set varies per deployment, they aren’t listed
here — run `/mcp tools <server>` in the
chat to see what a connected server exposes. See the
[MCP how-to](howto-mcp.html) for configuration.

{#internal}
## Internal

These tools manage the agent's own state. They are not typically
visible to the user but are important for how the agent operates.

| Tool | Description |
|---|---|
| `plan_tasks` | Decompose an intent into a task plan using the LLM |
| `manage_tasks` | Inspect, cancel, or reprioritise tasks in the work queue |
| `load_skill` | Load a specialised skill prompt for the current task |
| `workspace_info` | Read a `cantrip.workspace.yaml` manifest (charms, cross-charm relations, shared config) from the current tree or any ancestor directory |
| `virtual_file_read` | Read a compressed virtual file from context |
| `virtual_file_search` | Search across virtual files |
| `showboat` | Generate a Showboat demo from the charm |
| `rodney` | Scaffold a Rodney demo |
