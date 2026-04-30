"""``if:`` filter expression compiler and evaluator.

Hooks can declare a tiny boolean expression ("if": "tool == 'git_push'")
that is evaluated against the event payload before the hook fires.  The
language is intentionally small — comparisons, boolean combinators,
attribute / subscript access, list / tuple literals — so a misconfigured
hook can't shell out, read files, or loop.

Validation (``_validate_ast``) runs at config-load time so bad
expressions surface in ``_parse_hook`` with a clear pointer to the
config line, not at fire-time when the operator is already waiting.
"""

from __future__ import annotations

import ast
from typing import Any

from cantrip.hooks.types import HookConfigError


# Sentinel returned by the filter evaluator when a payload field is
# missing.  Compared with ``==`` / ``in`` it yields ``False``, so a
# filter like ``task.category == "BUILD"`` against a payload without a
# ``task`` field simply skips the hook rather than raising — far more
# useful when events have heterogeneous payloads.
class _Missing:
    """Truthy-false sentinel for absent payload fields."""

    __slots__ = ()
    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return other is self

    def __ne__(self, other: object) -> bool:
        return other is not self

    def __contains__(self, _: object) -> bool:
        return False

    def __iter__(self):
        return iter(())

    def __getattr__(self, _name: str) -> _Missing:
        return self

    def __getitem__(self, _key: object) -> _Missing:
        return self

    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()


# AST node types allowed in ``if:`` expressions.  Function calls,
# lambdas, comprehensions, etc. are rejected at compile time — the
# expression language is intentionally small so a misconfigured hook
# can't shell out, read files, or loop.
_ALLOWED_AST_NODES = frozenset(
    {
        ast.Expression,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Attribute,
        ast.Subscript,
        ast.List,
        ast.Tuple,
    }
)


class _FilterExpr:
    """Compiled ``if:`` filter evaluated against an event payload.

    Stores the original source for diagnostics plus the pre-parsed AST
    so ``matches()`` is fast on the hot path.  All validation happens
    at compile time — bad expressions fail in ``_parse_hook`` with a
    clear error that points at the config line, not at fire-time when
    the operator is already waiting on a tool call.
    """

    __slots__ = ("source", "_tree")

    def __init__(self, source: str):
        self.source = source
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as exc:
            raise HookConfigError(f"invalid `if:` expression {source!r}: {exc.msg}") from exc
        _validate_ast(tree, source)
        self._tree = tree

    def matches(self, payload: dict[str, Any]) -> bool:
        """Return True when the filter accepts *payload*.

        Evaluation failures (missing keys, comparison-to-missing,
        unsupported operand types) resolve to False so a filter that
        references a key an event doesn't carry simply skips the hook
        rather than raising.
        """
        try:
            value = _eval_node(self._tree.body, payload)
        except (KeyError, AttributeError, TypeError):
            return False
        return bool(value) and value is not _MISSING


def _validate_ast(tree: ast.AST, source: str) -> None:
    """Walk *tree* and reject any node type outside the allowlist."""
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_AST_NODES:
            raise HookConfigError(
                f"disallowed expression element in `if:` {source!r}: {type(node).__name__}"
            )


def _eval_node(node: ast.AST, payload: dict[str, Any]) -> Any:
    """Recursively evaluate a validated AST node against *payload*.

    Only called on trees that survived ``_validate_ast``, so the match
    is exhaustive for the allowed node set — any unexpected type here
    is a validator bug, not a user input.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return payload.get(node.id, _MISSING)
    if isinstance(node, ast.Attribute):
        parent = _eval_node(node.value, payload)
        if isinstance(parent, dict):
            return parent.get(node.attr, _MISSING)
        if parent is _MISSING:
            return _MISSING
        return getattr(parent, node.attr, _MISSING)
    if isinstance(node, ast.Subscript):
        parent = _eval_node(node.value, payload)
        key = _eval_node(node.slice, payload)
        if parent is _MISSING or key is _MISSING:
            return _MISSING
        try:
            return parent[key]
        except (KeyError, IndexError, TypeError):
            return _MISSING
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, payload)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v, payload) for v in node.values)
        return any(_eval_node(v, payload) for v in node.values)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, payload)
        for op, right_node in zip(node.ops, node.comparators, strict=True):
            right = _eval_node(right_node, payload)
            if not _apply_comparison(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(elt, payload) for elt in node.elts]
    raise TypeError(f"unevaluatable node: {type(node).__name__}")


def _apply_comparison(op: ast.cmpop, left: Any, right: Any) -> bool:
    """Apply one comparison operator with missing-safe semantics."""
    if left is _MISSING or right is _MISSING:
        # Eq / NotEq against a missing sentinel compare correctly; all
        # other comparisons against missing are False so ordering ops
        # don't raise TypeError on ``None``.
        if isinstance(op, ast.Eq):
            return left is right
        if isinstance(op, ast.NotEq):
            return left is not right
        if isinstance(op, (ast.In, ast.NotIn)):
            return isinstance(op, ast.NotIn)
        return False
    try:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.In):
            return left in right
        if isinstance(op, ast.NotIn):
            return left not in right
    except TypeError:
        return False
    return False
