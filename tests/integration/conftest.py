"""Integration test configuration — shared fixtures and helpers."""

import asyncio
import json
from collections.abc import Callable

import pytest

from cantrip.agent.queue import TaskStatus, WorkQueue
from cantrip.agent.tools import base as tools_base
from cantrip.llm import base as llm
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Provider variants
# ---------------------------------------------------------------------------


class CallbackProvider(FakeProvider):
    """Provider that delegates to a callback for dynamic response logic.

    The callback receives the messages and tools and returns a ``Response``.
    Useful when tests need to inspect message content or vary behaviour.
    """

    def __init__(
        self,
        callback: Callable[[list[llm.Message], list[llm.Tool] | None], llm.Response],
    ) -> None:
        super().__init__()
        self._callback = callback

    async def complete(
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None = None,  # noqa: ARG002
        temperature: float = 0.7,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        thinking_budget: int | None = None,  # noqa: ARG002
    ) -> llm.Response:
        self._call_count += 1
        # Yield to the event loop so executor tests don't starve other coroutines.
        await asyncio.sleep(0)
        return self._callback(messages, tools)


class MultiRoleProvider(FakeProvider):
    """Provider with separate response queues for planner vs subagent calls.

    Distinguishes by checking the system prompt for ``task planner`` (planner)
    or ``autonomous subagent`` (subagent) keywords.
    """

    def __init__(
        self,
        planner_responses: list[llm.Response] | None = None,
        subagent_responses: list[llm.Response] | None = None,
    ) -> None:
        super().__init__()
        self._planner_responses = list(planner_responses or [])
        self._subagent_responses = list(subagent_responses or [])
        self._planner_call_count = 0
        self._subagent_call_count = 0

    async def complete(
        self,
        messages: list[llm.Message],
        tools: list[llm.Tool] | None = None,  # noqa: ARG002
        temperature: float = 0.7,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        thinking_budget: int | None = None,  # noqa: ARG002
    ) -> llm.Response:
        self._call_count += 1

        # Determine role from system prompt content.
        system_text = ""
        for msg in messages:
            if msg.role == llm.Role.SYSTEM:
                system_text = msg.content.lower()
                break

        # Yield to the event loop so executor tests don't starve other coroutines.
        await asyncio.sleep(0)

        if "task planner" in system_text and (
            self._planner_call_count < len(self._planner_responses)
        ):
            resp = self._planner_responses[self._planner_call_count]
            self._planner_call_count += 1
            return resp

        if "autonomous subagent" in system_text and (
            self._subagent_call_count < len(self._subagent_responses)
        ):
            resp = self._subagent_responses[self._subagent_call_count]
            self._subagent_call_count += 1
            return resp

        return llm.Response(content="default response")


# ---------------------------------------------------------------------------
# Stub tools
# ---------------------------------------------------------------------------


def make_stub_tool(name: str, result: str | None = None) -> tools_base.Tool:
    """Create a minimal stub tool that returns a fixed result."""
    result_text = result or f"{name} executed"

    class _Stub(tools_base.Tool):
        @property
        def name(self) -> str:
            return _name

        @property
        def description(self) -> str:
            return f"Stub tool: {_name}"

        @property
        def parameters(self) -> dict:
            return {"type": "object", "properties": {}}

        async def execute(self, **_kwargs) -> tools_base.ToolResult:  # type: ignore[override]
            return tools_base.ToolResult(success=True, output=_result_text)

    # Bind via closure defaults to avoid late-binding issues.
    _name = name
    _result_text = result_text
    return _Stub()


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


async def wait_for_queue_state(
    queue: WorkQueue,
    *,
    done_count: int | None = None,
    failed_count: int | None = None,
    timeout: float = 5.0,
) -> None:
    """Poll the queue until the expected state is reached or timeout.

    Polls every 20ms rather than using fixed sleeps.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if done_count is not None:
            actual_done = sum(1 for t in queue.all_tasks() if t.status == TaskStatus.DONE)
            if actual_done >= done_count:
                if failed_count is None:
                    return
                actual_failed = sum(1 for t in queue.all_tasks() if t.status == TaskStatus.FAILED)
                if actual_failed >= failed_count:
                    return
        elif failed_count is not None:
            actual_failed = sum(1 for t in queue.all_tasks() if t.status == TaskStatus.FAILED)
            if actual_failed >= failed_count:
                return
        await asyncio.sleep(0.02)
    raise TimeoutError(
        f"Queue did not reach expected state within {timeout}s. "
        f"Tasks: {[(t.id, t.title, t.status.value) for t in queue.all_tasks()]}"
    )


# ---------------------------------------------------------------------------
# JSON fixtures — canned planner outputs
# ---------------------------------------------------------------------------


RESEARCH_PLAN_JSON = json.dumps(
    [
        {
            "id": "source-analysis",
            "title": "Analyse the source repository",
            "category": "research",
            "description": "Clone the repo and explore the codebase.",
            "dependencies": [],
        },
        {
            "id": "web-research",
            "title": "Research workload documentation",
            "category": "research",
            "description": "Fetch external docs and deployment guides.",
            "dependencies": [],
        },
        {
            "id": "operational-discovery",
            "title": "Synthesise design proposal",
            "category": "research",
            "description": "Combine all research into a design proposal.",
            "dependencies": ["source-analysis", "web-research"],
        },
        {
            "id": "confirm-design",
            "title": "Confirm design with user",
            "category": "confirm",
            "description": "Present the design proposal for user approval.",
            "dependencies": ["operational-discovery"],
        },
    ]
)


BUILD_PLAN_JSON = json.dumps(
    [
        {
            "id": "scaffold-charm",
            "title": "Scaffold the charm project",
            "category": "build",
            "description": "Initialise the charm directory structure.",
            "dependencies": [],
        },
        {
            "id": "write-charm-code",
            "title": "Write charm code",
            "category": "build",
            "description": "Implement the charm in src/charm.py.",
            "dependencies": ["scaffold-charm"],
        },
        {
            "id": "write-tests",
            "title": "Write unit tests",
            "category": "build",
            "description": "Write Scenario-based unit tests.",
            "dependencies": ["write-charm-code"],
        },
    ]
)


SAMPLE_DESIGN_MD = """\
# Redis

## Substrate

Kubernetes — Redis is commonly deployed as a containerised service.

## Substrate reasoning

K8s provides easy scaling and Pebble-based workload management.

## Charm path

Custom — Redis has specific operational patterns that require a full ops charm.

## Charm path reasoning

Redis needs custom relation handling for replication and sentinel.

## Charmhub

Build new — no well-maintained Redis charm exists for k8s.

## Integrations

- redis-client (provides)
- cos-agent (requires)
- certificates (requires)

## Config

- port: Redis listening port (default 6379)
- maxmemory: Maximum memory limit
- maxmemory-policy: Eviction policy

## Actions

- backup: Create an RDB snapshot
- restore: Restore from a backup

## Scaling

Horizontal scaling via Redis Sentinel for high availability.

## Operational patterns

Redis uses RDB snapshots and AOF logging for persistence. Health is checked
via the PING command. Clustering is handled through Redis Sentinel.

## Questions

- Should we support Redis Cluster mode?
- What TLS configuration is needed?

## Sources

- https://redis.io/docs/
- https://hub.docker.com/_/redis
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_executor(monkeypatch: pytest.MonkeyPatch):
    """Speed up executor polling and reduce task timeout for tests."""
    import cantrip.agent.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(executor_mod, "_DEFAULT_TASK_TIMEOUT", 5)
