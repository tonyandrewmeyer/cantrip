"""Rockcraft and OCI registry tools."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Profiles that require the experimental extensions flag.
_EXPERIMENTAL_PROFILES = frozenset({"go-framework", "express-framework", "fastapi-framework"})


class RockcraftInitTool(Tool):
    """Tool to initialise a rockcraft project with a framework profile."""

    @property
    def name(self) -> str:
        return "rockcraft_init"

    @property
    def description(self) -> str:
        return (
            "Initialise a rockcraft project using a framework profile. "
            "This creates a rockcraft.yaml for building an OCI image (rock) "
            "from a 12-factor application."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to initialise in",
                    "default": ".",
                },
                "profile": {
                    "type": "string",
                    "description": "Framework profile for the rock",
                    "enum": [
                        "flask-framework",
                        "django-framework",
                        "fastapi-framework",
                        "go-framework",
                        "express-framework",
                        "spring-boot-framework",
                    ],
                },
            },
            "required": ["profile"],
        }

    async def execute(self, profile: str, path: str = ".") -> ToolResult:
        """Run rockcraft init with the given profile."""
        if not shutil.which("rockcraft"):
            return ToolResult(
                success=False,
                output="",
                error="rockcraft not found. Is it installed?",
            )

        try:
            target_path = Path(path).resolve()
            target_path.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            if profile in _EXPERIMENTAL_PROFILES:
                env["ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS"] = "true"

            result = subprocess.run(
                ["rockcraft", "init", f"--profile={profile}"],
                cwd=target_path,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "rockcraft init failed",
                )

            return ToolResult(
                success=True,
                output=f"Initialised rock at {target_path}\n{result.stdout}",
                data={"path": str(target_path), "profile": profile},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="rockcraft init timed out",
            )


class RockcraftPackTool(Tool):
    """Tool to pack a rock (OCI image)."""

    @property
    def name(self) -> str:
        return "rockcraft_pack"

    @property
    def description(self) -> str:
        return (
            "Pack the application into a .rock OCI image file. "
            "The first build may take several minutes as it downloads the Ubuntu base."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory containing rockcraft.yaml",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run rockcraft pack."""
        if not shutil.which("rockcraft"):
            return ToolResult(
                success=False,
                output="",
                error="rockcraft not found. Is it installed?",
            )

        try:
            rock_path = Path(path).resolve()

            # Always set the experimental flag — harmless when not needed.
            env = os.environ.copy()
            env["ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS"] = "true"

            result = subprocess.run(
                ["rockcraft", "pack"],
                cwd=rock_path,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "rockcraft pack failed",
                )

            # Find the resulting .rock file.
            rock_files = list(rock_path.glob("*.rock"))
            rock_file = rock_files[0] if rock_files else None

            return ToolResult(
                success=True,
                output=f"Packed rock successfully\n{result.stdout}",
                data={
                    "path": str(rock_path),
                    "rock_file": str(rock_file) if rock_file else None,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="rockcraft pack timed out (600s limit)",
            )


class SkopeoRegistryPushTool(Tool):
    """Tool to push a rock to an OCI registry via skopeo."""

    @property
    def name(self) -> str:
        return "skopeo_registry_push"

    @property
    def description(self) -> str:
        return (
            "Push a .rock file to an OCI container registry using skopeo. "
            "Defaults to the MicroK8s built-in registry at localhost:32000."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rock_file": {
                    "type": "string",
                    "description": "Path to the .rock file",
                },
                "image_name": {
                    "type": "string",
                    "description": "Name for the image in the registry",
                },
                "registry": {
                    "type": "string",
                    "description": "Registry address",
                    "default": "localhost:32000",
                },
                "tag": {
                    "type": "string",
                    "description": "Image tag",
                    "default": "latest",
                },
            },
            "required": ["rock_file", "image_name"],
        }

    async def execute(
        self,
        rock_file: str,
        image_name: str,
        registry: str = "localhost:32000",
        tag: str = "latest",
    ) -> ToolResult:
        """Push a rock to a container registry."""
        if not shutil.which("skopeo"):
            return ToolResult(
                success=False,
                output="",
                error="skopeo not found. Is it installed?",
            )

        rock_path = Path(rock_file)
        if not rock_path.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Rock file not found: {rock_file}",
            )

        try:
            image_url = f"{registry}/{image_name}:{tag}"
            result = subprocess.run(
                [
                    "skopeo",
                    "copy",
                    "--insecure-policy",
                    "--dest-tls-verify=false",
                    f"oci-archive:{rock_path}",
                    f"docker://{image_url}",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "skopeo push failed",
                )

            return ToolResult(
                success=True,
                output=f"Pushed rock to {image_url}\n{result.stdout}",
                data={"image_url": image_url},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="skopeo push timed out",
            )
