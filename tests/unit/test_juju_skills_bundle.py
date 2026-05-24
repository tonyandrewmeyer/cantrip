"""Drift guard for the canonical/skills Juju bundle.

The bundle at ``bundles/canonical-skills-juju/`` is regenerated from
``src/cantrip/skills/<name>/SKILL.md`` by ``scripts/build_juju_skills_bundle.py``.
These tests fail loudly if the regenerator no longer reproduces the committed
copy (so a source edit without ``make juju-skills-bundle`` is caught) and if
the regenerated frontmatter would not satisfy the canonical/skills validator
(so a malformed bundle never makes it to publication).
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from scripts import build_juju_skills_bundle as builder

_FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)
_SUMMARY_MAX_CHARS = 160
_MIN_DESCRIPTION_WORDS = 20
_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9-]+$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_TRIGGER_RE = re.compile(r"\bWHEN\s*:", re.IGNORECASE)


def _read_frontmatter(path: pathlib.Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    assert match is not None, f"{path}: missing YAML frontmatter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), f"{path}: frontmatter is not a mapping"
    return data


def test_bundle_has_no_drift() -> None:
    """Regenerating the bundle must produce exactly the committed bytes."""
    assert builder.check() == 0, (
        "bundles/canonical-skills-juju/ is out of sync with"
        " src/cantrip/skills/. Run `make juju-skills-bundle` and commit"
        " the regenerated files."
    )


def test_bundle_contains_expected_skills() -> None:
    """Every manifest entry produces a SKILL.md in the destination tree."""
    for spec in builder.MANIFEST:
        path = builder.DEST_DIR / spec.bundle_name / "SKILL.md"
        assert path.exists(), f"missing generated skill: {path}"


def test_bundle_has_readme() -> None:
    readme = builder.BUNDLE_DIR / "README.md"
    assert readme.exists()
    text = readme.read_text(encoding="utf-8")
    assert "make juju-skills-bundle" in text
    assert "canonical/skills" in text


@pytest.mark.parametrize("spec", builder.MANIFEST, ids=lambda s: s.bundle_name)
def test_frontmatter_matches_canonical_skills_validator(
    spec: builder.SkillSpec,
) -> None:
    """Each emitted SKILL.md satisfies the canonical/skills validator's rules."""
    path = builder.DEST_DIR / spec.bundle_name / "SKILL.md"
    data = _read_frontmatter(path)

    # Top-level required fields.
    assert data.get("license") == "Apache-2.0"
    assert isinstance(data.get("name"), str)
    name = data["name"]
    assert _VALID_NAME_RE.fullmatch(name), f"{name!r} is not kebab-case"
    assert name == spec.bundle_name

    description = data.get("description")
    assert isinstance(description, str)
    assert len(description.split()) >= _MIN_DESCRIPTION_WORDS, (
        f"{name}: description must be at least {_MIN_DESCRIPTION_WORDS} words"
    )
    assert _TRIGGER_RE.search(description), (
        f"{name}: description must contain a WHEN: trigger phrase"
    )

    # metadata block.
    metadata = data.get("metadata")
    assert isinstance(metadata, dict)
    author = metadata.get("author")
    assert isinstance(author, str) and author.startswith("Canonical")
    version = metadata.get("version")
    assert isinstance(version, str) and _SEMVER_RE.fullmatch(version), (
        f"{name}: metadata.version must be semver, got {version!r}"
    )
    summary = metadata.get("summary")
    assert isinstance(summary, str)
    assert len(summary) <= _SUMMARY_MAX_CHARS, (
        f"{name}: metadata.summary is {len(summary)} chars (recommended max {_SUMMARY_MAX_CHARS})"
    )
    tags = metadata.get("tags")
    assert isinstance(tags, list) and all(isinstance(t, str) for t in tags)
    assert "juju" in tags, f"{name}: every skill in the Juju bundle carries the 'juju' tag"


@pytest.mark.parametrize("spec", builder.MANIFEST, ids=lambda s: s.bundle_name)
def test_body_carries_derivation_banner(spec: builder.SkillSpec) -> None:
    """Every shipped SKILL.md carries the cantrip-derivation banner."""
    path = builder.DEST_DIR / spec.bundle_name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    # Banner sits right after the frontmatter and before the body's H1.
    assert "Generated from Cantrip's source skill" in text
    assert f"src/cantrip/skills/{spec.source_name}/SKILL.md" in text
    assert "Do NOT hand-edit" in text


@pytest.mark.parametrize("spec", builder.MANIFEST, ids=lambda s: s.bundle_name)
def test_bundled_tool_aliases_have_been_rewritten(
    spec: builder.SkillSpec,
) -> None:
    """The cantrip bundled-tool aliases collapse to their CLI equivalents.

    Catches a regression where a new bundled-tool alias is added to cantrip
    but not to the substitution table, so the published bundle silently
    leaks the cantrip-only name.
    """
    path = builder.DEST_DIR / spec.bundle_name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    for cantrip_name, _cli in builder._TOOL_SUBSTITUTIONS:
        # The banner mentions `quick_pack` / `harness_inventory` etc. as a
        # category warning — those names are in CANTRIP_ONLY_TOOLS and the
        # substitution table never touches them. The substitution-table
        # names should not survive in the output.
        assert cantrip_name not in text, (
            f"{spec.bundle_name}: bundled-tool alias {cantrip_name!r}"
            f" survived the substitution pass"
        )
