"""Tests for Phase 108.9 — file-tree dotfile cull.

The file tree used to surface every dotfile directory at the top
of the listing (``.agents``, ``.claude``, ``.craft``, ``.github``,
``.hypothesis``, ``.pytest_cache``, …) before any charm content.
The filter is now "specific noise dirs *or* any dotfile
directory"; dotfile **files** (``.gitignore``, ``.editorconfig``)
stay visible because they are routinely edited.
"""

from __future__ import annotations

import pathlib

import pytest

from cantrip.tui.widgets.filetree import is_hidden_path

pytestmark = pytest.mark.tui


# ---------------------------------------------------------------------------
# Pure-rule tests — no Pilot needed; ``is_hidden_path`` is a free function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        ".git",
        ".tox",
        ".venv",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".hypothesis",
        ".github",
        ".claude",
        ".craft",
        ".agents",
        ".cantrip",
        ".vscode",
        ".idea",
    ],
)
def test_dotfile_directory_is_hidden(tmp_path: pathlib.Path, name: str) -> None:
    """Every dotfile directory at the top level disappears from the tree."""
    target = tmp_path / name
    target.mkdir()
    assert is_hidden_path(target) is True


@pytest.mark.parametrize(
    "name",
    [
        ".gitignore",
        ".editorconfig",
        ".envrc",
        ".python-version",
    ],
)
def test_dotfile_file_is_visible(tmp_path: pathlib.Path, name: str) -> None:
    """Dotfile *files* stay in the tree — users routinely edit them."""
    target = tmp_path / name
    target.write_text("# regular content")
    assert is_hidden_path(target) is False


@pytest.mark.parametrize(
    "name",
    [
        "__pycache__",
        "node_modules",
    ],
)
def test_explicit_noise_directory_is_hidden(tmp_path: pathlib.Path, name: str) -> None:
    """The explicit-name allowlist still catches non-dotfile noise dirs."""
    target = tmp_path / name
    target.mkdir()
    assert is_hidden_path(target) is True


@pytest.mark.parametrize(
    "name",
    [
        "src",
        "tests",
        "lib",
        "docs",
        "charmcraft.yaml",
        "pyproject.toml",
        "README.md",
    ],
)
def test_charm_relevant_paths_are_visible(tmp_path: pathlib.Path, name: str) -> None:
    """Ordinary charm-relevant entries pass through untouched."""
    target = tmp_path / name
    if "." in name and not name.startswith("."):
        target.write_text("payload")
    else:
        target.mkdir()
    assert is_hidden_path(target) is False


# ---------------------------------------------------------------------------
# Regression: the same rule prunes the repo_stats walk so the file count
# and the file-tree don't drift.
# ---------------------------------------------------------------------------


def test_repo_stats_walk_skips_dotfile_dirs(tmp_path: pathlib.Path) -> None:
    """``compute_repo_stats`` does not visit dotfile directories.

    Only ``src/charm.py`` should contribute; the workflow YAML under
    ``.github`` and the skill markdown under ``.claude`` must not
    inflate the file or line counts even though they pre-date the
    Phase 108.9 rule (and therefore weren't in the legacy
    ``_HIDDEN_NAMES`` allowlist).
    """
    from cantrip.tui.widgets.repo_stats import compute_repo_stats

    src = tmp_path / "src"
    src.mkdir()
    (src / "charm.py").write_text("x = 1\n")
    gh = tmp_path / ".github" / "workflows"
    gh.mkdir(parents=True)
    (gh / "ci.yaml").write_text("name: CI\non: push\n")
    claude = tmp_path / ".claude" / "skills"
    claude.mkdir(parents=True)
    (claude / "skill.md").write_text("# skill\n\nbody\n")

    stats = compute_repo_stats(tmp_path)
    assert stats.files == 1
    assert stats.most_recent_file == pathlib.PurePath("src/charm.py")
