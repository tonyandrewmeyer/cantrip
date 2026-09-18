"""Security rules — secrets management, TLS support."""

import re

from .. import models
from . import Rule

_SECRET_CONFIG_KEYWORDS = {"password", "secret", "token", "api-key", "api_key", "credential"}

# Evidence that the charm manages secrets through Juju rather than plain-text
# config.  The ops framework spells the API ``app.add_secret`` /
# ``model.get_secret`` / ``ops.SecretChanged`` — none of which contain the
# literal ``juju…secret``, so matching only that missed every charm using the
# supported API.  The legacy alternative is kept for prose mentions and for
# ``juju secret`` CLI invocations that pre-date the ops surface.
_JUJU_SECRETS_PATTERN = re.compile(
    r"""
      juju.*secret                                     # prose / CLI mention
    | \bSecret(?:Changed|Rotate|Remove|Expired)        # ops event classes
    | \bsecret[-_](?:changed|rotate|rotated|remove|removed|expired)\b
    | \badd_secret\b                                   # Application/Unit.add_secret
    | \bget_secret\b                                   # Model.get_secret
    | \bops\.Secret\b                                  # type annotations
    | \bsecret[-_]id\b
    """,
    re.VERBOSE,
)


def _is_secret_typed(option: object) -> bool:
    """Whether a config option is declared ``type: secret``.

    Such an option holds a secret URI, not the sensitive value itself, so it is
    already the recommended shape and must never be flagged.
    """
    return isinstance(option, dict) and option.get("type") == "secret"


class SecretInPlainConfig(Rule):
    """Detect config options that look like secrets but aren't using Juju secrets."""

    id = "SEC001"
    name = "secret-in-plain-config"
    description = "Secret-like config option found — use Juju secrets instead"
    default_severity = models.Severity.ERROR

    def check(self, context: models.CharmContext) -> list[models.Diagnostic]:
        # Check if the charm uses the Juju secrets API.
        all_source = "\n".join(
            content for path, content in context.python_sources.items() if "lib" not in path.parts
        )
        has_juju_secrets = bool(_JUJU_SECRETS_PATTERN.search(all_source))

        # Look for config options with secret-looking names.  An option already
        # declared ``type: secret`` carries a URI rather than the value, so it
        # is exempt regardless of what the source looks like.
        secret_opts: list[str] = [
            opt_name
            for opt_name, opt_def in context.config_options.items()
            if any(kw in opt_name.lower() for kw in _SECRET_CONFIG_KEYWORDS)
            and not _is_secret_typed(opt_def)
        ]

        if secret_opts and not has_juju_secrets:
            diagnostics: list[models.Diagnostic] = [
                self.diagnostic(
                    f"Config option '{opt}' looks like a secret "
                    f"— use Juju secrets instead of plain-text config",
                    path="charmcraft.yaml",
                    fix_hint=(
                        "Declare the option as 'type: secret' and read the value with "
                        "Model.get_secret()"
                    ),
                )
                for opt in secret_opts
            ]
            return diagnostics
        return []


class NoTLSSupport(Rule):
    """Check for TLS/encryption support."""

    id = "SEC002"
    name = "no-tls-support"
    description = "No TLS/encryption support detected"
    default_severity = models.Severity.INFO

    def check(self, context: models.CharmContext) -> list[models.Diagnostic]:
        # Check for tls-certificates relation.
        for section in ("requires", "provides", "peers"):
            for rel_def in context.metadata.get(section, {}).values():
                if isinstance(rel_def, dict) and rel_def.get("interface") in (
                    "tls-certificates",
                    "certificates",
                ):
                    return []

        # Check source for TLS-related code.
        all_source = "\n".join(context.python_sources.values())
        if re.search(r"\btls\b|\bcertificate\b|\bssl\b", all_source, re.IGNORECASE):
            return []

        return [
            self.diagnostic(
                "No TLS/encryption support detected",
                fix_hint="Add a tls-certificates relation for encryption in transit",
            )
        ]
