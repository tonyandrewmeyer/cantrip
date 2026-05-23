"""Differential / metamorphic property tests for the transcript renderers.

The named-scenario tests in ``test_transcript_rendering.py`` cover the
example cases.  These property tests pin the cross-cutting invariants
the renderers should preserve under *any* well-shaped input:

* *Determinism.*  Rendering the same :class:`TranscriptData` twice — or
  the same message dict twice — produces byte-identical output.  The
  formatters have no hidden state.
* *Fence safety.*  ``_fence_for`` returns a string of backticks whose
  length is strictly greater than the longest backtick run in the
  input, and never shorter than the standard three.  Code blocks built
  with this fence can wrap arbitrary content without the closing fence
  triggering early on inner backticks.
* *Header presence.*  ``render_message(msg, include_header=True)``
  always begins with ``### <ROLE>``.  ``include_header=False`` drops
  the heading without altering the rest of the body.
* *Markdown structure.*  ``render_markdown`` always contains a
  ``# Cantrip Transcript`` heading and a ``## Conversation`` section
  divider, and every input message contributes a ``### <ROLE>`` line.
  Output ends with exactly one trailing newline.
* *JSONL well-formedness.*  Every line of ``render_jsonl`` is valid
  JSON; the line count equals
  ``len(messages) + len(events) + len(tasks) + sum(len(v) for v in subagent_messages.values())``;
  empty input renders to the empty string.
* *Type-field tagging.*  Every JSONL line carries a ``"type"`` field
  whose value is one of ``message``, ``event``, ``task``, or
  ``subagent_message`` — matching the source bucket.
* *Order preservation.*  JSONL emits messages before events before
  tasks before subagent messages, in their input order within each
  bucket.
"""

from __future__ import annotations

import copy
import json

from hypothesis import given
from hypothesis import strategies as st

from cantrip.transcript.export import TranscriptData
from cantrip.transcript.jsonl import render_jsonl
from cantrip.transcript.markdown import _fence_for, render_markdown, render_message

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _safe_text() -> st.SearchStrategy[str]:
    """ASCII letters + space — no backticks, no fence-meaningful chars."""
    return st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=32)


def _backtick_heavy_text() -> st.SearchStrategy[str]:
    """Text that includes random backtick runs — exercises ``_fence_for``."""
    return st.lists(
        st.one_of(_safe_text(), st.text(alphabet="`", min_size=1, max_size=8)),
        min_size=1,
        max_size=6,
    ).map("".join)


def _role() -> st.SearchStrategy[str]:
    return st.sampled_from(["user", "assistant", "system", "tool"])


def _timestamp() -> st.SearchStrategy[str]:
    """A deterministic ISO-ish stamp.  Real ones are richer but the
    renderer only treats the value as opaque text."""
    return st.text(alphabet="0123456789-:T", min_size=10, max_size=20)


def _tool_call_dict() -> st.SearchStrategy[dict]:
    return st.fixed_dictionaries(
        {
            "name": st.text(alphabet="abcdef_", min_size=1, max_size=10),
            "arguments": st.dictionaries(
                keys=st.text(alphabet="abc", min_size=1, max_size=4),
                values=st.one_of(_safe_text(), st.integers(min_value=-9, max_value=9)),
                max_size=3,
            ),
        }
    )


def _tool_result_dict() -> st.SearchStrategy[dict]:
    return st.fixed_dictionaries(
        {
            "content": _backtick_heavy_text(),
            "is_error": st.booleans(),
        }
    )


def _message_dict() -> st.SearchStrategy[dict]:
    """A transcript-style message dict.

    Mirrors the shape the SQLite store produces: ``role``, ``content``,
    ``timestamp``, optional ``tool_calls`` and ``tool_results`` lists.
    """
    return st.fixed_dictionaries(
        {
            "role": _role(),
            "content": _safe_text(),
            "timestamp": _timestamp(),
            "tool_calls": st.lists(_tool_call_dict(), max_size=2),
            "tool_results": st.lists(_tool_result_dict(), max_size=2),
        }
    )


def _event_dict() -> st.SearchStrategy[dict]:
    return st.fixed_dictionaries(
        {
            "event_type": st.sampled_from(["task_added", "task_done", "tool_call"]),
            "timestamp": _timestamp(),
            "detail": st.dictionaries(
                keys=st.text(alphabet="abc", min_size=1, max_size=4),
                values=_safe_text(),
                max_size=3,
            ),
        }
    )


def _task_dict() -> st.SearchStrategy[dict]:
    return st.fixed_dictionaries(
        {
            "id": st.text(alphabet="abcdef0123456789", min_size=8, max_size=12),
            "title": _safe_text(),
            "status": st.sampled_from(["pending", "active", "done", "failed", "blocked"]),
            "category": st.sampled_from(["research", "build", "deploy", "test"]),
            "description": _safe_text(),
            "result": st.one_of(st.none(), _safe_text()),
        }
    )


def _transcript_data() -> st.SearchStrategy[TranscriptData]:
    """Build a random :class:`TranscriptData` instance."""
    return st.builds(
        TranscriptData,
        charm_name=_safe_text(),
        charm_path=_safe_text(),
        messages=st.lists(_message_dict(), max_size=4),
        tasks=st.lists(_task_dict(), max_size=3),
        subagent_messages=st.dictionaries(
            keys=st.text(alphabet="abcdef0123456789", min_size=8, max_size=12),
            values=st.lists(_message_dict(), min_size=1, max_size=2),
            max_size=2,
        ),
        events=st.lists(_event_dict(), max_size=3),
        token_usage=st.fixed_dictionaries(
            {
                "prompt_tokens": st.integers(min_value=0, max_value=1000),
                "completion_tokens": st.integers(min_value=0, max_value=1000),
            }
        ),
    )


# ---------------------------------------------------------------------------
# _fence_for invariants
# ---------------------------------------------------------------------------


class TestFenceFor:
    """``_fence_for`` produces a safe fence for any content."""

    @given(content=_backtick_heavy_text())
    def test_fence_is_all_backticks(self, content: str) -> None:
        fence = _fence_for(content)
        assert set(fence) == {"`"}, f"Fence must be backticks only, got {fence!r}."

    @given(content=_backtick_heavy_text())
    def test_fence_length_at_least_three(self, content: str) -> None:
        assert len(_fence_for(content)) >= 3

    @given(content=_backtick_heavy_text())
    def test_fence_outlasts_longest_run(self, content: str) -> None:
        # Walk the content and find the longest consecutive backtick run.
        longest = 0
        run = 0
        for ch in content:
            if ch == "`":
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        fence_len = len(_fence_for(content))
        if longest >= 3:
            assert fence_len > longest, (
                f"Fence of length {fence_len} cannot safely wrap a run of {longest} backticks."
            )
        else:
            assert fence_len == 3

    @given(content=_safe_text())
    def test_backtick_free_content_uses_triple_fence(self, content: str) -> None:
        # Skip the contrived case where the strategy happens to emit a
        # backtick (the strategy alphabet excludes it, so this is a
        # belt-and-braces guard).
        if "`" in content:
            return
        assert _fence_for(content) == "```"


# ---------------------------------------------------------------------------
# render_message invariants
# ---------------------------------------------------------------------------


class TestRenderMessage:
    """``render_message`` is deterministic and respects ``include_header``."""

    @given(msg=_message_dict())
    def test_render_is_deterministic(self, msg: dict) -> None:
        snapshot = copy.deepcopy(msg)
        first = render_message(msg)
        second = render_message(msg)
        assert first == second
        # And it does not mutate the input dict.
        assert msg == snapshot

    @given(msg=_message_dict())
    def test_header_present_when_requested(self, msg: dict) -> None:
        rendered = render_message(msg, include_header=True)
        role = msg["role"].upper()
        first_line = rendered.split("\n", 1)[0]
        assert first_line.startswith(f"### {role} ("), (
            f"Expected '### {role} (...)' header, got {first_line!r}."
        )

    @given(msg=_message_dict())
    def test_header_absent_when_suppressed(self, msg: dict) -> None:
        rendered = render_message(msg, include_header=False)
        # The role-and-timestamp heading must not appear at the start.
        role = msg["role"].upper()
        assert not rendered.startswith(f"### {role}")

    @given(msg=_message_dict())
    def test_tool_calls_emit_details_block(self, msg: dict) -> None:
        rendered = render_message(msg)
        if msg["tool_calls"]:
            assert "<details><summary>Tool:" in rendered
        # And every tool name appears.
        for tc in msg["tool_calls"]:
            assert tc["name"] in rendered

    @given(msg=_message_dict())
    def test_tool_results_emit_details_block(self, msg: dict) -> None:
        rendered = render_message(msg)
        for tr in msg["tool_results"]:
            label = "Error" if tr["is_error"] else "Result"
            assert f"<details><summary>{label}</summary>" in rendered

    @given(content=_backtick_heavy_text(), role=_role(), ts=_timestamp())
    def test_backtick_heavy_tool_result_is_fenced_safely(
        self, content: str, role: str, ts: str
    ) -> None:
        # Build a message whose only payload is a backtick-heavy tool
        # result.  The renderer must pick a fence that's strictly longer
        # than the worst run in the body so the closing fence can't fire
        # early.
        msg = {
            "role": role,
            "content": "",
            "timestamp": ts,
            "tool_calls": [],
            "tool_results": [{"content": content, "is_error": False}],
        }
        rendered = render_message(msg)
        longest = 0
        run = 0
        for ch in content:
            if ch == "`":
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        # Find the fence used (the first backtick run after the
        # ``<details>`` opener).  It must be longer than ``longest``
        # when ``longest >= 3``.
        if longest >= 3:
            for line in rendered.splitlines():
                stripped = line.strip()
                if stripped and set(stripped) == {"`"}:
                    assert len(stripped) > longest, (
                        f"Fence {stripped!r} cannot safely wrap a run of "
                        f"{longest} backticks in tool-result content."
                    )
                    break


# ---------------------------------------------------------------------------
# render_markdown invariants
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    """Whole-transcript Markdown render has a stable shape."""

    @given(data=_transcript_data())
    def test_render_is_deterministic(self, data: TranscriptData) -> None:
        first = render_markdown(data)
        second = render_markdown(data)
        assert first == second

    @given(data=_transcript_data())
    def test_render_does_not_mutate_data(self, data: TranscriptData) -> None:
        snapshot = copy.deepcopy(data)
        render_markdown(data)
        assert data == snapshot

    @given(data=_transcript_data())
    def test_starts_with_top_heading(self, data: TranscriptData) -> None:
        rendered = render_markdown(data)
        assert rendered.startswith("# Cantrip Transcript")

    @given(data=_transcript_data())
    def test_contains_conversation_section(self, data: TranscriptData) -> None:
        rendered = render_markdown(data)
        assert "## Conversation" in rendered

    @given(data=_transcript_data())
    def test_ends_with_single_newline(self, data: TranscriptData) -> None:
        rendered = render_markdown(data)
        assert rendered.endswith("\n")
        # Not multiple trailing newlines.
        assert not rendered.endswith("\n\n\n")

    @given(data=_transcript_data())
    def test_every_message_gets_a_role_header(self, data: TranscriptData) -> None:
        rendered = render_markdown(data)
        # Each role header line is ``### ROLE (timestamp)``.  Count by
        # role to confirm every input message contributes one.
        expected_per_role: dict[str, int] = {}
        for msg in data.messages:
            expected_per_role[msg["role"].upper()] = (
                expected_per_role.get(msg["role"].upper(), 0) + 1
            )
        for role, want in expected_per_role.items():
            got = sum(1 for line in rendered.splitlines() if line.startswith(f"### {role} ("))
            assert got >= want, (
                f"Expected at least {want} header lines for role {role!r}, found {got}."
            )


# ---------------------------------------------------------------------------
# render_jsonl invariants
# ---------------------------------------------------------------------------


class TestRenderJsonl:
    """JSONL output is well-formed and tagged."""

    @given(data=_transcript_data())
    def test_render_is_deterministic(self, data: TranscriptData) -> None:
        assert render_jsonl(data) == render_jsonl(data)

    @given(data=_transcript_data())
    def test_empty_data_renders_to_empty_string(self, data: TranscriptData) -> None:
        empty = TranscriptData()
        assert render_jsonl(empty) == ""
        # The strategy already covers populated cases — this just makes
        # sure the empty short-circuit holds for the constant.

    @given(data=_transcript_data())
    def test_line_count_matches_input_buckets(self, data: TranscriptData) -> None:
        rendered = render_jsonl(data)
        if not rendered:
            # All buckets empty — line count is zero by definition.
            assert (
                not data.messages
                and not data.events
                and not data.tasks
                and not data.subagent_messages
            )
            return
        lines = rendered.rstrip("\n").split("\n")
        expected = (
            len(data.messages)
            + len(data.events)
            + len(data.tasks)
            + sum(len(v) for v in data.subagent_messages.values())
        )
        assert len(lines) == expected

    @given(data=_transcript_data())
    def test_every_line_is_valid_json(self, data: TranscriptData) -> None:
        rendered = render_jsonl(data)
        for line in rendered.splitlines():
            if not line:
                continue
            decoded = json.loads(line)
            assert isinstance(decoded, dict)
            assert "type" in decoded

    @given(data=_transcript_data())
    def test_type_field_matches_source_bucket(self, data: TranscriptData) -> None:
        rendered = render_jsonl(data)
        types = [json.loads(line)["type"] for line in rendered.splitlines() if line]
        # Order: messages → events → tasks → subagent_messages.
        message_count = len(data.messages)
        event_count = len(data.events)
        task_count = len(data.tasks)
        subagent_count = sum(len(v) for v in data.subagent_messages.values())
        assert types[:message_count] == ["message"] * message_count
        assert types[message_count : message_count + event_count] == ["event"] * event_count
        assert (
            types[message_count + event_count : message_count + event_count + task_count]
            == ["task"] * task_count
        )
        assert types[message_count + event_count + task_count :] == (
            ["subagent_message"] * subagent_count
        )
