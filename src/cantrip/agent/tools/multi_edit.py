"""Batch file editing tool — apply multiple search-replace edits in one call."""

from typing import Any

from cantrip.agent.tools.base import ToolResult
from cantrip.agent.tools.files import (
    PathAwareTool,
    _did_you_mean_hint,
    _relaxed_whitespace_span,
)


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

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        edits = arguments.get("edits") or []
        if not isinstance(edits, list) or not edits:
            return None
        files = {edit.get("file", "") for edit in edits if isinstance(edit, dict)}
        files.discard("")
        n = len(edits)
        if len(files) == 1:
            target = next(iter(files))
            return f"Applying {n} edit{'s' if n != 1 else ''} to {target}…"
        if files:
            return f"Applying {n} edit{'s' if n != 1 else ''} across {len(files)} files…"
        return f"Applying {n} edit{'s' if n != 1 else ''}…"

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
                            "relax_whitespace": {
                                "type": "boolean",
                                "description": (
                                    "Optional: when true, fall back to a "
                                    "whitespace-tolerant match if the exact "
                                    "old isn't found.  Off by default."
                                ),
                                "default": False,
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
        # Phase 103.4: track resolved paths for successful edits so the
        # dispatcher can decrement the miss counter for each one even
        # when the batch later fails.
        success_paths: list[str] = []

        for i, edit in enumerate(edits):
            file_path = edit.get("file", "")
            old = edit.get("old", "")
            new = edit.get("new", "")

            if not file_path or not old:
                return _partial_result(
                    applied,
                    results,
                    f"Edit {i + 1}: missing 'file' or 'old' field.",
                    success_paths=success_paths,
                )

            try:
                resolved = self._resolve_path(file_path)
            except ValueError as exc:
                return _partial_result(
                    applied,
                    results,
                    f"Edit {i + 1}: {exc}",
                    success_paths=success_paths,
                )

            if not resolved.exists():
                return _partial_result(
                    applied,
                    results,
                    f"Edit {i + 1}: file not found: {file_path}",
                    success_paths=success_paths,
                )

            try:
                content = resolved.read_text()
            except (OSError, UnicodeDecodeError) as exc:
                # ``UnicodeDecodeError`` fires on binary or mis-encoded
                # files (latin-1, UTF-16, etc.); surface it as a friendly
                # partial result rather than letting the tool dispatch
                # see an uncaught exception.
                return _partial_result(
                    applied,
                    results,
                    f"Edit {i + 1}: cannot read {file_path}: {exc}",
                    success_paths=success_paths,
                )

            relax_whitespace = bool(edit.get("relax_whitespace", False))
            relaxed_span: tuple[int, int] | None = None
            if old in content:
                count = content.count(old)
                if count > 1:
                    return _partial_result(
                        applied,
                        results,
                        f"Edit {i + 1}: string appears {count} times in {file_path}. "
                        f"Provide more context for a unique match.",
                        success_paths=success_paths,
                    )
                new_content = content.replace(old, new)
            else:
                # Phase 103.3: opt-in whitespace-tolerant fallback before
                # giving up so the obvious drift cases ("\n\n" vs
                # "\n  \n", tab/space, trailing newlines) match without
                # forcing the model to re-read the file.
                if relax_whitespace:
                    relaxed_span = _relaxed_whitespace_span(old, content)
                if relaxed_span is None:
                    # Phase 103.2: surface the closest substring as a
                    # unified diff so the next attempt aims at real
                    # on-disk bytes.
                    hint = _did_you_mean_hint(old, content)
                    error = f"Edit {i + 1}: string not found in {file_path}: {old[:80]}..."
                    if hint:
                        error = f"{error}\n\nDid you mean:\n{hint}"
                    # Phase 103.4: emit a per-file miss signal so the
                    # dispatcher can tick the post-resume miss counter.
                    return _partial_result(
                        applied,
                        results,
                        error,
                        success_paths=success_paths,
                        miss_path=str(resolved),
                    )
                start, end = relaxed_span
                new_content = content[:start] + new + content[end:]
            try:
                resolved.write_text(new_content)
            except OSError as exc:
                return _partial_result(
                    applied,
                    results,
                    f"Edit {i + 1}: cannot write {file_path}: {exc}",
                    success_paths=success_paths,
                )

            applied += 1
            success_paths.append(str(resolved))
            results.append(f"Edit {i + 1}: replaced in {file_path}")

        # Count distinct files touched for a richer caption than just edit count.
        # The schema names the per-edit field ``file`` (line 37 above); reading
        # ``file_path`` here always returned the empty string, so every caption
        # collapsed to "across 0 files" regardless of how many files were edited.
        touched = sorted({edit.get("file", "") for edit in edits if edit.get("file")})
        if len(touched) == 1:
            caption = f"{applied} edit{'s' if applied != 1 else ''} in {touched[0]}"
        else:
            caption = f"{applied} edit{'s' if applied != 1 else ''} across {len(touched)} files"
        # Phase 103.4: ``edit_success_paths`` tells the dispatcher to
        # decrement the post-resume miss counter once per file edited.
        return ToolResult(
            success=True,
            output="\n".join(results),
            data={
                "applied": applied,
                "total": len(edits),
                "edit_success_paths": list(success_paths),
            },
            caption=caption,
        )


def _partial_result(
    applied: int,
    results: list[str],
    error: str,
    *,
    success_paths: list[str] | None = None,
    miss_path: str | None = None,
) -> ToolResult:
    """Build a failure result that reports how many edits succeeded before the error.

    *success_paths* and *miss_path* surface the Phase 103.4 hallucination
    counter signals: paths whose edits did succeed (so the dispatcher
    decrements the counter for each) and the file whose ``old_string``
    miss triggered the failure (so the dispatcher increments).
    """
    output = "\n".join(results) if results else ""
    if applied > 0:
        error = f"{applied} edit(s) applied before failure. {error}"
    data: dict[str, Any] = {}
    if success_paths:
        data["edit_success_paths"] = list(success_paths)
    if miss_path:
        data["edit_miss_path"] = miss_path
    return ToolResult(success=False, output=output, error=error, data=data)
