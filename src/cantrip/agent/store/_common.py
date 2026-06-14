"""Shared helpers, constants, and schema SQL for the session store."""

import datetime  # noqa: F401
import json
import sqlite3

SCHEMA_VERSION = 17


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
    -- Phase 99.2: persisted per-goal budget so ``/budget`` caps survive
    -- ``cantrip resume``.  ``goal_budget_started_at`` doubles as the
    -- "is a budget set?" signal — NULL means no budget, non-NULL means
    -- a budget exists (caps are individually NULL-able for uncapped
    -- axes).  The ``started_at`` value is the SQLite-format timestamp
    -- the GoalBudget started counting from; ``measure_usage`` uses it
    -- to window the ``token_usage`` query, so spend totals reconstruct
    -- automatically across resume without storing them separately.
    goal_budget_max_iterations INTEGER,
    goal_budget_max_prompt_tokens INTEGER,
    goal_budget_max_completion_tokens INTEGER,
    goal_budget_started_at TEXT,
    -- Phase 99.3: free-text user-prose objective for the session.
    -- Stores the user's goal sentence verbatim so Ralph re-feed and
    -- future goal-aware status surfaces work from the user's words
    -- rather than a ``charm_name`` + ``charm_type`` paraphrase.  NULL
    -- when no objective has been set.
    objective TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    choice TEXT NOT NULL,
    reason TEXT,
    timestamp TEXT NOT NULL,
    -- Phase 51b.2: distinguishes locally-recorded decisions ('local')
    -- from decisions that arrived via the shared team-sync log
    -- ('shared').  Nullable for back-compat — pre-v14 rows read as
    -- 'local' in load_session.
    source TEXT
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
    -- Phase 72.3: which provider role consumed these tokens.  ``chat``
    -- (or NULL for legacy rows) is the conversational path; ``embed``
    -- and ``rerank`` are the retrieval-side roles introduced by the
    -- role router.  Lets /cost separate retrieval spend from chat
    -- spend without losing the per-model breakdown.
    role TEXT,
    -- Anthropic prompt-cache token counts for this request.  ``prompt_tokens``
    -- above is the fresh (non-cached) input only; these two record the
    -- cache-read (billed at 0.1x) and cache-creation (1.25x / 2x) tokens
    -- so cost survives a session resume and the cache hit-rate can be
    -- reconstructed from the store rather than only the live in-memory
    -- accumulators.  Zero for providers without prompt caching.
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
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

-- Indexes for tables that grow with session size and are routinely
-- queried by a column other than the primary key.  Idempotent — added
-- to ``_SCHEMA_SQL`` so they land on every open without bumping the
-- migration version.
CREATE INDEX IF NOT EXISTS ix_subagent_messages_task
    ON subagent_messages(task_id);
CREATE INDEX IF NOT EXISTS ix_events_event_type
    ON events(event_type);
CREATE INDEX IF NOT EXISTS ix_events_timestamp
    ON events(timestamp);
"""


def _truncate(text: str, max_bytes: int = _MAX_CONTENT_BYTES) -> str:
    """Truncate text exceeding *max_bytes* with a marker."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    # Truncate at character boundary — slice the bytes once and let
    # the lossy decode drop any partial code unit at the end.
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
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
