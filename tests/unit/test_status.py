"""Tests for Juju status parsing via Jubilant types."""

from jubilant import statustypes


def test_parse_empty_status():
    """Test parsing empty status."""
    data = {
        "model": {
            "name": "test-model",
            "type": "iaas",
            "cloud": "localhost",
            "region": "",
            "version": "3.1.0",
            "controller": "test-controller",
            "model-status": {"current": "available"},
        },
        "machines": {},
        "applications": {},
    }

    status = statustypes.Status._from_dict(data)

    assert status.model.name == "test-model"
    assert status.model.cloud == "localhost"
    assert status.model.controller == "test-controller"
    assert status.apps == {}


def test_parse_status_with_app():
    """Test parsing status with an application."""
    data = {
        "model": {
            "name": "dev",
            "type": "iaas",
            "cloud": "localhost",
            "region": "",
            "version": "3.1.0",
            "controller": "lxd",
            "model-status": {"current": "available"},
        },
        "machines": {},
        "applications": {
            "flask-app": {
                "charm": "flask-app",
                "charm-origin": "local",
                "charm-name": "flask-app",
                "charm-rev": 1,
                "exposed": False,
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
                    "database": [
                        {
                            "related-application": "postgresql",
                            "interface": "pgsql",
                            "scope": "global",
                        }
                    ],
                },
            }
        },
    }

    status = statustypes.Status._from_dict(data)

    assert status.model.name == "dev"
    assert len(status.apps) == 1

    app = status.apps["flask-app"]
    assert app.app_status.current == "active"
    assert len(app.units) == 1

    unit = app.units["flask-app/0"]
    assert unit.workload_status.current == "active"
    assert unit.address == "10.0.0.5"
    assert "8000/tcp" in unit.open_ports

    assert "database" in app.relations
    assert app.relations["database"][0].related_app == "postgresql"
