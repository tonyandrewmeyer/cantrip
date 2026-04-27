"""Append-only JSONL audit trail for Phase 80 policy decisions.

Phase 80.4: each policy decision made by the subagent dispatcher
lands as a single JSON line in ``<charm>/.cantrip-audit.jsonl``.
The file is additive to the SQLite ``events`` table — SQLite stays
the primary store; the JSONL is a streaming, grep-friendly export
that plays nicely with ``tail -f`` and off-the-shelf log
aggregators.

The module is intentionally small:

* Serialise a policy decision to one line.
* Write the line atomically under a lock so parallel subagent runs
  don't interleave their JSON.
* Scrub string arguments through the existing
  :func:`cantrip.agent.memory_export.sanitise_body` so secrets
  (GitHub tokens, AWS keys, Bearer tokens, Slack tokens, ``password=``
  values) never reach the audit file.

Read-side helpers live here too so the ``cantrip audit`` CLI
subcommand can filter / export without reaching into SQLite.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import json
import logging
import pathlib
import threading
from collections.abc import Iterable, Iterator
from typing import Any

from cantrip.agent.memory_export import sanitise_body

log = logging.getLogger(__name__)

#: Name of the audit file inside a charm directory.  Hidden by the
#: leading dot so ``ls`` and ``find`` don't surface it by default,
#: matching ``.cantrip`` / ``.cantrip-audit.jsonl`` naming.
AUDIT_FILENAME = ".cantrip-audit.jsonl"


class AuditAction(enum.StrEnum):
    """Possible outcomes for a policy decision.

    Values mirror the human-readable labels used in the Phase 80
    spec so audit consumers can filter with a substring match
    without reaching for the enum.
    """

    ALLOWED = "allowed"
    DENIED = "denied"
    REVIEW_REQUESTED = "review-requested"
    RATE_LIMITED = "rate-limited"


@dataclasses.dataclass(frozen=True)
class AuditEntry:
    """One line in the audit JSONL.

    Every field is JSON-serialisable.  ``timestamp`` is ISO-8601 UTC
    so ``sort`` / ``grep`` scripts stay Unicode-sortable.
    ``arguments`` is the scrubbed argument dict — callers should
    never pass raw secrets here.
    """

    timestamp: str
    task_id: str | None
    tool: str
    action: AuditAction
    policy_name: str
    reason: str
    arguments: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_json(self) -> str:
        """Serialise to a single JSON line (no trailing newline)."""
        return json.dumps(
            {
                "timestamp": self.timestamp,
                "task_id": self.task_id,
                "tool": self.tool,
                "action": self.action.value,
                "policy_name": self.policy_name,
                "reason": self.reason,
                "arguments": self.arguments,
            },
            sort_keys=False,
            ensure_ascii=False,
            default=str,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AuditEntry:
        """Build an entry from a parsed JSON dict (for CLI reads)."""
        return cls(
            timestamp=str(raw.get("timestamp", "")),
            task_id=raw.get("task_id"),
            tool=str(raw.get("tool", "")),
            action=AuditAction(raw.get("action", AuditAction.ALLOWED.value)),
            policy_name=str(raw.get("policy_name", "")),
            reason=str(raw.get("reason", "")),
            arguments=dict(raw.get("arguments", {})),
        )


def scrub_arguments(
    arguments: dict[str, Any],
    *,
    charm_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Recursively scrub string values in *arguments* through the Phase 50.2 sanitiser.

    Walks the argument tree so secrets buried in nested dicts (e.g.
    ``juju_config``'s ``values`` map) or lists (e.g. a ``run_command``
    argv carrying a token) are redacted alongside top-level strings.
    Non-collection, non-string values (numbers, booleans, ``None``)
    pass through unchanged.  The sanitiser knows about the canonical
    secret shapes (GitHub / AWS / Slack tokens, ``password=`` pairs,
    Bearer tokens) and is used elsewhere to clean memory exports and
    skill bodies — reusing it keeps the "what counts as a secret"
    answer in one place.
    """
    return {key: _scrub_value(value, charm_path=charm_path) for key, value in arguments.items()}


def _scrub_value(value: Any, *, charm_path: pathlib.Path | None) -> Any:
    """Apply :func:`sanitise_body` recursively over JSON-shaped data."""
    if isinstance(value, str):
        cleaned, _ = sanitise_body(value, charm_path=charm_path)
        return cleaned
    if isinstance(value, dict):
        return {k: _scrub_value(v, charm_path=charm_path) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v, charm_path=charm_path) for v in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(v, charm_path=charm_path) for v in value)
    return value


class AuditWriter:
    """Thread-safe append writer for ``.cantrip-audit.jsonl``.

    Multiple subagents run concurrently and all write through a
    single writer instance shared by the dispatcher.  The lock
    serialises the ``open+write+close`` dance so two JSON lines
    can't interleave partially.

    Each write flushes and ``os.fsync`` isn't used — the audit trail
    is a best-effort observability export, not a WAL.  If a crash
    loses the last line, the SQLite ``events`` table is still the
    canonical record (Phase 80.4 explicitly layers JSONL over SQLite,
    not instead of it).
    """

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> pathlib.Path:
        """File the writer appends to."""
        return self._path

    def write(self, entry: AuditEntry) -> None:
        """Append *entry* as one JSON line; parent dirs must exist."""
        line = entry.to_json()
        with self._lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")


def make_entry(
    *,
    tool: str,
    action: AuditAction,
    policy_name: str,
    reason: str,
    arguments: dict[str, Any] | None = None,
    task_id: str | None = None,
    charm_path: pathlib.Path | None = None,
    now: datetime.datetime | None = None,
) -> AuditEntry:
    """Build an ``AuditEntry`` with arguments scrubbed and timestamp stamped.

    Centralises the "make one audit line" work so callers (the
    subagent dispatcher, the main-agent hook POST path) don't each
    re-implement scrubbing and timestamp formatting.
    """
    when = now or datetime.datetime.now(datetime.UTC)
    scrubbed = scrub_arguments(arguments or {}, charm_path=charm_path)
    return AuditEntry(
        timestamp=when.isoformat(),
        task_id=task_id,
        tool=tool,
        action=action,
        policy_name=policy_name,
        reason=reason,
        arguments=scrubbed,
    )


def read_entries(path: pathlib.Path) -> Iterator[AuditEntry]:
    """Yield :class:`AuditEntry` rows from a JSONL file.

    Malformed lines log a warning and are skipped rather than
    aborting the read — the audit trail is observability data and
    one corrupt line shouldn't hide the rest.
    """
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                log.warning("Skipping malformed audit line %s:%d: %s", path, lineno, exc)
                continue
            try:
                yield AuditEntry.from_dict(raw)
            except (KeyError, ValueError, TypeError) as exc:
                log.warning("Skipping invalid audit line %s:%d: %s", path, lineno, exc)


def filter_entries(
    entries: Iterable[AuditEntry],
    *,
    task_id: str | None = None,
    action: AuditAction | str | None = None,
    tool: str | None = None,
) -> Iterator[AuditEntry]:
    """Apply the ``cantrip audit list`` filter chain to an entry iterator."""
    wanted_action: AuditAction | None = AuditAction(action) if isinstance(action, str) else action
    for entry in entries:
        if task_id is not None and entry.task_id != task_id:
            continue
        if wanted_action is not None and entry.action is not wanted_action:
            continue
        if tool is not None and entry.tool != tool:
            continue
        yield entry
