"""Unit tests for ``quickpack.metadata``."""

import pathlib

import pytest
import yaml

from quickpack import metadata


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

    def test_resolve_target_python_24_04(self) -> None:
        """24.04 base maps to system Python 3.12."""
        assert metadata.resolve_target_python({"base": "ubuntu@24.04"}) == "3.12"

    def test_resolve_target_python_22_04(self) -> None:
        """22.04 base maps to system Python 3.10 — common scaffolded charm default."""
        assert metadata.resolve_target_python({"base": "ubuntu@22.04"}) == "3.10"

    def test_resolve_target_python_prefers_build_base(self) -> None:
        """``build-base`` overrides ``base`` when both are set.

        charmcraft uses build-base to pick the build environment, so
        the venv's Python must match build-base, not the runtime base.
        """
        project = {"base": "ubuntu@22.04", "build-base": "ubuntu@24.04"}
        assert metadata.resolve_target_python(project) == "3.12"

    def test_resolve_target_python_unknown_series_returns_none(self) -> None:
        """An unrecognised series falls back so the caller picks host Python."""
        assert metadata.resolve_target_python({"base": "ubuntu@99.04"}) is None

    def test_resolve_target_python_non_ubuntu_returns_none(self) -> None:
        """Non-Ubuntu bases (centos, etc.) fall back to host Python.

        We don't ship a mapping for them; refusing here would break
        any downstream that has its own Python on PATH.
        """
        assert metadata.resolve_target_python({"base": "centos@9"}) is None

    def test_local_arch_accepts_arm64_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("quickpack.metadata.platform.machine", lambda: "arm64")
        assert metadata.local_arch() == "arm64"

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
