"""Tests for step-level durable-execution checkpoints (Phase 52.1)."""

import datetime
import pathlib
import sqlite3
from collections.abc import Iterator

import pytest

from cantrip.agent.durability import (
    KEEP_CHECKPOINTS_ENV,
    KIND_BYTES,
    KIND_LLM_RESPONSE,
    KIND_TOOL_RESULT,
    KIND_VALUE,
    NO_RESUME_ENV,
    CheckpointCtx,
    CheckpointRecord,
    CheckpointStore,
    checkpoint,
    compute_input_hash,
    response_from_dict,
    response_to_dict,
    should_keep_checkpoints,
    should_skip_resume,
    tool_result_from_dict,
    tool_result_to_dict,
)
from cantrip.agent.store import SessionStore
from cantrip.agent.tools.base import ToolResult as AgentToolResult
from cantrip.llm.base import Image, Response, ToolCall


@pytest.fixture
def store(tmp_path: pathlib.Path) -> Iterator[SessionStore]:
    """Return an open SessionStore backed by a temporary file."""
    s = SessionStore(tmp_path / ".cantrip")
    s.open()
    yield s
    s.close()


@pytest.fixture
def checkpoints(store: SessionStore) -> CheckpointStore:
    """Thin CheckpointStore over the tmp-backed SessionStore."""
    return CheckpointStore(store)


class TestSchema:
    """The v10 schema change creates ``step_checkpoints`` on fresh + migrated DBs."""

    def test_fresh_db_has_table(self, store: SessionStore) -> None:
        rows = store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='step_checkpoints'"
        ).fetchall()
        assert len(rows) == 1

    def test_fresh_db_has_index(self, store: SessionStore) -> None:
        rows = store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_step_checkpoints_task'"
        ).fetchall()
        assert len(rows) == 1

    def test_migration_from_v9_adds_table(self, tmp_path: pathlib.Path) -> None:
        """A pre-v10 database gains the table when the store opens it."""
        db_path = tmp_path / ".cantrip"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (9);
            CREATE TABLE tasks (id TEXT PRIMARY KEY);
        """)
        conn.commit()
        conn.close()

        store = SessionStore(db_path)
        store.open()
        try:
            tables = {
                r[0]
                for r in store._db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "step_checkpoints" in tables
            # Version now matches SCHEMA_VERSION.
            from cantrip.agent.store import SCHEMA_VERSION

            [(version,)] = store._db.execute("SELECT version FROM schema_version").fetchall()
            assert version == SCHEMA_VERSION
        finally:
            store.close()

    def test_unique_constraint_on_task_step_ordinal(self, store: SessionStore) -> None:
        """``(task_id, step_name, ordinal)`` is UNIQUE — upsert replaces cleanly."""
        store.record_checkpoint(
            task_id="t1",
            step_name="llm_turn",
            ordinal=1,
            input_hash="h1",
            result_kind=KIND_VALUE,
            result_blob=b"first",
        )
        # Same triple → upsert (INSERT OR REPLACE), not a conflict.
        store.record_checkpoint(
            task_id="t1",
            step_name="llm_turn",
            ordinal=1,
            input_hash="h2",
            result_kind=KIND_VALUE,
            result_blob=b"second",
        )
        row = store.get_checkpoint("t1", "llm_turn", 1)
        assert row is not None
        assert row["input_hash"] == "h2"
        assert bytes(row["result_blob"]) == b"second"


class TestSessionStoreMethods:
    """Direct SessionStore CRUD — the raw SQL surface ``CheckpointStore`` wraps."""

    def test_record_and_get_round_trips_bytes(self, store: SessionStore) -> None:
        store.record_checkpoint(
            task_id="t1",
            step_name="tool:juju_status",
            ordinal=1,
            input_hash="abc",
            result_kind=KIND_TOOL_RESULT,
            result_blob=b'{"success": true}',
        )
        row = store.get_checkpoint("t1", "tool:juju_status", 1)
        assert row is not None
        assert row["task_id"] == "t1"
        assert row["step_name"] == "tool:juju_status"
        assert row["ordinal"] == 1
        assert row["input_hash"] == "abc"
        assert row["result_kind"] == KIND_TOOL_RESULT
        assert bytes(row["result_blob"]) == b'{"success": true}'
        assert row["created_at"]

    def test_get_returns_none_when_absent(self, store: SessionStore) -> None:
        assert store.get_checkpoint("missing", "llm_turn", 1) is None

    def test_next_ordinal_starts_at_1(self, store: SessionStore) -> None:
        assert store.next_checkpoint_ordinal("fresh-task", "llm_turn") == 1

    def test_next_ordinal_increments(self, store: SessionStore) -> None:
        for n in (1, 2, 3):
            store.record_checkpoint(
                task_id="t1",
                step_name="llm_turn",
                ordinal=n,
                input_hash=f"h{n}",
                result_kind=KIND_VALUE,
                result_blob=b"",
            )
        assert store.next_checkpoint_ordinal("t1", "llm_turn") == 4
        # A different step name has its own counter.
        assert store.next_checkpoint_ordinal("t1", "tool:foo") == 1

    def test_list_for_task_returns_insertion_order(self, store: SessionStore) -> None:
        for name, ordinal in [("llm_turn", 1), ("tool:x", 1), ("llm_turn", 2)]:
            store.record_checkpoint(
                task_id="t1",
                step_name=name,
                ordinal=ordinal,
                input_hash=f"h-{name}-{ordinal}",
                result_kind=KIND_VALUE,
                result_blob=b"",
            )
        rows = store.list_checkpoints_for_task("t1")
        assert [(r["step_name"], r["ordinal"]) for r in rows] == [
            ("llm_turn", 1),
            ("tool:x", 1),
            ("llm_turn", 2),
        ]

    def test_count_for_task(self, store: SessionStore) -> None:
        for n in (1, 2, 3):
            store.record_checkpoint(
                task_id="t1",
                step_name="llm_turn",
                ordinal=n,
                input_hash=f"h{n}",
                result_kind=KIND_VALUE,
                result_blob=b"",
            )
        assert store.count_checkpoints_for_task("t1") == 3
        assert store.count_checkpoints_for_task("other") == 0

    def test_purge_removes_only_target_task(self, store: SessionStore) -> None:
        for task_id in ("t1", "t2"):
            store.record_checkpoint(
                task_id=task_id,
                step_name="llm_turn",
                ordinal=1,
                input_hash="h",
                result_kind=KIND_VALUE,
                result_blob=b"",
            )
        removed = store.purge_checkpoints_for_task("t1")
        assert removed == 1
        assert store.count_checkpoints_for_task("t1") == 0
        assert store.count_checkpoints_for_task("t2") == 1


class TestCheckpointStore:
    """The JSON-envelope facade and kind-dispatching decoder."""

    def test_record_and_get_round_trips_json_value(self, checkpoints: CheckpointStore) -> None:
        value = {"turn": 3, "tokens": 412, "tools": ["juju_status", "read_file"]}
        checkpoints.record("t1", "llm_turn", 1, "hash-1", KIND_LLM_RESPONSE, value)
        record = checkpoints.get("t1", "llm_turn", 1)
        assert record is not None
        assert record.task_id == "t1"
        assert record.step_name == "llm_turn"
        assert record.ordinal == 1
        assert record.input_hash == "hash-1"
        assert record.kind == KIND_LLM_RESPONSE
        assert record.decode() == value

    def test_get_returns_none_for_missing(self, checkpoints: CheckpointStore) -> None:
        assert checkpoints.get("nope", "llm_turn", 1) is None

    def test_bytes_kind_stores_blob_verbatim(self, checkpoints: CheckpointStore) -> None:
        raw = b"\x82\xa3key\xa5value\xa1n\x01"  # Arbitrary non-utf-8 bytes.
        checkpoints.record("t1", "opaque", 1, "h", KIND_BYTES, raw)
        record = checkpoints.get("t1", "opaque", 1)
        assert record is not None
        assert record.decode() == raw

    def test_bytes_kind_rejects_non_bytes(self, checkpoints: CheckpointStore) -> None:
        with pytest.raises(TypeError, match="requires bytes"):
            checkpoints.record("t1", "opaque", 1, "h", KIND_BYTES, "not bytes")

    def test_non_serialisable_value_raises_at_record_time(
        self, checkpoints: CheckpointStore
    ) -> None:
        """Loud-failure on record so a stale caller doesn't mask the bug."""

        class NotSerialisable:
            pass

        with pytest.raises(TypeError, match="not JSON-serialisable"):
            checkpoints.record("t1", "bad", 1, "h", KIND_VALUE, NotSerialisable())

    def test_json_default_handles_common_types(self, checkpoints: CheckpointStore) -> None:
        """``Path``, ``datetime``, and ``set`` round-trip through the envelope."""
        path = pathlib.Path("/tmp/charm")
        ts = datetime.datetime(2026, 4, 24, 12, 30, tzinfo=datetime.UTC)
        tags = {"build", "deploy"}
        value = {"path": path, "ts": ts, "tags": tags}
        checkpoints.record("t1", "plan", 1, "h", KIND_VALUE, value)
        decoded = checkpoints.get("t1", "plan", 1)
        assert decoded is not None
        payload = decoded.decode()
        assert isinstance(payload, dict)
        assert payload["path"] == "/tmp/charm"
        assert payload["ts"].startswith("2026-04-24T12:30:00")
        # Sets round-trip as sorted lists.
        assert sorted(payload["tags"]) == ["build", "deploy"]

    def test_next_ordinal_delegates(self, checkpoints: CheckpointStore) -> None:
        checkpoints.record("t1", "llm_turn", 1, "h", KIND_VALUE, 1)
        assert checkpoints.next_ordinal("t1", "llm_turn") == 2

    def test_list_for_task_returns_records(self, checkpoints: CheckpointStore) -> None:
        checkpoints.record("t1", "llm_turn", 1, "h1", KIND_LLM_RESPONSE, {"turn": 1})
        checkpoints.record("t1", "llm_turn", 2, "h2", KIND_LLM_RESPONSE, {"turn": 2})
        records = checkpoints.list_for_task("t1")
        assert [r.ordinal for r in records] == [1, 2]
        assert all(isinstance(r, CheckpointRecord) for r in records)
        assert records[1].decode() == {"turn": 2}

    def test_count_for_task_matches_store(self, checkpoints: CheckpointStore) -> None:
        checkpoints.record("t1", "llm_turn", 1, "h", KIND_VALUE, {})
        assert checkpoints.count_for_task("t1") == 1
        assert checkpoints.count_for_task("other") == 0

    def test_purge_task_bypasses_env_var(
        self,
        checkpoints: CheckpointStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``purge_task`` is the blunt tool — even $KEEP set can't save you."""
        monkeypatch.setenv(KEEP_CHECKPOINTS_ENV, "1")
        checkpoints.record("t1", "llm_turn", 1, "h", KIND_VALUE, {})
        removed = checkpoints.purge_task("t1")
        assert removed == 1
        assert checkpoints.count_for_task("t1") == 0


class TestOnTaskDone:
    """GC hook honours ``$CANTRIP_KEEP_CHECKPOINTS`` for debugging."""

    def test_purges_completed_task_by_default(
        self,
        checkpoints: CheckpointStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(KEEP_CHECKPOINTS_ENV, raising=False)
        checkpoints.record("t1", "llm_turn", 1, "h", KIND_VALUE, {})
        checkpoints.record("t1", "llm_turn", 2, "h", KIND_VALUE, {})
        checkpoints.on_task_done("t1")
        assert checkpoints.count_for_task("t1") == 0

    def test_skips_purge_when_env_var_set(
        self,
        checkpoints: CheckpointStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(KEEP_CHECKPOINTS_ENV, "1")
        checkpoints.record("t1", "llm_turn", 1, "h", KIND_VALUE, {})
        checkpoints.on_task_done("t1")
        assert checkpoints.count_for_task("t1") == 1

    def test_other_truthy_env_values(
        self,
        checkpoints: CheckpointStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Common truthy shapes all disable the purge."""
        for raw in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv(KEEP_CHECKPOINTS_ENV, raw)
            assert should_keep_checkpoints(), f"{raw!r} should be truthy"

    def test_zero_and_empty_are_falsy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for raw in ("0", "false", "", "no"):
            monkeypatch.setenv(KEEP_CHECKPOINTS_ENV, raw)
            assert not should_keep_checkpoints(), f"{raw!r} should be falsy"

    def test_does_not_touch_other_tasks(
        self,
        checkpoints: CheckpointStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv(KEEP_CHECKPOINTS_ENV, raising=False)
        checkpoints.record("t1", "llm_turn", 1, "h", KIND_VALUE, {})
        checkpoints.record("t2", "llm_turn", 1, "h", KIND_VALUE, {})
        checkpoints.on_task_done("t1")
        assert checkpoints.count_for_task("t1") == 0
        assert checkpoints.count_for_task("t2") == 1


class TestInputHash:
    """``compute_input_hash`` is deterministic across equivalent inputs."""

    def test_same_inputs_produce_same_hash(self) -> None:
        a = compute_input_hash("claude-opus-4-7", {"tool": "juju_status", "args": {"x": 1}})
        b = compute_input_hash("claude-opus-4-7", {"tool": "juju_status", "args": {"x": 1}})
        assert a == b

    def test_different_inputs_produce_different_hash(self) -> None:
        a = compute_input_hash("claude-opus-4-7", {"tool": "juju_status"})
        b = compute_input_hash("claude-opus-4-7", {"tool": "juju_deploy"})
        assert a != b

    def test_dict_key_order_does_not_matter(self) -> None:
        """Stable across the same dict re-ordered — that's the whole point."""
        a = compute_input_hash({"a": 1, "b": 2, "c": 3})
        b = compute_input_hash({"c": 3, "a": 1, "b": 2})
        assert a == b

    def test_non_json_types_fall_back_to_repr(self) -> None:
        """Non-native types don't blow up hashing (they get ``repr()``'d)."""

        class X:
            def __repr__(self) -> str:
                return "<X stable>"

        h1 = compute_input_hash(X())
        h2 = compute_input_hash(X())
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex


class TestCheckpointCtx:
    """Per-step monotonic counter that drives ordinal allocation."""

    def test_counter_starts_at_1(self, checkpoints: CheckpointStore) -> None:
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")
        assert ctx.next_ordinal("llm_turn") == 1

    def test_counter_increments_per_call(self, checkpoints: CheckpointStore) -> None:
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")
        assert [ctx.next_ordinal("llm_turn") for _ in range(4)] == [1, 2, 3, 4]

    def test_counters_are_independent_per_step(self, checkpoints: CheckpointStore) -> None:
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")
        assert ctx.next_ordinal("llm_turn") == 1
        assert ctx.next_ordinal("tool:juju_status") == 1
        assert ctx.next_ordinal("llm_turn") == 2
        assert ctx.next_ordinal("tool:juju_status") == 2


class TestCheckpointWrapper:
    """``checkpoint()`` replay semantics: miss runs fn, hit returns stored."""

    async def test_miss_runs_fn_and_persists(self, checkpoints: CheckpointStore) -> None:
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")
        calls = 0

        async def fn() -> dict[str, int]:
            nonlocal calls
            calls += 1
            return {"turn": 3, "tokens": 412}

        result = await checkpoint(ctx, "llm_turn", fn, kind=KIND_LLM_RESPONSE)
        assert result == {"turn": 3, "tokens": 412}
        assert calls == 1
        # Persisted for next run.
        record = checkpoints.get("t1", "llm_turn", 1)
        assert record is not None
        assert record.kind == KIND_LLM_RESPONSE
        assert record.decode() == {"turn": 3, "tokens": 412}

    async def test_hit_returns_stored_without_running_fn(
        self, checkpoints: CheckpointStore
    ) -> None:
        """Simulate a resume: pre-populate the store, then fn must not run."""
        checkpoints.record(
            "t1", "llm_turn", 1, "abc", KIND_LLM_RESPONSE, {"turn": 3, "tokens": 412}
        )
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")
        calls = 0

        async def fn() -> dict[str, int]:
            nonlocal calls
            calls += 1
            return {"turn": 999, "tokens": 0}  # Different value — proves we didn't run.

        result = await checkpoint(ctx, "llm_turn", fn, kind=KIND_LLM_RESPONSE)
        assert result == {"turn": 3, "tokens": 412}
        assert calls == 0

    async def test_auto_numbers_repeated_calls(self, checkpoints: CheckpointStore) -> None:
        """Successive calls for the same step name walk ordinals 1, 2, 3."""
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")

        async def make_fn(value: int) -> int:
            return value

        results = [await checkpoint(ctx, "llm_turn", lambda v=v: make_fn(v)) for v in (10, 20, 30)]
        assert results == [10, 20, 30]
        records = checkpoints.list_for_task("t1")
        assert [(r.step_name, r.ordinal, r.decode()) for r in records] == [
            ("llm_turn", 1, 10),
            ("llm_turn", 2, 20),
            ("llm_turn", 3, 30),
        ]

    async def test_replay_after_partial_run(self, checkpoints: CheckpointStore) -> None:
        """Session 1 stored turns 1-2; session 2 re-runs but only issues turn 3."""
        checkpoints.record("t1", "llm_turn", 1, "", KIND_VALUE, "first")
        checkpoints.record("t1", "llm_turn", 2, "", KIND_VALUE, "second")
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")
        ran = []

        async def fn(tag: str) -> str:
            ran.append(tag)
            return tag

        r1 = await checkpoint(ctx, "llm_turn", lambda: fn("first-replay"))
        r2 = await checkpoint(ctx, "llm_turn", lambda: fn("second-replay"))
        r3 = await checkpoint(ctx, "llm_turn", lambda: fn("third-fresh"))
        assert r1 == "first"
        assert r2 == "second"
        assert r3 == "third-fresh"
        assert ran == ["third-fresh"]  # Only the miss ran fn.

    async def test_input_hash_mismatch_invalidates_and_reruns(
        self,
        checkpoints: CheckpointStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A different input hash means the stored row is stale — re-run."""
        import logging

        checkpoints.record("t1", "llm_turn", 1, "old-hash", KIND_VALUE, "stale")
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")
        calls = 0

        async def fn() -> str:
            nonlocal calls
            calls += 1
            return "fresh"

        with caplog.at_level(logging.WARNING, logger="cantrip.agent.durability"):
            result = await checkpoint(ctx, "llm_turn", fn, input_hash="new-hash")
        assert result == "fresh"
        assert calls == 1
        # Row overwritten with new hash + new value.
        record = checkpoints.get("t1", "llm_turn", 1)
        assert record is not None
        assert record.input_hash == "new-hash"
        assert record.decode() == "fresh"
        assert any("input-hash mismatch" in rec.message for rec in caplog.records)

    async def test_matching_input_hash_hits(self, checkpoints: CheckpointStore) -> None:
        checkpoints.record("t1", "llm_turn", 1, "h", KIND_VALUE, "cached")
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")
        calls = 0

        async def fn() -> str:
            nonlocal calls
            calls += 1
            return "should not see this"

        result = await checkpoint(ctx, "llm_turn", fn, input_hash="h")
        assert result == "cached"
        assert calls == 0

    async def test_none_input_hash_accepts_any_stored(self, checkpoints: CheckpointStore) -> None:
        """When the caller doesn't supply a hash, any stored row is a hit."""
        checkpoints.record("t1", "llm_turn", 1, "stored-hash", KIND_VALUE, "cached")
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")

        async def fn() -> str:
            raise AssertionError("fn must not run on hit")

        result = await checkpoint(ctx, "llm_turn", fn)
        assert result == "cached"

    async def test_bytes_kind_round_trips(self, checkpoints: CheckpointStore) -> None:
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")

        async def fn() -> bytes:
            return b"\x82\xa3key\xa5value"

        result = await checkpoint(ctx, "opaque", fn, kind=KIND_BYTES)
        assert result == b"\x82\xa3key\xa5value"
        # And replay returns bytes verbatim.
        ctx2 = CheckpointCtx(store=checkpoints, task_id="t1")
        replayed = await checkpoint(ctx2, "opaque", fn, kind=KIND_BYTES)
        assert replayed == b"\x82\xa3key\xa5value"

    async def test_independent_step_names_do_not_interfere(
        self, checkpoints: CheckpointStore
    ) -> None:
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")

        async def fn_llm() -> str:
            return "turn-result"

        async def fn_tool() -> dict[str, object]:
            return {"ok": True}

        assert await checkpoint(ctx, "llm_turn", fn_llm) == "turn-result"
        assert await checkpoint(ctx, "tool:juju_status", fn_tool, kind=KIND_TOOL_RESULT) == {
            "ok": True
        }
        assert await checkpoint(ctx, "llm_turn", fn_llm) == "turn-result"  # ordinal=2 miss
        # Three distinct records, two step names.
        records = checkpoints.list_for_task("t1")
        assert {(r.step_name, r.ordinal) for r in records} == {
            ("llm_turn", 1),
            ("llm_turn", 2),
            ("tool:juju_status", 1),
        }

    async def test_different_tasks_are_isolated(self, checkpoints: CheckpointStore) -> None:
        ctx_a = CheckpointCtx(store=checkpoints, task_id="task-A")
        ctx_b = CheckpointCtx(store=checkpoints, task_id="task-B")
        calls: list[str] = []

        async def fn(tag: str) -> str:
            calls.append(tag)
            return tag

        await checkpoint(ctx_a, "llm_turn", lambda: fn("A-1"))
        await checkpoint(ctx_b, "llm_turn", lambda: fn("B-1"))
        assert calls == ["A-1", "B-1"]  # Both missed — independent stores per task.
        # And each sees only its own rows.
        assert [r.decode() for r in checkpoints.list_for_task("task-A")] == ["A-1"]
        assert [r.decode() for r in checkpoints.list_for_task("task-B")] == ["B-1"]

    async def test_stored_input_hash_empty_when_caller_omits(
        self, checkpoints: CheckpointStore
    ) -> None:
        """Omitting ``input_hash`` on record stores ``""`` — compatible with future opt-in."""
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")

        async def fn() -> int:
            return 42

        await checkpoint(ctx, "llm_turn", fn)
        record = checkpoints.get("t1", "llm_turn", 1)
        assert record is not None
        assert record.input_hash == ""


class TestResponseSerialisation:
    """``response_to_dict`` / ``response_from_dict`` round-trip an ``llm.Response``."""

    def test_round_trips_content_only(self) -> None:
        original = Response(content="hello world", finish_reason="stop")
        restored = response_from_dict(response_to_dict(original))
        assert restored.content == original.content
        assert restored.finish_reason == original.finish_reason
        assert restored.tool_calls == []

    def test_round_trips_tool_calls(self) -> None:
        original = Response(
            content="",
            tool_calls=[
                ToolCall(id="tc1", name="read_file", arguments={"path": "foo.py"}),
                ToolCall(id="tc2", name="grep", arguments={"pattern": "X", "files": ["a", "b"]}),
            ],
        )
        restored = response_from_dict(response_to_dict(original))
        assert len(restored.tool_calls) == 2
        assert restored.tool_calls[0].id == "tc1"
        assert restored.tool_calls[0].name == "read_file"
        assert restored.tool_calls[0].arguments == {"path": "foo.py"}
        assert restored.tool_calls[1].arguments == {"pattern": "X", "files": ["a", "b"]}

    def test_round_trips_usage_and_metadata(self) -> None:
        original = Response(
            content="x",
            usage={"prompt_tokens": 42, "completion_tokens": 17},
            metadata={"_provider_name": "fake", "_task_category": "build"},
        )
        restored = response_from_dict(response_to_dict(original))
        assert restored.usage == {"prompt_tokens": 42, "completion_tokens": 17}
        assert restored.metadata["_task_category"] == "build"


class TestToolResultSerialisation:
    """``tool_result_to_dict`` / ``tool_result_from_dict`` round-trip agent tool results."""

    def test_round_trips_success_path(self) -> None:
        original = AgentToolResult(
            success=True,
            output="42 lines",
            data={"count": 42},
            caption="Read 42 lines from f.py",
        )
        restored = tool_result_from_dict(tool_result_to_dict(original))
        assert restored.success is True
        assert restored.output == "42 lines"
        assert restored.data == {"count": 42}
        assert restored.caption == "Read 42 lines from f.py"
        assert restored.error is None
        assert restored.images == []

    def test_round_trips_failure_path(self) -> None:
        original = AgentToolResult(
            success=False,
            output="",
            error="snapd barfed",
            caption="Pack failed",
        )
        restored = tool_result_from_dict(tool_result_to_dict(original))
        assert restored.success is False
        assert restored.error == "snapd barfed"
        assert restored.caption == "Pack failed"

    def test_round_trips_images_via_base64(self) -> None:
        """Images carry raw bytes; the envelope base64-encodes them."""
        raw = b"\x89PNG\r\n\x1a\n\x00\x01\x02"
        original = AgentToolResult(
            success=True,
            output="screenshot",
            images=[Image(data=raw, mime="image/png")],
        )
        envelope = tool_result_to_dict(original)
        # Envelope is JSON-native — bytes were encoded, not left raw.
        import json

        blob = json.dumps(envelope)
        assert isinstance(blob, str)
        assert b"\x89".decode("latin-1") not in blob  # Raw bytes didn't leak in.
        restored = tool_result_from_dict(envelope)
        assert len(restored.images) == 1
        assert restored.images[0].data == raw
        assert restored.images[0].mime == "image/png"


class TestNoResumeEnv:
    """``CANTRIP_NO_RESUME`` toggles the subagent replay lookup (Phase 52.4)."""

    def test_truthy_values_skip_resume(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for raw in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv(NO_RESUME_ENV, raw)
            assert should_skip_resume(), f"{raw!r} should disable resume"

    def test_falsy_values_keep_resume_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for raw in ("0", "false", "", "no"):
            monkeypatch.setenv(NO_RESUME_ENV, raw)
            assert not should_skip_resume(), f"{raw!r} must leave resume on"

    def test_unset_defaults_to_resume_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(NO_RESUME_ENV, raising=False)
        assert not should_skip_resume()


class TestCheckpointEventEmission:
    """Phase 52.5 — ``checkpoint()`` records structured hit/miss/invalidated events."""

    async def test_miss_records_checkpoint_miss_event(
        self, store: SessionStore, checkpoints: CheckpointStore
    ) -> None:
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")

        async def fn() -> int:
            return 42

        await checkpoint(ctx, "llm_turn", fn, input_hash="h", kind=KIND_LLM_RESPONSE)

        events = store.load_events(event_type="checkpoint_miss")
        assert len(events) == 1
        import json as _json

        detail = events[0]["detail"]
        if isinstance(detail, str):
            detail = _json.loads(detail)
        assert detail["task_id"] == "t1"
        assert detail["step_name"] == "llm_turn"
        assert detail["ordinal"] == 1
        assert detail["kind"] == KIND_LLM_RESPONSE

    async def test_hit_records_checkpoint_hit_event(
        self, store: SessionStore, checkpoints: CheckpointStore
    ) -> None:
        checkpoints.record("t1", "llm_turn", 1, "h", KIND_LLM_RESPONSE, {"turn": 1})
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")

        async def fn() -> dict[str, int]:
            return {"turn": 999}

        await checkpoint(ctx, "llm_turn", fn, input_hash="h", kind=KIND_LLM_RESPONSE)

        hits = store.load_events(event_type="checkpoint_hit")
        misses = store.load_events(event_type="checkpoint_miss")
        assert len(hits) == 1
        assert len(misses) == 0
        import json as _json

        detail = hits[0]["detail"]
        if isinstance(detail, str):
            detail = _json.loads(detail)
        assert detail["ordinal"] == 1
        assert detail["kind"] == KIND_LLM_RESPONSE

    async def test_hash_mismatch_records_invalidated_and_miss(
        self, store: SessionStore, checkpoints: CheckpointStore
    ) -> None:
        checkpoints.record("t1", "llm_turn", 1, "old", KIND_VALUE, "stale")
        ctx = CheckpointCtx(store=checkpoints, task_id="t1")

        async def fn() -> str:
            return "fresh"

        await checkpoint(ctx, "llm_turn", fn, input_hash="new")

        invalidated = store.load_events(event_type="checkpoint_invalidated")
        misses = store.load_events(event_type="checkpoint_miss")
        assert len(invalidated) == 1
        assert len(misses) == 1  # The re-run after invalidation persisted as a miss.
        import json as _json

        invalid_detail = invalidated[0]["detail"]
        if isinstance(invalid_detail, str):
            invalid_detail = _json.loads(invalid_detail)
        assert invalid_detail["stored_hash"] == "old"
        assert invalid_detail["current_hash"] == "new"
