"""Property-based tests for ``design.parse_design_from_result``.

The example tests in ``test_design_parsing.py`` cover hand-written
design documents.  These properties stress two complementary cases:

* arbitrary text must parse without raising and preserve the raw source;
  and
* generated, well-structured design Markdown must round-trip the fields
  Cantrip extracts from headings and bullet lists.
"""

from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st

from cantrip.agent.design import CompanionCharm, DesignQuestion, parse_design_from_result

_TEXT = (
    st.text(
        alphabet=string.ascii_letters + string.digits + " ._/-():",
        min_size=1,
        max_size=40,
    )
    .map(str.strip)
    .filter(bool)
)

_KEY = (
    st.text(
        alphabet=string.ascii_letters + string.digits + " -_",
        min_size=1,
        max_size=20,
    )
    .map(str.strip)
    .filter(bool)
)

_TOKEN = st.text(
    alphabet=string.ascii_lowercase + string.digits + "-_",
    min_size=1,
    max_size=20,
)

_ITEMS = st.lists(_TEXT, max_size=4)


@st.composite
def _design_markdown(
    draw: st.DrawFn,
) -> tuple[
    str,
    str,
    str,
    str,
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
    list[CompanionCharm],
    list[DesignQuestion],
]:
    """Build a structured design document plus the expected parsed values."""
    workload_name = draw(_TEXT)
    substrate = "\n".join(draw(st.lists(_TEXT, min_size=1, max_size=3)))
    charm_path = "\n".join(draw(st.lists(_TEXT, min_size=1, max_size=3)))
    integrations = draw(_ITEMS)
    config_options = draw(_ITEMS)
    actions = draw(_ITEMS)
    security_surface = draw(_ITEMS)
    sources = draw(_ITEMS)
    companion_rows = draw(
        st.lists(
            st.tuples(_TOKEN, _TOKEN, _TOKEN, st.booleans()),
            max_size=3,
            unique_by=lambda row: (row[0], row[1], row[2]),
        )
    )
    question_rows = draw(
        st.lists(
            st.tuples(_KEY, _TEXT, st.lists(_TEXT, max_size=3)),
            max_size=3,
            unique_by=lambda row: (row[0], row[1]),
        )
    )

    companions = [
        CompanionCharm(charm_name=name, endpoint=endpoint, interface=interface)
        for name, endpoint, interface, _ in companion_rows
    ]
    questions = [
        DesignQuestion(key=key, text=text, suggestions=suggestions)
        for key, text, suggestions in question_rows
    ]

    section_blocks = {
        "Substrate": substrate,
        "Charm path": charm_path,
        "Integrations": "\n".join(f"- {item}" for item in integrations),
        "Config": "\n".join(f"- {item}" for item in config_options),
        "Actions": "\n".join(f"- {item}" for item in actions),
        "Security surface": "\n".join(f"- {item}" for item in security_surface),
        "Sources": "\n".join(f"- {item}" for item in sources),
        "Companion charms": "\n".join(
            (
                f"- {name} via `{endpoint}` ({interface})"
                if use_backticks
                else f"- {name} via {endpoint} ({interface})"
            )
            for name, endpoint, interface, use_backticks in companion_rows
        ),
        "Questions": "\n".join(
            "\n".join(
                [f"- **{key}**: {text}", *(f"  - {suggestion}" for suggestion in suggestions)]
            )
            for key, text, suggestions in question_rows
        ),
    }

    ordered_headings = draw(st.permutations(list(section_blocks)))
    sections = [f"# {workload_name}"]
    for heading in ordered_headings:
        body = section_blocks[heading]
        sections.append(f"## {heading}\n\n{body}")
    text = "\n\n".join(sections)
    return (
        text,
        workload_name,
        substrate,
        charm_path,
        integrations,
        config_options,
        actions,
        security_surface,
        sources,
        companions,
        questions,
    )


class TestParseDesignFromResultProperties:
    """Invariants of the design parser over arbitrary Markdown."""

    @given(text=st.text(max_size=500))
    def test_arbitrary_text_never_raises_and_preserves_raw_text(self, text: str) -> None:
        """Unstructured model output should still parse into a best-effort proposal."""
        proposal = parse_design_from_result(text)
        assert proposal.raw_design_md == text

    @given(case=_design_markdown())
    def test_structured_sections_round_trip_known_fields(
        self,
        case: tuple[
            str,
            str,
            str,
            str,
            list[str],
            list[str],
            list[str],
            list[str],
            list[str],
            list[CompanionCharm],
            list[DesignQuestion],
        ],
    ) -> None:
        """Heading-driven content should survive regardless of section order."""
        (
            text,
            workload_name,
            substrate,
            charm_path,
            integrations,
            config_options,
            actions,
            security_surface,
            sources,
            companions,
            questions,
        ) = case
        proposal = parse_design_from_result(text)
        assert proposal.raw_design_md == text
        assert proposal.workload_name == workload_name
        assert proposal.substrate == substrate
        assert proposal.charm_path == charm_path
        assert proposal.integrations == integrations
        assert proposal.config_options == config_options
        assert proposal.actions == actions
        assert proposal.security_surface == security_surface
        assert proposal.sources == sources
        assert proposal.companions == companions
        assert proposal.questions_for_user == questions
