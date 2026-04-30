"""Memory primitives for Cantrip.

Phase 43 adds two complementary memory scopes:

* **Charm-scope** memories live in the per-charm ``.cantrip`` SQLite database
  and are managed by :class:`cantrip.agent.store.SessionStore`.
* **Global-scope** memories live on the filesystem under
  ``~/.config/cantrip/memory/`` as Markdown files with YAML frontmatter,
  fronted by an always-loaded ``MEMORY.md`` index.

Phase 51b.1 adds an optional **shared** charm-scope layer rooted at
``<charm-root>/.cantrip/shared/memory/`` (same Markdown frontmatter format)
that teammates commit to git so memories travel with the charm.  Entries
loaded from the shared directory keep ``scope="charm"`` but carry
``source="shared"`` so listings can filter or display them differently.

This module provides the filesystem side and a unified :class:`MemoryManager`
that the agent tools and the system-prompt builder talk to.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import logging
import os
import pathlib
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import yaml

if TYPE_CHECKING:
    from cantrip.agent.store import SessionStore

log = logging.getLogger(__name__)

# Maximum number of lines read from the global MEMORY.md index before truncation.
# Rationale: keep the prompt-index section bounded so a runaway index cannot
# blow the system-prompt budget.  Extra lines are dropped with a marker.
MEMORY_INDEX_MAX_LINES = 200

# Filename of the always-loaded global index.
INDEX_FILENAME = "MEMORY.md"

# Frontmatter delimiter for individual memory files.
_FRONTMATTER_DELIMITER = "---"

# Kinds of memory we recognise.  Not an enum so callers can store free-form
# subtypes later without a breaking change, but tools validate against this set.
VALID_KINDS = frozenset({"fact", "rule", "lesson"})

# Valid lifecycle statuses.
VALID_STATUSES = frozenset({"active", "quarantined", "archived"})

# Characters forbidden in topic filenames — keep it portable and avoid path
# traversal through a user-supplied title.
_SAFE_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _default_global_dir() -> pathlib.Path:
    """Return the default location for the global memory directory.

    Honours ``CANTRIP_MEMORY_DIR`` when set; otherwise falls back to
    ``$XDG_CONFIG_HOME/cantrip/memory`` or ``~/.config/cantrip/memory``.
    """
    override = os.environ.get("CANTRIP_MEMORY_DIR")
    if override:
        return pathlib.Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = pathlib.Path(xdg).expanduser() if xdg else pathlib.Path.home() / ".config"
    return base / "cantrip" / "memory"


def shared_memory_dir(charm_path: pathlib.Path) -> pathlib.Path:
    """Return the conventional shared-memory directory under *charm_path*.

    The path is ``<charm-root>/.cantrip-shared/memory/``.  The team-sync
    spec originally proposed ``.cantrip/shared/memory/``, but
    ``<charm-root>/.cantrip`` is currently the per-charm SQLite session
    file — a single path cannot be both a file and a directory — so the
    shared layer lives at a sibling path.  Teammates commit
    ``.cantrip-shared/`` to git the same way; the rename has no other
    behavioural consequence.
    """
    return charm_path / ".cantrip-shared" / "memory"


# Valid values for the ``team_memory_writes`` setting (Phase 51b.1).
#
# - ``local`` (default): charm-scope writes land in the per-charm SQLite
#   store, matching pre-51b behaviour.
# - ``shared``: charm-scope writes land in the shared memory directory
#   so teammates pick them up on the next pull.
# - ``ask``: each charm-scope write is routed through the decider
#   callback registered on :class:`MemoryManager`; if no callback is
#   registered the write falls back to ``local`` with a debug log so an
#   unconfigured TUI never silently drops writes.
TEAM_MEMORY_WRITES_LOCAL = "local"
TEAM_MEMORY_WRITES_SHARED = "shared"
TEAM_MEMORY_WRITES_ASK = "ask"
VALID_TEAM_MEMORY_WRITES = frozenset(
    {TEAM_MEMORY_WRITES_LOCAL, TEAM_MEMORY_WRITES_SHARED, TEAM_MEMORY_WRITES_ASK}
)


def _resolve_team_memory_writes(default: str = TEAM_MEMORY_WRITES_LOCAL) -> str:
    """Read the ``CANTRIP_TEAM_MEMORY_WRITES`` env var, falling back to *default*.

    An unset or unrecognised value falls back to the default rather than
    raising, so a typo in the environment never disables charm-scope
    writes outright.
    """
    raw = os.environ.get("CANTRIP_TEAM_MEMORY_WRITES")
    if not raw:
        return default
    value = raw.strip().lower()
    if value not in VALID_TEAM_MEMORY_WRITES:
        log.warning(
            "Ignoring unknown CANTRIP_TEAM_MEMORY_WRITES=%r (expected one of %s)",
            raw,
            ", ".join(sorted(VALID_TEAM_MEMORY_WRITES)),
        )
        return default
    return value


def slugify_title(title: str) -> str:
    """Turn a memory title into a safe filename stem.

    Lower-cases, replaces runs of non-``[a-z0-9._-]`` characters with ``_``,
    strips leading and trailing separators, and falls back to ``memory``
    when the result would be empty.
    """
    slug = _SAFE_SLUG_RE.sub("_", title.lower()).strip("._-")
    return slug or "memory"


@dataclasses.dataclass
class MemoryEntry:
    """An in-memory representation of a single memory.

    Covers both charm-scope rows from SQLite and global-scope Markdown files.
    The ``scope`` field identifies the origin.
    """

    title: str
    kind: str
    body: str
    scope: str  # "charm" or "global"
    id: int | None = None
    source: str = "manual"
    tags: list[str] = dataclasses.field(default_factory=list)
    citations: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None
    last_accessed_at: str | None = None
    last_validated_at: str | None = None
    access_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view suitable for tool output."""
        return {
            "title": self.title,
            "kind": self.kind,
            "body": self.body,
            "scope": self.scope,
            "id": self.id,
            "source": self.source,
            "tags": list(self.tags),
            "citations": list(self.citations),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_accessed_at": self.last_accessed_at,
            "last_validated_at": self.last_validated_at,
            "access_count": self.access_count,
        }


@dataclasses.dataclass(frozen=True)
class CitationCheck:
    """Outcome of validating a single citation against the current filesystem."""

    citation: dict[str, Any]
    ok: bool
    reason: str


# Default soft-expiry window — memories that have neither been accessed
# nor revalidated within this many days are archived by a sweep.  Taken
# from Phase 43.2's spec; override per-call or via ``CANTRIP_MEMORY_SOFT_EXPIRY_DAYS``.
DEFAULT_SOFT_EXPIRY_DAYS = 60

# Default hard-prompt window — archived memories older than this many days
# are surfaced as deletion candidates so the user can clear them out.
# Override via ``CANTRIP_MEMORY_HARD_EXPIRY_DAYS``.
DEFAULT_HARD_EXPIRY_DAYS = 180


@dataclasses.dataclass(frozen=True)
class SweepResult:
    """Summary of a TTL sweep pass.

    ``archived`` lists the ``(scope, title)`` pairs that moved from
    ``active`` to ``archived`` on this sweep; ``kept`` is the count of
    active entries left untouched.  The ``cutoff`` timestamp is what the
    sweep used to decide staleness, handy for surfacing in UI.
    """

    archived: list[tuple[str, str]]
    kept: int
    cutoff: str


@dataclasses.dataclass(frozen=True)
class RevalidationResult:
    """Outcome of revalidating a single memory's citations.

    ``new_status`` is set when revalidation changed the memory's lifecycle
    status (``active`` → ``quarantined`` or the reverse); ``None`` means
    the status was left untouched.  ``validated_at`` is the ISO timestamp
    that got written to the entry's ``last_validated_at`` column, letting
    callers surface "last checked X minutes ago" in UI later.
    """

    title: str
    scope: str
    ok: bool
    reason: str
    checks: list[CitationCheck] = dataclasses.field(default_factory=list)
    new_status: str | None = None
    validated_at: str | None = None


def sha_for_range(path: pathlib.Path, line_start: int | None, line_end: int | None) -> str:
    """Return the hex SHA-256 of ``path`` (optionally restricted to a line range).

    Lines are 1-indexed and inclusive on both ends.  Passing ``None`` for
    either bound uses the start or end of the file respectively.  This is
    the canonical hash stored in a citation so revalidation can spot a
    drifting source file.
    """
    text = path.read_text()
    if line_start is None and line_end is None:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    lines = text.splitlines(keepends=True)
    start_idx = max(1, line_start or 1) - 1
    end_idx = len(lines) if line_end is None else min(len(lines), line_end)
    selected = "".join(lines[start_idx:end_idx])
    return hashlib.sha256(selected.encode("utf-8")).hexdigest()


def validate_citation(
    citation: dict[str, Any], *, base_path: pathlib.Path | None = None
) -> CitationCheck:
    """Check a single citation against the current filesystem.

    The citation is considered valid when ``path`` resolves to a readable
    file and — when a ``sha`` is stored — its current SHA matches.
    Citations without a ``sha`` are treated as existence-only checks: the
    file merely has to still be there.  Relative paths resolve against
    ``base_path`` when supplied; otherwise relative paths report as
    invalid since there is no stable anchor for them.
    """
    raw_path = citation.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return CitationCheck(citation=citation, ok=False, reason="missing path")
    candidate = pathlib.Path(raw_path)
    if not candidate.is_absolute():
        if base_path is None:
            return CitationCheck(
                citation=citation,
                ok=False,
                reason=f"relative path {raw_path!r} has no base to resolve against",
            )
        candidate = base_path / candidate
    if not candidate.is_file():
        return CitationCheck(citation=citation, ok=False, reason=f"file not found: {candidate}")
    stored_sha = citation.get("sha")
    if not isinstance(stored_sha, str) or not stored_sha:
        return CitationCheck(citation=citation, ok=True, reason="file exists")
    line_start = _maybe_int(citation.get("line_start"))
    line_end = _maybe_int(citation.get("line_end"))
    try:
        actual_sha = sha_for_range(candidate, line_start, line_end)
    except OSError as exc:
        return CitationCheck(citation=citation, ok=False, reason=f"cannot read {candidate}: {exc}")
    if actual_sha != stored_sha:
        return CitationCheck(
            citation=citation,
            ok=False,
            reason=f"sha mismatch at {candidate}: stored {stored_sha[:12]}…, "
            f"current {actual_sha[:12]}…",
        )
    return CitationCheck(citation=citation, ok=True, reason="sha match")


def _maybe_int(value: Any) -> int | None:
    """Best-effort int coercion; returns ``None`` on anything uncoerceable."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_soft_expiry() -> int:
    """Return the soft-expiry window in days, honouring ``CANTRIP_MEMORY_SOFT_EXPIRY_DAYS``.

    An invalid or non-positive env value falls back to the default so a
    misconfiguration never disables expiry silently.
    """
    return _resolve_positive_int_env("CANTRIP_MEMORY_SOFT_EXPIRY_DAYS", DEFAULT_SOFT_EXPIRY_DAYS)


def _resolve_hard_expiry() -> int:
    """Return the hard-prompt window in days, honouring ``CANTRIP_MEMORY_HARD_EXPIRY_DAYS``."""
    return _resolve_positive_int_env("CANTRIP_MEMORY_HARD_EXPIRY_DAYS", DEFAULT_HARD_EXPIRY_DAYS)


def _resolve_positive_int_env(name: str, default: int) -> int:
    """Read *name* from the environment as a positive int, falling back on misconfig."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        log.warning("Ignoring non-integer %s=%r", name, raw)
        return default
    if parsed <= 0:
        log.warning("Ignoring non-positive %s=%s", name, parsed)
        return default
    return parsed


def _parse_iso(value: str | None) -> datetime.datetime | None:
    """Best-effort ISO-8601 parse; returns naive datetimes as UTC-aware."""
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed


def _is_stale(entry: MemoryEntry, cutoff: datetime.datetime) -> bool:
    """Return True when the memory's most recent touch is older than ``cutoff``.

    Checks ``last_accessed_at`` and ``last_validated_at`` (falling back to
    ``created_at`` when either is missing).  A memory is stale only when
    *both* signals are older than the cutoff — one recent touch keeps it
    alive.  An entry with no parseable timestamps at all is treated as
    fresh so a corrupt row never gets silently archived.
    """
    accessed = _parse_iso(entry.last_accessed_at) or _parse_iso(entry.created_at)
    validated = _parse_iso(entry.last_validated_at) or _parse_iso(entry.created_at)
    if accessed is None and validated is None:
        return False
    if accessed is not None and accessed >= cutoff:
        return False
    return not (validated is not None and validated >= cutoff)


class GlobalMemoryStore:
    """Filesystem-backed memory store under ``~/.config/cantrip/memory/``.

    Individual memories are Markdown files with YAML frontmatter.  The
    sibling ``MEMORY.md`` is an always-loaded index — one line per memory —
    that the system prompt injects verbatim so the agent can decide which
    memories to ``memory_read`` for full context.

    Parameters ``scope`` and ``source_override`` exist so subclasses
    (notably :class:`SharedMemoryStore`) can reuse the same on-disk
    machinery while reporting a different ``MemoryEntry.scope`` / ``source``
    pair to callers.  The ``GlobalMemoryStore`` defaults preserve the
    pre-51b behaviour: ``scope="global"``, no source override.
    """

    def __init__(
        self,
        directory: pathlib.Path | None = None,
        *,
        scope: str = "global",
        source_override: str | None = None,
    ) -> None:
        self._dir = directory or _default_global_dir()
        self._scope = scope
        self._source_override = source_override

    @property
    def directory(self) -> pathlib.Path:
        """Return the on-disk directory backing this store."""
        return self._dir

    @property
    def index_path(self) -> pathlib.Path:
        """Return the path to the always-loaded MEMORY.md index."""
        return self._dir / INDEX_FILENAME

    def _ensure_dir(self) -> None:
        """Create the backing directory on first write, 0700 to match secret stores."""
        if not self._dir.exists():
            self._dir.mkdir(parents=True, exist_ok=True)
            try:
                self._dir.chmod(0o700)
            except OSError:
                # Best-effort permission hardening; some filesystems (e.g.
                # mounted VM shares) don't support chmod.
                log.debug("Could not chmod %s; leaving default permissions", self._dir)

    def _path_for(self, title: str) -> pathlib.Path:
        return self._dir / f"{slugify_title(title)}.md"

    def list_entries(
        self,
        *,
        kind: str | None = None,
        status: str | None = "active",
        tag: str | None = None,
    ) -> list[MemoryEntry]:
        """List all memory files, optionally filtered by kind, status, or tag."""
        if not self._dir.is_dir():
            return []
        entries: list[MemoryEntry] = []
        for path in sorted(self._dir.iterdir()):
            if path.name == INDEX_FILENAME or not path.is_file():
                continue
            if path.suffix.lower() != ".md":
                continue
            try:
                entry = self._read_file(path)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                log.warning("Skipping malformed global memory %s: %s", path, exc)
                continue
            if kind is not None and entry.kind != kind:
                continue
            if status is not None and entry.status != status:
                continue
            if tag is not None and tag not in entry.tags:
                continue
            entries.append(entry)
        return entries

    def get(self, title: str) -> MemoryEntry | None:
        """Return the memory with *title* or ``None`` if no file exists."""
        path = self._path_for(title)
        if not path.exists():
            return None
        try:
            return self._read_file(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            log.warning("Cannot read global memory %s: %s", path, exc)
            return None

    def search(self, query: str, *, status: str | None = "active") -> list[MemoryEntry]:
        """Case-insensitive substring match across title and body."""
        needle = query.lower()
        return [
            entry
            for entry in self.list_entries(status=status)
            if needle in entry.title.lower() or needle in entry.body.lower()
        ]

    def write(
        self,
        title: str,
        kind: str,
        body: str,
        *,
        source: str = "manual",
        citations: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        status: str = "active",
    ) -> MemoryEntry:
        """Create or overwrite the memory file for *title*."""
        self._ensure_dir()
        path = self._path_for(title)
        now = _now_iso()
        # Stamp the on-disk source with the override so a future reader
        # without the override (e.g. someone manually inspecting the file
        # on a teammate's machine) still sees that the entry came from
        # the shared layer.
        effective_source = self._source_override if self._source_override is not None else source
        frontmatter: dict[str, Any] = {
            "title": title,
            "kind": kind,
            "source": effective_source,
            "created": now,
            "updated": now,
            "status": status,
            "tags": list(tags or []),
            "citations": list(citations or []),
        }
        # Preserve the original ``created`` timestamp on overwrite so we don't
        # erase the provenance of a long-lived memory.
        if path.exists():
            try:
                existing = self._read_file(path)
                if existing.created_at:
                    frontmatter["created"] = existing.created_at
            except (OSError, ValueError, yaml.YAMLError):
                log.debug("Ignoring existing malformed memory at %s on overwrite", path)
        rendered = _render_markdown(frontmatter, body)
        path.write_text(rendered)
        self._rebuild_index()
        return self._read_file(path)

    def update(
        self,
        title: str,
        *,
        body: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        citations: list[dict[str, Any]] | None = None,
        last_accessed_at: str | None = None,
        last_validated_at: str | None = None,
    ) -> MemoryEntry | None:
        """Partial update of an existing global memory file."""
        existing = self.get(title)
        if existing is None:
            return None
        now = _now_iso()
        effective_source = (
            self._source_override if self._source_override is not None else existing.source
        )
        frontmatter: dict[str, Any] = {
            "title": existing.title,
            "kind": kind if kind is not None else existing.kind,
            "source": effective_source,
            "created": existing.created_at or now,
            "updated": now,
            "status": status if status is not None else existing.status,
            "tags": list(tags if tags is not None else existing.tags),
            "citations": list(citations if citations is not None else existing.citations),
        }
        if last_accessed_at is not None:
            frontmatter["last_accessed"] = last_accessed_at
        elif existing.last_accessed_at:
            frontmatter["last_accessed"] = existing.last_accessed_at
        if last_validated_at is not None:
            frontmatter["last_validated"] = last_validated_at
        elif existing.last_validated_at:
            frontmatter["last_validated"] = existing.last_validated_at
        new_body = body if body is not None else existing.body
        path = self._path_for(title)
        path.write_text(_render_markdown(frontmatter, new_body))
        self._rebuild_index()
        return self._read_file(path)

    def delete(self, title: str) -> bool:
        """Remove the memory file for *title*; return ``True`` if a file was removed."""
        path = self._path_for(title)
        if not path.exists():
            return False
        path.unlink()
        self._rebuild_index()
        return True

    def read_index(self) -> str:
        """Return the contents of the MEMORY.md index, or empty string.

        Truncates to :data:`MEMORY_INDEX_MAX_LINES` lines so the system-prompt
        injection stays bounded even if the file grows large.
        """
        if not self.index_path.exists():
            return ""
        try:
            raw = self.index_path.read_text()
        except OSError:
            return ""
        lines = raw.splitlines()
        if len(lines) <= MEMORY_INDEX_MAX_LINES:
            return raw
        kept = lines[:MEMORY_INDEX_MAX_LINES]
        kept.append(f"[truncated — {len(lines) - MEMORY_INDEX_MAX_LINES} more lines omitted]")
        return "\n".join(kept) + "\n"

    def _rebuild_index(self) -> None:
        """Regenerate MEMORY.md from the current on-disk files.

        The index is one line per memory: ``- [title](file.md) — description``
        where the description is the memory's first non-empty body line.
        """
        if not self._dir.is_dir():
            return
        entries = self.list_entries(status=None)
        header = "# Memory Index\n\n"
        if not entries:
            self.index_path.write_text(header)
            return
        lines = [header]
        for entry in entries:
            filename = self._path_for(entry.title).name
            first_line = _first_line(entry.body)
            hook = first_line[:120] if first_line else entry.kind
            lines.append(f"- [{entry.title}]({filename}) — {hook}\n")
        self.index_path.write_text("".join(lines))

    def _read_file(self, path: pathlib.Path) -> MemoryEntry:
        """Parse a memory Markdown file into a :class:`MemoryEntry`."""
        raw = path.read_text()
        frontmatter, body = _split_frontmatter(raw)
        if not isinstance(frontmatter, dict):
            raise ValueError(f"Frontmatter is not a mapping in {path}")
        title = frontmatter.get("title")
        kind = frontmatter.get("kind")
        if not title or not kind:
            raise ValueError(f"Frontmatter missing title or kind in {path}")
        if self._source_override is not None:
            source = self._source_override
        else:
            source = str(frontmatter.get("source", "manual"))
        return MemoryEntry(
            title=str(title),
            kind=str(kind),
            body=body,
            scope=self._scope,
            source=source,
            tags=[str(t) for t in frontmatter.get("tags", []) or []],
            citations=list(frontmatter.get("citations", []) or []),
            status=str(frontmatter.get("status", "active")),
            created_at=_opt_str(frontmatter.get("created")),
            updated_at=_opt_str(frontmatter.get("updated")),
            last_accessed_at=_opt_str(frontmatter.get("last_accessed")),
            last_validated_at=_opt_str(frontmatter.get("last_validated")),
        )


class SharedMemoryStore(GlobalMemoryStore):
    """Filesystem-backed shared memory store under ``<charm-root>/.cantrip/shared/memory/``.

    Reuses the on-disk format and machinery of :class:`GlobalMemoryStore`,
    but reports entries with ``scope="charm"`` (since the directory is
    charm-rooted) and ``source="shared"`` so callers can filter shared
    entries out of listings or display them differently from local
    charm-scope entries living in SQLite.

    Construct via :meth:`for_charm` so the conventional path under the
    charm root is used; pass an explicit ``directory`` for tests.
    """

    def __init__(self, directory: pathlib.Path) -> None:
        super().__init__(directory, scope="charm", source_override="shared")

    @classmethod
    def for_charm(cls, charm_path: pathlib.Path) -> SharedMemoryStore:
        """Return a store rooted at the conventional path under *charm_path*."""
        return cls(shared_memory_dir(charm_path))


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string without microseconds."""
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat()


def _opt_str(value: Any) -> str | None:
    """Coerce an optional frontmatter field to ``str | None``."""
    if value is None:
        return None
    return str(value)


def _first_line(body: str) -> str:
    """Return the first non-empty line of *body*, stripped."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _render_markdown(frontmatter: dict[str, Any], body: str) -> str:
    """Render YAML frontmatter and Markdown body into a SKILL.md-style file."""
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    trimmed = body.strip()
    return f"---\n{yaml_block}\n---\n\n{trimmed}\n" if trimmed else f"---\n{yaml_block}\n---\n"


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown file into its YAML frontmatter dict and Markdown body."""
    lines = raw.split("\n")
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return {}, raw
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_DELIMITER:
            end = i
            break
    if end is None:
        return {}, raw
    frontmatter_text = "\n".join(lines[1:end])
    data = yaml.safe_load(frontmatter_text) or {}
    body = "\n".join(lines[end + 1 :]).strip()
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}, body


class MemoryManager:
    """Unified interface over charm-scope (SQLite) and global-scope (filesystem) memories.

    Tools call the manager to list, read, write, update, and forget memories
    without caring which scope they live in.  The manager picks the backend
    from the ``scope`` argument; read and search default to spanning both.

    Phase 51b.1: when a :class:`SharedMemoryStore` is supplied, charm-scope
    operations also consult ``<charm-root>/.cantrip/shared/memory/``.  The
    ``team_memory_writes`` setting selects between the local SQLite store
    and the shared directory for new charm-scope writes.
    """

    def __init__(
        self,
        session_store: SessionStore | None,
        global_store: GlobalMemoryStore | None = None,
        *,
        charm_path: pathlib.Path | None = None,
        shared_store: SharedMemoryStore | None = None,
        team_memory_writes: str | None = None,
        team_memory_decider: Callable[[str, str], str] | None = None,
    ) -> None:
        self._session_store = session_store
        self._global_store = global_store or GlobalMemoryStore()
        self._charm_path = charm_path
        if shared_store is None and charm_path is not None:
            shared_store = SharedMemoryStore.for_charm(charm_path)
        self._shared_store = shared_store
        if team_memory_writes is None:
            team_memory_writes = _resolve_team_memory_writes()
        elif team_memory_writes not in VALID_TEAM_MEMORY_WRITES:
            raise MemoryScopeError(
                f"Invalid team_memory_writes: {team_memory_writes!r}. "
                f"Must be one of: {', '.join(sorted(VALID_TEAM_MEMORY_WRITES))}"
            )
        self._team_memory_writes = team_memory_writes
        self._team_memory_decider = team_memory_decider
        self._on_recall: Callable[[MemoryEntry], None] | None = None
        self._on_write: Callable[[MemoryEntry], None] | None = None

    def set_recall_callback(self, callback: Callable[[MemoryEntry], None] | None) -> None:
        """Register a callback fired whenever a memory is read by title.

        Used by the agent to surface "Recalled memory: …" in UI without
        coupling the manager to the event bus directly.  Pass ``None``
        to clear.
        """
        self._on_recall = callback

    def set_write_callback(self, callback: Callable[[MemoryEntry], None] | None) -> None:
        """Register a callback fired whenever a memory is created or overwritten.

        Mirrors :meth:`set_recall_callback` so the agent can publish a
        "Wrote memory: …" UI event regardless of whether the write came
        from the auto-writer or a tool call.
        """
        self._on_write = callback

    @property
    def global_store(self) -> GlobalMemoryStore:
        """The filesystem-backed global memory store."""
        return self._global_store

    @property
    def shared_store(self) -> SharedMemoryStore | None:
        """The shared (team-sync) memory store, or ``None`` when not configured."""
        return self._shared_store

    @property
    def team_memory_writes(self) -> str:
        """Current ``team_memory_writes`` setting (``local`` / ``shared`` / ``ask``)."""
        return self._team_memory_writes

    def has_charm_scope(self) -> bool:
        """Return True when a per-charm SQLite store is available."""
        return self._session_store is not None

    # ── Listing and lookup ──────────────────────────────────────────────

    def list_entries(
        self,
        *,
        scope: str | None = None,
        kind: str | None = None,
        status: str | None = "active",
        tag: str | None = None,
    ) -> list[MemoryEntry]:
        """Return entries matching the filters.  ``scope=None`` spans both sides.

        When a shared store is configured, charm-scope listings include
        entries from ``<charm-root>/.cantrip/shared/memory/`` after the
        local SQLite rows; titles that exist in both stores are surfaced
        twice — local and shared — so callers can see the divergence.
        """
        entries: list[MemoryEntry] = []
        if scope in (None, "charm") and self._session_store is not None:
            for row in self._session_store.list_memory(kind=kind, status=status, tag=tag):
                entries.append(_row_to_entry(row))
        if scope in (None, "charm") and self._shared_store is not None:
            entries.extend(self._shared_store.list_entries(kind=kind, status=status, tag=tag))
        if scope in (None, "global"):
            entries.extend(self._global_store.list_entries(kind=kind, status=status, tag=tag))
        return entries

    def read(self, *, title: str, scope: str | None = None) -> MemoryEntry | None:
        """Read a single memory by title; optionally restrict to one scope.

        When ``scope`` is ``None``, charm-scope is searched first so a charm
        override shadows a global memory of the same name.  Within charm
        scope, the local SQLite store wins over the shared directory so a
        teammate's just-pulled entry doesn't overwrite something the local
        operator deliberately customised.  The matched entry's access
        counter is bumped as a side effect, and the recall callback
        (if any) is fired so UIs can show "Recalled memory: …".
        """
        entry: MemoryEntry | None = None
        if scope in (None, "charm") and self._session_store is not None:
            row = self._session_store.get_memory_by_title(title)
            if row is not None:
                self._session_store.touch_memory(cast("int", row["id"]))
                entry = _row_to_entry(row)
        if entry is None and scope in (None, "charm") and self._shared_store is not None:
            entry = self._shared_store.get(title)
        if entry is None and scope in (None, "global"):
            entry = self._global_store.get(title)
        if entry is not None and self._on_recall is not None:
            try:
                self._on_recall(entry)
            except Exception:  # noqa: BLE001 - never let a UI hook break recall.
                log.debug("recall callback failed", exc_info=True)
        return entry

    def search(self, query: str, *, scope: str | None = None) -> list[MemoryEntry]:
        """Keyword search across scopes. Returns charm-scope hits first."""
        entries: list[MemoryEntry] = []
        if scope in (None, "charm") and self._session_store is not None:
            for row in self._session_store.search_memory(query):
                entries.append(_row_to_entry(row))
        if scope in (None, "charm") and self._shared_store is not None:
            entries.extend(self._shared_store.search(query))
        if scope in (None, "global"):
            entries.extend(self._global_store.search(query))
        return entries

    # ── Mutation ────────────────────────────────────────────────────────

    def write(
        self,
        *,
        scope: str,
        title: str,
        kind: str,
        body: str,
        source: str = "manual",
        tags: list[str] | None = None,
        citations: list[dict[str, Any]] | None = None,
        status: str = "active",
    ) -> MemoryEntry:
        """Create a new memory in *scope*. Overwrites an existing entry with the same title.

        Charm-scope writes consult the ``team_memory_writes`` setting:
        ``local`` (default) routes to the SQLite store, ``shared`` routes
        to the shared directory under ``<charm-root>/.cantrip/shared/memory/``,
        and ``ask`` calls the registered decider callback (falling back
        to local when no callback is registered).
        """
        _validate_kind(kind)
        _validate_status(status)
        entry: MemoryEntry
        if scope == "charm":
            target = self._resolve_charm_write_target(title, kind)
            if target == "shared":
                if self._shared_store is None:
                    raise MemoryScopeError(
                        "shared charm-scope memory requires a shared store "
                        "(needs charm_path on MemoryManager)"
                    )
                entry = self._shared_store.write(
                    title,
                    kind,
                    body,
                    source=source,
                    citations=citations,
                    tags=tags,
                    status=status,
                )
            else:
                if self._session_store is None:
                    raise MemoryScopeError("charm-scope memory requires an active charm session")
                existing = self._session_store.get_memory_by_title(title)
                if existing is None:
                    memory_id = self._session_store.record_memory(
                        title=title,
                        kind=kind,
                        body=body,
                        source=source,
                        citations=citations,
                        tags=tags,
                        status=status,
                    )
                    row = self._session_store.get_memory(memory_id)
                else:
                    self._session_store.update_memory(
                        cast("int", existing["id"]),
                        body=body,
                        kind=kind,
                        tags=tags,
                        status=status,
                        citations=citations,
                    )
                    row = self._session_store.get_memory(cast("int", existing["id"]))
                assert row is not None
                entry = _row_to_entry(row)
        elif scope == "global":
            entry = self._global_store.write(
                title,
                kind,
                body,
                source=source,
                citations=citations,
                tags=tags,
                status=status,
            )
        else:
            raise MemoryScopeError(f"Unknown memory scope: {scope!r}")
        if self._on_write is not None:
            try:
                self._on_write(entry)
            except Exception:  # noqa: BLE001 - never let a UI hook break write.
                log.debug("write callback failed", exc_info=True)
        return entry

    def _resolve_charm_write_target(self, title: str, kind: str) -> str:
        """Pick ``"local"`` or ``"shared"`` for a charm-scope write.

        ``team_memory_writes`` drives the choice.  ``ask`` mode invokes
        the registered decider callback with ``(title, kind)`` and
        expects ``"local"`` or ``"shared"`` back; any other return falls
        back to ``"local"`` with a warning.  An unset decider in ``ask``
        mode also falls back to ``"local"`` so an unconfigured TUI never
        silently drops writes.
        """
        mode = self._team_memory_writes
        if mode == TEAM_MEMORY_WRITES_SHARED:
            return "shared" if self._shared_store is not None else "local"
        if mode == TEAM_MEMORY_WRITES_ASK:
            if self._team_memory_decider is None or self._shared_store is None:
                log.debug(
                    "team_memory_writes=ask but no decider/shared store; falling back to local"
                )
                return "local"
            try:
                choice = self._team_memory_decider(title, kind)
            except Exception:  # noqa: BLE001 - decider is user code, never break the write.
                log.warning("team_memory_decider raised; falling back to local", exc_info=True)
                return "local"
            if choice == "shared":
                return "shared"
            if choice != "local":
                log.warning(
                    "team_memory_decider returned %r (expected local|shared); using local", choice
                )
            return "local"
        return "local"

    def update(
        self,
        *,
        scope: str,
        title: str,
        body: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        citations: list[dict[str, Any]] | None = None,
        last_validated_at: str | None = None,
    ) -> MemoryEntry | None:
        """Partial update of an existing memory."""
        if kind is not None:
            _validate_kind(kind)
        if status is not None:
            _validate_status(status)
        if scope == "charm":
            if self._session_store is not None:
                row = self._session_store.get_memory_by_title(title)
                if row is not None:
                    self._session_store.update_memory(
                        cast("int", row["id"]),
                        body=body,
                        kind=kind,
                        tags=tags,
                        status=status,
                        citations=citations,
                        last_validated_at=last_validated_at,
                    )
                    return _row_to_entry(
                        cast(
                            "dict[str, object]",
                            self._session_store.get_memory(cast("int", row["id"])),
                        )
                    )
            if self._shared_store is not None:
                return self._shared_store.update(
                    title,
                    body=body,
                    kind=kind,
                    tags=tags,
                    status=status,
                    citations=citations,
                    last_validated_at=last_validated_at,
                )
            return None
        if scope == "global":
            return self._global_store.update(
                title,
                body=body,
                kind=kind,
                tags=tags,
                status=status,
                citations=citations,
                last_validated_at=last_validated_at,
            )
        raise MemoryScopeError(f"Unknown memory scope: {scope!r}")

    def forget(self, *, scope: str, title: str) -> bool:
        """Delete the memory; return True when something was removed.

        Charm-scope deletes prefer the local SQLite store; if the title
        exists only in the shared directory the shared file is removed
        instead.  An entry that lives in both stores has only its local
        copy deleted — the caller has to forget again to remove the
        shared copy, mirroring the read-precedence rule.
        """
        if scope == "charm":
            if self._session_store is not None:
                row = self._session_store.get_memory_by_title(title)
                if row is not None:
                    return self._session_store.delete_memory(cast("int", row["id"]))
            if self._shared_store is not None:
                return self._shared_store.delete(title)
            return False
        if scope == "global":
            return self._global_store.delete(title)
        raise MemoryScopeError(f"Unknown memory scope: {scope!r}")

    # ── Revalidation ────────────────────────────────────────────────────

    def revalidate(self, *, scope: str, title: str) -> RevalidationResult:
        """Validate the citations on a single memory and update its status.

        A memory with no citations is left at its current status but still
        gets a fresh ``last_validated_at`` timestamp — the check is
        trivially successful.  On any citation failure the memory is moved
        to ``quarantined`` so the prompt-index excludes it.  Recovery (a
        later revalidate that passes) moves it back to ``active``.
        """
        entry = self.read(title=title, scope=scope)
        if entry is None:
            return RevalidationResult(
                title=title, scope=scope, ok=False, reason="not found", checks=[]
            )
        checks = [validate_citation(c, base_path=self._charm_path) for c in entry.citations]
        all_ok = all(c.ok for c in checks)
        new_status: str | None = None
        if entry.status == "active" and not all_ok:
            new_status = "quarantined"
        elif entry.status == "quarantined" and all_ok:
            new_status = "active"
        now = _now_iso()
        self.update(
            scope=scope,
            title=title,
            status=new_status,
            last_validated_at=now,
        )
        return RevalidationResult(
            title=title,
            scope=scope,
            ok=all_ok,
            reason=(
                "no citations"
                if not checks
                else "all citations valid"
                if all_ok
                else "one or more citations invalid"
            ),
            checks=checks,
            new_status=new_status,
            validated_at=now,
        )

    def revalidate_all(self, *, scope: str | None = None) -> list[RevalidationResult]:
        """Revalidate every entry in *scope* (or both scopes by default)."""
        results: list[RevalidationResult] = []
        for entry in self.list_entries(scope=scope, status=None):
            results.append(self.revalidate(scope=entry.scope, title=entry.title))
        return results

    # ── TTL sweep ───────────────────────────────────────────────────────

    def sweep_stale(
        self,
        *,
        scope: str | None = None,
        soft_days: int | None = None,
        now: datetime.datetime | None = None,
    ) -> SweepResult:
        """Archive active memories whose last touch is older than the threshold.

        A memory is stale when ``last_accessed_at`` *and* ``last_validated_at``
        (falling back to ``created_at`` when either is missing) are older
        than ``soft_days`` days.  Only ``active`` entries are considered so
        the sweep is idempotent — already-archived and quarantined memories
        are left alone.
        """
        threshold = soft_days if soft_days is not None else _resolve_soft_expiry()
        reference = now or datetime.datetime.now(datetime.UTC)
        cutoff_dt = reference - datetime.timedelta(days=threshold)
        cutoff = cutoff_dt.replace(microsecond=0).isoformat()
        archived: list[tuple[str, str]] = []
        kept = 0
        for entry in self.list_entries(scope=scope, status="active"):
            if _is_stale(entry, cutoff_dt):
                self.update(scope=entry.scope, title=entry.title, status="archived")
                archived.append((entry.scope, entry.title))
            else:
                kept += 1
        return SweepResult(archived=archived, kept=kept, cutoff=cutoff)

    def list_due_for_purge(
        self,
        *,
        scope: str | None = None,
        hard_days: int | None = None,
        now: datetime.datetime | None = None,
    ) -> list[MemoryEntry]:
        """Return archived memories that have aged past the hard-prompt threshold.

        These are candidates for permanent deletion via the hard-prompt
        flow ("delete or refresh?").  Only entries with ``status='archived'``
        whose ``updated_at`` is older than ``hard_days`` ago qualify.
        ``updated_at`` is the natural anchor: it's set when the sweep
        archived the entry, so the count starts from the archive moment
        rather than from the original creation date.
        """
        threshold = hard_days if hard_days is not None else _resolve_hard_expiry()
        reference = now or datetime.datetime.now(datetime.UTC)
        cutoff = reference - datetime.timedelta(days=threshold)
        candidates: list[MemoryEntry] = []
        for entry in self.list_entries(scope=scope, status="archived"):
            anchor = _parse_iso(entry.updated_at) or _parse_iso(entry.created_at)
            if anchor is not None and anchor < cutoff:
                candidates.append(entry)
        return candidates

    # ── Prompt injection ────────────────────────────────────────────────

    def render_prompt_index(self) -> str:
        """Render the Memory Index section for the system prompt.

        Always returns *something* even when both scopes are empty — an
        empty string — so the template can trivially skip the section.
        """
        parts: list[str] = []
        global_index = self._global_store.read_index()
        if global_index.strip():
            parts.append("### Global\n\n" + global_index.strip())
        charm_lines: list[str] = []
        if self._session_store is not None:
            for row in self._session_store.list_memory(status="active"):
                title = row["title"]
                kind = row["kind"]
                tags = row["tags"] if isinstance(row["tags"], list) else []
                tag_suffix = f" [{', '.join(tags)}]" if tags else ""
                charm_lines.append(f"- **{title}** ({kind}){tag_suffix}")
        if self._shared_store is not None:
            for entry in self._shared_store.list_entries(status="active"):
                tag_suffix = f" [{', '.join(entry.tags)}]" if entry.tags else ""
                charm_lines.append(f"- **{entry.title}** ({entry.kind}, shared){tag_suffix}")
        if charm_lines:
            parts.append("### Charm\n\n" + "\n".join(charm_lines))
        return "\n\n".join(parts).strip()


class MemoryScopeError(ValueError):
    """Raised when a caller requests an unknown or unavailable memory scope."""


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        allowed = ", ".join(sorted(VALID_KINDS))
        raise MemoryScopeError(f"Invalid memory kind: {kind!r}. Must be one of: {allowed}")


def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        allowed = ", ".join(sorted(VALID_STATUSES))
        raise MemoryScopeError(f"Invalid memory status: {status!r}. Must be one of: {allowed}")


def _row_to_entry(row: dict[str, object]) -> MemoryEntry:
    """Convert a charm-scope SQLite row dict to a :class:`MemoryEntry`."""
    tags_raw = row.get("tags") or []
    citations_raw = row.get("citations") or []
    tags = [str(t) for t in cast("list[Any]", tags_raw)]
    citations = list(cast("list[dict[str, Any]]", citations_raw))
    return MemoryEntry(
        title=str(row["title"]),
        kind=str(row["kind"]),
        body=str(row["body"]),
        scope="charm",
        id=cast("int", row["id"]),
        source=str(row.get("source", "manual")),
        tags=tags,
        citations=citations,
        status=str(row.get("status", "active")),
        created_at=_opt_str(row.get("created_at")),
        updated_at=_opt_str(row.get("updated_at")),
        last_accessed_at=_opt_str(row.get("last_accessed_at")),
        last_validated_at=_opt_str(row.get("last_validated_at")),
        access_count=int(cast("int", row.get("access_count") or 0)),
    )


__all__ = [
    "DEFAULT_HARD_EXPIRY_DAYS",
    "DEFAULT_SOFT_EXPIRY_DAYS",
    "INDEX_FILENAME",
    "MEMORY_INDEX_MAX_LINES",
    "TEAM_MEMORY_WRITES_ASK",
    "TEAM_MEMORY_WRITES_LOCAL",
    "TEAM_MEMORY_WRITES_SHARED",
    "VALID_KINDS",
    "VALID_STATUSES",
    "VALID_TEAM_MEMORY_WRITES",
    "CitationCheck",
    "GlobalMemoryStore",
    "MemoryEntry",
    "MemoryManager",
    "MemoryScopeError",
    "RevalidationResult",
    "SharedMemoryStore",
    "SweepResult",
    "sha_for_range",
    "shared_memory_dir",
    "slugify_title",
    "validate_citation",
]
