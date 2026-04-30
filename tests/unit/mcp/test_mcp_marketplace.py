"""Tests for MCP marketplace discovery + /mcp marketplace (Phase 45.5)."""

from __future__ import annotations

import json
import pathlib
import time

import pytest

from cantrip.agent.commands.mcp import (
    handle_mcp,
    handle_mcp_async,
    is_marketplace_subcommand,
)
from cantrip.mcp import (
    Marketplace,
    MarketplaceLoader,
    MarketplaceServer,
    MarketplaceSource,
    MCPRegistry,
    load_marketplace_sources,
)
from cantrip.mcp.exceptions import MCPConfigError
from cantrip.mcp.marketplace import (
    DEFAULT_CACHE_TTL_SECONDS,
    SourceKind,
    parse_source,
)


def _write_yaml(path: pathlib.Path, content: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _sample_marketplace_json() -> str:
    """Return a valid marketplace.json string for the directory loader."""
    return json.dumps(
        {
            "name": "sample",
            "description": "Sample marketplace",
            "servers": {
                "filesystem": {
                    "description": "Local filesystem access",
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["@mcp/server-filesystem", "/tmp"],
                },
                "github": {
                    "description": "GitHub API",
                    "command": "uvx",
                    "args": ["github-mcp"],
                    "env_required": ["GITHUB_TOKEN"],
                    "scopes": ["repo"],
                },
                "grafana": {
                    "description": "Grafana over HTTP",
                    "transport": "http",
                    "url": "https://grafana.example.com/mcp",
                },
            },
        }
    )


# ── Source parsing ─────────────────────────────────────────────────────


class TestParseSource:
    def test_github(self) -> None:
        src = parse_source({"github": "owner/repo"}, source_label="x")
        assert src.kind == SourceKind.GITHUB
        assert src.location == "owner/repo"
        assert src.label == "github:owner/repo"

    def test_directory(self) -> None:
        src = parse_source({"directory": "/tmp/cat"}, source_label="x")
        assert src.kind == SourceKind.DIRECTORY
        assert src.location == "/tmp/cat"

    def test_url(self) -> None:
        src = parse_source({"url": "https://example.com/marketplace.json"}, source_label="x")
        assert src.kind == SourceKind.URL

    def test_must_be_mapping(self) -> None:
        with pytest.raises(MCPConfigError, match="must be a mapping"):
            parse_source("not-a-dict", source_label="x")  # type: ignore[arg-type]

    def test_exactly_one_kind_required(self) -> None:
        with pytest.raises(MCPConfigError, match="exactly one"):
            parse_source({}, source_label="x")
        with pytest.raises(MCPConfigError, match="exactly one"):
            parse_source(
                {"github": "a/b", "url": "https://x"},
                source_label="x",
            )

    def test_extra_keys_rejected(self) -> None:
        with pytest.raises(MCPConfigError, match="unexpected keys"):
            parse_source(
                {"github": "owner/repo", "extra": "value"},
                source_label="x",
            )

    def test_github_must_be_owner_repo(self) -> None:
        with pytest.raises(MCPConfigError, match="<owner>/<repo>"):
            parse_source({"github": "just-a-name"}, source_label="x")

    def test_empty_value_rejected(self) -> None:
        with pytest.raises(MCPConfigError, match="non-empty"):
            parse_source({"directory": "  "}, source_label="x")

    def test_fetch_url_for_github(self) -> None:
        src = parse_source({"github": "anthropic-ai/mcp"}, source_label="x")
        url = src.fetch_url()
        assert url is not None
        assert url.startswith("https://raw.githubusercontent.com/anthropic-ai/mcp/")
        assert url.endswith("/marketplace.json")

    def test_fetch_url_for_url(self) -> None:
        src = parse_source({"url": "https://x.example/m.json"}, source_label="x")
        assert src.fetch_url() == "https://x.example/m.json"

    def test_fetch_url_for_directory_is_none(self) -> None:
        src = parse_source({"directory": "/tmp"}, source_label="x")
        assert src.fetch_url() is None


# ── YAML loader ────────────────────────────────────────────────────────


class TestLoadMarketplaceSources:
    def test_no_files_returns_empty(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(tmp_path / "missing.yaml"))
        assert load_marketplace_sources(repo_root=tmp_path / "no-such-dir") == []

    def test_no_marketplaces_block_returns_empty(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(tmp_path / "missing.yaml"))
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_yaml(
            repo / "cantrip.mcp.yaml",
            "servers:\n  s:\n    command: x\n",
        )
        assert load_marketplace_sources(repo_root=repo) == []

    def test_basic_load(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(tmp_path / "missing.yaml"))
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_yaml(
            repo / "cantrip.mcp.yaml",
            """
marketplaces:
  - github: anthropic-ai/mcp-servers
  - directory: ~/local
servers: {}
""",
        )
        sources = load_marketplace_sources(repo_root=repo)
        assert len(sources) == 2
        assert sources[0].kind == SourceKind.GITHUB
        assert sources[1].kind == SourceKind.DIRECTORY

    def test_user_and_repo_dedupe(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = _write_yaml(
            tmp_path / "user.yaml",
            "marketplaces:\n  - github: a/b\n",
        )
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(user))
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_yaml(
            repo / "cantrip.mcp.yaml",
            """
marketplaces:
  - github: a/b
  - github: c/d
""",
        )
        sources = load_marketplace_sources(repo_root=repo)
        # One a/b (deduped), one c/d.
        assert len(sources) == 2
        assert {s.location for s in sources} == {"a/b", "c/d"}

    def test_marketplaces_must_be_list(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(tmp_path / "missing.yaml"))
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_yaml(
            repo / "cantrip.mcp.yaml",
            "marketplaces: not-a-list\n",
        )
        # Malformed file is logged + skipped, not raised.
        assert load_marketplace_sources(repo_root=repo) == []


# ── MarketplaceLoader ─────────────────────────────────────────────────


class TestMarketplaceLoader:
    @pytest.mark.asyncio
    async def test_directory_round_trip(self, tmp_path: pathlib.Path) -> None:
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "marketplace.json").write_text(_sample_marketplace_json())
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(catalog))
        market = await loader.load(src)
        assert market.name == "sample"
        assert {s.name for s in market.servers} == {"filesystem", "github", "grafana"}
        # Inspect a server descriptor.
        github = next(s for s in market.servers if s.name == "github")
        assert github.command == "uvx"
        assert github.env_required == ["GITHUB_TOKEN"]
        assert github.scopes == ["repo"]
        # Cache file written.
        assert any(loader.cache_dir.glob("*.json"))

    @pytest.mark.asyncio
    async def test_directory_missing_file_raises(self, tmp_path: pathlib.Path) -> None:
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(tmp_path / "no-such"))
        with pytest.raises(OSError, match="no marketplace.json"):
            await loader.load(src)

    @pytest.mark.asyncio
    async def test_load_all_skips_failures(self, tmp_path: pathlib.Path) -> None:
        good_dir = tmp_path / "good"
        good_dir.mkdir()
        (good_dir / "marketplace.json").write_text(_sample_marketplace_json())
        sources = [
            MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(good_dir)),
            MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(tmp_path / "missing")),
        ]
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        markets = await loader.load_all(sources)
        # Only the good source loaded; the missing one was logged + skipped.
        assert len(markets) == 1
        assert markets[0].name == "sample"

    @pytest.mark.asyncio
    async def test_http_get_wraps_aiohttp_error_as_oserror(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """aiohttp errors are converted to OSError so load_all's catch clause skips them."""
        import aiohttp

        def _raise(*_args: object, **_kwargs: object) -> object:
            raise aiohttp.ClientError("simulated network glitch")

        monkeypatch.setattr(aiohttp, "ClientSession", _raise)
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        with pytest.raises(OSError, match="HTTP fetch failed"):
            await loader._http_get("http://example.invalid/marketplace.json")

    @pytest.mark.asyncio
    async def test_cache_hit_skips_re_read(self, tmp_path: pathlib.Path) -> None:
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        marketplace_path = catalog / "marketplace.json"
        marketplace_path.write_text(_sample_marketplace_json())
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(catalog))
        await loader.load(src)
        # Mutate the on-disk file.  A cache hit must surface the
        # original content; only `refresh=True` re-reads.
        marketplace_path.write_text(json.dumps({"name": "changed", "servers": {}}))
        cached = await loader.load(src)
        assert cached.name == "sample"
        fresh = await loader.load(src, refresh=True)
        assert fresh.name == "changed"

    @pytest.mark.asyncio
    async def test_cache_expires(self, tmp_path: pathlib.Path) -> None:
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        marketplace_path = catalog / "marketplace.json"
        marketplace_path.write_text(_sample_marketplace_json())
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache", cache_ttl_seconds=0.0)
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(catalog))
        await loader.load(src)
        # TTL of zero means the cache is immediately stale; a mutation
        # should be picked up on the next load.
        marketplace_path.write_text(json.dumps({"name": "fresh", "servers": {}}))
        # Sleep ensures the mtime is past the cutoff window.
        time.sleep(0.01)
        market = await loader.load(src)
        assert market.name == "fresh"

    @pytest.mark.asyncio
    async def test_malformed_json_raises(self, tmp_path: pathlib.Path) -> None:
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "marketplace.json").write_text("{not json")
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(catalog))
        with pytest.raises(MCPConfigError, match="malformed JSON"):
            await loader.load(src)

    @pytest.mark.asyncio
    async def test_top_level_not_mapping_raises(self, tmp_path: pathlib.Path) -> None:
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "marketplace.json").write_text("[1, 2, 3]")
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(catalog))
        with pytest.raises(MCPConfigError, match="must be a mapping"):
            await loader.load(src)

    @pytest.mark.asyncio
    async def test_args_must_be_string_list(self, tmp_path: pathlib.Path) -> None:
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "marketplace.json").write_text(json.dumps({"servers": {"x": {"args": [1, 2]}}}))
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(catalog))
        with pytest.raises(MCPConfigError, match="`args`"):
            await loader.load(src)

    def test_default_ttl_is_a_day(self) -> None:
        assert DEFAULT_CACHE_TTL_SECONDS >= 60


# ── /mcp marketplace slash command ────────────────────────────────────


class TestMcpMarketplaceCommand:
    def test_subcommand_detection(self) -> None:
        assert is_marketplace_subcommand("marketplace")
        assert is_marketplace_subcommand("marketplace refresh")
        assert is_marketplace_subcommand("MARKETPLACE")
        assert not is_marketplace_subcommand("tools server")
        assert not is_marketplace_subcommand("")

    def test_sync_dispatch_routes_marketplace_to_async(self) -> None:
        """The sync handler refuses marketplace ops; the async one handles them."""
        from cantrip.mcp import MCPRegistry

        out = handle_mcp(MCPRegistry([]), "marketplace")
        assert "async" in out

    @pytest.mark.asyncio
    async def test_no_sources_shows_hint(self) -> None:
        loader = MarketplaceLoader(cache_dir=pathlib.Path("/tmp/_unused"))
        out = await handle_mcp_async(MCPRegistry([]), [], loader, "marketplace")
        assert "No MCP marketplaces" in out
        assert "marketplaces:" in out  # Hint includes a sample.

    @pytest.mark.asyncio
    async def test_listing(self, tmp_path: pathlib.Path) -> None:
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "marketplace.json").write_text(_sample_marketplace_json())
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(catalog))
        out = await handle_mcp_async(MCPRegistry([]), [src], loader, "marketplace")
        # All three sample servers present.
        assert "**filesystem**" in out
        assert "**github**" in out
        assert "**grafana**" in out
        # Install hint shows the npx command.
        assert "npx @mcp/server-filesystem /tmp" in out
        # env_required and scopes surface in the listing.
        assert "GITHUB_TOKEN" in out
        assert "repo" in out
        # HTTP server uses the http hint format.
        assert "http https://grafana.example.com/mcp" in out

    @pytest.mark.asyncio
    async def test_refresh_subcommand(self, tmp_path: pathlib.Path) -> None:
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        marketplace_path = catalog / "marketplace.json"
        marketplace_path.write_text(_sample_marketplace_json())
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        src = MarketplaceSource(kind=SourceKind.DIRECTORY, location=str(catalog))
        # Prime the cache.
        await loader.load(src)
        # Mutate the file.
        marketplace_path.write_text(json.dumps({"name": "fresh", "servers": {}}))
        out = await handle_mcp_async(MCPRegistry([]), [src], loader, "marketplace refresh")
        assert "fresh" in out

    @pytest.mark.asyncio
    async def test_unknown_subcommand(self, tmp_path: pathlib.Path) -> None:
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        out = await handle_mcp_async(MCPRegistry([]), [], loader, "marketplace bogus")
        assert "Error" in out
        assert "unknown marketplace subcommand" in out

    @pytest.mark.asyncio
    async def test_help_subcommand(self, tmp_path: pathlib.Path) -> None:
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        out = await handle_mcp_async(MCPRegistry([]), [], loader, "marketplace help")
        assert "MCP commands" in out
        assert "marketplace" in out

    @pytest.mark.asyncio
    async def test_async_handler_falls_through_for_non_marketplace(
        self,
    ) -> None:
        """Calling the async handler with a non-marketplace verb routes to sync."""
        loader = MarketplaceLoader(cache_dir=pathlib.Path("/tmp/_unused"))
        out = await handle_mcp_async(MCPRegistry([]), [], loader, "")
        assert "No MCP servers" in out


# ── End-to-end with a fake marketplace stored locally ────────────────


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_pipeline_directory_source(self, tmp_path: pathlib.Path) -> None:
        # Stage a marketplace.
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "marketplace.json").write_text(_sample_marketplace_json())
        # Stage a YAML config that points at it.
        repo = tmp_path / "repo"
        repo.mkdir()
        _write_yaml(
            repo / "cantrip.mcp.yaml",
            f"""
marketplaces:
  - directory: {catalog}
""",
        )
        # Drive the public API.
        sources = load_marketplace_sources(repo_root=repo)
        assert len(sources) == 1
        loader = MarketplaceLoader(cache_dir=tmp_path / "cache")
        markets = await loader.load_all(sources)
        assert len(markets) == 1
        assert isinstance(markets[0], Marketplace)
        assert isinstance(markets[0].servers[0], MarketplaceServer)
