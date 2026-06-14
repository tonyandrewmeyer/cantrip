# Terraform-module prompts

Paste these into Cantrip in order, from the charm's directory. Wait
for each autonomous run to complete before pasting the next.

Run this recipe **after** the charm builds and deploys cleanly — the
module should reflect a configuration you've already validated.

## 1 — Generate the module

```
Load the terraform skill and generate a Terraform module for this
charm under terraform/ with the standard four files: main.tf,
variables.tf, outputs.tf, terraform.tf.

- main.tf: a juju_application resource with a charm { name = "<this
  charm>", channel = var.channel } block, referencing variables for
  app_name, model_uuid, units, and config.
- variables.tf: declare app_name, model_uuid, channel, units, config
  with sensible defaults (model_uuid has no default).
- outputs.tf: export at least app_name.
- terraform.tf: a required_providers block pinning the juju/juju
  provider.

If this charm has a relation it cannot function without, add a
juju_integration for that one — nothing else.
```

The "load the terraform skill" cue gets Cantrip the file-structure
and composition guidance up front.

## 2 — Keep it composable

```
Don't add cross-charm integrations or COS wiring to the module —
only integrations strictly internal to this charm's operation.
Cross-charm relations belong in a higher composition layer where the
caller combines modules. Each module manages one juju_application.
```

This is the one rule people get wrong: a charm module is *not* a
deployment bundle.

## 3 — Confirm done

```
/tasks
```

```
Show me the terraform/ directory contents and confirm the
juju_application names this charm (not a placeholder) and the
juju/juju provider is pinned in terraform.tf.
```

Then run the verifier:

```bash
python /path/to/cantrip/cookbook/generate-a-terraform-module/verify.py .
```

And, if you have the Terraform CLI, the parse check:

```bash
cd terraform && terraform init -backend=false && terraform validate
```

## Optional — commit

```
git_add the terraform/ directory, git_commit with the message
"Add Terraform module".
```
