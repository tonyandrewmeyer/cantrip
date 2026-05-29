"""Integration tests: isolation and security boundaries in real flows.

Phase 93.4.  The sandbox (Phase 49), per-subagent worktrees (Phase 44),
and the policy / permission stack (Phase 68 / 80) each carry a promise:
a hallucinated or compromised tool call cannot reach outside its
intended scope.  Those promises are well covered at unit granularity,
but the roadmap asks for the same guarantees verified in *real flows* —
the actual ``PathAwareTool`` boundary, the live ``RunCommandTool``
sandbox wiring, the real ``git worktree`` lifecycle through the
executor, and the composed permission / policy gate inside a running
``Subagent`` — so a regression in any of them is caught before release.

These are regression guards, not optional hardening: every assertion
pins a boundary that already exists in the shipped code.
"""

from __future__ import annotations

import asyncio
import pathlib
import shutil
import subprocess
import types
from unittest.mock import AsyncMock, patch

import pytest

from cantrip.agent.executor import BackgroundExecutor
from cantrip.agent.git.worktree import (
    _BRANCH_PREFIX,
    _WORKTREES_DIRNAME,
    _DefaultWorktreeAllocator,
)
from cantrip.agent.policy.policy import GovernancePolicy
from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus, WorkQueue
from cantrip.agent.safety.permissions import (
    BUILTIN_PERMISSIONS,
    PLAN_MODE_OVERLAY,
    PermissionOutcome,
    PermissionRule,
    PermissionRuleset,
    compose_rulesets,
)
from cantrip.agent.safety.sandbox import SandboxPolicy
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import Subagent, SubagentContext
from cantrip.agent.tools.files import EditFileTool, ListDirectoryTool, ReadFileTool, WriteFileTool
from cantrip.agent.tools.run_command import RunCommandTool
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider
from tests.support.providers import CallbackProvider
from tests.support.tools import make_stub_tool


def _git_available() -> bool:
    return shutil.which("git") is not None


def _init_repo(path: pathlib.Path) -> None:
    """Initialise *path* as a git repo with one commit so HEAD exists."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)


def _commit_in_worktree(worktree: pathlib.Path, filename: str, contents: str) -> None:
    """Write *filename* in *worktree* and commit it on the ephemeral branch."""
    (worktree / filename).write_text(contents)
    subprocess.run(["git", "add", filename], cwd=worktree, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", f"add {filename}"],
        cwd=worktree,
        check=True,
    )


def _worktree_paths(repo: pathlib.Path) -> list[str]:
    """Return the working-tree paths git currently tracks for *repo*."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        line.split(" ", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def _branch_exists(repo: pathlib.Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# 1. Workspace boundary under pressure (real tool / agent flow)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkspaceBoundaryUnderPressure:
    """``PathAwareTool`` confines reads / writes to the charm directory.

    The boundary is enforced in :meth:`PathAwareTool._resolve_path`, which
    every file tool inherits.  These exercises drive the production tool
    objects directly with adversarial paths — traversal, symlink escape,
    and out-of-tree absolutes — and assert the escape never lands outside
    the base directory.
    """

    @pytest.mark.asyncio
    async def test_symlink_escape_on_write_is_refused(self, tmp_path: pathlib.Path) -> None:
        """A symlink pointing outside the base must not become a write escape."""
        base = tmp_path / "charm"
        outside = tmp_path / "outside"
        base.mkdir()
        outside.mkdir()
        # A symlink inside the charm that resolves to a sibling directory.
        (base / "escape").symlink_to(outside, target_is_directory=True)

        tool = WriteFileTool(base_path=base)
        result = await tool.execute(path="escape/pwned.txt", content="owned")

        assert not result.success
        assert "outside allowed directory" in (result.error or "")
        # The write never reached the out-of-tree target.
        assert not (outside / "pwned.txt").exists()

    @pytest.mark.asyncio
    async def test_symlink_escape_on_read_is_refused(self, tmp_path: pathlib.Path) -> None:
        """Reading through an escaping symlink must not leak out-of-tree files."""
        base = tmp_path / "charm"
        outside = tmp_path / "outside"
        base.mkdir()
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("top secret")
        (base / "link").symlink_to(outside, target_is_directory=True)

        tool = ReadFileTool(base_path=base)
        result = await tool.execute(path="link/secret.txt")

        assert not result.success
        assert "outside allowed directory" in (result.error or "")
        assert "top secret" not in result.output

    @pytest.mark.asyncio
    async def test_absolute_out_of_tree_write_is_refused(self, tmp_path: pathlib.Path) -> None:
        """An absolute path outside the base directory is rejected."""
        base = tmp_path / "charm"
        base.mkdir()
        target = tmp_path / "elsewhere.txt"

        tool = WriteFileTool(base_path=base)
        result = await tool.execute(path=str(target), content="nope")

        assert not result.success
        assert "outside allowed directory" in (result.error or "")
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_dotdot_traversal_on_edit_is_refused(self, tmp_path: pathlib.Path) -> None:
        """``../`` traversal is rejected by ``edit_file`` before any read."""
        base = tmp_path / "charm"
        base.mkdir()
        victim = tmp_path / "victim.txt"
        victim.write_text("original")

        tool = EditFileTool(base_path=base)
        result = await tool.execute(
            path="../victim.txt",
            old_string="original",
            new_string="tampered",
        )

        assert not result.success
        assert "outside allowed directory" in (result.error or "")
        assert victim.read_text() == "original"

    @pytest.mark.asyncio
    async def test_list_directory_traversal_is_refused(self, tmp_path: pathlib.Path) -> None:
        """``list_directory`` cannot enumerate a parent of the base directory."""
        base = tmp_path / "charm"
        base.mkdir()

        tool = ListDirectoryTool(base_path=base)
        result = await tool.execute(path="../../..")

        assert not result.success
        assert "outside allowed directory" in (result.error or "")

    @pytest.mark.asyncio
    async def test_in_tree_write_still_succeeds(self, tmp_path: pathlib.Path) -> None:
        """The boundary doesn't break legitimate in-tree writes (control case)."""
        base = tmp_path / "charm"
        base.mkdir()

        tool = WriteFileTool(base_path=base)
        result = await tool.execute(path="src/app.py", content="x = 1\n")

        assert result.success
        assert (base / "src" / "app.py").read_text() == "x = 1\n"


# ---------------------------------------------------------------------------
# 2. Sandbox confinement and destructive-command gate (real RunCommandTool)
# ---------------------------------------------------------------------------


class _RecordingSandbox:
    """A :class:`SandboxedRunner` stand-in that records the policy it saw.

    The real runner shells out under bwrap / unshare, which isn't
    deterministic across CI hosts.  This double captures the
    :class:`SandboxPolicy` ``RunCommandTool`` constructs so a test can
    assert the network is blocked and only the cwd is writable — the two
    properties the sandbox promise rests on — without depending on a
    particular kernel feature being available.
    """

    def __init__(self) -> None:
        self.calls: list[types.SimpleNamespace] = []

    def run(
        self,
        argv,
        *,
        cwd,
        policy,
        timeout=None,
        capture_output=True,
        text=True,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            types.SimpleNamespace(argv=list(argv), cwd=pathlib.Path(cwd), policy=policy)
        )
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout="ok", stderr="")


@pytest.mark.integration
class TestRunCommandSandboxAndDestructiveGate:
    """``RunCommandTool`` confines subprocesses and gates destructive shapes."""

    @pytest.mark.asyncio
    async def test_command_runs_with_network_blocked_and_cwd_only_writable(
        self, tmp_path: pathlib.Path
    ) -> None:
        """An allowlisted command runs under a no-network, cwd-scoped policy."""
        sandbox = _RecordingSandbox()
        tool = RunCommandTool(
            allowlist=frozenset({"make"}),
            base_path=tmp_path,
            sandbox_runner=sandbox,
        )

        result = await tool.execute(command="make build", cwd=str(tmp_path))

        assert result.success
        assert len(sandbox.calls) == 1
        policy: SandboxPolicy = sandbox.calls[0].policy
        assert policy.network is False
        assert policy.read_write_paths == (tmp_path.resolve(),)

    @pytest.mark.asyncio
    async def test_cwd_outside_project_tree_is_refused(self, tmp_path: pathlib.Path) -> None:
        """A working directory outside the base path never reaches the sandbox."""
        sandbox = _RecordingSandbox()
        tool = RunCommandTool(
            allowlist=frozenset({"make"}),
            base_path=tmp_path,
            sandbox_runner=sandbox,
        )

        result = await tool.execute(command="make build", cwd="/etc")

        assert not result.success
        assert "outside the project tree" in (result.error or "")
        assert sandbox.calls == []

    @pytest.mark.asyncio
    async def test_destructive_shape_blocked_without_approval(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``rm -rf`` is refused unless a policy opts into destructive commands."""
        # Hermetic: no discovered policy => no destructive approval.
        monkeypatch.setattr("cantrip.agent.policy.policy.discover_policies", lambda **_kw: [])
        sandbox = _RecordingSandbox()
        tool = RunCommandTool(
            allowlist=frozenset({"rm", "make"}),
            base_path=tmp_path,
            sandbox_runner=sandbox,
        )

        result = await tool.execute(command="rm -rf build", cwd=str(tmp_path))

        assert not result.success
        assert "requires explicit approval" in (result.error or "")
        # The subprocess never fired.
        assert sandbox.calls == []

    @pytest.mark.asyncio
    async def test_destructive_shape_allowed_with_approval_policy(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A policy with ``approve_destructive`` lets the gated shape through."""
        monkeypatch.setattr(
            "cantrip.agent.policy.policy.discover_policies",
            lambda **_kw: [GovernancePolicy(name="unattended", approve_destructive=True)],
        )
        sandbox = _RecordingSandbox()
        tool = RunCommandTool(
            allowlist=frozenset({"rm", "make"}),
            base_path=tmp_path,
            sandbox_runner=sandbox,
        )

        result = await tool.execute(command="rm -rf build", cwd=str(tmp_path))

        assert result.success
        # The approved command did reach the (recording) sandbox.
        assert len(sandbox.calls) == 1
        assert sandbox.calls[0].argv == ["rm", "-rf", "build"]


# ---------------------------------------------------------------------------
# 3. Worktree lifecycle and git isolation (real allocator + real git)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _git_available(), reason="git CLI not available")
class TestWorktreeIsolationAndLifecycle:
    """Per-subagent worktrees isolate writes and clean up after themselves."""

    @pytest.mark.asyncio
    async def test_concurrent_worktrees_are_isolated_then_merge_back(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Concurrently-allocated worktrees don't see each other's commits.

        Each worktree commits a distinct file on its own ephemeral branch;
        neither the sibling worktree nor the main tree observes the change
        until the executor merges the branch back.  The serialised
        merge-lock then lands both files on main without conflict.
        """
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator()

        # Allocate two worktrees concurrently to exercise the allocator lock.
        handle_a, handle_b = await asyncio.gather(
            allocator.allocate("task-a", tmp_path),
            allocator.allocate("task-b", tmp_path),
        )
        assert handle_a is not None
        assert handle_b is not None

        _commit_in_worktree(handle_a.path, "a.txt", "from a\n")
        _commit_in_worktree(handle_b.path, "b.txt", "from b\n")

        # Isolation: neither worktree sees the other's file, and main has neither.
        assert (handle_a.path / "a.txt").exists()
        assert not (handle_a.path / "b.txt").exists()
        assert (handle_b.path / "b.txt").exists()
        assert not (handle_b.path / "a.txt").exists()
        assert not (tmp_path / "a.txt").exists()
        assert not (tmp_path / "b.txt").exists()

        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[make_stub_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(charm_path=tmp_path),
            worktree_allocator=allocator,
        )
        task_a = AgentTask(id="task-a", title="Add a", category=TaskCategory.BUILD)
        task_b = AgentTask(id="task-b", title="Add b", category=TaskCategory.BUILD)

        assert await executor._merge_worktree(handle_a, task_a) is None
        assert await executor._merge_worktree(handle_b, task_b) is None

        # Both files reconciled onto main.
        assert (tmp_path / "a.txt").read_text() == "from a\n"
        assert (tmp_path / "b.txt").read_text() == "from b\n"

        await allocator.release("task-a")
        await allocator.release("task-b")

    @pytest.mark.asyncio
    async def test_dirty_main_tree_blocks_merge_and_preserves_branch(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Uncommitted work in main is never overwritten by a merge-back."""
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator()
        handle = await allocator.allocate("dirty", tmp_path)
        assert handle is not None
        _commit_in_worktree(handle.path, "feature.py", "print('hi')\n")

        # The user has unstaged work in the main tree.
        (tmp_path / "README.md").write_text("locally edited\n")

        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[make_stub_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(charm_path=tmp_path),
            worktree_allocator=allocator,
        )
        task = AgentTask(id="dirty", title="Add feature", category=TaskCategory.BUILD)

        error = await executor._merge_worktree(handle, task)

        assert error is not None
        assert "uncommitted changes" in error
        # The merge was skipped — main keeps the user's edit, not the feature.
        assert (tmp_path / "README.md").read_text() == "locally edited\n"
        assert not (tmp_path / "feature.py").exists()
        # Branch preserved for manual merge; release with keep_branch honours it.
        assert _branch_exists(tmp_path, handle.branch)
        await allocator.release("dirty", keep_branch=True)
        assert _branch_exists(tmp_path, handle.branch)

    @pytest.mark.asyncio
    async def test_failed_subagent_releases_worktree_with_no_leakage(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A crashing subagent leaves no worktree directory or branch behind.

        Drives the real ``_execute_task`` path with a real allocator and a
        subagent patched to raise.  The ``finally`` cleanup must drop the
        worktree and its ephemeral branch so a failed task doesn't leak a
        temporary tree across the session.
        """
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator()
        executor = BackgroundExecutor(
            queue=WorkQueue(),
            tools=[make_stub_tool("read_file")],
            provider=FakeProvider(responses=[Response(content="done")]),
            state=AgentState(charm_path=tmp_path),
            worktree_allocator=allocator,
        )
        task = AgentTask(id="boom", title="Will crash", category=TaskCategory.RESEARCH)
        executor._queue.add_task(task)
        executor._queue.set_active(task.id)

        expected_path = tmp_path / _WORKTREES_DIRNAME / "boom"
        expected_branch = f"{_BRANCH_PREFIX}boom"

        with patch("cantrip.agent.executor.core.Subagent") as mock_cls:
            mock_cls.return_value.run = AsyncMock(side_effect=RuntimeError("subagent exploded"))
            await executor._execute_task(task)

        # Task ended terminally and the worktree was fully cleaned up.
        assert executor._queue.get_task(task.id).status == TaskStatus.FAILED
        assert not expected_path.exists()
        assert not (tmp_path / _WORKTREES_DIRNAME).exists() or not any(
            (tmp_path / _WORKTREES_DIRNAME).iterdir()
        )
        assert expected_path.as_posix() not in _worktree_paths(tmp_path)
        assert not _branch_exists(tmp_path, expected_branch)
        assert allocator.get("boom") is None


# ---------------------------------------------------------------------------
# 4. Policy / permission boundary inside a running subagent
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPermissionAndPolicyBoundaryInRealFlows:
    """The composed policy / permission gate holds inside ``Subagent.run``."""

    @pytest.mark.asyncio
    async def test_plan_mode_denies_write_tool_in_real_run(self, tmp_path: pathlib.Path) -> None:
        """With the plan-mode overlay active, an edit call is refused, unexecuted."""
        from cantrip.agent.tools.base import ToolResult

        edit_tool = make_stub_tool("edit_file")
        edit_tool.execute = AsyncMock(return_value=ToolResult(success=True, output="edited"))

        captured_errors: list[str] = []

        def callback(messages, _tools):
            # On the follow-up turn, harvest any tool-result error text.
            for msg in messages:
                for tr in getattr(msg, "tool_results", None) or []:
                    if tr.is_error:
                        captured_errors.append(tr.content or "")
            if any(captured_errors):
                return Response(content="Understood, staying read-only.")
            return Response(
                content="",
                tool_calls=[
                    ToolCall(id="tc1", name="edit_file", arguments={"path": "charm.py"}),
                ],
            )

        ctx = SubagentContext(
            task=AgentTask(id="t", title="Edit", category=TaskCategory.BUILD),
            charm_path=str(tmp_path),
        )
        subagent = Subagent(
            ctx,
            tools=[edit_tool],
            provider=CallbackProvider(callback),
            permissions=compose_rulesets(PermissionRuleset(), PLAN_MODE_OVERLAY),
        )

        result = await subagent.run()

        edit_tool.execute.assert_not_called()
        assert result.text == "Understood, staying read-only."
        assert captured_errors
        assert "permissions policy" in captured_errors[0].lower()

    @pytest.mark.asyncio
    async def test_category_scope_blocks_cross_category_tool(self, tmp_path: pathlib.Path) -> None:
        """A RESEARCH subagent cannot execute a deploy-only tool."""
        from cantrip.agent.tools.base import ToolResult

        deploy_tool = make_stub_tool("juju_deploy")
        deploy_tool.execute = AsyncMock(return_value=ToolResult(success=True, output="deployed"))

        captured_errors: list[str] = []

        def callback(messages, _tools):
            for msg in messages:
                for tr in getattr(msg, "tool_results", None) or []:
                    if tr.is_error:
                        captured_errors.append(tr.content or "")
            if any(captured_errors):
                return Response(content="Cannot deploy from research.")
            return Response(
                content="",
                tool_calls=[ToolCall(id="tc1", name="juju_deploy", arguments={})],
            )

        ctx = SubagentContext(
            task=AgentTask(id="t", title="Research", category=TaskCategory.RESEARCH),
            charm_path=str(tmp_path),
        )
        subagent = Subagent(ctx, tools=[deploy_tool], provider=CallbackProvider(callback))

        result = await subagent.run()

        deploy_tool.execute.assert_not_called()
        assert result.text == "Cannot deploy from research."
        assert captured_errors
        assert "policy" in captured_errors[0].lower()

    @pytest.mark.asyncio
    async def test_destructive_shell_tool_gated_in_real_run(self, tmp_path: pathlib.Path) -> None:
        """A subagent's ``rm -rf`` shell call is refused before it can execute.

        ``run_command`` is on the org-wide review list, so the policy gate
        intercepts the call ahead of the subprocess.  Either way the
        destructive shell command never runs — the defence-in-depth stack
        keeps the shell behind an approval boundary.
        """
        from cantrip.agent.tools.base import ToolResult

        run_tool = make_stub_tool("run_command")
        run_tool.execute = AsyncMock(return_value=ToolResult(success=True, output="ran"))

        captured_errors: list[str] = []

        def callback(messages, _tools):
            for msg in messages:
                for tr in getattr(msg, "tool_results", None) or []:
                    if tr.is_error:
                        captured_errors.append(tr.content or "")
            if any(captured_errors):
                return Response(content="Won't delete the tree.")
            return Response(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc1",
                        name="run_command",
                        arguments={"command": "rm -rf /tmp/everything"},
                    ),
                ],
            )

        ctx = SubagentContext(
            task=AgentTask(id="t", title="Clean", category=TaskCategory.BUILD),
            charm_path=str(tmp_path),
        )
        subagent = Subagent(
            ctx,
            tools=[run_tool],
            provider=CallbackProvider(callback),
            permissions=BUILTIN_PERMISSIONS,
        )

        result = await subagent.run()

        run_tool.execute.assert_not_called()
        assert result.text == "Won't delete the tree."
        assert captured_errors
        assert "approval" in captured_errors[0].lower()

    @pytest.mark.asyncio
    async def test_ask_without_manager_denies_in_real_run(self, tmp_path: pathlib.Path) -> None:
        """An ``ask`` verdict with no approval surface degrades to deny."""
        from cantrip.agent.tools.base import ToolResult

        edit_tool = make_stub_tool("edit_file")
        edit_tool.execute = AsyncMock(return_value=ToolResult(success=True, output="edited"))

        captured_errors: list[str] = []

        def callback(messages, _tools):
            for msg in messages:
                for tr in getattr(msg, "tool_results", None) or []:
                    if tr.is_error:
                        captured_errors.append(tr.content or "")
            if any(captured_errors):
                return Response(content="No approval available.")
            return Response(
                content="",
                tool_calls=[
                    ToolCall(id="tc1", name="edit_file", arguments={"path": "charm.py"}),
                ],
            )

        ask_rules = PermissionRuleset(
            tools=(PermissionRule("edit_file", PermissionOutcome.ASK),),
        )
        ctx = SubagentContext(
            task=AgentTask(id="t", title="Edit", category=TaskCategory.BUILD),
            charm_path=str(tmp_path),
        )
        # No permission_manager wired — the gate must refuse rather than hang.
        subagent = Subagent(
            ctx,
            tools=[edit_tool],
            provider=CallbackProvider(callback),
            permissions=ask_rules,
        )

        result = await subagent.run()

        edit_tool.execute.assert_not_called()
        assert result.text == "No approval available."
        assert captured_errors
        assert "permission required" in captured_errors[0].lower()
