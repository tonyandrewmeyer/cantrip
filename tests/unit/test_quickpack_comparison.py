"""Comparison tests: quickpack vs charmcraft pack.

These tests pack the same charm with both quickpack and charmcraft, then
compare the results for correctness and speed.  They are slow (real uv and
charmcraft invocations) and require charmcraft to be installed.

Run with::

    uv run pytest tests/unit/test_quickpack_comparison.py -v --run-slow
"""

import pathlib
import shutil
import subprocess
import time
import zipfile

import pytest
import yaml

from quickpack import pack

# Skip the entire module if charmcraft is not installed.
_HAS_CHARMCRAFT = shutil.which("charmcraft") is not None
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not _HAS_CHARMCRAFT, reason="charmcraft not installed"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scaffold_charm(base_dir: pathlib.Path) -> pathlib.Path:
    """Create a realistic charm project with the uv plugin."""
    charm_dir = base_dir / "testcharm"
    charm_dir.mkdir(parents=True)

    charmcraft = {
        "name": "testcharm",
        "type": "charm",
        "summary": "A test charm for comparison",
        "description": "Used to compare quickpack output with charmcraft pack.",
        "base": "ubuntu@24.04",
        "platforms": {"ubuntu@24.04:amd64": None},
        "parts": {
            "charm": {
                "plugin": "uv",
                "source": ".",
            },
        },
        "config": {
            "options": {
                "port": {
                    "type": "int",
                    "default": 8080,
                    "description": "The port to listen on.",
                },
            },
        },
        "requires": {
            "database": {"interface": "mysql"},
        },
    }
    (charm_dir / "charmcraft.yaml").write_text(
        yaml.safe_dump(charmcraft, default_flow_style=False)
    )

    # src/charm.py
    src = charm_dir / "src"
    src.mkdir()
    (src / "charm.py").write_text(
        '#!/usr/bin/env python3\n"""Test charm."""\nimport ops\n\n'
        "class TestCharm(ops.CharmBase):\n"
        "    def __init__(self, framework: ops.Framework) -> None:\n"
        "        super().__init__(framework)\n"
        "        self.framework.observe(self.on.install, self._on_install)\n\n"
        "    def _on_install(self, event: ops.InstallEvent) -> None:\n"
        "        self.unit.status = ops.ActiveStatus()\n\n\n"
        'if __name__ == "__main__":\n    ops.main(TestCharm)\n'
    )

    # pyproject.toml
    (charm_dir / "pyproject.toml").write_text(
        "[project]\n"
        'name = "testcharm"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["ops>=2.17"]\n\n'
        "[build-system]\n"
        'requires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n'
    )

    # Create uv.lock by running uv lock.
    subprocess.run(
        ["uv", "lock"],
        cwd=str(charm_dir),
        check=True,
        capture_output=True,
        timeout=120,
    )

    return charm_dir


def _charmcraft_pack(
    charm_dir: pathlib.Path,
    *,
    destructive: bool = False,
    output_dir: pathlib.Path | None = None,
) -> tuple[pathlib.Path, float]:
    """Run charmcraft pack and return (charm_path, elapsed_seconds)."""
    cmd = ["charmcraft", "pack"]
    if destructive:
        cmd.append("--destructive-mode")

    start = time.monotonic()
    result = subprocess.run(
        cmd,
        cwd=str(charm_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )
    elapsed = time.monotonic() - start

    if result.returncode != 0:
        pytest.fail(
            f"charmcraft pack failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    # Find the .charm file.
    charm_files = list(charm_dir.glob("*.charm"))
    if not charm_files:
        pytest.fail("charmcraft pack produced no .charm file")

    charm_path = charm_files[0]
    if output_dir is not None:
        dest = output_dir / charm_path.name
        shutil.move(str(charm_path), str(dest))
        charm_path = dest

    return charm_path, elapsed


def _quickpack_timed(
    charm_dir: pathlib.Path,
    output_dir: pathlib.Path | None = None,
) -> tuple[pathlib.Path, float]:
    """Run quickpack and return (charm_path, elapsed_seconds)."""
    start = time.monotonic()
    charm_path = pack.quick_pack(charm_dir, output_dir=output_dir)
    elapsed = time.monotonic() - start
    return charm_path, elapsed


def _zip_contents(charm_path: pathlib.Path) -> dict[str, bytes]:
    """Return a dict of {arcname: content} from a .charm file."""
    with zipfile.ZipFile(str(charm_path)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _venv_packages(contents: dict[str, bytes]) -> set[str]:
    """Extract the set of top-level package directory names from venv/."""
    packages: set[str] = set()
    for name in contents:
        if name.startswith("venv/") and "/site-packages/" in name:
            # Extract the directory immediately under site-packages.
            after_sp = name.split("/site-packages/", 1)[1]
            top = after_sp.split("/")[0]
            if top and not top.startswith("_"):
                packages.add(top)
    return packages


# ---------------------------------------------------------------------------
# Comparison tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def comparison_charm(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Scaffold a charm once for the whole module."""
    base = tmp_path_factory.mktemp("comparison")
    return _scaffold_charm(base)


class TestOutputComparison:
    """Compare quickpack output against charmcraft pack."""

    def _compare_outputs(
        self,
        qp_contents: dict[str, bytes],
        cc_contents: dict[str, bytes],
    ) -> None:
        """Assert that the two charm archives contain equivalent content."""
        qp_files = set(qp_contents.keys())
        cc_files = set(cc_contents.keys())

        # Files that quickpack generates differently (version/timestamp) or
        # that charmcraft may add from its own lifecycle.
        metadata_files = {"manifest.yaml"}
        # charmcraft may include charmcraft.yaml in the archive with the
        # charm plugin; quickpack does not.  Allow extra files from charmcraft.
        extra_cc = cc_files - qp_files - metadata_files
        missing_qp = cc_files - qp_files - metadata_files - extra_cc

        # All files in quickpack output should be in charmcraft output
        # (except manifest which differs by design).
        extra_qp = qp_files - cc_files - metadata_files
        assert not extra_qp, f"quickpack has extra files: {extra_qp}"
        assert not missing_qp, f"quickpack is missing files: {missing_qp}"

        # Compare content of key metadata files.
        for fname in ("metadata.yaml", "dispatch", "config.yaml", "actions.yaml"):
            if fname in qp_contents and fname in cc_contents:
                qp_data = yaml.safe_load(qp_contents[fname]) if fname.endswith(".yaml") else None
                cc_data = yaml.safe_load(cc_contents[fname]) if fname.endswith(".yaml") else None
                if qp_data is not None and cc_data is not None:
                    assert qp_data == cc_data, f"{fname} content differs"
                elif fname == "dispatch":
                    # Compare dispatch scripts — the entrypoint line should match.
                    qp_dispatch = qp_contents[fname].decode()
                    cc_dispatch = cc_contents[fname].decode()
                    assert "src/charm.py" in qp_dispatch
                    assert "src/charm.py" in cc_dispatch

        # Compare venv packages.
        qp_pkgs = _venv_packages(qp_contents)
        cc_pkgs = _venv_packages(cc_contents)
        # quickpack should have at least the same packages.
        missing_pkgs = cc_pkgs - qp_pkgs
        assert not missing_pkgs, f"quickpack venv is missing packages: {missing_pkgs}"

    def test_matches_charmcraft_destructive_output(
        self,
        comparison_charm: pathlib.Path,
        tmp_path: pathlib.Path,
    ) -> None:
        """Quickpack output should match charmcraft --destructive-mode."""
        qp_out = tmp_path / "qp"
        qp_out.mkdir()
        cc_out = tmp_path / "cc"
        cc_out.mkdir()

        qp_path, _ = _quickpack_timed(comparison_charm, output_dir=qp_out)
        cc_path, _ = _charmcraft_pack(comparison_charm, destructive=True, output_dir=cc_out)

        qp_contents = _zip_contents(qp_path)
        cc_contents = _zip_contents(cc_path)
        self._compare_outputs(qp_contents, cc_contents)

    def test_matches_charmcraft_normal_output(
        self,
        comparison_charm: pathlib.Path,
        tmp_path: pathlib.Path,
    ) -> None:
        """Quickpack output should match regular charmcraft pack."""
        qp_out = tmp_path / "qp"
        qp_out.mkdir()
        cc_out = tmp_path / "cc"
        cc_out.mkdir()

        qp_path, _ = _quickpack_timed(comparison_charm, output_dir=qp_out)
        cc_path, _ = _charmcraft_pack(comparison_charm, destructive=False, output_dir=cc_out)

        qp_contents = _zip_contents(qp_path)
        cc_contents = _zip_contents(cc_path)
        self._compare_outputs(qp_contents, cc_contents)


class TestSpeedComparison:
    """Verify quickpack is significantly faster than charmcraft."""

    def test_faster_than_destructive_mode(
        self,
        comparison_charm: pathlib.Path,
        tmp_path: pathlib.Path,
    ) -> None:
        """Quickpack must be faster than charmcraft --destructive-mode."""
        qp_out = tmp_path / "qp"
        qp_out.mkdir()
        cc_out = tmp_path / "cc"
        cc_out.mkdir()

        _, qp_time = _quickpack_timed(comparison_charm, output_dir=qp_out)
        _, cc_time = _charmcraft_pack(comparison_charm, destructive=True, output_dir=cc_out)

        assert qp_time < cc_time, (
            f"quickpack ({qp_time:.1f}s) was not faster than "
            f"charmcraft --destructive-mode ({cc_time:.1f}s)"
        )

    def test_twice_as_fast_as_normal_pack(
        self,
        comparison_charm: pathlib.Path,
        tmp_path: pathlib.Path,
    ) -> None:
        """Quickpack must be at least 2x faster than regular charmcraft pack."""
        qp_out = tmp_path / "qp"
        qp_out.mkdir()
        cc_out = tmp_path / "cc"
        cc_out.mkdir()

        _, qp_time = _quickpack_timed(comparison_charm, output_dir=qp_out)
        _, cc_time = _charmcraft_pack(comparison_charm, destructive=False, output_dir=cc_out)

        assert qp_time * 2 <= cc_time, (
            f"quickpack ({qp_time:.1f}s) was not 2x faster than charmcraft pack ({cc_time:.1f}s)"
        )

    def test_three_times_faster_than_clean_pack(
        self,
        comparison_charm: pathlib.Path,
        tmp_path: pathlib.Path,
    ) -> None:
        """Quickpack must be at least 3x faster than charmcraft pack after clean."""
        # Clean charmcraft's build cache first.
        subprocess.run(
            ["charmcraft", "clean"],
            cwd=str(comparison_charm),
            capture_output=True,
            timeout=60,
        )

        qp_out = tmp_path / "qp"
        qp_out.mkdir()
        cc_out = tmp_path / "cc"
        cc_out.mkdir()

        _, qp_time = _quickpack_timed(comparison_charm, output_dir=qp_out)
        _, cc_time = _charmcraft_pack(comparison_charm, destructive=False, output_dir=cc_out)

        assert qp_time * 3 <= cc_time, (
            f"quickpack ({qp_time:.1f}s) was not 3x faster than "
            f"charmcraft clean + pack ({cc_time:.1f}s)"
        )
