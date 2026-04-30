"""Tests for AGENTS.md generation."""

import pathlib

from cantrip.agent.core import CantripAgent
from cantrip.agent.prompts.agents_md import render_agents_md
from tests.conftest import FakeProvider


class TestRenderAgentsMd:
    """Tests for the render_agents_md function."""

    def test_render_basic(self) -> None:
        """Renders with just a name, no type."""
        result = render_agents_md("my-charm")
        assert "my-charm" in result
        assert "AGENTS.md" in result
        # Without a type, both machine and K8s guidance should appear.
        assert "Pebble" in result
        assert "machine" in result.lower()

    def test_render_kubernetes(self) -> None:
        """Kubernetes type includes Pebble, omits functional tests."""
        result = render_agents_md("k8s-app", charm_type="kubernetes")
        assert "k8s-app" in result
        assert "**Kubernetes** charm" in result
        assert "Pebble" in result
        assert "Functional tests" not in result

    def test_render_machine(self) -> None:
        """Machine type includes functional tests, omits Pebble."""
        result = render_agents_md("db-charm", charm_type="machine")
        assert "db-charm" in result
        assert "**machine** charm" in result
        assert "Functional tests" in result
        # Machine charms should not mention Pebble in the intro section.
        assert "Pebble" not in result

    def test_charm_name_in_juju_commands(self) -> None:
        """The charm name is substituted into Juju CLI examples."""
        result = render_agents_md("my-app")
        assert "juju deploy ./my-app.charm" in result
        assert "juju add-unit my-app" in result


class TestEnsureAgentsMd:
    """Tests for CantripAgent._ensure_agents_md integration."""

    def test_creates_file_and_symlink(self, tmp_path: pathlib.Path) -> None:
        """Agent with charm_path creates AGENTS.md and a CLAUDE.md symlink."""
        CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        agents_md = tmp_path / "AGENTS.md"
        claude_md = tmp_path / "CLAUDE.md"
        assert agents_md.is_file()
        assert claude_md.is_symlink()
        assert claude_md.readlink() == pathlib.Path("AGENTS.md")
        # Symlink resolves to the same content.
        assert claude_md.read_text() == agents_md.read_text()
        # Uses directory name as charm_name fallback.
        assert tmp_path.name in agents_md.read_text()

    def test_does_not_overwrite_existing_agents_md(self, tmp_path: pathlib.Path) -> None:
        """Existing AGENTS.md is not touched and no symlink is created."""
        existing = tmp_path / "AGENTS.md"
        existing.write_text("custom agents content")
        CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert existing.read_text() == "custom agents content"
        assert not (tmp_path / "CLAUDE.md").exists()

    def test_does_not_overwrite_existing_claude_md(self, tmp_path: pathlib.Path) -> None:
        """Existing CLAUDE.md (regular file) is preserved; no AGENTS.md is added."""
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("custom claude content")
        CantripAgent(provider=FakeProvider(), charm_path=tmp_path)
        assert existing.read_text() == "custom claude content"
        assert not (tmp_path / "AGENTS.md").exists()

    def test_uses_charm_name_from_state(self, tmp_path: pathlib.Path) -> None:
        """When state.charm_name is set via loaded session, it is used."""
        provider = FakeProvider()
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        agent.state.charm_name = "fancy-charm"
        agent.save_state()

        # Wipe the AGENTS.md + CLAUDE.md symlink so the next call re-creates them.
        (tmp_path / "CLAUDE.md").unlink()
        (tmp_path / "AGENTS.md").unlink()

        agent2 = CantripAgent(provider=provider, charm_path=tmp_path)
        # __init__ already wrote with the directory name; clear and call
        # again after load_state to pick up charm_name.
        (tmp_path / "CLAUDE.md").unlink()
        (tmp_path / "AGENTS.md").unlink()
        agent2.load_state()
        agent2._ensure_agents_md(tmp_path)

        content = (tmp_path / "AGENTS.md").read_text()
        assert "fancy-charm" in content

    def test_no_file_without_charm_path(self) -> None:
        """No AGENTS.md is created when charm_path is not set."""
        agent = CantripAgent(provider=FakeProvider())
        assert agent.state.charm_path is None
