"""Integration tests for the Phase 80.5 destructive-command gate.

Exercise the in-code gate inside ``JujuDestroyModelTool``,
``JujuRemoveApplicationTool``, and ``RunCommandTool`` — all three
refuse destructive shapes unless a policy layer explicitly opts in
via ``approve_destructive: true``.
"""

from __future__ import annotations

import pathlib
from unittest import mock

import pytest

from cantrip.agent.tools.juju import (
    JujuDestroyModelTool,
    JujuRemoveApplicationTool,
)
from cantrip.agent.tools.run_command import DEFAULT_ALLOWLIST, RunCommandTool


@pytest.fixture
def _isolate_policies(tmp_path, monkeypatch):
    """Point ``Path.home()`` at an empty tmp_path so policy discovery
    doesn't pick up anything from the real $HOME during tests."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    yield tmp_path


@pytest.fixture(autouse=True)
def _local_controller(monkeypatch):
    """Phase 10b: bypass the controller-safety gate so these tests target
    the destructive gate, not the controller-safety layer that fires
    first inside the same tools."""
    monkeypatch.setattr(
        "cantrip.agent.tools.juju._common.controller_confirm_required",
        lambda *_args, **_kwargs: (False, ""),
    )


class TestJujuDestroyModelGate:
    @pytest.mark.asyncio
    async def test_gate_blocks_without_approval(self, _isolate_policies) -> None:
        tool = JujuDestroyModelTool()
        result = await tool.execute(model="dev")
        assert not result.success
        assert "approve_destructive" in result.error

    @pytest.mark.asyncio
    async def test_gate_allows_with_per_user_opt_in(
        self, _isolate_policies, tmp_path: pathlib.Path
    ) -> None:
        """A user-config policy with approve_destructive=True unblocks the call."""
        policies_dir = tmp_path / ".config" / "cantrip" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "yolo.yaml").write_text("name: yolo\napprove_destructive: true\n")

        tool = JujuDestroyModelTool()
        # Gate is through — the juju "not installed" path now fires.
        with mock.patch(
            "cantrip.agent.tools.juju._common._juju_available",
            return_value=False,
        ):
            result = await tool.execute(model="dev")
        assert not result.success
        # Error switched from "approve_destructive" to "not found".
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_gate_names_the_tool_in_the_refusal(self, _isolate_policies) -> None:
        tool = JujuDestroyModelTool()
        result = await tool.execute(model="dev")
        assert "juju_destroy_model" in result.error


class TestJujuRemoveApplicationGate:
    @pytest.mark.asyncio
    async def test_gate_blocks_without_approval(self, _isolate_policies) -> None:
        tool = JujuRemoveApplicationTool()
        result = await tool.execute(app_name="postgres")
        assert not result.success
        assert "approve_destructive" in result.error
        assert "juju_remove_application" in result.error

    @pytest.mark.asyncio
    async def test_gate_allows_with_opt_in(
        self, _isolate_policies, tmp_path: pathlib.Path
    ) -> None:
        policies_dir = tmp_path / ".config" / "cantrip" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "yolo.yaml").write_text("name: yolo\napprove_destructive: true\n")

        tool = JujuRemoveApplicationTool()
        with mock.patch(
            "cantrip.agent.tools.juju._common._juju_available",
            return_value=False,
        ):
            result = await tool.execute(app_name="postgres")
        assert not result.success
        assert "not found" in result.error.lower()


class TestRunCommandDestructiveShape:
    """Arg-pattern gate inside ``RunCommandTool.execute``."""

    @pytest.fixture
    def _rm_allowed_tool(self, tmp_path: pathlib.Path) -> RunCommandTool:
        """A RunCommandTool whose allowlist includes ``rm`` and ``git``
        — lets the destructive-shape gate be the thing that refuses
        rather than the base-command allow-list."""
        allowlist = DEFAULT_ALLOWLIST | {"rm", "git"}
        return RunCommandTool(allowlist=allowlist, base_path=tmp_path)

    @pytest.mark.asyncio
    async def test_rm_rf_blocked_without_approval(
        self, _rm_allowed_tool, _isolate_policies, tmp_path: pathlib.Path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        result = await _rm_allowed_tool.execute(
            command=f"rm -rf {target}",
            cwd=str(tmp_path),
        )
        assert not result.success
        assert "rm -rf" in result.error
        assert "approve_destructive" in result.error
        # Target survived.
        assert target.exists()

    @pytest.mark.asyncio
    async def test_rm_without_rf_passes_the_shape_gate(
        self, _rm_allowed_tool, _isolate_policies, tmp_path: pathlib.Path
    ) -> None:
        """Plain ``rm <file>`` (no -r or -f) is not a destructive shape.

        The run_command tool still runs — so the file actually
        disappears.  This test pins the negative case so a future
        tightening of the pattern doesn't accidentally block benign
        single-file deletes.
        """
        target = tmp_path / "dispensable.txt"
        target.write_text("x")
        result = await _rm_allowed_tool.execute(
            command=f"rm {target}",
            cwd=str(tmp_path),
        )
        assert result.success, result.error
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_git_push_force_blocked_without_approval(
        self, _rm_allowed_tool, _isolate_policies, tmp_path: pathlib.Path
    ) -> None:
        result = await _rm_allowed_tool.execute(
            command="git push --force origin main",
            cwd=str(tmp_path),
        )
        assert not result.success
        assert "git push --force" in result.error
        assert "approve_destructive" in result.error

    @pytest.mark.asyncio
    async def test_git_reset_hard_blocked_without_approval(
        self, _rm_allowed_tool, _isolate_policies, tmp_path: pathlib.Path
    ) -> None:
        result = await _rm_allowed_tool.execute(
            command="git reset --hard HEAD~1",
            cwd=str(tmp_path),
        )
        assert not result.success
        assert "git reset --hard" in result.error

    @pytest.mark.asyncio
    async def test_rm_rf_allowed_with_opt_in(
        self, _rm_allowed_tool, _isolate_policies, tmp_path: pathlib.Path
    ) -> None:
        """With approve_destructive=true, the shape gate passes and the
        subprocess fires.  The target directory actually gets deleted.
        """
        policies_dir = tmp_path / ".config" / "cantrip" / "policies"
        policies_dir.mkdir(parents=True)
        (policies_dir / "yolo.yaml").write_text("name: yolo\napprove_destructive: true\n")

        target = tmp_path / "dispensable"
        target.mkdir()
        (target / "file.txt").write_text("x")

        result = await _rm_allowed_tool.execute(
            command=f"rm -rf {target}",
            cwd=str(tmp_path),
        )
        assert result.success, result.error
        assert not target.exists()
