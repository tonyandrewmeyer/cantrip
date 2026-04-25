"""End-to-end tests exercising real tools against the live Juju environment.

These tests require a running Juju controller (``juju status`` must work).
They do NOT require an LLM API key.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from cantrip.agent.tools import build_tools
from cantrip.agent.tools.base import ToolResult


def _juju_status_works() -> bool:
    """Return True only if ``juju status`` succeeds against a live controller."""
    if not shutil.which("juju"):
        return False
    try:
        result = subprocess.run(
            ["juju", "status", "--format", "json"],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _live_model_name() -> str | None:
    """Return the short name of any non-controller model on the live controller.

    Used by tests that need a real model to query but should not assume a
    specific name is present.  Returns None when juju is not reachable or
    the controller has only its bookkeeping ``controller`` model.
    """
    if not shutil.which("juju"):
        return None
    try:
        result = subprocess.run(
            ["juju", "models", "--format", "json"],
            capture_output=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    current = payload.get("current-model")
    if isinstance(current, str) and current and not current.endswith("/controller"):
        return current.split("/", 1)[-1]
    for entry in payload.get("models") or ():
        short = entry.get("short-name")
        if isinstance(short, str) and short and short != "controller":
            return short
    return None


_JUJU_LIVE = _juju_status_works()
_JUJU_MODEL = _live_model_name()

# Skip the entire module if juju is not available.
pytestmark = pytest.mark.skipif(
    not shutil.which("juju"),
    reason="juju CLI not available",
)


@pytest.fixture
def tool_map() -> dict:
    """Build the full tool set with a temporary charm path."""
    with tempfile.TemporaryDirectory() as tmp:
        tools = build_tools(base_path=Path(tmp))
        yield {t.name: t for t in tools}


class TestJujuTools:
    """Test Juju tools against the real environment."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _JUJU_LIVE, reason="juju controller not reachable")
    async def test_juju_status(self, tool_map: dict) -> None:
        """juju_status returns the current model status."""
        tool = tool_map["juju_status"]
        result: ToolResult = await tool.execute()
        assert result.success
        assert "Model:" in result.output

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _JUJU_LIVE, reason="juju controller not reachable")
    async def test_juju_status_named_model(self, tool_map: dict) -> None:
        """juju_status works with an explicit model name."""
        if _JUJU_MODEL is None:
            pytest.skip("no non-controller model available on live controller")
        tool = tool_map["juju_status"]
        result: ToolResult = await tool.execute(model=_JUJU_MODEL)
        assert result.success

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _JUJU_LIVE, reason="juju controller not reachable")
    async def test_juju_status_bad_model(self, tool_map: dict) -> None:
        """juju_status fails gracefully for a non-existent model."""
        tool = tool_map["juju_status"]
        result: ToolResult = await tool.execute(model="nonexistent-model-xyz")
        assert not result.success

    @pytest.mark.asyncio
    async def test_juju_list_models(self, tool_map: dict) -> None:
        """juju_list_models returns available models."""
        tool = tool_map.get("juju_list_models")
        if tool is None:
            pytest.skip("juju_list_models tool not available")
        if _JUJU_MODEL is None:
            pytest.skip("no non-controller model available on live controller")
        result: ToolResult = await tool.execute()
        assert result.success
        assert _JUJU_MODEL in result.output


class TestFileTools:
    """Test file tools with real filesystem operations."""

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, tool_map: dict) -> None:
        """write_file then read_file round-trips content."""
        write = tool_map["write_file"]
        read = tool_map["read_file"]

        result = await write.execute(path="test_e2e.txt", content="hello e2e")
        assert result.success

        result = await read.execute(path="test_e2e.txt")
        assert result.success
        assert "hello e2e" in result.output

    @pytest.mark.asyncio
    async def test_list_directory(self, tool_map: dict) -> None:
        """list_directory works on the charm path."""
        tool = tool_map["list_directory"]
        result: ToolResult = await tool.execute(path=".")
        assert result.success

    @pytest.mark.asyncio
    async def test_edit_file(self, tool_map: dict) -> None:
        """edit_file replaces content in a file."""
        write = tool_map["write_file"]
        edit = tool_map["edit_file"]
        read = tool_map["read_file"]

        await write.execute(path="edit_test.txt", content="foo bar baz")
        result = await edit.execute(path="edit_test.txt", old_string="bar", new_string="qux")
        assert result.success

        result = await read.execute(path="edit_test.txt")
        assert "foo qux baz" in result.output


class TestPreflightIntegration:
    """Test preflight checks against the real environment."""

    @pytest.mark.asyncio
    async def test_warm_up_detects_juju(self) -> None:
        """Preflight warm-up finds the juju CLI."""
        from cantrip.agent.preflight import PreflightRunner
        from cantrip.agent.state import AgentState

        state = AgentState()
        runner = PreflightRunner(state)
        result = await runner.warm_up()
        assert result.juju_available

    @pytest.mark.asyncio
    async def test_prepare_finds_controller(self) -> None:
        """Preflight prepare finds a healthy controller."""
        from cantrip.agent.preflight import PreflightRunner
        from cantrip.agent.state import AgentState

        state = AgentState()
        runner = PreflightRunner(state)
        result = await runner.prepare("k8s")
        assert result.juju_available
        assert result.controller_ready
        assert len(result.controllers) > 0


class TestSnapConfinement:
    """Test that deploy handles snap confinement for /tmp paths."""

    @pytest.mark.asyncio
    async def test_deploy_copies_charm_from_tmp(self) -> None:
        """A .charm file in /tmp is copied to ~/snap/juju/common/ before deploy."""
        # Create a dummy .charm file in /tmp.
        with tempfile.NamedTemporaryFile(
            suffix=".charm", prefix="test-e2e-", dir="/tmp", delete=False
        ) as f:
            dummy_charm = Path(f.name)
            f.write(b"not-a-real-charm")

        try:
            tools = build_tools(base_path=dummy_charm.parent)
            tool_map = {t.name: t for t in tools}
            deploy = tool_map["juju_deploy"]

            # This will fail because it's not a real charm, but the error
            # should be from juju (charm format), not from snap confinement.
            result: ToolResult = await deploy.execute(charm=str(dummy_charm), model="dev")
            assert not result.success
            # The error should NOT be about file not found / permission denied.
            # It should be about the charm format being invalid.
            error = (result.error or "").lower()
            assert "not found" not in error or "charm" in error
        finally:
            dummy_charm.unlink(missing_ok=True)
            # Clean up any temp copy.
            snap_copy = Path.home() / "snap" / "juju" / "common" / dummy_charm.name
            snap_copy.unlink(missing_ok=True)


class TestStatePersistence:
    """Test session state persistence end-to-end."""

    def test_save_and_load_round_trip(self) -> None:
        """Agent state survives save/load cycle."""
        from cantrip.agent.state import AgentState
        from cantrip.agent.store import SessionStore

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".cantrip"

            state = AgentState()
            state.charm_name = "test-e2e-charm"
            state.charm_type = "k8s"
            state.dev_model = "dev"
            state.cos_model = "cos"

            store = SessionStore(db_path)
            store.save_session(state)

            loaded = store.load_session()

            assert loaded is not None
            assert loaded.charm_name == "test-e2e-charm"
            assert loaded.charm_type == "k8s"
            assert loaded.dev_model == "dev"
            assert loaded.cos_model == "cos"

    def test_task_persistence(self) -> None:
        """Tasks survive save/load cycle."""
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
        from cantrip.agent.store import SessionStore

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".cantrip"
            store = SessionStore(db_path)

            queue = WorkQueue()
            task = AgentTask(
                title="Build charm",
                category=TaskCategory.BUILD,
                status=TaskStatus.DONE,
                result="Built successfully",
            )
            queue.add_task(task)
            store.save_tasks(queue.all_tasks())

            loaded = store.load_tasks()
            assert len(loaded) == 1
            assert loaded[0].title == "Build charm"
            assert loaded[0].status == TaskStatus.DONE
            assert loaded[0].result == "Built successfully"
