"""Prompt ablation harness — Phase 79.5.

Drop each top-level section of the rendered system prompt in turn,
rerun the Phase 79.2 smoke invariants, and report which sections
actually pull their weight.  Lets a human author reason about which
sentences earn their tokens before a prompt change lands —
matches Anthropic's April 2026 postmortem remediation: "continue
ablations to understand the impact of each line."

Usage::

    uv run python -m tests.eval.ablate --provider openrouter \\
        --model openai/gpt-4o-mini

The tool only ever runs against the default ``build_system_prompt()``
output (no charm context), so the same provider call shape exercised
by ``tests/eval/test_system_prompt_smoke.py`` is what you see here.
Cost is bounded: ~30 sections × 2 invariants × 1 baseline = ~62
model calls — pennies on a cheap model.

Operates on the rendered prompt rather than mutating
``system.md.j2`` so a misbehaving template does not poison the on-disk
source.  Sections are parsed top-level (``## Heading``) and parsing
is fence-aware so the WORKLOAD.md / DESIGN.md templates *inside*
fenced code blocks aren't mistaken for prompt sections.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import re
import sys
from typing import TYPE_CHECKING

from cantrip.agent.prompts.system import build_system_prompt
from cantrip.llm import create_provider
from cantrip.llm.base import LLMProvider, Message, Role, Tool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------


_HEADING = re.compile(r"^## (.+)$")
_FENCE = re.compile(r"^```")


@dataclasses.dataclass(frozen=True)
class Section:
    """One top-level section of the rendered prompt.

    ``start`` and ``end`` are line indices (half-open: ``end`` is the
    first line *after* the section).  ``name`` is the heading text
    minus the ``## `` prefix.
    """

    name: str
    start: int
    end: int


def parse_sections(prompt: str) -> list[Section]:
    """Return the top-level ``## Heading`` sections of *prompt*.

    Fence-aware: ``## Purpose`` etc. that appear inside a fenced code
    block (the WORKLOAD.md / DESIGN.md templates the prompt embeds)
    are *not* treated as prompt sections — those are example output
    for the model, not headings of the prompt itself.

    The text *before* the first heading (preamble) is not returned as
    a section; ablation never drops it because removing the preamble
    typically shifts the entire prompt's framing in ways unrelated to
    the section under test.
    """
    lines = prompt.splitlines()
    in_fence = False
    headings: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING.match(line)
        if m:
            headings.append((i, m.group(1)))
    sections: list[Section] = []
    for idx, (start, name) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        sections.append(Section(name=name, start=start, end=end))
    return sections


def with_section_dropped(prompt: str, section: Section) -> str:
    """Return *prompt* with *section* removed.

    Preserves a single blank line at the boundary so the surrounding
    structure does not collapse together (``## A\\n## B`` after
    dropping ``## A``'s body would leave the two headings
    accidentally adjacent in a way the original prompt never had).
    """
    lines = prompt.splitlines()
    return "\n".join(lines[: section.start] + lines[section.end :])


# ---------------------------------------------------------------------------
# Provider call shape — kept aligned with test_system_prompt_smoke.py
# ---------------------------------------------------------------------------


def _read_file_tool() -> Tool:
    return Tool(
        name="read_file",
        description="Read the contents of a file in the charm directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (relative to charm root).",
                },
            },
            "required": ["path"],
        },
    )


@dataclasses.dataclass(frozen=True)
class SmokeResult:
    """Outcome of one ablation run against one provider.

    ``tool_call`` and ``non_empty`` mirror the two 79.2 invariants:
    the model emits a ``read_file`` tool call when asked, and the
    bare-greeting reply is non-empty (or includes tool calls).
    ``error`` is set when a transport error or provider 4xx skipped
    the run; the cell is reported as "?" in that case so the operator
    knows the absence is not the prompt's fault.
    """

    tool_call: bool | None
    non_empty: bool | None
    error: str | None = None

    def passed(self) -> int:
        return int(bool(self.tool_call)) + int(bool(self.non_empty))


async def _smoke_once(provider: LLMProvider, system_prompt: str) -> SmokeResult:
    """Run both 79.2 invariants once against *system_prompt*."""
    try:
        tool_response = await provider.complete(
            [
                Message(role=Role.SYSTEM, content=system_prompt),
                Message(
                    role=Role.USER,
                    content=(
                        "What is the project name in `pyproject.toml`?  "
                        "Use the `read_file` tool to read the file before "
                        "answering — do not guess."
                    ),
                ),
            ],
            tools=[_read_file_tool()],
            max_tokens=512,
        )
        text_response = await provider.complete(
            [
                Message(role=Role.SYSTEM, content=system_prompt),
                Message(
                    role=Role.USER,
                    content="Hello!  Reply with a single short sentence — no tools.",
                ),
            ],
            max_tokens=128,
        )
    except Exception as exc:
        return SmokeResult(tool_call=None, non_empty=None, error=str(exc))
    tool_names = [tc.name for tc in tool_response.tool_calls]
    return SmokeResult(
        tool_call="read_file" in tool_names,
        non_empty=bool(text_response.content) or bool(text_response.tool_calls),
    )


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


def _cell(value: bool | None) -> str:
    if value is None:
        return "?"
    return "✓" if value else "✗"


def _delta_label(baseline: SmokeResult, ablated: SmokeResult) -> str:
    """Human-readable diff between the baseline and an ablated run."""
    if ablated.error:
        return f"err: {ablated.error[:60]}"
    losses: list[str] = []
    if baseline.tool_call and not ablated.tool_call:
        losses.append("tool_call")
    if baseline.non_empty and not ablated.non_empty:
        losses.append("non_empty")
    gains: list[str] = []
    if not baseline.tool_call and ablated.tool_call:
        gains.append("tool_call")
    if not baseline.non_empty and ablated.non_empty:
        gains.append("non_empty")
    if losses and gains:
        return f"-{','.join(losses)} +{','.join(gains)}"
    if losses:
        return f"-{','.join(losses)}"
    if gains:
        return f"+{','.join(gains)}"
    return "no change"


@dataclasses.dataclass(frozen=True)
class Row:
    """One row of the report."""

    label: str
    result: SmokeResult
    delta: str


async def _produce_rows(
    provider: LLMProvider,
    sections: list[Section],
    prompt: str,
) -> AsyncIterator[Row]:
    """Yield the baseline row followed by one row per ablated section."""
    baseline = await _smoke_once(provider, prompt)
    yield Row(label="(baseline)", result=baseline, delta="")
    for section in sections:
        ablated_prompt = with_section_dropped(prompt, section)
        ablated = await _smoke_once(provider, ablated_prompt)
        yield Row(
            label=section.name,
            result=ablated,
            delta=_delta_label(baseline, ablated),
        )


def render_report(rows: list[Row]) -> str:
    """Render the rows as a fixed-width text table."""
    name_width = max(36, max((len(r.label) for r in rows), default=0))
    header = f"{'section':<{name_width}}  {'tool_call':<10}  {'non_empty':<10}  delta"
    sep = f"{'-' * name_width}  {'-' * 10}  {'-' * 10}  -----"
    lines = [header, sep]
    lines.extend(
        f"{row.label:<{name_width}}  "
        f"{_cell(row.result.tool_call):<10}  "
        f"{_cell(row.result.non_empty):<10}  "
        f"{row.delta}"
        for row in rows
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_PROVIDER_KEYS: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tests.eval.ablate",
        description=(
            "Drop each top-level section of the rendered system prompt and "
            "rerun the 79.2 smoke invariants.  Reports which sections pull "
            "their weight."
        ),
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=sorted(_PROVIDER_KEYS),
        help="Provider preset to test against.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Optional model override.  Defaults to the provider's default "
            "model.  Use a cheap model — this issues one call per section "
            "per invariant."
        ),
    )
    parser.add_argument(
        "--list-sections",
        action="store_true",
        help="Print the parsed section names without calling any provider.",
    )
    return parser.parse_args(argv)


async def _async_main(argv: list[str]) -> int:
    args = _parse_args(argv)
    prompt = build_system_prompt()
    sections = parse_sections(prompt)
    if args.list_sections:
        for section in sections:
            print(section.name)
        return 0
    env_var = _PROVIDER_KEYS[args.provider]
    if not os.environ.get(env_var):
        print(f"{env_var} is not set — skipping ablation run.", file=sys.stderr)
        return 2
    provider = create_provider(args.provider, model=args.model)
    rows: list[Row] = [row async for row in _produce_rows(provider, sections, prompt)]
    print(render_report(rows))
    # Exit non-zero when at least one section's ablation lost a previously-
    # passing invariant.  The CLI is a development tool, not a CI gate, but
    # a meaningful exit code lets a script hook the harness up later.
    regressed = any(r.delta.startswith("-") for r in rows[1:])
    return 1 if regressed else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_async_main(list(argv) if argv is not None else sys.argv[1:]))


if __name__ == "__main__":  # pragma: no cover — entry point
    raise SystemExit(main())
