"""Tests for the MCP OAuth flow handlers + config (Phase 45.4b)."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import aiohttp
import pytest

from cantrip.mcp import MCPConfigError, OAuthConfig, ServerConfig, load_configs
from cantrip.mcp.client import MCPClient
from cantrip.mcp.config import _parse_yaml
from cantrip.mcp.oauth import (
    CALLBACK_PATH,
    DEFAULT_OAUTH_TIMEOUT,
    build_client_metadata,
    make_callback_handler,
    make_redirect_handler,
    make_redirect_uri,
    wait_for_localhost_callback,
)
from cantrip.mcp.types import TransportKind


def _free_port() -> int:
    """Pick a free port on the loopback interface for the callback test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_yaml(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ── OAuthConfig parsing ────────────────────────────────────────────────


class TestOAuthConfigParsing:
    def test_minimal(self, tmp_path: Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            """
servers:
  s:
    transport: http
    url: https://example.com/mcp
    oauth: {}
""",
        )
        cfg = _parse_yaml(f)[0]
        assert cfg.oauth is not None
        assert cfg.oauth.client_name == "cantrip"
        assert cfg.oauth.scopes == []
        assert cfg.oauth.redirect_port == 9876
        assert cfg.oauth.client_metadata_url is None

    def test_full(self, tmp_path: Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            """
servers:
  s:
    transport: http
    url: https://example.com/mcp
    oauth:
      client_name: cantrip-prod
      scopes: ["repo", "user"]
      redirect_port: 9999
      client_metadata_url: https://example.com/metadata.json
""",
        )
        cfg = _parse_yaml(f)[0]
        assert cfg.oauth is not None
        assert cfg.oauth.client_name == "cantrip-prod"
        assert cfg.oauth.scopes == ["repo", "user"]
        assert cfg.oauth.redirect_port == 9999
        assert cfg.oauth.client_metadata_url == "https://example.com/metadata.json"

    def test_oauth_must_be_mapping(self, tmp_path: Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            "servers:\n  s:\n    transport: http\n    url: https://x\n    oauth: nope\n",
        )
        with pytest.raises(MCPConfigError, match="must be a mapping"):
            _parse_yaml(f)

    def test_client_name_must_be_non_empty(self, tmp_path: Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            """
servers:
  s:
    transport: http
    url: https://example.com/mcp
    oauth:
      client_name: ""
""",
        )
        with pytest.raises(MCPConfigError, match="non-empty"):
            _parse_yaml(f)

    def test_redirect_port_must_be_int(self, tmp_path: Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            """
servers:
  s:
    transport: http
    url: https://x
    oauth:
      redirect_port: "9999"
""",
        )
        with pytest.raises(MCPConfigError, match="must be an integer"):
            _parse_yaml(f)

    def test_redirect_port_out_of_range(self, tmp_path: Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            """
servers:
  s:
    transport: http
    url: https://x
    oauth:
      redirect_port: 99999
""",
        )
        with pytest.raises(MCPConfigError, match="between 1 and 65535"):
            _parse_yaml(f)

    def test_oauth_rejected_for_stdio(self, tmp_path: Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            "servers:\n  s:\n    command: x\n    oauth: {}\n",
        )
        with pytest.raises(MCPConfigError, match="only valid for the http transport"):
            _parse_yaml(f)

    def test_load_configs_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(tmp_path / "missing.yaml"))
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_yaml(
            repo / "cantrip.mcp.yaml",
            """
servers:
  prod:
    transport: http
    url: https://example.com/mcp
    oauth:
      client_name: x
      scopes: [a, b]
""",
        )
        cfgs = load_configs(repo_root=repo)
        assert len(cfgs) == 1
        assert cfgs[0].oauth is not None
        assert cfgs[0].oauth.scopes == ["a", "b"]


# ── OAuth handler helpers ─────────────────────────────────────────────


class TestRedirectUri:
    def test_format(self) -> None:
        assert make_redirect_uri(9876) == "http://127.0.0.1:9876/callback"


class TestRedirectHandler:
    @pytest.mark.asyncio
    async def test_invokes_webbrowser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        opened: list[str] = []

        def _fake_open(url: str, new: int = 0, autoraise: bool = False) -> bool:  # noqa: ARG001
            opened.append(url)
            return True

        monkeypatch.setattr("cantrip.mcp.oauth.webbrowser.open", _fake_open)
        handler = make_redirect_handler()
        await handler("https://example.com/authorize?x=1")
        assert opened == ["https://example.com/authorize?x=1"]

    @pytest.mark.asyncio
    async def test_logs_when_browser_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _fake_open(url: str, new: int = 0, autoraise: bool = False) -> bool:  # noqa: ARG001
            return False

        monkeypatch.setattr("cantrip.mcp.oauth.webbrowser.open", _fake_open)
        handler = make_redirect_handler()
        with caplog.at_level("WARNING"):
            await handler("https://example.com/authorize")
        assert any("Could not open a browser" in r.message for r in caplog.records)


# ── Localhost callback listener ───────────────────────────────────────


async def _post_callback(
    port: int,
    *,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> None:
    """Make the loopback HTTP request the SDK would make on the redirect."""
    params: dict[str, str] = {}
    if code is not None:
        params["code"] = code
    if state is not None:
        params["state"] = state
    if error is not None:
        params["error"] = error
    url = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
    async with aiohttp.ClientSession() as session, session.get(url, params=params) as resp:
        await resp.text()


class TestLocalhostCallback:
    @pytest.mark.asyncio
    async def test_round_trip_returns_code_and_state(self) -> None:
        port = _free_port()

        async def _trigger() -> None:
            await asyncio.sleep(0.05)
            await _post_callback(port, code="auth-code-123", state="abc")

        trigger = asyncio.create_task(_trigger())
        code, state = await wait_for_localhost_callback(port, timeout=5.0)
        await trigger
        assert code == "auth-code-123"
        assert state == "abc"

    @pytest.mark.asyncio
    async def test_round_trip_without_state(self) -> None:
        port = _free_port()

        async def _trigger() -> None:
            await asyncio.sleep(0.05)
            await _post_callback(port, code="just-the-code")

        trigger = asyncio.create_task(_trigger())
        code, state = await wait_for_localhost_callback(port, timeout=5.0)
        await trigger
        assert code == "just-the-code"
        assert state is None

    @pytest.mark.asyncio
    async def test_oauth_error_response_raises(self) -> None:
        port = _free_port()

        async def _trigger() -> None:
            await asyncio.sleep(0.05)
            await _post_callback(port, error="access_denied")

        trigger = asyncio.create_task(_trigger())
        with pytest.raises(OSError, match="OAuth error: access_denied"):
            await wait_for_localhost_callback(port, timeout=5.0)
        await trigger

    @pytest.mark.asyncio
    async def test_missing_code_raises(self) -> None:
        port = _free_port()

        async def _trigger() -> None:
            await asyncio.sleep(0.05)
            await _post_callback(port)  # No code, no error.

        trigger = asyncio.create_task(_trigger())
        with pytest.raises(OSError, match="missing `code`"):
            await wait_for_localhost_callback(port, timeout=5.0)
        await trigger

    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        port = _free_port()
        with pytest.raises(TimeoutError):
            await wait_for_localhost_callback(port, timeout=0.1)

    @pytest.mark.asyncio
    async def test_port_already_in_use_raises(self) -> None:
        # Bind a socket to a port; the listener should refuse to start.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            with pytest.raises(OSError, match="could not bind"):
                await wait_for_localhost_callback(port, timeout=2.0)
        finally:
            sock.close()


class TestCallbackHandlerFactory:
    """The handler factory wraps wait_for_localhost_callback."""

    @pytest.mark.asyncio
    async def test_factory_returns_async_callable(self) -> None:
        handler = make_callback_handler(_free_port(), timeout=0.1)
        # Awaiting it without anyone hitting the URL times out cleanly.
        with pytest.raises(TimeoutError):
            await handler()

    def test_default_timeout_constant(self) -> None:
        assert DEFAULT_OAUTH_TIMEOUT >= 60


# ── Client metadata builder ───────────────────────────────────────────


class TestBuildClientMetadata:
    def test_minimal(self) -> None:
        from mcp.shared.auth import OAuthClientMetadata

        cfg = OAuthConfig(client_name="cantrip-test", redirect_port=9876)
        meta = build_client_metadata(cfg)
        assert isinstance(meta, OAuthClientMetadata)
        assert meta.client_name == "cantrip-test"
        # The SDK coerces redirect URIs to ``pydantic.AnyUrl``; compare
        # by string so the test isn't sensitive to that internal type.
        assert [str(u) for u in meta.redirect_uris] == ["http://127.0.0.1:9876/callback"]

    def test_with_scopes(self) -> None:
        cfg = OAuthConfig(client_name="x", scopes=["read", "write"], redirect_port=8000)
        meta = build_client_metadata(cfg)
        assert meta.scope == "read write"

    def test_no_scopes_means_none(self) -> None:
        cfg = OAuthConfig(client_name="x", redirect_port=8000)
        meta = build_client_metadata(cfg)
        assert meta.scope is None


# ── MCPClient OAuth wiring ────────────────────────────────────────────


class TestMCPClientOAuthWiring:
    def test_no_oauth_returns_none(self, tmp_path: Path) -> None:
        cfg = ServerConfig(
            name="s",
            transport=TransportKind.HTTP,
            url="https://example.com/mcp",
            oauth=None,
        )
        client = MCPClient(cfg)
        assert client._build_oauth_provider() is None  # noqa: SLF001 - test only

    def test_oauth_set_builds_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Keep the storage off the user's actual ~/.config dir.
        monkeypatch.setenv("CANTRIP_MCP_TOKEN_DIR", str(tmp_path))
        cfg = ServerConfig(
            name="s",
            transport=TransportKind.HTTP,
            url="https://example.com/mcp",
            oauth=OAuthConfig(client_name="t", scopes=["a"], redirect_port=9876),
        )
        client = MCPClient(cfg)
        provider = client._build_oauth_provider()  # noqa: SLF001 - test only
        assert provider is not None
        # The SDK exposes the provider as an httpx.Auth subclass.
        import httpx

        assert isinstance(provider, httpx.Auth)

    @pytest.mark.asyncio
    async def test_stdio_with_oauth_rejected_at_validate(self, tmp_path: Path) -> None:
        cfg = ServerConfig(
            name="s",
            transport=TransportKind.STDIO,
            command="/bin/true",
            oauth=OAuthConfig(),
        )
        client = MCPClient(cfg)
        with pytest.raises(MCPConfigError, match="only valid for the http transport"):
            await client.start()
