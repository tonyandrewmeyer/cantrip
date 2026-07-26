"""Session persistence controller — save, load, preview, archive, resume.

Held by :class:`CantripAgent` as ``self._persistence`` and re-exposed
through thin delegators so the public surface keeps working unchanged.
Each method handles one aspect of the ``.cantrip`` SQLite-backed session
lifecycle.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from typing import TYPE_CHECKING

from cantrip.agent.queue import AgentTask, TaskStatus
from cantrip.agent.session_preview import SessionPreview
from cantrip.llm.base import Message, Role

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from cantrip.agent.queue import WorkQueue
    from cantrip.agent.state import AgentState
    from cantrip.agent.store import SessionStore

log = logging.getLogger(__name__)


class PersistenceController:
    """Owns session persistence: save, load, preview, archive, resume summary.

    Callables are injected for agent internals that live outside this
    controller's ownership boundary (store lifecycle, context-manager
    counters, message rehydration).
    """

    def __init__(
        self,
        *,
        state: AgentState,
        work_queue: WorkQueue,
        ensure_store: Callable[[], None],
        get_store: Callable[[], SessionStore | None],
        reset_store: Callable[[], None],
        restore_safety_state: Callable[[int, int, bool, bool], None],
        rebuild_messages: Callable[[], int],
    ) -> None:
        self._state = state
        self._work_queue = work_queue
        self._ensure_store = ensure_store
        self._get_store = get_store
        self._reset_store = reset_store
        self._restore_safety_state = restore_safety_state
        self._rebuild_messages = rebuild_messages

    # -- Save ------------------------------------------------------------------

    def save_state(self) -> None:
        """Save agent state to the session store."""
        self._ensure_store()
        store = self._get_store()
        if store:
            store.save_session(self._state)
            store.save_tasks(self._work_queue.all_tasks())

    # -- Preview ---------------------------------------------------------------

    def preview_session(self) -> SessionPreview:
        """Peek at the persisted session without mutating agent state.

        Called on launch by every surface (CLI, TUI, Web) to decide
        whether to show a resume prompt.  Returns
        ``SessionPreview(exists=False)`` when there's nothing on disk,
        when the charm path hasn't been set, or when the store can't be
        opened — so callers can branch on ``preview.exists`` without
        catching.
        """
        if not self._state.charm_path:
            return SessionPreview()
        db_path = self._state.charm_path / ".cantrip"
        if not db_path.is_file():
            return SessionPreview()
        try:
            self._ensure_store()
        except (sqlite3.Error, OSError):
            log.warning("Failed to open session store for preview")
            return SessionPreview()
        store = self._get_store()
        if store is None:
            return SessionPreview()
        try:
            peek = store.peek_session()
            if peek is None:
                return SessionPreview()
            tasks = store.load_tasks()
            counts: dict[str, int] = {}
            for t in tasks:
                counts[t.status.value] = counts.get(t.status.value, 0) + 1
            message_count = store.count_messages()
        except (sqlite3.Error, KeyError, ValueError):
            log.warning("Failed to preview session — .cantrip file may be corrupt")
            return SessionPreview()
        return SessionPreview(
            exists=True,
            charm_name=peek.get("charm_name") if isinstance(peek.get("charm_name"), str) else None,
            charm_type=peek.get("charm_type") if isinstance(peek.get("charm_type"), str) else None,
            framework=peek.get("framework") if isinstance(peek.get("framework"), str) else None,
            dev_model=peek.get("dev_model") if isinstance(peek.get("dev_model"), str) else None,
            cos_model=peek.get("cos_model") if isinstance(peek.get("cos_model"), str) else None,
            updated_at=(
                peek.get("updated_at") if isinstance(peek.get("updated_at"), str) else None
            ),
            message_count=message_count,
            task_counts=counts,
        )

    # -- Transcript tail -------------------------------------------------------

    def transcript_tail(self, limit: int = 20) -> list[Message]:
        """Return the last ``limit`` persisted messages, for "review" mode.

        Used when the user answers *Transcript* at the resume prompt —
        they see the tail before committing to Resume or Fresh.  Reads
        from the store but does not touch ``self._state.messages``.
        """
        self._ensure_store()
        store = self._get_store()
        if store is None:
            return []
        try:
            raw = store.load_active_branch()
        except (sqlite3.Error, KeyError, ValueError):
            return []
        result: list[Message] = []
        for msg in raw[-limit:]:
            role_str = msg.get("role", "")
            try:
                role = Role(role_str)
            except ValueError:
                continue
            content = msg.get("content", "")
            if not content:
                continue
            result.append(Message(role=role, content=str(content)))
        return result

    # -- Archive ---------------------------------------------------------------

    def archive_session(self) -> pathlib.Path | None:
        """Rename the current ``.cantrip`` file aside so a fresh session can start.

        Closes the session store, moves the file to
        ``.cantrip.bak-<timestamp>``, and resets the lazy-init flag so
        the next ``_ensure_store()`` call creates a new, empty database.
        Returns the backup path, or None if there was nothing to archive.
        """
        if not self._state.charm_path:
            return None
        db_path = self._state.charm_path / ".cantrip"
        if not db_path.is_file():
            return None
        store = self._get_store()
        if store is not None:
            try:
                store.close()
            except sqlite3.Error:
                log.warning("Failed to close session store before archiving")
        timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = db_path.with_name(f".cantrip.bak-{timestamp}")
        db_path.rename(backup)
        self._reset_store()
        log.info("Archived prior session to %s", backup)
        return backup

    # -- Load ------------------------------------------------------------------

    def load_state(self) -> bool:
        """Load agent state from the session store.

        Returns True if state was loaded, False if no state exists
        or the database is corrupt.
        """
        self._ensure_store()
        store = self._get_store()
        if not store:
            return False

        try:
            loaded = store.load_session()
        except (sqlite3.Error, KeyError, ValueError, TypeError):
            log.warning("Failed to load session — .cantrip file may be corrupt")
            self._reset_store()
            return False
        if loaded is None:
            return False

        self._state.charm_name = loaded.charm_name
        self._state.charm_path = loaded.charm_path
        self._state.charm_type = loaded.charm_type
        self._state.framework = loaded.framework
        self._state.dev_model = loaded.dev_model
        self._state.cos_model = loaded.cos_model
        self._state.decisions = loaded.decisions
        # Phase 99.2: restore the persisted ``/budget`` caps so the
        # operator doesn't re-specify them after every resume.  Matches
        # the compaction-counters pattern below — persisted state wins
        # over whatever ``cli.py`` stamped from CLI flags / env vars at
        # construction time, so resume is "pick up where you left off".
        self._state.goal_budget = loaded.goal_budget
        # Phase 99.3: same idea for the user-prose objective.  A
        # session that already had ``/goal "build a Postgres charm"``
        # set must come back with that string after resume so Ralph
        # re-feeds and goal-aware status surfaces keep using the
        # user's words.  An ``--objective`` flag passed at resume
        # time stamps state before this point and is overridden
        # here — the persisted value wins, mirroring the budget path.
        self._state.objective = loaded.objective

        # Restore compaction safety counters so per-session budgets survive
        # resume and we don't hand a fresh budget to a session that has
        # already been compacting aggressively.
        try:
            compactions, emergencies, cycle, exhausted = store.load_compaction_counters()
            self._restore_safety_state(
                compactions,
                emergencies,
                cycle,
                exhausted,
            )
        except sqlite3.Error:
            log.warning("Failed to restore compaction counters")

        # Restore conversation history so the LLM retains context.
        # Phase 67.1: load only the active branch so a /branch made
        # before quitting carries through to resume; off-branch
        # messages stay in the DB and remain reachable via /tree.
        try:
            self._rebuild_messages()
            if self._state.messages:
                log.info(
                    "Restored %d conversation messages from prior session",
                    len(self._state.messages),
                )
        except (sqlite3.Error, KeyError, ValueError):
            log.warning("Failed to load conversation history — continuing without it")

        # Restore persisted tasks into the work queue, resetting any that
        # were mid-flight when the previous session ended.  Skip tasks
        # whose IDs are already in the queue — a background worker
        # (issue triage, watcher) may have raced ahead of resume and
        # added the same deterministic ID.  Logging at warning level so
        # the operator sees the collision without the session crashing.
        tasks = store.load_tasks()
        existing_ids = {t.id for t in self._work_queue.all_tasks()}
        fresh_tasks: list[AgentTask] = []
        for task in tasks:
            if task.status == TaskStatus.ACTIVE:
                log.warning(
                    "Resetting stale active task %s (%s) to pending",
                    task.id,
                    task.title,
                )
                task.status = TaskStatus.PENDING
            if task.id in existing_ids:
                log.warning(
                    "Skipping persisted task %s (%s): already in the work "
                    "queue from a background worker",
                    task.id,
                    task.title,
                )
                continue
            fresh_tasks.append(task)
        if fresh_tasks:
            self._work_queue.add_tasks(fresh_tasks)

        store = self._get_store()
        if store:
            store.record_event(
                "session_resume",
                {
                    "charm_name": self._state.charm_name,
                    "task_count": len(tasks),
                },
            )

        # Phase 103.1: arm the must-read-first directive so the next turn
        # tells the model to re-read on disk before editing.  A
        # post-compaction or post-rehydrate ``edit_file`` that trusts
        # in-conversation memory of file bytes loses 5+ minutes per
        # mismatch; the directive is one-shot and self-clears once the
        # agent performs at least one ``read_file``.
        self._state.was_resumed = True

        return True

    # -- Resume summary --------------------------------------------------------

    def build_resume_summary(self) -> str | None:
        """Build a structured summary of prior session work.

        Returns a Markdown-formatted string suitable for injection as a
        USER message, or ``None`` if the state contains nothing useful
        to summarise.
        """
        state = self._state
        has_content = state.charm_name or state.decisions or self._work_queue.all_tasks()
        if not has_content:
            return None

        parts: list[str] = ["[Session resumed] Previous session context:\n"]

        if state.charm_name:
            charm_type = state.charm_type or "unknown"
            charm_path = state.charm_path or "unknown"
            parts.append(f"**Charm:** {state.charm_name} ({charm_type}) at {charm_path}")
        if state.framework:
            parts.append(f"**Framework:** {state.framework}")
        if state.dev_model or state.cos_model:
            parts.append(
                f"**Models:** dev={state.dev_model or 'none'}, cos={state.cos_model or 'none'}"
            )

        if state.decisions:
            parts.append("\n**Decisions:**")
            parts.extend(f"- {d.type}: {d.choice}" for d in state.decisions)

        tasks = self._work_queue.all_tasks()
        if tasks:
            counts: dict[str, int] = {}
            for t in tasks:
                counts[t.status.value] = counts.get(t.status.value, 0) + 1
            done = counts.get("done", 0)
            failed = counts.get("failed", 0)
            pending = counts.get("pending", 0) + counts.get("active", 0) + counts.get("blocked", 0)
            parts.append(f"\n**Task progress:** {done} done, {failed} failed, {pending} pending")
            completed = [t.title for t in tasks if t.status == TaskStatus.DONE]
            if completed:
                parts.append("**Recent completed tasks:**")
                parts.extend(f"- {title}" for title in completed[-5:])

        summary = "\n".join(parts)

        # Inject into conversation history so the LLM sees prior context.
        # Use SYSTEM role to avoid breaking alternating user/assistant patterns.
        self._state.messages.append(Message(role=Role.SYSTEM, content=summary))
        return summary
