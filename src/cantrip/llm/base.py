"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Message role."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """A tool call from the assistant."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result of a tool call."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
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


@dataclass
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
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    """Response from the LLM."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A streaming chunk."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
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
    ) -> Response:
        """Generate a completion.

        When *max_tokens* is ``None``, providers use their own sensible
        default.  When *thinking_budget* is set, providers that support
        extended thinking will allocate that many tokens for internal
        reasoning before responding.
        """

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
    ) -> AsyncIterator[Chunk]:
        """Stream a completion.

        When *max_tokens* is ``None``, providers use their own sensible
        default.  When *thinking_budget* is set, providers that support
        extended thinking will allocate that many tokens for internal
        reasoning before responding.
        """

    @property
    def max_tools(self) -> int | None:
        """Maximum number of tools the provider can handle, or None for no limit."""
        return None

    @property
    def supports_vision(self) -> bool:
        """Whether this provider accepts image attachments on user messages.

        Callers that want to hand the model a screenshot or a rendered
        panel should gate on this property — vision-blind providers
        raise ``NotImplementedError`` when they see an ``Image`` they
        can't forward.
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
