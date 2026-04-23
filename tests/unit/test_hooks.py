"""Tests for the user-configurable hooks subsystem (Phase 46.1 + 46.2 + 46.3)."""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from cantrip.hooks import (
    DEFAULT_HOOK_TIMEOUT,
    REPO_CONFIG_FILENAME,
    HookConfig,
    HookConfigError,
    HookEvent,
    HookResult,
    HookRunner,
    _FilterExpr,
    _parse_yaml,
    first_veto,
    load_hooks,
)

# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


class TestParseYaml:
    """Tests for the low-level YAML parser."""

    def test_empty_file_returns_no_hooks(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("")
        assert _parse_yaml(path) == []

    def test_file_without_hooks_key(self, tmp_path: pathlib.Path):
        """A YAML document with no ``hooks`` key is a no-op, not an error."""
        path = tmp_path / "hooks.yaml"
        path.write_text("servers: {}\n")
        assert _parse_yaml(path) == []

    def test_top_level_must_be_mapping(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("- just\n- a\n- list\n")
        with pytest.raises(HookConfigError, match="must be a mapping"):
            _parse_yaml(path)

    def test_hooks_must_be_a_list(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  not-a: list\n")
        with pytest.raises(HookConfigError, match="must be a list"):
            _parse_yaml(path)

    def test_unknown_event_rejected(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  - event: maybe_tool_call\n    run: echo\n")
        with pytest.raises(HookConfigError, match="unknown event"):
            _parse_yaml(path)

    def test_missing_run_rejected(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  - event: pre_tool_call\n")
        with pytest.raises(HookConfigError, match="`run`"):
            _parse_yaml(path)

    def test_bad_timeout_type_rejected(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  - event: pre_tool_call\n    run: echo\n    timeout: nope\n")
        with pytest.raises(HookConfigError, match="must be a number"):
            _parse_yaml(path)

    def test_negative_timeout_rejected(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  - event: pre_tool_call\n    run: echo\n    timeout: -1\n")
        with pytest.raises(HookConfigError, match="must be positive"):
            _parse_yaml(path)

    def test_bad_continue_on_error_type_rejected(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text(
            "hooks:\n  - event: pre_tool_call\n    run: echo\n    continue_on_error: yes-please\n"
        )
        with pytest.raises(HookConfigError, match="true or false"):
            _parse_yaml(path)

    def test_name_defaults_to_first_word_of_run(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  - event: pre_tool_call\n    run: jq -r .tool\n")
        [hook] = _parse_yaml(path)
        assert hook.name == "jq"

    def test_explicit_name_honoured(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  - name: my-hook\n    event: pre_tool_call\n    run: echo\n")
        [hook] = _parse_yaml(path)
        assert hook.name == "my-hook"

    def test_default_timeout_is_used_when_omitted(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  - event: pre_tool_call\n    run: echo\n")
        [hook] = _parse_yaml(path)
        assert hook.timeout == DEFAULT_HOOK_TIMEOUT
        # continue_on_error default is True — matches the docstring.
        assert hook.continue_on_error is True

    def test_parses_all_known_events(self, tmp_path: pathlib.Path):
        """Every ``HookEvent`` value is accepted by the parser."""
        hooks_yaml = "hooks:\n" + "".join(
            f"  - event: {e.value}\n    run: echo {e.value}\n    name: {e.value}\n"
            for e in HookEvent
        )
        path = tmp_path / "hooks.yaml"
        path.write_text(hooks_yaml)
        parsed = _parse_yaml(path)
        assert {h.event for h in parsed} == set(HookEvent)


# ---------------------------------------------------------------------------
# Config discovery / merging
# ---------------------------------------------------------------------------


class TestLoadHooks:
    """Tests for ``load_hooks`` user + repo scope merging."""

    def test_returns_empty_when_no_configs(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Missing files yield an empty list — not an error."""
        monkeypatch.setenv("CANTRIP_HOOKS_USER_CONFIG", str(tmp_path / "nonexistent.yaml"))
        assert load_hooks(repo_root=tmp_path) == []

    def test_repo_overrides_user_on_name_collision(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """When both scopes define a hook with the same name, repo wins."""
        user_cfg = tmp_path / "user.yaml"
        user_cfg.write_text(
            "hooks:\n  - name: shared\n    event: pre_tool_call\n    run: echo user-scope\n"
        )
        repo_cfg = tmp_path / REPO_CONFIG_FILENAME
        repo_cfg.write_text(
            "hooks:\n  - name: shared\n    event: post_tool_call\n    run: echo repo-scope\n"
        )
        monkeypatch.setenv("CANTRIP_HOOKS_USER_CONFIG", str(user_cfg))

        hooks = load_hooks(repo_root=tmp_path)
        [shared] = hooks
        assert shared.run == "echo repo-scope"
        assert shared.event is HookEvent.POST_TOOL_CALL

    def test_user_and_repo_hooks_both_included(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Different-named hooks from both scopes contribute to the result."""
        user_cfg = tmp_path / "user.yaml"
        user_cfg.write_text(
            "hooks:\n  - name: user-only\n    event: pre_tool_call\n    run: echo\n"
        )
        repo_cfg = tmp_path / REPO_CONFIG_FILENAME
        repo_cfg.write_text(
            "hooks:\n  - name: repo-only\n    event: post_tool_call\n    run: echo\n"
        )
        monkeypatch.setenv("CANTRIP_HOOKS_USER_CONFIG", str(user_cfg))

        names = {h.name for h in load_hooks(repo_root=tmp_path)}
        assert names == {"user-only", "repo-only"}

    def test_malformed_yaml_logs_warning_and_returns_others(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """A broken user config doesn't take out the repo config (or the agent)."""
        import logging

        user_cfg = tmp_path / "user.yaml"
        # Syntactically malformed YAML.
        user_cfg.write_text("hooks:\n  - [missing colon\n")
        repo_cfg = tmp_path / REPO_CONFIG_FILENAME
        repo_cfg.write_text(
            "hooks:\n  - name: survivor\n    event: pre_tool_call\n    run: echo\n"
        )
        monkeypatch.setenv("CANTRIP_HOOKS_USER_CONFIG", str(user_cfg))

        with caplog.at_level(logging.WARNING, logger="cantrip.hooks"):
            hooks = load_hooks(repo_root=tmp_path)

        assert {h.name for h in hooks} == {"survivor"}
        assert any("malformed" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# HookRunner execution
# ---------------------------------------------------------------------------


class TestHookRunner:
    """Tests for ``HookRunner.fire`` — the event dispatch path."""

    @pytest.mark.asyncio
    async def test_fire_on_empty_runner_is_noop(self):
        results = await HookRunner().fire(HookEvent.PRE_TOOL_CALL, {})
        assert results == []

    @pytest.mark.asyncio
    async def test_fire_runs_matching_hooks_with_json_payload(self, tmp_path: pathlib.Path):
        """The hook receives the payload as JSON on stdin and echoes it out."""
        out = tmp_path / "captured.json"
        hook = HookConfig(
            name="capture",
            event=HookEvent.PRE_TOOL_CALL,
            run=f"cat > {out}",
            timeout=10,
        )
        runner = HookRunner([hook])

        [result] = await runner.fire(
            HookEvent.PRE_TOOL_CALL, {"tool": "juju_status", "arguments": {}}
        )
        assert result.exit_code == 0
        assert result.timed_out is False

        payload = json.loads(out.read_text())
        assert payload["tool"] == "juju_status"
        assert payload["event"] == "pre_tool_call"
        # Timestamp is added automatically so hooks can tell invocations apart.
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_non_matching_hook_does_not_run(self, tmp_path: pathlib.Path):
        marker = tmp_path / "ran"
        # Only registers for ``post_tool_call``.
        hook = HookConfig(
            name="marker",
            event=HookEvent.POST_TOOL_CALL,
            run=f"touch {marker}",
        )
        runner = HookRunner([hook])

        results = await runner.fire(HookEvent.PRE_TOOL_CALL, {})
        assert results == []
        assert not marker.exists()

    @pytest.mark.asyncio
    async def test_multiple_hooks_same_event_all_fire_sequentially(self, tmp_path: pathlib.Path):
        """Two hooks on the same event both run, in declaration order."""
        log_file = tmp_path / "order.log"
        hook_a = HookConfig(
            name="a",
            event=HookEvent.PRE_COMPACT,
            run=f"echo A >> {log_file}",
        )
        hook_b = HookConfig(
            name="b",
            event=HookEvent.PRE_COMPACT,
            run=f"echo B >> {log_file}",
        )
        runner = HookRunner([hook_a, hook_b])

        results = await runner.fire(HookEvent.PRE_COMPACT, {})
        assert [r.name for r in results] == ["a", "b"]
        assert log_file.read_text() == "A\nB\n"

    @pytest.mark.asyncio
    async def test_timeout_is_enforced(self):
        """A hook that exceeds its timeout is marked ``timed_out`` and killed."""
        hook = HookConfig(
            name="slow",
            event=HookEvent.PRE_TOOL_CALL,
            run="sleep 5",
            timeout=0.3,
        )
        runner = HookRunner([hook])

        [result] = await runner.fire(HookEvent.PRE_TOOL_CALL, {})
        assert result.timed_out is True
        # Exit code will be non-zero (negative when killed by signal).
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_failing_hook_does_not_raise(self):
        """A non-zero exit is reported on the result, not raised."""
        hook = HookConfig(
            name="fail",
            event=HookEvent.PRE_TOOL_CALL,
            run="false",
            timeout=5,
        )
        runner = HookRunner([hook])

        [result] = await runner.fire(HookEvent.PRE_TOOL_CALL, {})
        assert result.exit_code == 1
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_hook_stderr_is_captured(self):
        hook = HookConfig(
            name="complain",
            event=HookEvent.PRE_TOOL_CALL,
            run="echo something-went-wrong >&2; exit 3",
            timeout=5,
        )
        runner = HookRunner([hook])

        [result] = await runner.fire(HookEvent.PRE_TOOL_CALL, {})
        assert result.exit_code == 3
        assert "something-went-wrong" in result.stderr

    def test_hooks_for_returns_only_matching_event(self):
        """``hooks_for`` is a read-only view for diagnostics."""
        hook_a = HookConfig(name="a", event=HookEvent.PRE_TOOL_CALL, run="true")
        hook_b = HookConfig(name="b", event=HookEvent.POST_TOOL_CALL, run="true")
        runner = HookRunner([hook_a, hook_b])

        pre = runner.hooks_for(HookEvent.PRE_TOOL_CALL)
        assert [h.name for h in pre] == ["a"]

        # Mutating the returned list does not affect the runner.
        pre.clear()
        assert runner.hooks_for(HookEvent.PRE_TOOL_CALL) == [hook_a]

    def test_hook_count_sums_all_events(self):
        hooks = [
            HookConfig(name="a", event=HookEvent.PRE_TOOL_CALL, run="true"),
            HookConfig(name="b", event=HookEvent.POST_TOOL_CALL, run="true"),
            HookConfig(name="c", event=HookEvent.PRE_TOOL_CALL, run="true"),
        ]
        assert HookRunner(hooks).hook_count == 3
        assert HookRunner([]).hook_count == 0

    def test_from_disk_builds_runner_from_yaml(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        user_cfg = tmp_path / "user.yaml"
        user_cfg.write_text(
            yaml.safe_dump(
                {
                    "hooks": [
                        {"name": "x", "event": "pre_tool_call", "run": "true"},
                    ]
                }
            )
        )
        monkeypatch.setenv("CANTRIP_HOOKS_USER_CONFIG", str(user_cfg))

        runner = HookRunner.from_disk(repo_root=tmp_path)
        assert runner.hook_count == 1
        assert [h.name for h in runner.hooks_for(HookEvent.PRE_TOOL_CALL)] == ["x"]


# ---------------------------------------------------------------------------
# End-to-end: main agent fires hooks at lifecycle events
# ---------------------------------------------------------------------------


class TestAgentFiresHooks:
    """Phase 46.2: main-agent lifecycle integration."""

    @pytest.mark.asyncio
    async def test_tool_call_fires_pre_and_post_hooks(self, tmp_path: pathlib.Path):
        """Every main-agent tool call fires pre_tool_call + post_tool_call."""
        # Deferred imports keep this test file cheap to collect.
        from unittest.mock import AsyncMock

        from cantrip.agent.core import CantripAgent
        from cantrip.agent.tools.base import ToolResult
        from cantrip.llm.base import Response, ToolCall
        from tests.conftest import FakeProvider

        log_file = tmp_path / "events.log"
        hooks = [
            HookConfig(
                name="pre",
                event=HookEvent.PRE_TOOL_CALL,
                run=f"echo pre >> {log_file}",
            ),
            HookConfig(
                name="post",
                event=HookEvent.POST_TOOL_CALL,
                run=f"echo post >> {log_file}",
            ),
        ]

        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Done."),
            ]
        )
        agent = CantripAgent(provider=provider, hook_runner=HookRunner(hooks))
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="ok"))

        await agent.process_message("Check status")

        assert log_file.read_text() == "pre\npost\n"


# ---------------------------------------------------------------------------
# _FilterExpr — if: expression compiler + evaluator (Phase 46.3)
# ---------------------------------------------------------------------------


class TestFilterExprParsing:
    """Parse-time validation: bad expressions fail with a clear error."""

    def test_syntax_error_rejected(self):
        with pytest.raises(HookConfigError, match="invalid `if:`"):
            _FilterExpr("tool ==")

    def test_function_call_rejected(self):
        with pytest.raises(HookConfigError, match="disallowed"):
            _FilterExpr("print('hi')")

    def test_method_call_rejected(self):
        """Attribute access is allowed; calling that attribute is not."""
        with pytest.raises(HookConfigError, match="disallowed"):
            _FilterExpr("tool.startswith('git_')")

    def test_lambda_rejected(self):
        with pytest.raises(HookConfigError, match="disallowed"):
            _FilterExpr("lambda x: x")

    def test_comprehension_rejected(self):
        with pytest.raises(HookConfigError, match="disallowed"):
            _FilterExpr("[x for x in [1,2]]")

    def test_augmented_assignment_rejected(self):
        """Statements (not expressions) fail at the ``ast.parse`` step."""
        with pytest.raises(HookConfigError, match="invalid `if:`"):
            _FilterExpr("x = 1")


class TestFilterExprEvaluation:
    """Runtime: ``matches()`` against real payload shapes."""

    def test_eq_true(self):
        assert _FilterExpr('tool == "git_push"').matches({"tool": "git_push"}) is True

    def test_eq_false(self):
        assert _FilterExpr('tool == "git_push"').matches({"tool": "read_file"}) is False

    def test_neq(self):
        expr = _FilterExpr('tool != "git_push"')
        assert expr.matches({"tool": "read_file"}) is True
        assert expr.matches({"tool": "git_push"}) is False

    def test_and_short_circuits(self):
        expr = _FilterExpr('tool == "git_push" and source == "main"')
        assert expr.matches({"tool": "git_push", "source": "main"}) is True
        assert expr.matches({"tool": "git_push", "source": "subagent"}) is False
        assert expr.matches({"tool": "read_file", "source": "main"}) is False

    def test_or(self):
        expr = _FilterExpr('tool == "git_push" or tool == "git_pull"')
        assert expr.matches({"tool": "git_pull"}) is True
        assert expr.matches({"tool": "juju_status"}) is False

    def test_not(self):
        expr = _FilterExpr('not source == "subagent"')
        assert expr.matches({"source": "main"}) is True
        assert expr.matches({"source": "subagent"}) is False

    def test_in_membership(self):
        expr = _FilterExpr('tool in ["git_push", "git_pull", "git_commit"]')
        assert expr.matches({"tool": "git_push"}) is True
        assert expr.matches({"tool": "juju_status"}) is False

    def test_not_in(self):
        expr = _FilterExpr('tool not in ["read_file", "list_directory"]')
        assert expr.matches({"tool": "git_push"}) is True
        assert expr.matches({"tool": "read_file"}) is False

    def test_substring_via_in(self):
        expr = _FilterExpr('"git" in tool')
        assert expr.matches({"tool": "git_push"}) is True
        assert expr.matches({"tool": "juju_status"}) is False

    def test_nested_attribute_access(self):
        """Dotted names walk through nested dicts."""
        expr = _FilterExpr('arguments.branch == "main"')
        payload = {"arguments": {"branch": "main", "remote": "origin"}}
        assert expr.matches(payload) is True
        payload = {"arguments": {"branch": "feat-42"}}
        assert expr.matches(payload) is False

    def test_subscript_access(self):
        expr = _FilterExpr('arguments["branch"] == "main"')
        payload = {"arguments": {"branch": "main"}}
        assert expr.matches(payload) is True

    def test_numeric_comparison(self):
        expr = _FilterExpr("tokens_before > 100000")
        assert expr.matches({"tokens_before": 150000}) is True
        assert expr.matches({"tokens_before": 50000}) is False

    def test_missing_field_returns_false(self):
        """References to absent fields don't raise — the filter rejects."""
        expr = _FilterExpr('tool == "git_push"')
        assert expr.matches({}) is False

    def test_missing_nested_field_returns_false(self):
        """Nested access through a missing root also rejects gracefully."""
        expr = _FilterExpr('task.category == "BUILD"')
        assert expr.matches({}) is False
        # And the reverse: ``task`` present, ``category`` missing.
        assert expr.matches({"task": {}}) is False

    def test_missing_field_inequality(self):
        """``!=`` against a missing field is True (field != concrete value)."""
        expr = _FilterExpr('tool != "git_push"')
        assert expr.matches({}) is True

    def test_ordering_op_against_missing_is_false(self):
        """``>`` / ``<`` against missing return False rather than raising."""
        expr = _FilterExpr("tokens_before > 100")
        assert expr.matches({}) is False

    def test_list_literal_of_mixed_types(self):
        expr = _FilterExpr("code in [200, 201, 204]")
        assert expr.matches({"code": 200}) is True
        assert expr.matches({"code": 500}) is False


class TestLoadHooksParsesIfFilter:
    """End-to-end: ``if:`` YAML entries become compiled ``_FilterExpr``."""

    def test_filter_accepted(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text(
            'hooks:\n  - event: pre_tool_call\n    if: tool == "git_push"\n    run: echo\n'
        )
        [hook] = _parse_yaml(path)
        assert hook.if_expr is not None
        assert hook.if_expr.source == 'tool == "git_push"'

    def test_missing_if_is_none(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text("hooks:\n  - event: pre_tool_call\n    run: echo\n")
        [hook] = _parse_yaml(path)
        assert hook.if_expr is None

    def test_empty_if_rejected(self, tmp_path: pathlib.Path):
        path = tmp_path / "hooks.yaml"
        path.write_text('hooks:\n  - event: pre_tool_call\n    if: ""\n    run: echo\n')
        with pytest.raises(HookConfigError, match="`if`"):
            _parse_yaml(path)

    def test_malformed_if_surfaces_hook_name(self, tmp_path: pathlib.Path):
        """A bad filter message names the hook so the operator finds it."""
        path = tmp_path / "hooks.yaml"
        path.write_text(
            "hooks:\n  - name: my-hook\n    event: pre_tool_call\n    if: print()\n    run: echo\n"
        )
        with pytest.raises(HookConfigError, match="my-hook"):
            _parse_yaml(path)


class TestHookRunnerSkipsFilteredHooks:
    """HookRunner.fire respects ``if:`` filters."""

    @pytest.mark.asyncio
    async def test_matching_filter_runs_hook(self, tmp_path: pathlib.Path):
        marker = tmp_path / "ran"
        hook = HookConfig(
            name="git-only",
            event=HookEvent.PRE_TOOL_CALL,
            run=f"touch {marker}",
            if_expr=_FilterExpr('tool == "git_push"'),
        )
        runner = HookRunner([hook])

        results = await runner.fire(HookEvent.PRE_TOOL_CALL, {"tool": "git_push"})
        assert len(results) == 1
        assert marker.exists()

    @pytest.mark.asyncio
    async def test_non_matching_filter_skips_hook(self, tmp_path: pathlib.Path):
        marker = tmp_path / "ran"
        hook = HookConfig(
            name="git-only",
            event=HookEvent.PRE_TOOL_CALL,
            run=f"touch {marker}",
            if_expr=_FilterExpr('tool == "git_push"'),
        )
        runner = HookRunner([hook])

        results = await runner.fire(HookEvent.PRE_TOOL_CALL, {"tool": "juju_status"})
        assert results == []
        assert not marker.exists()

    @pytest.mark.asyncio
    async def test_filter_can_reference_auto_added_event_field(self, tmp_path: pathlib.Path):
        """``event`` is injected into the payload and filters can read it."""
        marker = tmp_path / "ran"
        hook = HookConfig(
            name="pre-only",
            event=HookEvent.PRE_TOOL_CALL,
            run=f"touch {marker}",
            if_expr=_FilterExpr('event == "pre_tool_call"'),
        )
        runner = HookRunner([hook])

        await runner.fire(HookEvent.PRE_TOOL_CALL, {"tool": "x"})
        assert marker.exists()

    @pytest.mark.asyncio
    async def test_filtered_and_unfiltered_hooks_on_same_event(self, tmp_path: pathlib.Path):
        """Multiple hooks: filtered ones skip, unfiltered fire, preserving order."""
        log_file = tmp_path / "log"
        hooks = [
            HookConfig(
                name="always",
                event=HookEvent.PRE_TOOL_CALL,
                run=f"echo always >> {log_file}",
            ),
            HookConfig(
                name="git-only",
                event=HookEvent.PRE_TOOL_CALL,
                run=f"echo git-only >> {log_file}",
                if_expr=_FilterExpr('tool == "git_push"'),
            ),
            HookConfig(
                name="read-only",
                event=HookEvent.PRE_TOOL_CALL,
                run=f"echo read-only >> {log_file}",
                if_expr=_FilterExpr('tool == "read_file"'),
            ),
        ]
        runner = HookRunner(hooks)

        await runner.fire(HookEvent.PRE_TOOL_CALL, {"tool": "git_push"})
        assert log_file.read_text() == "always\ngit-only\n"


# ---------------------------------------------------------------------------
# Veto semantics — HookResult.vetoed + first_veto helper (Phase 46.4a)
# ---------------------------------------------------------------------------


class TestHookResultVetoed:
    """``HookResult.vetoed`` reflects continue_on_error + exit_code."""

    def _result(
        self,
        *,
        exit_code: int | None = 0,
        timed_out: bool = False,
        continue_on_error: bool = True,
    ) -> HookResult:
        return HookResult(
            name="h",
            event=HookEvent.PRE_TOOL_CALL,
            exit_code=exit_code,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            timed_out=timed_out,
            continue_on_error=continue_on_error,
        )

    def test_success_not_vetoed(self):
        assert self._result(exit_code=0).vetoed is False

    def test_failure_with_continue_on_error_not_vetoed(self):
        """Default ``continue_on_error=true`` preserves 46.2 behaviour."""
        assert self._result(exit_code=1, continue_on_error=True).vetoed is False

    def test_failure_without_continue_on_error_vetoes(self):
        assert self._result(exit_code=1, continue_on_error=False).vetoed is True

    def test_timeout_vetoes_when_strict(self):
        assert self._result(timed_out=True, continue_on_error=False).vetoed is True

    def test_timeout_does_not_veto_when_lenient(self):
        assert self._result(timed_out=True, continue_on_error=True).vetoed is False

    def test_veto_reason_names_hook(self):
        r = self._result(exit_code=2, continue_on_error=False)
        r = HookResult(
            name="require-clean",
            event=HookEvent.PRE_TOOL_CALL,
            exit_code=2,
            stdout="",
            stderr="uncommitted changes on main\n",
            duration_seconds=0.1,
            timed_out=False,
            continue_on_error=False,
        )
        assert "require-clean" in r.veto_reason
        assert "uncommitted" in r.veto_reason

    def test_veto_reason_falls_back_to_exit_code_when_silent(self):
        r = HookResult(
            name="silent",
            event=HookEvent.PRE_TOOL_CALL,
            exit_code=7,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            timed_out=False,
            continue_on_error=False,
        )
        assert "exit 7" in r.veto_reason

    def test_veto_reason_for_timeout(self):
        r = HookResult(
            name="slow",
            event=HookEvent.PRE_TOOL_CALL,
            exit_code=None,
            stdout="",
            stderr="",
            duration_seconds=3.2,
            timed_out=True,
            continue_on_error=False,
        )
        assert "timed out" in r.veto_reason
        assert "slow" in r.veto_reason


class TestFirstVetoHelper:
    """``first_veto`` returns the first vetoing result, in order."""

    def _pair(self, exit_a: int, exit_b: int, strict_a: bool, strict_b: bool):
        a = HookResult(
            name="a",
            event=HookEvent.PRE_TOOL_CALL,
            exit_code=exit_a,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            continue_on_error=not strict_a,
        )
        b = HookResult(
            name="b",
            event=HookEvent.PRE_TOOL_CALL,
            exit_code=exit_b,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            continue_on_error=not strict_b,
        )
        return [a, b]

    def test_empty_list_returns_none(self):
        assert first_veto([]) is None

    def test_all_ok_returns_none(self):
        results = self._pair(0, 0, False, False)
        assert first_veto(results) is None

    def test_first_veto_wins(self):
        results = self._pair(1, 1, strict_a=True, strict_b=True)
        veto = first_veto(results)
        assert veto is not None and veto.name == "a"

    def test_non_strict_failure_ignored(self):
        """continue_on_error=true + failure still not a veto."""
        results = self._pair(1, 1, strict_a=False, strict_b=True)
        veto = first_veto(results)
        assert veto is not None and veto.name == "b"


# ---------------------------------------------------------------------------
# End-to-end: main agent respects tool-call vetoes (Phase 46.4a)
# ---------------------------------------------------------------------------


class TestAgentRespectsToolCallVeto:
    """A ``pre_tool_call`` veto synthesises an error ToolResult."""

    @pytest.mark.asyncio
    async def test_veto_skips_tool_execution(self, tmp_path: pathlib.Path):
        """The tool function is not called when a pre-hook vetoes."""
        from unittest.mock import AsyncMock

        from cantrip.agent.core import CantripAgent
        from cantrip.agent.tools.base import ToolResult
        from cantrip.llm.base import Response, ToolCall
        from tests.conftest import FakeProvider

        hooks = [
            HookConfig(
                name="block-git-push",
                event=HookEvent.PRE_TOOL_CALL,
                run='sh -c "echo not on my watch >&2; exit 1"',
                continue_on_error=False,
                if_expr=_FilterExpr('tool == "git_push"'),
            ),
        ]

        tool_call = ToolCall(id="tc1", name="git_push", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="OK, I'll stop."),
            ]
        )
        agent = CantripAgent(provider=provider, hook_runner=HookRunner(hooks))
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="pushed!"))

        await agent.process_message("Push please")

        # The tool was never called — the hook blocked it.
        agent._execute_tool.assert_not_awaited()

        # The LLM received a TOOL message explaining the veto.
        tool_msg = next(m for m in agent.state.messages if m.role.name == "TOOL")
        [tr] = tool_msg.tool_results
        assert tr.is_error is True
        assert "block-git-push" in tr.content
        assert "not on my watch" in tr.content

    @pytest.mark.asyncio
    async def test_non_vetoing_failure_does_not_block(self, tmp_path: pathlib.Path):
        """A failing hook with ``continue_on_error: true`` does NOT veto.

        This protects 46.2 users from a surprise change of semantics.
        """
        from unittest.mock import AsyncMock

        from cantrip.agent.core import CantripAgent
        from cantrip.agent.tools.base import ToolResult
        from cantrip.llm.base import Response, ToolCall
        from tests.conftest import FakeProvider

        hooks = [
            HookConfig(
                name="noisy",
                event=HookEvent.PRE_TOOL_CALL,
                run="false",  # Always fails, but lenient.
                continue_on_error=True,
            ),
        ]

        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Done."),
            ]
        )
        agent = CantripAgent(provider=provider, hook_runner=HookRunner(hooks))
        tool_mock = AsyncMock(return_value=ToolResult(success=True, output="active"))
        agent._execute_tool = tool_mock

        await agent.process_message("Check status")

        # The tool DID run despite the hook failure.
        tool_mock.assert_awaited_once()


class TestAgentRespectsCompactionVeto:
    """A ``pre_compact`` veto preserves the conversation context as-is."""

    @pytest.mark.asyncio
    async def test_compaction_blocked_by_hook(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        from unittest.mock import AsyncMock

        from cantrip.agent.core import CantripAgent
        from cantrip.llm.base import Response
        from tests.conftest import FakeProvider

        hooks = [
            HookConfig(
                name="pin",
                event=HookEvent.PRE_COMPACT,
                run="false",
                continue_on_error=False,
            ),
        ]

        provider = FakeProvider([Response(content="hi")])
        agent = CantripAgent(provider=provider, hook_runner=HookRunner(hooks))

        # Force ``should_compact`` to trip on the next turn.
        monkeypatch.setattr(agent._context_manager, "should_compact", lambda _msgs: True)
        compact_mock = AsyncMock()
        monkeypatch.setattr(agent._context_manager, "compact", compact_mock)

        # Drive one turn with a tool call so the compaction-check site
        # is reachable; but skip_compact because pre_compact vetoed.
        from cantrip.agent.tools.base import ToolResult
        from cantrip.llm.base import ToolCall

        tool_call = ToolCall(id="tc1", name="juju_status", arguments={})
        agent.provider = FakeProvider(
            [
                Response(content="", tool_calls=[tool_call]),
                Response(content="Done."),
            ]
        )
        agent._execute_tool = AsyncMock(return_value=ToolResult(success=True, output="active"))

        await agent.process_message("status please")

        # Compaction never ran — the pre-hook blocked it.
        compact_mock.assert_not_awaited()
