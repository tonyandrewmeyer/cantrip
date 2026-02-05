"""Google Gemini LLM provider."""

import os
from collections.abc import AsyncIterator

import google.generativeai as genai

from cantrip.llm.base import Chunk, LLMProvider, Message, Response, Role, Tool, ToolCall


class GeminiProvider(LLMProvider):
    """Google Gemini implementation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-1.5-pro",
    ):
        """Initialise the Gemini provider."""
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model)
        self.model_name = model

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        """Convert messages to Gemini format."""
        result = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                # Gemini handles system prompts differently
                # Prepend to first user message or add as user context
                continue
            elif msg.role == Role.USER:
                result.append({"role": "user", "parts": [msg.content]})
            elif msg.role == Role.ASSISTANT:
                result.append({"role": "model", "parts": [msg.content]})
            # TODO: Handle tool calls and results
        return result

    def _convert_tools(self, tools: list[Tool] | None) -> list | None:
        """Convert tools to Gemini format."""
        if not tools:
            return None

        gemini_tools = []
        for tool in tools:
            gemini_tools.append(
                genai.protos.Tool(
                    function_declarations=[
                        genai.protos.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters=tool.parameters,
                        )
                    ]
                )
            )
        return gemini_tools

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
        history = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
        )

        # Start chat with system instruction
        chat = self.model.start_chat(
            history=history[:-1] if len(history) > 1 else [],
        )

        # Get the last user message
        last_message = history[-1]["parts"][0] if history else ""
        if system_prompt:
            # Prepend system prompt to first message if needed
            # TODO: Better handling of system prompts
            pass

        response = await chat.send_message_async(
            last_message,
            generation_config=generation_config,
            tools=gemini_tools,
        )

        # Parse tool calls if present
        tool_calls = []
        if response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call"):
                    fc = part.function_call
                    tool_calls.append(
                        ToolCall(
                            id=fc.name,  # Gemini doesn't use IDs
                            name=fc.name,
                            arguments=dict(fc.args),
                        )
                    )

        return Response(
            content=response.text if not tool_calls else "",
            tool_calls=tool_calls,
            finish_reason="stop",
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
        """Stream a completion."""
        system_prompt = self._get_system_prompt(messages)
        history = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
        )

        chat = self.model.start_chat(
            history=history[:-1] if len(history) > 1 else [],
        )

        last_message = history[-1]["parts"][0] if history else ""

        response = await chat.send_message_async(
            last_message,
            generation_config=generation_config,
            tools=gemini_tools,
            stream=True,
        )

        async for chunk in response:
            if chunk.text:
                yield Chunk(content=chunk.text)

        yield Chunk(is_final=True)

    def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages (approximate)."""
        # Simple approximation: ~4 chars per token
        total_chars = sum(len(msg.content) for msg in messages)
        return total_chars // 4
