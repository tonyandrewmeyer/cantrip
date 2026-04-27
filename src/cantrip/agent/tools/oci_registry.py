"""Docker Hub registry tools for searching and inspecting OCI images."""

from typing import Any

import httpx

from cantrip.agent.tools.base import Tool, ToolResult

# Cap search results to avoid blowing up the LLM context window.
MAX_SEARCH_RESULTS = 15

_SEARCH_URL = "https://hub.docker.com/v2/search/repositories/"
_REPO_URL = "https://hub.docker.com/v2/repositories"


def _normalise_image(image: str) -> tuple[str, str]:
    """Split an image reference into (namespace, repository).

    Bare names like ``redis`` are expanded to ``library/redis``
    (the Docker Hub convention for official images).
    """
    if "/" in image:
        parts = image.split("/", 1)
        return parts[0], parts[1]
    return "library", image


def _format_bytes(n: int) -> str:
    """Format a byte count as a human-readable size string.

    Examples: ``"123 MB"``, ``"1.2 GB"``.
    """
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.0f} KB"
    return f"{n} B"


def _format_count(n: int) -> str:
    """Format a large count with a human-readable suffix.

    Examples: ``"456K"``, ``"1.2B"``.
    """
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


class RegistrySearchTool(Tool):
    """Search Docker Hub for OCI images."""

    @property
    def name(self) -> str:
        return "registry_search"

    @property
    def description(self) -> str:
        return (
            "Search Docker Hub for OCI images matching a query."
            " Returns image name, description, star count, pull count,"
            " and whether the image is official."
            " Use this to find existing images for K8s charm OCI resources."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'redis', 'postgresql', 'nginx').",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str) -> ToolResult:
        """Search Docker Hub for images matching *query*."""
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params={"query": query, "page_size": 25},
                )
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out searching Docker Hub for '{query}'",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {exc.response.status_code} searching Docker Hub for '{query}'",
                data={"status_code": exc.response.status_code, "query": query},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error searching Docker Hub: {exc}",
            )
        except ValueError as exc:
            # ``json.JSONDecodeError`` is a ``ValueError`` subclass.  A
            # 200 with non-JSON (captive portal, broken CDN edge) used
            # to crash this tool with an unhandled traceback.
            return ToolResult(
                success=False,
                output="",
                error=f"Docker Hub returned non-JSON response for '{query}': {exc}",
            )

        raw_results = body.get("results", []) if isinstance(body, dict) else []
        total = len(raw_results)
        truncated = total > MAX_SEARCH_RESULTS
        results = raw_results[:MAX_SEARCH_RESULTS]

        formatted: list[dict[str, Any]] = []
        lines: list[str] = []
        for item in results:
            repo_name = item.get("repo_name", "unknown")
            short_description = item.get("short_description", "")
            star_count = item.get("star_count", 0)
            pull_count = item.get("pull_count", 0)
            is_official = item.get("is_official", False)

            formatted.append(
                {
                    "repo_name": repo_name,
                    "short_description": short_description,
                    "star_count": star_count,
                    "pull_count": pull_count,
                    "is_official": is_official,
                }
            )
            official_badge = " [official]" if is_official else ""
            pulls_str = _format_count(pull_count)
            lines.append(
                f"- **{repo_name}**{official_badge}"
                f" ({pulls_str} pulls, {star_count} stars)"
                f" — {short_description}"
            )

        if not lines:
            output = f"No images found for '{query}'."
        else:
            header = f"Found {total} image(s) for '{query}'"
            if truncated:
                header += f" (showing first {MAX_SEARCH_RESULTS})"
            header += ":\n"
            output = header + "\n".join(lines)

        return ToolResult(
            success=True,
            output=output,
            data={"results": formatted, "total": total, "query": query},
            caption=f"{total} image{'s' if total != 1 else ''} for {query!r}",
        )


class RegistryImageInfoTool(Tool):
    """Retrieve tag and architecture details for a Docker Hub image."""

    @property
    def name(self) -> str:
        return "registry_image_info"

    @property
    def description(self) -> str:
        return (
            "Get tag listing and architecture details for an image on Docker Hub."
            " Use this after registry_search to evaluate whether an image is"
            " suitable as an OCI resource for a K8s charm."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": (
                        "Image name (e.g. 'redis', 'bitnami/redis')."
                        " Bare names are expanded to library/<name>."
                    ),
                },
                "tag": {
                    "type": "string",
                    "description": "Optional tag to filter by (e.g. '7-alpine').",
                },
            },
            "required": ["image"],
        }

    async def execute(self, image: str, tag: str | None = None) -> ToolResult:
        """Fetch tag details for the given *image*."""
        namespace, repository = _normalise_image(image)

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                response = await client.get(
                    f"{_REPO_URL}/{namespace}/{repository}/tags/",
                    params={"page_size": 25, "ordering": "last_updated"},
                )
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out fetching Docker Hub info for '{image}'",
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 404:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Image '{image}' not found on Docker Hub",
                    data={"status_code": 404, "image": image},
                )
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {code} fetching Docker Hub info for '{image}'",
                data={"status_code": code, "image": image},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error fetching Docker Hub info: {exc}",
            )
        except ValueError as exc:
            # ``json.JSONDecodeError`` is a ``ValueError`` subclass — a
            # 200 with non-JSON used to crash this tool unhandled.
            return ToolResult(
                success=False,
                output="",
                error=f"Docker Hub returned non-JSON response for '{image}': {exc}",
            )

        raw_tags = body.get("results", []) if isinstance(body, dict) else []

        tags: list[dict[str, Any]] = []
        lines: list[str] = []
        for entry in raw_tags:
            tag_name = entry.get("name", "unknown")

            # When a specific tag filter is provided, skip non-matching tags.
            if tag and tag != tag_name:
                continue

            size_bytes = entry.get("full_size", 0) or 0
            last_updated = entry.get("last_updated", "unknown")
            architectures = sorted(
                {
                    img.get("architecture", "unknown")
                    for img in entry.get("images", [])
                    if img.get("architecture")
                }
            )

            tags.append(
                {
                    "name": tag_name,
                    "size_bytes": size_bytes,
                    "last_updated": last_updated,
                    "architectures": architectures,
                }
            )

            size_str = _format_bytes(size_bytes)
            arch_str = ", ".join(architectures) if architectures else "unknown"
            # Trim the timestamp to date only for readability.
            date_str = last_updated[:10] if len(last_updated) >= 10 else last_updated
            lines.append(f"- **{tag_name}** ({size_str}, {arch_str}) — updated {date_str}")

        if not lines:
            if tag:
                output = f"No tag '{tag}' found for image '{image}'."
            else:
                output = f"No tags found for image '{image}'."
        else:
            display_name = image if "/" in image else f"library/{image}"
            header = f"Tags for {display_name}:\n"
            output = header + "\n".join(lines)

        if tag and tags:
            caption = f"{image}:{tag}"
        elif tag:
            caption = f"{image}:{tag} not found"
        else:
            caption = f"{image}: {len(tags)} tag{'s' if len(tags) != 1 else ''}"
        return ToolResult(
            success=True,
            output=output,
            data={"image": image, "tags": tags},
            caption=caption,
        )
