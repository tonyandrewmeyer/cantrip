"""File pattern matching tool for the agent.

Uses ``pathlib.Path.glob`` to find files by pattern, filtering out
common noise directories (``.git``, ``__pycache__``, etc.).
"""

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

        matches = _collect_matches(resolved, pattern, max_results)

        if not matches:
            return ToolResult(
                success=True,
                output="No matching files found.",
                data={"match_count": 0},
                caption=f"No files matching {pattern!r}",
            )

        # Report paths relative to the search directory.
        rel_paths = [str(m.relative_to(resolved)) for m in matches]

        truncated = len(rel_paths) > max_results
        if truncated:
            rel_paths = rel_paths[:max_results]

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
) -> list[pathlib.Path]:
    """Collect up to *limit* + 1 matches, skipping noise directories.

    Collects one extra to detect truncation.  Results are sorted
    alphabetically for deterministic output.
    """
    results: list[pathlib.Path] = []
    for match in root.glob(pattern):
        if _in_skip_dir(match, root):
            continue
        if match.is_file():
            results.append(match)
            if len(results) > limit:
                break
    results.sort()
    return results


def _in_skip_dir(path: pathlib.Path, root: pathlib.Path) -> bool:
    """Return True if *path* is inside a directory we should skip."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return any(part in _SKIP_DIRS for part in rel.parts)
