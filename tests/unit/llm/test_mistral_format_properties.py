"""Property-based tests for the Mistral payload rewriter and parser.

The example-based tests in ``test_mistral_format.py`` cover named cases
(simple assistant + tool fold, no-tool-calls passthrough, JSON-invalid
markers, etc.).  These property tests pin the round-trip contract
across randomly shaped conversations and randomly garbled inputs:

* *No input mutation.*  ``rewrite_for_mistral`` returns a new list of
  new :class:`Message` instances; the original list and its messages
  are untouched.
* *Never grows.*  ``len(rewrite_for_mistral(messages)) <= len(messages)``
  — the rewriter only collapses TOOL messages into the preceding
  ASSISTANT, never inserts new ones.
* *Folded assistants carry the marker.*  Any output message that
  consumed at least one following TOOL message has
  ``[TOOL_CALLS]...[/TOOL_CALLS]`` in its ``content`` and an empty
  ``tool_calls`` list.
* *Round-trip recovers tool calls.*  For every ASSISTANT message in the
  input that had tool calls and was followed by at least one TOOL
  message, ``parse_mistral_tool_call_content`` on the rewritten
  content recovers tool calls with the original names and arguments.
* *Parser is identity on marker-free content.*  Content with no
  ``[TOOL_CALLS]`` substring round-trips through the parser unchanged.
* *Parser fails safe on garbage.*  Markers wrapping non-JSON or
  non-array payloads return ``([], original_content)`` — the parser
  never raises and never silently swallows the input.
* *Parser is idempotent on the remainder.*  After one parse, the
  returned remainder has no parseable tool calls left in it.
"""

from __future__ import annotations

import copy
import json

from hypothesis import given
from hypothesis import strategies as st

from cantrip.llm.base import Message, Role, ToolCall, ToolResult
from cantrip.llm.mistral_format import (
    parse_mistral_tool_call_content,
    rewrite_for_mistral,
)

_TOOL_CALLS_OPEN = "[TOOL_CALLS]"
_TOOL_CALLS_CLOSE = "[/TOOL_CALLS]"
_TOOL_RESULTS_OPEN = "[TOOL_RESULTS]"
_TOOL_RESULTS_CLOSE = "[/TOOL_RESULTS]"

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _short_text() -> st.SearchStrategy[str]:
    """Plain ASCII text that won't accidentally contain Mistral markers."""
    return st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz ",
        min_size=0,
        max_size=24,
    )


def _tool_name() -> st.SearchStrategy[str]:
    return st.text(alphabet="abcdef_", min_size=1, max_size=10)


def _call_id() -> st.SearchStrategy[str]:
    return st.text(alphabet="abcdef0123456789", min_size=4, max_size=12)


def _arguments_dict() -> st.SearchStrategy[dict[str, object]]:
    """A small JSON-safe arguments dict."""
    return st.dictionaries(
        keys=st.text(alphabet="abcdef_", min_size=1, max_size=6),
        values=st.one_of(
            st.integers(min_value=-100, max_value=100),
            st.booleans(),
            _short_text(),
        ),
        max_size=4,
    )


def _tool_call() -> st.SearchStrategy[ToolCall]:
    return st.builds(ToolCall, id=_call_id(), name=_tool_name(), arguments=_arguments_dict())


def _tool_result() -> st.SearchStrategy[ToolResult]:
    return st.builds(ToolResult, tool_call_id=_call_id(), content=_short_text())


def _user_message() -> st.SearchStrategy[Message]:
    return st.builds(Message, role=st.just(Role.USER), content=_short_text())


def _system_message() -> st.SearchStrategy[Message]:
    return st.builds(Message, role=st.just(Role.SYSTEM), content=_short_text())


@st.composite
def _assistant_with_calls(draw: st.DrawFn) -> Message:
    """An assistant message that has at least one tool call."""
    calls = draw(st.lists(_tool_call(), min_size=1, max_size=3))
    return Message(role=Role.ASSISTANT, content=draw(_short_text()), tool_calls=calls)


@st.composite
def _assistant_plain(draw: st.DrawFn) -> Message:
    return Message(role=Role.ASSISTANT, content=draw(_short_text()))


@st.composite
def _tool_message(draw: st.DrawFn) -> Message:
    results = draw(st.lists(_tool_result(), min_size=1, max_size=3))
    return Message(role=Role.TOOL, content="", tool_results=results)


@st.composite
def _conversation(draw: st.DrawFn) -> list[Message]:
    """Build a random conversation with realistic shape.

    Each block is one of: a USER turn, a SYSTEM turn, a plain ASSISTANT,
    or an ASSISTANT-with-calls followed by 0..2 TOOL messages.  Keeps
    the structure plausible enough that the rewriter exercises every
    branch of its loop.
    """
    blocks_strategy = st.lists(
        st.one_of(
            _user_message().map(lambda m: [m]),
            _system_message().map(lambda m: [m]),
            _assistant_plain().map(lambda m: [m]),
            st.tuples(
                _assistant_with_calls(),
                st.lists(_tool_message(), min_size=0, max_size=2),
            ).map(lambda t: [t[0]] + t[1]),
        ),
        min_size=1,
        max_size=4,
    )
    blocks = draw(blocks_strategy)
    messages: list[Message] = []
    for block in blocks:
        messages.extend(block)
    return messages


# ---------------------------------------------------------------------------
# rewrite_for_mistral invariants
# ---------------------------------------------------------------------------


class TestRewriteForMistral:
    """The outbound rewriter folds TOOL into ASSISTANT non-destructively."""

    @given(messages=_conversation())
    def test_does_not_mutate_input(self, messages: list[Message]) -> None:
        before = copy.deepcopy(messages)
        rewrite_for_mistral(messages)
        # Each input message must be field-for-field identical to its
        # pre-rewrite snapshot.
        assert len(messages) == len(before)
        for live, snap in zip(messages, before, strict=True):
            assert live == snap

    @given(messages=_conversation())
    def test_output_length_never_exceeds_input(self, messages: list[Message]) -> None:
        rewritten = rewrite_for_mistral(messages)
        assert len(rewritten) <= len(messages)

    @given(messages=_conversation())
    def test_folded_assistants_have_marker_and_no_calls(self, messages: list[Message]) -> None:
        rewritten = rewrite_for_mistral(messages)
        # Locate every input position where an assistant-with-calls was
        # followed by at least one TOOL message; the matching rewritten
        # message must carry the marker and have no tool_calls left.
        i = 0
        out_idx = 0
        while i < len(messages):
            msg = messages[i]
            if (
                msg.role == Role.ASSISTANT
                and msg.tool_calls
                and i + 1 < len(messages)
                and messages[i + 1].role == Role.TOOL
            ):
                j = i + 1
                while j < len(messages) and messages[j].role == Role.TOOL:
                    j += 1
                folded = rewritten[out_idx]
                assert _TOOL_CALLS_OPEN in folded.content
                assert _TOOL_CALLS_CLOSE in folded.content
                assert folded.tool_calls == [], (
                    "After folding, the assistant's tool_calls list should be empty."
                )
                out_idx += 1
                i = j
            else:
                out_idx += 1
                i += 1

    @given(messages=_conversation())
    def test_round_trip_recovers_tool_calls(self, messages: list[Message]) -> None:
        # For every ASSISTANT with tool_calls that gets folded, the
        # parser on its rewritten content must recover the original
        # call names and arguments.
        rewritten = rewrite_for_mistral(messages)
        original_pairs: list[tuple[Message, int]] = []  # (input msg, output idx)
        i = 0
        out_idx = 0
        while i < len(messages):
            msg = messages[i]
            if (
                msg.role == Role.ASSISTANT
                and msg.tool_calls
                and i + 1 < len(messages)
                and messages[i + 1].role == Role.TOOL
            ):
                original_pairs.append((msg, out_idx))
                j = i + 1
                while j < len(messages) and messages[j].role == Role.TOOL:
                    j += 1
                out_idx += 1
                i = j
            else:
                out_idx += 1
                i += 1

        for original, idx in original_pairs:
            parsed, _ = parse_mistral_tool_call_content(rewritten[idx].content)
            assert len(parsed) == len(original.tool_calls)
            for got, want in zip(parsed, original.tool_calls, strict=True):
                assert got.name == want.name
                assert got.arguments == want.arguments

    @given(messages=_conversation())
    def test_non_assistant_messages_pass_through_unchanged(self, messages: list[Message]) -> None:
        rewritten = rewrite_for_mistral(messages)
        # Walk the input and the output in lock-step: every USER /
        # SYSTEM message appears verbatim in the same relative order
        # in the output.
        non_assistant_in = [m for m in messages if m.role in (Role.USER, Role.SYSTEM)]
        non_assistant_out = [m for m in rewritten if m.role in (Role.USER, Role.SYSTEM)]
        assert non_assistant_in == non_assistant_out


# ---------------------------------------------------------------------------
# parse_mistral_tool_call_content invariants
# ---------------------------------------------------------------------------


class TestParseMistralToolCallContent:
    """The inbound parser is identity on marker-free / malformed content."""

    @given(content=_short_text())
    def test_no_markers_returns_original(self, content: str) -> None:
        calls, remainder = parse_mistral_tool_call_content(content)
        assert calls == []
        assert remainder == content

    @given(
        prefix=_short_text(),
        garbage=st.text(
            alphabet='abcdefghijklmnopqrstuvwxyz {}[]":,',
            min_size=0,
            max_size=32,
        ),
        suffix=_short_text(),
    )
    def test_garbage_between_markers_returns_original(
        self, prefix: str, garbage: str, suffix: str
    ) -> None:
        # The parser only accepts a non-empty JSON array of dicts with
        # a "name" field — anything else falls back to (empty, original).
        content = f"{prefix}{_TOOL_CALLS_OPEN}{garbage}{_TOOL_CALLS_CLOSE}{suffix}"
        # If the garbage happens to parse as a valid call array, skip.
        try:
            parsed_garbage = json.loads(garbage) if garbage else None
        except (json.JSONDecodeError, ValueError):
            parsed_garbage = None
        is_real_call = (
            isinstance(parsed_garbage, list)
            and len(parsed_garbage) > 0
            and all(isinstance(x, dict) and "name" in x for x in parsed_garbage)
        )
        if is_real_call:
            return  # Hypothesis happened to construct valid input; skip.

        calls, remainder = parse_mistral_tool_call_content(content)
        assert calls == []
        assert remainder == content, (
            f"Garbled marker content should not be partially consumed: "
            f"input={content!r}, remainder={remainder!r}"
        )

    @given(content=_short_text())
    def test_unclosed_open_marker_returns_original(self, content: str) -> None:
        # An open marker without a closing one is a parser-grade error
        # but must still return the input untouched.
        injected = f"{_TOOL_CALLS_OPEN}{content}"
        calls, remainder = parse_mistral_tool_call_content(injected)
        assert calls == []
        assert remainder == injected

    @given(calls=st.lists(_tool_call(), min_size=1, max_size=3), surround=_short_text())
    def test_well_formed_payload_recovers_calls(
        self, calls: list[ToolCall], surround: str
    ) -> None:
        # Build a content string the way ``rewrite_for_mistral`` would,
        # surrounded by prose, and check the parser pulls the calls out
        # with matching name + arguments.
        payload = json.dumps(
            [{"name": c.name, "arguments": c.arguments, "id": c.id} for c in calls],
            ensure_ascii=False,
        )
        content = f"{surround}\n{_TOOL_CALLS_OPEN}{payload}{_TOOL_CALLS_CLOSE}\n{surround}"
        parsed, remainder = parse_mistral_tool_call_content(content)
        assert len(parsed) == len(calls)
        for got, want in zip(parsed, calls, strict=True):
            assert got.name == want.name
            assert got.arguments == want.arguments
        # The remainder must no longer contain the marker.
        assert _TOOL_CALLS_OPEN not in remainder
        assert _TOOL_CALLS_CLOSE not in remainder

    @given(calls=st.lists(_tool_call(), min_size=1, max_size=3), surround=_short_text())
    def test_parser_is_idempotent_on_remainder(self, calls: list[ToolCall], surround: str) -> None:
        payload = json.dumps(
            [{"name": c.name, "arguments": c.arguments, "id": c.id} for c in calls],
            ensure_ascii=False,
        )
        content = f"{surround}\n{_TOOL_CALLS_OPEN}{payload}{_TOOL_CALLS_CLOSE}\n{surround}"
        _, remainder = parse_mistral_tool_call_content(content)
        # Parsing the remainder produces no calls and returns it
        # unchanged — the markers were stripped on the first pass.
        again_calls, again_remainder = parse_mistral_tool_call_content(remainder)
        assert again_calls == []
        assert again_remainder == remainder
