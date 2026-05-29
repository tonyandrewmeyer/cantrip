"""Tests for Phase 52.5 `cantrip checkpoints {list,show,delete}` CLI handlers.

The three subcommand helpers are small enough to test directly without
spinning up ``main()`` — each takes a ready-to-use ``CheckpointStore``
and writes to stdout / stderr, which ``capsys`` captures.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.runtime.durability import (
    KIND_LLM_RESPONSE,
    KIND_TOOL_RESULT,
    CheckpointStore,
)
from cantrip.agent.store import SessionStore
from cantrip.main import (
    _checkpoints_delete,
    _checkpoints_list,
    _checkpoints_show,
)
from cantrip.transcript.export import TranscriptData
from cantrip.tui.screens.transcript import TranscriptScreen


@pytest.fixture
def store_with_data(tmp_path: pathlib.Path) -> Iterator[SessionStore]:
    """A SessionStore prepopulated with one task and three checkpoints."""
    s = SessionStore(tmp_path / ".cantrip")
    s.open()
    s.save_tasks(
        [
            AgentTask(
                id="task-A",
                title="Build redis",
                category=TaskCategory.BUILD,
                description="",
                status=TaskStatus.DONE,
            )
        ]
    )
    cps = CheckpointStore(s)
    cps.record(
        "task-A",
        "llm_turn",
        1,
        "hash-1",
        KIND_LLM_RESPONSE,
        {
            "content": "turn one",
            "tool_calls": [],
            "finish_reason": "stop",
            "usage": {},
            "metadata": {},
        },
    )
    cps.record(
        "task-A",
        "tool:read_file",
        1,
        "hash-2",
        KIND_TOOL_RESULT,
        {
            "success": True,
            "output": "ok",
            "data": {},
            "error": None,
            "images": [],
            "caption": None,
        },
    )
    cps.record(
        "task-A",
        "llm_turn",
        2,
        "hash-3",
        KIND_LLM_RESPONSE,
        {
            "content": "final",
            "tool_calls": [],
            "finish_reason": "stop",
            "usage": {},
            "metadata": {},
        },
    )
    yield s
    s.close()


class TestCheckpointsList:
    def test_no_tasks_with_checkpoints(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        s = SessionStore(tmp_path / ".cantrip")
        s.open()
        try:
            code = _checkpoints_list(s, CheckpointStore(s), task_id=None)
        finally:
            s.close()
        assert code == 0
        assert "No tasks with checkpoints." in capsys.readouterr().out

    def test_list_all_tasks(
        self, store_with_data: SessionStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _checkpoints_list(store_with_data, CheckpointStore(store_with_data), task_id=None)
        assert code == 0
        out = capsys.readouterr().out
        assert "Build redis" in out
        assert "task-A" in out
        assert "3 step(s)" in out
        assert "llm_turn#1" in out
        assert "tool:read_file#1" in out
        assert "llm_turn#2" in out

    def test_list_filtered_by_task_id(
        self, store_with_data: SessionStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _checkpoints_list(
            store_with_data, CheckpointStore(store_with_data), task_id="task-A"
        )
        assert code == 0
        assert "llm_turn#1" in capsys.readouterr().out

    def test_list_filtered_missing_task(
        self, store_with_data: SessionStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _checkpoints_list(
            store_with_data, CheckpointStore(store_with_data), task_id="task-nope"
        )
        assert code == 0
        assert "No checkpoints for task 'task-nope'." in capsys.readouterr().out


class TestCheckpointsShow:
    def test_show_decodes_blob_as_json(
        self, store_with_data: SessionStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _checkpoints_show(CheckpointStore(store_with_data), "task-A", "llm_turn", 1)
        assert code == 0
        out = capsys.readouterr().out
        assert "Kind:       llm_response" in out
        assert "hash-1" in out
        # The decoded blob appears as pretty-printed JSON below the header.
        assert '"content": "turn one"' in out

    def test_show_missing_row_errors(
        self, store_with_data: SessionStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _checkpoints_show(CheckpointStore(store_with_data), "task-A", "llm_turn", 99)
        assert code == 1
        assert "no checkpoint for" in capsys.readouterr().err


class TestCheckpointsDelete:
    def test_delete_empty_task_is_noop(
        self, store_with_data: SessionStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _checkpoints_delete(CheckpointStore(store_with_data), task_id="task-nope", yes=True)
        assert code == 0
        assert "No checkpoints to delete" in capsys.readouterr().out

    def test_delete_with_yes_purges(
        self, store_with_data: SessionStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cps = CheckpointStore(store_with_data)
        assert cps.count_for_task("task-A") == 3
        code = _checkpoints_delete(cps, task_id="task-A", yes=True)
        assert code == 0
        assert cps.count_for_task("task-A") == 0
        assert "Removed 3 checkpoint(s)" in capsys.readouterr().out

    def test_delete_without_yes_prompts_and_aborts_on_no(
        self,
        store_with_data: SessionStore,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        cps = CheckpointStore(store_with_data)
        code = _checkpoints_delete(cps, task_id="task-A", yes=False)
        assert code == 1
        assert cps.count_for_task("task-A") == 3  # Still there.
        assert "Aborted." in capsys.readouterr().out

    def test_delete_without_yes_confirms_on_y(
        self,
        store_with_data: SessionStore,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
        cps = CheckpointStore(store_with_data)
        code = _checkpoints_delete(cps, task_id="task-A", yes=False)
        assert code == 0
        assert cps.count_for_task("task-A") == 0


class TestTranscriptCheckpointView:
    """Transcript viewer's ``_checkpoint_lines`` renders the new tab."""

    def test_empty_data_shows_notice(self) -> None:
        data = TranscriptData()
        lines = TranscriptScreen._checkpoint_lines(data)
        assert lines == ["No step checkpoints recorded."]

    def test_populated_data_renders_per_task_block(self) -> None:
        data = TranscriptData(
            tasks=[{"id": "task-A", "title": "Build redis"}],
            checkpoints={
                "task-A": [
                    {
                        "step_name": "llm_turn",
                        "ordinal": 1,
                        "input_hash": "abcdef1234567890",
                        "kind": "llm_response",
                        "created_at": "2026-04-24T10:00:00",
                    },
                    {
                        "step_name": "tool:read_file",
                        "ordinal": 1,
                        "input_hash": "deadbeef",
                        "kind": "tool_result",
                        "created_at": "2026-04-24T10:00:01",
                    },
                ]
            },
        )
        lines = TranscriptScreen._checkpoint_lines(data)
        joined = "\n".join(lines)
        assert "Build redis" in joined
        assert "task-A" in joined
        assert "2 step(s)" in joined
        assert "llm_turn#1" in joined
        assert "tool:read_file#1" in joined
        assert "abcdef123456" in joined  # Input hash truncated to 12 chars.
        assert "2026-04-24T10:00:00" in joined

    def test_unknown_task_id_falls_back_to_placeholder(self) -> None:
        """A checkpoint whose task isn't in ``tasks`` still renders."""
        data = TranscriptData(
            tasks=[],
            checkpoints={
                "orphan-task": [
                    {
                        "step_name": "llm_turn",
                        "ordinal": 1,
                        "input_hash": "",
                        "kind": "llm_response",
                        "created_at": "2026-04-24T10:00:00",
                    }
                ]
            },
        )
        lines = TranscriptScreen._checkpoint_lines(data)
        joined = "\n".join(lines)
        assert "(unknown task)" in joined
        assert "orphan-task" in joined
        assert "(none)" in joined  # Empty input_hash falls back to "(none)".
