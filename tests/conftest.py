"""Shared test fixtures and helpers."""

from __future__ import annotations

import pathlib

import pytest

from cantrip.agent.queue import AgentTask
from cantrip.llm.base import Chunk, LLMProvider, Message, Response, Tool


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom CLI flags."""
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests (charmcraft comparison, real builds).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests marked ``slow`` unless ``--run-slow`` is given."""
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(reason="need --run-slow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(autouse=True)
def _disable_pypi_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the PyPI self-update check (Phase 63) off during tests.

    The TUI's ``on_mount`` kicks off ``check_for_update()`` as a
    background worker and the CLI fires it from ``_repl``.  Tests
    should never touch the live PyPI JSON endpoint — opt out by
    default and let the dedicated ``test_update.py`` suite re-enable
    the check with monkeypatches and fake transports.
    """
    monkeypatch.setenv("CANTRIP_NO_UPDATE_CHECK", "1")


class FakeProvider(LLMProvider):
    """A fake LLM provider for testing.

    Accepts an optional list of canned Response objects. Each call to
    complete() pops the next response; once exhausted it returns a
    default "default response" message.
    """

    @property
    def name(self) -> str:
        return "fake"

    @property
    def context_window_tokens(self) -> int:
        return self._context_window_tokens

    def __init__(
        self,
        responses: list[Response] | None = None,
        context_window_tokens: int = 200_000,
    ):
        self._responses = list(responses or [])
        self._call_count = 0
        self.model_name = "fake-model"
        self._context_window_tokens = context_window_tokens

    async def complete(
        self,
        messages: list[Message],  # noqa: ARG002
        tools: list[Tool] | None = None,  # noqa: ARG002
        temperature: float = 0.7,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        thinking_budget: int | None = None,  # noqa: ARG002
    ) -> Response:
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return Response(content="default response")

    async def stream(
        self,
        messages: list[Message],  # noqa: ARG002
        tools: list[Tool] | None = None,  # noqa: ARG002
        temperature: float = 0.7,  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
        thinking_budget: int | None = None,  # noqa: ARG002
    ):
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
        else:
            resp = Response(content="default response")

        # Yield text content as individual word chunks to simulate streaming.
        if resp.content:
            words = resp.content.split(" ")
            for i, word in enumerate(words):
                text = word if i == 0 else " " + word
                yield Chunk(content=text)

        yield Chunk(
            tool_calls=resp.tool_calls,
            is_final=True,
            usage=resp.usage,
            metadata=resp.metadata,
        )

    def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages (approximate)."""
        total = 0
        for msg in messages:
            total += len(msg.content)
            for tc in msg.tool_calls:
                total += len(tc.name) + len(str(tc.arguments))
            for tr in msg.tool_results:
                total += len(tr.content)
        return total // 4


@pytest.fixture
def fake_provider() -> FakeProvider:
    """Return a FakeProvider with no canned responses."""
    return FakeProvider()


# ---------------------------------------------------------------------------
# Fake service implementations for executor protocol injection (Phase 21.2)
# ---------------------------------------------------------------------------


class FakeGitService:
    """In-memory fake for the GitService protocol.

    Tracks calls and returns configurable values without touching the
    filesystem or invoking subprocess.
    """

    def __init__(
        self,
        *,
        fingerprints: list[str] | None = None,
        head: str | None = "abc123",
        uncommitted: bool = False,
    ) -> None:
        self._fingerprints = list(fingerprints or [])
        self._fp_idx = 0
        self._head = head
        self._uncommitted = uncommitted
        self.revert_calls: list[tuple[str, str, str]] = []

    def fingerprint(self, charm_path: str | pathlib.Path | None) -> str:
        if not charm_path or not self._fingerprints:
            return ""
        if self._fp_idx < len(self._fingerprints):
            fp = self._fingerprints[self._fp_idx]
            self._fp_idx += 1
            return fp
        return self._fingerprints[-1]

    def snapshot_head(self, charm_path: str | pathlib.Path | None) -> str | None:
        if not charm_path:
            return None
        return self._head

    def revert_to_clean(
        self,
        charm_path: str | pathlib.Path,
        task: AgentTask,
        snapshot: str,
    ) -> None:
        self.revert_calls.append((str(charm_path), task.id, snapshot))

    def has_uncommitted_changes(self, charm_path: str | pathlib.Path) -> bool:  # noqa: ARG002
        return self._uncommitted


class FakeStateService:
    """In-memory fake for the StateService protocol."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str]]] = []
        self.usage_records: list[dict[str, object]] = []
        self.saved_tasks: list[list[AgentTask]] = []

    def record_event(self, event_type: str, detail: dict[str, str]) -> None:
        self.events.append((event_type, detail))

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        self.usage_records.append(
            {
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        )

    def save_tasks(self, tasks: list[AgentTask]) -> None:
        self.saved_tasks.append(list(tasks))


class FakeEnvironmentChecker:
    """Fake for the EnvironmentChecker protocol."""

    def __init__(self, error: str | None = None) -> None:
        self._error = error

    def check(self, task: AgentTask) -> str | None:  # noqa: ARG002
        return self._error


class FakeFollowupPlanner:
    """Fake for the FollowupPlanner protocol."""

    def __init__(self, followups: list[AgentTask] | None = None) -> None:
        self._followups = followups or []

    def followup_tasks(self, task: AgentTask) -> list[AgentTask]:  # noqa: ARG002
        return list(self._followups)
