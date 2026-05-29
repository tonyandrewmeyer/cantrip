"""Branch-coverage backfill for ``cantrip.agent.context.context_providers_builtin``.

The base ``test_context_providers.py`` exercises the parser, registry, and
each provider's happy-path / argument-validation surface.  This file
covers the failure / fallback branches the existing suite skips:
``_juju_config_is_readonly`` flag-prefix forms, ``_root_for`` fallbacks,
``FileProvider`` OSError on read, ``DiffProvider`` no-git / timeout /
OSError / non-zero rc / truncate paths, ``TreeProvider`` traversal /
non-directory / render error, ``_render_tree`` fallback walk and
elision, ``ProblemsProvider`` happy path + lint-error path,
``UrlProvider`` / ``CharmProvider`` / ``JujuProvider`` shell branches,
``DocsProvider`` end-to-end (missing args, missing query, missing
router, success, search failure), ``build_default_registry`` registers
``DocsProvider`` when given a router, and ``_as_protocol`` rejects a
non-conforming object.
"""

from __future__ import annotations

import dataclasses
import pathlib
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cantrip.agent.context import context_providers_builtin as cpb
from cantrip.agent.context.context_providers import (
    ExpansionContext,
)
from cantrip.agent.tools import ToolResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _CompletedProcess:
    """Stand-in for :class:`subprocess.CompletedProcess`."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


# ---------------------------------------------------------------------------
# _juju_config_is_readonly — flag-prefix forms
# ---------------------------------------------------------------------------


class TestJujuConfigIsReadOnly:
    """Mutation-flag rejection for the ``@juju config`` shape."""

    @pytest.mark.parametrize(
        "rest",
        [
            ["myapp", "--reset=key"],
            ["myapp", "--reset-from-file=overrides.yaml"],
            ["myapp", "--file=overrides.yaml"],
        ],
    )
    def test_attached_value_forms_are_rejected(self, rest: list[str]) -> None:
        # The bare-flag forms are exercised by test_context_providers.py;
        # the ``--flag=value`` shape is a separate branch in
        # ``_juju_config_is_readonly``.
        assert cpb._juju_config_is_readonly(rest) is False

    def test_read_only_form_passes(self) -> None:
        assert cpb._juju_config_is_readonly(["myapp", "logging-config"]) is True


# ---------------------------------------------------------------------------
# _root_for — fallback ladder
# ---------------------------------------------------------------------------


class TestRootFor:
    """``_root_for`` picks charm_path → repo_root → cwd in order."""

    def test_uses_charm_path_when_set(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        assert cpb._root_for(ctx) == tmp_path

    def test_falls_back_to_repo_root_when_no_charm_path(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(repo_root=tmp_path)
        assert cpb._root_for(ctx) == tmp_path

    def test_falls_back_to_cwd_when_neither_is_set(self) -> None:
        # No fixtures touch ``ExpansionContext``, so a bare instance is
        # the third-fallback case.  ``cwd()`` may differ between the
        # test invocation and the assertion if a fixture changes
        # directory; we only assert it routes through ``Path.cwd``.
        ctx = ExpansionContext()
        with patch(
            "cantrip.agent.context.context_providers_builtin.pathlib.Path.cwd",
            return_value=pathlib.Path("/tmp/synthetic-cwd"),
        ):
            assert cpb._root_for(ctx) == pathlib.Path("/tmp/synthetic-cwd")


# ---------------------------------------------------------------------------
# FileProvider read-error path
# ---------------------------------------------------------------------------


class TestFileProviderReadError:
    """``FileProvider.expand`` reports OS errors inline."""

    @pytest.mark.asyncio
    async def test_oserror_during_read_is_reported(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "x.txt"
        target.write_text("payload")
        ctx = ExpansionContext(charm_path=tmp_path)
        provider = cpb.FileProvider()

        with patch.object(
            pathlib.Path,
            "read_text",
            side_effect=OSError("permission denied"),
        ):
            block = await provider.expand("x.txt", ctx)

        assert block.ok is False
        assert "permission denied" in block.rendered


# ---------------------------------------------------------------------------
# DiffProvider — every branch except the clean-tree case
# ---------------------------------------------------------------------------


class TestDiffProviderBranches:
    """``DiffProvider`` failure / non-clean / truncate paths."""

    @pytest.mark.asyncio
    async def test_no_git_on_path(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        with patch(
            "cantrip.agent.context.context_providers_builtin.shutil.which", return_value=None
        ):
            block = await cpb.DiffProvider().expand("", ctx)
        assert "git not installed" in block.rendered
        assert block.ok is False

    @pytest.mark.asyncio
    async def test_timeout_during_diff(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/git",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git diff", timeout=1),
            ),
        ):
            block = await cpb.DiffProvider().expand("", ctx)
        assert "timed out" in block.rendered
        assert block.ok is False

    @pytest.mark.asyncio
    async def test_oserror_during_diff(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/git",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                side_effect=OSError("ebadf"),
            ),
        ):
            block = await cpb.DiffProvider().expand("", ctx)
        assert "ebadf" in block.rendered
        assert block.ok is False

    @pytest.mark.asyncio
    async def test_non_zero_returncode(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/git",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                return_value=_CompletedProcess(returncode=128, stderr="not a repository"),
            ),
        ):
            block = await cpb.DiffProvider().expand("", ctx)
        assert "not a repository" in block.rendered
        assert "git returned 128" in block.rendered
        assert block.ok is False

    @pytest.mark.asyncio
    async def test_renders_truncated_diff_body(self, tmp_path: pathlib.Path) -> None:
        # A non-empty diff exercises the ``truncate`` happy path that
        # the existing clean-tree test does not reach.
        ctx = ExpansionContext(charm_path=tmp_path)
        diff_text = "diff --git a/x b/x\n+hello\n"
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/git",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                return_value=_CompletedProcess(returncode=0, stdout=diff_text),
            ),
        ):
            block = await cpb.DiffProvider().expand("", ctx)
        assert block.ok is True
        assert "hello" in block.rendered


# ---------------------------------------------------------------------------
# TreeProvider — early-return branches
# ---------------------------------------------------------------------------


class TestTreeProviderBranches:
    """``TreeProvider`` traversal / non-directory / error paths."""

    @pytest.mark.asyncio
    async def test_traversal_args_are_rejected(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        block = await cpb.TreeProvider().expand("../etc", ctx)
        assert block.ok is False
        assert "must stay within" in block.rendered

    @pytest.mark.asyncio
    async def test_path_arg_pointing_at_a_file_is_rejected(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "f.py").write_text("x")
        ctx = ExpansionContext(charm_path=tmp_path)
        block = await cpb.TreeProvider().expand("f.py", ctx)
        assert block.ok is False
        assert "not a directory" in block.rendered

    @pytest.mark.asyncio
    async def test_render_tree_error_is_surfaced(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        # Force ``_render_tree`` to return an error string — the provider
        # should pass it through unchanged.
        with patch(
            "cantrip.agent.context.context_providers_builtin._render_tree",
            return_value=("", "synthetic-failure"),
        ):
            block = await cpb.TreeProvider().expand("", ctx)
        assert block.ok is False
        assert "synthetic-failure" in block.rendered


# ---------------------------------------------------------------------------
# _render_tree — git fallbacks and walk path
# ---------------------------------------------------------------------------


class TestRenderTree:
    """``_render_tree`` git failure → fallback walk, elision, errors."""

    def test_git_timeout_returns_error_string(self, tmp_path: pathlib.Path) -> None:
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/git",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=1),
            ),
        ):
            text, error = cpb._render_tree(tmp_path, tmp_path)
        assert text == ""
        assert "timed out" in error.lower() or "timeout" in error.lower()

    def test_subdir_outside_repo_falls_back_to_dot(self, tmp_path: pathlib.Path) -> None:
        # ``rel_target`` cannot be derived because *target* is not a
        # subpath of *repo_root* — the helper should fall back to ``.``.
        outside = tmp_path / "outside"
        outside.mkdir()
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/git",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                return_value=_CompletedProcess(returncode=0, stdout="a.py\nb.py\n"),
            ),
        ):
            text, error = cpb._render_tree(outside, repo_root)
        assert error == ""
        assert "a.py" in text
        assert "b.py" in text

    def test_git_returns_no_files(self, tmp_path: pathlib.Path) -> None:
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/git",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                return_value=_CompletedProcess(returncode=0, stdout=""),
            ),
        ):
            text, error = cpb._render_tree(tmp_path, tmp_path)
        assert error == ""
        assert "no tracked files" in text

    def test_elides_when_over_limit(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("cantrip.agent.context.context_providers_builtin._TREE_MAX_FILES", 3)
        files = "\n".join(f"f{i}.py" for i in range(7))
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/git",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                return_value=_CompletedProcess(returncode=0, stdout=files),
            ),
        ):
            text, error = cpb._render_tree(tmp_path, tmp_path)
        assert error == ""
        assert "more files elided" in text

    def test_fallback_walk_when_git_missing(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("b")
        with patch(
            "cantrip.agent.context.context_providers_builtin.shutil.which", return_value=None
        ):
            text, error = cpb._render_tree(tmp_path, tmp_path)
        assert error == ""
        assert "a.py" in text
        assert "sub/b.py" in text

    def test_fallback_walk_empty_directory(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.context.context_providers_builtin.shutil.which", return_value=None
        ):
            text, error = cpb._render_tree(tmp_path, tmp_path)
        assert error == ""
        assert text == "(empty)"

    def test_fallback_walk_oserror_returns_error(self, tmp_path: pathlib.Path) -> None:
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which", return_value=None
            ),
            patch.object(
                pathlib.Path,
                "rglob",
                side_effect=OSError("io error"),
            ),
        ):
            text, error = cpb._render_tree(tmp_path, tmp_path)
        assert text == ""
        assert "io error" in error

    def test_fallback_walk_elides(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("cantrip.agent.context.context_providers_builtin._TREE_MAX_FILES", 2)
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x")
        with patch(
            "cantrip.agent.context.context_providers_builtin.shutil.which", return_value=None
        ):
            text, error = cpb._render_tree(tmp_path, tmp_path)
        assert error == ""
        assert "more files elided" in text


# ---------------------------------------------------------------------------
# ProblemsProvider
# ---------------------------------------------------------------------------


class TestProblemsProvider:
    """``@problems`` runs the lint sweep and renders the result."""

    @pytest.mark.asyncio
    async def test_renders_diagnostics_block(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        block_obj = MagicMock()
        block_obj.to_text.return_value = "RUFF: 1 issue\n"
        with patch(
            "cantrip.agent.context.context_providers_builtin.lint_context.gather_project_diagnostics",
            new_callable=AsyncMock,
            return_value=block_obj,
        ):
            block = await cpb.ProblemsProvider().expand("", ctx)
        assert block.ok is True
        assert "RUFF: 1 issue" in block.rendered

    @pytest.mark.asyncio
    async def test_lint_error_is_inlined(self, tmp_path: pathlib.Path) -> None:
        ctx = ExpansionContext(charm_path=tmp_path)
        with patch(
            "cantrip.agent.context.context_providers_builtin.lint_context.gather_project_diagnostics",
            new_callable=AsyncMock,
            side_effect=RuntimeError("lint died"),
        ):
            block = await cpb.ProblemsProvider().expand("", ctx)
        assert block.ok is False
        assert "lint died" in block.rendered


# ---------------------------------------------------------------------------
# UrlProvider / CharmProvider — success + tool-error paths
# ---------------------------------------------------------------------------


def _result(success: bool, output: str = "", error: str | None = None) -> ToolResult:
    return ToolResult(success=success, output=output, error=error)


class TestUrlProviderShell:
    """``UrlProvider`` success / failure routing through WebFetchTool."""

    @pytest.mark.asyncio
    async def test_success_returns_truncated_body(self) -> None:
        with patch(
            "cantrip.agent.context.context_providers_builtin.web_tools.WebFetchTool"
        ) as cls:
            cls.return_value.execute = AsyncMock(return_value=_result(True, "<body>"))
            block = await cpb.UrlProvider().expand(
                "https://canonical.com",
                ExpansionContext(),
            )
        assert block.ok is True
        assert "<body>" in block.rendered

    @pytest.mark.asyncio
    async def test_failure_inlined(self) -> None:
        with patch(
            "cantrip.agent.context.context_providers_builtin.web_tools.WebFetchTool"
        ) as cls:
            cls.return_value.execute = AsyncMock(
                return_value=_result(False, "", error="rate limited")
            )
            block = await cpb.UrlProvider().expand(
                "https://canonical.com",
                ExpansionContext(),
            )
        assert block.ok is False
        assert "rate limited" in block.rendered


class TestCharmProviderShell:
    """``CharmProvider`` success / failure routing through CharmhubInfoTool."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch(
            "cantrip.agent.context.context_providers_builtin.charmhub_tools.CharmhubInfoTool"
        ) as cls:
            cls.return_value.execute = AsyncMock(return_value=_result(True, "name: postgresql"))
            block = await cpb.CharmProvider().expand("postgresql", ExpansionContext())
        assert block.ok is True
        assert "postgresql" in block.rendered

    @pytest.mark.asyncio
    async def test_failure(self) -> None:
        with patch(
            "cantrip.agent.context.context_providers_builtin.charmhub_tools.CharmhubInfoTool"
        ) as cls:
            cls.return_value.execute = AsyncMock(
                return_value=_result(False, "", error="not found")
            )
            block = await cpb.CharmProvider().expand(
                "no-such-charm",
                ExpansionContext(),
            )
        assert block.ok is False
        assert "not found" in block.rendered


# ---------------------------------------------------------------------------
# PresetProvider — catalogue index / single-preset / unknown-slug
# ---------------------------------------------------------------------------


class TestPresetProviderShell:
    """``PresetProvider`` reads the in-repo catalogue — no I/O."""

    @pytest.mark.asyncio
    async def test_bare_renders_index(self) -> None:
        block = await cpb.PresetProvider().expand("", ExpansionContext())
        assert block.ok is True
        assert block.raw == "@preset"
        assert "`cos-lite`" in block.rendered
        assert "`identity-platform`" in block.rendered

    @pytest.mark.asyncio
    async def test_named_preset_renders_layout(self) -> None:
        block = await cpb.PresetProvider().expand("cos-lite", ExpansionContext())
        assert block.ok is True
        assert block.raw == "@preset cos-lite"
        assert "COS Lite" in block.rendered
        # Apps grouped by layer + edges with interface names.
        assert "**Routing**" in block.rendered
        assert "alertmanager_dispatch" in block.rendered

    @pytest.mark.asyncio
    async def test_unknown_slug_is_inline_error(self) -> None:
        block = await cpb.PresetProvider().expand("no-such-bundle", ExpansionContext())
        assert block.ok is False
        assert "unknown preset" in block.rendered
        assert "cos-lite" in block.rendered  # lists the known slugs

    def test_registered_in_default_registry(self) -> None:
        assert "preset" in cpb.build_default_registry().names()


# ---------------------------------------------------------------------------
# JujuProvider — actual subprocess routing
# ---------------------------------------------------------------------------


class TestJujuProviderShell:
    """``JujuProvider`` covers the ``juju`` subprocess path."""

    @pytest.mark.asyncio
    async def test_no_juju_on_path(self) -> None:
        with patch(
            "cantrip.agent.context.context_providers_builtin.shutil.which", return_value=None
        ):
            block = await cpb.JujuProvider().expand("status", ExpansionContext())
        assert block.ok is False
        assert "juju not installed" in block.rendered

    @pytest.mark.asyncio
    async def test_timeout_is_reported(self) -> None:
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/juju",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="juju", timeout=1),
            ),
        ):
            block = await cpb.JujuProvider().expand("status", ExpansionContext())
        assert block.ok is False
        assert "timed out" in block.rendered

    @pytest.mark.asyncio
    async def test_oserror_is_reported(self) -> None:
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/juju",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                side_effect=OSError("eperm"),
            ),
        ):
            block = await cpb.JujuProvider().expand("status", ExpansionContext())
        assert block.ok is False
        assert "eperm" in block.rendered

    @pytest.mark.asyncio
    async def test_non_zero_rc_includes_stderr(self) -> None:
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/juju",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                return_value=_CompletedProcess(returncode=1, stderr="model not found"),
            ),
        ):
            block = await cpb.JujuProvider().expand("status", ExpansionContext())
        assert block.ok is False
        assert "model not found" in block.rendered

    @pytest.mark.asyncio
    async def test_non_zero_rc_with_blank_stderr_uses_default_message(self) -> None:
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/juju",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                return_value=_CompletedProcess(returncode=2, stderr=""),
            ),
        ):
            block = await cpb.JujuProvider().expand("status", ExpansionContext())
        assert block.ok is False
        assert "command failed" in block.rendered

    @pytest.mark.asyncio
    async def test_success_returns_stdout(self) -> None:
        with (
            patch(
                "cantrip.agent.context.context_providers_builtin.shutil.which",
                return_value="/bin/juju",
            ),
            patch(
                "cantrip.agent.context.context_providers_builtin.subprocess.run",
                return_value=_CompletedProcess(returncode=0, stdout="App  Status\nfoo  active"),
            ),
        ):
            block = await cpb.JujuProvider().expand("status", ExpansionContext())
        assert block.ok is True
        assert "active" in block.rendered


# ---------------------------------------------------------------------------
# DocsProvider
# ---------------------------------------------------------------------------


class TestDocsProvider:
    """``@docs <site> <query>`` end-to-end shape."""

    @pytest.mark.asyncio
    async def test_missing_args(self) -> None:
        block = await cpb.DocsProvider().expand("", ExpansionContext())
        assert block.ok is False
        assert "usage" in block.rendered.lower()

    @pytest.mark.asyncio
    async def test_missing_query(self) -> None:
        block = await cpb.DocsProvider().expand("ops", ExpansionContext())
        assert block.ok is False
        assert "missing query" in block.rendered

    @pytest.mark.asyncio
    async def test_no_role_router(self) -> None:
        # ``role_router=None`` is the default; the provider must not
        # try to construct ``DocsSearchTool`` in that case.
        block = await cpb.DocsProvider().expand("ops secrets", ExpansionContext())
        assert block.ok is False
        assert "no role router" in block.rendered

    @pytest.mark.asyncio
    async def test_search_failure_inlined(self, tmp_path: pathlib.Path) -> None:
        router = MagicMock()
        provider = cpb.DocsProvider(role_router=router, cache_root=tmp_path)
        with patch("cantrip.agent.tools.docs_search.DocsSearchTool") as cls:
            cls.return_value.execute = AsyncMock(
                return_value=_result(False, "", error="index empty")
            )
            block = await provider.expand("ops secrets", ExpansionContext())
        assert block.ok is False
        assert "index empty" in block.rendered

    @pytest.mark.asyncio
    async def test_search_success_returns_truncated_body(self, tmp_path: pathlib.Path) -> None:
        router = MagicMock()
        provider = cpb.DocsProvider(role_router=router, cache_root=tmp_path)
        with patch("cantrip.agent.tools.docs_search.DocsSearchTool") as cls:
            cls.return_value.execute = AsyncMock(return_value=_result(True, "secrets are great"))
            block = await provider.expand("ops secrets", ExpansionContext())
        assert block.ok is True
        assert "secrets are great" in block.rendered


# ---------------------------------------------------------------------------
# build_default_registry / _as_protocol
# ---------------------------------------------------------------------------


class TestBuildDefaultRegistry:
    """Phase 72.1 router-aware registry assembly."""

    def test_includes_docs_when_router_provided(self) -> None:
        router = MagicMock()
        registry = cpb.build_default_registry(role_router=router)
        assert "docs" in registry.names()

    def test_omits_docs_without_router(self) -> None:
        registry = cpb.build_default_registry()
        assert "docs" not in registry.names()


class TestAsProtocol:
    """``_as_protocol`` rejects non-conforming objects."""

    def test_accepts_conformant_provider(self) -> None:
        provider = cpb.FileProvider()
        assert cpb._as_protocol(provider) is provider

    def test_rejects_non_provider(self) -> None:
        class _NotAProvider:
            pass

        with pytest.raises(TypeError):
            cpb._as_protocol(_NotAProvider())
