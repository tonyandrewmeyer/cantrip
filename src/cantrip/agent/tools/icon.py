"""Painter — LLM-driven charm icon generation (Phase 70.5).

Every Charmhub charm ships an ``icon.svg`` at the project root.  The
existing :class:`cantrip.agent.tools.publishing.GenerateIconTool`
writes a deterministic placeholder (a coloured circle with the charm's
initial); this tool, ``charm_icon_generate``, is the upgrade path —
it routes a structured prompt to an image-generation provider
(default Imagen via Google's ``google-genai`` SDK) and writes the
returned PNG into ``icon.svg`` as an embedded base64 ``<image>``
element.

Why embed PNG in SVG rather than vectorise?  Reliable SVG generation
from image models is still weak; rastering then tracing (potrace) is
a follow-up that adds a heavy dependency.  An embedded-PNG SVG is
valid SVG, Charmhub accepts it, and the doc page tells the user a
designer-polish pass is recommended before release — same honesty as
the Phase 70.5 spec calls for.

A session-level USD cap (``state.icon_max_session_cost_usd``) bounds
spend so iterating on an icon can't burn the budget.  The tool refuses
to overwrite a non-default ``icon.svg`` unless the caller passes
``force=true`` — files matching the deterministic placeholder shape or
carrying the ``cantrip-icon-generated`` marker we write on success
are treated as expendable.
"""

from __future__ import annotations

import base64
import logging
import pathlib
from collections.abc import Callable
from typing import Any

import yaml

from cantrip.agent.state import AgentState
from cantrip.agent.store import SessionStore
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.llm.image import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_IMAGE_PROVIDER,
    ImageGenerationError,
    ImageProvider,
    ImageResult,
    create_image_provider,
)

log = logging.getLogger(__name__)

# Charmhub icon style guidance, baked into every Painter prompt.  The
# constraints are non-negotiable: square, no embedded text (icons are
# rendered at 32×32), high contrast for dark/light theme switching.
_ICON_STYLE_PROMPT = (
    "Charmhub charm icon: square, flat, simple, high-contrast, "
    "single recognisable subject centred on a solid colour "
    "background.  Legible at 64×64 and 32×32 pixels.  No embedded "
    "text, no gradients, no fine detail.  Suitable for a software "
    "operator icon listed alongside other charms."
)

# Marker comment we embed in every generated SVG so a regenerate
# loop can tell "this came from us, safe to overwrite" from "the
# user dropped real artwork here".
_GENERATED_MARKER = "cantrip-icon-generated"

# Substring fingerprint of the Phase 7 placeholder generator
# (``GenerateIconTool``).  When the existing icon contains this
# pattern we treat it as an expendable placeholder, matching the
# behaviour the placeholder tool ships today.
_PLACEHOLDER_FINGERPRINT = '<circle cx="128" cy="128"'

# Type alias for the image-provider factory.  Tests inject a stub
# that returns a deterministic provider; production passes
# :func:`cantrip.llm.image.create_image_provider`.
ImageProviderFactory = Callable[[str | None, str | None], ImageProvider]


def _default_factory(provider_name: str | None, model: str | None) -> ImageProvider:
    """Production image-provider factory."""
    return create_image_provider(provider_name, model=model)


def _read_charm_name(charm_dir: pathlib.Path) -> str | None:
    """Extract the charm's name from ``charmcraft.yaml``, if present."""
    charmcraft_yaml = charm_dir / "charmcraft.yaml"
    if not charmcraft_yaml.is_file():
        return None
    try:
        metadata = yaml.safe_load(charmcraft_yaml.read_text())
    except (OSError, yaml.YAMLError):
        return None
    if isinstance(metadata, dict):
        name = metadata.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _existing_icon_is_expendable(icon_path: pathlib.Path) -> bool:
    """Decide whether an existing ``icon.svg`` is safe to overwrite.

    Files we wrote ourselves (carrying the marker) and the Phase 7
    placeholder shape are expendable; anything else is treated as
    user-supplied art and refused unless ``force=true``.
    """
    if not icon_path.exists():
        return True
    try:
        content = icon_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Unreadable existing file — refuse rather than overwrite.
        return False
    if _GENERATED_MARKER in content:
        return True
    return _PLACEHOLDER_FINGERPRINT in content


def _build_prompt(
    charm_name: str,
    description: str,
    palette_hint: str | None,
) -> str:
    """Compose the structured prompt sent to the image provider."""
    parts: list[str] = [_ICON_STYLE_PROMPT]
    parts.append(f"Charm: {charm_name}.")
    if description.strip():
        parts.append(f"Workload: {description.strip()}.")
    if palette_hint and palette_hint.strip():
        parts.append(f"Palette hint: {palette_hint.strip()}.")
    return " ".join(parts)


def _embed_png_in_svg(png_bytes: bytes, charm_name: str) -> str:
    """Wrap a PNG in a valid Charmhub-style SVG envelope.

    The SVG ``<image>`` element references the PNG via a base64
    ``data:`` URL, so the file is one self-contained artefact (no
    sibling PNG to ship).  A leading XML comment carries the
    :data:`_GENERATED_MARKER` so a future regeneration knows it can
    overwrite the file safely.
    """
    encoded = base64.b64encode(png_bytes).decode("ascii")
    safe_name = charm_name.replace("--", "-").strip()
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<!-- {_GENERATED_MARKER}: charm={safe_name}; "
        "raster — designer-polish recommended before release -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="256" height="256" viewBox="0 0 256 256">\n'
        '  <image x="0" y="0" width="256" height="256" '
        f'href="data:image/png;base64,{encoded}" />\n'
        "</svg>\n"
    )


class CharmIconGenerateTool(Tool):
    """Generate a charm icon via an image-generation provider."""

    def __init__(
        self,
        state: AgentState,
        *,
        store_getter: Callable[[], SessionStore | None] | None = None,
        provider_factory: ImageProviderFactory | None = None,
    ) -> None:
        self._state = state
        self._store_getter = store_getter
        self._provider_factory: ImageProviderFactory = provider_factory or _default_factory

    @property
    def name(self) -> str:
        return "charm_icon_generate"

    @property
    def description(self) -> str:
        return (
            "Generate a Charmhub-style icon.svg for a charm using an "
            "image-generation provider (default: Google Imagen).  Embeds "
            "the returned PNG inside a valid SVG envelope so the file is "
            "ready to commit.  Refuses to overwrite a non-default icon "
            "unless force=true.  Bounded by a per-session USD cap "
            "(state.icon_max_session_cost_usd, default $1)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": (
                        "One-line workload description "
                        "(e.g. 'PostgreSQL database', 'LDAP server')."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Charm directory (default: current working dir).",
                    "default": ".",
                },
                "charm_name": {
                    "type": "string",
                    "description": (
                        "Charm name; defaults to the value in "
                        "charmcraft.yaml or the directory name."
                    ),
                },
                "palette_hint": {
                    "type": "string",
                    "description": (
                        "Optional colour or style hint (e.g. 'cool blues', 'Canonical orange')."
                    ),
                },
                "force": {
                    "type": "boolean",
                    "description": (
                        "Overwrite an existing icon.svg even when it "
                        "doesn't look like a placeholder (default: false)."
                    ),
                },
            },
            "required": ["description"],
        }

    async def execute(
        self,
        description: str,
        path: str = ".",
        charm_name: str | None = None,
        palette_hint: str | None = None,
        force: bool = False,
    ) -> ToolResult:
        """Generate icon.svg in *path* (default: cwd) for *description*."""
        description = (description or "").strip()
        if not description:
            return ToolResult(
                success=False,
                output="",
                error="charm_icon_generate requires a non-empty description.",
            )

        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Charm directory not found: {path}",
            )

        if not charm_name:
            charm_name = _read_charm_name(charm_dir) or charm_dir.name

        icon_path = charm_dir / "icon.svg"
        if icon_path.exists() and not force and not _existing_icon_is_expendable(icon_path):
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Refusing to overwrite existing {icon_path} — the "
                    f"file does not look like a placeholder.  Pass "
                    f"force=true to replace it."
                ),
                data={"path": str(icon_path), "skipped": True},
            )

        budget_error = self._check_budget()
        if budget_error is not None:
            return budget_error

        provider_name = self._state.icon_provider_name or DEFAULT_IMAGE_PROVIDER
        model_name = self._state.icon_model or DEFAULT_IMAGE_MODEL

        try:
            provider = self._provider_factory(provider_name, model_name)
        except ValueError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to construct image provider: {exc}",
            )

        prompt = _build_prompt(charm_name, description, palette_hint)
        try:
            result: ImageResult = await provider.generate(prompt)
        except ImageGenerationError as exc:
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
            )

        try:
            svg = _embed_png_in_svg(result.data, charm_name)
            icon_path.write_text(svg, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to write {icon_path}: {exc}",
            )

        self._state.icon_calls_total += 1
        self._state.icon_session_cost_usd += result.cost_usd

        self._record_event(
            charm_name=charm_name,
            description=description,
            palette_hint=palette_hint,
            provider_name=provider.name,
            model_name=result.model,
            cost_usd=result.cost_usd,
            icon_path=icon_path,
        )

        summary = (
            f"Generated icon.svg for '{charm_name}' at {icon_path}.\n"
            f"- model: {provider.name}/{result.model}\n"
            f"- cost: ≈ ${result.cost_usd:.4f} "
            f"(session ≈ ${self._state.icon_session_cost_usd:.4f} of "
            f"${self._state.icon_max_session_cost_usd:.2f} cap)\n"
            f"- format: PNG embedded in SVG; designer-polish recommended "
            f"before release."
        )
        return ToolResult(
            success=True,
            output=summary,
            data={
                "path": str(icon_path),
                "charm_name": charm_name,
                "provider": provider.name,
                "model": result.model,
                "cost_usd": result.cost_usd,
                "session_cost_usd": self._state.icon_session_cost_usd,
                "calls_total": self._state.icon_calls_total,
                "embedded_png": True,
            },
            caption=f"Painted icon.svg ({charm_name})",
        )

    def _check_budget(self) -> ToolResult | None:
        """Refuse early when the session cost cap is already exhausted."""
        if self._state.icon_session_cost_usd >= self._state.icon_max_session_cost_usd:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Painter session cost cap reached "
                    f"(${self._state.icon_session_cost_usd:.2f} of "
                    f"${self._state.icon_max_session_cost_usd:.2f}).  "
                    "Raise state.icon_max_session_cost_usd to keep "
                    "generating icons."
                ),
            )
        return None

    def _record_event(
        self,
        *,
        charm_name: str,
        description: str,
        palette_hint: str | None,
        provider_name: str,
        model_name: str,
        cost_usd: float,
        icon_path: pathlib.Path,
    ) -> None:
        if self._store_getter is None:
            return
        store = self._store_getter()
        if store is None:
            return
        try:
            store.record_event(
                "icon_generated",
                {
                    "charm_name": charm_name,
                    "description": description,
                    "palette_hint": palette_hint,
                    "provider": provider_name,
                    "model": model_name,
                    "cost_usd": cost_usd,
                    "icon_path": str(icon_path),
                    "session_cost_usd": self._state.icon_session_cost_usd,
                    "calls_total": self._state.icon_calls_total,
                },
            )
        except (OSError, ValueError, RuntimeError) as exc:
            # Recording failure must not break the tool — the icon
            # already exists on disk.  Log loudly so audits aren't
            # lost silently.
            log.warning("Failed to record icon_generated event: %s", exc)


__all__ = [
    "CharmIconGenerateTool",
    "ImageProviderFactory",
]
