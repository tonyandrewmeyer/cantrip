"""Tests for the web UI server."""

import asyncio
import types
import weakref
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp.web as web
import jinja2
from aiohttp.test_utils import TestClient, TestServer

from cantrip.web.server import (
    _MAX_LOG_LINES,
    _STATIC_DIR,
    _TEMPLATE_DIR,
    _VALID_LOG_LEVELS,
    AGENT_KEY,
    CHAT_LOCK_KEY,
    CURRENT_TURN_KEY,
    JINJA_ENV_KEY,
    PORT_KEY,
    WS_CLIENTS_KEY,
    _broadcast,
)


def _render_template() -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    return env.get_template("index.html.j2").render(charm_name="", tasks=[], port=8471)


class _StubWs:
    """Minimal stand-in for a ``WebSocketResponse`` that accepts weakrefs."""

    __slots__ = ("closed", "__weakref__")

    def __init__(self, *, closed: bool = False) -> None:
        self.closed = closed


def _build_ws_app(agent: MagicMock) -> web.Application:
    """Build a minimal ``web.Application`` wired for the websocket tests.

    Registers the real ``_websocket_handler`` and ``_index`` route plus the
    keys the handler looks up (``AGENT_KEY``, ``WS_CLIENTS_KEY``,
    ``chat_lock``, ``jinja_env`` and ``port``).  Mirrors what
    ``_create_app`` builds, minus the routes we don't drive.
    """
    from cantrip.web import server

    app = web.Application()
    app[AGENT_KEY] = agent
    app[WS_CLIENTS_KEY] = weakref.WeakSet()
    app[CHAT_LOCK_KEY] = asyncio.Lock()
    app[CURRENT_TURN_KEY] = {"task": None}
    app[JINJA_ENV_KEY] = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    app[PORT_KEY] = 8471
    app.router.add_get("/ws", server._websocket_handler)
    return app


class TestWebServerBasics:
    """Tests for web server setup and configuration."""

    def test_template_dir_exists(self) -> None:
        assert _TEMPLATE_DIR.is_dir()

    def test_static_dir_exists(self) -> None:
        assert _STATIC_DIR.is_dir()

    def test_template_file_exists(self) -> None:
        assert (_TEMPLATE_DIR / "index.html.j2").exists()

    def test_css_file_exists(self) -> None:
        assert (_STATIC_DIR / "style.css").exists()

    def test_js_file_exists(self) -> None:
        assert (_STATIC_DIR / "cantrip.js").exists()


class TestBroadcast:
    """Tests for the _broadcast function."""

    def test_broadcast_with_no_clients(self) -> None:
        """Broadcasting with no clients should not raise."""
        import weakref

        import aiohttp.web as web

        app = web.Application()
        app[WS_CLIENTS_KEY] = weakref.WeakSet()
        # Should not raise.
        _broadcast(app, "test_event", {"key": "value"})

    def test_broadcast_skips_non_serialisable_payload(self) -> None:
        """A non-JSON-serialisable payload is logged and dropped — not raised."""
        import weakref

        import aiohttp.web as web

        app = web.Application()
        app[WS_CLIENTS_KEY] = weakref.WeakSet()
        # ``object()`` has no JSON encoder; the broadcaster must not crash.
        _broadcast(app, "weird", {"obj": object()})


class TestBroadcastChat:
    """Tests for the ``_broadcast_chat`` helper (Phase 77)."""

    def test_payload_includes_reasoning_field_when_supplied(self) -> None:
        """``reasoning`` flows through to the websocket payload so the
        browser can render the collapsible ``<details>`` block.
        """
        from cantrip.web.server import _broadcast_chat

        app = web.Application()
        captured: list[tuple[str, dict]] = []
        with patch(
            "cantrip.web.server._broadcast",
            side_effect=lambda _a, t, d: captured.append((t, d)),
        ):
            _broadcast_chat(app, "assistant", "42", reasoning="I weighed the options.")

        assert len(captured) == 1
        event_type, payload = captured[0]
        assert event_type == "chat_message"
        assert payload["role"] == "assistant"
        assert payload["content"] == "42"
        assert payload["reasoning"] == "I weighed the options."

    def test_payload_defaults_reasoning_to_empty_string(self) -> None:
        from cantrip.web.server import _broadcast_chat

        app = web.Application()
        captured: list[tuple[str, dict]] = []
        with patch(
            "cantrip.web.server._broadcast",
            side_effect=lambda _a, t, d: captured.append((t, d)),
        ):
            _broadcast_chat(app, "system", "hello")

        assert captured[0][1]["reasoning"] == ""


class TestTrailingReasoning:
    """``_trailing_reasoning`` reads from the latest assistant turn."""

    def _agent_with_messages(self, messages):
        from cantrip.llm.base import Message, Role

        agent = MagicMock()
        agent.state = MagicMock()
        agent.state.messages = [
            Message(
                role=Role(role),
                content=content,
                metadata=metadata,
            )
            for role, content, metadata in messages
        ]
        return agent

    def test_returns_thinking_content_from_last_assistant(self) -> None:
        from cantrip.web.server import _trailing_reasoning

        agent = self._agent_with_messages(
            [
                ("user", "Hi", {}),
                ("assistant", "Hello", {"_thinking_content": "Polite greeting."}),
            ]
        )
        assert _trailing_reasoning(agent) == "Polite greeting."

    def test_empty_string_when_no_reasoning(self) -> None:
        from cantrip.web.server import _trailing_reasoning

        agent = self._agent_with_messages(
            [
                ("user", "Hi", {}),
                ("assistant", "Hello", {}),
            ]
        )
        assert _trailing_reasoning(agent) == ""

    def test_skips_non_assistant_messages(self) -> None:
        """A recent user message must not shadow the prior assistant's
        reasoning when walking backwards."""
        from cantrip.web.server import _trailing_reasoning

        agent = self._agent_with_messages(
            [
                ("assistant", "first", {"_thinking_content": "first reasoning"}),
                ("user", "follow-up", {}),
            ]
        )
        assert _trailing_reasoning(agent) == "first reasoning"


class TestPreflightBroadcast:
    """Tests for preflight-event forwarding over the WebSocket."""

    def test_broadcast_preflight_event_payload(self) -> None:
        """_broadcast_preflight_event maps PreflightEvent to WS payload."""
        import weakref

        import aiohttp.web as web

        from cantrip.agent.preflight import CheckStatus, PreflightEvent
        from cantrip.web.server import _broadcast_preflight_event

        app = web.Application()
        app[WS_CLIENTS_KEY] = weakref.WeakSet()

        captured: list[tuple[str, dict]] = []
        with patch(
            "cantrip.web.server._broadcast",
            side_effect=lambda _a, t, d: captured.append((t, d)),
        ):
            _broadcast_preflight_event(
                app,
                PreflightEvent(
                    check_name="controller",
                    status=CheckStatus.RUNNING,
                    message="Checking controller",
                ),
            )

        assert len(captured) == 1
        event_type, payload = captured[0]
        assert event_type == "preflight_updated"
        assert payload["check_name"] == "controller"
        assert payload["label"] == "Controller"
        assert payload["status"] == "running"
        assert payload["message"] == "Checking controller"

    def test_preflight_labels_cover_all_checks(self) -> None:
        """Every standard check name has a human-readable label."""
        from cantrip.web.server import _PREFLIGHT_CHECKS, _PREFLIGHT_LABELS

        for check in _PREFLIGHT_CHECKS:
            assert check in _PREFLIGHT_LABELS
            assert _PREFLIGHT_LABELS[check]


class TestTemplateRendering:
    """Tests for the Jinja2 template."""

    def test_renders_without_error(self) -> None:
        import jinja2

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("index.html.j2")
        html = template.render(charm_name="test-charm", tasks=[], port=8471)

        assert "<!DOCTYPE html>" in html
        assert "Cantrip" in html
        assert "test-charm" in html

    def test_renders_with_tasks(self) -> None:
        import jinja2

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("index.html.j2")
        tasks = [
            {"id": "t1", "title": "Build charm", "status": "done", "category": "build"},
            {"id": "t2", "title": "Deploy", "status": "active", "category": "deploy"},
        ]
        html = template.render(charm_name="my-charm", tasks=tasks, port=8471)

        assert "Build charm" in html
        assert "task-done" in html
        assert "task-active" in html

    def test_renders_empty_state(self) -> None:
        import jinja2

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("index.html.j2")
        html = template.render(charm_name="", tasks=[], port=8471)

        assert "No tasks yet" in html

    def test_template_includes_update_banner(self) -> None:
        """Phase 63.4: the update banner is in the DOM (hidden on first load)."""
        html = _render_template()
        assert 'id="update-banner"' in html
        # Hidden by default — filled in by _fetchUpdateStatus on page load.
        assert 'class="update-banner"' in html
        assert 'id="update-banner-dismiss"' in html

    def test_template_includes_cache_indicator(self) -> None:
        """Phase 78.2: header has a cache-hit indicator in the DOM, hidden until data arrives."""
        html = _render_template()
        assert 'id="cache-indicator"' in html
        assert 'class="cache-indicator"' in html
        # Screen-reader label + aria-live so the hit-rate update is
        # announced when it arrives.
        assert 'aria-live="polite"' in html


class TestJavaScript:
    """Tests for the client-side JavaScript."""

    def test_js_defines_cantrip_namespace(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "const cantrip" in js

    def test_js_has_connect_function(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "function connect" in js

    def test_js_has_websocket_reconnect(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "reconnectDelay" in js

    def test_js_has_message_dispatcher(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "chat_message" in js
        assert "task_updated" in js
        assert "thinking" in js

    def test_js_has_update_banner_plumbing(self) -> None:
        """Phase 63.4: self-update banner fetches, renders, and persists dismissal."""
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "_fetchUpdateStatus" in js
        assert "_renderUpdateBanner" in js
        assert "/api/update-status" in js
        assert "update_available" in js
        assert "UPDATE_DISMISS_KEY" in js
        assert "localStorage" in js

    def test_js_handles_cache_metrics_updated(self) -> None:
        """Phase 78.2: JS handles CACHE_METRICS_UPDATED and updates the indicator."""
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "cache_metrics_updated" in js
        assert "_updateCacheMetrics" in js
        assert "cache-indicator" in js
        # Matches the TUI modelbar wording for feature equivalence.
        assert "cache: " in js and "% hit" in js


class TestCSS:
    """Tests for the stylesheet."""

    def test_css_has_grid_layout(self) -> None:
        css = (_STATIC_DIR / "style.css").read_text()
        assert "grid-template-columns" in css

    def test_css_has_responsive_breakpoint(self) -> None:
        css = (_STATIC_DIR / "style.css").read_text()
        assert "@media" in css
        assert "700px" in css

    def test_css_has_task_status_classes(self) -> None:
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".task-done" in css
        assert ".task-active" in css
        assert ".task-failed" in css
        assert ".task-pending" in css
        assert ".task-blocked" in css

    def test_css_has_juju_status_styles(self) -> None:
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".juju-app" in css
        assert ".juju-app-name" in css
        assert ".status-active" in css

    def test_css_has_overlay_styles(self) -> None:
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".overlay" in css
        assert ".overlay-content" in css

    def test_css_has_markdown_styles(self) -> None:
        css = (_STATIC_DIR / "style.css").read_text()
        # ``.msg-body`` applies to user and assistant alike now that
        # both render Markdown.
        assert ".msg-body pre" in css
        assert ".msg-body code" in css
        assert ".msg-body table" in css

    def test_css_has_cache_indicator_styles(self) -> None:
        """Phase 78.2: the cache badge is styled with the monospace font stack."""
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".cache-indicator" in css
        assert "var(--font-mono)" in css

    def test_css_has_reasoning_styles(self) -> None:
        """Reasoning / chain-of-thought renders as a collapsible <details>."""
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".msg-reasoning" in css
        assert ".msg-reasoning > summary" in css
        assert ".msg-reasoning-body" in css


class TestJavaScriptFeatures:
    """Tests for the enhanced JavaScript features."""

    def test_js_appends_message_with_server_rendered_html(self) -> None:
        """Markdown renders server-side; the browser just injects the HTML."""
        js = (_STATIC_DIR / "cantrip.js").read_text()
        # The old regex renderer must be gone.
        assert "_renderMarkdown" not in js
        # ``appendMessage`` takes html + timestamp + reasoning and
        # ``innerHTML``s the HTML.
        assert "function appendMessage(role, content, html, timestamp, reasoning)" in js
        assert "body.innerHTML = html" in js

    def test_js_renders_reasoning_as_details_block(self) -> None:
        """When ``reasoning`` is present, the browser builds a collapsible
        ``<details>`` block.  The body is text-content (not innerHTML) so
        a reasoning string containing angle brackets can't become a
        DOM-injection vector.
        """
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert 'createElement("details")' in js
        assert "msg-reasoning" in js
        assert "💭 thinking" in js

    def test_js_has_juju_status_fetch(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "_fetchJujuStatus" in js
        assert "juju-status" in js

    def test_js_has_keyboard_shortcuts(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "_handleKeyDown" in js
        assert "Escape" in js

    def test_js_has_overlays(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "toggleHelp" in js
        assert "toggleLogs" in js
        assert "toggleGraph" in js

    def test_js_has_logs_fetch(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "_fetchLogs" in js
        assert "/api/logs" in js


class TestTemplateFeatures:
    """Tests for the enhanced template features."""

    def test_template_has_juju_panel(self) -> None:
        import jinja2

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("index.html.j2")
        html = template.render(charm_name="", tasks=[], port=8471)
        assert "juju-panel" in html
        assert "Juju Status" in html

    def test_template_has_help_overlay(self) -> None:
        import jinja2

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("index.html.j2")
        html = template.render(charm_name="", tasks=[], port=8471)
        assert "help-overlay" in html
        assert "Keyboard Shortcuts" in html

    def test_template_has_logs_overlay(self) -> None:
        import jinja2

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("index.html.j2")
        html = template.render(charm_name="", tasks=[], port=8471)
        assert "logs-overlay" in html
        assert "Juju Logs" in html

    def test_template_has_graph_overlay(self) -> None:
        import jinja2

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("index.html.j2")
        html = template.render(charm_name="", tasks=[], port=8471)
        assert "graph-overlay" in html
        assert "Integration Graph" in html


class TestGraphView:
    """Tests for the integration graph view."""

    def test_js_has_graph_toggle(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "toggleGraph" in js

    def test_js_has_graph_renderer(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "_renderGraph" in js
        assert "_fetchGraph" in js

    def test_js_has_graph_keyboard_shortcut(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        # The G key triggers toggleGraph.
        assert '"g"' in js or "'g'" in js

    def test_css_has_graph_styles(self) -> None:
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".graph-view" in css
        assert ".graph-app" in css
        assert ".graph-relations" in css
        assert ".graph-relation" in css


class TestLogInputValidation:
    """Tests for /api/logs and /api/logs-stream input validation."""

    def test_valid_log_levels_contains_standard_levels(self) -> None:
        assert {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} == _VALID_LOG_LEVELS

    def test_max_log_lines_is_reasonable(self) -> None:
        assert _MAX_LOG_LINES == 5000

    def test_valid_log_levels_is_frozen(self) -> None:
        assert isinstance(_VALID_LOG_LEVELS, frozenset)

    def test_api_logs_clamps_lines_parameter(self) -> None:
        """Verify lines is clamped within [1, _MAX_LOG_LINES]."""
        import asyncio
        import types
        from unittest.mock import MagicMock, patch

        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        from cantrip.web import server

        agent = MagicMock()
        agent.state.dev_model = "test-model"

        app = web.Application()
        app[AGENT_KEY] = agent
        app.router.add_get("/api/logs", server._api_logs)

        fake_result = types.SimpleNamespace(stdout="line1\nline2\n", returncode=0)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                # Negative lines should be clamped to 1.
                with (
                    patch("shutil.which", return_value="/usr/bin/juju"),
                    patch("subprocess.run", return_value=fake_result) as mock_run,
                ):
                    resp = await client.get("/api/logs?lines=-50")
                    assert resp.status == 200
                    cmd = mock_run.call_args[0][0]
                    assert cmd[cmd.index("--limit") + 1] == "1"

                # Excessively large lines should be clamped to _MAX_LOG_LINES.
                with (
                    patch("shutil.which", return_value="/usr/bin/juju"),
                    patch("subprocess.run", return_value=fake_result) as mock_run,
                ):
                    resp = await client.get("/api/logs?lines=999999")
                    assert resp.status == 200
                    cmd = mock_run.call_args[0][0]
                    assert cmd[cmd.index("--limit") + 1] == str(_MAX_LOG_LINES)

        asyncio.run(_run())

    def test_api_logs_rejects_invalid_level(self) -> None:
        """Verify invalid level falls back to WARNING."""
        import asyncio
        import types
        from unittest.mock import MagicMock, patch

        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        from cantrip.web import server

        agent = MagicMock()
        agent.state.dev_model = "test-model"

        app = web.Application()
        app[AGENT_KEY] = agent
        app.router.add_get("/api/logs", server._api_logs)

        fake_result = types.SimpleNamespace(stdout="", returncode=0)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                # Malicious level should fall back to WARNING.
                with (
                    patch("shutil.which", return_value="/usr/bin/juju"),
                    patch("subprocess.run", return_value=fake_result) as mock_run,
                ):
                    resp = await client.get("/api/logs?level=; rm -rf /")
                    assert resp.status == 200
                    cmd = mock_run.call_args[0][0]
                    assert cmd[cmd.index("--level") + 1] == "WARNING"

                # Valid level (case-insensitive) should be accepted.
                with (
                    patch("shutil.which", return_value="/usr/bin/juju"),
                    patch("subprocess.run", return_value=fake_result) as mock_run,
                ):
                    resp = await client.get("/api/logs?level=error")
                    assert resp.status == 200
                    cmd = mock_run.call_args[0][0]
                    assert cmd[cmd.index("--level") + 1] == "ERROR"

        asyncio.run(_run())


class TestAccessibility:
    """Invariants captured from the WCAG 2.1 AA audit (Phase 60).

    These guard the remediations from ``design/WEB_UI_ACCESSIBILITY_AUDIT.md``
    against silent regressions.  Each assertion corresponds to a numbered
    finding in that audit.
    """

    def test_chat_input_has_programmatic_label(self) -> None:
        # Finding 3: visible <label for="chat-input"> is preferred.
        html = _render_template()
        assert 'for="chat-input"' in html

    def test_send_button_uses_strong_accent_background(self) -> None:
        # Finding 2: Send button must not sit on the low-contrast --accent.
        css = (_STATIC_DIR / "style.css").read_text()
        assert "--accent-strong" in css
        # The Send button background should reference the strong accent.
        block = css.split("#chat-form button")[1].split("}")[0]
        assert "var(--accent-strong)" in block

    def test_send_button_has_focus_visible_rule(self) -> None:
        # Finding 1: keyboard users need a visible focus indicator.
        css = (_STATIC_DIR / "style.css").read_text()
        assert "#chat-form button:focus-visible" in css

    def test_global_focus_visible_rule_present(self) -> None:
        css = (_STATIC_DIR / "style.css").read_text()
        assert ":focus-visible" in css

    def test_chat_messages_is_live_region(self) -> None:
        # Finding 4: assistant replies must be announced.
        html = _render_template()
        assert 'id="chat-messages"' in html
        assert 'role="log"' in html
        assert 'aria-live="polite"' in html
        assert 'aria-relevant="additions"' in html

    def test_thinking_indicator_is_status_region(self) -> None:
        # Finding 4: thinking indicator stays in the DOM via `hidden`, not
        # display:none, so role=status can announce the state change.
        html = _render_template()
        indicator = html.split('id="thinking-indicator"')[1].split(">")[0]
        assert 'role="status"' in indicator
        assert 'aria-live="polite"' in indicator
        assert "hidden" in indicator

    def test_connection_status_has_role(self) -> None:
        # Finding 8: the dot needs a real label, not just `title`.
        html = _render_template()
        dot = html.split('id="connection-status"')[1].split(">")[0]
        assert 'role="status"' in dot
        assert "aria-label=" in dot

    def test_overlays_are_dialogs(self) -> None:
        # Finding 5: every overlay must be a modal dialog.
        html = _render_template()
        for overlay_id in ("help-overlay", "logs-overlay", "graph-overlay"):
            opening = html.split(f'id="{overlay_id}"')[1].split(">")[0]
            assert 'role="dialog"' in opening, overlay_id
            assert 'aria-modal="true"' in opening, overlay_id
            assert "aria-labelledby=" in opening, overlay_id

    def test_overlay_headings_have_stable_ids(self) -> None:
        html = _render_template()
        for heading_id in (
            "help-overlay-title",
            "logs-overlay-title",
            "graph-overlay-title",
        ):
            assert f'id="{heading_id}"' in html

    def test_header_buttons_have_type_button(self) -> None:
        # Finding 6: three header buttons must not default to type=submit.
        html = _render_template()
        for btn_id in ("btn-help", "btn-logs", "btn-graph"):
            frag = html.split(f'id="{btn_id}"')[1].split(">")[0]
            assert 'type="button"' in frag, btn_id

    def test_header_buttons_have_aria_labels(self) -> None:
        # Finding 7: screen readers shouldn't announce "question mark, button".
        html = _render_template()
        assert 'aria-label="Help"' in html
        assert 'aria-label="Logs"' in html
        assert 'aria-label="Graph"' in html

    def test_header_buttons_expose_aria_expanded(self) -> None:
        # Finding 9: disclosure buttons reflect the state of what they control.
        html = _render_template()
        for btn_id, overlay_id in (
            ("btn-help", "help-overlay"),
            ("btn-logs", "logs-overlay"),
            ("btn-graph", "graph-overlay"),
        ):
            frag = html.split(f'id="{btn_id}"')[1].split(">")[0]
            assert 'aria-expanded="false"' in frag, btn_id
            assert f'aria-controls="{overlay_id}"' in frag, btn_id

    def test_sections_have_accessible_names(self) -> None:
        # Finding 14: <section> elements need names to appear as regions.
        html = _render_template()
        chat = html.split('id="chat-panel"')[1].split(">")[0]
        workspace = html.split('id="right-panels"')[1].split(">")[0]
        assert "aria-label=" in chat
        assert "aria-label=" in workspace

    def test_shortcuts_use_description_list(self) -> None:
        # Finding 11: shortcut pairs should be a <dl>, not a <table>.
        html = _render_template()
        assert "shortcuts-list" in html
        assert "<dl" in html
        assert "shortcuts-table" not in html

    def test_shortcuts_are_alt_gated(self) -> None:
        # Finding 12: global single-key shortcuts must require a modifier.
        html = _render_template()
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "Alt+H" in html or "<kbd>Alt</kbd>" in html
        # The handler bails out unless Alt is held (and only Alt).
        assert "e.altKey" in js

    def test_js_manages_inert_on_overlay_open(self) -> None:
        # Finding 5: background must be inert while a dialog is open.
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "inert = true" in js
        assert "inert = false" in js

    def test_js_toggles_aria_expanded(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert 'setAttribute("aria-expanded", "true")' in js
        assert 'setAttribute("aria-expanded", "false")' in js

    def test_js_restores_focus_on_close(self) -> None:
        # Finding 5: focus is captured on open and restored on close.
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "document.activeElement" in js
        assert "_savedFocus" in js

    def test_js_traps_tab_in_overlay(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "_handleOverlayTab" in js

    def test_js_sets_connection_status_aria_label(self) -> None:
        # Finding 8: _setStatus must set aria-label, not only title.
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert 'setAttribute("aria-label"' in js

    def test_js_uses_hidden_attribute_for_thinking(self) -> None:
        # Finding 4: thinking indicator toggles via `hidden` so the live
        # region is preserved in the a11y tree.
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "el.hidden = !active" in js


class TestSafeWsSend:
    """Tests for _safe_ws_send error-swallowing behaviour."""

    def test_forwards_payload_to_open_ws(self) -> None:
        from cantrip.web import server

        ws = AsyncMock()
        ws.send_str = AsyncMock()
        asyncio.run(server._safe_ws_send(ws, "hello"))
        ws.send_str.assert_awaited_once_with("hello")

    def test_silences_connection_reset(self) -> None:
        from cantrip.web import server

        ws = AsyncMock()
        ws.send_str = AsyncMock(side_effect=ConnectionResetError())
        # Must not raise.
        asyncio.run(server._safe_ws_send(ws, "x"))

    def test_silences_os_error(self) -> None:
        from cantrip.web import server

        ws = AsyncMock()
        ws.send_str = AsyncMock(side_effect=OSError("broken pipe"))
        asyncio.run(server._safe_ws_send(ws, "x"))


class TestBroadcastFanOut:
    """Exercise _broadcast's fan-out and stale-client pruning."""

    def test_fan_out_sends_to_every_open_client(self) -> None:
        from cantrip.web import server

        sent: list[tuple[object, str]] = []

        async def _fake_send(ws: web.WebSocketResponse, payload: str) -> None:
            sent.append((ws, payload))

        async def _run() -> None:
            app = web.Application()
            clients: weakref.WeakSet = weakref.WeakSet()
            # Use simple namespaces rather than real WebSocketResponses; the
            # broadcast code only reads ``.closed`` and passes the object to
            # ``_safe_ws_send``, which we patch.
            ws_open_a = _StubWs(closed=False)
            ws_open_b = _StubWs(closed=False)
            clients.add(ws_open_a)
            clients.add(ws_open_b)
            app[WS_CLIENTS_KEY] = clients

            with patch.object(server, "_safe_ws_send", _fake_send):
                server._broadcast(app, "task_updated", {"id": "t1"})
                # Yield so ensure_future()-scheduled coroutines run.
                await asyncio.sleep(0)

            payloads = {payload for _, payload in sent}
            assert len(sent) == 2
            assert payloads == {'{"type": "task_updated", "data": {"id": "t1"}}'}

        asyncio.run(_run())

    def test_stale_clients_are_pruned(self) -> None:
        from cantrip.web import server

        async def _noop(_ws: web.WebSocketResponse, _payload: str) -> None:
            raise AssertionError("closed clients must not be sent to")

        async def _run() -> None:
            app = web.Application()
            clients: weakref.WeakSet = weakref.WeakSet()
            closed = _StubWs(closed=True)
            clients.add(closed)
            app[WS_CLIENTS_KEY] = clients

            with patch.object(server, "_safe_ws_send", _noop):
                server._broadcast(app, "thinking", {"active": False})
                await asyncio.sleep(0)

            assert closed not in clients

        asyncio.run(_run())

    def test_payload_shape_is_type_and_data(self) -> None:
        """The wire format is ``{"type": str, "data": dict}``."""
        from cantrip.web import server

        captured: list[str] = []

        async def _capture(_ws: web.WebSocketResponse, payload: str) -> None:
            captured.append(payload)

        async def _run() -> None:
            app = web.Application()
            clients: weakref.WeakSet = weakref.WeakSet()
            ws = _StubWs(closed=False)
            clients.add(ws)
            app[WS_CLIENTS_KEY] = clients

            with patch.object(server, "_safe_ws_send", _capture):
                server._broadcast(app, "chat_message", {"role": "assistant"})
                await asyncio.sleep(0)

            import json

            assert len(captured) == 1
            assert json.loads(captured[0]) == {
                "type": "chat_message",
                "data": {"role": "assistant"},
            }

        asyncio.run(_run())


class TestMakeBusForwarder:
    """_make_bus_forwarder returns a subscriber that forwards to _broadcast."""

    def test_forwards_event_to_broadcast(self) -> None:
        from cantrip.ui import events as ui_events
        from cantrip.web import server

        async def _run() -> None:
            app = web.Application()
            app[WS_CLIENTS_KEY] = weakref.WeakSet()
            captured: list[tuple[str, dict]] = []

            with patch.object(
                server,
                "_broadcast",
                lambda _app, evt_type, data: captured.append((evt_type, data)),
            ):
                forwarder = server._make_bus_forwarder(app)
                forwarder(
                    ui_events.Event(
                        type=ui_events.EventType.TASK_UPDATED,
                        payload={"id": "t1", "status": "done"},
                    )
                )

            assert captured == [("task_updated", {"id": "t1", "status": "done"})]

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# _websocket_handler lifecycle
# ---------------------------------------------------------------------------


def _make_agent(response: str = "ok") -> MagicMock:
    """Return a MagicMock agent shaped for the websocket handler."""
    agent = MagicMock()
    agent.state.charm_name = "mycharm"
    agent.state.dev_model = "dev"
    agent.state.messages = []
    agent._work_queue = None
    agent.process_message = AsyncMock(return_value=response)
    agent.save_state = MagicMock()
    # Default: no arena pending.  Tests that care about the arena
    # intercept override this explicitly.  Without the override
    # ``MagicMock`` makes ``active_arena`` return another MagicMock
    # (truthy), which would mis-route every chat message as an arena
    # pick.
    agent.active_arena = None
    return agent


class TestWebSocketHandler:
    """End-to-end tests for ``_websocket_handler``."""

    def test_connect_registers_client_and_disconnect_prunes(self) -> None:
        agent = _make_agent()
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await asyncio.sleep(0)  # let handler start
                assert len(app[WS_CLIENTS_KEY]) == 1
                await ws.close()
                # Wait for the handler's ``finally`` to run.
                for _ in range(50):
                    if len(app[WS_CLIENTS_KEY]) == 0:
                        break
                    await asyncio.sleep(0.01)
                assert len(app[WS_CLIENTS_KEY]) == 0

        asyncio.run(_run())

    def test_chat_input_happy_path(self) -> None:
        agent = _make_agent(response="assistant-reply")
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await ws.send_json({"type": "chat_input", "data": {"content": "hi"}})

                frames = []
                for _ in range(3):
                    msg = await ws.receive(timeout=2.0)
                    frames.append(msg.json())

                types_seen = [f["type"] for f in frames]
                assert types_seen == ["thinking", "thinking", "chat_message"]
                assert frames[0]["data"] == {"active": True}
                assert frames[1]["data"] == {"active": False}
                assert frames[2]["data"]["role"] == "assistant"
                assert frames[2]["data"]["content"] == "assistant-reply"
                # Server pre-renders Markdown and ships the HTML alongside.
                assert "<p>assistant-reply</p>" in frames[2]["data"]["html"]
                # A timestamp is included on every chat message.
                assert frames[2]["data"]["timestamp"].endswith("Z")
                agent.process_message.assert_awaited_once_with("hi")
                agent.save_state.assert_called_once()
                await ws.close()

        asyncio.run(_run())

    def test_invalid_json_is_ignored(self) -> None:
        agent = _make_agent()
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await ws.send_str("not json{")
                # Follow with a real chat_input to prove the loop recovered.
                await ws.send_json({"type": "chat_input", "data": {"content": "hi"}})
                msg = await ws.receive(timeout=2.0)
                assert msg.json()["type"] == "thinking"
                await ws.close()

        asyncio.run(_run())

    def test_empty_content_is_ignored(self) -> None:
        agent = _make_agent()
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await ws.send_json({"type": "chat_input", "data": {"content": "   "}})
                # The handler must not call process_message; send another
                # real message and prove only one round of frames arrives.
                await ws.send_json({"type": "chat_input", "data": {"content": "real"}})
                msg = await ws.receive(timeout=2.0)
                assert msg.json() == {"type": "thinking", "data": {"active": True}}
                agent.process_message.assert_awaited_once_with("real")
                await ws.close()

        asyncio.run(_run())

    def test_cancel_request_interrupts_in_flight_turn(self) -> None:
        """A ``cancel_request`` WS message cancels process_message and returns a system message."""

        async def _slow_process(_content: str) -> str:
            await asyncio.sleep(30)
            return "should not be reached"

        agent = _make_agent()
        agent.process_message = AsyncMock(side_effect=_slow_process)
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await ws.send_json({"type": "chat_input", "data": {"content": "hi"}})

                # Wait for "thinking active" to confirm the turn started.
                first = await ws.receive(timeout=2.0)
                assert first.json() == {"type": "thinking", "data": {"active": True}}

                # Give the turn task a tick to actually start awaiting.
                await asyncio.sleep(0.05)

                await ws.send_json({"type": "cancel_request"})

                frames: list[dict] = []
                for _ in range(2):
                    msg = await ws.receive(timeout=2.0)
                    frames.append(msg.json())

                types_seen = [f["type"] for f in frames]
                assert types_seen == ["thinking", "chat_message"]
                assert frames[0]["data"] == {"active": False}
                assert frames[1]["data"]["role"] == "system"
                assert frames[1]["data"]["content"] == "Cancelled."
                # save_state must NOT be called when the turn is cancelled.
                agent.save_state.assert_not_called()
                await ws.close()

        asyncio.run(_run())

    def test_cancel_without_in_flight_turn_is_noop(self) -> None:
        """A spurious ``cancel_request`` with no pending turn just returns."""
        agent = _make_agent()
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await ws.send_json({"type": "cancel_request"})
                # Follow with a real chat_input to prove the loop still works.
                await ws.send_json({"type": "chat_input", "data": {"content": "hi"}})
                msg = await ws.receive(timeout=2.0)
                assert msg.json()["type"] == "thinking"
                await ws.close()

        asyncio.run(_run())

    def test_unknown_message_type_is_ignored(self) -> None:
        agent = _make_agent()
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await ws.send_json({"type": "something_else"})
                await ws.send_json({"type": "chat_input", "data": {"content": "hi"}})
                msg = await ws.receive(timeout=2.0)
                assert msg.json()["type"] == "thinking"
                await ws.close()

        asyncio.run(_run())

    def _run_with_process_exc(self, exc: Exception) -> list[dict]:
        agent = _make_agent()
        agent.process_message = AsyncMock(side_effect=exc)
        app = _build_ws_app(agent)

        async def _run() -> list[dict]:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await ws.send_json({"type": "chat_input", "data": {"content": "hi"}})
                out: list[dict] = []
                for _ in range(3):
                    msg = await ws.receive(timeout=2.0)
                    out.append(msg.json())
                await ws.close()
                return out

        return asyncio.run(_run())

    def test_rate_limit_error_surfaces_friendly_system_message(self) -> None:
        from cantrip.llm.base import ProviderRateLimitError

        frames = self._run_with_process_exc(ProviderRateLimitError("slow down"))
        assert [f["type"] for f in frames] == ["thinking", "thinking", "chat_message"]
        assert frames[-1]["data"]["role"] == "system"
        assert "temporarily unavailable" in frames[-1]["data"]["content"]

    def test_overloaded_error_surfaces_friendly_system_message(self) -> None:
        from cantrip.llm.base import ProviderOverloadedError

        frames = self._run_with_process_exc(ProviderOverloadedError("busy"))
        assert frames[-1]["data"]["role"] == "system"
        assert "temporarily unavailable" in frames[-1]["data"]["content"]

    def test_provider_error_surfaces_the_error_string(self) -> None:
        from cantrip.llm.base import ProviderError

        frames = self._run_with_process_exc(ProviderError("bad key"))
        assert frames[-1]["data"]["role"] == "system"
        assert "Provider error: bad key" in frames[-1]["data"]["content"]

    def test_runtime_errors_surface_as_generic_error(self) -> None:
        frames = self._run_with_process_exc(RuntimeError("boom"))
        assert frames[-1]["data"]["role"] == "system"
        assert "Error: boom" in frames[-1]["data"]["content"]

    def test_os_errors_surface_as_generic_error(self) -> None:
        frames = self._run_with_process_exc(OSError("nope"))
        assert frames[-1]["data"]["role"] == "system"
        assert "Error: nope" in frames[-1]["data"]["content"]

    def test_value_errors_surface_as_generic_error(self) -> None:
        frames = self._run_with_process_exc(ValueError("no good"))
        assert frames[-1]["data"]["role"] == "system"
        assert "Error: no good" in frames[-1]["data"]["content"]

    def test_client_close_breaks_loop_cleanly(self) -> None:
        """When the client sends CLOSE, the handler exits the loop via
        the explicit ``break`` branch, not just the StopAsyncIteration that
        aiohttp raises once the underlying websocket is gone."""
        agent = _make_agent()
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await ws.close()
                # Drain pending messages; the handler should prune the
                # client from WS_CLIENTS_KEY once it exits.
                for _ in range(50):
                    if len(app[WS_CLIENTS_KEY]) == 0:
                        break
                    await asyncio.sleep(0.01)
                assert len(app[WS_CLIENTS_KEY]) == 0

        asyncio.run(_run())

    def test_websocket_rejects_cross_origin_upgrade(self) -> None:
        """A WS upgrade from a foreign Origin gets 403, not a connection."""
        import aiohttp

        agent = _make_agent()
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                try:
                    await client.ws_connect("/ws", headers={"Origin": "http://evil.example.com"})
                except aiohttp.WSServerHandshakeError as exc:
                    assert exc.status == 403
                    return
                raise AssertionError("expected handshake error from cross-origin Origin")

        asyncio.run(_run())

    def test_websocket_allows_missing_origin(self) -> None:
        """Non-browser clients (no Origin) still connect."""
        agent = _make_agent()
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                await asyncio.sleep(0)
                assert len(app[WS_CLIENTS_KEY]) == 1
                await ws.close()

        asyncio.run(_run())

    def test_websocket_ignores_non_dict_json(self) -> None:
        """Scalar/array JSON doesn't AttributeError on payload.get."""
        agent = _make_agent(response="ok")
        app = _build_ws_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/ws")
                # All three are valid JSON but not dicts.
                await ws.send_str("null")
                await ws.send_str("123")
                await ws.send_str('["x"]')
                # Loop should still be alive — a real chat_input proves recovery.
                import json as _json

                await ws.send_str(_json.dumps({"type": "chat_input", "data": {"content": "hi"}}))
                msg = await ws.receive(timeout=2.0)
                assert msg.json()["type"] == "thinking"
                await ws.close()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# REST handlers
# ---------------------------------------------------------------------------


def _work_queue_with(tasks: list[object]) -> object:
    queue = MagicMock()
    queue.all_tasks.return_value = tasks
    return queue


def _fake_task(
    id_: str,
    title: str,
    status: str = "pending",
    category: str = "build",
    description: str = "",
    result: str | None = None,
    worktree_path: str | None = None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=id_,
        title=title,
        status=types.SimpleNamespace(value=status),
        category=types.SimpleNamespace(value=category),
        description=description,
        result=result,
        worktree_path=worktree_path,
    )


class TestIndexHandler:
    """_index serves the Jinja template with initial state."""

    def test_renders_with_charm_name_and_no_tasks(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/", server._index)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/")
                assert resp.status == 200
                body = await resp.text()
                assert "<!DOCTYPE html>" in body
                assert "mycharm" in body

        asyncio.run(_run())

    def test_renders_tasks_from_work_queue(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        agent._work_queue = _work_queue_with([_fake_task("t1", "Scaffold", status="active")])
        app = _build_ws_app(agent)
        app.router.add_get("/", server._index)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/")
                body = await resp.text()
                assert "Scaffold" in body
                assert "task-active" in body

        asyncio.run(_run())


class TestApiState:
    """/api/state returns charm_name and the task list."""

    def test_returns_charm_name_and_tasks(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        agent._work_queue = _work_queue_with(
            [
                _fake_task(
                    "t1",
                    "Deploy",
                    status="done",
                    category="deploy",
                    description="ship it",
                    result="ok",
                )
            ]
        )
        app = _build_ws_app(agent)
        app.router.add_get("/api/state", server._api_state)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/state")
                data = await resp.json()
                assert data["charm_name"] == "mycharm"
                assert data["tasks"] == [
                    {
                        "id": "t1",
                        "title": "Deploy",
                        "status": "done",
                        "category": "deploy",
                        "description": "ship it",
                        "result": "ok",
                        "worktree_path": None,
                    }
                ]

        asyncio.run(_run())

    def test_empty_tasks_when_no_queue(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/state", server._api_state)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/state")
                data = await resp.json()
                assert data == {"charm_name": "mycharm", "tasks": []}

        asyncio.run(_run())

    def test_api_state_includes_worktree_path(self) -> None:
        """Phase 44.4: ``/api/state`` must surface each task's worktree path."""
        from cantrip.web import server

        agent = _make_agent()
        agent._work_queue = _work_queue_with(
            [
                _fake_task(
                    "t1",
                    "Build",
                    worktree_path="/tmp/charm/.cantrip-worktrees/t1",
                )
            ]
        )
        app = _build_ws_app(agent)
        app.router.add_get("/api/state", server._api_state)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/state")
                data = await resp.json()
                assert data["tasks"][0]["worktree_path"] == "/tmp/charm/.cantrip-worktrees/t1"

        asyncio.run(_run())


class TestApiSession:
    """Tests for the Phase 31.3 resume-prompt endpoints."""

    def _build_session_app(self, agent: MagicMock) -> web.Application:
        from cantrip.web import server

        app = _build_ws_app(agent)
        app[server.SESSION_DECIDED_KEY] = {"value": False}
        app[server.SESSION_DECIDE_LOCK_KEY] = asyncio.Lock()
        app.router.add_get("/api/session/preview", server._api_session_preview)
        app.router.add_post("/api/session/decide", server._api_session_decide)
        app.router.add_get("/api/session/transcript", server._api_session_transcript)
        return app

    def _fake_preview(
        self,
        *,
        exists: bool = True,
        summary: str = "Prior session: c",
    ) -> MagicMock:
        preview = MagicMock()
        preview.exists = exists
        preview.summary.return_value = summary
        preview.charm_name = "c"
        preview.charm_type = "k8s"
        preview.dev_model = "dev"
        preview.cos_model = None
        preview.updated_at = "2026-04-20"
        preview.message_count = 3
        preview.task_counts = {"pending": 1, "done": 2}
        preview.has_unfinished_tasks = True
        return preview

    def test_preview_returns_exists_and_not_decided(self) -> None:
        agent = _make_agent()
        agent.preview_session = MagicMock(return_value=self._fake_preview())
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/session/preview")
                data = await resp.json()
                assert data["exists"] is True
                assert data["decided"] is False
                assert data["charm_name"] == "c"
                assert data["task_counts"] == {"pending": 1, "done": 2}
                assert data["has_unfinished_tasks"] is True

        asyncio.run(_run())

    def test_preview_reflects_decided_flag(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        agent.preview_session = MagicMock(return_value=self._fake_preview())
        app = self._build_session_app(agent)
        app[server.SESSION_DECIDED_KEY]["value"] = True

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/session/preview")
                data = await resp.json()
                assert data["decided"] is True

        asyncio.run(_run())

    def test_decide_resume_loads_state_and_broadcasts(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        agent.load_state = MagicMock(return_value=True)
        agent.build_resume_summary = MagicMock(return_value="[resumed]")
        agent.archive_session = MagicMock()
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/session/decide", json={"choice": "resume"})
                assert resp.status == 200
                data = await resp.json()
                assert data["choice"] == "resume"
                assert data["summary"] == "[resumed]"

        asyncio.run(_run())
        agent.load_state.assert_called_once()
        agent.archive_session.assert_not_called()
        assert app[server.SESSION_DECIDED_KEY]["value"] is True

    def test_decide_fresh_archives_without_loading(self) -> None:
        from pathlib import Path

        from cantrip.web import server

        agent = _make_agent()
        backup = Path("/tmp/.cantrip.bak-X")
        agent.archive_session = MagicMock(return_value=backup)
        agent.load_state = MagicMock()
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/session/decide", json={"choice": "fresh"})
                assert resp.status == 200
                data = await resp.json()
                assert data["choice"] == "fresh"
                assert data["backup"] == str(backup)

        asyncio.run(_run())
        agent.archive_session.assert_called_once()
        agent.load_state.assert_not_called()
        assert app[server.SESSION_DECIDED_KEY]["value"] is True

    def test_decide_twice_returns_conflict(self) -> None:
        agent = _make_agent()
        agent.archive_session = MagicMock(return_value=None)
        agent.load_state = MagicMock(return_value=False)
        agent.build_resume_summary = MagicMock(return_value=None)
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                first = await client.post("/api/session/decide", json={"choice": "resume"})
                assert first.status == 200
                second = await client.post("/api/session/decide", json={"choice": "fresh"})
                assert second.status == 409

        asyncio.run(_run())

    def test_decide_rejects_invalid_choice(self) -> None:
        agent = _make_agent()
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/session/decide", json={"choice": "huh"})
                assert resp.status == 400

        asyncio.run(_run())

    def test_decide_rejects_bad_json(self) -> None:
        agent = _make_agent()
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/session/decide", data="not json")
                assert resp.status == 400

        asyncio.run(_run())

    def test_decide_concurrent_requests_serialise(self) -> None:
        """Two concurrent POSTs — exactly one wins, the other gets 409.

        Without the lock, both could pass the ``decided`` gate before
        either flipped it (TOCTOU across the ``await request.json()``
        window) and both ``archive_session`` / ``load_state`` paths
        would fire.
        """
        agent = _make_agent()
        agent.archive_session = MagicMock(return_value=None)
        agent.load_state = MagicMock(return_value=False)
        agent.build_resume_summary = MagicMock(return_value=None)
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                r1, r2 = await asyncio.gather(
                    client.post("/api/session/decide", json={"choice": "resume"}),
                    client.post("/api/session/decide", json={"choice": "fresh"}),
                )
                statuses = sorted([r1.status, r2.status])
                assert statuses == [200, 409]
                # At most one of the write paths fired.
                fires = agent.archive_session.call_count + agent.load_state.call_count
                assert fires == 1

        asyncio.run(_run())

    def test_decide_rejects_cross_origin(self) -> None:
        """A POST from a foreign Origin gets 403."""
        agent = _make_agent()
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/session/decide",
                    json={"choice": "resume"},
                    headers={"Origin": "http://evil.example.com"},
                )
                assert resp.status == 403

        asyncio.run(_run())

    def test_decide_accepts_matching_origin(self) -> None:
        """A POST from the bound origin succeeds."""
        agent = _make_agent()
        agent.load_state = MagicMock(return_value=False)
        agent.build_resume_summary = MagicMock(return_value=None)
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/api/session/decide",
                    json={"choice": "resume"},
                    headers={"Origin": "http://127.0.0.1:8471"},
                )
                assert resp.status == 200

        asyncio.run(_run())

    def test_transcript_returns_messages(self) -> None:
        from cantrip.llm.base import Message, Role

        agent = _make_agent()
        agent.transcript_tail = MagicMock(
            return_value=[
                Message(role=Role.USER, content="hi"),
                Message(role=Role.ASSISTANT, content="hello"),
            ]
        )
        app = self._build_session_app(agent)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/session/transcript?limit=5")
                data = await resp.json()
                assert data == {
                    "messages": [
                        {"role": "user", "content": "hi"},
                        {"role": "assistant", "content": "hello"},
                    ]
                }

        asyncio.run(_run())
        agent.transcript_tail.assert_called_once_with(limit=5)


class TestApiMessages:
    """/api/messages returns conversation history filtered by content."""

    def test_returns_messages_excluding_empty_content(self) -> None:
        from cantrip.llm.base import Message, Role
        from cantrip.web import server

        agent = _make_agent()
        agent.state.messages = [
            Message(role=Role.USER, content="hello"),
            Message(role=Role.ASSISTANT, content=""),
            Message(role=Role.ASSISTANT, content="world"),
        ]
        app = _build_ws_app(agent)
        app.router.add_get("/api/messages", server._api_messages)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/messages")
                data = await resp.json()
                messages = data["messages"]
                assert [m["role"] for m in messages] == ["user", "assistant"]
                assert [m["content"] for m in messages] == ["hello", "world"]
                # Every message carries pre-rendered HTML.
                assert "<p>hello</p>" in messages[0]["html"]
                assert "<p>world</p>" in messages[1]["html"]
                # And a timestamp.
                assert messages[0]["timestamp"]
                assert messages[1]["timestamp"]

    def test_uses_store_timestamps_when_available(self) -> None:
        """When the agent has a SQLite store, its persisted timestamps win."""
        from cantrip.web import server

        agent = _make_agent()
        store = MagicMock()
        store.load_messages.return_value = [
            {"role": "user", "content": "hi", "timestamp": "2026-04-22T08:00:00Z"},
            {"role": "assistant", "content": "hello", "timestamp": "2026-04-22T08:00:05Z"},
        ]
        agent._store = store
        app = _build_ws_app(agent)
        app.router.add_get("/api/messages", server._api_messages)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/messages")
                data = await resp.json()
                messages = data["messages"]
                assert messages[0]["timestamp"] == "2026-04-22T08:00:00Z"
                assert messages[1]["timestamp"] == "2026-04-22T08:00:05Z"

        asyncio.run(_run())


class TestApiJujuStatus:
    """/api/juju-status covers the three branches."""

    def test_returns_empty_when_no_dev_model(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        agent.state.dev_model = None
        app = _build_ws_app(agent)
        app.router.add_get("/api/juju-status", server._api_juju_status)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/juju-status")
                data = await resp.json()
                assert data == {"apps": {}, "relations": []}

        asyncio.run(_run())

    def test_returns_apps_and_relations(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/juju-status", server._api_juju_status)

        unit_status = types.SimpleNamespace(
            workload_status=types.SimpleNamespace(current="active", message="ready"),
            address="10.0.0.1",
        )
        app_status = types.SimpleNamespace(
            app_status=types.SimpleNamespace(current="active", message="healthy"),
            charm="my-charm",
            units={"my-app/0": unit_status},
        )
        relation = types.SimpleNamespace(
            provider="prometheus:metrics-endpoint",
            requirer="my-app:metrics",
            interface="prometheus_scrape",
        )
        status = types.SimpleNamespace(
            apps={"my-app": app_status},
            relations=[relation, relation],  # duplicate — must be deduped
        )

        fake_juju = MagicMock()
        fake_juju.status.return_value = status
        with (
            patch("jubilant.Juju", return_value=fake_juju),
            patch("jubilant.CLIError", RuntimeError),
        ):

            async def _run() -> None:
                async with TestClient(TestServer(app)) as client:
                    resp = await client.get("/api/juju-status")
                    data = await resp.json()

                    assert "my-app" in data["apps"]
                    app_entry = data["apps"]["my-app"]
                    assert app_entry["status"] == "active"
                    assert app_entry["message"] == "healthy"
                    assert app_entry["charm"] == "my-charm"
                    assert app_entry["units"]["my-app/0"] == {
                        "status": "active",
                        "message": "ready",
                        "address": "10.0.0.1",
                    }
                    # Relations deduped to a single entry.
                    assert len(data["relations"]) == 1
                    assert data["relations"][0]["interface"] == "prometheus_scrape"

            asyncio.run(_run())

    def test_returns_empty_on_cli_error(self) -> None:
        import jubilant

        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/juju-status", server._api_juju_status)

        fake_juju = MagicMock()
        fake_juju.status.side_effect = jubilant.CLIError(0, ["juju", "status"], "", "")
        with patch("jubilant.Juju", return_value=fake_juju):

            async def _run() -> None:
                async with TestClient(TestServer(app)) as client:
                    resp = await client.get("/api/juju-status")
                    data = await resp.json()
                    assert data == {"apps": {}, "relations": []}

            asyncio.run(_run())


# ---------------------------------------------------------------------------
# _create_app and _ws_logs_stream
# ---------------------------------------------------------------------------


class TestCreateApp:
    """_create_app wires keys and routes correctly."""

    def test_registers_expected_routes(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = server._create_app(agent, port=1234)

        paths = {route.resource.canonical for route in app.router.routes()}
        assert "/" in paths
        assert "/api/state" in paths
        assert "/api/messages" in paths
        assert "/api/juju-status" in paths
        assert "/api/update-status" in paths
        assert "/api/logs" in paths
        assert "/api/logs-stream" in paths
        assert "/api/session/preview" in paths
        assert "/api/session/decide" in paths
        assert "/api/session/transcript" in paths
        assert "/ws" in paths
        # Static route is registered under /static.
        assert any(p.startswith("/static") for p in paths)

    def test_stores_agent_port_and_clients(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = server._create_app(agent, port=9999)
        assert app[AGENT_KEY] is agent
        assert app[PORT_KEY] == 9999
        assert isinstance(app[WS_CLIENTS_KEY], weakref.WeakSet)
        assert isinstance(app[CHAT_LOCK_KEY], asyncio.Lock)
        assert isinstance(app[JINJA_ENV_KEY], jinja2.Environment)


class TestApiUpdateStatus:
    """``/api/update-status`` serves the Phase 63.4 PyPI verdict."""

    def test_null_info_when_state_empty(self) -> None:
        from cantrip.web import server
        from cantrip.web.server import UPDATE_STATE_KEY

        agent = _make_agent()
        app = _build_ws_app(agent)
        app[UPDATE_STATE_KEY] = {"info": None}
        app.router.add_get("/api/update-status", server._api_update_status)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/update-status")
                data = await resp.json()
                assert data == {"info": None}

        asyncio.run(_run())

    def test_serialises_update_info(self) -> None:
        from cantrip import update
        from cantrip.web import server
        from cantrip.web.server import UPDATE_STATE_KEY

        info = update.UpdateInfo(
            current="0.1.0",
            latest="0.2.0",
            pypi_url="https://pypi.org/project/juju-cantrip/0.2.0/",
            release_timestamp="2026-04-21T00:00:00Z",
            release_notes_markdown="## 0.2.0\n\n- Nice.",
            installed_yanked=False,
        )
        agent = _make_agent()
        app = _build_ws_app(agent)
        app[UPDATE_STATE_KEY] = {"info": info}
        app.router.add_get("/api/update-status", server._api_update_status)

        async def _run() -> None:
            with patch(
                "cantrip.update.detect_install_method",
                return_value=update.InstallMethod.UV_TOOL,
            ):
                async with TestClient(TestServer(app)) as client:
                    resp = await client.get("/api/update-status")
                    data = await resp.json()
                    payload = data["info"]
                    assert payload["latest"] == "0.2.0"
                    assert payload["current"] == "0.1.0"
                    assert payload["upgrade_command"] == "uv tool upgrade juju-cantrip"
                    assert payload["install_method"] == "uv-tool"
                    assert payload["installed_yanked"] is False

        asyncio.run(_run())

    def test_non_updateinfo_state_serialises_as_null(self) -> None:
        from cantrip.web import server
        from cantrip.web.server import UPDATE_STATE_KEY

        agent = _make_agent()
        app = _build_ws_app(agent)
        # Stashing a junk value mustn't crash the endpoint — defensive
        # coding because the key is public and could be cleared.
        app[UPDATE_STATE_KEY] = {"info": "not an UpdateInfo"}
        app.router.add_get("/api/update-status", server._api_update_status)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/update-status")
                data = await resp.json()
                assert data == {"info": None}

        asyncio.run(_run())


class TestRunUpdateCheck:
    """``_run_update_check`` populates state and broadcasts once settled."""

    def test_broadcasts_available_and_stores_info(self) -> None:
        from cantrip import update
        from cantrip.web import server
        from cantrip.web.server import UPDATE_STATE_KEY

        info = update.UpdateInfo(
            current="0.1.0",
            latest="0.2.0",
            pypi_url="https://pypi.org/project/juju-cantrip/0.2.0/",
            release_timestamp=None,
        )
        agent = _make_agent()
        app = _build_ws_app(agent)
        app[UPDATE_STATE_KEY] = {"info": None}

        async def _run() -> None:
            with (
                patch("cantrip.update.check_for_update", new=AsyncMock(return_value=info)),
                patch(
                    "cantrip.update.detect_install_method",
                    return_value=update.InstallMethod.UNKNOWN,
                ),
                patch("cantrip.web.server._broadcast") as mock_broadcast,
            ):
                await server._run_update_check(app)
            assert app[UPDATE_STATE_KEY]["info"] is info
            mock_broadcast.assert_called_once()
            args = mock_broadcast.call_args.args
            assert args[1] == "update_available"
            payload = args[2]["info"]
            assert payload["latest"] == "0.2.0"
            # UNKNOWN installer → upgrade_command is None; frontend
            # falls back to the "visit PyPI" button.
            assert payload["upgrade_command"] is None

        asyncio.run(_run())

    def test_broadcasts_null_on_no_update(self) -> None:
        from cantrip.web import server
        from cantrip.web.server import UPDATE_STATE_KEY

        agent = _make_agent()
        app = _build_ws_app(agent)
        app[UPDATE_STATE_KEY] = {"info": None}

        async def _run() -> None:
            with (
                patch("cantrip.update.check_for_update", new=AsyncMock(return_value=None)),
                patch("cantrip.web.server._broadcast") as mock_broadcast,
            ):
                await server._run_update_check(app)
            # Still broadcasts, but with info=None so reconnecting
            # clients see the definitive "nothing to show" answer.
            mock_broadcast.assert_called_once()
            assert mock_broadcast.call_args.args[2] == {"info": None}

        asyncio.run(_run())

    def test_swallows_worker_errors(self) -> None:
        from cantrip.web import server
        from cantrip.web.server import UPDATE_STATE_KEY

        agent = _make_agent()
        app = _build_ws_app(agent)
        app[UPDATE_STATE_KEY] = {"info": None}

        async def _run() -> None:
            with (
                patch(
                    "cantrip.update.check_for_update",
                    new=AsyncMock(side_effect=OSError("network down")),
                ),
                patch("cantrip.web.server._broadcast") as mock_broadcast,
            ):
                await server._run_update_check(app)
            # Error path still broadcasts null; never raises.
            mock_broadcast.assert_called_once()

        asyncio.run(_run())


class TestApiLogsEdgeCases:
    """/api/logs branches not exercised by TestLogInputValidation."""

    def test_returns_empty_when_no_dev_model(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        agent.state.dev_model = None
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs", server._api_logs)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/api/logs")
                data = await resp.json()
                assert data == {"lines": [], "error": "No model or juju CLI"}

        asyncio.run(_run())

    def test_returns_empty_when_juju_cli_missing(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs", server._api_logs)

        async def _run() -> None:
            with patch("shutil.which", return_value=None):
                async with TestClient(TestServer(app)) as client:
                    resp = await client.get("/api/logs")
                    data = await resp.json()
                    assert data["error"] == "No model or juju CLI"

        asyncio.run(_run())

    def test_non_integer_lines_falls_back_to_default(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs", server._api_logs)

        fake_result = types.SimpleNamespace(stdout="one\ntwo", returncode=0)

        async def _run() -> None:
            with (
                patch("shutil.which", return_value="/usr/bin/juju"),
                patch("subprocess.run", return_value=fake_result) as run_mock,
            ):
                async with TestClient(TestServer(app)) as client:
                    resp = await client.get("/api/logs?lines=not-an-int")
                    data = await resp.json()
                    assert resp.status == 200
                    assert data["lines"] == ["one", "two"]
                    # Default was used: "--limit 100".
                    cmd = run_mock.call_args[0][0]
                    assert cmd[cmd.index("--limit") + 1] == "100"

        asyncio.run(_run())

    def test_timeout_returns_empty_lines(self) -> None:
        import subprocess

        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs", server._api_logs)

        async def _run() -> None:
            with (
                patch("shutil.which", return_value="/usr/bin/juju"),
                patch(
                    "subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd=["juju"], timeout=15),
                ),
            ):
                async with TestClient(TestServer(app)) as client:
                    resp = await client.get("/api/logs")
                    data = await resp.json()
                    assert data == {"lines": []}

        asyncio.run(_run())


class TestWsLogsStream:
    """/api/logs-stream — WebSocket that tails juju debug-log."""

    def test_sends_error_when_no_model(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        agent.state.dev_model = None
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs-stream", server._ws_logs_stream)

        async def _run() -> None:
            async with TestClient(TestServer(app)) as client:
                ws = await client.ws_connect("/api/logs-stream")
                msg = await ws.receive(timeout=2.0)
                assert msg.json() == {"error": "No model or juju CLI"}
                # Server closes the socket; the next receive returns CLOSE.
                close = await ws.receive(timeout=2.0)
                assert close.type in (
                    web.WSMsgType.CLOSE,
                    web.WSMsgType.CLOSED,
                    web.WSMsgType.CLOSING,
                )

        asyncio.run(_run())

    def test_sends_error_when_juju_not_available(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs-stream", server._ws_logs_stream)

        async def _run() -> None:
            with patch("cantrip.juju.log_stream.juju_available", return_value=False):
                async with TestClient(TestServer(app)) as client:
                    ws = await client.ws_connect("/api/logs-stream")
                    msg = await ws.receive(timeout=2.0)
                    assert msg.json() == {"error": "No model or juju CLI"}

        asyncio.run(_run())

    def test_streams_lines_from_juju(self) -> None:
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs-stream", server._ws_logs_stream)

        async def _fake_stream(*_args, **_kwargs):
            for line in ("unit-0: started", "unit-0: ready"):
                yield line

        async def _run() -> None:
            with (
                patch("cantrip.juju.log_stream.juju_available", return_value=True),
                patch("cantrip.juju.log_stream.stream_lines", _fake_stream),
            ):
                async with TestClient(TestServer(app)) as client:
                    ws = await client.ws_connect("/api/logs-stream")
                    first = await ws.receive(timeout=2.0)
                    second = await ws.receive(timeout=2.0)
                    assert first.json() == {"line": "unit-0: started"}
                    assert second.json() == {"line": "unit-0: ready"}

        asyncio.run(_run())

    def test_os_error_from_stream_is_silenced(self) -> None:
        """An OSError mid-stream must be caught; the handler then closes the
        socket in its ``finally`` block."""
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs-stream", server._ws_logs_stream)

        async def _fake_stream(*_args, **_kwargs):
            yield "first line"
            raise OSError("pipe broke")

        async def _run() -> None:
            with (
                patch("cantrip.juju.log_stream.juju_available", return_value=True),
                patch("cantrip.juju.log_stream.stream_lines", _fake_stream),
            ):
                async with TestClient(TestServer(app)) as client:
                    ws = await client.ws_connect("/api/logs-stream")
                    first = await ws.receive(timeout=2.0)
                    assert first.json() == {"line": "first line"}
                    # Server closes the socket after the OSError.
                    close = await ws.receive(timeout=2.0)
                    assert close.type in (
                        web.WSMsgType.CLOSE,
                        web.WSMsgType.CLOSED,
                        web.WSMsgType.CLOSING,
                    )

        asyncio.run(_run())

    def test_normalises_invalid_level_to_warning(self) -> None:
        """Malicious query string must fall back to WARNING."""
        from cantrip.web import server

        agent = _make_agent()
        app = _build_ws_app(agent)
        app.router.add_get("/api/logs-stream", server._ws_logs_stream)

        captured: dict = {}

        async def _fake_stream(model: str, **kwargs):
            captured["model"] = model
            captured.update(kwargs)
            if False:
                yield  # pragma: no cover — make this a generator

        async def _run() -> None:
            with (
                patch("cantrip.juju.log_stream.juju_available", return_value=True),
                patch("cantrip.juju.log_stream.stream_lines", _fake_stream),
            ):
                async with TestClient(TestServer(app)) as client:
                    ws = await client.ws_connect("/api/logs-stream?level=; rm")
                    # Drain close frame.
                    await ws.receive(timeout=2.0)

            assert captured["level"] == "WARNING"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# run_web entry point
# ---------------------------------------------------------------------------


class TestRunWebEntryPoint:
    """run_web's top-level argument handling."""

    def test_returns_1_on_provider_error(self) -> None:
        from cantrip.llm.base import ProviderError
        from cantrip.web import server

        args = types.SimpleNamespace(
            provider="claude",
            model=None,
            snap="gemma3",
            light_snap=None,
            light_provider=None,
            light_model=None,
            path=None,
            web_port=9999,
        )

        with patch.object(server, "create_provider", side_effect=ProviderError("no key")):
            assert server.run_web(args) == 1

    def test_returns_1_on_value_error(self) -> None:
        from cantrip.web import server

        args = types.SimpleNamespace(
            provider="unknown",
            model=None,
            snap="gemma3",
            light_snap=None,
            light_provider=None,
            light_model=None,
            path=None,
            web_port=9999,
        )

        with patch.object(server, "create_provider", side_effect=ValueError("no such provider")):
            assert server.run_web(args) == 1

    def test_happy_path_dispatches_to_async_runner(self) -> None:
        """``run_web`` must construct an agent and hand off to asyncio.run."""
        from cantrip.web import server

        args = types.SimpleNamespace(
            provider="claude",
            model=None,
            snap="gemma3",
            light_snap=None,
            light_provider=None,
            light_model=None,
            path=None,
            web_port=1234,
        )

        fake_agent = MagicMock()

        def _close_and_return(coro, *_a, **_kw):
            coro.close()
            return None

        with (
            patch.object(server, "create_provider", return_value=MagicMock(model_name="m")),
            patch.object(server, "resolve_light_provider", return_value=(None, None)),
            patch.object(server, "CantripAgent", return_value=fake_agent) as agent_ctor,
            patch.object(server.asyncio, "run", side_effect=_close_and_return) as run_mock,
        ):
            rc = server.run_web(args)

        assert rc == 0
        agent_ctor.assert_called_once()
        run_mock.assert_called_once()

    def test_keyboard_interrupt_is_swallowed(self) -> None:
        from cantrip.web import server

        args = types.SimpleNamespace(
            provider="claude",
            model=None,
            snap="gemma3",
            light_snap=None,
            light_provider=None,
            light_model=None,
            path=None,
            web_port=1234,
        )

        def _close_and_raise(coro, *_a, **_kw):
            coro.close()
            raise KeyboardInterrupt

        with (
            patch.object(server, "create_provider", return_value=MagicMock(model_name="m")),
            patch.object(server, "resolve_light_provider", return_value=(None, None)),
            patch.object(server, "CantripAgent", return_value=MagicMock()),
            patch.object(server.asyncio, "run", side_effect=_close_and_raise),
        ):
            assert server.run_web(args) == 0


class TestRunWebAsync:
    """_run_web_async wires up the event bus and runs until cancelled."""

    def test_starts_site_and_stops_on_cancel(self) -> None:
        from cantrip.web import server

        agent = MagicMock()
        agent.load_state.return_value = False
        agent.build_resume_summary.return_value = ""
        preview = MagicMock()
        preview.exists = False
        agent.preview_session = MagicMock(return_value=preview)
        agent.state.charm_name = "c"
        agent._work_queue = None
        agent.event_bus = MagicMock()
        agent.start_executor = MagicMock()
        agent.stop_executor = AsyncMock()
        agent.mcp_registry = MagicMock()
        agent.mcp_registry.configured = []
        agent.start_mcp = AsyncMock()
        agent.stop_mcp = AsyncMock()

        fake_runner = MagicMock()
        fake_runner.setup = AsyncMock()
        fake_runner.cleanup = AsyncMock()
        fake_site = MagicMock()
        fake_site.start = AsyncMock()

        async def _runner() -> None:
            task = asyncio.create_task(server._run_web_async(agent, 1234))
            # Give it a moment to reach asyncio.Event().wait().
            await asyncio.sleep(0.05)
            task.cancel()
            # ``_run_web_async`` swallows CancelledError and returns None
            # after running the finally-block cleanup.
            assert await task is None

        with (
            patch.object(server.web, "AppRunner", return_value=fake_runner),
            patch.object(server.web, "TCPSite", return_value=fake_site),
        ):
            asyncio.run(_runner())

        fake_runner.setup.assert_awaited_once()
        fake_site.start.assert_awaited_once()
        agent.start_executor.assert_called_once()
        agent.stop_executor.assert_awaited_once()
        fake_runner.cleanup.assert_awaited_once()
        agent.event_bus.bind_loop.assert_called_once()
        agent.event_bus.subscribe.assert_called_once()

    def test_defers_load_state_for_browser_choice(self) -> None:
        """Phase 31.3: server no longer auto-loads; it waits for the prompt."""
        from cantrip.web import server

        agent = MagicMock()
        agent.load_state.return_value = True
        agent.build_resume_summary.return_value = "resumed"
        preview = MagicMock()
        preview.exists = True
        agent.preview_session = MagicMock(return_value=preview)
        agent.state.charm_name = "c"
        agent._work_queue = None
        agent.event_bus = MagicMock()
        agent.start_executor = MagicMock()
        agent.stop_executor = AsyncMock()
        agent.mcp_registry = MagicMock()
        agent.mcp_registry.configured = []
        agent.start_mcp = AsyncMock()
        agent.stop_mcp = AsyncMock()

        fake_runner = MagicMock()
        fake_runner.setup = AsyncMock()
        fake_runner.cleanup = AsyncMock()
        fake_site = MagicMock()
        fake_site.start = AsyncMock()

        async def _runner() -> None:
            task = asyncio.create_task(server._run_web_async(agent, 1234))
            await asyncio.sleep(0.05)
            task.cancel()
            assert await task is None

        with (
            patch.object(server.web, "AppRunner", return_value=fake_runner),
            patch.object(server.web, "TCPSite", return_value=fake_site),
        ):
            asyncio.run(_runner())

        # Preview was consulted but load_state wasn't called — that
        # happens only after the browser POSTs /api/session/decide.
        agent.preview_session.assert_called_once()
        agent.load_state.assert_not_called()
        agent.build_resume_summary.assert_not_called()
