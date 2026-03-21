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
class Message:
    """A conversation message."""

    role: Role
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
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
    ) -> Response:
        """Generate a completion."""

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[Chunk]:
        """Stream a completion."""

    @property
    def max_tools(self) -> int | None:
        """Maximum number of tools the provider can handle, or None for no limit."""
        return None

    def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages (approximate).

        The default implementation uses a character-based heuristic.
        Subclasses may override with a provider-specific tokeniser.
        """
        return estimate_message_tokens(messages)
