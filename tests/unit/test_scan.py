"""Tests for the deterministic repo scan helper."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile

import pytest

from cantrip.agent.tools._scan import scan


@pytest.fixture
def temp_repo() -> pathlib.Path:
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


class TestScan:
    """Exercise the bounded detection passes in ``cantrip.agent.tools._scan``."""

    def test_manifests_only_infers_language(self, temp_repo: pathlib.Path) -> None:
        (temp_repo / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1.0"\n')
        (temp_repo / "uv.lock").write_text("version = 1\n")

        result = scan(temp_repo)

        assert result.manifests == ("pyproject.toml", "uv.lock")
        assert result.language == "python"
        assert result.framework is None
        assert result.entry_points == ()

    def test_ci_cd_detection_reads_workflow_directory(self, temp_repo: pathlib.Path) -> None:
        workflow_dir = temp_repo / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "ci.yml").write_text("name: ci\n")

        result = scan(temp_repo)

        assert result.ci_cd == ("GitHub Actions",)

    def test_entry_point_only_uses_source_suffix_fallback(self, temp_repo: pathlib.Path) -> None:
        src = temp_repo / "src"
        src.mkdir()
        (src / "main.py").write_text("print('hello')\n")

        result = scan(temp_repo)

        assert result.entry_points == ("src/main.py",)
        assert result.language == "python"
        assert result.framework is None

    def test_existing_charm_marker_sets_existing_flag(self, temp_repo: pathlib.Path) -> None:
        (temp_repo / "charmcraft.yaml").write_text("type: charm\n")
        (temp_repo / ".cantrip").mkdir()

        result = scan(temp_repo)

        assert result.is_existing_charm is True
        assert result.manifests == ("charmcraft.yaml",)
        assert result.extras["root_markers"] == [".cantrip", "charmcraft.yaml"]

    def test_mixed_workload_and_config_signals_are_collected(
        self, temp_repo: pathlib.Path
    ) -> None:
        (temp_repo / "Dockerfile").write_text("FROM ubuntu:24.04\n")
        (temp_repo / "docker-compose.yaml").write_text("services:\n  app:\n    build: .\n")
        (temp_repo / "SECURITY.md").write_text("# Security\n")
        (temp_repo / ".editorconfig").write_text("root = true\n")
        (temp_repo / ".env.example").write_text("PORT=8080\n")
        (temp_repo / "settings.yaml").write_text("port: 8080\n")
        deploy_dir = temp_repo / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "demo.service").write_text("[Unit]\nDescription=Demo\n")

        result = scan(temp_repo)

        assert result.containers == ("Dockerfile", "docker-compose.yaml")
        assert result.security_configs == ("SECURITY.md",)
        assert result.lint_configs == (".editorconfig",)
        assert result.env_templates == (".env.example",)
        assert result.extras["config_files"] == ["settings.yaml"]
        assert result.extras["systemd_units"] == ["deploy/demo.service"]

    def test_excluded_directories_are_pruned(self, temp_repo: pathlib.Path) -> None:
        node_modules = temp_repo / "node_modules"
        node_modules.mkdir()
        (node_modules / "package.json").write_text('{"dependencies": {"express": "^4.18.0"}}')
        (node_modules / ".env.example").write_text("SECRET=nope\n")
        (temp_repo / "main.rs").write_text("fn main() {}\n")

        result = scan(temp_repo)

        assert result.manifests == ()
        assert result.env_templates == ()
        assert result.framework is None
        assert result.language == "rust"
        assert result.extras["scan_stats"]["truncated"] is False

    def test_recent_git_churn_is_counted(self, temp_repo: pathlib.Path) -> None:
        subprocess.run(["git", "init"], cwd=temp_repo, check=True, capture_output=True, text=True)
        (temp_repo / "README.md").write_text("# Demo\n")
        subprocess.run(["git", "add", "README.md"], cwd=temp_repo, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "init",
            ],
            cwd=temp_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        result = scan(temp_repo)

        assert result.recent_commit_count == 1
