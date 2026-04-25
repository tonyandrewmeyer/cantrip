"""Tests for the structured-response pipeline (Phase 73.3)."""

from __future__ import annotations

import pytest

from cantrip.llm import base as llm
from cantrip.llm.schemas import (
    ACCEPTANCE_REPORT,
    BUILTIN_SCHEMAS,
    CHECK_RESULT,
    ORACLE_ANSWER,
    PLANNER_BRIEFING,
)
from cantrip.llm.structured import (
    StructuredOutputError,
    _strip_markdown_fences,
    complete_structured,
    validate_against_schema,
)

_TINY_SCHEMA: dict = {
    "type": "object",
    "title": "Tiny",
    "properties": {
        "answer": {"type": "string"},
    },
    "required": ["answer"],
    "additionalProperties": False,
}


class TestStripMarkdownFences:
    """Strip wrapping ```` ```json ```` fences before JSON parsing."""

    def test_plain_text_unchanged(self):
        assert _strip_markdown_fences('{"a": 1}') == '{"a": 1}'

    def test_json_fence_stripped(self):
        text = '```json\n{"a": 1}\n```'
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_bare_fence_stripped(self):
        text = '```\n{"a": 1}\n```'
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_uppercase_json_fence_stripped(self):
        text = '```JSON\n{"a": 1}\n```'
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_surrounding_whitespace_trimmed(self):
        assert _strip_markdown_fences("\n\n  {}  \n\n") == "{}"

    def test_unclosed_fence_left_alone(self):
        # No closing ``` — the regex shouldn't match, so the text
        # comes through and the JSON parser will fail loudly.
        text = '```json\n{"a": 1}'
        assert _strip_markdown_fences(text) == '```json\n{"a": 1}'


class TestValidateAgainstSchema:
    """Pure function: parse + validate."""

    def test_happy_path_returns_dict(self):
        assert validate_against_schema('{"answer": "yes"}', _TINY_SCHEMA) == {"answer": "yes"}

    def test_strips_fences_before_parsing(self):
        text = '```json\n{"answer": "yes"}\n```'
        assert validate_against_schema(text, _TINY_SCHEMA) == {"answer": "yes"}

    def test_unparseable_text_raises_with_context(self):
        with pytest.raises(StructuredOutputError) as info:
            validate_against_schema("not json at all", _TINY_SCHEMA)
        err = info.value
        assert "not valid JSON" in str(err)
        assert err.raw_text == "not json at all"
        assert err.schema is _TINY_SCHEMA

    def test_missing_required_field_raises(self):
        with pytest.raises(StructuredOutputError) as info:
            validate_against_schema('{"other": "field"}', _TINY_SCHEMA)
        assert "did not match schema" in str(info.value)

    def test_wrong_type_raises(self):
        with pytest.raises(StructuredOutputError) as info:
            validate_against_schema('{"answer": 42}', _TINY_SCHEMA)
        assert "did not match schema" in str(info.value)

    def test_additional_property_raises(self):
        with pytest.raises(StructuredOutputError):
            validate_against_schema('{"answer": "yes", "extra": "no"}', _TINY_SCHEMA)

    def test_top_level_array_rejected_when_object_expected(self):
        # JSON allows top-level arrays but the built-in schemas all
        # describe objects.  Surface the type mismatch up-front.
        array_schema: dict = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        }
        with pytest.raises(StructuredOutputError) as info:
            validate_against_schema("[1, 2, 3]", array_schema)
        assert "did not match schema" in str(info.value)

    def test_empty_string_raises_dedicated_error(self):
        with pytest.raises(StructuredOutputError) as info:
            validate_against_schema("   \n  ", _TINY_SCHEMA)
        assert "Empty response" in str(info.value)


class TestCompleteStructured:
    """Integration: complete_structured wraps provider.complete()."""

    async def test_happy_path_returns_parsed_dict(self, fake_provider):
        fake_provider._responses = [llm.Response(content='{"answer": "ok"}')]
        result = await complete_structured(
            fake_provider,
            messages=[llm.Message(role=llm.Role.USER, content="ping")],
            schema=_TINY_SCHEMA,
        )
        assert result == {"answer": "ok"}
        assert fake_provider.last_response_schema is _TINY_SCHEMA

    async def test_response_schema_forwarded_to_provider(self, fake_provider):
        # Use a payload that validates against PLANNER_BRIEFING so the
        # call succeeds; the assertion is about the schema reaching
        # the wire layer, not about validation.
        fake_provider._responses = [
            llm.Response(content='{"tasks": [{"title": "x", "category": "build"}]}')
        ]
        await complete_structured(
            fake_provider,
            messages=[llm.Message(role=llm.Role.USER, content="ping")],
            schema=PLANNER_BRIEFING,
        )
        # Confirm the schema reaches the wire layer; native enforcement
        # in real providers reads from this argument.
        assert fake_provider.last_response_schema is PLANNER_BRIEFING

    async def test_markdown_fenced_reply_validates(self, fake_provider):
        fake_provider._responses = [
            llm.Response(content='```json\n{"answer": "ok"}\n```'),
        ]
        result = await complete_structured(
            fake_provider,
            messages=[llm.Message(role=llm.Role.USER, content="ping")],
            schema=_TINY_SCHEMA,
        )
        assert result == {"answer": "ok"}

    async def test_one_corrective_retry_on_validation_failure(self, fake_provider):
        fake_provider._responses = [
            llm.Response(content="not json"),  # first try fails
            llm.Response(content='{"answer": "fixed"}'),  # corrected
        ]
        result = await complete_structured(
            fake_provider,
            messages=[llm.Message(role=llm.Role.USER, content="ping")],
            schema=_TINY_SCHEMA,
        )
        assert result == {"answer": "fixed"}

    async def test_retries_exhausted_raises_last_error(self, fake_provider):
        fake_provider._responses = [
            llm.Response(content="garbage 1"),
            llm.Response(content="garbage 2"),
        ]
        with pytest.raises(StructuredOutputError) as info:
            await complete_structured(
                fake_provider,
                messages=[llm.Message(role=llm.Role.USER, content="ping")],
                schema=_TINY_SCHEMA,
                retries=1,
            )
        # Final error carries the *last* raw text so the caller knows
        # which attempt's output to surface.
        assert info.value.raw_text == "garbage 2"

    async def test_zero_retries_means_one_attempt(self, fake_provider):
        fake_provider._responses = [llm.Response(content="garbage")]
        with pytest.raises(StructuredOutputError):
            await complete_structured(
                fake_provider,
                messages=[llm.Message(role=llm.Role.USER, content="ping")],
                schema=_TINY_SCHEMA,
                retries=0,
            )
        # Only one provider call happened.
        assert fake_provider._call_count == 1

    async def test_negative_retries_rejected(self, fake_provider):
        with pytest.raises(ValueError, match="non-negative"):
            await complete_structured(
                fake_provider,
                messages=[],
                schema=_TINY_SCHEMA,
                retries=-1,
            )


class TestProviderBodyShape:
    """OpenAI-compat and Gemini build the right wire payload for response_schema."""

    def test_openai_compat_wraps_schema_in_response_format(self):
        # Build an OpenAI-compat instance via Fireworks (no network calls
        # since _build_request_body is purely synchronous).
        from cantrip.llm.fireworks import FireworksProvider

        provider = FireworksProvider.__new__(FireworksProvider)
        # Bypass __init__ to avoid the API-key probe; supply just what
        # _build_request_body needs.
        provider.model_name = "kimi-k2"
        provider._supports_tools = False
        provider._supports_vision = False
        provider._context_window = 8192

        body = provider._build_request_body(
            messages=[llm.Message(role=llm.Role.USER, content="hi")],
            tools=None,
            temperature=0.7,
            response_schema=_TINY_SCHEMA,
        )
        assert "response_format" in body
        rf = body["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "Tiny"  # from schema title
        assert rf["json_schema"]["schema"] is _TINY_SCHEMA
        assert rf["json_schema"]["strict"] is True

    def test_openai_compat_omits_response_format_when_no_schema(self):
        from cantrip.llm.fireworks import FireworksProvider

        provider = FireworksProvider.__new__(FireworksProvider)
        provider.model_name = "kimi-k2"
        provider._supports_tools = False
        provider._supports_vision = False
        provider._context_window = 8192

        body = provider._build_request_body(
            messages=[llm.Message(role=llm.Role.USER, content="hi")],
            tools=None,
            temperature=0.7,
        )
        assert "response_format" not in body

    def test_openai_compat_response_format_uses_default_name_when_no_title(self):
        from cantrip.llm.fireworks import FireworksProvider

        provider = FireworksProvider.__new__(FireworksProvider)
        provider.model_name = "kimi-k2"
        provider._supports_tools = False
        provider._supports_vision = False
        provider._context_window = 8192

        no_title_schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        body = provider._build_request_body(
            messages=[llm.Message(role=llm.Role.USER, content="hi")],
            tools=None,
            temperature=0.7,
            response_schema=no_title_schema,
        )
        assert body["response_format"]["json_schema"]["name"] == "response"

    def test_supports_response_schema_flags(self):
        from cantrip.llm.claude import ClaudeProvider
        from cantrip.llm.fireworks import FireworksProvider
        from cantrip.llm.gemini import GeminiProvider

        # Bypass __init__ for capability-only checks.
        gemini = GeminiProvider.__new__(GeminiProvider)
        claude = ClaudeProvider.__new__(ClaudeProvider)
        fireworks = FireworksProvider.__new__(FireworksProvider)

        assert gemini.supports_response_schema is True
        assert fireworks.supports_response_schema is True
        # Anthropic accepts the kwarg but doesn't enforce — caller-
        # side validation is the only guarantee there.
        assert claude.supports_response_schema is False


class TestBuiltinSchemas:
    """The shipped schemas accept their own canonical sample payloads."""

    def test_planner_briefing_accepts_minimal_task(self):
        sample = {"tasks": [{"title": "scaffold the charm", "category": "build"}]}
        validate_against_schema(_to_json(sample), PLANNER_BRIEFING)

    def test_planner_briefing_rejects_unknown_category(self):
        sample = {"tasks": [{"title": "x", "category": "groceries"}]}
        with pytest.raises(StructuredOutputError):
            validate_against_schema(_to_json(sample), PLANNER_BRIEFING)

    def test_oracle_answer_accepts_answer_only(self):
        validate_against_schema('{"answer": "use ops 2.16+"}', ORACLE_ANSWER)

    def test_oracle_answer_accepts_full_payload(self):
        sample = {
            "answer": "yes",
            "confidence": 0.8,
            "caveats": ["limited evidence"],
            "references": ["charmhub.io/foo"],
        }
        validate_against_schema(_to_json(sample), ORACLE_ANSWER)

    def test_oracle_answer_rejects_out_of_range_confidence(self):
        with pytest.raises(StructuredOutputError):
            validate_against_schema('{"answer": "x", "confidence": 1.5}', ORACLE_ANSWER)

    def test_check_result_pass_minimal(self):
        validate_against_schema('{"status": "pass", "message": "all clear"}', CHECK_RESULT)

    def test_check_result_rejects_unknown_status(self):
        with pytest.raises(StructuredOutputError):
            validate_against_schema('{"status": "maybe", "message": "x"}', CHECK_RESULT)

    def test_acceptance_report_minimal(self):
        sample = {"app": "redis", "overall_status": "pass"}
        validate_against_schema(_to_json(sample), ACCEPTANCE_REPORT)

    def test_acceptance_report_with_findings(self):
        sample = {
            "app": "redis",
            "overall_status": "partial",
            "coverage": ["actions", "config"],
            "findings": [
                {"severity": "warning", "area": "actions", "description": "no get-status"},
            ],
        }
        validate_against_schema(_to_json(sample), ACCEPTANCE_REPORT)

    def test_builtin_registry_lookup(self):
        assert BUILTIN_SCHEMAS["planner_briefing"] is PLANNER_BRIEFING
        assert BUILTIN_SCHEMAS["oracle_answer"] is ORACLE_ANSWER
        assert BUILTIN_SCHEMAS["check_result"] is CHECK_RESULT
        assert BUILTIN_SCHEMAS["acceptance_report"] is ACCEPTANCE_REPORT
        assert set(BUILTIN_SCHEMAS) == {
            "planner_briefing",
            "oracle_answer",
            "check_result",
            "acceptance_report",
        }


def _to_json(obj: object) -> str:
    """Tiny helper so the schema fixtures read more like JSON than Python."""
    import json

    return json.dumps(obj)
