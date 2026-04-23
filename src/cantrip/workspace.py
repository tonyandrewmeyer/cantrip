"""Multi-charm workspace manifest (Phase 33.3).

A workspace manifest declares a set of related charms that live under a
common root — typically a monorepo with one charm per subdirectory —
plus the cross-charm relations and any config values they share.  The
agent reads the manifest through the ``workspace_info`` tool; it is
not required for single-charm work.

Pure-function design: parsing is deterministic, frozen dataclasses
are round-trippable to a dict, and there is no implicit filesystem
access beyond the single :func:`load_workspace` entry point.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any

import yaml

# Canonical filename agents and the CLI look for.
MANIFEST_FILENAME = "cantrip.workspace.yaml"


class WorkspaceError(ValueError):
    """Raised when a workspace manifest is missing or malformed."""


@dataclasses.dataclass(frozen=True, slots=True)
class WorkspaceCharm:
    """One charm inside a workspace."""

    name: str
    path: pathlib.Path
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "path": str(self.path)}
        if self.description is not None:
            data["description"] = self.description
        return data


@dataclasses.dataclass(frozen=True, slots=True)
class WorkspaceRelation:
    """One cross-charm relation described by the workspace."""

    provider: str  # "charm-name:endpoint"
    requirer: str  # "charm-name:endpoint"
    interface: str
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "provider": self.provider,
            "requirer": self.requirer,
            "interface": self.interface,
        }
        if self.description is not None:
            data["description"] = self.description
        return data


@dataclasses.dataclass(frozen=True, slots=True)
class Workspace:
    """A parsed workspace manifest."""

    name: str
    root: pathlib.Path
    charms: tuple[WorkspaceCharm, ...]
    relations: tuple[WorkspaceRelation, ...] = ()
    shared_config: dict[str, Any] = dataclasses.field(default_factory=dict)
    description: str | None = None

    def charm_names(self) -> list[str]:
        return [c.name for c in self.charms]

    def find_charm(self, name: str) -> WorkspaceCharm | None:
        for charm in self.charms:
            if charm.name == name:
                return charm
        return None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "workspace": self.name,
            "root": str(self.root),
            "charms": [c.to_dict() for c in self.charms],
        }
        if self.relations:
            data["relations"] = [r.to_dict() for r in self.relations]
        if self.shared_config:
            data["shared_config"] = dict(self.shared_config)
        if self.description is not None:
            data["description"] = self.description
        return data


def load_workspace(path: pathlib.Path | str) -> Workspace:
    """Parse a workspace manifest from disk.

    ``path`` may point at either the manifest file itself or the
    directory containing it.  The returned :class:`Workspace` resolves
    every charm path against the manifest's directory so later callers
    can use them verbatim.

    Raises :class:`WorkspaceError` on a missing file, malformed YAML,
    or a manifest that violates the schema (missing ``workspace`` name,
    no charms, duplicate charm names, relations naming unknown charms,
    and so on).
    """
    manifest_path = _resolve_manifest_path(path)
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkspaceError(f"Cannot read workspace manifest {manifest_path}: {exc}") from exc

    try:
        raw = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as exc:
        raise WorkspaceError(f"Invalid YAML in {manifest_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise WorkspaceError(f"Manifest {manifest_path} must be a YAML mapping")

    return _parse(raw, root=manifest_path.parent.resolve())


def _resolve_manifest_path(path: pathlib.Path | str) -> pathlib.Path:
    """Return the concrete manifest file path for the given argument."""
    candidate = pathlib.Path(path)
    manifest = candidate / MANIFEST_FILENAME if candidate.is_dir() else candidate
    if not manifest.is_file():
        raise WorkspaceError(f"No workspace manifest at {manifest}")
    return manifest.resolve()


def _parse(raw: dict[str, Any], *, root: pathlib.Path) -> Workspace:
    """Validate and convert a loaded YAML dict into a :class:`Workspace`."""
    name = raw.get("workspace")
    if not isinstance(name, str) or not name.strip():
        raise WorkspaceError("Manifest must declare a non-empty 'workspace' name")

    charms_raw = raw.get("charms")
    if not isinstance(charms_raw, list) or not charms_raw:
        raise WorkspaceError("Manifest must list at least one charm under 'charms:'")

    charms: list[WorkspaceCharm] = []
    seen_names: set[str] = set()
    for entry in charms_raw:
        if not isinstance(entry, dict):
            raise WorkspaceError(f"Invalid charm entry: {entry!r}")
        cname = entry.get("name")
        cpath = entry.get("path")
        if not isinstance(cname, str) or not cname.strip():
            raise WorkspaceError(f"Charm entry missing 'name': {entry!r}")
        if not isinstance(cpath, str) or not cpath.strip():
            raise WorkspaceError(f"Charm entry missing 'path': {entry!r}")
        if cname in seen_names:
            raise WorkspaceError(f"Duplicate charm name in workspace: {cname!r}")
        seen_names.add(cname)
        resolved = (root / cpath).resolve()
        desc = entry.get("description")
        if desc is not None and not isinstance(desc, str):
            raise WorkspaceError(f"Charm {cname!r} 'description' must be a string")
        charms.append(WorkspaceCharm(name=cname, path=resolved, description=desc))

    relations_raw = raw.get("relations", []) or []
    if not isinstance(relations_raw, list):
        raise WorkspaceError("'relations' must be a list if present")
    relations: list[WorkspaceRelation] = []
    for entry in relations_raw:
        if not isinstance(entry, dict):
            raise WorkspaceError(f"Invalid relation entry: {entry!r}")
        provider = entry.get("provider")
        requirer = entry.get("requirer")
        interface = entry.get("interface")
        if not (
            isinstance(provider, str) and isinstance(requirer, str) and isinstance(interface, str)
        ):
            raise WorkspaceError(
                f"Relation entry must include 'provider', 'requirer', and 'interface': {entry!r}"
            )
        _check_endpoint(provider, seen_names, label="provider")
        _check_endpoint(requirer, seen_names, label="requirer")
        desc = entry.get("description")
        if desc is not None and not isinstance(desc, str):
            raise WorkspaceError(f"Relation {interface!r} 'description' must be a string")
        relations.append(
            WorkspaceRelation(
                provider=provider,
                requirer=requirer,
                interface=interface,
                description=desc,
            )
        )

    shared_config_raw = raw.get("shared_config", {}) or {}
    if not isinstance(shared_config_raw, dict):
        raise WorkspaceError("'shared_config' must be a mapping if present")

    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        raise WorkspaceError("'description' must be a string if present")

    return Workspace(
        name=name,
        root=root,
        charms=tuple(charms),
        relations=tuple(relations),
        shared_config=dict(shared_config_raw),
        description=description,
    )


def _check_endpoint(value: str, known_charms: set[str], *, label: str) -> None:
    """Validate that a ``charm:endpoint`` string names a known charm."""
    if ":" not in value:
        raise WorkspaceError(f"Relation {label!r} must be 'charm-name:endpoint' (got {value!r})")
    charm_name, endpoint = value.split(":", 1)
    if not charm_name or not endpoint:
        raise WorkspaceError(f"Relation {label!r} empty side in {value!r}")
    if charm_name not in known_charms:
        raise WorkspaceError(
            f"Relation {label!r} names unknown charm {charm_name!r}; workspace has "
            f"{sorted(known_charms)}"
        )


def find_manifest(start: pathlib.Path | str) -> pathlib.Path | None:
    """Walk up from ``start`` looking for a workspace manifest.

    Returns the manifest path if found, or ``None`` otherwise.  Stops at
    the filesystem root.  Useful when Cantrip is launched inside a
    subdirectory of a multi-charm repo and should auto-detect the
    workspace.
    """
    current = pathlib.Path(start).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / MANIFEST_FILENAME
        if candidate.is_file():
            return candidate
    return None
