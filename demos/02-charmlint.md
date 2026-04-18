# charmlint: Standalone Juju Charm Linter

*2026-04-18T10:05:47Z by Showboat 0.6.1*
<!-- showboat-id: 9db436df-0b72-4677-aa1e-817144553aa4 -->

`charmlint` is shipped inside the `cantrip` package as a standalone executable. It lints a Juju charm across 12 categories with 40+ deterministic rules covering actions, metadata, observability, testing, security, documentation, and charmcraft compatibility.

Cantrip's agent runs it under the hood during the build loop, but it's equally useful as a standalone tool in CI or on a developer's laptop.

## Rule categories

Rule IDs are prefixed by category: ACT (actions), COS (observability), DOC (documentation), LIB (libraries), META (metadata), SEC (security), TST (testing), DEP (deprecated APIs), STR (structure), CFG (config quality), STA (status), ATT (attestations).

```bash
ls src/charmlint/rules/ | grep -v __
```

```output
actions.py
attestations.py
charmcraft_compat.py
config_quality.py
deprecated.py
documentation.py
libraries.py
metadata.py
observability.py
security.py
status.py
structure.py
testing.py
unknown_fields.py
```

## Example: linting a sample charm

Cantrip's test suite ships several reference charms. Let's lint the Miniflux gold reference:

```bash
uv run charmlint --no-color tests/eval/charms/miniflux/gold-claude | head -40
```

```output
charmcraft.yaml ACT001 Missing 'get-health' action (or alias: health-check, check-health, get-status, health)
charmcraft.yaml ACT002 Missing 'pause' action (or alias: stop, disable)
charmcraft.yaml ACT003 Missing 'resume' action (or alias: start, enable)
DOC001 No README.md found
DOC002 No installation/setup documentation found
DOC003 No configuration documentation found
DOC004 No usage documentation found
DOC005 No troubleshooting documentation found
charmcraft.yaml META002 Missing 'display-name' field
charmcraft.yaml META005 Missing 'docs' URL
charmcraft.yaml META006 Missing 'issues' URL
charmcraft.yaml META007 Missing 'source' URL
COS005 ops-tracing not detected — add for distributed tracing
SEC002 No TLS/encryption support detected
STS001 No BlockedStatus for missing required configuration
STS002 No BlockedStatus for conflicting/invalid configuration
STS003 No status set for missing relations
STR001 No LICENSE/LICENCE file found
STR002 No icon.svg found

Found 19 issues (10 warnings, 9 info)
```

## Filter to a single category

Use `--select` to focus on one area — here, only observability/COS rules:

```bash
uv run charmlint --no-color --select COS tests/eval/charms/miniflux/gold-claude
```

```output
COS005 ops-tracing not detected — add for distributed tracing

Found 1 issue (1 warning)
```

## Machine-readable output

`--format json` is what Cantrip's agent uses when it runs charmlint as a tool call — it gets structured diagnostics it can reason about:

```bash
uv run charmlint --format=json --select META tests/eval/charms/miniflux/gold-claude
```

```output
{
  "charm_dir": "/home/ubuntu/cantrip/tests/eval/charms/miniflux/gold-claude",
  "total": 4,
  "errors": 0,
  "warnings": 1,
  "info": 3,
  "diagnostics": [
    {
      "rule_id": "META002",
      "severity": "warning",
      "message": "Missing 'display-name' field",
      "path": "charmcraft.yaml"
    },
    {
      "rule_id": "META005",
      "severity": "info",
      "message": "Missing 'docs' URL",
      "path": "charmcraft.yaml"
    },
    {
      "rule_id": "META006",
      "severity": "info",
      "message": "Missing 'issues' URL",
      "path": "charmcraft.yaml"
    },
    {
      "rule_id": "META007",
      "severity": "info",
      "message": "Missing 'source' URL",
      "path": "charmcraft.yaml"
    }
  ]
}
```

## Strict mode for CI

Without flags, `charmlint` exits non-zero only on errors. With `--strict`, warnings also fail the run — ideal for a CI gate:

```bash
uv run charmlint --no-color --strict --select COS tests/eval/charms/miniflux/gold-claude; echo "exit=$?"
```

```output
COS005 ops-tracing not detected — add for distributed tracing

Found 1 issue (1 warning)
exit=2
```
