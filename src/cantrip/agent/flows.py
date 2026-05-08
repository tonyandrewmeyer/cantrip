"""Flow skills — Mermaid decision diagrams as walkable workflows (Phase 69.4).

A flow is a markdown file with YAML frontmatter (``type: flow`` is the
discriminator), a fenced ``mermaid`` block describing nodes and edges,
and ``%% <id>: <annotation>`` lines that tell the agent what to do at
each node.  The dispatcher hands the parsed diagram to the agent; the
agent walks the tree and announces branch decisions inline so the user
can follow its reasoning.

Distinct from neighbouring shapes:

* :mod:`cantrip.agent.skills` — knowledge bundles loaded into context.
* :mod:`cantrip.agent.recipes` — parameterised, retryable execution.
* :class:`Flow` — a *visual decision tree* the agent walks step by
  step.  Branches are selected by the agent; the runtime validates
  the diagram up front but does not enforce traversal.

The module owns:

1. The :class:`Flow`, :class:`FlowNode`, :class:`FlowEdge`,
   :class:`FlowAnnotation` dataclasses and :class:`NodeKind` enum.
2. :func:`parse_mermaid` — turns a fenced ``mermaid`` block into a
   structured graph.
3. :func:`load_flow_file` and :func:`discover_flows` — walk the
   bundled / user / repo roots and turn ``*.md`` files into validated
   :class:`Flow` objects.
4. :func:`render_flow_prompt` — composes the agent prompt that asks
   the agent to walk the flow.

Mermaid only in v1; D2 support is deferred behind a real authoring
need.  The roadmap explicitly notes "extend the existing schema with
one new ``type`` value", so the surface here matches Phase 33 skills'
frontmatter shape on the keys it shares (``name``, ``description``).
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import pathlib
import re

import yaml

log = logging.getLogger(__name__)


_FRONTMATTER_DELIMITER = "---"
_FRONTMATTER_KEYS: frozenset[str] = frozenset({"name", "description", "type"})

#: Discovery roots.  Sibling-of-SQLite layout matches recipes
#: (``.cantrip-recipes``) and the rest of the family — ``<charm>/.cantrip``
#: is the SQLite session file and a single path can't be both.
USER_CONFIG_FLOWS_DIR = pathlib.Path(".config") / "cantrip" / "flows"
REPO_FLOWS_DIR = pathlib.Path(".cantrip-flows")

#: Bundled flows ship inside the wheel at ``cantrip/flows/`` (sibling of
#: ``cantrip/recipes/`` and ``cantrip/skills/``).  The directory has no
#: ``__init__.py`` — it's content, not a Python package.
BUNDLED_FLOWS_DIR = pathlib.Path(__file__).resolve().parents[1] / "flows"


_VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class FlowError(ValueError):
    """Raised on flow parse, validation, or load failure."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class NodeKind(enum.StrEnum):
    """The shape Mermaid encodes at the node literal.

    * ``ACTION`` — square brackets ``id[label]`` — the agent does something.
    * ``DECISION`` — curly braces ``id{label}`` — the agent picks a branch.
    * ``TERMINAL`` — round brackets ``id(label)`` — the flow ends here.
      A flow may have multiple terminal nodes (e.g., success / abort).

    Other Mermaid shapes (stadium ``id([label])``, subroutine
    ``id[[label]]``, hexagon ``id{{label}}``, etc.) parse but fold into
    ``ACTION`` — v1 only distinguishes the three semantic kinds.
    """

    ACTION = "action"
    DECISION = "decision"
    TERMINAL = "terminal"


@dataclasses.dataclass(frozen=True, slots=True)
class FlowNode:
    """One node in a flow diagram."""

    id: str
    label: str
    kind: NodeKind = NodeKind.ACTION
    annotation: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class FlowEdge:
    """One directed transition between two nodes.

    ``label`` carries the branch name surfaced to decision nodes
    (``A -->|yes| B``); empty when the edge has no label
    (``A --> B``).
    """

    src: str
    dest: str
    label: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class Flow:
    """One loaded flow."""

    name: str
    description: str
    intro_prose: str
    diagram_source: str
    entry_node: str
    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...]
    source: pathlib.Path | None = None

    def node(self, node_id: str) -> FlowNode:
        """Return the node with *node_id*; raise ``KeyError`` on miss."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def outgoing(self, node_id: str) -> tuple[FlowEdge, ...]:
        """Edges leaving *node_id*, in declaration order."""
        return tuple(edge for edge in self.edges if edge.src == node_id)


# ---------------------------------------------------------------------------
# Mermaid parser
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(
    r"```mermaid\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)

# Node literal patterns.  Order matters — match the bracket-shape
# variants before the bare ``id`` form so ``id[label]`` is not parsed
# as ``id`` followed by a stray bracket.
_NODE_PATTERNS: tuple[tuple[NodeKind, re.Pattern[str]], ...] = (
    (NodeKind.ACTION, re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\[([^\]\n]+)\]\s*$")),
    (NodeKind.DECISION, re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\{([^}\n]+)\}\s*$")),
    (NodeKind.TERMINAL, re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\(([^)\n]+)\)\s*$")),
)

# Edge with optional label: ``A -->|yes| B`` or ``A --> B``.
_EDGE_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)"
    r"\s*-->"
    r"(?:\s*\|([^|\n]+)\|)?"
    r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*$"
)

# Annotation comment: ``%% <id>: <annotation>`` (one per line).  The
# Mermaid spec treats ``%%`` as a comment; using it for our annotations
# means a Mermaid renderer can still draw the diagram unchanged.
_ANNOTATION_RE = re.compile(r"^\s*%%\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")

_FLOWCHART_HEADER_RE = re.compile(r"^\s*flowchart\s+(LR|RL|TB|TD|BT)\s*$", re.IGNORECASE)


def extract_mermaid_block(body: str) -> str:
    """Return the contents of the first ``mermaid`` fenced block.

    Raises :class:`FlowError` when the body has zero or multiple
    Mermaid blocks — both shapes signal an authoring mistake (the
    diagram is the flow; ambiguity here is never benign).
    """
    matches = list(_FENCE_RE.finditer(body))
    if not matches:
        raise FlowError("no ```mermaid fenced block found in flow body")
    if len(matches) > 1:
        raise FlowError(
            f"multiple ```mermaid fenced blocks found "
            f"({len(matches)}); flows must have exactly one"
        )
    return matches[0].group("body")


def parse_mermaid(
    source: str,
) -> tuple[tuple[FlowNode, ...], tuple[FlowEdge, ...], dict[str, str]]:
    """Parse a Mermaid flowchart into nodes, edges, and annotations.

    Returns a 3-tuple: ordered nodes, ordered edges, and a
    ``{node_id: annotation}`` map.  The caller decides which checks
    to run — :func:`load_flow_file` runs the full validation slate.

    The parser is deliberately strict: it accepts a documented subset
    of Mermaid (flowchart with the three node shapes above and ``-->``
    edges) and refuses anything outside it with a clear line-prefixed
    error.  Saying yes to the full Mermaid grammar would invite
    silent rendering drift between Cantrip's prompt-time view of the
    diagram and a renderer's view.
    """
    nodes_by_id: dict[str, FlowNode] = {}
    edges: list[FlowEdge] = []
    annotations: dict[str, str] = {}

    saw_header = False
    for line_no, raw in enumerate(source.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if not saw_header and _FLOWCHART_HEADER_RE.match(stripped):
            saw_header = True
            continue

        ann = _ANNOTATION_RE.match(stripped)
        if ann is not None:
            node_id = ann.group(1)
            text = ann.group(2)
            if node_id in annotations:
                raise FlowError(f"line {line_no}: duplicate annotation for node {node_id!r}")
            annotations[node_id] = text
            continue

        # Plain ``%%`` comments without ``id:`` are accepted and skipped
        # so the diagram can still carry standard Mermaid commentary.
        if stripped.startswith("%%"):
            continue

        edge = _EDGE_RE.match(stripped)
        if edge is not None:
            src, label, dest = edge.group(1), edge.group(2) or "", edge.group(3)
            edges.append(FlowEdge(src=src, dest=dest, label=label.strip()))
            continue

        matched_node: FlowNode | None = None
        for kind, pattern in _NODE_PATTERNS:
            node_match = pattern.match(stripped)
            if node_match is None:
                continue
            node_id, label = node_match.group(1), node_match.group(2).strip()
            if node_id in nodes_by_id:
                raise FlowError(f"line {line_no}: duplicate node {node_id!r}")
            matched_node = FlowNode(id=node_id, label=label, kind=kind)
            nodes_by_id[node_id] = matched_node
            break

        if matched_node is None:
            raise FlowError(
                f"line {line_no}: could not parse {stripped!r} — expected a "
                "flowchart header, a node literal "
                "(``id[label]`` / ``id{label}`` / ``id(label)``), an edge "
                "(``id --> id`` or ``id -->|label| id``), or an annotation "
                "(``%% id: text``)"
            )

    if not saw_header:
        raise FlowError("flow diagram is missing the ``flowchart TD`` header")

    return tuple(nodes_by_id.values()), tuple(edges), annotations


def _validate_graph(
    nodes: tuple[FlowNode, ...],
    edges: tuple[FlowEdge, ...],
    annotations: dict[str, str],
) -> tuple[FlowNode, ...]:
    """Apply the v1 well-formedness rules and stamp annotations onto nodes.

    Raises :class:`FlowError` on:

    * Empty graph (no nodes).
    * Edges that name an unknown node id.
    * Annotations that name an unknown node id.
    * A node missing an annotation (every node referenced by the
      diagram needs at least a one-line description so the agent
      knows what to do).
    * No entry node (every node has an incoming edge — i.e., a cycle
      with no clear start).
    * More than one entry node — flows have a single starting point.
    * A decision node with fewer than two outgoing edges.
    * A non-decision node with more than one outgoing edge — those
      shapes belong on a decision node (``id{...}``).
    """
    if not nodes:
        raise FlowError("flow diagram declares no nodes")
    node_ids = {node.id for node in nodes}

    for edge in edges:
        if edge.src not in node_ids:
            raise FlowError(f"edge {edge.src!r} -> {edge.dest!r} names unknown source node")
        if edge.dest not in node_ids:
            raise FlowError(f"edge {edge.src!r} -> {edge.dest!r} names unknown destination node")

    for ann_id in annotations:
        if ann_id not in node_ids:
            raise FlowError(f"annotation %% {ann_id}: ... names unknown node id")

    missing = [node.id for node in nodes if node.id not in annotations]
    if missing:
        raise FlowError(
            f"every node needs a ``%% <id>: <description>`` annotation; missing: {missing}"
        )

    incoming = {node.id: 0 for node in nodes}
    outgoing: dict[str, list[FlowEdge]] = {node.id: [] for node in nodes}
    for edge in edges:
        incoming[edge.dest] += 1
        outgoing[edge.src].append(edge)

    entries = [node for node in nodes if incoming[node.id] == 0]
    if not entries:
        raise FlowError(
            "flow has no entry node — every node has an incoming edge (unreachable cycle)"
        )
    if len(entries) > 1:
        ids = sorted(node.id for node in entries)
        raise FlowError(
            f"flow has multiple entry nodes {ids}; flows must have a single starting node"
        )

    for node in nodes:
        out = outgoing[node.id]
        if node.kind == NodeKind.DECISION and len(out) < 2:
            raise FlowError(
                f"decision node {node.id!r} has {len(out)} outgoing edge(s); "
                "decision nodes need at least two branches"
            )
        if node.kind != NodeKind.DECISION and len(out) > 1:
            raise FlowError(
                f"node {node.id!r} ({node.kind.value}) has {len(out)} outgoing "
                "edges; multiple branches require a decision node "
                f"(``{node.id}{{label}}``)"
            )
        if node.kind == NodeKind.DECISION:
            seen_labels: set[str] = set()
            for edge in out:
                if not edge.label:
                    raise FlowError(
                        f"decision node {node.id!r}: outgoing edge to "
                        f"{edge.dest!r} has no branch label "
                        f"(``{node.id} -->|<label>| {edge.dest}``)"
                    )
                if edge.label in seen_labels:
                    raise FlowError(
                        f"decision node {node.id!r}: branch label "
                        f"{edge.label!r} appears on more than one outgoing edge"
                    )
                seen_labels.add(edge.label)

    annotated = tuple(dataclasses.replace(node, annotation=annotations[node.id]) for node in nodes)
    return annotated


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _name_from_filename(path: pathlib.Path) -> str:
    stem = path.stem.lower()
    if not _VALID_NAME_RE.fullmatch(stem):
        raise FlowError(
            f"{path}: invalid flow name {stem!r}; must match "
            "[a-z0-9][a-z0-9_-]* — letters, digits, hyphens, underscores"
        )
    return stem


def _split_frontmatter(path: pathlib.Path) -> tuple[dict[str, object], str]:
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        raise FlowError(f"{path}: missing opening frontmatter delimiter ``---``")
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_DELIMITER:
            end = i
            break
    if end is None:
        raise FlowError(f"{path}: opening frontmatter delimiter has no closing ``---``")
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise FlowError(f"{path}: invalid YAML frontmatter: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise FlowError(f"{path}: frontmatter must be a YAML mapping")
    body = "\n".join(lines[end + 1 :]).strip()
    return data, body


def _intro_prose(body: str) -> str:
    """Return the prose that precedes the first fenced ``mermaid`` block.

    The dispatcher uses this to surface a one-paragraph "what does this
    flow do?" preamble alongside the diagram.  Returns ``""`` when the
    diagram starts at the top of the body.
    """
    match = _FENCE_RE.search(body)
    if match is None:
        return body.strip()
    return body[: match.start()].strip()


def load_flow_file(path: pathlib.Path) -> Flow:
    """Load one flow file into a :class:`Flow`.

    Raises :class:`FlowError` with a path-prefixed message on any
    problem — frontmatter, type, body, diagram parse, validation.
    Callers that prefer "log + skip" should catch and log rather
    than letting a malformed file halt discovery.
    """
    name = _name_from_filename(path)
    frontmatter, body = _split_frontmatter(path)

    unknown = set(frontmatter.keys()) - _FRONTMATTER_KEYS
    if unknown:
        raise FlowError(
            f"{path}: unknown frontmatter keys {sorted(unknown)}; "
            f"expected subset of {sorted(_FRONTMATTER_KEYS)}"
        )

    type_obj = frontmatter.get("type")
    if type_obj != "flow":
        raise FlowError(f"{path}: frontmatter must declare ``type: flow`` (got {type_obj!r})")

    description_obj = frontmatter.get("description")
    if not isinstance(description_obj, str) or not description_obj.strip():
        raise FlowError(f"{path}: 'description' must be a non-empty string")

    name_obj = frontmatter.get("name")
    if name_obj is not None and name_obj != name:
        raise FlowError(
            f"{path}: 'name' frontmatter ({name_obj!r}) must match the "
            f"filename stem ({name!r}) or be omitted"
        )

    if not body.strip():
        raise FlowError(f"{path}: flow body is empty; the diagram is required")

    try:
        diagram_source = extract_mermaid_block(body)
    except FlowError as exc:
        raise FlowError(f"{path}: {exc}") from exc
    try:
        nodes, edges, annotations = parse_mermaid(diagram_source)
    except FlowError as exc:
        raise FlowError(f"{path}: {exc}") from exc
    try:
        nodes = _validate_graph(nodes, edges, annotations)
    except FlowError as exc:
        raise FlowError(f"{path}: {exc}") from exc

    incoming: dict[str, int] = {node.id: 0 for node in nodes}
    for edge in edges:
        incoming[edge.dest] += 1
    entry_node = next(node.id for node in nodes if incoming[node.id] == 0)

    return Flow(
        name=name,
        description=description_obj.strip(),
        intro_prose=_intro_prose(body),
        diagram_source=diagram_source,
        entry_node=entry_node,
        nodes=nodes,
        edges=edges,
        source=path,
    )


def _collect_flows(directory: pathlib.Path) -> dict[str, Flow]:
    """Walk *directory* for ``*.md`` files and load each one."""
    found: dict[str, Flow] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() != ".md" or not path.is_file():
            continue
        try:
            flow = load_flow_file(path)
        except FlowError as exc:
            log.warning("Skipping malformed flow file %s: %s", path, exc)
            continue
        found[flow.name] = flow
    return found


def discover_flows(
    *,
    charm_path: pathlib.Path | None = None,
    user_config_dir: pathlib.Path | None = None,
    bundled_dir: pathlib.Path | None = None,
) -> list[Flow]:
    """Discover flows from bundled, user, and repo directories.

    Precedence (later wins on name collision): bundled built-ins <
    user (``~/.config/cantrip/flows/``) < repo
    (``<charm>/.cantrip-flows/``).  Mirrors the recipe-discovery
    contract so authors who have already learned the recipe layout
    learn flows for free.
    """
    if user_config_dir is None:
        user_config_dir = pathlib.Path.home() / ".config" / "cantrip"
    if bundled_dir is None:
        bundled_dir = BUNDLED_FLOWS_DIR
    user_dir = user_config_dir / "flows"
    merged: dict[str, Flow] = dict(_collect_flows(bundled_dir))
    for name, flow in _collect_flows(user_dir).items():
        merged[name] = flow
    if charm_path is not None:
        repo_dir = charm_path / REPO_FLOWS_DIR
        for name, flow in _collect_flows(repo_dir).items():
            merged[name] = flow
    return sorted(merged.values(), key=lambda f: f.name)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class FlowRegistry:
    """Immutable view over the loaded flows."""

    flows: tuple[Flow, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.flows)

    def get(self, name: str) -> Flow | None:
        for flow in self.flows:
            if flow.name == name:
                return flow
        return None


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


_BRANCH_MARKER = "BRANCH:"


def render_flow_prompt(flow: Flow) -> str:
    """Compose the agent prompt that asks the agent to walk *flow*.

    The prompt has four sections:

    1. A one-paragraph introduction (the flow's frontmatter
       description + any prose before the diagram).
    2. The Mermaid diagram, fenced, so a Mermaid-aware renderer can
       still draw it inline.
    3. The per-node annotations as a numbered list, ordered with the
       entry node first and the rest in declaration order.
    4. Walking-the-flow instructions: start at the entry node, use
       the ``BRANCH:`` marker before picking a branch in a decision
       node so the user can follow the reasoning.
    """
    parts: list[str] = []
    parts.append(f"# Flow: `{flow.name}` — {flow.description}")
    if flow.intro_prose:
        parts.append(flow.intro_prose)
    parts.append("```mermaid\n" + flow.diagram_source.rstrip() + "\n```")

    parts.append("## Per-node instructions\n")
    annotation_lines: list[str] = []
    ordered = sorted(flow.nodes, key=lambda n: (n.id != flow.entry_node, n.id))
    for node in ordered:
        kind_label = node.kind.value
        annotation_lines.append(
            f"- **`{node.id}`** ({kind_label}: {node.label}) — {node.annotation}"
        )
    parts.append("\n".join(annotation_lines))

    parts.append(
        "## Walk the flow\n\n"
        f"Start at node **`{flow.entry_node}`**.  Carry out each node's "
        "instructions in order, following the diagram.  At every "
        "**decision** node, write a single line of the form "
        f"``{_BRANCH_MARKER} <label>`` (using one of the branch labels on "
        "the diagram's outgoing edges) before moving on, so the user can "
        "follow your reasoning.  Stop at any **terminal** node.  If a "
        "step blocks on something you cannot resolve (for example, "
        "missing user input or a tool that's gated by permissions), "
        "stop and explain rather than guess."
    )

    return "\n\n".join(parts)


__all__ = [
    "BUNDLED_FLOWS_DIR",
    "Flow",
    "FlowEdge",
    "FlowError",
    "FlowNode",
    "FlowRegistry",
    "NodeKind",
    "REPO_FLOWS_DIR",
    "USER_CONFIG_FLOWS_DIR",
    "discover_flows",
    "extract_mermaid_block",
    "load_flow_file",
    "parse_mermaid",
    "render_flow_prompt",
]
