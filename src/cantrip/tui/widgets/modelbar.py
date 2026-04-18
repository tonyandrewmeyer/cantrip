"""Model information bar widget for the TUI."""

import contextlib

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from cantrip.llm import pricing


class ModelInfoBar(Widget):
    """Collapsible bar showing model, context, and token usage information.

    Updated after each agent response via reactive properties.
    """

    DEFAULT_CSS = """
    ModelInfoBar {
        height: auto;
        max-height: 3;
        padding: 0 1;
        background: $primary-background;
        color: $text-muted;
    }

    ModelInfoBar .model-info-row {
        height: 1;
    }
    """

    model_name: reactive[str] = reactive("", init=False)
    light_model_name: reactive[str] = reactive("", init=False)
    provider_name: reactive[str] = reactive("", init=False)
    thinking_mode: reactive[str] = reactive("", init=False)

    context_used: reactive[int] = reactive(0, init=False)
    context_window: reactive[int] = reactive(0, init=False)
    compact_threshold: reactive[float] = reactive(0.80, init=False)

    session_prompt_tokens: reactive[int] = reactive(0, init=False)
    session_completion_tokens: reactive[int] = reactive(0, init=False)
    session_request_count: reactive[int] = reactive(0, init=False)

    alltime_prompt_tokens: reactive[int] = reactive(0, init=False)
    alltime_completion_tokens: reactive[int] = reactive(0, init=False)
    alltime_request_count: reactive[int] = reactive(0, init=False)

    cache_creation_tokens: reactive[int] = reactive(0, init=False)
    cache_read_tokens: reactive[int] = reactive(0, init=False)

    session_cost_usd: reactive[float] = reactive(0.0, init=False)
    alltime_cost_usd: reactive[float] = reactive(0.0, init=False)

    github_repo: reactive[str] = reactive("", init=False)

    def compose(self) -> ComposeResult:
        """Compose the bar layout."""
        yield Static("", id="model-info-line1", classes="model-info-row")
        yield Static("", id="model-info-line2", classes="model-info-row")

    def _refresh_content(self) -> None:
        """Rebuild both lines from current reactive values."""
        # Line 1: model, provider, thinking mode, light model.
        parts: list[str] = []
        if self.model_name:
            label = self.model_name
            if self.provider_name:
                label = f"{self.provider_name}/{label}"
            parts.append(label)
        if self.thinking_mode:
            parts.append(f"[{self.thinking_mode}]")
        if self.light_model_name:
            parts.append(f"light: {self.light_model_name}")
        if self.github_repo:
            parts.append(f"gh: {self.github_repo}")

        # Line 2: context usage, compaction distance, session tokens.
        ctx_parts: list[str] = []
        if self.context_window > 0:
            pct = (self.context_used / self.context_window * 100) if self.context_window else 0
            compact_at = int(self.compact_threshold * 100)
            remaining = self.context_window - self.context_used
            ctx_parts.append(
                f"context: {_fmt_k(self.context_used)}/{_fmt_k(self.context_window)} "
                f"({pct:.0f}%, compacts at {compact_at}%, "
                f"{_fmt_k(remaining)} remaining)"
            )

        session_total = self.session_prompt_tokens + self.session_completion_tokens
        if session_total > 0:
            session_label = (
                f"session: {_fmt_k(session_total)} "
                f"({_fmt_k(self.session_prompt_tokens)} in, "
                f"{_fmt_k(self.session_completion_tokens)} out, "
                f"{self.session_request_count} req)"
            )
            # Show cache hit rate when Claude prompt caching is active.
            cache_total = self.cache_creation_tokens + self.cache_read_tokens
            if cache_total > 0:
                hit_pct = self.cache_read_tokens / cache_total * 100
                session_label += f"  cache: {hit_pct:.0f}% hit"
            if self.session_cost_usd > 0:
                session_label += f"  est. {pricing.format_cost(self.session_cost_usd)}"
            ctx_parts.append(session_label)

        alltime_total = self.alltime_prompt_tokens + self.alltime_completion_tokens
        if alltime_total > 0 and alltime_total != session_total:
            alltime_label = f"all-time: {_fmt_k(alltime_total)} ({self.alltime_request_count} req)"
            if self.alltime_cost_usd > 0:
                alltime_label += f"  est. {pricing.format_cost(self.alltime_cost_usd)}"
            ctx_parts.append(alltime_label)

        with contextlib.suppress(NoMatches):
            self.query_one("#model-info-line1", Static).update("  ".join(parts))
            self.query_one("#model-info-line2", Static).update("  ".join(ctx_parts))

    # Every reactive triggers the same refresh — generate watchers in a loop
    # rather than writing 13 identical two-line methods.


# Textual discovers watcher methods by name (watch_<attr>).  Generate them
# from the reactive attribute list so each change triggers _refresh_content.
for _attr in (
    "model_name",
    "light_model_name",
    "provider_name",
    "thinking_mode",
    "context_used",
    "context_window",
    "compact_threshold",
    "session_prompt_tokens",
    "session_completion_tokens",
    "session_request_count",
    "alltime_prompt_tokens",
    "alltime_completion_tokens",
    "alltime_request_count",
    "cache_creation_tokens",
    "cache_read_tokens",
    "session_cost_usd",
    "alltime_cost_usd",
    "github_repo",
):
    setattr(ModelInfoBar, f"watch_{_attr}", lambda self: self._refresh_content())


def _fmt_k(n: int) -> str:
    """Format a token count as a compact string (e.g. 1.2M, 48.5k, 320)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
