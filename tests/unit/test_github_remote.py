"""Tests for GitHub remote detection (Phase 42.1)."""

import subprocess
from pathlib import Path
from unittest import mock

from cantrip.agent.core import detect_github_repo


class TestDetectGithubRepo:
    """Tests for detect_github_repo()."""

    def test_none_path_returns_none(self) -> None:
        assert detect_github_repo(None) is None

    def test_https_url(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/canonical/grafana-k8s.git\n"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) == "canonical/grafana-k8s"

    def test_https_url_without_dot_git(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/canonical/grafana-k8s\n"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) == "canonical/grafana-k8s"

    def test_ssh_url(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="git@github.com:juju/terraform-provider-juju.git\n"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) == "juju/terraform-provider-juju"

    def test_ssh_url_without_dot_git(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="git@github.com:owner/repo\n"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) == "owner/repo"

    def test_non_github_https_returns_none(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://gitlab.com/owner/repo.git\n"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) is None

    def test_non_github_ssh_returns_none(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="git@gitlab.com:owner/repo.git\n"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) is None

    def test_git_not_installed(self, tmp_path: Path) -> None:
        with mock.patch("cantrip.agent.core.subprocess.run", side_effect=FileNotFoundError):
            assert detect_github_repo(tmp_path) is None

    def test_not_a_git_repo(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: not a git repository"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) is None

    def test_no_origin_remote(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="fatal: No such remote 'origin'"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) is None

    def test_timeout(self, tmp_path: Path) -> None:
        with mock.patch(
            "cantrip.agent.core.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            assert detect_github_repo(tmp_path) is None

    def test_os_error(self, tmp_path: Path) -> None:
        with mock.patch(
            "cantrip.agent.core.subprocess.run",
            side_effect=OSError("permission denied"),
        ):
            assert detect_github_repo(tmp_path) is None

    def test_empty_stdout(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="\n")
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result):
            assert detect_github_repo(tmp_path) is None

    def test_passes_charm_path_as_cwd(self, tmp_path: Path) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="https://github.com/owner/repo.git\n"
        )
        with mock.patch("cantrip.agent.core.subprocess.run", return_value=result) as m:
            detect_github_repo(tmp_path)
            m.assert_called_once()
            assert m.call_args.kwargs["cwd"] == str(tmp_path)
