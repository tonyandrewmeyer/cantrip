"""Web UI server — aiohttp app with WebSocket for real-time updates."""

import argparse
import asyncio
import json
import logging
import pathlib
import weakref

import aiohttp.web as web
import jinja2

from cantrip.agent.core import CantripAgent
from cantrip.agent.queue import AgentTask
from cantrip.llm import create_provider, resolve_light_model
from cantrip.llm.base import ProviderError

log = logging.getLogger(__name__)

_DEFAULT_PORT = 8471
_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"
_STATIC_DIR = pathlib.Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------

def _broadcast(app: web.Application, event_type: str, data: dict) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    payload = json.dumps({"type": event_type, "data": data})
    clients: weakref.WeakSet = app["ws_clients"]
    stale: list[web.WebSocketResponse] = []
    for ws in clients:
        if ws.closed:
            stale.append(ws)
            continue
        asyncio.ensure_future(ws.send_str(payload))
    for ws in stale:
        clients.discard(ws)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def _index(request: web.Request) -> web.Response:
    """Serve the main page with initial state baked in."""
    env: jinja2.Environment = request.app["jinja_env"]
    agent: CantripAgent = request.app["agent"]
    template = env.get_template("index.html.j2")

    tasks = []
    if agent._work_queue:
        tasks = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "category": t.category.value,
            }
            for t in agent._work_queue.all_tasks()
        ]

    html = template.render(
        charm_name=agent.state.charm_name or "",
        tasks=tasks,
        port=request.app["port"],
    )
    return web.Response(text=html, content_type="text/html")


async def _api_state(request: web.Request) -> web.Response:
    """Return current tasks and messages as JSON."""
    agent: CantripAgent = request.app["agent"]

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
            }
            for t in agent._work_queue.all_tasks()
        ]

    return web.json_response({
        "charm_name": agent.state.charm_name or "",
        "tasks": tasks,
    })


async def _api_juju_status(request: web.Request) -> web.Response:
    """Return Juju model status as JSON for the status panel."""
    agent: CantripAgent = request.app["agent"]
    dev_model = agent.state.dev_model
    if not dev_model:
        return web.json_response({"apps": {}, "relations": []})

    try:
        import jubilant

        juju = jubilant.Juju(model=dev_model)
        status = juju.status()
    except Exception:
        log.debug("Failed to fetch juju status", exc_info=True)
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
                relations.append({
                    "provider": str(getattr(rel, "provider", "")),
                    "requirer": str(getattr(rel, "requirer", "")),
                    "interface": str(getattr(rel, "interface", "")),
                })

    return web.json_response({"apps": apps, "relations": relations})


async def _api_logs(request: web.Request) -> web.Response:
    """Return recent juju debug-log output."""
    import shutil
    import subprocess

    agent: CantripAgent = request.app["agent"]
    dev_model = agent.state.dev_model
    lines = int(request.query.get("lines", "100"))
    level = request.query.get("level", "WARNING")

    if not dev_model or not shutil.which("juju"):
        return web.json_response({"lines": [], "error": "No model or juju CLI"})

    try:
        result = subprocess.run(
            ["juju", "debug-log", "--model", dev_model, "-n", str(lines),
             "--level", level, "--no-tail"],
            capture_output=True, text=True, timeout=15,
        )
        log_lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log_lines = []

    return web.json_response({"lines": log_lines})


async def _websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle a WebSocket connection for real-time chat and updates."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app["ws_clients"].add(ws)
    log.info("WebSocket client connected (%d total)", len(request.app["ws_clients"]))

    agent: CantripAgent = request.app["agent"]

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

                    # Broadcast thinking state.
                    _broadcast(request.app, "thinking", {"active": True})

                    try:
                        response = await agent.process_message(content)
                        _broadcast(request.app, "thinking", {"active": False})
                        _broadcast(request.app, "chat_message", {
                            "role": "assistant",
                            "content": response,
                        })
                    except ProviderError as e:
                        _broadcast(request.app, "thinking", {"active": False})
                        _broadcast(request.app, "chat_message", {
                            "role": "system",
                            "content": f"Provider error: {e}",
                        })
                    except Exception as e:
                        _broadcast(request.app, "thinking", {"active": False})
                        _broadcast(request.app, "chat_message", {
                            "role": "system",
                            "content": f"Error: {e}",
                        })
                        log.exception("Error processing message")

            elif msg.type in (
                web.WSMsgType.ERROR,
                web.WSMsgType.CLOSE,
            ):
                break
    finally:
        request.app["ws_clients"].discard(ws)
        log.info("WebSocket client disconnected (%d remaining)", len(request.app["ws_clients"]))

    return ws


# ---------------------------------------------------------------------------
# Task change callback
# ---------------------------------------------------------------------------

def _make_task_callback(app: web.Application):
    """Create a callback that broadcasts task changes to WebSocket clients."""
    def _on_task_changed(task: AgentTask) -> None:
        _broadcast(app, "task_updated", {
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "category": task.category.value,
            "description": task.description,
            "result": task.result,
        })
    return _on_task_changed


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def _create_app(agent: CantripAgent, port: int) -> web.Application:
    """Build the aiohttp application."""
    app = web.Application()
    app["agent"] = agent
    app["port"] = port
    app["ws_clients"] = weakref.WeakSet()

    # Jinja2 environment for server-side rendering.
    app["jinja_env"] = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )

    # Routes.
    app.router.add_get("/", _index)
    app.router.add_get("/api/state", _api_state)
    app.router.add_get("/api/juju-status", _api_juju_status)
    app.router.add_get("/api/logs", _api_logs)
    app.router.add_get("/ws", _websocket_handler)
    app.router.add_static("/static", _STATIC_DIR, name="static")

    # Wire task callbacks.
    callback = _make_task_callback(app)
    agent._work_queue.set_callback(callback)

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run_web_async(agent: CantripAgent, port: int) -> None:
    """Start the web server and agent executor."""
    app = _create_app(agent, port)

    # Start the executor so autonomous tasks run.
    agent.start_executor(
        on_task_changed=_make_task_callback(app),
    )

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

    # Resolve light provider.
    light_provider = None
    light_provider_name = getattr(args, "light_provider", None)
    if light_provider_name:
        light_snap = light_snap_name or snap_name
        light_provider = create_provider(
            light_provider_name, args.light_model, snap_name=light_snap,
        )
    elif light_snap_name and args.provider == "inference-snap":
        light_provider = create_provider("inference-snap", snap_name=light_snap_name)
    else:
        main_model = provider.model_name
        resolved = args.light_model or resolve_light_model(args.provider, main_model)
        if resolved != main_model:
            light_provider = create_provider(args.provider, resolved, snap_name=snap_name)

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
