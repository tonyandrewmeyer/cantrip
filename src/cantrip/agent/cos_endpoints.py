"""Derive COS endpoint URLs from a cached Juju status snapshot.

The Trace/Observability screen (F4) needs to surface real Grafana deep-link
URLs and an honest reachability indicator instead of placeholder text.  This
module turns a ``jubilant.Status`` snapshot (typically the watcher's cached
COS poll) into a :class:`CosEndpoints` value the screen can render
synchronously.

No network calls happen here: reachability is inferred from the cached
status only.  If the watcher has never polled, the caller sees
``CosEndpoints(known=False)`` and can render "Unknown" rather than lying
about the state.
"""

from __future__ import annotations

import dataclasses
import json
import re
import typing
import urllib.parse

if typing.TYPE_CHECKING:
    import jubilant

# Grafana-k8s and related charms publish the public URL in the app status
# message (e.g. "Serving at http://grafana.example").  The regex is
# permissive — we just need to lift the first URL token out of free-form
# text that the charm authors control.
_URL_RE = re.compile(r"https?://[^\s,;]+")

# Charms use suffixed names like ``grafana-k8s``, ``loki-k8s``, ``tempo``.
# Matching by prefix keeps us tolerant of deployments that rename apps.
_GRAFANA_PREFIXES = ("grafana",)
_TEMPO_PREFIXES = ("tempo",)
_LOKI_PREFIXES = ("loki",)

# ``grafana-agent`` / ``grafana-agent-k8s`` is a telemetry forwarder, not the
# Grafana UI — it ships no public URL and would shadow the real ``grafana-k8s``
# match on any model that runs both, blanking the F4 endpoint screen.  The
# tempo / loki families don't have an analogous sibling, so this exclusion
# is grafana-specific.
_GRAFANA_EXCLUDE_SUBSTRINGS = ("agent",)


@dataclasses.dataclass(frozen=True)
class CosEndpoints:
    """Snapshot of COS endpoint info parsed from a Juju status.

    ``known`` is False before the first poll has landed; the other fields
    should be ignored in that case.  Once True, the other fields describe
    what the cached snapshot contained.
    """

    known: bool = False
    grafana_url: str | None = None
    grafana_active: bool = False
    has_grafana: bool = False
    has_tempo: bool = False
    has_loki: bool = False

    @property
    def grafana_explore_url(self) -> str | None:
        """Grafana Explore landing page, or None if the base URL is unknown."""
        if self.grafana_url is None:
            return None
        return f"{self.grafana_url.rstrip('/')}/explore"

    @property
    def tempo_explore_url(self) -> str | None:
        """Grafana Explore deep-link preselecting the Tempo datasource."""
        if self.grafana_url is None or not self.has_tempo:
            return None
        return _build_explore_url(self.grafana_url, datasource="tempo")

    @property
    def loki_explore_url(self) -> str | None:
        """Grafana Explore deep-link preselecting the Loki datasource."""
        if self.grafana_url is None or not self.has_loki:
            return None
        return _build_explore_url(self.grafana_url, datasource="loki")


def _build_explore_url(grafana_base: str, *, datasource: str) -> str:
    """Build a Grafana Explore URL preselecting ``datasource``.

    Grafana 10+ accepts a JSON blob in the ``left`` query parameter.
    """
    pane = {
        "datasource": datasource,
        "queries": [{"refId": "A"}],
        "range": {"from": "now-1h", "to": "now"},
    }
    params = {"orgId": "1", "left": json.dumps(pane, separators=(",", ":"))}
    return f"{grafana_base.rstrip('/')}/explore?{urllib.parse.urlencode(params)}"


def _name_matches(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name.startswith(p) for p in prefixes)


def _extract_grafana(
    status: jubilant.Status,
) -> tuple[bool, bool, str | None]:
    """Return ``(has_grafana, active, url)`` for the COS Grafana app.

    ``active`` is True only when Grafana has at least one unit and every
    unit's workload status is ``active``.  ``url`` is the first URL token
    found in the app's workload status message, if any.
    """
    for name, app in status.apps.items():
        if not _name_matches(name, _GRAFANA_PREFIXES):
            continue
        if any(token in name for token in _GRAFANA_EXCLUDE_SUBSTRINGS):
            continue
        message = app.app_status.message or ""
        match = _URL_RE.search(message)
        url = match.group(0) if match is not None else None
        active = bool(app.units) and all(
            unit.workload_status.current == "active" for unit in app.units.values()
        )
        return True, active, url
    return False, False, None


def derive_endpoints(status: jubilant.Status | None) -> CosEndpoints:
    """Derive :class:`CosEndpoints` from a cached Juju status snapshot.

    Returns ``CosEndpoints(known=False)`` when ``status`` is None so the
    caller can distinguish "no poll yet" from "polled but Grafana absent".
    """
    if status is None:
        return CosEndpoints()
    has_grafana, grafana_active, grafana_url = _extract_grafana(status)
    return CosEndpoints(
        known=True,
        grafana_url=grafana_url,
        grafana_active=grafana_active,
        has_grafana=has_grafana,
        has_tempo=any(_name_matches(n, _TEMPO_PREFIXES) for n in status.apps),
        has_loki=any(_name_matches(n, _LOKI_PREFIXES) for n in status.apps),
    )
