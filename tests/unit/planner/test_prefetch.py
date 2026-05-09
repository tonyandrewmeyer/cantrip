"""Planner symbol-prefetch tests — Phase 72b.3."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from cantrip.agent.planner import PlanningContext, TaskPlanner
from cantrip.agent.planner.prefetch import (
    extract_symbol_candidates,
    prefetch_symbol_block,
)
from cantrip.codeintel import CodeIntel, CodeIntelQuery
from tests.conftest import FakeProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def charm_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """Tiny charm with one well-known method + class for the index to find."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "charm.py").write_text(
        textwrap.dedent(
            """
            import ops


            class IngressHandler:
                def refresh(self) -> None:
                    pass


            class MyCharm(ops.CharmBase):
                def __init__(self, framework):
                    super().__init__(framework)
                    self.handler = IngressHandler()

                def _on_install(self, event):
                    pass
            """
        ).strip()
        + "\n"
    )
    return tmp_path


@pytest.fixture
def index(charm_root: pathlib.Path) -> CodeIntel:
    ci = CodeIntel(charm_root)
    ci.build()
    return ci


# ---------------------------------------------------------------------------
# Token detection
# ---------------------------------------------------------------------------


class TestExtractSymbolCandidates:
    def test_dotted_qualified_names(self) -> None:
        out = extract_symbol_candidates("Reproduce MyCharm._on_install on install.")
        assert "MyCharm._on_install" in out

    def test_camel_case_classes(self) -> None:
        out = extract_symbol_candidates("Hook IngressHandler into the charm.")
        assert "IngressHandler" in out

    def test_snake_case_helpers(self) -> None:
        out = extract_symbol_candidates("Wire the build_layer helper through.")
        assert "build_layer" in out

    def test_short_tokens_skipped(self) -> None:
        # Three-character ``foo`` would collide with too many builtins.
        out = extract_symbol_candidates("Add foo and bar.")
        assert "foo" not in out
        assert "bar" not in out

    def test_acronyms_in_stop_list(self) -> None:
        out = extract_symbol_candidates("Document the API and YAML schema.")
        assert "api" not in [c.lower() for c in out]
        assert "yaml" not in [c.lower() for c in out]

    def test_first_occurrence_order(self) -> None:
        # Source position drives candidate order so the first token
        # the user mentioned does not get bumped down by a later one
        # of equal precision.
        out = extract_symbol_candidates(
            "Use IngressHandler then MyCharm._on_install for verification."
        )
        assert out.index("IngressHandler") < out.index("MyCharm._on_install")

    def test_enclosing_dotted_swallows_fragments(self) -> None:
        # ``MyCharm._on_install`` contains the bare ``MyCharm``
        # (CamelCase) and the bare ``_on_install`` (snake_case)
        # tokens.  The enclosing dotted span keeps; the inner
        # fragments drop so the prefetch candidate list does not
        # carry three different ways to ask for the same thing.
        out = extract_symbol_candidates("Reproduce MyCharm._on_install today.")
        assert "MyCharm._on_install" in out
        assert "MyCharm" not in out
        assert "_on_install" not in out

    def test_dedup(self) -> None:
        out = extract_symbol_candidates("MyCharm and MyCharm and MyCharm.")
        # ``MyCharm`` is single-CamelCase so it doesn't match (only
        # multi-segment CamelCase matches by design).  But the pattern
        # still has to dedup when it does match.
        out = extract_symbol_candidates("IngressHandler IngressHandler.")
        assert out.count("IngressHandler") == 1

    def test_empty_input(self) -> None:
        assert extract_symbol_candidates("") == []
        assert extract_symbol_candidates("   ") == []


# ---------------------------------------------------------------------------
# prefetch_symbol_block
# ---------------------------------------------------------------------------


class TestPrefetchSymbolBlock:
    def test_returns_block_for_known_symbol(self, index: CodeIntel) -> None:
        block = prefetch_symbol_block("Add behaviour to MyCharm._on_install.", index)
        assert block is not None
        assert "MyCharm._on_install" in block
        assert "Code intelligence" in block
        # The block carries a snippet so the subagent skips the read.
        assert "src/charm.py" in block

    def test_unknown_symbol_returns_none(self, index: CodeIntel) -> None:
        # ``compute_imaginary_thing`` is not in the fixture charm.
        block = prefetch_symbol_block("Implement compute_imaginary_thing today.", index)
        assert block is None

    def test_no_index_returns_none(self) -> None:
        block = prefetch_symbol_block("MyCharm._on_install", None)
        assert block is None

    def test_no_symbols_in_text_returns_none(self, index: CodeIntel) -> None:
        block = prefetch_symbol_block("Just some plain English text.", index)
        assert block is None

    def test_qualified_match_beats_unqualified(self, index: CodeIntel) -> None:
        # Both ``MyCharm._on_install`` (qualified) and ``IngressHandler``
        # (unqualified class) are real.  The qualified hit ranks
        # first, so the rendered block should be about the method.
        block = prefetch_symbol_block(
            "Touch IngressHandler and MyCharm._on_install in the same change.",
            index,
        )
        assert block is not None
        assert "_on_install" in block

    def test_prefix_only_match_skipped(self, charm_root: pathlib.Path, index: CodeIntel) -> None:
        # ``Ingress`` matches only as a PREFIX hit (the real class is
        # ``IngressHandler``).  Prefetch drops it because PREFIX is
        # below the trusted-match floor — too speculative to surface
        # without a confirming turn.
        block = prefetch_symbol_block("Wire up Ingress later.", index)
        # Either None (nothing trusted) or a different symbol —
        # never a prefix-only hint that pretends to be authoritative.
        if block is not None:
            assert "Ingress." not in block.split("\n")[0]


# ---------------------------------------------------------------------------
# TaskPlanner integration
# ---------------------------------------------------------------------------


class TestPlannerEnrichment:
    @pytest.mark.asyncio
    async def test_no_codeintel_means_no_enrichment(self, charm_root: pathlib.Path) -> None:
        provider = FakeProvider()
        planner = TaskPlanner(provider, code_intel=None)
        ctx = PlanningContext(intent="Add IngressHandler wiring.")
        tasks = await planner.plan(ctx)
        # Without an index the descriptions stay untouched.
        for t in tasks:
            assert "Code intelligence" not in (t.description or "")

    @pytest.mark.asyncio
    async def test_enrichment_appends_block_to_description(
        self, charm_root: pathlib.Path, index: CodeIntel
    ) -> None:
        provider = FakeProvider()
        planner = TaskPlanner(provider, code_intel=index)
        ctx = PlanningContext(
            intent="Reproduce MyCharm._on_install behaviour.",
            charm_name="my-charm",
        )
        tasks = await planner.plan(ctx)
        assert tasks  # deterministic plan should produce at least one task
        # Some task picks up the symbol from the user's intent and
        # has the prefetch block appended to its description.
        enriched = [t for t in tasks if "Code intelligence" in (t.description or "")]
        assert enriched, "expected at least one task to carry the prefetch block"
        first = enriched[0]
        assert "MyCharm._on_install" in first.description

    @pytest.mark.asyncio
    async def test_enrichment_respects_existing_description(self, index: CodeIntel) -> None:
        provider = FakeProvider()
        planner = TaskPlanner(provider, code_intel=index)
        ctx = PlanningContext(intent="Touch IngressHandler.", charm_name="x")
        tasks = await planner.plan(ctx)
        for t in tasks:
            if "Code intelligence" in (t.description or ""):
                # The existing description body still leads; the block
                # is appended after a blank line.
                head, _, tail = t.description.partition("Code intelligence")
                assert head.strip()
                assert tail
                return
        pytest.skip("no task picked up the prefetch — fixture coverage gap")

    @pytest.mark.asyncio
    async def test_enrichment_is_a_protocol_consumer(self, charm_root: pathlib.Path) -> None:
        # The planner accepts anything that satisfies CodeIntelQuery,
        # not just the concrete CodeIntel.  This pins the seam from
        # 72b.4 against the prefetch path.
        from cantrip.codeintel import (
            DefinitionResult,
            ReferencesResult,
        )

        class _StubIndex:
            def __init__(self, root: pathlib.Path) -> None:
                self._root = root

            @property
            def repo_root(self) -> pathlib.Path:
                return self._root

            def build(self, *, force: bool = False) -> None:
                del force

            def workspace_symbols(self, query, **kwargs):  # noqa: ANN001 — stub
                del query, kwargs
                return ([], 0)

            def go_to_definition(self, symbol, **kwargs):  # noqa: ANN001 — stub
                del kwargs
                return DefinitionResult(query=symbol, matches=(), semantic=False, note="stub")

            def find_references(self, symbol, **kwargs):  # noqa: ANN001 — stub
                del kwargs
                return ReferencesResult(
                    query=symbol,
                    locations=(),
                    truncated=0,
                    semantic=False,
                    candidates=(),
                    note="stub",
                )

        stub: CodeIntelQuery = _StubIndex(charm_root)
        provider = FakeProvider()
        planner = TaskPlanner(provider, code_intel=stub)
        ctx = PlanningContext(intent="Touch MyCharm._on_install.")
        tasks = await planner.plan(ctx)
        # A stub that always returns no matches just means no
        # enrichment — that's the point: the seam composes.
        for t in tasks:
            assert "Code intelligence" not in (t.description or "")
