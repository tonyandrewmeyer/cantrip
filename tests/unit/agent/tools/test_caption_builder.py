"""Tests for ``build_tool_caption`` — the fallback caption formatter used
by the Phase 75 inline tool blocks.

The helper lives in ``cantrip.agent.tools.base`` and is called from
both the main-agent and subagent emission paths.  A tool's own
``ToolResult.caption`` wins when set; otherwise the helper
synthesises ``verb value`` (Phase 108.5 — formerly
``tool_name(key=value)``) from the arguments using a verb mapping
plus a preferred-key list so the fallback reads as English without
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
        """``read_file`` maps to verb ``read``; the path becomes the target."""
        caption = build_tool_caption("read_file", {"path": "src/foo.py"})
        assert caption == "read src/foo.py"

    def test_file_path_arg_surfaces(self):
        """``write_file`` maps to ``write``; ``file_path`` is in the preferred list."""
        caption = build_tool_caption("write_file", {"file_path": "src/foo.py"})
        assert caption == "write src/foo.py"

    def test_command_arg_quoted_when_it_contains_spaces(self):
        """``run_command`` maps to ``run``; spaces in the command stay quoted."""
        caption = build_tool_caption("run_command", {"command": "make check"})
        assert caption == 'run "make check"'

    def test_url_arg_surfaces(self):
        """``web_fetch`` maps to ``fetch``; URL is the target."""
        caption = build_tool_caption("web_fetch", {"url": "https://example.com"})
        assert caption == "fetch https://example.com"

    def test_falls_back_to_first_non_preferred_arg(self):
        """A tool not in the verb map keeps its bare name as the verb."""
        caption = build_tool_caption("list_items", {"category": "BUILD"})
        assert caption == "list_items BUILD"

    def test_empty_arguments_produce_bare_verb(self):
        """No arguments → just the verb (or bare tool name when not mapped)."""
        caption = build_tool_caption("juju_status", {})
        assert caption == "juju_status"

    def test_none_arguments_produce_bare_verb(self):
        """``None`` arguments behave like an empty dict."""
        caption = build_tool_caption("juju_status", None)
        assert caption == "juju_status"

    def test_none_and_empty_values_are_skipped(self):
        """A ``None`` or ``""`` value is skipped in favour of the next arg."""
        caption = build_tool_caption("tool", {"path": None, "command": "pwd"})
        assert caption == "tool pwd"

    def test_long_value_is_truncated(self):
        """Values past the cap collapse with an ellipsis but stay one line."""
        long_cmd = "x" * 200
        caption = build_tool_caption("bash", {"command": long_cmd})
        assert caption.startswith("bash ")
        assert "…" in caption
        assert len(caption) < 90  # Rough upper bound.

    def test_newlines_are_collapsed(self):
        """Multi-line commands collapse so the chat block stays one row."""
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
        assert caption == "fake_tool src/foo.py"

    def test_quotes_in_value_are_normalised(self):
        """Values containing quotes get wrapped + inner quotes downgraded."""
        caption = build_tool_caption("fake", {"command": 'echo "hi"'})
        # The caption must stay parseable as a one-liner — no nested
        # double-quotes confusing the reader.
        assert caption.startswith("fake ")
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
        """Phase 108.5: the fallback intro shape mirrors the post-call form.

        The leading ``·`` glyph the chat surface attaches is what
        tells the user the call is in flight, so the caption itself
        does not need a ``Running …`` prefix.  ``stub`` is not in
        ``_TOOL_VERBS``, so its bare name acts as the verb.
        """
        caption = build_tool_intro_caption(_StubTool(), "stub", {"path": "src/foo.py"})
        assert caption == "stub src/foo.py"

    def test_tool_override_wins(self):
        """A tool's own ``intro_caption`` keeps its English-prose form."""
        tool = _StubTool(override="Packing the charm…")
        caption = build_tool_intro_caption(tool, "charmcraft_pack", {"path": "."})
        assert caption == "Packing the charm…"

    def test_no_tool_falls_back_to_synthesised(self):
        """A renderer-only caller still gets a useful verb-target intro."""
        caption = build_tool_intro_caption(None, "web_fetch", {"url": "https://x"})
        assert caption == "fetch https://x"

    def test_no_args_yields_bare_verb(self):
        """No arguments → just the verb (no trailing ``…``)."""
        caption = build_tool_intro_caption(None, "juju_status", {})
        assert caption == "juju_status"

    def test_tool_intro_caption_exception_falls_back(self):
        """Exception in the override is swallowed; fallback still fires."""
        tool = _StubTool(raises=True)
        caption = build_tool_intro_caption(tool, "stub", {"path": "x"})
        assert caption == "stub x"

    def test_tool_returning_empty_string_falls_back(self):
        """Empty-string override is treated as "no override"."""
        tool = _StubTool(override="")
        caption = build_tool_intro_caption(tool, "stub", {"path": "x"})
        assert caption == "stub x"

    def test_long_value_truncated_in_intro(self):
        """Long values still truncate cleanly under the new shape."""
        long_cmd = "x" * 200
        caption = build_tool_intro_caption(None, "bash", {"command": long_cmd})
        assert caption.startswith("bash ")
        assert "…" in caption
        assert len(caption) < 100
