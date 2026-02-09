"""Shared test fixtures and helpers."""

import pytest

from cantrip.llm.base import LLMProvider, Message, Response, Tool


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
    ):
        yield  # pragma: no cover

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
