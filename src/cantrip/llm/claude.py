"""Anthropic Claude LLM provider."""

import base64
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import anthropic

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
    estimate_tokens,
)

log = logging.getLogger(__name__)

_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-haiku-4-5-20251001": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-6-20250917": 200_000,
    "claude-opus-4-7": 200_000,
}
_DEFAULT_CONTEXT_WINDOW = 200_000

# Minimum cached-prefix size for Anthropic prompt caching to activate.
# Sonnet and Haiku: 1024 tokens.  Opus: 2048 tokens.  Below these, the
# `cache_control` hint is silently ignored by the API.
_CACHE_MIN_TOKENS_OPUS = 2048
_CACHE_MIN_TOKENS_DEFAULT = 1024

# Anthropic's documented per-image cap is 5 MB of raw bytes; larger
# payloads are rejected server-side.  We enforce the same limit client-
# side so the caller gets a fast, clear error.
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


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

    @property
    def supports_vision(self) -> bool:
        """Claude 3+ models all accept image content blocks."""
        return True

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
        # One-shot flag so the cache-eligibility warning only logs once per
        # provider instance, not on every call.
        self._cache_warning_logged = False

    def _cache_min_tokens(self) -> int:
        """Minimum system-prompt tokens required for Anthropic caching to activate."""
        if "opus" in self.model_name:
            return _CACHE_MIN_TOKENS_OPUS
        return _CACHE_MIN_TOKENS_DEFAULT

    def _check_cache_eligibility(self, system_prompt: str) -> None:
        """Warn once if the system prompt is too short for caching to activate."""
        if self._cache_warning_logged:
            return
        min_tokens = self._cache_min_tokens()
        prompt_tokens = estimate_tokens(system_prompt)
        if prompt_tokens < min_tokens:
            log.warning(
                "System prompt is ~%d tokens — below Anthropic's %d-token "
                "minimum for %s prompt caching. The cache_control hint will "
                "be ignored and every turn will re-read the full prompt.",
                prompt_tokens,
                min_tokens,
                self.model_name,
            )
        self._cache_warning_logged = True

    @staticmethod
    def _image_blocks(images: list[Image]) -> list[dict]:
        """Build Anthropic ``image`` content blocks from ``Image`` payloads.

        Enforces the 5 MB per-image cap client-side and base64-encodes
        the raw bytes for the ``source.data`` field.
        """
        blocks: list[dict] = []
        for img in images:
            if len(img.data) > _MAX_IMAGE_BYTES:
                raise ProviderError(
                    f"Image exceeds Claude's {_MAX_IMAGE_BYTES}-byte per-image "
                    f"limit: {len(img.data)} bytes ({img.mime})"
                )
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.mime,
                        "data": base64.b64encode(img.data).decode("ascii"),
                    },
                }
            )
        return blocks

    def _convert_messages(self, messages: list[Message]) -> list[dict]:
        """Convert messages to Anthropic API format.

        SYSTEM messages are excluded here (passed separately).
        ASSISTANT messages with tool_calls produce content blocks.
        TOOL messages produce tool_result content blocks.
        USER messages with image attachments produce mixed image + text
        content blocks (images first so the model sees the visual
        before the instruction).
        """
        result = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue

            elif msg.role == Role.USER:
                if msg.images:
                    content = self._image_blocks(msg.images)
                    if msg.content:
                        content.append({"type": "text", "text": msg.content})
                    result.append({"role": "user", "content": content})
                else:
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
                    if tr.images:
                        # When a tool result carries images, the
                        # ``content`` field becomes a list of content
                        # blocks with the images first and the text
                        # caption last — same ordering Anthropic docs
                        # use so the model sees the visual before the
                        # caption that describes it.
                        tr_blocks = self._image_blocks(tr.images)
                        if tr.content:
                            tr_blocks.append({"type": "text", "text": tr.content})
                        content.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tr.tool_call_id,
                                "content": tr_blocks,
                                "is_error": tr.is_error,
                            }
                        )
                    else:
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
        """Convert tools to Anthropic format.

        The last tool carries a ``cache_control`` marker so the cached
        prefix extends across the entire tools block, not just the
        system prompt.  With Cantrip's large tool catalogue this is the
        single biggest cache hit available — without the marker the
        tools are sent fresh on every call.
        """
        if not tools:
            return None

        api_tools: list[dict] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]
        api_tools[-1]["cache_control"] = {"type": "ephemeral"}
        return api_tools

    @staticmethod
    def _mark_last_message_for_caching(api_messages: list[dict]) -> None:
        """Attach ``cache_control`` to the final message's last content block.

        Uses a third Anthropic cache breakpoint (system + tools + history)
        so multi-turn agent loops cache the conversation prefix and only
        the new turn's tokens are billed at full input rate.  String
        content is upgraded to a text block so the marker has somewhere
        to attach.
        """
        if not api_messages:
            return
        last = api_messages[-1]
        content = last["content"]
        if isinstance(content, str):
            last["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif content:
            content[-1]["cache_control"] = {"type": "ephemeral"}

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: list[Tool] | None,
        temperature: float,
        max_tokens: int | None,
        thinking_budget: int | None = None,
    ) -> dict:
        """Build the shared kwargs dict for ``messages.create`` / ``messages.stream``."""
        system_prompt = self._get_system_prompt(messages)
        api_messages = self._convert_messages(messages)
        self._mark_last_message_for_caching(api_messages)
        api_tools = self._convert_tools(tools)

        effective_max = max_tokens or 8192
        # Extended thinking requires a larger max_tokens budget that
        # includes both thinking and output tokens.
        if thinking_budget:
            effective_max = max(effective_max, thinking_budget + 4096)

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": effective_max,
            "messages": api_messages,
            "temperature": temperature,
        }
        if thinking_budget:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
            # Extended thinking requires temperature=1.
            kwargs["temperature"] = 1
        if system_prompt:
            self._check_cache_eligibility(system_prompt)
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if api_tools:
            kwargs["tools"] = api_tools
        return kwargs

    @staticmethod
    def _extract_usage(usage: object) -> dict[str, int]:
        """Extract token counts from an Anthropic usage object."""
        result = {
            "prompt_tokens": usage.input_tokens,
            "completion_tokens": usage.output_tokens,
        }
        if hasattr(usage, "cache_creation_input_tokens"):
            result["cache_creation_input_tokens"] = usage.cache_creation_input_tokens or 0
        if hasattr(usage, "cache_read_input_tokens"):
            result["cache_read_input_tokens"] = usage.cache_read_input_tokens or 0
        return result

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> Response:
        """Generate a completion.

        *response_schema* is accepted for interface parity (Phase
        73.3) but not enforced natively — Anthropic has no
        ``response_format`` analogue today.  Callers that need
        structured output should wrap this provider with
        :func:`cantrip.llm.structured.complete_structured`, which
        handles validation and one corrective retry on its own.
        """
        del response_schema  # No native enforcement; see docstring.
        kwargs = self._build_kwargs(messages, tools, temperature, max_tokens, thinking_budget)

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
        thinking_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "thinking":
                thinking_parts.append(block.thinking)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

        usage = self._extract_usage(response.usage)
        metadata: dict[str, object] = {}
        if thinking_parts:
            metadata["_thinking_content"] = "\n".join(thinking_parts)

        return Response(
            content="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason="tool_use" if response.stop_reason == "tool_use" else "stop",
            usage=usage,
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

        *response_schema* is accepted for interface parity but not
        enforced natively — see :meth:`complete` for the rationale.
        """
        del response_schema  # No native enforcement; see complete().
        kwargs = self._build_kwargs(messages, tools, temperature, max_tokens, thinking_budget)

        tool_calls: list[ToolCall] = []
        current_tool: dict | None = None
        usage: dict[str, int] = {}

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

                # Capture usage from the accumulated final message.
                final_message = await stream.get_final_message()
                if final_message.usage is not None:
                    usage = self._extract_usage(final_message.usage)
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

        yield Chunk(tool_calls=tool_calls, is_final=True, usage=usage)

    # count_tokens inherited from LLMProvider (character-based heuristic).

    async def count_tokens_accurate(self, messages: list[Message]) -> int:
        """Count tokens via Anthropic's ``/v1/messages/count_tokens`` endpoint.

        Falls back to the character-based heuristic when the API is
        unreachable, rate-limited, or returns an unexpected shape.
        Callers that need latency-insensitive accuracy (compaction
        decisions, effectiveness logging) should prefer this; hot paths
        should stick with ``count_tokens()``.
        """
        system_prompt = self._get_system_prompt(messages)
        api_messages = self._convert_messages(messages)
        # The API refuses an empty messages list; return the heuristic
        # instead of making a doomed request.
        if not api_messages:
            return self.count_tokens(messages)
        kwargs: dict = {
            "model": self.model_name,
            "messages": api_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        try:
            result = await self.client.messages.count_tokens(**kwargs)
        except (anthropic.APIError, anthropic.APIConnectionError):
            log.debug("count_tokens API failed; falling back to heuristic", exc_info=True)
            return self.count_tokens(messages)
        tokens = getattr(result, "input_tokens", None)
        if tokens is None:
            return self.count_tokens(messages)
        return int(tokens)
