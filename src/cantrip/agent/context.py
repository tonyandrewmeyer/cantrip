"""Context window management via virtual files and compaction."""

import logging
import re
from dataclasses import dataclass

from cantrip.llm.base import (
    _CHARS_PER_TOKEN,
    LLMProvider,
    Message,
    Role,
    ToolResult,
    estimate_message_tokens,
    estimate_tokens,
)

log = logging.getLogger(__name__)


@dataclass
class VirtualFile:
    """A virtualised piece of content stored outside the conversation."""

    id: str
    name: str
    content: str
    source: str
    token_estimate: int


@dataclass
class SearchMatch:
    """A single regex match inside a virtual file."""

    file_id: str
    line_number: int
    line: str


class VirtualFileStore:
    """In-memory store for virtualised content, keyed by short IDs."""

    def __init__(self) -> None:
        self._files: dict[str, VirtualFile] = {}
        self._counter = 0

    def store(self, content: str, name: str, source: str) -> str:
        """Store content and return a virtual file ID."""
        self._counter += 1
        file_id = f"vf_{self._counter}"
        token_estimate = estimate_tokens(content)
        self._files[file_id] = VirtualFile(
            id=file_id,
            name=name,
            content=content,
            source=source,
            token_estimate=token_estimate,
        )
        return file_id

    def get(self, file_id: str) -> VirtualFile | None:
        """Retrieve a virtual file by ID."""
        return self._files.get(file_id)

    def get_lines(self, file_id: str, start: int, end: int) -> str | None:
        """Return lines [start, end) from a virtual file (1-indexed).

        Returns None if the file does not exist.
        """
        vf = self._files.get(file_id)
        if vf is None:
            return None
        lines = vf.content.splitlines()
        # Clamp to valid range (1-indexed).
        start = max(1, start)
        end = min(len(lines) + 1, end)
        return "\n".join(lines[start - 1 : end - 1])

    def search(
        self,
        pattern: str,
        file_id: str | None = None,
        max_matches: int = 20,
    ) -> list[SearchMatch]:
        """Search virtual files by regex pattern.

        If *file_id* is given, only that file is searched; otherwise all
        files are searched.  Returns up to *max_matches* results.

        Raises ``re.error`` for invalid patterns.
        """
        compiled = re.compile(pattern)
        matches: list[SearchMatch] = []

        targets = (
            [self._files[file_id]]
            if file_id and file_id in self._files
            else list(self._files.values())
        )

        for vf in targets:
            for line_number, line in enumerate(vf.content.splitlines(), start=1):
                if compiled.search(line):
                    matches.append(SearchMatch(file_id=vf.id, line_number=line_number, line=line))
                    if len(matches) >= max_matches:
                        return matches
        return matches

    def list_files(self) -> list[VirtualFile]:
        """Return all stored virtual files."""
        return list(self._files.values())


_COMPACTION_PROMPT = """\
Summarise the following conversation history. Preserve:
- All decisions made and their rationale
- Current charm state (name, type, framework, path)
- Important tool results and their outcomes
- Any errors encountered and how they were resolved
- The user's goals and requirements

Be concise but complete. This summary will replace the conversation history.\
"""

# Number of most recent messages to keep after compaction.
_KEEP_RECENT = 4


class ContextManager:
    """Orchestrates token estimation, virtualisation, and compaction."""

    def __init__(
        self,
        virtual_store: VirtualFileStore,
        context_window_tokens: int,
        compaction_threshold: float = 0.80,
        virtualisation_threshold: int = 10_000,
        virtualisation_preview: int = 1_000,
    ) -> None:
        self._store = virtual_store
        self._context_window = context_window_tokens
        self._compaction_threshold = compaction_threshold
        self._virtualisation_threshold = virtualisation_threshold
        self._virtualisation_preview = virtualisation_preview

    def estimate_tokens(self, messages: list[Message]) -> int:
        """Estimate the total token count across all messages."""
        return estimate_message_tokens(messages)

    def virtualise_message(self, message: Message) -> Message:
        """Replace oversized content with a virtual file pointer.

        For TOOL messages, each ToolResult is checked independently.
        For other messages, the entire content is checked.
        """
        if message.role == Role.TOOL and message.tool_results:
            return self._virtualise_tool_message(message)

        content_tokens = estimate_tokens(message.content)
        if content_tokens < self._virtualisation_threshold:
            return message

        file_id = self._store.store(
            content=message.content,
            name=f"{message.role.value}_message",
            source=f"virtualised:{message.role.value}",
        )
        preview_chars = self._virtualisation_preview * _CHARS_PER_TOKEN
        preview = message.content[:preview_chars]
        new_content = (
            f"{preview}\n\n"
            f"[Content truncated — full text stored as virtual file {file_id}. "
            f"Use virtual_file_read to access.]"
        )
        return Message(
            role=message.role,
            content=new_content,
            tool_calls=message.tool_calls,
            tool_results=message.tool_results,
        )

    def _virtualise_tool_message(self, message: Message) -> Message:
        """Virtualise individual tool results that exceed the threshold."""

        new_results = []
        changed = False
        for tr in message.tool_results:
            content_tokens = estimate_tokens(tr.content)
            if content_tokens >= self._virtualisation_threshold:
                file_id = self._store.store(
                    content=tr.content,
                    name=f"tool_result:{tr.tool_call_id}",
                    source=f"tool_result:{tr.tool_call_id}",
                )
                preview_chars = self._virtualisation_preview * _CHARS_PER_TOKEN
                preview = tr.content[:preview_chars]
                new_content = (
                    f"{preview}\n\n"
                    f"[Content truncated — full text stored as virtual file {file_id}. "
                    f"Use virtual_file_read to access.]"
                )
                new_results.append(
                    ToolResult(
                        tool_call_id=tr.tool_call_id,
                        content=new_content,
                        is_error=tr.is_error,
                    )
                )
                changed = True
            else:
                new_results.append(tr)

        if not changed:
            return message

        return Message(
            role=message.role,
            content=message.content,
            tool_calls=message.tool_calls,
            tool_results=new_results,
        )

    def build_budget_message(self, messages: list[Message]) -> Message:
        """Build a transient context budget message for the LLM."""
        used = self.estimate_tokens(messages)
        available = self._context_window - used
        virtual_files = self._store.list_files()

        parts = [
            f"[Context Budget] {used:,} / {self._context_window:,} tokens used "
            f"({available:,} remaining)."
        ]

        if virtual_files:
            parts.append("\nVirtual files available:")
            for vf in virtual_files:
                parts.append(f"  - {vf.id}: {vf.name} (~{vf.token_estimate:,} tokens)")

        return Message(role=Role.USER, content="\n".join(parts))

    def should_compact(self, messages: list[Message]) -> bool:
        """Return True if the conversation should be compacted."""
        if len(messages) < _KEEP_RECENT + 1:
            return False
        used = self.estimate_tokens(messages)
        return used >= self._context_window * self._compaction_threshold

    async def compact(
        self,
        messages: list[Message],
        system_prompt: str,
        provider: LLMProvider,
    ) -> list[Message]:
        """Compact the conversation by summarising older messages.

        Saves the full history as a virtual file, asks the provider to
        summarise it, then returns ``[summary] + last N messages``.
        """
        # Save full history as a virtual file.
        history_text = self._format_history(messages)
        file_id = self._store.store(
            content=history_text,
            name="conversation_history",
            source="compaction",
        )
        log.info("Saved conversation history as %s before compaction", file_id)

        # Ask the provider to summarise.
        summary_messages = [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content=f"{_COMPACTION_PROMPT}\n\n{history_text}"),
        ]
        response = await provider.complete(summary_messages, temperature=0.3)

        summary_content = (
            f"[Conversation Summary]\n{response.content}\n\n"
            f"[Full history saved as virtual file {file_id}. "
            f"Use virtual_file_read or virtual_file_search to access.]"
        )
        summary_msg = Message(role=Role.USER, content=summary_content)

        # Keep the most recent messages for continuity.
        recent = messages[-_KEEP_RECENT:] if len(messages) > _KEEP_RECENT else messages
        return [summary_msg] + list(recent)

    @staticmethod
    def _format_history(messages: list[Message]) -> str:
        """Format messages into a readable text representation."""
        parts: list[str] = []
        for msg in messages:
            role = msg.role.value.upper()
            if msg.content:
                parts.append(f"[{role}] {msg.content}")
            for tc in msg.tool_calls:
                parts.append(f"[{role}:tool_call] {tc.name}({tc.arguments})")
            for tr in msg.tool_results:
                status = "error" if tr.is_error else "ok"
                parts.append(f"[TOOL:{status}] {tr.content[:500]}")
        return "\n".join(parts)
