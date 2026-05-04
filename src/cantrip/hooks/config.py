"""Discovery and parsing of ``hooks.yaml`` files.

Two scopes are merged: the user-level
``$XDG_CONFIG_HOME/cantrip/hooks.yaml`` and the per-repo
``./cantrip.hooks.yaml`` next to the charm.  Repo wins on name
collision (matches the MCP config convention).
"""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Any

import yaml

from cantrip.hooks.filter import _FilterExpr
from cantrip.hooks.types import (
    DEFAULT_HOOK_TIMEOUT,
    REPO_CONFIG_FILENAME,
    USER_CONFIG_PATH,
    HookConfig,
    HookConfigError,
    HookEvent,
)

log = logging.getLogger(__name__)


def _user_config_path() -> pathlib.Path | None:
    """Resolve the user-scope hooks file, honouring the env override."""
    override = os.environ.get("CANTRIP_HOOKS_USER_CONFIG")
    if override:
        return pathlib.Path(override).expanduser()
    return USER_CONFIG_PATH.expanduser()


def _candidate_paths(repo_root: pathlib.Path | str | None) -> list[pathlib.Path]:
    """Return the user- then repo-scope config paths in load order.

    Repo is loaded after user so a repo-level ``name`` collision
    overrides the user-level hook of the same name — matching the
    MCP config semantics.  ``repo_root`` is coerced to ``pathlib.Path``
    so callers can pass either a ``Path`` or a ``str`` — the CLI and
    TUI pass ``charm_path`` through verbatim and users provide it as
    either type.
    """
    user = _user_config_path()
    paths: list[pathlib.Path] = [user] if user else []
    if repo_root is not None:
        paths.append(pathlib.Path(repo_root) / REPO_CONFIG_FILENAME)
    return paths


def load_hooks(repo_root: pathlib.Path | str | None = None) -> list[HookConfig]:
    """Discover and merge hooks from the user + repo scope YAML files.

    Returns a deterministic list (user hooks first in declaration
    order, repo hooks after, name collisions resolved in favour of the
    repo declaration).  Missing files are not errors; malformed files
    log a warning and contribute nothing so a broken user config can't
    take down the agent.
    """
    by_name: dict[str, HookConfig] = {}
    for source in _candidate_paths(repo_root):
        if not source.is_file():
            continue
        try:
            entries = _parse_yaml(source)
        except HookConfigError as exc:
            log.warning("Ignoring malformed hooks config at %s: %s", source, exc)
            continue
        for hook in entries:
            by_name[hook.name] = hook
    return list(by_name.values())


def _parse_yaml(path: pathlib.Path) -> list[HookConfig]:
    """Parse one hooks YAML file into :class:`HookConfig` instances."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HookConfigError(f"{path} is not valid UTF-8: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HookConfigError(f"could not parse {path}: {exc}") from exc
    except RecursionError as exc:
        raise HookConfigError(f"{path} nesting too deep ({exc})") from exc
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise HookConfigError(
            f"top-level value in {path} must be a mapping, got {type(raw).__name__}"
        )
    hooks_block = raw.get("hooks")
    if hooks_block is None:
        return []
    if not isinstance(hooks_block, list):
        raise HookConfigError(
            f"`hooks` in {path} must be a list, got {type(hooks_block).__name__}"
        )
    out: list[HookConfig] = []
    for index, spec in enumerate(hooks_block):
        if not isinstance(spec, dict):
            raise HookConfigError(
                f"hook #{index} in {path} must be a mapping, got {type(spec).__name__}"
            )
        out.append(_parse_hook(spec, path, index))
    return out


def _parse_hook(spec: dict[str, Any], path: pathlib.Path, index: int) -> HookConfig:
    """Validate one hook spec.  Raises :class:`HookConfigError` on bad input."""
    event_raw = spec.get("event")
    if not isinstance(event_raw, str) or not event_raw.strip():
        raise HookConfigError(f"hook #{index} in {path}: `event` must be a non-empty string")
    try:
        event = HookEvent(event_raw.strip())
    except ValueError as exc:
        valid = ", ".join(sorted(e.value for e in HookEvent))
        raise HookConfigError(
            f"hook #{index} in {path}: unknown event {event_raw!r} (expected one of: {valid})"
        ) from exc

    run_raw = spec.get("run")
    if not isinstance(run_raw, str) or not run_raw.strip():
        raise HookConfigError(f"hook #{index} in {path}: `run` must be a non-empty string")

    name_raw = spec.get("name")
    if name_raw is None:
        # Default the hook name to the first shell word of ``run`` so
        # logs are readable without forcing every user to write a
        # ``name:`` line.
        name = run_raw.strip().split()[0] or f"hook-{index}"
    elif not isinstance(name_raw, str) or not name_raw.strip():
        raise HookConfigError(
            f"hook #{index} in {path}: `name` must be a non-empty string when set"
        )
    else:
        name = name_raw.strip()

    timeout_raw = spec.get("timeout", DEFAULT_HOOK_TIMEOUT)
    if isinstance(timeout_raw, bool) or not isinstance(timeout_raw, (int, float)):
        raise HookConfigError(f"hook {name!r} in {path}: `timeout` must be a number")
    if timeout_raw <= 0:
        raise HookConfigError(f"hook {name!r} in {path}: `timeout` must be positive")

    continue_raw = spec.get("continue_on_error", True)
    if not isinstance(continue_raw, bool):
        raise HookConfigError(
            f"hook {name!r} in {path}: `continue_on_error` must be true or false"
        )

    if_raw = spec.get("if")
    if_expr: _FilterExpr | None = None
    if if_raw is not None:
        if not isinstance(if_raw, str) or not if_raw.strip():
            raise HookConfigError(
                f"hook {name!r} in {path}: `if` must be a non-empty string when set"
            )
        try:
            if_expr = _FilterExpr(if_raw.strip())
        except HookConfigError as exc:
            # Re-raise with the hook's name + path prefixed so the
            # operator can find the broken entry without scanning the
            # whole file.
            raise HookConfigError(f"hook {name!r} in {path}: {exc}") from exc

    return HookConfig(
        name=name,
        event=event,
        run=run_raw.strip(),
        timeout=float(timeout_raw),
        continue_on_error=continue_raw,
        if_expr=if_expr,
    )
