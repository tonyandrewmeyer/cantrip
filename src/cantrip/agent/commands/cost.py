"""``/cost`` — token usage and estimated cost rollups.

Mirrors the CLI's legacy ``_print_cost`` block so the same summary is
useful as a system message in the TUI and Web surfaces.  Lifted out
of the dispatcher in Phase 85.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cantrip.llm import pricing

if TYPE_CHECKING:
    from cantrip.agent.core import CantripAgent


def format_cost(agent: CantripAgent) -> str:
    """Render token usage and estimated cost as plain text.

    Mirrors the CLI's legacy ``_print_cost`` output so the same block
    is useful in the TUI and Web as a system message.
    """
    store = agent.store
    if not store:
        return "_No usage data available._"

    total = store.get_total_usage()
    prompt = int(total.get("prompt_tokens", 0) or 0)
    completion = int(total.get("completion_tokens", 0) or 0)
    total_tokens = prompt + completion

    if total_tokens == 0:
        return "_No tokens used yet._"

    lines = [
        "**Token usage**",
        f"- Prompt:     {prompt:>10,}",
        f"- Completion: {completion:>10,}",
        f"- Total:      {total_tokens:>10,}",
    ]

    if agent.cache_creation_tokens or agent.cache_read_tokens:
        cache_total = agent.cache_creation_tokens + agent.cache_read_tokens
        hit_pct = agent.cache_read_tokens / cache_total * 100 if cache_total else 0
        lines.append(f"- Cache hit:  {hit_pct:>9.0f}%")

    # Phase 104: context-management rollup — which compaction strategy is
    # running, how often it has fired, and the live tool count (small
    # local models trim hard, so the operator wants to see what's
    # actually being offered to the model).
    cm = agent.context_manager
    compactions = cm.compactions_attempted
    emergencies = cm.emergencies_attempted
    lines.append("")
    lines.append("**Context**")
    mode_note = " (short-session)" if cm.short_session_mode else ""
    lines.append(f"- Compaction strategy: {cm.compaction_strategy}{mode_note}")
    if compactions or emergencies:
        lines.append(
            f"- Compactions: {compactions}"
            + (f", emergency truncations: {emergencies}" if emergencies else "")
        )
    full_tools = len(agent._tools)
    active_tools = len(agent._tools_for_llm() or [])
    if active_tools < full_tools:
        lines.append(
            f"- Tools offered to model: {active_tools} of {full_tools} "
            f"(curated for {agent.workflow_phase.value} phase)"
        )
    else:
        lines.append(f"- Tools offered to model: {active_tools}")

    # Phase 52.6: tokens avoided via step-checkpoint replay.  These are
    # billed zero this session (the live provider never fired) but the
    # sum is worth showing so the user can see the cost-savings headroom
    # the durable-execution machinery bought them.
    savings = store.get_replay_savings()
    saved_total = savings["prompt_tokens"] + savings["completion_tokens"]
    if saved_total:
        lines.append(
            f"- Cached from checkpoint: {saved_total:,} tokens "
            f"({savings['prompt_tokens']:,} prompt, "
            f"{savings['completion_tokens']:,} completion, "
            f"{savings['request_count']} replayed turn(s))"
        )

    by_model = store.get_usage_by_model()
    total_cost = 0.0
    if by_model:
        lines.append("")
        lines.append("**By model**")
        for row in by_model:
            model = row.get("model", "unknown")
            reqs = int(row.get("request_count", 0) or 0)
            prompt_t = int(row.get("prompt_tokens", 0) or 0)
            completion_t = int(row.get("completion_tokens", 0) or 0)
            tokens = prompt_t + completion_t
            cost = pricing.estimate_cost(
                str(model),
                prompt_tokens=prompt_t,
                completion_tokens=completion_t,
            )
            total_cost += cost
            cost_str = pricing.format_cost(cost) if cost > 0 else "free"
            lines.append(f"- {model}: {tokens:,} tokens, {reqs} requests, {cost_str}")

    if agent.cache_read_tokens or agent.cache_creation_tokens:
        cache_cost = pricing.estimate_cost(
            agent.provider.model_name,
            cache_read_tokens=agent.cache_read_tokens,
            cache_write_tokens=agent.cache_creation_tokens,
        )
        total_cost += cache_cost

    # Per-category breakdown (Phase 31.4) — aggregate across models so a
    # category row sums every subagent that ran under it.  Cache cost is
    # global (not category-attributed) so it stays out of this table.
    by_cat = store.get_usage_by_category()
    if by_cat:
        cat_totals: dict[str, tuple[int, float, int]] = {}
        for row in by_cat:
            cat = str(row.get("category", "conversation"))
            prompt_t = int(row.get("prompt_tokens", 0) or 0)
            completion_t = int(row.get("completion_tokens", 0) or 0)
            reqs = int(row.get("request_count", 0) or 0)
            cost = pricing.estimate_cost(
                str(row.get("model", "")),
                prompt_tokens=prompt_t,
                completion_tokens=completion_t,
            )
            tokens, running_cost, running_reqs = cat_totals.get(cat, (0, 0.0, 0))
            cat_totals[cat] = (
                tokens + prompt_t + completion_t,
                running_cost + cost,
                running_reqs + reqs,
            )
        lines.append("")
        lines.append("**By category**")
        for cat in sorted(cat_totals):
            tokens, cat_cost, reqs = cat_totals[cat]
            cost_str = pricing.format_cost(cat_cost) if cat_cost > 0 else "free"
            lines.append(f"- {cat}: {tokens:,} tokens, {reqs} requests, {cost_str}")

    # Phase 72.3: per-role rollup (chat / embed / rerank) — separates
    # retrieval spend from chat so the user sees where the bill goes.
    # NULL legacy rows fall under ``chat``; rolling them in keeps the
    # historical total honest.
    by_role = getattr(store, "get_usage_by_role", lambda: [])()
    if by_role and any(row.get("role", "chat") != "chat" for row in by_role):
        lines.append("")
        lines.append("**By role**")
        for row in by_role:
            role = str(row.get("role", "chat"))
            prompt_t = int(row.get("prompt_tokens", 0) or 0)
            completion_t = int(row.get("completion_tokens", 0) or 0)
            reqs = int(row.get("request_count", 0) or 0)
            tokens = prompt_t + completion_t
            lines.append(f"- {role}: {tokens:,} tokens, {reqs} requests")

    if total_cost > 0:
        lines.append("")
        lines.append(f"_Estimated total: {pricing.format_cost(total_cost)}_")
        lines.append("_(approximate; published list prices, may drift)_")

    # Phase 103.4: surface unresolved edit-string misses so the operator
    # can spot a session that's burning rounds on hallucinated
    # ``old_string`` values without trawling the transcript.  Quiet when
    # everything has resolved (the common case) — the line only fires
    # when at least one path still has a non-zero count.
    misses = {path: count for path, count in agent.state.edit_string_misses.items() if count > 0}
    if misses:
        total_misses = sum(misses.values())
        lines.append("")
        lines.append(
            f"**Edit-string misses (unresolved):** {total_misses} across "
            f"{len(misses)} file{'s' if len(misses) != 1 else ''}"
        )
        lines.extend(f"- {path}: {misses[path]}" for path in sorted(misses))

    return "\n".join(lines)
