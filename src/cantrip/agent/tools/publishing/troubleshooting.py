"""Extract troubleshooting entries from the agent's debug history.

Walks the messages + subagent_messages tables for tool-result errors
paired with the agent's diagnosis and the next successful tool call, then
emits docs/how-to/troubleshooting.md grouped by category.
"""

import dataclasses
import json
import pathlib
import re
import sqlite3
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Marker that delimits the auto-generated troubleshooting section.
_TROUBLESHOOTING_MARKER = "<!-- cantrip-generated below -->"

# Heuristics for grouping errors.  Keyword patterns are intentionally
# coarse — generation-time, no LLM call.  Order matters: the first match
# wins, so put more specific categories before general ones.
# Order matters: charm-stack-specific patterns (image, observability,
# secret, relation, hook) win over the generic transport-layer ones
# (network, storage) so an error mentioning a stack component lands in
# the bucket the operator looks at first.
_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "image",
        re.compile(
            r"\b(ImagePullBackOff|ErrImagePull|oci[\s-]image|registry|"
            r"manifest unknown|pull access denied|repository does not exist)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "observability",
        re.compile(
            r"\b(tempo|loki|grafana|prometheus|alertmanager|"
            r"otel|opentelemetry|tracing|metrics-endpoint)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "secret",
        re.compile(
            r"\b(secret-not-found|SecretNotFound|secret.*not.*owned|"
            r"unknown secret|access to.*secret denied)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "relation",
        re.compile(
            r"\b(relation[-_ ](not[-_ ]found|broken|departed)|"
            r"ENDPOINT_NOT_FOUND|RELATION_NOT_FOUND|"
            r"no relation to|interface mismatch|relation.*does not exist|"
            r"juju integrate.*failed)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hook",
        re.compile(
            # ``hook ... failed`` / ``hook ... error`` covers ``hook failed``,
            # ``hook 'install' failed``, ``hook install-error``, etc.
            r"\bhook\b.{0,40}\b(?:failed|error|not[\s_-]found)\b|"
            r"\b(?:install-error|charm hook|pebble-ready.*error|"
            r"config-changed.*error|upgrade-charm.*error)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "network",
        re.compile(
            r"\b(connection refused|no route to host|name or service not known|"
            r"timed? out|unreachable|dns|getaddrinfo|connection reset|"
            r"connection aborted|TLS handshake)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "storage",
        re.compile(
            r"\b(storage[-_ ]not[-_ ]found|persistentvolume|pvc|"
            r"insufficient storage|disk[ -]full|no space left)\b",
            re.IGNORECASE,
        ),
    ),
)


def _safe_load_json_field(raw: object) -> object:
    """Decode a JSON-text column, returning ``None`` on absence or corruption.

    Mirrors the helper in :mod:`cantrip.agent.store` but is local to
    :mod:`publishing` so the troubleshooting walker doesn't reach into
    the store module's internals.
    """
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str | bytes):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# Stable display order for the grouped report.
_CATEGORY_ORDER: tuple[str, ...] = (
    "relation",
    "hook",
    "secret",
    "image",
    "network",
    "storage",
    "observability",
    "general",
)

_CATEGORY_TITLES: dict[str, str] = {
    "relation": "Relation errors",
    "hook": "Hook failures",
    "secret": "Secret access errors",
    "image": "Image pull / OCI errors",
    "network": "Network errors",
    "storage": "Storage errors",
    "observability": "Observability stack errors",
    "general": "Other errors",
}

# Threshold below which an error is considered "trivial" — typo-shaped
# one-liners that don't warrant a troubleshooting entry.  Errors that
# match a non-general category are kept regardless.
_MIN_DIAGNOSTIC_LINES = 5

# Strip the ``<tool_result name='...'>`` wrapper Cantrip adds around tool
# results so the extracted excerpt is the actual error text.
_TOOL_RESULT_WRAP_RE = re.compile(
    r"^<tool_result\s+name=[^>]*>\n(.*)\n</tool_result>\s*$", re.DOTALL
)


def _categorise_error(text: str) -> str:
    """Bucket *text* into one of the known troubleshooting categories."""
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return "general"


def _strip_tool_result_wrapper(content: str) -> str:
    """Drop the ``<tool_result>`` wrapper Cantrip adds around tool output."""
    match = _TOOL_RESULT_WRAP_RE.match(content.strip())
    return match.group(1) if match else content.strip()


def _excerpt(text: str, *, max_lines: int = 12) -> str:
    """Return the first *max_lines* of *text* trimmed for embedding."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text.rstrip()
    return "\n".join(lines[:max_lines]) + f"\n… ({len(lines) - max_lines} more lines elided)"


@dataclasses.dataclass(frozen=True)
class TroubleshootingEntry:
    """A single troubleshooting entry mined from the transcript."""

    category: str
    symptom: str
    cause: str | None
    resolution: str | None
    citation: str  # Human-readable transcript pointer (e.g. ``message #42``).


def _read_transcript_pairs(db_path: pathlib.Path) -> list[TroubleshootingEntry]:
    """Mine error→fix pairs from the messages + subagent_messages tables.

    Walks each table chronologically.  For every assistant message whose
    tool results carry ``is_error=true``, captures:

    - **Symptom:** the wrapped tool-result content (stripped + excerpted).
    - **Cause:** the next assistant message's text content within the
      same source (main vs. subagent task) — this is typically the
      agent's diagnosis.
    - **Resolution:** the first subsequent assistant message that issues
      a successful tool call (any tool) within five turns.
    - **Citation:** "main message #N" or "subagent task <id> message #N".

    Returns an empty list when the database is missing or the relevant
    tables aren't present — generation-time best-effort, never raises.
    """
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []
    try:
        conn.row_factory = sqlite3.Row
        entries: list[TroubleshootingEntry] = []

        try:
            main_rows = list(
                conn.execute(
                    "SELECT id, role, content, tool_results, timestamp FROM messages ORDER BY id"
                )
            )
        except sqlite3.OperationalError:
            main_rows = []

        entries.extend(_pairs_from_message_stream(main_rows, source_label="main"))

        try:
            tasks = list(
                conn.execute("SELECT DISTINCT task_id FROM subagent_messages ORDER BY task_id")
            )
        except sqlite3.OperationalError:
            tasks = []

        for row in tasks:
            task_id = row["task_id"]
            sub_rows = list(
                conn.execute(
                    "SELECT message_index AS id, role, content, tool_results "
                    "FROM subagent_messages WHERE task_id = ? "
                    "ORDER BY message_index",
                    (task_id,),
                )
            )
            entries.extend(
                _pairs_from_message_stream(sub_rows, source_label=f"subagent/{task_id}")
            )

        return entries
    finally:
        conn.close()


def _pairs_from_message_stream(
    rows: list[sqlite3.Row], *, source_label: str
) -> list[TroubleshootingEntry]:
    """Extract ``TroubleshootingEntry`` records from one chronological stream.

    The stream is either the main agent's ``messages`` table or a single
    subagent task's slice of ``subagent_messages``.  Each error tool
    result kicks off a lookahead within the same stream — diagnoses and
    resolutions don't cross stream boundaries because conversations are
    independent.
    """
    entries: list[TroubleshootingEntry] = []
    for index, row in enumerate(rows):
        tool_results = _safe_load_json_field(row["tool_results"]) or []
        if not isinstance(tool_results, list):
            continue
        error_results = [tr for tr in tool_results if isinstance(tr, dict) and tr.get("is_error")]
        if not error_results:
            continue
        for error_result in error_results:
            raw_content = str(error_result.get("content", ""))
            symptom_text = _strip_tool_result_wrapper(raw_content)
            category = _categorise_error(symptom_text)
            line_count = len(symptom_text.splitlines())
            if category == "general" and line_count < _MIN_DIAGNOSTIC_LINES:
                continue
            cause = _next_assistant_text(rows, index)
            resolution = _next_successful_tool_call(rows, index)
            entries.append(
                TroubleshootingEntry(
                    category=category,
                    symptom=_excerpt(symptom_text),
                    cause=cause,
                    resolution=resolution,
                    citation=f"{source_label} message #{row['id']}",
                )
            )
    return entries


def _next_assistant_text(rows: list[sqlite3.Row], index: int) -> str | None:
    """Return the agent's next non-empty text reply within five turns."""
    for offset in range(1, 6):
        target = index + offset
        if target >= len(rows):
            return None
        next_row = rows[target]
        if next_row["role"] != "assistant":
            continue
        content = (next_row["content"] or "").strip()
        if content:
            return _excerpt(content, max_lines=8)
    return None


def _next_successful_tool_call(rows: list[sqlite3.Row], index: int) -> str | None:
    """Return a one-line summary of the next successful tool invocation."""
    for offset in range(1, 8):
        target = index + offset
        if target >= len(rows):
            return None
        next_row = rows[target]
        if next_row["role"] != "tool":
            continue
        next_results = _safe_load_json_field(next_row["tool_results"]) or []
        if not isinstance(next_results, list):
            continue
        for result in next_results:
            if isinstance(result, dict) and not result.get("is_error"):
                content = str(result.get("content", "")).strip()
                stripped = _strip_tool_result_wrapper(content)
                first_line = stripped.splitlines()[0] if stripped else "(empty)"
                return first_line[:140]
    return None


def _format_troubleshooting_entry(entry: TroubleshootingEntry, index: int) -> str:
    """Render a single entry as a Markdown ``### N. <symptom>`` block."""
    summary_line = entry.symptom.splitlines()[0] if entry.symptom else "(empty)"
    summary_line = summary_line[:80]
    sections: list[str] = [f"### {index}. {summary_line}", ""]
    sections.append("**Symptom:**")
    sections.append("")
    sections.append("```")
    sections.append(entry.symptom)
    sections.append("```")
    sections.append("")
    if entry.cause:
        sections.append("**Cause:** " + entry.cause.replace("\n", " "))
        sections.append("")
    if entry.resolution:
        sections.append("**Resolution:** " + entry.resolution)
        sections.append("")
    sections.append(f"**See also:** {entry.citation}")
    sections.append("")
    return "\n".join(sections)


def format_troubleshooting_page(entries: list[TroubleshootingEntry]) -> str:
    """Render *entries* grouped by category into a Markdown page section.

    Returns just the auto-generated body — no top-level heading and no
    intro — so the caller can compose it with marker-based preservation.
    """
    if not entries:
        return (
            "_No troubleshooting entries have been mined from the session "
            "transcript yet.  Entries appear here once the agent encounters "
            "and resolves errors during build / deploy / test._\n"
        )

    grouped: dict[str, list[TroubleshootingEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.category, []).append(entry)

    lines: list[str] = []
    for category in _CATEGORY_ORDER:
        bucket = grouped.get(category, [])
        if not bucket:
            continue
        lines.append(f"## {_CATEGORY_TITLES[category]}")
        lines.append("")
        for index, entry in enumerate(bucket, start=1):
            lines.append(_format_troubleshooting_entry(entry, index))
    return "\n".join(lines)


def _resolve_troubleshooting_intro(charm_dir: pathlib.Path) -> str:
    """Decide what intro content sits above the auto-generated section.

    Mirrors the architecture-page pattern: if a marker is present in an
    existing ``troubleshooting.md``, preserve everything above it; if
    the file exists without a marker, treat it as charm-author content
    and preserve verbatim; otherwise emit a default "Troubleshooting"
    heading.
    """
    path = charm_dir / "docs" / "how-to" / "troubleshooting.md"
    if path.is_file():
        existing = path.read_text()
        if _TROUBLESHOOTING_MARKER in existing:
            return existing.split(_TROUBLESHOOTING_MARKER, 1)[0]
        return existing
    return "# Troubleshooting\n\nCommon errors mined from this charm's build history.\n"


def _compose_troubleshooting_page(intro: str, body: str) -> str:
    """Stitch the intro and the auto-generated section together."""
    intro = intro.rstrip()
    if not intro:
        intro = "# Troubleshooting\n"
    return intro + "\n\n" + _TROUBLESHOOTING_MARKER + "\n\n" + body


def _ensure_troubleshooting_in_toctree(charm_dir: pathlib.Path) -> bool:
    """Add ``troubleshooting`` to ``docs/how-to/index.md`` if it isn't already.

    Returns True when the index file was modified.  No-op when the
    index doesn't exist (the next ``generate_docs`` will rebuild it
    from scratch and pick up the file via Phase 74.4 plumbing).
    """
    index_path = charm_dir / "docs" / "how-to" / "index.md"
    if not index_path.is_file():
        return False
    text = index_path.read_text()
    # Quick check — exact-line match avoids false positives from prose.
    if re.search(r"^troubleshooting$", text, re.MULTILINE):
        return False
    # Insert before the closing ```` ``` ```` of the toctree block.
    new_text, count = re.subn(
        r"(\n)```(\s*)$",
        r"\ntroubleshooting\n```\2",
        text,
        count=1,
    )
    if count == 0:
        return False
    index_path.write_text(new_text)
    return True


class ExtractTroubleshootingTool(Tool):
    """Render a troubleshooting page from error→fix pairs in the transcript."""

    @property
    def name(self) -> str:
        return "extract_troubleshooting"

    @property
    def description(self) -> str:
        return (
            "Mine the Cantrip session transcript (.cantrip SQLite) for "
            "error→fix pairs and write them as a categorised "
            "troubleshooting page at docs/how-to/troubleshooting.md.  "
            "Charm-author content above the cantrip-generated marker is "
            "preserved across re-runs."
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
                "db_path": {
                    "type": "string",
                    "description": (
                        "Optional override for the .cantrip session-store "
                        "path.  Defaults to <path>/.cantrip."
                    ),
                },
            },
        }

    async def execute(self, path: str = ".", db_path: str | None = None) -> ToolResult:
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        store_path = pathlib.Path(db_path).expanduser() if db_path else charm_dir / ".cantrip"
        entries = _read_transcript_pairs(store_path)
        intro = _resolve_troubleshooting_intro(charm_dir)
        body = format_troubleshooting_page(entries)
        content = _compose_troubleshooting_page(intro, body)

        target = charm_dir / "docs" / "how-to" / "troubleshooting.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

        toctree_updated = _ensure_troubleshooting_in_toctree(charm_dir)

        category_counts: dict[str, int] = {}
        for entry in entries:
            category_counts[entry.category] = category_counts.get(entry.category, 0) + 1

        summary = f"Refreshed {target.relative_to(charm_dir)} with {len(entries)} entry/entries."
        if category_counts:
            summary += (
                "  By category: "
                + ", ".join(f"{cat} {count}" for cat, count in sorted(category_counts.items()))
                + "."
            )
        if toctree_updated:
            summary += "  Added 'troubleshooting' to docs/how-to/index.md toctree."
        return ToolResult(
            success=True,
            output=summary,
            data={
                "path": str(target),
                "entry_count": len(entries),
                "category_counts": category_counts,
                "store_path": str(store_path),
                "toctree_updated": toctree_updated,
            },
            caption=f"{len(entries)} entr{'ies' if len(entries) != 1 else 'y'}",
        )
