"""Rule base class and registry for charmlint."""

from abc import ABC, abstractmethod

from charmlint.models import CharmContext, Diagnostic, Severity

# Global rule registry — populated by Rule.__init_subclass__.
_RULES: dict[str, "Rule"] = {}


class Rule(ABC):
    """Base class for all charmlint rules.

    Subclasses must define ``id``, ``name``, ``description``, and
    ``default_severity`` as class attributes, and implement ``check()``.
    Rules are automatically registered on class creation.
    """

    id: str
    name: str
    description: str
    default_severity: Severity

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Only register concrete rules (those with an id attribute).
        if hasattr(cls, "id") and not getattr(cls, "_abstract", False):
            _RULES[cls.id] = cls()

    @abstractmethod
    def check(self, context: CharmContext) -> list[Diagnostic]:
        """Run the rule against the given charm context."""

    def diagnostic(
        self,
        message: str,
        *,
        severity: Severity | None = None,
        path: str | None = None,
        line: int | None = None,
        fix_hint: str | None = None,
    ) -> Diagnostic:
        """Convenience helper to create a Diagnostic for this rule."""
        return Diagnostic(
            rule_id=self.id,
            severity=severity or self.default_severity,
            message=message,
            path=path,
            line=line,
            fix_hint=fix_hint,
        )


def get_all_rules() -> dict[str, Rule]:
    """Return a copy of the rule registry."""
    return dict(_RULES)
