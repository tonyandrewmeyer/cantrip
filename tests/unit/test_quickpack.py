"""Unit tests for the quickpack package."""

import pathlib
import stat
import subprocess
import zipfile
from unittest import mock

import pytest
import yaml

from quickpack import jujuignore, metadata, pack, parts

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Jujuignore tests
# ---------------------------------------------------------------------------


class TestJujuignore:
    """Tests for jujuignore pattern matching."""

    def test_default_ignores(self) -> None:
        ignore = jujuignore.JujuIgnore()
        assert ignore.match(".git", is_dir=True)
        assert ignore.match(".tox", is_dir=True)
        assert ignore.match("build", is_dir=True)
        assert ignore.match(".jujuignore", is_dir=False)

    def test_custom_pattern(self) -> None:
        ignore = jujuignore.JujuIgnore(["*.pyc"])
        assert ignore.match("module.pyc", is_dir=False)
        assert not ignore.match("module.py", is_dir=False)

    def test_negation(self) -> None:
        ignore = jujuignore.JujuIgnore(["*.log", "!important.log"])
        # The negation inverts — important.log should NOT be ignored.
        assert not ignore.match("important.log", is_dir=False)
        assert ignore.match("debug.log", is_dir=False)

    def test_directory_only(self) -> None:
        ignore = jujuignore.JujuIgnore(["cache/"])
        assert ignore.match("cache", is_dir=True)
        assert not ignore.match("cache", is_dir=False)

    def test_doublestar(self) -> None:
        ignore = jujuignore.JujuIgnore(["**/__pycache__"])
        assert ignore.match("src/__pycache__", is_dir=True)
        assert ignore.match("deep/nested/__pycache__", is_dir=True)

    def test_leading_slash(self) -> None:
        """A pattern with a leading / only matches at the root."""
        ignore = jujuignore.JujuIgnore(["/build/"])
        assert ignore.match("build", is_dir=True)
        # Should NOT match build in a subdirectory.
        assert not ignore.match("src/build", is_dir=True)

    def test_from_file(self, tmp_path: pathlib.Path) -> None:
        ignore_file = tmp_path / ".jujuignore"
        ignore_file.write_text("*.bak\n# comment\n\ntmp/\n")
        ignore = jujuignore.JujuIgnore.from_file(str(ignore_file))
        assert ignore.match("foo.bak", is_dir=False)
        assert ignore.match("tmp", is_dir=True)

    def test_from_file_missing(self, tmp_path: pathlib.Path) -> None:
        """Missing file should use only defaults."""
        ignore = jujuignore.JujuIgnore.from_file(str(tmp_path / ".jujuignore"))
        assert ignore.match(".git", is_dir=True)
        assert not ignore.match("src", is_dir=True)

    def test_venv_ignored(self) -> None:
        ignore = jujuignore.JujuIgnore()
        assert ignore.match("venv", is_dir=True)

    def test_comment_and_blank_lines(self) -> None:
        ignore = jujuignore.JujuIgnore(["# comment", "", "   ", "*.tmp"])
        assert ignore.match("foo.tmp", is_dir=False)
        # Comments and blanks should not create matchers.
        assert not ignore.match("# comment", is_dir=False)


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


class TestMetadata:
    """Tests for charmcraft.yaml → metadata.yaml generation."""

    def test_parse_charmcraft_yaml(self, charm_project: pathlib.Path) -> None:
        project = metadata.parse_charmcraft_yaml(charm_project)
        assert project["name"] == "mycharm"
        assert project["summary"] == "A test charm"

    def test_parse_missing(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(FileNotFoundError):
            metadata.parse_charmcraft_yaml(tmp_path)

    def test_parse_infers_name_from_directory(self, tmp_path: pathlib.Path) -> None:
        """When charmcraft.yaml has no name field, infer from directory name."""
        charm_dir = tmp_path / "saml-integrator"
        charm_dir.mkdir()
        (charm_dir / "charmcraft.yaml").write_text(
            'type: "charm"\nbases:\n  - build-on:\n    - name: ubuntu\n'
        )
        project = metadata.parse_charmcraft_yaml(charm_dir)
        assert project["name"] == "saml-integrator"

    def test_resolve_base_modern(self) -> None:
        project = {"base": "ubuntu@24.04"}
        assert metadata.resolve_base(project) == ("ubuntu", "24.04")

    def test_resolve_base_platforms(self) -> None:
        project = {"platforms": {"ubuntu@22.04:amd64": None}}
        assert metadata.resolve_base(project) == ("ubuntu", "22.04")

    def test_resolve_base_legacy(self) -> None:
        project = {
            "bases": [
                {"run-on": [{"name": "ubuntu", "channel": "20.04"}]},
            ],
        }
        assert metadata.resolve_base(project) == ("ubuntu", "20.04")

    def test_resolve_base_default(self) -> None:
        assert metadata.resolve_base({}) == ("ubuntu", "24.04")

    def test_resolve_entrypoint_default(self) -> None:
        assert metadata.resolve_entrypoint({}) == "src/charm.py"

    def test_resolve_entrypoint_custom(self) -> None:
        project = {
            "parts": {
                "charm": {"charm-entrypoint": "src/app.py"},
            },
        }
        assert metadata.resolve_entrypoint(project) == "src/app.py"

    def test_generate_metadata_basic(self) -> None:
        project = {
            "name": "test-charm",
            "summary": "A summary",
            "description": "A description",
        }
        meta = metadata.generate_metadata(project)
        assert meta["name"] == "test-charm"
        assert meta["summary"] == "A summary"

    def test_generate_metadata_title_renamed(self) -> None:
        project = {
            "name": "test-charm",
            "summary": "s",
            "description": "d",
            "title": "My Charm",
        }
        meta = metadata.generate_metadata(project)
        assert "title" not in meta
        assert meta["display-name"] == "My Charm"

    def test_generate_metadata_links_flattened(self) -> None:
        project = {
            "name": "test-charm",
            "summary": "s",
            "description": "d",
            "links": {
                "documentation": "https://docs.example.com",
                "contact": "admin@example.com",
                "issues": "https://github.com/example/issues",
                "website": "https://example.com",
                "source": "https://github.com/example",
            },
        }
        meta = metadata.generate_metadata(project)
        assert meta["docs"] == "https://docs.example.com"
        assert meta["maintainers"] == ["admin@example.com"]
        assert meta["issues"] == "https://github.com/example/issues"
        assert meta["website"] == "https://example.com"
        assert meta["source"] == "https://github.com/example"

    def test_generate_metadata_links_contact_list(self) -> None:
        project = {
            "name": "test",
            "summary": "s",
            "description": "d",
            "links": {"contact": ["a@b.com", "c@d.com"]},
        }
        meta = metadata.generate_metadata(project)
        assert meta["maintainers"] == ["a@b.com", "c@d.com"]

    def test_generate_metadata_relations(self) -> None:
        project = {
            "name": "test",
            "summary": "s",
            "description": "d",
            "requires": {"db": {"interface": "mysql"}},
            "provides": {"web": {"interface": "http"}},
        }
        meta = metadata.generate_metadata(project)
        assert meta["requires"] == {"db": {"interface": "mysql"}}
        assert meta["provides"] == {"web": {"interface": "http"}}

    def test_generate_manifest(self) -> None:
        project = {"name": "test", "base": "ubuntu@24.04"}
        manifest = metadata.generate_manifest(project, arch="amd64")
        assert manifest["bases"][0]["name"] == "ubuntu"
        assert manifest["bases"][0]["channel"] == "24.04"
        assert manifest["bases"][0]["architectures"] == ["amd64"]
        assert manifest["charmcraft-version"].startswith("quickpack-")
        assert "charmcraft-started-at" in manifest
        attrs = manifest["analysis"]["attributes"]
        assert {"name": "language", "result": "unknown"} in attrs
        assert {"name": "framework", "result": "unknown"} in attrs

    def test_generate_manifest_detects_python(self) -> None:
        project = {
            "name": "test",
            "base": "ubuntu@24.04",
            "parts": {"charm": {"plugin": "uv"}},
        }
        manifest = metadata.generate_manifest(project, arch="amd64")
        attrs = manifest["analysis"]["attributes"]
        assert {"name": "language", "result": "python"} in attrs

    def test_charm_filename_arch_only(self) -> None:
        project = {"name": "myapp", "base": "ubuntu@24.04", "platforms": {"amd64": None}}
        assert metadata.charm_filename(project, arch="amd64") == "myapp_amd64.charm"

    def test_charm_filename_full_platform(self) -> None:
        project = {"name": "myapp", "platforms": {"ubuntu@24.04:amd64": None}}
        assert metadata.charm_filename(project, arch="amd64") == "myapp_ubuntu@24.04-amd64.charm"

    def test_charm_filename_no_platforms(self) -> None:
        project = {"name": "myapp", "base": "ubuntu@24.04"}
        assert metadata.charm_filename(project, arch="amd64") == "myapp_ubuntu@24.04-amd64.charm"

    def test_write_optional_yaml_from_disk(self, tmp_path: pathlib.Path) -> None:
        charm_dir = tmp_path / "charm"
        charm_dir.mkdir()
        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        # Write a source config.yaml on disk.
        (charm_dir / "config.yaml").write_text("options:\n  port:\n    type: int\n")

        project = {"config": {"options": {"port": {"type": "string"}}}}
        metadata.write_optional_yaml(project, "config", "config.yaml", charm_dir, prime_dir)

        # Should copy the on-disk version, not generate from project dict.
        content = (prime_dir / "config.yaml").read_text()
        assert "int" in content

    def test_write_optional_yaml_generated(self, tmp_path: pathlib.Path) -> None:
        charm_dir = tmp_path / "charm"
        charm_dir.mkdir()
        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        project = {"actions": {"restart": {"description": "Restart the service"}}}
        metadata.write_optional_yaml(project, "actions", "actions.yaml", charm_dir, prime_dir)

        content = yaml.safe_load((prime_dir / "actions.yaml").read_text())
        assert content["restart"]["description"] == "Restart the service"

    def test_write_optional_yaml_absent(self, tmp_path: pathlib.Path) -> None:
        charm_dir = tmp_path / "charm"
        charm_dir.mkdir()
        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        metadata.write_optional_yaml({}, "config", "config.yaml", charm_dir, prime_dir)
        assert not (prime_dir / "config.yaml").exists()


# ---------------------------------------------------------------------------
# Parts tests
# ---------------------------------------------------------------------------


class TestParts:
    """Tests for parts processing."""

    def test_process_uv_part_copies_src_and_lib(
        self, charm_project: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """UV part should copy only src/ and lib/, not other project files."""
        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        # Add a README that should NOT be copied by the UV plugin.
        (charm_project / "README.md").write_text("# Hello\n")

        with mock.patch("quickpack.parts.subprocess.run"):
            parts.process_uv_part(charm_project, prime_dir, {"source": "."})

        assert (prime_dir / "src" / "charm.py").exists()
        assert (prime_dir / "lib" / "helpers.py").exists()
        assert not (prime_dir / "README.md").exists()

    def test_process_uv_part_no_src(self, tmp_path: pathlib.Path) -> None:
        """UV part should handle missing src/ gracefully."""
        charm_dir = tmp_path / "charm"
        charm_dir.mkdir()
        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        with mock.patch("quickpack.parts.subprocess.run"):
            parts.process_uv_part(charm_dir, prime_dir, {"source": "."})

        assert not (prime_dir / "src").exists()

    def test_process_dump_part(self, tmp_path: pathlib.Path) -> None:
        """Dump part should copy files respecting organize rules."""
        source = tmp_path / "extra"
        source.mkdir()
        (source / "config.ini").write_text("[section]\nkey=val\n")

        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        config = {
            "plugin": "dump",
            "source": str(source),
            "organize": {"config.ini": "etc/config.ini"},
        }
        parts.process_dump_part(tmp_path, prime_dir, config)

        assert (prime_dir / "etc" / "config.ini").exists()
        assert not (prime_dir / "config.ini").exists()

    def test_process_dump_part_stage_filter(self, tmp_path: pathlib.Path) -> None:
        """Stage filter should exclude non-matching files."""
        source = tmp_path / "files"
        source.mkdir()
        (source / "keep.txt").write_text("keep\n")
        (source / "drop.log").write_text("drop\n")

        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        config = {
            "plugin": "dump",
            "source": str(source),
            "stage": ["*.txt"],
        }
        parts.process_dump_part(tmp_path, prime_dir, config)

        assert (prime_dir / "keep.txt").exists()
        assert not (prime_dir / "drop.log").exists()

    def test_process_dump_part_prime_filter(self, tmp_path: pathlib.Path) -> None:
        """Prime filter should exclude files with - prefix."""
        source = tmp_path / "files"
        source.mkdir()
        (source / "a.txt").write_text("a\n")
        (source / "b.txt").write_text("b\n")

        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        config = {
            "plugin": "dump",
            "source": str(source),
            "prime": ["-b.txt"],
        }
        parts.process_dump_part(tmp_path, prime_dir, config)

        assert (prime_dir / "a.txt").exists()
        assert not (prime_dir / "b.txt").exists()

    def test_process_parts_no_parts(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(ValueError, match="No parts found"):
            parts.process_parts(tmp_path, tmp_path, {})

    def test_process_parts_no_uv(self, tmp_path: pathlib.Path) -> None:
        project = {"parts": {"extra": {"plugin": "dump", "source": "."}}}
        with pytest.raises(ValueError, match="requires a part with plugin: uv"):
            parts.process_parts(tmp_path, tmp_path, project)

    def test_process_parts_unsupported_plugin(self, tmp_path: pathlib.Path) -> None:
        project = {"parts": {"charm": {"plugin": "poetry"}}}
        with pytest.raises(ValueError, match="only supports 'uv', 'dump', and 'nil'"):
            parts.process_parts(tmp_path, tmp_path, project)

    def test_process_parts_rejects_override_build(self, tmp_path: pathlib.Path) -> None:
        # Charms like traefik-k8s, tempo, loki use override-build to run
        # custom commands (rustup, make, etc).  Quick pack can't replicate
        # those safely — it must fail clearly so the caller falls back to
        # charmcraft pack.
        project = {
            "parts": {
                "charm": {
                    "plugin": "uv",
                    "source": ".",
                    "override-build": "cargo build --release",
                }
            }
        }
        with pytest.raises(ValueError, match="override-build"):
            parts.process_parts(tmp_path, tmp_path, project)

    def test_process_parts_rejects_override_stage_prime_pull(self, tmp_path: pathlib.Path) -> None:
        for override in ("override-stage", "override-prime", "override-pull"):
            project = {"parts": {"charm": {"plugin": "uv", override: "true"}}}
            with pytest.raises(ValueError, match=override):
                parts.process_parts(tmp_path, tmp_path, project)

    def test_match_fileset_inclusions(self) -> None:
        assert parts._match_fileset("foo.py", ["*.py"])
        assert not parts._match_fileset("foo.txt", ["*.py"])

    def test_match_fileset_exclusions(self) -> None:
        assert parts._match_fileset("foo.py", ["-*.txt"])
        assert not parts._match_fileset("foo.txt", ["-*.txt"])

    def test_match_fileset_mixed(self) -> None:
        assert parts._match_fileset("a.py", ["*.py", "-b.py"])
        assert not parts._match_fileset("b.py", ["*.py", "-b.py"])

    def test_process_nil_part_noop(self) -> None:
        """Nil plugin with no override does nothing and doesn't raise."""
        parts.process_nil_part("setup", {})

    def test_process_nil_part_with_craftctl_only(self) -> None:
        """Nil with override-build that is just craftctl default is fine."""
        parts.process_nil_part(
            "setup",
            {
                "override-build": "craftctl default\n",
            },
        )

    def test_process_nil_part_with_comments(self) -> None:
        """Nil with override-build that has comments + craftctl default is fine."""
        parts.process_nil_part(
            "setup",
            {
                "override-build": "# Install tools\ncraftctl default\n",
            },
        )

    def test_process_nil_part_unsafe_override(self) -> None:
        """Nil with unrecognised override-build raises ValueError."""
        with pytest.raises(ValueError, match="cannot handle safely"):
            parts.process_nil_part(
                "setup",
                {
                    "override-build": "curl http://example.com | sh\n",
                },
            )

    def test_process_parts_accepts_nil(self, tmp_path: pathlib.Path) -> None:
        """Nil parts are accepted alongside a uv part."""
        prime = tmp_path / "prime"
        prime.mkdir()
        project = {
            "parts": {
                "setup": {"plugin": "nil"},
                "charm": {"plugin": "uv", "source": "."},
            },
        }
        with mock.patch("quickpack.parts.subprocess.run"):
            parts.process_parts(tmp_path, prime, project)

    def test_handle_override_git_version(self, tmp_path: pathlib.Path) -> None:
        """Git version override writes a version file."""
        prime = tmp_path / "prime"
        prime.mkdir()
        override = "craftctl default\ngit describe --always > $CRAFT_PART_INSTALL/version\n"
        with mock.patch("quickpack.parts.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="v1.2.3\n")
            parts._handle_override_build(tmp_path, prime, "charm", override)
        assert (prime / "version").read_text() == "v1.2.3\n"

    def test_handle_override_rustup(self, tmp_path: pathlib.Path) -> None:
        """Rustup override just verifies rustc is available."""
        prime = tmp_path / "prime"
        prime.mkdir()
        override = "rustup default stable\ncraftctl default\n"
        with mock.patch("quickpack.parts.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            parts._handle_override_build(tmp_path, prime, "charm", override)

    def test_handle_override_rustup_missing(self, tmp_path: pathlib.Path) -> None:
        """Rustup override raises when rustc is not available."""
        prime = tmp_path / "prime"
        prime.mkdir()
        override = "rustup default stable\ncraftctl default\n"
        with mock.patch("quickpack.parts.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1)
            with pytest.raises(ValueError, match="rustc is not available"):
                parts._handle_override_build(tmp_path, prime, "charm", override)

    def test_handle_override_unsafe(self, tmp_path: pathlib.Path) -> None:
        """Unrecognised override-build raises ValueError."""
        prime = tmp_path / "prime"
        prime.mkdir()
        override = "pip install something-sketchy\ncraftctl default\n"
        with pytest.raises(ValueError, match="cannot handle safely"):
            parts._handle_override_build(tmp_path, prime, "charm", override)


# ---------------------------------------------------------------------------
# Pack tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


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
