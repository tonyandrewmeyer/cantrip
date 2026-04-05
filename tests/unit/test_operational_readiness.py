"""Tests for the operational readiness assessment tool."""

import textwrap
from pathlib import Path

import pytest
import yaml

from cantrip.agent.tools.operational_readiness import (
    PILLAR_BEST_PRACTICES,
    PILLAR_DOCUMENTATION,
    PILLAR_MAINTAINABILITY,
    PILLAR_RELIABILITY,
    PILLAR_SECURITY,
    OperationalReadinessTool,
    _categorise_checks,
    _check_action_quality,
    _check_common_actions,
    _check_config_quality,
    _check_documentation,
    _check_maintainability,
    _check_reliability,
    _check_security,
    _check_status_reporting,
    _score_pillar,
)


@pytest.fixture()
def tmp_charm(tmp_path: Path) -> Path:
    """Create a minimal charm directory."""
    (tmp_path / "charmcraft.yaml").write_text(
        yaml.dump(
            {
                "name": "test-charm",
                "requires": {
                    "database": {"interface": "mysql"},
                },
            }
        )
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "charm.py").write_text(
        textwrap.dedent("""\
            import ops
            class TestCharm(ops.CharmBase):
                def __init__(self, *args):
                    super().__init__(*args)
                    self.unit.status = ops.BlockedStatus("missing config")
        """)
    )
    return tmp_path


@pytest.fixture()
def tool() -> OperationalReadinessTool:
    return OperationalReadinessTool()


# ===================================================================
# TestCheckStatusReporting
# ===================================================================


class TestCheckStatusReporting:
    """Tests for _check_status_reporting."""

    def test_detects_missing_config_status(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "charm.py").write_text('self.unit.status = BlockedStatus("missing config")')
        results = _check_status_reporting([src / "charm.py"])
        # The "missing.*config" pattern should match.
        config_checks = [r for r in results if "missing required config" in r[2].lower()]
        assert any(passed for _, passed, _ in config_checks)

    def test_no_status_calls(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "charm.py").write_text("print('hello')")
        results = _check_status_reporting([src / "charm.py"])
        assert all(not passed for _, passed, _ in results)

    def test_upgrade_status(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            'self.unit.status = MaintenanceStatus("upgrade in progress")'
        )
        results = _check_status_reporting([src / "charm.py"])
        upgrade_checks = [r for r in results if "upgrade" in r[2].lower()]
        assert any(passed for _, passed, _ in upgrade_checks)


# ===================================================================
# TestCheckCommonActions
# ===================================================================


class TestCheckCommonActions:
    """Tests for _check_common_actions."""

    def test_all_actions_present(self) -> None:
        actions = {
            "get-health": {"description": "Check health"},
            "pause": {"description": "Pause"},
            "resume": {"description": "Resume"},
        }
        results = _check_common_actions(actions)
        assert all(passed for _, passed, _ in results)

    def test_no_actions(self) -> None:
        results = _check_common_actions({})
        assert all(not passed for _, passed, _ in results)

    def test_aliases_accepted(self) -> None:
        actions = {
            "health-check": {},
            "stop": {},
            "start": {},
        }
        results = _check_common_actions(actions)
        assert all(passed for _, passed, _ in results)


# ===================================================================
# TestCheckActionQuality
# ===================================================================


class TestCheckActionQuality:
    """Tests for _check_action_quality."""

    def test_good_action(self) -> None:
        actions = {
            "backup": {
                "description": "Create a backup",
                "params": {
                    "properties": {
                        "target": {"type": "string", "description": "Backup target"},
                    }
                },
            }
        }
        results = _check_action_quality(actions)
        assert all(passed for _, passed, _ in results)

    def test_missing_description(self) -> None:
        actions = {"backup": {"params": {}}}
        results = _check_action_quality(actions)
        desc_check = [r for r in results if "description" in r[2] and "backup" in r[2]]
        assert any(not passed for _, passed, _ in desc_check)


# ===================================================================
# TestCheckConfigQuality
# ===================================================================


class TestCheckConfigQuality:
    """Tests for _check_config_quality."""

    def test_good_config(self) -> None:
        config = {
            "options": {
                "port": {
                    "type": "int",
                    "default": 8080,
                    "description": "Listening port",
                }
            }
        }
        results = _check_config_quality(config)
        assert all(passed for _, passed, _ in results)

    def test_missing_fields(self) -> None:
        config = {"options": {"port": {}}}
        results = _check_config_quality(config)
        assert any(not passed for _, passed, _ in results)


# ===================================================================
# TestCheckDocumentation
# ===================================================================


class TestCheckDocumentation:
    """Tests for _check_documentation."""

    def test_readme_mentions_install(self, tmp_path: Path) -> None:
        results = _check_documentation(tmp_path, "## Installation\n\nRun juju deploy")
        install_check = [r for r in results if "installation" in r[0]]
        assert install_check[0][1] is True

    def test_docs_directory(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "how-to" / "upgrade.md").parent.mkdir(parents=True)
        (docs / "how-to" / "upgrade.md").write_text("# Upgrade guide")
        results = _check_documentation(tmp_path, "")
        upgrade_check = [r for r in results if "upgrade" in r[0]]
        assert upgrade_check[0][1] is True

    def test_no_docs(self, tmp_path: Path) -> None:
        results = _check_documentation(tmp_path, "")
        assert all(not passed for _, passed, _ in results)


# ===================================================================
# TestCheckReliability
# ===================================================================


class TestCheckReliability:
    """Tests for _check_reliability."""

    def test_has_backup_restore(self) -> None:
        actions = {"create-backup": {}, "restore-backup": {}}
        results = _check_reliability(actions, [])
        backup_check = [r for r in results if "backup" in r[0].lower()]
        assert any(passed for _, passed, _ in backup_check)

    def test_graceful_shutdown(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "charm.py").write_text("self.on.stop.observe(self._on_stop)")
        results = _check_reliability({}, [src / "charm.py"])
        shutdown_check = [r for r in results if "shutdown" in r[0]]
        assert shutdown_check[0][1] is True


# ===================================================================
# TestCheckMaintainability
# ===================================================================


class TestCheckMaintainability:
    """Tests for _check_maintainability."""

    def test_full_cos(self) -> None:
        metadata = {
            "requires": {
                "tracing": {"interface": "tracing"},
                "metrics": {"interface": "metrics-endpoint"},
                "log-proxy": {"interface": "logging"},
            },
            "provides": {
                "dashboard": {"interface": "grafana-dashboard"},
            },
        }
        results = _check_maintainability(metadata, {}, [])
        cos_checks = [r for r in results if "cos:" in r[0]]
        assert all(passed for _, passed, _ in cos_checks)

    def test_no_cos(self) -> None:
        results = _check_maintainability({}, {}, [])
        cos_checks = [r for r in results if "cos:" in r[0]]
        assert all(not passed for _, passed, _ in cos_checks)

    def test_diagnostics_action(self) -> None:
        results = _check_maintainability({}, {"collect-diagnostics": {}}, [])
        diag = [r for r in results if "diagnostics" in r[0]]
        assert diag[0][1] is True


# ===================================================================
# TestCheckSecurity
# ===================================================================


class TestCheckSecurity:
    """Tests for _check_security."""

    def test_tls_relation(self) -> None:
        metadata = {
            "requires": {"certs": {"interface": "tls-certificates"}},
        }
        results = _check_security(metadata, [], {})
        tls_check = [r for r in results if "encryption" in r[0]]
        assert tls_check[0][1] is True

    def test_secrets_management_ok_without_secret_config(self) -> None:
        """No secret-like config means secrets management is not an issue."""
        results = _check_security({}, [], {})
        secret_check = [r for r in results if "secrets" in r[0]]
        assert secret_check[0][1] is True

    def test_secrets_management_fails_with_password_config(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "charm.py").write_text("print('hello')")
        metadata = {
            "config": {"options": {"admin-password": {"type": "string"}}},
        }
        results = _check_security(metadata, [src / "charm.py"], {})
        secret_check = [r for r in results if "secrets" in r[0]]
        assert secret_check[0][1] is False


# ===================================================================
# TestScorePillar
# ===================================================================


class TestScorePillar:
    """Tests for _score_pillar."""

    def test_all_pass(self) -> None:
        checks = [("a", True, "x"), ("b", True, "y")]
        assert _score_pillar(checks) == (2, 2, 100)

    def test_half_pass(self) -> None:
        checks = [("a", True, "x"), ("b", False, "y")]
        assert _score_pillar(checks) == (1, 2, 50)

    def test_empty(self) -> None:
        assert _score_pillar([]) == (0, 0, 100)

    def test_all_fail(self) -> None:
        checks = [("a", False, "x"), ("b", False, "y")]
        assert _score_pillar(checks) == (0, 2, 0)


# ===================================================================
# TestCategoriseChecks
# ===================================================================


class TestCategoriseChecks:
    """Tests for _categorise_checks."""

    def test_routes_to_correct_pillar(self) -> None:
        checks = [
            ("status:missing-config", True, "status"),
            ("docs:installation", False, "install docs"),
            ("reliability:health-check", True, "health"),
            ("maintainability:cos:tracing", False, "tracing"),
            ("security:encryption-transit", True, "tls"),
        ]
        by_pillar = _categorise_checks(checks)
        assert len(by_pillar[PILLAR_BEST_PRACTICES]) == 1
        assert len(by_pillar[PILLAR_DOCUMENTATION]) == 1
        assert len(by_pillar[PILLAR_RELIABILITY]) == 1
        assert len(by_pillar[PILLAR_MAINTAINABILITY]) == 1
        assert len(by_pillar[PILLAR_SECURITY]) == 1


# ===================================================================
# TestOperationalReadinessTool
# ===================================================================


class TestOperationalReadinessTool:
    """Integration tests for the full tool."""

    @pytest.mark.asyncio()
    async def test_minimal_charm(self, tmp_charm: Path, tool: OperationalReadinessTool) -> None:
        result = await tool.execute(path=str(tmp_charm))
        assert result.success is True
        assert "Operational Readiness" in result.output
        assert "overall_score" in result.data
        assert "pillar_scores" in result.data
        assert "findings" in result.data
        assert result.data["charm_name"] == "test-charm"

    @pytest.mark.asyncio()
    async def test_nonexistent_path(self, tool: OperationalReadinessTool) -> None:
        result = await tool.execute(path="/nonexistent/path")
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio()
    async def test_no_metadata(self, tmp_path: Path, tool: OperationalReadinessTool) -> None:
        result = await tool.execute(path=str(tmp_path))
        assert result.success is False
        assert "charmcraft.yaml" in (result.error or "")

    @pytest.mark.asyncio()
    async def test_well_equipped_charm(
        self, tmp_path: Path, tool: OperationalReadinessTool
    ) -> None:
        """A charm with many operational features should score higher."""
        (tmp_path / "charmcraft.yaml").write_text(
            yaml.dump(
                {
                    "name": "well-equipped",
                    "actions": {
                        "get-health": {"description": "Check health"},
                        "pause": {"description": "Pause services"},
                        "resume": {"description": "Resume services"},
                        "create-backup": {"description": "Create backup"},
                        "restore-backup": {"description": "Restore from backup"},
                        "collect-diagnostics": {"description": "Collect diagnostics"},
                        "pre-upgrade-check": {"description": "Pre-upgrade checks"},
                    },
                    "config": {
                        "options": {
                            "port": {
                                "type": "int",
                                "default": 8080,
                                "description": "Listening port",
                            },
                        },
                    },
                    "requires": {
                        "tracing": {"interface": "tracing"},
                        "metrics": {"interface": "metrics-endpoint"},
                        "log-proxy": {"interface": "logging"},
                        "certs": {"interface": "tls-certificates"},
                    },
                    "provides": {
                        "dashboard": {"interface": "grafana-dashboard"},
                    },
                }
            )
        )
        src = tmp_path / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            textwrap.dedent("""\
                import ops
                class WellEquipped(ops.CharmBase):
                    def __init__(self, *args):
                        super().__init__(*args)
                        self.unit.status = ops.BlockedStatus("missing config")
                        self.unit.status = ops.WaitingStatus("waiting for relation")
                        self.unit.status = ops.MaintenanceStatus("upgrade in progress")
                        self.on.stop.observe(self._on_stop)
                    def _on_stop(self, event):
                        pass
            """)
        )
        (tmp_path / "README.md").write_text(
            "# Well Equipped\n## Installation\n## Configuration\n"
            "## Usage\n## Troubleshooting\n## Upgrade\n## Backup\n## Management"
        )

        result = await tool.execute(path=str(tmp_path))
        assert result.success is True
        assert result.data["overall_score"] > 50

    @pytest.mark.asyncio()
    async def test_writes_report_file(
        self, tmp_charm: Path, tool: OperationalReadinessTool
    ) -> None:
        await tool.execute(path=str(tmp_charm))
        report_path = tmp_charm / "OPERATIONAL_READINESS.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "Operational Readiness" in content

    @pytest.mark.asyncio()
    async def test_data_has_checks_list(
        self, tmp_charm: Path, tool: OperationalReadinessTool
    ) -> None:
        result = await tool.execute(path=str(tmp_charm))
        assert isinstance(result.data["checks"], list)
        assert all("name" in c and "pillar" in c and "passed" in c for c in result.data["checks"])

    @pytest.mark.asyncio()
    async def test_tool_properties(self, tool: OperationalReadinessTool) -> None:
        assert tool.name == "operational_readiness"
        assert "Operational Readiness" in tool.description
        assert tool.parameters["type"] == "object"
