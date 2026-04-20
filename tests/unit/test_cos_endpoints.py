"""Tests for :mod:`cantrip.agent.cos_endpoints`."""

from __future__ import annotations

import json
import urllib.parse
from unittest import mock

import jubilant
import pytest

from cantrip.agent import cos_endpoints


def _app(
    status: str = "active",
    message: str = "",
    unit_statuses: tuple[str, ...] = ("active",),
) -> mock.MagicMock:
    """Build a mock app with the given app status and unit workload statuses."""
    mock_app = mock.MagicMock()
    mock_app.app_status.current = status
    mock_app.app_status.message = message

    units: dict[str, mock.MagicMock] = {}
    for idx, unit_status in enumerate(unit_statuses):
        mock_unit = mock.MagicMock()
        mock_unit.workload_status.current = unit_status
        mock_unit.workload_status.message = ""
        units[f"unit/{idx}"] = mock_unit
    mock_app.units = units
    return mock_app


def _status(apps: dict[str, mock.MagicMock]) -> jubilant.Status:
    """Wrap ``apps`` in a ``jubilant.Status``-spec'd MagicMock."""
    mock_status = mock.MagicMock(spec=jubilant.Status)
    mock_status.apps = apps
    return mock_status


class TestDeriveEndpoints:
    def test_none_status_returns_unknown(self):
        """No poll yet — known is False and everything else is the default."""
        endpoints = cos_endpoints.derive_endpoints(None)
        assert endpoints.known is False
        assert endpoints.has_grafana is False
        assert endpoints.has_tempo is False
        assert endpoints.has_loki is False
        assert endpoints.grafana_url is None
        assert endpoints.grafana_explore_url is None
        assert endpoints.tempo_explore_url is None
        assert endpoints.loki_explore_url is None

    def test_empty_status_is_known_but_empty(self):
        """A status with no apps is known=True but flags all False."""
        endpoints = cos_endpoints.derive_endpoints(_status({}))
        assert endpoints.known is True
        assert endpoints.has_grafana is False
        assert endpoints.grafana_url is None
        assert endpoints.grafana_active is False

    def test_grafana_active_with_url_in_message(self):
        """A URL in the workload-status message is lifted into ``grafana_url``."""
        endpoints = cos_endpoints.derive_endpoints(
            _status(
                {
                    "grafana-k8s": _app(
                        message="Serving at http://grafana.example:3000",
                    ),
                }
            )
        )
        assert endpoints.has_grafana is True
        assert endpoints.grafana_active is True
        assert endpoints.grafana_url == "http://grafana.example:3000"
        assert endpoints.grafana_explore_url == "http://grafana.example:3000/explore"

    def test_grafana_active_without_url(self):
        """A running Grafana with no URL in its message still reports active."""
        endpoints = cos_endpoints.derive_endpoints(_status({"grafana-k8s": _app(message="")}))
        assert endpoints.has_grafana is True
        assert endpoints.grafana_active is True
        assert endpoints.grafana_url is None
        assert endpoints.grafana_explore_url is None

    def test_grafana_blocked_unit_is_not_active(self):
        """A unit in ``blocked`` flips ``grafana_active`` to False."""
        endpoints = cos_endpoints.derive_endpoints(
            _status(
                {
                    "grafana-k8s": _app(
                        unit_statuses=("active", "blocked"),
                    ),
                }
            )
        )
        assert endpoints.has_grafana is True
        assert endpoints.grafana_active is False

    def test_grafana_with_no_units_is_not_active(self):
        """An app with zero units can't be reachable."""
        endpoints = cos_endpoints.derive_endpoints(
            _status({"grafana-k8s": _app(unit_statuses=())})
        )
        assert endpoints.has_grafana is True
        assert endpoints.grafana_active is False

    def test_has_tempo_and_loki_by_name_prefix(self):
        """Prefix match picks up ``tempo``, ``tempo-k8s``, ``loki``, ``loki-k8s``."""
        endpoints = cos_endpoints.derive_endpoints(
            _status(
                {
                    "tempo-k8s": _app(),
                    "loki": _app(),
                }
            )
        )
        assert endpoints.has_tempo is True
        assert endpoints.has_loki is True

    def test_missing_tempo_and_loki(self):
        """Apps without a COS component leave the corresponding flag False."""
        endpoints = cos_endpoints.derive_endpoints(_status({"grafana-k8s": _app()}))
        assert endpoints.has_tempo is False
        assert endpoints.has_loki is False

    def test_tempo_explore_url_requires_grafana_url_and_tempo(self):
        """Tempo explore URL needs both a Grafana base and Tempo app present."""
        # Only Tempo — no Grafana URL.
        endpoints = cos_endpoints.derive_endpoints(_status({"tempo-k8s": _app()}))
        assert endpoints.tempo_explore_url is None
        # Grafana URL but no Tempo.
        endpoints = cos_endpoints.derive_endpoints(
            _status(
                {
                    "grafana-k8s": _app(
                        message="URL: http://g.example",
                    ),
                }
            )
        )
        assert endpoints.tempo_explore_url is None

    def test_explore_urls_embed_datasource(self):
        """Full URL carries a JSON ``left`` blob selecting the datasource."""
        endpoints = cos_endpoints.derive_endpoints(
            _status(
                {
                    "grafana-k8s": _app(
                        message="URL: http://g.example",
                    ),
                    "tempo-k8s": _app(),
                    "loki-k8s": _app(),
                }
            )
        )
        for url, datasource in (
            (endpoints.tempo_explore_url, "tempo"),
            (endpoints.loki_explore_url, "loki"),
        ):
            assert url is not None
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            pane = json.loads(params["left"][0])
            assert pane["datasource"] == datasource
            assert pane["queries"] == [{"refId": "A"}]

    def test_url_regex_stops_at_whitespace(self):
        """Trailing commentary in the status message must not leak into the URL."""
        endpoints = cos_endpoints.derive_endpoints(
            _status(
                {
                    "grafana-k8s": _app(
                        message="Serving at http://g.example:3000 (admin: change me)",
                    ),
                }
            )
        )
        assert endpoints.grafana_url == "http://g.example:3000"


@pytest.mark.parametrize(
    ("base", "expected_prefix"),
    [
        ("http://g.example", "http://g.example/explore?"),
        ("http://g.example/", "http://g.example/explore?"),
    ],
)
def test_grafana_explore_url_normalises_trailing_slash(base: str, expected_prefix: str) -> None:
    """The base URL's trailing slash should not produce a double slash."""
    endpoints = cos_endpoints.CosEndpoints(known=True, grafana_url=base)
    assert endpoints.grafana_explore_url is not None
    assert endpoints.grafana_explore_url.startswith(expected_prefix.rstrip("?"))
