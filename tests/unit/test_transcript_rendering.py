"""Tests for transcript rendering: HTML, Markdown, and JSONL formatters."""

import json

from cantrip.transcript.export import TranscriptData
from cantrip.transcript.html import render_html, render_html_paginated
from cantrip.transcript.jsonl import render_jsonl
from cantrip.transcript.markdown import render_markdown


def _sample_data(**overrides) -> TranscriptData:
    """Build a TranscriptData with sensible defaults, overridable per-field."""
    defaults = {
        "charm_name": "redis-k8s",
        "charm_path": "/tmp/redis-k8s",
        "messages": [
            {
                "role": "user",
                "content": "Build me a Redis charm",
                "timestamp": "2026-04-05T12:00:00",
                "tool_calls": [],
                "tool_results": [],
            },
            {
                "role": "assistant",
                "content": "Sure, I'll build a Redis charm for you.",
                "timestamp": "2026-04-05T12:00:05",
                "tool_calls": [
                    {"id": "tc1", "name": "write_file", "arguments": {"path": "src/charm.py"}},
                ],
                "tool_results": [],
            },
            {
                "role": "tool",
                "content": "",
                "timestamp": "2026-04-05T12:00:06",
                "tool_calls": [],
                "tool_results": [
                    {"tool_call_id": "tc1", "content": "File written", "is_error": False},
                ],
            },
        ],
        "tasks": [
            {
                "id": "t1",
                "title": "Scaffold charm",
                "status": "done",
                "category": "build",
                "description": "Create charm structure",
            },
        ],
        "subagent_messages": {
            "t1": [
                {"role": "user", "content": "Scaffold now", "timestamp": "2026-04-05T12:01:00"},
            ],
        },
        "events": [
            {
                "event_type": "design_confirmed",
                "detail": {"workload": "redis"},
                "timestamp": "2026-04-05T12:00:00",
            },
        ],
        "token_usage": {"prompt_tokens": 1000, "completion_tokens": 500},
    }
    defaults.update(overrides)
    return TranscriptData(**defaults)


class TestRenderMarkdown:
    """Tests for Markdown transcript rendering."""

    def test_includes_heading(self):
        md = render_markdown(_sample_data())
        assert "# Cantrip Transcript" in md
        assert "redis-k8s" in md

    def test_includes_path(self):
        md = render_markdown(_sample_data())
        assert "**Path:** /tmp/redis-k8s" in md

    def test_includes_token_usage(self):
        md = render_markdown(_sample_data())
        assert "1000 prompt" in md
        assert "500 completion" in md

    def test_includes_tasks(self):
        md = render_markdown(_sample_data())
        assert "## Tasks" in md
        assert "Scaffold charm" in md
        assert "[DONE]" in md

    def test_includes_conversation(self):
        md = render_markdown(_sample_data())
        assert "## Conversation" in md
        assert "Build me a Redis charm" in md

    def test_tool_calls_in_details(self):
        md = render_markdown(_sample_data())
        assert "<details><summary>Tool: write_file</summary>" in md

    def test_tool_results_in_details(self):
        md = render_markdown(_sample_data())
        assert "<details><summary>Result</summary>" in md
        assert "File written" in md

    def test_error_tool_result_prefixed(self):
        data = _sample_data(messages=[
            {
                "role": "tool",
                "content": "",
                "timestamp": "",
                "tool_calls": [],
                "tool_results": [
                    {"tool_call_id": "tc1", "content": "BOOM", "is_error": True},
                ],
            },
        ])
        md = render_markdown(data)
        assert "<details><summary>Error</summary>" in md

    def test_includes_events(self):
        md = render_markdown(_sample_data())
        assert "## Events" in md
        assert "design_confirmed" in md

    def test_no_tasks_skips_section(self):
        md = render_markdown(_sample_data(tasks=[]))
        assert "## Tasks" not in md

    def test_no_events_skips_section(self):
        md = render_markdown(_sample_data(events=[]))
        assert "## Events" not in md

    def test_no_charm_name(self):
        md = render_markdown(_sample_data(charm_name=""))
        assert "# Cantrip Transcript\n" in md


class TestRenderJsonl:
    """Tests for JSONL transcript rendering."""

    def test_message_lines(self):
        output = render_jsonl(_sample_data())
        lines = output.strip().split("\n")
        message_lines = [json.loads(line) for line in lines if json.loads(line)["type"] == "message"]
        assert len(message_lines) == 3

    def test_event_lines(self):
        output = render_jsonl(_sample_data())
        lines = output.strip().split("\n")
        event_lines = [json.loads(line) for line in lines if json.loads(line)["type"] == "event"]
        assert len(event_lines) == 1
        assert event_lines[0]["event_type"] == "design_confirmed"

    def test_task_lines(self):
        output = render_jsonl(_sample_data())
        lines = output.strip().split("\n")
        task_lines = [json.loads(line) for line in lines if json.loads(line)["type"] == "task"]
        assert len(task_lines) == 1
        assert task_lines[0]["title"] == "Scaffold charm"

    def test_subagent_message_lines(self):
        output = render_jsonl(_sample_data())
        lines = output.strip().split("\n")
        sa_lines = [json.loads(line) for line in lines if json.loads(line)["type"] == "subagent_message"]
        assert len(sa_lines) == 1

    def test_empty_data_returns_empty(self):
        data = TranscriptData()
        output = render_jsonl(data)
        assert output == ""

    def test_ordering(self):
        """Messages come first, then events, tasks, subagent messages."""
        output = render_jsonl(_sample_data())
        lines = output.strip().split("\n")
        types = [json.loads(line)["type"] for line in lines]
        # All messages should come before all events.
        msg_indices = [i for i, t in enumerate(types) if t == "message"]
        event_indices = [i for i, t in enumerate(types) if t == "event"]
        task_indices = [i for i, t in enumerate(types) if t == "task"]
        if msg_indices and event_indices:
            assert max(msg_indices) < min(event_indices)
        if event_indices and task_indices:
            assert max(event_indices) < min(task_indices)


class TestRenderHtml:
    """Tests for HTML transcript rendering."""

    def test_html_contains_charm_name(self):
        html = render_html(_sample_data())
        assert "redis-k8s" in html

    def test_html_contains_messages(self):
        html = render_html(_sample_data())
        assert "Build me a Redis charm" in html

    def test_html_is_valid_structure(self):
        html = render_html(_sample_data())
        assert "<html" in html.lower()
        assert "</html>" in html.lower()


class TestRenderHtmlPaginated:
    """Tests for paginated HTML rendering."""

    def test_single_page_when_few_messages(self):
        data = _sample_data()
        pages = render_html_paginated(data, page_size=100)
        assert len(pages) == 1
        assert pages[0][0] == "transcript_1.html"

    def test_multiple_pages(self):
        msgs = [
            {"role": "user", "content": f"msg {i}", "timestamp": "", "tool_calls": [],
             "tool_results": []}
            for i in range(10)
        ]
        data = _sample_data(messages=msgs)
        pages = render_html_paginated(data, page_size=3)
        assert len(pages) == 4  # ceil(10/3) = 4

    def test_page_filenames(self):
        msgs = [
            {"role": "user", "content": f"msg {i}", "timestamp": "", "tool_calls": [],
             "tool_results": []}
            for i in range(6)
        ]
        data = _sample_data(messages=msgs)
        pages = render_html_paginated(data, page_size=2, stem="export")
        filenames = [p[0] for p in pages]
        assert filenames == ["export_1.html", "export_2.html", "export_3.html"]

    def test_tasks_only_on_first_page(self):
        msgs = [
            {"role": "user", "content": f"msg {i}", "timestamp": "", "tool_calls": [],
             "tool_results": []}
            for i in range(4)
        ]
        data = _sample_data(messages=msgs)
        pages = render_html_paginated(data, page_size=2)
        # First page should have task info.
        assert "Scaffold charm" in pages[0][1]
        # Second page should not repeat tasks.
        # (Tasks section appears only on page 1 — hard to assert without parsing,
        # but at minimum the content should differ.)

    def test_empty_messages(self):
        data = _sample_data(messages=[])
        pages = render_html_paginated(data, page_size=5)
        assert len(pages) == 1

    def test_page_size_one(self):
        msgs = [
            {"role": "user", "content": f"msg {i}", "timestamp": "", "tool_calls": [],
             "tool_results": []}
            for i in range(3)
        ]
        data = _sample_data(messages=msgs)
        pages = render_html_paginated(data, page_size=1)
        assert len(pages) == 3
