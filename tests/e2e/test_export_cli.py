"""End-to-end tests for the ``cantrip export-transcript`` CLI subcommand.

These tests invoke cantrip as a subprocess, verifying that the CLI
entry point works correctly with all three export formats and produces
valid output files. No LLM API key required.
"""

import json
import subprocess
from pathlib import Path

import pytest

from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_database(charm_path: Path) -> None:
    """Create a .cantrip database with enough data for meaningful exports."""
    db_path = charm_path / ".cantrip"
    store = SessionStore(db_path)
    store.open()

    state = AgentState(
        charm_name="cli-test-charm",
        charm_path=charm_path,
        charm_type="k8s",
        framework="ops",
    )
    store.save_session(state)

    store.record_message("user", "Build me a charm")
    store.record_message("assistant", "Sure, building your charm now.")
    store.record_message(
        "assistant",
        "",
        tool_calls=[
            {"id": "tc1", "name": "write_file", "arguments": {"path": "src/charm.py"}},
        ],
    )
    store.record_message(
        "tool",
        "",
        tool_results=[
            {"tool_call_id": "tc1", "content": "Written.", "is_error": False},
        ],
    )
    store.record_message("assistant", "Done!")

    tasks = [
        AgentTask(
            id="research",
            title="Research workload",
            status=TaskStatus.DONE,
            category=TaskCategory.RESEARCH,
            result="Researched.",
        ),
        AgentTask(
            id="build",
            title="Build charm",
            status=TaskStatus.DONE,
            category=TaskCategory.BUILD,
            result="Built.",
        ),
    ]
    store.save_tasks(tasks)

    store.record_subagent_message("research", 0, "system", "You are a subagent.")
    store.record_subagent_message("research", 1, "assistant", "Research complete.")

    store.record_event("task_started", {"task_id": "research"})
    store.record_event("task_completed", {"task_id": "research"})

    store.record_usage("gemini", "gemini-2.0-flash", 100, 50)

    store.close()


def _run_cantrip(*args: str) -> subprocess.CompletedProcess:
    """Run ``cantrip`` as a subprocess via its console_scripts entry point."""
    return subprocess.run(
        ["uv", "run", "cantrip", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestExportCLI:
    """Test the ``cantrip export-transcript`` subcommand."""

    def test_export_html(self, tmp_path: Path):
        """Export as HTML produces a valid HTML file."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        _seed_database(charm_path)

        result = _run_cantrip("export-transcript", str(charm_path), "--format", "html")

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Transcript exported" in result.stdout

        output_file = charm_path / "transcript.html"
        assert output_file.exists()
        content = output_file.read_text()
        assert "<html" in content
        assert "cli-test-charm" in content

    def test_export_markdown(self, tmp_path: Path):
        """Export as Markdown produces a valid .md file."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        _seed_database(charm_path)

        result = _run_cantrip("export-transcript", str(charm_path), "--format", "markdown")

        assert result.returncode == 0, f"stderr: {result.stderr}"

        output_file = charm_path / "transcript.md"
        assert output_file.exists()
        content = output_file.read_text()
        assert "# Cantrip Transcript" in content
        assert "cli-test-charm" in content
        assert "## Tasks" in content
        assert "## Conversation" in content

    def test_export_jsonl(self, tmp_path: Path):
        """Export as JSONL produces valid newline-delimited JSON."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        _seed_database(charm_path)

        result = _run_cantrip("export-transcript", str(charm_path), "--format", "jsonl")

        assert result.returncode == 0, f"stderr: {result.stderr}"

        output_file = charm_path / "transcript.jsonl"
        assert output_file.exists()
        content = output_file.read_text()
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) >= 5  # messages + events + tasks

        for line in lines:
            parsed = json.loads(line)
            assert "type" in parsed
            assert parsed["type"] in {"message", "event", "task", "subagent_message"}

    def test_export_custom_output_path(self, tmp_path: Path):
        """--output writes to the specified path."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        _seed_database(charm_path)

        output_file = tmp_path / "custom_output.md"
        result = _run_cantrip(
            "export-transcript",
            str(charm_path),
            "--format",
            "markdown",
            "--output",
            str(output_file),
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert output_file.exists()
        assert "cli-test-charm" in output_file.read_text()

    def test_export_filter_task(self, tmp_path: Path):
        """--task filters to a single task."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        _seed_database(charm_path)

        output_file = tmp_path / "filtered.jsonl"
        result = _run_cantrip(
            "export-transcript",
            str(charm_path),
            "--format",
            "jsonl",
            "--task",
            "research",
            "--output",
            str(output_file),
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        content = output_file.read_text()
        lines = [line for line in content.strip().split("\n") if line]

        task_lines = [json.loads(ln) for ln in lines if '"type": "task"' in ln]
        assert len(task_lines) == 1
        assert task_lines[0]["id"] == "research"

    def test_export_filter_phase(self, tmp_path: Path):
        """--phase filters tasks by category group."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        _seed_database(charm_path)

        output_file = tmp_path / "phase.jsonl"
        result = _run_cantrip(
            "export-transcript",
            str(charm_path),
            "--format",
            "jsonl",
            "--phase",
            "build",
            "--output",
            str(output_file),
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        content = output_file.read_text()
        lines = [line for line in content.strip().split("\n") if line]

        task_lines = [json.loads(ln) for ln in lines if '"type": "task"' in ln]
        assert len(task_lines) == 1
        assert task_lines[0]["id"] == "build"

    def test_export_no_cantrip_file_fails(self, tmp_path: Path):
        """Exporting from a directory with no .cantrip file fails gracefully."""
        charm_path = tmp_path / "empty-charm"
        charm_path.mkdir()

        result = _run_cantrip("export-transcript", str(charm_path))

        assert result.returncode == 1
        assert "no .cantrip file" in result.stdout.lower() or "error" in result.stdout.lower()


@pytest.mark.e2e
class TestCLIEntryPoints:
    """Verify basic CLI entry points work."""

    def test_version(self):
        """cantrip --version prints version and exits 0."""
        result = _run_cantrip("--version")
        assert result.returncode == 0
        assert "cantrip" in result.stdout.lower()

    def test_run_help(self):
        """cantrip run --help prints usage and exits 0."""
        result = _run_cantrip("run", "--help")
        assert result.returncode == 0
        assert "--provider" in result.stdout
        assert "--no-tui" in result.stdout

    def test_export_help(self):
        """cantrip export-transcript --help prints usage and exits 0."""
        result = _run_cantrip("export-transcript", "--help")
        assert result.returncode == 0
        assert "--format" in result.stdout
        assert "--task" in result.stdout
