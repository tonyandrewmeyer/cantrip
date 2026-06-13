"""Conversation-history management for the agent.

This module hosts :class:`MessageHistory`, a service composed onto
:class:`~cantrip.agent.core.CantripAgent`. It records messages and persists
them to the store, rebuilds the active conversation branch after a rewind,
assembles the message list handed to the provider, and collapses history for
short sessions by folding old rounds into the ledger. All message, store, and
ledger state stays on the agent; the service reads and writes it through
``self._agent``.
"""

from __future__ import annotations

import logging
import typing

from cantrip.agent.context.context import SHORT_SESSION_INTURN_FOLD_AFTER, ContextManager
from cantrip.llm.base import Message, Role

if typing.TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent

log = logging.getLogger("cantrip.agent.core")


class MessageHistory:
    """Recording, rebuilding, and assembling the agent's conversation history."""

    def __init__(self, agent: CantripAgent) -> None:
        self._agent = agent

    def record_message(self, msg: Message) -> int | None:
        """Persist a conversation message to the session store.

        Returns the SQLite row ID of the inserted record, or ``None``
        when the store is not yet initialised.  User-role messages
        also get the row ID stamped onto :attr:`Message.metadata` so
        Phase 68.1 ``/undo`` can map a sliced message back to the
        rows it needs to delete.
        """
        self._agent._ensure_store()
        if not self._agent._store:
            return None
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls
            ]
        tool_results = None
        if msg.tool_results:
            tool_results = [
                {
                    "tool_call_id": tr.tool_call_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                }
                for tr in msg.tool_results
            ]
        row_id = self._agent._store.record_message(
            role=msg.role.value,
            content=msg.content,
            tool_calls=tool_calls,
            tool_results=tool_results,
            metadata=msg.metadata or None,
        )
        if msg.role == Role.USER:
            msg.metadata["db_message_id"] = row_id
        return row_id

    def rebuild_messages_from_active_branch(self) -> int:
        """Reload ``state.messages`` from the store's currently active branch.

        Phase 67.1 hook used by both resume (``load_state``) and
        ``/branch`` (which moves the head pointer and then re-reads
        the path).  Clears ``state.messages`` first so a partial
        rehydration leaves nothing stale; rolls forward through the
        branch ordering tool calls / results aren't restored
        (the LLM only needs role + content to keep context, and
        re-running tools on resume would double-pay).  Returns the
        number of messages rehydrated.
        """
        self._agent._ensure_store()
        if self._agent._store is None:
            return 0
        raw_messages = self._agent._store.load_active_branch()
        self._agent.state.messages.clear()
        for msg in raw_messages:
            role_str = msg.get("role", "")
            try:
                role = Role(role_str)
            except ValueError:
                continue
            content = msg.get("content", "")
            if not content:
                continue
            restored = Message(role=role, content=str(content))
            if role == Role.USER and msg.get("id") is not None:
                restored.metadata["db_message_id"] = msg["id"]
            self._agent.state.messages.append(restored)
        return len(self._agent.state.messages)

    def build_llm_messages(self, include_budget: bool = False) -> list[Message]:
        """Build the full message list for the LLM including system prompt.

        When *include_budget* is True, a transient context budget message
        is appended (not stored in state.messages).

        In short-session mode the accumulated history ledger
        (:attr:`AgentState.ledger`) is rendered into a SYSTEM message
        right after the prompt so a tight-context model retains a thread
        of past actions even though the raw transcript has been dropped.
        Like the budget message, it is built fresh each turn and never
        stored in ``state.messages``.

        The per-turn-volatile dynamic context (skills index, repo map) and
        the budget note are appended *after* the conversation as ephemeral
        messages.  The provider keeps its history cache breakpoint on the
        last non-ephemeral message, so this tail is re-sent at full price
        but never invalidates the cached system + history prefix.
        """
        messages = [Message(role=Role.SYSTEM, content=self._agent._build_system_prompt())]
        if self._agent._context_manager.short_session_mode and self._agent.state.ledger:
            messages.append(
                self._agent._context_manager.build_ledger_message(self._agent.state.ledger)
            )
        messages.extend(self._agent.state.messages)
        dynamic = self._agent._build_dynamic_context_message()
        if dynamic is not None:
            messages.append(dynamic)
        if include_budget:
            messages.append(self._agent._context_manager.build_budget_message(messages))
        return messages

    def collapse_messages_for_short_session(self) -> None:
        """Fold the prior conversation into the ledger and reset the working set.

        Called at the start of every user turn in short-session mode (and
        only when there is something to fold).  Conceptually each turn
        becomes a near-fresh session: ``state.messages`` collapses to
        empty here, the new user message is appended by the caller, and
        :meth:`_build_llm_messages` re-renders ``state.ledger`` into the
        prompt.  This also covers resume — the next turn after a restored
        transcript re-derives the ledger from it, so nothing about the
        ledger needs persisting.
        """
        if not self._agent._context_manager.short_session_mode or not self._agent.state.messages:
            return
        carried = len(self._agent.state.messages)
        new_entries = self._agent._context_manager.build_ledger_entries(self._agent.state.messages)
        ContextManager.extend_ledger(self._agent.state.ledger, new_entries)
        self._agent.state.messages = []
        log.info(
            "Short-session: collapsed %d messages into %d new ledger entries at turn start",
            carried,
            len(new_entries),
        )

    def maybe_fold_oldest_round_into_ledger(self, turn_start_idx: int) -> None:
        """Eagerly fold the oldest completed tool round of this turn into the ledger.

        Once a turn has accumulated more than
        :data:`SHORT_SESSION_INTURN_FOLD_AFTER` completed tool rounds,
        the oldest is distilled into ledger entries and its raw messages
        dropped — keeping the in-conversation working set small without
        waiting for the compaction threshold.  No-op outside
        short-session mode.
        """
        if not self._agent._context_manager.short_session_mode:
            return
        msgs = self._agent.state.messages

        def _round_starts() -> list[int]:
            return [
                i
                for i in range(turn_start_idx + 1, len(msgs))
                if msgs[i].role == Role.ASSISTANT and msgs[i].tool_calls
            ]

        starts = _round_starts()
        while len(starts) > SHORT_SESSION_INTURN_FOLD_AFTER:
            start, nxt = starts[0], starts[1]
            # Only fold a round whose tool results have actually landed.
            if not any(msgs[j].role == Role.TOOL for j in range(start + 1, nxt)):
                break
            folded = msgs[start:nxt]
            new_entries = self._agent._context_manager.build_ledger_entries(folded)
            ContextManager.extend_ledger(self._agent.state.ledger, new_entries)
            del msgs[start:nxt]
            log.info(
                "Short-session: folded oldest in-turn round (%d msgs, %d entries) into ledger",
                len(folded),
                len(new_entries),
            )
            starts = _round_starts()
