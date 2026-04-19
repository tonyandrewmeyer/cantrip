"""Unit tests for ``quickpack.pack`` (the core packing logic)."""

import pathlib
import stat
import zipfile
from unittest import mock

import pytest
import yaml

from quickpack import pack


class TestPack:
    """Tests for the core packing logic."""

    def test_ensure_jujuignore_creates(self, tmp_path: pathlib.Path) -> None:
        pack._ensure_jujuignore(tmp_path)
        content = (tmp_path / ".jujuignore").read_text()
        assert "*.charm" in content
        assert ".cantrip" in content

    def test_ensure_jujuignore_appends(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".jujuignore").write_text("*.bak\n")
        pack._ensure_jujuignore(tmp_path)
        content = (tmp_path / ".jujuignore").read_text()
        assert "*.bak" in content
        assert "*.charm" in content
        assert ".cantrip" in content

    def test_ensure_jujuignore_idempotent(self, tmp_path: pathlib.Path) -> None:
        pack._ensure_jujuignore(tmp_path)
        pack._ensure_jujuignore(tmp_path)
        content = (tmp_path / ".jujuignore").read_text()
        assert content.count("*.charm") == 1

    def test_write_dispatch(self, tmp_path: pathlib.Path) -> None:
        pack._write_dispatch(tmp_path, "src/charm.py")
        dispatch = tmp_path / "dispatch"
        assert dispatch.exists()
        content = dispatch.read_text()
        assert "src/charm.py" in content
        assert content.startswith("#!/bin/sh\n")
        # Check executable.
        mode = dispatch.stat().st_mode
        assert mode & stat.S_IXUSR

    def test_write_dispatch_custom_entrypoint(self, tmp_path: pathlib.Path) -> None:
        pack._write_dispatch(tmp_path, "src/app.py")
        content = (tmp_path / "dispatch").read_text()
        assert "src/app.py" in content

    def test_build_zip(self, tmp_path: pathlib.Path) -> None:
        prime = tmp_path / "prime"
        prime.mkdir()
        (prime / "dispatch").write_text("#!/bin/sh\n")
        sub = prime / "src"
        sub.mkdir()
        (sub / "charm.py").write_text("import ops\n")

        zip_path = tmp_path / "test.charm"
        pack._build_zip(zip_path, prime)

        with zipfile.ZipFile(str(zip_path)) as zf:
            names = zf.namelist()
            assert "dispatch" in names
            assert "src/charm.py" in names

    def test_build_zip_skips_pycache_dirs(self, tmp_path: pathlib.Path) -> None:
        """``__pycache__`` directories are excluded but ``.pyc`` beside
        sources (legacy layout) are included to match charmcraft."""
        prime = tmp_path / "prime"
        prime.mkdir()
        (prime / "dispatch").write_text("#!/bin/sh\n")
        sub = prime / "src"
        sub.mkdir()
        (sub / "charm.py").write_text("import ops\n")
        cache = sub / "__pycache__"
        cache.mkdir()
        (cache / "charm.cpython-312.pyc").write_bytes(b"\x00")
        # A .pyc next to its .py (legacy layout) SHOULD be included.
        (sub / "charm.pyc").write_bytes(b"\x00")

        zip_path = tmp_path / "test.charm"
        pack._build_zip(zip_path, prime)

        with zipfile.ZipFile(str(zip_path)) as zf:
            names = zf.namelist()
            assert "src/charm.py" in names
            assert "src/charm.pyc" in names
            assert not any("__pycache__" in n for n in names)

    def test_quick_pack_end_to_end(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """End-to-end test with mocked uv commands."""
        output_dir = tmp_path / "output"

        with mock.patch("quickpack.parts.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            result = pack.quick_pack(charm_project, output_dir=output_dir)

        assert result.exists()
        assert result.suffix == ".charm"
        assert result.parent == output_dir

        # Verify zip contents.
        with zipfile.ZipFile(str(result)) as zf:
            names = zf.namelist()
            assert "dispatch" in names
            assert "metadata.yaml" in names
            assert "manifest.yaml" in names
            assert "src/charm.py" in names
            assert "lib/helpers.py" in names

            # Verify metadata.yaml content.
            meta = yaml.safe_load(zf.read("metadata.yaml"))
            assert meta["name"] == "mycharm"
            assert meta["summary"] == "A test charm"
            assert meta["requires"] == {"database": {"interface": "mysql"}}

            # Verify manifest.yaml content.
            manifest = yaml.safe_load(zf.read("manifest.yaml"))
            assert manifest["charmcraft-version"].startswith("quickpack-")
            assert len(manifest["bases"]) == 1

            # Verify dispatch content.
            dispatch = zf.read("dispatch").decode()
            assert "src/charm.py" in dispatch

    def test_quick_pack_updates_jujuignore(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        with mock.patch("quickpack.parts.subprocess.run"):
            pack.quick_pack(charm_project, output_dir=tmp_path / "out")

        content = (charm_project / ".jujuignore").read_text()
        assert "*.charm" in content
        assert ".cantrip" in content

    def test_quick_pack_charm_name(self, charm_project: pathlib.Path) -> None:
        with mock.patch("quickpack.parts.subprocess.run"):
            result = pack.quick_pack(charm_project)
        assert result.name.startswith("mycharm_")
        assert result.name.endswith(".charm")

    def test_quick_pack_with_actions(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """Charms with actions should include actions.yaml in the .charm."""
        project = yaml.safe_load((charm_project / "charmcraft.yaml").read_text())
        project["actions"] = {"restart": {"description": "Restart"}}
        (charm_project / "charmcraft.yaml").write_text(yaml.safe_dump(project))

        with mock.patch("quickpack.parts.subprocess.run"):
            result = pack.quick_pack(charm_project, output_dir=tmp_path)

        with zipfile.ZipFile(str(result)) as zf:
            assert "actions.yaml" in zf.namelist()
            actions = yaml.safe_load(zf.read("actions.yaml"))
            assert "restart" in actions

    def test_quick_pack_with_config(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """Charms with config should include config.yaml in the .charm."""
        project = yaml.safe_load((charm_project / "charmcraft.yaml").read_text())
        project["config"] = {"options": {"port": {"type": "int", "default": 8080}}}
        (charm_project / "charmcraft.yaml").write_text(yaml.safe_dump(project))

        with mock.patch("quickpack.parts.subprocess.run"):
            result = pack.quick_pack(charm_project, output_dir=tmp_path)

        with zipfile.ZipFile(str(result)) as zf:
            assert "config.yaml" in zf.namelist()

    def test_quick_pack_with_dump_part(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """Extra dump parts should include their files in the .charm."""
        extra = charm_project / "extra"
        extra.mkdir()
        (extra / "nginx.conf").write_text("server {}\n")

        project = yaml.safe_load((charm_project / "charmcraft.yaml").read_text())
        project["parts"]["static-files"] = {
            "plugin": "dump",
            "source": str(extra),
        }
        (charm_project / "charmcraft.yaml").write_text(yaml.safe_dump(project))

        with mock.patch("quickpack.parts.subprocess.run"):
            result = pack.quick_pack(charm_project, output_dir=tmp_path)

        with zipfile.ZipFile(str(result)) as zf:
            assert "nginx.conf" in zf.namelist()

    def test_compile_bytecode(self, tmp_path: pathlib.Path) -> None:
        """Bytecode compilation creates .pyc files next to sources."""
        prime = tmp_path / "prime"
        prime.mkdir()
        src = prime / "src"
        src.mkdir()
        (src / "charm.py").write_text("x = 1\n")

        pack._compile_bytecode(prime)
        assert (src / "charm.pyc").exists()

    def test_quick_pack_includes_pyc(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """End-to-end: .charm archive includes .pyc files."""
        with mock.patch("quickpack.parts.subprocess.run"):
            result = pack.quick_pack(charm_project, output_dir=tmp_path)

        with zipfile.ZipFile(str(result)) as zf:
            names = zf.namelist()
            assert "src/charm.pyc" in names

    def test_quick_pack_with_nil_part(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """Nil parts are handled alongside uv parts."""
        project = yaml.safe_load((charm_project / "charmcraft.yaml").read_text())
        project["parts"]["setup"] = {"plugin": "nil"}
        (charm_project / "charmcraft.yaml").write_text(yaml.safe_dump(project))

        with mock.patch("quickpack.parts.subprocess.run"):
            result = pack.quick_pack(charm_project, output_dir=tmp_path)

        assert result.exists()

    def test_quick_pack_rejects_override_build(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """Override-build raises so the dev loop falls back to charmcraft (Phase 38.3)."""
        project = yaml.safe_load((charm_project / "charmcraft.yaml").read_text())
        project["parts"]["charm"]["override-build"] = (
            "craftctl default\ngit describe --always > $CRAFT_PART_INSTALL/version\n"
        )
        (charm_project / "charmcraft.yaml").write_text(yaml.safe_dump(project))

        with pytest.raises(ValueError, match="override-build"):
            pack.quick_pack(charm_project, output_dir=tmp_path)

    def test_quick_pack_no_charmcraft_yaml(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(FileNotFoundError, match="charmcraft.yaml"):
            pack.quick_pack(tmp_path)

    def test_quick_pack_custom_entrypoint(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        project = yaml.safe_load((charm_project / "charmcraft.yaml").read_text())
        project["parts"]["charm"]["charm-entrypoint"] = "src/app.py"
        (charm_project / "charmcraft.yaml").write_text(yaml.safe_dump(project))

        # Create the custom entrypoint.
        (charm_project / "src" / "app.py").write_text("import ops\n")

        with mock.patch("quickpack.parts.subprocess.run"):
            result = pack.quick_pack(charm_project, output_dir=tmp_path)

        with zipfile.ZipFile(str(result)) as zf:
            dispatch = zf.read("dispatch").decode()
            assert "src/app.py" in dispatch
