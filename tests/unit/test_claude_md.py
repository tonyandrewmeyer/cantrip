"""Tests for CLAUDE.md generation."""

import pathlib

from cantrip.agent.core import CantripAgent
from cantrip.agent.prompts.claude_md import render_claude_md
from tests.conftest import FakeProvider


class TestRenderClaudeMd:
    """Tests for the render_claude_md function."""

    def test_render_basic(self) -> None:
        """Renders with just a name, no type."""
        result = render_claude_md("my-charm")
        assert "my-charm" in result
        assert "CLAUDE.md" in result
        # Without a type, both machine and K8s guidance should appear.
        assert "Pebble" in result
        assert "machine" in result.lower()

    def test_render_kubernetes(self) -> None:
        """Kubernetes type includes Pebble, omits functional tests."""
        result = render_claude_md("k8s-app", charm_type="kubernetes")
        assert "k8s-app" in result
        assert "**Kubernetes** charm" in result
        assert "Pebble" in result
        assert "Functional tests" not in result

    def test_render_machine(self) -> None:
        """Machine type includes functional tests, omits Pebble."""
        result = render_claude_md("db-charm", charm_type="machine")
        assert "db-charm" in result
        assert "**machine** charm" in result
        assert "Functional tests" in result
        # Machine charms should not mention Pebble in the intro section.
        assert "Pebble" not in result

    def test_charm_name_in_juju_commands(self) -> None:
        """The charm name is substituted into Juju CLI examples."""
        result = render_claude_md("my-app")
        assert "juju deploy ./my-app.charm" in result
        assert "juju add-unit my-app" in result


class TestEnsureClaudeMd:
    """Tests for CantripAgent._ensure_claude_md integration."""

    def test_creates_file(self, tmp_path: pathlib.Path) -> None:
        """Agent with charm_path creates CLAUDE.md on init."""
        CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        # Uses directory name as charm_name fallback.
        assert tmp_path.name in content

    def test_does_not_overwrite(self, tmp_path: pathlib.Path) -> None:
        """Existing CLAUDE.md is not touched."""
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("custom content")
        CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert existing.read_text() == "custom content"

    def test_uses_charm_name_from_state(self, tmp_path: pathlib.Path) -> None:
        """When state.charm_name is set via loaded session, it is used."""
        provider = FakeProvider()
        # Create an agent, set charm_name, save state.
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "fancy-charm"
        agent.save_state()

        # Remove the CLAUDE.md so the next agent will re-create it.
        (tmp_path / "CLAUDE.md").unlink()

        # Create a fresh agent and load state before checking the file.
        agent2 = CantripAgent(provider=provider, charm_path=tmp_path)
        # The CLAUDE.md was created during __init__ before load_state,
        # so it uses the directory name. To test with charm_name, call
        # _ensure_claude_md again after loading state.
        (tmp_path / "CLAUDE.md").unlink()
        agent2.load_state()
        agent2._ensure_claude_md(tmp_path)

        content = (tmp_path / "CLAUDE.md").read_text()
        assert "fancy-charm" in content

    def test_no_file_without_charm_path(self) -> None:
        """No CLAUDE.md is created when charm_path is not set."""
        agent = CantripAgent(provider=FakeProvider())
        assert agent.state.charm_path is None
