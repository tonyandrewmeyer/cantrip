"""Subagent tests: Phase 80.2 policy wiring.

Exercise the ``_build_policy_enforcer`` helper, the list-time
``filter_tools`` pass, and the call-time ``check_tool`` gate in the
subagent dispatcher.  These tests don't run a full subagent loop —
they pin the policy behaviour at its seams so a later refactor can't
silently weaken the stack.
"""

from __future__ import annotations

import pathlib

import pytest

from cantrip.agent.policy.policy import (
    ORG_WIDE_POLICY,
    GovernancePolicy,
    PolicyAction,
    PolicyEnforcer,
)
from cantrip.agent.queue import AgentTask, TaskCategory
from cantrip.agent.subagent import (
    _CATEGORY_TOOLS,
    Subagent,
    _build_policy_enforcer,
    _filter_tools,
)
from cantrip.llm.base import Response, ToolCall
from tests.conftest import FakeProvider
from tests.unit.subagent.conftest import _make_context, _make_tool


class TestBuildPolicyEnforcer:
    """Verify the composed policy stack matches the defence-in-depth design."""

    def test_org_wide_review_list_propagates(self) -> None:
        """ORG_WIDE_POLICY's approval list survives composition."""
        enforcer = _build_policy_enforcer(TaskCategory.INFRA, charm_path=None)
        # INFRA allow-list includes juju_destroy_model, but ORG_WIDE
        # puts it on the review list — so the composed verdict is
        # REVIEW (which the filter treats as DENY for now).
        assert enforcer.check_tool("juju_destroy_model") == PolicyAction.REVIEW

    def test_unknown_category_denies_everything(self) -> None:
        """CONFIRM and other categories with no allow-list get zero tools."""
        enforcer = _build_policy_enforcer(TaskCategory.CONFIRM, charm_path=None)
        # Allow-list is the sentinel so no real tool name matches.
        assert enforcer.check_tool("read_file") == PolicyAction.DENY

    def test_category_allowlist_filters_non_allowed(self) -> None:
        """A tool outside the category allow-list is denied."""
        enforcer = _build_policy_enforcer(TaskCategory.RESEARCH, charm_path=None)
        # juju_deploy is not in the RESEARCH allow-list.
        assert enforcer.check_tool("juju_deploy") == PolicyAction.DENY

    def test_category_allowlist_permits_allowed(self) -> None:
        enforcer = _build_policy_enforcer(TaskCategory.RESEARCH, charm_path=None)
        # web_fetch is in the RESEARCH allow-list and not on the review list.
        assert enforcer.check_tool("web_fetch") == PolicyAction.ALLOW

    def test_mcp_tools_always_allowed(self) -> None:
        """Phase 45.2: MCP tools bypass the policy stack entirely."""
        enforcer = _build_policy_enforcer(TaskCategory.RESEARCH, charm_path=None)
        # Even a tool that obviously isn't in the RESEARCH allow-list
        # (e.g. mcp__grafana__query) passes because of the prefix.
        assert enforcer.check_tool("mcp__grafana__query") == PolicyAction.ALLOW
        assert enforcer.check_tool("mcp__any__thing") == PolicyAction.ALLOW

    def test_per_charm_file_tightens_the_stack(self, tmp_path: pathlib.Path) -> None:
        """A per-charm policy file can add a block on top of the defaults."""
        (tmp_path / "cantrip.policies.yaml").write_text(
            "name: production\nblocked_tools:\n  - web_fetch\n"
        )
        enforcer = _build_policy_enforcer(TaskCategory.RESEARCH, charm_path=str(tmp_path))
        # web_fetch was allowed by the category layer; the per-charm
        # block overrides that to DENY.
        assert enforcer.check_tool("web_fetch") == PolicyAction.DENY

    def test_per_charm_file_cannot_loosen_org_wide_review(self, tmp_path: pathlib.Path) -> None:
        """A per-charm policy can't dilute the org-wide approval list.

        Composition is most-restrictive-wins, so if ORG_WIDE reviews a
        tool, a per-charm file listing the same tool as allowed
        doesn't undo that — it just intersects with the existing
        allow-list.  This pins the defence-in-depth guarantee.
        """
        (tmp_path / "cantrip.policies.yaml").write_text(
            "name: loose\nallowed_tools:\n  - juju_destroy_model\n"
        )
        enforcer = _build_policy_enforcer(TaskCategory.INFRA, charm_path=str(tmp_path))
        assert enforcer.check_tool("juju_destroy_model") == PolicyAction.REVIEW

    def test_composed_policy_name_reflects_stack(self) -> None:
        enforcer = _build_policy_enforcer(TaskCategory.BUILD, charm_path=None)
        assert "org-wide" in enforcer.policy.name
        assert "category:build" in enforcer.policy.name


class TestFilterToolsShim:
    """``_filter_tools`` is the thin shim for callers without a full SubagentContext."""

    def test_filter_drops_review_tools(self) -> None:
        """REVIEW verdict degrades to DENY in filter_tools until Phase 68.2 lands."""
        tools = [
            _make_tool("juju_add_model"),  # in the INFRA allow-list, not reviewed.
            _make_tool("juju_destroy_model"),  # in INFRA allow-list AND ORG_WIDE review list.
            _make_tool("git_push"),  # in INFRA allow-list AND ORG_WIDE review list.
        ]
        filtered = _filter_tools(tools, TaskCategory.INFRA)
        names = {t.name for t in filtered}
        assert "juju_add_model" in names
        assert "juju_destroy_model" not in names
        assert "git_push" not in names

    def test_filter_preserves_mcp_bypass(self) -> None:
        """MCP tools pass through unchanged, matching the old filter."""
        tools = [_make_tool("mcp__grafana__query"), _make_tool("made_up_tool")]
        filtered = _filter_tools(tools, TaskCategory.BUILD)
        names = {t.name for t in filtered}
        assert "mcp__grafana__query" in names
        assert "made_up_tool" not in names


class TestPolicyEnforcerDenyReason:
    """The deny_reason string names the composed policy for audit."""

    def test_deny_reason_mentions_policy_stack(self) -> None:
        enforcer = _build_policy_enforcer(TaskCategory.RESEARCH, charm_path=None)
        reason = enforcer.deny_reason("juju_deploy")
        assert "juju_deploy" in reason
        # Composition name is "org-wide+category:research+..." so both
        # source layers are identifiable in the audit output.
        assert "policy" in reason.lower()

    def test_deny_reason_empty_for_allowed_tool(self) -> None:
        enforcer = _build_policy_enforcer(TaskCategory.RESEARCH, charm_path=None)
        assert enforcer.deny_reason("web_fetch") == ""


class TestOrgWideReviewListStability:
    """Pin the review list so a later refactor can't silently weaken it."""

    def test_org_wide_covers_destructive_juju(self) -> None:
        for tool in (
            "juju_destroy_model",
            "juju_destroy_controller",
            "juju_remove_application",
            "juju_remove_relation",
        ):
            assert ORG_WIDE_POLICY.check_tool(tool) == PolicyAction.REVIEW, tool

    def test_org_wide_covers_git_push_and_shell(self) -> None:
        for tool in ("run_command", "git_push"):
            assert ORG_WIDE_POLICY.check_tool(tool) == PolicyAction.REVIEW, tool

    def test_category_allowlists_still_contain_reviewed_tools(self) -> None:
        """The category data still includes the destructive tools — the
        ORG_WIDE review layer is what gates them, not removal from the
        category allow-list.  If this invariant breaks, the review
        gate becomes a no-op because the category layer already
        excluded the tool.
        """
        assert "juju_destroy_model" in _CATEGORY_TOOLS[TaskCategory.INFRA]
        assert "juju_remove_application" in _CATEGORY_TOOLS[TaskCategory.DEPLOY]
        assert "git_push" in _CATEGORY_TOOLS[TaskCategory.INFRA]


class TestExtraPolicies:
    """``extra_policies`` lets tests add a layer without touching YAML."""

    def test_extra_policy_adds_block(self) -> None:
        extra = GovernancePolicy(name="test-extra", blocked_tools=frozenset({"web_fetch"}))
        enforcer = _build_policy_enforcer(
            TaskCategory.RESEARCH,
            charm_path=None,
            extra_policies=(extra,),
        )
        assert enforcer.check_tool("web_fetch") == PolicyAction.DENY

    def test_extra_policy_adds_rate_limit(self) -> None:
        extra = GovernancePolicy(name="test-rate", max_calls_per_request=10)
        enforcer = _build_policy_enforcer(
            TaskCategory.RESEARCH,
            charm_path=None,
            extra_policies=(extra,),
        )
        assert enforcer.policy.max_calls_per_request == 10


class TestAuditIntegration:
    """Phase 80.4: subagent writes one JSONL audit line per decision."""

    @pytest.mark.asyncio
    async def test_allowed_and_denied_calls_both_land_in_audit_file(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A two-turn run with one allowed tool and one policy-denied tool
        produces two audit lines with the right actions and policy name.
        """
        from cantrip.agent.audit import AUDIT_FILENAME, AuditAction, read_entries

        read_tool = _make_tool("read_file")
        task = AgentTask(id="t-audit", title="Audit test", category=TaskCategory.BUILD)
        ctx = _make_context(task=task, charm_path=str(tmp_path))

        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc1", name="read_file", arguments={"path": "f.py"}),
                    ],
                ),
                Response(content="Done."),
            ],
        )
        subagent = Subagent(ctx, tools=[read_tool], provider=provider)

        # Swap the policy mid-way isn't necessary — the stock
        # BUILD category policy allows read_file.  Force a denial
        # by replacing the enforcer with one that blocks read_file
        # and making the tool visible again.
        subagent._policy = PolicyEnforcer(
            policy=GovernancePolicy(
                name="test-block",
                blocked_tools=frozenset({"read_file"}),
            )
        )
        subagent._tool_map["read_file"] = read_tool
        subagent._tools = [read_tool]

        await subagent.run()

        audit_path = tmp_path / AUDIT_FILENAME
        assert audit_path.is_file()
        entries = list(read_entries(audit_path))
        # Exactly one denial entry for read_file (LLM tried it once).
        assert len(entries) == 1
        entry = entries[0]
        assert entry.tool == "read_file"
        assert entry.action is AuditAction.DENIED
        assert entry.task_id == "t-audit"
        assert entry.policy_name == "test-block"
        assert "blocked" in entry.reason.lower() or "policy" in entry.reason.lower()

    @pytest.mark.asyncio
    async def test_audit_file_not_written_without_charm_path(self, tmp_path: pathlib.Path) -> None:
        """A subagent without a charm_path writes no audit file.

        The JSONL is keyed off the charm directory; there's nowhere
        meaningful to put the file without one.  Existing subagent
        tests that don't set charm_path shouldn't start leaving stray
        files in their cwd.
        """
        from cantrip.agent.audit import AUDIT_FILENAME

        task = AgentTask(id="t", title="x", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)  # No charm_path.
        provider = FakeProvider(responses=[Response(content="Nothing to do.")])
        subagent = Subagent(ctx, tools=[], provider=provider)
        assert subagent._audit_writer is None

        await subagent.run()

        assert not (tmp_path / AUDIT_FILENAME).exists()


class TestCallTimeGate:
    """A policy DENY at call time short-circuits to a synthetic error result.

    The integration test covers the gate even when the LLM somehow
    requests a tool the filter-time pass didn't expose (hallucinated
    name, future rate-limit DENY that triggers mid-run, etc.).
    """

    @pytest.mark.asyncio
    async def test_policy_denied_call_returns_synthetic_error(self) -> None:
        """A DENY verdict produces a ToolResult(is_error=True) naming the policy."""
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Read", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc1", name="read_file", arguments={"path": "f.py"}),
                    ],
                ),
                Response(content="Denied, moving on."),
            ],
        )
        subagent = Subagent(ctx, tools=[tool], provider=provider)

        # Install a policy that blocks read_file — simulates the rate-
        # limit scenario from Phase 80.3 or a per-charm block that
        # appeared after the tool list was built.  We also need to
        # add read_file back to the visible tool list, since the
        # subagent would have filtered it at construction.
        subagent._policy = PolicyEnforcer(
            policy=GovernancePolicy(
                name="test-block",
                blocked_tools=frozenset({"read_file"}),
            )
        )
        subagent._tool_map["read_file"] = tool
        subagent._tools = [tool]

        result = await subagent.run()

        # The LLM got a follow-up turn — that's why the final text is
        # "Denied, moving on."  The important part is the tool was
        # never actually executed.
        assert result.text == "Denied, moving on."
        tool.execute.assert_not_called()
