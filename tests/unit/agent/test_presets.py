"""Tests for the preset bundle catalogue (:mod:`cantrip.agent.presets`)."""

from __future__ import annotations

import pytest
from jubilant import statustypes

from cantrip.agent import presets

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(apps: dict[str, str]) -> statustypes.Status:
    """Build a minimal k8s Status; ``apps`` maps app name → charm name."""
    return statustypes.Status._from_dict(
        {
            "model": {
                "name": "dev",
                "type": "caas",
                "cloud": "k8s",
                "region": "",
                "version": "3.5.0",
                "controller": "k8s",
                "model-status": {"current": "available"},
            },
            "machines": {},
            "applications": {
                name: {
                    "charm": charm,
                    "charm-origin": "charmhub",
                    "charm-name": charm,
                    "charm-rev": 1,
                    "exposed": False,
                    "application-status": {"current": "active"},
                    "units": {},
                    "relations": {},
                }
                for name, charm in apps.items()
            },
        }
    )


# ---------------------------------------------------------------------------
# Catalogue integrity
# ---------------------------------------------------------------------------


class TestCatalogueIntegrity:
    def test_slugs_are_unique(self) -> None:
        names = presets.preset_names()
        assert len(names) == len(set(names))
        assert set(names) == {b.name for b in presets.CATALOGUE}

    def test_get_preset_round_trips(self) -> None:
        for name in presets.preset_names():
            bundle = presets.get_preset(name)
            assert bundle is not None
            assert bundle.name == name

    def test_get_preset_unknown_is_none(self) -> None:
        assert presets.get_preset("does-not-exist") is None

    @pytest.mark.parametrize("bundle", presets.CATALOGUE, ids=lambda b: b.name)
    def test_edges_reference_known_apps(self, bundle: presets.PresetBundle) -> None:
        app_names = {a.name for a in bundle.apps}
        for edge in bundle.edges:
            assert edge.provider in app_names, f"{bundle.name}: {edge.provider}"
            assert edge.requirer in app_names, f"{bundle.name}: {edge.requirer}"
            assert edge.interface, f"{bundle.name}: empty interface"
            assert edge.description, f"{bundle.name}: empty edge description"

    @pytest.mark.parametrize("bundle", presets.CATALOGUE, ids=lambda b: b.name)
    def test_app_layers_declared(self, bundle: presets.PresetBundle) -> None:
        for app in bundle.apps:
            assert app.layer in bundle.layers, f"{bundle.name}: {app.name} layer {app.layer!r}"
            assert app.summary, f"{bundle.name}: {app.name} has no summary"

    @pytest.mark.parametrize("bundle", presets.CATALOGUE, ids=lambda b: b.name)
    def test_every_app_has_an_edge(self, bundle: presets.PresetBundle) -> None:
        # A preset app with no relations isn't part of the "shape".
        for app in bundle.apps:
            assert bundle.edges_for(app.name), f"{bundle.name}: {app.name} is unconnected"


class TestPresetBundleHelpers:
    def test_apps_by_layer_preserves_order_and_drops_empty(self) -> None:
        cos = presets.get_preset("cos-lite")
        assert cos is not None
        layers = list(cos.apps_by_layer())
        # Only layers that actually have apps, in declaration order.
        assert layers == [lyr for lyr in cos.layers if any(a.layer == lyr for a in cos.apps)]
        assert all(cos.apps_by_layer()[lyr] for lyr in layers)

    def test_app_lookup(self) -> None:
        cos = presets.get_preset("cos-lite")
        assert cos is not None
        assert cos.app("prometheus") is not None
        assert cos.app("prometheus").charm == "prometheus-k8s"
        assert cos.app("nope") is None

    def test_edges_for_both_directions(self) -> None:
        cos = presets.get_preset("cos-lite")
        assert cos is not None
        # Traefik is on the provider side of its ingress edges.
        traefik_edges = cos.edges_for("traefik")
        assert traefik_edges
        assert all("traefik" in (e.provider, e.requirer) for e in traefik_edges)
        # Grafana appears as a requirer on datasource/dashboard edges.
        assert any(e.requirer == "grafana" for e in cos.edges_for("grafana"))


# ---------------------------------------------------------------------------
# match_preset
# ---------------------------------------------------------------------------


class TestMatchPreset:
    def test_empty_model_is_none(self) -> None:
        assert presets.match_preset(_status({})) is None

    def test_full_cos_lite_matches(self) -> None:
        status = _status(
            {
                "traefik": "traefik-k8s",
                "prometheus": "prometheus-k8s",
                "loki": "loki-k8s",
                "alertmanager": "alertmanager-k8s",
                "grafana": "grafana-k8s",
                "catalogue": "catalogue-k8s",
            }
        )
        match = presets.match_preset(status)
        assert match is not None
        assert match.bundle.name == "cos-lite"
        assert match.matched_apps == 6
        assert match.fraction == pytest.approx(1.0)
        assert match.app_layers["traefik"] == "Routing"
        assert match.app_layers["grafana"] == "Visualisation"

    def test_partial_but_over_threshold_matches(self) -> None:
        # 4 of 6 COS apps, all matched by charm name even though renamed.
        status = _status(
            {
                "metrics": "prometheus-k8s",
                "logs": "loki-k8s",
                "alerts": "alertmanager-k8s",
                "dashboards": "grafana-k8s",
            }
        )
        match = presets.match_preset(status)
        assert match is not None
        assert match.bundle.name == "cos-lite"
        assert match.matched_apps == 4
        assert match.app_layers["metrics"] == "Telemetry"

    def test_too_few_apps_is_none(self) -> None:
        status = _status({"prometheus": "prometheus-k8s", "grafana": "grafana-k8s"})
        assert presets.match_preset(status) is None

    def test_below_fraction_is_none(self) -> None:
        # 3 distinct identity-platform apps, but that's only 3/7 < 0.5.
        status = _status(
            {
                "hydra": "hydra",
                "kratos": "kratos",
                "postgresql": "postgresql-k8s",
            }
        )
        # postgresql also matches cos? no — postgresql isn't a COS app.
        # 3 of 7 identity apps → below the fraction gate.
        assert presets.match_preset(status) is None

    def test_app_name_prefix_match(self) -> None:
        # Bundle says "prometheus"; user deployed "prometheus-k8s".
        status = _status(
            {
                "traefik-k8s": "traefik-k8s",
                "prometheus-k8s": "prometheus-k8s",
                "grafana-k8s": "grafana-k8s",
            }
        )
        match = presets.match_preset(status)
        assert match is not None
        assert match.bundle.name == "cos-lite"
        assert match.matched_apps == 3

    def test_paas_placeholder_does_not_match_by_charm(self) -> None:
        # The 12-Factor preset's "app" has charm "<paas-charm>" — a live
        # app named "app" matches by name, but a live charm literally
        # called "<paas-charm>" should never spuriously match.
        status = _status(
            {
                "traefik": "traefik-k8s",
                "postgresql": "postgresql-k8s",
                "app": "flask-k8s",
            }
        )
        match = presets.match_preset(status)
        assert match is not None
        assert match.bundle.name == "twelve-factor-cos"
        assert match.app_layers["app"] == "Application"

    def test_best_match_wins_on_app_count(self) -> None:
        # A real COS Lite model overlaps the twelve-factor-cos preset
        # too (it lists prometheus / loki / grafana), but matches fewer
        # of its apps — so cos-lite wins on matched-app count.
        status = _status(
            {
                "traefik": "traefik-k8s",
                "prometheus": "prometheus-k8s",
                "loki": "loki-k8s",
                "grafana": "grafana-k8s",
                "alertmanager": "alertmanager-k8s",
                "catalogue": "catalogue-k8s",
            }
        )
        match = presets.match_preset(status)
        assert match is not None
        # 6/6 of cos-lite vs 4/8 of twelve-factor-cos.
        assert match.bundle.name == "cos-lite"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRendering:
    def test_render_index_lists_every_preset(self) -> None:
        text = presets.render_index()
        for bundle in presets.CATALOGUE:
            assert f"`{bundle.name}`" in text
            assert bundle.title in text

    @pytest.mark.parametrize("bundle", presets.CATALOGUE, ids=lambda b: b.name)
    def test_render_preset_includes_layers_and_edges(self, bundle: presets.PresetBundle) -> None:
        text = presets.render_preset(bundle)
        assert bundle.title in text
        assert "## Applications" in text
        assert "## Relations" in text
        for layer in bundle.apps_by_layer():
            assert f"**{layer}**" in text
        for edge in bundle.edges:
            assert edge.interface in text
        for app in bundle.apps:
            assert f"`{app.name}`" in text
        # Placeholder charm names never leak into the rendered text.
        assert "<paas-charm>" not in text
        # Optional apps are flagged.
        if any(app.optional for app in bundle.apps):
            assert "optional)" in text
