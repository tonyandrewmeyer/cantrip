"""Config quality rules — types, defaults, descriptions."""

from charmlint.models import CharmContext, Diagnostic, Severity
from charmlint.rules import Rule


class ConfigMissingType(Rule):
    """Check that all config options have a defined type."""

    id = "CFG001"
    name = "config-missing-type"
    description = "Config option is missing a type"
    default_severity = Severity.WARNING

    def check(self, context: CharmContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for opt_name, opt_def in context.config_options.items():
            if not isinstance(opt_def, dict):
                continue
            if not opt_def.get("type"):
                diagnostics.append(
                    self.diagnostic(
                        f"Config option '{opt_name}' is missing a type",
                        path="charmcraft.yaml",
                    )
                )
        return diagnostics


class ConfigMissingDefault(Rule):
    """Check that all config options have a default value."""

    id = "CFG002"
    name = "config-missing-default"
    description = "Config option is missing a default value"
    default_severity = Severity.INFO

    def check(self, context: CharmContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for opt_name, opt_def in context.config_options.items():
            if not isinstance(opt_def, dict):
                continue
            if "default" not in opt_def:
                diagnostics.append(
                    self.diagnostic(
                        f"Config option '{opt_name}' is missing a default value",
                        path="charmcraft.yaml",
                    )
                )
        return diagnostics


class ConfigMissingDescription(Rule):
    """Check that all config options have a description."""

    id = "CFG003"
    name = "config-missing-description"
    description = "Config option is missing a description"
    default_severity = Severity.WARNING

    def check(self, context: CharmContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for opt_name, opt_def in context.config_options.items():
            if not isinstance(opt_def, dict):
                continue
            if not opt_def.get("description"):
                diagnostics.append(
                    self.diagnostic(
                        f"Config option '{opt_name}' is missing a description",
                        path="charmcraft.yaml",
                    )
                )
        return diagnostics
