"""Tests for the Phase 74.1 docs-bridge: TUTORIAL.md / DEMO.md / architecture.md
charm-root files getting bridged into the Diátaxis tree by ``generate_docs``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cantrip.agent.tools.publishing import (
    GenerateDocsTool,
    GenerateReadmeTool,
    _replace_first_h1,
    _rewrite_root_link,
    bridge_root_file,
    generate_docs_scaffold,
)

# ===========================================================================
# Pure helpers
# ===========================================================================


class TestReplaceFirstH1:
    def test_replaces_first_h1(self) -> None:
        result = _replace_first_h1("# Old\n\nbody\n", "# New")
        assert result.startswith("# New\n")
        assert "body" in result

    def test_leaves_h2_alone(self) -> None:
        result = _replace_first_h1("## Sub\n\nbody\n", "# New")
        # No H1 to replace — the helper should prepend the new heading.
        assert result.startswith("# New\n\n")
        assert "## Sub" in result

    def test_preserves_trailing_newline(self) -> None:
        with_nl = _replace_first_h1("# Old\nbody\n", "# New")
        without_nl = _replace_first_h1("# Old\nbody", "# New")
        assert with_nl.endswith("\n")
        assert not without_nl.endswith("\n")

    def test_replaces_only_first(self) -> None:
        result = _replace_first_h1("# First\n\n# Second\n", "# New")
        assert "# New" in result
        assert "# Second" in result

    def test_empty_content(self) -> None:
        result = _replace_first_h1("", "# New")
        assert result.startswith("# New")


class TestRewriteRootLink:
    def test_absolute_url_unchanged(self) -> None:
        assert _rewrite_root_link("https://example.com") == "https://example.com"
        assert _rewrite_root_link("mailto:foo@example.com") == "mailto:foo@example.com"

    def test_anchor_only_unchanged(self) -> None:
        assert _rewrite_root_link("#section") == "#section"

    def test_bridge_target_cross_reference(self) -> None:
        # Cross-references between bridged pages resolve via ``../<other>``.
        assert _rewrite_root_link("DEMO.md") == "../how-to/deploy-and-verify"
        assert _rewrite_root_link("architecture.md") == "../explanation/architecture"

    def test_bridge_target_with_anchor(self) -> None:
        assert (
            _rewrite_root_link("TUTORIAL.md#quick-start")
            == "../tutorial/getting-started#quick-start"
        )

    def test_root_relative_path_climbs_two_levels(self) -> None:
        assert _rewrite_root_link("WORKLOAD.md") == "../../WORKLOAD.md"
        assert (
            _rewrite_root_link("demo/screenshots/grafana.png")
            == "../../demo/screenshots/grafana.png"
        )

    def test_dot_slash_prefix_stripped(self) -> None:
        assert _rewrite_root_link("./README.md") == "../../README.md"

    def test_dotdot_prefix_left_alone(self) -> None:
        assert _rewrite_root_link("../sibling/path.md") == "../sibling/path.md"


# ===========================================================================
# bridge_root_file
# ===========================================================================


class TestBridgeRootFile:
    def test_tutorial_target_path(self) -> None:
        docs_path, _ = bridge_root_file("TUTORIAL.md", "# Tutorial\n", "My App")
        assert docs_path == "docs/tutorial/getting-started.md"

    def test_demo_target_path(self) -> None:
        docs_path, _ = bridge_root_file("DEMO.md", "# Demo\n", "My App")
        assert docs_path == "docs/how-to/deploy-and-verify.md"

    def test_architecture_target_path(self) -> None:
        docs_path, _ = bridge_root_file("architecture.md", "# Architecture\n", "My App")
        assert docs_path == "docs/explanation/architecture.md"

    def test_tutorial_heading_includes_display_name(self) -> None:
        _, content = bridge_root_file("TUTORIAL.md", "# Walk-through\n\nbody\n", "Redis K8s")
        assert content.startswith("# Get started with Redis K8s\n")
        assert "body" in content

    def test_demo_heading_includes_display_name(self) -> None:
        _, content = bridge_root_file("DEMO.md", "# Demo\n", "My App")
        assert content.startswith("# Deploy and verify My App\n")

    def test_architecture_heading_is_static(self) -> None:
        _, content = bridge_root_file("architecture.md", "# Whatever\n", "My App")
        assert content.startswith("# Architecture\n")

    def test_links_are_rewritten(self) -> None:
        source = (
            "# Tutorial\n"
            "\n"
            "See [the demo](DEMO.md) and the [architecture](architecture.md).\n"
            "Also see [WORKLOAD.md](WORKLOAD.md).\n"
            "Image: ![graph](demo/screenshots/grafana.png)\n"
        )
        _, content = bridge_root_file("TUTORIAL.md", source, "My App")
        assert "(../how-to/deploy-and-verify)" in content
        assert "(../explanation/architecture)" in content
        assert "(../../WORKLOAD.md)" in content
        assert "(../../demo/screenshots/grafana.png)" in content

    def test_unknown_root_file_raises(self) -> None:
        with pytest.raises(KeyError):
            bridge_root_file("README.md", "# Readme\n", "My App")


# ===========================================================================
# generate_docs_scaffold with root_files
# ===========================================================================


_SAMPLE_METADATA = {
    "name": "my-app",
    "display-name": "My App",
    "summary": "A widget server.",
    "description": "Long description.",
    "config": {"options": {"port": {"type": "int", "default": 8080}}},
    "actions": {"backup": {"description": "Snapshot data."}},
    "requires": {"db": {"interface": "pgsql"}},
    "provides": {"metrics-endpoint": {"interface": "prometheus_scrape"}},
}


class TestGenerateDocsScaffoldRootFiles:
    def test_no_root_files_uses_stub_tutorial(self) -> None:
        files = generate_docs_scaffold("my-app", _SAMPLE_METADATA)
        tutorial = files["docs/tutorial/getting-started.md"]
        # The templated stub mentions the deploy command.
        assert "juju deploy my-app" in tutorial

    def test_root_tutorial_overrides_stub(self) -> None:
        root = {"TUTORIAL.md": "# Tutorial\n\nCustom content from acceptance tests.\n"}
        files = generate_docs_scaffold("my-app", _SAMPLE_METADATA, root_files=root)
        tutorial = files["docs/tutorial/getting-started.md"]
        assert tutorial.startswith("# Get started with My App\n")
        assert "Custom content from acceptance tests." in tutorial
        # The metadata-derived deploy command stub is gone.
        assert "juju wait-for application" not in tutorial

    def test_root_demo_adds_deploy_and_verify(self) -> None:
        root = {"DEMO.md": "# Demo\n\nReal command output here.\n"}
        files = generate_docs_scaffold("my-app", _SAMPLE_METADATA, root_files=root)
        assert "docs/how-to/deploy-and-verify.md" in files
        page = files["docs/how-to/deploy-and-verify.md"]
        assert page.startswith("# Deploy and verify My App\n")
        assert "Real command output here." in page

    def test_root_architecture_overrides_stub(self) -> None:
        root = {"architecture.md": "# Arch\n\nMermaid here.\n"}
        files = generate_docs_scaffold("my-app", _SAMPLE_METADATA, root_files=root)
        arch = files["docs/explanation/architecture.md"]
        assert arch.startswith("# Architecture\n")
        assert "Mermaid here." in arch
        # The default stub's TODO marker is gone when overridden.
        assert "TODO" not in arch

    def test_howto_index_omits_deploy_and_verify_without_demo(self) -> None:
        files = generate_docs_scaffold("my-app", _SAMPLE_METADATA)
        index = files["docs/how-to/index.md"]
        assert "deploy-and-verify" not in index

    def test_howto_index_includes_deploy_and_verify_when_bridged(self) -> None:
        root = {"DEMO.md": "# Demo\n"}
        files = generate_docs_scaffold("my-app", _SAMPLE_METADATA, root_files=root)
        index = files["docs/how-to/index.md"]
        assert "deploy-and-verify" in index
        # And ordering puts it right after `deploy`.
        deploy_pos = index.index("deploy\n")
        verify_pos = index.index("deploy-and-verify\n")
        configure_pos = index.index("configure\n")
        assert deploy_pos < verify_pos < configure_pos

    def test_unknown_root_file_ignored(self) -> None:
        # Files we don't know how to bridge shouldn't break the scaffold.
        root = {"README.md": "irrelevant"}
        files = generate_docs_scaffold("my-app", _SAMPLE_METADATA, root_files=root)
        assert "docs/tutorial/getting-started.md" in files

    def test_falls_back_to_display_name_from_name(self) -> None:
        meta = {"name": "redis"}
        root = {"TUTORIAL.md": "# Tutorial\n"}
        files = generate_docs_scaffold("redis", meta, root_files=root)
        assert files["docs/tutorial/getting-started.md"].startswith("# Get started with redis\n")


# ===========================================================================
# GenerateDocsTool execution: root files → bridged content + stubs
# ===========================================================================


class TestGenerateDocsToolBridges:
    @pytest.fixture
    def tool(self) -> GenerateDocsTool:
        return GenerateDocsTool()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.mark.asyncio
    async def test_no_root_files_keeps_stub_behaviour(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        tutorial = (temp_dir / "docs" / "tutorial" / "getting-started.md").read_text()
        assert "juju deploy my-charm" in tutorial
        # No root file existed, so no bridge entries.
        assert result.data["bridged"] == []

    @pytest.mark.asyncio
    async def test_bridges_tutorial_and_writes_stub(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "TUTORIAL.md").write_text("# Tutorial\n\nReal walkthrough.\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        bridged_page = temp_dir / "docs" / "tutorial" / "getting-started.md"
        assert bridged_page.exists()
        assert "Real walkthrough." in bridged_page.read_text()
        # Root file is rewritten to a stub so existing links still resolve.
        stub = (temp_dir / "TUTORIAL.md").read_text()
        assert stub.startswith("# Moved")
        assert "docs/tutorial/getting-started.md" in stub
        # Tool result reports the bridge.
        assert any("TUTORIAL.md" in entry for entry in result.data["bridged"])

    @pytest.mark.asyncio
    async def test_bridges_demo_into_how_to(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "DEMO.md").write_text("# Demo\n\nCommand output.\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        page = temp_dir / "docs" / "how-to" / "deploy-and-verify.md"
        assert page.exists()
        assert "Command output." in page.read_text()
        assert (temp_dir / "DEMO.md").read_text().startswith("# Moved")
        # Howto index lists the new entry.
        index = (temp_dir / "docs" / "how-to" / "index.md").read_text()
        assert "deploy-and-verify" in index

    @pytest.mark.asyncio
    async def test_bridges_architecture_into_explanation(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "architecture.md").write_text("# Arch\n\n```mermaid\ngraph LR\nA-->B\n```\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        arch = (temp_dir / "docs" / "explanation" / "architecture.md").read_text()
        assert arch.startswith("# Architecture\n")
        assert "graph LR" in arch
        assert (temp_dir / "architecture.md").read_text().startswith("# Moved")

    @pytest.mark.asyncio
    async def test_existing_stub_not_re_bridged(self, tool, temp_dir) -> None:
        # Once the root file is a "Moved" pointer, a re-run shouldn't bridge
        # the pointer back into docs/ — it should keep whatever's currently
        # in docs/ as the source of truth.
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "TUTORIAL.md").write_text(
            "# Moved\n\nThis content now lives in [`docs/tutorial/getting-started.md`]"
            "(docs/tutorial/getting-started.md).\n"
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        # No bridge happened, so the docs/ tutorial is the metadata-derived
        # stub rather than the "Moved" pointer.
        tutorial = (temp_dir / "docs" / "tutorial" / "getting-started.md").read_text()
        assert "Moved" not in tutorial
        assert result.data["bridged"] == []

    @pytest.mark.asyncio
    async def test_links_inside_bridged_content_get_rewritten(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "TUTORIAL.md").write_text(
            "# Tutorial\n\nSee [DEMO.md](DEMO.md) and [WORKLOAD.md](WORKLOAD.md).\n"
        )

        await tool.execute(path=str(temp_dir))

        page = (temp_dir / "docs" / "tutorial" / "getting-started.md").read_text()
        assert "(../how-to/deploy-and-verify)" in page
        assert "(../../WORKLOAD.md)" in page


# ===========================================================================
# GenerateReadmeTool prefers bridged paths
# ===========================================================================


class TestGenerateReadmeBridgedLinks:
    @pytest.fixture
    def tool(self) -> GenerateReadmeTool:
        return GenerateReadmeTool()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.mark.asyncio
    async def test_falls_back_to_legacy_root_files(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "TUTORIAL.md").write_text("# Tutorial\n")
        (temp_dir / "DEMO.md").write_text("# Demo\n")
        (temp_dir / "architecture.md").write_text("# Arch\n")

        await tool.execute(path=str(temp_dir))

        readme = (temp_dir / "README.md").read_text()
        assert "[TUTORIAL.md](TUTORIAL.md)" in readme
        assert "[DEMO.md](DEMO.md)" in readme
        assert "[architecture.md](architecture.md)" in readme

    @pytest.mark.asyncio
    async def test_prefers_bridged_docs_paths(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "TUTORIAL.md").write_text("# Moved\n")
        (temp_dir / "DEMO.md").write_text("# Moved\n")
        (temp_dir / "architecture.md").write_text("# Moved\n")
        (temp_dir / "docs" / "tutorial").mkdir(parents=True)
        (temp_dir / "docs" / "tutorial" / "getting-started.md").write_text("# Get started\n")
        (temp_dir / "docs" / "how-to").mkdir()
        (temp_dir / "docs" / "how-to" / "deploy-and-verify.md").write_text("# Deploy\n")
        (temp_dir / "docs" / "explanation").mkdir()
        (temp_dir / "docs" / "explanation" / "architecture.md").write_text("# Arch\n")

        await tool.execute(path=str(temp_dir))

        readme = (temp_dir / "README.md").read_text()
        assert "docs/tutorial/getting-started.md" in readme
        assert "docs/how-to/deploy-and-verify.md" in readme
        assert "docs/explanation/architecture.md" in readme

    @pytest.mark.asyncio
    async def test_no_demo_section_without_any_files(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")

        await tool.execute(path=str(temp_dir))

        readme = (temp_dir / "README.md").read_text()
        assert "## Demo" not in readme

    @pytest.mark.asyncio
    async def test_mixed_only_bridged_demo(self, tool, temp_dir) -> None:
        # Only DEMO.md was bridged, tutorial wasn't — we should link both, but
        # to the bridged DEMO and the legacy TUTORIAL.
        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")
        (temp_dir / "TUTORIAL.md").write_text("# Tutorial\n")
        (temp_dir / "DEMO.md").write_text("# Moved\n")
        (temp_dir / "docs" / "how-to").mkdir(parents=True)
        (temp_dir / "docs" / "how-to" / "deploy-and-verify.md").write_text("# Deploy\n")

        await tool.execute(path=str(temp_dir))

        readme = (temp_dir / "README.md").read_text()
        assert "[TUTORIAL.md](TUTORIAL.md)" in readme
        assert "docs/how-to/deploy-and-verify.md" in readme
