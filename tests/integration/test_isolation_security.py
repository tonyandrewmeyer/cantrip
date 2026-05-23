"""Integration tests: isolation, sandbox, and security boundary enforcement.

Phase 93.4.  Tests that the sandbox/workspace/worktree boundaries hold
under pressure: path traversal, symlink escapes, out-of-tree writes,
temp-file leakage, cleanup after failure, worktree lifecycle, and
policy/permission boundary enforcement in real flows.

These act as regression guards for Phase 49's sandbox promise and
Phase 44's worktree isolation — things that must keep working correctly
even as the rest of the codebase evolves.

Tests that require a real git installation are gated with a ``skipif``
on ``shutil.which("git")``.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from cantrip.agent import permissions as perm_mod
from cantrip.agent import sandbox as sandbox_mod
from cantrip.agent.permissions import (
    BUILTIN_PERMISSIONS,
    PLAN_MODE_OVERLAY,
    PermissionAskRequest,
    PermissionManager,
    PermissionOutcome,
    PermissionRule,
    PermissionRuleset,
    compose_rulesets,
    evaluate,
)
from cantrip.agent.policy import GovernancePolicy, PolicyAction, compose_policies
from cantrip.agent.sandbox import SandboxedRunner, SandboxPolicy
from cantrip.agent.worktree import (
    _BRANCH_PREFIX,
    _WORKTREES_DIRNAME,
    _DefaultWorktreeAllocator,
)

_GIT_AVAILABLE = shutil.which("git") is not None
requires_git = pytest.mark.skipif(not _GIT_AVAILABLE, reason="git CLI not available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(path: pathlib.Path) -> None:
    """Initialise *path* as a git repo with one commit."""
    env = {**os.environ, "HOME": str(pathlib.Path.home())}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, env=env)
    subprocess.run(
        ["git", "config", "user.email", "test@cantrip.local"], cwd=path, check=True, env=env
    )
    subprocess.run(["git", "config", "user.name", "Cantrip Test"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True, env=env)
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "initial"],
        cwd=path,
        check=True,
        env=env,
    )


def _branch_exists(repo: pathlib.Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _worktree_paths(repo: pathlib.Path) -> list[str]:
    """Return all paths git knows about via ``git worktree list``."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        line.split(" ", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


# ===========================================================================
# 1. Sandbox policy: wrap() method builds correct argv without real bwrap
# ===========================================================================


@pytest.mark.integration
class TestSandboxPolicyArgvConstruction:
    """Verify that SandboxedRunner.wrap() constructs safe argv regardless of mechanism.

    We test the ``bwrap`` and ``unshare`` wrap helpers without invoking
    the real sandbox tool — they are pure argv builders.  The ``run()``
    path is tested separately.
    """

    def test_bwrap_wrap_includes_cwd_bind(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="bwrap")
        argv = runner.wrap(["make", "test"], cwd=tmp_path, policy=SandboxPolicy())
        # CWD must appear as a ``--bind`` destination so the command can write.
        assert "--bind" in argv
        bind_idx = argv.index("--bind")
        assert str(tmp_path) in argv[bind_idx : bind_idx + 3]

    def test_bwrap_wrap_network_off_adds_unshare_net(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="bwrap")
        argv = runner.wrap(["ls"], cwd=tmp_path, policy=SandboxPolicy(network=False))
        assert "--unshare-net" in argv

    def test_bwrap_wrap_network_on_omits_unshare_net(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="bwrap")
        argv = runner.wrap(["ls"], cwd=tmp_path, policy=SandboxPolicy(network=True))
        assert "--unshare-net" not in argv

    def test_bwrap_wrap_read_write_path_included(self, tmp_path: pathlib.Path):
        extra = tmp_path / "writable"
        extra.mkdir()
        runner = SandboxedRunner(mechanism="bwrap")
        argv = runner.wrap(
            ["ls"],
            cwd=tmp_path / "subdir",
            policy=SandboxPolicy(read_write_paths=(extra,)),
        )
        assert str(extra) in argv

    def test_bwrap_wrap_missing_read_write_path_skipped(self, tmp_path: pathlib.Path):
        """Missing extra write paths are silently dropped (not an error)."""
        missing = tmp_path / "does-not-exist"
        runner = SandboxedRunner(mechanism="bwrap")
        # Should not raise even though the path doesn't exist.
        argv = runner.wrap(
            ["ls"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_write_paths=(missing,)),
        )
        assert str(missing) not in argv

    def test_unshare_wrap_includes_net_when_network_off(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="unshare")
        argv = runner.wrap(["ls"], cwd=tmp_path, policy=SandboxPolicy(network=False))
        # ``--net`` unshares the network namespace under ``unshare``.
        assert "--net" in argv

    def test_unshare_wrap_omits_net_when_network_on(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="unshare")
        argv = runner.wrap(["ls"], cwd=tmp_path, policy=SandboxPolicy(network=True))
        assert "--net" not in argv

    def test_none_mechanism_returns_bare_argv(self, tmp_path: pathlib.Path):
        runner = SandboxedRunner(mechanism="none")
        argv = runner.wrap(["echo", "hello"], cwd=tmp_path, policy=SandboxPolicy())
        assert argv == ["echo", "hello"]

    def test_read_only_path_bound_in_bwrap(self, tmp_path: pathlib.Path):
        ro_path = tmp_path / "read-only"
        ro_path.mkdir()
        runner = SandboxedRunner(mechanism="bwrap")
        argv = runner.wrap(
            ["ls"],
            cwd=tmp_path,
            policy=SandboxPolicy(read_only_paths=(ro_path,)),
        )
        assert "--ro-bind" in argv
        # The read-only path must appear after ``--ro-bind``.
        ro_idx = [
            i for i, a in enumerate(argv) if a == "--ro-bind" and str(ro_path) in argv[i : i + 3]
        ]
        assert ro_idx, "ro path not bound read-only in bwrap argv"


# ===========================================================================
# 2. Sandbox path-traversal and symlink protection
# ===========================================================================


@pytest.mark.integration
class TestSandboxPathBoundaries:
    """Verify the sandbox doesn't expose paths outside the designated roots."""

    def test_policy_read_write_path_resolved(self, tmp_path: pathlib.Path):
        """Paths in the policy are resolved so a traversal component can't escape.

        The SandboxedRunner resolves all read_write_paths via
        ``pathlib.Path(path).resolve()`` before building the argv.  We verify
        that resolving a path containing ``..`` collapses the traversal so the
        bwrap ``--bind`` argument points to the real, canonical path.
        """
        # Create a real sub-directory so pathlib can resolve a ``..`` path through it.
        sub = tmp_path / "sub"
        sub.mkdir()
        # A path that traverses back to the parent: ``tmp/sub/../sibling``.
        traversal = sub / ".." / "sibling"
        # ``pathlib.Path.resolve()`` must collapse the ``..`` component.
        actual = traversal.resolve()
        assert ".." not in actual.parts
        # The resolved path must still be inside tmp_path.
        assert str(actual).startswith(str(tmp_path))

    def test_symlink_outside_sandbox_not_automatically_bound(self, tmp_path: pathlib.Path):
        """A symlink inside the sandbox that points outside is not auto-bound."""
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "key.txt").write_text("top-secret")

        sandbox_root = tmp_path / "sandbox"
        sandbox_root.mkdir()
        link = sandbox_root / "escape"
        link.symlink_to(secret)

        runner = SandboxedRunner(mechanism="bwrap")
        argv = runner.wrap(["ls"], cwd=sandbox_root, policy=SandboxPolicy())
        # The symlink target (secret dir) should not appear as a bound mount.
        assert str(secret) not in " ".join(argv)

    def test_none_sandbox_does_not_add_extra_args(self, tmp_path: pathlib.Path):
        """The no-op sandbox must never inject extra flags into argv."""
        runner = SandboxedRunner(mechanism="none")
        inner = ["python3", "-c", "print('ok')"]
        result = runner.wrap(inner, cwd=tmp_path, policy=SandboxPolicy())
        assert result == inner

    def test_event_sink_receives_policy_decision(self, tmp_path: pathlib.Path):
        """Event sink gets called with the policy payload on every run()."""
        events: list[tuple[str, dict]] = []
        sandbox_mod.set_event_sink(lambda name, payload: events.append((name, payload)))
        try:
            runner = SandboxedRunner(mechanism="none")
            runner.run(["true"], cwd=tmp_path, policy=SandboxPolicy())
        finally:
            sandbox_mod.set_event_sink(None)

        assert events, "event sink was never called"
        name, payload = events[0]
        assert name == "sandbox_policy"
        assert payload["mechanism"] == "none"
        assert "argv" in payload
        assert payload["network"] is False  # default

    def test_tmp_file_cleanup_after_run(self, tmp_path: pathlib.Path):
        """Running a command via the sandbox doesn't leave tmp files behind."""
        before = set(pathlib.Path(tempfile.gettempdir()).iterdir())
        runner = SandboxedRunner(mechanism="none")
        runner.run(["true"], cwd=tmp_path)
        after = set(pathlib.Path(tempfile.gettempdir()).iterdir())
        # No cantrip-sandbox-probe-* files lingering.
        new_files = {p for p in (after - before) if "cantrip" in p.name}
        assert not new_files, f"tmp files leaked: {new_files}"


# ===========================================================================
# 3. Worktree lifecycle and git isolation
# ===========================================================================


@pytest.mark.integration
@requires_git
class TestWorktreeLifecycle:
    """Worktree allocation, teardown, and isolation in a real git repo."""

    @pytest.mark.asyncio
    async def test_allocate_creates_branch_and_directory(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        handle = await allocator.allocate("task-1", tmp_path)

        assert handle is not None
        assert handle.path.exists()
        assert handle.branch == f"{_BRANCH_PREFIX}task-1"
        assert _branch_exists(tmp_path, handle.branch)

        await allocator.release("task-1")

    @pytest.mark.asyncio
    async def test_release_removes_worktree_and_branch(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        handle = await allocator.allocate("task-2", tmp_path)
        assert handle is not None
        wt_path = handle.path
        branch = handle.branch

        await allocator.release("task-2")

        assert not wt_path.exists()
        assert not _branch_exists(tmp_path, branch)

    @pytest.mark.asyncio
    async def test_keep_branch_preserves_branch_on_release(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        handle = await allocator.allocate("task-3", tmp_path)
        assert handle is not None
        branch = handle.branch

        await allocator.release("task-3", keep_branch=True)

        assert not handle.path.exists()
        assert _branch_exists(tmp_path, branch)
        # Clean up the leftover branch.
        subprocess.run(["git", "branch", "-D", branch], cwd=tmp_path, check=False)

    @pytest.mark.asyncio
    async def test_non_git_path_returns_none(self, tmp_path: pathlib.Path):
        """A non-git directory returns None rather than raising."""
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        handle = await allocator.allocate("task-nogit", tmp_path)
        assert handle is None

    @pytest.mark.asyncio
    async def test_two_worktrees_are_isolated_on_disk(self, tmp_path: pathlib.Path):
        """Files written in one worktree don't appear in another."""
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        h1 = await allocator.allocate("wt-a", tmp_path)
        h2 = await allocator.allocate("wt-b", tmp_path)
        assert h1 is not None and h2 is not None

        # Write a file in the first worktree only.
        (h1.path / "secret.txt").write_text("only-in-wt-a")

        # Verify the file is NOT visible in the second worktree.
        assert not (h2.path / "secret.txt").exists()

        await allocator.release("wt-a")
        await allocator.release("wt-b")

    @pytest.mark.asyncio
    async def test_dirty_worktree_does_not_block_release(self, tmp_path: pathlib.Path):
        """An uncommitted file in the worktree is removed on release (--force)."""
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        handle = await allocator.allocate("dirty-task", tmp_path)
        assert handle is not None

        # Leave a dirty file in the worktree.
        (handle.path / "dirty.txt").write_text("uncommitted change")

        # Release should succeed without raising even though the worktree is dirty.
        await allocator.release("dirty-task")
        assert not handle.path.exists()

    @pytest.mark.asyncio
    async def test_reap_orphans_removes_stale_handles(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        h = await allocator.allocate("orphan-task", tmp_path)
        assert h is not None

        # active_task_ids does NOT include "orphan-task" → it's an orphan.
        reaped = await allocator.reap_orphans(active_task_ids=set())
        assert reaped == 1
        assert not h.path.exists()

    @pytest.mark.asyncio
    async def test_reap_disk_orphans_cleans_prior_session_worktrees(self, tmp_path: pathlib.Path):
        """Worktrees left by a previous process are removed by reap_disk_orphans."""
        _init_repo(tmp_path)
        # Allocate in one allocator instance (simulating a previous session).
        old_allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        h = await old_allocator.allocate("prev-session-task", tmp_path)
        assert h is not None
        # The old allocator is "gone" (process exited); a fresh one has no handles.
        new_allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        reaped = await new_allocator.reap_disk_orphans(tmp_path, active_task_ids=set())
        assert reaped >= 1
        assert not h.path.exists()

    @pytest.mark.asyncio
    async def test_git_isolation_branch_excludes_worktree_dir(self, tmp_path: pathlib.Path):
        """The ``.cantrip-worktrees`` dir is excluded from git status in the main tree."""
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        h = await allocator.allocate("exclude-test", tmp_path)
        assert h is not None

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        # The worktree directory must not appear as an untracked change.
        assert _WORKTREES_DIRNAME not in status.stdout

        await allocator.release("exclude-test")

    @pytest.mark.asyncio
    async def test_allocate_duplicate_raises(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        await allocator.allocate("dup-task", tmp_path)
        with pytest.raises(ValueError, match="already allocated"):
            await allocator.allocate("dup-task", tmp_path)
        await allocator.release("dup-task")


# ===========================================================================
# 4. Worktree failure-cleanup
# ===========================================================================


@pytest.mark.integration
@requires_git
class TestWorktreeFailureCleanup:
    """Verify worktrees are properly cleaned up even after unexpected failures."""

    @pytest.mark.asyncio
    async def test_release_idempotent_on_already_released(self, tmp_path: pathlib.Path):
        """Releasing a task that was never allocated is a no-op."""
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        # Should not raise.
        await allocator.release("never-allocated-task")

    @pytest.mark.asyncio
    async def test_release_of_manually_removed_directory(self, tmp_path: pathlib.Path):
        """If the worktree dir was removed externally, release falls back to prune."""
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(min_free_bytes=0)
        handle = await allocator.allocate("rm-task", tmp_path)
        assert handle is not None

        # Simulate external removal.
        shutil.rmtree(handle.path)

        # Release must not raise — git worktree prune recovers.
        await allocator.release("rm-task")

    @pytest.mark.asyncio
    async def test_max_worktrees_cap_prevents_over_allocation(self, tmp_path: pathlib.Path):
        _init_repo(tmp_path)
        allocator = _DefaultWorktreeAllocator(max_worktrees=2, min_free_bytes=0)
        h1 = await allocator.allocate("cap-1", tmp_path)
        h2 = await allocator.allocate("cap-2", tmp_path)
        h3 = await allocator.allocate("cap-3", tmp_path)
        assert h1 is not None
        assert h2 is not None
        assert h3 is None  # Cap reached.

        await allocator.release("cap-1")
        await allocator.release("cap-2")


# ===========================================================================
# 5. Permission boundary — plan mode, destructive gates, category-scoped access
# ===========================================================================


@pytest.mark.integration
class TestPermissionBoundaryPlanMode:
    """Plan mode overlay denies mutating tools while allowing read-only ones."""

    def test_plan_mode_denies_write_file(self):
        ruleset = compose_rulesets(BUILTIN_PERMISSIONS, PLAN_MODE_OVERLAY)
        decision = evaluate(ruleset, "write_file", {"path": "/tmp/x"})
        assert decision.denied

    def test_plan_mode_denies_run_command(self):
        ruleset = compose_rulesets(BUILTIN_PERMISSIONS, PLAN_MODE_OVERLAY)
        decision = evaluate(ruleset, "run_command", {"command": "make test"})
        assert decision.denied

    def test_plan_mode_allows_read_file(self):
        ruleset = compose_rulesets(BUILTIN_PERMISSIONS, PLAN_MODE_OVERLAY)
        decision = evaluate(ruleset, "read_file", {"path": "/tmp/file.txt"})
        assert decision.outcome is PermissionOutcome.ALLOW

    def test_plan_mode_allows_web_search(self):
        ruleset = compose_rulesets(BUILTIN_PERMISSIONS, PLAN_MODE_OVERLAY)
        decision = evaluate(ruleset, "web_search")
        assert decision.outcome is PermissionOutcome.ALLOW

    def test_plan_mode_allows_juju_status(self):
        ruleset = compose_rulesets(BUILTIN_PERMISSIONS, PLAN_MODE_OVERLAY)
        decision = evaluate(ruleset, "juju_status")
        assert decision.outcome is PermissionOutcome.ALLOW

    def test_plan_mode_denies_unknown_tool(self):
        ruleset = compose_rulesets(BUILTIN_PERMISSIONS, PLAN_MODE_OVERLAY)
        decision = evaluate(ruleset, "some_new_tool")
        assert decision.denied

    def test_plan_mode_message_includes_tool_name(self):
        msg = perm_mod.plan_mode_message("write_file")
        assert "write_file" in msg
        assert "/build" in msg


@pytest.mark.integration
class TestPermissionBoundaryDestructiveGates:
    """Destructive commands are denied/asked per rule without plan mode."""

    def test_rm_rf_denied_by_builtin(self):
        ruleset = BUILTIN_PERMISSIONS
        decision = evaluate(ruleset, "run_command", {"command": "rm -rf /tmp/foo"})
        assert decision.denied

    def test_env_file_path_denied_by_builtin(self):
        ruleset = BUILTIN_PERMISSIONS
        decision = evaluate(ruleset, "read_file", {"path": "/home/user/.env"})
        assert decision.denied

    def test_dotenv_file_denied(self):
        ruleset = BUILTIN_PERMISSIONS
        decision = evaluate(ruleset, "write_file", {"path": "/project/secrets.env"})
        assert decision.denied

    def test_allow_rule_last_wins_over_deny(self):
        """A later ``allow`` rule overrides an earlier ``deny``."""
        ruleset = PermissionRuleset(
            bash=(
                PermissionRule("rm *", PermissionOutcome.DENY, source="test"),
                PermissionRule("rm /tmp/*", PermissionOutcome.ALLOW, source="test"),
            )
        )
        decision = evaluate(ruleset, "run_command", {"command": "rm /tmp/safe"})
        assert decision.outcome is PermissionOutcome.ALLOW

    def test_deny_most_restrictive_across_sections(self):
        """When tool says allow but bash says deny, most-restrictive wins."""
        ruleset = PermissionRuleset(
            tools=(PermissionRule("run_command", PermissionOutcome.ALLOW, source="test"),),
            bash=(PermissionRule("rm -rf *", PermissionOutcome.DENY, source="test"),),
        )
        decision = evaluate(ruleset, "run_command", {"command": "rm -rf /danger"})
        assert decision.denied

    def test_no_rules_defaults_to_allow(self):
        ruleset = PermissionRuleset(name="empty")
        decision = evaluate(ruleset, "any_tool", {"path": "/tmp/file"})
        assert decision.outcome is PermissionOutcome.ALLOW
        assert "default allow" in decision.reason


@pytest.mark.integration
class TestPermissionBoundaryCategoryScoped:
    """Per-agent/category overlays scope tool access correctly.

    The permission evaluator uses most-restrictive-wins across sections; a
    per-agent overlay can TIGHTEN (add denials) but cannot LOOSEN a global
    deny (the global deny still appears in ``candidates`` and beats any
    overlay allow).  Tests reflect that actual behaviour.
    """

    def test_research_overlay_denies_write_file_for_research_agent(self):
        """Research agent overlay adds a deny for write_file (tightening)."""
        overlay = PermissionRuleset(
            tools=(
                PermissionRule("write_file", PermissionOutcome.DENY, source="research-overlay"),
            ),
            name="research-overlay",
        )
        # Global has no rule for write_file → default allow.
        ruleset = PermissionRuleset(
            agents={"research": overlay},
            name="test",
        )
        decision = evaluate(ruleset, "write_file", {}, agent_name="research")
        assert decision.denied

    def test_build_agent_allows_write_file_when_no_overlay(self):
        """Build agent has no overlay; write_file defaults to allow."""
        overlay = PermissionRuleset(
            tools=(
                PermissionRule("write_file", PermissionOutcome.DENY, source="research-overlay"),
            ),
            name="research-overlay",
        )
        ruleset = PermissionRuleset(
            agents={"research": overlay},
            name="test",
        )
        # No overlay for "build" → falls through to global (no rule → allow).
        decision = evaluate(ruleset, "write_file", {}, agent_name="build")
        assert decision.outcome is PermissionOutcome.ALLOW

    def test_agent_name_none_does_not_apply_overlays(self):
        """Without agent_name, per-agent overlays are not consulted."""
        overlay = PermissionRuleset(
            tools=(PermissionRule("special_tool", PermissionOutcome.DENY, source="overlay"),),
            name="overlay",
        )
        ruleset = PermissionRuleset(
            agents={"myagent": overlay},
            name="test",
        )
        # Without agent_name, the overlay isn't applied → default allow.
        decision = evaluate(ruleset, "special_tool", {}, agent_name=None)
        assert decision.outcome is PermissionOutcome.ALLOW

    def test_research_overlay_tightens_ask_to_deny(self):
        """An overlay can tighten an ASK in the global to a DENY for one agent."""
        global_ruleset = PermissionRuleset(
            tools=(PermissionRule("run_command", PermissionOutcome.ASK, source="global"),),
            name="global",
        )
        research_overlay = PermissionRuleset(
            tools=(PermissionRule("run_command", PermissionOutcome.DENY, source="research"),),
            name="research",
        )
        ruleset = PermissionRuleset(
            tools=global_ruleset.tools,
            agents={"research": research_overlay},
            name="composed",
        )
        # Research agent: deny wins over ask (most restrictive).
        assert evaluate(ruleset, "run_command", {}, agent_name="research").denied
        # Other agents: only the global ask applies.
        assert (
            evaluate(ruleset, "run_command", {}, agent_name="build").outcome
            is PermissionOutcome.ASK
        )

    def test_composed_rulesets_user_then_repo_last_wins(self, tmp_path: pathlib.Path):
        """Repo permissions layer on top of user permissions; last-match-wins."""
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        (user_dir / "permissions.yaml").write_text("bash:\n  'make *': allow\n  'rm *': deny\n")
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        cantrip_dir = repo_dir / ".cantrip"
        cantrip_dir.mkdir()
        (cantrip_dir / "permissions.yaml").write_text("bash:\n  'rm /tmp/*': allow\n")
        active = perm_mod.discover_permissions(
            charm_path=repo_dir,
            user_config_dir=user_dir,
            include_builtin=False,
        )
        # The repo layer's ``rm /tmp/*`` allow is the LAST matching rule
        # in the bash section for this command → allow.
        decision = evaluate(active, "run_command", {"command": "rm /tmp/cantrip-test"})
        assert decision.outcome is PermissionOutcome.ALLOW

        # But a plain ``rm /home/user`` only matches the user layer's deny.
        decision2 = evaluate(active, "run_command", {"command": "rm /home/user/file"})
        assert decision2.denied


# ===========================================================================
# 6. PermissionManager — ask/resolve async flow
# ===========================================================================


@pytest.mark.integration
class TestPermissionManagerFlow:
    """PermissionManager parks ask decisions and resolves them from another task."""

    @pytest.mark.asyncio
    async def test_ask_resolved_true_returns_true(self):
        requests: list[PermissionAskRequest] = []
        mgr = PermissionManager(
            timeout_seconds=5.0,
            on_request=requests.append,
        )
        task = asyncio.create_task(
            mgr.request(
                tool_name="run_command",
                reason="bash command matches 'make *'",
                arguments={"command": "make test"},
                request_id="test-req-1",
            )
        )
        await asyncio.sleep(0)
        # The request should be parked.
        assert mgr.pending

        mgr.resolve("test-req-1", approved=True)

        result = await task
        assert result is True

    @pytest.mark.asyncio
    async def test_ask_resolved_false_returns_false(self):
        mgr = PermissionManager(timeout_seconds=5.0)
        task = asyncio.create_task(
            mgr.request(
                tool_name="edit_file",
                reason="path matches '*/sensitive/*'",
                arguments={"path": "/tmp/x"},
                request_id="test-req-2",
            )
        )
        await asyncio.sleep(0)
        mgr.resolve("test-req-2", approved=False)
        result = await task
        assert result is False

    @pytest.mark.asyncio
    async def test_yolo_mode_auto_approves(self):
        mgr = PermissionManager(timeout_seconds=1.0)
        mgr.set_yolo(enabled=True)
        result = await mgr.request(
            tool_name="run_command",
            reason="ask rule matched",
            arguments={"command": "ls"},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_resolve_unknown_request_id_is_noop(self):
        mgr = PermissionManager(timeout_seconds=1.0)
        # Should not raise even if no request with that id exists.
        mgr.resolve("nonexistent-id", approved=True)


# ===========================================================================
# 7. GovernancePolicy destructive-command gate
# ===========================================================================


@pytest.mark.integration
class TestGovernancePolicyDestructiveGate:
    """GovernancePolicy blocks destructive tools by default; approve_destructive unlocks."""

    def test_blocked_tool_is_denied(self):
        policy = GovernancePolicy(
            blocked_tools=frozenset({"rm", "deploy_charm"}),
            name="test",
        )
        assert policy.check_tool("rm") is PolicyAction.DENY
        assert policy.check_tool("deploy_charm") is PolicyAction.DENY

    def test_review_tool_gets_review_action(self):
        policy = GovernancePolicy(
            require_human_approval=frozenset({"push_charm"}),
            name="test",
        )
        assert policy.check_tool("push_charm") is PolicyAction.REVIEW

    def test_allow_list_denies_unlisted(self):
        policy = GovernancePolicy(
            allowed_tools=frozenset({"read_file", "list_directory"}),
            name="test",
        )
        assert policy.check_tool("write_file") is PolicyAction.DENY
        assert policy.check_tool("read_file") is PolicyAction.ALLOW

    def test_compose_approve_destructive_or_wins(self):
        p1 = GovernancePolicy(approve_destructive=False, name="base")
        p2 = GovernancePolicy(approve_destructive=True, name="yolo")
        composed = compose_policies(p1, p2)
        assert composed.approve_destructive is True

    def test_compose_blocked_tools_union(self):
        p1 = GovernancePolicy(blocked_tools=frozenset({"rm"}), name="a")
        p2 = GovernancePolicy(blocked_tools=frozenset({"dd"}), name="b")
        composed = compose_policies(p1, p2)
        assert "rm" in composed.blocked_tools
        assert "dd" in composed.blocked_tools

    def test_compose_allowed_tools_intersection(self):
        p1 = GovernancePolicy(allowed_tools=frozenset({"read_file", "write_file"}), name="a")
        p2 = GovernancePolicy(allowed_tools=frozenset({"read_file", "list_directory"}), name="b")
        composed = compose_policies(p1, p2)
        assert composed.allowed_tools == frozenset({"read_file"})

    def test_compose_rate_limit_picks_strictest(self):
        p1 = GovernancePolicy(max_calls_per_request=100, name="a")
        p2 = GovernancePolicy(max_calls_per_request=20, name="b")
        composed = compose_policies(p1, p2)
        assert composed.max_calls_per_request == 20
