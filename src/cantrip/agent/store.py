"""SQLite-backed session store."""

import json
import sqlite3
from pathlib import Path

from cantrip.agent.state import AgentState, Decision

SCHEMA_VERSION = 1

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
"""


class SessionStore:
    """SQLite-backed persistence for Cantrip session data and token usage."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        """Open the database and ensure the schema exists."""
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_SQL)

        # Initialise schema version if empty.
        row = self._conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()
        if row[0] == 0:
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> sqlite3.Connection:
        """Return the active connection, raising if not open."""
        if self._conn is None:
            raise RuntimeError("SessionStore is not open")
        return self._conn

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
            "SELECT type, choice, reason FROM decisions ORDER BY id"
        ).fetchall()
        for dr in decision_rows:
            state.decisions.append(
                Decision(type=dr["type"], choice=dr["choice"], reason=dr["reason"])
            )

        return state

    # ── Token usage ──────────────────────────────────────────────────────

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Record token usage for a single LLM request."""
        self._db.execute(
            """\
            INSERT INTO token_usage (provider, model, prompt_tokens, completion_tokens)
            VALUES (?, ?, ?, ?)
            """,
            (provider, model, prompt_tokens, completion_tokens),
        )
        self._db.commit()

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
