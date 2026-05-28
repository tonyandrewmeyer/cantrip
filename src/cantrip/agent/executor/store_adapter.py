"""Adapter that exposes a ``SessionStore`` through the ``StateService`` protocol."""

from cantrip.agent.queue import AgentTask
from cantrip.agent.store import SessionStore


class _SessionStoreAdapter:
    """Adapts a SessionStore to the StateService protocol."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def record_event(self, event_type: str, detail: dict[str, str]) -> None:
        self._store.record_event(event_type, detail)

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        category: str | None = None,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        self._store.record_usage(
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            category=category,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

    def save_tasks(self, tasks: list[AgentTask]) -> None:
        self._store.save_tasks(tasks)
