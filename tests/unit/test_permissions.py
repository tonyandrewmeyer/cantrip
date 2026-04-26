"""Tests for declarative permission config (Phase 68.2)."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from cantrip.agent.permissions import (
    BUILTIN_PERMISSIONS,
    DEFAULT_BASH_TOOLS,
    PERMISSION_CONFIRM_PREFIX,
    PermissionAskRequest,
    PermissionDecision,
    PermissionManager,
    PermissionOutcome,
    PermissionParseError,
    PermissionRule,
    PermissionRuleset,
    compose_rulesets,
    discover_permissions,
    evaluate,
    load_permissions_file,
    ruleset_from_dict,
)

# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


class TestPermissionRule:
    """Direct glob-match behaviour on a single rule."""

    def test_matches_glob(self):
        rule = PermissionRule("git push*", PermissionOutcome.ASK)
        assert rule.matches("git push origin main")
        assert not rule.matches("git pull origin main")

    def test_case_sensitive(self):
        rule = PermissionRule("Rm *", PermissionOutcome.DENY)
        assert not rule.matches("rm -rf /tmp")
        assert rule.matches("Rm foo")


# ---------------------------------------------------------------------------
# evaluate() — the decision function
# ---------------------------------------------------------------------------


class TestEvaluate:
    """Per-call decision with last-match-wins and most-restrictive-wins."""

    def test_empty_ruleset_defaults_to_allow(self):
        decision = evaluate(PermissionRuleset(), "fs_read", {"path": "README.md"})
        assert decision.outcome is PermissionOutcome.ALLOW
        assert decision.matched_rule is None

    def test_tool_section_match(self):
        ruleset = PermissionRuleset(
            tools=(
                PermissionRule("fs_*", PermissionOutcome.ALLOW),
                PermissionRule("fs_write", PermissionOutcome.DENY),
            )
        )
        # Last-match-wins within the section: ``fs_write`` hit is later.
        assert evaluate(ruleset, "fs_write").outcome is PermissionOutcome.DENY
        # ``fs_read`` only hits the wildcard; stays ALLOW.
        assert evaluate(ruleset, "fs_read").outcome is PermissionOutcome.ALLOW

    def test_last_match_wins_within_section(self):
        ruleset = PermissionRuleset(
            bash=(
                PermissionRule("*", PermissionOutcome.ASK),
                PermissionRule("git *", PermissionOutcome.ALLOW),
                PermissionRule("rm *", PermissionOutcome.DENY),
            )
        )
        # ``git status`` matches wildcard *and* ``git *``; the later one wins.
        assert (
            evaluate(ruleset, "run_command", {"command": "git status"}).outcome
            is PermissionOutcome.ALLOW
        )
        assert (
            evaluate(ruleset, "run_command", {"command": "rm -rf /tmp"}).outcome
            is PermissionOutcome.DENY
        )
        # ``ls`` only matches the wildcard, so it's ASK.
        assert evaluate(ruleset, "run_command", {"command": "ls"}).outcome is PermissionOutcome.ASK

    def test_bash_argv_list_joins_to_string(self):
        """An argv list is shell-joined before matching."""
        ruleset = PermissionRuleset(bash=(PermissionRule("rm -rf *", PermissionOutcome.DENY),))
        decision = evaluate(ruleset, "run_command", {"argv": ["rm", "-rf", "/tmp/foo"]})
        assert decision.outcome is PermissionOutcome.DENY

    def test_paths_section_match(self):
        ruleset = PermissionRuleset(
            paths=(
                PermissionRule("*", PermissionOutcome.ALLOW),
                PermissionRule("*.env", PermissionOutcome.DENY),
            )
        )
        assert (
            evaluate(ruleset, "fs_read", {"path": "src/main.py"}).outcome
            is PermissionOutcome.ALLOW
        )
        assert (
            evaluate(ruleset, "fs_read", {"path": "config.env"}).outcome is PermissionOutcome.DENY
        )

    def test_most_restrictive_wins_across_sections(self):
        """Cross-section disagreement resolves deny > ask > allow."""
        ruleset = PermissionRuleset(
            tools=(PermissionRule("run_command", PermissionOutcome.ALLOW),),
            bash=(PermissionRule("rm *", PermissionOutcome.DENY),),
        )
        decision = evaluate(ruleset, "run_command", {"command": "rm -rf /tmp"})
        assert decision.outcome is PermissionOutcome.DENY

    def test_per_agent_override_tightens(self):
        """Per-agent rules evaluated after global ones."""
        agent_overlay = PermissionRuleset(
            tools=(PermissionRule("fs_write", PermissionOutcome.DENY),)
        )
        ruleset = PermissionRuleset(
            tools=(PermissionRule("fs_*", PermissionOutcome.ALLOW),),
            agents={"research": agent_overlay},
        )
        # With no agent: tools-allow wins.
        assert evaluate(ruleset, "fs_write").outcome is PermissionOutcome.ALLOW
        # research overlay tightens to DENY.
        assert (
            evaluate(ruleset, "fs_write", agent_name="research").outcome is PermissionOutcome.DENY
        )

    def test_per_agent_override_loosens(self):
        agent_overlay = PermissionRuleset(bash=(PermissionRule("*", PermissionOutcome.ALLOW),))
        ruleset = PermissionRuleset(
            bash=(PermissionRule("*", PermissionOutcome.ASK),),
            agents={"build": agent_overlay},
        )
        # Without agent — ask.
        assert evaluate(ruleset, "run_command", {"command": "ls"}).outcome is PermissionOutcome.ASK
        # With build agent — the overlay rule is evaluated too.  Both
        # sections match; most-restrictive (ASK) still wins because
        # the cross-section rule picks the stricter outcome.
        decision = evaluate(ruleset, "run_command", {"command": "ls"}, agent_name="build")
        assert decision.outcome is PermissionOutcome.ASK

    def test_reason_names_rule_and_source(self):
        ruleset = PermissionRuleset(
            bash=(PermissionRule("rm *", PermissionOutcome.DENY, source="repo:bash"),)
        )
        decision = evaluate(ruleset, "run_command", {"command": "rm -rf /tmp"})
        assert "rm *" in decision.reason
        assert "deny" in decision.reason
        assert "repo:bash" in decision.reason


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


class TestYAMLLoader:
    """Parse ``permissions.yaml`` files into rulesets."""

    def test_simple_round_trip(self, tmp_path: Path):
        path = tmp_path / "permissions.yaml"
        path.write_text(
            textwrap.dedent(
                """\
                tools:
                  "fs_read": "allow"
                  "fs_write": "ask"
                bash:
                  "rm *": "deny"
                """
            )
        )
        ruleset = load_permissions_file(path)
        assert evaluate(ruleset, "fs_read").outcome is PermissionOutcome.ALLOW
        assert evaluate(ruleset, "fs_write").outcome is PermissionOutcome.ASK
        assert (
            evaluate(ruleset, "run_command", {"command": "rm -rf /tmp"}).outcome
            is PermissionOutcome.DENY
        )

    def test_per_agent_block(self, tmp_path: Path):
        path = tmp_path / "permissions.yaml"
        path.write_text(
            textwrap.dedent(
                """\
                tools:
                  "fs_write": "allow"
                agents:
                  research:
                    tools:
                      "fs_write": "deny"
                """
            )
        )
        ruleset = load_permissions_file(path)
        assert (
            evaluate(ruleset, "fs_write", agent_name="research").outcome is PermissionOutcome.DENY
        )
        assert evaluate(ruleset, "fs_write", agent_name="build").outcome is PermissionOutcome.ALLOW

    def test_unknown_top_level_key_raises(self, tmp_path: Path):
        path = tmp_path / "permissions.yaml"
        path.write_text("unexpected_key:\n  foo: bar\n")
        with pytest.raises(PermissionParseError):
            load_permissions_file(path)

    def test_unknown_outcome_raises(self, tmp_path: Path):
        path = tmp_path / "permissions.yaml"
        path.write_text('tools:\n  "fs_read": "maybe"\n')
        with pytest.raises(PermissionParseError):
            load_permissions_file(path)

    def test_empty_file_yields_empty_ruleset(self, tmp_path: Path):
        path = tmp_path / "permissions.yaml"
        path.write_text("")
        ruleset = load_permissions_file(path)
        assert ruleset.tools == ()
        assert ruleset.bash == ()
        assert ruleset.paths == ()

    def test_inline_dict_parses(self):
        ruleset = ruleset_from_dict(
            {"bash_tools": ["run_command", "shell"]},
            source="inline",
        )
        assert "run_command" in ruleset.bash_tools
        assert "shell" in ruleset.bash_tools


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class TestComposition:
    """``compose_rulesets`` concatenates layers, last wins."""

    def test_repo_overrides_user(self):
        user_rs = PermissionRuleset(
            tools=(PermissionRule("fs_*", PermissionOutcome.ASK),),
            name="user",
        )
        repo_rs = PermissionRuleset(
            tools=(PermissionRule("fs_read", PermissionOutcome.ALLOW),),
            name="repo",
        )
        composed = compose_rulesets(user_rs, repo_rs)
        # fs_read matches both; repo rule is later, so ALLOW wins.
        assert evaluate(composed, "fs_read").outcome is PermissionOutcome.ALLOW
        # fs_write only matches the user rule.
        assert evaluate(composed, "fs_write").outcome is PermissionOutcome.ASK

    def test_empty_returns_empty(self):
        assert compose_rulesets().tools == ()
        assert compose_rulesets().name == "empty"

    def test_single_layer_returns_itself(self):
        rs = PermissionRuleset(name="only")
        assert compose_rulesets(rs) is rs

    def test_agent_overlays_compose(self):
        user_rs = PermissionRuleset(
            agents={
                "build": PermissionRuleset(tools=(PermissionRule("x", PermissionOutcome.ASK),)),
            },
            name="user",
        )
        repo_rs = PermissionRuleset(
            agents={
                "build": PermissionRuleset(tools=(PermissionRule("x", PermissionOutcome.DENY),)),
            },
            name="repo",
        )
        composed = compose_rulesets(user_rs, repo_rs)
        # Both agent overlays compose; the later DENY wins.
        assert evaluate(composed, "x", agent_name="build").outcome is PermissionOutcome.DENY


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    """``discover_permissions`` walks the canonical paths."""

    def test_builtin_defaults_deny_rm_rf(self):
        # The built-in ruleset *alone* denies ``rm -rf *`` per roadmap.
        assert (
            evaluate(BUILTIN_PERMISSIONS, "run_command", {"command": "rm -rf /tmp/foo"}).outcome
            is PermissionOutcome.DENY
        )

    def test_builtin_defaults_ask_git_push(self):
        assert (
            evaluate(
                BUILTIN_PERMISSIONS, "run_command", {"command": "git push origin main"}
            ).outcome
            is PermissionOutcome.ASK
        )

    def test_builtin_defaults_deny_env_read(self):
        assert (
            evaluate(BUILTIN_PERMISSIONS, "fs_read", {"path": "secrets/.env"}).outcome
            is PermissionOutcome.DENY
        )
        assert (
            evaluate(BUILTIN_PERMISSIONS, "fs_read", {"path": ".env"}).outcome
            is PermissionOutcome.DENY
        )

    def test_repo_wins_over_user(self, tmp_path: Path):
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        user_file = user_dir / "permissions.yaml"
        user_file.write_text('tools:\n  "fs_read": "ask"\n')

        repo_dir = tmp_path / "repo"
        cantrip_dir = repo_dir / ".cantrip"
        cantrip_dir.mkdir(parents=True)
        repo_file = cantrip_dir / "permissions.yaml"
        repo_file.write_text('tools:\n  "fs_read": "allow"\n')

        ruleset = discover_permissions(
            charm_path=repo_dir,
            user_config_dir=user_dir,
            include_builtin=False,
        )
        assert evaluate(ruleset, "fs_read").outcome is PermissionOutcome.ALLOW

    def test_missing_files_yield_empty(self, tmp_path: Path):
        ruleset = discover_permissions(
            charm_path=tmp_path,
            user_config_dir=tmp_path / "does-not-exist",
            include_builtin=False,
        )
        assert ruleset.tools == ()
        assert ruleset.bash == ()

    def test_malformed_user_file_is_skipped(self, tmp_path: Path):
        user_dir = tmp_path
        (user_dir / "permissions.yaml").write_text('tools:\n  "fs": "wibble"\n')
        # No raise — malformed file is logged + skipped.
        ruleset = discover_permissions(user_config_dir=user_dir, include_builtin=False)
        assert ruleset.tools == ()


# ---------------------------------------------------------------------------
# Permission manager (async ask/resolve)
# ---------------------------------------------------------------------------


class TestPermissionManager:
    """Park decisions on futures, resolve from the conversation layer."""

    @pytest.mark.asyncio
    async def test_approve_resolves_to_true(self):
        manager = PermissionManager(timeout_seconds=5.0)
        received: list[PermissionAskRequest] = []
        manager.set_on_request(received.append)

        async def approve_soon() -> None:
            # Let the manager register the request first.
            await asyncio.sleep(0)
            manager.resolve(received[0].request_id, approved=True)

        task = asyncio.create_task(approve_soon())
        approved = await manager.request(tool_name="run_command", reason="needs approval")
        await task

        assert approved is True
        assert received[0].tool_name == "run_command"
        assert received[0].task_id.startswith(PERMISSION_CONFIRM_PREFIX)
        # Future is cleaned up after resolution.
        assert manager.pending == []

    @pytest.mark.asyncio
    async def test_deny_resolves_to_false(self):
        manager = PermissionManager(timeout_seconds=5.0)
        rid = "fixed-id"

        async def deny_soon() -> None:
            await asyncio.sleep(0)
            manager.resolve(rid, approved=False)

        task = asyncio.create_task(deny_soon())
        approved = await manager.request(tool_name="run_command", reason="x", request_id=rid)
        await task
        assert approved is False

    @pytest.mark.asyncio
    async def test_timeout_auto_denies(self):
        manager = PermissionManager(timeout_seconds=0.05)
        approved = await manager.request(tool_name="x", reason="y")
        assert approved is False
        assert manager.pending == []

    @pytest.mark.asyncio
    async def test_resolve_missing_id_returns_false(self):
        manager = PermissionManager()
        assert manager.resolve("nope", approved=True) is False

    @pytest.mark.asyncio
    async def test_cancel_all_denies_every_pending(self):
        manager = PermissionManager(timeout_seconds=5.0)

        async def make_request(rid: str) -> bool:
            return await manager.request(tool_name="x", reason="y", request_id=rid)

        t1 = asyncio.create_task(make_request("a"))
        t2 = asyncio.create_task(make_request("b"))
        await asyncio.sleep(0)  # let tasks register
        manager.cancel_all()
        results = await asyncio.gather(t1, t2)
        assert results == [False, False]
        assert manager.pending == []


# ---------------------------------------------------------------------------
# Subagent integration smoke test
# ---------------------------------------------------------------------------


class TestSubagentGate:
    """Minimal check that the gate integrates with ``_apply_permission_gate``.

    The Subagent test suite exercises the full dispatch loop; here we
    just confirm a DENY decision short-circuits to a refused result
    without the subagent needing a real provider.
    """

    @pytest.mark.asyncio
    async def test_deny_returns_refused_tool_result(self):
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import Subagent, SubagentContext
        from tests.conftest import FakeProvider

        task = AgentTask(title="t", category=TaskCategory.RESEARCH)
        ctx = SubagentContext(task=task)
        ruleset = PermissionRuleset(tools=(PermissionRule("fs_read", PermissionOutcome.DENY),))
        subagent = Subagent(
            context=ctx,
            tools=[],
            provider=FakeProvider(),
            permissions=ruleset,
        )
        decision = PermissionDecision(
            outcome=PermissionOutcome.DENY,
            reason="tool name matches 'fs_read'",
            matched_rule=ruleset.tools[0],
        )
        result = await subagent._apply_permission_gate("fs_read", {"path": "x"}, decision)
        assert result is not None
        assert result.success is False
        assert "Refused by permissions policy" in (result.error or "")

    @pytest.mark.asyncio
    async def test_allow_returns_none(self):
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import Subagent, SubagentContext
        from tests.conftest import FakeProvider

        task = AgentTask(title="t", category=TaskCategory.RESEARCH)
        ctx = SubagentContext(task=task)
        subagent = Subagent(
            context=ctx,
            tools=[],
            provider=FakeProvider(),
        )
        # No decision at all means "prior gate already acted" — the
        # gate helper passes through to let the caller proceed.
        assert await subagent._apply_permission_gate("fs_read", {}, None) is None
        allow_decision = PermissionDecision(
            outcome=PermissionOutcome.ALLOW, reason="default allow"
        )
        assert await subagent._apply_permission_gate("fs_read", {}, allow_decision) is None

    @pytest.mark.asyncio
    async def test_ask_routes_through_manager(self):
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import Subagent, SubagentContext
        from tests.conftest import FakeProvider

        task = AgentTask(title="t", category=TaskCategory.BUILD)
        ctx = SubagentContext(task=task)
        manager = PermissionManager(timeout_seconds=5.0)
        rule = PermissionRule("git push*", PermissionOutcome.ASK, source="test:bash")
        ruleset = PermissionRuleset(bash=(rule,))
        subagent = Subagent(
            context=ctx,
            tools=[],
            provider=FakeProvider(),
            permissions=ruleset,
            permission_manager=manager,
        )
        decision = PermissionDecision(
            outcome=PermissionOutcome.ASK,
            reason="git push*",
            matched_rule=rule,
        )

        async def approve_when_parked() -> None:
            # Wait until the manager sees the request, then approve it.
            while not manager.pending:
                await asyncio.sleep(0)
            manager.resolve(manager.pending[0], approved=True)

        approve_task = asyncio.create_task(approve_when_parked())
        result = await subagent._apply_permission_gate(
            "run_command", {"command": "git push origin main"}, decision
        )
        await approve_task
        assert result is None  # approved → caller proceeds

    @pytest.mark.asyncio
    async def test_ask_without_manager_degrades_to_deny(self):
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import Subagent, SubagentContext
        from tests.conftest import FakeProvider

        task = AgentTask(title="t", category=TaskCategory.BUILD)
        ctx = SubagentContext(task=task)
        rule = PermissionRule("sudo *", PermissionOutcome.ASK, source="test:bash")
        ruleset = PermissionRuleset(bash=(rule,))
        subagent = Subagent(
            context=ctx,
            tools=[],
            provider=FakeProvider(),
            permissions=ruleset,
            permission_manager=None,
        )
        decision = PermissionDecision(
            outcome=PermissionOutcome.ASK, reason="sudo *", matched_rule=rule
        )
        result = await subagent._apply_permission_gate(
            "run_command", {"command": "sudo rm /tmp"}, decision
        )
        assert result is not None
        assert result.success is False
        assert "Permission required" in (result.error or "")


def test_default_bash_tools_is_nonempty():
    """A sanity check — empty bash_tools would silently skip bash matching."""
    assert "run_command" in DEFAULT_BASH_TOOLS


# ---------------------------------------------------------------------------
# `cantrip permissions test` and `cantrip permissions list` CLI subcommands
# (Phase 70 follow-up — Amp parity)
# ---------------------------------------------------------------------------


class TestPermissionsCLI:
    """``cantrip permissions {test,list}`` evaluates and dumps the ruleset."""

    def _args(self, **overrides: object):
        import argparse

        defaults = {
            "tool": None,
            "bash_command": None,
            "path_arg": None,
            "agent_name": None,
            "charm_path": None,
            "user_config_dir": None,
            "no_builtin": False,
            "show_rules": False,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_test_builtin_bash_deny(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """Built-in ``rm -rf *`` rule still fires through the CLI."""
        from cantrip.main import _permissions_test

        args = self._args(
            tool="run_command",
            bash_command="rm -rf /tmp/x",
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_test(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Outcome: DENY" in out
        assert "rm -rf *" in out
        assert "builtin:bash" in out

    def test_test_path_match(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """Path argument matches the ``paths`` section."""
        from cantrip.main import _permissions_test

        args = self._args(
            tool="read_file",
            path_arg=".env",
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_test(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Outcome: DENY" in out
        assert "Path:    .env" in out
        assert "builtin:paths" in out

    def test_test_no_match_default_allow(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """A tool with no matching rule falls through to default allow."""
        from cantrip.main import _permissions_test

        args = self._args(
            tool="juju_status",
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_test(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Outcome: ALLOW" in out
        assert "no rule matched" in out

    def test_test_repo_yaml_rule_attribution(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """A repo-level rule wins last and shows up by file path."""
        from cantrip.main import _permissions_test

        repo_yaml = tmp_path / ".cantrip" / "permissions.yaml"
        repo_yaml.parent.mkdir()
        repo_yaml.write_text(
            textwrap.dedent(
                """
                tools:
                  juju_destroy_model: ask
                """
            ).strip()
        )
        args = self._args(
            tool="juju_destroy_model",
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_test(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Outcome: ASK" in out
        assert str(repo_yaml) in out

    def test_test_agent_overlay_tightens(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """``--agent`` activates the per-agent overlay; cross-section deny wins."""
        from cantrip.main import _permissions_test

        repo_yaml = tmp_path / ".cantrip" / "permissions.yaml"
        repo_yaml.parent.mkdir()
        repo_yaml.write_text(
            textwrap.dedent(
                """
                tools:
                  charmhub_search: allow
                agents:
                  RESEARCH:
                    tools:
                      charmhub_search: deny
                """
            ).strip()
        )
        # Without the overlay, only the global allow rule applies.
        bare = self._args(
            tool="charmhub_search",
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_test(bare)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Outcome: ALLOW" in out

        # With ``--agent RESEARCH`` the overlay deny wins under most-restrictive.
        with_overlay = self._args(
            tool="charmhub_search",
            agent_name="RESEARCH",
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_test(with_overlay)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Outcome: DENY" in out
        assert "Agent:   RESEARCH" in out
        assert "agents:RESEARCH" in out

    def test_test_show_rules_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """``--show-rules`` appends the loaded ruleset listing."""
        from cantrip.main import _permissions_test

        args = self._args(
            tool="juju_status",
            show_rules=True,
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_test(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Outcome: ALLOW" in out
        assert "Loaded ruleset:" in out
        assert "[bash]" in out  # built-in bash rules are always present

    def test_test_no_builtin_skips_safe_defaults(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """``--no-builtin`` lets ``rm -rf`` fall through when no user rule covers it."""
        from cantrip.main import _permissions_test

        args = self._args(
            tool="run_command",
            bash_command="rm -rf /tmp/x",
            no_builtin=True,
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_test(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Outcome: ALLOW" in out
        assert "no rule matched" in out

    def test_list_with_no_files_shows_builtin(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """``permissions list`` with no user/repo files prints the built-in rules."""
        from cantrip.main import _permissions_list

        args = self._args(
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Loaded ruleset: builtin" in out
        assert "rm -rf *" in out
        assert "builtin:paths" in out

    def test_list_no_builtin_with_no_files_says_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """With ``--no-builtin`` and no files, the listing is empty."""
        from cantrip.main import _permissions_list

        args = self._args(
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
            no_builtin=True,
        )
        rc = _permissions_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No permission rules loaded." in out

    def test_list_includes_per_agent_overlay(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """A repo file with ``agents:`` shows up under an ``[agents:NAME]`` group."""
        from cantrip.main import _permissions_list

        repo_yaml = tmp_path / ".cantrip" / "permissions.yaml"
        repo_yaml.parent.mkdir()
        repo_yaml.write_text(
            textwrap.dedent(
                """
                agents:
                  RESEARCH:
                    tools:
                      web_fetch: allow
                """
            ).strip()
        )
        args = self._args(
            charm_path=tmp_path,
            user_config_dir=tmp_path / "no-such-dir",
        )
        rc = _permissions_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "[agents:RESEARCH]" in out
        assert "web_fetch" in out
