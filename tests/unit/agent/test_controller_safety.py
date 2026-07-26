"""Tests for controller-safety classification and the confirm gate (Phase 10b)."""

import json
from unittest import mock

from cantrip.agent import controller_safety
from cantrip.agent.controller_safety import (
    ControllerKind,
    ControllerSafety,
    classify_controller,
    confirm_message,
    controller_confirm_required,
    current_controller_safety,
    production_controllers,
)


class TestClassifyController:
    """Tests for the heuristic classifier."""

    def test_localhost_cloud_is_local(self):
        assert classify_controller({"cloud": "localhost"}) is ControllerKind.LOCAL

    def test_lxd_cloud_is_local(self):
        assert classify_controller({"cloud": "lxd"}) is ControllerKind.LOCAL

    def test_k8s_with_loopback_endpoint_is_local(self):
        info = {"cloud": "k8s", "api-endpoints": ["127.0.0.1:17070"]}
        assert classify_controller(info) is ControllerKind.LOCAL

    def test_microk8s_with_snap_socket_is_local(self):
        info = {
            "cloud": "microk8s",
            "api-endpoints": ["unix:///var/snap/microk8s/common/run/socket"],
        }
        assert classify_controller(info) is ControllerKind.LOCAL

    def test_k8s_with_remote_endpoint_is_non_local(self):
        info = {"cloud": "k8s", "api-endpoints": ["10.0.4.7:17070"]}
        assert classify_controller(info) is ControllerKind.NON_LOCAL

    def test_aws_cloud_is_non_local(self):
        info = {"cloud": "aws", "api-endpoints": ["18.224.5.6:17070"]}
        assert classify_controller(info) is ControllerKind.NON_LOCAL

    def test_empty_cloud_is_unknown(self):
        assert classify_controller({}) is ControllerKind.UNKNOWN

    def test_k8s_without_endpoints_is_non_local(self):
        # No endpoints means we cannot prove it's local; fail closed.
        info = {"cloud": "kubernetes", "api-endpoints": []}
        assert classify_controller(info) is ControllerKind.NON_LOCAL


class TestProductionControllers:
    """Tests for the production_controllers settings reader."""

    def test_missing_settings_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(controller_safety, "_SETTINGS_PATH", tmp_path / "settings.json")
        assert production_controllers() == []

    def test_malformed_settings_file(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text("not json", encoding="utf-8")
        monkeypatch.setattr(controller_safety, "_SETTINGS_PATH", path)
        assert production_controllers() == []

    def test_top_level_not_a_mapping(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(["foo"]), encoding="utf-8")
        monkeypatch.setattr(controller_safety, "_SETTINGS_PATH", path)
        assert production_controllers() == []

    def test_value_not_a_list(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"production_controllers": "ctrl"}), encoding="utf-8")
        monkeypatch.setattr(controller_safety, "_SETTINGS_PATH", path)
        assert production_controllers() == []

    def test_valid_list(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps({"production_controllers": ["prod-aws", "prod-k8s", 5]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(controller_safety, "_SETTINGS_PATH", path)
        assert production_controllers() == ["prod-aws", "prod-k8s"]


def _stub_run_juju_json(payload):
    """Build a ``_run_juju_json`` stub that returns *payload* regardless of args.

    A test helper rather than a lambda so the unused parameters don't trip
    ruff's ARG005 rule.  The keyword name ``timeout`` matters — the
    production caller invokes ``_run_juju_json(args, timeout=10)``.
    """

    def _stub(args, timeout=10):
        return payload

    return _stub


class TestCurrentControllerSafety:
    """Tests for current_controller_safety with mocked juju output."""

    def test_juju_unavailable_returns_unknown(self, monkeypatch):
        monkeypatch.setattr(controller_safety, "_run_juju_json", _stub_run_juju_json(None))
        monkeypatch.setattr(controller_safety, "production_controllers", lambda: [])
        safety = current_controller_safety()
        assert safety.kind is ControllerKind.UNKNOWN
        assert safety.confirm_required is False

    def test_local_lxd_controller(self, monkeypatch):
        payload = {
            "concierge-lxd": {
                "details": {
                    "cloud": "localhost",
                    "api-endpoints": ["127.0.0.1:17070"],
                }
            }
        }
        monkeypatch.setattr(controller_safety, "_run_juju_json", _stub_run_juju_json(payload))
        monkeypatch.setattr(controller_safety, "production_controllers", lambda: [])
        safety = current_controller_safety()
        assert safety.name == "concierge-lxd"
        assert safety.cloud == "localhost"
        assert safety.kind is ControllerKind.LOCAL
        assert safety.confirm_required is False

    def test_remote_aws_controller(self, monkeypatch):
        payload = {
            "prod-aws": {
                "details": {
                    "cloud": "aws",
                    "api-endpoints": ["18.10.20.30:17070"],
                }
            }
        }
        monkeypatch.setattr(controller_safety, "_run_juju_json", _stub_run_juju_json(payload))
        monkeypatch.setattr(controller_safety, "production_controllers", lambda: [])
        safety = current_controller_safety()
        assert safety.kind is ControllerKind.NON_LOCAL
        assert safety.confirm_required is True

    def test_explicit_production_list_overrides_local_heuristic(self, monkeypatch):
        payload = {
            "looks-local": {
                "details": {
                    "cloud": "localhost",
                    "api-endpoints": ["127.0.0.1:17070"],
                }
            }
        }
        monkeypatch.setattr(controller_safety, "_run_juju_json", _stub_run_juju_json(payload))
        monkeypatch.setattr(controller_safety, "production_controllers", lambda: ["looks-local"])
        safety = current_controller_safety()
        # Heuristic alone says local, but the explicit list flips the gate on.
        assert safety.kind is ControllerKind.LOCAL
        assert safety.in_production_list is True
        assert safety.confirm_required is True

    def test_controller_prefix_in_model_argument(self, monkeypatch):
        captured: list[list[str]] = []

        def fake_run(args, timeout=10):
            captured.append(list(args))
            return {
                "remote-ctrl": {"details": {"cloud": "aws", "api-endpoints": ["1.2.3.4:17070"]}}
            }

        monkeypatch.setattr(controller_safety, "_run_juju_json", fake_run)
        monkeypatch.setattr(controller_safety, "production_controllers", lambda: [])
        safety = current_controller_safety(model="remote-ctrl:dev")
        assert captured == [["show-controller", "remote-ctrl"]]
        assert safety.kind is ControllerKind.NON_LOCAL


class TestConfirmMessage:
    """Tests for the synthetic-error message wording."""

    def test_non_local_message(self):
        safety = ControllerSafety(
            name="prod-aws",
            cloud="aws",
            kind=ControllerKind.NON_LOCAL,
            in_production_list=False,
        )
        msg = confirm_message("juju_deploy", safety)
        assert "non-local controller" in msg
        assert "'prod-aws'" in msg
        assert "'aws'" in msg
        assert "confirmed=true" in msg

    def test_production_list_message_escalates_language(self):
        safety = ControllerSafety(
            name="prod",
            cloud="localhost",
            kind=ControllerKind.LOCAL,
            in_production_list=True,
        )
        msg = confirm_message("juju_destroy_model", safety)
        assert "production controller" in msg
        assert "'prod'" in msg


class TestControllerConfirmRequired:
    """Tests for the tool-side gate."""

    def test_confirmed_true_skips_check(self, monkeypatch):
        called = mock.MagicMock()
        monkeypatch.setattr(controller_safety, "current_controller_safety", called)
        blocked, message = controller_confirm_required("juju_deploy", confirmed=True)
        assert blocked is False
        assert message == ""
        called.assert_not_called()

    def test_local_controller_passes_through(self, monkeypatch):
        monkeypatch.setattr(
            controller_safety,
            "current_controller_safety",
            lambda model=None: ControllerSafety(
                name="local",
                cloud="localhost",
                kind=ControllerKind.LOCAL,
                in_production_list=False,
            ),
        )
        blocked, message = controller_confirm_required("juju_deploy")
        assert blocked is False
        assert message == ""

    def test_non_local_controller_blocks(self, monkeypatch):
        monkeypatch.setattr(
            controller_safety,
            "current_controller_safety",
            lambda model=None: ControllerSafety(
                name="prod",
                cloud="aws",
                kind=ControllerKind.NON_LOCAL,
                in_production_list=False,
            ),
        )
        blocked, message = controller_confirm_required("juju_deploy")
        assert blocked is True
        assert "non-local controller" in message
        assert "'prod'" in message
