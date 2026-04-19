"""Shared fixtures for the quickpack unit tests."""

import pathlib

import pytest
import yaml


@pytest.fixture
def charm_project(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal charm project with the uv plugin."""
    charm_dir = tmp_path / "mycharm"
    charm_dir.mkdir()

    charmcraft = {
        "name": "mycharm",
        "type": "charm",
        "summary": "A test charm",
        "description": "A charm for testing quick pack.",
        "base": "ubuntu@24.04",
        "platforms": {"amd64": None},
        "parts": {
            "charm": {
                "plugin": "uv",
                "source": ".",
            },
        },
        "requires": {
            "database": {"interface": "mysql"},
        },
    }
    (charm_dir / "charmcraft.yaml").write_text(yaml.safe_dump(charmcraft))

    # Create src/charm.py.
    src = charm_dir / "src"
    src.mkdir()
    (src / "charm.py").write_text("#!/usr/bin/env python3\nimport ops\n")

    # Create lib/ directory.
    lib = charm_dir / "lib"
    lib.mkdir()
    (lib / "helpers.py").write_text("# helpers\n")

    # Create pyproject.toml and uv.lock for uv sync.
    (charm_dir / "pyproject.toml").write_text(
        '[project]\nname = "mycharm"\nversion = "0.1.0"\n'
        'requires-python = ">=3.12"\ndependencies = ["ops>=2.0"]\n'
    )
    (charm_dir / "uv.lock").write_text("")

    return charm_dir
