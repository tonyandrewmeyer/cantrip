"""Google Gemini LLM provider."""

import json
import os
from collections.abc import AsyncIterator

from google import genai
from google.genai import types as genai_types

from cantrip.llm.base import (
    Chunk,
    LLMProvider,
    Message,
    ProviderError,
    ProviderRateLimitError,
    Response,
    Role,
    Tool,
    ToolCall,
)

_CONTEXT_WINDOWS: dict[str, int] = {
    "gemini-2.0-flash": 1_048_576,
}
_DEFAULT_CONTEXT_WINDOW = 1_048_576


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
        model: str = "gemini-2.0-flash",
    ):
        """Initialise the Gemini provider."""
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided")

        self._client = genai.Client(api_key=self.api_key)
        self.model_name = model

    def _convert_messages(self, messages: list[Message]) -> list[genai_types.Content]:
        """Convert messages to Gemini format.

        Handles USER, ASSISTANT (with optional tool_calls), and TOOL messages.
        SYSTEM messages are handled separately via system_instruction.
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
                if msg.tool_calls:
                    # Assistant message that contains tool calls.
                    parts: list[genai_types.Part] = []
                    if msg.content:
                        parts.append(genai_types.Part(text=msg.content))
                    for tc in msg.tool_calls:
                        parts.append(
                            genai_types.Part(
                                function_call=genai_types.FunctionCall(
                                    name=tc.name,
                                    args=tc.arguments,
                                )
                            )
                        )
                    result.append(genai_types.Content(role="model", parts=parts))
                else:
                    result.append(
                        genai_types.Content(
                            role="model",
                            parts=[genai_types.Part(text=msg.content)],
                        )
                    )

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

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_prompt,
            tools=gemini_tools,
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
        )

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
        except genai.errors.APIError as e:
            raise ProviderError(f"Gemini API error: {e}") from e

        # Parse tool calls if present.
        tool_calls = []
        text_parts = []
        if response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.function_call and part.function_call.name:
                    tool_calls.append(
                        ToolCall(
                            id=part.function_call.name,
                            name=part.function_call.name,
                            arguments=dict(part.function_call.args),
                        )
                    )
                elif part.text:
                    text_parts.append(part.text)

        content = "".join(text_parts)

        return Response(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage={
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
            },
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

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_prompt,
            tools=gemini_tools,
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
        )

        try:
            response_stream = self._client.aio.models.generate_content_stream(
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
        except genai.errors.APIError as e:
            raise ProviderError(f"Gemini API error: {e}") from e

        tool_calls = []
        async for chunk in response_stream:
            if not chunk.candidates or not chunk.candidates[0].content:
                continue
            if chunk.candidates[0].content.parts:
                for part in chunk.candidates[0].content.parts:
                    if part.function_call and part.function_call.name:
                        tool_calls.append(
                            ToolCall(
                                id=part.function_call.name,
                                name=part.function_call.name,
                                arguments=dict(part.function_call.args),
                            )
                        )
                    elif part.text:
                        yield Chunk(content=part.text)

        yield Chunk(tool_calls=tool_calls, is_final=True)

    def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages (approximate).

        Accounts for message content, tool call names/arguments,
        and tool result content.
        """
        total = 0
        for msg in messages:
            total += len(msg.content)
            for tc in msg.tool_calls:
                total += len(tc.name) + len(str(tc.arguments))
            for tr in msg.tool_results:
                total += len(tr.content)
        return total // 4
