"""Tests for CharmcraftPackTool — pre-pack PaaS requirements guard."""

import pathlib
import tempfile
from unittest import mock

import pytest

from cantrip.agent.tools.charm import (
    CharmcraftPackTool,
)


class TestCharmcraftPackPaasRequirementsGuard:
    """Pre-pack guard against a broken PaaS requirements.txt.

    Even if the agent's init step produced a correct requirements.txt,
    a subsequent ``cp`` or ``edit_file`` can still overwrite it.  The
    pack tool runs the same re-assertion one last time before handing
    off to ``charmcraft pack`` so a broken charm is never shipped.
    """

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield pathlib.Path(td)

    @pytest.fixture
    def tool(self):
        return CharmcraftPackTool()

    @pytest.mark.asyncio
    async def test_pack_repairs_overwritten_requirements(self, tool, temp_dir):
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir()
        (charm_dir / "charmcraft.yaml").write_text(
            "name: x\ntype: charm\nextensions:\n  - flask-framework\n"
        )
        # Simulate the post-``cp`` state that caused the live test failure.
        (charm_dir / "requirements.txt").write_text("flask>=3.0\n")

        # ``charmcraft pack`` itself is mocked — we only care about the guard.
        with mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="packed", stderr=""),
        ):
            result = await tool.execute(path=str(charm_dir))

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "paas-charm" in reqs
        assert "flask>=3.0" in reqs

    @pytest.mark.asyncio
    async def test_pack_does_not_touch_non_paas_requirements(self, tool, temp_dir):
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir()
        (charm_dir / "charmcraft.yaml").write_text("name: x\ntype: charm\n")
        (charm_dir / "requirements.txt").write_text("ops >= 2.0\n")

        with mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="packed", stderr=""),
        ):
            await tool.execute(path=str(charm_dir))

        reqs = (charm_dir / "requirements.txt").read_text()
        assert "paas-charm" not in reqs
