from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING


class UsageMixin:
    """Token-usage recording and aggregation queries."""

    if TYPE_CHECKING:
        # Provided by SessionStore; declared for type-checkers only.
        _db: sqlite3.Connection

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        category: str | None = None,
        role: str | None = None,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> int:
        """Record token usage for a single LLM request. Returns the row ID.

        *category* is the ``TaskCategory`` value of the task that was
        active when the request fired (subagent turns), or ``None`` for
        main-conversation-loop turns that aren't tied to a task.  Used
        by ``/cost`` to break cost down by category.

        Phase 72.3: *role* labels which provider role consumed the
        tokens — ``"chat"``, ``"embed"``, ``"rerank"``.  ``None`` is
        treated as ``"chat"`` by aggregation queries so legacy rows
        and current chat traffic share the same bucket.

        *cache_read_tokens* / *cache_creation_tokens* are Anthropic's
        prompt-cache counts for this request — persisted so cache cost
        and hit-rate survive a session resume.  *prompt_tokens* is the
        fresh (non-cached) input only, matching the provider's
        ``input_tokens``.  Both default to 0 for providers without
        prompt caching.
        """
        cursor = self._db.execute(
            """\
            INSERT INTO token_usage
                (provider, model, prompt_tokens, completion_tokens, category, role,
                 cache_read_tokens, cache_creation_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                model,
                prompt_tokens,
                completion_tokens,
                category,
                role,
                cache_read_tokens,
                cache_creation_tokens,
            ),
        )
        self._db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def get_usage_by_role(self) -> list[dict[str, object]]:
        """Return token usage grouped by provider role.

        Phase 72.3: surfaces the embed / rerank spend separately from
        chat so ``/cost`` can show how much of the bill is going to
        retrieval.  NULL legacy rows fall under ``"chat"``.
        """
        rows = self._db.execute(
            """\
            SELECT COALESCE(role, 'chat') AS role,
                   SUM(prompt_tokens)      AS prompt_tokens,
                   SUM(completion_tokens)   AS completion_tokens,
                   COUNT(*)                 AS request_count
            FROM token_usage
            GROUP BY COALESCE(role, 'chat')
            ORDER BY role
            """
        ).fetchall()
        return [
            {
                "role": row["role"],
                "prompt_tokens": row["prompt_tokens"] or 0,
                "completion_tokens": row["completion_tokens"] or 0,
                "request_count": row["request_count"],
            }
            for row in rows
        ]

    def get_total_usage(self) -> dict[str, int]:
        """Return aggregate token counts across all requests.

        Includes the prompt-cache totals (``cache_read_tokens`` /
        ``cache_creation_tokens``) so a resumed session can rehydrate its
        in-memory cache accumulators and report cache cost / hit-rate as
        if it had never restarted.
        """
        row = self._db.execute(
            """\
            SELECT COALESCE(SUM(prompt_tokens), 0)         AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0)      AS completion_tokens,
                   COALESCE(SUM(cache_read_tokens), 0)      AS cache_read_tokens,
                   COALESCE(SUM(cache_creation_tokens), 0)  AS cache_creation_tokens
            FROM token_usage
            """
        ).fetchone()
        return {
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "cache_read_tokens": row["cache_read_tokens"],
            "cache_creation_tokens": row["cache_creation_tokens"],
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
        :func:`cantrip.agent.runtime.durability.checkpoint` on
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
