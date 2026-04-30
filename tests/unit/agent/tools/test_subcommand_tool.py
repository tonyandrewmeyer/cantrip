"""Tests for the ``SubcommandTool`` bundle wrapper and dispatch helpers."""

from __future__ import annotations

from typing import Any

import pytest

from cantrip.agent.tools import (
    SubcommandTool,
    Tool,
    ToolResult,
    expand_leaves,
    resolve_subcommand,
)


class _Echo(Tool):
    """Minimal leaf that echoes its kwargs back via the result data."""

    def __init__(self, name: str, description: str = "echo") -> None:
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            success=True,
            output=str(kwargs),
            data=dict(kwargs),
            caption=f"{self._name} ok",
        )


def _bundle() -> SubcommandTool:
    return SubcommandTool(
        "demo",
        "Demo bundle.",
        {
            "alpha": _Echo("demo_alpha"),
            "beta": _Echo("demo_beta"),
        },
    )


class TestSubcommandTool:
    def test_rejects_empty_subcommands(self) -> None:
        with pytest.raises(ValueError, match="at least one subcommand"):
            SubcommandTool("empty", "no leaves", {})

    def test_parameters_lists_subcommands(self) -> None:
        params = _bundle().parameters
        assert params["properties"]["subcommand"]["enum"] == ["alpha", "beta"]
        assert "subcommand" in params["required"]
        assert params["additionalProperties"] is True

    def test_description_includes_each_leaf_schema(self) -> None:
        desc = _bundle().description
        assert "## alpha" in desc
        assert "## beta" in desc
        # The leaf's own JSON parameter schema must be present so the
        # LLM can pick the right argument keys without seeing the
        # leaf as a separate tool entry.
        assert '"value"' in desc

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_subcommand(self) -> None:
        bundle = _bundle()
        result = await bundle.execute(subcommand="alpha", value="hi")
        assert result.success
        assert result.data == {"value": "hi"}
        assert result.caption == "demo_alpha ok"

    @pytest.mark.asyncio
    async def test_execute_unknown_subcommand_returns_error(self) -> None:
        result = await _bundle().execute(subcommand="missing", value="x")
        assert not result.success
        assert "unknown subcommand" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_missing_subcommand_returns_error(self) -> None:
        result = await _bundle().execute()
        assert not result.success
        assert "missing required 'subcommand'" in (result.error or "")


class TestExpandLeaves:
    def test_expand_includes_bundle_and_leaves(self) -> None:
        bundle = _bundle()
        standalone = _Echo("solo")
        out = expand_leaves([bundle, standalone])
        names = [t.name for t in out]
        # The bundle entry comes first, then its leaves; standalone passes through.
        assert names == ["demo", "demo_alpha", "demo_beta", "solo"]


class TestResolveSubcommand:
    def _tool_map(self) -> dict[str, Tool]:
        return {t.name: t for t in expand_leaves([_bundle(), _Echo("solo")])}

    def test_bundle_call_resolves_to_leaf(self) -> None:
        tm = self._tool_map()
        name, args = resolve_subcommand(tm, "demo", {"subcommand": "alpha", "value": "hi"})
        assert name == "demo_alpha"
        assert args == {"value": "hi"}

    def test_unknown_subcommand_passes_through_to_bundle(self) -> None:
        tm = self._tool_map()
        # When the subcommand is unknown, ``resolve_subcommand`` keeps
        # the bundle name so the bundle's own ``execute`` produces the
        # canonical error message rather than us raising here.
        name, args = resolve_subcommand(tm, "demo", {"subcommand": "missing", "value": "hi"})
        assert name == "demo"
        assert args == {"subcommand": "missing", "value": "hi"}

    def test_direct_leaf_call_passes_through(self) -> None:
        tm = self._tool_map()
        # Hallucinated direct leaf call (e.g. a skill file says
        # ``demo_alpha(...)``) — leaf is in tool_map via expand_leaves
        # so it dispatches normally without rewrite.
        name, args = resolve_subcommand(tm, "demo_alpha", {"value": "hi"})
        assert name == "demo_alpha"
        assert args == {"value": "hi"}

    def test_non_bundle_tool_passes_through(self) -> None:
        tm = self._tool_map()
        name, args = resolve_subcommand(tm, "solo", {"value": "hi"})
        assert name == "solo"
        assert args == {"value": "hi"}

    def test_unknown_tool_passes_through(self) -> None:
        tm = self._tool_map()
        name, args = resolve_subcommand(tm, "nope", {"foo": "bar"})
        assert name == "nope"
        assert args == {"foo": "bar"}


class TestRegisteredBundles:
    """Smoke tests that the four real families are bundled correctly."""

    def test_juju_bundle_present(self) -> None:
        from cantrip.agent.tools import build_tools

        names = {t.name for t in build_tools()}
        # The bundle is exposed; the legacy leaf names are not (they
        # only show up via ``expand_leaves`` when building the
        # dispatch map).
        assert "juju" in names
        assert "git" in names
        assert "gh" in names
        assert "juju_status" not in names
        assert "git_commit" not in names
        assert "gh_pr_create" not in names

    def test_dispatch_map_still_finds_leaves(self) -> None:
        from cantrip.agent.tools import build_tools

        tools = build_tools()
        tool_map = {t.name: t for t in expand_leaves(tools)}
        # Permission rules and audit logs are written against leaf
        # names; if these stop appearing in the dispatch map the
        # whole gate stack starts denying-by-default.
        for leaf in (
            "juju_status",
            "juju_deploy",
            "git_commit",
            "git_status",
            "gh_pr_create",
        ):
            assert leaf in tool_map, leaf

    def test_llm_facing_count_under_openai_cap(self) -> None:
        """Sanity check: the static toolset is well under OpenAI's 128 cap.

        The whole point of the bundling work — if a future change
        re-introduces 30+ standalone tools and trips this, we'd
        rather catch it here than in production traffic to OpenRouter.
        """
        from cantrip.agent.tools import build_tools

        assert len(build_tools()) <= 100
