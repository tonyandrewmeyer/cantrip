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
from cantrip.agent.runtime.goal_budget import GoalBudget
from cantrip.agent.state import AgentState, Decision, load_shared_decisions
from cantrip.agent.store._checkpoints import CheckpointsMixin
from cantrip.agent.store._common import (
    _SCHEMA_SQL,
    SCHEMA_VERSION,
    _message_row_to_dict,
    _safe_json_load,
    _truncate,
)
from cantrip.agent.store._memory import MemoryMixin
from cantrip.agent.store._usage import UsageMixin

log = logging.getLogger(__name__)


class SessionStore(UsageMixin, MemoryMixin, CheckpointsMixin):
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
        # Caller (``open``) only invokes this when the schema_version
        # table has at least one row, so the SELECT always returns one.
        row = self._conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        current = row[0]

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

        if current < 13:
            # v13: per-role cost breakdown (Phase 72.3).  Existing rows
            # get NULL so historical totals stay correct — aggregations
            # treat NULL as the legacy ``chat`` role.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(token_usage)").fetchall()}
            if "role" not in cols:
                self._conn.execute("ALTER TABLE token_usage ADD COLUMN role TEXT")

        if current < 14:
            # v14: source provenance on decisions (Phase 51b.2).  Existing
            # rows get NULL — load_session treats NULL as ``"local"`` so
            # pre-shared-log decisions keep their original meaning.  The
            # column is nullable so the migration can be additive on a
            # populated decisions table without a backfill pass.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(decisions)").fetchall()}
            if "source" not in cols:
                self._conn.execute("ALTER TABLE decisions ADD COLUMN source TEXT")

        if current < 15:
            # v15: persisted per-goal budget on the session table
            # (Phase 99.2).  Existing rows get NULL across all four
            # columns — load_session reads NULL ``goal_budget_started_at``
            # as "no budget", so pre-99.2 sessions resume uncapped just
            # as they did before the change.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(session)").fetchall()}
            for column in (
                "goal_budget_max_iterations",
                "goal_budget_max_prompt_tokens",
                "goal_budget_max_completion_tokens",
            ):
                if column not in cols:
                    self._conn.execute(f"ALTER TABLE session ADD COLUMN {column} INTEGER")
            if "goal_budget_started_at" not in cols:
                self._conn.execute("ALTER TABLE session ADD COLUMN goal_budget_started_at TEXT")

        if current < 16:
            # v16: free-text user-prose objective on the session table
            # (Phase 99.3).  Existing rows get NULL — load_session reads
            # that as "no objective set" and the agent falls back to the
            # spec-derived paraphrase exactly as it did before.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(session)").fetchall()}
            if "objective" not in cols:
                self._conn.execute("ALTER TABLE session ADD COLUMN objective TEXT")

        if current < 17:
            # v17: persist Anthropic prompt-cache token counts on
            # token_usage so cache cost and hit-rate survive a session
            # resume (previously they lived only in the in-memory
            # accumulators and reset to zero on reload).  Existing rows get
            # 0 — historical totals stay correct, just without a
            # retroactive cache breakdown they never had.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(token_usage)").fetchall()}
            if "cache_read_tokens" not in cols:
                self._conn.execute(
                    "ALTER TABLE token_usage ADD COLUMN "
                    "cache_read_tokens INTEGER NOT NULL DEFAULT 0"
                )
            if "cache_creation_tokens" not in cols:
                self._conn.execute(
                    "ALTER TABLE token_usage ADD COLUMN "
                    "cache_creation_tokens INTEGER NOT NULL DEFAULT 0"
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

        # Phase 99.2: persist the per-goal budget if one is set.  All four
        # columns go to NULL when ``goal_budget`` is None so a later
        # ``/budget --clear`` round-trips back to "no budget" instead of
        # leaving stale caps in the database.
        budget = state.goal_budget
        budget_iterations = budget.max_iterations if budget is not None else None
        budget_prompt = budget.max_prompt_tokens if budget is not None else None
        budget_completion = budget.max_completion_tokens if budget is not None else None
        budget_started_at = budget.started_at if budget is not None else None

        db.execute(
            """\
            INSERT INTO session (id, charm_name, charm_path, charm_type,
                                 framework, dev_model, cos_model,
                                 design_proposal, message_count,
                                 goal_budget_max_iterations,
                                 goal_budget_max_prompt_tokens,
                                 goal_budget_max_completion_tokens,
                                 goal_budget_started_at,
                                 objective,
                                 updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                charm_name                        = excluded.charm_name,
                charm_path                        = excluded.charm_path,
                charm_type                        = excluded.charm_type,
                framework                         = excluded.framework,
                dev_model                         = excluded.dev_model,
                cos_model                         = excluded.cos_model,
                design_proposal                   = excluded.design_proposal,
                message_count                     = excluded.message_count,
                goal_budget_max_iterations        = excluded.goal_budget_max_iterations,
                goal_budget_max_prompt_tokens     = excluded.goal_budget_max_prompt_tokens,
                goal_budget_max_completion_tokens = excluded.goal_budget_max_completion_tokens,
                goal_budget_started_at            = excluded.goal_budget_started_at,
                objective                         = excluded.objective,
                updated_at                        = datetime('now')
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
                budget_iterations,
                budget_prompt,
                budget_completion,
                budget_started_at,
                state.objective,
            ),
        )

        # Replace decisions: clear then re-insert.  Shared-source rows
        # are skipped — they live in the team-sync JSONL file and would
        # otherwise duplicate every load.
        db.execute("DELETE FROM decisions")
        for d in state.decisions:
            if d.source == "shared":
                continue
            db.execute(
                "INSERT INTO decisions (type, choice, reason, timestamp, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (d.type, d.choice, d.reason, d.timestamp.isoformat(), d.source),
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
            objective=row["objective"],
        )

        # Restore the design proposal from persisted Markdown.
        raw_design = row["design_proposal"]
        if raw_design:
            state.design_proposal = design_mod.parse_design_from_result(raw_design)

        # Phase 99.2: restore the per-goal budget if one was persisted.
        # ``goal_budget_started_at`` doubles as the "is a budget set?"
        # signal — non-NULL means a budget existed, even if every cap
        # is NULL (uncapped axes).  Pre-v15 databases gain the columns
        # at NULL via the v15 migration and resume without a budget,
        # matching the prior session-scoped behaviour.
        budget_started_at = row["goal_budget_started_at"]
        if budget_started_at:
            state.goal_budget = GoalBudget(
                max_iterations=row["goal_budget_max_iterations"],
                max_prompt_tokens=row["goal_budget_max_prompt_tokens"],
                max_completion_tokens=row["goal_budget_max_completion_tokens"],
                started_at=str(budget_started_at),
            )

        decision_rows = self._db.execute(
            "SELECT type, choice, reason, timestamp, source FROM decisions ORDER BY id"
        ).fetchall()
        merged: list[Decision] = []
        for dr in decision_rows:
            ts = dr["timestamp"]
            try:
                timestamp = datetime.datetime.fromisoformat(ts) if ts else datetime.datetime.now()
            except (ValueError, TypeError):
                timestamp = datetime.datetime.now()
            merged.append(
                Decision(
                    type=dr["type"],
                    choice=dr["choice"],
                    reason=dr["reason"],
                    timestamp=timestamp,
                    source=dr["source"] or "local",
                )
            )
        # Phase 51b.2: pull in decisions from the shared team-sync log so
        # teammates' choices show up in /decisions alongside the local
        # ones.  Shared rows are flagged so the UI can render them
        # differently and so save_session won't write them back to
        # SQLite — the JSONL file is the source of truth.
        if state.charm_path is not None:
            merged.extend(load_shared_decisions(state.charm_path))
        # Merge by timestamp so a teammate's earlier decision sorts before
        # a later local one in /decisions, the resume preview, and the
        # prompt-injected decisions block.  ``sort`` is stable, so two
        # entries with identical timestamps keep their relative
        # local-then-shared ordering — useful when ``Decision.timestamp``
        # falls back to ``datetime.now`` because a row was missing the
        # field.
        merged.sort(key=lambda d: d.timestamp)
        state.decisions.extend(merged)

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

    def update_message_content(self, message_id: int, content: str) -> None:
        """Replace the content of a previously-recorded message.

        Phase 102.2: streaming partial writeback updates the in-flight
        assistant row as chunks arrive so a mid-stream disconnect leaves
        a recoverable transcript instead of an empty assistant turn.
        Does nothing when *message_id* doesn't exist (the partial-row
        cleanup in ``_complete_with_retry`` may have already removed
        it on a fast successful turn).
        """
        db = self._db
        db.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (_truncate(content or ""), message_id),
        )
        db.commit()

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

    def latest_visible_shell_row(self) -> dict[str, object] | None:
        """Return the most recent ``role='shell'`` row not flagged hidden.

        Phase 72.2 follow-up: backs the ``@terminal`` context provider.
        Walks backwards from the newest shell row until one is found
        whose ``metadata.hidden_from_agent`` is missing or false; rows
        with ``hidden_from_agent=True`` (the ``$$`` incognito prefix)
        are skipped so the provider's contract stays one-way — content
        the operator marked hidden never re-enters the prompt through
        this surface.  Returns ``None`` when no eligible row exists.
        """
        rows = self._db.execute(
            "SELECT * FROM messages WHERE role = 'shell' ORDER BY id DESC"
        ).fetchall()
        for r in rows:
            try:
                decoded = _message_row_to_dict(r)
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Skipping corrupt shell row %s: %s", r["id"], exc)
                continue
            metadata = decoded.get("metadata") or {}
            if not isinstance(metadata, dict):
                continue
            if metadata.get("hidden_from_agent"):
                continue
            return decoded
        return None

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

    # ── Migration ────────────────────────────────────────────────────────

    @staticmethod
    def migrate_from_json(json_path: pathlib.Path, db_path: pathlib.Path) -> None:
        """Migrate an existing session.json file into a new SQLite database.

        Creates the database at *db_path*, loads the JSON data, and writes
        it into the session and decisions tables.

        Raises ``ValueError`` when *json_path* is unreadable, contains
        non-UTF-8 bytes, or is not valid JSON.  Callers handle this as
        "skip the migration and start fresh" — see ``CantripAgent._init_store``.
        """
        try:
            raw = json_path.read_text(errors="replace")
        except OSError as exc:
            raise ValueError(f"cannot read legacy session.json at {json_path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"legacy session.json at {json_path} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(f"legacy session.json at {json_path} top-level is not an object")

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
