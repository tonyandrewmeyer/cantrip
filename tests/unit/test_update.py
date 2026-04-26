"""Tests for the PyPI version-check and installer-detection helpers.

The tests cover three concerns:

- :func:`check_for_update` returns the right ``UpdateInfo`` (or
  ``None``) under newer / equal / older / broken-PyPI conditions,
  honours both opt-outs, and reads/writes the disk cache as
  expected.
- :func:`detect_install_method` classifies every ``sys.executable``
  shape we care about (uv tool, pipx, pip --user, generic venv,
  snap) and never crashes on weird paths.
- :func:`upgrade_command` returns a sensible string per method and
  ``None`` for ``UNKNOWN`` so callers can fall through to the PyPI
  URL.
"""

from __future__ import annotations

import json
import pathlib
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import cantrip
from cantrip import update

# ─────────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Point the cache directory at a tmp dir for the duration of the test."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv(update.CACHE_DIR_ENV, str(cache_dir))
    yield cache_dir


@pytest.fixture
def no_settings_optout(tmp_path, monkeypatch):
    """Make ``_settings_disabled`` look at an empty tmp file."""
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(update, "_SETTINGS_PATH", settings)
    yield settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Make sure the disable env var doesn't leak between tests."""
    monkeypatch.delenv(update.DISABLE_ENV, raising=False)
    yield


def _make_pypi_payload(
    latest: str,
    with_releases: bool = True,
    *,
    yanked_versions: tuple[str, ...] = (),
    extra_versions: tuple[str, ...] = (),
) -> dict:
    """Build a PyPI JSON payload mirroring the public schema.

    *yanked_versions* lists versions whose files should carry
    ``yanked: true`` — used to exercise the yanked-detection path.
    *extra_versions* adds additional release entries (file metadata
    only) so the ``releases`` map can include the installed version
    as well as ``latest``.
    """
    payload: dict = {"info": {"version": latest}}
    if with_releases:
        releases: dict[str, list[dict]] = {}
        for version in (latest, *extra_versions):
            releases[version] = [
                {
                    "upload_time_iso_8601": "2026-04-01T12:00:00.000000Z",
                    "upload_time": "2026-04-01T12:00:00",
                    "yanked": version in yanked_versions,
                }
            ]
        payload["releases"] = releases
    return payload


def _patch_httpx(payload: dict | None = None, *, side_effect: Exception | None = None):
    """Build a mock ``httpx.AsyncClient`` returning the same response per call.

    Use :func:`_patch_httpx_routed` when the test exercises both the
    PyPI fetch and the GitHub CHANGELOG fetch from a single
    ``check_for_update`` invocation.
    """
    body = json.dumps(payload or {}).encode()
    response = httpx.Response(
        status_code=200,
        content=body,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", update._PYPI_URL),
    )
    client = AsyncMock()
    if side_effect is not None:
        client.get = AsyncMock(side_effect=side_effect)
    else:
        client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch("cantrip.update.httpx.AsyncClient", return_value=client)


def _patch_httpx_routed(
    *,
    pypi_payload: dict | None = None,
    changelog_text: str | None = None,
    changelog_status: int = 200,
):
    """Build a mock ``httpx.AsyncClient`` that routes by URL substring.

    Requests whose URL contains ``"/pypi/"`` get the PyPI JSON;
    everything else (the GitHub raw URL) gets *changelog_text* with
    *changelog_status*.  Pass ``changelog_text=None`` and
    ``changelog_status=404`` to simulate the "tag doesn't exist
    yet" fallback.
    """

    pypi_body = json.dumps(pypi_payload or {}).encode()

    async def _get(url: str, *_args, **_kwargs):
        if "/pypi/" in url:
            return httpx.Response(
                status_code=200,
                content=pypi_body,
                headers={"content-type": "application/json"},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            status_code=changelog_status,
            content=(changelog_text or "").encode(),
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", url),
        )

    client = AsyncMock()
    client.get = AsyncMock(side_effect=_get)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch("cantrip.update.httpx.AsyncClient", return_value=client)


# ─────────────────────────────────────────────────────────────────
#  check_for_update
# ─────────────────────────────────────────────────────────────────


class TestCheckForUpdate:
    """End-to-end behaviour of :func:`update.check_for_update`."""

    @pytest.mark.asyncio
    async def test_newer_release_returns_update_info(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx(_make_pypi_payload("0.2.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.current == "0.1.0"
        assert info.latest == "0.2.0"
        assert info.pypi_url == "https://pypi.org/project/juju-cantrip/0.2.0/"
        assert info.release_timestamp == "2026-04-01T12:00:00.000000Z"

    @pytest.mark.asyncio
    async def test_equal_version_returns_none(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "1.0.0")
        with _patch_httpx(_make_pypi_payload("1.0.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_pypi_older_than_installed_returns_none(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # User on a pre-release ahead of the public latest — happens
        # for editable / development installs from a Git checkout.
        monkeypatch.setattr(cantrip, "__version__", "1.5.0")
        with _patch_httpx(_make_pypi_payload("1.0.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self, isolated_cache, no_settings_optout, monkeypatch):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx(side_effect=httpx.ConnectError("DNS")):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, isolated_cache, no_settings_optout, monkeypatch):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx(side_effect=httpx.TimeoutException("slow")):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_http_status_error_returns_none(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # 503 from PyPI shouldn't blow up the user's startup.
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        bad = httpx.Response(
            status_code=503,
            request=httpx.Request("GET", update._PYPI_URL),
        )
        client = AsyncMock()
        client.get = AsyncMock(return_value=bad)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("cantrip.update.httpx.AsyncClient", return_value=client):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        bad = httpx.Response(
            status_code=200,
            content=b"not json",
            request=httpx.Request("GET", update._PYPI_URL),
        )
        client = AsyncMock()
        client.get = AsyncMock(return_value=bad)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("cantrip.update.httpx.AsyncClient", return_value=client):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_missing_info_block_returns_none(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx({"unexpected": "shape"}):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_invalid_version_string_returns_none(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx({"info": {"version": "not-a-version"}}):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_pre_release_installed_compared_correctly(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # ``packaging`` orders ``1.0.0rc1 < 1.0.0`` so an rc user
        # should be nagged about the GA release.
        monkeypatch.setattr(cantrip, "__version__", "1.0.0rc1")
        with _patch_httpx(_make_pypi_payload("1.0.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.latest == "1.0.0"


# ─────────────────────────────────────────────────────────────────
#  Opt-outs
# ─────────────────────────────────────────────────────────────────


class TestOptOuts:
    """Both opt-outs short-circuit the check before any I/O."""

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    @pytest.mark.asyncio
    async def test_env_var_disables(
        self,
        value,
        isolated_cache,
        no_settings_optout,
        monkeypatch,
    ):
        monkeypatch.setenv(update.DISABLE_ENV, value)
        # If we reached httpx the patch would be required; the
        # bare absence proves the env var short-circuited first.
        info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
    @pytest.mark.asyncio
    async def test_falsy_env_var_does_not_disable(
        self,
        value,
        isolated_cache,
        no_settings_optout,
        monkeypatch,
    ):
        monkeypatch.setenv(update.DISABLE_ENV, value)
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx(_make_pypi_payload("0.2.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is not None  # network was actually consulted

    @pytest.mark.asyncio
    async def test_settings_file_disables(
        self,
        isolated_cache,
        no_settings_optout,
    ):
        no_settings_optout.write_text(
            json.dumps({"update_check_disabled": True}),
            encoding="utf-8",
        )
        info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_settings_file_false_does_not_disable(
        self,
        isolated_cache,
        no_settings_optout,
        monkeypatch,
    ):
        no_settings_optout.write_text(
            json.dumps({"update_check_disabled": False}),
            encoding="utf-8",
        )
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx(_make_pypi_payload("0.2.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is not None

    @pytest.mark.asyncio
    async def test_malformed_settings_does_not_disable(
        self,
        isolated_cache,
        no_settings_optout,
        monkeypatch,
    ):
        no_settings_optout.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx(_make_pypi_payload("0.2.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is not None  # malformed file should not silently disable

    def test_update_check_disabled_helper(self, no_settings_optout, monkeypatch):
        assert update.update_check_disabled() is False
        monkeypatch.setenv(update.DISABLE_ENV, "1")
        assert update.update_check_disabled() is True


# ─────────────────────────────────────────────────────────────────
#  Cache
# ─────────────────────────────────────────────────────────────────


class TestCache:
    """The disk cache hits, misses, and expires correctly."""

    @pytest.mark.asyncio
    async def test_fresh_cache_skips_network(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        # Seed the cache: latest = 0.2.0 means an update is available.
        update._write_cache("0.2.0", "2026-04-01T12:00:00.000000Z")
        # Patch httpx to assert it is *not* called.
        client = AsyncMock()
        with patch("cantrip.update.httpx.AsyncClient", return_value=client) as p:
            info = await update.check_for_update()
        assert info is not None
        assert info.latest == "0.2.0"
        assert info.release_timestamp == "2026-04-01T12:00:00.000000Z"
        p.assert_not_called()

    @pytest.mark.asyncio
    async def test_fresh_cache_returns_none_when_current(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # Cache says 0.1.0 is latest; user is also on 0.1.0 — no
        # nag, no network call.
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        update._write_cache("0.1.0", None)
        client = AsyncMock()
        with patch("cantrip.update.httpx.AsyncClient", return_value=client) as p:
            info = await update.check_for_update()
        assert info is None
        p.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_cache_falls_through_to_network(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        update._write_cache("0.2.0", None)
        # Backdate the cache file past the TTL.
        cache_file = update._cache_path()
        old = time.time() - update.DEFAULT_CACHE_TTL_SECONDS - 60
        import os

        os.utime(cache_file, (old, old))

        with _patch_httpx(_make_pypi_payload("0.3.0")):
            info = await update.check_for_update()
        assert info is not None
        assert info.latest == "0.3.0"  # network won; cache was ignored

    @pytest.mark.asyncio
    async def test_corrupt_cache_falls_through_to_network(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        cache_file = update._cache_path()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not json", encoding="utf-8")

        with _patch_httpx(_make_pypi_payload("0.2.0")):
            info = await update.check_for_update()
        assert info is not None

    @pytest.mark.asyncio
    async def test_use_cache_false_bypasses_cache(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        # Cache says 0.99.0 — fresh — but ``use_cache=False`` should
        # ignore it and consult the network instead.
        update._write_cache("0.99.0", None)
        with _patch_httpx(_make_pypi_payload("0.2.0")):
            info = await update.check_for_update(use_cache=False)
        # Network said 0.2.0 — and 0.2.0 > 0.1.0, so we get a
        # real UpdateInfo for 0.2.0 (not the cached 0.99.0).
        assert info is not None
        assert info.latest == "0.2.0"

    @pytest.mark.asyncio
    async def test_successful_check_writes_cache(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx(_make_pypi_payload("0.2.0")):
            await update.check_for_update(use_cache=False)
        cache_file = update._cache_path()
        assert cache_file.is_file()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data["latest"] == "0.2.0"
        assert data["release_timestamp"] == "2026-04-01T12:00:00.000000Z"


# ─────────────────────────────────────────────────────────────────
#  Installer detection
# ─────────────────────────────────────────────────────────────────


class TestDetectInstallMethod:
    """``sys.executable`` shape → InstallMethod heuristics."""

    @pytest.fixture(autouse=True)
    def fixed_home(self, monkeypatch, tmp_path):
        # Pin Path.home() so the ``~/.local/`` heuristics don't depend
        # on whoever runs the test suite.
        fake_home = tmp_path / "home" / "tester"
        fake_home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda _cls: fake_home))
        return fake_home

    @pytest.fixture
    def venv_off(self, monkeypatch):
        # System Python: sys.prefix == sys.base_prefix.
        monkeypatch.setattr("sys.prefix", "/usr")
        monkeypatch.setattr("sys.base_prefix", "/usr")

    def _set_executable(self, monkeypatch, path: str) -> None:
        monkeypatch.setattr("sys.executable", path)

    def test_uv_tool_detected(self, monkeypatch, fixed_home, venv_off):
        self._set_executable(
            monkeypatch,
            f"{fixed_home}/.local/share/uv/tools/cantrip/bin/python",
        )
        assert update.detect_install_method() == update.InstallMethod.UV_TOOL

    def test_system_uv_tool_detected(self, monkeypatch, venv_off):
        self._set_executable(monkeypatch, "/usr/share/uv/tools/cantrip/bin/python")
        assert update.detect_install_method() == update.InstallMethod.UV_TOOL

    def test_pipx_detected(self, monkeypatch, fixed_home, venv_off):
        self._set_executable(
            monkeypatch,
            f"{fixed_home}/.local/pipx/venvs/cantrip/bin/python",
        )
        assert update.detect_install_method() == update.InstallMethod.PIPX

    def test_pipx_share_layout_detected(self, monkeypatch, fixed_home, venv_off):
        self._set_executable(
            monkeypatch,
            f"{fixed_home}/.local/share/pipx/venvs/cantrip/bin/python",
        )
        assert update.detect_install_method() == update.InstallMethod.PIPX

    def test_snap_detected(self, monkeypatch, venv_off):
        self._set_executable(monkeypatch, "/snap/cantrip/current/bin/python")
        assert update.detect_install_method() == update.InstallMethod.SNAP

    def test_pip_user_detected(self, monkeypatch, fixed_home, venv_off):
        # ``pip install --user`` puts the launcher under ~/.local/bin/.
        self._set_executable(monkeypatch, f"{fixed_home}/.local/bin/python3")
        assert update.detect_install_method() == update.InstallMethod.PIP_USER

    def test_generic_venv_detected(self, monkeypatch, fixed_home):
        self._set_executable(monkeypatch, f"{fixed_home}/projects/myvenv/bin/python")
        # Venv: prefix differs from base_prefix.
        monkeypatch.setattr("sys.prefix", f"{fixed_home}/projects/myvenv")
        monkeypatch.setattr("sys.base_prefix", "/usr")
        assert update.detect_install_method() == update.InstallMethod.PIP_VENV

    def test_venv_under_local_share_is_venv_not_user(self, monkeypatch, fixed_home):
        # A venv created under ~/.local/share/ should be classified as
        # PIP_VENV, not PIP_USER — the venv signal wins.
        self._set_executable(
            monkeypatch,
            f"{fixed_home}/.local/share/myvenv/bin/python",
        )
        monkeypatch.setattr("sys.prefix", f"{fixed_home}/.local/share/myvenv")
        monkeypatch.setattr("sys.base_prefix", "/usr")
        assert update.detect_install_method() == update.InstallMethod.PIP_VENV

    def test_unknown_layout_returns_unknown(self, monkeypatch, venv_off):
        self._set_executable(monkeypatch, "/opt/wherever/python")
        assert update.detect_install_method() == update.InstallMethod.UNKNOWN

    def test_never_crashes_on_weird_paths(self, monkeypatch, venv_off):
        # Fuzz with a small grab-bag of weird strings — the helper
        # must always return *some* InstallMethod, not raise.
        weird_paths = [
            "",
            "/",
            "//",
            "relative/path/python",
            "/path/with spaces/python",
            "/path/with\nnewline/python",
            "/snap-but-not-quite/cantrip/python",
            "/usr/bin/python with extra junk",
            "/snap/cantrip/current/bin/python",  # genuine snap
            "/.local/share/uv/tools/cantrip/bin/python",  # leading dot
        ]
        for path in weird_paths:
            self._set_executable(monkeypatch, path)
            method = update.detect_install_method()
            assert isinstance(method, update.InstallMethod), f"path: {path!r}"


# ─────────────────────────────────────────────────────────────────
#  Upgrade command
# ─────────────────────────────────────────────────────────────────


class TestUpgradeCommand:
    """Each method maps to a copy-pasteable upgrade command, except UNKNOWN."""

    @pytest.mark.parametrize(
        "method,expected",
        [
            (update.InstallMethod.UV_TOOL, "uv tool upgrade juju-cantrip"),
            (update.InstallMethod.PIPX, "pipx upgrade juju-cantrip"),
            (update.InstallMethod.PIP_USER, "uv pip install --user --upgrade juju-cantrip"),
            (update.InstallMethod.PIP_VENV, "uv pip install --upgrade juju-cantrip"),
            (update.InstallMethod.SNAP, "snap refresh cantrip"),
        ],
    )
    def test_known_methods_map_to_commands(self, method, expected):
        assert update.upgrade_command(method) == expected

    def test_unknown_returns_none(self):
        assert update.upgrade_command(update.InstallMethod.UNKNOWN) is None

    def test_default_uses_detected_method(self, monkeypatch):
        # Confirm the default-arg path consults detect_install_method.
        monkeypatch.setattr(
            update,
            "detect_install_method",
            lambda: update.InstallMethod.PIPX,
        )
        assert update.upgrade_command() == "pipx upgrade juju-cantrip"


# ─────────────────────────────────────────────────────────────────
#  Changelog parsing
# ─────────────────────────────────────────────────────────────────


_SAMPLE_CHANGELOG = """\
# Changelog

All notable changes ...

## Unreleased

### Documentation
- Stuff that hasn't shipped.

## 0.3.0 — 2026-04-01

### Added
- New feature C.

### Fixed
- Bug C.

## 0.2.0 (2026-03-15)

### Added
- New feature B.

## 0.1.5

### Fixed
- Tiny fix.

## 0.1.0

### Added
- Initial release.
"""


class TestExtractReleaseNotes:
    """``extract_release_notes`` walks ``## <version>`` headings correctly."""

    def test_collects_sections_strictly_between_current_and_latest(self):
        sections = update.extract_release_notes(
            _SAMPLE_CHANGELOG,
            current="0.1.5",
            latest="0.3.0",
        )
        versions = [v for v, _ in sections]
        # Exclusive of current, inclusive of latest: 0.2.0 and 0.3.0.
        assert versions == ["0.3.0", "0.2.0"]

    def test_skips_unreleased_section(self):
        sections = update.extract_release_notes(
            _SAMPLE_CHANGELOG,
            current="0.1.0",
            latest="0.3.0",
        )
        versions = [v for v, _ in sections]
        assert "Unreleased" not in versions
        assert versions == ["0.3.0", "0.2.0", "0.1.5"]

    def test_returns_newest_first(self):
        sections = update.extract_release_notes(
            _SAMPLE_CHANGELOG,
            current="0.1.0",
            latest="0.3.0",
        )
        versions = [v for v, _ in sections]
        # The CHANGELOG already lists newest first; the helper must
        # not reverse it on the way out.
        assert versions == sorted(versions, reverse=True)

    def test_section_body_includes_subsection_headings(self):
        sections = update.extract_release_notes(
            _SAMPLE_CHANGELOG,
            current="0.2.0",
            latest="0.3.0",
        )
        assert len(sections) == 1
        version, body = sections[0]
        assert version == "0.3.0"
        # ``### Added`` and ``### Fixed`` are section bodies, not
        # new section starts — they should land in the body.
        assert "### Added" in body
        assert "### Fixed" in body
        assert "New feature C." in body
        # The next ``## 0.2.0`` heading must NOT bleed into 0.3.0's body.
        assert "0.2.0" not in body

    def test_empty_when_current_equals_latest(self):
        assert (
            update.extract_release_notes(
                _SAMPLE_CHANGELOG,
                current="0.3.0",
                latest="0.3.0",
            )
            == []
        )

    def test_empty_when_current_above_latest(self):
        assert (
            update.extract_release_notes(
                _SAMPLE_CHANGELOG,
                current="0.99.0",
                latest="0.3.0",
            )
            == []
        )

    def test_invalid_versions_return_empty(self):
        assert (
            update.extract_release_notes(
                _SAMPLE_CHANGELOG,
                current="not-a-version",
                latest="0.3.0",
            )
            == []
        )

    def test_v_prefixed_headings_are_recognised(self):
        markdown = "## v1.0.0\n\n- First.\n\n## v0.9.0\n\n- Older.\n"
        sections = update.extract_release_notes(
            markdown,
            current="0.9.0",
            latest="1.0.0",
        )
        assert [v for v, _ in sections] == ["1.0.0"]

    def test_unparseable_heading_starts_a_skip_window(self):
        # ``## Unreleased`` body must not bleed into the previous
        # version's body even if the file is unconventional.
        markdown = "## 1.0.0\n\n- Done.\n\n## Unreleased\n\n- Nope.\n\n## 0.9.0\n\n- Old.\n"
        sections = update.extract_release_notes(
            markdown,
            current="0.9.0",
            latest="1.0.0",
        )
        assert [v for v, _ in sections] == ["1.0.0"]
        body = sections[0][1]
        assert "Done." in body
        assert "Nope." not in body  # Unreleased was skipped
        assert "Old." not in body  # 0.9.0 wasn't in range


# ─────────────────────────────────────────────────────────────────
#  Changelog fetch
# ─────────────────────────────────────────────────────────────────


class TestFetchChangelog:
    """``fetch_changelog`` is gracious when the tag doesn't exist."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_text(self):
        with _patch_httpx_routed(changelog_text=_SAMPLE_CHANGELOG):
            text = await update.fetch_changelog("0.3.0")
        assert text == _SAMPLE_CHANGELOG

    @pytest.mark.asyncio
    async def test_missing_tag_returns_none(self):
        with _patch_httpx_routed(changelog_text=None, changelog_status=404):
            text = await update.fetch_changelog("99.0.0")
        assert text is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        # Reuse _patch_httpx (not routed) and force a connect error.
        with _patch_httpx(side_effect=httpx.ConnectError("DNS")):
            text = await update.fetch_changelog("0.3.0")
        assert text is None

    @pytest.mark.asyncio
    async def test_repo_slug_env_override(self, monkeypatch):
        captured: list[str] = []

        async def _capture(url: str, *_args, **_kwargs):
            captured.append(url)
            return httpx.Response(
                status_code=200,
                content=b"# Hi",
                request=httpx.Request("GET", url),
            )

        client = AsyncMock()
        client.get = AsyncMock(side_effect=_capture)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setenv(update.REPO_SLUG_ENV, "alt-owner/alt-repo")
        with patch("cantrip.update.httpx.AsyncClient", return_value=client):
            await update.fetch_changelog("1.2.3")
        assert captured
        assert "alt-owner/alt-repo" in captured[0]
        assert "v1.2.3" in captured[0]


# ─────────────────────────────────────────────────────────────────
#  check_for_update — integration with notes + filters
# ─────────────────────────────────────────────────────────────────


class TestCheckForUpdateWithNotes:
    """The end-to-end happy path includes release notes when available."""

    @pytest.mark.asyncio
    async def test_release_notes_attached_to_update_info(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.5")
        with _patch_httpx_routed(
            pypi_payload=_make_pypi_payload("0.3.0"),
            changelog_text=_SAMPLE_CHANGELOG,
        ):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.release_notes_markdown is not None
        # Notes for 0.2.0 and 0.3.0; not 0.1.5 itself or earlier.
        assert "## 0.3.0" in info.release_notes_markdown
        assert "## 0.2.0" in info.release_notes_markdown
        assert "## 0.1.0" not in info.release_notes_markdown

    @pytest.mark.asyncio
    async def test_changelog_404_leaves_notes_none(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # A pre-release that landed on main but wasn't tagged: PyPI
        # has the version but GitHub raw 404s.  The user still gets
        # the version notice; just no inline notes.
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        with _patch_httpx_routed(
            pypi_payload=_make_pypi_payload("0.2.0"),
            changelog_text=None,
            changelog_status=404,
        ):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.latest == "0.2.0"
        assert info.release_notes_markdown is None

    @pytest.mark.asyncio
    async def test_include_release_notes_false_skips_changelog_fetch(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # When ``include_release_notes=False``, only the PyPI fetch
        # should happen.  Assert by counting client.get calls.
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        captured_urls: list[str] = []

        async def _route(url: str, *_args, **_kwargs):
            captured_urls.append(url)
            return httpx.Response(
                status_code=200,
                content=json.dumps(_make_pypi_payload("0.2.0")).encode(),
                request=httpx.Request("GET", url),
            )

        client = AsyncMock()
        client.get = AsyncMock(side_effect=_route)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("cantrip.update.httpx.AsyncClient", return_value=client):
            info = await update.check_for_update(use_cache=False, include_release_notes=False)
        assert info is not None
        assert info.release_notes_markdown is None
        # Only one HTTP call — the PyPI fetch — went out.
        assert len(captured_urls) == 1
        assert "/pypi/" in captured_urls[0]

    @pytest.mark.asyncio
    async def test_cache_round_trips_release_notes(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.5")
        with _patch_httpx_routed(
            pypi_payload=_make_pypi_payload("0.3.0"),
            changelog_text=_SAMPLE_CHANGELOG,
        ):
            first = await update.check_for_update(use_cache=False)
        assert first is not None
        first_notes = first.release_notes_markdown
        assert first_notes is not None

        # Second call uses the cache; no network at all.
        client = AsyncMock()
        with patch("cantrip.update.httpx.AsyncClient", return_value=client) as p:
            second = await update.check_for_update()
        p.assert_not_called()
        assert second is not None
        assert second.release_notes_markdown == first_notes


# ─────────────────────────────────────────────────────────────────
#  Pre-release filter (63.6)
# ─────────────────────────────────────────────────────────────────


class TestPrereleaseFilter:
    """Stable users aren't nagged about pre-releases."""

    @pytest.mark.asyncio
    async def test_stable_user_not_nagged_about_prerelease(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "1.0.0")
        with _patch_httpx_routed(pypi_payload=_make_pypi_payload("1.1.0rc1")):
            info = await update.check_for_update(use_cache=False)
        assert info is None

    @pytest.mark.asyncio
    async def test_prerelease_user_sees_other_prereleases(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # A user who installed 1.1.0rc1 has opted into the bleeding
        # edge — they should see 1.1.0rc2.
        monkeypatch.setattr(cantrip, "__version__", "1.1.0rc1")
        with _patch_httpx_routed(pypi_payload=_make_pypi_payload("1.1.0rc2")):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.latest == "1.1.0rc2"

    @pytest.mark.asyncio
    async def test_prerelease_user_sees_stable_release(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # The reverse case: 1.0.0rc1 → 1.0.0 GA always wins.  Already
        # covered indirectly by an earlier test, asserted explicitly
        # here so the filter logic is documented end-to-end.
        monkeypatch.setattr(cantrip, "__version__", "1.0.0rc1")
        with _patch_httpx_routed(pypi_payload=_make_pypi_payload("1.0.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.latest == "1.0.0"


# ─────────────────────────────────────────────────────────────────
#  Yanked detection (63.6)
# ─────────────────────────────────────────────────────────────────


class TestYankedDetection:
    """``UpdateInfo.installed_yanked`` reflects the PyPI ``yanked`` flag."""

    @pytest.mark.asyncio
    async def test_yanked_installed_flagged(self, isolated_cache, no_settings_optout, monkeypatch):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        payload = _make_pypi_payload(
            "0.2.0",
            yanked_versions=("0.1.0",),
            extra_versions=("0.1.0",),
        )
        with _patch_httpx_routed(pypi_payload=payload):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.installed_yanked is True

    @pytest.mark.asyncio
    async def test_unyanked_installed_not_flagged(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        monkeypatch.setattr(cantrip, "__version__", "0.1.0")
        payload = _make_pypi_payload("0.2.0", extra_versions=("0.1.0",))
        with _patch_httpx_routed(pypi_payload=payload):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.installed_yanked is False

    @pytest.mark.asyncio
    async def test_installed_version_not_in_releases_means_not_yanked(
        self, isolated_cache, no_settings_optout, monkeypatch
    ):
        # Dev install or a release predating PyPI's yank metadata —
        # ``releases`` doesn't list the installed version at all.
        monkeypatch.setattr(cantrip, "__version__", "0.0.1.dev0")
        with _patch_httpx_routed(pypi_payload=_make_pypi_payload("0.2.0")):
            info = await update.check_for_update(use_cache=False)
        assert info is not None
        assert info.installed_yanked is False

    def test_yanked_helper_handles_malformed_payload(self):
        assert update._is_version_yanked("not a dict", "0.1.0") is False
        assert update._is_version_yanked({"releases": "not a dict"}, "0.1.0") is False
        assert update._is_version_yanked({"releases": {"0.1.0": "not a list"}}, "0.1.0") is False
        assert update._is_version_yanked({"releases": {}}, "0.1.0") is False


# ─────────────────────────────────────────────────────────────────
#  CLI notice formatting
# ─────────────────────────────────────────────────────────────────


class TestFormatCliNotice:
    """``format_cli_notice`` produces the two-line post-REPL notice."""

    def _info(self, **overrides) -> update.UpdateInfo:
        defaults = {
            "current": "0.1.0",
            "latest": "0.2.0",
            "pypi_url": "https://pypi.org/project/juju-cantrip/0.2.0/",
            "release_timestamp": None,
        }
        defaults.update(overrides)
        return update.UpdateInfo(**defaults)

    def test_known_installer_shows_command(self):
        notice = update.format_cli_notice(self._info(), method=update.InstallMethod.UV_TOOL)
        assert "0.2.0" in notice
        assert "0.1.0" in notice
        assert "https://pypi.org/project/juju-cantrip/0.2.0/" in notice
        assert "uv tool upgrade juju-cantrip" in notice
        # Two lines — keeps piped stdout short and predictable.
        assert notice.count("\n") == 1

    def test_unknown_installer_falls_back_to_url(self):
        notice = update.format_cli_notice(self._info(), method=update.InstallMethod.UNKNOWN)
        assert "usual installer" in notice
        assert "uv tool upgrade" not in notice
        assert "https://pypi.org/project/juju-cantrip/0.2.0/" in notice

    def test_yanked_install_changes_headline(self):
        notice = update.format_cli_notice(
            self._info(installed_yanked=True),
            method=update.InstallMethod.PIPX,
        )
        assert "yanked" in notice
        assert "pipx upgrade juju-cantrip" in notice

    def test_default_method_detects(self, monkeypatch):
        monkeypatch.setattr(update, "detect_install_method", lambda: update.InstallMethod.PIPX)
        notice = update.format_cli_notice(self._info())
        assert "pipx upgrade juju-cantrip" in notice


class TestFormatSlashNotice:
    """``format_slash_notice`` renders the ``/update`` chat response."""

    def _info(self, **overrides) -> update.UpdateInfo:
        defaults = {
            "current": "0.1.0",
            "latest": "0.2.0",
            "pypi_url": "https://pypi.org/project/juju-cantrip/0.2.0/",
            "release_timestamp": None,
        }
        defaults.update(overrides)
        return update.UpdateInfo(**defaults)

    def test_renders_markdown_link_and_fenced_command(self):
        notice = update.format_slash_notice(self._info(), method=update.InstallMethod.UV_TOOL)
        assert "<https://pypi.org/project/juju-cantrip/0.2.0/>" in notice
        assert "`uv tool upgrade juju-cantrip`" in notice
        # Restart reminder is load-bearing — the running process still
        # executes the old code after the user upgrades.
        assert "restart" in notice.lower()

    def test_unknown_installer_fallback(self):
        notice = update.format_slash_notice(self._info(), method=update.InstallMethod.UNKNOWN)
        assert "your usual installer" in notice
        assert "uv tool upgrade" not in notice


class TestSetUpdateCheckDisabled:
    """``set_update_check_disabled`` round-trips the toggle into settings.json."""

    def test_writes_new_file(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        monkeypatch.setattr(update, "_SETTINGS_PATH", path)
        written = update.set_update_check_disabled(True)
        assert written == path
        assert json.loads(path.read_text())["update_check_disabled"] is True

    def test_preserves_existing_keys(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"other": "keep", "update_check_disabled": False}))
        monkeypatch.setattr(update, "_SETTINGS_PATH", path)
        update.set_update_check_disabled(True)
        data = json.loads(path.read_text())
        assert data["update_check_disabled"] is True
        assert data["other"] == "keep"

    def test_replaces_malformed_file(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text("not json")
        monkeypatch.setattr(update, "_SETTINGS_PATH", path)
        update.set_update_check_disabled(False)
        assert json.loads(path.read_text()) == {"update_check_disabled": False}

    def test_round_trip_with_update_check_disabled(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        monkeypatch.setattr(update, "_SETTINGS_PATH", path)
        monkeypatch.delenv(update.DISABLE_ENV, raising=False)

        update.set_update_check_disabled(True)
        assert update.update_check_disabled() is True
        update.set_update_check_disabled(False)
        assert update.update_check_disabled() is False

    def test_atomic_write_preserves_old_file_on_failure(self, tmp_path, monkeypatch):
        """A write that fails mid-flight must leave the original file intact.

        With a non-atomic ``path.write_text``, an interrupted call would
        truncate-and-fail, losing any unrelated keys the user had set.
        The tmp+rename pattern keeps the original until the new file is
        complete on disk.
        """
        path = tmp_path / "settings.json"
        original = {"other": "preserved", "update_check_disabled": False}
        path.write_text(json.dumps(original))
        monkeypatch.setattr(update, "_SETTINGS_PATH", path)

        # Force ``Path.replace`` to fail so the rename never lands.
        def _boom(_self, _target):
            raise OSError("simulated rename failure")

        monkeypatch.setattr(pathlib.Path, "replace", _boom)
        import contextlib

        with contextlib.suppress(OSError):
            update.set_update_check_disabled(True)
        # Original content survives — atomic semantics held.
        assert json.loads(path.read_text()) == original
