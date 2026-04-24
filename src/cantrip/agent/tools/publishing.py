"""Charmhub publishing, README generation, icon, and documentation tools."""

import datetime
import hashlib
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
        charm_dir = Path(path).resolve()
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
        charm_dir = Path(path).resolve()
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
        )


# ---------------------------------------------------------------------------
# Documentation generation (Diátaxis + canonical starter pack)
# ---------------------------------------------------------------------------


def _read_charm_metadata(charm_dir: Path) -> dict[str, Any]:
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


def generate_docs_scaffold(
    charm_name: str,
    metadata: dict[str, Any],
    *,
    root_files: dict[str, str] | None = None,
) -> dict[str, str]:
    """Generate a complete docs scaffold as a ``{relative_path: content}`` map.

    Follows the Diátaxis structure (tutorial, how-to, reference, explanation)
    and uses the Canonical starter pack conventions (Makefile, conf.py,
    requirements.txt, .readthedocs.yaml).  Content files are MyST Markdown.

    When *root_files* maps a known charm-root file (``TUTORIAL.md`` /
    ``DEMO.md`` / ``architecture.md``) to its current contents, the scaffold
    bridges that content into the matching ``docs/`` page rather than emitting
    the metadata-derived stub.
    """
    year = datetime.date.today().year
    display_name = metadata.get("display-name") or metadata.get("name", charm_name)
    description = metadata.get("description", "")
    summary = metadata.get("summary", description.split("\n")[0] if description else "")
    source_url = metadata.get("source", "")

    config = metadata.get("config", {}).get("options", {})
    actions = metadata.get("actions", {})
    requires = metadata.get("requires", {})
    provides = metadata.get("provides", {})

    files: dict[str, str] = {}

    # -- Root index (reStructuredText for Sphinx toctree compatibility) -----

    # Build the relations list for the tutorial.
    relation_lines: list[str] = []
    for rel_name, rel_data in requires.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        relation_lines.append(f"juju integrate {charm_name} {rel_name}:{iface}")

    files["docs/index.rst"] = (
        f"{display_name} documentation\n"
        f"{'=' * (len(display_name) + 14)}\n"
        f"\n"
        f"{summary}\n"
        f"\n"
        f"---------\n"
        f"\n"
        f"In this documentation\n"
        f"---------------------\n"
        f"\n"
        f".. grid:: 2\n"
        f"\n"
        f"   .. grid-item-card:: `Tutorial </tutorial/getting-started>`_\n"
        f"\n"
        f"      **Get started** - a hands-on introduction to {display_name}\n"
        f"\n"
        f"   .. grid-item-card:: `How-to guides </how-to/index>`_\n"
        f"\n"
        f"      **Step-by-step guides** - key operations and common tasks\n"
        f"\n"
        f"   .. grid-item-card:: `Reference </reference/index>`_\n"
        f"\n"
        f"      **Technical information** - configuration, actions, integrations\n"
        f"\n"
        f"   .. grid-item-card:: `Explanation </explanation/index>`_\n"
        f"\n"
        f"      **Discussion and clarification** - architecture and design decisions\n"
        f"\n"
        f".. toctree::\n"
        f"   :hidden:\n"
        f"   :maxdepth: 2\n"
        f"\n"
        f"   tutorial/getting-started\n"
        f"   how-to/index\n"
        f"   reference/index\n"
        f"   explanation/index\n"
    )

    # -- Tutorial -----------------------------------------------------------

    deploy_cmd = f"juju deploy {charm_name}"
    files["docs/tutorial/getting-started.md"] = (
        f"# Get started with {display_name}\n"
        f"\n"
        f"This tutorial walks you through deploying {display_name} and verifying\n"
        f"that it is running correctly.\n"
        f"\n"
        f"## Prerequisites\n"
        f"\n"
        f"- A Juju controller bootstrapped and ready\n"
        f"- A Juju model created (`juju add-model {charm_name}`)\n"
        f"\n"
        f"## Deploy the charm\n"
        f"\n"
        f"```bash\n"
        f"{deploy_cmd}\n"
        f"```\n"
        f"\n"
        f"Wait for the deployment to settle:\n"
        f"\n"
        f"```bash\n"
        f"juju wait-for application {charm_name} --query='status.current==\"active\"'\n"
        f"```\n"
        f"\n"
        f"## Verify the deployment\n"
        f"\n"
        f"Check that the application is active and idle:\n"
        f"\n"
        f"```bash\n"
        f"juju status\n"
        f"```\n"
        + (
            "\n## Establish integrations\n\n"
            + "".join(f"```bash\n{line}\n```\n\n" for line in relation_lines)
            if relation_lines
            else ""
        )
        + "\n## Next steps\n"
        "\n"
        "- Read the [how-to guides](../how-to/index) for common operations\n"
        "- See the [configuration reference](../reference/configuration) "
        "for available options\n"
    )

    # -- How-to guides ------------------------------------------------------

    bridged_files: dict[str, str] = {}
    if root_files:
        for root_name, raw_content in root_files.items():
            if root_name not in _BRIDGE_TARGETS:
                continue
            docs_path, rewritten = bridge_root_file(root_name, raw_content, display_name)
            bridged_files[docs_path] = rewritten

    howto_entries = ["deploy"]
    if "docs/how-to/deploy-and-verify.md" in bridged_files:
        howto_entries.append("deploy-and-verify")
    howto_entries.extend(["configure", "integrate"])
    if actions:
        howto_entries.append("actions")

    files["docs/how-to/index.md"] = (
        f"# How-to guides\n"
        f"\n"
        f"Step-by-step guides for key operations with {display_name}.\n"
        f"\n"
        f"```{{toctree}}\n"
        f":maxdepth: 1\n"
        f"\n" + "".join(f"{entry}\n" for entry in howto_entries) + "```\n"
    )

    files["docs/how-to/deploy.md"] = (
        f"# Deploy {display_name}\n"
        f"\n"
        f"## From Charmhub\n"
        f"\n"
        f"```bash\n"
        f"juju deploy {charm_name}\n"
        f"```\n"
        f"\n"
        f"## From a local `.charm` file\n"
        f"\n"
        f"```bash\n"
        f"juju deploy ./{charm_name}_amd64.charm\n"
        f"```\n"
    )

    # Configuration how-to.
    config_lines: list[str] = []
    for opt_name in list(config.keys())[:3]:
        config_lines.append(f"```bash\njuju config {charm_name} {opt_name}=<value>\n```\n")
    files["docs/how-to/configure.md"] = (
        f"# Configure {display_name}\n"
        f"\n"
        f"Set configuration options using `juju config`:\n"
        f"\n"
        + (
            "\n".join(config_lines)
            if config_lines
            else f"```bash\njuju config {charm_name} <option>=<value>\n```\n"
        )
        + "\nSee the [configuration reference](../reference/configuration) "
        "for the full list of options.\n"
    )

    # Integrations how-to.
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
    files["docs/how-to/integrate.md"] = (
        f"# Integrate {display_name}\n"
        f"\n"
        + (
            "\n".join(integrate_lines)
            if integrate_lines
            else "This charm has no integrations defined yet.\n"
        )
        + "\nSee the [integrations reference](../reference/integrations) "
        "for details.\n"
    )

    # Actions how-to (only if there are actions).
    if actions:
        action_lines: list[str] = []
        for action_name, action_data in actions.items():
            desc = ""
            if isinstance(action_data, dict):
                desc = action_data.get("description", "")
            action_lines.append(
                f"## `{action_name}`\n\n"
                + (f"{desc}\n\n" if desc else "")
                + f"```bash\njuju run {charm_name}/leader {action_name}\n```\n"
            )
        files["docs/how-to/actions.md"] = "# Run actions\n\n" + "\n".join(action_lines)

    # -- Reference ----------------------------------------------------------

    ref_toctree_entries = [
        "configuration",
        "integrations",
    ]
    if actions:
        ref_toctree_entries.append("actions")
    files["docs/reference/index.md"] = (
        f"# Reference\n"
        f"\n"
        f"Technical reference for {display_name}.\n"
        f"\n"
        f"```{{toctree}}\n"
        f":maxdepth: 1\n"
        f"\n" + "\n".join(ref_toctree_entries) + "\n"
        "```\n"
    )

    # Configuration reference.
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
    files["docs/reference/configuration.md"] = "# Configuration reference\n\n" + (
        "\n".join(config_ref_lines)
        if config_ref_lines
        else "No configuration options are defined.\n"
    )

    # Integrations reference.
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
    files["docs/reference/integrations.md"] = "# Integrations reference\n\n" + (
        "\n".join(integ_ref_lines) if integ_ref_lines else "No integrations are defined.\n"
    )

    # Actions reference (only if there are actions).
    if actions:
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
        files["docs/reference/actions.md"] = "# Actions reference\n\n" + "\n".join(
            action_ref_lines
        )

    # -- Explanation --------------------------------------------------------

    files["docs/explanation/index.md"] = (
        f"# Explanation\n"
        f"\n"
        f"Discussion and background information about {display_name}.\n"
        f"\n"
        f"```{{toctree}}\n"
        f":maxdepth: 1\n"
        f"\n"
        f"architecture\n"
        f"```\n"
    )

    diagram = generate_architecture_diagram(charm_name, metadata)
    files["docs/explanation/architecture.md"] = (
        "# Architecture\n"
        "\n" + (f"{description}\n\n" if description else "") + "## Relation topology\n"
        "\n"
        "```mermaid\n"
        f"{diagram}"
        "```\n"
        "\n"
        "## Charm design\n"
        "\n"
        "<!-- TODO: Describe the charm's architecture, Pebble layers, "
        "relation data flow, and operational patterns. -->\n"
    )

    # -- Build infrastructure -----------------------------------------------

    files["docs/conf.py"] = (
        f"import datetime\n"
        f"\n"
        f'project = "{display_name}"\n'
        f'author = "Canonical Ltd."\n'
        f"\n"
        f'html_title = project + " documentation"\n'
        f"\n"
        f'copyright = "{year}, %s" % author\n'
        f"\n"
        f"extensions = [\n"
        f'    "canonical_sphinx",\n'
        f"]\n"
        f"\n"
        f"html_context = {{\n"
        + (f'    "github_url": "{source_url}",\n' if source_url else "")
        + "}\n"
        "\n"
        "exclude_patterns = [\n"
        '    "_build",\n'
        '    ".sphinx",\n'
        "]\n"
    )

    files["docs/requirements.txt"] = "canonical-sphinx~=0.6\n"

    files["docs/.custom_wordlist.txt"] = f"{charm_name}\n{display_name}\nJuju\nCharmhub\nPebble\n"

    files["docs/.gitignore"] = "_build/\n.sphinx/\n"

    # Makefile — pull in the canonical starter pack Makefile via include.
    files["docs/Makefile"] = (
        "# Docs Makefile — canonical starter pack\n"
        "#\n"
        "# Install:  make install\n"
        "# Build:    make html\n"
        "# Serve:    make run\n"
        "\n"
        "SPHINX_DIR       ?= .sphinx\n"
        "SPHINX_OPTS      ?= -c . -d $(SPHINX_DIR)/.doctrees -j auto\n"
        "SPHINX_BUILD     ?= $(DOCS_VENVDIR)/bin/sphinx-build\n"
        "SPHINX_HOST      ?= 127.0.0.1\n"
        "SPHINX_PORT      ?= 8000\n"
        "DOCS_VENVDIR     ?= $(SPHINX_DIR)/venv\n"
        "DOCS_VENV        ?= $(DOCS_VENVDIR)/bin/activate\n"
        "DOCS_SOURCEDIR   ?= .\n"
        "DOCS_BUILDDIR    ?= _build\n"
        "\n"
        "help:\n"
        "\t@echo\n"
        '\t@echo "  make run        — watch, build and serve the documentation"\n'
        '\t@echo "  make html       — build HTML output"\n'
        '\t@echo "  make serve      — serve already-built documentation"\n'
        '\t@echo "  make clean-doc  — clean built doc files"\n'
        '\t@echo "  make clean      — clean full environment"\n'
        '\t@echo "  make install    — set up the build environment"\n'
        "\t@echo\n"
        "\n"
        ".PHONY: help html run serve install clean clean-doc\n"
        "\n"
        "$(DOCS_VENVDIR):\n"
        "\t@echo '... setting up virtualenv'\n"
        "\tpython3 -m venv $(DOCS_VENVDIR)\n"
        "\t. $(DOCS_VENV); pip install --upgrade -r requirements.txt \\\n"
        "\t    --log $(DOCS_VENVDIR)/pip_install.log\n"
        "\t@touch $(DOCS_VENVDIR)\n"
        "\n"
        "install: $(DOCS_VENVDIR)\n"
        "\n"
        "run: install\n"
        "\t. $(DOCS_VENV); sphinx-autobuild -b dirhtml "
        '"$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" $(SPHINX_OPTS) '
        "--host $(SPHINX_HOST) --port $(SPHINX_PORT)\n"
        "\n"
        "html: install\n"
        "\t. $(DOCS_VENV); $(SPHINX_BUILD) -b dirhtml "
        '"$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" $(SPHINX_OPTS)\n'
        "\n"
        "serve:\n"
        '\tcd "$(DOCS_BUILDDIR)" && python3 -m http.server '
        "$(SPHINX_PORT) --bind $(SPHINX_HOST)\n"
        "\n"
        "clean: clean-doc\n"
        '\t@test ! -e "$(DOCS_VENVDIR)" -o '
        '-d "$(DOCS_VENVDIR)" && rm -rf $(DOCS_VENVDIR)\n'
        "\n"
        "clean-doc:\n"
        '\t@test ! -e "$(DOCS_BUILDDIR)" -o '
        '-d "$(DOCS_BUILDDIR)" && rm -rf $(DOCS_BUILDDIR)\n'
    )

    # ReadTheDocs configuration.
    files[".readthedocs.yaml"] = (
        "# Read the Docs configuration\n"
        "# https://docs.readthedocs.io/en/stable/config-file/v2.html\n"
        "\n"
        "version: 2\n"
        "\n"
        "build:\n"
        "  os: ubuntu-22.04\n"
        "  tools:\n"
        "    python: '3.12'\n"
        "  jobs:\n"
        "    post_checkout:\n"
        "      - git fetch --unshallow || true\n"
        "\n"
        "sphinx:\n"
        "  builder: dirhtml\n"
        "  configuration: docs/conf.py\n"
        "  fail_on_warning: true\n"
        "\n"
        "python:\n"
        "  install:\n"
        "    - requirements: docs/requirements.txt\n"
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
        charm_dir = Path(path).resolve()
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

        files = generate_docs_scaffold(charm_name, metadata, root_files=root_files)

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

        return ToolResult(
            success=True,
            output=summary,
            data={
                "charm_name": charm_name,
                "file_count": len(written),
                "files": sorted(written),
                "bridged": bridged,
            },
        )
