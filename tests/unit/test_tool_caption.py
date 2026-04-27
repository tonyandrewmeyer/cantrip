"""Tests for ``build_tool_caption`` — the fallback caption formatter used
by the Phase 75 inline tool blocks.

The helper lives in ``cantrip.agent.tools.base`` and is called from
both the main-agent and subagent emission paths.  A tool's own
``ToolResult.caption`` wins when set; otherwise the helper
synthesises ``tool_name(key=value)`` from the arguments using a
preferred-key list so the fallback stays informative without
per-tool configuration.
"""

from typing import Any

from cantrip.agent.tools.base import (
    Tool,
    ToolResult,
    build_tool_caption,
    build_tool_intro_caption,
)


class TestBuildToolCaption:
    """Fallback caption format covers the common tool shapes."""

    def test_explicit_caption_wins(self):
        result = ToolResult(
            success=True,
            output="",
            caption="Read 47 lines from src/foo.py",
        )
        caption = build_tool_caption("read_file", {"file_path": "src/foo.py"}, result)
        assert caption == "Read 47 lines from src/foo.py"

    def test_path_arg_surfaces_in_fallback(self):
        caption = build_tool_caption("read_file", {"path": "src/foo.py"})
        assert caption == "read_file(path=src/foo.py)"

    def test_file_path_arg_surfaces(self):
        caption = build_tool_caption("write_file", {"file_path": "src/foo.py"})
        assert caption == "write_file(file_path=src/foo.py)"

    def test_command_arg_quoted_when_it_contains_spaces(self):
        caption = build_tool_caption("run_command", {"command": "make check"})
        assert caption == 'run_command(command="make check")'

    def test_url_arg_surfaces(self):
        caption = build_tool_caption("web_fetch", {"url": "https://example.com"})
        assert caption == "web_fetch(url=https://example.com)"

    def test_falls_back_to_first_non_preferred_arg(self):
        """A tool with a non-preferred first arg still gets a useful caption."""
        caption = build_tool_caption("list_items", {"category": "BUILD"})
        assert caption == "list_items(category=BUILD)"

    def test_empty_arguments_produce_bare_call(self):
        caption = build_tool_caption("juju_status", {})
        assert caption == "juju_status()"

    def test_none_arguments_produce_bare_call(self):
        caption = build_tool_caption("juju_status", None)
        assert caption == "juju_status()"

    def test_none_and_empty_values_are_skipped(self):
        """A ``None`` or ``""`` value is skipped in favour of the next arg."""
        caption = build_tool_caption("tool", {"path": None, "command": "pwd"})
        assert caption == "tool(command=pwd)"

    def test_long_value_is_truncated(self):
        long_cmd = "x" * 200
        caption = build_tool_caption("bash", {"command": long_cmd})
        # Caption stays on one line; suffix is an ellipsis.
        assert caption.startswith("bash(command=")
        assert caption.endswith(")")
        # Surrounding quotes + ellipsis + some truncation.
        assert "…" in caption
        assert len(caption) < 90  # Rough upper bound.

    def test_newlines_are_collapsed(self):
        caption = build_tool_caption("run_command", {"command": "line1\nline2"})
        assert "\n" not in caption
        # The collapse marker is visible in the caption.
        assert " ⏎ " in caption

    def test_preferred_keys_win_over_non_preferred(self):
        """When multiple args present, the preferred-key list wins."""
        caption = build_tool_caption(
            "fake_tool",
            {"extras": "ignored", "path": "src/foo.py"},
        )
        assert caption == "fake_tool(path=src/foo.py)"

    def test_quotes_in_value_are_normalised(self):
        """Values containing quotes get wrapped + inner quotes downgraded."""
        caption = build_tool_caption("fake", {"command": 'echo "hi"'})
        # The caption must stay parseable as a one-liner — no nested
        # double-quotes confusing the reader.
        assert caption.startswith("fake(command=")
        assert caption.count('"') <= 2  # Leading + trailing only.


class _StubTool(Tool):
    """Minimal Tool used to exercise the ``intro_caption`` hook."""

    def __init__(self, *, override: str | None = None, raises: bool = False) -> None:
        self._override = override
        self._raises = raises

    @property
    def name(self) -> str:
        return "stub"

    @property
    def description(self) -> str:
        return "stub"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(success=True, output="")

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        if self._raises:
            raise ValueError("boom")
        return self._override


class TestBuildToolIntroCaption:
    """Phase 82 — the pre-call intro caption helper."""

    def test_default_returns_none_so_fallback_kicks_in(self):
        # The base class's intro_caption returns None; the helper falls
        # back to the synthesised "Running tool_name(key=value)…" form.
        caption = build_tool_intro_caption(_StubTool(), "stub", {"path": "src/foo.py"})
        assert caption == "Running stub(path=src/foo.py)…"

    def test_tool_override_wins(self):
        tool = _StubTool(override="Packing the charm…")
        caption = build_tool_intro_caption(tool, "charmcraft_pack", {"path": "."})
        assert caption == "Packing the charm…"

    def test_no_tool_falls_back_to_synthesised(self):
        # When the tool object is unknown (renderer-only callers), the
        # helper still yields a useful intro from the arguments alone.
        caption = build_tool_intro_caption(None, "web_fetch", {"url": "https://x"})
        assert caption == "Running web_fetch(url=https://x)…"

    def test_no_args_yields_bare_running_string(self):
        caption = build_tool_intro_caption(None, "juju_status", {})
        assert caption == "Running juju_status…"

    def test_tool_intro_caption_exception_falls_back(self):
        tool = _StubTool(raises=True)
        caption = build_tool_intro_caption(tool, "stub", {"path": "x"})
        # Exception in the override is swallowed; the fallback synthesis
        # still produces a useful pending caption.
        assert caption == "Running stub(path=x)…"

    def test_tool_returning_empty_string_falls_back(self):
        # An override of "" is treated as "no override" so the fallback
        # synthesis still produces a useful caption rather than a blank
        # spinner line.
        tool = _StubTool(override="")
        caption = build_tool_intro_caption(tool, "stub", {"path": "x"})
        assert caption == "Running stub(path=x)…"

    def test_long_value_truncated_in_intro(self):
        long_cmd = "x" * 200
        caption = build_tool_intro_caption(None, "bash", {"command": long_cmd})
        assert caption.startswith("Running bash(command=")
        assert caption.endswith("…)…")
        assert len(caption) < 100
