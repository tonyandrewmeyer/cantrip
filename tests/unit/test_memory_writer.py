"""Tests for the memory auto-writer (Phase 43.2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from cantrip.agent.memory import GlobalMemoryStore, MemoryManager
from cantrip.agent.memory_writer import (
    AutoWriter,
    TriggerKind,
    WriteMemoryContext,
    collect_file_citations,
    parse_writer_response,
)
from cantrip.agent.store import SessionStore
from cantrip.llm.base import Response
from tests.conftest import FakeProvider


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SessionStore]:
    s = SessionStore(tmp_path / ".cantrip")
    s.open()
    yield s
    s.close()


@pytest.fixture
def global_store(tmp_path: Path) -> GlobalMemoryStore:
    return GlobalMemoryStore(tmp_path / "globalmem")


@pytest.fixture
def manager(store: SessionStore, global_store: GlobalMemoryStore, tmp_path: Path) -> MemoryManager:
    return MemoryManager(session_store=store, global_store=global_store, charm_path=tmp_path)


# ── parse_writer_response ───────────────────────────────────────────────


class TestParseWriterResponse:
    """The JSON parser handles common LLM output shapes."""

    def test_bare_json(self) -> None:
        payload = parse_writer_response('{"decision": "skip"}')
        assert payload == {"decision": "skip"}

    def test_fenced_json_labelled(self) -> None:
        raw = '```json\n{"decision": "write"}\n```'
        assert parse_writer_response(raw) == {"decision": "write"}

    def test_fenced_json_unlabelled(self) -> None:
        raw = '```\n{"decision": "write"}\n```'
        assert parse_writer_response(raw) == {"decision": "write"}

    def test_surrounding_prose_tolerated(self) -> None:
        raw = 'Here is the decision:\n\n{"decision": "skip", "reasoning": "x"}\n\nThanks.'
        assert parse_writer_response(raw)["decision"] == "skip"

    def test_rejects_non_object(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            parse_writer_response("[1, 2, 3]")

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError, match="no JSON"):
            parse_writer_response("this is not json at all")


# ── collect_file_citations ──────────────────────────────────────────────


class TestCollectFileCitations:
    """Scanning tool-call logs for file-path citations."""

    def test_extracts_file_paths(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        calls = [
            {"name": "read_file", "arguments": {"path": str(tmp_path / "a.py")}},
            {"name": "edit_file", "arguments": {"path": str(tmp_path / "b.py")}},
        ]
        paths = collect_file_citations(calls)
        assert len(paths) == 2
        assert any(p.name == "a.py" for p in paths)
        assert any(p.name == "b.py" for p in paths)

    def test_deduplicates(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("a")
        calls = [
            {"name": "read_file", "arguments": {"path": str(tmp_path / "a.py")}},
            {"name": "read_file", "arguments": {"path": str(tmp_path / "a.py")}},
        ]
        paths = collect_file_citations(calls)
        assert len(paths) == 1

    def test_ignores_non_file_tools(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("a")
        calls = [
            {"name": "juju_status", "arguments": {}},
            {"name": "read_file", "arguments": {"path": str(tmp_path / "a.py")}},
        ]
        paths = collect_file_citations(calls)
        assert len(paths) == 1

    def test_drops_missing_files(self, tmp_path: Path) -> None:
        calls = [
            {
                "name": "read_file",
                "arguments": {"path": str(tmp_path / "does_not_exist.py")},
            }
        ]
        assert collect_file_citations(calls) == []

    def test_relative_paths_need_base(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        f = tmp_path / "src" / "charm.py"
        f.write_text("x")
        calls = [{"name": "read_file", "arguments": {"path": "src/charm.py"}}]
        assert collect_file_citations(calls) == []  # No base given.
        paths = collect_file_citations(calls, base_path=tmp_path)
        assert [p.resolve() for p in paths] == [f.resolve()]

    def test_multi_edit_and_file_path_arg(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("a")
        calls = [
            {
                "name": "multi_edit",
                "arguments": {"file_path": str(tmp_path / "a.py")},
            }
        ]
        paths = collect_file_citations(calls)
        assert len(paths) == 1


# ── AutoWriter ──────────────────────────────────────────────────────────


def _writer_response(payload: dict[str, object]) -> Response:
    """Wrap *payload* as a canned LLM response for FakeProvider."""
    return Response(content=json.dumps(payload))


class TestAutoWriterPropose:
    """Proposing a memory without persisting it."""

    @pytest.mark.asyncio
    async def test_skip_decision(self, manager: MemoryManager) -> None:
        provider = FakeProvider(
            responses=[_writer_response({"decision": "skip", "reasoning": "not durable"})]
        )
        writer = AutoWriter(provider=provider, manager=manager)
        context = WriteMemoryContext(trigger=TriggerKind.USER_CORRECTION, summary="minor typo")
        decision = await writer.propose(context)
        assert decision.decision == "skip"
        assert "not durable" in decision.reasoning
        assert decision.proposal is None
        assert decision.persisted is False

    @pytest.mark.asyncio
    async def test_write_decision(self, manager: MemoryManager) -> None:
        provider = FakeProvider(
            responses=[
                _writer_response(
                    {
                        "decision": "write",
                        "reasoning": "saves 10 min next time",
                        "memory": {
                            "title": "uv-lock-stale",
                            "kind": "lesson",
                            "scope": "global",
                            "body": "Run `uv lock` before charmcraft pack.",
                            "tags": ["uv", "charmcraft"],
                        },
                    }
                )
            ]
        )
        writer = AutoWriter(provider=provider, manager=manager)
        decision = await writer.propose(
            WriteMemoryContext(
                trigger=TriggerKind.TOOL_FAILURE_RETRY,
                summary="charmcraft pack failed; uv lock fixed it",
            )
        )
        assert decision.decision == "write"
        assert decision.proposal is not None
        assert decision.proposal.title == "uv-lock-stale"
        assert decision.proposal.kind == "lesson"
        assert decision.proposal.scope == "global"
        assert decision.proposal.tags == ["uv", "charmcraft"]
        assert decision.persisted is False  # propose() never writes.

    @pytest.mark.asyncio
    async def test_malformed_json_becomes_skip(self, manager: MemoryManager) -> None:
        provider = FakeProvider(responses=[Response(content="nope, not json")])
        writer = AutoWriter(provider=provider, manager=manager)
        decision = await writer.propose(
            WriteMemoryContext(trigger=TriggerKind.USER_CORRECTION, summary="x")
        )
        assert decision.decision == "skip"
        assert "parse failed" in decision.reasoning
        assert decision.error is not None

    @pytest.mark.asyncio
    async def test_missing_required_fields_becomes_skip(self, manager: MemoryManager) -> None:
        provider = FakeProvider(
            responses=[
                _writer_response(
                    {
                        "decision": "write",
                        "reasoning": "x",
                        "memory": {"title": "", "kind": "fact", "scope": "charm"},
                    }
                )
            ]
        )
        writer = AutoWriter(provider=provider, manager=manager)
        decision = await writer.propose(
            WriteMemoryContext(trigger=TriggerKind.USER_CORRECTION, summary="x")
        )
        assert decision.decision == "skip"
        assert decision.error == "missing required fields"


class TestAutoWriterWrite:
    """The full propose-then-persist path."""

    @pytest.mark.asyncio
    async def test_persists_with_citations(self, manager: MemoryManager, tmp_path: Path) -> None:
        source = tmp_path / "src.py"
        source.write_text("charm code here\n")
        provider = FakeProvider(
            responses=[
                _writer_response(
                    {
                        "decision": "write",
                        "reasoning": "keep it",
                        "memory": {
                            "title": "coverage-threshold",
                            "kind": "rule",
                            "scope": "charm",
                            "body": "Keep coverage above 80.",
                            "tags": ["tests"],
                        },
                    }
                )
            ]
        )
        writer = AutoWriter(provider=provider, manager=manager)
        context = WriteMemoryContext(
            trigger=TriggerKind.USER_CORRECTION,
            summary="user raised the coverage threshold",
            cited_paths=[source],
            charm_path=tmp_path,
        )
        decision = await writer.write(context)
        assert decision.persisted
        assert decision.entry is not None
        assert decision.entry.title == "coverage-threshold"
        # Citation was captured with a real SHA.
        citations = decision.entry.citations
        assert len(citations) == 1
        cite = citations[0]
        assert cite["path"] == str(source)
        assert len(cite["sha"]) == 64  # SHA-256 hex length.
        # Source field is set to "auto" so later queries can separate
        # auto-written memories from manual ones.
        assert decision.entry.source == "auto"

    @pytest.mark.asyncio
    async def test_skip_decision_does_not_persist(self, manager: MemoryManager) -> None:
        provider = FakeProvider(
            responses=[_writer_response({"decision": "skip", "reasoning": "trivial"})]
        )
        writer = AutoWriter(provider=provider, manager=manager)
        decision = await writer.write(
            WriteMemoryContext(trigger=TriggerKind.USER_CORRECTION, summary="typo fix")
        )
        assert decision.decision == "skip"
        assert not decision.persisted
        assert manager.list_entries() == []

    @pytest.mark.asyncio
    async def test_write_with_missing_file_still_persists_without_citation(
        self, manager: MemoryManager, tmp_path: Path
    ) -> None:
        """Unreadable citation paths are dropped rather than blocking the write."""
        provider = FakeProvider(
            responses=[
                _writer_response(
                    {
                        "decision": "write",
                        "reasoning": "good one",
                        "memory": {
                            "title": "t",
                            "kind": "fact",
                            "scope": "charm",
                            "body": "b",
                        },
                    }
                )
            ]
        )
        writer = AutoWriter(provider=provider, manager=manager)
        missing = tmp_path / "gone.py"
        decision = await writer.write(
            WriteMemoryContext(
                trigger=TriggerKind.TASK_COMPLETE,
                summary="task done",
                cited_paths=[missing],
                charm_path=tmp_path,
            )
        )
        assert decision.persisted
        assert decision.entry is not None
        assert decision.entry.citations == []

    @pytest.mark.asyncio
    async def test_provider_exception_becomes_skip(self, manager: MemoryManager) -> None:
        class ExplodingProvider(FakeProvider):
            async def complete(self, *args, **kwargs):  # type: ignore[override]
                raise RuntimeError("boom")

        writer = AutoWriter(provider=ExplodingProvider(), manager=manager)
        decision = await writer.write(
            WriteMemoryContext(trigger=TriggerKind.USER_CORRECTION, summary="x")
        )
        assert decision.decision == "skip"
        assert decision.error is not None
        assert "boom" in decision.error

    @pytest.mark.asyncio
    async def test_invalid_scope_becomes_write_but_not_persisted(
        self, manager: MemoryManager
    ) -> None:
        """If the LLM returns an unknown scope the write surfaces the error."""
        provider = FakeProvider(
            responses=[
                _writer_response(
                    {
                        "decision": "write",
                        "reasoning": "x",
                        "memory": {
                            "title": "t",
                            "kind": "fact",
                            "scope": "elsewhere",
                            "body": "b",
                        },
                    }
                )
            ]
        )
        writer = AutoWriter(provider=provider, manager=manager)
        decision = await writer.write(
            WriteMemoryContext(trigger=TriggerKind.USER_CORRECTION, summary="x")
        )
        assert decision.decision == "write"
        assert not decision.persisted
        assert decision.error is not None


# ── User-correction trigger detection ──────────────────────────────────


class TestIsUserCorrection:
    """Heuristic detection of user-correction phrases."""

    @pytest.mark.parametrize(
        "message",
        [
            "no, that's wrong",
            "Actually, use postgres",
            "wait, stop",
            "don't run charmcraft pack again",
            "Don't push to main",
            "Please always use uv lock first",
            "never delete the .cantrip file",
            "do not modify the rockcraft.yaml",
            "that's wrong — try again",
            "that is incorrect",
            "not what i asked for",
            "not like that",
            "instead, use the existing charm",
            "Always include ops-tracing",
            "Never use Harness",
        ],
    )
    def test_detects_corrections(self, message: str) -> None:
        from cantrip.agent.core import _is_user_correction

        assert _is_user_correction(message)

    @pytest.mark.parametrize(
        "message",
        [
            "I don't see the issue",  # "don't" but not imperative.
            "thanks, that worked",
            "build me a charm for redis",
            "what does this do?",
            "I think we should add COS",
            "sometimes this happens",
            "",
            "   ",
        ],
    )
    def test_skips_non_corrections(self, message: str) -> None:
        from cantrip.agent.core import _is_user_correction

        assert not _is_user_correction(message)


# ── Memory event emission ──────────────────────────────────────────────


class TestMemoryCallbacks:
    """Write/recall callbacks fire on the right operations."""

    def test_write_callback_fires(self, manager: MemoryManager) -> None:
        seen: list[str] = []
        manager.set_write_callback(lambda e: seen.append(e.title))
        manager.write(scope="charm", title="t", kind="fact", body="b")
        assert seen == ["t"]

    def test_write_callback_fires_for_global_scope(self, manager: MemoryManager) -> None:
        seen: list[str] = []
        manager.set_write_callback(lambda e: seen.append(e.scope))
        manager.write(scope="global", title="g", kind="fact", body="b")
        assert seen == ["global"]

    def test_recall_callback_fires_on_read(self, manager: MemoryManager) -> None:
        manager.write(scope="charm", title="t", kind="fact", body="b")
        seen: list[str] = []
        manager.set_recall_callback(lambda e: seen.append(e.title))
        assert manager.read(title="t") is not None
        assert seen == ["t"]

    def test_recall_callback_does_not_fire_on_miss(self, manager: MemoryManager) -> None:
        seen: list[str] = []
        manager.set_recall_callback(lambda e: seen.append(e.title))
        assert manager.read(title="never-existed") is None
        assert seen == []

    def test_callback_failures_swallowed(self, manager: MemoryManager) -> None:
        """A broken UI hook never breaks the underlying memory operation."""

        def boom(_entry: object) -> None:
            raise RuntimeError("ui exploded")

        manager.set_write_callback(boom)
        manager.set_recall_callback(boom)
        # Both must succeed despite the callback exploding.
        manager.write(scope="charm", title="t", kind="fact", body="b")
        assert manager.read(title="t") is not None


# ── Trigger integration with CantripAgent ──────────────────────────────


class TestCorrectionTriggerIntegration:
    """End-to-end test that a user correction fires the auto-writer."""

    @pytest.mark.asyncio
    async def test_correction_message_fires_writer_and_emits_event(self, tmp_path: Path) -> None:
        """A correction message in process_message persists a memory and emits MEMORY_WRITTEN."""
        from cantrip.agent.core import CantripAgent
        from cantrip.ui.events import EventType

        # Two canned responses: the first is the conversation loop's
        # answer to the user; the second is the auto-writer's JSON.
        provider = FakeProvider(
            responses=[
                Response(content="okay, I'll switch approach"),
                _writer_response(
                    {
                        "decision": "write",
                        "reasoning": "user correction worth recording",
                        "memory": {
                            "title": "skip-charmcraft-pack",
                            "kind": "rule",
                            "scope": "charm",
                            "body": "Don't run charmcraft pack on this charm.",
                            "tags": ["charmcraft"],
                        },
                    }
                ),
            ]
        )
        agent = CantripAgent(provider=provider, charm_path=tmp_path)
        captured: list[str] = []

        def _capture(event: object) -> None:
            assert hasattr(event, "type")
            captured.append(event.type)  # type: ignore[attr-defined]

        agent.event_bus.subscribe(EventType.MEMORY_WRITTEN, _capture)

        await agent.process_message("don't run charmcraft pack again")
        # Drain the background auto-writer task spawned by process_message.
        for task in list(agent._memory_background_tasks):
            await task

        assert EventType.MEMORY_WRITTEN in captured
        # Memory landed in the manager.
        entry = agent._memory_manager.read(title="skip-charmcraft-pack")
        assert entry is not None
        assert entry.kind == "rule"
        assert entry.source == "auto"

    @pytest.mark.asyncio
    async def test_non_correction_does_not_fire_writer(self, tmp_path: Path) -> None:
        from cantrip.agent.core import CantripAgent

        provider = FakeProvider(responses=[Response(content="working on it")])
        agent = CantripAgent(provider=provider, charm_path=tmp_path)

        await agent.process_message("build me a charm for redis")
        # No background tasks should have been scheduled.
        assert agent._memory_background_tasks == set()
        # And nothing landed in the manager.
        assert agent._memory_manager.list_entries() == []
