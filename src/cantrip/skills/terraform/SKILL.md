---
name: terraform
description: Generating Terraform modules for declarative charm deployment
---

# Terraform Modules for Juju Charms

A Terraform module lets users deploy your charm declaratively using the Juju Terraform
provider. Instead of running `juju deploy` commands, they write HCL that describes the
desired state — the provider handles the rest.

## Why Ship a Terraform Module

- **Declarative deployment** — users describe what they want, not how to get there
- **Composability** — modules can be combined into larger stacks
- **GitOps workflows** — infrastructure as code, version-controlled and reviewable
- **Enterprise adoption** — many organisations already use Terraform for provisioning

## When to Generate

Generate a Terraform module **after the charm is built and deployed successfully**. The
module codifies the deployment pattern you have already validated. Do not generate it
before the charm works — the module should reflect a known-good configuration.

Suggest Terraform module generation to the user once build and deploy succeed, unless
they have already mentioned it or declined.

## Standard File Structure

Every charm Terraform module lives in a `terraform/` directory at the charm root and
contains four files:

```
terraform/
  main.tf          # The juju_application resource and any required integrations
  variables.tf     # Input variables (model name, channel, config overrides, etc.)
  outputs.tf       # Outputs (application name, endpoint bindings, etc.)
  versions.tf      # Required providers block (juju provider version constraint)
```

### `main.tf`

Defines the `juju_application` resource. References variables for anything the caller
might want to override (model, channel, units, config values).

```hcl
resource "juju_application" "my_charm" {
  name  = var.app_name
  model = var.model_name
  charm {
    name    = "my-charm"
    channel = var.channel
  }
  units = var.units
  config = var.config
}
```

If the charm has **required integrations** (e.g. a database it cannot function without),
include `juju_integration` resources for those. Optional integrations should be left to
the caller.

### `variables.tf`

Declare all input variables with sensible defaults:

```hcl
variable "app_name" {
  description = "Name of the deployed application"
  type        = string
  default     = "my-charm"
}

variable "model_name" {
  description = "Name of the Juju model to deploy into"
  type        = string
}

variable "channel" {
  description = "Charmhub channel"
  type        = string
  default     = "latest/stable"
}

variable "units" {
  description = "Number of units to deploy"
  type        = number
  default     = 1
}

variable "config" {
  description = "Charm configuration overrides"
  type        = map(string)
  default     = {}
}
```

### `outputs.tf`

Export values that downstream modules or the caller might need:

```hcl
output "app_name" {
  description = "Name of the deployed application"
  value       = juju_application.my_charm.name
}
```

### `versions.tf`

Pin the Juju Terraform provider:

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "~> 0.14"
    }
  }
}
```

## The Composition Pattern

Individual charm modules **do not define integrations between applications**. Each module
manages a single `juju_application` resource (and any integrations that are strictly
internal to that charm's operation).

Cross-charm integrations — relating a web app to a database, wiring COS endpoints, or
connecting ingress — belong at a **higher composition layer**. The caller combines
multiple modules and adds `juju_integration` resources to wire them together:

```hcl
module "webapp" {
  source     = "./modules/webapp"
  model_name = juju_model.dev.name
}

module "postgresql" {
  source     = "./modules/postgresql"
  model_name = juju_model.dev.name
}

resource "juju_integration" "webapp_db" {
  model = juju_model.dev.name
  application {
    name     = module.webapp.app_name
    endpoint = "database"
  }
  application {
    name     = module.postgresql.app_name
    endpoint = "database"
  }
}
```

This keeps modules reusable and avoids tight coupling between charms.

## Using the Tools

### `generate_terraform`

Generates the four-file module from the charm's metadata. Call it with the charm path:

```
generate_terraform(charm_path="/path/to/my-charm")
```

The tool reads `charmcraft.yaml` to determine the charm name, config options, required
integrations, and resources — then produces `terraform/main.tf`, `variables.tf`,
`outputs.tf`, and `versions.tf`.

### `validate_terraform`

Validates the generated module:

```
validate_terraform(charm_path="/path/to/my-charm")
```

This runs `terraform fmt --check`, `terraform init`, and `terraform validate` inside the
`terraform/` directory. Fix any issues it reports before committing.

## Testing

After generating and validating, run the full test suite:

```bash
cd terraform/
terraform init
terraform test
```

Terraform test files (`*.tftest.hcl`) can be added to `terraform/tests/` to verify the
module's plan output without applying changes.

## Linting

Keep the module tidy with standard Terraform tooling:

```bash
terraform fmt --recursive terraform/
tflint --recursive terraform/
```

`terraform fmt` enforces canonical HCL formatting. `tflint` catches common mistakes
such as undeclared variables, deprecated syntax, and provider-specific issues.

## Checklist

Before committing the Terraform module:

1. `validate_terraform` passes (format, init, validate)
2. All variables have descriptions and sensible defaults where appropriate
3. `model_name` has no default (the caller must provide it)
4. The composition pattern is respected — no cross-charm integrations in the module
5. `versions.tf` pins the Juju provider version
6. The module is documented in the charm's README
