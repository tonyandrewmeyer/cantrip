"""Mode and model slash commands.

Extracted from :mod:`cantrip.agent.commands.slash` (Phase 113.5).  Groups the
session-mode toggles — ``/plan`` and ``/build`` (plan mode), ``/architect``
(the two-model architect/editor split), ``/auto-commit``, ``/yolo``,
``/pause`` and ``/resume`` (autonomous-loop control), and ``/ralph`` (the
bounded refinement loop) — alongside the ``/model`` provider switch they sit
with.  Each handler returns plain text except ``/model``, which returns a
:class:`~cantrip.agent.commands.slash.SlashResult`.
"""

from __future__ import annotations

import logging
import typing

from cantrip.llm.base import Message, ProviderError, Role
from cantrip.ui import events as ui_events

if typing.TYPE_CHECKING:
    from cantrip.agent.commands.slash import SlashResult
    from cantrip.agent.core import CantripAgent

log = logging.getLogger(__name__)


# Providers that ``/model`` can construct with just a name (plus an
# optional model slug).  ``openai-compatible`` is deliberately absent —
# it needs a ``--base-url`` that doesn't fit the slash syntax.  Restart
# the session with ``cantrip --provider openai-compatible --base-url ...``
# when targeting a generic endpoint.
_MODEL_SWITCH_PROVIDERS: frozenset[str] = frozenset(
    {"gemini", "claude", "fireworks", "openrouter", "opencode-zen", "inference-snap"}
)


def _handle_model(agent: CantripAgent, args: str) -> SlashResult:
    """Dispatch the ``/model`` slash command.

    No argument: print the active provider + model.  Argument parses
    as ``provider`` (switch to that provider's default model) or
    ``provider/model`` (switch to a specific model).  Model slugs can
    contain ``/`` themselves — only the first ``/`` is treated as the
    separator.
    """
    from cantrip.agent.commands.slash import SlashResult

    spec = args.strip()
    if not spec:
        light = ""
        if agent._light_provider is not None:
            light = f" (light: {agent._light_provider.name}/{agent._light_provider.model_name})"
        return SlashResult(
            text=(
                f"**Active model:** {agent.provider.name}/"
                f"{agent.provider.model_name}{light}\n\n"
                "Usage: `/model <provider>[/model]` — switch to another "
                "provider.  Known providers: "
                f"`{'`, `'.join(sorted(_MODEL_SWITCH_PROVIDERS))}`.  "
                "Model slug is optional (uses the provider's default "
                "when omitted).  Example: `/model claude/claude-sonnet-4-6`."
            )
        )

    provider_name, _, model_slug = spec.partition("/")
    provider_name = provider_name.strip()
    model_slug = model_slug.strip() or None

    if provider_name not in _MODEL_SWITCH_PROVIDERS:
        return SlashResult(
            text=(
                f"Unknown provider `{provider_name}`.  Known providers: "
                f"`{'`, `'.join(sorted(_MODEL_SWITCH_PROVIDERS))}`.  "
                "For `openai-compatible` endpoints, restart Cantrip with "
                "`--provider openai-compatible --base-url ...`."
            )
        )

    try:
        agent.switch_model(provider_name, model_slug)
    except (ProviderError, ValueError) as exc:
        return SlashResult(text=f"_Failed to switch model: {exc}_")

    return SlashResult(
        text=(
            f"Switched to **{agent.provider.name}/{agent.provider.model_name}** "
            f"(context window: {agent.provider.context_window_tokens:,} tokens)."
        )
    )


def handle_plan(agent: CantripAgent) -> str:
    """Phase 68.4 ``/plan``: enter the read-only plan-mode gate.

    Flips ``state.plan_mode`` and publishes a ``STATUS_BAR_CHANGED``
    event so every surface (TUI, Web, CLI) can re-tint the mode
    indicator.  Returns a concise one-liner noting the allow-listed
    tools.  Already-in-plan-mode is a no-op; the status line stays
    a single, truthful sentence.
    """
    if agent.state.plan_mode:
        return "Already in plan mode.  Use `/build` to resume executing changes."
    agent.state.plan_mode = True
    # Clear any stale summary from a prior plan cycle.  ``/build``
    # will capture a new one the next time the agent produces a
    # "Proposed changes" section.
    agent.state.plan_summary = None
    try:
        agent.event_bus.publish(ui_events.status_bar_changed(mode="plan"))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /plan")
    return (
        "**Plan mode on.**  I will read the code, Juju state, git history, "
        "and web, and produce a *Proposed changes* summary — but I won't "
        "edit files, run shells, or deploy.  Flip back with `/build`."
    )


def handle_build(agent: CantripAgent) -> str:
    """Phase 68.4 ``/build``: leave plan mode and resume executing changes.

    Flips ``state.plan_mode`` off and, when a ``plan_summary`` was
    captured while planning, re-sends it as an assistant-role prelude
    so the agent picks the next turn up with the *Proposed changes*
    section already in scope.  Without a captured summary we just
    note the mode switch.
    """
    if not agent.state.plan_mode:
        return "Already in build mode — every tool is available."
    agent.state.plan_mode = False
    resume_note = ""
    if agent.state.plan_summary:
        # Drop the summary into ``state.messages`` so the next user
        # message sees it in the LLM's context.  We tag the role as
        # ASSISTANT so the LLM treats it as its own prior output and
        # builds on it rather than re-planning from scratch.
        agent.state.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=f"## Proposed changes (from plan mode)\n\n{agent.state.plan_summary}",
            )
        )
        resume_note = (
            "  Resumed the plan's *Proposed changes* section as context — "
            "the next turn will execute against it."
        )
        agent.state.plan_summary = None
    try:
        agent.event_bus.publish(ui_events.status_bar_changed(mode="build"))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /build")
    return f"**Build mode on.**  Every tool is available again.{resume_note}"


def handle_architect(agent: CantripAgent, args: str) -> str:
    """Phase 71.2 ``/architect``: toggle architect/editor two-model split.

    Bare ``/architect`` flips the flag; ``/architect on`` and
    ``/architect off`` are explicit forms.  An optional second token
    sets the editor provider/model in the same syntax as ``/model``
    (``provider`` or ``provider/model``).  When toggled on without
    an explicit editor, ``resolve_light_provider`` picks a same-
    family cheaper variant.  When no lighter variant exists the
    editor falls back to the main provider (no cost saving but the
    dual-pass shape stays).

    Examples::

        /architect              # toggle on/off
        /architect on           # enable
        /architect on claude/claude-haiku-4-5-20251001
        /architect off
    """
    tokens = args.strip().split(maxsplit=1)
    if not tokens:
        target = not agent.state.architect_mode
        editor_spec = ""
    else:
        first = tokens[0].lower()
        if first in {"on", "enable", "true", "1"}:
            target = True
        elif first in {"off", "disable", "false", "0"}:
            target = False
        else:
            return (
                "Usage: `/architect` toggles, `/architect on` enables, "
                "`/architect off` disables.  An optional second token "
                "(`provider` or `provider/model`) overrides the editor."
            )
        editor_spec = tokens[1].strip() if len(tokens) > 1 else ""

    if editor_spec and not target:
        return "_Editor override only makes sense with `/architect on`._"

    if editor_spec:
        provider_name, _, model_slug = editor_spec.partition("/")
        provider_name = provider_name.strip()
        model_slug = model_slug.strip() or None
        if provider_name not in _MODEL_SWITCH_PROVIDERS:
            return (
                f"Unknown editor provider `{provider_name}`.  Known "
                f"providers: `{'`, `'.join(sorted(_MODEL_SWITCH_PROVIDERS))}`."
            )
        agent.state.editor_provider = provider_name
        agent.state.editor_model = model_slug

    if target == agent.state.architect_mode and not editor_spec:
        return (
            f"Architect mode is already {'on' if target else 'off'}.  Bare `/architect` toggles."
        )

    agent.state.architect_mode = target
    agent.state.architect_consecutive_failures = 0
    if not target:
        # Drop any explicit editor override on disable so the next
        # enable starts from the same-family default.
        agent.state.editor_provider = None
        agent.state.editor_model = None

    try:
        agent.event_bus.publish(
            ui_events.status_bar_changed(mode="architect" if target else "build")
        )
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /architect")

    if not target:
        return "**Architect mode off.**  Single-model conversation resumed."

    editor_label = _describe_editor(agent)
    return (
        f"**Architect mode on.**  Architect: "
        f"`{agent.provider.name}/{agent.provider.model_name}` — "
        f"Editor: `{editor_label}`.  Each turn now runs as "
        "*propose → edit*; both passes appear separately in `/cost`."
    )


def _describe_editor(agent: CantripAgent) -> str:
    """One-line label for the current editor provider/model.

    Reads ``state.editor_provider`` / ``editor_model`` first; falls
    back to the resolved light provider when no explicit override is
    set; falls back to the main provider when no lighter variant
    exists either (the no-saving case).
    """
    if agent.state.editor_provider:
        slug = agent.state.editor_model or "<default>"
        return f"{agent.state.editor_provider}/{slug}"
    light = getattr(agent, "_light_provider", None)
    if light is not None:
        return f"{light.name}/{light.model_name}"
    return f"{agent.provider.name}/{agent.provider.model_name}"


def handle_auto_commit(agent: CantripAgent, args: str) -> str:
    """Phase 71.3 ``/auto-commit``: toggle per-turn auto-commit.

    Bare ``/auto-commit`` flips the flag; ``/auto-commit on`` and
    ``/auto-commit off`` are explicit.  When on, every turn that
    mutates files lands as a discrete git commit with a Cantrip
    co-author trailer; pre-existing dirty work commits separately
    as ``chore(pre-cantrip): save in-progress work``.

    The toggle is sticky for the session and not persisted; restart
    Cantrip with ``--no-auto-commit`` to start fresh sessions with
    auto-commit disabled.
    """
    token = args.strip().lower()
    if token in {"on", "enable", "true", "1"}:
        target = True
    elif token in {"off", "disable", "false", "0"}:
        target = False
    elif token == "":
        target = not agent.state.git_auto_commit
    else:
        return (
            "Usage: `/auto-commit` toggles, `/auto-commit on` enables, "
            "`/auto-commit off` disables."
        )

    if target == agent.state.git_auto_commit:
        return f"Auto-commit is already {'on' if target else 'off'}."

    agent.state.git_auto_commit = target
    if target:
        return (
            "**Auto-commit on.**  Every turn that touches files will "
            "land as a discrete git commit with a Cantrip co-author "
            "trailer; pre-existing dirty work commits first."
        )
    return (
        "**Auto-commit off.**  Agent edits stay in the working tree and you choose when to commit."
    )


def handle_yolo(agent: CantripAgent, args: str) -> str:
    """Phase 69.2 ``/yolo``: toggle unattended auto-approve mode.

    Bare ``/yolo`` flips the flag.  ``/yolo on`` and ``/yolo off``
    are explicit forms used by scripts and by operators who want to
    be sure which state they are heading into.  Any other argument
    is rejected with a usage line to prevent typos like
    ``/yolo yes`` from being silently interpreted.

    Syncs the flag onto the executor's ``PermissionManager`` when
    one is running so existing pending asks either resolve (on) or
    stop auto-approving (off).  Publishes a
    ``STATUS_BAR_CHANGED`` event with ``mode=yolo|build`` so every
    surface repaints its banner in lockstep.
    """
    token = args.strip().lower()
    if token in {"on", "enable", "true", "1"}:
        target = True
    elif token in {"off", "disable", "false", "0"}:
        target = False
    elif token == "":
        target = not agent.state.yolo_mode
    else:
        return "Usage: `/yolo` toggles, `/yolo on` enables, `/yolo off` disables."

    if target == agent.state.yolo_mode:
        state_text = "on" if target else "off"
        return f"Already in yolo mode {state_text}."

    agent.state.yolo_mode = target
    executor_ctl = getattr(agent, "_executor_ctl", None)
    if executor_ctl is not None:
        try:
            executor_ctl.set_yolo(target)
        except AttributeError:
            log.debug("executor_ctl has no set_yolo method", exc_info=True)

    try:
        agent.event_bus.publish(ui_events.status_bar_changed(mode="yolo" if target else "build"))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /yolo")

    if target:
        return (
            "**Yolo mode on.**  Every `ask` permission auto-approves "
            "for the rest of this session.  `deny` rules still block — "
            "review your `permissions.yaml` before a destructive run.  "
            "Flip back with `/yolo off`."
        )
    return "**Yolo mode off.**  `ask` rules prompt again as usual."


def handle_pause(agent: CantripAgent, args: str) -> str:
    """Phase 99.1 ``/pause``: stop the autonomous loop picking new tasks.

    The flag is sticky: chat keeps working and any CONFIRM task already
    in flight continues to completion, but no new background tasks are
    dispatched until the user runs ``/resume``.  Bare ``/pause`` is the
    only accepted form — ``on``/``off`` arguments would just duplicate
    the ``/resume`` verb.
    """
    if args.strip():
        return "Usage: `/pause` takes no arguments — use `/resume` to restart the loop."

    executor_ctl = getattr(agent, "_executor_ctl", None)
    if executor_ctl is None or not hasattr(executor_ctl, "user_pause"):
        return "Background executor is not available — nothing to pause."

    changed = executor_ctl.user_pause()
    try:
        agent.event_bus.publish(ui_events.status_bar_changed(loop_state=agent.lifecycle_label()))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /pause")

    if not changed:
        return "Already paused.  Use `/resume` to restart the autonomous loop."
    return (
        "**Autonomous loop paused.**  Chat and CONFIRM tasks keep working; "
        "no new background tasks will start until you run `/resume`."
    )


def handle_resume(agent: CantripAgent, args: str) -> str:
    """Phase 99.1 ``/resume``: restart a paused autonomous loop."""
    if args.strip():
        return "Usage: `/resume` takes no arguments — use `/pause` to stop the loop."

    executor_ctl = getattr(agent, "_executor_ctl", None)
    if executor_ctl is None or not hasattr(executor_ctl, "user_resume"):
        return "Background executor is not available — nothing to resume."

    changed = executor_ctl.user_resume()
    try:
        agent.event_bus.publish(ui_events.status_bar_changed(loop_state=agent.lifecycle_label()))
    except (TypeError, ValueError, RuntimeError, AttributeError):
        log.exception("status_bar_changed publish failed on /resume")

    if not changed:
        return "Already running.  Use `/pause` to stop the autonomous loop."
    return "**Autonomous loop resumed.**  Background tasks pick up where they left off."


def handle_ralph(agent: CantripAgent, args: str) -> str:
    """Phase 69.1 ``/ralph N``: enable the bounded iterate-until-green loop.

    Stamps ``state.ralph_max_iterations`` on the agent so the next
    print-mode invocation (or future TUI integration) picks it up.
    Bare ``/ralph`` reports the current setting.  ``/ralph off``
    or ``/ralph 0`` disables.  Any positive integer is the new cap;
    ``-1`` is unlimited.

    Mid-session in the TUI the flag is informational — the actual
    refinement loop only fires inside ``cantrip run --print``
    (where there's no human to drive iteration manually).  We still
    accept the slash command in the TUI so a session can record
    its intended Ralph cap for later or to flip the audit-trail
    flag explicitly.
    """
    token = args.strip().lower()
    current = agent.state.ralph_max_iterations
    if token == "":
        if current == 0:
            return (
                "Ralph loop is **off**.  Run `/ralph N` to set a cap, or "
                "`cantrip run --ralph N --print '<goal>'` for unattended "
                "refinement."
            )
        if current < 0:
            return "Ralph loop is **on** with no iteration cap (`-1` = unlimited)."
        return f"Ralph loop is **on** with a cap of {current} iteration(s)."

    if token in {"off", "disable", "false", "0"}:
        new_value = 0
    else:
        try:
            new_value = int(token)
        except ValueError:
            return (
                "Usage: `/ralph` shows the cap, `/ralph N` sets it, "
                "`/ralph off` or `/ralph 0` disables, `/ralph -1` is "
                "unlimited."
            )

    agent.state.ralph_max_iterations = new_value

    if new_value == 0:
        return "**Ralph loop off.**  Single-shot runs only."
    if new_value < 0:
        return (
            "**Ralph loop on (unlimited).**  Loop until the agent emits "
            "`STOP` or stall detection trips.  Bounded internally by a "
            "safety ceiling so a stuck agent can't run forever."
        )
    return (
        f"**Ralph loop on, cap = {new_value}.**  Re-feeds the goal up to "
        f"{new_value} time(s) until the agent emits `STOP` on its own "
        "line."
    )
