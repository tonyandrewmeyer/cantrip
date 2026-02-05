"""Tests for Juju status parsing."""

from cantrip.juju.status import parse_status_json


def test_parse_empty_status():
    """Test parsing empty status."""
    data = {
        "model": {
            "name": "test-model",
            "cloud": "localhost",
            "region": None,
            "controller": "test-controller",
        },
        "applications": {},
    }

    status = parse_status_json(data)

    assert status.name == "test-model"
    assert status.cloud == "localhost"
    assert status.controller == "test-controller"
    assert status.apps == []


def test_parse_status_with_app():
    """Test parsing status with an application."""
    data = {
        "model": {
            "name": "dev",
            "cloud": "localhost",
            "region": None,
            "controller": "lxd",
        },
        "applications": {
            "flask-app": {
                "charm": "flask-app",
                "application-status": {
                    "current": "active",
                    "message": "Ready",
                },
                "units": {
                    "flask-app/0": {
                        "workload-status": {
                            "current": "active",
                            "message": "Running",
                        },
                        "juju-status": {
                            "current": "idle",
                        },
                        "address": "10.0.0.5",
                        "open-ports": ["8000/tcp"],
                    }
                },
                "relations": {
                    "database": ["postgresql"],
                },
            }
        },
    }

    status = parse_status_json(data)

    assert status.name == "dev"
    assert len(status.apps) == 1

    app = status.apps[0]
    assert app.name == "flask-app"
    assert app.status == "active"
    assert len(app.units) == 1

    unit = app.units[0]
    assert unit.name == "flask-app/0"
    assert unit.workload_status == "active"
    assert unit.address == "10.0.0.5"
    assert "8000/tcp" in unit.ports

    assert "database" in app.relations
    assert "postgresql" in app.relations["database"]
