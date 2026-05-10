# Generate a Terraform module

**Ship your charm with a Terraform module so users can deploy it
declaratively.** Instead of `juju deploy` commands, callers write
HCL describing the desired state and the Juju Terraform provider
reconciles it — GitOps-friendly, composable, and the shape many
organisations already expect.

This recipe drives Cantrip's `terraform` skill to produce the
standard four-file module under `terraform/` at the charm root.

Use it for:

- A charm you've built and deployed successfully and now want to
  package for Terraform-based stacks.
- Adding a `terraform/` module to an existing charm that doesn't
  have one yet.
- Onboarding to the module conventions — the verifier spells out
  the expected shape.

Generate the module **after** the charm builds and deploys: the
module codifies a known-good deployment, so it should reflect a
configuration you've actually validated.

## What you need

- **Cantrip** installed (`uv sync --dev && uv pip install -e .`
  from the Cantrip repo, or however you usually do it).
- **An existing charm** — a `charmcraft.yaml` at minimum; ideally
  one you've already packed and deployed.
- **The Terraform CLI** (`terraform`) only if you want to run
  `terraform validate` afterwards. The recipe and its verifier
  don't need it — they check files on disk.
- **No Juju controller needed** for generating or verifying the
  module (you'll want one to actually *apply* it later).

## What you get

A module directory with this shape:

```
<charm-dir>/
└── terraform/
    ├── main.tf          # resource "juju_application" "<charm>" { charm { name = "<charm>" ... } }
    ├── variables.tf     # app_name, model_uuid, channel, units, config — with defaults
    ├── outputs.tf       # at least: output "app_name" = juju_application.<charm>.name
    └── terraform.tf     # terraform { required_providers { juju = { source = "juju/juju" ... } } }
```

If the charm has a relation it **cannot function without** (a
database it requires, say), `main.tf` also carries a
`juju_integration` for that. *Optional* integrations — COS wiring,
ingress, cross-charm relations — are deliberately left out: those
belong at a higher composition layer where the caller combines
multiple modules. Keeping each module to a single `juju_application`
(plus only its strictly-internal integrations) is what makes
modules reusable.

## Walkthrough

1. From the charm's directory, start Cantrip:
   ```bash
   cd ~/charms/my-charm
   cantrip .
   ```

2. Paste the prompts from [`prompts.md`](prompts.md) one at a time.
   Wait for each autonomous run to finish before the next paste.

3. When Cantrip reports the module is generated, verify the shape:
   ```bash
   python /path/to/cantrip/cookbook/generate-a-terraform-module/verify.py .
   ```

   You should see `OK — Terraform module shape verified.` with exit
   code 0. Failures print a short reason naming the missing file or
   block.

4. Confirm it parses (needs the Terraform CLI):
   ```bash
   cd terraform && terraform init -backend=false && terraform validate
   ```

## How the verifier works

[`verify.py`](verify.py) loads the charm directory and asserts:

- A `terraform/` directory exists with all four standard files:
  `main.tf`, `variables.tf`, `outputs.tf`, `terraform.tf`.
- `main.tf` declares a `resource "juju_application" "..." {}` block,
  it has a nested `charm { ... }` block, and it references this
  charm's name (the `name` from `charmcraft.yaml`) — not a
  placeholder.
- `variables.tf` declares at least one `variable "..." {}` block.
- `outputs.tf` declares at least one `output "..." {}` block.
- `terraform.tf` has a `terraform { ... }` block with a
  `required_providers` entry pinning the `juju/juju` provider
  source.

It does not run `terraform init` / `validate` — that needs the CLI
and a provider download. The verifier is a shape contract; run
`terraform validate` yourself for the parse check.

## Why this recipe is in the cookbook

A Terraform module has a small, well-defined shape, and Cantrip's
`terraform` skill commits to it. Pinning that shape in a verifier
gives us:

1. **Teaching artifact** — `verify.py` is a concise spec of the
   module conventions: where the files live, what each must
   contain, the single-application composition rule.
2. **Regression fixture** — if the skill drifts (a file gets
   renamed, the provider source changes, the composition pattern
   moves), the verifier and the recipe disagree and CI's structure
   sweep over `cookbook/*/` flags it.

## Related

- Cantrip's `terraform` skill — the in-agent guidance behind the
  module shape and the composition pattern.
- [Juju Terraform provider](https://registry.terraform.io/providers/juju/juju/latest/docs)
  — the provider the module pins.
- [`build-a-stateful-charm/`](../build-a-stateful-charm/README.md)
  — build the charm first; this recipe packages the result.
