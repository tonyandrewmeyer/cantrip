"""Tests for the deterministic repo scan helper."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
from unittest import mock

import pytest

from cantrip.agent.tools import _scan
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


class TestScanBranches:
    """Cover the failure / boundary branches in ``_scan``.

    The happy paths in ``TestScan`` exercise the canonical detection
    passes; this class fills in the branches Phase 93.1 flagged: glob
    manifests, non-workflow CI configs, git-churn failure modes, the
    bounded-walk symlink and depth/budget guards, and the input
    validation errors in :func:`scan`.
    """

    def test_glob_manifest_pattern_is_matched(self, temp_repo: pathlib.Path) -> None:
        """A glob entry in ``MANIFESTS`` (e.g. ``*.gemspec``) matches by pattern."""
        (temp_repo / "demo.gemspec").write_text(
            "Gem::Specification.new do |s|\n  s.name = 'demo'\nend\n"
        )

        result = scan(temp_repo)

        assert "demo.gemspec" in result.manifests

    def test_direct_ci_cd_file_is_detected(self, temp_repo: pathlib.Path) -> None:
        """CI configs that aren't ``.github/workflows`` resolve via direct match."""
        (temp_repo / ".gitlab-ci.yml").write_text("stages:\n  - test\n")

        result = scan(temp_repo)

        assert "GitLab CI" in result.ci_cd

    def test_recent_commits_returns_none_when_git_missing(self, temp_repo: pathlib.Path) -> None:
        """``OSError`` from ``subprocess.run`` (e.g. git not on PATH) is swallowed."""
        (temp_repo / ".git").mkdir()  # The early-out only fires when ``.git`` is absent.

        with mock.patch.object(_scan.subprocess, "run", side_effect=OSError("no git")):
            assert _scan._count_recent_commits(temp_repo) is None

    def test_recent_commits_returns_none_on_nonzero_exit(self, temp_repo: pathlib.Path) -> None:
        """A non-zero git exit (broken repo state) yields ``None`` rather than raising."""
        (temp_repo / ".git").mkdir()
        fake = subprocess.CompletedProcess(args=["git"], returncode=128, stdout="", stderr="boom")

        with mock.patch.object(_scan.subprocess, "run", return_value=fake):
            assert _scan._count_recent_commits(temp_repo) is None

    def test_recent_commits_returns_none_when_output_not_a_count(
        self, temp_repo: pathlib.Path
    ) -> None:
        """Non-numeric stdout (unexpected git output) is treated as missing."""
        (temp_repo / ".git").mkdir()
        fake = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="abc\n", stderr="")

        with mock.patch.object(_scan.subprocess, "run", return_value=fake):
            assert _scan._count_recent_commits(temp_repo) is None

    def test_symlinked_directory_is_skipped(self, temp_repo: pathlib.Path) -> None:
        """Symlinked directories are filtered out of the walk listing.

        A self-referential symlink would loop forever if the walk
        descended into it; the explicit ``is_symlink()`` guard at the
        top of ``_walk_filesystem`` is the protection that lets the
        scan stay bounded.
        """
        (temp_repo / "main.py").write_text("print('hi')\n")  # Real entry-point file.
        (temp_repo / "loop").symlink_to(temp_repo, target_is_directory=True)

        result = scan(temp_repo)

        assert "main.py" in result.entry_points
        # The symlinked alias is dropped before any of its (looped) contents
        # can leak into the result.
        all_paths = [
            *result.manifests,
            *result.entry_points,
            *result.containers,
            *result.security_configs,
            *result.lint_configs,
            *result.env_templates,
            *result.extras["config_files"],
            *result.extras["systemd_units"],
        ]
        assert not any(path.startswith("loop/") for path in all_paths)
        assert result.extras["scan_stats"]["truncated"] is False

    def test_depth_limit_prunes_deep_directories(
        self, temp_repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Subdirectories beyond ``_MAX_SCAN_DEPTH`` are dropped from the walk."""
        monkeypatch.setattr(_scan, "_MAX_SCAN_DEPTH", 2)
        deep = temp_repo / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "leaf.py").write_text("# pruned\n")
        (temp_repo / "a" / "b" / "kept.py").write_text("# kept\n")

        result = scan(temp_repo)

        assert not any("/c/" in path or path.endswith("leaf.py") for path in result.entry_points)

    def test_file_budget_truncates_walk(
        self, temp_repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``_MAX_SCANNED_FILES`` is hit, the walk stops and reports truncated."""
        monkeypatch.setattr(_scan, "_MAX_SCANNED_FILES", 3)
        for index in range(10):
            (temp_repo / f"file_{index}.txt").write_text(str(index))

        result = scan(temp_repo)

        stats = result.extras["scan_stats"]
        assert stats["truncated"] is True
        assert stats["files_scanned"] == 3

    def test_scan_rejects_missing_path(self, temp_repo: pathlib.Path) -> None:
        """A non-existent path produces ``ValueError`` rather than a silent empty scan."""
        missing = temp_repo / "does-not-exist"

        with pytest.raises(ValueError, match="not found"):
            scan(missing)

    def test_scan_rejects_non_directory(self, temp_repo: pathlib.Path) -> None:
        """A path that exists but is a file (not a directory) is rejected."""
        target = temp_repo / "regular.txt"
        target.write_text("hello\n")

        with pytest.raises(ValueError, match="not a directory"):
            scan(target)
