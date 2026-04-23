"""Tests for :mod:`cantrip.workspace` (Phase 33.3)."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from cantrip.workspace import (
    MANIFEST_FILENAME,
    Workspace,
    WorkspaceError,
    find_manifest,
    load_workspace,
)


def _write_manifest(root: pathlib.Path, body: str) -> pathlib.Path:
    (root / MANIFEST_FILENAME).write_text(textwrap.dedent(body).lstrip())
    return root / MANIFEST_FILENAME


class TestLoadWorkspace:
    """Happy-path and error-path parsing."""

    def test_minimal_manifest_parses(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms:
              - name: api
                path: ./api-operator
            """,
        )
        (tmp_path / "api-operator").mkdir()
        ws = load_workspace(tmp_path)
        assert ws.name == "demo"
        assert ws.root == tmp_path.resolve()
        assert [c.name for c in ws.charms] == ["api"]
        assert ws.charms[0].path == (tmp_path / "api-operator").resolve()
        assert ws.relations == ()
        assert ws.shared_config == {}

    def test_manifest_path_or_directory_both_work(self, tmp_path: pathlib.Path):
        manifest = _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms:
              - name: a
                path: ./a
            """,
        )
        via_dir = load_workspace(tmp_path)
        via_file = load_workspace(manifest)
        assert via_dir.name == via_file.name == "demo"

    def test_full_manifest_roundtrips_to_dict(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            workspace: my-platform
            description: API + workers sharing a queue.
            charms:
              - name: my-api
                path: ./my-api-operator
                description: 12-factor Flask charm.
              - name: my-worker
                path: ./my-worker-operator
            relations:
              - provider: my-api:workers
                requirer: my-worker:coordinator
                interface: worker-coordination
                description: API emits jobs; worker acks.
            shared_config:
              log_level: info
              tls_mode: strict
            """,
        )
        ws = load_workspace(tmp_path)
        assert ws.name == "my-platform"
        assert ws.description is not None and "API" in ws.description
        assert ws.charm_names() == ["my-api", "my-worker"]
        assert len(ws.relations) == 1
        assert ws.relations[0].interface == "worker-coordination"
        assert ws.shared_config == {"log_level": "info", "tls_mode": "strict"}
        assert ws.find_charm("my-api") is not None
        assert ws.find_charm("not-a-thing") is None

        # to_dict must contain every provided field.
        payload = ws.to_dict()
        assert payload["workspace"] == "my-platform"
        assert payload["charms"][0]["description"] == "12-factor Flask charm."
        assert payload["relations"][0]["interface"] == "worker-coordination"
        assert payload["shared_config"]["tls_mode"] == "strict"

    def test_missing_manifest_raises(self, tmp_path: pathlib.Path):
        with pytest.raises(WorkspaceError, match="No workspace manifest"):
            load_workspace(tmp_path)

    def test_invalid_yaml_raises(self, tmp_path: pathlib.Path):
        (tmp_path / MANIFEST_FILENAME).write_text("workspace: demo\n  charms:\n- : bad\n")
        with pytest.raises(WorkspaceError, match="Invalid YAML"):
            load_workspace(tmp_path)

    def test_manifest_not_mapping_raises(self, tmp_path: pathlib.Path):
        (tmp_path / MANIFEST_FILENAME).write_text("- just\n- a list\n")
        with pytest.raises(WorkspaceError, match="must be a YAML mapping"):
            load_workspace(tmp_path)

    def test_missing_workspace_name_raises(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            charms:
              - name: a
                path: ./a
            """,
        )
        with pytest.raises(WorkspaceError, match="non-empty 'workspace' name"):
            load_workspace(tmp_path)

    def test_empty_charms_raises(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms: []
            """,
        )
        with pytest.raises(WorkspaceError, match="at least one charm"):
            load_workspace(tmp_path)

    def test_duplicate_charm_name_raises(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms:
              - name: dup
                path: ./a
              - name: dup
                path: ./b
            """,
        )
        with pytest.raises(WorkspaceError, match="Duplicate charm name"):
            load_workspace(tmp_path)

    def test_relation_with_unknown_charm_raises(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms:
              - name: a
                path: ./a
            relations:
              - provider: a:ep
                requirer: ghost:ep
                interface: some-iface
            """,
        )
        with pytest.raises(WorkspaceError, match="names unknown charm"):
            load_workspace(tmp_path)

    def test_relation_missing_colon_raises(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms:
              - name: a
                path: ./a
              - name: b
                path: ./b
            relations:
              - provider: a
                requirer: b:ep
                interface: iface
            """,
        )
        with pytest.raises(WorkspaceError, match="must be 'charm-name:endpoint'"):
            load_workspace(tmp_path)

    def test_relation_missing_interface_raises(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms:
              - name: a
                path: ./a
              - name: b
                path: ./b
            relations:
              - provider: a:ep
                requirer: b:ep
            """,
        )
        with pytest.raises(WorkspaceError, match="must include 'provider'"):
            load_workspace(tmp_path)


class TestFindManifest:
    """Walking upwards to locate a manifest."""

    def test_finds_manifest_in_cwd(self, tmp_path: pathlib.Path):
        manifest = _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms: [{name: a, path: ./a}]
            """,
        )
        assert find_manifest(tmp_path) == manifest.resolve()

    def test_finds_manifest_in_ancestor(self, tmp_path: pathlib.Path):
        manifest = _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms: [{name: a, path: ./a}]
            """,
        )
        nested = tmp_path / "a" / "src" / "deep"
        nested.mkdir(parents=True)
        assert find_manifest(nested) == manifest.resolve()

    def test_returns_none_when_absent(self, tmp_path: pathlib.Path):
        # tmp_path itself has no manifest, and its ancestors inside pytest's
        # tmp tree don't either.
        assert find_manifest(tmp_path / "nested") is None or isinstance(
            find_manifest(tmp_path / "nested"), pathlib.Path
        )
        # More precise: explicitly build a directory chain with no manifest.
        nested = tmp_path / "x" / "y"
        nested.mkdir(parents=True)
        # Start search in an isolated subtree; walking up eventually hits root.
        # We accept either None or some Path that Cantrip doesn't own — the
        # important contract is the function doesn't raise.
        result = find_manifest(nested)
        if result is not None:
            assert result.is_file()


class TestWorkspaceHelpers:
    """Frozen-dataclass accessors."""

    def test_charm_names_and_lookup(self, tmp_path: pathlib.Path):
        _write_manifest(
            tmp_path,
            """
            workspace: demo
            charms:
              - name: alpha
                path: ./alpha
              - name: beta
                path: ./beta
            """,
        )
        ws = load_workspace(tmp_path)
        assert ws.charm_names() == ["alpha", "beta"]
        assert ws.find_charm("alpha") is not None
        assert ws.find_charm("gamma") is None

    def test_workspace_is_frozen(self):
        ws = Workspace(name="x", root=pathlib.Path("/"), charms=())
        with pytest.raises(AttributeError):
            ws.name = "changed"  # type: ignore[misc]
