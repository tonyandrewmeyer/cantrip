"""Google Gemini LLM provider."""

import base64
import binascii
import contextlib
import json
import os
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import types as genai_types

from cantrip.llm.base import (
    Chunk,
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
    "gemini-2.0-flash": 1_048_576,
    "gemini-3-flash-preview": 1_048_576,
    "gemini-3-pro-preview": 1_048_576,
    "gemini-3.1-pro-preview": 1_048_576,
}
_DEFAULT_CONTEXT_WINDOW = 1_048_576

# Gemini 3 strongly recommends temperature 1.0 (lower values cause looping).
_GEMINI_3_TEMPERATURE = 1.0


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
    ) -> genai_types.GenerateContentConfig:
        """Build the generation config, applying Gemini 3 overrides when needed."""
        thinking_config = None
        if self._is_gemini_3():
            temperature = _GEMINI_3_TEMPERATURE
            thinking_config = genai_types.ThinkingConfig(include_thoughts=False)

        return genai_types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_prompt,
            tools=gemini_tools,
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
            thinking_config=thinking_config,
        )

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
                result.append(
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=msg.content)],
                    )
                )

            elif msg.role == Role.ASSISTANT:
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
                    result.append(genai_types.Content(role="model", parts=parts))
                else:
                    if msg.content:
                        parts.append(genai_types.Part(text=msg.content))
                    if parts:
                        result.append(genai_types.Content(role="model", parts=parts))

            elif msg.role == Role.TOOL:
                # Tool results are sent as user-role function responses in Gemini.
                parts = []
                for tr in msg.tool_results:
                    # Parse content back to dict if possible for structured response.
                    try:
                        response_data = json.loads(tr.content)
                    except (json.JSONDecodeError, TypeError):
                        response_data = {"result": tr.content}
                    parts.append(
                        genai_types.Part.from_function_response(
                            name=tr.tool_call_id,
                            response=response_data,
                        )
                    )
                result.append(genai_types.Content(role="user", parts=parts))

        return result

    def _convert_tools(self, tools: list[Tool] | None) -> list[genai_types.Tool] | None:
        """Convert tools to Gemini format."""
        if not tools:
            return None

        declarations = []
        for tool in tools:
            declarations.append(
                genai_types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                )
            )
        return [genai_types.Tool(function_declarations=declarations)]

    def _get_system_prompt(self, messages: list[Message]) -> str | None:
        """Extract system prompt from messages."""
        for msg in messages:
            if msg.role == Role.SYSTEM:
                return msg.content
        return None

    @staticmethod
    def _collect_thought_parts(
        parts: list[Any],
    ) -> list[dict[str, str]]:
        """Collect thought signature parts from a Gemini response for round-trip.

        Returns a list of dicts with base64-encoded signatures that can be
        stored in ``Message.metadata["_gemini_thought_parts"]`` and later
        reconstructed into ``genai_types.Part`` objects.
        """
        thought_parts: list[dict[str, str]] = []
        for part in parts:
            if getattr(part, "thought", False) and getattr(part, "thought_signature", None):
                thought_parts.append(
                    {
                        "thought_signature": base64.b64encode(part.thought_signature).decode(
                            "ascii"
                        ),
                    }
                )
        return thought_parts

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
    ) -> Response:
        """Generate a completion."""
        system_prompt = self._get_system_prompt(messages)
        contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)
        config = self._build_config(temperature, system_prompt, gemini_tools)

        try:
            response = await self._client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
        except genai.errors.ClientError as e:
            if e.code == 429:
                raise ProviderRateLimitError(
                    "Gemini API rate limit exceeded. Please wait a moment and try again."
                ) from e
            raise ProviderError(f"Gemini API error: {e}") from e
        except genai.errors.ServerError as e:
            raise ProviderOverloadedError(
                f"Gemini API temporarily unavailable ({e.code}). Will retry shortly."
            ) from e
        except genai.errors.APIError as e:
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
                tool_calls.append(
                    ToolCall(
                        id=part.function_call.name,
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
        return Response(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage={
                "prompt_tokens": (usage_meta.prompt_token_count or 0) if usage_meta else 0,
                "completion_tokens": (
                    (usage_meta.candidates_token_count or 0) if usage_meta else 0
                ),
            },
            metadata=metadata,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[Chunk]:
        """Stream a completion.

        Note: if the model responds with tool calls, they are accumulated and
        yielded in the final chunk, since Gemini streams function calls
        incrementally.
        """
        system_prompt = self._get_system_prompt(messages)
        contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)
        config = self._build_config(temperature, system_prompt, gemini_tools)

        tool_calls = []
        all_thought_parts: list[dict[str, str]] = []
        all_fc_signatures: list[dict[str, str]] = []
        try:
            response_stream = await self._client.aio.models.generate_content_stream(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            async for chunk in response_stream:
                if not chunk.candidates or not chunk.candidates[0].content:
                    continue
                if chunk.candidates[0].content.parts:
                    all_thought_parts.extend(
                        self._collect_thought_parts(chunk.candidates[0].content.parts)
                    )
                    for part in chunk.candidates[0].content.parts:
                        if part.function_call and part.function_call.name:
                            tool_calls.append(
                                ToolCall(
                                    id=part.function_call.name,
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
        except genai.errors.ClientError as e:
            if e.code == 429:
                raise ProviderRateLimitError(
                    "Gemini API rate limit exceeded. Please wait a moment and try again."
                ) from e
            raise ProviderError(f"Gemini API error: {e}") from e
        except genai.errors.ServerError as e:
            raise ProviderOverloadedError(
                f"Gemini API temporarily unavailable ({e.code}). Will retry shortly."
            ) from e
        except genai.errors.APIError as e:
            raise ProviderError(f"Gemini API error: {e}") from e

        metadata: dict[str, Any] = {}
        if all_thought_parts:
            metadata["_gemini_thought_parts"] = all_thought_parts
        if all_fc_signatures:
            metadata["_gemini_fc_signatures"] = all_fc_signatures
        yield Chunk(tool_calls=tool_calls, is_final=True, metadata=metadata)

    # count_tokens inherited from LLMProvider (character-based heuristic).
