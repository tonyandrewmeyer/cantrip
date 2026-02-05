"""Google Gemini LLM provider."""

import json
import os
from collections.abc import AsyncIterator

import google.generativeai as genai

from cantrip.llm.base import Chunk, LLMProvider, Message, Response, Role, Tool, ToolCall


class GeminiProvider(LLMProvider):
    """Google Gemini implementation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
    ):
        """Initialise the Gemini provider."""
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided")

        genai.configure(api_key=self.api_key)
        self.model_name = model

    def _create_model(self, system_prompt: str | None = None) -> genai.GenerativeModel:
        """Create a GenerativeModel, optionally with a system instruction."""
        kwargs = {}
        if system_prompt:
            kwargs["system_instruction"] = system_prompt
        return genai.GenerativeModel(self.model_name, **kwargs)

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        """Convert messages to Gemini format.

        Handles USER, ASSISTANT (with optional tool_calls), and TOOL messages.
        SYSTEM messages are handled separately via system_instruction.
        """
        result = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue

            elif msg.role == Role.USER:
                result.append({"role": "user", "parts": [msg.content]})

            elif msg.role == Role.ASSISTANT:
                if msg.tool_calls:
                    # Assistant message that contains tool calls.
                    parts = []
                    if msg.content:
                        parts.append(msg.content)
                    for tc in msg.tool_calls:
                        parts.append(
                            genai.protos.Part(
                                function_call=genai.protos.FunctionCall(
                                    name=tc.name,
                                    args=tc.arguments,
                                )
                            )
                        )
                    result.append({"role": "model", "parts": parts})
                else:
                    result.append({"role": "model", "parts": [msg.content]})

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
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tr.tool_call_id,
                                response=response_data,
                            )
                        )
                    )
                result.append({"role": "user", "parts": parts})

        return result

    def _convert_tools(self, tools: list[Tool] | None) -> list | None:
        """Convert tools to Gemini format."""
        if not tools:
            return None

        declarations = []
        for tool in tools:
            declarations.append(
                genai.protos.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                )
            )
        return [genai.protos.Tool(function_declarations=declarations)]

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
        model = self._create_model(system_prompt)
        history = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
        )

        # Use chat API: history is everything except the last message.
        chat = model.start_chat(
            history=history[:-1] if len(history) > 1 else [],
        )

        last_message = history[-1]["parts"] if history else [""]

        response = await chat.send_message_async(
            last_message,
            generation_config=generation_config,
            tools=gemini_tools,
        )

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
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
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
        model = self._create_model(system_prompt)
        history = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
        )

        chat = model.start_chat(
            history=history[:-1] if len(history) > 1 else [],
        )

        last_message = history[-1]["parts"] if history else [""]

        response = await chat.send_message_async(
            last_message,
            generation_config=generation_config,
            tools=gemini_tools,
            stream=True,
        )

        tool_calls = []
        async for chunk in response:
            if chunk.parts:
                for part in chunk.parts:
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
        """Count tokens in messages (approximate)."""
        total_chars = sum(len(msg.content) for msg in messages)
        return total_chars // 4
