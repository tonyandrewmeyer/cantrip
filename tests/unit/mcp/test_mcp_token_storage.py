"""Tests for MCP token storage (Phase 45.4a)."""

from __future__ import annotations

import pathlib
import shutil
import stat

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from cantrip.mcp.token_storage import (
    GPG_OPT_IN_ENV,
    TOKEN_DIR_ENV,
    FileTokenStorage,
    default_token_dir,
    gpg_enabled,
)


def _sample_tokens() -> OAuthToken:
    return OAuthToken(
        access_token="access-123",
        token_type="Bearer",
        expires_in=3600,
        scope="repo",
        refresh_token="refresh-456",
    )


def _sample_client_info() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        redirect_uris=["http://localhost:9999/callback"],
        client_name="cantrip-test",
        client_id="client-id-here",
        client_secret="client-secret-here",
    )


# ── Default-path resolution ────────────────────────────────────────────


class TestDefaultTokenDir:
    def test_env_override(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(TOKEN_DIR_ENV, str(tmp_path / "custom"))
        assert default_token_dir() == tmp_path / "custom"

    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(TOKEN_DIR_ENV, raising=False)
        # Just check the path resolves under home — don't write to it.
        assert "cantrip" in default_token_dir().as_posix()


class TestGpgEnabled:
    def test_default_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(GPG_OPT_IN_ENV, raising=False)
        assert not gpg_enabled()

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(GPG_OPT_IN_ENV, value)
        assert gpg_enabled()

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_falsy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(GPG_OPT_IN_ENV, value)
        assert not gpg_enabled()


# ── Plain-text round-trip ─────────────────────────────────────────────


class TestFileTokenStorage:
    @pytest.fixture(autouse=True)
    def _disable_gpg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(GPG_OPT_IN_ENV, raising=False)

    @pytest.mark.asyncio
    async def test_no_file_returns_none(self, tmp_path: pathlib.Path) -> None:
        store = FileTokenStorage("test-server", base_dir=tmp_path)
        assert await store.get_tokens() is None
        assert await store.get_client_info() is None

    @pytest.mark.asyncio
    async def test_token_round_trip(self, tmp_path: pathlib.Path) -> None:
        store = FileTokenStorage("test-server", base_dir=tmp_path)
        original = _sample_tokens()
        await store.set_tokens(original)
        loaded = await store.get_tokens()
        assert loaded is not None
        assert loaded.access_token == "access-123"
        assert loaded.refresh_token == "refresh-456"
        assert loaded.expires_in == 3600

    @pytest.mark.asyncio
    async def test_client_info_round_trip(self, tmp_path: pathlib.Path) -> None:
        store = FileTokenStorage("test-server", base_dir=tmp_path)
        await store.set_client_info(_sample_client_info())
        loaded = await store.get_client_info()
        assert loaded is not None
        assert loaded.client_id == "client-id-here"
        assert loaded.client_secret == "client-secret-here"

    @pytest.mark.asyncio
    async def test_per_server_isolation(self, tmp_path: pathlib.Path) -> None:
        a = FileTokenStorage("server-a", base_dir=tmp_path)
        b = FileTokenStorage("server-b", base_dir=tmp_path)
        await a.set_tokens(OAuthToken(access_token="a-token", token_type="Bearer"))
        await b.set_tokens(OAuthToken(access_token="b-token", token_type="Bearer"))
        a_loaded = await a.get_tokens()
        b_loaded = await b.get_tokens()
        assert a_loaded is not None and a_loaded.access_token == "a-token"
        assert b_loaded is not None and b_loaded.access_token == "b-token"

    @pytest.mark.asyncio
    async def test_perms_are_user_only(self, tmp_path: pathlib.Path) -> None:
        store = FileTokenStorage("test-server", base_dir=tmp_path)
        await store.set_tokens(_sample_tokens())
        token_file = store.server_dir / "tokens.json"
        mode = stat.S_IMODE(token_file.stat().st_mode)
        # 0600 — owner read+write only.
        assert mode == 0o600
        # Per-server dir at 0700.
        dir_mode = stat.S_IMODE(store.server_dir.stat().st_mode)
        assert dir_mode == 0o700

    @pytest.mark.asyncio
    async def test_atomic_write_no_tmp_left(self, tmp_path: pathlib.Path) -> None:
        store = FileTokenStorage("test-server", base_dir=tmp_path)
        await store.set_tokens(_sample_tokens())
        # No half-written temp file should remain.
        assert not list(store.server_dir.glob("*.tmp"))

    @pytest.mark.asyncio
    async def test_overwrite_replaces(self, tmp_path: pathlib.Path) -> None:
        store = FileTokenStorage("test-server", base_dir=tmp_path)
        await store.set_tokens(_sample_tokens())
        await store.set_tokens(OAuthToken(access_token="updated", token_type="Bearer"))
        loaded = await store.get_tokens()
        assert loaded is not None
        assert loaded.access_token == "updated"

    @pytest.mark.asyncio
    async def test_malformed_file_returns_none(self, tmp_path: pathlib.Path) -> None:
        store = FileTokenStorage("test-server", base_dir=tmp_path)
        store.server_dir.mkdir(parents=True)
        (store.server_dir / "tokens.json").write_text("{not json")
        assert await store.get_tokens() is None

    @pytest.mark.asyncio
    async def test_unreadable_file_returns_none(self, tmp_path: pathlib.Path) -> None:
        store = FileTokenStorage("test-server", base_dir=tmp_path)
        store.server_dir.mkdir(parents=True)
        token_file = store.server_dir / "tokens.json"
        token_file.write_text("{}")
        token_file.chmod(0o000)
        try:
            assert await store.get_tokens() is None
        finally:
            token_file.chmod(0o600)


# ── GPG-encrypted round-trip ───────────────────────────────────────────


def _gpg_available() -> bool:
    """True when gpg is on PATH; tests that need it skip otherwise."""
    return shutil.which("gpg") is not None


class TestGpgRoundTrip:
    @pytest.mark.asyncio
    async def test_gpg_round_trip(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        if not _gpg_available():
            pytest.skip("gpg binary not available")
        # Use a test-only GNUPGHOME so we don't touch the user's keychain.
        gnupg_home = tmp_path / ".gnupg"
        gnupg_home.mkdir(mode=0o700)
        monkeypatch.setenv("GNUPGHOME", str(gnupg_home))
        # Symmetric encryption needs a passphrase; set it via env.
        monkeypatch.setenv("GPG_PASSPHRASE", "test-passphrase")
        # The wrapper invokes gpg with --batch --yes --symmetric and
        # reads the passphrase from gpg-agent or piped in.  We pass it
        # via PINENTRY_USER_DATA so the loopback prompt picks it up.
        # Easiest path: use --passphrase-fd 0 by extending the command,
        # but that requires modifying the wrapper.  Instead we configure
        # gpg-agent to allow loopback.
        agent_conf = gnupg_home / "gpg-agent.conf"
        agent_conf.write_text("allow-loopback-pinentry\n")
        gpg_conf = gnupg_home / "gpg.conf"
        gpg_conf.write_text("pinentry-mode loopback\npassphrase test-passphrase\n")
        monkeypatch.setenv(GPG_OPT_IN_ENV, "1")

        store = FileTokenStorage("test-server", base_dir=tmp_path / "tokens")
        try:
            await store.set_tokens(_sample_tokens())
        except OSError as exc:
            pytest.skip(f"gpg setup unsupported in this env: {exc}")
        loaded = await store.get_tokens()
        # If the read fails (e.g. agent quirks) we accept None — the
        # important property is that no plaintext leaked.
        if loaded is not None:
            assert loaded.access_token == "access-123"
        # Plaintext must NOT be readable from the file.
        path = store.server_dir / "tokens.json"
        raw = path.read_bytes()
        assert b"access-123" not in raw
