"""Unit tests for the ``quickpack`` CLI."""

import pathlib
import subprocess


class TestCli:
    """Tests for the quickpack CLI."""

    def test_cli_help(self) -> None:
        result = subprocess.run(
            ["uv", "run", "quickpack", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "quickpack" in result.stdout

    def test_cli_missing_charmcraft_yaml(self, tmp_path: pathlib.Path) -> None:
        result = subprocess.run(
            ["uv", "run", "quickpack", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "charmcraft.yaml" in result.stderr

    def test_cli_help_mentions_verify_attestations(self) -> None:
        result = subprocess.run(
            ["uv", "run", "quickpack", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--verify-attestations" in result.stdout
