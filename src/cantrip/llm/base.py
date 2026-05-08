"""Base LLM provider interface."""

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Message role."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclasses.dataclass
class ToolCall:
    """A tool call from the assistant."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclasses.dataclass
class ToolResult:
    """Result of a tool call.

    ``images`` attaches image payloads to the tool result.  Providers
    that understand image content blocks in ``tool_result`` (Anthropic
    today) forward them inline alongside the text caption.  Providers
    whose tool-role messages are text-only (OpenAI-compatible,
    Gemini's ``FunctionResponse``) drop the images and keep the
    caption — the caption should always carry enough information to
    be useful on its own.
    """

    tool_call_id: str
    content: str
    is_error: bool = False
    images: list["Image"] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Image:
    """An image attachment for a multimodal message.

    ``data`` holds raw image bytes (not base64).  ``mime`` is the
    IANA media type the provider expects — ``image/png``,
    ``image/jpeg``, ``image/gif``, ``image/webp``.  Providers handle
    conversion to their native wire format (Anthropic content blocks,
    Gemini ``Part.inline_data``, OpenAI ``image_url`` with a
    ``data:`` URI).
    """

    data: bytes
    mime: str


@dataclasses.dataclass
class Message:
    """A conversation message.

    ``images`` attaches image payloads to a user-role message.  They
    are sent verbatim to providers whose ``supports_vision`` property
    is True; vision-blind providers raise ``NotImplementedError`` when
    they see images so callers notice rather than silently dropping
    the attachment.
    """

    role: Role
    content: str
    tool_calls: list[ToolCall] = dataclasses.field(default_factory=list)
    tool_results: list[ToolResult] = dataclasses.field(default_factory=list)
    images: list[Image] = dataclasses.field(default_factory=list)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Response:
    """Response from the LLM."""

    content: str
    tool_calls: list[ToolCall] = dataclasses.field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = dataclasses.field(default_factory=dict)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Chunk:
    """A streaming chunk."""

    content: str = ""
    tool_calls: list[ToolCall] = dataclasses.field(default_factory=list)
    is_final: bool = False
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)
    usage: dict[str, int] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Tool:
    """Tool definition for the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


# Approximate characters per token — used for fast heuristic token counting
# when a provider does not offer a native tokeniser.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the token count of *text* using a character-based heuristic."""
    return len(text) // _CHARS_PER_TOKEN


def estimate_message_tokens(messages: list["Message"]) -> int:
    """Estimate total tokens across a list of messages.

    Accounts for message content, tool call names/arguments, and tool
    result content.  Used as the default ``count_tokens`` implementation
    and by the context manager for budget tracking.
    """
    total = 0
    for msg in messages:
        total += len(msg.content)
        for tc in msg.tool_calls:
            total += len(tc.name) + len(str(tc.arguments))
        for tr in msg.tool_results:
            total += len(tr.content)
    return total // _CHARS_PER_TOKEN


class ProviderRateLimitError(Exception):
    """Raised when the LLM provider returns a rate-limit / quota error."""


class ProviderOverloadedError(Exception):
    """Raised when the provider is temporarily overloaded (503, 529, etc.)."""


class ProviderError(Exception):
    """Raised for non-transient provider errors (auth, invalid request, etc.)."""


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider (e.g. 'gemini', 'claude')."""

    @property
    @abstractmethod
    def context_window_tokens(self) -> int:
        """Maximum context window size in tokens for the current model."""

    @abstractmethod
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

        When *max_tokens* is ``None``, providers use their own sensible
        default.  When *thinking_budget* is set, providers that support
        extended thinking will allocate that many tokens for internal
        reasoning before responding.

        When *response_schema* is set (Phase 73.3), providers that
        support native structured output (Gemini, OpenAI-compatible)
        ask the model to return JSON conforming to the schema.
        Providers without native support (Anthropic today) accept
        the argument but rely on caller-side validation via
        :func:`cantrip.llm.structured.complete_structured`.  The
        :attr:`supports_response_schema` flag distinguishes the two.
        """

    @abstractmethod
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

        When *max_tokens* is ``None``, providers use their own sensible
        default.  When *thinking_budget* is set, providers that support
        extended thinking will allocate that many tokens for internal
        reasoning before responding.

        When *response_schema* is set, the provider applies native
        structured-output enforcement when available.  See
        :meth:`complete` for the full contract.
        """

    @property
    def max_tools(self) -> int | None:
        """Maximum number of tools the provider can handle, or None for no limit."""
        return None

    @property
    def conversation_temperature(self) -> float:
        """Default sampling temperature for the main conversation loop.

        Frontier APIs converge on ~0.7 because they ride on top of
        well-tuned RLHF/instruction-tuning that keeps tool-call
        formatting reliable even at higher temperatures.  Local quantised
        models (the inference snaps) are more brittle: small samplers
        excursions cause them to break out of the OpenAI tool-call
        envelope and emit raw XML / chat-template scaffolding inside
        ``content``.  Providers can override this to clamp the
        conversation temperature back to a level where tool calls
        round-trip reliably.
        """
        return 0.7

    @property
    def supports_vision(self) -> bool:
        """Whether this provider accepts image attachments on user messages.

        Callers that want to hand the model a screenshot or a rendered
        panel should gate on this property — vision-blind providers
        raise ``NotImplementedError`` when they see an ``Image`` they
        can't forward.
        """
        return False

    @property
    def supports_response_schema(self) -> bool:
        """Whether this provider applies *response_schema* natively (Phase 73.3).

        ``True`` when the wire protocol enforces JSON-schema
        conformance on the response (Gemini's
        ``response_mime_type``/``response_schema``, OpenAI-
        compatible's ``response_format``).  ``False`` when the
        provider accepts the argument but cannot enforce it; callers
        in that path get Cantrip-side validation only via
        :func:`cantrip.llm.structured.complete_structured`.
        """
        return False

    @staticmethod
    def _messages_have_images(messages: list["Message"]) -> bool:
        """Return True when any message carries an image attachment."""
        return any(msg.images for msg in messages)

    @staticmethod
    def _get_system_prompt(messages: list[Message]) -> str | None:
        """Extract the first system prompt from *messages*, or ``None``."""
        for msg in messages:
            if msg.role == Role.SYSTEM:
                return msg.content
        return None

    def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages (approximate).

        The default implementation uses a character-based heuristic.
        Subclasses may override with a provider-specific tokeniser.
        This method is synchronous and allocation-free — safe to call
        on every budget check.
        """
        return estimate_message_tokens(messages)

    async def count_tokens_accurate(self, messages: list[Message]) -> int:
        """Accurate token count via provider API when available.

        Providers that expose a native token-counting endpoint (e.g.
        Anthropic's ``/v1/messages/count_tokens``) should override this
        to return the exact count.  The default implementation falls
        back to ``count_tokens()`` so callers can always ``await`` it
        without checking provider capabilities.

        Use this for decision points where accuracy matters — e.g.
        logging compaction effectiveness, choosing whether to
        virtualise a borderline message.  For hot paths (every turn
        of the conversation loop), stick with ``count_tokens()`` to
        avoid per-call API latency and quota burn.
        """
        return self.count_tokens(messages)
