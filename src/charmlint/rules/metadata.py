"""Metadata rules — charmcraft.yaml field completeness.

The unified ``charmcraft.yaml`` renamed several fields that the legacy
``metadata.yaml`` kept at the top level: ``display-name`` became
``title``, and the ``docs`` / ``issues`` / ``source`` URLs moved into a
``links`` mapping (as ``documentation`` / ``issues`` / ``source``).
Each rule below therefore accepts the modern spelling *or* the legacy
one, so a compliant modern charm is not flagged while an unmigrated
``metadata.yaml`` charm keeps linting as before.
"""

import dataclasses
from typing import Any

from .. import models
from . import Rule


@dataclasses.dataclass(frozen=True)
class _MetadataCheck:
    """One field-completeness check.

    ``keys`` are top-level metadata keys and ``link_keys`` are keys
    under the ``links`` mapping; the field counts as declared when any
    of them holds a value.
    """

    field: str
    rule_id: str
    message: str
    severity: models.Severity
    keys: tuple[str, ...]
    link_keys: tuple[str, ...] = ()


_METADATA_CHECKS: list[_MetadataCheck] = [
    _MetadataCheck(
        field="name",
        rule_id="META001",
        message="Missing 'name' field in charm metadata",
        severity=models.Severity.ERROR,
        keys=("name",),
    ),
    _MetadataCheck(
        field="title",
        rule_id="META002",
        message="Missing 'title' field (or legacy 'display-name')",
        severity=models.Severity.WARNING,
        keys=("title", "display-name"),
    ),
    _MetadataCheck(
        field="summary",
        rule_id="META003",
        message="Missing 'summary' field",
        severity=models.Severity.WARNING,
        keys=("summary",),
    ),
    _MetadataCheck(
        field="description",
        rule_id="META004",
        message="Missing 'description' field",
        severity=models.Severity.WARNING,
        keys=("description",),
    ),
    _MetadataCheck(
        field="docs",
        rule_id="META005",
        message="Missing documentation URL ('links.documentation' or legacy 'docs')",
        severity=models.Severity.INFO,
        keys=("docs",),
        link_keys=("documentation",),
    ),
    _MetadataCheck(
        field="issues",
        rule_id="META006",
        message="Missing issues URL ('links.issues' or legacy 'issues')",
        severity=models.Severity.INFO,
        keys=("issues",),
        link_keys=("issues",),
    ),
    _MetadataCheck(
        field="source",
        rule_id="META007",
        message="Missing source URL ('links.source' or legacy 'source')",
        severity=models.Severity.INFO,
        keys=("source",),
        link_keys=("source",),
    ),
]


def _is_populated(value: Any) -> bool:
    """Whether a metadata value counts as present.

    ``links.issues``, ``links.source`` and ``links.website`` accept
    either a single string or a list of strings, so a bare truthiness
    test would treat ``source: ['']`` as satisfied.  Blank strings and
    lists holding only blanks are as good as absent.
    """
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_is_populated(item) for item in value)
    return bool(value)


def _is_declared(metadata: dict[str, Any], spec: _MetadataCheck) -> bool:
    """Whether *metadata* declares the field *spec* looks for."""
    if any(_is_populated(metadata.get(key)) for key in spec.keys):
        return True
    links = metadata.get("links")
    if not isinstance(links, dict):
        return False
    return any(_is_populated(links.get(key)) for key in spec.link_keys)


def _make_rule(spec: _MetadataCheck) -> type[Rule]:
    """Dynamically create a Rule subclass for a metadata field check."""

    class _MetadataRule(Rule):
        id = spec.rule_id
        name = f"missing-{spec.field}"
        description = spec.message
        default_severity = spec.severity

        def check(self, context: models.CharmContext) -> list[models.Diagnostic]:
            if _is_declared(context.metadata, spec):
                return []
            return [self.diagnostic(spec.message, path="charmcraft.yaml")]

    _MetadataRule.__name__ = f"MetadataRule_{spec.rule_id}"
    _MetadataRule.__qualname__ = _MetadataRule.__name__
    return _MetadataRule


# Register all metadata rules.
for _spec in _METADATA_CHECKS:
    _make_rule(_spec)
