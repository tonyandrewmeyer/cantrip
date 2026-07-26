"""Live-browser accessibility regression tests (Phase 60.9).

Drives the Cantrip web UI through ``uvx rodney`` to assert the invariants
captured in ``design/WEB_UI_ACCESSIBILITY_AUDIT.md`` against a real
rendered page.  Complements the static checks in
``tests/unit/test_web_server.py::TestAccessibility`` by catching
regressions that only appear once the browser has computed roles,
styles, and focus — script-wiring for ``aria-expanded`` toggling,
``inert`` on the backdrop while an overlay is open, focus management,
and computed-contrast for the Send button.

The whole module skips when ``uvx rodney`` or Chromium isn't available,
so it's safe to collect in CI without mandating either dependency.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import threading
import weakref
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import aiohttp.web as web
import jinja2
import pytest

from cantrip.web.server import (
    _STATIC_DIR,
    _TEMPLATE_DIR,
    AGENT_KEY,
    CHAT_LOCK_KEY,
    JINJA_ENV_KEY,
    PORT_KEY,
    WS_CLIENTS_KEY,
    _index,
)

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterator

# Every test in this module is synchronous on purpose — the aiohttp app
# runs on a dedicated thread so test bodies can call subprocess.run
# without blocking an event loop.  pytest-asyncio's auto mode only wraps
# ``async def`` tests, so sync ones need no extra configuration.

_RODNEY_STARTUP_TIMEOUT = 90.0
_RODNEY_CMD_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Environment probing — skip the whole module if rodney or chrome is absent
# ---------------------------------------------------------------------------


def _probe_rodney() -> str | None:
    """Return a skip reason if ``uvx rodney`` or Chromium can't be used.

    Checks in order of cheapness so CI doesn't pay to download rodney
    just to discover there's no browser to drive.
    """
    if not any(
        shutil.which(binary) is not None
        for binary in ("chromium", "chromium-browser", "google-chrome", "chrome")
    ):
        return "no chromium/chrome binary on PATH"
    if shutil.which("uvx") is None:
        return "uvx is not available"
    try:
        result = subprocess.run(
            ["uvx", "rodney", "--version"],
            capture_output=True,
            text=True,
            timeout=_RODNEY_STARTUP_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"uvx rodney not runnable: {exc}"
    if result.returncode != 0:
        return f"uvx rodney --version exited {result.returncode}: {result.stderr}"
    return None


_skip_reason = _probe_rodney()
if _skip_reason is not None:
    pytest.skip(_skip_reason, allow_module_level=True)


# ---------------------------------------------------------------------------
# Thread-hosted aiohttp server
# ---------------------------------------------------------------------------


class _ServerThread(threading.Thread):
    """Run an aiohttp application on a dedicated thread with its own loop.

    The test bodies block on ``subprocess.run(...)`` for rodney commands,
    so the server needs a loop that is not the one pytest-asyncio is
    managing.  A daemon thread with its own loop keeps that cleanly
    separated.
    """

    def __init__(self, app: web.Application) -> None:
        super().__init__(daemon=True, name="cantrip-web-test")
        self._app = app
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._ready = threading.Event()
        self._quit = threading.Event()
        self.url: str | None = None
        self._error: BaseException | None = None

    def run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)

            runner = web.AppRunner(self._app)
            self._runner = runner
            loop.run_until_complete(runner.setup())

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()

            site = web.TCPSite(runner, "127.0.0.1", port)
            loop.run_until_complete(site.start())

            self.url = f"http://127.0.0.1:{port}"
            self._ready.set()

            async def _idle() -> None:
                while not self._quit.is_set():
                    await asyncio.sleep(0.05)

            loop.run_until_complete(_idle())
            loop.run_until_complete(runner.cleanup())
        except BaseException as exc:
            self._error = exc
            self._ready.set()
        finally:
            if self._loop is not None and not self._loop.is_closed():
                self._loop.close()

    def wait_ready(self, timeout: float = 10.0) -> str:
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError("web server did not become ready")
        if self._error is not None:
            raise self._error
        assert self.url is not None
        return self.url

    def shutdown(self) -> None:
        self._quit.set()
        self.join(timeout=5.0)


def _make_test_agent() -> MagicMock:
    """Return a MagicMock shaped just enough for ``_index`` to render."""
    agent = MagicMock()
    agent.state.charm_name = ""
    agent._work_queue = None
    return agent


def _build_app(agent: MagicMock) -> web.Application:
    app = web.Application()
    app[AGENT_KEY] = agent
    app[PORT_KEY] = 0
    app[WS_CLIENTS_KEY] = weakref.WeakSet()
    app[CHAT_LOCK_KEY] = asyncio.Lock()
    app[JINJA_ENV_KEY] = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    app.router.add_get("/", _index)
    app.router.add_static("/static", _STATIC_DIR, name="static")
    return app


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _rodney_home(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    return tmp_path_factory.mktemp("rodney-home")


@pytest.fixture(scope="module")
def rodney_env(_rodney_home: pathlib.Path) -> dict[str, str]:
    """Environment dict that isolates the rodney session from the user's."""
    import os

    env = dict(os.environ)
    env["RODNEY_HOME"] = str(_rodney_home)
    return env


@pytest.fixture(scope="module")
def _chrome(rodney_env: dict[str, str]) -> Iterator[None]:
    """Start a Chromium instance under rodney's control for the module."""
    subprocess.run(
        ["uvx", "rodney", "start"],
        env=rodney_env,
        check=True,
        timeout=_RODNEY_STARTUP_TIMEOUT,
        capture_output=True,
    )
    try:
        yield
    finally:
        subprocess.run(
            ["uvx", "rodney", "stop"],
            env=rodney_env,
            check=False,
            timeout=_RODNEY_CMD_TIMEOUT,
            capture_output=True,
        )


@pytest.fixture(scope="module")
def _server() -> Iterator[str]:
    agent = _make_test_agent()
    app = _build_app(agent)
    thread = _ServerThread(app)
    thread.start()
    try:
        yield thread.wait_ready(timeout=10.0)
    finally:
        thread.shutdown()


@pytest.fixture
def page(_chrome: None, _server: str, rodney_env: dict[str, str]) -> str:
    """Navigate rodney to a freshly loaded page; return the base URL."""
    _rodney(["open", _server], env=rodney_env)
    _rodney(["waitload"], env=rodney_env)
    # The template loads cantrip.js which wires the dialog helpers on
    # DOMContentLoaded.  Wait for chat-input to exist as a cheap proxy
    # for "DOM parsed, scripts executed".
    _rodney(["wait", "#chat-input"], env=rodney_env)
    return _server


# ---------------------------------------------------------------------------
# rodney helpers
# ---------------------------------------------------------------------------


def _rodney(
    args: list[str],
    *,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["uvx", "rodney", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_RODNEY_CMD_TIMEOUT,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"rodney {' '.join(args)} failed ({result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return result


def _ax_node(selector: str, env: dict[str, str]) -> dict[str, str]:
    """Parse ``rodney ax-node``'s text output into a dict.

    The default output is one ``key: value`` per line
    (``role: button``, ``name: Test``, ``focusable: true``).  That's a
    much simpler surface than the ``--json`` mode, which nests role and
    name inside ``{"type": "role", "value": ...}`` wrappers derived from
    the Chrome DevTools Protocol.
    """
    result = _rodney(["ax-node", selector], env=env)
    info: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        info[key.strip()] = value.strip()
    return info


def _js(expr: str, env: dict[str, str]) -> str:
    """Evaluate a JS expression; return the trimmed stdout."""
    return _rodney(["js", expr], env=env).stdout.strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRolesAndNames:
    """The browser's a11y tree exposes the roles and names from the audit."""

    def test_chat_messages_exposed_as_log(self, page: str, rodney_env: dict[str, str]) -> None:
        # Finding 4: assistant replies live in a log landmark.
        node = _ax_node("#chat-messages", rodney_env)
        assert node.get("role") == "log", node

    def test_send_button_accessible_name(self, page: str, rodney_env: dict[str, str]) -> None:
        # Finding 7 generalised: the Send button must have a name.
        node = _ax_node("#chat-form button", rodney_env)
        assert node.get("name") == "Send", node
        assert node.get("role") == "button", node

    def test_chat_input_has_label_not_just_placeholder(
        self, page: str, rodney_env: dict[str, str]
    ) -> None:
        # Finding 3: the visually-hidden <label> wins over the placeholder
        # as the programmatic name.  The placeholder stays as the visual
        # hint but must not be the accessible name.
        node = _ax_node("#chat-input", rodney_env)
        assert "Describe what you want to build" in (node.get("name") or ""), node

    def test_header_buttons_have_readable_names(
        self, page: str, rodney_env: dict[str, str]
    ) -> None:
        # Finding 7: "?" on btn-help must announce as "Help", not glyph.
        assert _ax_node("#btn-help", rodney_env).get("name") == "Help"
        assert _ax_node("#btn-logs", rodney_env).get("name") == "Logs"
        assert _ax_node("#btn-graph", rodney_env).get("name") == "Graph"

    def test_connection_status_has_name(self, page: str, rodney_env: dict[str, str]) -> None:
        # Finding 8: the dot must expose its state as a name, not only a title.
        node = _ax_node("#connection-status", rodney_env)
        assert node.get("name"), node


class TestOverlaysAreDialogs:
    """Overlays behave as modal dialogs per WCAG 2.4.3 / 4.1.2 (finding 5)."""

    def test_help_overlay_opens_and_moves_focus(
        self, page: str, rodney_env: dict[str, str]
    ) -> None:
        _rodney(["click", "#btn-help"], env=rodney_env)
        active = _js("document.activeElement.id || ''", rodney_env)
        # Heading captures focus on open (tabindex=-1).
        assert active == "help-overlay-title", active

    def test_help_overlay_flips_aria_expanded(self, page: str, rodney_env: dict[str, str]) -> None:
        _rodney(["click", "#btn-help"], env=rodney_env)
        assert (
            _js("document.getElementById('btn-help').getAttribute('aria-expanded')", rodney_env)
            == "true"
        )

    def test_main_is_inert_while_overlay_open(self, page: str, rodney_env: dict[str, str]) -> None:
        _rodney(["click", "#btn-help"], env=rodney_env)
        # All three landmarks outside the dialog should become inert so
        # Tab / click don't leak into the backdrop.
        header_inert = _js("document.querySelector('body > header').inert", rodney_env)
        main_inert = _js("document.querySelector('body > main').inert", rodney_env)
        footer_inert = _js("document.querySelector('body > footer').inert", rodney_env)
        assert header_inert == "true"
        assert main_inert == "true"
        assert footer_inert == "true"

    def test_escape_closes_and_restores_focus(self, page: str, rodney_env: dict[str, str]) -> None:
        _rodney(["click", "#btn-help"], env=rodney_env)
        # Dispatch Escape at the document level — the handler is registered
        # on ``document`` in ``cantrip.js``.
        _js(
            "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))",
            rodney_env,
        )
        # aria-expanded flips back and focus returns to the trigger.
        assert (
            _js("document.getElementById('btn-help').getAttribute('aria-expanded')", rodney_env)
            == "false"
        )
        assert _js("document.activeElement.id || ''", rodney_env) == "btn-help"
        # Backdrop regains interactivity.
        assert _js("document.querySelector('body > main').inert", rodney_env) == "false"


class TestContrast:
    """Computed-style contrast for the primary action (finding 2)."""

    def test_send_button_meets_aa_contrast(self, page: str, rodney_env: dict[str, str]) -> None:
        # Recompute the WCAG 2 contrast ratio client-side so we're testing
        # what the browser actually paints, not the CSS token names.
        contrast_js = _SEND_BUTTON_CONTRAST_JS
        ratio_text = _js(contrast_js, rodney_env)
        ratio = float(ratio_text)
        # 4.5:1 is the WCAG 2 AA threshold for normal text; the Send
        # button label sits comfortably above it when styled with
        # --accent-strong.
        assert ratio >= 4.5, f"Send button contrast {ratio:.2f} falls below 4.5:1"


# JS snippet factored out so the test body stays readable.  Uses the
# WCAG 2 relative-luminance formula.
_SEND_BUTTON_CONTRAST_JS = """
(() => {
  const btn = document.querySelector('#chat-form button');
  const styles = getComputedStyle(btn);
  const parse = (s) => s.match(/[\\d.]+/g).slice(0, 3).map(Number);
  const lum = ([r, g, b]) => {
    const conv = (c) => {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    const [R, G, B] = [r, g, b].map(conv);
    return 0.2126 * R + 0.7152 * G + 0.0722 * B;
  };
  const L1 = lum(parse(styles.color));
  const L2 = lum(parse(styles.backgroundColor));
  const hi = Math.max(L1, L2), lo = Math.min(L1, L2);
  return ((hi + 0.05) / (lo + 0.05)).toFixed(3);
})()
"""
