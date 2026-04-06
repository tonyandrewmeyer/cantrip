"""Anthropic Claude LLM provider."""

import json
import os
from collections.abc import AsyncIterator

import anthropic

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
    "claude-sonnet-4-5-20250929": 200_000,
}
_DEFAULT_CONTEXT_WINDOW = 200_000


class ClaudeProvider(LLMProvider):
    """Anthropic Claude implementation."""

    @property
    def name(self) -> str:
        """Short identifier for this provider."""
        return "claude"

    @property
    def context_window_tokens(self) -> int:
        """Maximum context window size in tokens for the current model."""
        return _CONTEXT_WINDOWS.get(self.model_name, _DEFAULT_CONTEXT_WINDOW)

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5-20250929",
    ):
        """Initialise the Claude provider."""
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not provided")

        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self.model_name = model

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        """Convert messages to Anthropic API format.

        SYSTEM messages are excluded here (passed separately).
        ASSISTANT messages with tool_calls produce content blocks.
        TOOL messages produce tool_result content blocks.
        """
        result = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue

            elif msg.role == Role.USER:
                result.append({"role": "user", "content": msg.content})

            elif msg.role == Role.ASSISTANT:
                if msg.tool_calls:
                    content = []
                    if msg.content:
                        content.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tc.id,
                                "name": tc.name,
                                "input": tc.arguments,
                            }
                        )
                    result.append({"role": "assistant", "content": content})
                else:
                    result.append({"role": "assistant", "content": msg.content})

            elif msg.role == Role.TOOL:
                content = []
                for tr in msg.tool_results:
                    content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tr.tool_call_id,
                            "content": tr.content,
                            "is_error": tr.is_error,
                        }
                    )
                result.append({"role": "user", "content": content})

        return result

    def _convert_tools(self, tools: list[Tool] | None) -> list[dict] | None:
        """Convert tools to Anthropic format."""
        if not tools:
            return None

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
    ) -> Response:
        """Generate a completion."""
        system_prompt = self._get_system_prompt(messages)
        api_messages = self._convert_messages(messages)
        api_tools = self._convert_tools(tools)

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": 4096,
            "messages": api_messages,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if api_tools:
            kwargs["tools"] = api_tools

        try:
            response = await self.client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            raise ProviderRateLimitError(
                "Claude API rate limit exceeded. Please wait a moment and try again."
            ) from e
        except anthropic.InternalServerError as e:
            raise ProviderOverloadedError(
                f"Claude API temporarily unavailable ({e.status_code}). Will retry shortly."
            ) from e
        except anthropic.APIError as e:
            raise ProviderError(f"Claude API error: {e}") from e

        # Parse response content blocks.
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

        return Response(
            content="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason="tool_use" if response.stop_reason == "tool_use" else "stop",
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
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
        api_messages = self._convert_messages(messages)
        api_tools = self._convert_tools(tools)

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": 4096,
            "messages": api_messages,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if api_tools:
            kwargs["tools"] = api_tools

        tool_calls: list[ToolCall] = []
        current_tool: dict | None = None

        try:
            stream_cm = self.client.messages.stream(**kwargs)
            async with stream_cm as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            current_tool = {
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input_json": "",
                            }

                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield Chunk(content=event.delta.text)
                        elif event.delta.type == "input_json_delta" and current_tool is not None:
                            current_tool["input_json"] += event.delta.partial_json

                    elif event.type == "content_block_stop" and current_tool is not None:
                        try:
                            arguments = json.loads(current_tool["input_json"])
                        except json.JSONDecodeError:
                            arguments = {}
                        tool_calls.append(
                            ToolCall(
                                id=current_tool["id"],
                                name=current_tool["name"],
                                arguments=arguments,
                            )
                        )
                        current_tool = None
        except anthropic.RateLimitError as e:
            raise ProviderRateLimitError(
                "Claude API rate limit exceeded. Please wait a moment and try again."
            ) from e
        except anthropic.InternalServerError as e:
            raise ProviderOverloadedError(
                f"Claude API temporarily unavailable ({e.status_code}). Will retry shortly."
            ) from e
        except anthropic.APIError as e:
            raise ProviderError(f"Claude API error: {e}") from e

        yield Chunk(tool_calls=tool_calls, is_final=True)

    # count_tokens inherited from LLMProvider (character-based heuristic).
