"""Tests for the charm audit tool.

Most findings come from charmlint, which has its own test suite upstream.
These tests cover CharmAuditTool end to end and the checks that live in
audit.py itself.
"""

import pathlib
import tempfile
from unittest import mock

import pytest

from cantrip.agent.tools import audit
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
    async def test_listing_fields_use_modern_charmcraft_names(self, tool, temp_dir) -> None:
        """A modern charm's listing fields all read as present.

        Regression (#63): the META rules only recognised the legacy
        top-level keys, so ``title`` plus a ``links`` block still
        reported four missing listing fields.
        """
        _write_charmcraft_yaml(
            temp_dir,
            extra=(
                "title: Test Charm\n"
                "summary: A test charm\n"
                "description: Detailed description\n"
                "links:\n"
                "  documentation: https://docs.example.com\n"
                "  issues:\n    - https://github.com/test/issues\n"
                "  source:\n    - https://github.com/test/charm\n"
            ),
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        listing = result.data["listing_fields"]
        assert listing["title"] is True
        assert listing["links.documentation"] is True
        assert listing["links.issues"] is True
        assert listing["links.source"] is True

    @pytest.mark.asyncio
    async def test_listing_fields_flag_a_bare_charm(self, tool, temp_dir) -> None:
        """A charm with neither spelling still reports the fields missing."""
        _write_charmcraft_yaml(temp_dir)

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        listing = result.data["listing_fields"]
        assert listing["title"] is False
        assert listing["links.documentation"] is False
        assert listing["links.issues"] is False
        assert listing["links.source"] is False

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
        lib = temp_dir / "lib" / "charms" / "tls_certificates_interface" / "v3"
        lib.mkdir(parents=True)
        (lib / "tls_certificates.py").write_text("LIBID = 'x'\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["fetch_libs"][0]["lib_prefix"] == (
            "charms.tls_certificates_interface.v3.tls_certificates"
        )

    @pytest.mark.asyncio
    async def test_fetch_libs_in_report(self, tool, temp_dir) -> None:
        """Fetch-libs with known PyPI equivalents appear in the report."""
        _write_charmcraft_yaml(temp_dir)
        lib = temp_dir / "lib" / "charms" / "tls_certificates_interface" / "v3"
        lib.mkdir(parents=True)
        (lib / "tls_certificates.py").write_text("LIBID = 'x'\n")

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


# ===================================================================
# TestAuditToolCantripChecks
# ===================================================================


class TestAuditToolCantripChecks:
    """Tests for the gap checks that run in audit.py rather than charmlint."""

    @pytest.fixture
    def tool(self) -> CharmAuditTool:
        return CharmAuditTool()

    @pytest.mark.asyncio
    async def test_cos_gaps_read_split_metadata(self, tool, temp_dir) -> None:
        """Relations declared in a legacy metadata.yaml count."""
        _write_charmcraft_yaml(temp_dir)
        (temp_dir / "metadata.yaml").write_text(
            "name: test-charm\nprovides:\n  metrics-endpoint:\n    interface: prometheus_scrape\n"
        )

        result = await tool.execute(path=str(temp_dir))

        gaps = result.data["gaps"]
        assert gaps["cos_metrics"] is False
        assert gaps["cos_tracing"] is True
        assert "Missing tracing relation" in result.output

    @pytest.mark.asyncio
    async def test_ops_tracing_detected_in_source(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("import ops_tracing\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["gaps"]["ops_tracing"] is False

    @pytest.mark.asyncio
    async def test_reactive_framework_flagged(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)
        src = temp_dir / "src"
        src.mkdir()
        (src / "charm.py").write_text("from charms.reactive import when\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.data["gaps"]["reactive_framework"] is True
        assert result.data["deprecated_apis"] == [
            {
                "api": "reactive-framework",
                "file": "src/charm.py",
                "advice": (
                    "Uses legacy reactive framework (charms.reactive / @when / @hook decorators)"
                ),
            }
        ]
        assert "## Must Fix" in result.output

    @pytest.mark.asyncio
    async def test_charmlint_failure_fails_the_audit(self, tool, temp_dir) -> None:
        _write_charmcraft_yaml(temp_dir)

        with mock.patch.object(
            audit.charmlint_tool,
            "run_charmlint",
            side_effect=audit.charmlint_tool.CharmlintError("charmlint timed out"),
        ):
            result = await tool.execute(path=str(temp_dir))

        assert not result.success
        assert result.error == "charmlint timed out"
