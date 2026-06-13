"""Tests for flow skills (Phase 69.4) — parser, loader, registry."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from cantrip.agent.workflows import flows

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _diagram(*lines: str) -> str:
    """Compose a Mermaid block from raw line fragments."""
    return "flowchart TD\n" + "\n".join(lines)


def _wrap(diagram_body: str, *, intro: str = "Sample flow.", name: str = "sample") -> str:
    """Wrap a diagram body in a complete flow file (frontmatter + fence).

    Leaves the fence markers at column zero so the parser regex catches
    them regardless of how *diagram_body* is indented.  Callers who
    want the diagram indented inside the fence should bake the leading
    whitespace into *diagram_body* itself; the helper does not dedent.
    """
    return (
        "---\n"
        f"name: {name}\n"
        "type: flow\n"
        f"description: {intro}\n"
        "---\n\n"
        "```mermaid\n"
        f"{diagram_body}\n"
        "```\n"
    )


_MINIMAL_DIAGRAM = _diagram(
    "    a[Start]",
    "    b(Done)",
    "    a --> b",
    "    %% a: Begin.",
    "    %% b: Finish.",
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParseMermaid:
    def test_basic_round_trip(self):
        nodes, edges, ann = flows.parse_mermaid(
            _diagram(
                "    survey[Inspect]",
                "    decide{Add metrics?}",
                "    finish(Done)",
                "    survey --> decide",
                "    decide -->|yes| finish",
                "    decide -->|no| finish",
                "    %% survey: Read charm files.",
                "    %% decide: Pick yes if metrics exist.",
                "    %% finish: Done.",
            )
        )
        kinds = {n.id: n.kind for n in nodes}
        assert kinds == {
            "survey": flows.NodeKind.ACTION,
            "decide": flows.NodeKind.DECISION,
            "finish": flows.NodeKind.TERMINAL,
        }
        edge_tuples = [(e.src, e.dest, e.label) for e in edges]
        assert edge_tuples == [
            ("survey", "decide", ""),
            ("decide", "finish", "yes"),
            ("decide", "finish", "no"),
        ]
        assert ann == {
            "survey": "Read charm files.",
            "decide": "Pick yes if metrics exist.",
            "finish": "Done.",
        }

    def test_missing_header_raises(self):
        with pytest.raises(flows.FlowError, match="missing the ``flowchart TD`` header"):
            flows.parse_mermaid("a[Start]\nb(Done)\na --> b\n%% a: x\n%% b: y\n")

    def test_unparseable_line_raises_with_context(self):
        with pytest.raises(flows.FlowError, match="line 2:"):
            flows.parse_mermaid("flowchart TD\nthis is gibberish\n")

    def test_duplicate_node_raises(self):
        body = _diagram(
            "    a[First]",
            "    a[Second]",
            "    %% a: x",
        )
        with pytest.raises(flows.FlowError, match="duplicate node 'a'"):
            flows.parse_mermaid(body)

    def test_duplicate_annotation_raises(self):
        body = _diagram(
            "    a[Start]",
            "    %% a: first",
            "    %% a: second",
        )
        with pytest.raises(flows.FlowError, match="duplicate annotation"):
            flows.parse_mermaid(body)

    def test_plain_comments_ignored(self):
        body = _diagram(
            "    %% This is a plain comment without a colon.",
            "    a[Start]",
            "    b(Done)",
            "    a --> b",
            "    %% a: x",
            "    %% b: y",
        )
        nodes, _, ann = flows.parse_mermaid(body)
        assert {n.id for n in nodes} == {"a", "b"}
        assert ann == {"a": "x", "b": "y"}


# ---------------------------------------------------------------------------
# Validation rules (via load_flow_file → _validate_graph)
# ---------------------------------------------------------------------------


def _write(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    path = tmp_path / f"{name}.md"
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


class TestValidationRules:
    def test_minimal_loads(self, tmp_path):
        path = _write(tmp_path, "minimal", _wrap(_MINIMAL_DIAGRAM, name="minimal"))
        flow = flows.load_flow_file(path)
        assert flow.name == "minimal"
        assert flow.entry_node == "a"
        assert {n.id for n in flow.nodes} == {"a", "b"}

    def test_unknown_edge_source(self, tmp_path):
        body = _diagram(
            "    a[Start]",
            "    b(Done)",
            "    ghost --> b",
            "    a --> b",
            "    %% a: x",
            "    %% b: y",
        )
        path = _write(tmp_path, "bad", _wrap(body, name="bad"))
        with pytest.raises(flows.FlowError, match="unknown source"):
            flows.load_flow_file(path)

    def test_unknown_edge_destination(self, tmp_path):
        body = _diagram(
            "    a[Start]",
            "    b(Done)",
            "    a --> ghost",
            "    a --> b",
            "    %% a: x",
            "    %% b: y",
        )
        path = _write(tmp_path, "bad", _wrap(body, name="bad"))
        with pytest.raises(flows.FlowError, match="unknown destination"):
            flows.load_flow_file(path)

    def test_unknown_annotation_id(self, tmp_path):
        body = _diagram(
            "    a[Start]",
            "    b(Done)",
            "    a --> b",
            "    %% a: x",
            "    %% b: y",
            "    %% ghost: oops",
        )
        path = _write(tmp_path, "bad", _wrap(body, name="bad"))
        with pytest.raises(flows.FlowError, match="unknown node id"):
            flows.load_flow_file(path)

    def test_missing_annotation_for_node(self, tmp_path):
        body = _diagram(
            "    a[Start]",
            "    b(Done)",
            "    a --> b",
            "    %% a: x",
        )
        path = _write(tmp_path, "missing", _wrap(body, name="missing"))
        with pytest.raises(flows.FlowError, match="every node needs"):
            flows.load_flow_file(path)

    def test_no_entry_node(self, tmp_path):
        # Cycle with no clear start — refuse.
        body = _diagram(
            "    a[A]",
            "    b{B}",
            "    a --> b",
            "    b -->|loop| a",
            "    b -->|exit| a",
            "    %% a: x",
            "    %% b: y",
        )
        path = _write(tmp_path, "cycle", _wrap(body, name="cycle"))
        with pytest.raises(flows.FlowError, match="no entry node"):
            flows.load_flow_file(path)

    def test_multiple_entry_nodes(self, tmp_path):
        body = _diagram(
            "    a[A]",
            "    b[B]",
            "    c(Done)",
            "    a --> c",
            "    b --> c",
            "    %% a: x",
            "    %% b: y",
            "    %% c: z",
        )
        path = _write(tmp_path, "two-roots", _wrap(body, name="two-roots"))
        with pytest.raises(flows.FlowError, match="multiple entry nodes"):
            flows.load_flow_file(path)

    def test_decision_needs_two_branches(self, tmp_path):
        body = _diagram(
            "    a[Start]",
            "    d{Choose}",
            "    b(Done)",
            "    a --> d",
            "    d -->|only| b",
            "    %% a: x",
            "    %% d: y",
            "    %% b: z",
        )
        path = _write(tmp_path, "lonely", _wrap(body, name="lonely"))
        with pytest.raises(flows.FlowError, match="at least two branches"):
            flows.load_flow_file(path)

    def test_decision_branches_need_labels(self, tmp_path):
        body = _diagram(
            "    a[Start]",
            "    d{Choose}",
            "    b(Done)",
            "    c(Done2)",
            "    a --> d",
            "    d --> b",
            "    d --> c",
            "    %% a: x",
            "    %% d: y",
            "    %% b: z",
            "    %% c: w",
        )
        path = _write(tmp_path, "unlabelled", _wrap(body, name="unlabelled"))
        with pytest.raises(flows.FlowError, match="no branch label"):
            flows.load_flow_file(path)

    def test_decision_branch_labels_unique(self, tmp_path):
        body = _diagram(
            "    a[Start]",
            "    d{Choose}",
            "    b(Done)",
            "    c(Done2)",
            "    a --> d",
            "    d -->|same| b",
            "    d -->|same| c",
            "    %% a: x",
            "    %% d: y",
            "    %% b: z",
            "    %% c: w",
        )
        path = _write(tmp_path, "dup-branch", _wrap(body, name="dup-branch"))
        with pytest.raises(flows.FlowError, match="appears on more than one"):
            flows.load_flow_file(path)

    def test_action_node_with_two_outgoing_rejected(self, tmp_path):
        # An action node with two outgoing edges should have been a
        # decision node — surface the authoring mistake.
        body = _diagram(
            "    a[Start]",
            "    b(Done)",
            "    c(Done2)",
            "    a --> b",
            "    a --> c",
            "    %% a: x",
            "    %% b: y",
            "    %% c: z",
        )
        path = _write(tmp_path, "fork-action", _wrap(body, name="fork-action"))
        with pytest.raises(flows.FlowError, match="multiple branches require a decision node"):
            flows.load_flow_file(path)

    def test_multiple_terminals_allowed(self, tmp_path):
        body = _diagram(
            "    a[Start]",
            "    d{Choose}",
            "    win(Win)",
            "    lose(Lose)",
            "    a --> d",
            "    d -->|yes| win",
            "    d -->|no| lose",
            "    %% a: x",
            "    %% d: y",
            "    %% win: z",
            "    %% lose: w",
        )
        path = _write(tmp_path, "multi-end", _wrap(body, name="multi-end"))
        flow = flows.load_flow_file(path)
        terminals = [n for n in flow.nodes if n.kind is flows.NodeKind.TERMINAL]
        assert {n.id for n in terminals} == {"win", "lose"}


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


class TestLoaderFrontmatter:
    def test_missing_frontmatter_open(self, tmp_path):
        path = tmp_path / "nofm.md"
        path.write_text("```mermaid\nflowchart TD\n```\n", encoding="utf-8")
        with pytest.raises(flows.FlowError, match="missing opening frontmatter"):
            flows.load_flow_file(path)

    def test_unclosed_frontmatter(self, tmp_path):
        path = tmp_path / "unclosed.md"
        path.write_text("---\nname: x\n", encoding="utf-8")
        with pytest.raises(flows.FlowError, match="opening frontmatter delimiter has no closing"):
            flows.load_flow_file(path)

    def test_unknown_frontmatter_key(self, tmp_path):
        path = tmp_path / "unknown.md"
        path.write_text(
            textwrap.dedent(
                f"""\
                ---
                name: x
                type: flow
                description: y
                stranger: 1
                ---

                ```mermaid
                {_MINIMAL_DIAGRAM}
                ```
                """
            ),
            encoding="utf-8",
        )
        with pytest.raises(flows.FlowError, match="unknown frontmatter keys"):
            flows.load_flow_file(path)

    def test_type_must_be_flow(self, tmp_path):
        path = tmp_path / "wrong-type.md"
        path.write_text(
            textwrap.dedent(
                f"""\
                ---
                name: x
                type: skill
                description: y
                ---

                ```mermaid
                {_MINIMAL_DIAGRAM}
                ```
                """
            ),
            encoding="utf-8",
        )
        with pytest.raises(flows.FlowError, match="``type: flow``"):
            flows.load_flow_file(path)

    def test_name_must_match_filename(self, tmp_path):
        path = tmp_path / "actual-name.md"
        path.write_text(
            textwrap.dedent(
                f"""\
                ---
                name: different-name
                type: flow
                description: y
                ---

                ```mermaid
                {_MINIMAL_DIAGRAM}
                ```
                """
            ),
            encoding="utf-8",
        )
        with pytest.raises(flows.FlowError, match="must match the filename stem"):
            flows.load_flow_file(path)

    def test_invalid_filename(self, tmp_path):
        path = tmp_path / "-bad-name.md"
        path.write_text(
            f"---\ntype: flow\ndescription: y\n---\n\n```mermaid\n{_MINIMAL_DIAGRAM}\n```\n",
            encoding="utf-8",
        )
        with pytest.raises(flows.FlowError, match="invalid flow name"):
            flows.load_flow_file(path)

    def test_no_mermaid_block(self, tmp_path):
        path = tmp_path / "no-block.md"
        path.write_text(
            textwrap.dedent(
                """\
                ---
                type: flow
                description: y
                ---

                Just prose, no diagram.
                """
            ),
            encoding="utf-8",
        )
        with pytest.raises(flows.FlowError, match="no ```mermaid"):
            flows.load_flow_file(path)

    def test_multiple_mermaid_blocks(self, tmp_path):
        path = tmp_path / "two-blocks.md"
        path.write_text(
            "---\ntype: flow\ndescription: y\n---\n\n"
            f"```mermaid\n{_MINIMAL_DIAGRAM}\n```\n\n"
            f"```mermaid\n{_MINIMAL_DIAGRAM}\n```\n",
            encoding="utf-8",
        )
        with pytest.raises(flows.FlowError, match="multiple ```mermaid"):
            flows.load_flow_file(path)


# ---------------------------------------------------------------------------
# Discovery + bundled flows
# ---------------------------------------------------------------------------


class TestDiscovery:
    def _absent_bundle(self, tmp_path):
        return tmp_path / "absent-bundle"

    def test_repo_overrides_user(self, tmp_path):
        user_root = tmp_path / "user"
        user_dir = user_root / "flows"
        user_dir.mkdir(parents=True)
        repo = tmp_path / "repo"
        repo_dir = repo / ".cantrip-flows"
        repo_dir.mkdir(parents=True)
        for path, label in [(user_dir / "shared.md", "User"), (repo_dir / "shared.md", "Repo")]:
            path.write_text(
                "---\ntype: flow\n"
                f"description: {label}-scope.\n"
                "---\n\n"
                f"```mermaid\n{_MINIMAL_DIAGRAM}\n```\n",
                encoding="utf-8",
            )
        loaded = flows.discover_flows(
            charm_path=repo,
            user_config_dir=user_root,
            bundled_dir=self._absent_bundle(tmp_path),
        )
        match = next(f for f in loaded if f.name == "shared")
        assert match.description == "Repo-scope."

    def test_user_overrides_bundled(self, tmp_path):
        # A user-scope file can override a bundled built-in by name.
        user_root = tmp_path / "user"
        user_dir = user_root / "flows"
        user_dir.mkdir(parents=True)
        (user_dir / "charm-cos-enable.md").write_text(
            "---\ntype: flow\n"
            "description: User override of charm-cos-enable.\n"
            "---\n\n"
            f"```mermaid\n{_MINIMAL_DIAGRAM}\n```\n",
            encoding="utf-8",
        )
        loaded = flows.discover_flows(user_config_dir=user_root)
        match = next(f for f in loaded if f.name == "charm-cos-enable")
        assert match.description == "User override of charm-cos-enable."

    def test_default_bundled_dir_loads_builtins(self):
        # No user/repo dirs; only the bundled flows land.  Pin the
        # names so a removed built-in surfaces as a test failure.
        loaded = flows.discover_flows(
            user_config_dir=pathlib.Path("/__nonexistent_user_config_dir")
        )
        names = {f.name for f in loaded}
        assert {"charm-cos-enable", "charm-reactive-to-ops", "charm-upgrade-ladder"} <= names

    def test_bundled_flows_render_with_defaults(self):
        # End-to-end smoke: every built-in renders to a non-trivial
        # prompt and surfaces every node's annotation.
        loaded = flows.discover_flows(
            user_config_dir=pathlib.Path("/__nonexistent_user_config_dir")
        )
        by_name = {f.name: f for f in loaded}
        for name in ("charm-cos-enable", "charm-reactive-to-ops", "charm-upgrade-ladder"):
            flow = by_name[name]
            rendered = flows.render_flow_prompt(flow)
            assert len(rendered) > 500, f"{name} rendered to {len(rendered)} chars"
            for node in flow.nodes:
                assert node.annotation, f"{name} node {node.id} has no annotation"
                assert node.annotation in rendered

    def test_malformed_file_skipped(self, tmp_path, caplog):
        repo = tmp_path / "repo"
        repo_dir = repo / ".cantrip-flows"
        repo_dir.mkdir(parents=True)
        # ok.md loads cleanly.
        (repo_dir / "ok.md").write_text(
            f"---\ntype: flow\ndescription: y\n---\n\n```mermaid\n{_MINIMAL_DIAGRAM}\n```\n",
            encoding="utf-8",
        )
        # broken.md missing description — load fails; discovery logs + skips.
        (repo_dir / "broken.md").write_text(
            f"---\ntype: flow\n---\n\n```mermaid\n{_MINIMAL_DIAGRAM}\n```\n",
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            loaded = flows.discover_flows(
                charm_path=repo,
                user_config_dir=tmp_path / "u",
                bundled_dir=self._absent_bundle(tmp_path),
            )
        assert [f.name for f in loaded] == ["ok"]
        assert any("broken.md" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


class TestRender:
    def test_prompt_includes_diagram_and_annotations(self, tmp_path):
        path = _write(tmp_path, "sample", _wrap(_MINIMAL_DIAGRAM, name="sample"))
        flow = flows.load_flow_file(path)
        rendered = flows.render_flow_prompt(flow)
        assert "```mermaid" in rendered
        assert "Begin." in rendered
        assert "Finish." in rendered
        assert "BRANCH:" in rendered
        # The entry node leads the per-node listing.
        first_block = rendered.split("## Per-node instructions")[1]
        assert first_block.lstrip().startswith("- **`a`**")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_get_returns_flow(self, tmp_path):
        path = _write(tmp_path, "x", _wrap(_MINIMAL_DIAGRAM, name="x"))
        flow = flows.load_flow_file(path)
        registry = flows.FlowRegistry(flows=(flow,))
        assert registry.get("x") is flow
        assert registry.get("missing") is None
        assert registry.names == ("x",)
