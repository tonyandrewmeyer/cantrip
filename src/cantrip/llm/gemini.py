"""Google Gemini LLM provider."""

import base64
import binascii
import contextlib
import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from cantrip.llm.base import (
    Chunk,
    Image,
    LLMProvider,
    Message,
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    Response,
    Role,
    Tool,
    ToolCall,
)

_CONTEXT_WINDOWS: dict[str, int] = {
    "gemini-3-flash-preview": 1_048_576,
    "gemini-3-pro-preview": 1_048_576,
    "gemini-3.1-pro-preview": 1_048_576,
}
_DEFAULT_CONTEXT_WINDOW = 1_048_576

# Gemini 3 strongly recommends temperature 1.0 (lower values cause looping).
_GEMINI_3_TEMPERATURE = 1.0

# Gemini's documented inline-data cap is 20 MB per request; we apply it
# per-image to keep the limit comprehensible and fail fast.
_MAX_IMAGE_BYTES = 20 * 1024 * 1024

# Map Gemini's ``FinishReason`` enum onto cantrip's string convention
# (modelled on OpenAI's ``finish_reason`` values).  The previous code
# hardcoded ``"stop"`` for every non-tool-call response, which silently
# masked truncation, safety blocks, and recitation refusals — the agent
# would treat a clipped response as complete.
_FINISH_REASON_MAP: dict[str, str] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "BLOCKLIST": "content_filter",
    "MALFORMED_FUNCTION_CALL": "tool_calls",
    "IMAGE_SAFETY": "content_filter",
    "UNEXPECTED_TOOL_CALL": "tool_calls",
}


def _map_finish_reason(reason: Any) -> str | None:
    """Translate a Gemini ``FinishReason`` enum into cantrip's convention.

    Returns ``None`` when the response carries no usable signal so the
    caller can fall back to its tool-call default.  Tolerates the
    SDK returning either an enum (``FinishReason.MAX_TOKENS``) or the
    bare string the REST API serialises.
    """
    if reason is None:
        return None
    name = getattr(reason, "name", None) or str(reason).rsplit(".", 1)[-1]
    return _FINISH_REASON_MAP.get(name)


def _completion_tokens(usage_meta: Any) -> int:
    """Return the *total* output token count for billing.

    Gemini 2.5+ "thinking" models charge for ``thoughts_token_count``
    at the same rate as ``candidates_token_count``, but expose them
    in two separate fields.  The previous code only summed the
    visible-output count, so a response that burned its budget on
    thinking before producing visible content reported zero
    completion tokens — both wrong for cost tracking and confusing
    when the response was empty but the bill wasn't.

    Defensively reads only ``int``-typed values: the SDK returns
    ``int | None`` in practice, but a flaky mock or future schema
    change yielding a non-numeric value should degrade to ``0`` for
    that axis rather than crashing the whole completion.
    """
    if usage_meta is None:
        return 0

    def _as_int(name: str) -> int:
        value = getattr(usage_meta, name, None)
        return value if isinstance(value, int) else 0

    return _as_int("candidates_token_count") + _as_int("thoughts_token_count")


class GeminiProvider(LLMProvider):
    """Google Gemini implementation."""

    @property
    def name(self) -> str:
        """Short identifier for this provider."""
        return "gemini"

    @property
    def context_window_tokens(self) -> int:
        """Maximum context window size in tokens for the current model."""
        return _CONTEXT_WINDOWS.get(self.model_name, _DEFAULT_CONTEXT_WINDOW)

    @property
    def supports_vision(self) -> bool:
        """Gemini 1.5+ models all accept inline image parts."""
        return True

    @property
    def supports_response_schema(self) -> bool:
        """Gemini accepts ``response_mime_type`` + ``response_schema``."""
        return True

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-3.1-pro-preview",
    ):
        """Initialise the Gemini provider."""
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided")

        self._client = genai.Client(api_key=self.api_key)
        self.model_name = model

    def _is_gemini_3(self) -> bool:
        """Whether the current model is a Gemini 3 variant."""
        return self.model_name.startswith("gemini-3")

    def _build_config(
        self,
        temperature: float,
        system_prompt: str | None,
        gemini_tools: list[genai_types.Tool] | None,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> genai_types.GenerateContentConfig:
        """Build the generation config, applying Gemini 3 overrides when needed."""
        thinking_config = None
        if self._is_gemini_3():
            temperature = _GEMINI_3_TEMPERATURE
            if thinking_budget:
                thinking_config = genai_types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=thinking_budget,
                )
            else:
                thinking_config = genai_types.ThinkingConfig(include_thoughts=False)

        # Phase 73.3: native structured-output enforcement.  Gemini
        # rejects ``tools`` in the same request as ``response_schema``,
        # so callers using a schema must hand-feed the data they want
        # rather than mixing the two surfaces.  We pass the schema
        # through verbatim — the SDK accepts plain dicts and converts
        # them into the native ``Schema`` shape internally.
        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "system_instruction": system_prompt,
            "tools": gemini_tools,
            "automatic_function_calling": genai_types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
            "thinking_config": thinking_config,
        }
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema

        return genai_types.GenerateContentConfig(**config_kwargs)

    def _convert_messages(self, messages: list[Message]) -> list[genai_types.Content]:
        """Convert messages to Gemini format.

        Handles USER, ASSISTANT (with optional tool_calls), and TOOL messages.
        SYSTEM messages are handled separately via system_instruction.
        Gemini 3 thought signature parts are restored from message metadata.
        """
        result: list[genai_types.Content] = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue
            elif msg.role == Role.USER:
                result.append(self._convert_user_message(msg))
            elif msg.role == Role.ASSISTANT:
                content = self._convert_assistant_message(msg)
                if content is not None:
                    result.append(content)
            elif msg.role == Role.TOOL:
                result.append(self._convert_tool_message(msg))
        return result

    @staticmethod
    def _image_parts(images: list[Image]) -> list[genai_types.Part]:
        """Build Gemini inline-data image parts from ``Image`` payloads.

        Enforces the 20 MB per-image cap so oversized payloads fail
        with a clear error before hitting the API.
        """
        parts: list[genai_types.Part] = []
        for img in images:
            if len(img.data) > _MAX_IMAGE_BYTES:
                raise ProviderError(
                    f"Image exceeds Gemini's {_MAX_IMAGE_BYTES}-byte per-image "
                    f"limit: {len(img.data)} bytes ({img.mime})"
                )
            parts.append(genai_types.Part.from_bytes(data=img.data, mime_type=img.mime))
        return parts

    @staticmethod
    def _convert_user_message(msg: Message) -> genai_types.Content:
        """Convert a USER message to Gemini format.

        Image parts precede the text part so the model sees the visual
        context before the instruction that references it.
        """
        parts: list[genai_types.Part] = []
        if msg.images:
            parts.extend(GeminiProvider._image_parts(msg.images))
        if msg.content or not parts:
            parts.append(genai_types.Part(text=msg.content))
        return genai_types.Content(role="user", parts=parts)

    @staticmethod
    def _convert_assistant_message(msg: Message) -> genai_types.Content | None:
        """Convert an ASSISTANT message to Gemini format.

        Returns ``None`` when the message has no content or parts to send
        (e.g. an empty assistant turn with no tool calls).
        """
        parts: list[genai_types.Part] = []

        # Restore thought signature parts for Gemini 3 round-trip.
        for tp in msg.metadata.get("_gemini_thought_parts", []):
            with contextlib.suppress(KeyError, ValueError, binascii.Error):
                parts.append(
                    genai_types.Part(
                        thought=True,
                        thought_signature=base64.b64decode(tp["thought_signature"]),
                    )
                )

        if msg.tool_calls:
            if msg.content:
                parts.append(genai_types.Part(text=msg.content))
            fc_sigs = msg.metadata.get("_gemini_fc_signatures", [])
            for i, tc in enumerate(msg.tool_calls):
                fc_part = genai_types.Part(
                    function_call=genai_types.FunctionCall(
                        name=tc.name,
                        args=tc.arguments,
                    )
                )
                if i < len(fc_sigs) and fc_sigs[i].get("thought_signature"):
                    with contextlib.suppress(ValueError, binascii.Error):
                        fc_part.thought_signature = base64.b64decode(
                            fc_sigs[i]["thought_signature"]
                        )
                parts.append(fc_part)
            return genai_types.Content(role="model", parts=parts)

        if msg.content:
            parts.append(genai_types.Part(text=msg.content))
        if parts:
            return genai_types.Content(role="model", parts=parts)
        return None

    @staticmethod
    def _convert_tool_message(msg: Message) -> genai_types.Content:
        """Convert a TOOL message to Gemini format.

        Tool results are sent as user-role function responses.
        """
        parts: list[genai_types.Part] = []
        for tr in msg.tool_results:
            try:
                response_data = json.loads(tr.content)
            except (json.JSONDecodeError, TypeError):
                response_data = {"result": tr.content}
            # Tool call IDs use "function_name_N" format; the Gemini API
            # expects the actual function name, so strip the index suffix.
            func_name = re.sub(r"_\d+$", "", tr.tool_call_id)
            parts.append(
                genai_types.Part.from_function_response(
                    name=func_name,
                    response=response_data,
                )
            )
        return genai_types.Content(role="user", parts=parts)

    @staticmethod
    def _sanitize_schema_for_gemini(schema: Any) -> Any:
        """Strip JSON-Schema keys Gemini's function-declaration subset rejects.

        Gemini rejects ``additionalProperties`` (and ``additionalItems``) inside
        ``function_declarations[*].parameters`` — the Google SDK serialises
        those keys to snake_case on the wire, which surfaces as
        ``Unknown name "additional_properties"``.  Cantrip's subcommand
        bundles (``git``/``gh``/``juju``) set ``additionalProperties: True``
        deliberately, and MCP-supplied schemas may carry the same key, so we
        strip it recursively before handing the schema to the SDK.
        """
        if isinstance(schema, dict):
            return {
                k: GeminiProvider._sanitize_schema_for_gemini(v)
                for k, v in schema.items()
                if k not in ("additionalProperties", "additionalItems")
            }
        if isinstance(schema, list):
            return [GeminiProvider._sanitize_schema_for_gemini(item) for item in schema]
        return schema

    def _convert_tools(self, tools: list[Tool] | None) -> list[genai_types.Tool] | None:
        """Convert tools to Gemini format."""
        if not tools:
            return None

        declarations = [
            genai_types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=self._sanitize_schema_for_gemini(tool.parameters),
            )
            for tool in tools
        ]
        return [genai_types.Tool(function_declarations=declarations)]

    @staticmethod
    def _format_rate_limit_message(err: genai_errors.ClientError) -> str:
        """Build a human-readable rate-limit message from a Gemini 429.

        Gemini returns the structured error JSON inside ``err.details`` — the
        outer ``message`` field is itself a JSON blob whose inner
        ``error.message`` carries a "Please retry in …" hint, and the
        ``QuotaFailure`` detail names the quota that was breached (per-minute,
        per-day, …).  We surface both so the user can tell a transient
        backoff from an exhausted daily quota.
        """
        fallback = "Gemini API rate limit exceeded. Please wait a moment and try again."
        details = getattr(err, "details", None)
        if not isinstance(details, dict):
            return fallback
        inner_message = details.get("message")
        inner: dict[str, Any] = {}
        if isinstance(inner_message, str):
            try:
                parsed = json.loads(inner_message)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                inner = parsed.get("error") or {}

        text = inner.get("message") if isinstance(inner, dict) else None
        if not isinstance(text, str):
            text = details.get("message") if isinstance(details.get("message"), str) else ""

        retry_hint = ""
        match = re.search(r"[Pp]lease retry in\s+(\S+)", text or "")
        if match:
            retry_hint = f" Retry in {match.group(1).rstrip('.')}."

        quota_hint = ""
        quota_metric = ""
        for detail in (inner.get("details") or []) if isinstance(inner, dict) else []:
            if not isinstance(detail, dict):
                continue
            for violation in detail.get("violations") or []:
                if isinstance(violation, dict) and violation.get("quotaMetric"):
                    quota_metric = str(violation["quotaMetric"])
                    break
            if quota_metric:
                break
        if "per_day" in quota_metric or "per_model_per_day" in quota_metric:
            quota_hint = " (daily quota exhausted)"
        elif "per_minute" in quota_metric:
            quota_hint = " (per-minute quota)"

        if retry_hint or quota_hint:
            return f"Gemini API rate limit exceeded{quota_hint}.{retry_hint}".strip()
        return fallback

    @staticmethod
    def _collect_thought_parts(
        parts: list[Any],
    ) -> list[dict[str, str]]:
        """Collect thought signature parts from a Gemini response for round-trip.

        Returns a list of dicts with base64-encoded signatures that can be
        stored in ``Message.metadata["_gemini_thought_parts"]`` and later
        reconstructed into ``genai_types.Part`` objects.
        """
        thought_parts: list[dict[str, str]] = [
            {
                "thought_signature": base64.b64encode(part.thought_signature).decode("ascii"),
            }
            for part in parts
            if getattr(part, "thought", False) and getattr(part, "thought_signature", None)
        ]
        return thought_parts

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> Response:
        """Generate a completion."""
        system_prompt = self._get_system_prompt(messages)
        contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)
        config = self._build_config(
            temperature,
            system_prompt,
            gemini_tools,
            max_output_tokens=max_tokens,
            thinking_budget=thinking_budget,
            response_schema=response_schema,
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
        except genai_errors.ClientError as e:
            if e.code == 429:
                raise ProviderRateLimitError(self._format_rate_limit_message(e)) from e
            raise ProviderError(f"Gemini API error: {e}") from e
        except genai_errors.ServerError as e:
            raise ProviderOverloadedError(
                f"Gemini API temporarily unavailable ({e.code}). Will retry shortly."
            ) from e
        except genai_errors.APIError as e:
            raise ProviderError(f"Gemini API error: {e}") from e

        # Parse tool calls, text, and thought signatures from response parts.
        tool_calls = []
        text_parts = []
        if not response.candidates:
            raise ProviderError("Gemini returned an empty response (no candidates).")
        candidate_content = response.candidates[0].content
        response_parts = (candidate_content.parts if candidate_content else None) or []
        thought_parts = self._collect_thought_parts(response_parts)

        fc_signatures: list[dict[str, str]] = []
        for part in response_parts:
            if part.function_call and part.function_call.name:
                # Index suffix ensures unique IDs when the same tool is called
                # multiple times in one response.
                call_id = f"{part.function_call.name}_{len(tool_calls)}"
                tool_calls.append(
                    ToolCall(
                        id=call_id,
                        name=part.function_call.name,
                        arguments=dict(part.function_call.args or {}),
                    )
                )
                sig = getattr(part, "thought_signature", None)
                if sig:
                    fc_signatures.append(
                        {"thought_signature": base64.b64encode(sig).decode("ascii")}
                    )
            elif part.text:
                text_parts.append(part.text)

        content = "".join(text_parts)
        metadata: dict[str, Any] = {}
        if thought_parts:
            metadata["_gemini_thought_parts"] = thought_parts
        if fc_signatures:
            metadata["_gemini_fc_signatures"] = fc_signatures

        usage_meta = response.usage_metadata
        # Read the candidate's actual ``finish_reason`` rather than
        # always reporting ``"stop"`` — a ``MAX_TOKENS`` truncation,
        # a ``SAFETY`` block, or a ``RECITATION`` refusal need to be
        # visible to the agent.  Falls back to ``"tool_calls"`` /
        # ``"stop"`` only when the SDK didn't surface a reason.
        candidate_finish: str | None = None
        if response.candidates:
            candidate_finish = _map_finish_reason(response.candidates[0].finish_reason)
        if tool_calls:
            # Gemini reports ``FinishReason.STOP`` even on tool-call
            # responses (the model "stopped" emitting tokens after the
            # function call).  Cantrip's convention puts that in the
            # ``"tool_calls"`` bucket so the dispatcher can branch on
            # finish_reason without also peeking at tool_calls.  Real
            # truncation / safety still propagates through.
            if candidate_finish in (None, "stop"):
                finish_reason = "tool_calls"
            else:
                finish_reason = candidate_finish
        else:
            finish_reason = candidate_finish or "stop"
        return Response(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": (usage_meta.prompt_token_count or 0) if usage_meta else 0,
                "completion_tokens": _completion_tokens(usage_meta),
            },
            metadata=metadata,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[Chunk]:
        """Stream a completion.

        Note: if the model responds with tool calls, they are accumulated and
        yielded in the final chunk, since Gemini streams function calls
        incrementally.
        """
        system_prompt = self._get_system_prompt(messages)
        contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)
        config = self._build_config(
            temperature,
            system_prompt,
            gemini_tools,
            max_output_tokens=max_tokens,
            thinking_budget=thinking_budget,
            response_schema=response_schema,
        )

        tool_calls = []
        all_thought_parts: list[dict[str, str]] = []
        all_fc_signatures: list[dict[str, str]] = []
        usage: dict[str, int] = {}
        try:
            response_stream = await self._client.aio.models.generate_content_stream(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            async for chunk in response_stream:
                # Gemini typically reports cumulative usage on every chunk and
                # always on the final chunk. Overwrite so we end up with the
                # last (most complete) values. Guard against ``None`` so a
                # malformed response degrades to empty usage rather than
                # crashing (mirrors the Claude streaming guard from 41.10).
                chunk_usage = getattr(chunk, "usage_metadata", None)
                if chunk_usage is not None:
                    usage = {
                        "prompt_tokens": chunk_usage.prompt_token_count or 0,
                        "completion_tokens": _completion_tokens(chunk_usage),
                    }
                if not chunk.candidates or not chunk.candidates[0].content:
                    continue
                if chunk.candidates[0].content.parts:
                    all_thought_parts.extend(
                        self._collect_thought_parts(chunk.candidates[0].content.parts)
                    )
                    for part in chunk.candidates[0].content.parts:
                        if part.function_call and part.function_call.name:
                            call_id = f"{part.function_call.name}_{len(tool_calls)}"
                            tool_calls.append(
                                ToolCall(
                                    id=call_id,
                                    name=part.function_call.name,
                                    arguments=dict(part.function_call.args or {}),
                                )
                            )
                            sig = getattr(part, "thought_signature", None)
                            if sig:
                                all_fc_signatures.append(
                                    {"thought_signature": base64.b64encode(sig).decode("ascii")}
                                )
                        elif part.text:
                            yield Chunk(content=part.text)
        except genai_errors.ClientError as e:
            if e.code == 429:
                raise ProviderRateLimitError(self._format_rate_limit_message(e)) from e
            raise ProviderError(f"Gemini API error: {e}") from e
        except genai_errors.ServerError as e:
            raise ProviderOverloadedError(
                f"Gemini API temporarily unavailable ({e.code}). Will retry shortly."
            ) from e
        except genai_errors.APIError as e:
            raise ProviderError(f"Gemini API error: {e}") from e

        metadata: dict[str, Any] = {}
        if all_thought_parts:
            metadata["_gemini_thought_parts"] = all_thought_parts
        if all_fc_signatures:
            metadata["_gemini_fc_signatures"] = all_fc_signatures
        yield Chunk(tool_calls=tool_calls, is_final=True, metadata=metadata, usage=usage)

    # count_tokens inherited from LLMProvider (character-based heuristic).
