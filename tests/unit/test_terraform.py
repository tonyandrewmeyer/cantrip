"""Tests for the Terraform module generator."""

import pathlib

import pytest
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

    assert set(result.keys()) == {"main.tf", "variables.tf", "outputs.tf", "terraform.tf"}
    for content in result.values():
        assert isinstance(content, str)
        assert len(content) > 0


def test_main_tf_contains_charm_name(tmp_path: pathlib.Path):
    path = _write_charmcraft(tmp_path, _FULL_YAML)
    result = terraform.generate_terraform_module(path)
    main = result["main.tf"]

    assert 'name     = "test-charm-k8s"' in main
    assert 'resource "juju_application" "test_charm"' in main


def test_main_tf_uses_model_uuid(tmp_path: pathlib.Path):
    """main.tf must reference var.model_uuid, not var.model."""
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)
    main = result["main.tf"]

    assert "var.model_uuid" in main
    assert "var.model\n" not in main


def test_variables_tf_contains_model_uuid(tmp_path: pathlib.Path):
    """The model_uuid variable is present and has no default (required)."""
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)
    variables = result["variables.tf"]

    assert 'variable "model_uuid"' in variables
    assert 'variable "model"' not in variables
    # The model_uuid block should NOT contain a default line.
    block_start = variables.index('variable "model_uuid"')
    block_end = variables.index("}", block_start)
    model_block = variables[block_start:block_end]
    assert "default" not in model_block


def test_outputs_application_object(tmp_path: pathlib.Path):
    """CC008 mandates an 'application' output with the full resource object."""
    path = _write_charmcraft(tmp_path, _FULL_YAML)
    result = terraform.generate_terraform_module(path)
    outputs = result["outputs.tf"]

    assert 'output "application"' in outputs
    assert "juju_application.test_charm" in outputs
    # Old-style app_name output should not exist.
    assert 'output "app_name"' not in outputs


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


def test_terraform_tf_content(tmp_path: pathlib.Path):
    """CC008 mandates terraform.tf (not versions.tf)."""
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)

    assert "terraform.tf" in result
    assert "versions.tf" not in result
    tf = result["terraform.tf"]
    assert 'required_version = ">= 1.6"' in tf
    assert 'source  = "juju/juju"' in tf
    assert 'version = "~> 1.0"' in tf


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


def test_base_defaults_to_null(tmp_path: pathlib.Path):
    """CC008 mandates base default = null, not a hardcoded value."""
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)
    variables = result["variables.tf"]

    block_start = variables.index('variable "base"')
    block_end = variables.index("}", block_start)
    base_block = variables[block_start:block_end]
    assert "default     = null" in base_block


def test_constraints_defaults_to_null(tmp_path: pathlib.Path):
    """CC008 mandates constraints default = null, not arch=amd64."""
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)
    variables = result["variables.tf"]

    block_start = variables.index('variable "constraints"')
    block_end = variables.index("}", block_start)
    constraints_block = variables[block_start:block_end]
    assert "default     = null" in constraints_block
    assert "arch=amd64" not in constraints_block


def test_variables_alphabetical_order(tmp_path: pathlib.Path):
    """CC008 mandates variables in alphabetical order."""
    path = _write_charmcraft(tmp_path, _MINIMAL_YAML)
    result = terraform.generate_terraform_module(path)
    variables = result["variables.tf"]

    # Extract variable names in order of appearance.
    import re

    var_names = re.findall(r'variable "(\w+)"', variables)
    assert var_names == sorted(var_names), f"Variables not alphabetical: {var_names}"


def test_outputs_alphabetical_order(tmp_path: pathlib.Path):
    """CC008 mandates outputs in alphabetical order."""
    path = _write_charmcraft(tmp_path, _FULL_YAML)
    result = terraform.generate_terraform_module(path)
    outputs = result["outputs.tf"]

    import re

    output_names = re.findall(r'output "(\w+)"', outputs)
    assert output_names == sorted(output_names), f"Outputs not alphabetical: {output_names}"


# -- Error path tests --------------------------------------------------------


def test_invalid_yaml_raises_value_error(tmp_path: pathlib.Path):
    """Invalid YAML input raises ValueError with a clear message."""
    path = tmp_path / "charmcraft.yaml"
    path.write_text("name: [unterminated")
    with pytest.raises(ValueError, match="Invalid YAML"):
        terraform.generate_terraform_module(path)


def test_empty_yaml_raises_value_error(tmp_path: pathlib.Path):
    """Empty YAML file raises ValueError."""
    path = tmp_path / "charmcraft.yaml"
    path.write_text("")
    with pytest.raises(ValueError, match="empty or not a mapping"):
        terraform.generate_terraform_module(path)


def test_yaml_list_raises_value_error(tmp_path: pathlib.Path):
    """YAML that parses to a list (not a dict) raises ValueError."""
    path = tmp_path / "charmcraft.yaml"
    path.write_text("- item1\n- item2\n")
    with pytest.raises(ValueError, match="empty or not a mapping"):
        terraform.generate_terraform_module(path)


def test_missing_name_raises_key_error(tmp_path: pathlib.Path):
    """YAML without a 'name' field raises KeyError."""
    path = tmp_path / "charmcraft.yaml"
    path.write_text(yaml.dump({"type": "charm"}))
    with pytest.raises(KeyError, match="name"):
        terraform.generate_terraform_module(path)
