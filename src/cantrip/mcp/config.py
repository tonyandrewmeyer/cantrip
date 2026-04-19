"""YAML loader for MCP server declarations (Phase 45.2).

Two scopes are honoured, in order — later scopes override earlier ones
on a server-name conflict:

1. **User scope**: ``~/.config/cantrip/mcp.yaml`` (or
   ``$CANTRIP_MCP_USER_CONFIG`` when set).
2. **Repo scope**: ``./cantrip.mcp.yaml`` next to the charm directory.

The YAML schema, kept deliberately small, mirrors the Claude Code /
Cursor / Codex format for portability:

```yaml
servers:
  charmhub:
    command: charmhub-mcp
    args: ["--profile", "default"]
    env:
      CHARMHUB_TOKEN: "..."
    allowed_tools: ["charmhub_search", "charmhub_info"]
  grafana:
    transport: http
    url: https://grafana.example.com/mcp
    headers:
      Authorization: "Bearer ..."
```
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from cantrip.mcp.exceptions import MCPConfigError
from cantrip.mcp.types import ServerConfig, TransportKind

log = logging.getLogger(__name__)

# Filenames Cantrip looks for in each scope.
USER_CONFIG_PATH = Path("~/.config/cantrip/mcp.yaml")
REPO_CONFIG_FILENAME = "cantrip.mcp.yaml"


def load_configs(repo_root: Path | None = None) -> list[ServerConfig]:
    """Discover and merge MCP server configs from user + repo scope.

    Returns the configured servers as a deterministic, alphabetised list
    of :class:`ServerConfig`.  Missing files are not errors; an empty
    config returns an empty list so callers can call this unconditionally
    on every startup.
    """
    by_name: dict[str, ServerConfig] = {}
    for source in _candidate_paths(repo_root):
        if not source.is_file():
            continue
        try:
            servers = _parse_yaml(source)
        except MCPConfigError as exc:
            log.warning("Ignoring malformed MCP config at %s: %s", source, exc)
            continue
        for server in servers:
            # Repo-scope config overrides user-scope on the same name.
            by_name[server.name] = server
    return sorted(by_name.values(), key=lambda s: s.name)


def _candidate_paths(repo_root: Path | None) -> list[Path]:
    """Return the user- then repo-scope config paths in load order."""
    user = _user_config_path()
    paths: list[Path] = [user] if user else []
    if repo_root is not None:
        paths.append(repo_root / REPO_CONFIG_FILENAME)
    return paths


def _user_config_path() -> Path | None:
    """Resolve the user-scope config path, honouring the env override."""
    override = os.environ.get("CANTRIP_MCP_USER_CONFIG")
    if override:
        return Path(override).expanduser()
    return USER_CONFIG_PATH.expanduser()


def _parse_yaml(path: Path) -> list[ServerConfig]:
    """Parse a single YAML file into ``ServerConfig`` instances.

    Raises :class:`MCPConfigError` on any structural problem so the
    loader can skip the file with a clear log message rather than
    crashing the agent at startup.
    """
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise MCPConfigError(f"could not parse {path}: {exc}") from exc
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise MCPConfigError(
            f"top-level value in {path} must be a mapping, got {type(raw).__name__}"
        )
    servers_block = raw.get("servers")
    if servers_block is None:
        return []
    if not isinstance(servers_block, dict):
        raise MCPConfigError(
            f"`servers` in {path} must be a mapping, got {type(servers_block).__name__}"
        )
    out: list[ServerConfig] = []
    for name, spec in servers_block.items():
        if not isinstance(name, str) or not name.strip():
            raise MCPConfigError(f"server name in {path} must be a non-empty string")
        if not isinstance(spec, dict):
            raise MCPConfigError(
                f"server {name!r} in {path} must be a mapping, got {type(spec).__name__}"
            )
        out.append(_parse_server(name.strip(), spec, source=path))
    return out


def _parse_server(name: str, spec: dict[str, Any], *, source: Path) -> ServerConfig:
    """Validate a single server block and build its :class:`ServerConfig`."""
    transport_raw = str(spec.get("transport", "stdio")).lower()
    try:
        transport = TransportKind(transport_raw)
    except ValueError as exc:
        raise MCPConfigError(
            f"server {name!r} in {source}: unknown transport "
            f"{transport_raw!r} (expected one of: "
            f"{', '.join(sorted(t.value for t in TransportKind))})"
        ) from exc

    args = _string_list(spec.get("args"), name=name, key="args", source=source)
    headers = _string_dict(spec.get("headers"), name=name, key="headers", source=source)
    env = _string_dict(spec.get("env"), name=name, key="env", source=source)
    allowed_tools = _string_list(
        spec.get("allowed_tools"), name=name, key="allowed_tools", source=source
    )

    timeout = spec.get("timeout_seconds", 30.0)
    if not isinstance(timeout, (int, float)):
        raise MCPConfigError(f"server {name!r} in {source}: `timeout_seconds` must be numeric")
    if timeout <= 0:
        raise MCPConfigError(f"server {name!r} in {source}: `timeout_seconds` must be positive")

    cwd_raw = spec.get("cwd")
    cwd: str | None = None
    if cwd_raw is not None:
        if not isinstance(cwd_raw, str):
            raise MCPConfigError(f"server {name!r} in {source}: `cwd` must be a string")
        cwd = str(Path(cwd_raw).expanduser())

    command_raw = spec.get("command")
    command: str | None = None
    if command_raw is not None:
        if not isinstance(command_raw, str):
            raise MCPConfigError(f"server {name!r} in {source}: `command` must be a string")
        command = command_raw

    url_raw = spec.get("url")
    url: str | None = None
    if url_raw is not None:
        if not isinstance(url_raw, str):
            raise MCPConfigError(f"server {name!r} in {source}: `url` must be a string")
        url = url_raw

    config = ServerConfig(
        name=name,
        transport=transport,
        command=command,
        args=args,
        env=env,
        cwd=cwd,
        url=url,
        headers=headers,
        timeout_seconds=float(timeout),
        allowed_tools=allowed_tools,
    )
    # Cross-field validation — fail fast at config time rather than
    # at start time so the user sees the error in one place.
    if transport == TransportKind.STDIO and not config.command:
        raise MCPConfigError(f"server {name!r} in {source}: stdio transport requires `command`")
    if transport == TransportKind.HTTP and not config.url:
        raise MCPConfigError(f"server {name!r} in {source}: http transport requires `url`")
    return config


def _string_list(value: Any, *, name: str, key: str, source: Path) -> list[str]:
    """Coerce ``value`` to ``list[str]`` or raise :class:`MCPConfigError`."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise MCPConfigError(
            f"server {name!r} in {source}: `{key}` must be a list, got {type(value).__name__}"
        )
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise MCPConfigError(f"server {name!r} in {source}: `{key}` items must be strings")
        out.append(item)
    return out


def _string_dict(value: Any, *, name: str, key: str, source: Path) -> dict[str, str]:
    """Coerce ``value`` to ``dict[str, str]`` or raise :class:`MCPConfigError`."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MCPConfigError(
            f"server {name!r} in {source}: `{key}` must be a mapping, got {type(value).__name__}"
        )
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise MCPConfigError(
                f"server {name!r} in {source}: `{key}` keys and values must be strings"
            )
        out[k] = v
    return out


__all__ = [
    "REPO_CONFIG_FILENAME",
    "USER_CONFIG_PATH",
    "load_configs",
]
