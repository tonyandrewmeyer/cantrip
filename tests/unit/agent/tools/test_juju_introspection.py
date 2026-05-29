"""Tests for Juju introspection tools (relation data, app config, offers)."""

import json
import pathlib
from unittest import mock

import pytest
import yaml

from cantrip.agent.tools.juju import (
    JujuGetAppConfigTool,
    JujuListOffersTool,
    JujuReadRelationDataTool,
    _validate_config_against_charm,
)


@pytest.fixture()
def relation_tool() -> JujuReadRelationDataTool:
    return JujuReadRelationDataTool()


@pytest.fixture()
def config_tool() -> JujuGetAppConfigTool:
    return JujuGetAppConfigTool()


@pytest.fixture()
def offers_tool() -> JujuListOffersTool:
    return JujuListOffersTool()


# ===================================================================
# TestJujuReadRelationDataTool
# ===================================================================


class TestJujuReadRelationDataTool:
    """Tests for JujuReadRelationDataTool."""

    def test_tool_properties(self, relation_tool: JujuReadRelationDataTool) -> None:
        assert relation_tool.name == "juju_read_relation_data"
        assert "unit" in relation_tool.parameters["required"]

    @pytest.mark.asyncio()
    async def test_no_juju(self, relation_tool: JujuReadRelationDataTool) -> None:
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await relation_tool.execute(unit="myapp/0")
        assert result.success is False

    @pytest.mark.asyncio()
    async def test_reads_relation_data(self, relation_tool: JujuReadRelationDataTool) -> None:
        show_unit_output = json.dumps(
            {
                "myapp/0": {
                    "relation-info": [
                        {
                            "endpoint": "database",
                            "relation-id": 1,
                            "application-data": {"version": "14"},
                            "local-unit": {"data": {"egress-subnets": "10.0.0.0/24"}},
                            "related-units": {
                                "postgresql/0": {
                                    "data": {
                                        "host": "10.0.0.5",
                                        "port": "5432",
                                    }
                                }
                            },
                        }
                    ]
                }
            }
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.juju._common._run_juju", return_value=show_unit_output
            ),
        ):
            result = await relation_tool.execute(unit="myapp/0")

        assert result.success is True
        assert len(result.data["relations"]) == 1
        assert result.data["relations"][0]["endpoint"] == "database"
        assert "host" in result.data["relations"][0]["related_units"]["postgresql/0"]

    @pytest.mark.asyncio()
    async def test_filters_by_endpoint(self, relation_tool: JujuReadRelationDataTool) -> None:
        show_unit_output = json.dumps(
            {
                "myapp/0": {
                    "relation-info": [
                        {"endpoint": "database", "relation-id": 1, "related-units": {}},
                        {"endpoint": "cache", "relation-id": 2, "related-units": {}},
                    ]
                }
            }
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.juju._common._run_juju", return_value=show_unit_output
            ),
        ):
            result = await relation_tool.execute(unit="myapp/0", endpoint="database")

        assert result.success is True
        assert len(result.data["relations"]) == 1
        assert result.data["relations"][0]["endpoint"] == "database"

    @pytest.mark.asyncio()
    async def test_no_relations(self, relation_tool: JujuReadRelationDataTool) -> None:
        show_unit_output = json.dumps({"myapp/0": {"relation-info": []}})

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.juju._common._run_juju", return_value=show_unit_output
            ),
        ):
            result = await relation_tool.execute(unit="myapp/0")

        assert result.success is True
        assert result.data["relations"] == []

    @pytest.mark.asyncio()
    async def test_timeout(self, relation_tool: JujuReadRelationDataTool) -> None:
        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common._run_juju", side_effect=TimeoutError),
        ):
            result = await relation_tool.execute(unit="myapp/0")
        assert result.success is False
        assert "timed out" in result.error

    @pytest.mark.asyncio()
    async def test_cli_failure(self, relation_tool: JujuReadRelationDataTool) -> None:
        import jubilant

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch(
                "cantrip.agent.tools.juju._common._run_juju",
                side_effect=jubilant.CLIError(1, ["juju", "show-unit"], stderr="unit not found"),
            ),
        ):
            result = await relation_tool.execute(unit="myapp/0")
        assert result.success is False
        assert "unit not found" in result.error


# ===================================================================
# TestJujuGetAppConfigTool
# ===================================================================


class TestJujuGetAppConfigTool:
    """Tests for JujuGetAppConfigTool."""

    def test_tool_properties(self, config_tool: JujuGetAppConfigTool) -> None:
        assert config_tool.name == "juju_get_app_config"
        assert "app" in config_tool.parameters["required"]

    @pytest.mark.asyncio()
    async def test_no_juju(self, config_tool: JujuGetAppConfigTool) -> None:
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await config_tool.execute(app="myapp")
        assert result.success is False

    @pytest.mark.asyncio()
    async def test_reads_config_with_sources(self, config_tool: JujuGetAppConfigTool) -> None:
        config_output = json.dumps(
            {
                "settings": {
                    "port": {
                        "type": "int",
                        "value": 8080,
                        "source": "default",
                        "description": "Listening port",
                    },
                    "log-level": {
                        "type": "string",
                        "value": "debug",
                        "source": "user",
                        "description": "Log level",
                    },
                }
            }
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common._run_juju", return_value=config_output),
        ):
            result = await config_tool.execute(app="myapp")

        assert result.success is True
        assert result.data["user_set_count"] == 1
        config_map = {c["name"]: c for c in result.data["config"]}
        assert config_map["port"]["source"] == "default"
        assert config_map["log-level"]["source"] == "user"
        assert "log-level" in result.output

    @pytest.mark.asyncio()
    async def test_timeout(self, config_tool: JujuGetAppConfigTool) -> None:
        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common._run_juju", side_effect=TimeoutError),
        ):
            result = await config_tool.execute(app="myapp")
        assert result.success is False
        assert "timed out" in result.error


# ===================================================================
# TestJujuListOffersTool
# ===================================================================


class TestJujuListOffersTool:
    """Tests for JujuListOffersTool."""

    def test_tool_properties(self, offers_tool: JujuListOffersTool) -> None:
        assert offers_tool.name == "juju_list_offers"

    @pytest.mark.asyncio()
    async def test_no_juju(self, offers_tool: JujuListOffersTool) -> None:
        with mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=False):
            result = await offers_tool.execute()
        assert result.success is False

    @pytest.mark.asyncio()
    async def test_no_offers(self, offers_tool: JujuListOffersTool) -> None:
        mock_status = mock.MagicMock()
        mock_status.offers = {}

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common._run_juju", return_value=mock_status),
        ):
            result = await offers_tool.execute()

        assert result.success is True
        assert result.data["count"] == 0

    @pytest.mark.asyncio()
    async def test_lists_offers(self, offers_tool: JujuListOffersTool) -> None:
        ep = mock.MagicMock()
        ep.interface = "mysql"

        offer = mock.MagicMock()
        offer.app = "postgresql"
        offer.charm = "postgresql-k8s"
        offer.active_connected_count = 1
        offer.total_connected_count = 2
        offer.endpoints = {"db": ep}

        mock_status = mock.MagicMock()
        mock_status.offers = {"postgresql-db": offer}

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common._run_juju", return_value=mock_status),
        ):
            result = await offers_tool.execute()

        assert result.success is True
        assert result.data["count"] == 1
        assert result.data["offers"][0]["name"] == "postgresql-db"
        assert result.data["offers"][0]["app"] == "postgresql"
        assert "postgresql-db" in result.output

    @pytest.mark.asyncio()
    async def test_timeout(self, offers_tool: JujuListOffersTool) -> None:
        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common._run_juju", side_effect=TimeoutError),
        ):
            result = await offers_tool.execute()
        assert result.success is False
        assert "timed out" in result.error


# ===================================================================
# TestValidateConfigAgainstCharm
# ===================================================================


class TestValidateConfigAgainstCharm:
    """Tests for _validate_config_against_charm."""

    def test_undeclared_key_detected(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            yaml.dump({"config": {"options": {"port": {"type": "int"}}}})
        )
        issues = _validate_config_against_charm({"port", "old-setting"}, str(tmp_path))
        undeclared = [i for i in issues if i["key"] == "old-setting"]
        assert len(undeclared) == 1
        assert "deprecated" in undeclared[0]["issue"].lower()

    def test_missing_declared_key_detected(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            yaml.dump(
                {
                    "config": {
                        "options": {
                            "port": {"type": "int"},
                            "log-level": {"type": "string"},
                        }
                    }
                }
            )
        )
        issues = _validate_config_against_charm({"port"}, str(tmp_path))
        missing = [i for i in issues if i["key"] == "log-level"]
        assert len(missing) == 1
        assert "not present" in missing[0]["issue"].lower()

    def test_no_issues_when_matching(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            yaml.dump({"config": {"options": {"port": {"type": "int"}}}})
        )
        issues = _validate_config_against_charm({"port"}, str(tmp_path))
        assert issues == []

    def test_no_charm_config_returns_empty(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(yaml.dump({"name": "test"}))
        issues = _validate_config_against_charm({"port"}, str(tmp_path))
        assert issues == []

    def test_config_yaml_fallback(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "config.yaml").write_text(yaml.dump({"options": {"port": {"type": "int"}}}))
        issues = _validate_config_against_charm({"port", "extra"}, str(tmp_path))
        assert any(i["key"] == "extra" for i in issues)

    def test_nonexistent_path(self) -> None:
        issues = _validate_config_against_charm({"port"}, "/nonexistent")
        assert issues == []


# ===================================================================
# TestGetAppConfigWithValidation
# ===================================================================


class TestGetAppConfigWithValidation:
    """Tests for JujuGetAppConfigTool with charm_path validation."""

    @pytest.fixture()
    def tool(self) -> JujuGetAppConfigTool:
        return JujuGetAppConfigTool()

    @pytest.mark.asyncio()
    async def test_validation_issues_in_output(
        self, tool: JujuGetAppConfigTool, tmp_path: pathlib.Path
    ) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            yaml.dump({"config": {"options": {"port": {"type": "int"}}}})
        )
        config_output = json.dumps(
            {
                "settings": {
                    "port": {"type": "int", "value": 8080, "source": "default"},
                    "old-key": {"type": "string", "value": "x", "source": "user"},
                }
            }
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common._run_juju", return_value=config_output),
        ):
            result = await tool.execute(app="myapp", charm_path=str(tmp_path))

        assert result.success is True
        assert len(result.data["validation_issues"]) > 0
        assert any(i["key"] == "old-key" for i in result.data["validation_issues"])
        assert "Validation Issues" in result.output

    @pytest.mark.asyncio()
    async def test_no_validation_without_charm_path(self, tool: JujuGetAppConfigTool) -> None:
        config_output = json.dumps(
            {
                "settings": {
                    "port": {"type": "int", "value": 8080, "source": "default"},
                }
            }
        )

        with (
            mock.patch("cantrip.agent.tools.juju._common._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._common._run_juju", return_value=config_output),
        ):
            result = await tool.execute(app="myapp")

        assert result.data["validation_issues"] == []
