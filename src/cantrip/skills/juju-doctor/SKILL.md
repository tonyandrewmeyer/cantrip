---
name: juju-doctor
description: Probe-based deployment validation with juju-doctor — scriptlet probes, rulesets, live and offline (sosreport) checks
---

# juju-doctor

Probe-based diagnostic tool for validating Juju deployments.
juju-doctor closes a gap collect-status / update-status / Pebble
checks don't: a single tool that asserts deployment-wide invariants,
runs against a live model **or** static sosreport artefacts, and
composes simple probes into solution-level rulesets.

> Adapted from the `juju-doctor` skill in
> `tonyandrewmeyer/charming-with-claude`, CC BY 4.0 (Tony Meyer, 2025).
> Reformatted for cantrip's bundled-skill frontmatter; content
> otherwise unchanged.  See Provenance at the foot of this skill for
> the source link.

## Installation

```bash
uv pip install juju-doctor
# or
pip install juju-doctor
```

Development install:

```bash
git clone https://github.com/canonical/juju-doctor.git
cd juju-doctor
uv sync --extra=dev && uv pip install -e .
```

## Core concepts

### Artefacts

juju-doctor operates on three types of Juju artefacts:

| Artefact | Source command | Description |
|----------|---------------|-------------|
| **status** | `juju status --format=yaml` | Unit status, application status, machine info |
| **bundle** | `juju export-bundle` | Deployed bundle configuration |
| **show-unit** | `juju show-unit --format=yaml` | Detailed unit information |

### Probe types

**Scriptlet probes** (Python) — functions named after artefact types
that receive data indexed by model name:

```python
def status(juju_statuses: dict[str, dict]):
    """Validate that all units are active/idle."""
    for model_name, status_data in juju_statuses.items():
        apps = status_data.get("applications", {})
        for app_name, app_data in apps.items():
            for unit_name, unit_data in app_data.get("units", {}).items():
                ws = unit_data.get("workload-status", {})
                if ws.get("current") != "active":
                    raise Exception(
                        f"{unit_name} in {model_name} is "
                        f"{ws.get('current')}, not active"
                    )
```

**Ruleset probes** (YAML) — declarative files that coordinate
multiple probes:

```yaml
name: my-solution-ruleset
probes:
  - type: scriptlet
    url: file://probes/check_active.py
  - type: scriptlet
    url: file://probes/check_relations.py
  - type: ruleset
    url: file://rulesets/nested.yaml
  - type: scriptlet
    url: github://canonical/my-charm//probes/validate.py
```

## Core workflows

### Live models

```bash
# Single model
juju-doctor check -p file://probes/check_active.py -m mymodel

# Multiple models
juju-doctor check -p file://probes/check_active.py -m model1 -m model2

# Multiple probes
juju-doctor check \
  -p file://probes/check_active.py \
  -p file://probes/check_relations.py \
  -m mymodel

# Using a ruleset
juju-doctor check -p file://rulesets/solution.yaml -m mymodel
```

### Static artefacts (offline)

```bash
juju status --format=yaml > status.yaml
juju-doctor check -p file://probes/check_active.py --status status.yaml

juju export-bundle > bundle.yaml
juju-doctor check -p file://probes/check_bundle.py --bundle bundle.yaml

juju show-unit myapp/0 --format=yaml > show-unit.yaml
juju-doctor check -p file://probes/check_unit.py --show-unit show-unit.yaml

# Combine multiple artefacts
juju-doctor check \
  -p file://probes/full_check.py \
  --status status.yaml \
  --bundle bundle.yaml \
  --show-unit show-unit.yaml
```

### Remote probes from GitHub

```bash
juju-doctor check \
  -p github://canonical/my-charm//probes/validate.py \
  -m mymodel
```

### Output

```bash
# Default tree output
juju-doctor check -p file://probes/check.py -m mymodel

# Example output:
# Results
# ├── 🔴 probes_check_relations.py
# └── 🟢 probes_check_active.py
# Total: 🟢 1/2 🔴 1/2

# Machine-readable
juju-doctor check -p file://probes/check.py -m mymodel --format json

# Verbose
juju-doctor check -p file://probes/check.py -m mymodel -v
```

### Schema inspection

```bash
juju-doctor schema
juju-doctor schema --builtins
```

## Writing probes

### Scriptlet probe structure

```python
"""Probe: Validate deployment health."""

def status(juju_statuses: dict[str, dict]):
    """Check all units are active and idle."""
    for model_name, data in juju_statuses.items():
        for app_name, app in data.get("applications", {}).items():
            for unit_name, unit in app.get("units", {}).items():
                ws = unit.get("workload-status", {})
                agent = unit.get("juju-status", {})
                if ws.get("current") != "active":
                    raise Exception(f"{unit_name}: workload is {ws.get('current')}")
                if agent.get("current") != "idle":
                    raise Exception(f"{unit_name}: agent is {agent.get('current')}")


def bundle(juju_bundles: dict[str, dict]):
    """Validate bundle configuration."""
    for model_name, bundle_data in juju_bundles.items():
        apps = bundle_data.get("applications", {})
        if not apps:
            raise Exception(f"{model_name}: no applications in bundle")
```

**Rules**:

- Function names **must** match artefact types: `status`, `bundle`, `show_unit`.
- Each function receives a `dict[str, dict]` indexed by model name.
- Raise an `Exception` to signal failure (message becomes the error output).
- Return normally (or return `None`) to signal success.
- A single probe file can contain multiple artefact functions.

### Common patterns

#### All units active / idle

```python
def status(juju_statuses: dict[str, dict]):
    for model, data in juju_statuses.items():
        for app, app_data in data.get("applications", {}).items():
            for unit, unit_data in app_data.get("units", {}).items():
                ws = unit_data.get("workload-status", {})
                if ws.get("current") != "active":
                    raise Exception(f"{unit}: {ws.get('current')}")
```

#### Required relations exist

```python
def status(juju_statuses: dict[str, dict]):
    required = {"database", "ingress"}
    for model, data in juju_statuses.items():
        relations = set(data.get("relations", {}).keys())
        for app, app_data in data.get("applications", {}).items():
            for rel in app_data.get("relations", {}):
                relations.add(rel)
        missing = required - relations
        if missing:
            raise Exception(f"{model}: missing relations: {missing}")
```

#### Bundle has expected apps and unit counts

```python
def bundle(juju_bundles: dict[str, dict]):
    for model, bundle_data in juju_bundles.items():
        apps = bundle_data.get("applications", {})
        for app_name, app in apps.items():
            num_units = app.get("num_units", 1)
            if num_units < 1:
                raise Exception(f"{app_name}: has {num_units} units")
            charm = app.get("charm", "")
            if not charm:
                raise Exception(f"{app_name}: no charm specified")
```

#### Catch blocked / error status

```python
def status(juju_statuses: dict[str, dict]):
    for model, data in juju_statuses.items():
        for app, app_data in data.get("applications", {}).items():
            app_status = app_data.get("application-status", {})
            if app_status.get("current") in ("blocked", "error"):
                msg = app_status.get("message", "no message")
                raise Exception(f"{app}: {app_status['current']} — {msg}")
```

## Project organisation

```
probes/
├── check_active.py         # Unit health checks
├── check_relations.py      # Relation validation
├── check_config.py         # Configuration validation
└── rulesets/
    └── full-check.yaml     # Combined ruleset
```

## Best practices

### Writing probes

1. **One concern per probe** — keep probes focused on a single validation.
2. **Descriptive error messages** — include the model name, unit name, and what went wrong.
3. **Handle missing data gracefully** — use `.get()` with defaults; not all fields are always present.
4. **Use rulesets to compose** — combine simple probes into comprehensive checks rather than writing monolithic ones.
5. **Test offline first** — capture artefacts with `juju status --format=yaml` and validate against those before running against live models.

### Organising probes

1. **Version-control with the charm** — store alongside the charm they validate.
2. **Use rulesets for solutions** — when multiple charms form a solution, create a ruleset that validates the whole deployment.
3. **Share via GitHub** — use `github://` URLs in rulesets for reusable probes.
4. **Document expected state** — comment probes to explain what "healthy" means.

### Support workflows

1. **Collect artefacts from sosreport** — extract `juju status` and `juju export-bundle` output.
2. **Run probes offline** — `juju-doctor check --status status.yaml --bundle bundle.yaml`.
3. **Share results** — `--format json` is the machine-readable surface.
4. **Encode deployment requirements as probes** — solution-specific rulesets for repeatable validation.

## Troubleshooting

### juju-doctor not found

```bash
pip show juju-doctor   # or: uv pip show juju-doctor
pip install --upgrade juju-doctor
```

### Probe fails to load

- Check the URL format: `file://path/to/probe.py` (relative to working directory).
- Verify the Python file has valid syntax.
- Ensure function names match artefact types (`status`, `bundle`, `show_unit`).

### Live model connection issues

```bash
juju status
juju models
juju-doctor check -p file://probe.py -m $(juju models --format=json | python3 -c "import sys,json; print(json.load(sys.stdin)['models'][0]['name'])")
```

### Unexpected results

```bash
juju-doctor check -p file://probe.py -m mymodel -v

# Capture the artefact and inspect manually
juju status --format=yaml > /tmp/status.yaml
python3 -c "import yaml; print(yaml.safe_load(open('/tmp/status.yaml')))"

# Then test the probe offline
juju-doctor check -p file://probe.py --status /tmp/status.yaml -v
```

## Command reference

```bash
juju-doctor check [OPTIONS]
  --probe, -p     Probe URL (file://, github://) — repeatable
  --model, -m     Live model name — repeatable
  --status        Path to juju status YAML file
  --bundle        Path to juju bundle YAML file
  --show-unit     Path to juju show-unit YAML file
  --verbose, -v   Verbose output
  --format, -o    Output format: tree (default) or json

juju-doctor schema
juju-doctor schema --builtins

juju-doctor --help
juju-doctor --version
```

## Resources

- juju-doctor on GitHub: <https://github.com/canonical/juju-doctor>
- juju-doctor on PyPI: <https://pypi.org/project/juju-doctor>
- Discourse: <https://discourse.charmhub.io/t/juju-doctor-why-does-juju-need-it/17748>

## Key reminders

- Probes raise `Exception` to signal failure, return normally for success.
- Use `file://` URLs for local probes, `github://` for remote ones.
- Always test probes offline with captured artefacts before running live.
- Compose simple probes into rulesets rather than writing monolithic validators.

## Provenance

Adapted from [the `juju-doctor` skill](https://github.com/tonyandrewmeyer/charming-with-claude/tree/main/skills/juju-doctor)
in [`tonyandrewmeyer/charming-with-claude`](https://github.com/tonyandrewmeyer/charming-with-claude),
CC BY 4.0 (Tony Meyer, 2025).  Content reformatted for cantrip's
bundled-skill frontmatter; otherwise unchanged.
