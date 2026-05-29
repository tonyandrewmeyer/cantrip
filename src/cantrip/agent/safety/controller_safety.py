"""Controller-safety classification and confirm-gate helpers.

Phase 10b safety patch.  Charm-improvement and other agent flows can
deploy via ``jubilant.Juju()`` against the *current* Juju controller —
whichever the local ``juju`` CLI defaults to.  If that's a production
controller (registered earlier with ``juju register`` for an unrelated
purpose, then left as default), the agent will mutate state without
warning.  The helpers here classify a controller as local, non-local,
or unknown, and produce a small ``(blocked, message)`` gate that
mutating tools call before executing so the LLM is forced to surface
the target controller to the operator and ask for confirmation.

Two classification axes:

* *Heuristic.*  Cloud type ``localhost`` / ``lxd`` is always local.
  ``microk8s`` / ``k8s`` are local only when the controller's API
  endpoints point at loopback (``127.0.0.1``, ``[::1]``, ``localhost``)
  or a snap-managed socket (e.g. ``/var/snap/microk8s/...``).  Anything
  else flips a "non-local" flag.
* *Explicit list.*  A ``production_controllers: [str]`` field in
  ``~/.config/cantrip/settings.json`` lets the operator name controllers
  that should always require confirm regardless of cloud type.  Belt-
  and-braces with the heuristic for cases where the heuristic
  under-classifies (a remote controller on a private network that
  *looks* local, for example).

The gate composes both: a controller hits the gate when *either* axis
says non-local.  Production-list matches escalate the message language
so the operator notices what they are about to touch.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import pathlib
from typing import Any

from cantrip.agent.preflight import _K8S_CLOUDS, _run_juju_json

log = logging.getLogger(__name__)

# Mirrors update.py's settings location.  Settings are flat JSON keys;
# there is no schema layer, so each consumer reads its own keys.
_SETTINGS_PATH = pathlib.Path("~/.config/cantrip/settings.json")

# Cloud types that are always local — concierge / LXD bootstrap or a
# manual ``juju bootstrap localhost`` landed them.
_LOCAL_CLOUDS: frozenset[str] = frozenset({"localhost", "lxd"})

# Substrings that mark a Kubernetes controller's API endpoint as local.
# Loopback addresses cover ``juju bootstrap k8s`` against a local
# cluster; the snap socket covers microk8s bootstrapped against the
# local snap-managed cluster.
_LOCAL_K8S_HINTS: tuple[str, ...] = (
    "127.0.0.1",
    "[::1]",
    "localhost",
    "/var/snap/microk8s/",
)


class ControllerKind(enum.StrEnum):
    """Whether a controller looks safe for unsupervised mutation."""

    LOCAL = "local"
    NON_LOCAL = "non_local"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class ControllerSafety:
    """Result of classifying a target controller."""

    name: str | None
    cloud: str
    kind: ControllerKind
    in_production_list: bool

    @property
    def confirm_required(self) -> bool:
        """True when the controller should not be touched without confirm."""
        return self.kind is ControllerKind.NON_LOCAL or self.in_production_list


def production_controllers() -> list[str]:
    """Read the operator-supplied production-controller list.

    Returns the names listed under ``production_controllers`` in
    ``~/.config/cantrip/settings.json``, or an empty list when the file
    is absent, malformed, or the key is missing.  A malformed file is
    not an error — it just means the explicit-list axis falls silent
    and the heuristic alone decides.
    """
    path = _SETTINGS_PATH.expanduser()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.debug(
            "Could not parse %s — ignoring production_controllers list",
            path,
            exc_info=True,
        )
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("production_controllers", [])
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, str)]


def classify_controller(info: dict[str, Any]) -> ControllerKind:
    """Classify a controller from a flat ``{cloud, api-endpoints}`` dict.

    Callers flatten ``juju show-controller`` output to this shape so
    the classifier itself stays unaware of the JSON envelope.
    """
    cloud = info.get("cloud", "")
    api_endpoints = info.get("api-endpoints") or []
    if cloud in _LOCAL_CLOUDS:
        return ControllerKind.LOCAL
    if cloud in _K8S_CLOUDS:
        for endpoint in api_endpoints:
            if isinstance(endpoint, str) and any(hint in endpoint for hint in _LOCAL_K8S_HINTS):
                return ControllerKind.LOCAL
        return ControllerKind.NON_LOCAL
    if not cloud:
        return ControllerKind.UNKNOWN
    return ControllerKind.NON_LOCAL


def _controller_for_model(model: str | None) -> str | None:
    """Extract the controller name from ``ctrl:model`` syntax, if present."""
    if model and ":" in model:
        return model.split(":", 1)[0]
    return None


def current_controller_safety(model: str | None = None) -> ControllerSafety:
    """Inspect the current (or model-targeted) controller and classify it.

    ``model`` may be a plain name (uses the current controller) or a
    ``controller:model`` form (targets that controller explicitly).
    Returns :attr:`ControllerKind.UNKNOWN` when juju is missing or
    ``show-controller`` produces nothing usable — callers treat that
    as "do not gate", since blocking calls because of a missing CLI
    would break test environments where juju is intentionally absent.
    """
    target = _controller_for_model(model)
    args = ["show-controller"]
    if target:
        args.append(target)
    data = _run_juju_json(args, timeout=10)
    if not data:
        return ControllerSafety(
            name=target,
            cloud="",
            kind=ControllerKind.UNKNOWN,
            in_production_list=bool(target and target in production_controllers()),
        )
    name = next(iter(data.keys()), None)
    info = next(iter(data.values()), {})
    details = info.get("details", {}) if isinstance(info, dict) else {}
    flat = {
        "cloud": details.get("cloud", "") if isinstance(details, dict) else "",
        "api-endpoints": (details.get("api-endpoints", []) if isinstance(details, dict) else []),
    }
    kind = classify_controller(flat)
    in_production_list = bool(name and name in production_controllers())
    return ControllerSafety(
        name=name,
        cloud=flat["cloud"],
        kind=kind,
        in_production_list=in_production_list,
    )


def confirm_message(tool_name: str, safety: ControllerSafety) -> str:
    """Build the synthetic-error message a tool returns when refusing."""
    controller = safety.name or "unknown"
    cloud = safety.cloud or "unknown"
    if safety.in_production_list:
        header = (
            f"Refusing to run {tool_name!r} against **production controller** "
            f"{controller!r} (cloud={cloud!r}) without explicit operator approval."
        )
    else:
        header = (
            f"Refusing to run {tool_name!r} against non-local controller "
            f"{controller!r} (cloud={cloud!r}) without explicit operator approval."
        )
    return (
        f"{header}  Show the operator the target controller and ask them to "
        "confirm.  Re-call with ``confirmed=true`` once they approve."
    )


def controller_confirm_required(
    tool_name: str,
    *,
    model: str | None = None,
    confirmed: bool = False,
) -> tuple[bool, str]:
    """Tool-side gate: should this call be refused pending operator confirm?

    Returns ``(blocked, message)``.  When ``blocked`` is ``True``, the
    caller should return a synthetic error ``ToolResult`` with
    ``message`` as the error text and prompt the operator to confirm.
    When ``False``, the call may proceed unchanged.
    """
    if confirmed:
        return False, ""
    safety = current_controller_safety(model=model)
    if not safety.confirm_required:
        return False, ""
    return True, confirm_message(tool_name, safety)
