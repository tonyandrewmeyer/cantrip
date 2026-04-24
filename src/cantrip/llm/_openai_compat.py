"""Shared base class for OpenAI-compatible chat-completion providers.

Several Cantrip providers speak the same wire format: Canonical's
inference snaps, Fireworks.ai, and any generic OpenAI-compatible
endpoint (Together, Groq, vLLM, …).  They differ only in base URL,
authentication, and model-catalogue behaviour; the message/tool
conversion and HTTP plumbing are identical.

This module holds that shared logic.  Subclasses construct an
``httpx.AsyncClient`` (with their own auth headers), set their own
capability flags, and set ``self.model_name``; everything else —
request building, streaming SSE parsing, tool-call accumulation,
error mapping — is inherited.
"""

import base64
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

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

log = logging.getLogger(__name__)

# Sensible upper bound for base64-encoded image_url payloads.  Matches
# Gemini's 20 MB cap.
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


class OpenAICompatBase(LLMProvider):
    """Abstract base for providers that speak the OpenAI chat-completions API.

    Concrete subclasses are responsible for:

    * Setting ``self.client`` to a configured ``httpx.AsyncClient`` with
      the correct ``base_url`` and (where applicable) ``Authorization``
      header.
    * Setting ``self.model_name`` to the model identifier to send in
      each request.
    * Setting ``self._context_window``, ``self._supports_tools`` and
      ``self._supports_vision`` at construction (may be updated later
      by capability probes).
    * Implementing the abstract ``name`` property on ``LLMProvider``.

    The error-message prefix used in exceptions comes from
    ``self._error_label`` — override to customise wording (defaults to
    the provider's ``name``).
    """

    client: httpx.AsyncClient
    model_name: str
    _context_window: int
    _supports_tools: bool
    _supports_vision: bool

    @property
    def context_window_tokens(self) -> int:
        """Maximum context window size in tokens for the current model."""
        return self._context_window

    @property
    def supports_vision(self) -> bool:
        """Whether this provider accepts image attachments."""
        return self._supports_vision

    @property
    def _error_label(self) -> str:
        """Short label used in error messages.  Defaults to the provider name."""
        return self.name

    # -- Message conversion (to OpenAI chat format) -----------------------

    @staticmethod
    def _image_content_parts(images: list[Image]) -> list[dict[str, Any]]:
        """Build OpenAI multi-part ``image_url`` entries from ``Image`` payloads.

        Images are base64-encoded and wrapped in a ``data:`` URI, the
        format all OpenAI-compatible endpoints accept.  Enforces the
        20 MB per-image cap.
        """
        parts: list[dict[str, Any]] = []
        for img in images:
            if len(img.data) > _MAX_IMAGE_BYTES:
                raise ProviderError(
                    f"Image exceeds the {_MAX_IMAGE_BYTES}-byte per-image "
                    f"limit: {len(img.data)} bytes ({img.mime})"
                )
            encoded = base64.b64encode(img.data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{img.mime};base64,{encoded}"},
                }
            )
        return parts

    def _convert_messages(self, messages: list[Message]) -> tuple[str | None, list[dict]]:
        """Convert messages to OpenAI chat API format.

        Returns a (system_prompt, messages) tuple.  The system prompt is
        extracted from the first SYSTEM message and returned separately
        so callers can prepend it if the API expects a system role.

        Consecutive user or assistant messages are merged into a single
        message because some local backends (notably Mediapipe in the
        gemma3 snap) reject conversations with consecutive same-role
        turns.  Once a user message carries images the content becomes
        a multi-part list, which the backend treats as a distinct turn —
        subsequent plain-text user messages do not merge into a list-
        valued content field.
        """
        if self._messages_have_images(messages) and not self._supports_vision:
            raise NotImplementedError(
                f"Provider '{self._error_label}' does not support image input. "
                f"Switch to a vision-capable model or drop the image attachments."
            )

        system_prompt: str | None = None
        result: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                system_prompt = msg.content
                continue

            if msg.role == Role.USER:
                if msg.images:
                    content_parts: list[dict[str, Any]] = self._image_content_parts(msg.images)
                    if msg.content:
                        content_parts.append({"type": "text", "text": msg.content})
                    result.append({"role": "user", "content": content_parts})
                elif (
                    result
                    and result[-1]["role"] == "user"
                    and isinstance(result[-1]["content"], str)
                ):
                    if msg.content:
                        result[-1]["content"] += "\n\n" + msg.content
                else:
                    result.append({"role": "user", "content": msg.content})

            elif msg.role == Role.ASSISTANT:
                entry: dict[str, Any] = {"role": "assistant"}
                if msg.tool_calls:
                    entry["content"] = msg.content or None
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                else:
                    if (
                        result
                        and result[-1]["role"] == "assistant"
                        and "tool_calls" not in result[-1]
                    ):
                        if msg.content:
                            result[-1]["content"] += "\n\n" + msg.content
                        continue
                    entry["content"] = msg.content
                result.append(entry)

            elif msg.role == Role.TOOL:
                for tr in msg.tool_results:
                    result.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            "content": tr.content,
                        }
                    )

        return system_prompt, result

    @staticmethod
    def _convert_tools(tools: list[Tool] | None) -> list[dict] | None:
        """Convert tools to OpenAI function-calling format."""
        if not tools:
            return None

        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    # -- API calls --------------------------------------------------------

    def _build_request_body(
        self,
        messages: list[Message],
        tools: list[Tool] | None,
        temperature: float,
        *,
        stream: bool = False,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
    ) -> dict[str, Any]:
        """Build the JSON request body for a chat completion."""
        system_prompt, api_messages = self._convert_messages(messages)
        if system_prompt:
            api_messages.insert(0, {"role": "system", "content": system_prompt})

        body: dict[str, Any] = {
            "model": self.model_name,
            "messages": api_messages,
            "temperature": temperature,
            "stream": stream,
        }

        if stream:
            body["stream_options"] = {"include_usage": True}

        # OpenAI-compatible reasoning models (Kimi K2, DeepSeek-R1,
        # GLM reasoning variants) spend reasoning tokens from the same
        # ``max_tokens`` pool as the final answer.  Mirror Claude's
        # semantic: when the caller signals ``thinking_budget``, raise
        # the cap so reasoning has room without starving the response.
        effective_max = max_tokens
        if thinking_budget:
            floor = thinking_budget + 4096
            effective_max = floor if effective_max is None else max(effective_max, floor)
        if effective_max is not None:
            body["max_tokens"] = effective_max

        if self._supports_tools:
            api_tools = self._convert_tools(tools)
            if api_tools:
                body["tools"] = api_tools

        return body

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: list[dict]) -> list[ToolCall]:
        """Parse tool calls from an OpenAI-format response."""
        tool_calls = []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            arguments = func.get("arguments", "{}")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=arguments,
                )
            )
        return tool_calls

    def _raise_http_error(self, exc: httpx.HTTPStatusError) -> None:
        """Map an HTTPStatusError to the right ProviderError subclass."""
        status = exc.response.status_code
        if status == 429:
            raise ProviderRateLimitError(f"{self._error_label} rate limit reached.") from exc
        if status >= 500:
            raise ProviderOverloadedError(f"{self._error_label} server error ({status}).") from exc
        detail = ""
        with contextlib.suppress(AttributeError, UnicodeDecodeError, ValueError):
            detail = exc.response.text[:500]
        raise ProviderError(f"{self._error_label} error ({status}): {detail or exc}") from exc

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
    ) -> Response:
        """Generate a completion via the OpenAI-compatible API."""
        body = self._build_request_body(
            messages,
            tools,
            temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
        )

        try:
            resp = await self.client.post("/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            self._raise_http_error(e)
        except httpx.HTTPError as e:
            raise ProviderError(f"Failed to connect to {self._error_label}: {e}") from e

        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(
                f"{self._error_label} returned non-JSON response: {resp.text[:200]}"
            ) from exc
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = self._parse_tool_calls(raw_tool_calls)
        reasoning = message.get("reasoning_content") or ""

        usage = data.get("usage", {})

        # Some open-weights models (Kimi K2, DeepSeek-R1 family, GLM
        # reasoning variants) return chain-of-thought as a sibling
        # ``reasoning_content`` field.  Surface it on the same metadata
        # key Claude uses for extended thinking so renderers stay on
        # one code path.
        metadata: dict[str, Any] = {}
        if reasoning:
            metadata["_thinking_content"] = reasoning

        return Response(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
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
    ) -> AsyncIterator[Chunk]:
        """Stream a completion via SSE."""
        body = self._build_request_body(
            messages,
            tools,
            temperature,
            stream=True,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
        )

        tool_calls_acc: dict[int, dict[str, str]] = {}
        usage: dict[str, int] = {}
        reasoning_parts: list[str] = []

        try:
            async with self.client.stream("POST", "/chat/completions", json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: ") :]
                    if payload.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    chunk_usage = data.get("usage")
                    if chunk_usage:
                        usage = {
                            "prompt_tokens": chunk_usage.get("prompt_tokens", 0),
                            "completion_tokens": chunk_usage.get("completion_tokens", 0),
                        }

                    choices = data.get("choices") or [{}]
                    delta = choices[0].get("delta", {})

                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.get("id", ""),
                                "name": "",
                                "arguments": "",
                            }
                        func = tc_delta.get("function", {})
                        if "name" in func:
                            tool_calls_acc[idx]["name"] = func["name"]
                        if "arguments" in func:
                            tool_calls_acc[idx]["arguments"] += func["arguments"]

                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        reasoning_parts.append(reasoning)

                    text = delta.get("content")
                    if text:
                        yield Chunk(content=text)

        except httpx.HTTPStatusError as e:
            self._raise_http_error(e)
        except httpx.HTTPError as e:
            raise ProviderError(f"Failed to connect to {self._error_label}: {e}") from e

        final_tool_calls = []
        for idx in sorted(tool_calls_acc):
            acc = tool_calls_acc[idx]
            try:
                arguments = json.loads(acc["arguments"])
            except json.JSONDecodeError:
                arguments = {}
            final_tool_calls.append(ToolCall(id=acc["id"], name=acc["name"], arguments=arguments))

        metadata: dict[str, Any] = {}
        if reasoning_parts:
            metadata["_thinking_content"] = "".join(reasoning_parts)

        yield Chunk(tool_calls=final_tool_calls, is_final=True, usage=usage, metadata=metadata)
