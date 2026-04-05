"""Metadata rules — charmcraft.yaml field completeness."""

from charmlint.models import CharmContext, Diagnostic, Severity
from charmlint.rules import Rule

# (field_name, rule_id, human_description, default_severity)
_METADATA_CHECKS: list[tuple[str, str, str, Severity]] = [
    ("name", "META001", "Missing 'name' field in charm metadata", Severity.ERROR),
    ("display-name", "META002", "Missing 'display-name' field", Severity.WARNING),
    ("summary", "META003", "Missing 'summary' field", Severity.WARNING),
    ("description", "META004", "Missing 'description' field", Severity.WARNING),
    ("docs", "META005", "Missing 'docs' URL", Severity.INFO),
    ("issues", "META006", "Missing 'issues' URL", Severity.INFO),
    ("source", "META007", "Missing 'source' URL", Severity.INFO),
]


def _make_rule(_field: str, _id: str, _msg: str, _sev: Severity) -> type[Rule]:
    """Dynamically create a Rule subclass for a metadata field check."""
    fld, rid, msg, sev = _field, _id, _msg, _sev

    class _MetadataRule(Rule):
        id = rid
        name = f"missing-{fld}"
        description = msg
        default_severity = sev

        def check(self, context: CharmContext) -> list[Diagnostic]:
            if not context.metadata.get(fld):
                return [self.diagnostic(msg, path="charmcraft.yaml")]
            return []

    _MetadataRule.__name__ = f"MetadataRule_{rid}"
    _MetadataRule.__qualname__ = _MetadataRule.__name__
    return _MetadataRule


# Register all metadata rules.
for _field, _rule_id, _message, _severity in _METADATA_CHECKS:
    _make_rule(_field, _rule_id, _message, _severity)
