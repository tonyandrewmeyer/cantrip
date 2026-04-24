"""Context window management via virtual files and compaction."""

import logging
import re
import time
from dataclasses import dataclass

from cantrip.agent.prompts.compaction import load_compaction_prompt
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


# Compaction safety defaults — chosen to be well above normal usage while still
# catching pathological loops.  A healthy long session compacts maybe 5–10
# times; 20 gives plenty of headroom.  Emergency truncation is the last-ditch
# path, so 5 is ample.
_MAX_COMPACTIONS_PER_SESSION = 20
_MAX_EMERGENCIES_PER_SESSION = 5

# Cycle detection window: if compaction fires this many times within this
# many seconds without ever dropping the post-compaction token count below the
# threshold, treat it as a cycle and stop.
_CYCLE_WINDOW_SECONDS = 60.0
_CYCLE_FIRE_COUNT = 3

# When post/pre ratio exceeds this, compaction barely helped — log a warning so
# operators notice ineffective compaction before it escalates into a cycle.
_INEFFECTIVE_COMPACTION_RATIO = 0.9


@dataclass
class _CompactionEvent:
    """One compaction or emergency-truncate fire — used for cycle detection."""

    timestamp: float
    pre_tokens: int
    post_tokens: int
    kind: str  # "compact" or "emergency"


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
        max_compactions: int = _MAX_COMPACTIONS_PER_SESSION,
        max_emergencies: int = _MAX_EMERGENCIES_PER_SESSION,
    ) -> None:
        self._store = virtual_store
        self._context_window = context_window_tokens
        self._compaction_threshold = compaction_threshold
        self._virtualisation_threshold = virtualisation_threshold
        self._virtualisation_preview = virtualisation_preview
        self._max_compactions = max_compactions
        self._max_emergencies = max_emergencies
        # Mutable safety state.  Counters survive session resume — see
        # restore_safety_state()/safety_state().
        self._compactions_attempted = 0
        self._emergencies_attempted = 0
        self._history: list[_CompactionEvent] = []
        # Latched flags: once set they stay set for the session so the caller
        # can check whether compaction has been disabled.
        self._cycle_detected = False
        self._budget_exhausted = False
        # Set True when a safety warning needs to be surfaced to the user.
        # Cleared by consume_safety_warning().
        self._pending_warning: str | None = None

    @property
    def compactions_attempted(self) -> int:
        """Number of LLM-backed compactions fired this session."""
        return self._compactions_attempted

    @property
    def emergencies_attempted(self) -> int:
        """Number of emergency truncations fired this session."""
        return self._emergencies_attempted

    @property
    def cycle_detected(self) -> bool:
        """True once a compact/expand cycle has been detected."""
        return self._cycle_detected

    @property
    def budget_exhausted(self) -> bool:
        """True once the per-session compaction budget has been exhausted."""
        return self._budget_exhausted

    def safety_state(self) -> tuple[int, int]:
        """Return (compactions_attempted, emergencies_attempted) for persistence."""
        return self._compactions_attempted, self._emergencies_attempted

    def restore_safety_state(self, compactions_attempted: int, emergencies_attempted: int) -> None:
        """Restore counters from persisted state on session resume."""
        self._compactions_attempted = max(0, compactions_attempted)
        self._emergencies_attempted = max(0, emergencies_attempted)

    def consume_safety_warning(self) -> str | None:
        """Return and clear any pending safety warning for the user."""
        warning = self._pending_warning
        self._pending_warning = None
        return warning

    def _log_compression_ratio(self, pre_tokens: int, post_tokens: int) -> None:
        """Log how much compaction shrank the context.

        Warns when the post/pre ratio exceeds ``_INEFFECTIVE_COMPACTION_RATIO``
        so operators can see when summarisation is failing to compress
        (e.g.  repetitive content or an over-verbose summariser).
        """
        if pre_tokens <= 0:
            return
        ratio = post_tokens / pre_tokens
        if ratio >= _INEFFECTIVE_COMPACTION_RATIO:
            log.warning(
                "Compaction only reduced context to %.0f%% of prior size "
                "(%d → %d tokens); summariser may be ineffective for this content",
                ratio * 100,
                pre_tokens,
                post_tokens,
            )
        else:
            log.info(
                "Compaction reduced context to %.0f%% of prior size (%d → %d tokens)",
                ratio * 100,
                pre_tokens,
                post_tokens,
            )

    def _record_event(self, kind: str, pre_tokens: int, post_tokens: int) -> None:
        self._history.append(
            _CompactionEvent(
                timestamp=time.monotonic(),
                pre_tokens=pre_tokens,
                post_tokens=post_tokens,
                kind=kind,
            )
        )

    def _is_cycle(self) -> bool:
        """Detect a compact/expand cycle.

        A cycle is ``_CYCLE_FIRE_COUNT`` events within ``_CYCLE_WINDOW_SECONDS``
        where none of the post-compaction token counts dropped below the
        compaction threshold.  That means compaction keeps firing without
        making real progress — symptom of the LLM re-expanding summarised
        content or a tool producing huge output immediately after each
        compaction.
        """
        if len(self._history) < _CYCLE_FIRE_COUNT:
            return False
        recent = self._history[-_CYCLE_FIRE_COUNT:]
        now = time.monotonic()
        if now - recent[0].timestamp > _CYCLE_WINDOW_SECONDS:
            return False
        threshold_tokens = int(self._context_window * self._compaction_threshold)
        # Cycle if every recent event left the post count above the threshold.
        return all(event.post_tokens >= threshold_tokens for event in recent)

    def update_context_window(self, tokens: int) -> None:
        """Change the tracked context-window size mid-session.

        Used when the active provider is swapped at runtime via
        ``/model`` (Phase 67.2) so the compaction threshold tracks
        the new model's window rather than the startup one.
        """
        if tokens <= 0:
            raise ValueError("context_window_tokens must be positive")
        self._context_window = tokens

    @property
    def compaction_threshold(self) -> float:
        """Fraction of context window at which compaction triggers."""
        return self._compaction_threshold

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
                        images=list(tr.images),
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
        """Build a transient context budget message for the LLM.

        The body is wrapped in ``<system_note>...</system_note>`` with a short
        instruction so smaller models (observed with gemini-3-flash-preview)
        don't echo the budget line verbatim in their reply.
        """
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

        body = "\n".join(parts)
        framed = (
            "<system_note>\n"
            "The following is metadata for your own planning — do not echo it in your reply.\n"
            f"{body}\n"
            "</system_note>"
        )
        return Message(role=Role.USER, content=framed)

    def should_compact(self, messages: list[Message]) -> bool:
        """Return True if the conversation should be compacted.

        Returns False (with a one-off user-visible warning) when the
        per-session budget is exhausted or a compact/expand cycle has been
        detected — so the conversation loop can continue even if compaction
        is no longer useful.
        """
        if self._cycle_detected or self._budget_exhausted:
            return False
        if len(messages) < _KEEP_RECENT + 1:
            return False
        used = self.estimate_tokens(messages)
        if used < self._context_window * self._compaction_threshold:
            return False
        if self._compactions_attempted >= self._max_compactions:
            self._budget_exhausted = True
            self._pending_warning = (
                "Context compaction budget exhausted "
                f"({self._max_compactions} compactions this session).  "
                "Consider starting a new session or reducing output verbosity."
            )
            log.warning(
                "Compaction budget exhausted (%d attempts); skipping further compactions",
                self._compactions_attempted,
            )
            return False
        return True

    async def compact(
        self,
        messages: list[Message],
        system_prompt: str,
        provider: LLMProvider,
    ) -> list[Message]:
        """Compact the conversation by summarising older messages.

        Saves the full history as a virtual file, asks the provider to
        summarise it, then returns ``[summary] + last N messages``.  If the
        resulting context is not actually smaller, falls back to
        ``emergency_truncate()`` immediately.  Also detects compact/expand
        cycles — if this is the Nth recent fire with no progress, disables
        further compaction for the session.
        """
        pre_tokens = self.estimate_tokens(messages)
        self._compactions_attempted += 1

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
            Message(role=Role.USER, content=f"{load_compaction_prompt()}\n\n{history_text}"),
        ]
        response = await provider.complete(summary_messages, temperature=0.3)

        summary_content = (
            f"[Conversation Summary]\n{response.content}\n\n"
            f"[Full history saved as virtual file {file_id}. "
            f"Use virtual_file_read or virtual_file_search to access.]"
        )
        summary_msg = Message(role=Role.SYSTEM, content=summary_content)

        # Keep the most recent messages for continuity.
        recent = messages[-_KEEP_RECENT:] if len(messages) > _KEEP_RECENT else messages
        result = [summary_msg] + list(recent)
        post_tokens = self.estimate_tokens(result)

        # Post-compaction size validation: if the summary didn't actually
        # reduce the context, fall back to emergency_truncate on the
        # original messages rather than shipping a bloated summary.
        if post_tokens >= pre_tokens:
            log.warning(
                "Compaction did not reduce context size (%d → %d tokens); "
                "falling back to emergency truncation",
                pre_tokens,
                post_tokens,
            )
            result = self.emergency_truncate(messages)
            post_tokens = self.estimate_tokens(result)

        # Accurate token counts for cycle detection and the effectiveness
        # log.  Providers that lack a native count endpoint fall back to
        # the same heuristic we used above, so this is free for them.
        accurate_pre = await provider.count_tokens_accurate(messages)
        accurate_post = await provider.count_tokens_accurate(result)

        self._record_event("compact", accurate_pre, accurate_post)
        self._log_compression_ratio(accurate_pre, accurate_post)

        if self._is_cycle():
            self._cycle_detected = True
            self._pending_warning = (
                "Context is growing faster than compaction can shrink it.  "
                "Consider starting a new session or reducing output verbosity."
            )
            log.warning(
                "Compaction cycle detected (%d fires in %ds without progress); "
                "disabling further compactions this session",
                _CYCLE_FIRE_COUNT,
                int(_CYCLE_WINDOW_SECONDS),
            )

        return result

    def emergency_truncate(self, messages: list[Message]) -> list[Message]:
        """Drop oldest non-system messages to fit within the context budget.

        Used as a last-resort fallback when LLM-based compaction fails or
        fails to reduce size.  Keeps the system message (if any) and the
        most recent messages that fit within 80% of the context window.
        Counts towards the per-session emergency budget — once exhausted,
        still runs (we can't afford *not* to truncate) but sets a pending
        warning so the caller knows.
        """
        pre_tokens = self.estimate_tokens(messages)
        self._emergencies_attempted += 1
        if self._emergencies_attempted > self._max_emergencies and self._pending_warning is None:
            self._pending_warning = (
                "Emergency context truncation has fired "
                f"{self._emergencies_attempted} times this session "
                f"(budget: {self._max_emergencies}).  Consider starting a "
                "new session — the context manager is struggling to keep up."
            )
            log.warning(
                "Emergency truncation budget exceeded (%d / %d)",
                self._emergencies_attempted,
                self._max_emergencies,
            )

        system_msgs = [m for m in messages if m.role == Role.SYSTEM]
        non_system = [m for m in messages if m.role != Role.SYSTEM]

        budget = int(self._context_window * 0.80)
        system_tokens = self.estimate_tokens(system_msgs)
        remaining = budget - system_tokens

        # Walk backwards through non-system messages, keeping as many as fit.
        kept: list[Message] = []
        for msg in reversed(non_system):
            msg_tokens = self.estimate_tokens([msg])
            if remaining - msg_tokens < 0 and kept:
                # Already have at least one message; stop adding more.
                break
            remaining -= msg_tokens
            kept.append(msg)

        kept.reverse()
        result = system_msgs + kept
        log.warning(
            "Emergency truncation: kept %d of %d non-system messages",
            len(kept),
            len(non_system),
        )
        self._record_event("emergency", pre_tokens, self.estimate_tokens(result))
        return result

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
                # Preserve more content for errors (failure info is often
                # near the end of tracebacks).
                limit = 2000 if tr.is_error else 1000
                content = tr.content[:limit]
                if len(tr.content) > limit:
                    content += "\n…(truncated)"
                parts.append(f"[TOOL:{status}] {content}")
        return "\n".join(parts)
