"""Shared helpers and imports for the Juju tool sub-package.

Every tool submodule references the patchable helpers and modules
*through this module object* (e.g. ``_common._run_juju``,
``_common.jubilant.Juju``) so that ``mock.patch`` against
``cantrip.agent.tools.juju._common.<name>`` affects all call sites.
"""

import asyncio
import functools
import json
import os
import pathlib
import re
import shlex
import shutil
from collections.abc import Callable
from typing import Any

import jubilant

from cantrip import diagnostics
from cantrip.agent.safety.controller_safety import controller_confirm_required
from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju_subprocess import (
    juju_available as _juju_available,
)
from cantrip.agent.tools.juju_subprocess import (
    juju_version as _juju_version,
)
from cantrip.agent.tools.juju_subprocess import (
    looks_like_juju_crash as _looks_like_juju_crash,
)

# Re-exported names that callers reference via the module object.  The
# imports above are deliberately kept even when this module does not use
# them directly, so submodules can write ``_common.jubilant`` etc.
__all__ = [
    "Tool",
    "ToolResult",
    "asyncio",
    "controller_confirm_required",
    "diagnostics",
    "functools",
    "json",
    "jubilant",
    "os",
    "pathlib",
    "re",
    "shlex",
    "shutil",
    "_JUJU_TIMEOUT",
    "_agent_charm_dir",
    "_is_k8s_model",
    "_juju_available",
    "_juju_version",
    "_looks_like_juju_crash",
    "_maybe_dump_juju_crash",
    "_run_juju",
]

# Default timeout for Jubilant operations (seconds).
_JUJU_TIMEOUT = 120


def _maybe_dump_juju_crash(context: str, exc: jubilant.CLIError) -> None:
    """Write a crash dump when a Jubilant CLIError looks crash-shaped.

    Side effect on ``$XDG_STATE_HOME/cantrip/diagnostics.log``; the
    exception is left for the caller to surface as usual.  A no-op
    for normal "model doesn't exist"-style failures.
    """
    stderr = exc.stderr or ""
    if not _looks_like_juju_crash(exc.returncode, stderr):
        return
    extra: dict[str, str] = {}
    version = _juju_version()
    if version:
        extra["juju_version"] = version
    diagnostics.report_command_crash(
        context=context,
        cmd=exc.cmd,
        returncode=exc.returncode,
        stdout=exc.stdout or "",
        stderr=stderr,
        extra=extra or None,
    )


async def _run_juju(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a blocking Jubilant call in a thread with a timeout.

    Prevents a hung Juju CLI from blocking the entire event loop.
    Writes a crash dump to ``diagnostics.log`` when Jubilant raises a
    crash-shaped ``CLIError`` so the user has full upstream-repro
    material even after the conversation context rolls over.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(functools.partial(func, *args, **kwargs)),
            timeout=_JUJU_TIMEOUT,
        )
    except jubilant.CLIError as exc:
        context = getattr(func, "__name__", None) or "juju"
        _maybe_dump_juju_crash(f"jubilant:{context}", exc)
        raise


def _agent_charm_dir(unit: str) -> str:
    """Convert a unit name like ``my-app/0`` to its on-disk charm directory.

    Raises ``ValueError`` if the unit name is not in ``app/number`` format.
    """
    parts = unit.split("/")
    if len(parts) != 2 or not parts[1].isdigit():
        raise ValueError(f"Invalid unit name '{unit}'. Expected format: 'app-name/0'")
    return f"/var/lib/juju/agents/unit-{parts[0]}-{parts[1]}/charm"


async def _is_k8s_model(juju: jubilant.Juju) -> bool:
    """Return True if the current model is a Kubernetes (CAAS) model."""
    info = await _run_juju(juju.show_model)
    return info.model_type == "caas"
