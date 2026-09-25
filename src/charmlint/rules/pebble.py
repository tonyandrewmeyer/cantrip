"""Pebble layer rules.

The ``custom-charm`` skill's K8s subsection recites three Pebble
contracts the agent currently re-derives every turn:

1. ``container.add_layer(name, layer, combine=True)`` — without
   ``combine=True``, repeated calls stack duplicates instead of
   merging.
2. Pebble methods must be guarded by ``container.can_connect()``;
   without the guard a hook can hit ``ConnectionError`` early in
   the unit's lifecycle.
3. Each service entry in a Pebble layer needs ``override``,
   ``command``, and ``startup``.

This module ships the static checks for all three.  The handler
detection is per-function to mirror the relation-data rules, widened
by a call-graph pass so a guard in the caller covers the helpers it
calls; the service-dict scan walks every dict literal in src/ source
so it catches layers built inline as well as via helper methods.
"""

import ast
import collections
import pathlib

from .. import models
from . import Rule

# Pebble methods that need a can_connect guard.
_PEBBLE_CALLS = frozenset({"add_layer", "replan", "restart", "start", "stop", "autostart", "exec"})


def _function_segments(
    sources: dict[pathlib.Path, str],
) -> list[tuple[pathlib.Path, ast.FunctionDef, str]]:
    """Yield ``(path, FunctionDef, source-text)`` for every function in src/."""
    out: list[tuple[pathlib.Path, ast.FunctionDef, str]] = []
    for path, content in sources.items():
        if "lib" in path.parts:
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                segment = ast.get_source_segment(content, node)
                if segment:
                    out.append((path, node, segment))
    return out


def _locally_guarded(func: ast.FunctionDef, source: str) -> bool:
    """Whether this function body carries its own ``can_connect()`` guard."""
    if "can_connect" in source:
        return True
    # The pebble_ready handler is called *because* connect succeeded —
    # the framework has done the guard for us.
    return "pebble_ready" in func.name or "PebbleReady" in source


def _called_names(func: ast.FunctionDef) -> set[str]:
    """Names of the callables invoked from this function's body."""
    names: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _reachable(callees: dict[str, set[str]], roots: set[str]) -> set[str]:
    """Names reachable from ``roots`` by following call edges."""
    seen: set[str] = set()
    pending = collections.deque(roots)
    while pending:
        for callee in callees[pending.popleft()]:
            if callee not in seen:
                seen.add(callee)
                pending.append(callee)
    return seen


def _unguarded_names(
    segments: list[tuple[pathlib.Path, ast.FunctionDef, str]],
) -> set[str]:
    """Names of the charm's functions that can run without a Pebble guard.

    Per-function analysis alone reports a false positive on the common
    "guard once in ``_reconcile``, then call helpers" shape: the helper
    carries no guard of its own but only ever runs after one.  Resolving
    that needs the charm's call graph, so build one keyed by function
    name — the AST carries no type information, so ``self._migrate(...)``
    can only be matched by attribute name — and call a function exposed
    unless a guard covers every route to it.

    A function is exposed when no guarded function reaches it at all
    (nothing in the charm calls it, so the framework dispatches it
    directly; or it sits in a recursive knot with no guarded entry
    point), or when any of its callers is itself exposed.  Everything
    else runs only downstream of a guard and passes.
    """
    names = {func.name for _, func, _ in segments}
    guarded = {func.name for _, func, source in segments if _locally_guarded(func, source)}
    # A name defined twice counts as guarded only when every definition
    # guards, so one unguarded namesake cannot hide behind its sibling.
    guarded -= {func.name for _, func, source in segments if not _locally_guarded(func, source)}

    callees: dict[str, set[str]] = collections.defaultdict(set)
    for _, func, _ in segments:
        for callee in _called_names(func) & names:
            if callee != func.name:  # Recursion is not a route in from elsewhere.
                callees[func.name].add(callee)

    covered = _reachable(callees, guarded)
    unguarded = names - guarded - covered
    pending = collections.deque(unguarded)
    while pending:
        for callee in callees[pending.popleft()]:
            if callee in guarded or callee in unguarded:
                continue
            unguarded.add(callee)
            pending.append(callee)
    return unguarded


def _string_key(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _has_kwarg(call: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in call.keywords)


class PebbleAddLayerNoCombine(Rule):
    """Flag ``add_layer(...)`` calls missing ``combine=True``."""

    id = "PEB001"
    name = "pebble-add-layer-no-combine"
    description = "container.add_layer() called without combine=True"
    default_severity = models.Severity.WARNING

    def check(self, context: models.CharmContext) -> list[models.Diagnostic]:
        diagnostics: list[models.Diagnostic] = []
        for path, content in context.python_sources.items():
            if "lib" in path.parts:
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_layer"
                ):
                    continue
                if _has_kwarg(node, "combine"):
                    continue
                diagnostics.append(
                    self.diagnostic(
                        "add_layer() called without combine=True — repeated calls "
                        "stack duplicate layers instead of merging",
                        path=str(path),
                        line=node.lineno,
                        fix_hint="Pass `combine=True` so calls merge into the existing layer",
                    )
                )
        return diagnostics


class PebbleCallWithoutCanConnect(Rule):
    """Flag Pebble methods reachable without a can_connect guard.

    A guard in a caller counts: see :func:`_unguarded_names` for how
    the charm's call graph decides which functions are exposed.
    """

    id = "PEB002"
    name = "pebble-call-without-can-connect"
    description = "Pebble method reachable with no can_connect() guard on any route to it"
    default_severity = models.Severity.WARNING

    def check(self, context: models.CharmContext) -> list[models.Diagnostic]:
        diagnostics: list[models.Diagnostic] = []
        segments = _function_segments(context.python_sources)
        unguarded = _unguarded_names(segments)
        for path, func, source in segments:
            if _locally_guarded(func, source) or func.name not in unguarded:
                continue
            for node in ast.walk(func):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _PEBBLE_CALLS
                ):
                    continue
                diagnostics.append(
                    self.diagnostic(
                        f"Function '{func.name}' calls .{node.func.attr}() with no "
                        "can_connect() guard — early hooks may raise ConnectionError",
                        path=str(path),
                        line=func.lineno,
                        fix_hint=(
                            "Add `if not container.can_connect(): event.defer(); return` "
                            "or hoist the call into the pebble_ready handler"
                        ),
                    )
                )
                break  # One diagnostic per function is enough.
        return diagnostics


def _service_dict_keys(service_node: ast.expr) -> set[str] | None:
    """Return the string-keyed entries of an AST Dict, else ``None``."""
    if not isinstance(service_node, ast.Dict):
        return None
    keys: set[str] = set()
    for key_node in service_node.keys:
        if key_node is None:
            continue
        key = _string_key(key_node)
        if key is not None:
            keys.add(key)
    return keys


def _iter_service_entries(dict_node: ast.Dict) -> list[tuple[str, ast.expr]]:
    """For a layer Dict that has a ``services`` key, return ``(svc_name, svc_node)``."""
    entries: list[tuple[str, ast.expr]] = []
    for key_node, value_node in zip(dict_node.keys, dict_node.values, strict=False):
        if key_node is None:
            continue
        if _string_key(key_node) != "services":
            continue
        if not isinstance(value_node, ast.Dict):
            continue
        for svc_key, svc_value in zip(value_node.keys, value_node.values, strict=False):
            if svc_key is None:
                continue
            name = _string_key(svc_key)
            if name is not None:
                entries.append((name, svc_value))
    return entries


_REQUIRED_SERVICE_KEYS = ("override", "command", "startup")


class PebbleLayerServiceMissingKeys(Rule):
    """Flag Pebble layer service dicts missing override/command/startup."""

    id = "PEB003"
    name = "pebble-layer-service-missing-keys"
    description = "Pebble layer service entry missing required key (override/command/startup)"
    default_severity = models.Severity.WARNING

    def check(self, context: models.CharmContext) -> list[models.Diagnostic]:
        diagnostics: list[models.Diagnostic] = []
        for path, content in context.python_sources.items():
            if "lib" in path.parts:
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for svc_name, svc_node in _iter_service_entries(node):
                    keys = _service_dict_keys(svc_node)
                    if keys is None:
                        continue
                    missing = [k for k in _REQUIRED_SERVICE_KEYS if k not in keys]
                    if not missing:
                        continue
                    diagnostics.append(
                        self.diagnostic(
                            f"Pebble service '{svc_name}' is missing required key(s): "
                            f"{', '.join(missing)}",
                            path=str(path),
                            line=svc_node.lineno,
                            fix_hint=(
                                "Pebble services need `override` (replace/merge), "
                                "`command`, and `startup` (enabled/disabled) at minimum"
                            ),
                        )
                    )
        return diagnostics
