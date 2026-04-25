"""Tests for prompt-based review checks (Phase 70.4)."""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any

import pytest

from cantrip.agent import checks
from cantrip.llm.base import LLMProvider, Message, Response, Role

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _write_check(path: pathlib.Path, body: str) -> None:
    path.write_text(body)


def _check(name: str = "demo", **overrides: Any) -> checks.Check:
    """Build an in-memory Check for runner tests that don't load from disk."""
    defaults: dict[str, Any] = {
        "name": name,
        "description": "test check",
        "severity": "warning",
        "globs": (),
        "tools": (),
        "body": "Evaluate the rule.",
        "path": pathlib.Path(f"/tmp/{name}.md"),
        "source": checks.SOURCE_BUNDLED,
    }
    defaults.update(overrides)
    return checks.Check(**defaults)


@dataclasses.dataclass
class StubProvider:
    """Tiny LLMProvider stand-in for unit tests.

    Records the messages it receives so a test can assert what the
    runner actually sent the model, and returns a canned JSON string
    that the structured-output path validates against
    ``CHECK_RESULT``.
    """

    payload: dict[str, Any]
    name: str = "stub"
    model_name: str = "stub-1"
    context_window_tokens: int = 8192
    max_tools: int | None = None
    supports_response_schema: bool = False
    received: list[list[Message]] = dataclasses.field(default_factory=list)

    async def complete(self, *, messages: list[Message], **_kwargs: Any) -> Response:
        import json

        self.received.append(list(messages))
        return Response(content=json.dumps(self.payload), tool_calls=[])

    async def stream(self, *, messages: list[Message], **_kwargs: Any):  # pragma: no cover
        raise NotImplementedError("StubProvider only implements complete()")


# ---------------------------------------------------------------------------
# Loader / discovery
# ---------------------------------------------------------------------------


class TestParseCheckFile:
    """Frontmatter parsing — required fields, severity coercion, etc."""

    def test_minimum_valid_check_parses(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "demo.md"
        _write_check(
            path,
            "---\nname: demo\ndescription: A demo check.\n---\n\nEvaluate the rule.\n",
        )
        check = checks._parse_check_file(path, source=checks.SOURCE_BUNDLED)
        assert check.name == "demo"
        assert check.severity == "warning"  # default
        assert check.globs == ()
        assert check.body == "Evaluate the rule."
        assert check.source == checks.SOURCE_BUNDLED

    def test_severity_coerced_when_unknown(
        self,
        tmp_path: pathlib.Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = tmp_path / "demo.md"
        _write_check(
            path,
            "---\nname: demo\ndescription: x\nseverity: catastrophic\n---\n\nbody\n",
        )
        check = checks._parse_check_file(path, source=checks.SOURCE_BUNDLED)
        assert check.severity == "warning"  # falls back to default
        assert "unknown severity" in caplog.text

    def test_globs_and_tools_coerced_to_tuples(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "demo.md"
        _write_check(
            path,
            "---\n"
            "name: demo\n"
            "description: x\n"
            "globs: [README.md, src/*.py]\n"
            "tools: read_file, list_files\n"
            "---\n\nbody\n",
        )
        check = checks._parse_check_file(path, source=checks.SOURCE_BUNDLED)
        assert check.globs == ("README.md", "src/*.py")
        # Comma-separated string accepted, same as the skills loader.
        assert check.tools == ("read_file", "list_files")

    def test_missing_name_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "demo.md"
        _write_check(path, "---\ndescription: x\n---\n\nbody\n")
        with pytest.raises(ValueError, match="must contain 'name'"):
            checks._parse_check_file(path, source=checks.SOURCE_BUNDLED)

    def test_missing_closing_delimiter_raises(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "demo.md"
        _write_check(path, "---\nname: demo\ndescription: x\nbody never closes")
        with pytest.raises(ValueError, match="closing frontmatter"):
            checks._parse_check_file(path, source=checks.SOURCE_BUNDLED)

    def test_empty_body_raises(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "demo.md"
        _write_check(path, "---\nname: demo\ndescription: x\n---\n")
        with pytest.raises(ValueError, match="check body is empty"):
            checks._parse_check_file(path, source=checks.SOURCE_BUNDLED)


class TestCheckIndexPrecedence:
    """Repo overrides user overrides bundled, with shadow diagnostics."""

    def test_repo_shadows_user_shadows_bundled(self, tmp_path: pathlib.Path) -> None:
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"
        repo = tmp_path / "repo" / ".cantrip" / "checks"
        for d in (bundled, user, repo):
            d.mkdir(parents=True)

        _write_check(
            bundled / "shared.md",
            "---\nname: shared\ndescription: bundled\n---\n\nbundled-body\n",
        )
        _write_check(
            user / "shared.md",
            "---\nname: shared\ndescription: user\n---\n\nuser-body\n",
        )
        _write_check(
            repo / "shared.md",
            "---\nname: shared\ndescription: repo\n---\n\nrepo-body\n",
        )

        index = checks.CheckIndex(
            project_root=tmp_path / "repo",
            user_dir=user,
            bundled_dir=bundled,
        )
        discovered = index.discover()

        assert len(discovered) == 1
        assert discovered[0].body == "repo-body"
        assert discovered[0].source == checks.SOURCE_REPO
        # Two shadow notes — bundled→user, user→repo.
        assert len(index.shadows) == 2
        assert any("bundled" in s for s in index.shadows)
        assert any("user" in s for s in index.shadows)

    def test_only_bundled_when_no_user_or_repo_dirs(self, tmp_path: pathlib.Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        _write_check(
            bundled / "demo.md",
            "---\nname: demo\ndescription: d\n---\n\nbody\n",
        )
        index = checks.CheckIndex(
            project_root=tmp_path / "no-such-repo",
            user_dir=tmp_path / "no-such-user",
            bundled_dir=bundled,
        )
        assert [c.name for c in index.discover()] == ["demo"]
        assert index.shadows == []

    def test_malformed_check_skipped_with_warning(
        self,
        tmp_path: pathlib.Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        _write_check(bundled / "good.md", "---\nname: good\ndescription: d\n---\n\nbody\n")
        _write_check(bundled / "bad.md", "no frontmatter at all")
        index = checks.CheckIndex(
            user_dir=tmp_path / "no-user",
            bundled_dir=bundled,
        )
        names = [c.name for c in index.discover()]
        assert names == ["good"]
        assert "Skipping malformed check" in caplog.text


class TestBundledChecks:
    """The three built-in checks shipped with Cantrip parse and round-trip."""

    def test_bundled_dir_loads_three_checks(self) -> None:
        index = checks.CheckIndex(
            project_root=pathlib.Path("/no-such-repo"),
            user_dir=pathlib.Path("/no-such-user"),
        )
        names = [c.name for c in index.discover()]
        # Spec ships three: README coherence, action ergonomics,
        # relation-data hygiene.
        assert "charm-readme-coherence" in names
        assert "action-ergonomics" in names
        assert "relation-data-hygiene" in names


# ---------------------------------------------------------------------------
# Glob scoping
# ---------------------------------------------------------------------------


class TestGlobScoping:
    """Glob matches mirror the skills convention (path vs basename)."""

    def test_basename_pattern_matches_anywhere(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "src" / "deep" / "README.md"
        target.parent.mkdir(parents=True)
        target.write_text("ok")
        assert checks._matches_globs(target, ("README.md",), tmp_path)

    def test_path_pattern_anchored_to_charm_root(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "src" / "charm.py"
        target.parent.mkdir(parents=True)
        target.write_text("ok")
        assert checks._matches_globs(target, ("src/*.py",), tmp_path)
        assert not checks._matches_globs(target, ("tests/*.py",), tmp_path)

    def test_double_star_matches_any_depth(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "src" / "a" / "b" / "thing.py"
        target.parent.mkdir(parents=True)
        target.write_text("ok")
        assert checks._matches_globs(target, ("src/**/*.py",), tmp_path)

    def test_scope_files_returns_subset(self, tmp_path: pathlib.Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("hi")
        charm = tmp_path / "src" / "charm.py"
        charm.parent.mkdir()
        charm.write_text("class Charm: pass")
        check = _check(globs=("README.md",))
        scoped = checks._scope_files(check, charm_root=tmp_path, candidate_files=[readme, charm])
        assert scoped == [readme]

    def test_scope_files_with_no_globs_returns_all(self, tmp_path: pathlib.Path) -> None:
        files = []
        for n in range(3):
            f = tmp_path / f"f{n}.py"
            f.write_text("x")
            files.append(f)
        check = _check(globs=())
        scoped = checks._scope_files(check, charm_root=tmp_path, candidate_files=files)
        assert scoped == files

    def test_scope_files_capped(self, tmp_path: pathlib.Path) -> None:
        files = []
        for n in range(checks._MAX_FILES_PER_CHECK + 5):
            f = tmp_path / f"f{n}.py"
            f.write_text("x")
            files.append(f)
        check = _check(globs=())
        scoped = checks._scope_files(check, charm_root=tmp_path, candidate_files=files)
        assert len(scoped) == checks._MAX_FILES_PER_CHECK


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class TestRunCheck:
    """Single-check runner — pass / fail / error / skipped paths."""

    async def test_pass_status_propagates(self, tmp_path: pathlib.Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("hello")
        provider = StubProvider(payload={"status": "pass", "message": "looks fine"})
        result = await checks.run_check(
            _check(severity="warning"),
            provider=provider,  # type: ignore[arg-type]
            charm_root=tmp_path,
            files=[readme],
        )
        assert result.status == "pass"
        assert result.message == "looks fine"
        assert not result.is_failure()

    async def test_fail_status_with_evidence(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "README.md"
        target.write_text("hello")
        provider = StubProvider(
            payload={
                "status": "fail",
                "severity": "error",
                "message": "README is empty of substance",
                "evidence": "Just 'hello'",
                "suggested_fix": "Add a description paragraph",
            }
        )
        result = await checks.run_check(
            _check(severity="warning"),
            provider=provider,  # type: ignore[arg-type]
            charm_root=tmp_path,
            files=[target],
        )
        assert result.status == "fail"
        assert result.severity == "error"  # model overrode the rule's default
        assert result.evidence == "Just 'hello'"
        assert result.suggested_fix == "Add a description paragraph"
        assert result.is_failure()

    async def test_no_files_returns_skipped(self, tmp_path: pathlib.Path) -> None:
        provider = StubProvider(payload={"status": "pass", "message": "n/a"})
        result = await checks.run_check(
            _check(),
            provider=provider,  # type: ignore[arg-type]
            charm_root=tmp_path,
            files=[],
        )
        assert result.status == "skipped"
        # Provider must not have been invoked when no files matched.
        assert provider.received == []

    async def test_invalid_status_coerced_to_error(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "README.md"
        target.write_text("x")
        provider = StubProvider(payload={"status": "maybe", "message": "uncertain"})
        result = await checks.run_check(
            _check(),
            provider=provider,  # type: ignore[arg-type]
            charm_root=tmp_path,
            files=[target],
        )
        # ``maybe`` is not in {pass, fail} — runner coerces to "error"
        # rather than a silent pass.
        assert result.status == "error"

    async def test_severity_falls_back_to_check_default(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "README.md"
        target.write_text("x")
        provider = StubProvider(
            payload={
                "status": "fail",
                "severity": "lava-hot",  # unknown severity
                "message": "bad",
            }
        )
        result = await checks.run_check(
            _check(severity="critical"),
            provider=provider,  # type: ignore[arg-type]
            charm_root=tmp_path,
            files=[target],
        )
        assert result.severity == "critical"  # rule's own severity wins

    async def test_provider_failure_surfaces_as_error_status(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "README.md"
        target.write_text("x")

        class CrashingProvider(StubProvider):
            async def complete(self, **_kwargs: Any) -> Response:
                raise RuntimeError("network on fire")

        provider = CrashingProvider(payload={})
        result = await checks.run_check(
            _check(),
            provider=provider,  # type: ignore[arg-type]
            charm_root=tmp_path,
            files=[target],
        )
        assert result.status == "error"
        assert "network on fire" in result.message

    async def test_user_prompt_includes_rule_body_and_files(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "README.md"
        target.write_text("MAGIC-MARKER-TEXT")
        provider = StubProvider(payload={"status": "pass", "message": "ok"})
        await checks.run_check(
            _check(body="rule says: do the thing"),
            provider=provider,  # type: ignore[arg-type]
            charm_root=tmp_path,
            files=[target],
        )
        assert provider.received, "provider was not called"
        user_msg = next(m for m in provider.received[0] if m.role == Role.USER)
        assert "rule says: do the thing" in user_msg.content
        assert "MAGIC-MARKER-TEXT" in user_msg.content


class TestRunAllChecks:
    """End-to-end aggregation."""

    async def test_aggregate_orders_failures_first(self, tmp_path: pathlib.Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("hello")

        provider = StubProvider(payload={"status": "fail", "message": "broken"})
        provider2 = StubProvider(payload={"status": "pass", "message": "ok"})

        # Use a dispatcher provider that returns different verdicts per call.
        verdicts = iter(
            [
                {"status": "pass", "message": "ok-1"},
                {"status": "fail", "message": "bad-2"},
                {"status": "pass", "message": "ok-3"},
            ]
        )

        class Sequencer(StubProvider):
            async def complete(self, **_kwargs: Any) -> Response:
                import json

                return Response(content=json.dumps(next(verdicts)), tool_calls=[])

        all_checks = [_check(name=f"c{i}") for i in range(3)]
        report = await checks.run_all_checks(
            all_checks,
            provider=Sequencer(payload={}),  # type: ignore[arg-type]
            charm_root=tmp_path,
            candidate_files=[readme],
        )
        # Failure renders first thanks to _result_sort_key.
        text = report.to_text()
        fail_idx = text.index("c1")
        pass_idx = text.index("c0")
        assert fail_idx < pass_idx
        assert report.has_failures()
        assert report.counts_by_status() == {
            "pass": 2,
            "fail": 1,
            "skipped": 0,
            "error": 0,
        }

        # Suppress unused-variable warnings.
        _ = (provider, provider2)

    async def test_shadow_diagnostics_included_in_report(self, tmp_path: pathlib.Path) -> None:
        report = await checks.run_all_checks(
            [],
            provider=StubProvider(payload={}),  # type: ignore[arg-type]
            charm_root=tmp_path,
            candidate_files=[],
            shadows=("`x` from repo shadows bundled",),
        )
        assert "Shadowed checks" in report.to_text()


# ---------------------------------------------------------------------------
# Slash command
# ---------------------------------------------------------------------------


class TestSlashReview:
    """The /review slash command wires the index + runner together."""

    async def test_handler_runs_checks_and_renders_markdown(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from types import SimpleNamespace

        from cantrip.agent import lint_context, slash_commands

        monkeypatch.setattr(
            lint_context,
            "gather_project_diagnostics",
            _stub_diagnostics,
        )
        canned_report = checks.CheckReport(
            results=(
                checks.CheckResult(
                    name="demo",
                    status="fail",
                    severity="warning",
                    message="no good",
                ),
            )
        )

        async def fake_run_all_checks(
            _discovered: Any,
            **_kwargs: Any,
        ) -> checks.CheckReport:
            return canned_report

        monkeypatch.setattr(checks, "run_all_checks", fake_run_all_checks)
        # Make sure CheckIndex.discover doesn't return empty (otherwise the
        # handler short-circuits before calling run_all_checks).
        monkeypatch.setattr(
            checks.CheckIndex,
            "discover",
            lambda _self: [_check(name="demo")],
        )

        agent = SimpleNamespace(
            state=SimpleNamespace(charm_path=tmp_path),
            provider=StubProvider(payload={}),
        )
        result = slash_commands._handle_review(agent, "")  # type: ignore[arg-type]
        assert result.markdown is True
        body = await result.followup
        assert "demo" in body
        assert "no good" in body

    async def test_handler_handles_empty_check_set(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from types import SimpleNamespace

        from cantrip.agent import slash_commands

        monkeypatch.setattr(
            checks.CheckIndex,
            "discover",
            lambda _self: [],
        )
        monkeypatch.setattr(checks.CheckIndex, "shadows", property(lambda _self: []))

        agent = SimpleNamespace(
            state=SimpleNamespace(charm_path=tmp_path),
            provider=StubProvider(payload={}),
        )
        result = slash_commands._handle_review(agent, "")  # type: ignore[arg-type]
        body = await result.followup
        assert "No checks configured" in body

    def test_handler_rejects_unknown_args(self) -> None:
        from types import SimpleNamespace

        from cantrip.agent import slash_commands

        agent = SimpleNamespace(
            state=SimpleNamespace(charm_path=pathlib.Path("/tmp")),
            provider=StubProvider(payload={}),
        )
        result = slash_commands._handle_review(agent, "--severity high")  # type: ignore[arg-type]
        assert result.followup is None
        assert "Per-check filters are not implemented" in result.text

    def test_handler_without_charm_path(self) -> None:
        from types import SimpleNamespace

        from cantrip.agent import slash_commands

        agent = SimpleNamespace(
            state=SimpleNamespace(charm_path=None),
            provider=StubProvider(payload={}),
        )
        result = slash_commands._handle_review(agent, "")  # type: ignore[arg-type]
        assert result.followup is None
        assert "no charm path" in result.text.lower()


async def _stub_diagnostics(*_args: Any, **_kwargs: Any):
    """Return an empty diagnostics block — slash test only cares about Checks."""
    from cantrip.agent.lint_context import DiagnosticsBlock

    return DiagnosticsBlock()


# Avoid an unused-import nag when ``LLMProvider`` is purely for typing.
_ = LLMProvider
