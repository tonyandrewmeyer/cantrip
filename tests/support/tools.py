"""Shared :class:`Tool` doubles for unit and integration tests.

Multiple test modules used to define their own minimal ``_StubTool`` /
``_make_tool`` helper because nothing centralised the shape.  This
module is the single home for that pattern — reach for
:func:`make_stub_tool` whenever a test needs *a* tool but doesn't
care what it does, only that it exists in the registry and returns a
predictable result.

For failure injection (Phase 93.2) use :func:`make_stub_tool` with
``success=False`` for a tool that *returns* an error result, or
:func:`make_raising_tool` for one that *raises* mid-execute — the two
exercise different branches of :func:`cantrip.agent.tools.base.execute_tool`.
"""

from __future__ import annotations

from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


def make_stub_tool(
    name: str,
    *,
    description: str | None = None,
    output: str = "ok",
    success: bool = True,
    parameters: dict[str, Any] | None = None,
) -> Tool:
    """Return a minimal :class:`Tool` instance suitable for executor / subagent tests.

    The returned tool has *name*, advertises an empty ``object`` parameter
    schema (or *parameters* if given), and resolves :meth:`Tool.execute`
    to ``ToolResult(success=success, output=output)``.  Use this whenever
    a test needs a tool placeholder rather than real behaviour.
    """
    desc = description if description is not None else f"Stub tool {name}"
    schema = parameters if parameters is not None else {"type": "object", "properties": {}}

    class _StubTool(Tool):
        @property
        def name(self) -> str:
            return name

        @property
        def description(self) -> str:
            return desc

        @property
        def parameters(self) -> dict[str, Any]:
            return schema

        async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
            return ToolResult(success=success, output=output)

    return _StubTool()


def make_raising_tool(
    name: str,
    *,
    exc: BaseException | None = None,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> Tool:
    """Return a :class:`Tool` whose :meth:`Tool.execute` raises *exc*.

    Defaults to ``RuntimeError(f"{name} crashed")`` — one of the types
    :func:`cantrip.agent.tools.base.execute_tool` is expected to catch
    and turn into an error :class:`ToolResult`.  Use this to prove a
    crashing tool doesn't take the conversation / subagent loop down
    with it; pair it with :func:`make_stub_tool` (``success=False``) to
    also cover the "tool returned a clean failure" branch.
    """
    error = exc if exc is not None else RuntimeError(f"{name} crashed")
    desc = description if description is not None else f"Raising stub tool {name}"
    schema = parameters if parameters is not None else {"type": "object", "properties": {}}

    class _RaisingTool(Tool):
        @property
        def name(self) -> str:
            return name

        @property
        def description(self) -> str:
            return desc

        @property
        def parameters(self) -> dict[str, Any]:
            return schema

        async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
            raise error

    return _RaisingTool()
