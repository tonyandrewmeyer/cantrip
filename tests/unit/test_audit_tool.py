"""Tests for the charm audit tool.

Unit tests for internal helper functions that were previously in audit.py
have been moved to tests/unit/charmlint/ since audit.py now delegates to
charmlint.  This file retains integration tests for CharmAuditTool and
tests for the modern-patterns check (which remains in audit.py).
"""

import pathlib
import tempfile

import pytest

from cantrip.agent.tools.audit import (
    CharmAuditTool,
    _check_modern_patterns,
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


@pytest.fixture
def tool():
    return CharmAuditTool()


def _write_charmcraft_yaml(charm_dir: pathlib.Path, extra: str = "") -> None:
    """Write a minimal charmcraft.yaml."""
    (charm_dir / "charmcraft.yaml").write_text(f"name: test-charm\ntype: charm\n{extra}")


# ===================================================================
# TestCharmAuditTool
# ===================================================================


class TestCharmAuditTool:
    """Integration tests for CharmAuditTool.execute."""

    @pytest.mark.asyncio
    async def test_missing_metadata(self, tool, temp_dir) -> None:
        """Returns error when no charmcraft.yaml is present."""
        result = await tool.execute(path=str(temp_dir))
        assert not result.success
        assert "charmcraft.yaml" in result.error

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tool) -> None:
        result = await tool.execute(path="/nonexistent/path")
        assert not result.success

    @pytest.mark.asyncio
    async def test_minimal_charm(self, tool, temp_dir) -> None:
        """A minimal charm has many findings."""
        _write_charmcraft_yaml(temp_dir)

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["charm_name"] == "test-charm"
        assert result.data["total_issues"] > 0
        # Should flag missing tests, COS, README, etc.
        assert result.data["gaps"]["unit_tests"] is True
        assert result.data["gaps"]["cos_tracing"] is True
        assert result.data["gaps"]["readme"] is True

    @pytest.mark.asyncio
    async def test_well_equipped_charm(self, tool, temp_dir) -> None:
        """A charm with COS, tests, and metadata has fewer issues."""
        _write_charmcraft_yaml(
            temp_dir,
            extra=(
                "display-name: Test Charm\n"
                "summary: A test charm\n"
                "description: Detailed description\n"
                "docs: https://docs.example.com\n"
                "issues: https://github.com/test/issues\n"
                "source: https://github.com/test/charm\n"
                "tags:\n  - testing\n"
                "requires:\n"
                "  tracing:\n    interface: tracing\n"
                "  logging:\n    interface: loki_push_api\n"
                "provides:\n"
                "  metrics-endpoint:\n    interface: prometheus_scrape\n"
                "  grafana-dashboard:\n    interface: grafana_dashboard\n"
            ),
        )
        # Add tests.
        unit_dir = temp_dir / "tests" / "unit"
        unit_dir.mkdir(parents=True)
        (unit_dir / "test_charm.py").write_text("pass\n")
        integ_dir = temp_dir / "tests" / "integration"
        integ_dir.mkdir(parents=True)
        (integ_dir / "test_charm.py").write_text("pass\n")
        # Add README and LICENSE.
        (temp_dir / "README.md").write_text("# Test Charm\n")
        (temp_dir / "LICENSE").write_text("Apache-2.0\n")
        # Add requirements with ops-tracing.
        (temp_dir / "requirements.txt").write_text("ops>=2.0\nops-tracing>=1.0\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["gaps"]["unit_tests"] is False
        assert result.data["gaps"]["integration_tests"] is False
        assert result.data["gaps"]["cos_tracing"] is False
        assert result.data["gaps"]["readme"] is False
        assert result.data["gaps"]["licence"] is False

    @pytest.mark.asyncio
    async def test_output_is_markdown(self, tool, temp_dir) -> None:
        """The output is a formatted Markdown audit report."""
        _write_charmcraft_yaml(temp_dir)

        result = await tool.execute(path=str(temp_dir))

        assert result.output.startswith("# Audit Report:")

    @pytest.mark.asyncio
    async def test_legacy_metadata_yaml(self, tool, temp_dir) -> None:
        """Falls back to metadata.yaml when charmcraft.yaml is absent."""
        (temp_dir / "metadata.yaml").write_text("name: legacy-charm\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["charm_name"] == "legacy-charm"

    @pytest.mark.asyncio
    async def test_deprecated_apis_in_data(self, tool, temp_dir) -> None:
        """Deprecated APIs are reported in the data dict."""
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            "from ops.framework import StoredState\nclass MyCharm:\n    _stored = StoredState()\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert len(result.data["deprecated_apis"]) >= 1

    @pytest.mark.asyncio
    async def test_fetch_libs_in_data(self, tool, temp_dir) -> None:
        """Fetch-libs findings are reported in the data dict."""
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            "from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert len(result.data["fetch_libs"]) >= 1

    @pytest.mark.asyncio
    async def test_fetch_libs_in_report(self, tool, temp_dir) -> None:
        """Fetch-libs with known PyPI equivalents appear in the report."""
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text(
            "from charms.tls_certificates_interface.v3.tls_certificates "
            "import TLSCertificatesRequiresV3\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert "charmlibs-interfaces-tls-certificates" in result.output


# ===================================================================
# TestCheckModernPatterns
# ===================================================================


class TestCheckModernPatterns:
    """Tests for _check_modern_patterns — still in audit.py."""

    def test_reconcile_detected(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def _reconcile(self):\n    pass\n")
        result = _check_modern_patterns(temp_dir)
        assert result["holistic_status"] is True

    def test_config_changed_detected(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def _on_config_changed(self, event):\n    pass\n")
        result = _check_modern_patterns(temp_dir)
        assert result["config_reconciliation"] is True

    def test_pebble_readiness_detected(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("if container.can_connect():\n    container.push(...)\n")
        result = _check_modern_patterns(temp_dir)
        assert result["pebble_readiness"] is True

    def test_nothing_detected(self, temp_dir) -> None:
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("print('hello')\n")
        result = _check_modern_patterns(temp_dir)
        assert all(not v for v in result.values())


# ===================================================================
# TestAuditToolModernisation
# ===================================================================


class TestAuditToolModernisation:
    """Tests for type annotation and modern pattern gaps in audit output."""

    @pytest.fixture
    def tool(self) -> CharmAuditTool:
        return CharmAuditTool()

    @pytest.mark.asyncio
    async def test_type_annotation_gap_flagged(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def greet(name):\n    return name\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["gaps"]["type_annotations"] is True
        assert "type annotation" in result.output.lower()

    @pytest.mark.asyncio
    async def test_type_annotation_gap_not_flagged(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def greet(name: str) -> str:\n    return name\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["gaps"]["type_annotations"] is False

    @pytest.mark.asyncio
    async def test_modern_patterns_gap_flagged(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("print('hello')\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["gaps"]["modern_patterns"] is True
        assert "modern pattern" in result.output.lower()

    @pytest.mark.asyncio
    async def test_modern_patterns_in_data(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("def _reconcile(self):\n    pass\n")

        result = await tool.execute(path=str(temp_dir))

        assert "modern_patterns" in result.data
        assert result.data["modern_patterns"]["holistic_status"] is True
