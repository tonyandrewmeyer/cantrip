"""Shared fixtures and helpers for executor unit tests."""

from typing import Any
from unittest.mock import MagicMock

from cantrip.agent.executor import (
    BackgroundExecutor,
)
from cantrip.agent.queue import WorkQueue
from cantrip.agent.state import AgentState
from cantrip.llm.base import Response
from tests.conftest import FakeProvider
from tests.support.tools import make_stub_tool as _make_tool


def _make_executor(
    queue: WorkQueue | None = None,
    state: AgentState | None = None,
    provider: FakeProvider | None = None,
    store: MagicMock | None = None,
    light_provider: FakeProvider | None = None,
    on_task_done: Any = None,
    on_task_failed: Any = None,
) -> BackgroundExecutor:
    """Build a BackgroundExecutor with sensible defaults."""
    return BackgroundExecutor(
        queue=queue or WorkQueue(),
        tools=[_make_tool("read_file")],
        provider=provider or FakeProvider(responses=[Response(content="done")]),
        state=state or AgentState(),
        store=store,
        light_provider=light_provider,
        on_task_done=on_task_done,
        on_task_failed=on_task_failed,
    )
