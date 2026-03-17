"""Tests for the web UI server."""

from cantrip.web.server import _STATIC_DIR, _TEMPLATE_DIR, _broadcast


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
        app["ws_clients"] = weakref.WeakSet()
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
