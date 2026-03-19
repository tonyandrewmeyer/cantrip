"""Tests for the subagent runner."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory
from cantrip.agent.subagent import (
    _CATEGORY_GUIDANCE,
    _CATEGORY_TOOLS,
    MAX_SUBAGENT_ROUNDS,
    ProviderThrottle,
    Subagent,
    SubagentContext,
    _build_subagent_prompt,
    _filter_tools,
    _select_provider,
    _task_instruction,
    _tools_for_llm,
)
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm.base import ProviderRateLimitError, Response, ToolCall
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str, execute_return: ToolResult | None = None) -> Tool:
    """Build a minimal Tool stub with the given *name*."""

    class _StubTool(Tool):
        @property
        def _name(self) -> str:
            return name

        @property
        def _desc(self) -> str:
            return f"Stub tool {name}"

        @property
        def _params(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

    # We cannot override abstract properties with simple assignments, so
    # we use a concrete subclass with the right property names.
    class StubTool(_StubTool):
        @property
        def name(self) -> str:  # type: ignore[override]
            return self._name

        @property
        def description(self) -> str:  # type: ignore[override]
            return self._desc

        @property
        def parameters(self) -> dict[str, Any]:  # type: ignore[override]
            return self._params

        async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
            return execute_return or ToolResult(success=True, output="ok")

    tool = StubTool()
    tool.execute = AsyncMock(  # type: ignore[method-assign]
        return_value=execute_return or ToolResult(success=True, output="ok"),
    )
    return tool


def _make_context(**overrides: Any) -> SubagentContext:
    """Build a SubagentContext with sensible defaults."""
    defaults: dict[str, Any] = {
        "task": AgentTask(
            id="test-task",
            title="Test task",
            category=TaskCategory.BUILD,
            description="A test task description.",
        ),
    }
    defaults.update(overrides)
    return SubagentContext(**defaults)


# ===================================================================
# TestSubagentContext
# ===================================================================


class TestSubagentContext:
    """Tests for SubagentContext dataclass construction."""

    def test_defaults(self) -> None:
        task = AgentTask(id="t1", title="T", category=TaskCategory.RESEARCH)
        ctx = SubagentContext(task=task)

        assert ctx.task is task
        assert ctx.charm_name is None
        assert ctx.charm_path is None
        assert ctx.charm_type is None
        assert ctx.framework is None
        assert ctx.dev_model is None
        assert ctx.cos_model is None
        assert ctx.decisions == []
        assert ctx.prior_results == {}

    def test_full_construction(self) -> None:
        task = AgentTask(id="t2", title="Build", category=TaskCategory.BUILD)
        ctx = SubagentContext(
            task=task,
            charm_name="redis-k8s",
            charm_path="/tmp/redis-k8s",
            charm_type="k8s",
            framework="flask",
            dev_model="dev",
            cos_model="cos",
            decisions=[{"type": "path", "choice": "A"}],
            prior_results={"research": "Found docs"},
        )

        assert ctx.charm_name == "redis-k8s"
        assert ctx.prior_results == {"research": "Found docs"}


# ===================================================================
# TestFilterTools
# ===================================================================


class TestFilterTools:
    """Tests for _filter_tools — category-based tool selection."""

    def test_research_gets_correct_tools(self) -> None:
        tools = [
            _make_tool("web_fetch"),
            _make_tool("write_file"),
            _make_tool("charmhub_search"),
            _make_tool("juju_deploy"),
        ]
        filtered = _filter_tools(tools, TaskCategory.RESEARCH)

        names = {t.name for t in filtered}
        assert "web_fetch" in names
        assert "charmhub_search" in names
        assert "write_file" in names
        assert "juju_deploy" not in names

    def test_build_gets_correct_tools(self) -> None:
        tools = [
            _make_tool("read_file"),
            _make_tool("write_file"),
            _make_tool("juju_deploy"),
        ]
        filtered = _filter_tools(tools, TaskCategory.BUILD)

        names = {t.name for t in filtered}
        assert "read_file" in names
        assert "write_file" in names
        assert "juju_deploy" not in names

    def test_confirm_returns_empty(self) -> None:
        tools = [_make_tool("read_file"), _make_tool("web_fetch")]
        filtered = _filter_tools(tools, TaskCategory.CONFIRM)

        assert filtered == []

    def test_deploy_includes_juju_tools(self) -> None:
        tools = [
            _make_tool("juju_deploy"),
            _make_tool("juju_status"),
            _make_tool("git_commit"),
        ]
        filtered = _filter_tools(tools, TaskCategory.DEPLOY)

        names = {t.name for t in filtered}
        assert "juju_deploy" in names
        assert "juju_status" in names
        assert "git_commit" not in names

    def test_debug_includes_observability(self) -> None:
        tools = [
            _make_tool("juju_debug_log"),
            _make_tool("tempo_query"),
            _make_tool("loki_query"),
            _make_tool("charmcraft_init"),
        ]
        filtered = _filter_tools(tools, TaskCategory.DEBUG)

        names = {t.name for t in filtered}
        assert "juju_debug_log" in names
        assert "tempo_query" in names
        assert "loki_query" in names
        assert "charmcraft_init" not in names

    def test_infra_includes_concierge(self) -> None:
        tools = [
            _make_tool("concierge_prepare"),
            _make_tool("concierge_status"),
            _make_tool("read_file"),
        ]
        filtered = _filter_tools(tools, TaskCategory.INFRA)

        names = {t.name for t in filtered}
        assert "concierge_prepare" in names
        assert "concierge_status" in names
        assert "read_file" not in names

    def test_deploy_includes_fast_path_tools(self) -> None:
        tools = [
            _make_tool("charm_sync"),
            _make_tool("juju_dispatch"),
            _make_tool("juju_deploy"),
            _make_tool("write_file"),
        ]
        filtered = _filter_tools(tools, TaskCategory.DEPLOY)

        names = {t.name for t in filtered}
        assert "charm_sync" in names
        assert "juju_dispatch" in names
        assert "juju_deploy" in names
        assert "write_file" not in names

    def test_empty_tools_returns_empty(self) -> None:
        assert _filter_tools([], TaskCategory.BUILD) == []


# ===================================================================
# TestSelectProvider
# ===================================================================


class TestSelectProvider:
    """Tests for _select_provider — routing to light vs primary."""

    def test_research_uses_light(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.RESEARCH, primary, light)
        assert result is light

    def test_infra_uses_light(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.INFRA, primary, light)
        assert result is light

    def test_build_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.BUILD, primary, light)
        assert result is primary

    def test_deploy_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.DEPLOY, primary, light)
        assert result is primary

    def test_no_light_falls_back_to_primary(self) -> None:
        primary = FakeProvider()
        result = _select_provider(TaskCategory.RESEARCH, primary, None)
        assert result is primary

    def test_test_category_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.TEST, primary, light)
        assert result is primary

    def test_debug_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(TaskCategory.DEBUG, primary, light)
        assert result is primary

    def test_model_hint_primary_overrides_category(self) -> None:
        """Explicit PRIMARY hint forces primary even for a light category."""
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH,
            primary,
            light,
            model_hint=ModelHint.PRIMARY,
        )
        assert result is primary

    def test_model_hint_light_overrides_category(self) -> None:
        """Explicit LIGHT hint forces light even for a primary category."""
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.BUILD,
            primary,
            light,
            model_hint=ModelHint.LIGHT,
        )
        assert result is light

    def test_model_hint_light_without_provider_falls_back(self) -> None:
        """LIGHT hint without a light provider falls back to primary."""
        primary = FakeProvider()
        result = _select_provider(
            TaskCategory.BUILD,
            primary,
            None,
            model_hint=ModelHint.LIGHT,
        )
        assert result is primary


# ===================================================================
# TestToolsForLlm
# ===================================================================


class TestToolsForLlm:
    """Tests for _tools_for_llm — conversion to LLM descriptors."""

    def test_empty_returns_none(self) -> None:
        assert _tools_for_llm([]) is None

    def test_converts_tools(self) -> None:
        tools = [_make_tool("read_file"), _make_tool("web_fetch")]
        result = _tools_for_llm(tools)

        assert result is not None
        assert len(result) == 2
        assert result[0].name == "read_file"
        assert result[1].name == "web_fetch"


# ===================================================================
# TestBuildSubagentPrompt
# ===================================================================


class TestBuildSubagentPrompt:
    """Tests for _build_subagent_prompt — system prompt construction."""

    def test_contains_role_preamble(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "autonomous subagent" in prompt

    def test_contains_task_title(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "Test task" in prompt

    def test_contains_task_category(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "build" in prompt

    def test_contains_task_description(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "A test task description." in prompt

    def test_contains_charm_context(self) -> None:
        ctx = _make_context(
            charm_name="redis-k8s",
            charm_path="/tmp/redis-k8s",
            charm_type="k8s",
            framework="flask",
            dev_model="dev-model",
            cos_model="cos-model",
        )
        prompt = _build_subagent_prompt(ctx)

        assert "redis-k8s" in prompt
        assert "/tmp/redis-k8s" in prompt
        assert "k8s" in prompt
        assert "flask" in prompt
        assert "dev-model" in prompt
        assert "cos-model" in prompt

    def test_omits_none_charm_context(self) -> None:
        ctx = _make_context(charm_name=None, charm_path=None)
        prompt = _build_subagent_prompt(ctx)
        assert "Charm context" not in prompt

    def test_contains_category_guidance(self) -> None:
        task = AgentTask(id="r", title="Research", category=TaskCategory.RESEARCH)
        ctx = _make_context(task=task)
        prompt = _build_subagent_prompt(ctx)
        assert "Guidance" in prompt
        assert "Cite sources" in prompt

    def test_contains_prior_results(self) -> None:
        ctx = _make_context(prior_results={"research-task": "Found Redis docs at..."})
        prompt = _build_subagent_prompt(ctx)
        assert "Prior task results" in prompt
        assert "research-task" in prompt
        assert "Found Redis docs at..." in prompt

    def test_omits_prior_results_when_empty(self) -> None:
        ctx = _make_context(prior_results={})
        prompt = _build_subagent_prompt(ctx)
        assert "Prior task results" not in prompt

    def test_contains_decisions(self) -> None:
        ctx = _make_context(
            decisions=[
                {"type": "substrate", "choice": "k8s", "reason": "Modern deployment"},
            ],
        )
        prompt = _build_subagent_prompt(ctx)
        assert "Decisions" in prompt
        assert "substrate" in prompt
        assert "k8s" in prompt
        assert "Modern deployment" in prompt

    def test_omits_decisions_when_empty(self) -> None:
        ctx = _make_context(decisions=[])
        prompt = _build_subagent_prompt(ctx)
        assert "Decisions" not in prompt

    def test_contains_completion_instruction(self) -> None:
        ctx = _make_context()
        prompt = _build_subagent_prompt(ctx)
        assert "Completion" in prompt
        assert "summary" in prompt


# ===================================================================
# TestTaskInstruction
# ===================================================================


class TestTaskInstruction:
    """Tests for _task_instruction — user message formatting."""

    def test_title_only(self) -> None:
        task = AgentTask(id="t", title="Do something", category=TaskCategory.BUILD)
        result = _task_instruction(task)
        assert result == "Do something"

    def test_title_and_description(self) -> None:
        task = AgentTask(
            id="t",
            title="Research Redis",
            category=TaskCategory.RESEARCH,
            description="Clone the repo and analyse the framework.",
        )
        result = _task_instruction(task)
        assert "Research Redis" in result
        assert "Clone the repo" in result
        assert "\n\n" in result

    def test_empty_description_omitted(self) -> None:
        task = AgentTask(id="t", title="Deploy", category=TaskCategory.DEPLOY, description="")
        result = _task_instruction(task)
        assert result == "Deploy"


# ===================================================================
# TestSubagentRun
# ===================================================================


class TestSubagentRun:
    """Tests for Subagent.run() — the tool-call loop."""

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_content(self) -> None:
        provider = FakeProvider(responses=[Response(content="Task complete.")])
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        result = await subagent.run()

        assert result == "Task complete."

    @pytest.mark.asyncio
    async def test_one_tool_call_round(self) -> None:
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
                Response(content="Done reading."),
            ],
        )
        subagent = Subagent(ctx, tools=[tool], provider=provider)

        result = await subagent.run()

        assert result == "Done reading."
        tool.execute.assert_called_once_with(path="f.py")

    @pytest.mark.asyncio
    async def test_max_rounds_stops_loop(self) -> None:
        """When the LLM keeps requesting tools, the loop stops after MAX_SUBAGENT_ROUNDS."""
        tool = _make_tool("read_file")
        task = AgentTask(id="t", title="Loop", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        # Every response has tool calls — the loop should cap out.
        responses = [
            Response(
                content=f"round {i}",
                tool_calls=[
                    ToolCall(id=f"tc{i}", name="read_file", arguments={}),
                ],
            )
            for i in range(MAX_SUBAGENT_ROUNDS + 5)
        ]
        provider = FakeProvider(responses=responses)
        subagent = Subagent(ctx, tools=[tool], provider=provider)

        await subagent.run()

        # The last response consumed is at round MAX_SUBAGENT_ROUNDS (0-indexed: +1 initial).
        assert provider._call_count == MAX_SUBAGENT_ROUNDS + 1

    @pytest.mark.asyncio
    async def test_uses_correct_temperature(self) -> None:
        """Verify the subagent passes temperature=0.5 to the provider."""
        recorded_temps: list[float] = []

        class RecordingProvider(FakeProvider):
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                recorded_temps.append(temperature)
                return Response(content="done")

        provider = RecordingProvider()
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        await subagent.run()

        assert recorded_temps == [0.5]

    @pytest.mark.asyncio
    async def test_research_task_uses_light_provider(self) -> None:
        primary = FakeProvider(responses=[Response(content="primary")])
        light = FakeProvider(responses=[Response(content="light")])
        task = AgentTask(id="r", title="Research", category=TaskCategory.RESEARCH)
        ctx = _make_context(task=task)

        subagent = Subagent(ctx, tools=[], provider=primary, light_provider=light)
        result = await subagent.run()

        assert result == "light"


# ===================================================================
# TestSubagentRetry
# ===================================================================


class TestSubagentRetry:
    """Tests for rate-limit retry behaviour."""

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self) -> None:
        call_count = 0

        class FlakeyProvider(FakeProvider):
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ProviderRateLimitError("rate limited")
                return Response(content="recovered")

        provider = FlakeyProvider()
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        # Patch asyncio.sleep to avoid actual delays.
        import cantrip.agent.subagent as subagent_mod

        original_sleep = subagent_mod.asyncio.sleep
        subagent_mod.asyncio.sleep = AsyncMock()  # type: ignore[assignment]
        try:
            result = await subagent.run()
        finally:
            subagent_mod.asyncio.sleep = original_sleep  # type: ignore[assignment]

        assert result == "recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries_raises(self) -> None:
        class AlwaysRateLimited(FakeProvider):
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                raise ProviderRateLimitError("rate limited")

        provider = AlwaysRateLimited()
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        import cantrip.agent.subagent as subagent_mod

        original_sleep = subagent_mod.asyncio.sleep
        subagent_mod.asyncio.sleep = AsyncMock()  # type: ignore[assignment]
        try:
            with pytest.raises(ProviderRateLimitError):
                await subagent.run()
        finally:
            subagent_mod.asyncio.sleep = original_sleep  # type: ignore[assignment]


# ===================================================================
# TestSubagentToolExecution
# ===================================================================


class TestSubagentToolExecution:
    """Tests for tool execution error handling within the subagent."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        """Calling a tool not in the tool map returns an error ToolResult."""
        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc1", name="nonexistent_tool", arguments={}),
                    ],
                ),
                Response(content="Handled."),
            ],
        )
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider)

        result = await subagent.run()

        assert result == "Handled."

    @pytest.mark.asyncio
    async def test_type_error_returns_error_result(self) -> None:
        """A TypeError during tool execution is caught and returned as an error."""
        bad_tool = _make_tool("read_file")
        bad_tool.execute = AsyncMock(  # type: ignore[method-assign]
            side_effect=TypeError("missing required argument"),
        )

        task = AgentTask(id="t", title="Read", category=TaskCategory.BUILD)
        ctx = _make_context(task=task)

        provider = FakeProvider(
            responses=[
                Response(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc1", name="read_file", arguments={}),
                    ],
                ),
                Response(content="Error handled."),
            ],
        )
        subagent = Subagent(ctx, tools=[bad_tool], provider=provider)

        result = await subagent.run()

        assert result == "Error handled."


# ===================================================================
# TestResearchGuidance
# ===================================================================


class TestResearchGuidance:
    """Tests for the enhanced RESEARCH category guidance."""

    def test_cite_sources_in_guidance(self) -> None:
        task = AgentTask(id="r", title="Research", category=TaskCategory.RESEARCH)
        ctx = _make_context(task=task)
        prompt = _build_subagent_prompt(ctx)
        assert "Cite sources" in prompt

    def test_unknown_markers_in_guidance(self) -> None:
        task = AgentTask(id="r", title="Research", category=TaskCategory.RESEARCH)
        ctx = _make_context(task=task)
        prompt = _build_subagent_prompt(ctx)
        assert "[UNKNOWN]" in prompt

    def test_operational_story_questions(self) -> None:
        task = AgentTask(
            id="od",
            title="Synthesise design proposal",
            category=TaskCategory.RESEARCH,
        )
        ctx = _make_context(task=task)
        prompt = _build_subagent_prompt(ctx)
        assert "Storage" in prompt
        assert "Clustering" in prompt
        assert "Health" in prompt
        assert "Failure modes" in prompt
        assert "Observability" in prompt


# ===================================================================
# TestDesignContentInjection
# ===================================================================


class TestDesignContentInjection:
    """Tests for design content injection into the subagent prompt."""

    def test_design_content_in_build_prompt(self) -> None:
        """Design content appears in the prompt when set."""
        task = AgentTask(id="b", title="Build charm", category=TaskCategory.BUILD)
        ctx = _make_context(
            task=task,
            design_content="## Substrate\nK8s\n## Integrations\n- COS\n- TLS",
        )
        prompt = _build_subagent_prompt(ctx)
        assert "Approved design" in prompt
        assert "## Substrate" in prompt
        assert "- COS" in prompt

    def test_design_content_omitted_when_none(self) -> None:
        """When design_content is None, the section is absent."""
        task = AgentTask(id="b", title="Build charm", category=TaskCategory.BUILD)
        ctx = _make_context(task=task, design_content=None)
        prompt = _build_subagent_prompt(ctx)
        assert "Approved design" not in prompt


# ===================================================================
# TestResearchToolAllowlist
# ===================================================================


class TestResearchToolAllowlist:
    """Tests for write_file being in the RESEARCH tool allowlist."""

    def test_write_file_in_research_tools(self) -> None:
        tools = [_make_tool("write_file"), _make_tool("read_file")]
        filtered = _filter_tools(tools, TaskCategory.RESEARCH)
        names = {t.name for t in filtered}
        assert "write_file" in names


# ===================================================================
# TestOperationalDiscoveryUsePrimaryModel
# ===================================================================


class TestOperationalDiscoveryUsePrimaryModel:
    """Tests for routing operational-discovery tasks to the primary model."""

    def test_operational_discovery_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH, primary, light, task_title="operational-discovery"
        )
        assert result is primary

    def test_synthesise_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH, primary, light, task_title="Synthesise design proposal"
        )
        assert result is primary

    def test_regular_research_uses_light(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH, primary, light, task_title="Research the workload"
        )
        assert result is light

    def test_no_light_provider_uses_primary(self) -> None:
        primary = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH, primary, None, task_title="operational-discovery"
        )
        assert result is primary


# ===================================================================
# TestProviderThrottle
# ===================================================================


class TestProviderThrottle:
    """Tests for the shared rate-limit throttle."""

    @pytest.mark.asyncio
    async def test_no_throttle_no_wait(self) -> None:
        """Without signalling, wait_if_throttled returns immediately."""
        throttle = ProviderThrottle()
        # Should not block or raise.
        await throttle.wait_if_throttled("gemini")

    @pytest.mark.asyncio
    async def test_signal_then_wait(self) -> None:
        """After signalling, wait_if_throttled sleeps until the cooldown expires."""
        import cantrip.agent.subagent as subagent_mod

        throttle = ProviderThrottle()
        throttle.signal_rate_limit("gemini", 5.0)

        original_sleep = subagent_mod.asyncio.sleep
        slept: list[float] = []

        async def fake_sleep(duration: float) -> None:
            slept.append(duration)

        subagent_mod.asyncio.sleep = fake_sleep  # type: ignore[assignment]
        try:
            await throttle.wait_if_throttled("gemini")
        finally:
            subagent_mod.asyncio.sleep = original_sleep  # type: ignore[assignment]

        assert len(slept) == 1
        assert slept[0] > 0

    @pytest.mark.asyncio
    async def test_different_providers_independent(self) -> None:
        """Throttling one provider does not affect another."""
        throttle = ProviderThrottle()
        throttle.signal_rate_limit("gemini", 60.0)
        # Claude should not be throttled.
        await throttle.wait_if_throttled("claude")

    def test_longer_cooldown_preserved(self) -> None:
        """If an existing cooldown is longer, it is kept."""
        throttle = ProviderThrottle()
        throttle.signal_rate_limit("gemini", 60.0)
        first_deadline = throttle._cooldowns["gemini"]
        throttle.signal_rate_limit("gemini", 1.0)
        assert throttle._cooldowns["gemini"] == first_deadline

    @pytest.mark.asyncio
    async def test_throttle_passed_to_subagent(self) -> None:
        """Subagent calls wait_if_throttled before each LLM request."""
        waited = []

        class TrackingThrottle(ProviderThrottle):
            async def wait_if_throttled(self, provider_name: str) -> None:
                waited.append(provider_name)

        provider = FakeProvider(responses=[Response(content="done")])
        ctx = _make_context()
        throttle = TrackingThrottle()
        subagent = Subagent(ctx, tools=[], provider=provider, throttle=throttle)

        await subagent.run()

        assert len(waited) == 1
        assert waited[0] == provider.name

    @pytest.mark.asyncio
    async def test_throttle_signalled_on_rate_limit(self) -> None:
        """When a rate limit occurs, the throttle is signalled."""
        call_count = 0

        class FlakeyProvider(FakeProvider):
            async def complete(self, messages, tools=None, temperature=0.7):  # noqa: ARG002
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ProviderRateLimitError("rate limited")
                return Response(content="recovered")

        throttle = ProviderThrottle()
        provider = FlakeyProvider()
        ctx = _make_context()
        subagent = Subagent(ctx, tools=[], provider=provider, throttle=throttle)

        import cantrip.agent.subagent as subagent_mod

        original_sleep = subagent_mod.asyncio.sleep
        subagent_mod.asyncio.sleep = AsyncMock()  # type: ignore[assignment]
        try:
            result = await subagent.run()
        finally:
            subagent_mod.asyncio.sleep = original_sleep  # type: ignore[assignment]

        assert result == "recovered"
        # The throttle should have recorded a cooldown for the provider.
        assert provider.name in throttle._cooldowns


# ===================================================================
# TestCommitAfterBuild
# ===================================================================


class TestCommitAfterBuild:
    """Tests for commit-after-build guidance and tool allowlists."""

    def test_build_guidance_mentions_git_commit(self) -> None:
        """BUILD guidance instructs the subagent to commit its work."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "git_commit" in guidance

    def test_debug_guidance_mentions_git_commit(self) -> None:
        """DEBUG guidance instructs the subagent to commit fixes."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.DEBUG]
        assert "git_commit" in guidance

    def test_git_add_in_debug_tools(self) -> None:
        """git_add is in the DEBUG tool allowlist."""
        assert "git_add" in _CATEGORY_TOOLS[TaskCategory.DEBUG]

    def test_git_commit_in_debug_tools(self) -> None:
        """git_commit is in the DEBUG tool allowlist."""
        assert "git_commit" in _CATEGORY_TOOLS[TaskCategory.DEBUG]


# ===================================================================
# TestSelfVerification
# ===================================================================


class TestSelfVerification:
    """Tests for lightweight self-verification in BUILD subagents."""

    def test_charm_validate_in_build_tools(self) -> None:
        """charm_validate is in the BUILD tool allowlist."""
        assert "charm_validate" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_run_charm_tests_in_build_tools(self) -> None:
        """run_charm_tests is in the BUILD tool allowlist."""
        assert "run_charm_tests" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_build_guidance_mentions_charm_validate(self) -> None:
        """BUILD guidance instructs the subagent to run charm_validate."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "charm_validate" in guidance


# ===================================================================
# TestRedGreenBuildGuidance
# ===================================================================


class TestRedGreenBuildGuidance:
    """Tests for red/green (integration-tests-first) build guidance."""

    def test_build_guidance_mentions_red_green(self) -> None:
        """BUILD guidance includes the red/green cycle instruction."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "Red/green cycle" in guidance

    def test_build_guidance_mentions_integration_tests_first(self) -> None:
        """BUILD guidance instructs writing integration tests before charm code."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "integration tests do not exist yet" in guidance

    def test_build_guidance_mentions_jubilant(self) -> None:
        """BUILD guidance references Jubilant for integration test patterns."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "Jubilant" in guidance

    def test_build_guidance_mentions_pattern_parameter(self) -> None:
        """BUILD guidance mentions the pattern parameter for targeted test runs."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "pattern" in guidance

    def test_build_guidance_mentions_scenario_for_unit_tests(self) -> None:
        """BUILD guidance still includes Scenario for unit tests as a second pass."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "Scenario" in guidance

    def test_build_guidance_unit_tests_for_edge_cases(self) -> None:
        """BUILD guidance positions unit tests for edge cases and error paths."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.BUILD]
        assert "BlockedStatus" in guidance
        assert "WaitingStatus" in guidance

    def test_test_guidance_mentions_combined_validation(self) -> None:
        """TEST guidance includes combined unit + integration validation gate."""
        guidance = _CATEGORY_GUIDANCE[TaskCategory.TEST]
        assert "unit tests and integration tests" in guidance
        assert "combined" in guidance.lower()


# ===================================================================
# TestCharmAuditToolAllowlists
# ===================================================================


class TestCharmAuditToolAllowlists:
    """Tests for charm_audit tool registration in category allowlists."""

    def test_charm_audit_in_research_tools(self) -> None:
        """charm_audit is available to RESEARCH subagents for auditing."""
        assert "charm_audit" in _CATEGORY_TOOLS[TaskCategory.RESEARCH]

    def test_charm_audit_in_build_tools(self) -> None:
        """charm_audit is available to BUILD subagents for re-checking after fixes."""
        assert "charm_audit" in _CATEGORY_TOOLS[TaskCategory.BUILD]


# ===================================================================
# TestDemoGeneration
# ===================================================================


class TestDemoGeneration:
    """Tests for demo generation support in BUILD subagents."""

    def test_juju_status_in_build_tools(self) -> None:
        """juju_status is available for demo subagents to capture deployment state."""
        assert "juju_status" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_juju_run_action_in_build_tools(self) -> None:
        """juju_run_action is available for demo subagents to exercise actions."""
        assert "juju_run_action" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_juju_config_in_build_tools(self) -> None:
        """juju_config is available for demo subagents to capture config."""
        assert "juju_config" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_juju_debug_log_in_build_tools(self) -> None:
        """juju_debug_log is available for demo subagents to capture logs."""
        assert "juju_debug_log" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_demo_guidance_injected_for_demo_task(self) -> None:
        """Demo-specific guidance is injected when task title contains 'demo'."""
        from cantrip.agent.queue import AgentTask

        context = _make_context(
            task=AgentTask(
                title="Generate demo artefacts",
                category=TaskCategory.BUILD,
            ),
        )
        prompt = _build_subagent_prompt(context)
        assert "Demo guidance" in prompt
        assert "DEMO.md" in prompt
        assert "demo.sh" in prompt
        assert "TUTORIAL.md" in prompt

    def test_demo_guidance_not_injected_for_regular_build(self) -> None:
        """Regular BUILD tasks do not get demo guidance."""
        from cantrip.agent.queue import AgentTask

        context = _make_context(
            task=AgentTask(
                title="Build charm for Redis",
                category=TaskCategory.BUILD,
            ),
        )
        prompt = _build_subagent_prompt(context)
        assert "Demo guidance" not in prompt


# ===================================================================
# TestBenchmarkAndFuzzToolAllowlists
# ===================================================================


class TestAdvancedTestingToolAllowlists:
    """Tests for advanced testing tool registration in category allowlists."""

    def test_hook_benchmark_in_test_tools(self) -> None:
        assert "hook_benchmark" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_fuzz_charm_in_test_tools(self) -> None:
        assert "fuzz_charm" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_fuzz_charm_in_build_tools(self) -> None:
        assert "fuzz_charm" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_test_report_in_test_tools(self) -> None:
        assert "test_report" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_chaos_test_in_test_tools(self) -> None:
        assert "chaos_test" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_scaling_test_in_test_tools(self) -> None:
        assert "scaling_test" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_upgrade_test_in_test_tools(self) -> None:
        assert "upgrade_test" in _CATEGORY_TOOLS[TaskCategory.TEST]
