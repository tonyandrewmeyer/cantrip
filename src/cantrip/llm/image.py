"""Image-generation provider abstraction (Phase 70.5 Painter).

Cantrip's text providers are a polished layer; image generation is
a separate API on every backend (Imagen, DALL-E, Stable Diffusion,
…) that doesn't fit ``LLMProvider``'s "messages → response" shape.
This module gives the Painter (``charm_icon_generate`` tool and
``/icon`` slash command) a small, swap-friendly surface so a future
provider can slot in behind the same interface.

The first concrete implementation wraps Google's ``google-genai``
Imagen models.  Other backends (OpenAI ``images.generate``,
Stability, locally-hosted Stable Diffusion) plug in by subclassing
``ImageProvider`` and registering in :func:`create_image_provider`.
"""

from __future__ import annotations

import abc
import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# Per-image USD estimate for the default Imagen model.  A real
# pricing table can land in :mod:`cantrip.llm.pricing` later; for
# the cost cap a flat per-image rate is enough to bound spend.
_IMAGEN_COST_PER_IMAGE_USD = 0.04

# Default model when the caller doesn't pass one explicitly.  Picked
# for the best price/quality tradeoff among Google's Imagen lineup
# at time of writing; override via ``state.icon_model`` per session.
DEFAULT_IMAGE_PROVIDER = "gemini"
DEFAULT_IMAGE_MODEL = "imagen-3.0-generate-002"


@dataclass
class ImageResult:
    """A single generated image plus accounting metadata.

    ``data`` is raw bytes (typically PNG); ``mime`` is the IANA
    media type so callers can choose between rastering, embedding,
    or vectorising.  ``cost_usd`` is the provider's best estimate
    for this single call — populated even when the underlying API
    doesn't return token usage, because image APIs price per-image.
    """

    data: bytes
    mime: str
    model: str
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageProvider(abc.ABC):
    """Base class for image-generation backends.

    Subclasses implement :meth:`generate`.  ``name`` and ``model``
    are short identifiers used in cost accounting and transcript
    events.  Keep the interface minimal — the Painter is
    deliberately a thin caller of "give me a PNG for this prompt",
    not a full image-model orchestration layer.
    """

    def __init__(self, *, model: str) -> None:
        self.model = model

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short provider identifier (``gemini``, ``openai``, …)."""

    @abc.abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        size: tuple[int, int] = (1024, 1024),
    ) -> ImageResult:
        """Generate one image for *prompt*.

        ``size`` is a hint — providers that only support fixed sizes
        return their nearest match.  Implementations should raise
        ``ImageGenerationError`` on provider failure rather than
        propagating the underlying exception so callers can present
        a uniform error message.
        """


class ImageGenerationError(RuntimeError):
    """Raised when an image provider fails to produce an image."""


# ---------------------------------------------------------------------------
# Gemini Imagen
# ---------------------------------------------------------------------------


class GeminiImageProvider(ImageProvider):
    """Image generation via Google Imagen through ``google-genai``.

    Constructed lazily so callers can probe for an API key without
    paying the SDK import cost up-front.  ``api_key`` falls back to
    ``$GEMINI_API_KEY`` / ``$GOOGLE_API_KEY`` to match the text
    provider's resolution order.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_IMAGE_MODEL,
        api_key: str | None = None,
    ) -> None:
        super().__init__(model=model)
        resolved = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not resolved:
            raise ValueError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) not provided — set the "
                "env var or pass api_key= to construct GeminiImageProvider."
            )
        self._api_key = resolved
        self._client: Any | None = None

    @property
    def name(self) -> str:
        return "gemini"

    def _get_client(self) -> Any:
        """Lazily build the genai client.

        Late import keeps the cold-start cost to importing this
        module zero — the Painter only loads google-genai when an
        icon is actually generated.
        """
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        size: tuple[int, int] = (1024, 1024),
    ) -> ImageResult:
        from google.genai import errors as genai_errors
        from google.genai import types as genai_types

        client = self._get_client()

        # Square aspect baked in: charm icons are 64×64 / 32×32 on
        # Charmhub, so we always ask for 1:1 and downscale on disk.
        config = genai_types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="1:1",
        )
        try:
            response = await client.aio.models.generate_images(
                model=self.model,
                prompt=prompt,
                config=config,
            )
        except genai_errors.APIError as exc:
            raise ImageGenerationError(f"Imagen call failed ({self.model}): {exc}") from exc

        generated = list(getattr(response, "generated_images", None) or [])
        if not generated:
            raise ImageGenerationError(
                f"Imagen returned no images for model {self.model}; "
                f"prompt may have been blocked by safety filters."
            )

        first = generated[0]
        image_obj = getattr(first, "image", None)
        data = getattr(image_obj, "image_bytes", None) if image_obj is not None else None
        if not data:
            raise ImageGenerationError(f"Imagen response for {self.model} carried no image bytes.")

        return ImageResult(
            data=bytes(data),
            mime="image/png",
            model=self.model,
            cost_usd=_IMAGEN_COST_PER_IMAGE_USD,
            metadata={"size_hint": list(size)},
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_image_provider(
    name: str | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> ImageProvider:
    """Construct an image provider by short name.

    ``name`` defaults to :data:`DEFAULT_IMAGE_PROVIDER`; ``model``
    defaults to :data:`DEFAULT_IMAGE_MODEL` when the provider is
    Gemini.  Unknown providers raise ``ValueError`` so the caller
    can surface a clear "not configured" message rather than
    crashing inside the SDK.
    """
    resolved_name = (name or DEFAULT_IMAGE_PROVIDER).lower()
    if resolved_name == "gemini":
        return GeminiImageProvider(
            model=model or DEFAULT_IMAGE_MODEL,
            api_key=api_key,
        )
    raise ValueError(f"Unknown image provider {resolved_name!r}; supported: gemini")


__all__ = [
    "DEFAULT_IMAGE_MODEL",
    "DEFAULT_IMAGE_PROVIDER",
    "GeminiImageProvider",
    "ImageGenerationError",
    "ImageProvider",
    "ImageResult",
    "create_image_provider",
]
