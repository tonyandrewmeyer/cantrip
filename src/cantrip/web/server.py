"""Web UI server — aiohttp app with WebSocket for real-time updates."""

import argparse
import asyncio
import contextlib
import datetime
import json
import logging
import pathlib
import weakref

import aiohttp.web as web
import jinja2

from cantrip import update
from cantrip.agent import slash_commands
from cantrip.agent.core import CantripAgent
from cantrip.agent.preflight import DEFAULT_PRESET, PreflightEvent
from cantrip.llm import create_provider, resolve_light_provider
from cantrip.llm.base import ProviderError, ProviderOverloadedError, ProviderRateLimitError, Role
from cantrip.ui import events as ui_events
from cantrip.web import markdown as md_render

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8471
_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"
_STATIC_DIR = pathlib.Path(__file__).parent / "static"

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_MAX_LOG_LINES = 5000

# Typed keys for ``web.Application`` shared state.  aiohttp emits
# ``NotAppKeyWarning`` for raw string keys; these provide the same
# ergonomics with static typing and no warning.
AGENT_KEY: web.AppKey[CantripAgent] = web.AppKey("agent", CantripAgent)
WS_CLIENTS_KEY: web.AppKey[weakref.WeakSet] = web.AppKey("ws_clients", weakref.WeakSet)
CHAT_LOCK_KEY: web.AppKey[asyncio.Lock] = web.AppKey("chat_lock", asyncio.Lock)
JINJA_ENV_KEY: web.AppKey[jinja2.Environment] = web.AppKey("jinja_env", jinja2.Environment)
PORT_KEY: web.AppKey[int] = web.AppKey("port", int)

# Holds the currently-running ``process_message`` task so a ``cancel``
# WebSocket message can interrupt it.  The chat lock serialises turns,
# so at most one task is in flight at a time — a single slot suffices.
CURRENT_TURN_KEY: web.AppKey[dict[str, asyncio.Task | None]] = web.AppKey("current_turn", dict)

# Tracks whether the resume-prompt decision has been made for this
# server lifetime.  Shared across all connected clients — the first one
# to pick Resume / Fresh wins; subsequent page loads see ``decided=True``
# and skip the banner.
SESSION_DECIDED_KEY: web.AppKey[dict[str, bool]] = web.AppKey("session_decided", dict)

# Holds the latest PyPI update verdict for this server process.  The
# startup worker fills in ``"info"`` (an :class:`update.UpdateInfo` or
# ``None``) when the check completes.  Shared across clients so every
# page load — including late reconnects — sees the same answer.
UPDATE_STATE_KEY: web.AppKey[dict[str, object]] = web.AppKey("update_state", dict)


# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------


async def _safe_ws_send(ws: web.WebSocketResponse, payload: str) -> None:
    """Send a message to a WebSocket, silently handling connection errors."""
    with contextlib.suppress(ConnectionResetError, ConnectionError, OSError):
        await ws.send_str(payload)


def _broadcast(app: web.Application, event_type: str, data: dict) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    payload = json.dumps({"type": event_type, "data": data})
    clients: weakref.WeakSet = app[WS_CLIENTS_KEY]
    stale: list[web.WebSocketResponse] = []
    for ws in clients:
        if ws.closed:
            stale.append(ws)
            continue
        asyncio.ensure_future(_safe_ws_send(ws, payload))
    for ws in stale:
        clients.discard(ws)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _trailing_reasoning(agent: CantripAgent) -> str:
    """Return the reasoning text on the most recent assistant message.

    Walks backwards through ``agent.state.messages`` until it finds
    an assistant turn, then returns whatever landed in its
    ``_thinking_content`` metadata (Claude thinking or
    OpenAI-compatible ``reasoning_content``).  Empty string when the
    turn produced no reasoning.
    """
    for msg in reversed(agent.state.messages):
        if msg.role == Role.ASSISTANT:
            return str(msg.metadata.get("_thinking_content", ""))
    return ""


def _broadcast_chat(
    app: web.Application,
    role: str,
    content: str,
    *,
    reasoning: str = "",
) -> None:
    """Broadcast a ``chat_message`` with pre-rendered Markdown HTML.

    Centralising the render call here means every chat message — user,
    assistant, or system — arrives at the browser as both the source
    text (``content``) and the rendered HTML (``html``), so the
    frontend can ``innerHTML`` the HTML without having to run its own
    Markdown parser.  The timestamp is a UTC ISO string; the browser
    formats it per-locale.

    When ``reasoning`` is non-empty, the browser renders it inside a
    collapsible ``<details>`` above the answer — Claude's extended
    thinking and Kimi K2's ``reasoning_content`` both flow through
    this channel.
    """
    _broadcast(
        app,
        "chat_message",
        {
            "role": role,
            "content": content,
            "html": md_render.render(content),
            "reasoning": reasoning,
            "timestamp": _now_iso(),
        },
    )


def _handle_shared_slash_command(app: web.Application, agent: CantripAgent, content: str) -> bool:
    """Dispatch the shared slash commands via :mod:`slash_commands`.

    Returns ``True`` when the message was handled — the caller then
    skips the LLM round.  Echoes the user's command and the system
    response so the chat history matches the TUI behaviour.  Async
    follow-ups (e.g. ``/mcp marketplace``) run as a background task
    and broadcast their result when complete.
    """
    result = slash_commands.dispatch(agent, content)
    if result is None:
        return False
    _broadcast_chat(app, "user", content)
    _broadcast_chat(app, "system", result.text)
    if result.followup is not None:
        asyncio.create_task(_broadcast_followup(app, result.followup))
    return True


async def _broadcast_followup(app: web.Application, followup) -> None:
    """Await a dispatcher follow-up coroutine and broadcast its result."""
    try:
        output = await followup
    except Exception as exc:  # noqa: BLE001 - background task; surface any error
        output = f"_Error: marketplace lookup failed: {exc}_"
    _broadcast_chat(app, "system", output)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def _index(request: web.Request) -> web.Response:
    """Serve the main page with initial state baked in."""
    env = request.app[JINJA_ENV_KEY]
    agent: CantripAgent = request.app[AGENT_KEY]
    template = env.get_template("index.html.j2")

    tasks = []
    if agent._work_queue:
        tasks = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "category": t.category.value,
                "worktree_path": t.worktree_path,
            }
            for t in agent._work_queue.all_tasks()
        ]

    html = template.render(
        charm_name=agent.state.charm_name or "",
        tasks=tasks,
        port=request.app[PORT_KEY],
    )
    return web.Response(text=html, content_type="text/html")


async def _api_state(request: web.Request) -> web.Response:
    """Return current tasks and messages as JSON."""
    agent: CantripAgent = request.app[AGENT_KEY]

    tasks = []
    if agent._work_queue:
        tasks = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "category": t.category.value,
                "description": t.description,
                "result": t.result,
                "worktree_path": t.worktree_path,
            }
            for t in agent._work_queue.all_tasks()
        ]

    return web.json_response(
        {
            "charm_name": agent.state.charm_name or "",
            "tasks": tasks,
        }
    )


async def _api_messages(request: web.Request) -> web.Response:
    """Return conversation history as JSON for page reload.

    Prefers the SQLite store when available — it carries persisted
    ``timestamp`` columns so the browser can show when each message
    arrived.  Falls back to the in-memory ``state.messages`` when the
    store isn't initialised yet (e.g. first page load before any
    message is sent); those messages are stamped with the current
    time since we have no better signal.
    """
    agent: CantripAgent = request.app[AGENT_KEY]
    messages = _messages_with_timestamps(agent)
    return web.json_response({"messages": messages})


def _messages_with_timestamps(agent: CantripAgent) -> list[dict[str, object]]:
    """Build the ``/api/messages`` payload with a ``timestamp`` per row."""
    store = getattr(agent, "_store", None)
    if store is not None:
        try:
            rows = store.load_messages()
        except (OSError, ValueError, RuntimeError):
            rows = []
        if rows:
            return [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "html": md_render.render(str(r["content"] or "")),
                    "reasoning": _row_reasoning(r),
                    "timestamp": r.get("timestamp"),
                }
                for r in rows
                if r.get("content")
            ]

    now = _now_iso()
    return [
        {
            "role": msg.role.value,
            "content": msg.content,
            "html": md_render.render(msg.content),
            "reasoning": str(msg.metadata.get("_thinking_content", "")),
            "timestamp": now,
        }
        for msg in agent.state.messages
        if msg.content
    ]


def _row_reasoning(row: dict[str, object]) -> str:
    """Extract reasoning text from a persisted message row."""
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        return str(metadata.get("_thinking_content", ""))
    return ""


async def _api_session_preview(request: web.Request) -> web.Response:
    """Return a lightweight preview of any persisted session.

    The browser calls this on page load to decide whether to show the
    resume banner.  ``decided`` is True once Resume or Fresh has been
    chosen for this server process, so a second page load doesn't
    re-prompt.
    """
    agent: CantripAgent = request.app[AGENT_KEY]
    decided_flag = request.app[SESSION_DECIDED_KEY].get("value", False)
    preview = agent.preview_session()
    return web.json_response(
        {
            "exists": preview.exists,
            "decided": decided_flag,
            "summary": preview.summary(),
            "charm_name": preview.charm_name,
            "charm_type": preview.charm_type,
            "dev_model": preview.dev_model,
            "cos_model": preview.cos_model,
            "updated_at": preview.updated_at,
            "message_count": preview.message_count,
            "task_counts": preview.task_counts,
            "has_unfinished_tasks": preview.has_unfinished_tasks,
        }
    )


async def _api_session_decide(request: web.Request) -> web.Response:
    """Accept a Resume / Fresh choice and load or archive accordingly.

    Idempotent — once decided, further POSTs return 409 so concurrent
    clients don't race into a double-archive.
    """
    app = request.app
    agent: CantripAgent = app[AGENT_KEY]
    flag = app[SESSION_DECIDED_KEY]
    if flag.get("value"):
        return web.json_response({"error": "Session decision already made"}, status=409)

    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON"}, status=400)
    choice = str(body.get("choice") or "").strip().lower()
    if choice not in ("resume", "fresh"):
        return web.json_response({"error": "choice must be 'resume' or 'fresh'"}, status=400)

    if choice == "resume":
        loaded = agent.load_state()
        summary = agent.build_resume_summary() if loaded else None
        flag["value"] = True
        if summary:
            _broadcast_chat(app, "system", summary)
        return web.json_response({"choice": "resume", "summary": summary})

    # Fresh path.
    backup = agent.archive_session()
    flag["value"] = True
    if backup is not None:
        msg = f"Starting fresh — prior session archived to {backup.name}."
        _broadcast_chat(app, "system", msg)
    return web.json_response({"choice": "fresh", "backup": str(backup) if backup else None})


async def _api_session_transcript(request: web.Request) -> web.Response:
    """Return the last N persisted messages so the UI can render a tail."""
    agent: CantripAgent = request.app[AGENT_KEY]
    try:
        limit = int(request.query.get("limit", "20"))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 200))
    messages = agent.transcript_tail(limit=limit)
    return web.json_response(
        {"messages": [{"role": msg.role.value, "content": msg.content} for msg in messages]}
    )


async def _api_update_status(request: web.Request) -> web.Response:
    """Return the PyPI update verdict for this server process.

    Shape mirrors the WebSocket ``update_available`` event so the
    frontend can reuse a single ``_renderUpdateBanner`` helper.
    ``info=null`` means either "we're on the latest release" or "the
    background check hasn't settled yet" — the browser shouldn't care,
    because the WebSocket event fires the moment a verdict arrives.
    """
    state = request.app[UPDATE_STATE_KEY]
    info = state.get("info")
    return web.json_response({"info": _update_info_payload(info)})


def _update_info_payload(info: object) -> dict[str, object] | None:
    """Serialise an :class:`update.UpdateInfo` for the wire.

    Returns ``None`` when *info* isn't an ``UpdateInfo`` (notably when
    we're on the latest release and the worker stored ``None``).  The
    payload includes the installer-aware upgrade command so the
    frontend doesn't have to replicate the mapping.
    """
    if not isinstance(info, update.UpdateInfo):
        return None
    method = update.detect_install_method()
    command = update.upgrade_command(method)
    return {
        "current": info.current,
        "latest": info.latest,
        "pypi_url": info.pypi_url,
        "release_timestamp": info.release_timestamp,
        "release_notes_markdown": info.release_notes_markdown,
        "installed_yanked": info.installed_yanked,
        "install_method": method.value,
        "upgrade_command": command,
    }


async def _api_juju_status(request: web.Request) -> web.Response:
    """Return Juju model status as JSON for the status panel."""
    agent: CantripAgent = request.app[AGENT_KEY]
    dev_model = agent.state.dev_model
    if not dev_model:
        return web.json_response({"apps": {}, "relations": []})

    try:
        import functools

        import jubilant

        juju = jubilant.Juju(model=dev_model)
        status = await asyncio.to_thread(functools.partial(juju.status))
    except (jubilant.CLIError, OSError, TimeoutError) as exc:
        log.debug("Failed to fetch juju status: %s", exc)
        return web.json_response({"apps": {}, "relations": []})

    apps: dict[str, dict] = {}
    for app_name, app_status in status.apps.items():
        units: dict[str, dict] = {}
        for unit_name, unit_status in app_status.units.items():
            units[unit_name] = {
                "status": unit_status.workload_status.current,
                "message": unit_status.workload_status.message or "",
                "address": unit_status.address or "",
            }
        apps[app_name] = {
            "status": app_status.app_status.current,
            "message": app_status.app_status.message or "",
            "charm": app_status.charm or "",
            "units": units,
        }

    relations: list[dict] = []
    seen: set[str] = set()
    if hasattr(status, "relations"):
        for rel in status.relations:
            key = f"{rel.provider}:{rel.interface}:{rel.requirer}"
            if key not in seen:
                seen.add(key)
                relations.append(
                    {
                        "provider": str(getattr(rel, "provider", "")),
                        "requirer": str(getattr(rel, "requirer", "")),
                        "interface": str(getattr(rel, "interface", "")),
                    }
                )

    return web.json_response({"apps": apps, "relations": relations})


async def _api_logs(request: web.Request) -> web.Response:
    """Return recent juju debug-log output."""
    import shutil
    import subprocess

    agent: CantripAgent = request.app[AGENT_KEY]
    dev_model = agent.state.dev_model
    try:
        lines = int(request.query.get("lines", "100"))
    except ValueError:
        lines = 100
    lines = max(1, min(lines, _MAX_LOG_LINES))
    level = request.query.get("level", "WARNING").upper()
    if level not in _VALID_LOG_LEVELS:
        level = "WARNING"

    if not dev_model or not shutil.which("juju"):
        return web.json_response({"lines": [], "error": "No model or juju CLI"})

    try:
        cmd = [
            "juju",
            "debug-log",
            "--model",
            dev_model,
            "-n",
            str(lines),
            "--level",
            level,
            "--no-tail",
        ]
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=15
        )
        log_lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log_lines = []

    return web.json_response({"lines": log_lines})


async def _ws_logs_stream(request: web.Request) -> web.WebSocketResponse:
    """Stream live log lines via WebSocket using juju debug-log --tail."""
    from cantrip.juju.log_stream import juju_available, stream_lines

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    agent: CantripAgent = request.app[AGENT_KEY]
    dev_model = agent.state.dev_model
    level = request.query.get("level", "WARNING").upper()
    if level not in _VALID_LOG_LEVELS:
        level = "WARNING"

    if not dev_model or not juju_available():
        await ws.send_json({"error": "No model or juju CLI"})
        await ws.close()
        return ws

    try:
        async for line in stream_lines(
            dev_model,
            level=level,
            lines=50,
            max_lines=5000,
        ):
            if ws.closed:
                break
            await ws.send_json({"line": line})
    except (OSError, asyncio.CancelledError):
        pass
    finally:
        if not ws.closed:
            await ws.close()

    return ws


async def _process_chat_turn(app: web.Application, agent: CantripAgent, content: str) -> None:
    """Run one chat turn end-to-end, broadcasting progress and results.

    Extracted from the WebSocket handler so it can run as a background
    task.  Keeping it off the read loop is what lets ``cancel_request``
    arrive while a turn is in flight — the handler returns to
    ``ws.receive()`` immediately after dispatching, instead of blocking
    on ``agent.process_message``.
    """
    chat_lock = app[CHAT_LOCK_KEY]
    async with chat_lock:
        _broadcast(app, "thinking", {"active": True})

        turn_task = asyncio.create_task(agent.process_message(content))
        app[CURRENT_TURN_KEY]["task"] = turn_task
        try:
            response = await turn_task
            _broadcast(app, "thinking", {"active": False})
            _broadcast_chat(
                app,
                "assistant",
                response,
                reasoning=_trailing_reasoning(agent),
            )
            agent.save_state()
        except asyncio.CancelledError:
            _broadcast(app, "thinking", {"active": False})
            _broadcast_chat(app, "system", "Cancelled.")
        except (ProviderRateLimitError, ProviderOverloadedError) as e:
            _broadcast(app, "thinking", {"active": False})
            _broadcast_chat(
                app,
                "system",
                "Provider temporarily unavailable — please wait a moment and try again.",
            )
            log.warning("Provider rate limited: %s", e)
        except ProviderError as e:
            _broadcast(app, "thinking", {"active": False})
            _broadcast_chat(app, "system", f"Provider error: {e}")
        except (OSError, ValueError, RuntimeError) as e:
            _broadcast(app, "thinking", {"active": False})
            _broadcast_chat(app, "system", f"Error: {e}")
            log.exception("Error processing message")
        finally:
            app[CURRENT_TURN_KEY]["task"] = None


async def _websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle a WebSocket connection for real-time chat and updates."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app[WS_CLIENTS_KEY].add(ws)
    log.info("WebSocket client connected (%d total)", len(request.app[WS_CLIENTS_KEY]))

    agent: CantripAgent = request.app[AGENT_KEY]
    turn_tasks: set[asyncio.Task] = set()

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                if payload.get("type") == "cancel_request":
                    current = request.app[CURRENT_TURN_KEY].get("task")
                    if current is not None and not current.done():
                        current.cancel()
                    continue

                if payload.get("type") == "chat_input":
                    content = payload.get("data", {}).get("content", "").strip()
                    if not content:
                        continue

                    # Blind A/B arena picks resolve the pending session
                    # before the slash dispatcher sees the reply.
                    if agent.active_arena is not None:
                        reveal = agent.handle_arena_pick(content)
                        if reveal is not None:
                            _broadcast_chat(request.app, "system", reveal)
                            continue

                    # Memory slash commands run inline (no LLM), so handle
                    # them before grabbing the chat lock or showing the
                    # thinking indicator.  Echo the user's command first so
                    # the chat shows what they typed.
                    if _handle_shared_slash_command(request.app, agent, content):
                        continue

                    # Dispatch the turn as a background task so the read
                    # loop stays free to handle ``cancel_request``.  The
                    # chat lock inside ``_process_chat_turn`` still
                    # serialises concurrent turns from multiple clients.
                    task = asyncio.create_task(_process_chat_turn(request.app, agent, content))
                    turn_tasks.add(task)
                    task.add_done_callback(turn_tasks.discard)

            elif msg.type in (
                web.WSMsgType.ERROR,
                web.WSMsgType.CLOSE,
            ):
                break
    finally:
        request.app[WS_CLIENTS_KEY].discard(ws)
        log.info("WebSocket client disconnected (%d remaining)", len(request.app[WS_CLIENTS_KEY]))

    return ws


# ---------------------------------------------------------------------------
# Event bus bridge
# ---------------------------------------------------------------------------


def _make_bus_forwarder(app: web.Application) -> ui_events.Subscriber:
    """Return a wildcard subscriber that forwards bus events to WebSocket clients."""

    def _forward(event: ui_events.Event) -> None:
        _broadcast(app, event.type.value, event.payload)

    return _forward


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def _create_app(agent: CantripAgent, port: int) -> web.Application:
    """Build the aiohttp application."""
    app = web.Application()
    app[AGENT_KEY] = agent
    app[PORT_KEY] = port
    app[WS_CLIENTS_KEY] = weakref.WeakSet()
    app[CHAT_LOCK_KEY] = asyncio.Lock()
    app[CURRENT_TURN_KEY] = {"task": None}

    # Jinja2 environment for server-side rendering.
    app[JINJA_ENV_KEY] = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )

    # Phase 31.3: resume-prompt decision flag.  Shared across clients;
    # the first to decide flips it, subsequent page loads skip the banner.
    app[SESSION_DECIDED_KEY] = {"value": False}

    # Phase 63.4: self-update verdict.  Filled in by the startup
    # worker; served both as a GET and as a WebSocket event on arrival.
    app[UPDATE_STATE_KEY] = {"info": None}

    # Routes.
    app.router.add_get("/", _index)
    app.router.add_get("/api/state", _api_state)
    app.router.add_get("/api/messages", _api_messages)
    app.router.add_get("/api/session/preview", _api_session_preview)
    app.router.add_post("/api/session/decide", _api_session_decide)
    app.router.add_get("/api/session/transcript", _api_session_transcript)
    app.router.add_get("/api/juju-status", _api_juju_status)
    app.router.add_get("/api/update-status", _api_update_status)
    app.router.add_get("/api/logs", _api_logs)
    app.router.add_get("/api/logs-stream", _ws_logs_stream)
    app.router.add_get("/ws", _websocket_handler)
    app.router.add_static("/static", _STATIC_DIR, name="static")

    return app


# ---------------------------------------------------------------------------
# Preflight bridge
# ---------------------------------------------------------------------------


# Check names emitted by :class:`PreflightRunner` during ``prepare()``.
# The browser uses this list to render the pending rows before the first
# event arrives, so users see the full checklist rather than nothing.
_PREFLIGHT_CHECKS = ("concierge", "prepare", "juju", "controller", "cos")
_PREFLIGHT_LABELS = {
    "concierge": "Concierge",
    "prepare": "Environment",
    "juju": "Juju CLI",
    "controller": "Controller",
    "cos": "COS",
    # Phase-1-only check; emitted only when concierge is missing.
    "snap_install": "Snap install",
    # Phase-2-only check from bootstrap().
    "bootstrap": "Bootstrap",
}


def _broadcast_preflight_event(app: web.Application, event: PreflightEvent) -> None:
    """Forward a preflight callback event as a WebSocket message."""
    _broadcast(
        app,
        "preflight_updated",
        {
            "check_name": event.check_name,
            "label": _PREFLIGHT_LABELS.get(event.check_name, event.check_name),
            "status": event.status.value,
            "message": event.message,
            "detail": event.detail,
        },
    )


async def _run_preflight(app: web.Application, agent: CantripAgent) -> None:
    """Run environment preflight once at web startup and broadcast progress.

    Mirrors the TUI's eager ``_start_prepare`` path so ``--web`` users get
    the same environment preparation and the same visibility into it.
    Failures are swallowed — preflight reports them through the checklist;
    exceptions also land on the status as ``failed``.
    """
    loop = asyncio.get_running_loop()

    def _callback(event: PreflightEvent) -> None:
        # Preflight runs on the loop already, but ``_broadcast`` schedules
        # futures — doing that from a thread would crash.  The callback
        # is always invoked from the preflight coroutine itself, so we're
        # on the loop; ``call_soon_threadsafe`` guards against any future
        # refactor that moves the callback to a worker thread.
        loop.call_soon_threadsafe(_broadcast_preflight_event, app, event)

    _broadcast(app, "preflight_started", {"checks": list(_PREFLIGHT_CHECKS)})
    try:
        await agent.prepare(preset=DEFAULT_PRESET, callback=_callback)
    except (OSError, RuntimeError, ValueError) as exc:
        log.warning("Preflight failed: %s", exc)
        _broadcast(
            app,
            "preflight_failed",
            {"error": str(exc)},
        )
    finally:
        _broadcast(app, "preflight_complete", {})


async def _run_update_check(app: web.Application) -> None:
    """Background worker — populate ``UPDATE_STATE_KEY`` and broadcast.

    A ``None`` verdict means the user is already on the latest release
    (or opted out); we still fire the WebSocket event so reconnecting
    clients see a definitive answer instead of assuming the check is
    still pending.  The check honours the shared disk cache, so a TUI
    launched minutes earlier doesn't cost this path an extra HTTP
    round-trip.
    """
    try:
        info = await update.check_for_update()
    except (OSError, RuntimeError, ValueError):
        info = None
    app[UPDATE_STATE_KEY]["info"] = info
    _broadcast(app, "update_available", {"info": _update_info_payload(info)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_web_async(agent: CantripAgent, port: int) -> None:
    """Start the web server and agent executor."""
    app = _create_app(agent, port)

    # Phase 31.3: defer load_state to the browser's resume-prompt
    # decision.  If no prior session exists, pre-mark as decided so the
    # banner is never shown and first-run users don't see it.
    preview = agent.preview_session()
    if not preview.exists:
        app[SESSION_DECIDED_KEY]["value"] = True

    # Forward all bus events to WebSocket clients.
    agent.event_bus.bind_loop(asyncio.get_running_loop())
    agent.event_bus.subscribe(None, _make_bus_forwarder(app))

    # Start the executor so autonomous tasks run.
    agent.start_executor()

    # Phase 63.4: kick off the PyPI self-update check in the
    # background.  Clients pick up the verdict via GET
    # ``/api/update-status`` on load and via the ``update_available``
    # WebSocket event on completion.
    asyncio.create_task(_run_update_check(app))

    # Phase 31.13: run environment preflight so the browser gets the
    # same eager-prepare visibility the TUI has.  Events flow out over
    # the WebSocket as ``preflight_updated`` messages.
    asyncio.create_task(_run_preflight(app, agent))

    # Connect any configured MCP servers in the background.  Failures
    # land in the registry's per-server status; ``/mcp`` shows them.
    if agent.mcp_registry.configured:
        asyncio.create_task(agent.start_mcp())

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    print(f"Cantrip Web UI running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.\n")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await agent.stop_executor()
        await agent.stop_mcp()
        await runner.cleanup()


def run_web(args: argparse.Namespace) -> int:
    """Run Cantrip in web UI mode."""
    try:
        snap_name = getattr(args, "snap", "gemma3")
        light_snap_name = getattr(args, "light_snap", None)
        base_url = getattr(args, "base_url", None)
        provider = create_provider(
            args.provider, args.model, snap_name=snap_name, base_url=base_url
        )
    except (ValueError, ProviderError) as e:
        print(f"Error: {e}")
        return 1

    # Resolve light provider using the shared helper.
    light_provider, _light_model_name = resolve_light_provider(
        provider,
        args.provider,
        light_provider_name=getattr(args, "light_provider", None),
        light_model_override=args.light_model,
        snap_name=snap_name,
        light_snap_name=light_snap_name,
    )

    agent = CantripAgent(
        provider=provider,
        charm_path=args.path,
        light_provider=light_provider,
    )

    # Phase 55.3: stamp the per-goal budget from CLI flags + env vars.
    from cantrip.agent.goal_budget import from_cli_args

    agent.state.goal_budget = from_cli_args(
        max_iterations=getattr(args, "max_iterations", None),
        max_tokens=getattr(args, "max_tokens", None),
    )

    # Phase 68.1: opt out of per-turn working-tree snapshots.
    from cantrip.agent.snapshots import snapshots_enabled

    agent.state.snapshot_enabled = snapshots_enabled(
        no_snapshots_flag=bool(getattr(args, "no_snapshots", False)),
    )

    port = getattr(args, "web_port", _DEFAULT_PORT)

    try:
        asyncio.run(_run_web_async(agent, port))
    except KeyboardInterrupt:
        print("\nShutting down.")

    return 0
