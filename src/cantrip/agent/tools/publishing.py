"""Charmhub publishing, README generation, icon, and documentation tools."""

import dataclasses
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import sqlite3
import subprocess
from typing import Any

import jinja2
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

        charm_path = pathlib.Path(charm_file)
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
                caption=f"Uploaded {charm_path.name} (rev {revision})"
                if revision is not None
                else f"Uploaded {charm_path.name}",
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
                caption=f"Released {name} r{revision} → {channel}",
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
        charm_path = pathlib.Path(path).resolve()
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


# ---------------------------------------------------------------------------
# Placeholder icon generation
# ---------------------------------------------------------------------------

# A curated palette of distinct, accessible colours for placeholder icons.
_ICON_COLOURS = [
    "#e74c3c",  # red
    "#e67e22",  # orange
    "#f1c40f",  # yellow
    "#2ecc71",  # green
    "#1abc9c",  # teal
    "#3498db",  # blue
    "#9b59b6",  # purple
    "#e91e63",  # pink
    "#00bcd4",  # cyan
    "#8bc34a",  # lime
]


def generate_placeholder_svg(charm_name: str) -> str:
    """Return a minimal SVG placeholder icon for *charm_name*.

    Produces a 256×256 SVG with a coloured circle and the charm's
    first letter centred in white.  The colour is deterministically
    chosen from the charm name so the same charm always gets the
    same icon.
    """
    initial = charm_name[0].upper() if charm_name else "?"
    colour_idx = int(hashlib.md5(charm_name.encode()).hexdigest(), 16) % len(_ICON_COLOURS)
    fill = _ICON_COLOURS[colour_idx]

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
        'viewBox="0 0 256 256">\n'
        f'  <circle cx="128" cy="128" r="120" fill="{fill}" />\n'
        f'  <text x="128" y="140" text-anchor="middle" '
        f'font-family="sans-serif" font-size="120" font-weight="bold" '
        f'fill="white">{initial}</text>\n'
        "</svg>\n"
    )


class GenerateIconTool(Tool):
    """Generate a placeholder icon.svg for a charm."""

    @property
    def name(self) -> str:
        return "generate_icon"

    @property
    def description(self) -> str:
        return (
            "Generate a placeholder icon.svg for a charm. Produces a simple "
            "coloured circle with the charm's initial letter, suitable for "
            "Charmhub listing. The user can replace it with real artwork later."
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
                "charm_name": {
                    "type": "string",
                    "description": (
                        "Charm name (used for the initial letter and colour). "
                        "If omitted, read from charmcraft.yaml."
                    ),
                },
            },
        }

    async def execute(self, path: str = ".", charm_name: str | None = None) -> ToolResult:
        """Generate icon.svg in the charm directory."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        # Determine charm name.
        if not charm_name:
            charmcraft_yaml = charm_dir / "charmcraft.yaml"
            if charmcraft_yaml.exists():
                try:
                    metadata = yaml.safe_load(charmcraft_yaml.read_text())
                    if isinstance(metadata, dict):
                        charm_name = metadata.get("name")
                except yaml.YAMLError:
                    pass
            if not charm_name:
                charm_name = charm_dir.name

        svg = generate_placeholder_svg(charm_name)
        icon_path = charm_dir / "icon.svg"
        icon_path.write_text(svg)

        return ToolResult(
            success=True,
            output=f"Generated placeholder icon.svg for '{charm_name}' at {icon_path}",
            data={"path": str(icon_path), "charm_name": charm_name},
            caption=f"Wrote icon.svg ({charm_name})",
        )


# ---------------------------------------------------------------------------
# Architecture diagram generation (Mermaid)
# ---------------------------------------------------------------------------


def generate_architecture_diagram(
    charm_name: str,
    metadata: dict[str, Any],
) -> str:
    """Generate a Mermaid architecture diagram from charm metadata.

    Shows the charm as a central node with its requires, provides, and
    peer relations as connected entities.  Containers (for K8s charms)
    appear as internal components.
    """
    lines: list[str] = ["graph LR"]

    # Central charm node.
    charm_id = _mermaid_id(charm_name)
    display = metadata.get("display-name", charm_name)
    lines.append(f"    {charm_id}[{display}]")

    # Containers (K8s charms).
    containers = metadata.get("containers", {})
    if containers:
        lines.append(f"    subgraph {charm_id}_containers[Containers]")
        for ctr_name in containers:
            ctr_id = _mermaid_id(f"ctr_{ctr_name}")
            lines.append(f"        {ctr_id}[/{ctr_name}/]")
        lines.append("    end")
        lines.append(f"    {charm_id} --- {charm_id}_containers")

    # Requires relations.
    requires = metadata.get("requires", {})
    for rel_name, rel_data in requires.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        provider_id = _mermaid_id(f"req_{rel_name}")
        label = f"{rel_name}\\n({iface})" if iface else rel_name
        lines.append(f"    {provider_id}({rel_name} provider) -- {label} --> {charm_id}")

    # Provides relations.
    provides = metadata.get("provides", {})
    for rel_name, rel_data in provides.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        requirer_id = _mermaid_id(f"prov_{rel_name}")
        label = f"{rel_name}\\n({iface})" if iface else rel_name
        lines.append(f"    {charm_id} -- {label} --> {requirer_id}({rel_name} requirer)")

    # Peers relations.
    peers = metadata.get("peers", {})
    for rel_name, rel_data in peers.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        peer_id = _mermaid_id(f"peer_{rel_name}")
        label = f"{rel_name}\\n({iface})" if iface else rel_name
        lines.append(f"    {charm_id} <-- {label} --> {peer_id}({rel_name} peer)")

    return "\n".join(lines) + "\n"


def _mermaid_id(name: str) -> str:
    """Convert a name to a valid Mermaid node ID."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


class GenerateDiagramTool(Tool):
    """Generate a Mermaid architecture diagram for a charm."""

    @property
    def name(self) -> str:
        return "generate_diagram"

    @property
    def description(self) -> str:
        return (
            "Generate a Mermaid architecture diagram from charmcraft.yaml "
            "showing the charm's relations, containers, and integrations. "
            "Writes architecture.md to the charm directory."
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
                "charm_name": {
                    "type": "string",
                    "description": ("Charm name. If omitted, read from charmcraft.yaml."),
                },
            },
        }

    async def execute(self, path: str = ".", charm_name: str | None = None) -> ToolResult:
        """Generate architecture.md with a Mermaid diagram."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        metadata = _read_charm_metadata(charm_dir)
        if not charm_name:
            charm_name = metadata.get("name", charm_dir.name)

        diagram = generate_architecture_diagram(charm_name, metadata)

        content = f"# {charm_name} — Architecture\n\n```mermaid\n{diagram}```\n"

        out_path = charm_dir / "architecture.md"
        out_path.write_text(content)

        return ToolResult(
            success=True,
            output=(f"Generated architecture diagram for '{charm_name}' at {out_path}"),
            data={"path": str(out_path), "charm_name": charm_name},
            caption=f"Wrote architecture.md ({charm_name})",
        )


# ---------------------------------------------------------------------------
# Documentation generation (Diátaxis + canonical starter pack)
# ---------------------------------------------------------------------------

# Jinja2 templates that back :func:`generate_docs_scaffold`.  Static skeleton
# only — dynamic loops (config options, action lists, integrations) are
# pre-rendered into ``*_block`` strings by the renderer below and substituted
# into the templates as a single placeholder.  Per Phase 85.6 of the roadmap.
_DOCS_TEMPLATE_DIR = pathlib.Path(__file__).parents[2] / "charm" / "docs_templates"
_DOCS_TEMPLATE_ENV: jinja2.Environment | None = None

# (output path relative to charm root, template path relative to docs_templates/).
# ``actions`` pages are appended conditionally below.
_DOCS_TEMPLATE_FILES: tuple[tuple[str, str], ...] = (
    ("docs/index.rst", "docs/index.rst.j2"),
    ("docs/tutorial/getting-started.md", "docs/tutorial/getting-started.md.j2"),
    ("docs/how-to/index.md", "docs/how-to/index.md.j2"),
    ("docs/how-to/deploy.md", "docs/how-to/deploy.md.j2"),
    ("docs/how-to/configure.md", "docs/how-to/configure.md.j2"),
    ("docs/how-to/integrate.md", "docs/how-to/integrate.md.j2"),
    ("docs/reference/index.md", "docs/reference/index.md.j2"),
    ("docs/reference/configuration.md", "docs/reference/configuration.md.j2"),
    ("docs/reference/integrations.md", "docs/reference/integrations.md.j2"),
    ("docs/explanation/index.md", "docs/explanation/index.md.j2"),
    ("docs/explanation/architecture.md", "docs/explanation/architecture.md.j2"),
    ("docs/conf.py", "docs/conf.py.j2"),
    ("docs/requirements.txt", "docs/requirements.txt.j2"),
    ("docs/.custom_wordlist.txt", "docs/custom_wordlist.txt.j2"),
    ("docs/.gitignore", "docs/gitignore.j2"),
    ("docs/Makefile", "docs/Makefile.j2"),
    (".readthedocs.yaml", "readthedocs.yaml.j2"),
)


def _docs_template_env() -> jinja2.Environment:
    """Return the shared docs Jinja env, creating it on first call."""
    global _DOCS_TEMPLATE_ENV  # noqa: PLW0603
    if _DOCS_TEMPLATE_ENV is None:
        _DOCS_TEMPLATE_ENV = jinja2.Environment(
            loader=jinja2.FileSystemLoader(_DOCS_TEMPLATE_DIR),
            keep_trailing_newline=True,
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _DOCS_TEMPLATE_ENV


def _read_charm_metadata(charm_dir: pathlib.Path) -> dict[str, Any]:
    """Read and return charmcraft.yaml metadata, or empty dict on failure."""
    charmcraft_yaml = charm_dir / "charmcraft.yaml"
    if not charmcraft_yaml.exists():
        return {}
    try:
        data = yaml.safe_load(charmcraft_yaml.read_text())
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


# ---------------------------------------------------------------------------
# Bridging Phase 13 root files (TUTORIAL.md / DEMO.md / architecture.md) into
# the Diátaxis tree so the docs/ site reflects what the agent actually did
# rather than the metadata-derived stubs.
# ---------------------------------------------------------------------------

# Map root-file name → docs/ destination path (without ``.md`` so the toctree
# entries match Sphinx's ``dirhtml`` link form).
_BRIDGE_TARGETS: dict[str, str] = {
    "TUTORIAL.md": "tutorial/getting-started",
    "DEMO.md": "how-to/deploy-and-verify",
    "architecture.md": "explanation/architecture",
}

# Markdown link / image regex.  Captures the bracket text and the URL
# separately so the alt/text can be preserved unchanged.
_MARKDOWN_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")

# Absolute-URL prefixes left untouched by the link rewriter.
_ABSOLUTE_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://|^//|^mailto:|^tel:")


def _replace_first_h1(content: str, new_heading: str) -> str:
    """Replace the first ATX H1 in *content* with *new_heading*.

    Falls back to prepending the heading when the source has no H1, so the
    bridged page always starts with one.
    """
    lines = content.splitlines()
    for i, line in enumerate(lines):
        # H1 is exactly one ``#`` followed by a space; ``##`` and deeper are
        # left alone.
        if line.startswith("# ") or line.rstrip() == "#":
            lines[i] = new_heading
            return "\n".join(lines) + ("\n" if content.endswith("\n") else "")
    prefix = new_heading + "\n\n"
    return prefix + content


def _rewrite_root_link(url: str) -> str:
    """Rewrite *url* (originally relative to the charm root) for a docs/<dir>/<page> file.

    - Absolute URLs and anchors are left as-is.
    - Cross-references to other bridged root files become docs/-tree links
      (``../how-to/deploy-and-verify`` etc.) so the rebuilt site still
      resolves them.
    - Other root-relative paths get a ``../../`` prefix to climb out of
      ``docs/<dir>/`` back to the charm root.

    All bridge destinations currently live at depth 2 (``docs/<dir>/<page>``),
    so the climb count is fixed at two.
    """
    if _ABSOLUTE_URL_RE.match(url) or url.startswith("#"):
        return url
    path, anchor = (url.split("#", 1) + [""])[:2]
    anchor_suffix = "#" + anchor if anchor else ""
    if path.startswith("./"):
        path = path[2:]
    if not path:
        return anchor_suffix or url
    # Already escaping out of a subdirectory — leave well alone.
    if path.startswith("../"):
        return url
    if path in _BRIDGE_TARGETS:
        return "../" + _BRIDGE_TARGETS[path] + anchor_suffix
    return "../../" + path + anchor_suffix


def _rewrite_links(content: str) -> str:
    """Apply :func:`_rewrite_root_link` to every Markdown link in *content*."""

    def _sub(match: re.Match[str]) -> str:
        bang, text, url, title = match.group(1), match.group(2), match.group(3), match.group(4)
        new_url = _rewrite_root_link(url)
        return f"{bang}[{text}]({new_url}{title or ''})"

    return _MARKDOWN_LINK_RE.sub(_sub, content)


def bridge_root_file(
    root_filename: str,
    content: str,
    display_name: str,
) -> tuple[str, str]:
    """Convert a charm-root demo file into its docs/-tree equivalent.

    Returns ``(docs_relative_path, rewritten_content)``.  Raises
    :class:`KeyError` for filenames that aren't bridged.
    """
    target = _BRIDGE_TARGETS[root_filename]
    docs_path = "docs/" + target + ".md"
    new_heading = _BRIDGE_HEADINGS[root_filename](display_name)
    rewritten = _replace_first_h1(content, new_heading)
    rewritten = _rewrite_links(rewritten)
    return docs_path, rewritten


# Heading rewrite per bridged file.  Tutorial and how-to pick up the charm's
# display name so the page reads naturally; architecture is just "Architecture"
# because the page title is enough context.
_BRIDGE_HEADINGS: dict[str, Any] = {
    "TUTORIAL.md": lambda display_name: f"# Get started with {display_name}",
    "DEMO.md": lambda display_name: f"# Deploy and verify {display_name}",
    "architecture.md": lambda _display_name: "# Architecture",
}


# Stub left at the charm root after a file has been bridged into ``docs/``.
# Keeps existing in-repo links from 404-ing while making the move discoverable.
_ROOT_STUB_TEMPLATE = (
    "# Moved\n"
    "\n"
    "This content now lives in [`{docs_path}`]({docs_path}).\n"
    "\n"
    "It was bridged into the Diátaxis tree by `generate_docs` so the\n"
    "documentation site builds from a single source.\n"
)


def _root_stub(docs_path: str) -> str:
    return _ROOT_STUB_TEMPLATE.format(docs_path=docs_path)


# ---------------------------------------------------------------------------
# Phase 74.2 — populate tutorial / how-to from acceptance-test artefacts.
# ---------------------------------------------------------------------------

# Phase 13's demo subagent leaves rich captured artefacts in ``demo/``
# (juju-status.txt, actions/<name>.json, …).  Phase 17 leaves a markdown
# summary at ``ACCEPTANCE.md``.  Together they're the "test transcript" the
# roadmap calls for: real commands the agent ran and the output it saw.

# IPv4 octet — 0–255 — used to avoid replacing version strings like 1.2.3.4
# that aren't valid IPv4 addresses (tightened a little vs the trivial
# four-dot pattern).  Each octet is 0–255.
_IPV4_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4_RE = re.compile(rf"\b{_IPV4_OCTET}(?:\.{_IPV4_OCTET}){{3}}\b")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_K8S_FQDN_RE = re.compile(r"\b[\w.-]+\.svc\.cluster\.local\b")
_SHA256_RE = re.compile(r"\bsha256:[0-9a-fA-F]{64}\b")


def sanitise_capture(text: str) -> str:
    """Replace cluster-specific identifiers in *text* with stable placeholders.

    Patterns replaced:

    - IPv4 addresses → ``<unit-ip>``
    - UUIDs (canonical 8-4-4-4-12 hex layout) → ``<model-uuid>``
    - Kubernetes service FQDNs (``*.svc.cluster.local``) → ``<svc-fqdn>``
    - OCI ``sha256:…`` digests → ``<image-sha256>``

    The replacements are intentionally conservative — we'd rather leak a
    rare false-negative than over-redact and produce docs that don't tell
    the reader what the charm actually does.  Versioned strings like
    ``1.2.3.4`` are caught by the IPv4 regex (octets 0–255) since they're
    syntactically valid IPv4 too; in the docs context this is fine.
    """
    text = _UUID_RE.sub("<model-uuid>", text)
    text = _SHA256_RE.sub("<image-sha256>", text)
    text = _K8S_FQDN_RE.sub("<svc-fqdn>", text)
    text = _IPV4_RE.sub("<unit-ip>", text)
    return text


@dataclasses.dataclass(frozen=True)
class AcceptanceArtefacts:
    """Bundle of acceptance-test artefacts read from a charm directory.

    Each field is already sanitised; callers can embed the values directly.
    """

    juju_status: str | None = None
    action_outputs: dict[str, str] = dataclasses.field(default_factory=dict)
    has_acceptance_md: bool = False

    @property
    def is_populated(self) -> bool:
        """True when at least one artefact is present."""
        return bool(self.juju_status) or bool(self.action_outputs) or self.has_acceptance_md


def load_acceptance_artefacts(charm_dir: pathlib.Path) -> AcceptanceArtefacts:
    """Read demo/ + ACCEPTANCE.md artefacts from *charm_dir*.

    Returns an empty :class:`AcceptanceArtefacts` when nothing is present
    (tests haven't run yet) — callers gate behaviour on
    :attr:`AcceptanceArtefacts.is_populated`.
    """
    juju_status: str | None = None
    status_path = charm_dir / "demo" / "juju-status.txt"
    if status_path.is_file():
        juju_status = sanitise_capture(status_path.read_text().rstrip())

    action_outputs: dict[str, str] = {}
    actions_dir = charm_dir / "demo" / "actions"
    if actions_dir.is_dir():
        for action_path in sorted(actions_dir.glob("*.json")):
            try:
                raw = action_path.read_text()
                # Pretty-print so the captured output reads naturally; if the
                # file isn't valid JSON, embed it as-is.
                payload = json.loads(raw)
                rendered = json.dumps(payload, indent=2, sort_keys=True)
            except json.JSONDecodeError:
                rendered = raw.rstrip()
            action_outputs[action_path.stem] = sanitise_capture(rendered)

    has_acceptance_md = (charm_dir / "ACCEPTANCE.md").is_file()

    return AcceptanceArtefacts(
        juju_status=juju_status,
        action_outputs=action_outputs,
        has_acceptance_md=has_acceptance_md,
    )


def _juju_status_excerpt(juju_status: str, *, max_lines: int = 30) -> str:
    """Trim *juju_status* to the first *max_lines* lines for inline embedding."""
    lines = juju_status.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    truncated = "\n".join(lines[:max_lines])
    return truncated + f"\n… ({len(lines) - max_lines} more lines elided)"


_STUB_FALLBACK_NOTICE = (
    "<!-- This page is templated.  Once acceptance tests run "
    "(`acceptance_report`), the agent will rebuild it from the captured "
    "deploy + test output. -->\n\n"
)


def _populate_tutorial_from_artefacts(
    charm_name: str,
    display_name: str,
    metadata: dict[str, Any],
    artefacts: AcceptanceArtefacts,
) -> str:
    """Build a real-output tutorial page from the captured artefacts."""
    requires = metadata.get("requires", {})
    actions = metadata.get("actions", {})

    sections: list[str] = [
        f"# Get started with {display_name}",
        "",
        f"This tutorial walks you through deploying {display_name} the way the agent",
        "did during acceptance testing.  Every command and every output block below",
        "is what the agent actually ran and saw — so the steps are reproducible.",
        "",
        "## Prerequisites",
        "",
        "- A Juju controller bootstrapped and ready",
        "",
        "## Add a model",
        "",
        "```console",
        f"$ juju add-model {charm_name}",
        "```",
        "",
        "## Deploy the charm",
        "",
        "```console",
        f"$ juju deploy {charm_name}",
        "```",
        "",
    ]

    if requires:
        sections.extend(["## Establish integrations", ""])
        for rel_name, rel_data in requires.items():
            iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
            sections.extend(
                [
                    "```console",
                    f"$ juju integrate {charm_name}:{rel_name} <provider>  # interface: {iface}",
                    "```",
                    "",
                ]
            )

    if artefacts.juju_status:
        sections.extend(
            [
                "## Verify the deployment",
                "",
                "```console",
                "$ juju status",
                _juju_status_excerpt(artefacts.juju_status),
                "```",
                "",
            ]
        )

    if actions and artefacts.action_outputs:
        first_action = next(iter(actions))
        if first_action in artefacts.action_outputs:
            sections.extend(
                [
                    f"## Exercise the `{first_action}` action",
                    "",
                    "```console",
                    f"$ juju run {charm_name}/leader {first_action}",
                    artefacts.action_outputs[first_action],
                    "```",
                    "",
                ]
            )

    sections.extend(
        [
            "## Next steps",
            "",
            "- Read the [how-to guides](../how-to/index) for common operations.",
            "- See the [configuration reference](../reference/configuration) "
            "for available options.",
            "",
        ]
    )

    return "\n".join(sections)


def _populate_actions_from_artefacts(
    charm_name: str,
    actions: dict[str, Any],
    artefacts: AcceptanceArtefacts,
) -> str:
    """Emit a per-action how-to with captured JSON output where available."""
    sections: list[str] = ["# Run actions", ""]
    for action_name, action_data in actions.items():
        desc = action_data.get("description", "") if isinstance(action_data, dict) else ""
        sections.append(f"## `{action_name}`")
        sections.append("")
        if desc:
            sections.append(desc)
            sections.append("")
        sections.append("```console")
        sections.append(f"$ juju run {charm_name}/leader {action_name}")
        if action_name in artefacts.action_outputs:
            sections.append(artefacts.action_outputs[action_name])
        sections.append("```")
        sections.append("")
    return "\n".join(sections)


def _populate_deploy_and_verify_from_artefacts(
    charm_name: str,
    display_name: str,
    metadata: dict[str, Any],
    artefacts: AcceptanceArtefacts,
) -> str:
    """Recipe-form deploy-and-verify page (no narrative, real output)."""
    requires = metadata.get("requires", {})
    sections: list[str] = [
        f"# Deploy and verify {display_name}",
        "",
        "Reproduce the deployment exactly as the agent ran it during acceptance",
        "testing.",
        "",
        "```console",
        f"$ juju add-model {charm_name}",
        f"$ juju deploy {charm_name}",
    ]
    for rel_name, rel_data in requires.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        sections.append(f"$ juju integrate {charm_name}:{rel_name} <provider>  # {iface}")
    sections.append("```")
    sections.append("")

    if artefacts.juju_status:
        sections.extend(
            [
                "Wait for the model to settle:",
                "",
                "```console",
                "$ juju status",
                _juju_status_excerpt(artefacts.juju_status),
                "```",
                "",
            ]
        )

    return "\n".join(sections)


def _build_integrations_block(charm_name: str, requires: dict[str, Any]) -> str:
    """Render the tutorial's Establish-integrations section, or '' when empty."""
    relation_lines = [
        f"juju integrate {charm_name} {rel_name}:"
        f"{rel_data.get('interface', '') if isinstance(rel_data, dict) else ''}"
        for rel_name, rel_data in requires.items()
    ]
    if not relation_lines:
        return ""
    return "\n## Establish integrations\n\n" + "".join(
        f"```bash\n{line}\n```\n\n" for line in relation_lines
    )


def _build_config_block(charm_name: str, config: dict[str, Any]) -> str:
    """Render the configure how-to body — sample blocks for the first three options."""
    config_lines = [
        f"```bash\njuju config {charm_name} {opt_name}=<value>\n```\n"
        for opt_name in list(config.keys())[:3]
    ]
    if config_lines:
        return "\n".join(config_lines)
    return f"```bash\njuju config {charm_name} <option>=<value>\n```\n"


def _build_integrate_block(
    charm_name: str, requires: dict[str, Any], provides: dict[str, Any]
) -> str:
    """Render the integrate how-to body, listing requires and provides relations."""
    integrate_lines: list[str] = []
    for rel_name, rel_data in requires.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        integrate_lines.append(
            f"### `{rel_name}` (`{iface}`)\n\n"
            f"```bash\njuju integrate {charm_name}:{rel_name} <provider>\n```\n"
        )
    for rel_name, rel_data in provides.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        integrate_lines.append(
            f"### `{rel_name}` (`{iface}`)\n\n"
            f"```bash\njuju integrate {charm_name}:{rel_name} <requirer>\n```\n"
        )
    if integrate_lines:
        return "\n".join(integrate_lines)
    return "This charm has no integrations defined yet.\n"


def _build_actions_block(charm_name: str, actions: dict[str, Any]) -> str:
    """Render the actions how-to body — one section per action, optional desc.

    Returned without a trailing newline; the template that consumes this
    block (``docs/how-to/actions.md.j2``) ends with ``{{ block }}\\n`` so
    the file lands with a single terminal newline.
    """
    action_lines: list[str] = []
    for action_name, action_data in actions.items():
        desc = action_data.get("description", "") if isinstance(action_data, dict) else ""
        action_lines.append(
            f"## `{action_name}`\n\n"
            + (f"{desc}\n\n" if desc else "")
            + f"```bash\njuju run {charm_name}/leader {action_name}\n```\n"
        )
    return "\n".join(action_lines).removesuffix("\n")


def _build_config_ref_block(config: dict[str, Any]) -> str:
    """Render the configuration reference body, one section per option.

    Returned without a trailing newline; see :func:`_build_actions_block`.
    """
    config_ref_lines: list[str] = []
    for opt_name, opt_data in config.items():
        opt_type = opt_data.get("type", "string")
        opt_desc = opt_data.get("description", "")
        opt_default = opt_data.get("default", "")
        entry = f"## `{opt_name}`\n\n"
        entry += f"- **Type:** `{opt_type}`\n"
        if opt_default not in ("", None):
            entry += f"- **Default:** `{opt_default}`\n"
        if opt_desc:
            entry += f"\n{opt_desc}\n"
        config_ref_lines.append(entry)
    if config_ref_lines:
        return "\n".join(config_ref_lines).removesuffix("\n")
    return "No configuration options are defined."


def _build_integ_ref_block(requires: dict[str, Any], provides: dict[str, Any]) -> str:
    """Render the integrations reference body, grouped by requires / provides.

    Returned without a trailing newline; see :func:`_build_actions_block`.
    """
    integ_ref_lines: list[str] = []
    if requires:
        integ_ref_lines.append("## Requires\n")
        for rel_name, rel_data in requires.items():
            iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
            integ_ref_lines.append(f"### `{rel_name}`\n\n- **Interface:** `{iface}`\n")
    if provides:
        integ_ref_lines.append("## Provides\n")
        for rel_name, rel_data in provides.items():
            iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
            integ_ref_lines.append(f"### `{rel_name}`\n\n- **Interface:** `{iface}`\n")
    if integ_ref_lines:
        return "\n".join(integ_ref_lines).removesuffix("\n")
    return "No integrations are defined."


def _build_actions_ref_block(actions: dict[str, Any]) -> str:
    """Render the actions reference body, with optional parameter tables.

    Returned without a trailing newline; see :func:`_build_actions_block`.
    """
    action_ref_lines: list[str] = []
    for action_name, action_data in actions.items():
        desc = ""
        params_block = ""
        if isinstance(action_data, dict):
            desc = action_data.get("description", "")
            params = action_data.get("params", {})
            if params:
                param_lines = []
                for p_name, p_data in params.items():
                    p_type = p_data.get("type", "string") if isinstance(p_data, dict) else ""
                    p_desc = p_data.get("description", "") if isinstance(p_data, dict) else ""
                    param_lines.append(f"  - `{p_name}` ({p_type}): {p_desc}")
                params_block = "- **Parameters:**\n" + "\n".join(param_lines) + "\n"
        entry = f"## `{action_name}`\n\n"
        if desc:
            entry += f"{desc}\n\n"
        if params_block:
            entry += f"{params_block}\n"
        action_ref_lines.append(entry)
    return "\n".join(action_ref_lines).removesuffix("\n")


def generate_docs_scaffold(
    charm_name: str,
    metadata: dict[str, Any],
    *,
    root_files: dict[str, str] | None = None,
    acceptance: AcceptanceArtefacts | None = None,
) -> dict[str, str]:
    """Generate a complete docs scaffold as a ``{relative_path: content}`` map.

    Follows the Diátaxis structure (tutorial, how-to, reference, explanation)
    and uses the Canonical starter pack conventions (Makefile, conf.py,
    requirements.txt, .readthedocs.yaml).  Content files are MyST Markdown.

    When *root_files* maps a known charm-root file (``TUTORIAL.md`` /
    ``DEMO.md`` / ``architecture.md``) to its current contents, the scaffold
    bridges that content into the matching ``docs/`` page rather than emitting
    the metadata-derived stub (Phase 74.1).

    When *acceptance* is populated (Phase 74.2), real captured commands and
    output from the demo/ tree replace the relevant templated stubs — the
    tutorial, the actions how-to, and the deploy-and-verify recipe.  Bridges
    from *root_files* still take precedence: the agent-authored ``TUTORIAL.md``
    is treated as authoritative over the artefact-derived version.
    """
    display_name = metadata.get("display-name") or metadata.get("name", charm_name)
    description = metadata.get("description", "")
    summary = metadata.get("summary", description.split("\n")[0] if description else "")
    source_url = metadata.get("source", "")

    config = metadata.get("config", {}).get("options", {})
    actions = metadata.get("actions", {})
    requires = metadata.get("requires", {})
    provides = metadata.get("provides", {})

    bridged_files: dict[str, str] = {}
    if root_files:
        for root_name, raw_content in root_files.items():
            if root_name not in _BRIDGE_TARGETS:
                continue
            docs_path, rewritten = bridge_root_file(root_name, raw_content, display_name)
            bridged_files[docs_path] = rewritten

    artefacts_present = bool(acceptance and acceptance.is_populated)

    howto_entries = ["deploy"]
    if "docs/how-to/deploy-and-verify.md" in bridged_files or artefacts_present:
        howto_entries.append("deploy-and-verify")
    howto_entries.extend(["configure", "integrate"])
    if actions:
        howto_entries.append("actions")

    ref_entries = ["configuration", "integrations"]
    if actions:
        ref_entries.append("actions")

    context: dict[str, Any] = {
        "charm_name": charm_name,
        "display_name": display_name,
        "summary": summary,
        "source_url": source_url,
        "year": datetime.date.today().year,
        "integrations_block": _build_integrations_block(charm_name, requires),
        "howto_entries_block": "".join(f"{entry}\n" for entry in howto_entries),
        "config_block": _build_config_block(charm_name, config),
        "integrate_block": _build_integrate_block(charm_name, requires, provides),
        "actions_block": _build_actions_block(charm_name, actions) if actions else "",
        "ref_entries_block": "".join(f"{entry}\n" for entry in ref_entries),
        "config_ref_block": _build_config_ref_block(config),
        "integ_ref_block": _build_integ_ref_block(requires, provides),
        "actions_ref_block": _build_actions_ref_block(actions) if actions else "",
        "description_block": f"{description}\n\n" if description else "",
        "architecture_diagram": generate_architecture_diagram(charm_name, metadata),
    }

    env = _docs_template_env()
    files: dict[str, str] = {
        output_path: env.get_template(template_path).render(**context)
        for output_path, template_path in _DOCS_TEMPLATE_FILES
    }
    if actions:
        files["docs/how-to/actions.md"] = env.get_template("docs/how-to/actions.md.j2").render(
            **context
        )
        files["docs/reference/actions.md"] = env.get_template(
            "docs/reference/actions.md.j2"
        ).render(**context)

    # ── Phase 74.2 — artefact-derived overrides ────────────────────────────
    # Real captured commands and output beat the metadata-derived stubs.
    # Bridged root files (74.1) win over both, so the order is:
    #     templated stubs  <  artefact-derived  <  bridged root files
    if artefacts_present:
        assert acceptance is not None
        files["docs/tutorial/getting-started.md"] = _populate_tutorial_from_artefacts(
            charm_name, display_name, metadata, acceptance
        )
        files["docs/how-to/deploy-and-verify.md"] = _populate_deploy_and_verify_from_artefacts(
            charm_name, display_name, metadata, acceptance
        )
        if actions:
            files["docs/how-to/actions.md"] = _populate_actions_from_artefacts(
                charm_name, actions, acceptance
            )
    else:
        # When acceptance hasn't run, mark each templated page so the reader
        # knows the content is generic until tests run.
        for stub_path in (
            "docs/tutorial/getting-started.md",
            "docs/how-to/deploy.md",
            "docs/how-to/integrate.md",
        ):
            if stub_path in files:
                files[stub_path] = _STUB_FALLBACK_NOTICE + files[stub_path]
        if "docs/how-to/actions.md" in files:
            files["docs/how-to/actions.md"] = (
                _STUB_FALLBACK_NOTICE + files["docs/how-to/actions.md"]
            )

    files.update(bridged_files)

    return files


class GenerateDocsTool(Tool):
    """Generate Diátaxis-structured documentation for a charm."""

    @property
    def name(self) -> str:
        return "generate_docs"

    @property
    def description(self) -> str:
        return (
            "Generate a docs/ directory with Diátaxis-structured documentation "
            "(tutorial, how-to, reference, explanation) using the Canonical "
            "starter pack. Reads charmcraft.yaml to populate configuration "
            "reference, actions, and integrations. Includes Makefile, conf.py, "
            "and .readthedocs.yaml for building with Sphinx."
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
                "charm_name": {
                    "type": "string",
                    "description": ("Charm name. If omitted, read from charmcraft.yaml."),
                },
            },
        }

    async def execute(self, path: str = ".", charm_name: str | None = None) -> ToolResult:
        """Generate the docs scaffold in the charm directory."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        metadata = _read_charm_metadata(charm_dir)
        if not charm_name:
            charm_name = metadata.get("name", charm_dir.name)

        # Pick up Phase 13 root files (TUTORIAL.md / DEMO.md / architecture.md)
        # so generate_docs_scaffold can bridge them into the docs/ tree.  We
        # only read files we'll actually bridge; the stub left at the root
        # afterwards isn't itself bridged on the next run because it lacks the
        # original page content.
        root_files: dict[str, str] = {}
        for root_name in _BRIDGE_TARGETS:
            root_path = charm_dir / root_name
            if not root_path.is_file():
                continue
            content = root_path.read_text()
            # Skip files that are already the post-bridge stub so re-runs
            # don't double-bridge a "Moved" pointer back into docs/.
            if content.lstrip().startswith("# Moved"):
                continue
            root_files[root_name] = content

        # Phase 74.2 — read demo/ + ACCEPTANCE.md so the scaffold can populate
        # tutorial / actions / deploy-and-verify with real captured output.
        acceptance = load_acceptance_artefacts(charm_dir)

        files = generate_docs_scaffold(
            charm_name, metadata, root_files=root_files, acceptance=acceptance
        )

        written: list[str] = []
        for rel_path, content in files.items():
            full_path = charm_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            written.append(rel_path)

        bridged: list[str] = []
        for root_name in root_files:
            target = _BRIDGE_TARGETS[root_name]
            docs_path = "docs/" + target + ".md"
            (charm_dir / root_name).write_text(_root_stub(docs_path))
            bridged.append(f"{root_name} → {docs_path}")

        summary = (
            f"Generated documentation scaffold for '{charm_name}' "
            f"({len(written)} files):\n"
            + "\n".join(f"  {f}" for f in sorted(written))
            + "\n\nBuild with: cd docs && make html"
        )
        if bridged:
            summary += "\n\nBridged from charm root:\n" + "\n".join(
                f"  {entry}" for entry in bridged
            )
        if acceptance.is_populated:
            populated_pages = ["docs/tutorial/getting-started.md"]
            populated_pages.append("docs/how-to/deploy-and-verify.md")
            if metadata.get("actions"):
                populated_pages.append("docs/how-to/actions.md")
            summary += "\n\nPopulated from acceptance artefacts:\n" + "\n".join(
                f"  {page}" for page in populated_pages
            )

        return ToolResult(
            success=True,
            output=summary,
            data={
                "charm_name": charm_name,
                "file_count": len(written),
                "files": sorted(written),
                "bridged": bridged,
                "acceptance_populated": acceptance.is_populated,
            },
            caption=f"Wrote {len(written)} doc{'s' if len(written) != 1 else ''}",
        )


# ---------------------------------------------------------------------------
# Phase 74.3 — extract design decisions from the session transcript and
# render them into docs/explanation/architecture.md as a chronological
# build log.  Driven by the same .cantrip SQLite store the agent already
# writes to via SessionStore.
# ---------------------------------------------------------------------------

# Marker that delimits the auto-generated section.  Anything above the
# marker is preserved across re-runs (charm-author intro); everything
# from the marker onwards gets refreshed.
_DECISIONS_MARKER = "<!-- cantrip-decisions-start -->"


def _read_decisions(db_path: pathlib.Path) -> list[dict[str, Any]]:
    """Read recorded design decisions from a Cantrip session SQLite file.

    Returns a chronologically-ordered list of ``{type, choice, reason,
    timestamp}`` dicts.  Returns an empty list when the file is missing,
    can't be opened, or doesn't have the ``decisions`` table — none of
    those should fail the documentation step.
    """
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT type, choice, reason, timestamp FROM decisions ORDER BY timestamp, id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            {
                "type": row["type"],
                "choice": row["choice"],
                "reason": row["reason"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def _scaffold_architecture_intro(charm_name: str, metadata: dict[str, Any]) -> str:
    """Render the same intro the docs scaffold would produce."""
    description = metadata.get("description", "")
    diagram = generate_architecture_diagram(charm_name, metadata)
    return (
        "# Architecture\n"
        "\n" + (f"{description}\n\n" if description else "") + "## Relation topology\n"
        "\n"
        "```mermaid\n"
        f"{diagram}"
        "```\n"
    )


def _resolve_architecture_intro(charm_dir: pathlib.Path) -> str:
    """Decide which intro content to put above the auto-generated decisions.

    Order of preference:

    1. ``docs/explanation/_intro.md`` — explicit charm-author override.
    2. Existing ``docs/explanation/architecture.md`` content above the
       :data:`_DECISIONS_MARKER` (everything below the marker is
       Cantrip-generated and gets refreshed).
    3. Existing ``docs/explanation/architecture.md`` with no marker —
       treated as fully user-authored, preserved verbatim.
    4. The scaffold's default intro (charm description + Mermaid
       relation diagram).
    """
    intro_path = charm_dir / "docs" / "explanation" / "_intro.md"
    if intro_path.is_file():
        return intro_path.read_text()

    arch_path = charm_dir / "docs" / "explanation" / "architecture.md"
    if arch_path.is_file():
        existing = arch_path.read_text()
        if _DECISIONS_MARKER in existing:
            return existing.split(_DECISIONS_MARKER, 1)[0]
        return existing

    metadata = _read_charm_metadata(charm_dir)
    charm_name = metadata.get("name", charm_dir.name)
    return _scaffold_architecture_intro(charm_name, metadata)


def _humanise_decision_type(type_label: str) -> str:
    """Render a snake_case decision type as a Title Case heading fragment."""
    # ``charm_path`` → ``Charm Path``; ``substrate`` → ``Substrate``.
    return " ".join(word.capitalize() for word in type_label.replace("-", "_").split("_"))


def format_decision_log(decisions: list[dict[str, Any]]) -> str:
    """Render *decisions* as a Markdown ``## Design decisions`` section.

    Each decision becomes a numbered ``###`` block with Decision, Recorded,
    Rationale, and Citation sub-fields when those values are present.
    Empty input yields a placeholder explaining that no decisions are
    recorded yet, so the page is still well-formed.
    """
    if not decisions:
        return (
            "## Design decisions\n"
            "\n"
            "No design decisions have been recorded yet.  This section "
            "fills in as the agent works through the design phase — "
            "substrate choice, charm path (12-Factor / Custom / "
            "Infrastructure), and any Charmhub recommendations land here "
            "with the rationale that drove them.\n"
        )

    lines = ["## Design decisions", ""]
    for index, decision in enumerate(decisions, start=1):
        type_label = _humanise_decision_type(decision["type"])
        lines.append(f"### {index}. {type_label}: {decision['choice']}")
        lines.append("")
        lines.append(f"- **Decision:** {decision['choice']}")
        if decision.get("timestamp"):
            lines.append(f"- **Recorded:** {decision['timestamp']}")
        lines.append(f"- **Citation:** session decisions table, entry {index}")
        if decision.get("reason"):
            lines.append("")
            lines.append(f"**Rationale:** {decision['reason']}")
        lines.append("")
    return "\n".join(lines)


def _compose_architecture_page(intro: str, decisions: list[dict[str, Any]]) -> str:
    """Stitch the intro and the auto-generated decision log together."""
    body = format_decision_log(decisions)
    intro = intro.rstrip()
    if not intro:
        intro = "# Architecture\n"
    return intro + "\n\n" + _DECISIONS_MARKER + "\n\n" + body


class ExtractDesignDecisionsTool(Tool):
    """Refresh ``docs/explanation/architecture.md`` with the chronological
    decision log mined from the session transcript.
    """

    @property
    def name(self) -> str:
        return "extract_design_decisions"

    @property
    def description(self) -> str:
        return (
            "Extract design decisions from the Cantrip session transcript "
            "(.cantrip SQLite) and render them as a chronological build "
            "log in docs/explanation/architecture.md.  Preserves any "
            "charm-author intro (docs/explanation/_intro.md or content "
            "above the cantrip-decisions-start marker)."
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
                "db_path": {
                    "type": "string",
                    "description": (
                        "Optional override for the .cantrip session-store "
                        "path.  Defaults to <path>/.cantrip."
                    ),
                },
            },
        }

    async def execute(self, path: str = ".", db_path: str | None = None) -> ToolResult:
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        store_path = pathlib.Path(db_path).resolve() if db_path else charm_dir / ".cantrip"
        decisions = _read_decisions(store_path)
        intro = _resolve_architecture_intro(charm_dir)
        content = _compose_architecture_page(intro, decisions)

        target = charm_dir / "docs" / "explanation" / "architecture.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

        summary = f"Refreshed {target.relative_to(charm_dir)} with {len(decisions)} decision(s)."
        if not decisions:
            summary += (
                "  No decisions recorded yet — the section explains "
                "that and refreshes when decisions land."
            )
        return ToolResult(
            success=True,
            output=summary,
            data={
                "path": str(target),
                "decision_count": len(decisions),
                "store_path": str(store_path),
            },
            caption=f"{len(decisions)} decision{'s' if len(decisions) != 1 else ''}",
        )


# ---------------------------------------------------------------------------
# Phase 74.4 — extract troubleshooting entries from the agent's debug
# history.  Walks the messages + subagent_messages tables for tool-result
# errors paired with the agent's diagnosis and the next successful tool
# call, then emits docs/how-to/troubleshooting.md grouped by category.
# ---------------------------------------------------------------------------

# Marker that delimits the auto-generated troubleshooting section.
_TROUBLESHOOTING_MARKER = "<!-- cantrip-generated below -->"

# Heuristics for grouping errors.  Keyword patterns are intentionally
# coarse — generation-time, no LLM call.  Order matters: the first match
# wins, so put more specific categories before general ones.
# Order matters: charm-stack-specific patterns (image, observability,
# secret, relation, hook) win over the generic transport-layer ones
# (network, storage) so an error mentioning a stack component lands in
# the bucket the operator looks at first.
_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "image",
        re.compile(
            r"\b(ImagePullBackOff|ErrImagePull|oci[\s-]image|registry|"
            r"manifest unknown|pull access denied|repository does not exist)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "observability",
        re.compile(
            r"\b(tempo|loki|grafana|prometheus|alertmanager|"
            r"otel|opentelemetry|tracing|metrics-endpoint)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "secret",
        re.compile(
            r"\b(secret-not-found|SecretNotFound|secret.*not.*owned|"
            r"unknown secret|access to.*secret denied)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "relation",
        re.compile(
            r"\b(relation[-_ ](not[-_ ]found|broken|departed)|"
            r"ENDPOINT_NOT_FOUND|RELATION_NOT_FOUND|"
            r"no relation to|interface mismatch|relation.*does not exist|"
            r"juju integrate.*failed)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hook",
        re.compile(
            # ``hook ... failed`` / ``hook ... error`` covers ``hook failed``,
            # ``hook 'install' failed``, ``hook install-error``, etc.
            r"\bhook\b.{0,40}\b(?:failed|error|not[\s_-]found)\b|"
            r"\b(?:install-error|charm hook|pebble-ready.*error|"
            r"config-changed.*error|upgrade-charm.*error)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "network",
        re.compile(
            r"\b(connection refused|no route to host|name or service not known|"
            r"timed? out|unreachable|dns|getaddrinfo|connection reset|"
            r"connection aborted|TLS handshake)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "storage",
        re.compile(
            r"\b(storage[-_ ]not[-_ ]found|persistentvolume|pvc|"
            r"insufficient storage|disk[ -]full|no space left)\b",
            re.IGNORECASE,
        ),
    ),
)


def _safe_load_json_field(raw: object) -> object:
    """Decode a JSON-text column, returning ``None`` on absence or corruption.

    Mirrors the helper in :mod:`cantrip.agent.store` but is local to
    :mod:`publishing` so the troubleshooting walker doesn't reach into
    the store module's internals.
    """
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str | bytes):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# Stable display order for the grouped report.
_CATEGORY_ORDER: tuple[str, ...] = (
    "relation",
    "hook",
    "secret",
    "image",
    "network",
    "storage",
    "observability",
    "general",
)

_CATEGORY_TITLES: dict[str, str] = {
    "relation": "Relation errors",
    "hook": "Hook failures",
    "secret": "Secret access errors",
    "image": "Image pull / OCI errors",
    "network": "Network errors",
    "storage": "Storage errors",
    "observability": "Observability stack errors",
    "general": "Other errors",
}

# Threshold below which an error is considered "trivial" — typo-shaped
# one-liners that don't warrant a troubleshooting entry.  Errors that
# match a non-general category are kept regardless.
_MIN_DIAGNOSTIC_LINES = 5

# Strip the ``<tool_result name='...'>`` wrapper Cantrip adds around tool
# results so the extracted excerpt is the actual error text.
_TOOL_RESULT_WRAP_RE = re.compile(
    r"^<tool_result\s+name=[^>]*>\n(.*)\n</tool_result>\s*$", re.DOTALL
)


def _categorise_error(text: str) -> str:
    """Bucket *text* into one of the known troubleshooting categories."""
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return "general"


def _strip_tool_result_wrapper(content: str) -> str:
    """Drop the ``<tool_result>`` wrapper Cantrip adds around tool output."""
    match = _TOOL_RESULT_WRAP_RE.match(content.strip())
    return match.group(1) if match else content.strip()


def _excerpt(text: str, *, max_lines: int = 12) -> str:
    """Return the first *max_lines* of *text* trimmed for embedding."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text.rstrip()
    return "\n".join(lines[:max_lines]) + f"\n… ({len(lines) - max_lines} more lines elided)"


@dataclasses.dataclass(frozen=True)
class TroubleshootingEntry:
    """A single troubleshooting entry mined from the transcript."""

    category: str
    symptom: str
    cause: str | None
    resolution: str | None
    citation: str  # Human-readable transcript pointer (e.g. ``message #42``).


def _read_transcript_pairs(db_path: pathlib.Path) -> list[TroubleshootingEntry]:
    """Mine error→fix pairs from the messages + subagent_messages tables.

    Walks each table chronologically.  For every assistant message whose
    tool results carry ``is_error=true``, captures:

    - **Symptom:** the wrapped tool-result content (stripped + excerpted).
    - **Cause:** the next assistant message's text content within the
      same source (main vs. subagent task) — this is typically the
      agent's diagnosis.
    - **Resolution:** the first subsequent assistant message that issues
      a successful tool call (any tool) within five turns.
    - **Citation:** "main message #N" or "subagent task <id> message #N".

    Returns an empty list when the database is missing or the relevant
    tables aren't present — generation-time best-effort, never raises.
    """
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        entries: list[TroubleshootingEntry] = []

        try:
            main_rows = list(
                conn.execute(
                    "SELECT id, role, content, tool_results, timestamp FROM messages ORDER BY id"
                )
            )
        except sqlite3.OperationalError:
            main_rows = []

        entries.extend(_pairs_from_message_stream(main_rows, source_label="main"))

        try:
            tasks = list(
                conn.execute("SELECT DISTINCT task_id FROM subagent_messages ORDER BY task_id")
            )
        except sqlite3.OperationalError:
            tasks = []

        for row in tasks:
            task_id = row["task_id"]
            sub_rows = list(
                conn.execute(
                    "SELECT message_index AS id, role, content, tool_results "
                    "FROM subagent_messages WHERE task_id = ? "
                    "ORDER BY message_index",
                    (task_id,),
                )
            )
            entries.extend(
                _pairs_from_message_stream(sub_rows, source_label=f"subagent/{task_id}")
            )

        return entries
    finally:
        conn.close()


def _pairs_from_message_stream(
    rows: list[sqlite3.Row], *, source_label: str
) -> list[TroubleshootingEntry]:
    """Extract ``TroubleshootingEntry`` records from one chronological stream.

    The stream is either the main agent's ``messages`` table or a single
    subagent task's slice of ``subagent_messages``.  Each error tool
    result kicks off a lookahead within the same stream — diagnoses and
    resolutions don't cross stream boundaries because conversations are
    independent.
    """
    entries: list[TroubleshootingEntry] = []
    for index, row in enumerate(rows):
        tool_results = _safe_load_json_field(row["tool_results"]) or []
        if not isinstance(tool_results, list):
            continue
        error_results = [tr for tr in tool_results if isinstance(tr, dict) and tr.get("is_error")]
        if not error_results:
            continue
        for error_result in error_results:
            raw_content = str(error_result.get("content", ""))
            symptom_text = _strip_tool_result_wrapper(raw_content)
            category = _categorise_error(symptom_text)
            line_count = len(symptom_text.splitlines())
            if category == "general" and line_count < _MIN_DIAGNOSTIC_LINES:
                continue
            cause = _next_assistant_text(rows, index)
            resolution = _next_successful_tool_call(rows, index)
            entries.append(
                TroubleshootingEntry(
                    category=category,
                    symptom=_excerpt(symptom_text),
                    cause=cause,
                    resolution=resolution,
                    citation=f"{source_label} message #{row['id']}",
                )
            )
    return entries


def _next_assistant_text(rows: list[sqlite3.Row], index: int) -> str | None:
    """Return the agent's next non-empty text reply within five turns."""
    for offset in range(1, 6):
        target = index + offset
        if target >= len(rows):
            return None
        next_row = rows[target]
        if next_row["role"] != "assistant":
            continue
        content = (next_row["content"] or "").strip()
        if content:
            return _excerpt(content, max_lines=8)
    return None


def _next_successful_tool_call(rows: list[sqlite3.Row], index: int) -> str | None:
    """Return a one-line summary of the next successful tool invocation."""
    for offset in range(1, 8):
        target = index + offset
        if target >= len(rows):
            return None
        next_row = rows[target]
        if next_row["role"] != "tool":
            continue
        next_results = _safe_load_json_field(next_row["tool_results"]) or []
        if not isinstance(next_results, list):
            continue
        for result in next_results:
            if isinstance(result, dict) and not result.get("is_error"):
                content = str(result.get("content", "")).strip()
                stripped = _strip_tool_result_wrapper(content)
                first_line = stripped.splitlines()[0] if stripped else "(empty)"
                return first_line[:140]
    return None


def _format_troubleshooting_entry(entry: TroubleshootingEntry, index: int) -> str:
    """Render a single entry as a Markdown ``### N. <symptom>`` block."""
    summary_line = entry.symptom.splitlines()[0] if entry.symptom else "(empty)"
    summary_line = summary_line[:80]
    sections: list[str] = [f"### {index}. {summary_line}", ""]
    sections.append("**Symptom:**")
    sections.append("")
    sections.append("```")
    sections.append(entry.symptom)
    sections.append("```")
    sections.append("")
    if entry.cause:
        sections.append("**Cause:** " + entry.cause.replace("\n", " "))
        sections.append("")
    if entry.resolution:
        sections.append("**Resolution:** " + entry.resolution)
        sections.append("")
    sections.append(f"**See also:** {entry.citation}")
    sections.append("")
    return "\n".join(sections)


def format_troubleshooting_page(entries: list[TroubleshootingEntry]) -> str:
    """Render *entries* grouped by category into a Markdown page section.

    Returns just the auto-generated body — no top-level heading and no
    intro — so the caller can compose it with marker-based preservation.
    """
    if not entries:
        return (
            "_No troubleshooting entries have been mined from the session "
            "transcript yet.  Entries appear here once the agent encounters "
            "and resolves errors during build / deploy / test._\n"
        )

    grouped: dict[str, list[TroubleshootingEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.category, []).append(entry)

    lines: list[str] = []
    for category in _CATEGORY_ORDER:
        bucket = grouped.get(category, [])
        if not bucket:
            continue
        lines.append(f"## {_CATEGORY_TITLES[category]}")
        lines.append("")
        for index, entry in enumerate(bucket, start=1):
            lines.append(_format_troubleshooting_entry(entry, index))
    return "\n".join(lines)


def _resolve_troubleshooting_intro(charm_dir: pathlib.Path) -> str:
    """Decide what intro content sits above the auto-generated section.

    Mirrors the architecture-page pattern: if a marker is present in an
    existing ``troubleshooting.md``, preserve everything above it; if
    the file exists without a marker, treat it as charm-author content
    and preserve verbatim; otherwise emit a default "Troubleshooting"
    heading.
    """
    path = charm_dir / "docs" / "how-to" / "troubleshooting.md"
    if path.is_file():
        existing = path.read_text()
        if _TROUBLESHOOTING_MARKER in existing:
            return existing.split(_TROUBLESHOOTING_MARKER, 1)[0]
        return existing
    return "# Troubleshooting\n\nCommon errors mined from this charm's build history.\n"


def _compose_troubleshooting_page(intro: str, body: str) -> str:
    """Stitch the intro and the auto-generated section together."""
    intro = intro.rstrip()
    if not intro:
        intro = "# Troubleshooting\n"
    return intro + "\n\n" + _TROUBLESHOOTING_MARKER + "\n\n" + body


def _ensure_troubleshooting_in_toctree(charm_dir: pathlib.Path) -> bool:
    """Add ``troubleshooting`` to ``docs/how-to/index.md`` if it isn't already.

    Returns True when the index file was modified.  No-op when the
    index doesn't exist (the next ``generate_docs`` will rebuild it
    from scratch and pick up the file via Phase 74.4 plumbing).
    """
    index_path = charm_dir / "docs" / "how-to" / "index.md"
    if not index_path.is_file():
        return False
    text = index_path.read_text()
    # Quick check — exact-line match avoids false positives from prose.
    if re.search(r"^troubleshooting$", text, re.MULTILINE):
        return False
    # Insert before the closing ```` ``` ```` of the toctree block.
    new_text, count = re.subn(
        r"(\n)```(\s*)$",
        r"\ntroubleshooting\n```\2",
        text,
        count=1,
    )
    if count == 0:
        return False
    index_path.write_text(new_text)
    return True


class ExtractTroubleshootingTool(Tool):
    """Render a troubleshooting page from error→fix pairs in the transcript."""

    @property
    def name(self) -> str:
        return "extract_troubleshooting"

    @property
    def description(self) -> str:
        return (
            "Mine the Cantrip session transcript (.cantrip SQLite) for "
            "error→fix pairs and write them as a categorised "
            "troubleshooting page at docs/how-to/troubleshooting.md.  "
            "Charm-author content above the cantrip-generated marker is "
            "preserved across re-runs."
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
                "db_path": {
                    "type": "string",
                    "description": (
                        "Optional override for the .cantrip session-store "
                        "path.  Defaults to <path>/.cantrip."
                    ),
                },
            },
        }

    async def execute(self, path: str = ".", db_path: str | None = None) -> ToolResult:
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        store_path = pathlib.Path(db_path).resolve() if db_path else charm_dir / ".cantrip"
        entries = _read_transcript_pairs(store_path)
        intro = _resolve_troubleshooting_intro(charm_dir)
        body = format_troubleshooting_page(entries)
        content = _compose_troubleshooting_page(intro, body)

        target = charm_dir / "docs" / "how-to" / "troubleshooting.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

        toctree_updated = _ensure_troubleshooting_in_toctree(charm_dir)

        category_counts: dict[str, int] = {}
        for entry in entries:
            category_counts[entry.category] = category_counts.get(entry.category, 0) + 1

        summary = f"Refreshed {target.relative_to(charm_dir)} with {len(entries)} entry/entries."
        if category_counts:
            summary += (
                "  By category: "
                + ", ".join(f"{cat} {count}" for cat, count in sorted(category_counts.items()))
                + "."
            )
        if toctree_updated:
            summary += "  Added 'troubleshooting' to docs/how-to/index.md toctree."
        return ToolResult(
            success=True,
            output=summary,
            data={
                "path": str(target),
                "entry_count": len(entries),
                "category_counts": category_counts,
                "store_path": str(store_path),
                "toctree_updated": toctree_updated,
            },
            caption=f"{len(entries)} entr{'ies' if len(entries) != 1 else 'y'}",
        )
