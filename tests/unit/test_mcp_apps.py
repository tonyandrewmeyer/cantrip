"""MCP Apps — Phase 73.2.

Covers the four spec invariants the phase calls out:

* ``ui`` content blocks are extracted at the MCP-client boundary.
* The web-UI iframe shape carries the spec-mandated sandbox attrs and
  no ``allow-same-origin``.
* The postMessage → permission gate → tool dispatch → audit round-trip
  works for ALLOW, DENY, and ASK outcomes.
* The TUI fallback renders the spec marker plus any text fallback the
  server attached.
"""

from __future__ import annotations

import asyncio
import pathlib
from typing import Any

import pytest

from cantrip.agent.audit import AUDIT_FILENAME, AuditAction, AuditWriter, read_entries
from cantrip.agent.controllers.mcp_controller import MCPController
from cantrip.agent.safety.permissions import (
    PermissionDecision,
    PermissionManager,
    PermissionOutcome,
)
from cantrip.agent.state import AgentState
from cantrip.agent.tools.base import ToolResult
from cantrip.agent.tools.mcp_tool import MCPTool
from cantrip.mcp import MCPToolInfo
from cantrip.mcp.client import _content_to_structured, _extract_app_render
from cantrip.mcp.types import MCPAppRender, MCPCallResult
from cantrip.ui import events as ui_events
from tests.support.mcp_fakes import (
    FakeMetaResourceBlock,
    FakeTextBlock,
    FakeUIBlock,
)

# ---------------------------------------------------------------------------
# Client-side extraction.
# ---------------------------------------------------------------------------


class TestContentToStructured:
    def test_pure_text_content_has_no_app_renders(self) -> None:
        result = _content_to_structured(
            [FakeTextBlock("hello"), FakeTextBlock("world")],
            server_name="srv",
        )
        assert isinstance(result, MCPCallResult)
        assert result.text == "hello\nworld"
        assert result.app_renders == ()

    def test_ui_block_extracted_and_placeholder_kept(self) -> None:
        result = _content_to_structured(
            [
                FakeTextBlock("see the form below"),
                FakeUIBlock(
                    html="<button>Click</button>",
                    title="Pebble Editor",
                    meta={"fallback": "Open in the web UI to edit the layer"},
                ),
            ],
            server_name="pebble",
        )
        assert len(result.app_renders) == 1
        render = result.app_renders[0]
        assert render.server_name == "pebble"
        assert render.title == "Pebble Editor"
        assert "<button>Click</button>" in render.html
        assert render.fallback_text == "Open in the web UI to edit the layer"
        # The placeholder lands in ``text`` so plain-text transcripts still
        # see that an app was rendered at this position.
        assert "Open in the web UI to edit the layer" in result.text

    def test_ui_block_without_html_is_ignored(self) -> None:
        result = _content_to_structured(
            [FakeUIBlock(html="")],
            server_name="srv",
        )
        assert result.app_renders == ()

    def test_meta_shape_b_is_recognised(self) -> None:
        block = FakeMetaResourceBlock(
            text="see the form",
            _meta={"app": {"html": "<p>hi</p>", "title": "Inspector"}},
        )
        result = _content_to_structured([block], server_name="srv")
        assert len(result.app_renders) == 1
        assert result.app_renders[0].title == "Inspector"
        assert result.app_renders[0].html == "<p>hi</p>"

    def test_non_html_mime_is_ignored(self) -> None:
        block = FakeUIBlock(html="<p>hi</p>", mimeType="application/svg+xml")
        assert _extract_app_render(block, server_name="srv") is None

    def test_max_height_clamped_to_int(self) -> None:
        block = FakeUIBlock(
            html="<p>hi</p>",
            meta={"max_height_px": 320},
        )
        render = _extract_app_render(block, server_name="srv")
        assert render is not None
        assert render.max_height_px == 320

    def test_negative_max_height_dropped(self) -> None:
        block = FakeUIBlock(html="<p>hi</p>", meta={"max_height_px": -10})
        render = _extract_app_render(block, server_name="srv")
        assert render is not None
        assert render.max_height_px is None


# ---------------------------------------------------------------------------
# MCPTool publishes a render event when it sees app renders.
# ---------------------------------------------------------------------------


class _StaticClient:
    """Stand-in for :class:`MCPClient` returning a pre-canned ``MCPCallResult``."""

    is_connected = True

    def __init__(self, result: MCPCallResult) -> None:
        self._result = result

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        del name, arguments
        return self._result


class _StaticRegistry:
    """Registry that always returns the same :class:`_StaticClient`."""

    def __init__(self, client: _StaticClient) -> None:
        self._client = client

    def get_client(self, name: str) -> _StaticClient:
        del name
        return self._client


def _make_controller(tmp_path: pathlib.Path) -> tuple[MCPController, list[ui_events.Event]]:
    bus = ui_events.EventBus()
    captured: list[ui_events.Event] = []
    bus.subscribe(None, captured.append)
    controller = MCPController(
        state=AgentState(charm_path=tmp_path),
        event_bus=bus,
        invalidate_tools_cache=lambda: None,
    )
    return controller, captured


class TestMCPToolPublishesRenderEvent:
    @pytest.mark.asyncio
    async def test_render_event_published_once_per_ui_block(self, tmp_path: pathlib.Path) -> None:
        controller, captured = _make_controller(tmp_path)
        render = MCPAppRender(
            server_name="pebble",
            title="Layer Editor",
            mime="text/html",
            html="<form></form>",
            fallback_text="(form)",
            max_height_px=200,
        )
        client = _StaticClient(MCPCallResult(text="(rendered)", app_renders=(render,)))
        info = MCPToolInfo(
            server_name="pebble",
            name="edit_layer",
            description="",
            input_schema={"type": "object"},
        )
        tool = MCPTool(info, _StaticRegistry(client), controller=controller)  # type: ignore[arg-type]

        result = await tool.execute()

        assert result.success
        assert "(rendered)" in result.output
        renders = [e for e in captured if e.type is ui_events.EventType.MCP_APP_RENDER]
        assert len(renders) == 1
        payload = renders[0].payload
        assert payload["server_name"] == "pebble"
        assert payload["title"] == "Layer Editor"
        assert payload["html"] == "<form></form>"
        assert payload["fallback_text"] == "(form)"
        assert payload["max_height_px"] == 200
        assert "app_ids" in result.data
        assert payload["app_id"] in result.data["app_ids"]

    @pytest.mark.asyncio
    async def test_no_event_when_no_ui_block(self, tmp_path: pathlib.Path) -> None:
        controller, captured = _make_controller(tmp_path)
        client = _StaticClient(MCPCallResult(text="plain", app_renders=()))
        info = MCPToolInfo(
            server_name="srv",
            name="t",
            description="",
            input_schema={"type": "object"},
        )
        tool = MCPTool(info, _StaticRegistry(client), controller=controller)  # type: ignore[arg-type]

        result = await tool.execute()

        assert result.success
        renders = [e for e in captured if e.type is ui_events.EventType.MCP_APP_RENDER]
        assert renders == []


# ---------------------------------------------------------------------------
# MCPController.handle_app_tool_call — permission gate + dispatch + audit.
# ---------------------------------------------------------------------------


def _register_static_app(
    controller: MCPController,
    server_name: str = "pebble",
    tool_name: str = "mcp__pebble__edit_layer",
) -> str:
    render = MCPAppRender(
        server_name=server_name,
        title="App",
        mime="text/html",
        html="<p>hi</p>",
    )
    return controller.register_app_render(render, tool_name=tool_name)


def _read_audit(tmp_path: pathlib.Path) -> list:
    return list(read_entries(tmp_path / AUDIT_FILENAME))


class TestHandleAppToolCall:
    @pytest.mark.asyncio
    async def test_allow_path_dispatches_and_audits(self, tmp_path: pathlib.Path) -> None:
        controller, captured = _make_controller(tmp_path)
        audit = AuditWriter(tmp_path / AUDIT_FILENAME)
        dispatched: list[tuple[str, dict[str, Any]]] = []

        async def _dispatch(name: str, arguments: dict[str, Any]) -> ToolResult:
            dispatched.append((name, arguments))
            return ToolResult(success=True, output="bar")

        controller.register_app_dispatcher(
            evaluate_permission=lambda *_: PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                reason="ok",
            ),
            dispatch_tool=_dispatch,
            audit_writer=audit,
        )
        app_id = _register_static_app(controller)

        await controller.handle_app_tool_call(
            app_id=app_id,
            request_id="req1",
            name="read_file",
            arguments={"path": "README.md"},
        )

        assert dispatched == [("read_file", {"path": "README.md"})]
        types_seen = [e.type for e in captured]
        # Render → pending → invoked → tool_result, in that order.
        assert ui_events.EventType.MCP_APP_RENDER in types_seen
        assert ui_events.EventType.TOOL_INVOKED_PENDING in types_seen
        assert ui_events.EventType.TOOL_INVOKED in types_seen
        invoked = next(e for e in captured if e.type is ui_events.EventType.TOOL_INVOKED)
        assert invoked.payload["success"] is True
        assert invoked.payload["source"] == "mcp-app"
        result_event = next(
            e for e in captured if e.type is ui_events.EventType.MCP_APP_TOOL_RESULT
        )
        assert result_event.payload["app_id"] == app_id
        assert result_event.payload["request_id"] == "req1"
        assert result_event.payload["success"] is True
        assert result_event.payload["output"] == "bar"

        entries = _read_audit(tmp_path)
        assert any(e.action is AuditAction.ALLOWED and e.tool == "read_file" for e in entries)

    @pytest.mark.asyncio
    async def test_deny_path_skips_dispatch_and_audits(self, tmp_path: pathlib.Path) -> None:
        controller, captured = _make_controller(tmp_path)
        audit = AuditWriter(tmp_path / AUDIT_FILENAME)
        dispatch_calls: list[str] = []

        async def _dispatch(name: str, arguments: dict[str, Any]) -> ToolResult:
            del arguments
            dispatch_calls.append(name)
            return ToolResult(success=True, output="should not run")

        controller.register_app_dispatcher(
            evaluate_permission=lambda *_: PermissionDecision(
                outcome=PermissionOutcome.DENY,
                reason="policy denies edit_file from mcp-app",
            ),
            dispatch_tool=_dispatch,
            audit_writer=audit,
        )
        app_id = _register_static_app(controller)

        await controller.handle_app_tool_call(
            app_id=app_id,
            request_id="req2",
            name="edit_file",
            arguments={"path": "secrets.yaml"},
        )

        assert dispatch_calls == []
        result_event = next(
            e for e in captured if e.type is ui_events.EventType.MCP_APP_TOOL_RESULT
        )
        assert result_event.payload["success"] is False
        assert "denies" in (result_event.payload["error"] or "")

        entries = _read_audit(tmp_path)
        assert any(e.action is AuditAction.DENIED for e in entries)

    @pytest.mark.asyncio
    async def test_ask_path_waits_for_user_approval(self, tmp_path: pathlib.Path) -> None:
        controller, captured = _make_controller(tmp_path)
        audit = AuditWriter(tmp_path / AUDIT_FILENAME)
        manager = PermissionManager(timeout_seconds=2.0)
        dispatched: list[str] = []

        async def _dispatch(name: str, arguments: dict[str, Any]) -> ToolResult:
            del arguments
            dispatched.append(name)
            return ToolResult(success=True, output="ok")

        controller.register_app_dispatcher(
            evaluate_permission=lambda *_: PermissionDecision(
                outcome=PermissionOutcome.ASK,
                reason="ask before write",
            ),
            dispatch_tool=_dispatch,
            permission_manager=manager,
            audit_writer=audit,
        )
        app_id = _register_static_app(controller)

        async def _approve() -> None:
            # Wait for the manager to park the ask, then approve it.
            for _ in range(200):
                if manager.pending:
                    break
                await asyncio.sleep(0.01)
            assert manager.pending, "ask was never parked"
            manager.resolve(manager.pending[0], approved=True)

        approver = asyncio.create_task(_approve())
        await controller.handle_app_tool_call(
            app_id=app_id,
            request_id="req3",
            name="write_file",
            arguments={"path": "out.yaml", "content": "x"},
        )
        await approver

        assert dispatched == ["write_file"]
        invoked = [e for e in captured if e.type is ui_events.EventType.TOOL_INVOKED]
        assert invoked and invoked[-1].payload["success"] is True
        entries = _read_audit(tmp_path)
        # ASK records as REVIEW_REQUESTED *and* the subsequent dispatch
        # outcome (ALLOWED) — both lines should land.
        actions = [e.action for e in entries]
        assert AuditAction.REVIEW_REQUESTED in actions
        assert AuditAction.ALLOWED in actions

    @pytest.mark.asyncio
    async def test_unknown_app_id_rejects_without_dispatch(self, tmp_path: pathlib.Path) -> None:
        controller, captured = _make_controller(tmp_path)
        audit = AuditWriter(tmp_path / AUDIT_FILENAME)
        dispatched: list[str] = []

        async def _dispatch(name: str, arguments: dict[str, Any]) -> ToolResult:
            del arguments
            dispatched.append(name)
            return ToolResult(success=True, output="")

        controller.register_app_dispatcher(
            evaluate_permission=lambda *_: PermissionDecision(
                outcome=PermissionOutcome.ALLOW,
                reason="ok",
            ),
            dispatch_tool=_dispatch,
            audit_writer=audit,
        )

        await controller.handle_app_tool_call(
            app_id="not-a-real-app",
            request_id="req4",
            name="read_file",
            arguments={"path": "/tmp/x"},
        )

        assert dispatched == []
        result_event = next(
            e for e in captured if e.type is ui_events.EventType.MCP_APP_TOOL_RESULT
        )
        assert result_event.payload["success"] is False
        assert "unknown MCP App id" in (result_event.payload["error"] or "")

        entries = _read_audit(tmp_path)
        assert any(e.action is AuditAction.DENIED for e in entries)


# ---------------------------------------------------------------------------
# TUI fallback wording.
# ---------------------------------------------------------------------------


class TestTuiFallbackText:
    """Plain-string assertions on the helper that builds the fallback body.

    Pulling the widget itself into a unit test would need a Textual
    event loop; the rendering is one ``add_system_message`` call so a
    string-shape check covers the spec invariant ("``[MCP App: <title>;
    open in web UI at <url>]`` plus the text-form of any fallback").
    """

    def test_marker_includes_title_and_web_url(self) -> None:
        from cantrip.tui.widgets.chat import ChatWidget

        sentinel: list[str] = []

        def _capture(content: str, *_args: object, **_kwargs: object) -> object:
            sentinel.append(content)
            return None

        widget = ChatWidget.__new__(ChatWidget)  # bypass Textual mount machinery
        widget.add_system_message = _capture  # type: ignore[method-assign]

        ChatWidget.add_mcp_app_fallback(
            widget,
            title="Pebble Editor",
            fallback_text="Open the web UI to edit the layer.",
            web_url="http://localhost:8471",
        )

        assert sentinel, "add_system_message was never called"
        body = sentinel[0]
        assert body.startswith("[MCP App: Pebble Editor; open in web UI at http://localhost:8471]")
        assert "Open the web UI to edit the layer." in body

    def test_marker_omits_web_url_when_unknown(self) -> None:
        from cantrip.tui.widgets.chat import ChatWidget

        sentinel: list[str] = []

        def _capture(content: str, *_args: object, **_kwargs: object) -> object:
            sentinel.append(content)
            return None

        widget = ChatWidget.__new__(ChatWidget)
        widget.add_system_message = _capture  # type: ignore[method-assign]

        ChatWidget.add_mcp_app_fallback(
            widget,
            title="Inspector",
            fallback_text="",
            web_url=None,
        )

        assert sentinel[0] == "[MCP App: Inspector]"


# ---------------------------------------------------------------------------
# Web-UI iframe shape — the spec mandates ``sandbox="allow-scripts
# allow-forms"`` with *no* ``allow-same-origin``.  We assert the literal
# string against the shipped JS so a regression would flip the test red.
# ---------------------------------------------------------------------------


class TestWebUIIframeShape:
    def test_sandbox_attrs_are_spec_compliant(self) -> None:
        import re

        js_path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "src"
            / "cantrip"
            / "web"
            / "static"
            / "cantrip.js"
        )
        contents = js_path.read_text(encoding="utf-8")
        # The literal sandbox attribute the dispatcher attaches.
        assert 'iframe.setAttribute("sandbox", "allow-scripts allow-forms")' in contents
        # And explicitly *no* ``allow-same-origin`` slips into any
        # ``setAttribute("sandbox", ...)`` call.  Comments mentioning
        # the token are fine (they exist precisely to remind readers
        # *not* to add it); a real attribute value would be the bug.
        sandbox_calls = re.findall(r'setAttribute\("sandbox",\s*"([^"]*)"\)', contents)
        for value in sandbox_calls:
            assert "allow-same-origin" not in value, (
                f"sandbox attribute carries allow-same-origin: {value!r}"
            )
