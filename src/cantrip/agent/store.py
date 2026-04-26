"""SQLite-backed session store."""

import datetime
import json
import logging
import os
import pathlib
import sqlite3
import stat

from cantrip.agent import design as design_mod
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState, Decision

log = logging.getLogger(__name__)

SCHEMA_VERSION = 12


def _safe_json_load(raw: str | None, fallback: object = None) -> object:
    """Parse a JSON string, returning *fallback* on ``None``, empty, or corrupt input."""
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


_MAX_CONTENT_BYTES = 50_000

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS session (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    charm_name TEXT,
    charm_path TEXT,
    charm_type TEXT,
    framework TEXT,
    dev_model TEXT,
    cos_model TEXT,
    design_proposal TEXT,
    message_count INTEGER DEFAULT 0,
    compactions_attempted INTEGER NOT NULL DEFAULT 0,
    emergencies_attempted INTEGER NOT NULL DEFAULT 0,
    cycle_detected INTEGER NOT NULL DEFAULT 0,
    budget_exhausted INTEGER NOT NULL DEFAULT 0,
    -- Phase 67.1: leaf message of the currently active conversation
    -- branch.  NULL for sessions with no messages yet; rebuilt to the
    -- highest message id at v12 migration time so existing transcripts
    -- read as a degenerate single-branch tree.  Updated on every
    -- record_message (advance) and delete_messages_from (rewind);
    -- /branch overrides it directly.
    active_head_message_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    choice TEXT NOT NULL,
    reason TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    -- NULL for main-conversation-loop turns and any legacy row written
    -- before the v9 migration; subagent turns stamp the task category
    -- here so /cost can break cost down by research / build / deploy /
    -- test / debug.
    category TEXT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    dependencies TEXT NOT NULL DEFAULT '[]',
    result TEXT,
    blocked_reason TEXT,
    model_hint TEXT,
    noop_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,
    tool_results TEXT,
    metadata TEXT,
    token_usage_id INTEGER,
    -- Phase 67.1: parent in the session tree.  NULL marks a root
    -- (the first message recorded).  /branch and /undo move the
    -- session.active_head_message_id pointer; the rows themselves
    -- are never deleted by branching, only by /undo.
    parent_turn_id INTEGER,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subagent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    message_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,
    tool_results TEXT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    citations TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed_at TEXT,
    last_validated_at TEXT,
    access_count INTEGER NOT NULL DEFAULT 0
);

-- Per-step durable-execution checkpoints (Phase 52.1).  One row per
-- LLM call or tool invocation inside a subagent task so replay after
-- rate-limit / Ctrl+C / crash can resume from the last completed step
-- instead of re-burning every turn from the top.  ``ordinal`` lets a
-- single step name recur within the same task (e.g. ``llm_turn`` fires
-- once per conversation turn); ``input_hash`` invalidates a stored
-- result when the caller's inputs drift, so a code change after the
-- fact doesn't get masked by a stale cache.  Garbage-collected on
-- successful task completion unless ``$CANTRIP_KEEP_CHECKPOINTS`` is
-- set.
CREATE TABLE IF NOT EXISTS step_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    result_blob BLOB NOT NULL,
    result_kind TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(task_id, step_name, ordinal)
);
CREATE INDEX IF NOT EXISTS ix_step_checkpoints_task
    ON step_checkpoints(task_id);
"""


def _truncate(text: str, max_bytes: int = _MAX_CONTENT_BYTES) -> str:
    """Truncate text exceeding *max_bytes* with a marker."""
    if len(text.encode("utf-8", errors="replace")) <= max_bytes:
        return text
    # Truncate at character boundary.
    truncated = text.encode("utf-8", errors="replace")[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + f"\n\n[truncated — {len(text)} characters total]"


def _message_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    """Convert a messages-table row to the dict shape callers expect.

    Centralised so :meth:`SessionStore.load_messages` (full tree) and
    :meth:`SessionStore.load_active_branch` (single path) decode rows
    the same way and gain new columns in lockstep.
    """
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "tool_calls": _safe_json_load(row["tool_calls"]),
        "tool_results": _safe_json_load(row["tool_results"]),
        "metadata": _safe_json_load(row["metadata"]),
        "token_usage_id": row["token_usage_id"],
        "parent_turn_id": row["parent_turn_id"],
        "timestamp": row["timestamp"],
    }


def _memory_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    """Convert a memory table row to a plain dict with decoded JSON fields."""
    return {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"],
        "body": row["body"],
        "source": row["source"],
        "citations": _safe_json_load(row["citations"], fallback=[]),
        "tags": _safe_json_load(row["tags"], fallback=[]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_accessed_at": row["last_accessed_at"],
        "last_validated_at": row["last_validated_at"],
        "access_count": row["access_count"],
    }


class SessionStore:
    """SQLite-backed persistence for Cantrip session data and token usage."""

    def __init__(self, db_path: pathlib.Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        """Open the database and ensure the schema exists."""
        is_new = not self._db_path.exists()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        # Restrict database to owner-only access (rw-------).
        if is_new:
            os.chmod(self._db_path, stat.S_IRUSR | stat.S_IWUSR)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA_SQL)

        # Initialise or migrate schema version.
        row = self._conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()
        if row[0] == 0:
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            self._conn.commit()
        else:
            self._apply_migrations()

        # Indexes that depend on columns added by migrations live here so
        # ``executescript(_SCHEMA_SQL)`` above doesn't try to index a
        # column that hasn't been added yet on a pre-migration database.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_messages_parent ON messages(parent_turn_id)"
        )
        self._conn.commit()

    def _apply_migrations(self) -> None:
        """Apply incremental schema migrations based on stored version."""
        assert self._conn is not None  # noqa: S101
        row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        current = row[0] if row else 1

        if current < 3:
            # v3: add model_hint column to tasks.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if "model_hint" not in cols:
                self._conn.execute("ALTER TABLE tasks ADD COLUMN model_hint TEXT")

        if current < 4:
            # v4: add messages, subagent_messages, and events tables.
            self._conn.executescript("""\
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    tool_calls TEXT,
                    tool_results TEXT,
                    metadata TEXT,
                    token_usage_id INTEGER,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS subagent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    message_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    tool_calls TEXT,
                    tool_results TEXT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '{}',
                    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)

        if current < 5:
            # v5: persist noop_count on tasks.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if "noop_count" not in cols:
                self._conn.execute(
                    "ALTER TABLE tasks ADD COLUMN noop_count INTEGER NOT NULL DEFAULT 0"
                )

        if current < 6:
            # v6: persist design_proposal on the session table.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(session)").fetchall()}
            if "design_proposal" not in cols:
                self._conn.execute("ALTER TABLE session ADD COLUMN design_proposal TEXT")

        if current < 7:
            # v7: persist compaction safety counters on the session table.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(session)").fetchall()}
            if "compactions_attempted" not in cols:
                self._conn.execute(
                    "ALTER TABLE session ADD COLUMN "
                    "compactions_attempted INTEGER NOT NULL DEFAULT 0"
                )
            if "emergencies_attempted" not in cols:
                self._conn.execute(
                    "ALTER TABLE session ADD COLUMN "
                    "emergencies_attempted INTEGER NOT NULL DEFAULT 0"
                )

        if current < 8:
            # v8: charm-scope memory table (Phase 43.1).
            self._conn.executescript("""\
                CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    citations TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_accessed_at TEXT,
                    last_validated_at TEXT,
                    access_count INTEGER NOT NULL DEFAULT 0
                );
            """)

        if current < 9:
            # v9: per-category cost breakdown (Phase 31.4).  Existing
            # rows get NULL so historical totals remain correct — the
            # aggregation queries treat NULL as "uncategorised".
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(token_usage)").fetchall()}
            if "category" not in cols:
                self._conn.execute("ALTER TABLE token_usage ADD COLUMN category TEXT")

        if current < 10:
            # v10: step-level durable-execution checkpoints (Phase 52.1).
            # Existing sessions gain an empty table; no backfill needed
            # because the feature only affects tasks started after the
            # upgrade.
            self._conn.executescript("""\
                CREATE TABLE IF NOT EXISTS step_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    input_hash TEXT NOT NULL,
                    result_blob BLOB NOT NULL,
                    result_kind TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(task_id, step_name, ordinal)
                );
                CREATE INDEX IF NOT EXISTS ix_step_checkpoints_task
                    ON step_checkpoints(task_id);
            """)

        if current < 11:
            # v11: persist compaction stop-flags on the session table
            # (Phase 78.3).  The counters were already persisted at v7,
            # but the boolean latches (cycle_detected, budget_exhausted)
            # were reset to False on every resume, letting a session
            # that had already been disabled silently re-arm.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(session)").fetchall()}
            if "cycle_detected" not in cols:
                self._conn.execute(
                    "ALTER TABLE session ADD COLUMN cycle_detected INTEGER NOT NULL DEFAULT 0"
                )
            if "budget_exhausted" not in cols:
                self._conn.execute(
                    "ALTER TABLE session ADD COLUMN budget_exhausted INTEGER NOT NULL DEFAULT 0"
                )

        if current < 12:
            # v12: session-tree rewind/branch (Phase 67.1).  Adds the
            # tree topology — a parent pointer on every message and a
            # leaf pointer on the session — and backfills both so an
            # existing flat transcript reads as a degenerate single-
            # branch tree (every row's parent is the previous row by
            # id; the active head is the highest id).
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(messages)").fetchall()}
            if "parent_turn_id" not in cols:
                self._conn.execute("ALTER TABLE messages ADD COLUMN parent_turn_id INTEGER")
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS ix_messages_parent ON messages(parent_turn_id)"
                )
                # Backfill: chain rows by ascending id.  LAG isn't
                # available on every shipped sqlite version so we
                # walk the rowset in Python — every existing transcript
                # is small enough that a single pass is fine.
                rows = self._conn.execute("SELECT id FROM messages ORDER BY id").fetchall()
                previous: int | None = None
                for row in rows:
                    if previous is not None:
                        self._conn.execute(
                            "UPDATE messages SET parent_turn_id = ? WHERE id = ?",
                            (previous, row[0]),
                        )
                    previous = row[0]
            session_cols = {
                r[1] for r in self._conn.execute("PRAGMA table_info(session)").fetchall()
            }
            if "active_head_message_id" not in session_cols:
                self._conn.execute("ALTER TABLE session ADD COLUMN active_head_message_id INTEGER")
            # Point the active head at the latest message so resume
            # picks up exactly where it left off.
            head_row = self._conn.execute("SELECT MAX(id) FROM messages").fetchone()
            head_id = head_row[0] if head_row else None
            session_row = self._conn.execute("SELECT id FROM session WHERE id = 1").fetchone()
            if session_row is not None:
                self._conn.execute(
                    "UPDATE session SET active_head_message_id = ? WHERE id = 1",
                    (head_id,),
                )

        if current < SCHEMA_VERSION:
            self._conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
            self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> sqlite3.Connection:
        """Return the active connection, opening the database on first access."""
        if self._conn is None:
            self.open()
        assert self._conn is not None
        return self._conn

    # ── Session CRUD ─────────────────────────────────────────────────────

    def save_session(self, state: AgentState) -> None:
        """Upsert the session row and replace all decisions."""
        db = self._db

        # Extract the raw Markdown from the design proposal for persistence.
        design_md: str | None = None
        if state.design_proposal is not None:
            to_md = getattr(state.design_proposal, "to_design_md", None)
            if callable(to_md):
                design_md = to_md()

        db.execute(
            """\
            INSERT INTO session (id, charm_name, charm_path, charm_type,
                                 framework, dev_model, cos_model,
                                 design_proposal, message_count,
                                 updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                charm_name       = excluded.charm_name,
                charm_path       = excluded.charm_path,
                charm_type       = excluded.charm_type,
                framework        = excluded.framework,
                dev_model        = excluded.dev_model,
                cos_model        = excluded.cos_model,
                design_proposal  = excluded.design_proposal,
                message_count    = excluded.message_count,
                updated_at       = datetime('now')
            """,
            (
                state.charm_name,
                str(state.charm_path) if state.charm_path else None,
                state.charm_type,
                state.framework,
                state.dev_model,
                state.cos_model,
                design_md,
                len(state.messages),
            ),
        )

        # Replace decisions: clear then re-insert.
        db.execute("DELETE FROM decisions")
        for d in state.decisions:
            db.execute(
                "INSERT INTO decisions (type, choice, reason, timestamp) VALUES (?, ?, ?, ?)",
                (d.type, d.choice, d.reason, d.timestamp.isoformat()),
            )
        db.commit()

    def load_session(self) -> AgentState | None:
        """Load session state from the database.

        Returns None when no session has been saved yet.
        """
        row = self._db.execute("SELECT * FROM session WHERE id = 1").fetchone()
        if row is None:
            return None

        state = AgentState(
            charm_name=row["charm_name"],
            charm_path=pathlib.Path(row["charm_path"]) if row["charm_path"] else None,
            charm_type=row["charm_type"],
            framework=row["framework"],
            dev_model=row["dev_model"],
            cos_model=row["cos_model"],
        )

        # Restore the design proposal from persisted Markdown.
        raw_design = row["design_proposal"]
        if raw_design:
            state.design_proposal = design_mod.parse_design_from_result(raw_design)

        decision_rows = self._db.execute(
            "SELECT type, choice, reason, timestamp FROM decisions ORDER BY id"
        ).fetchall()
        for dr in decision_rows:
            ts = dr["timestamp"]
            try:
                timestamp = datetime.datetime.fromisoformat(ts) if ts else datetime.datetime.now()
            except (ValueError, TypeError):
                timestamp = datetime.datetime.now()
            state.decisions.append(
                Decision(
                    type=dr["type"],
                    choice=dr["choice"],
                    reason=dr["reason"],
                    timestamp=timestamp,
                )
            )

        return state

    def peek_session(self) -> dict[str, object] | None:
        """Return lightweight session metadata without mutating any state.

        Used by ``CantripAgent.preview_session()`` to decide whether to
        offer a resume prompt on launch.  Returns None when no session
        row exists.
        """
        row = self._db.execute(
            "SELECT charm_name, charm_path, charm_type, framework, "
            "dev_model, cos_model, updated_at FROM session WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "charm_name": row["charm_name"],
            "charm_path": row["charm_path"],
            "charm_type": row["charm_type"],
            "framework": row["framework"],
            "dev_model": row["dev_model"],
            "cos_model": row["cos_model"],
            "updated_at": row["updated_at"],
        }

    def count_messages(self) -> int:
        """Return the number of persisted conversation messages."""
        row = self._db.execute("SELECT COUNT(*) FROM messages").fetchone()
        return int(row[0]) if row else 0

    # ── Compaction safety counters (Phase 40.2) ─────────────────────────

    def save_compaction_counters(
        self,
        compactions_attempted: int,
        emergencies_attempted: int,
        *,
        cycle_detected: bool = False,
        budget_exhausted: bool = False,
    ) -> None:
        """Persist the per-session compaction safety counters and stop-flags.

        Called from the conversation loop after each compaction/truncate so
        the budgets survive session resume.  Phase 78.3 extended this with
        the boolean ``cycle_detected`` / ``budget_exhausted`` latches — a
        session that already decided to stop compacting must remember that
        decision across resume, otherwise the very next turn could
        re-enable an ineffective compaction loop.  Assumes a session row
        already exists (save_session() creates it on first use).
        """
        self._db.execute(
            "UPDATE session SET compactions_attempted = ?, "
            "emergencies_attempted = ?, cycle_detected = ?, "
            "budget_exhausted = ?, updated_at = datetime('now') WHERE id = 1",
            (
                compactions_attempted,
                emergencies_attempted,
                1 if cycle_detected else 0,
                1 if budget_exhausted else 0,
            ),
        )
        self._db.commit()

    def load_compaction_counters(self) -> tuple[int, int, bool, bool]:
        """Return the four compaction safety values for the session.

        Returns (compactions_attempted, emergencies_attempted,
        cycle_detected, budget_exhausted).  Phase 78.3 extended this
        from a two-tuple to a four-tuple so the boolean stop-flags
        survive session resume.  Returns all-zero/False when no session
        row exists yet.
        """
        row = self._db.execute(
            "SELECT compactions_attempted, emergencies_attempted, "
            "cycle_detected, budget_exhausted FROM session WHERE id = 1"
        ).fetchone()
        if row is None:
            return 0, 0, False, False
        return (
            int(row["compactions_attempted"] or 0),
            int(row["emergencies_attempted"] or 0),
            bool(row["cycle_detected"] or 0),
            bool(row["budget_exhausted"] or 0),
        )

    # ── Task persistence ────────────────────────────────────────────────

    def save_tasks(self, tasks: list[AgentTask]) -> None:
        """Persist *tasks* using per-task upsert, removing stale rows."""
        db = self._db
        for t in tasks:
            db.execute(
                """\
                INSERT INTO tasks (id, title, status, category, description,
                                   dependencies, result, blocked_reason,
                                   model_hint, noop_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title          = excluded.title,
                    status         = excluded.status,
                    category       = excluded.category,
                    description    = excluded.description,
                    dependencies   = excluded.dependencies,
                    result         = excluded.result,
                    blocked_reason = excluded.blocked_reason,
                    model_hint     = excluded.model_hint,
                    noop_count     = excluded.noop_count
                """,
                (
                    t.id,
                    t.title,
                    t.status.value,
                    t.category.value,
                    t.description,
                    json.dumps(t.dependencies),
                    t.result,
                    t.blocked_reason,
                    t.model_hint.value if t.model_hint else None,
                    t.noop_count,
                    t.created_at.isoformat(),
                ),
            )
        # Remove rows for tasks no longer in the queue.
        current_ids = [t.id for t in tasks]
        if current_ids:
            placeholders = ",".join("?" * len(current_ids))
            db.execute(
                f"DELETE FROM tasks WHERE id NOT IN ({placeholders})",  # noqa: S608
                current_ids,
            )
        else:
            db.execute("DELETE FROM tasks")
        db.commit()

    def load_tasks(self) -> list[AgentTask]:
        """Load all tasks from the database."""
        rows = self._db.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
        tasks: list[AgentTask] = []
        for r in rows:
            try:
                raw_hint = r["model_hint"]
                deps = _safe_json_load(r["dependencies"], fallback=[]) or []
                created = datetime.datetime.fromisoformat(r["created_at"])
                tasks.append(
                    AgentTask(
                        id=r["id"],
                        title=r["title"],
                        status=TaskStatus(r["status"]),
                        category=TaskCategory(r["category"]),
                        description=r["description"],
                        dependencies=deps,
                        result=r["result"],
                        blocked_reason=r["blocked_reason"],
                        model_hint=ModelHint(raw_hint) if raw_hint else None,
                        created_at=created,
                        noop_count=r["noop_count"],
                    )
                )
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                log.warning("Skipping corrupt task row %s: %s", r["id"], exc)
        return tasks

    # ── Messages ─────────────────────────────────────────────────────────

    def record_message(
        self,
        role: str,
        content: str | None,
        tool_calls: list[dict[str, object]] | None = None,
        tool_results: list[dict[str, object]] | None = None,
        metadata: dict[str, object] | None = None,
        token_usage_id: int | None = None,
    ) -> int:
        """Persist a single conversation message. Returns the row ID.

        Phase 67.1: appends to whichever branch ``active_head_message_id``
        currently points at.  The new row's ``parent_turn_id`` is the
        head; the head is then advanced to the new row.  A NULL head
        means an empty session, so the new row becomes the root.
        """
        db = self._db
        head = self.get_active_head()
        cursor = db.execute(
            """\
            INSERT INTO messages
                (role, content, tool_calls, tool_results, metadata,
                 token_usage_id, parent_turn_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                role,
                _truncate(content or ""),
                json.dumps(tool_calls) if tool_calls else None,
                json.dumps(tool_results) if tool_results else None,
                json.dumps(metadata) if metadata else None,
                token_usage_id,
                head,
            ),
        )
        assert cursor.lastrowid is not None
        new_id = cursor.lastrowid
        self.set_active_head(new_id, commit=False)
        db.commit()
        return new_id

    def get_active_head(self) -> int | None:
        """Return the message id at the leaf of the active branch.

        ``None`` for sessions with no messages.  Used by
        :meth:`record_message` (to chain new rows to the right parent),
        :meth:`load_active_branch` (to walk back from the leaf), and
        ``/branch`` / ``/tree`` (which override it).
        """
        row = self._db.execute(
            "SELECT active_head_message_id FROM session WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        head = row["active_head_message_id"]
        return int(head) if head is not None else None

    def set_active_head(self, message_id: int | None, *, commit: bool = True) -> None:
        """Move the active-head pointer to *message_id*.

        Creates the session row if it doesn't yet exist (the very first
        ``record_message`` call lands here before
        :meth:`save_session` has run).  ``commit=False`` lets callers
        batch the head update with another write — :meth:`record_message`
        and :meth:`delete_messages_from` use that to keep the message
        insert / delete and the head update in a single transaction.
        """
        db = self._db
        existing = db.execute("SELECT id FROM session WHERE id = 1").fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO session (id, active_head_message_id) VALUES (1, ?)",
                (message_id,),
            )
        else:
            db.execute(
                "UPDATE session SET active_head_message_id = ?, "
                "updated_at = datetime('now') WHERE id = 1",
                (message_id,),
            )
        if commit:
            db.commit()

    def delete_messages_from(self, message_id: int) -> int:
        """Delete the message with *message_id* and every later message.

        Used by ``/undo`` (Phase 68.1) to truncate the persisted
        history alongside the in-memory ``state.messages`` slice.
        Returns the number of rows deleted so the caller can sanity-
        check that something actually moved.

        Phase 67.1: also rewinds ``active_head_message_id`` to the
        parent of the deleted row (or ``NULL`` when the deletion
        empties the session).  Without this, the head would still
        reference a row that no longer exists and the next
        ``record_message`` would write a dangling parent pointer.
        """
        db = self._db
        parent_row = db.execute(
            "SELECT parent_turn_id FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        new_head: int | None = None
        if parent_row is not None and parent_row["parent_turn_id"] is not None:
            new_head = int(parent_row["parent_turn_id"])
        cursor = db.execute(
            "DELETE FROM messages WHERE id >= ?",
            (message_id,),
        )
        deleted = cursor.rowcount or 0
        if deleted:
            self.set_active_head(new_head, commit=False)
        db.commit()
        return deleted

    def load_messages(self) -> list[dict[str, object]]:
        """Load every persisted conversation message in id order.

        Phase 67.1: this returns the *full* tree (every branch ever
        recorded), not just the active branch.  Resume / context
        rebuilding wants only the active branch — call
        :meth:`load_active_branch` for that.  ``/tree`` and the
        transcript exporter call this method to render or summarise
        every branch the user can switch back to.
        """
        rows = self._db.execute("SELECT * FROM messages ORDER BY id").fetchall()
        result: list[dict[str, object]] = []
        for r in rows:
            try:
                result.append(_message_row_to_dict(r))
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Skipping corrupt message row %s: %s", r["id"], exc)
        return result

    def is_message_on_active_branch(self, message_id: int) -> bool:
        """Return True if *message_id* is on the currently active branch.

        Used by ``/tree`` to mark which nodes are part of the live
        conversation versus historical forks.  Cheap walk — the branch
        is at most as long as the conversation.
        """
        active_ids = {m["id"] for m in self.load_active_branch()}
        return message_id in active_ids

    def load_active_branch(
        self,
        head: int | None = None,
    ) -> list[dict[str, object]]:
        """Load the messages on a branch, in order.

        Without an argument, walks from ``active_head_message_id``
        back to a ``NULL`` parent (the root) and reverses, yielding
        the conversation as the agent saw it.  Pass ``head`` to walk
        an explicit leaf — the export path uses this for ``--branch
        <turn-id>``.  Returns an empty list when the session has no
        messages or the leaf is missing (which shouldn't happen under
        normal operation but the call is on the resume path so it
        must not raise).

        For sessions persisted before the v12 migration, the migration
        backfilled a degenerate single-branch tree, so the default
        call returns the same ordered list ``load_messages`` used to.
        """
        if head is None:
            head = self.get_active_head()
        if head is None:
            return []
        chain: list[dict[str, object]] = []
        seen: set[int] = set()
        current: int | None = head
        while current is not None:
            if current in seen:
                # Cycle guard.  A well-formed tree can't cycle, but a
                # corrupt or hand-edited DB shouldn't crash the agent.
                log.warning("Cycle detected in message tree at id %s", current)
                break
            seen.add(current)
            row = self._db.execute(
                "SELECT * FROM messages WHERE id = ?",
                (current,),
            ).fetchone()
            if row is None:
                log.warning("Active branch references missing message id %s", current)
                break
            try:
                chain.append(_message_row_to_dict(row))
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Skipping corrupt message row %s on active branch: %s", current, exc)
            parent = row["parent_turn_id"]
            current = int(parent) if parent is not None else None
        chain.reverse()
        return chain

    # ── Subagent message recording ───────────────────────────────────────

    def record_subagent_message(
        self,
        task_id: str,
        message_index: int,
        role: str,
        content: str,
        tool_calls: list[dict[str, object]] | None = None,
        tool_results: list[dict[str, object]] | None = None,
    ) -> None:
        """Record a single message from a subagent conversation."""
        self._db.execute(
            """\
            INSERT INTO subagent_messages (task_id, message_index, role,
                                            content, tool_calls, tool_results)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                message_index,
                role,
                _truncate(content),
                json.dumps(tool_calls) if tool_calls else None,
                json.dumps(tool_results) if tool_results else None,
            ),
        )
        self._db.commit()

    def load_subagent_messages(
        self,
        task_id: str,
    ) -> list[dict[str, object]]:
        """Load all subagent messages for a specific task."""
        rows = self._db.execute(
            "SELECT * FROM subagent_messages WHERE task_id = ? ORDER BY message_index",
            (task_id,),
        ).fetchall()
        result: list[dict[str, object]] = []
        for r in rows:
            result.append(
                {
                    "task_id": r["task_id"],
                    "message_index": r["message_index"],
                    "role": r["role"],
                    "content": r["content"],
                    "tool_calls": _safe_json_load(r["tool_calls"]),
                    "tool_results": _safe_json_load(r["tool_results"]),
                    "timestamp": r["timestamp"],
                }
            )
        return result

    # ── Event log ────────────────────────────────────────────────────────

    def record_event(
        self,
        event_type: str,
        detail: dict[str, object] | None = None,
    ) -> int:
        """Record a structured event and return its row ID."""
        cursor = self._db.execute(
            "INSERT INTO events (event_type, detail) VALUES (?, ?)",
            (event_type, json.dumps(detail or {})),
        )
        self._db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def load_events(
        self,
        event_type: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, object]]:
        """Load events with optional type and time filters."""
        query = "SELECT * FROM events"
        conditions: list[str] = []
        params: list[str] = []
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id"
        rows = self._db.execute(query, params).fetchall()
        result: list[dict[str, object]] = []
        for r in rows:
            result.append(
                {
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "detail": _safe_json_load(r["detail"], fallback={}),
                    "timestamp": r["timestamp"],
                }
            )
        return result

    # ── Token usage ──────────────────────────────────────────────────────

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        category: str | None = None,
    ) -> int:
        """Record token usage for a single LLM request. Returns the row ID.

        *category* is the ``TaskCategory`` value of the task that was
        active when the request fired (subagent turns), or ``None`` for
        main-conversation-loop turns that aren't tied to a task.  Used
        by ``/cost`` to break cost down by category.
        """
        cursor = self._db.execute(
            """\
            INSERT INTO token_usage (provider, model, prompt_tokens, completion_tokens, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (provider, model, prompt_tokens, completion_tokens, category),
        )
        self._db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def get_total_usage(self) -> dict[str, int]:
        """Return aggregate token counts across all requests."""
        row = self._db.execute(
            """\
            SELECT COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0)  AS completion_tokens
            FROM token_usage
            """
        ).fetchone()
        return {
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
        }

    def get_usage_by_model(self) -> list[dict[str, object]]:
        """Return token usage broken down by provider and model."""
        rows = self._db.execute(
            """\
            SELECT provider,
                   model,
                   SUM(prompt_tokens)     AS prompt_tokens,
                   SUM(completion_tokens)  AS completion_tokens,
                   COUNT(*)                AS request_count
            FROM token_usage
            GROUP BY provider, model
            ORDER BY provider, model
            """
        ).fetchall()
        return [
            {
                "provider": r["provider"],
                "model": r["model"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "request_count": r["request_count"],
            }
            for r in rows
        ]

    def get_usage_since(self, since: str) -> dict[str, int]:
        """Return aggregate token counts for requests since *since* (ISO timestamp).

        Also includes a ``request_count`` key.
        """
        row = self._db.execute(
            """\
            SELECT COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0)  AS completion_tokens,
                   COUNT(*)                              AS request_count
            FROM token_usage
            WHERE timestamp >= ?
            """,
            (since,),
        ).fetchone()
        return {
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "request_count": row["request_count"],
        }

    def get_usage_by_category(self, since: str | None = None) -> list[dict[str, object]]:
        """Return token usage broken down by task category and model.

        *since* is an optional ISO timestamp; when provided, only rows
        logged after that point are included (session-scoped cost).
        Rows with a NULL category (main-conversation-loop turns or
        legacy pre-v9 rows) appear under the literal string
        ``"conversation"`` so the caller can render a single display
        row without a special case.
        """
        base = """\
            SELECT COALESCE(category, 'conversation') AS category,
                   provider,
                   model,
                   SUM(prompt_tokens)     AS prompt_tokens,
                   SUM(completion_tokens)  AS completion_tokens,
                   COUNT(*)                AS request_count
            FROM token_usage
        """
        params: tuple[object, ...] = ()
        if since is not None:
            base += " WHERE timestamp >= ?"
            params = (since,)
        base += " GROUP BY category, provider, model ORDER BY category, provider, model"
        rows = self._db.execute(base, params).fetchall()
        return [
            {
                "category": r["category"],
                "provider": r["provider"],
                "model": r["model"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "request_count": r["request_count"],
            }
            for r in rows
        ]

    def get_usage_by_model_since(self, since: str) -> list[dict[str, object]]:
        """Return per-model token usage for requests since *since* (ISO timestamp).

        Same shape as :meth:`get_usage_by_model` but filtered to a time
        window — used for session-scoped cost estimates that need to
        apply the right price to each model individually.
        """
        rows = self._db.execute(
            """\
            SELECT provider,
                   model,
                   SUM(prompt_tokens)     AS prompt_tokens,
                   SUM(completion_tokens)  AS completion_tokens,
                   COUNT(*)                AS request_count
            FROM token_usage
            WHERE timestamp >= ?
            GROUP BY provider, model
            ORDER BY provider, model
            """,
            (since,),
        ).fetchall()
        return [
            {
                "provider": r["provider"],
                "model": r["model"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "request_count": r["request_count"],
            }
            for r in rows
        ]

    def get_replay_savings(self) -> dict[str, int]:
        """Sum LLM tokens replayed from step checkpoints (Phase 52.6).

        Reads ``checkpoint_hit`` events whose detail carries
        ``prompt_tokens`` / ``completion_tokens`` (stamped by
        :func:`cantrip.agent.durability.checkpoint` on
        ``KIND_LLM_RESPONSE`` hits) and returns the running totals so
        ``/cost`` can show "cached from checkpoint" alongside the live
        token counts.  Tool hits contribute zero.

        The payload never exceeds a session's event count (tens to low
        hundreds in practice), so a Python-side sum is cheaper than
        adding a ``json_extract`` SQL path here.
        """
        rows = self._db.execute(
            "SELECT detail FROM events WHERE event_type = 'checkpoint_hit'"
        ).fetchall()
        prompt = 0
        completion = 0
        request_count = 0
        for row in rows:
            try:
                detail = json.loads(row["detail"]) if row["detail"] else {}
            except json.JSONDecodeError:
                continue
            if not isinstance(detail, dict):
                continue
            p = detail.get("prompt_tokens")
            c = detail.get("completion_tokens")
            if isinstance(p, int):
                prompt += p
            if isinstance(c, int):
                completion += c
            if isinstance(p, int) or isinstance(c, int):
                request_count += 1
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "request_count": request_count,
        }

    # ── Memory (charm scope, Phase 43) ───────────────────────────────────

    def record_memory(
        self,
        title: str,
        kind: str,
        body: str,
        *,
        source: str = "manual",
        citations: list[dict[str, object]] | None = None,
        tags: list[str] | None = None,
        status: str = "active",
    ) -> int:
        """Insert a new memory row and return its id."""
        cursor = self._db.execute(
            """\
            INSERT INTO memory (title, kind, body, source, citations, tags, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                kind,
                _truncate(body),
                source,
                json.dumps(citations or []),
                json.dumps(tags or []),
                status,
            ),
        )
        self._db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def update_memory(
        self,
        memory_id: int,
        *,
        body: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        citations: list[dict[str, object]] | None = None,
        last_accessed_at: str | None = None,
        last_validated_at: str | None = None,
    ) -> bool:
        """Partial update of a memory row. Returns True when a row was changed."""
        fields: list[str] = []
        params: list[object] = []
        if body is not None:
            fields.append("body = ?")
            params.append(_truncate(body))
        if kind is not None:
            fields.append("kind = ?")
            params.append(kind)
        if tags is not None:
            fields.append("tags = ?")
            params.append(json.dumps(tags))
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if citations is not None:
            fields.append("citations = ?")
            params.append(json.dumps(citations))
        if last_accessed_at is not None:
            fields.append("last_accessed_at = ?")
            params.append(last_accessed_at)
        if last_validated_at is not None:
            fields.append("last_validated_at = ?")
            params.append(last_validated_at)
        if not fields:
            return False
        fields.append("updated_at = datetime('now')")
        params.append(memory_id)
        cursor = self._db.execute(
            f"UPDATE memory SET {', '.join(fields)} WHERE id = ?",  # noqa: S608
            params,
        )
        self._db.commit()
        return cursor.rowcount > 0

    def touch_memory(self, memory_id: int) -> None:
        """Bump access_count and set last_accessed_at to now."""
        self._db.execute(
            "UPDATE memory SET access_count = access_count + 1, "
            "last_accessed_at = datetime('now') WHERE id = ?",
            (memory_id,),
        )
        self._db.commit()

    def delete_memory(self, memory_id: int) -> bool:
        """Remove a memory row. Returns True when a row was removed."""
        cursor = self._db.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
        self._db.commit()
        return cursor.rowcount > 0

    def get_memory(self, memory_id: int) -> dict[str, object] | None:
        """Fetch a memory row by id."""
        row = self._db.execute("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
        return _memory_row_to_dict(row) if row else None

    def get_memory_by_title(self, title: str) -> dict[str, object] | None:
        """Fetch a memory row by title."""
        row = self._db.execute("SELECT * FROM memory WHERE title = ?", (title,)).fetchone()
        return _memory_row_to_dict(row) if row else None

    def list_memory(
        self,
        *,
        kind: str | None = None,
        status: str | None = "active",
        tag: str | None = None,
    ) -> list[dict[str, object]]:
        """List memory rows matching optional filters, newest first.

        ``status=None`` returns every row regardless of status; the default
        hides archived and quarantined memories.  ``tag`` matches a single
        tag against the JSON-encoded tags column with a LIKE probe; callers
        that need exact matching should filter the result in Python.
        """
        query = "SELECT * FROM memory"
        conditions: list[str] = []
        params: list[object] = []
        if kind is not None:
            conditions.append("kind = ?")
            params.append(kind)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if tag is not None:
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC"
        rows = self._db.execute(query, params).fetchall()
        return [_memory_row_to_dict(r) for r in rows]

    def search_memory(
        self, query: str, *, status: str | None = "active"
    ) -> list[dict[str, object]]:
        """Keyword search across title and body. Case-insensitive substring match."""
        like = f"%{query}%"
        sql = (
            "SELECT * FROM memory WHERE (title LIKE ? OR body LIKE ?)"
            if status is None
            else "SELECT * FROM memory WHERE (title LIKE ? OR body LIKE ?) AND status = ?"
        )
        params: list[object] = [like, like]
        if status is not None:
            params.append(status)
        rows = self._db.execute(sql + " ORDER BY id DESC", params).fetchall()
        return [_memory_row_to_dict(r) for r in rows]

    # ── Step checkpoints (Phase 52.1 — durable execution) ────────────────

    def record_checkpoint(
        self,
        task_id: str,
        step_name: str,
        ordinal: int,
        input_hash: str,
        result_kind: str,
        result_blob: bytes,
    ) -> None:
        """Store one step result for resume on replay.

        Serialisation is the caller's responsibility — ``result_blob`` is
        stored verbatim in the ``result_blob`` BLOB column.  The
        roadmap's msgpack-or-JSON envelope lives one layer up in
        :mod:`cantrip.agent.durability` so callers picking a different
        encoding aren't forced through an extra decode.

        The ``(task_id, step_name, ordinal)`` triple is unique — upsert
        semantics via ``INSERT OR REPLACE`` handle the "same step re-run
        after input-hash invalidation" path from 52.2 without callers
        needing a prior DELETE.
        """
        self._db.execute(
            "INSERT OR REPLACE INTO step_checkpoints "
            "(task_id, step_name, ordinal, input_hash, result_blob, result_kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, step_name, ordinal, input_hash, result_blob, result_kind),
        )
        self._db.commit()

    def get_checkpoint(self, task_id: str, step_name: str, ordinal: int) -> sqlite3.Row | None:
        """Return the stored row for ``(task_id, step_name, ordinal)`` or ``None``.

        Callers match on ``input_hash`` before trusting the blob —
        :mod:`cantrip.agent.durability` wraps the raw row in a typed
        record and handles the invalidation path.
        """
        return self._db.execute(
            "SELECT task_id, step_name, ordinal, input_hash, result_kind, "
            "result_blob, created_at "
            "FROM step_checkpoints "
            "WHERE task_id = ? AND step_name = ? AND ordinal = ?",
            (task_id, step_name, ordinal),
        ).fetchone()

    def next_checkpoint_ordinal(self, task_id: str, step_name: str) -> int:
        """Return the next unused ordinal for a ``(task_id, step_name)`` pair.

        Starts at ``1`` — the first ``llm_turn`` in a task is
        ``ordinal=1``, the next is ``2``, and so on.  Callers don't
        track counters; they just ask for the next slot.  Off-the-end
        requests (probing past the last recorded step) return
        ``max(ordinal) + 1`` so replay can drop out of the cached
        prefix cleanly.
        """
        row = self._db.execute(
            "SELECT COALESCE(MAX(ordinal), 0) FROM step_checkpoints "
            "WHERE task_id = ? AND step_name = ?",
            (task_id, step_name),
        ).fetchone()
        return int(row[0]) + 1

    def list_checkpoints_for_task(self, task_id: str) -> list[sqlite3.Row]:
        """Return every recorded checkpoint for *task_id* in insertion order."""
        return list(
            self._db.execute(
                "SELECT task_id, step_name, ordinal, input_hash, result_kind, "
                "result_blob, created_at "
                "FROM step_checkpoints WHERE task_id = ? "
                "ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        )

    def count_checkpoints_for_task(self, task_id: str) -> int:
        """Return how many checkpoints are stored for *task_id*."""
        row = self._db.execute(
            "SELECT COUNT(*) FROM step_checkpoints WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row[0])

    def purge_checkpoints_for_task(self, task_id: str) -> int:
        """Delete every checkpoint for *task_id*.  Returns the row count removed.

        Called by :class:`CheckpointStore` on successful task
        completion to reclaim space; failed / paused tasks retain
        their checkpoints so the next run can resume.  The
        ``CANTRIP_KEEP_CHECKPOINTS`` env-var opt-out lives one layer
        up so the SQL path stays simple.
        """
        cursor = self._db.execute(
            "DELETE FROM step_checkpoints WHERE task_id = ?",
            (task_id,),
        )
        self._db.commit()
        return cursor.rowcount

    # ── Migration ────────────────────────────────────────────────────────

    @staticmethod
    def migrate_from_json(json_path: pathlib.Path, db_path: pathlib.Path) -> None:
        """Migrate an existing session.json file into a new SQLite database.

        Creates the database at *db_path*, loads the JSON data, and writes
        it into the session and decisions tables.
        """
        data = json.loads(json_path.read_text())

        store = SessionStore(db_path)
        store.open()
        try:
            state = AgentState(
                charm_name=data.get("charm_name"),
                charm_path=pathlib.Path(data["charm_path"]) if data.get("charm_path") else None,
                charm_type=data.get("charm_type"),
                framework=data.get("framework"),
                dev_model=data.get("dev_model"),
                cos_model=data.get("cos_model"),
            )
            for d in data.get("decisions", []):
                state.decisions.append(
                    Decision(
                        type=d["type"],
                        choice=d["choice"],
                        reason=d.get("reason"),
                    )
                )
            store.save_session(state)
        finally:
            store.close()
