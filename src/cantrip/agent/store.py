"""SQLite-backed session store."""

import datetime
import json
import logging
import os
import sqlite3
import stat
from pathlib import Path

from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState, Decision

log = logging.getLogger(__name__)

SCHEMA_VERSION = 4


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
    message_count INTEGER DEFAULT 0,
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
"""


def _truncate(text: str, max_bytes: int = _MAX_CONTENT_BYTES) -> str:
    """Truncate text exceeding *max_bytes* with a marker."""
    if len(text.encode("utf-8", errors="replace")) <= max_bytes:
        return text
    # Truncate at character boundary.
    truncated = text.encode("utf-8", errors="replace")[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + f"\n\n[truncated — {len(text)} characters total]"


class SessionStore:
    """SQLite-backed persistence for Cantrip session data and token usage."""

    def __init__(self, db_path: Path) -> None:
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
        return self._conn  # type: ignore[return-value]

    # ── Session CRUD ─────────────────────────────────────────────────────

    def save_session(self, state: AgentState) -> None:
        """Upsert the session row and replace all decisions."""
        db = self._db
        db.execute(
            """\
            INSERT INTO session (id, charm_name, charm_path, charm_type,
                                 framework, dev_model, cos_model, message_count,
                                 updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                charm_name     = excluded.charm_name,
                charm_path     = excluded.charm_path,
                charm_type     = excluded.charm_type,
                framework      = excluded.framework,
                dev_model      = excluded.dev_model,
                cos_model      = excluded.cos_model,
                message_count  = excluded.message_count,
                updated_at     = datetime('now')
            """,
            (
                state.charm_name,
                str(state.charm_path) if state.charm_path else None,
                state.charm_type,
                state.framework,
                state.dev_model,
                state.cos_model,
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
            charm_path=Path(row["charm_path"]) if row["charm_path"] else None,
            charm_type=row["charm_type"],
            framework=row["framework"],
            dev_model=row["dev_model"],
            cos_model=row["cos_model"],
        )

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

    # ── Task persistence ────────────────────────────────────────────────

    def save_tasks(self, tasks: list[AgentTask]) -> None:
        """Replace all stored tasks with *tasks*."""
        db = self._db
        db.execute("DELETE FROM tasks")
        for t in tasks:
            db.execute(
                """\
                INSERT INTO tasks (id, title, status, category, description,
                                   dependencies, result, blocked_reason,
                                   model_hint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    t.created_at.isoformat(),
                ),
            )
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
        """Persist a single conversation message. Returns the row ID."""
        cursor = self._db.execute(
            """\
            INSERT INTO messages
                (role, content, tool_calls, tool_results, metadata, token_usage_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                role,
                _truncate(content or ""),
                json.dumps(tool_calls) if tool_calls else None,
                json.dumps(tool_results) if tool_results else None,
                json.dumps(metadata) if metadata else None,
                token_usage_id,
            ),
        )
        self._db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def load_messages(self) -> list[dict[str, object]]:
        """Load all conversation messages ordered by ID."""
        rows = self._db.execute("SELECT * FROM messages ORDER BY id").fetchall()
        result: list[dict[str, object]] = []
        for r in rows:
            try:
                result.append(
                    {
                        "id": r["id"],
                        "role": r["role"],
                        "content": r["content"],
                        "tool_calls": _safe_json_load(r["tool_calls"]),
                        "tool_results": _safe_json_load(r["tool_results"]),
                        "metadata": _safe_json_load(r["metadata"]),
                        "token_usage_id": r["token_usage_id"],
                        "timestamp": r["timestamp"],
                    }
                )
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Skipping corrupt message row %s: %s", r["id"], exc)
        return result

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
        return cursor.lastrowid  # type: ignore[return-value]

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
    ) -> int:
        """Record token usage for a single LLM request. Returns the row ID."""
        cursor = self._db.execute(
            """\
            INSERT INTO token_usage (provider, model, prompt_tokens, completion_tokens)
            VALUES (?, ?, ?, ?)
            """,
            (provider, model, prompt_tokens, completion_tokens),
        )
        self._db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

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

    # ── Migration ────────────────────────────────────────────────────────

    @staticmethod
    def migrate_from_json(json_path: Path, db_path: Path) -> None:
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
                charm_path=Path(data["charm_path"]) if data.get("charm_path") else None,
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
