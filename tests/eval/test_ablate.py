"""Phase 79.5 prompt-ablation harness — parsing + reporter tests.

These exercise the section parser, the section-dropping helper, and
the reporter shape.  Provider-call paths are covered by the runtime
behaviour of :mod:`tests.eval.test_system_prompt_smoke` against a
real key; this file pins the parts that don't need network at all.
"""

from __future__ import annotations

import dataclasses
import textwrap

import pytest

from tests.eval.ablate import (
    Row,
    Section,
    SmokeResult,
    _delta_label,
    parse_sections,
    render_report,
    with_section_dropped,
)

# ---------------------------------------------------------------------------
# parse_sections
# ---------------------------------------------------------------------------


class TestParseSections:
    def test_top_level_headings(self) -> None:
        prompt = textwrap.dedent(
            """\
            Preamble line.

            ## Alpha
            Body of alpha.

            ## Beta
            Body of beta.
            """
        )
        sections = parse_sections(prompt)
        assert [s.name for s in sections] == ["Alpha", "Beta"]

    def test_inline_h3_headings_skipped(self) -> None:
        # Only ``## `` is a section; ``### `` is a sub-heading and
        # stays inside the enclosing section.
        prompt = textwrap.dedent(
            """\
            ## Alpha
            ### Subsection
            Body line.

            ## Beta
            Body of beta.
            """
        )
        sections = parse_sections(prompt)
        assert [s.name for s in sections] == ["Alpha", "Beta"]

    def test_fenced_headings_ignored(self) -> None:
        # The system prompt embeds fenced ``markdown`` blocks
        # (WORKLOAD.md, DESIGN.md) whose ``## Heading`` lines are
        # *example output* for the model, not prompt sections.
        prompt = textwrap.dedent(
            """\
            ## Real Section
            Body text.

            ```markdown
            ## Not A Real Section
            Inside the fence.

            ## Also Not One
            ```

            ## Another Real Section
            More body.
            """
        )
        sections = parse_sections(prompt)
        assert [s.name for s in sections] == ["Real Section", "Another Real Section"]

    def test_preamble_not_returned(self) -> None:
        prompt = "Preamble.\n\n## Alpha\nBody.\n"
        sections = parse_sections(prompt)
        assert len(sections) == 1
        assert sections[0].start > 0  # Section starts after the preamble

    def test_empty_prompt(self) -> None:
        assert parse_sections("") == []

    def test_no_sections(self) -> None:
        assert parse_sections("Just a paragraph.\nNothing else.\n") == []

    def test_real_system_prompt_is_parseable(self) -> None:
        # Render the actual shipped system prompt and confirm we find
        # multiple sections — guards against a future template
        # rewrite that drops the ``## `` convention without updating
        # this harness.
        from cantrip.agent.prompts.system import build_system_prompt

        prompt = build_system_prompt()
        sections = parse_sections(prompt)
        names = {s.name for s in sections}
        # Pin a couple of known sections so a partial regression
        # surfaces as a missing name, not just a count drift.
        assert "Your Purpose" in names
        assert "Tool Bundles" in names
        assert "Task Planning" in names
        assert len(sections) > 5


# ---------------------------------------------------------------------------
# with_section_dropped
# ---------------------------------------------------------------------------


class TestWithSectionDropped:
    def test_drops_named_section(self) -> None:
        prompt = textwrap.dedent(
            """\
            ## Alpha
            Body of alpha.

            ## Beta
            Body of beta.
            """
        )
        sections = parse_sections(prompt)
        target = next(s for s in sections if s.name == "Alpha")
        out = with_section_dropped(prompt, target)
        assert "Body of alpha" not in out
        assert "Body of beta" in out
        assert "## Beta" in out

    def test_drop_last_section(self) -> None:
        prompt = "## Alpha\nBody.\n\n## Beta\nMore body.\n"
        sections = parse_sections(prompt)
        out = with_section_dropped(prompt, sections[-1])
        assert "## Beta" not in out
        assert "## Alpha" in out

    def test_dropping_one_does_not_disturb_fenced_block(self) -> None:
        # If ``## Outer`` contains a fenced block with ``## NotASection``
        # inside it, dropping a sibling section must not leak content
        # from that fenced block.  Mostly a regression pin against
        # accidental greedy matching.
        prompt = textwrap.dedent(
            """\
            ## Outer
            ```markdown
            ## NotASection
            inside-fence
            ```

            ## Sibling
            sibling-body
            """
        )
        sections = parse_sections(prompt)
        sibling = next(s for s in sections if s.name == "Sibling")
        out = with_section_dropped(prompt, sibling)
        assert "inside-fence" in out
        assert "sibling-body" not in out


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


class TestDeltaLabel:
    def test_no_change(self) -> None:
        baseline = SmokeResult(tool_call=True, non_empty=True)
        ablated = SmokeResult(tool_call=True, non_empty=True)
        assert _delta_label(baseline, ablated) == "no change"

    def test_loss_reported(self) -> None:
        baseline = SmokeResult(tool_call=True, non_empty=True)
        ablated = SmokeResult(tool_call=False, non_empty=True)
        assert _delta_label(baseline, ablated) == "-tool_call"

    def test_gain_reported(self) -> None:
        baseline = SmokeResult(tool_call=False, non_empty=True)
        ablated = SmokeResult(tool_call=True, non_empty=True)
        assert _delta_label(baseline, ablated) == "+tool_call"

    def test_error_short_circuits_delta(self) -> None:
        baseline = SmokeResult(tool_call=True, non_empty=True)
        ablated = SmokeResult(tool_call=None, non_empty=None, error="connection reset")
        delta = _delta_label(baseline, ablated)
        assert delta.startswith("err:")
        assert "connection reset" in delta


class TestRenderReport:
    def test_baseline_then_sections(self) -> None:
        rows = [
            Row(
                label="(baseline)",
                result=SmokeResult(tool_call=True, non_empty=True),
                delta="",
            ),
            Row(
                label="Alpha",
                result=SmokeResult(tool_call=True, non_empty=True),
                delta="no change",
            ),
            Row(
                label="Beta",
                result=SmokeResult(tool_call=False, non_empty=True),
                delta="-tool_call",
            ),
        ]
        report = render_report(rows)
        assert "section" in report.splitlines()[0]
        assert "(baseline)" in report
        assert "Alpha" in report
        assert "Beta" in report
        assert "-tool_call" in report

    def test_renders_question_marks_for_errors(self) -> None:
        rows = [
            Row(
                label="(baseline)",
                result=SmokeResult(tool_call=True, non_empty=True),
                delta="",
            ),
            Row(
                label="Whatever",
                result=SmokeResult(tool_call=None, non_empty=None, error="boom"),
                delta="err: boom",
            ),
        ]
        report = render_report(rows)
        # Both invariants render as "?" for the errored row.
        for line in report.splitlines():
            if line.startswith("Whatever"):
                assert line.count("?") >= 2
                return
        pytest.fail("Whatever row not rendered")


# ---------------------------------------------------------------------------
# Section dataclass — equality + frozen behaviour
# ---------------------------------------------------------------------------


class TestSection:
    def test_equality(self) -> None:
        a = Section(name="X", start=1, end=10)
        b = Section(name="X", start=1, end=10)
        assert a == b

    def test_frozen(self) -> None:
        s = Section(name="X", start=1, end=10)
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.name = "Y"
