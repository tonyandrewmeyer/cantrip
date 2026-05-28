"""Shared MCP SDK content-block doubles for unit tests.

The MCP-Apps extraction code (:func:`cantrip.mcp.client._content_to_structured`
and :func:`cantrip.mcp.client._extract_app_render`) reads duck-typed
content blocks off a tool-call result.  Tests would otherwise need a live
MCP SDK and a real server to produce them, so these dataclasses stand in
with exactly the attributes the extractor inspects — nothing more.

Reach for these whenever a test drives the client-side extraction path:

* :class:`FakeTextBlock` — a plain ``text`` block (no app render).
* :class:`FakeUIBlock` — shape A: a first-class ``ui`` block carrying
  inline HTML plus the optional ``title`` / ``mimeType`` / ``meta`` the
  extractor reads.
* :class:`FakeMetaResourceBlock` — shape B: a generic ``resource`` block
  that smuggles an MCP-Apps payload through its ``_meta`` field.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any


class FakeMCPClient:
    """In-test stand-in for :class:`cantrip.mcp.client.MCPClient`.

    Exposes only the surface the MCP-backed tools exercise: a ``tools``
    list (each a ``SimpleNamespace`` with a ``name``) and an awaitable
    ``call_tool`` that returns a ``SimpleNamespace(text=...)``.  Every
    call is recorded on ``calls`` for assertions.

    *responses* and *errors* are keyed on the **tool name** by default.
    Set *key_arg* to key them on an argument instead — e.g.
    ``key_arg="name"`` so a single ``find_snap`` tool can return
    different payloads per requested snap name.
    """

    def __init__(
        self,
        *,
        tools: list[str],
        responses: dict[str, str] | None = None,
        errors: dict[str, Exception] | None = None,
        key_arg: str | None = None,
    ) -> None:
        self.tools = [SimpleNamespace(name=name) for name in tools]
        self._responses = responses or {}
        self._errors = errors or {}
        self._key_arg = key_arg
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append((name, arguments))
        key: object = name if self._key_arg is None else arguments.get(self._key_arg, "")
        if isinstance(key, str) and key in self._errors:
            raise self._errors[key]
        return SimpleNamespace(text=self._responses.get(key if isinstance(key, str) else "", ""))


class FakeMCPRegistry:
    """Registry stand-in mapping server name → :class:`FakeMCPClient`."""

    def __init__(self, clients: dict[str, FakeMCPClient]) -> None:
        self._clients = clients

    def get_client(self, name: str) -> FakeMCPClient | None:
        return self._clients.get(name)


@dataclasses.dataclass
class FakeTextBlock:
    """A plain text content block — produces no app render."""

    text: str
    type: str = "text"


@dataclasses.dataclass
class FakeUIBlock:
    """Shape A: a first-class ``ui`` block carrying inline HTML."""

    html: str
    type: str = "ui"
    mimeType: str = "text/html"
    title: str | None = None
    meta: dict[str, Any] | None = None


@dataclasses.dataclass
class FakeMetaResourceBlock:
    """Shape B: a generic resource that carries an MCP-Apps ``_meta`` field."""

    type: str = "resource"
    text: str = ""
    _meta: dict[str, Any] = dataclasses.field(default_factory=dict)
