"""Tests for :mod:`cantrip.compare` (Phase 31.7).

Covers snapshot extraction, the diff primitives, and the report
renderer.  Snapshots are built from real files on disk under
``tmp_path`` rather than mocked dicts — the module does non-trivial
YAML merging and file-system walking, so the tests mirror how the CLI
will call into it.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from cantrip import compare


def _write_charm(
    root: pathlib.Path,
    *,
    charmcraft: str | None = None,
    metadata: str | None = None,
    config: str | None = None,
    actions: str | None = None,
    unit_tests: int = 0,
    integration_tests: int = 0,
    landmarks: tuple[str, ...] = (),
) -> pathlib.Path:
    """Create a charm directory scaffold for a test.

    *landmarks* are extra top-level files/directories to touch so the
    structure diff has something to walk.  ``charmcraft.yaml`` etc.
    are written when their argument is non-None.
    """
    root.mkdir(parents=True, exist_ok=True)
    if charmcraft is not None:
        (root / "charmcraft.yaml").write_text(charmcraft)
    if metadata is not None:
        (root / "metadata.yaml").write_text(metadata)
    if config is not None:
        (root / "config.yaml").write_text(config)
    if actions is not None:
        (root / "actions.yaml").write_text(actions)
    for i in range(unit_tests):
        test_dir = root / "tests" / "unit"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / f"test_thing_{i}.py").write_text("def test_x(): pass\n")
    for i in range(integration_tests):
        test_dir = root / "tests" / "integration"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / f"test_integration_{i}.py").write_text("def test_y(): pass\n")
    for mark in landmarks:
        target = root / mark
        if "/" in mark or mark in {"src", "lib", "tests", "docs", "terraform"}:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.write_text("")
    return root


# ── snapshot_charm ────────────────────────────────────────────────────


class TestSnapshotCharm:
    """Cover the parse-charm-directory path."""

    def test_missing_directory_returns_empty_snapshot(self, tmp_path: pathlib.Path) -> None:
        """A non-existent path yields an empty-but-valid snapshot.

        Callers get NullSafe defaults rather than an exception so they
        can still run the diff and see "everything is missing on one
        side".
        """
        snap = compare.snapshot_charm(tmp_path / "nonexistent")
        assert snap.charm_name == "nonexistent"
        assert snap.config_options == {}
        assert snap.provides == {}
        assert snap.requires == {}
        assert snap.present_landmarks == frozenset()

    def test_parses_modern_charmcraft_yaml(self, tmp_path: pathlib.Path) -> None:
        """``charmcraft.yaml`` (4.x) merges metadata/config/actions in one file."""
        charmcraft = textwrap.dedent(
            """\
            name: my-charm
            base: ubuntu@24.04
            containers:
              workload:
                resource: oci-image
            extensions:
              - flask-framework
            requires:
              database:
                interface: postgresql_client
              logging:
                interface: loki_push_api
            provides:
              metrics:
                interface: prometheus_scrape
            peers:
              replicas:
                interface: my_charm_replicas
            config:
              options:
                log-level:
                  type: string
                  default: info
                replicas:
                  type: int
                  default: 3
            actions:
              backup:
                description: Take a backup.
              restore:
                description: Restore.
            """
        )
        charm = _write_charm(
            tmp_path / "modern",
            charmcraft=charmcraft,
            unit_tests=3,
            integration_tests=1,
            landmarks=("src", "pyproject.toml", "README.md"),
        )
        snap = compare.snapshot_charm(charm)

        assert snap.charm_name == "my-charm"
        assert snap.base == "ubuntu@24.04"
        assert snap.containers == frozenset({"workload"})
        assert snap.extensions == frozenset({"flask-framework"})
        assert snap.provides == {"metrics": "prometheus_scrape"}
        assert snap.requires == {"database": "postgresql_client", "logging": "loki_push_api"}
        assert snap.peers == {"replicas": "my_charm_replicas"}
        assert snap.config_options["log-level"]["type"] == "string"
        assert snap.config_options["log-level"]["default"] == "info"
        assert snap.config_options["replicas"]["default"] == 3
        assert snap.actions == frozenset({"backup", "restore"})
        assert snap.unit_test_count == 3
        assert snap.integration_test_count == 1
        assert "src" in snap.present_landmarks
        assert "pyproject.toml" in snap.present_landmarks
        assert "README.md" in snap.present_landmarks
        assert "tests/unit" in snap.present_landmarks

    def test_legacy_split_files_are_merged(self, tmp_path: pathlib.Path) -> None:
        """``metadata.yaml`` + ``config.yaml`` + ``actions.yaml`` still work."""
        charm = _write_charm(
            tmp_path / "legacy",
            metadata=textwrap.dedent(
                """\
                name: legacy-charm
                requires:
                  db:
                    interface: mysql
                """
            ),
            config=textwrap.dedent(
                """\
                options:
                  port:
                    type: int
                    default: 8080
                """
            ),
            actions=textwrap.dedent(
                """\
                reload:
                  description: Reload config.
                """
            ),
        )
        snap = compare.snapshot_charm(charm)
        assert snap.charm_name == "legacy-charm"
        assert snap.requires == {"db": "mysql"}
        assert snap.config_options["port"]["default"] == 8080
        assert snap.actions == frozenset({"reload"})

    def test_charmcraft_wins_over_legacy_files(self, tmp_path: pathlib.Path) -> None:
        """When both exist, charmcraft.yaml overrides metadata.yaml."""
        charm = _write_charm(
            tmp_path / "mixed",
            charmcraft="name: new-name\n",
            metadata="name: old-name\n",
        )
        snap = compare.snapshot_charm(charm)
        assert snap.charm_name == "new-name"

    def test_malformed_yaml_treated_as_empty(self, tmp_path: pathlib.Path) -> None:
        charm = _write_charm(tmp_path / "busted", charmcraft=": : :\n  - invalid\n  oops:")
        snap = compare.snapshot_charm(charm)
        # Falls back to directory name + empty fields, doesn't raise.
        assert snap.charm_name == "busted"
        assert snap.config_options == {}

    def test_non_dict_relation_entries_filtered(self, tmp_path: pathlib.Path) -> None:
        """A typo that makes ``requires`` a list must not crash the parser."""
        charm = _write_charm(
            tmp_path / "typo",
            charmcraft=textwrap.dedent(
                """\
                name: typo
                requires:
                  - database
                """
            ),
        )
        snap = compare.snapshot_charm(charm)
        assert snap.requires == {}

    def test_legacy_bases_list_form(self, tmp_path: pathlib.Path) -> None:
        """Older ``bases:`` list form still surfaces as ``name@channel``."""
        charm = _write_charm(
            tmp_path / "older",
            charmcraft=textwrap.dedent(
                """\
                name: older
                bases:
                  - name: ubuntu
                    channel: "22.04"
                """
            ),
        )
        snap = compare.snapshot_charm(charm)
        assert snap.base == "ubuntu@22.04"

    def test_legacy_bases_with_empty_build_on_list(self, tmp_path: pathlib.Path) -> None:
        """``bases: [{build-on: []}]`` must not crash the snapshot.

        Regression: an explicit but empty ``build-on`` list used to make
        ``_extract_base`` index past the end of the list and raise
        ``IndexError``, killing ``cantrip compare`` outright.
        """
        charm = _write_charm(
            tmp_path / "empty_build_on",
            charmcraft=textwrap.dedent(
                """\
                name: empty-build-on
                bases:
                  - build-on: []
                """
            ),
        )
        snap = compare.snapshot_charm(charm)
        assert snap.base == ""

    def test_legacy_bases_with_build_on_entries(self, tmp_path: pathlib.Path) -> None:
        """When ``build-on`` is populated, surface the first entry's name/channel."""
        charm = _write_charm(
            tmp_path / "build_on_pop",
            charmcraft=textwrap.dedent(
                """\
                name: build-on-pop
                bases:
                  - build-on:
                      - name: ubuntu
                        channel: "22.04"
                """
            ),
        )
        snap = compare.snapshot_charm(charm)
        assert snap.base == "ubuntu@22.04"

    def test_non_utf8_yaml_does_not_crash(self, tmp_path: pathlib.Path) -> None:
        """A latin-1 charmcraft.yaml must not abort the snapshot.

        Regression: ``_load_yaml`` called ``path.read_text()`` with
        strict UTF-8, so a file containing legacy bytes (e.g. a
        latin-1 ``é``) raised ``UnicodeDecodeError`` and crashed
        ``cantrip compare`` before the diff could run.
        """
        charm = tmp_path / "latin1"
        charm.mkdir()
        # ``é`` (0xe9) in latin-1 — invalid as utf-8.
        (charm / "charmcraft.yaml").write_bytes(b"name: latin1\nsummary: caf\xe9\n")
        snap = compare.snapshot_charm(charm)
        assert snap.charm_name == "latin1"


# ── compare_charms + diff primitives ─────────────────────────────────


class TestCompareCharms:
    """Cover :func:`compare.compare_charms` end-to-end."""

    def test_identical_charms_report_no_drift(self, tmp_path: pathlib.Path) -> None:
        body = textwrap.dedent(
            """\
            name: twin
            requires:
              db:
                interface: pg
            config:
              options:
                level: {type: string, default: info}
            """
        )
        a = _write_charm(tmp_path / "a", charmcraft=body, unit_tests=2)
        b = _write_charm(tmp_path / "b", charmcraft=body, unit_tests=2)

        report = compare.compare_charms(a, b)
        assert report.structure.added == () and report.structure.removed == ()
        assert report.config.added == ()
        assert report.config.removed == ()
        assert report.config.changed == ()
        assert report.requires.changed == ()

    def test_detects_added_removed_changed_config(self, tmp_path: pathlib.Path) -> None:
        left_body = textwrap.dedent(
            """\
            name: side-a
            config:
              options:
                shared: {type: string, default: one}
                only-left: {type: string, default: l}
            """
        )
        right_body = textwrap.dedent(
            """\
            name: side-b
            config:
              options:
                shared: {type: string, default: two}
                only-right: {type: int, default: 7}
            """
        )
        a = _write_charm(tmp_path / "a", charmcraft=left_body)
        b = _write_charm(tmp_path / "b", charmcraft=right_body)

        report = compare.compare_charms(a, b)
        assert report.config.added == ("only-right",)
        assert report.config.removed == ("only-left",)
        assert report.config.changed == ("shared",)

    def test_interface_change_surfaces_as_changed(self, tmp_path: pathlib.Path) -> None:
        """Same endpoint name with a different interface counts as changed."""
        a = _write_charm(
            tmp_path / "a",
            charmcraft=textwrap.dedent(
                """\
                name: a
                requires:
                  ingress:
                    interface: ingress
                """
            ),
        )
        b = _write_charm(
            tmp_path / "b",
            charmcraft=textwrap.dedent(
                """\
                name: b
                requires:
                  ingress:
                    interface: traefik_route
                """
            ),
        )
        report = compare.compare_charms(a, b)
        assert report.requires.changed == ("ingress",)
        assert report.requires.added == ()
        assert report.requires.removed == ()

    def test_test_counts_surface_in_snapshot(self, tmp_path: pathlib.Path) -> None:
        a = _write_charm(tmp_path / "a", charmcraft="name: a\n", unit_tests=5, integration_tests=2)
        b = _write_charm(tmp_path / "b", charmcraft="name: b\n", unit_tests=1, integration_tests=0)
        report = compare.compare_charms(a, b)
        assert report.left.unit_test_count == 5
        assert report.left.integration_test_count == 2
        assert report.right.unit_test_count == 1
        assert report.right.integration_test_count == 0


# ── Rendering ─────────────────────────────────────────────────────────


class TestFormatReport:
    """Smoke-tests for the human-readable report."""

    def test_identical_charms_render_as_identical(self, tmp_path: pathlib.Path) -> None:
        body = "name: twin\nrequires:\n  db:\n    interface: pg\n"
        a = _write_charm(tmp_path / "a", charmcraft=body, unit_tests=1)
        b = _write_charm(tmp_path / "b", charmcraft=body, unit_tests=1)
        report = compare.compare_charms(a, b)
        text = compare.format_report(report)

        assert "Comparing " in text
        assert "(identical" in text
        # Test-count line is always rendered, even when identical.
        assert "unit:" in text

    def test_surfaces_name_base_and_extensions(self, tmp_path: pathlib.Path) -> None:
        body = textwrap.dedent(
            """\
            name: showcase
            base: ubuntu@24.04
            extensions:
              - flask-framework
            """
        )
        a = _write_charm(tmp_path / "a", charmcraft=body)
        b = _write_charm(tmp_path / "b", charmcraft="name: other\n")
        text = compare.format_report(compare.compare_charms(a, b))

        assert "showcase" in text and "other" in text
        assert "ubuntu@24.04" in text
        assert "flask-framework" in text
        assert "(missing)" in text  # right has no base

    def test_changed_value_is_rendered_with_both_sides(self, tmp_path: pathlib.Path) -> None:
        """A changed config option should show left and right values side by side."""
        a = _write_charm(
            tmp_path / "a",
            charmcraft=(
                "name: a\nconfig:\n  options:\n    level: {type: string, default: info}\n"
            ),
        )
        b = _write_charm(
            tmp_path / "b",
            charmcraft=(
                "name: b\nconfig:\n  options:\n    level: {type: string, default: debug}\n"
            ),
        )
        text = compare.format_report(compare.compare_charms(a, b))
        assert "changed: level" in text
        assert "info" in text
        assert "debug" in text


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ({"a": 1}, {"a": 1}, ((), (), ())),
        ({"a": 1}, {"b": 2}, (("b",), ("a",), ())),
        ({"a": 1}, {"a": 2}, ((), (), ("a",))),
        ({"a": 1, "b": 2}, {"a": 1, "c": 3}, (("c",), ("b",), ())),
    ],
)
def test_diff_dicts_primitive(
    left: dict, right: dict, expected: tuple[tuple, tuple, tuple]
) -> None:
    """Sanity-check the diff primitive on its own — the end-to-end tests rely on it."""
    diff = compare._diff_dicts(left, right)
    assert (diff.added, diff.removed, diff.changed) == expected
