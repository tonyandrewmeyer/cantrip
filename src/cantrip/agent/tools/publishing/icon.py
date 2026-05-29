"""Placeholder icon generation for Charmhub listings."""

import hashlib
import pathlib
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult

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
                    metadata = yaml.safe_load(charmcraft_yaml.read_text(errors="replace"))
                    if isinstance(metadata, dict):
                        charm_name = metadata.get("name")
                except (yaml.YAMLError, RecursionError):
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
