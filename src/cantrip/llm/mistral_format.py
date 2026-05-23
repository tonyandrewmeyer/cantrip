"""Outbound rewriter and inbound parser for Mistral's Tekken chat template.

Mistral's Tekken template enforces strict ``user``/``assistant`` alternation
and rejects the OpenAI-shaped separate ``"tool"`` role messages that Cantrip
uses internally.  This module converts in both directions:

* **Outbound** (:func:`rewrite_for_mistral`): folds consecutive ``tool``-role
  messages into the preceding ``assistant`` message's content, using the
  markers the Tekken template expects:
  ``[TOOL_CALLS][...][/TOOL_CALLS]`` for invocations and
  ``[TOOL_RESULTS]{...}[/TOOL_RESULTS]`` for each result.

* **Inbound** (:func:`parse_mistral_tool_call_content`): client-side fallback
  for when llama.cpp's ``--jinja`` fails to convert the model's native
  ``[TOOL_CALLS]...[/TOOL_CALLS]`` output into an OpenAI-shaped ``tool_calls``
  array.  When the server returns the markers in ``content`` instead of in the
  structured ``tool_calls`` field, this parser extracts the calls and returns
  the Cantrip :class:`~cantrip.llm.base.ToolCall` shape.
"""

import dataclasses
import json
import logging

from cantrip.llm.base import Message, Role, ToolCall

log = logging.getLogger(__name__)

_TOOL_CALLS_OPEN = "[TOOL_CALLS]"
_TOOL_CALLS_CLOSE = "[/TOOL_CALLS]"
_TOOL_RESULTS_OPEN = "[TOOL_RESULTS]"
_TOOL_RESULTS_CLOSE = "[/TOOL_RESULTS]"


def rewrite_for_mistral(messages: list[Message]) -> list[Message]:
    """Rewrite an OpenAI-shaped conversation for Mistral's Tekken chat template.

    Consecutive ``tool``-role messages are absorbed into the content of the
    preceding ``assistant`` message.  The assistant turn receives both the
    ``[TOOL_CALLS]`` marker (describing the tool invocations) and one
    ``[TOOL_RESULTS]`` marker per result, separated by newlines.

    Input ``Message`` objects are never mutated.  Any assistant message that
    has its tool calls folded in is replaced with a new ``Message`` instance
    whose ``tool_calls`` list is empty and whose ``content`` carries the
    markers.  Unchanged messages are passed through as-is.
    """
    result: list[Message] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            # Look ahead to collect any immediately following TOOL messages.
            j = i + 1
            result_markers: list[str] = []
            while j < len(messages) and messages[j].role == Role.TOOL:
                for tr in messages[j].tool_results:
                    result_obj = {"content": tr.content, "call_id": tr.tool_call_id}
                    result_markers.append(
                        f"{_TOOL_RESULTS_OPEN}"
                        f"{json.dumps(result_obj, ensure_ascii=False)}"
                        f"{_TOOL_RESULTS_CLOSE}"
                    )
                j += 1

            calls_payload = [
                {"name": tc.name, "arguments": tc.arguments, "id": tc.id} for tc in msg.tool_calls
            ]
            tool_calls_marker = (
                f"{_TOOL_CALLS_OPEN}"
                f"{json.dumps(calls_payload, ensure_ascii=False)}"
                f"{_TOOL_CALLS_CLOSE}"
            )

            parts: list[str] = []
            if msg.content:
                parts.append(msg.content)
            parts.append(tool_calls_marker)
            parts.extend(result_markers)

            result.append(dataclasses.replace(msg, content="\n".join(parts), tool_calls=[]))
            i = j  # Skip over the absorbed TOOL messages.
        else:
            result.append(msg)
            i += 1
    return result


def parse_mistral_tool_call_content(content: str) -> tuple[list[ToolCall], str]:
    """Parse Mistral-format ``[TOOL_CALLS]...[/TOOL_CALLS]`` markers from content.

    Returns a ``(tool_calls, remainder)`` tuple.  When no markers are found, or
    when the text between them is not a valid non-empty JSON array of tool-call
    objects, both fields degrade gracefully: ``tool_calls`` is an empty list
    and ``remainder`` is the original unmodified ``content``.

    The JSON validity gate prevents false-positives when a model mentions the
    literal marker tokens in ordinary prose — only a syntactically valid JSON
    array with at least one ``{"name": "..."}`` entry triggers parsing.
    """
    open_start = content.find(_TOOL_CALLS_OPEN)
    if open_start == -1:
        return [], content

    json_start = open_start + len(_TOOL_CALLS_OPEN)
    close_start = content.find(_TOOL_CALLS_CLOSE, json_start)
    if close_start == -1:
        return [], content

    json_str = content[json_start:close_start]
    try:
        calls_data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return [], content

    if not isinstance(calls_data, list) or not calls_data:
        return [], content

    tool_calls: list[ToolCall] = []
    for idx, item in enumerate(calls_data):
        if not isinstance(item, dict) or "name" not in item:
            continue
        arguments = item.get("arguments") or {}
        if not isinstance(arguments, dict):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError, ValueError):
                arguments = {}
        tool_calls.append(
            ToolCall(
                id=item.get("id") or f"mistral-tc-{idx}",
                name=item["name"],
                arguments=arguments,
            )
        )

    if not tool_calls:
        return [], content

    # Strip the matched block; trim surrounding whitespace.
    after_close = close_start + len(_TOOL_CALLS_CLOSE)
    remainder = (content[:open_start] + content[after_close:]).strip()
    return tool_calls, remainder
