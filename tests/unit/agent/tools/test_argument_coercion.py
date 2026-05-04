"""Tests for the JSONSchema-driven argument coercion in ``execute_tool``."""

from __future__ import annotations

from typing import Any

import pytest

from cantrip.agent.tools.base import (
    Tool,
    ToolResult,
    _coerce_argument,
    _coerce_arguments,
    execute_tool,
)


class _RecordingTool(Tool):
    """Tool that records the kwargs it was invoked with so tests can inspect them."""

    def __init__(self, parameters: dict[str, Any]) -> None:
        self._parameters = parameters
        self.received: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return "recording_tool"

    @property
    def description(self) -> str:
        return "Test tool that records its arguments."

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.received = kwargs
        return ToolResult(success=True, output="ok")


class TestCoerceArgument:
    """Unit tests for the per-argument coercion helper."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("off", False),
            ("", False),
            ("  true  ", True),  # surrounding whitespace tolerated
        ],
    )
    def test_string_to_bool_for_known_literals(self, value: str, expected: bool) -> None:
        """The ``"false"`` case is the bug that motivated this fix.

        ``bool("false")`` is ``True`` because the string is non-empty, so
        a tool seeing ``destructive_mode="false"`` would silently flip
        the flag the wrong way.  The coercion must short-circuit before
        the tool sees the raw string.
        """
        assert _coerce_argument(value, {"type": "boolean"}) is expected

    def test_bool_unknown_string_passes_through_unchanged(self) -> None:
        # An unrecognisable bool string should reach the tool unchanged so
        # the tool can produce its own clear error rather than have the
        # coercion silently invent ``True`` or ``False``.
        assert _coerce_argument("maybe", {"type": "boolean"}) == "maybe"

    def test_string_to_int_coercion(self) -> None:
        assert _coerce_argument("42", {"type": "integer"}) == 42
        assert _coerce_argument("  -7  ", {"type": "integer"}) == -7

    def test_string_to_int_invalid_passes_through(self) -> None:
        # ``"3.14"`` is not a valid integer literal — leave for the tool.
        assert _coerce_argument("3.14", {"type": "integer"}) == "3.14"
        assert _coerce_argument("abc", {"type": "integer"}) == "abc"

    def test_string_to_number_coercion(self) -> None:
        assert _coerce_argument("3.14", {"type": "number"}) == pytest.approx(3.14)
        assert _coerce_argument("42", {"type": "number"}) == pytest.approx(42.0)

    def test_native_types_are_left_alone(self) -> None:
        # Already-correct types must round-trip identically.
        assert _coerce_argument(True, {"type": "boolean"}) is True
        assert _coerce_argument(False, {"type": "boolean"}) is False
        assert _coerce_argument(42, {"type": "integer"}) == 42
        assert _coerce_argument(3.14, {"type": "number"}) == pytest.approx(3.14)

    def test_string_type_left_unchanged(self) -> None:
        # If the schema says ``"type": "string"`` and the value is a
        # string that *happens* to spell ``"true"``, we must NOT coerce
        # it to bool — that text is a legitimate string.
        assert _coerce_argument("true", {"type": "string"}) == "true"

    def test_missing_or_unknown_schema_leaves_value_alone(self) -> None:
        assert _coerce_argument("true", {}) == "true"
        assert _coerce_argument("true", None) == "true"  # type: ignore[arg-type]
        assert _coerce_argument("true", {"type": "object"}) == "true"


class TestCoerceArguments:
    """Tests for the dict-walking driver."""

    def test_coerces_only_declared_keys(self) -> None:
        params = {
            "type": "object",
            "properties": {
                "flag": {"type": "boolean"},
                "name": {"type": "string"},
            },
        }
        out = _coerce_arguments({"flag": "false", "name": "true", "extra": "true"}, params)
        # ``flag`` coerces (boolean schema), ``name`` does not (string schema),
        # ``extra`` passes through unchanged because it has no schema entry.
        assert out == {"flag": False, "name": "true", "extra": "true"}

    def test_no_properties_block_returns_arguments_unchanged(self) -> None:
        # Some tools declare ``parameters = {"type": "object"}`` with no
        # ``properties`` — pass-through, don't crash.
        out = _coerce_arguments({"x": "true"}, {"type": "object"})
        assert out == {"x": "true"}

    def test_non_dict_parameters_returns_arguments_unchanged(self) -> None:
        out = _coerce_arguments({"x": "true"}, "not a schema")  # type: ignore[arg-type]
        assert out == {"x": "true"}


@pytest.mark.asyncio
class TestExecuteToolBooleanCoercion:
    """End-to-end: ``execute_tool`` honours the schema before dispatch."""

    async def test_boolean_string_false_does_not_silently_become_true(self) -> None:
        """The motivating regression: a tool with ``destructive_mode: bool`` would
        previously see ``destructive_mode="false"`` and treat it as truthy.
        """
        tool = _RecordingTool(
            parameters={
                "type": "object",
                "properties": {
                    "destructive_mode": {"type": "boolean", "default": False},
                },
            }
        )
        await execute_tool(
            {"recording_tool": tool}, "recording_tool", {"destructive_mode": "false"}
        )
        assert tool.received == {"destructive_mode": False}

    async def test_boolean_string_true_coerced_to_true(self) -> None:
        tool = _RecordingTool(
            parameters={
                "type": "object",
                "properties": {"flag": {"type": "boolean"}},
            }
        )
        await execute_tool({"recording_tool": tool}, "recording_tool", {"flag": "true"})
        assert tool.received == {"flag": True}

    async def test_integer_string_coerced(self) -> None:
        tool = _RecordingTool(
            parameters={
                "type": "object",
                "properties": {"timeout": {"type": "integer"}},
            }
        )
        await execute_tool({"recording_tool": tool}, "recording_tool", {"timeout": "60"})
        assert tool.received == {"timeout": 60}

    async def test_unknown_tool_still_returns_clean_error(self) -> None:
        # Coercion must not break the tool-not-found path.
        result = await execute_tool({}, "nope", {"x": "true"})
        assert result.success is False
        assert "Unknown tool" in (result.error or "")
