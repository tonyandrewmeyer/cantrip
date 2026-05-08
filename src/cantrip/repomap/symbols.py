"""Symbol extraction — Python ``ast`` for code, ``pyyaml`` for charm metadata.

Stdlib ``ast`` is enough for the Python side and avoids adding
``tree-sitter``; PyYAML is already a dependency.  Each parsed file
produces a :class:`FileSymbols` with ``definitions`` (names this file
introduces) and ``references`` (names this file mentions).  The graph
layer then connects references to definitions across files.
"""

from __future__ import annotations

import ast
import dataclasses
import enum
import logging
import pathlib
from typing import Any

import yaml

log = logging.getLogger(__name__)


class SymbolKind(enum.StrEnum):
    """What kind of definition a symbol represents."""

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CONFIG_OPTION = "config-option"
    ACTION = "action"
    RELATION = "relation"
    CONTAINER = "container"
    STORAGE = "storage"
    RESOURCE = "resource"


@dataclasses.dataclass(frozen=True)
class Symbol:
    """A named definition in the repository.

    ``signature`` is a one-line representation (parenthesised parameters
    for callables, ``: type`` for typed values, an interface name for
    relations).  ``line`` is 1-based; for synthetic (YAML-derived)
    symbols it points at the YAML key's line when available, else 0.
    """

    name: str
    kind: SymbolKind
    file: str
    line: int = 0
    signature: str = ""
    qualifier: str = ""  # e.g. enclosing class name for methods.

    @property
    def display_name(self) -> str:
        """Human-readable identifier including any qualifier."""
        if self.qualifier:
            return f"{self.qualifier}.{self.name}"
        return self.name


@dataclasses.dataclass(frozen=True)
class ReferenceLocation:
    """One reference site: ``name`` mentioned at ``file:line``.

    Populated by the Python visitor alongside :attr:`FileSymbols.references`
    so the codeintel layer can answer ``find_references`` without
    re-parsing.  Multiplicity matches ``references`` — a name mentioned
    ten times produces ten ``ReferenceLocation`` entries.  YAML-derived
    references stay in ``references`` only; YAML reference lines need
    a position-aware loader and are out of scope until a use case
    appears.
    """

    name: str
    file: str
    line: int  # 1-based; 0 when the parser cannot recover a position.


@dataclasses.dataclass
class FileSymbols:
    """Symbols extracted from one source file."""

    file: str
    definitions: list[Symbol] = dataclasses.field(default_factory=list)
    # Names this file mentions (calls, attribute access, references).
    # Multiplicity is preserved so a name referenced ten times weighs
    # ten times more than a name referenced once when the graph layer
    # builds edges.
    references: list[str] = dataclasses.field(default_factory=list)
    # Per-reference locations.  Aligned with ``references`` for Python
    # parses (one entry per name occurrence, in source order); empty
    # for YAML parses where line attribution would need a custom
    # loader.  Consumers that only want PageRank input keep using
    # ``references``; the codeintel layer reads ``reference_locations``.
    reference_locations: list[ReferenceLocation] = dataclasses.field(default_factory=list)
    # Imported-name aliases recovered from ``import`` / ``from … import …``
    # statements: ``alias`` -> ``original``.  ``import foo as f`` records
    # ``f -> foo``; ``from x import bar as b`` records ``b -> bar``.
    # Used by codeintel to resolve a query like ``f.thing()`` back to
    # the qualified ``foo.thing`` definition.  YAML parses leave this
    # empty.
    import_aliases: dict[str, str] = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------------------
# Python source extraction
# ---------------------------------------------------------------------------


def parse_python_file(path: pathlib.Path, *, repo_root: pathlib.Path) -> FileSymbols:
    """Parse one Python file and return its definitions + references.

    Returns an empty :class:`FileSymbols` if the file cannot be read or
    fails to parse — repo-map is best-effort and never blocks a turn
    on a syntax error in the user's code.
    """
    rel = _relative(path, repo_root)
    try:
        # Read bytes so ``ast.parse`` honours PEP 263 coding cookies and
        # BOMs.  ``read_text(encoding="utf-8")`` would raise on any
        # legitimate non-utf-8 file and the symbols would silently
        # vanish from the rank.
        source = path.read_bytes()
    except OSError as exc:
        log.debug("repomap: cannot read %s: %s", path, exc)
        return FileSymbols(file=rel)
    try:
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, ValueError) as exc:
        log.debug("repomap: cannot parse %s: %s", path, exc)
        return FileSymbols(file=rel)

    visitor = _PythonVisitor(file=rel)
    visitor.visit(tree)
    return FileSymbols(
        file=rel,
        definitions=visitor.definitions,
        references=visitor.references,
        reference_locations=visitor.reference_locations,
        import_aliases=dict(visitor.import_aliases),
    )


class _PythonVisitor(ast.NodeVisitor):
    """Collect top-level classes, methods, free functions, and references.

    Nested functions defined inside another function are skipped — they
    rarely matter for a bird's-eye view and surfacing them would dilute
    the map.  Methods are emitted with the enclosing class as the
    qualifier so the rendered map reads ``MyCharm._on_install`` rather
    than the bare method name.
    """

    def __init__(self, file: str) -> None:
        self.file = file
        self.definitions: list[Symbol] = []
        self.references: list[str] = []
        self.reference_locations: list[ReferenceLocation] = []
        self.import_aliases: dict[str, str] = {}
        self._class_stack: list[str] = []
        self._inside_function = False

    def _record_reference(self, name: str, lineno: int) -> None:
        """Capture a single reference name + its source line.

        Multiplicity matters for the PageRank graph (more refs = more
        weight) so duplicates are kept.  ``lineno`` is whatever ``ast``
        attaches to the call/attribute node — 1-based, never zero on a
        successful parse.
        """
        if not name:
            return
        self.references.append(name)
        self.reference_locations.append(ReferenceLocation(name=name, file=self.file, line=lineno))

    # -- definitions --------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 — ast naming
        bases = [_unparse(b) for b in node.bases]
        signature = f"({', '.join(bases)})" if bases else ""
        self.definitions.append(
            Symbol(
                name=node.name,
                kind=SymbolKind.CLASS,
                file=self.file,
                line=node.lineno,
                signature=signature,
            )
        )
        # Track inheritance as a reference so subclasses pull their
        # bases up the rank.  Each base name counts once.
        for base in node.bases:
            self._record_reference(_root_name(base), base.lineno)
        self._class_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._record_function(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self._inside_function:
            # Nested function — body still walked for references but
            # no definition emitted.
            for child in node.body:
                self.visit(child)
            return
        signature = _format_arguments(node.args)
        if node.returns is not None:
            signature = f"{signature} -> {_unparse(node.returns)}"
        if self._class_stack:
            kind = SymbolKind.METHOD
            qualifier = ".".join(self._class_stack)
        else:
            kind = SymbolKind.FUNCTION
            qualifier = ""
        self.definitions.append(
            Symbol(
                name=node.name,
                kind=kind,
                file=self.file,
                line=node.lineno,
                signature=signature,
                qualifier=qualifier,
            )
        )
        prev = self._inside_function
        self._inside_function = True
        for child in node.body:
            self.visit(child)
        self._inside_function = prev

    # -- references ---------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        ref = _root_name(node.func)
        if ref:
            self._record_reference(ref, node.lineno)
        # Surface the leaf attribute too — `self.framework.observe(...)`
        # should reference ``observe`` so charmlib helpers rank.
        leaf = _leaf_attr(node.func)
        if leaf and leaf != ref:
            self._record_reference(leaf, node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # Only surface the attribute as a reference when it's read
        # standalone (not the ``func`` of a Call we already handled).
        # ``ast`` doesn't tell us the parent here, so we accept some
        # double counting — the rank is comparative anyway.
        self._record_reference(node.attr, node.lineno)
        self.generic_visit(node)

    # -- imports ------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            # ``import foo`` — alias.name="foo", alias.asname=None.
            # ``import foo as f`` — alias.name="foo", alias.asname="f".
            # Keep the leftmost dotted segment (``foo`` from ``foo.bar``)
            # so attribute access through the import root resolves cleanly.
            head = alias.name.split(".", 1)[0]
            local = alias.asname or head
            if local != alias.name:
                self.import_aliases[local] = alias.name
            # Treat the import as a reference too so ``import foo`` lets
            # find_references locate the import site of ``foo``.
            self._record_reference(head, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            qualified = f"{module}.{alias.name}" if module else alias.name
            if local != alias.name or alias.asname is not None:
                self.import_aliases[local] = qualified
            # Record both the local binding and the imported symbol so
            # ``from foo import Bar`` lets find_references locate both.
            self._record_reference(alias.name, node.lineno)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Charm-metadata YAML extraction
# ---------------------------------------------------------------------------

# Recognised charm-metadata files.  ``charmcraft.yaml`` is the modern
# unified format; the others are legacy / split surfaces still seen on
# many charms.
_METADATA_FILES = {
    "charmcraft.yaml",
    "metadata.yaml",
    "config.yaml",
    "actions.yaml",
}


def parse_charm_metadata(path: pathlib.Path, *, repo_root: pathlib.Path) -> FileSymbols:
    """Extract relations, config options, actions, etc. from a charm YAML."""
    rel = _relative(path, repo_root)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        log.debug("repomap: cannot load %s: %s", path, exc)
        return FileSymbols(file=rel)
    if not isinstance(data, dict):
        return FileSymbols(file=rel)

    definitions: list[Symbol] = []
    references: list[str] = []

    # ``charmcraft.yaml`` may nest config under a ``config`` key while
    # ``config.yaml`` puts the same shape at the top level — handle both.
    config_block = _select(data, ("config",))
    if isinstance(config_block, dict):
        options = config_block.get("options", config_block)
        _emit_keyed(
            options, SymbolKind.CONFIG_OPTION, rel, definitions, kind_label="config option"
        )

    actions_block = data.get("actions") if path.name != "actions.yaml" else data
    _emit_keyed(actions_block, SymbolKind.ACTION, rel, definitions, kind_label="action")

    for relation_role in ("requires", "provides", "peers"):
        block = data.get(relation_role)
        if not isinstance(block, dict):
            continue
        for endpoint, body in block.items():
            interface = ""
            if isinstance(body, dict):
                interface = str(body.get("interface", ""))
            sig = f": {interface}" if interface else ""
            definitions.append(
                Symbol(
                    name=str(endpoint),
                    kind=SymbolKind.RELATION,
                    file=rel,
                    signature=sig,
                    qualifier=relation_role,
                )
            )
            if interface:
                references.append(interface)

    _emit_keyed(data.get("containers"), SymbolKind.CONTAINER, rel, definitions)
    _emit_keyed(data.get("storage"), SymbolKind.STORAGE, rel, definitions)
    _emit_keyed(data.get("resources"), SymbolKind.RESOURCE, rel, definitions)

    return FileSymbols(file=rel, definitions=definitions, references=references)


def is_charm_metadata(path: pathlib.Path) -> bool:
    """True if *path* is a charm-metadata YAML we know how to parse."""
    return path.name in _METADATA_FILES


def _emit_keyed(
    block: Any,
    kind: SymbolKind,
    file: str,
    sink: list[Symbol],
    *,
    kind_label: str = "",
) -> None:
    """Append one symbol per top-level key of *block*.

    No-op when *block* isn't a dict — charm authors do leave these
    sections empty or commented out.
    """
    del kind_label  # currently unused; reserved for future signature text
    if not isinstance(block, dict):
        return
    for key, body in block.items():
        sig = ""
        if isinstance(body, dict):
            type_str = body.get("type")
            if type_str:
                sig = f": {type_str}"
        sink.append(Symbol(name=str(key), kind=kind, file=file, signature=sig))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _relative(path: pathlib.Path, root: pathlib.Path) -> str:
    """Return ``path`` relative to ``root`` as a forward-slash string."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return ""


def _root_name(node: ast.AST) -> str:
    """Return the leftmost name in ``foo.bar.baz`` chains."""
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _leaf_attr(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _select(data: dict, keys: tuple[str, ...]) -> Any:
    cur: Any = data
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _format_arguments(args: ast.arguments) -> str:
    """Render an ``ast.arguments`` as a parenthesised parameter list."""
    parts: list[str] = []
    posonly = list(args.posonlyargs)
    pos = list(args.args)
    defaults = list(args.defaults)
    # Defaults align with the *trailing* portion of posonly+pos.
    n_with_defaults = len(defaults)
    fixed = posonly + pos
    n_no_default = len(fixed) - n_with_defaults
    for i, arg in enumerate(fixed):
        rendered = _format_arg(arg)
        if i >= n_no_default:
            default = defaults[i - n_no_default]
            rendered = f"{rendered}={_unparse(default)}"
        parts.append(rendered)
        if i == len(posonly) - 1 and posonly:
            parts.append("/")
    if args.vararg is not None:
        parts.append(f"*{_format_arg(args.vararg)}")
    elif args.kwonlyargs:
        parts.append("*")
    for kw, kd in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        rendered = _format_arg(kw)
        if kd is not None:
            rendered = f"{rendered}={_unparse(kd)}"
        parts.append(rendered)
    if args.kwarg is not None:
        parts.append(f"**{_format_arg(args.kwarg)}")
    return f"({', '.join(parts)})"


def _format_arg(arg: ast.arg) -> str:
    if arg.annotation is not None:
        return f"{arg.arg}: {_unparse(arg.annotation)}"
    return arg.arg
