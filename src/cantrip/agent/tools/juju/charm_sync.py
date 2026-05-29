"""Charm-sync tool: push local Python source directly to a running unit."""

import os
import pathlib
from typing import Any

import jubilant

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju import _common


class CharmSyncTool(Tool):
    """Tool to push local Python source files directly to a running unit.

    This bypasses the pack/refresh cycle for rapid iteration on Python-only
    changes. Each hook invocation starts a fresh Python process, so
    overwriting ``.py`` files on disk is sufficient.
    """

    @property
    def name(self) -> str:
        return "charm_sync"

    @property
    def description(self) -> str:
        return (
            "Push local Python source files (src/, lib/) directly to a running unit, "
            "bypassing charmcraft pack. Use for rapid iteration on Python-only changes. "
            "Always validate with a full pack/refresh before declaring the charm done."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unit": {
                    "type": "string",
                    "description": "Unit name (e.g., 'my-app/0')",
                },
                "charm_dir": {
                    "type": "string",
                    "description": (
                        "Local charm directory containing src/ and lib/. "
                        "Defaults to the current working directory."
                    ),
                },
                "directories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Directories to sync (default: ['src', 'lib'])",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
            },
            "required": ["unit"],
        }

    async def execute(
        self,
        unit: str,
        charm_dir: str | None = None,
        directories: list[str] | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Sync local Python source to a running unit."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )
        local_root = _common.pathlib.Path(charm_dir) if charm_dir else _common.pathlib.Path.cwd()
        dirs_to_sync = directories or ["src", "lib"]
        remote_root = _common._agent_charm_dir(unit)
        try:
            juju = _common.jubilant.Juju(model=model)
            k8s = await _common._is_k8s_model(juju)
            files = self._collect_python_files(local_root, dirs_to_sync, remote_root)
            if not files:
                return ToolResult(
                    success=True,
                    output=f"No .py files found in {dirs_to_sync}. Nothing to sync.",
                    data={"files_synced": 0},
                )
            for local_path, remote_path in files:
                await self._push_file(juju, unit, local_path, remote_path, k8s=k8s)
            synced_names = [str(f[0].relative_to(local_root)) for f in files]
            return ToolResult(
                success=True,
                output=(
                    f"Synced {len(files)} file(s) to {unit}:\n"
                    + "\n".join(f"  {n}" for n in synced_names)
                ),
                data={"files_synced": len(files), "files": synced_names},
                caption=f"Synced {len(files)} file{'s' if len(files) != 1 else ''} → {unit}",
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="charm sync timed out — the unit may be unreachable.",
            )
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )

    @staticmethod
    def _collect_python_files(
        local_root: pathlib.Path, dirs_to_sync: list[str], remote_root: str
    ) -> list[tuple[pathlib.Path, str]]:
        """Walk *dirs_to_sync* under *local_root* and pair each ``.py`` with its remote target."""
        files: list[tuple[pathlib.Path, str]] = []
        for dir_name in dirs_to_sync:
            local_dir = local_root / dir_name
            if not local_dir.is_dir():
                continue
            for root, _dirs, filenames in os.walk(local_dir):
                for fname in filenames:
                    if not fname.endswith(".py"):
                        continue
                    local_path = _common.pathlib.Path(root) / fname
                    relative = local_path.relative_to(local_root)
                    remote_path = f"{remote_root}/{relative}"
                    files.append((local_path, remote_path))
        return files

    @staticmethod
    async def _push_file(
        juju: jubilant.Juju,
        unit: str,
        local_path: pathlib.Path,
        remote_path: str,
        *,
        k8s: bool,
    ) -> None:
        """Copy one local file to *unit*; k8s uses ``juju scp`` into the charm container,
        machine charms shell out to ``sudo tee`` because scp drops privileges.
        """
        remote_parent = str(_common.pathlib.Path(remote_path).parent)
        safe_parent = _common.shlex.quote(remote_parent)
        safe_path = _common.shlex.quote(remote_path)
        if k8s:
            await _common._run_juju(
                juju.ssh,
                unit,
                f"mkdir -p {safe_parent}",
                container="charm",
            )
            await _common._run_juju(
                juju.scp,
                str(local_path),
                f"{unit}:{remote_path}",
                container="charm",
            )
        else:
            await _common._run_juju(juju.ssh, unit, f"sudo mkdir -p {safe_parent}")
            content = local_path.read_text()
            await _common._run_juju(
                juju.cli,
                "ssh",
                unit,
                f"sudo tee {safe_path}",
                stdin=content,
            )
