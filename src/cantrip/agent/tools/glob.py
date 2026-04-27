"""File pattern matching tool for the agent.

Uses ``pathlib.Path.glob`` to find files by pattern, filtering out
common noise directories (``.git``, ``__pycache__``, etc.).
"""

import heapq
import logging
import pathlib
from typing import Any

from cantrip.agent.tools.base import ToolResult
from cantrip.agent.tools.files import PathAwareTool

log = logging.getLogger(__name__)

# Maximum file paths returned to the LLM to avoid flooding context.
_DEFAULT_MAX_RESULTS = 50

# Hard ceiling — even if the caller asks for more, cap here.
_ABSOLUTE_MAX_RESULTS = 200

# Directory names to skip when collecting results.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


class GlobTool(PathAwareTool):
    """Find files matching a glob pattern."""

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.yaml'). "
            "Returns matching file paths relative to the search directory. "
            "Use this to discover project structure and locate files by name or extension."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Glob pattern to match (e.g. '**/*.py', 'tests/**/test_*.py', '*.yaml')."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Directory to search in (relative to charm directory, defaults to '.')."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": (
                        f"Maximum number of file paths to return (default {_DEFAULT_MAX_RESULTS})."
                    ),
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> ToolResult:
        """Run the glob and return matching file paths."""
        try:
            resolved = self._resolve_path(path)
        except ValueError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        if not resolved.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")

        if not resolved.is_dir():
            return ToolResult(success=False, output="", error=f"Not a directory: {path}")

        max_results = min(max(1, max_results), _ABSOLUTE_MAX_RESULTS)

        matches, total_seen = _collect_matches(resolved, pattern, max_results)

        if not matches:
            return ToolResult(
                success=True,
                output="No matching files found.",
                data={"match_count": 0},
                caption=f"No files matching {pattern!r}",
            )

        # Report paths relative to the search directory.
        rel_paths = [str(m.relative_to(resolved)) for m in matches]

        truncated = total_seen > max_results

        display = "\n".join(rel_paths)
        if truncated:
            display += f"\n\n(results truncated — showing {max_results} of more matches)"

        caption = f"{len(rel_paths)} files matching {pattern!r}"
        if truncated:
            caption += " (truncated)"
        return ToolResult(
            success=True,
            output=display,
            data={"match_count": len(rel_paths), "truncated": truncated},
            caption=caption,
        )


def _collect_matches(
    root: pathlib.Path,
    pattern: str,
    limit: int,
) -> tuple[list[pathlib.Path], int]:
    """Return the alphabetically-first *limit* matches plus a total count.

    ``root.glob`` yields in OS-defined order — usually directory-walk
    order, not alphabetical — so picking the first *limit* hits and
    sorting *afterwards* would silently mask alphabetically-earlier
    files when the pattern matches more than *limit* entries.
    Use a heap so memory stays bounded at ``O(limit)`` while still
    returning the correct slice.

    The second tuple element is the total match count (after the
    skip-dir filter), used by the caller to detect truncation
    honestly.
    """
    seen = 0
    heap: list[pathlib.Path] = []
    for match in root.glob(pattern):
        if _in_skip_dir(match, root):
            continue
        if not match.is_file():
            continue
        seen += 1
        # ``nsmallest``-style invariant: keep the *limit* smallest paths
        # by alphabetical order via a max-heap of negated keys.  Store
        # ``(neg_index, path)`` so ties resolve on path itself.
        if len(heap) < limit:
            heapq.heappush(heap, _MaxHeapEntry(match))
        elif heap[0].path > match:
            heapq.heapreplace(heap, _MaxHeapEntry(match))
    return sorted(entry.path for entry in heap), seen


class _MaxHeapEntry:
    """Wrap a Path so a ``heapq`` min-heap behaves like a max-heap on paths."""

    __slots__ = ("path",)

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path

    def __lt__(self, other: "_MaxHeapEntry") -> bool:
        # Reversed compare turns the min-heap into a max-heap so
        # ``heap[0]`` is the *largest* path currently kept.
        return self.path > other.path


def _in_skip_dir(path: pathlib.Path, root: pathlib.Path) -> bool:
    """Return True if *path* is inside a directory we should skip."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return any(part in _SKIP_DIRS for part in rel.parts)
