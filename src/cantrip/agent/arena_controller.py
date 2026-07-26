"""Arena lifecycle controller — blind A/B model comparisons.

Held by :class:`CantripAgent` as ``self._arena_ctl`` and re-exposed
through thin delegators so the public surface (``active_arena`` /
``begin_arena`` / ``handle_arena_pick``) keeps working unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cantrip.agent import arena

if TYPE_CHECKING:
    from collections.abc import Callable

    from cantrip.agent.memory import MemoryManager
    from cantrip.agent.store import SessionStore
    from cantrip.llm.base import LLMProvider

log = logging.getLogger(__name__)


class ArenaController:
    """Owns blind A/B arena sessions.

    *get_light_provider* and *get_memory_manager* are callables that
    lazily resolve the agent's light provider and memory manager
    respectively — both may be ``None`` early in the session lifecycle.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        get_light_provider: Callable[[], LLMProvider | None],
        get_memory_manager: Callable[[], MemoryManager],
        ensure_store: Callable[[], None],
        get_store: Callable[[], SessionStore | None],
    ) -> None:
        self._provider = provider
        self._get_light_provider = get_light_provider
        self._get_memory_manager = get_memory_manager
        self._ensure_store = ensure_store
        self._get_store = get_store
        self._session: arena.ArenaSession | None = None

    @property
    def active(self) -> arena.ArenaSession | None:
        """The pending blind A/B arena, or ``None`` when idle."""
        return self._session

    async def begin(self, prompt: str) -> str:
        """Run a blind A/B arena for *prompt* and return the formatted output.

        The arena uses the primary provider and the light provider as the
        two candidates.  When no light provider is configured the method
        returns a user-facing error message rather than raising.
        """
        if self._session is not None:
            return (
                "Arena already in progress — reply **A**, **B**, **tie**, or "
                "**skip** to finish the current arena before starting a new one."
            )
        light = self._get_light_provider()
        if light is None:
            return (
                "Arena requires a second provider, but no light provider is "
                "configured.  Set ``CANTRIP_LIGHT_PROVIDER`` and restart to "
                "enable ``/arena``."
            )
        try:
            session = await arena.run_blind_arena(
                provider_a=self._provider,
                provider_b=light,
                prompt=prompt,
            )
        except arena.ArenaError as exc:
            return f"Arena not started: {exc}"
        self._session = session

        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "arena_started",
                {
                    "session_id": session.session_id,
                    "prompt_excerpt": prompt[:200],
                    "candidate_a_model": session.candidate_a.model_name,
                    "candidate_b_model": session.candidate_b.model_name,
                },
            )
        return arena.format_blind_arena(session)

    def handle_pick(self, message: str) -> str | None:
        """Resolve a pending arena pick from a raw user reply.

        Returns the reveal text when the message is a valid pick
        (``A`` / ``B`` / ``tie`` / ``skip``), or ``None`` when the
        message is anything else.
        """
        session = self._session
        if session is None:
            return None
        outcome = arena.parse_pick(message)
        if outcome == arena.ArenaOutcome.UNRECOGNISED:
            return None
        # Valid outcome — consume the session before writing so a memory
        # write error does not leave the arena locked in pending state.
        self._session = None

        memory_entry = None
        if outcome != arena.ArenaOutcome.SKIPPED:
            try:
                memory_entry = arena.record_preference(
                    self._get_memory_manager(), session, outcome
                )
            except (OSError, RuntimeError) as exc:
                log.warning("Arena memory write failed: %s", exc)

        self._ensure_store()
        store = self._get_store()
        if store:
            store.record_event(
                "arena_resolved",
                {
                    "session_id": session.session_id,
                    "outcome": outcome,
                    "memory_written": "yes" if memory_entry is not None else "no",
                },
            )
        return arena.format_reveal(session, outcome)
