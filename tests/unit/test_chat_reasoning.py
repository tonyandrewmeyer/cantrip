"""Tests for reasoning / chain-of-thought rendering in the chat widget.

Phase 77.1 — Claude's extended thinking and OpenAI-compatible
``reasoning_content`` (Kimi K2, DeepSeek-R1 family) both land on
``ChatMessage.reasoning`` and surface as a dim preamble before the
final answer.  These tests cover the render path and the
``set_reasoning`` helper the streaming TUI loop uses to attach
reasoning after the text stream completes.
"""

from cantrip.tui.widgets.chat import (
    ChatMessage,
    MessageRole,
    MessageWidget,
)


class TestReasoningRender:
    """``_render_body`` prepends reasoning when present."""

    def test_no_reasoning_renders_content_only(self):
        widget = MessageWidget(
            ChatMessage(role=MessageRole.ASSISTANT, content="The answer is 42.")
        )
        rendered = widget._render_body()
        assert "💭 thinking" not in rendered
        assert "The answer is 42." in rendered

    def test_reasoning_renders_before_content(self):
        widget = MessageWidget(
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content="The answer is 42.",
                reasoning="The user asked a question; 42 is canonical.",
            )
        )
        rendered = widget._render_body()
        assert "💭 thinking" in rendered
        assert "The user asked a question" in rendered
        # Reasoning preamble appears before the content line.
        assert rendered.index("💭 thinking") < rendered.index("The answer is 42.")
        # Wrapped in dim italic so the answer reads as the primary content.
        assert "[dim italic]" in rendered

    def test_reasoning_escapes_rich_markup(self):
        """Reasoning text must not be parsed as Rich tags.

        A model's chain-of-thought that happens to contain ``[...]``
        should not flip styles on downstream content.
        """
        widget = MessageWidget(
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content="answer",
                reasoning="I should [b]think[/b] about this carefully.",
            )
        )
        rendered = widget._render_body()
        assert r"\[b]" in rendered
        assert r"\[/b]" in rendered

    def test_content_escapes_textual_closing_tags(self):
        """Plain message content with bracket tokens must not crash.

        ``/help`` documents ``/model [provider[/model]]`` — the literal
        ``[/model]`` substring inside a system message used to be
        interpreted by Textual's markup parser as an unbalanced
        closing tag and crashed the entire TUI on the next layout
        pass.  The plain (non-Markdown) render path must escape the
        body before concatenating into a markup string.
        """
        widget = MessageWidget(
            ChatMessage(
                role=MessageRole.SYSTEM,
                content="Usage: `/model [provider[/model]]`",
            )
        )
        rendered = widget._render_body()
        # ``rich_escape`` escapes the closing-tag form because that's
        # what crashes the parser; opening brackets are left alone.
        # The literal ``[/model]`` substring must show up escaped.
        assert r"\[/model]" in rendered

        # Crashed-only-when-rendered: feed the result through Textual's
        # markup parser to prove the tag is no longer treated as a
        # closing tag.  Before the fix this raised MarkupError.
        from textual.content import Content

        Content.from_markup(rendered)


class TestSetReasoning:
    """``ChatWidget.set_reasoning`` attaches reasoning to an existing widget."""

    def test_set_reasoning_updates_message(self):
        widget = MessageWidget(ChatMessage(role=MessageRole.ASSISTANT, content="Hello"))
        # ChatWidget.set_reasoning mutates the widget's message in place
        # and re-renders; _rerender silently no-ops when the static body
        # hasn't been composed yet, which is fine for this unit test.
        from cantrip.tui.widgets.chat import ChatWidget

        ChatWidget.set_reasoning(ChatWidget.__new__(ChatWidget), widget, "Because 42.")
        assert widget.message.reasoning == "Because 42."

    def test_set_reasoning_empty_string_leaves_field_unset(self):
        widget = MessageWidget(ChatMessage(role=MessageRole.ASSISTANT, content="Hello"))
        from cantrip.tui.widgets.chat import ChatWidget

        ChatWidget.set_reasoning(ChatWidget.__new__(ChatWidget), widget, "")
        assert widget.message.reasoning == ""
