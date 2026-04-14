"""Batch file editing tool — apply multiple search-replace edits in one call."""

from typing import Any

from cantrip.agent.tools.base import ToolResult
from cantrip.agent.tools.files import PathAwareTool


class MultiEditTool(PathAwareTool):
    """Apply multiple search-replace edits across one or more files."""

    @property
    def name(self) -> str:
        return "multi_edit"

    @property
    def description(self) -> str:
        return (
            "Apply multiple search-replace edits to one or more files in a single call. "
            "Each edit specifies a file path, an old string to find, and a new string to "
            "replace it with. Useful for mechanical refactors like renaming a symbol across "
            "several files. Edits are applied sequentially; if one fails, earlier edits "
            "are kept and the error is reported."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "description": "List of edits to apply.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "string",
                                "description": "Path to the file to edit.",
                            },
                            "old": {
                                "type": "string",
                                "description": "Exact string to find.",
                            },
                            "new": {
                                "type": "string",
                                "description": "Replacement string.",
                            },
                        },
                        "required": ["file", "old", "new"],
                    },
                },
            },
            "required": ["edits"],
        }

    async def execute(self, edits: list[dict[str, str]]) -> ToolResult:
        """Apply all edits sequentially."""
        if not edits:
            return ToolResult(success=False, output="", error="No edits provided.")

        applied = 0
        results: list[str] = []

        for i, edit in enumerate(edits):
            file_path = edit.get("file", "")
            old = edit.get("old", "")
            new = edit.get("new", "")

            if not file_path or not old:
                return _partial_result(
                    applied,
                    results,
                    f"Edit {i + 1}: missing 'file' or 'old' field.",
                )

            try:
                resolved = self._resolve_path(file_path)
            except ValueError as exc:
                return _partial_result(applied, results, f"Edit {i + 1}: {exc}")

            if not resolved.exists():
                return _partial_result(
                    applied, results, f"Edit {i + 1}: file not found: {file_path}"
                )

            try:
                content = resolved.read_text()
            except OSError as exc:
                return _partial_result(
                    applied, results, f"Edit {i + 1}: cannot read {file_path}: {exc}"
                )

            if old not in content:
                return _partial_result(
                    applied,
                    results,
                    f"Edit {i + 1}: string not found in {file_path}: {old[:80]}...",
                )

            count = content.count(old)
            if count > 1:
                return _partial_result(
                    applied,
                    results,
                    f"Edit {i + 1}: string appears {count} times in {file_path}. "
                    f"Provide more context for a unique match.",
                )

            new_content = content.replace(old, new)
            try:
                resolved.write_text(new_content)
            except OSError as exc:
                return _partial_result(
                    applied, results, f"Edit {i + 1}: cannot write {file_path}: {exc}"
                )

            applied += 1
            results.append(f"Edit {i + 1}: replaced in {file_path}")

        return ToolResult(
            success=True,
            output="\n".join(results),
            data={"applied": applied, "total": len(edits)},
        )


def _partial_result(
    applied: int,
    results: list[str],
    error: str,
) -> ToolResult:
    """Build a failure result that reports how many edits succeeded before the error."""
    output = "\n".join(results) if results else ""
    if applied > 0:
        error = f"{applied} edit(s) applied before failure. {error}"
    return ToolResult(success=False, output=output, error=error)
