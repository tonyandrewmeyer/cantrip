"""Tests for the web UI server."""

import jinja2

from cantrip.web.server import (
    _MAX_LOG_LINES,
    _STATIC_DIR,
    _TEMPLATE_DIR,
    _VALID_LOG_LEVELS,
    AGENT_KEY,
    WS_CLIENTS_KEY,
    _broadcast,
)


def _render_template() -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    return env.get_template("index.html.j2").render(charm_name="", tasks=[], port=8471)


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
        assert ".msg-assistant pre" in css
        assert ".msg-assistant code" in css


class TestJavaScriptFeatures:
    """Tests for the enhanced JavaScript features."""

    def test_js_has_markdown_renderer(self) -> None:
        js = (_STATIC_DIR / "cantrip.js").read_text()
        assert "_renderMarkdown" in js

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
                    assert cmd[cmd.index("-n") + 1] == "1"

                # Excessively large lines should be clamped to _MAX_LOG_LINES.
                with (
                    patch("shutil.which", return_value="/usr/bin/juju"),
                    patch("subprocess.run", return_value=fake_result) as mock_run,
                ):
                    resp = await client.get("/api/logs?lines=999999")
                    assert resp.status == 200
                    cmd = mock_run.call_args[0][0]
                    assert cmd[cmd.index("-n") + 1] == str(_MAX_LOG_LINES)

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
