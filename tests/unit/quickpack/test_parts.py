"""Unit tests for ``quickpack.parts``.

Includes the attestation-verification path which lives in
``quickpack.parts`` alongside the uv-part processing.
"""

import pathlib
from unittest import mock

import pytest

import pypi_attest
from quickpack import parts


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

    def test_uv_subprocess_failure_raises_runtime_error_with_stderr(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A failed `uv` invocation should surface as a friendly RuntimeError.

        Without the wrapper, ``subprocess.run(check=True)`` raises
        ``CalledProcessError`` which the CLI's exception handler does
        not catch — the user sees a Python traceback instead of the
        actual ``uv sync`` failure message.
        """
        import subprocess

        charm_dir = tmp_path / "charm"
        charm_dir.mkdir()
        prime_dir = tmp_path / "prime"
        prime_dir.mkdir()

        def _fail(cmd, **_kwargs):  # noqa: ANN001 — test stub mimics subprocess.run.
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=cmd,
                output="",
                stderr="error: missing uv.lock\n",
            )

        with (
            mock.patch("quickpack.parts.subprocess.run", side_effect=_fail),
            pytest.raises(RuntimeError) as exc_info,
        ):
            parts.process_uv_part(charm_dir, prime_dir, {"source": "."})

        # The wrapped error should preserve uv's stderr so the user
        # sees *why* the pack failed.
        assert "missing uv.lock" in str(exc_info.value)

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


def _write_dist_info(
    site_packages: pathlib.Path,
    name: str,
    version: str,
) -> None:
    """Create a minimal ``<name>-<version>.dist-info`` with a METADATA file."""
    dist_info = site_packages / f"{name}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    )


class TestAttestations:
    """Tests for quickpack's attestation-verification path."""

    def _make_venv_with(
        self,
        tmp_path: pathlib.Path,
        dists: list[tuple[str, str]],
    ) -> pathlib.Path:
        venv = tmp_path / "venv"
        site = venv / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True)
        for name, version in dists:
            _write_dist_info(site, name, version)
        return venv

    def test_iter_installed_distributions_reads_dist_info(self, tmp_path: pathlib.Path) -> None:
        venv = self._make_venv_with(tmp_path, [("ops", "3.7.0"), ("requests", "2.33.0")])
        result = parts._iter_installed_distributions(venv)
        assert sorted(result) == [("ops", "3.7.0"), ("requests", "2.33.0")]

    def test_iter_ignores_incomplete_dist_info(self, tmp_path: pathlib.Path) -> None:
        venv = tmp_path / "venv"
        site = venv / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True)
        # dist-info with no METADATA file.
        (site / "bogus-1.0.dist-info").mkdir()
        assert parts._iter_installed_distributions(venv) == []

    def test_must_have_unattested_raises(self, tmp_path: pathlib.Path) -> None:
        venv = self._make_venv_with(tmp_path, [("ops", "3.7.0")])
        stub = mock.MagicMock(
            return_value=pypi_attest.ProvenanceResult(
                name="ops",
                status=pypi_attest.ProvenanceStatus.UNATTESTED,
                version="3.7.0",
            )
        )
        with (
            mock.patch("pypi_attest.check_provenance", stub),
            pytest.raises(parts.AttestationError, match="required packages"),
        ):
            parts._verify_installed_attestations(venv, strict=False)

    def test_non_must_have_is_warning_in_default_mode(
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        venv = self._make_venv_with(tmp_path, [("requests", "2.33.0")])

        def _impl(name: str, _version: str | None = None, **_kw: object):
            return pypi_attest.ProvenanceResult(
                name=name,
                status=pypi_attest.ProvenanceStatus.UNATTESTED,
                version=_version,
            )

        with (
            mock.patch("pypi_attest.check_provenance", side_effect=_impl),
            caplog.at_level("WARNING", logger="quickpack.parts"),
        ):
            parts._verify_installed_attestations(venv, strict=False)

        assert any("requests" in rec.message for rec in caplog.records)

    def test_non_must_have_raises_in_strict_mode(self, tmp_path: pathlib.Path) -> None:
        venv = self._make_venv_with(tmp_path, [("requests", "2.33.0")])

        def _impl(name: str, _version: str | None = None, **_kw: object):
            return pypi_attest.ProvenanceResult(
                name=name,
                status=pypi_attest.ProvenanceStatus.UNATTESTED,
                version=_version,
            )

        with (
            mock.patch("pypi_attest.check_provenance", side_effect=_impl),
            pytest.raises(parts.AttestationError, match="strict mode"),
        ):
            parts._verify_installed_attestations(venv, strict=True)

    def test_unknown_status_does_not_fail(
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Network errors should degrade to warnings, not fail the pack."""
        venv = self._make_venv_with(tmp_path, [("ops", "3.7.0")])

        def _impl(name: str, _version: str | None = None, **_kw: object):
            return pypi_attest.ProvenanceResult(
                name=name,
                status=pypi_attest.ProvenanceStatus.UNKNOWN,
                version=_version,
                detail="offline",
            )

        with (
            mock.patch("pypi_attest.check_provenance", side_effect=_impl),
            caplog.at_level("WARNING", logger="quickpack.parts"),
        ):
            parts._verify_installed_attestations(venv, strict=True)

        assert any("offline" in rec.message for rec in caplog.records)

    def test_all_attested_is_silent(self, tmp_path: pathlib.Path) -> None:
        venv = self._make_venv_with(tmp_path, [("ops", "3.7.0")])

        def _impl(name: str, _version: str | None = None, **_kw: object):
            return pypi_attest.ProvenanceResult(
                name=name,
                status=pypi_attest.ProvenanceStatus.ATTESTED,
                version=_version,
            )

        with mock.patch("pypi_attest.check_provenance", side_effect=_impl):
            parts._verify_installed_attestations(venv, strict=True)
