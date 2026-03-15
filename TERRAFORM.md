# Terraform Support Design Document

Research and design for Phase 9 of Cantrip — generating, validating, and maintaining
Terraform modules for Juju-deployed charms.

## Research Findings

### 1. What is a Charm Terraform Module?

Every charm can ship a `terraform/` directory containing a reusable Terraform module that
deploys that charm via the [Juju Terraform provider](https://registry.terraform.io/providers/juju/juju).
This lets operators deploy charms declaratively with `terraform apply` rather than
`juju deploy`, and compose multi-charm deployments as code.

Each module is a **single-charm wrapper** — it deploys one `juju_application` and exposes
its relation endpoints for composition. Integration wiring between charms happens at a
higher-level composition module, not inside individual charm modules.

### 2. Standard File Structure

Every charm Terraform module lives in `terraform/` at the repo root and contains four files:

```
terraform/
├── main.tf          # Single juju_application resource
├── variables.tf     # Input variables
├── outputs.tf       # app_name + endpoint maps
└── versions.tf      # Provider version constraints
```

No `provider.tf` (provider config is left to the caller). No `backend.tf`.

### 3. Standard Variables

Based on the specification and real-world modules, the standard variable set is:

| Variable | Type | Default | Required | Notes |
|----------|------|---------|----------|-------|
| `model` | `string` | — | Yes | Juju model name |
| `app_name` | `string` | charm name | No | Name in Juju model |
| `channel` | `string` | `"latest/edge"` | No | Charm channel |
| `revision` | `number` | `null` | No | Pin to specific revision |
| `config` | `map(string)` | `{}` | No | Charm config options |
| `constraints` | `string` | `"arch=amd64"` | No | Juju constraints (amd64 default works around provider bug) |
| `units` | `number` | `1` | No | Number of units |
| `base` | `string` | `"ubuntu@22.04"` | No | Base for the charm |
| `resources` | `map(string)` | `{}` | No | OCI images or file resources |

The `constraints` default of `"arch=amd64"` is a workaround for a known Juju Terraform
provider bug (GitHub issue #344) where empty constraints cause failures.

### 4. Standard Outputs

Modules expose `app_name` plus endpoint maps using Terraform-safe underscore keys
mapped to actual Juju hyphenated endpoint names:

```hcl
output "app_name" {
  value = juju_application.myapp.name
}

output "provides" {
  value = {
    database          = "database"
    metrics_endpoint  = "metrics-endpoint"
  }
}

output "requires" {
  value = {
    certificates  = "certificates"
    logging       = "logging"
    tracing       = "tracing"
  }
}
```

The `provides`/`requires` split is the most structured convention (preferred).

### 5. Resource Pattern

Every module defines exactly one `juju_application` resource:

```hcl
resource "juju_application" "myapp" {
  name  = var.app_name
  model = var.model

  charm {
    name     = "my-charm-k8s"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }

  config      = var.config
  constraints = var.constraints
  trust       = true
  units       = var.units
}
```

Key patterns:
- `trust = true` is universal for K8s charms
- The `charm` block always contains `name`, `channel`, `revision`
- `base` appears in newer modules
- No `juju_integration` resources — those are handled at the composition layer

### 6. Integration Pattern (Composition Layer)

Individual modules do NOT define relations. A higher-level module composes them:

```hcl
module "mysql" {
  source = "./terraform"
  model  = juju_model.dev.name
}

module "grafana" {
  source = "git::https://github.com/canonical/grafana-k8s-operator//terraform"
  model  = juju_model.dev.name
}

resource "juju_integration" "grafana_to_mysql" {
  model = juju_model.dev.name

  application {
    name     = module.mysql.app_name
    endpoint = module.mysql.provides.grafana_dashboard
  }

  application {
    name     = module.grafana.app_name
    endpoint = module.grafana.requires.grafana_dashboard
  }
}
```

### 7. Version Constraints (versions.tf)

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "~> 1.0"
    }
  }
}
```

The charmkeeper spec specifies Terraform `~> 1.12` and Juju provider `~> 1.0`.

### 8. Testing

Tests live in `terraform/tests/` using Terraform's native test framework (`.tftest.hcl`):

```
terraform/tests/
├── setup/
│   └── main.tf        # Creates a Juju model for testing
└── main.tftest.hcl    # Test cases
```

Testing commands:
```bash
terraform init
terraform test
```

### 9. Linting

Each module requires a `.tflint.hcl` file:
```hcl
rule "terraform_required_version" {
  enabled = true
}
```

Quality commands:
```bash
terraform fmt --recursive
tflint --recursive
```

---

## Design Decisions

### D1: When to Generate

**Decision:** Generate on request, not by default.

Rationale: Not every charm needs a Terraform module. The user should explicitly ask for
Terraform support (e.g. "add Terraform module" or answering a design question about it).
However, the system prompt should mention Terraform as an option during design
confirmation so users are aware of it.

### D2: Module Structure

**Decision:** Follow the standard four-file structure exactly.

The module is fully inferrable from `charmcraft.yaml`:
- **charm name** → `charm.name` in main.tf and `app_name` default
- **relations** → `provides`/`requires` outputs
- **config options** → description text in `config` variable
- **resources** → `resources` variable (only if charm has resources)
- **storage** → `storage_directives` variable (only if charm has storage)
- **base** → `base` variable default

### D3: Integration with the Build Pipeline

**Decision:** Generate after the first successful deploy.

Positioning:
1. Design → Build → Deploy → **Terraform module generation** → Test → Done

At this point we know:
- The charm packs and deploys correctly
- All relation endpoints are confirmed from `charmcraft.yaml`
- Config options are finalised
- The channel and revision are known

The Terraform module generation is a BUILD task that reads `charmcraft.yaml` and writes
the four files. It does not require an LLM — it is a deterministic template expansion.

### D4: Validation

**Decision:** Run `terraform validate` and `terraform fmt --check` as quality checks.

Cantrip can validate the generated module if `terraform` is installed. If not available,
skip validation gracefully (the generated files are simple enough that template errors
are unlikely). `terraform plan` requires a live Juju controller, which may not be
available — so validate yes, plan only if environment is ready.

### D5: Maintenance

**Decision:** Regenerate when charm metadata changes.

When the user modifies `charmcraft.yaml` (adding relations, config, resources), the
Terraform module should be regenerated. The agent can detect this by diffing the
charmcraft.yaml against the last known state. This is a follow-up concern — not
required for the initial implementation.

---

## Implementation Plan

### Phase 9.1: Terraform Module Generator (Core)

A pure Python function that reads `charmcraft.yaml` and produces the four Terraform files.
No LLM needed — this is deterministic template expansion.

**New file:** `src/cantrip/charm/terraform.py`
- `generate_terraform_module(charmcraft_path: Path) -> dict[str, str]`
  - Parses `charmcraft.yaml` (name, assumes, config, provides, requires, resources, storage)
  - Returns `{"main.tf": ..., "variables.tf": ..., "outputs.tf": ..., "versions.tf": ...}`
- Helper functions for each file's content

### Phase 9.2: Agent Tool

**New tool:** `GenerateTerraformTool` in `src/cantrip/agent/tools/charm_tools.py`
- Name: `generate_terraform`
- Takes `charm_path` parameter
- Calls `generate_terraform_module()` and writes files to `{charm_path}/terraform/`
- Returns summary of generated files

Add to BUILD and INFRA tool allowlists in `subagent.py`.

### Phase 9.3: Validation Tool

**New tool:** `ValidateTerraformTool`
- Name: `validate_terraform`
- Runs `terraform fmt --check` and `terraform validate` in the terraform directory
- Gracefully degrades if `terraform` CLI is not installed
- Returns pass/fail with details

Add to BUILD and TEST tool allowlists.

### Phase 9.4: System Prompt and Skill

- Add a `terraform` skill in `src/cantrip/skills/terraform/SKILL.md`
- Mention Terraform as an option in the design confirmation flow
- Add guidance for when to suggest Terraform modules

### Phase 9.5: Planner Integration

- After a successful deploy, the planner can optionally generate a "Generate Terraform
  module" BUILD task if the user has indicated they want Terraform support
- The task is a lightweight BUILD that calls `generate_terraform` + `validate_terraform`
