"""Tests for the shared topology helpers (:mod:`cantrip.tui.topology`)."""

from __future__ import annotations

from jubilant import statustypes

from cantrip.tui import topology


def _status(apps: dict) -> statustypes.Status:
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
            "applications": apps,
        }
    )


def _app(*, status: str = "active", relations: dict | None = None) -> dict:
    return {
        "charm": "test",
        "charm-origin": "local",
        "charm-name": "test",
        "charm-rev": 1,
        "exposed": False,
        "application-status": {"current": status},
        "units": {},
        "relations": relations or {},
    }


def _rel(app_name: str, interface: str) -> dict:
    return {"related-application": app_name, "interface": interface, "scope": "global"}


class TestStatusLookups:
    def test_known_glyph_and_colours(self) -> None:
        assert topology.status_glyph("active") == "●"
        assert topology.status_glyph("blocked") == "◌"
        assert topology.status_colour("blocked") == "$error"
        assert topology.status_rich_colour("waiting") == "yellow"

    def test_unknown_status_falls_back(self) -> None:
        assert topology.status_glyph("brand-new-state") == "○"
        assert topology.status_colour("brand-new-state") == "$text-muted"
        assert topology.status_rich_colour("brand-new-state") == "yellow"


class TestDedupEdges:
    def test_empty_model(self) -> None:
        assert topology.dedup_edges(_status({})) == []

    def test_no_relations(self) -> None:
        assert topology.dedup_edges(_status({"a": _app(), "b": _app()})) == []

    def test_bidirectional_collapses_to_one(self) -> None:
        status = _status(
            {
                "flask-app": _app(
                    relations={"database": [_rel("postgresql", "postgresql_client")]}
                ),
                "postgresql": _app(
                    relations={"database": [_rel("flask-app", "postgresql_client")]}
                ),
            }
        )
        edges = topology.dedup_edges(status)
        assert edges == [
            topology.Edge(a="flask-app", b="postgresql", interface="postgresql_client")
        ]

    def test_sorted_endpoints_are_stable(self) -> None:
        # Whichever end Juju lists first, the Edge is (sorted-low, sorted-high).
        status = _status(
            {
                "zzz": _app(relations={"r": [_rel("aaa", "ingress")]}),
                "aaa": _app(relations={"r": [_rel("zzz", "ingress")]}),
            }
        )
        (edge,) = topology.dedup_edges(status)
        assert (edge.a, edge.b) == ("aaa", "zzz")

    def test_multiple_interfaces_between_same_pair(self) -> None:
        status = _status(
            {
                "a": _app(
                    relations={"x": [_rel("b", "ingress")], "y": [_rel("b", "tls_certificates")]}
                ),
                "b": _app(),
            }
        )
        edges = topology.dedup_edges(status)
        assert {e.interface for e in edges} == {"ingress", "tls_certificates"}
        assert all((e.a, e.b) == ("a", "b") for e in edges)
        # And sorted by interface within the pair.
        assert [e.interface for e in edges] == ["ingress", "tls_certificates"]

    def test_visible_filter_drops_half_dangling_edges(self) -> None:
        status = _status(
            {
                "a": _app(relations={"r": [_rel("b", "ingress")]}),
                "b": _app(relations={"r": [_rel("a", "ingress")], "s": [_rel("c", "db")]}),
                "c": _app(relations={"s": [_rel("b", "db")]}),
            }
        )
        # Hide "c": the b–c edge disappears, a–b stays.
        edges = topology.dedup_edges(status, visible={"a", "b"})
        assert edges == [topology.Edge(a="a", b="b", interface="ingress")]

    def test_edges_touching(self) -> None:
        edges = [
            topology.Edge("a", "b", "ingress"),
            topology.Edge("b", "c", "db"),
            topology.Edge("d", "e", "tls"),
        ]
        touching = topology.edges_touching(edges, "b")
        assert touching == [topology.Edge("a", "b", "ingress"), topology.Edge("b", "c", "db")]
        assert topology.edges_touching(edges, "z") == []
