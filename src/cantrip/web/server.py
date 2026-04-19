"""Web UI server — aiohttp app with WebSocket for real-time updates."""

import argparse
import asyncio
import contextlib
import json
import logging
import pathlib
import weakref

import aiohttp.web as web
import jinja2

from cantrip.agent import slash_commands
from cantrip.agent.core import CantripAgent
from cantrip.llm import create_provider, resolve_light_provider
from cantrip.llm.base import ProviderError, ProviderOverloadedError, ProviderRateLimitError
from cantrip.ui import events as ui_events

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
    _broadcast(app, "chat_message", {"role": "user", "content": content})
    _broadcast(app, "chat_message", {"role": "system", "content": result.text})
    if result.followup is not None:
        asyncio.create_task(_broadcast_followup(app, result.followup))
    return True


async def _broadcast_followup(app: web.Application, followup) -> None:
    """Await a dispatcher follow-up coroutine and broadcast its result."""
    try:
        output = await followup
    except Exception as exc:  # noqa: BLE001 - background task; surface any error
        output = f"_Error: marketplace lookup failed: {exc}_"
    _broadcast(app, "chat_message", {"role": "system", "content": output})


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
    """Return conversation history as JSON for page reload."""
    agent: CantripAgent = request.app[AGENT_KEY]

    messages = [
        {"role": msg.role.value, "content": msg.content}
        for msg in agent.state.messages
        if msg.content
    ]

    return web.json_response({"messages": messages})


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


async def _websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle a WebSocket connection for real-time chat and updates."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app[WS_CLIENTS_KEY].add(ws)
    log.info("WebSocket client connected (%d total)", len(request.app[WS_CLIENTS_KEY]))

    agent: CantripAgent = request.app[AGENT_KEY]

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                if payload.get("type") == "chat_input":
                    content = payload.get("data", {}).get("content", "").strip()
                    if not content:
                        continue

                    # Memory slash commands run inline (no LLM), so handle
                    # them before grabbing the chat lock or showing the
                    # thinking indicator.  Echo the user's command first so
                    # the chat shows what they typed.
                    if _handle_shared_slash_command(request.app, agent, content):
                        continue

                    # Serialise chat messages to prevent concurrent state mutation.
                    chat_lock = request.app[CHAT_LOCK_KEY]
                    async with chat_lock:
                        _broadcast(request.app, "thinking", {"active": True})

                        try:
                            response = await agent.process_message(content)
                            _broadcast(request.app, "thinking", {"active": False})
                            _broadcast(
                                request.app,
                                "chat_message",
                                {
                                    "role": "assistant",
                                    "content": response,
                                },
                            )
                            # Persist state after each turn.
                            agent.save_state()
                        except (
                            ProviderRateLimitError,
                            ProviderOverloadedError,
                        ) as e:
                            _broadcast(request.app, "thinking", {"active": False})
                            _broadcast(
                                request.app,
                                "chat_message",
                                {
                                    "role": "system",
                                    "content": (
                                        "Provider temporarily unavailable — "
                                        "please wait a moment and try again."
                                    ),
                                },
                            )
                            log.warning("Provider rate limited: %s", e)
                        except ProviderError as e:
                            _broadcast(request.app, "thinking", {"active": False})
                            _broadcast(
                                request.app,
                                "chat_message",
                                {
                                    "role": "system",
                                    "content": f"Provider error: {e}",
                                },
                            )
                        except (OSError, ValueError, RuntimeError) as e:
                            _broadcast(request.app, "thinking", {"active": False})
                            _broadcast(
                                request.app,
                                "chat_message",
                                {
                                    "role": "system",
                                    "content": f"Error: {e}",
                                },
                            )
                            log.exception("Error processing message")

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

    # Jinja2 environment for server-side rendering.
    app[JINJA_ENV_KEY] = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )

    # Routes.
    app.router.add_get("/", _index)
    app.router.add_get("/api/state", _api_state)
    app.router.add_get("/api/messages", _api_messages)
    app.router.add_get("/api/juju-status", _api_juju_status)
    app.router.add_get("/api/logs", _api_logs)
    app.router.add_get("/api/logs-stream", _ws_logs_stream)
    app.router.add_get("/ws", _websocket_handler)
    app.router.add_static("/static", _STATIC_DIR, name="static")

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_web_async(agent: CantripAgent, port: int) -> None:
    """Start the web server and agent executor."""
    app = _create_app(agent, port)

    # Load prior session state if available.
    if agent.load_state():
        summary = agent.build_resume_summary()
        if summary:
            log.info("Resumed session: %s", summary[:200])

    # Forward all bus events to WebSocket clients.
    agent.event_bus.bind_loop(asyncio.get_running_loop())
    agent.event_bus.subscribe(None, _make_bus_forwarder(app))

    # Start the executor so autonomous tasks run.
    agent.start_executor()

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
        provider = create_provider(args.provider, args.model, snap_name=snap_name)
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

    port = getattr(args, "web_port", _DEFAULT_PORT)

    try:
        asyncio.run(_run_web_async(agent, port))
    except KeyboardInterrupt:
        print("\nShutting down.")

    return 0
