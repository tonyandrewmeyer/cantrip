"""File operation tools for the agent."""

import difflib
import pathlib
import re
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


def _relaxed_whitespace_span(old_string: str, content: str) -> tuple[int, int] | None:
    """Locate *old_string* in *content* tolerant of whitespace differences.

    Phase 103.3: when ``edit_file`` / ``multi_edit`` opt into
    ``relax_whitespace=True`` and the exact ``old_string`` doesn't appear
    in the file, this fallback collapses any run of whitespace in
    *old_string* into a regex ``\\s+`` so the obvious cases — ``"\\n\\n"``
    vs ``"\\n  \\n"``, ``"foo bar"`` vs ``"foo\\tbar"``, an extra trailing
    newline — match without forcing the model to re-read the file.

    Returns ``(start, end)`` of the unique match in *content*, or
    ``None`` when there is no match or the match is ambiguous.  An
    ambiguous relaxed match would let the tool overwrite the wrong
    instance of a repeated pattern, so we refuse the edit instead.
    """
    if not old_string:
        return None

    # Tokenise into runs of whitespace and runs of non-whitespace.  Each
    # whitespace run becomes ``\s+`` so a single space matches a tab, a
    # double-space, or a newline-with-indent — the practical drift
    # patterns the model hits after a session resume.
    tokens = re.split(r"(\s+)", old_string)
    parts: list[str] = []
    for tok in tokens:
        if not tok:
            continue
        if tok.isspace():
            parts.append(r"\s+")
        else:
            parts.append(re.escape(tok))
    if not parts:
        return None

    pattern = "".join(parts)
    matches = list(re.finditer(pattern, content, flags=re.DOTALL))
    if len(matches) != 1:
        # Either no match or multiple matches — refuse the edit and let
        # the caller fall back to the bare-error path.
        return None
    return matches[0].span()


#: Minimum character-level similarity ratio between *old_string* and its
#: closest substring on disk before we synthesise a "did you mean" hint.
#: Below this, the diff would be more confusing than the bare preview.
_DID_YOU_MEAN_MIN_RATIO = 0.45


def _did_you_mean_hint(old_string: str, content: str, *, max_lines: int = 12) -> str | None:
    """Return a "did you mean" diff between *old_string* and the closest match.

    When ``edit_file`` / ``multi_edit`` fail because *old_string* doesn't
    appear in the file, the model historically gets back a 50-character
    preview of what it asked for and zero signal about what's actually on
    disk.  The next round burns a ``read_file`` to discover the drift.

    This helper finds the closest substring of the file using a
    character-level :class:`difflib.SequenceMatcher`, expands the match
    out to a line-aligned window roughly the same shape as *old_string*,
    and returns a unified diff between the two.  The diff body is capped
    at *max_lines* so a long file doesn't flood the tool result.

    Returns ``None`` when the file has effectively nothing in common with
    *old_string* (similarity below :data:`_DID_YOU_MEAN_MIN_RATIO`) — a
    synthetic diff in that case is more misleading than helpful.
    """
    if not old_string or not content:
        return None

    # Character-level match — reliable for the common case where the
    # model emitted a single line that disagrees with the file by a
    # quote style or a stray space.  Line-level matching collapses the
    # signal completely when the input is one line.
    matcher = difflib.SequenceMatcher(a=old_string, b=content, autojunk=False)
    block = matcher.find_longest_match(0, len(old_string), 0, len(content))

    # Nothing meaningfully shared.  Gate on "how much of what the model
    # asked for was found verbatim on disk": a 3-character coincidence
    # in a 200-byte ``old_string`` should not masquerade as a near miss.
    if block.size == 0:
        return None
    similarity = block.size / max(len(old_string), 1)
    if similarity < _DID_YOU_MEAN_MIN_RATIO:
        return None

    # Expand the match out to whole-line boundaries.  ``window_len``
    # widens the actual slice slightly past *old_string*'s length so the
    # diff shows surrounding context rather than just the matching
    # fragment in isolation.
    window_len = max(len(old_string), block.size) + 64
    expand = max(window_len - block.size, 0) // 2
    start = max(block.b - expand, 0)
    end = min(block.b + block.size + expand, len(content))

    # Snap to surrounding newlines so the slice begins and ends on whole
    # lines — keeps the unified diff legible.
    line_start = content.rfind("\n", 0, start) + 1
    next_nl = content.find("\n", end)
    line_end = next_nl + 1 if next_nl != -1 else len(content)

    actual_slice = content[line_start:line_end]
    line_no = content.count("\n", 0, line_start) + 1
    end_line_no = line_no + actual_slice.count("\n")

    old_lines = old_string.splitlines(keepends=True) or [old_string]
    actual_lines = actual_slice.splitlines(keepends=True) or [actual_slice]

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            actual_lines,
            fromfile="expected (your old_string)",
            tofile=f"actual (lines {line_no}-{end_line_no})",
            lineterm="",
        )
    )
    if not diff_lines:
        return None

    # Cap body lines so a giant rewrite doesn't flood the tool result.
    # Keep the file headers (first two lines) plus the hunk header, then
    # *max_lines* of body.
    if len(diff_lines) > max_lines + 3:
        diff_lines = diff_lines[: max_lines + 3] + ["… (truncated)"]
    return "\n".join(diff_lines)


class PathAwareTool(Tool):
    """Base class for tools that resolve paths relative to a base directory.

    Subclasses inherit ``_resolve_path`` which resolves user-supplied paths
    against an optional *base_path* and prevents path-traversal escapes.
    """

    def __init__(self, base_path: pathlib.Path | None = None) -> None:
        self.base_path = base_path

    def _resolve_path(self, path: str) -> pathlib.Path:
        """Resolve *path*, ensuring it stays within ``base_path`` when set."""
        candidate = pathlib.Path(path).expanduser()
        if self.base_path is None:
            if candidate.is_absolute():
                return candidate
            return candidate.resolve()

        base_resolved = self.base_path.resolve()
        resolved = candidate if candidate.is_absolute() else base_resolved / candidate
        resolved = resolved.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError(f"Path {path} is outside allowed directory")

        return resolved


class ReadFileTool(PathAwareTool):
    """Tool to read file contents."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Use this to examine existing code or configuration."

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        path = arguments.get("path")
        return f"Reading {path}…" if path else None

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative to charm directory)",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-based, inclusive). Omit to start from the beginning.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-based, inclusive). Omit to read to the end.",
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> ToolResult:
        """Read file contents, optionally restricted to a line range."""
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {path}",
                )
            if resolved.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path is a directory: {path}",
                )

            content = resolved.read_text()

            if start_line is not None or end_line is not None:
                lines = content.splitlines(keepends=True)
                total = len(lines)
                # Convert to 0-based indices with defaults.
                start = max((start_line or 1) - 1, 0)
                end = min(end_line or total, total)
                if start >= total:
                    return ToolResult(
                        success=True,
                        output="(no lines in requested range)",
                        data={"path": str(resolved), "total_lines": total},
                    )
                content = "".join(lines[start:end])
                # ``content.count("\n")`` under-reports by one for any file
                # whose last line lacks a trailing newline (common in legacy
                # text and many code files): the final element returned by
                # ``splitlines(keepends=True)`` then carries no ``\n`` of its
                # own.  Use the slice length, which is the real number of
                # lines we returned to the caller.
                shown = len(lines[start:end])
                return ToolResult(
                    success=True,
                    output=content,
                    data={
                        "path": str(resolved),
                        "size": len(content),
                        "lines": f"{start + 1}-{min(end, total)}",
                        "total_lines": total,
                    },
                    caption=f"Read {shown} lines from {path}",
                )

            line_count = content.count("\n")
            return ToolResult(
                success=True,
                output=content,
                data={"path": str(resolved), "size": len(content)},
                caption=f"Read {line_count} lines from {path}",
            )
        except (OSError, UnicodeDecodeError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class WriteFileTool(PathAwareTool):
    """Tool to write file contents."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
        )

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        path = arguments.get("path")
        return f"Writing {path}…" if path else None

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write (relative to charm directory)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str) -> ToolResult:
        """Write file contents."""
        try:
            resolved = self._resolve_path(path)

            # Create parent directories if needed
            resolved.parent.mkdir(parents=True, exist_ok=True)

            resolved.write_text(content)
            return ToolResult(
                success=True,
                output=f"Wrote {len(content)} bytes to {path}",
                data={"path": str(resolved), "size": len(content)},
                caption=f"Wrote {len(content)} bytes to {path}",
            )
        except (OSError, UnicodeEncodeError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class ListDirectoryTool(PathAwareTool):
    """Tool to list directory contents."""

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return "List files and directories in a path. Use this to explore the charm structure."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to list (relative to charm directory)",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """List directory contents."""
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Directory not found: {path}",
                )
            if not resolved.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path is not a directory: {path}",
                )

            entries = []
            for entry in sorted(resolved.iterdir()):
                if entry.is_dir():
                    label = f"dir:  {entry.name}/"
                else:
                    size = entry.stat().st_size
                    suffix = " -> " + str(entry.readlink()) if entry.is_symlink() else ""
                    label = f"file: {entry.name}  ({size} bytes){suffix}"
                entries.append(label)

            output = "\n".join(entries) if entries else "(empty directory)"
            display_path = path if path != "." else str(resolved)
            return ToolResult(
                success=True,
                output=output,
                data={"path": str(resolved), "count": len(entries)},
                caption=f"Listed {len(entries)} entries in {display_path}",
            )
        except (OSError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class EditFileTool(PathAwareTool):
    """Tool to make targeted edits to a file."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Replace a specific string in a file. Use for targeted edits without rewriting the whole file."

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        path = arguments.get("path")
        return f"Editing {path}…" if path else None

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The string to replace it with",
                },
                "relax_whitespace": {
                    "type": "boolean",
                    "description": (
                        "Optional: when true, fall back to a whitespace-tolerant "
                        "match if the exact old_string isn't found (collapses runs "
                        "of spaces, tolerates extra blank-line whitespace and "
                        "trailing newlines). Off by default — turn on after a "
                        "session resume when whitespace drift is suspected."
                    ),
                    "default": False,
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(
        self,
        path: str,
        old_string: str,
        new_string: str,
        relax_whitespace: bool = False,
    ) -> ToolResult:
        """Edit file by replacing string."""
        try:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {path}",
                )

            content = resolved.read_text()
            if old_string in content:
                # Check for ambiguity
                count = content.count(old_string)
                if count > 1:
                    return ToolResult(
                        success=False,
                        output="",
                        error=(
                            f"String appears {count} times. Provide more context for unique match."
                        ),
                    )

                new_content = content.replace(old_string, new_string)
                resolved.write_text(new_content)
                # Phase 103.4: ``edit_success_path`` lets the dispatcher
                # decrement the post-resume miss counter for this file.
                return ToolResult(
                    success=True,
                    output=f"Replaced string in {path}",
                    data={"path": str(resolved), "edit_success_path": str(resolved)},
                    caption=f"Edited {path} (1 replacement)",
                )

            # Phase 103.3: opt-in whitespace-tolerant fallback before
            # giving up — handles "\n\n" vs "\n  \n", tab/space drift,
            # and stray trailing newlines without forcing a re-read.
            if relax_whitespace:
                span = _relaxed_whitespace_span(old_string, content)
                if span is not None:
                    start, end = span
                    new_content = content[:start] + new_string + content[end:]
                    resolved.write_text(new_content)
                    return ToolResult(
                        success=True,
                        output=f"Replaced string in {path} (whitespace-tolerant)",
                        data={
                            "path": str(resolved),
                            "relax_whitespace": True,
                            "edit_success_path": str(resolved),
                        },
                        caption=f"Edited {path} (1 relaxed replacement)",
                    )

            suffix = "..." if len(old_string) > 50 else ""
            error_msg = f"String not found in file: {old_string[:50]}{suffix}"
            # Phase 103.2: pair the preview with a unified diff against
            # the closest substring on disk so the next round can target
            # the real bytes instead of guessing.
            hint = _did_you_mean_hint(old_string, content)
            if hint:
                error_msg = f"{error_msg}\n\nDid you mean:\n{hint}"
            # Phase 103.4: ``edit_miss_path`` lets the dispatcher tick
            # the post-resume miss counter for this file.
            return ToolResult(
                success=False,
                output="",
                error=error_msg,
                data={"edit_miss_path": str(resolved)},
            )
        except (OSError, UnicodeDecodeError, ValueError) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
