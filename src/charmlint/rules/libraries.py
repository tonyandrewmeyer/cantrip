"""Library rules — fetch-libs imports with PyPI equivalents."""

import re

from .. import models
from . import Rule

# Known charm libraries that have PyPI equivalents.
_FETCH_LIBS_PYPI_MAP: dict[str, str] = {
    "data_platform_libs": "data-platform-libs",
    "grafana_k8s": "grafana-k8s-lib",
    "loki_k8s": "loki-k8s-lib",
    "prometheus_k8s": "prometheus-k8s-lib",
    "tempo_coordinator_k8s": "tempo-coordinator-k8s-lib",
    "tempo_k8s": "tempo-k8s-lib",
    "traefik_k8s": "traefik-k8s-lib",
    "catalogue_k8s": "catalogue-k8s-lib",
    "certificate_transfer_interface": "certificate-transfer-interface-lib",
    "tls_certificates_interface": "tls-certificates-interface-lib",
    "observability_libs": "observability-libs",
    "operator_libs_linux": "operator-libs-linux",
    "sdcore_nms_k8s": "sdcore-nms-k8s-lib",
}

_IMPORT_RE = re.compile(r"from\s+charms\.(\w+)\.v\d+\.\w+")


class FetchLibsHasPyPI(Rule):
    """Detect fetch-libs imports that have known PyPI equivalents."""

    id = "LIB001"
    name = "fetch-libs-has-pypi"
    description = "Charm library import has a PyPI equivalent"
    default_severity = models.Severity.WARNING

    def check(self, context: models.CharmContext) -> list[models.Diagnostic]:
        diagnostics: list[models.Diagnostic] = []
        seen: set[str] = set()

        for path, content in context.python_sources.items():
            for match in _IMPORT_RE.finditer(content):
                prefix = match.group(1)
                if prefix in seen:
                    continue
                seen.add(prefix)

                pypi_name = _FETCH_LIBS_PYPI_MAP.get(prefix)
                if pypi_name:
                    line = content[: match.start()].count("\n") + 1
                    diagnostics.append(
                        self.diagnostic(
                            f"charms.{prefix} — replace with PyPI package '{pypi_name}'",
                            path=str(path),
                            line=line,
                            fix_hint=f"pip install {pypi_name}",
                        )
                    )
        return diagnostics


class FetchLibsUnknownPyPI(Rule):
    """Detect fetch-libs imports with no known PyPI equivalent."""

    id = "LIB002"
    name = "fetch-libs-unknown-pypi"
    description = "Charm library import — check PyPI for a published equivalent"
    default_severity = models.Severity.INFO

    def check(self, context: models.CharmContext) -> list[models.Diagnostic]:
        diagnostics: list[models.Diagnostic] = []
        seen: set[str] = set()

        for path, content in context.python_sources.items():
            for match in _IMPORT_RE.finditer(content):
                prefix = match.group(1)
                if prefix in seen:
                    continue
                seen.add(prefix)

                if prefix not in _FETCH_LIBS_PYPI_MAP:
                    line_no = content[: match.start()].count("\n") + 1
                    diagnostics.append(
                        self.diagnostic(
                            f"charms.{prefix} — check PyPI for a published equivalent",
                            path=str(path),
                            line=line_no,
                        )
                    )
        return diagnostics
