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


def _make_pypi_payload(latest: str, with_releases: bool = True) -> dict:
    """Build a PyPI JSON payload mirroring the public schema."""
    payload: dict = {"info": {"version": latest}}
    if with_releases:
        payload["releases"] = {
            latest: [
                {
                    "upload_time_iso_8601": "2026-04-01T12:00:00.000000Z",
                    "upload_time": "2026-04-01T12:00:00",
                }
            ]
        }
    return payload


def _patch_httpx(payload: dict | None = None, *, side_effect: Exception | None = None):
    """Build a mock ``httpx.AsyncClient`` context manager."""
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
        assert info.pypi_url == "https://pypi.org/project/cantrip/0.2.0/"
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
            (update.InstallMethod.UV_TOOL, "uv tool upgrade cantrip"),
            (update.InstallMethod.PIPX, "pipx upgrade cantrip"),
            (update.InstallMethod.PIP_USER, "pip install --user --upgrade cantrip"),
            (update.InstallMethod.PIP_VENV, "pip install --upgrade cantrip"),
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
        assert update.upgrade_command() == "pipx upgrade cantrip"
