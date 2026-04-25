"""Tests for Phase 75.6 — high-traffic tools populate ``ToolResult.caption``.

The captions surface inline in the chat (TUI + Web) via the ``TOOL_INVOKED``
event and replace the formulaic ``tool_name(arg=value)`` fallback the agent
loop would otherwise synthesise.  These tests assert the caption shape for
the tools listed in the 75.6 exit criterion: file-system, git, and
charm-tooling.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.charm import (
    CharmcraftFetchLibsTool,
    CharmcraftPackTool,
    CharmValidateTool,
)
from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from cantrip.agent.tools.git import (
    GitCloneTool,
    GitCommitTool,
    GitPushTool,
)
from cantrip.agent.tools.glob import GlobTool
from cantrip.agent.tools.grep import GrepTool


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ===========================================================================
# File-system
# ===========================================================================


class TestFileSystemCaptions:
    @pytest.mark.asyncio
    async def test_read_file(self, temp_dir) -> None:
        target = temp_dir / "sample.txt"
        target.write_text("line 1\nline 2\nline 3\n")
        result = await ReadFileTool(base_path=temp_dir).execute(path="sample.txt")
        assert result.success
        assert result.caption == "Read 3 lines from sample.txt"

    @pytest.mark.asyncio
    async def test_read_file_range(self, temp_dir) -> None:
        target = temp_dir / "sample.txt"
        target.write_text("a\nb\nc\nd\ne\n")
        result = await ReadFileTool(base_path=temp_dir).execute(
            path="sample.txt", start_line=2, end_line=4
        )
        assert result.success
        # Two newlines in the slice ``b\nc\nd\n`` → caption reports 3 lines.
        assert result.caption == "Read 3 lines from sample.txt"

    @pytest.mark.asyncio
    async def test_write_file(self, temp_dir) -> None:
        result = await WriteFileTool(base_path=temp_dir).execute(path="out.txt", content="hello")
        assert result.success
        assert result.caption == "Wrote 5 bytes to out.txt"

    @pytest.mark.asyncio
    async def test_list_directory(self, temp_dir) -> None:
        (temp_dir / "a.txt").write_text("a")
        (temp_dir / "b.txt").write_text("b")
        result = await ListDirectoryTool(base_path=temp_dir).execute(path=".")
        assert result.success
        assert result.caption is not None
        assert result.caption.startswith("Listed 2 entries in")

    @pytest.mark.asyncio
    async def test_edit_file(self, temp_dir) -> None:
        target = temp_dir / "f.txt"
        target.write_text("hello world")
        result = await EditFileTool(base_path=temp_dir).execute(
            path="f.txt", old_string="world", new_string="cantrip"
        )
        assert result.success
        assert result.caption == "Edited f.txt (1 replacement)"

    @pytest.mark.asyncio
    async def test_grep_with_matches(self, temp_dir) -> None:
        # Build a fake search corpus where one term shows up in two files.
        (temp_dir / "a.py").write_text("HookEvent matters\n")
        (temp_dir / "b.py").write_text("HookEvent again\n")
        result = await GrepTool(base_path=temp_dir).execute(pattern="HookEvent", path=".")
        assert result.success
        # Caption shape: ``N matches for 'HookEvent' across 2 file(s)``.
        assert result.caption is not None
        assert result.caption.startswith("2 matches for 'HookEvent' across 2 file(s)")

    @pytest.mark.asyncio
    async def test_grep_no_matches(self, temp_dir) -> None:
        (temp_dir / "a.py").write_text("nothing interesting\n")
        result = await GrepTool(base_path=temp_dir).execute(pattern="ZZZ_unmatched", path=".")
        assert result.success
        assert result.caption == "No matches for 'ZZZ_unmatched'"

    @pytest.mark.asyncio
    async def test_glob_with_matches(self, temp_dir) -> None:
        (temp_dir / "a.py").write_text("a")
        (temp_dir / "b.py").write_text("b")
        (temp_dir / "c.txt").write_text("c")
        result = await GlobTool(base_path=temp_dir).execute(pattern="*.py", path=".")
        assert result.success
        assert result.caption is not None
        assert result.caption.startswith("2 files matching '*.py'")

    @pytest.mark.asyncio
    async def test_glob_no_matches(self, temp_dir) -> None:
        result = await GlobTool(base_path=temp_dir).execute(pattern="*.never", path=".")
        assert result.success
        assert result.caption == "No files matching '*.never'"


# ===========================================================================
# Git
# ===========================================================================


class TestGitCaptions:
    @pytest.mark.asyncio
    async def test_clone_strips_protocol_and_dot_git(self, temp_dir) -> None:
        # Stub _run_git so the test doesn't actually clone anything.
        from cantrip.agent.tools import git as git_mod

        async def _run_clone(url: str) -> mock.MagicMock:
            tool = GitCloneTool()
            with mock.patch.object(
                git_mod,
                "_run_git",
                return_value=git_mod.ToolResult(success=True, output=""),
            ):
                return await tool.execute(url=url)

        result = await _run_clone("https://github.com/foo/bar.git")
        assert result.caption == "Cloned github.com/foo/bar"

        result = await _run_clone("git@github.com:foo/bar.git")
        assert result.caption == "Cloned github.com:foo/bar"

    @pytest.mark.asyncio
    async def test_commit_subject(self, temp_dir) -> None:
        # Initialise a git repo with a staged change.
        subprocess.run(["git", "init", "-q"], cwd=temp_dir, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=temp_dir,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_dir, check=True)
        (temp_dir / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_dir, check=True)

        result = await GitCommitTool().execute(
            message="Add a thing\n\nLong body that should be ignored.",
            path=str(temp_dir),
        )
        assert result.success
        assert result.caption == "Committed: 'Add a thing'"

    @pytest.mark.asyncio
    async def test_commit_long_subject_truncated(self, temp_dir) -> None:
        subprocess.run(["git", "init", "-q"], cwd=temp_dir, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=temp_dir,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_dir, check=True)
        (temp_dir / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "file.txt"], cwd=temp_dir, check=True)

        long_msg = "A" * 80
        result = await GitCommitTool().execute(message=long_msg, path=str(temp_dir))
        assert result.success
        assert result.caption is not None
        assert "…" in result.caption

    @pytest.mark.asyncio
    async def test_push_caption(self) -> None:
        from cantrip.agent.tools import git as git_mod

        with mock.patch.object(
            git_mod,
            "_run_git",
            return_value=git_mod.ToolResult(success=True, output=""),
        ):
            result = await GitPushTool().execute(remote="origin", branch="main", confirmed=True)
        assert result.success
        assert result.caption == "Pushed → origin/main"

    @pytest.mark.asyncio
    async def test_push_caption_no_branch(self) -> None:
        from cantrip.agent.tools import git as git_mod

        with mock.patch.object(
            git_mod,
            "_run_git",
            return_value=git_mod.ToolResult(success=True, output=""),
        ):
            result = await GitPushTool().execute(remote="origin", confirmed=True)
        assert result.success
        assert result.caption == "Pushed → origin"


# ===========================================================================
# Charm tooling
# ===========================================================================


class TestCharmToolingCaptions:
    @pytest.mark.asyncio
    async def test_charmcraft_pack_caption(self, temp_dir) -> None:
        # Stub the subprocess call and pre-create a fake .charm file so the
        # tool's "find the created .charm" branch finds it.
        (temp_dir / "fake.charm").write_bytes(b"x" * (2 * 1024 * 1024))

        with mock.patch("cantrip.agent.tools.charm.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="ok", stderr="")
            result = await CharmcraftPackTool().execute(path=str(temp_dir))

        assert result.success
        assert result.caption is not None
        assert result.caption.startswith("Packed → fake.charm")
        assert "MB" in result.caption

    @pytest.mark.asyncio
    async def test_charmcraft_fetch_libs_count(self, temp_dir) -> None:
        with mock.patch("cantrip.agent.tools.charm.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout="Fetched library a.b\nFetched library c.d\n",
                stderr="",
            )
            result = await CharmcraftFetchLibsTool().execute(path=str(temp_dir))

        assert result.success
        assert result.caption == "Fetched 2 libs"
        assert result.data["fetched_count"] == 2

    @pytest.mark.asyncio
    async def test_charmcraft_fetch_libs_no_lines(self, temp_dir) -> None:
        with mock.patch("cantrip.agent.tools.charm.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
            result = await CharmcraftFetchLibsTool().execute(path=str(temp_dir))
        assert result.success
        assert result.caption == "Fetched libraries"

    @pytest.mark.asyncio
    async def test_charm_validate_caption(self, temp_dir) -> None:
        # CharmValidateTool runs RunCharmTestsTool + CharmcraftPackTool.
        # Stub both to deterministic passes.
        from cantrip.agent.tools import charm as charm_mod

        fake_tests_result = mock.AsyncMock(
            return_value=mock.MagicMock(
                success=True,
                output="passed",
                data={"summary": "12 passed"},
            )
        )
        fake_pack_result = mock.AsyncMock(
            return_value=mock.MagicMock(
                success=True,
                output="ok",
                data={"charm_file": str(temp_dir / "fake.charm")},
                error=None,
            )
        )
        with (
            mock.patch.object(charm_mod, "RunCharmTestsTool") as fake_tests_cls,
            mock.patch.object(charm_mod, "CharmcraftPackTool") as fake_pack_cls,
        ):
            fake_tests_cls.return_value.execute = fake_tests_result
            fake_pack_cls.return_value.execute = fake_pack_result
            (temp_dir / "fake.charm").write_text("x")
            result = await CharmValidateTool().execute(path=str(temp_dir))

        assert result.success
        assert result.caption is not None
        assert "charm_validate" in result.caption
        assert "PASSED" in result.caption


# ===========================================================================
# Shell (Phase 81.1)
# ===========================================================================


class TestRunCommandCaption:
    @pytest.mark.asyncio
    async def test_success_caption_with_snippet(self, temp_dir) -> None:
        from cantrip.agent.tools.run_command import RunCommandTool

        fake_runner = mock.MagicMock()
        fake_runner.run.return_value = mock.MagicMock(
            returncode=0,
            stdout="all good\n",
            stderr="",
        )
        tool = RunCommandTool(sandbox_runner=fake_runner)
        result = await tool.execute(command="make lint", cwd=str(temp_dir))

        assert result.success
        assert result.caption == "make (exit 0): all good"

    @pytest.mark.asyncio
    async def test_success_no_output_caption(self, temp_dir) -> None:
        from cantrip.agent.tools.run_command import RunCommandTool

        fake_runner = mock.MagicMock()
        fake_runner.run.return_value = mock.MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        tool = RunCommandTool(sandbox_runner=fake_runner)
        result = await tool.execute(command="make", cwd=str(temp_dir))

        assert result.success
        assert result.caption == "make (exit 0)"

    @pytest.mark.asyncio
    async def test_failure_caption_includes_error_snippet(self, temp_dir) -> None:
        from cantrip.agent.tools.run_command import RunCommandTool

        fake_runner = mock.MagicMock()
        fake_runner.run.return_value = mock.MagicMock(
            returncode=1,
            stdout="",
            stderr="error: thing went wrong",
        )
        tool = RunCommandTool(sandbox_runner=fake_runner)
        result = await tool.execute(command="make test", cwd=str(temp_dir))

        assert not result.success
        assert result.caption is not None
        assert result.caption.startswith("make (exit 1)")
        assert "error: thing went wrong" in result.caption

    @pytest.mark.asyncio
    async def test_caption_collapses_newlines_and_truncates(self, temp_dir) -> None:
        from cantrip.agent.tools.run_command import RunCommandTool

        fake_runner = mock.MagicMock()
        fake_runner.run.return_value = mock.MagicMock(
            returncode=0,
            stdout="line one\nline two with a lot of additional content here too\n",
            stderr="",
        )
        tool = RunCommandTool(sandbox_runner=fake_runner)
        result = await tool.execute(command="make all", cwd=str(temp_dir))

        assert result.success
        # Newlines collapsed to spaces; truncated with ellipsis past 40 chars.
        assert result.caption is not None
        assert "\n" not in result.caption
        assert "…" in result.caption


# ===========================================================================
# Juju (Phase 81.2)
# ===========================================================================


class TestJujuCaptions:
    @pytest.mark.asyncio
    async def test_status_caption_pluralisation(self) -> None:
        from cantrip.agent.tools import juju as juju_mod
        from cantrip.agent.tools.juju import JujuStatusTool

        fake_status = mock.MagicMock()
        fake_status.model.name = "dev-model"
        # Four apps; one blocked.
        active_app = mock.MagicMock()
        active_app.app_status.current = "active"
        active_app.units = {}
        blocked_app = mock.MagicMock()
        blocked_app.app_status.current = "blocked"
        blocked_app.units = {}
        fake_status.apps = {
            "redis": active_app,
            "traefik": active_app,
            "postgres": active_app,
            "mysql": blocked_app,
        }
        with (
            mock.patch.object(juju_mod, "_juju_available", return_value=True),
            mock.patch.object(juju_mod, "jubilant", create=True) as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.status = mock.MagicMock(return_value=fake_status)
            fake_jubilant.CLIError = Exception
            fake_jubilant.TaskError = Exception
            result = await JujuStatusTool().execute()

        assert result.success
        assert result.caption == "4 apps, 1 blocked"

    @pytest.mark.asyncio
    async def test_status_caption_singular_no_blocked(self) -> None:
        from cantrip.agent.tools import juju as juju_mod
        from cantrip.agent.tools.juju import JujuStatusTool

        fake_status = mock.MagicMock()
        fake_status.model.name = "dev-model"
        only_app = mock.MagicMock()
        only_app.app_status.current = "active"
        only_app.units = {}
        fake_status.apps = {"redis": only_app}
        with (
            mock.patch.object(juju_mod, "_juju_available", return_value=True),
            mock.patch.object(juju_mod, "jubilant", create=True) as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.status = mock.MagicMock(return_value=fake_status)
            fake_jubilant.CLIError = Exception
            fake_jubilant.TaskError = Exception
            result = await JujuStatusTool().execute()

        assert result.success
        assert result.caption == "1 app"

    @pytest.mark.asyncio
    async def test_deploy_caption_with_app_name_and_model(self) -> None:
        from cantrip.agent.tools import juju as juju_mod
        from cantrip.agent.tools.juju import JujuDeployTool

        with (
            mock.patch.object(juju_mod, "_juju_available", return_value=True),
            mock.patch.object(juju_mod, "jubilant", create=True) as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.deploy = mock.MagicMock(return_value=None)
            fake_jubilant.CLIError = Exception
            fake_jubilant.TaskError = Exception
            result = await JujuDeployTool().execute(
                charm="redis-k8s",
                app_name="my-redis",
                model="dev",
            )

        assert result.success
        assert result.caption == "Deployed my-redis to dev"

    @pytest.mark.asyncio
    async def test_deploy_caption_falls_back_to_charm_stem(self) -> None:
        from cantrip.agent.tools import juju as juju_mod
        from cantrip.agent.tools.juju import JujuDeployTool

        with (
            mock.patch.object(juju_mod, "_juju_available", return_value=True),
            mock.patch.object(juju_mod, "jubilant", create=True) as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.deploy = mock.MagicMock(return_value=None)
            fake_jubilant.CLIError = Exception
            fake_jubilant.TaskError = Exception
            result = await JujuDeployTool().execute(charm="postgresql-k8s")

        assert result.success
        assert result.caption == "Deployed postgresql-k8s"

    @pytest.mark.asyncio
    async def test_relate_caption(self) -> None:
        from cantrip.agent.tools import juju as juju_mod
        from cantrip.agent.tools.juju import JujuRelateTool

        with (
            mock.patch.object(juju_mod, "_juju_available", return_value=True),
            mock.patch.object(juju_mod, "jubilant", create=True) as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.integrate = mock.MagicMock(return_value=None)
            fake_jubilant.CLIError = Exception
            fake_jubilant.TaskError = Exception
            result = await JujuRelateTool().execute(app1="redis", app2="traefik")

        assert result.success
        assert result.caption == "Integrated redis ↔ traefik"

    @pytest.mark.asyncio
    async def test_config_set_single_value_caption(self) -> None:
        from cantrip.agent.tools import juju as juju_mod
        from cantrip.agent.tools.juju import JujuConfigTool

        with (
            mock.patch.object(juju_mod, "_juju_available", return_value=True),
            mock.patch.object(juju_mod, "jubilant", create=True) as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.config = mock.MagicMock(return_value=None)
            fake_jubilant.CLIError = Exception
            fake_jubilant.TaskError = Exception
            result = await JujuConfigTool().execute(
                app_name="redis",
                values={"debug": "true"},
            )

        assert result.success
        assert result.caption == "Set redis: debug=true"

    @pytest.mark.asyncio
    async def test_config_set_multiple_values_caption(self) -> None:
        from cantrip.agent.tools import juju as juju_mod
        from cantrip.agent.tools.juju import JujuConfigTool

        with (
            mock.patch.object(juju_mod, "_juju_available", return_value=True),
            mock.patch.object(juju_mod, "jubilant", create=True) as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.config = mock.MagicMock(return_value=None)
            fake_jubilant.CLIError = Exception
            fake_jubilant.TaskError = Exception
            result = await JujuConfigTool().execute(
                app_name="redis",
                values={"debug": "true", "replicas": "3"},
            )

        assert result.success
        assert result.caption == "Set redis: 2 values"

    @pytest.mark.asyncio
    async def test_config_get_caption(self) -> None:
        from cantrip.agent.tools import juju as juju_mod
        from cantrip.agent.tools.juju import JujuConfigTool

        with (
            mock.patch.object(juju_mod, "_juju_available", return_value=True),
            mock.patch.object(juju_mod, "jubilant", create=True) as fake_jubilant,
        ):
            fake_jubilant.Juju.return_value.config = mock.MagicMock(return_value={"debug": False})
            fake_jubilant.CLIError = Exception
            fake_jubilant.TaskError = Exception
            result = await JujuConfigTool().execute(app_name="redis")

        assert result.success
        assert result.caption == "Read redis config"


# ===========================================================================
# Acceptance / audit / testing (Phase 81.3)
# ===========================================================================


class TestAcceptanceCaptions:
    @pytest.mark.asyncio
    async def test_run_charm_tests_caption(self, temp_dir) -> None:
        from cantrip.agent.tools.testing import RunCharmTestsTool

        # Set up enough of a charm dir that the tool reaches the subprocess call.
        (temp_dir / "tox.ini").write_text("")
        (temp_dir / "tests" / "unit").mkdir(parents=True)

        with (
            mock.patch("cantrip.agent.tools.testing.shutil.which", return_value="/usr/bin/python"),
            mock.patch("cantrip.agent.tools.testing.subprocess.run") as mock_run,
        ):
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout="=== 12 passed, 1 failed in 0.5s ===\n",
                stderr="",
            )
            result = await RunCharmTestsTool().execute(path=str(temp_dir))

        # Tests "failed" — exit code 0 in this stub, but we read the summary.
        assert result.caption == "12 passed, 1 failed"

    @pytest.mark.asyncio
    async def test_run_charm_tests_no_summary_caption(self, temp_dir) -> None:
        from cantrip.agent.tools.testing import RunCharmTestsTool

        (temp_dir / "tox.ini").write_text("")
        (temp_dir / "tests" / "unit").mkdir(parents=True)

        with (
            mock.patch("cantrip.agent.tools.testing.shutil.which", return_value="/usr/bin/python"),
            mock.patch("cantrip.agent.tools.testing.subprocess.run") as mock_run,
        ):
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
            result = await RunCharmTestsTool().execute(path=str(temp_dir))

        assert result.caption == "tests ran (no summary)"

    @pytest.mark.asyncio
    async def test_charm_audit_caption_clean(self, temp_dir) -> None:
        from cantrip.agent.tools import audit as audit_mod
        from cantrip.agent.tools.audit import CharmAuditTool

        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")

        with mock.patch.object(audit_mod, "_charmlint_to_audit_report") as fake_report:
            fake_report.return_value = ("# Audit Report\n", {}, {"total_issues": 0})
            result = await CharmAuditTool().execute(path=str(temp_dir))

        assert result.success
        assert result.caption == "clean"

    @pytest.mark.asyncio
    async def test_charm_audit_caption_issues(self, temp_dir) -> None:
        from cantrip.agent.tools import audit as audit_mod
        from cantrip.agent.tools.audit import CharmAuditTool

        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")

        with mock.patch.object(audit_mod, "_charmlint_to_audit_report") as fake_report:
            fake_report.return_value = ("# Audit Report\n", {}, {"total_issues": 2})
            result = await CharmAuditTool().execute(path=str(temp_dir))

        assert result.success
        assert result.caption == "2 issues"

    @pytest.mark.asyncio
    async def test_charm_audit_caption_singular(self, temp_dir) -> None:
        from cantrip.agent.tools import audit as audit_mod
        from cantrip.agent.tools.audit import CharmAuditTool

        (temp_dir / "charmcraft.yaml").write_text("name: my-charm\n")

        with mock.patch.object(audit_mod, "_charmlint_to_audit_report") as fake_report:
            fake_report.return_value = ("# Audit Report\n", {}, {"total_issues": 1})
            result = await CharmAuditTool().execute(path=str(temp_dir))

        assert result.caption == "1 issue"

    @pytest.mark.asyncio
    async def test_acceptance_report_caption(self, temp_dir) -> None:
        from cantrip.agent.tools.acceptance import AcceptanceReportTool

        result = await AcceptanceReportTool().execute(
            app="redis",
            path=str(temp_dir),
            actions="## Actions\n",
            relations="## Relations\n",
            endpoints="## Endpoints\n",
        )
        assert result.success
        assert result.caption == "Wrote ACCEPTANCE.md (3 sections)"

    @pytest.mark.asyncio
    async def test_acceptance_report_caption_singular(self, temp_dir) -> None:
        from cantrip.agent.tools.acceptance import AcceptanceReportTool

        result = await AcceptanceReportTool().execute(
            app="redis",
            path=str(temp_dir),
            actions="## Actions\n",
        )
        assert result.success
        assert result.caption == "Wrote ACCEPTANCE.md (1 section)"


# ===========================================================================
# Future-proofing — every registered Tool must be classified
# ===========================================================================


# Tools that intentionally rely on the formulaic ``tool_name(arg=value)``
# fallback rather than populating ``ToolResult.caption`` directly.  Each
# entry is a deliberate decision: the formulaic shape ("benchmark(path=foo)")
# already conveys what the tool did, and a hand-written caption wouldn't add
# meaningful information beyond that.
#
# Adding to this list requires reviewer judgement — prefer populating a
# real caption when the tool's effect would be clearer with one
# (file count, status verdict, deployed name, etc.).  See ``base.py``
# :class:`ToolResult` docstring and Phase 75 for the rationale.
_FALLBACK_OK: frozenset[str] = frozenset(
    {
        # Framework analysis — single ``path`` argument; output is a
        # long structured report.
        "analyse_framework",
        # Bundle deploy — wraps Juju with a single bundle path.
        "bundle_deploy",
        # Concierge environment prep — long status walls, not one-line
        # achievements.
        "concierge_prepare",
        "concierge_status",
        # Terraform tools — single-path scaffolding / validation.
        "generate_terraform",
        "validate_terraform",
        # Juju write-side actions and read-only probes whose value is
        # the data (or where a count would lose specificity).  Captioned
        # drive-bys for a future micro-pass.
        "juju_add_model",
        "juju_consume",
        "juju_debug_log",
        "juju_destroy_model",
        "juju_dispatch",
        "juju_get_app_config",
        "juju_list_offers",
        "juju_list_secrets",
        "juju_offer",
        "juju_read_relation_data",
        "juju_refresh",
        "juju_remove_application",
        "juju_run_action",
        "juju_show_secret",
        "juju_show_unit",
        "juju_ssh",
        "juju_stream_logs",
        "juju_trust",
        "juju_wait",
        # Inference and registry probes — the value is in the listing.
        "list_inference_snaps",
        "registry_image_info",
        "registry_search",
        "rockcraft_init",
        "skopeo_registry_push",
        # Observability — long query results.  ``loki_query(query=...)``
        # and ``tempo_query(trace_id=...)`` fallbacks are clearer than
        # any synthetic summary.
        "loki_query",
        "tempo_query",
        # PR review tools — wrap gh; argument shape is enough.
        "pr_review",
        "pr_review_reply",
        # Operational readiness — long Markdown report; no one-line summary.
        "operational_readiness",
        # Rodney / Showboat — accessibility / CSS audit tools, output is
        # the report.
        "rodney",
        "showboat",
        # Workspace info — listing tool; fallback ``workspace_info(path=...)``
        # is enough.
        "workspace_info",
    }
)


class TestCaptionCoverage:
    """Every registered Tool must populate caption or be on _FALLBACK_OK.

    Adding a new tool? Either:
      1. Set ``result.caption = "..."`` (or ``ToolResult(..., caption=...)``)
         on the success path.  Match the existing style: short, active verb,
         specific count/target where possible.
      2. Add the tool's ``name`` to ``_FALLBACK_OK`` above with a one-line
         comment explaining why the formulaic fallback is enough.

    The fallback (``tool_name(path=foo)``) is always a safe default — this
    test exists so the choice between rich caption and fallback is a
    visible review decision, not silent omission.
    """

    def test_every_registered_tool_classified(self) -> None:
        import inspect

        from cantrip.agent.tools import build_tools

        unclassified: list[str] = []
        for tool in build_tools():
            try:
                source = inspect.getsource(type(tool))
            except (OSError, TypeError):
                continue
            populates_caption = "caption" in source
            in_fallback = tool.name in _FALLBACK_OK
            if not populates_caption and not in_fallback:
                unclassified.append(tool.name)
        if unclassified:
            joined = ", ".join(sorted(unclassified))
            pytest.fail(
                "These tools neither populate ToolResult.caption nor appear in "
                f"_FALLBACK_OK: {joined}.  Either populate `result.caption = ...` "
                "on the success path or add the tool's name to _FALLBACK_OK with "
                "a one-line justification."
            )
