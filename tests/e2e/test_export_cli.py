"""End-to-end tests for the ``cantrip export-transcript`` CLI subcommand.

These tests invoke cantrip as a subprocess, verifying that the CLI
entry point works correctly with all three export formats and produces
valid output files. No LLM API key required.
"""

import json
import pathlib
import subprocess

import pytest

from tests.support import transcript_seed


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

    def test_export_html(self, tmp_path: pathlib.Path):
        """Export as HTML produces a valid HTML file."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        transcript_seed.seed_cli_export_session(charm_path)

        result = _run_cantrip("export-transcript", str(charm_path), "--format", "html")

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Transcript exported" in result.stdout

        output_file = charm_path / "transcript.html"
        assert output_file.exists()
        content = output_file.read_text()
        assert "<html" in content
        assert "cli-test-charm" in content

    def test_export_markdown(self, tmp_path: pathlib.Path):
        """Export as Markdown produces a valid .md file."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        transcript_seed.seed_cli_export_session(charm_path)

        result = _run_cantrip("export-transcript", str(charm_path), "--format", "markdown")

        assert result.returncode == 0, f"stderr: {result.stderr}"

        output_file = charm_path / "transcript.md"
        assert output_file.exists()
        content = output_file.read_text()
        assert "# Cantrip Transcript" in content
        assert "cli-test-charm" in content
        assert "## Tasks" in content
        assert "## Conversation" in content

    def test_export_jsonl(self, tmp_path: pathlib.Path):
        """Export as JSONL produces valid newline-delimited JSON."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        transcript_seed.seed_cli_export_session(charm_path)

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

    def test_export_custom_output_path(self, tmp_path: pathlib.Path):
        """--output writes to the specified path."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        transcript_seed.seed_cli_export_session(charm_path)

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

    def test_export_filter_task(self, tmp_path: pathlib.Path):
        """--task filters to a single task."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        transcript_seed.seed_cli_export_session(charm_path)

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

    def test_export_filter_phase(self, tmp_path: pathlib.Path):
        """--phase filters tasks by category group."""
        charm_path = tmp_path / "my-charm"
        charm_path.mkdir()
        transcript_seed.seed_cli_export_session(charm_path)

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

    def test_export_no_cantrip_file_fails(self, tmp_path: pathlib.Path):
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
