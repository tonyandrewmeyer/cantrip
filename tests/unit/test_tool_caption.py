"""Tests for ``build_tool_caption`` — the fallback caption formatter used
by the Phase 75 inline tool blocks.

The helper lives in ``cantrip.agent.tools.base`` and is called from
both the main-agent and subagent emission paths.  A tool's own
``ToolResult.caption`` wins when set; otherwise the helper
synthesises ``tool_name(key=value)`` from the arguments using a
preferred-key list so the fallback stays informative without
per-tool configuration.
"""

from cantrip.agent.tools.base import ToolResult, build_tool_caption


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
