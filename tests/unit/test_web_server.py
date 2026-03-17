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
