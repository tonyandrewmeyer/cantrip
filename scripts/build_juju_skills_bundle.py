#!/usr/bin/env python3
"""Build the canonical/skills Juju bundle from Cantrip's source skills.

The bundle is published to ``canonical/skills`` (see ``design/JUJU_SKILLS_BUNDLE.md``).
Cantrip is the source of truth; the regenerated bundle lives under
``examples/bundles/canonical-skills-juju/`` and is checked in so reviewers see both
halves in one PR.

Usage:
    uv run python scripts/build_juju_skills_bundle.py
    uv run python scripts/build_juju_skills_bundle.py --check
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import pathlib
import re
import sys
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_SKILLS_DIR = REPO_ROOT / "src" / "cantrip" / "skills"
BUNDLE_DIR = REPO_ROOT / "examples" / "bundles" / "canonical-skills-juju"
DEST_DIR = BUNDLE_DIR / "skills" / "products" / "juju"

# The bundle version stamped onto every generated SKILL.md. Bump on a curated
# release of the bundle (new skills shipped, descriptions reworked) — patch
# bumps for content-only edits to the underlying cantrip skills.
BUNDLE_VERSION = "1.0.0"

# Substitutions applied to the rendered body of every shipped skill. Cantrip's
# bundled tool aliases collapse onto their stable CLI equivalents so the
# published assets read for any agent, not just cantrip's autonomous loop.
# Order matters — longer keys go first to avoid prefix collisions
# (e.g. ``charmcraft_pack`` before ``charmcraft``).
_TOOL_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("charmcraft_pack", "charmcraft pack"),
    ("charmcraft_init", "charmcraft init"),
    ("charmcraft_upload", "charmcraft upload"),
    ("charmcraft_release", "charmcraft release"),
    ("charmcraft_fetch_libs", "charmcraft fetch-libs"),
    ("rockcraft_pack", "rockcraft pack"),
    ("rockcraft_init", "rockcraft init"),
    ("juju_deploy", "juju deploy"),
    ("juju_refresh", "juju refresh"),
    ("juju_wait", "juju wait-for application"),
    ("juju_relate", "juju integrate"),
    ("juju_integrate", "juju integrate"),
    ("juju_status", "juju status"),
    ("juju_config", "juju config"),
    ("juju_run_action", "juju run"),
    ("juju_offer", "juju offer"),
    ("juju_consume", "juju consume"),
    ("juju_list_offers", "juju find-offers"),
    ("juju_dispatch", "juju exec"),
    ("juju_debug_log", "juju debug-log"),
    ("juju_add_model", "juju add-model"),
    ("juju_destroy_model", "juju destroy-model"),
    ("git_clone", "git clone"),
)

# Cantrip helper tool names that have no clean CLI substitute. We don't try to
# rewrite these — the leading banner warns readers to translate them to the
# closest charmcraft / juju invocation. Listed here so the drift-guard test
# can verify the banner stays accurate.
CANTRIP_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "charm_validate",
        "charm_audit",
        "charm_sync",
        "quick_pack",
        "analyse_framework",
        "harness_inventory",
        "scenario_coverage",
        "generate_readme",
        "generate_terraform",
        "validate_terraform",
        "registry_search",
        "registry_image_info",
        "registry_image_exists",
        "registry_mirror",
        "setup_local_registry",
        "local_registry_status",
        "skopeo_registry_push",
        "loki_query",
        "tempo_query",
        "k8s_diagnostics",
        "inspect_env_keys",
        "preflight_targets",
        "check_rock_contract",
        "check_chisel_eligibility",
        "run_charm_tests",
        "web_fetch",
        "operational_readiness",
        "charmhub_search",
        "charmhub_info",
    }
)


@dataclasses.dataclass(frozen=True)
class SkillSpec:
    """One entry in the bundle manifest.

    Each entry binds a destination bundle name to a source cantrip skill and
    carries the per-skill metadata the canonical/skills validator demands.
    """

    bundle_name: str
    source_name: str
    summary: str
    tags: tuple[str, ...]
    when: str


# The v1 manifest. See ``design/JUJU_SKILLS_BUNDLE.md`` for the per-skill
# rationale and the skip list.
MANIFEST: tuple[SkillSpec, ...] = (
    SkillSpec(
        bundle_name="juju-charmcraft-yaml",
        source_name="charmcraft",
        summary=(
            "Authoring charmcraft.yaml, building and packaging charms, managing"
            " charm libraries, and publishing to Charmhub."
        ),
        tags=("juju", "charmcraft", "charmcraft-yaml", "packaging"),
        when=(
            "edit charmcraft.yaml, run charmcraft pack, run charmcraft init,"
            " manage charm libraries, publish a charm to Charmhub, set up"
            " multi-base builds, configure relations / config options,"
            " set up storage or containers."
        ),
    ),
    SkillSpec(
        bundle_name="juju-charm-py-custom",
        source_name="custom-charm",
        summary=(
            "End-to-end workflow for building ops-framework Juju charms for"
            " custom applications on Kubernetes (Pebble) or machine (systemd)."
        ),
        tags=("juju", "ops", "charm-py", "kubernetes", "machine", "pebble"),
        when=(
            "build a custom Juju charm, write src/charm.py with Pebble,"
            " write a machine charm with systemd, decide K8s vs machine"
            " substrate, scaffold a non-paas-charm with charmcraft init,"
            " customise the ops framework charm lifecycle."
        ),
    ),
    SkillSpec(
        bundle_name="juju-charm-py-infrastructure",
        source_name="infrastructure-charm",
        summary=(
            "Charm workflow for infrastructure software with peer relations,"
            " leader election, primary/replica failover, backup and restore."
        ),
        tags=(
            "juju",
            "ops",
            "charm-py",
            "infrastructure",
            "database",
            "cache",
            "broker",
        ),
        when=(
            "charm infrastructure software, charm a database / cache /"
            " message broker / proxy / monitoring system, implement peer"
            " relations, leader election, primary/replica failover, backup"
            " and restore actions, clustering."
        ),
    ),
    SkillSpec(
        bundle_name="juju-relation-data",
        source_name="relation-data-design",
        summary=(
            "Designing and implementing Juju relation databags (app + unit +"
            " peer), with safe secret sharing over relations."
        ),
        tags=("juju", "ops", "relations", "data-bag", "secrets"),
        when=(
            "design a Juju relation data bag, implement provider or requirer"
            " side of a charm relation, share Juju secrets over relations,"
            " design peer relations, write data validators."
        ),
    ),
    SkillSpec(
        bundle_name="juju-observability-cos",
        source_name="observability",
        summary=(
            "Wire Juju charms into the Canonical Observability Stack"
            " (ops-tracing, Prometheus + alerts, Loki, Grafana, Tempo,"
            " Alertmanager, Sloth, Catalogue, SEC0045)."
        ),
        tags=(
            "juju",
            "cos",
            "prometheus",
            "loki",
            "grafana",
            "tempo",
            "ops-tracing",
        ),
        when=(
            "add COS observability to a charm, wire ops-tracing, expose"
            " prometheus metrics, forward logs to Loki, ship Grafana"
            " dashboards, write Prometheus alert rules, configure"
            " Alertmanager routing, add Sloth SLOs, register with the"
            " Catalogue landing page, emit SEC0045 security event logs."
        ),
    ),
    SkillSpec(
        bundle_name="juju-scenario-tests",
        source_name="scenario-tests",
        summary=(
            "Writing unit tests for Juju charms with ops.testing (Scenario),"
            " the modern state-transition replacement for the deprecated"
            " Harness."
        ),
        tags=("juju", "ops", "testing", "scenario", "unit-tests"),
        when=(
            "write unit tests for a Juju charm, write Scenario tests with"
            " ops.testing, test charm with State and Context, test relations"
            " / config / pebble-ready / actions / secrets / collect-status,"
            " write multi-event state-transition tests."
        ),
    ),
    SkillSpec(
        bundle_name="juju-jubilant-tests",
        source_name="jubilant-tests",
        summary=(
            "Writing integration tests for Juju charms with Jubilant +"
            " pytest-jubilant; cross-model COS Lite smoke patterns."
        ),
        tags=("juju", "testing", "jubilant", "integration-tests"),
        when=(
            "write integration tests for a Juju charm, use Jubilant +"
            " pytest-jubilant, deploy charms in a test, relate to"
            " postgresql or COS, run actions in tests, write cross-model"
            " COS Lite smoke tests."
        ),
    ),
    SkillSpec(
        bundle_name="juju-harness-to-scenario",
        source_name="harness-migration",
        summary=(
            "Migrating deprecated ops.testing.Harness unit tests to"
            " state-transition (Scenario) tests, file by file."
        ),
        tags=(
            "juju",
            "ops",
            "testing",
            "scenario",
            "harness",
            "migration",
        ),
        when=(
            "migrate ops.testing.Harness tests to Scenario, modernise"
            " legacy Juju charm unit tests, rewrite Harness-based tests as"
            " state-transition tests, port relation_changed /"
            " pebble_ready / action tests off Harness."
        ),
    ),
    SkillSpec(
        bundle_name="juju-charm-actions",
        source_name="adding-actions",
        summary=(
            "Implementing Juju actions for operational tasks: declaration,"
            " handlers, progress logging, Scenario tests."
        ),
        tags=("juju", "ops", "actions", "operational"),
        when=(
            "add Juju actions to a charm, implement backup / rotate-"
            "credentials / restore actions, declare actions in"
            " charmcraft.yaml, write action handlers, test actions with"
            " Scenario, run actions with juju run."
        ),
    ),
    SkillSpec(
        bundle_name="juju-charm-config",
        source_name="adding-config",
        summary=(
            "Adding and validating Juju charm configuration options;"
            " applying config to Pebble layers and machine workloads."
        ),
        tags=("juju", "ops", "config", "config-changed"),
        when=(
            "add charm configuration options, declare config in"
            " charmcraft.yaml, validate config values in config-changed,"
            " apply config to a Pebble layer, apply config to a machine"
            " charm, write Scenario tests for config."
        ),
    ),
)


_FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)


def _parse_source(text: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md into YAML frontmatter + Markdown body."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("source skill is missing YAML frontmatter")
    data = yaml.safe_load(match.group(1)) or {}
    body = text[match.end() :]
    return data, body


def _apply_tool_substitutions(body: str) -> str:
    """Rewrite cantrip-bundled tool names to their stable CLI equivalents."""
    for cantrip_name, cli_name in _TOOL_SUBSTITUTIONS:
        body = body.replace(cantrip_name, cli_name)
    return body


def _build_description(source_desc: str, when: str) -> str:
    """Build a canonical/skills-shaped description.

    The validator demands at least 20 words and a trigger marker
    (``WHEN:`` / ``activat`` / ``trigger``). We promote the cantrip
    one-liner into a multi-line YAML block whose second sentence is the
    ``WHEN:`` trigger phrases — the same convention the upstream
    ``generate-agent-skills`` skill recommends.
    """
    source_desc = source_desc.strip().rstrip(".")
    return f"{source_desc}. WHEN: {when}"


def _render_skill(spec: SkillSpec, source_text: str) -> str:
    """Apply the manifest entry to a source SKILL.md and return the output."""
    source_meta, body = _parse_source(source_text)
    source_desc = str(source_meta.get("description") or "").strip()
    if not source_desc:
        raise ValueError(f"{spec.source_name}: source skill is missing a description")

    new_meta: dict[str, Any] = {
        "name": spec.bundle_name,
        "description": _build_description(source_desc, spec.when),
        "license": "Apache-2.0",
        "metadata": {
            "author": "Canonical/cantrip",
            "version": BUNDLE_VERSION,
            "summary": spec.summary,
            "tags": list(spec.tags),
        },
    }

    buf = io.StringIO()
    buf.write("---\n")
    yaml.safe_dump(
        new_meta,
        buf,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=80,
    )
    buf.write("---\n\n")
    buf.write(_banner(spec))
    buf.write("\n\n")
    buf.write(_apply_tool_substitutions(body).lstrip())
    return buf.getvalue()


def _banner(spec: SkillSpec) -> str:
    return (
        f"<!--\n"
        f"Generated from Cantrip's source skill at\n"
        f"`src/cantrip/skills/{spec.source_name}/SKILL.md`\n"
        f"(https://github.com/canonical/cantrip). Do NOT hand-edit —\n"
        f"re-run `make juju-skills-bundle` instead.\n"
        f"\n"
        f"Procedure steps may reference cantrip-specific helper tools (for\n"
        f"example `charm_validate`, `quick_pack`, `harness_inventory`).\n"
        f"Substitute the equivalent `charmcraft` / `juju` / standard CLI\n"
        f"invocation when running without cantrip.\n"
        f"-->"
    )


def _render_bundle_readme() -> str:
    skills_table = "\n".join(
        f"| `{spec.bundle_name}` | `src/cantrip/skills/{spec.source_name}/` | {spec.summary} |"
        for spec in MANIFEST
    )
    return f"""# Canonical Skills — Juju Bundle (generated)

This directory is the regenerated output of
`scripts/build_juju_skills_bundle.py`. Do **not** hand-edit any file under
`skills/`; edit the source skill in `src/cantrip/skills/<name>/SKILL.md` and
re-run `make juju-skills-bundle` to refresh the bundle.

The bundle is intended for publication to
[`canonical/skills`](https://github.com/canonical/skills) under
`skills/products/juju/<skill-name>/SKILL.md`. See
[`design/JUJU_SKILLS_BUNDLE.md`](../../design/research/JUJU_SKILLS_BUNDLE.md) for the
scope decision, frontmatter contract, and deferred items.

## Contents

| Bundle name | Source | Summary |
|---|---|---|
{skills_table}

## Regenerate

```bash
make juju-skills-bundle           # write the bundle from source
make juju-skills-bundle-check     # exit 1 if the regenerated bundle differs from the committed copy
```

The `-check` form is the drift guard `make check` runs via
`tests/unit/test_juju_skills_bundle.py`.

## Publishing

The push to `canonical/skills` is manual in v1. Copy
`examples/bundles/canonical-skills-juju/skills/products/juju/` into a local checkout
of `canonical/skills` and open a PR there. Upstream
`scripts/validate_skills.py` will validate the frontmatter on its CI.
"""


def _iter_outputs() -> list[tuple[pathlib.Path, str]]:
    """Compute the planned output files without writing anything."""
    outputs: list[tuple[pathlib.Path, str]] = []
    for spec in MANIFEST:
        source_path = SOURCE_SKILLS_DIR / spec.source_name / "SKILL.md"
        if not source_path.exists():
            raise FileNotFoundError(f"manifest references missing source skill: {source_path}")
        source_text = source_path.read_text(encoding="utf-8")
        rendered = _render_skill(spec, source_text)
        dest = DEST_DIR / spec.bundle_name / "SKILL.md"
        outputs.append((dest, rendered))
    outputs.append((BUNDLE_DIR / "README.md", _render_bundle_readme()))
    return outputs


def build() -> None:
    """Regenerate the bundle on disk."""
    for path, content in _iter_outputs():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def check() -> int:
    """Return 0 if the on-disk bundle matches a fresh regeneration, else 1."""
    drift: list[pathlib.Path] = []
    for path, content in _iter_outputs():
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing != content:
            drift.append(path)
    if drift:
        print("Bundle drift detected. Run `make juju-skills-bundle`.", file=sys.stderr)
        for path in drift:
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the regenerated bundle differs from disk.",
    )
    args = parser.parse_args(argv)
    if args.check:
        return check()
    build()
    print(f"Regenerated {len(MANIFEST)} skills under {BUNDLE_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
