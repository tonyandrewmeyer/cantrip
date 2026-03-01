"""Charmhub publishing and README generation tools."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for charmcraft network operations (seconds).
_CHARMCRAFT_TIMEOUT = 120


class CharmcraftUploadTool(Tool):
    """Tool to upload a packed charm to Charmhub."""

    @property
    def name(self) -> str:
        return "charmcraft_upload"

    @property
    def description(self) -> str:
        return (
            "Upload a .charm file to Charmhub. Returns the assigned revision number. "
            "Requires explicit user confirmation before executing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "charm_file": {
                    "type": "string",
                    "description": "Path to the .charm file to upload",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to execute. Ask the user to confirm the upload "
                        "(charm file, Charmhub name) before setting this."
                    ),
                    "default": False,
                },
            },
            "required": ["charm_file"],
        }

    async def execute(self, charm_file: str, confirmed: bool = False) -> ToolResult:
        """Run charmcraft upload."""
        if not confirmed:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Upload requires explicit user confirmation. "
                    "Show the user what will be uploaded (charm file, target) "
                    "and ask them to confirm, then call again with confirmed=true."
                ),
            )

        charm_path = Path(charm_file)
        if not charm_path.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Charm file not found: {charm_file}",
            )

        if not shutil.which("charmcraft"):
            return ToolResult(
                success=False,
                output="",
                error="charmcraft not found. Is it installed?",
            )

        try:
            result = subprocess.run(
                ["charmcraft", "upload", str(charm_path)],
                capture_output=True,
                text=True,
                timeout=_CHARMCRAFT_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "charmcraft upload failed",
                )

            # Parse revision number from output.
            revision: int | None = None
            match = re.search(r"Revision (\d+)", result.stdout)
            if match:
                revision = int(match.group(1))

            return ToolResult(
                success=True,
                output=result.stdout.strip(),
                data={"revision": revision, "charm_file": str(charm_path)},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft upload timed out",
            )


class CharmcraftReleaseTool(Tool):
    """Tool to release a charm revision to a Charmhub channel."""

    @property
    def name(self) -> str:
        return "charmcraft_release"

    @property
    def description(self) -> str:
        return (
            "Release a charm revision to a Charmhub channel. "
            "Requires explicit user confirmation before executing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Charm name on Charmhub",
                },
                "revision": {
                    "type": "integer",
                    "description": "Revision number to release",
                },
                "channel": {
                    "type": "string",
                    "description": "Target channel (e.g. latest/edge, latest/stable)",
                    "default": "latest/edge",
                },
                "resources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Resource revisions in 'name:revision' format (e.g. 'oci-image:3')"
                    ),
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to execute. Ask the user to confirm the release "
                        "(charm name, revision, channel) before setting this."
                    ),
                    "default": False,
                },
            },
            "required": ["name", "revision"],
        }

    async def execute(
        self,
        name: str,
        revision: int,
        channel: str = "latest/edge",
        resources: list[str] | None = None,
        confirmed: bool = False,
    ) -> ToolResult:
        """Run charmcraft release."""
        if not confirmed:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Release requires explicit user confirmation. "
                    "Show the user what will be released (charm name, revision, channel) "
                    "and ask them to confirm, then call again with confirmed=true."
                ),
            )

        if not shutil.which("charmcraft"):
            return ToolResult(
                success=False,
                output="",
                error="charmcraft not found. Is it installed?",
            )

        cmd = [
            "charmcraft",
            "release",
            name,
            "--revision",
            str(revision),
            "--channel",
            channel,
        ]

        if resources:
            for resource in resources:
                cmd.extend(["--resource", resource])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_CHARMCRAFT_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "charmcraft release failed",
                )

            return ToolResult(
                success=True,
                output=result.stdout.strip() or f"Released {name} r{revision} to {channel}",
                data={"name": name, "revision": revision, "channel": channel},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft release timed out",
            )


class GenerateReadmeTool(Tool):
    """Tool to generate a README.md from charm metadata."""

    @property
    def name(self) -> str:
        return "generate_readme"

    @property
    def description(self) -> str:
        return (
            "Generate a README.md for a charm by reading charmcraft.yaml and other "
            "metadata files. Produces a structured README with usage, configuration, "
            "actions, and integrations sections."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Generate a README.md from charm metadata."""
        charm_path = Path(path).resolve()
        charmcraft_yaml = charm_path / "charmcraft.yaml"

        if not charmcraft_yaml.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"charmcraft.yaml not found in {path}",
            )

        try:
            metadata = yaml.safe_load(charmcraft_yaml.read_text())
        except yaml.YAMLError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to parse charmcraft.yaml: {exc}",
            )

        charm_name = metadata.get("name", charm_path.name)
        charm_description = metadata.get("description", "")

        # Read optional supplementary files.
        workload_md = ""
        workload_path = charm_path / "WORKLOAD.md"
        if workload_path.exists():
            workload_md = workload_path.read_text()

        design_md = ""
        design_path = charm_path / "DESIGN.md"
        if design_path.exists():
            design_md = design_path.read_text()

        # Build README sections.
        sections: list[str] = []

        # Title and description.
        sections.append(f"# {charm_name}")
        if charm_description:
            sections.append(charm_description)

        # Extract a purpose summary from WORKLOAD.md if available.
        if workload_md:
            sections.append("## Overview")
            # Use the first paragraph or purpose section.
            for line in workload_md.split("\n"):
                if line.startswith("## Purpose"):
                    continue
                if line.startswith("## ") and "Purpose" not in line:
                    break
            sections.append("See [WORKLOAD.md](WORKLOAD.md) for detailed workload analysis.")

        # Usage.
        sections.append("## Usage")
        sections.append(f"```bash\njuju deploy {charm_name}\n```")

        # Configuration.
        config = metadata.get("config", {}).get("options", {})
        if config:
            sections.append("## Configuration")
            config_lines: list[str] = []
            for opt_name, opt_data in config.items():
                opt_type = opt_data.get("type", "string")
                opt_desc = opt_data.get("description", "")
                opt_default = opt_data.get("default", "")
                line = f"- **`{opt_name}`** ({opt_type})"
                if opt_desc:
                    line += f": {opt_desc}"
                if opt_default not in ("", None):
                    line += f" (default: `{opt_default}`)"
                config_lines.append(line)
            sections.append("\n".join(config_lines))

        # Actions.
        actions = metadata.get("actions", {})
        if actions:
            sections.append("## Actions")
            action_lines: list[str] = []
            for action_name, action_data in actions.items():
                action_desc = ""
                if isinstance(action_data, dict):
                    action_desc = action_data.get("description", "")
                line = f"- **`{action_name}`**"
                if action_desc:
                    line += f": {action_desc}"
                action_lines.append(line)
            sections.append("\n".join(action_lines))

        # Integrations (requires + provides).
        requires = metadata.get("requires", {})
        provides = metadata.get("provides", {})
        if requires or provides:
            sections.append("## Integrations")
            if requires:
                sections.append("### Requires")
                for rel_name, rel_data in requires.items():
                    interface = rel_data.get("interface", "")
                    sections.append(f"- **`{rel_name}`** (`{interface}`)")
            if provides:
                sections.append("### Provides")
                for rel_name, rel_data in provides.items():
                    interface = rel_data.get("interface", "")
                    sections.append(f"- **`{rel_name}`** (`{interface}`)")

        # Design reference.
        if design_md:
            sections.append("## Design")
            sections.append("See [DESIGN.md](DESIGN.md) for the charm design rationale.")

        # Contributing.
        sections.append("## Contributing")
        sections.append(
            "```bash\n"
            "# Set up development environment\n"
            "tox -e format  # Format code\n"
            "tox -e lint    # Run linters\n"
            "tox -e unit    # Run unit tests\n"
            "```"
        )

        readme_content = "\n\n".join(sections) + "\n"

        readme_path = charm_path / "README.md"
        readme_path.write_text(readme_content)

        return ToolResult(
            success=True,
            output=f"Generated README.md ({len(readme_content)} bytes) at {readme_path}",
            data={"path": str(readme_path), "charm_name": charm_name},
        )
