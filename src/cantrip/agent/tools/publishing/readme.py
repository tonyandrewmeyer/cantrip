"""README.md generation from charm metadata."""

import pathlib
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult


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
        charm_path = pathlib.Path(path).resolve()
        charmcraft_yaml = charm_path / "charmcraft.yaml"

        if not charmcraft_yaml.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"charmcraft.yaml not found in {path}",
            )

        try:
            metadata = yaml.safe_load(charmcraft_yaml.read_text(errors="replace"))
        except (yaml.YAMLError, RecursionError) as exc:
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

        # Architecture diagram.  Prefer the docs/-tree home (Phase 74.1) so
        # the README points at whatever the published site builds from.
        bridged_arch = charm_path / "docs" / "explanation" / "architecture.md"
        legacy_arch = charm_path / "architecture.md"
        if bridged_arch.exists():
            sections.append("## Architecture")
            sections.append(
                "See [docs/explanation/architecture.md]"
                "(docs/explanation/architecture.md) for the relation and "
                "container topology diagram."
            )
        elif legacy_arch.exists():
            sections.append("## Architecture")
            sections.append(
                "See [architecture.md](architecture.md) for the relation and "
                "container topology diagram."
            )

        # Demo and tutorial links.  Bridged docs/ pages take precedence over
        # the original root files; fall back to the root files when the bridge
        # has not run yet.
        bridged_tutorial = charm_path / "docs" / "tutorial" / "getting-started.md"
        bridged_demo = charm_path / "docs" / "how-to" / "deploy-and-verify.md"
        legacy_demo = charm_path / "DEMO.md"
        legacy_tutorial = charm_path / "TUTORIAL.md"
        juju_status_path = charm_path / "demo" / "juju-status.txt"
        has_demo_section = (
            bridged_tutorial.exists()
            or bridged_demo.exists()
            or legacy_demo.exists()
            or legacy_tutorial.exists()
        )
        if has_demo_section:
            sections.append("## Demo")
            if bridged_tutorial.exists():
                sections.append(
                    "See [docs/tutorial/getting-started.md]"
                    "(docs/tutorial/getting-started.md) for a guided walk-through."
                )
            elif legacy_tutorial.exists():
                sections.append("See [TUTORIAL.md](TUTORIAL.md) for a guided walk-through.")
            if bridged_demo.exists():
                sections.append(
                    "See [docs/how-to/deploy-and-verify.md]"
                    "(docs/how-to/deploy-and-verify.md) for an annotated demo "
                    "with real command output and screenshots."
                )
            elif legacy_demo.exists():
                sections.append(
                    "See [DEMO.md](DEMO.md) for an annotated demo with real "
                    "command output and screenshots."
                )
            if juju_status_path.exists():
                sections.append(
                    "\n<details><summary>juju status</summary>\n\n"
                    "```\n" + juju_status_path.read_text().rstrip() + "\n```\n\n"
                    "</details>"
                )

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
            caption=f"Wrote README.md ({len(readme_content)} bytes)",
        )
