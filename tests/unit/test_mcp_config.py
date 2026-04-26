"""Tests for the MCP YAML loader (Phase 45.2)."""

from __future__ import annotations

import pathlib

import pytest

from cantrip.mcp import MCPConfigError, ServerConfig, load_configs
from cantrip.mcp.config import _parse_yaml
from cantrip.mcp.types import TransportKind


def _write_yaml(path: pathlib.Path, content: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ── Single-file parsing ────────────────────────────────────────────────


class TestParseYaml:
    def test_minimal_stdio(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            "servers:\n  fs:\n    command: my-server\n",
        )
        configs = _parse_yaml(f)
        assert len(configs) == 1
        cfg = configs[0]
        assert cfg.name == "fs"
        assert cfg.transport == TransportKind.STDIO
        assert cfg.command == "my-server"
        assert cfg.args == []
        assert cfg.allowed_tools == []
        assert cfg.timeout_seconds == 30.0

    def test_full_stdio(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            """
servers:
  charmhub:
    command: charmhub-mcp
    args: ["--profile", "default"]
    env:
      TOKEN: "abc"
    cwd: "~/charmhub"
    timeout_seconds: 60
    allowed_tools: ["search", "info"]
""",
        )
        cfg = _parse_yaml(f)[0]
        assert cfg.command == "charmhub-mcp"
        assert cfg.args == ["--profile", "default"]
        assert cfg.env == {"TOKEN": "abc"}
        assert cfg.cwd is not None
        assert cfg.timeout_seconds == 60.0
        assert cfg.allowed_tools == ["search", "info"]

    def test_http(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            """
servers:
  grafana:
    transport: http
    url: https://grafana.example.com/mcp
    headers:
      Authorization: "Bearer xyz"
""",
        )
        cfg = _parse_yaml(f)[0]
        assert cfg.transport == TransportKind.HTTP
        assert cfg.url == "https://grafana.example.com/mcp"
        assert cfg.headers == {"Authorization": "Bearer xyz"}

    def test_empty_file(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(tmp_path / "mcp.yaml", "")
        assert _parse_yaml(f) == []

    def test_no_servers_block(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(tmp_path / "mcp.yaml", "other: stuff\n")
        assert _parse_yaml(f) == []

    def test_top_level_must_be_mapping(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(tmp_path / "mcp.yaml", "- a\n- b\n")
        with pytest.raises(MCPConfigError, match="must be a mapping"):
            _parse_yaml(f)

    def test_servers_must_be_mapping(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(tmp_path / "mcp.yaml", "servers: [1, 2]\n")
        with pytest.raises(MCPConfigError, match="`servers`"):
            _parse_yaml(f)

    def test_unknown_transport(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            "servers:\n  bad:\n    transport: telnet\n    command: x\n",
        )
        with pytest.raises(MCPConfigError, match="unknown transport"):
            _parse_yaml(f)

    def test_stdio_requires_command(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(tmp_path / "mcp.yaml", "servers:\n  bad: {}\n")
        with pytest.raises(MCPConfigError, match="requires `command`"):
            _parse_yaml(f)

    def test_http_requires_url(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            "servers:\n  bad:\n    transport: http\n",
        )
        with pytest.raises(MCPConfigError, match="requires `url`"):
            _parse_yaml(f)

    def test_negative_timeout(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            "servers:\n  bad:\n    command: x\n    timeout_seconds: -1\n",
        )
        with pytest.raises(MCPConfigError, match="positive"):
            _parse_yaml(f)

    def test_args_must_be_string_list(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            "servers:\n  bad:\n    command: x\n    args: [1, 2, 3]\n",
        )
        with pytest.raises(MCPConfigError, match="items must be strings"):
            _parse_yaml(f)

    def test_env_must_be_string_dict(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(
            tmp_path / "mcp.yaml",
            "servers:\n  bad:\n    command: x\n    env:\n      KEY: 5\n",
        )
        with pytest.raises(MCPConfigError, match="keys and values must be strings"):
            _parse_yaml(f)

    def test_malformed_yaml(self, tmp_path: pathlib.Path) -> None:
        f = _write_yaml(tmp_path / "mcp.yaml", "{unbalanced: [\n")
        with pytest.raises(MCPConfigError, match="could not parse"):
            _parse_yaml(f)


# ── Multi-source merge precedence ──────────────────────────────────────


class TestLoadConfigs:
    def test_no_files_returns_empty(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(tmp_path / "missing.yaml"))
        assert load_configs(repo_root=tmp_path / "no-such-dir") == []

    def test_user_only(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        user = _write_yaml(
            tmp_path / "user.yaml",
            "servers:\n  fs:\n    command: user-fs\n",
        )
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(user))
        cfgs = load_configs(repo_root=tmp_path / "no-repo")
        assert [c.name for c in cfgs] == ["fs"]
        assert cfgs[0].command == "user-fs"

    def test_repo_only(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Make sure the user-scope path is unreachable.
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(tmp_path / "missing.yaml"))
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _write_yaml(
            repo_root / "cantrip.mcp.yaml",
            "servers:\n  fs:\n    command: repo-fs\n",
        )
        cfgs = load_configs(repo_root=repo_root)
        assert [c.name for c in cfgs] == ["fs"]
        assert cfgs[0].command == "repo-fs"

    def test_repo_overrides_user_on_collision(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = _write_yaml(
            tmp_path / "user.yaml",
            "servers:\n  fs:\n    command: user-fs\n",
        )
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(user))
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _write_yaml(
            repo_root / "cantrip.mcp.yaml",
            "servers:\n  fs:\n    command: repo-fs\n",
        )
        cfgs = load_configs(repo_root=repo_root)
        assert len(cfgs) == 1
        assert cfgs[0].command == "repo-fs"

    def test_union_when_no_collision(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = _write_yaml(
            tmp_path / "user.yaml",
            "servers:\n  user-only:\n    command: u\n",
        )
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(user))
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _write_yaml(
            repo_root / "cantrip.mcp.yaml",
            "servers:\n  repo-only:\n    command: r\n",
        )
        cfgs = load_configs(repo_root=repo_root)
        assert sorted(c.name for c in cfgs) == ["repo-only", "user-only"]

    def test_malformed_user_file_skipped(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # A broken user-scope file is logged and skipped; repo still loads.
        user = _write_yaml(tmp_path / "user.yaml", "{not yaml")
        monkeypatch.setenv("CANTRIP_MCP_USER_CONFIG", str(user))
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        _write_yaml(
            repo_root / "cantrip.mcp.yaml",
            "servers:\n  fs:\n    command: x\n",
        )
        with caplog.at_level("WARNING"):
            cfgs = load_configs(repo_root=repo_root)
        assert [c.name for c in cfgs] == ["fs"]
        assert any("malformed" in r.message.lower() for r in caplog.records)


# ── ServerConfig directly ──────────────────────────────────────────────


class TestServerConfigDefaults:
    def test_defaults(self) -> None:
        cfg = ServerConfig(name="t")
        assert cfg.transport == TransportKind.STDIO
        assert cfg.command is None
        assert cfg.args == []
        assert cfg.timeout_seconds == 30.0
