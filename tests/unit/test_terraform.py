"""Tests for the Terraform module generator."""

import pathlib

import yaml

from cantrip.charm import terraform

_MINIMAL_YAML = {"name": "test-charm", "type": "charm"}

_FULL_YAML = {
    "name": "test-charm-k8s",
    "type": "charm",
    "bases": [
        {
            "build-on": [{"name": "ubuntu", "channel": "22.04"}],
            "run-on": [{"name": "ubuntu", "channel": "22.04"}],
        }
    ],
    "provides": {
        "metrics-endpoint": {"interface": "prometheus_scrape"},
        "grafana-dashboard": {"interface": "grafana_dashboard"},
    },
    "requires": {
        "certificates": {"interface": "tls-certificates"},
        "logging": {"interface": "loki_push_api"},
    },
}

_YAML_WITH_RESOURCES = {
    "name": "my-app-k8s",
    "type": "charm",
    "resources": {
        "oci-image": {"type": "oci-image", "description": "App image"},
    },
}

_YAML_WITH_STORAGE = {
    "name": "my-db-k8s",
    "type": "charm",
    "storage": {
        "data": {"type": "filesystem", "location": "/data"},
    },
}


def _write_charmcraft(tmp_path: pathlib.Path, data: dict) -> pathlib.Path:
    """Write a charmcraft.yaml into *tmp_path* and return its path."""
    path = tmp_path / "charmcraft.yaml"
    path.write_text(yaml.dump(data))
    return path


# -- Resource name helpers ---------------------------------------------------


def test_resource_name_strips_k8s_suffix():
    assert terraform._resource_name("redis-k8s") == "redis"


def test_resource_name_strips_operator_suffix():
    assert terraform._resource_name("mysql-k8s-operator") == "mysql"


def test_resource_name_replaces_hyphens():
    assert terraform._resource_name("my-cool-app") == "my_cool_app"


def test_resource_name_strips_plain_operator_suffix():
    assert terraform._resource_name("vault-operator") == "vault"


# -- Full generation ---------------------------------------------------------


def test_generate_minimal_charm(tmp_path: pathlib.Path):
    """A charmcraft.yaml with just a name produces all four files."""
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)

    assert set(result.keys()) == {"main.tf", "variables.tf", "outputs.tf", "versions.tf"}
    for content in result.values():
        assert isinstance(content, str)
        assert len(content) > 0


def test_main_tf_contains_charm_name(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _FULL_YAML)
    result = terraform.generate_terraform_module(path)
    main = result["main.tf"]

    assert 'name     = "test-charm-k8s"' in main
    assert 'resource "juju_application" "test_charm"' in main


def test_variables_tf_contains_model(tmp_path: pathlib.Path):
    """The model variable is present and has no default (required)."""
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)
    variables = result["variables.tf"]

    assert 'variable "model"' in variables
    # The model block should NOT contain a default line.
    model_block_start = variables.index('variable "model"')
    model_block_end = variables.index("}", model_block_start)
    model_block = variables[model_block_start:model_block_end]
    assert "default" not in model_block


def test_outputs_provides_and_requires(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _FULL_YAML)
    result = terraform.generate_terraform_module(path)
    outputs = result["outputs.tf"]

    assert 'output "provides"' in outputs
    assert 'output "requires"' in outputs
    assert 'metrics_endpoint = "metrics-endpoint"' in outputs
    assert 'grafana_dashboard = "grafana-dashboard"' in outputs
    assert 'certificates = "certificates"' in outputs
    assert 'logging = "logging"' in outputs


def test_resources_variable_included_when_charm_has_resources(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _YAML_WITH_RESOURCES)
    result = terraform.generate_terraform_module(path)

    assert 'variable "resources"' in result["variables.tf"]
    assert "resources = var.resources" in result["main.tf"]


def test_resources_variable_omitted_when_no_resources(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)

    assert 'variable "resources"' not in result["variables.tf"]
    assert "resources = var.resources" not in result["main.tf"]


def test_storage_variable_included_when_charm_has_storage(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _YAML_WITH_STORAGE)
    result = terraform.generate_terraform_module(path)

    assert 'variable "storage_directives"' in result["variables.tf"]
    assert "storage_directives = var.storage_directives" in result["main.tf"]


def test_storage_variable_omitted_when_no_storage(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)

    assert 'variable "storage_directives"' not in result["variables.tf"]
    assert "storage_directives = var.storage_directives" not in result["main.tf"]


def test_versions_tf_content(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)
    versions = result["versions.tf"]

    assert 'required_version = ">= 1.6"' in versions
    assert 'source  = "juju/juju"' in versions
    assert 'version = "~> 1.0"' in versions


def test_endpoints_hyphen_to_underscore(tmp_path: pathlib.Path):
    """Endpoint keys in outputs use underscores; values keep hyphens."""
    data = {
        "name": "app",
        "type": "charm",
        "provides": {"my-endpoint": {"interface": "some_iface"}},
    }
    path = _write_charmcraft(tmp_path, data)
    result = terraform.generate_terraform_module(path)
    outputs = result["outputs.tf"]

    assert 'my_endpoint = "my-endpoint"' in outputs


def test_provides_omitted_when_empty(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)

    assert 'output "provides"' not in result["outputs.tf"]
    assert 'output "requires"' not in result["outputs.tf"]
