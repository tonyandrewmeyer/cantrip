"""Anthropic Claude LLM provider."""

import json
import os
from collections.abc import AsyncIterator

import anthropic

from cantrip.llm.base import Chunk, LLMProvider, Message, Response, Role, Tool, ToolCall


class ClaudeProvider(LLMProvider):
    """Anthropic Claude implementation."""

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

    def _get_system_prompt(self, messages: list[Message]) -> str | None:
        """Extract system prompt from messages."""
        for msg in messages:
            if msg.role == Role.SYSTEM:
                return msg.content
        return None

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

        response = await self.client.messages.create(**kwargs)

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

        async with self.client.messages.stream(**kwargs) as stream:
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

        yield Chunk(tool_calls=tool_calls, is_final=True)

    def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages (approximate)."""
        total_chars = sum(len(msg.content) for msg in messages)
        return total_chars // 4
