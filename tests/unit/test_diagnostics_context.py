"""Tests for project-wide diagnostics aggregation (Phase 72.4)."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from cantrip.agent import lint_context
from cantrip.agent.tools.post_edit_lint import DiagnosticsReport, FileDiagnostic


def _diag(
    tool: str = "ruff",
    file: str = "src/charm.py",
    severity: str = "error",
    code: str = "X001",
    message: str = "msg",
    line: int | None = 1,
    column: int | None = 1,
) -> FileDiagnostic:
    """Build a FileDiagnostic with sensible defaults for tests."""
    return FileDiagnostic(
        tool=tool,
        file=file,
        severity=severity,
        code=code,
        message=message,
        line=line,
        column=column,
    )


class TestDiagnosticsBlock:
    """Rendering and severity-grouping behaviour of the block dataclass."""

    def test_empty_block_renders_no_issues_message(self) -> None:
        block = lint_context.DiagnosticsBlock()
        assert block.is_empty() is True
        assert "no issues found" in block.to_text()

    def test_renders_groups_by_severity_with_summary(self) -> None:
        block = lint_context.DiagnosticsBlock(
            diagnostics=(
                _diag(severity="warning", code="W1", message="warn-a"),
                _diag(severity="error", code="E1", message="err-a"),
                _diag(severity="info", code="I1", message="info-a"),
            )
        )
        text = block.to_text()
        # Summary line shows all three counts.
        assert "1 error" in text
        assert "1 warning" in text
        assert "1 info" in text
        # Group headers appear in priority order.
        error_idx = text.index("**errors**")
        warning_idx = text.index("**warnings**")
        info_idx = text.index("**infos**")
        assert error_idx < warning_idx < info_idx

    def test_truncation_footer_mentions_suppressed_count(self) -> None:
        block = lint_context.DiagnosticsBlock(
            diagnostics=(_diag(),),
            truncated=7,
        )
        text = block.to_text()
        assert "7 more issues suppressed" in text
        assert "cantrip lint" in text

    def test_skipped_notes_render_after_diagnostics(self) -> None:
        block = lint_context.DiagnosticsBlock(
            diagnostics=(_diag(),),
            skipped=("ty: binary not found on PATH",),
        )
        text = block.to_text()
        assert "[skipped] ty: binary not found on PATH" in text

    def test_counts_by_severity_default_zero(self) -> None:
        counts = lint_context.DiagnosticsBlock().counts_by_severity()
        assert counts == {"error": 0, "warning": 0, "info": 0}


class TestAggregate:
    """Internal merge + sort + truncate path."""

    def test_merges_multi_tool_reports(self) -> None:
        reports = [
            DiagnosticsReport(diagnostics=[_diag(tool="ruff")]),
            DiagnosticsReport(diagnostics=[_diag(tool="ty")]),
            DiagnosticsReport(diagnostics=[_diag(tool="charmlint")]),
        ]
        block = lint_context._aggregate(reports, max_chars=lint_context.DEFAULT_MAX_CHARS)
        tools = {d.tool for d in block.diagnostics}
        assert tools == {"ruff", "ty", "charmlint"}
        assert block.truncated == 0

    def test_sort_orders_by_severity_then_file(self) -> None:
        reports = [
            DiagnosticsReport(
                diagnostics=[
                    _diag(severity="warning", file="zzz.py"),
                    _diag(severity="error", file="bbb.py"),
                    _diag(severity="info", file="aaa.py"),
                    _diag(severity="error", file="aaa.py"),
                ]
            )
        ]
        block = lint_context._aggregate(reports, max_chars=lint_context.DEFAULT_MAX_CHARS)
        files_in_order = [(d.severity, d.file) for d in block.diagnostics]
        # Errors first (alphabetical within), then warning, then info.
        assert files_in_order == [
            ("error", "aaa.py"),
            ("error", "bbb.py"),
            ("warning", "zzz.py"),
            ("info", "aaa.py"),
        ]

    def test_truncation_drops_tail_and_records_count(self) -> None:
        # Create twenty diagnostics with descending priority — the tail
        # (info severity) should drop first when ``max_chars`` is tight.
        diags = [_diag(severity="error", code=f"E{i:03d}", line=i) for i in range(10)]
        diags += [_diag(severity="info", code=f"I{i:03d}", line=i) for i in range(10)]
        block = lint_context._aggregate(
            [DiagnosticsReport(diagnostics=diags)],
            max_chars=300,  # tight cap — forces truncation
        )
        assert block.truncated > 0
        # All retained issues must be at error severity (the tail dropped first).
        retained_severities = {d.severity for d in block.diagnostics}
        assert retained_severities == {"error"}
        # Footer renders honestly.
        assert f"{block.truncated} more issue" in block.to_text()

    def test_zero_diagnostics_with_skipped_round_trips(self) -> None:
        block = lint_context._aggregate(
            [DiagnosticsReport(skipped=["ruff: binary not found on PATH"])],
            max_chars=lint_context.DEFAULT_MAX_CHARS,
        )
        assert block.diagnostics == ()
        assert block.skipped == ("ruff: binary not found on PATH",)


class TestDiagnosticsCache:
    """TTL semantics on the simple in-process cache."""

    async def test_put_then_get_returns_block(self, tmp_path: pathlib.Path) -> None:
        cache = lint_context.DiagnosticsCache(ttl_seconds=60.0)
        block = lint_context.DiagnosticsBlock(diagnostics=(_diag(),))
        await cache.put(tmp_path, block)
        cached = await cache.get(tmp_path)
        assert cached is block

    async def test_get_returns_none_for_unknown_key(self, tmp_path: pathlib.Path) -> None:
        cache = lint_context.DiagnosticsCache()
        assert await cache.get(tmp_path) is None

    async def test_entry_evicted_after_ttl(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache = lint_context.DiagnosticsCache(ttl_seconds=30.0)
        clock = {"t": 1000.0}
        monkeypatch.setattr(cache, "_now", lambda: clock["t"])
        block = lint_context.DiagnosticsBlock(diagnostics=(_diag(),))
        await cache.put(tmp_path, block)
        clock["t"] += 29.0
        assert await cache.get(tmp_path) is block  # within TTL
        clock["t"] += 5.0  # now 34s elapsed — past 30s TTL
        assert await cache.get(tmp_path) is None

    async def test_clear_drops_every_entry(self, tmp_path: pathlib.Path) -> None:
        cache = lint_context.DiagnosticsCache()
        await cache.put(tmp_path, lint_context.DiagnosticsBlock())
        await cache.put(tmp_path / "other", lint_context.DiagnosticsBlock())
        await cache.clear()
        assert await cache.get(tmp_path) is None
        assert await cache.get(tmp_path / "other") is None


class TestGatherProjectDiagnostics:
    """End-to-end aggregator with the runners stubbed."""

    @pytest.fixture
    def cache(self) -> lint_context.DiagnosticsCache:
        # Fresh cache per test so TTL caching can't bleed across tests.
        return lint_context.DiagnosticsCache(ttl_seconds=30.0)

    async def test_runs_three_tools_when_charm_metadata_present(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: lint_context.DiagnosticsCache,
    ) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "metadata.yaml").write_text("name: demo\n")

        called: list[str] = []

        async def fake_ruff(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            called.append("ruff")
            return DiagnosticsReport(
                diagnostics=[_diag(tool="ruff", code="F401", message="unused-os")]
            )

        async def fake_ty(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            called.append("ty")
            return DiagnosticsReport(diagnostics=[_diag(tool="ty", severity="warning")])

        async def fake_charmlint(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            called.append("charmlint")
            return DiagnosticsReport(diagnostics=[_diag(tool="charmlint", severity="info")])

        monkeypatch.setattr(lint_context, "_run_ruff", fake_ruff)
        monkeypatch.setattr(lint_context, "_run_ty", fake_ty)
        monkeypatch.setattr(lint_context, "_run_charmlint", fake_charmlint)

        block = await lint_context.gather_project_diagnostics(tmp_path, cache=cache)

        assert sorted(called) == ["charmlint", "ruff", "ty"]
        assert {d.tool for d in block.diagnostics} == {"ruff", "ty", "charmlint"}

    async def test_skips_charmlint_without_metadata(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: lint_context.DiagnosticsCache,
    ) -> None:
        called: list[str] = []

        async def noop_ruff(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            called.append("ruff")
            return DiagnosticsReport()

        async def noop_ty(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            called.append("ty")
            return DiagnosticsReport()

        async def boom_charmlint(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            called.append("charmlint")
            return DiagnosticsReport()

        monkeypatch.setattr(lint_context, "_run_ruff", noop_ruff)
        monkeypatch.setattr(lint_context, "_run_ty", noop_ty)
        monkeypatch.setattr(lint_context, "_run_charmlint", boom_charmlint)

        await lint_context.gather_project_diagnostics(tmp_path, cache=cache)

        assert "charmlint" not in called
        assert sorted(called) == ["ruff", "ty"]

    async def test_returns_cached_block_within_ttl(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: lint_context.DiagnosticsCache,
    ) -> None:
        invocations = {"n": 0}

        async def counting_ruff(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            invocations["n"] += 1
            return DiagnosticsReport(diagnostics=[_diag(code=f"R{invocations['n']}")])

        async def empty(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            return DiagnosticsReport()

        monkeypatch.setattr(lint_context, "_run_ruff", counting_ruff)
        monkeypatch.setattr(lint_context, "_run_ty", empty)

        first = await lint_context.gather_project_diagnostics(tmp_path, cache=cache)
        second = await lint_context.gather_project_diagnostics(tmp_path, cache=cache)

        assert invocations["n"] == 1  # second call hit the cache
        assert second.diagnostics == first.diagnostics

    async def test_force_refresh_bypasses_cache(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: lint_context.DiagnosticsCache,
    ) -> None:
        invocations = {"n": 0}

        async def counting_ruff(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            invocations["n"] += 1
            return DiagnosticsReport()

        async def empty(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            return DiagnosticsReport()

        monkeypatch.setattr(lint_context, "_run_ruff", counting_ruff)
        monkeypatch.setattr(lint_context, "_run_ty", empty)

        await lint_context.gather_project_diagnostics(tmp_path, cache=cache)
        await lint_context.gather_project_diagnostics(tmp_path, cache=cache, force_refresh=True)

        assert invocations["n"] == 2

    async def test_runner_crash_surfaces_as_skipped_note(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: lint_context.DiagnosticsCache,
    ) -> None:
        async def crashing_ruff(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            raise RuntimeError("ruff process died")

        async def empty(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            return DiagnosticsReport()

        monkeypatch.setattr(lint_context, "_run_ruff", crashing_ruff)
        monkeypatch.setattr(lint_context, "_run_ty", empty)

        block = await lint_context.gather_project_diagnostics(tmp_path, cache=cache)
        assert any("crashed" in note for note in block.skipped)

    async def test_uses_charm_root_when_src_and_tests_missing(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: lint_context.DiagnosticsCache,
    ) -> None:
        captured: dict[str, list[pathlib.Path]] = {}

        async def capturing_ruff(targets: list[pathlib.Path], **_kwargs: Any) -> DiagnosticsReport:
            captured["ruff"] = targets
            return DiagnosticsReport()

        async def empty(*_args: Any, **_kwargs: Any) -> DiagnosticsReport:
            return DiagnosticsReport()

        monkeypatch.setattr(lint_context, "_run_ruff", capturing_ruff)
        monkeypatch.setattr(lint_context, "_run_ty", empty)

        await lint_context.gather_project_diagnostics(tmp_path, cache=cache)

        assert captured["ruff"] == [tmp_path]


class TestSubagentPromptIntegration:
    """The subagent briefing picks up ``diagnostics_text`` when set."""

    def test_diagnostics_section_added_when_text_present(self) -> None:
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import SubagentContext, _build_subagent_prompt

        task = AgentTask(
            title="Build it",
            category=TaskCategory.BUILD,
            description="implement the charm",
        )
        context = SubagentContext(task=task, diagnostics_text="Current diagnostics: 1 error")
        prompt = _build_subagent_prompt(context)

        assert "## Current diagnostics" in prompt
        assert "Current diagnostics: 1 error" in prompt

    def test_diagnostics_section_omitted_when_text_missing(self) -> None:
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import SubagentContext, _build_subagent_prompt

        task = AgentTask(
            title="Build it",
            category=TaskCategory.BUILD,
            description="implement the charm",
        )
        context = SubagentContext(task=task)
        prompt = _build_subagent_prompt(context)

        assert "## Current diagnostics" not in prompt


class TestSlashDiagnostics:
    """The /diagnostics slash command renders the aggregator output."""

    async def test_handler_returns_followup_with_block(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from types import SimpleNamespace

        from cantrip.agent.commands import slash as slash_commands

        stub_block = lint_context.DiagnosticsBlock(diagnostics=(_diag(message="banner-line"),))

        async def fake_gather(*_args: Any, **_kwargs: Any) -> lint_context.DiagnosticsBlock:
            return stub_block

        monkeypatch.setattr(lint_context, "gather_project_diagnostics", fake_gather)

        # Minimal fake agent — slash_commands._handle_diagnostics only
        # reads ``agent.state.charm_path``.
        agent = SimpleNamespace(state=SimpleNamespace(charm_path=tmp_path))
        result = slash_commands._handle_diagnostics(agent, args="")  # type: ignore[arg-type]

        assert result.markdown is True
        assert result.followup is not None
        body = await result.followup
        assert "Project diagnostics" in body
        assert "banner-line" in body

    def test_handler_returns_error_text_without_charm_path(self) -> None:
        from types import SimpleNamespace

        from cantrip.agent.commands import slash as slash_commands

        agent = SimpleNamespace(state=SimpleNamespace(charm_path=None))
        result = slash_commands._handle_diagnostics(agent, args="")  # type: ignore[arg-type]

        assert result.followup is None
        assert "no charm path" in result.text.lower()


class TestExecutorAttachDiagnostics:
    """The executor populates ``diagnostics_text`` for BUILD/DEBUG only."""

    async def test_build_task_picks_up_diagnostics(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
    ) -> None:
        from cantrip.agent.executor import BackgroundExecutor
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import SubagentContext

        async def fake_gather(*_args: Any, **_kwargs: Any) -> lint_context.DiagnosticsBlock:
            return lint_context.DiagnosticsBlock(diagnostics=(_diag(message="brittle"),))

        monkeypatch.setattr(lint_context, "gather_project_diagnostics", fake_gather)

        task = AgentTask(title="Build", category=TaskCategory.BUILD)
        context = SubagentContext(task=task, charm_path=str(tmp_path))

        # ``_attach_diagnostics_brief`` is a method on BackgroundExecutor
        # but the only state it touches is the *context*, so we can call
        # it via the unbound descriptor with a plain ``object()`` self.
        await BackgroundExecutor._attach_diagnostics_brief.__get__(object())(context)  # type: ignore[arg-type]

        assert context.diagnostics_text is not None
        assert "brittle" in context.diagnostics_text

    async def test_research_task_skipped(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
    ) -> None:
        from cantrip.agent.executor import BackgroundExecutor
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import SubagentContext

        called = {"n": 0}

        async def boom_gather(*_args: Any, **_kwargs: Any) -> lint_context.DiagnosticsBlock:
            called["n"] += 1
            raise AssertionError("should not run for RESEARCH")

        monkeypatch.setattr(lint_context, "gather_project_diagnostics", boom_gather)

        task = AgentTask(title="Look stuff up", category=TaskCategory.RESEARCH)
        context = SubagentContext(task=task, charm_path=str(tmp_path))

        await BackgroundExecutor._attach_diagnostics_brief.__get__(object())(context)  # type: ignore[arg-type]

        assert called["n"] == 0
        assert context.diagnostics_text is None

    async def test_failure_in_aggregator_does_not_abort_launch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
    ) -> None:
        from cantrip.agent.executor import BackgroundExecutor
        from cantrip.agent.queue import AgentTask, TaskCategory
        from cantrip.agent.subagent import SubagentContext

        async def crashy_gather(*_args: Any, **_kwargs: Any) -> lint_context.DiagnosticsBlock:
            raise OSError("filesystem on fire")

        monkeypatch.setattr(lint_context, "gather_project_diagnostics", crashy_gather)

        task = AgentTask(title="Debug", category=TaskCategory.DEBUG)
        context = SubagentContext(task=task, charm_path=str(tmp_path))

        # Must not raise.
        await BackgroundExecutor._attach_diagnostics_brief.__get__(object())(context)  # type: ignore[arg-type]

        assert context.diagnostics_text is None
