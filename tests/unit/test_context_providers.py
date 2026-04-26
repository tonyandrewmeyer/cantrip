"""Tests for the ``@``-mention context-provider registry (Phase 72.2)."""

from __future__ import annotations

import dataclasses
import pathlib
import subprocess

import pytest

from cantrip.agent import context_providers_builtin
from cantrip.agent.context_providers import (
    ArgStyle,
    ContextBlock,
    ContextProvider,
    ExpansionContext,
    ExpansionResult,
    ProviderInfo,
    ProviderRegistry,
    chars_for_tokens,
    expand_mentions,
    truncate,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _StubProvider:
    """Minimal provider — returns a canned rendered string."""

    info: ProviderInfo
    rendered: str = "STUB"

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:
        del ctx
        if args:
            return ContextBlock(
                raw=f"@{self.info.name} {args}", rendered=f"{self.rendered}({args})"
            )
        return ContextBlock(raw=f"@{self.info.name}", rendered=self.rendered)


def _registry(*providers: ContextProvider) -> ProviderRegistry:
    """Build a registry from a list of providers."""
    reg = ProviderRegistry()
    for provider in providers:
        reg.register(provider)
    return reg


def _file_provider() -> ContextProvider:
    return _StubProvider(
        info=ProviderInfo(name="file", summary="", arg_style=ArgStyle.TOKEN),
        rendered="<file>",
    )


def _diff_provider() -> ContextProvider:
    return _StubProvider(
        info=ProviderInfo(name="diff", summary="", arg_style=ArgStyle.NONE),
        rendered="<diff>",
    )


def _docs_provider() -> ContextProvider:
    return _StubProvider(
        info=ProviderInfo(name="docs", summary="", arg_style=ArgStyle.REST_OF_LINE),
        rendered="<docs>",
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParser:
    """Mention scan and arg-consumption rules."""

    @pytest.mark.asyncio
    async def test_no_mentions_passes_through(self) -> None:
        result = await expand_mentions("Hello world", _registry(), ExpansionContext())
        assert result.raw == "Hello world"
        assert result.expanded == "Hello world"
        assert result.changed is False
        assert result.blocks == ()

    @pytest.mark.asyncio
    async def test_email_address_is_not_a_mention(self) -> None:
        # The `@` must be preceded by whitespace or start-of-string;
        # `tony@example.com` must not trigger expansion even if a
        # provider named `example` were registered.
        registry = _registry(
            _StubProvider(info=ProviderInfo(name="example", summary="", arg_style=ArgStyle.NONE))
        )
        result = await expand_mentions("Email tony@example.com", registry, ExpansionContext())
        assert result.expanded == "Email tony@example.com"
        assert result.blocks == ()

    @pytest.mark.asyncio
    async def test_unknown_name_left_verbatim(self) -> None:
        result = await expand_mentions("ping @nonsense path", _registry(), ExpansionContext())
        assert result.expanded == "ping @nonsense path"
        assert result.blocks == ()

    @pytest.mark.asyncio
    async def test_double_at_reserved_for_threads(self) -> None:
        # ``@@`` must not be interpreted even if ``file`` is registered.
        registry = _registry(_file_provider())
        result = await expand_mentions("see @@thread7 ref", registry, ExpansionContext())
        assert result.expanded == "see @@thread7 ref"
        assert result.blocks == ()

    @pytest.mark.asyncio
    async def test_token_style_consumes_one_token(self) -> None:
        registry = _registry(_file_provider())
        result = await expand_mentions(
            "look at @file foo.py and rest", registry, ExpansionContext()
        )
        assert result.expanded == "look at <file>(foo.py) and rest"
        assert len(result.blocks) == 1

    @pytest.mark.asyncio
    async def test_rest_of_line_consumes_until_newline(self) -> None:
        registry = _registry(_docs_provider())
        result = await expand_mentions(
            "Look up @docs juju secrets quickly\nNext line",
            registry,
            ExpansionContext(),
        )
        # Args are everything until newline, stripped.
        assert "<docs>(juju secrets quickly)" in result.expanded
        assert "\nNext line" in result.expanded

    @pytest.mark.asyncio
    async def test_none_style_takes_no_args(self) -> None:
        registry = _registry(_diff_provider())
        result = await expand_mentions("see @diff please", registry, ExpansionContext())
        # ``@diff`` consumes nothing; surrounding text stays put.
        assert result.expanded == "see <diff> please"

    @pytest.mark.asyncio
    async def test_multiple_mentions_in_order(self) -> None:
        registry = _registry(_file_provider(), _diff_provider())
        result = await expand_mentions(
            "@diff and @file foo.py and @file bar.py",
            registry,
            ExpansionContext(),
        )
        assert result.expanded == "<diff> and <file>(foo.py) and <file>(bar.py)"
        assert len(result.blocks) == 3

    @pytest.mark.asyncio
    async def test_inside_fenced_code_block_is_skipped(self) -> None:
        registry = _registry(_diff_provider())
        text = "before\n```\nrun @diff manually\n```\nafter @diff"
        result = await expand_mentions(text, registry, ExpansionContext())
        # Only the trailing ``@diff`` outside the fence expanded.
        assert "run @diff manually" in result.expanded
        assert result.expanded.count("<diff>") == 1

    @pytest.mark.asyncio
    async def test_inside_inline_code_is_skipped(self) -> None:
        registry = _registry(_diff_provider())
        text = "use `@diff` to mention or @diff to expand"
        result = await expand_mentions(text, registry, ExpansionContext())
        assert "`@diff`" in result.expanded
        assert result.expanded.count("<diff>") == 1


# ---------------------------------------------------------------------------
# Expansion behaviour
# ---------------------------------------------------------------------------


class TestExpansion:
    """End-to-end expansion semantics."""

    @pytest.mark.asyncio
    async def test_records_raw_and_expanded(self) -> None:
        registry = _registry(_diff_provider())
        result = await expand_mentions("look @diff", registry, ExpansionContext())
        assert result.raw == "look @diff"
        assert result.expanded == "look <diff>"
        assert result.changed is True

    @pytest.mark.asyncio
    async def test_provider_error_renders_inline(self) -> None:
        @dataclasses.dataclass(frozen=True, slots=True)
        class Boom:
            info: ProviderInfo = ProviderInfo(name="boom", summary="", arg_style=ArgStyle.NONE)

            async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:  # noqa: ARG002
                raise RuntimeError("bang")

        registry = _registry(Boom())
        result = await expand_mentions("see @boom now", registry, ExpansionContext())
        assert "[@boom: error: bang]" in result.expanded
        assert len(result.blocks) == 1
        assert result.blocks[0].error == "bang"

    @pytest.mark.asyncio
    async def test_multiline_block_gets_fence_wrapper(self) -> None:
        @dataclasses.dataclass(frozen=True, slots=True)
        class MultiLine:
            info: ProviderInfo = ProviderInfo(name="ml", summary="", arg_style=ArgStyle.NONE)

            async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock:  # noqa: ARG002
                return ContextBlock(raw="@ml", rendered="line1\nline2\nline3")

        registry = _registry(MultiLine())
        result = await expand_mentions("@ml", registry, ExpansionContext())
        assert "[@ml]" in result.expanded
        assert "[/@ml]" in result.expanded
        assert "line1\nline2\nline3" in result.expanded


# ---------------------------------------------------------------------------
# Truncation helper
# ---------------------------------------------------------------------------


class TestTruncate:
    """Per-provider char budgets and the truncation footer."""

    def test_under_budget_passes_through(self) -> None:
        block = truncate(raw="@x", rendered="short", max_chars=100)
        assert block.rendered == "short"
        assert block.truncated_chars == 0

    def test_over_budget_appends_footer(self) -> None:
        body = "x" * 5000
        block = truncate(raw="@x", rendered=body, max_chars=200, note="see docs")
        assert block.truncated_chars > 0
        assert "truncated" in block.rendered
        assert "see docs" in block.rendered
        assert len(block.rendered) <= 200 + 50  # footer overhead

    def test_chars_for_tokens(self) -> None:
        assert chars_for_tokens(1000) == 4000
        assert chars_for_tokens(0) == 0
        assert chars_for_tokens(-5) == 0


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


class TestRegistry:
    """Registration, lookup, and catalogue surfaces."""

    def test_registration_and_lookup(self) -> None:
        registry = ProviderRegistry()
        provider = _diff_provider()
        registry.register(provider)
        assert registry.get("diff") is provider
        assert registry.get("missing") is None
        assert "diff" in registry.names()

    def test_re_registering_replaces(self) -> None:
        registry = ProviderRegistry()
        first = _diff_provider()
        second = _StubProvider(
            info=ProviderInfo(name="diff", summary="other", arg_style=ArgStyle.NONE)
        )
        registry.register(first)
        registry.register(second)
        assert registry.get("diff") is second

    def test_catalogue_sorted(self) -> None:
        registry = _registry(_file_provider(), _diff_provider(), _docs_provider())
        names = [info.name for info in registry.catalogue()]
        assert names == sorted(names)

    def test_provider_info_display(self) -> None:
        info_with = ProviderInfo(
            name="file", summary="", arg_style=ArgStyle.TOKEN, args_hint="<path>"
        )
        info_bare = ProviderInfo(name="diff", summary="", arg_style=ArgStyle.NONE)
        assert info_with.display == "@file <path>"
        assert info_bare.display == "@diff"


# ---------------------------------------------------------------------------
# Built-in providers
# ---------------------------------------------------------------------------


class TestFileProvider:
    """``@file <path>`` end-to-end behaviour."""

    @pytest.mark.asyncio
    async def test_reads_repo_file(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "hello.txt").write_text("hi")
        ctx = ExpansionContext(charm_path=tmp_path)
        registry = context_providers_builtin.build_default_registry()
        result = await expand_mentions("see @file hello.txt", registry, ctx)
        assert "hi" in result.expanded

    @pytest.mark.asyncio
    async def test_rejects_traversal(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        registry = context_providers_builtin.build_default_registry()
        result = await expand_mentions("@file ../../etc/passwd", registry, ctx)
        assert "must stay within" in result.expanded
        assert result.blocks[0].ok is False

    @pytest.mark.asyncio
    async def test_rejects_absolute(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        registry = context_providers_builtin.build_default_registry()
        result = await expand_mentions("@file /etc/passwd", registry, ctx)
        assert result.blocks[0].ok is False

    @pytest.mark.asyncio
    async def test_missing_path(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        registry = context_providers_builtin.build_default_registry()
        result = await expand_mentions("@file does_not_exist.py", registry, ctx)
        assert result.blocks[0].ok is False

    @pytest.mark.asyncio
    async def test_bare_mention_at_eos_reports_missing_path(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        registry = context_providers_builtin.build_default_registry()
        # Bare ``@file`` with nothing after it — the scanner has no
        # token to consume, so the provider receives empty args.
        result = await expand_mentions("look @file", registry, ctx)
        assert "missing path" in result.expanded
        assert result.blocks[0].ok is False


class TestDiffProvider:
    """``@diff`` shells out to ``git diff HEAD``."""

    @pytest.mark.asyncio
    async def test_clean_tree_message(self, tmp_path: pathlib.Path) -> None:
        # Initialise an empty repo so ``git diff`` succeeds.
        subprocess.run(
            ["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True, text=True
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@e.com",
                "-c",
                "user.name=T",
                "commit",
                "--allow-empty",
                "-m",
                "init",
                "-q",
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        ctx = ExpansionContext(charm_path=tmp_path)
        registry = context_providers_builtin.build_default_registry()
        result = await expand_mentions("@diff", registry, ctx)
        assert "working tree clean" in result.expanded


class TestTreeProvider:
    """``@tree`` lists tracked files via ``git ls-files``."""

    @pytest.mark.asyncio
    async def test_lists_tracked_files(self, tmp_path: pathlib.Path) -> None:
        subprocess.run(
            ["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True, text=True
        )
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        ctx = ExpansionContext(charm_path=tmp_path)
        registry = context_providers_builtin.build_default_registry()
        result = await expand_mentions("@tree", registry, ctx)
        assert "a.py" in result.expanded
        assert "b.py" in result.expanded

    @pytest.mark.asyncio
    async def test_subdirectory_filter(self, tmp_path: pathlib.Path) -> None:
        subprocess.run(
            ["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True, text=True
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "x.py").write_text("x")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "y.py").write_text("y")
        ctx = ExpansionContext(charm_path=tmp_path)
        registry = context_providers_builtin.build_default_registry()
        result = await expand_mentions("@tree src", registry, ctx)
        assert "src/x.py" in result.expanded
        assert "tests/y.py" not in result.expanded


class TestExpansionResultShape:
    """Wire-format assertions used by the input-layer integration."""

    def test_unchanged_skip_signal(self) -> None:
        # Sanity check the `changed` shortcut so the input-layer code
        # can rely on it to skip transcript splits when nothing happened.
        unchanged = ExpansionResult(raw="x", expanded="x", blocks=())
        changed = ExpansionResult(raw="x", expanded="<x>", blocks=())
        assert unchanged.changed is False
        assert changed.changed is True

    def test_summary_short_blocks(self) -> None:
        result = ExpansionResult(
            raw="@diff",
            expanded="<diff>",
            blocks=(ContextBlock(raw="@diff", rendered="x" * 200),),
        )
        assert "@diff (200 chars)" in result.summary()

    def test_summary_kilochar_blocks(self) -> None:
        result = ExpansionResult(
            raw="@diff",
            expanded="<diff>",
            blocks=(ContextBlock(raw="@diff", rendered="x" * 4500),),
        )
        # Anything ≥1000 chars renders as ``Nk chars`` for compactness.
        assert "k chars" in result.summary()

    def test_summary_marks_errors(self) -> None:
        result = ExpansionResult(
            raw="@boom",
            expanded="[@boom: error: bang]",
            blocks=(ContextBlock(raw="@boom", rendered="[@boom: error: bang]", error="bang"),),
        )
        assert "@boom [error]" in result.summary()


class TestMentionAutocompleteFilter:
    """Helpers that drive the TUI's mention suggestion popup."""

    def test_trailing_prefix_at_end_of_input(self) -> None:
        from cantrip.tui.widgets.chat import _trailing_mention_prefix

        assert _trailing_mention_prefix("look at @fi", 11) == "@fi"

    def test_trailing_prefix_after_space(self) -> None:
        from cantrip.tui.widgets.chat import _trailing_mention_prefix

        # Cursor mid-input: prefix is the last @-segment up to cursor.
        assert _trailing_mention_prefix("hello @diff and bye", 11) == "@diff"

    def test_no_prefix_when_at_after_letter(self) -> None:
        from cantrip.tui.widgets.chat import _trailing_mention_prefix

        # Email-style: the @ is preceded by a letter, so it's not a mention.
        assert _trailing_mention_prefix("user@host", 9) is None

    def test_no_prefix_after_whitespace_breaks_segment(self) -> None:
        from cantrip.tui.widgets.chat import _trailing_mention_prefix

        # Once whitespace appears between @ and cursor the mention is
        # already complete — no popup.
        assert _trailing_mention_prefix("@diff and more", 14) is None

    def test_double_at_skipped(self) -> None:
        from cantrip.tui.widgets.chat import _trailing_mention_prefix

        # ``@@`` reserved for thread refs — no completion.
        assert _trailing_mention_prefix("see @@thread", 12) is None

    def test_filter_returns_matches_and_prefix(self) -> None:
        from cantrip.tui.widgets.chat import _filter_mentions

        catalogue = (
            ProviderInfo(name="diff", summary="", arg_style=ArgStyle.NONE),
            ProviderInfo(name="docs", summary="", arg_style=ArgStyle.REST_OF_LINE),
            ProviderInfo(name="file", summary="", arg_style=ArgStyle.TOKEN),
        )
        matches, prefix = _filter_mentions(catalogue, "look @d", 7)
        assert prefix == "@d"
        names = [m.name for m in matches]
        assert "diff" in names
        assert "docs" in names
        assert "file" not in names
