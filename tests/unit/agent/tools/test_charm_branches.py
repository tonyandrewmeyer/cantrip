"""Branch-coverage backfill for ``cantrip.agent.tools.charm``.

The base suite covers happy-path tool invocations across separate
files (``test_charmcraft_init.py``, ``test_charmcraft_pack.py``,
``test_charm_validate.py``, ``test_terraform_tool.py``,
``test_framework_detection.py``).  This file fills the failure /
fallback / shell-out branches that thin out the per-file coverage:

- ``CharmcraftInitTool`` FileNotFoundError / TimeoutExpired / OSError
  exception paths
- ``CharmcraftPackTool`` destructive_mode + sudo retry, exception
  exits (FileNotFoundError, TimeoutExpired, generic OSError)
- ``CharmValidateTool`` coverage-pct branches (PASSED vs LOW)
- ``QuickPackTool`` ``_find_rust_binary``, ``_execute_rust`` (success /
  binary-vanishes / timeout / non-zero), ``_execute_python`` (success /
  FileNotFoundError / generic exception / CalledProcessError)
- ``CharmcraftFetchLibsTool`` end-to-end (success / non-zero rc /
  exception paths)
- ``AnalyseFrameworkTool`` "no framework" suggested-substrate hints
  and the broad-exception path
- ``GenerateTerraformTool`` yaml-parse-error path
- ``ValidateTerraformTool`` fmt-OK / init-failed / validate-failed
  matrix
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cantrip.agent.tools import charm as charm_module
from cantrip.agent.tools.charm import (
    AnalyseFrameworkTool,
    CharmcraftFetchLibsTool,
    CharmcraftInitTool,
    CharmcraftPackTool,
    CharmValidateTool,
    GenerateTerraformTool,
    QuickPackTool,
    ValidateTerraformTool,
)


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# CharmcraftInitTool exception paths
# ---------------------------------------------------------------------------


class TestCharmcraftInitExceptions:
    """``CharmcraftInitTool.execute`` exception arms."""

    @pytest.mark.asyncio
    async def test_file_not_found_when_charmcraft_missing(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            result = await CharmcraftInitTool().execute(name="t", path=str(tmp_path))
        assert result.success is False
        assert "charmcraft not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_timeout_during_init(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="charmcraft", timeout=1),
        ):
            result = await CharmcraftInitTool().execute(name="t", path=str(tmp_path))
        assert result.success is False
        assert "timed out" in (result.error or "")

    @pytest.mark.asyncio
    async def test_oserror_is_translated(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            result = await CharmcraftInitTool().execute(name="t", path=str(tmp_path))
        assert result.success is False
        assert "eperm" in (result.error or "")

    @pytest.mark.asyncio
    async def test_non_zero_rc_returns_failure(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=1, stdout="", stderr="bad profile"),
        ):
            result = await CharmcraftInitTool().execute(name="t", path=str(tmp_path))
        assert result.success is False
        assert "bad profile" in (result.error or "")


# ---------------------------------------------------------------------------
# CharmcraftPackTool — destructive + sudo retry, exceptions
# ---------------------------------------------------------------------------


class TestCharmcraftPackBranches:
    """``CharmcraftPackTool`` destructive-mode and exception branches."""

    @pytest.mark.asyncio
    async def test_destructive_mode_appended(self, tmp_path: pathlib.Path) -> None:
        captured: list[list[str]] = []

        def _mock_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return _proc(returncode=0)

        with patch("cantrip.agent.tools.charm.subprocess.run", side_effect=_mock_run):
            await CharmcraftPackTool().execute(path=str(tmp_path), destructive_mode=True)
        assert any("--destructive-mode" in c for c in captured)

    @pytest.mark.asyncio
    async def test_destructive_mode_retries_with_sudo_on_permission_error(
        self, tmp_path: pathlib.Path
    ) -> None:
        # Build a fake .charm so the success branch can find it.
        charm_file = tmp_path / "test_amd64.charm"

        call_count = {"n": 0}

        def _mock_run(_cmd: list[str], **_kwargs: Any) -> MagicMock:
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First attempt fails with a build-packages error.
                return _proc(returncode=1, stderr="build packages: permission denied")
            # Second (sudo) attempt succeeds — produce a stub .charm file.
            charm_file.write_bytes(b"")
            return _proc(returncode=0, stdout="ok")

        with (
            patch("cantrip.agent.tools.charm.subprocess.run", side_effect=_mock_run),
            patch("cantrip.agent.tools.charm.os.chown"),
        ):
            result = await CharmcraftPackTool().execute(path=str(tmp_path), destructive_mode=True)
        assert result.success is True
        assert call_count["n"] == 2  # retry happened

    @pytest.mark.asyncio
    async def test_non_zero_rc_returns_failure(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=1, stderr="bad metadata"),
        ):
            result = await CharmcraftPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "bad metadata" in (result.error or "")

    @pytest.mark.asyncio
    async def test_no_charm_file_caption_fallback(self, tmp_path: pathlib.Path) -> None:
        # rc=0 but no .charm file lands in the directory — caption falls
        # back to the no-file string.
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=0, stdout="ok"),
        ):
            result = await CharmcraftPackTool().execute(path=str(tmp_path))
        assert result.success is True
        assert "no .charm file" in (result.caption or "")

    @pytest.mark.asyncio
    async def test_charmcraft_missing(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            result = await CharmcraftPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "charmcraft not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_pack_timeout(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="charmcraft", timeout=1),
        ):
            result = await CharmcraftPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "timed out" in (result.error or "")

    @pytest.mark.asyncio
    async def test_pack_oserror(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            result = await CharmcraftPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "eperm" in (result.error or "")


# ---------------------------------------------------------------------------
# Phase 110.1 — CharmcraftPackTool flips state.pack_succeeded on success
# ---------------------------------------------------------------------------


class TestCharmcraftPackConvergenceFlag:
    """``CharmcraftPackTool`` signals convergence on success only.

    Drives the Phase 110.1 planner gate that closes the
    ``design/LOCAL_MODELS.md`` §5.2.2 Mistral Nemo post-pack spiral.
    """

    @pytest.mark.asyncio
    async def test_success_flips_pack_succeeded(self, tmp_path: pathlib.Path) -> None:
        from cantrip.agent.state import AgentState

        state = AgentState()
        assert state.pack_succeeded is False
        # Drop a stub .charm so the success branch resolves it.
        (tmp_path / "test_amd64.charm").write_bytes(b"")
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=0, stdout="ok"),
        ):
            result = await CharmcraftPackTool(state=state).execute(path=str(tmp_path))
        assert result.success is True
        assert state.pack_succeeded is True

    @pytest.mark.asyncio
    async def test_failure_leaves_pack_succeeded_unset(self, tmp_path: pathlib.Path) -> None:
        from cantrip.agent.state import AgentState

        state = AgentState()
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=1, stderr="bad metadata"),
        ):
            result = await CharmcraftPackTool(state=state).execute(path=str(tmp_path))
        assert result.success is False
        assert state.pack_succeeded is False

    @pytest.mark.asyncio
    async def test_no_state_does_not_raise(self, tmp_path: pathlib.Path) -> None:
        # Legacy instantiation without state is still supported — the
        # success path just skips the flag flip rather than crashing.
        (tmp_path / "test_amd64.charm").write_bytes(b"")
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=0, stdout="ok"),
        ):
            result = await CharmcraftPackTool().execute(path=str(tmp_path))
        assert result.success is True


class TestQuickPackConvergenceFlag:
    """``QuickPackTool`` flips ``state.pack_succeeded`` on both backends."""

    @pytest.mark.asyncio
    async def test_rust_success_flips_pack_succeeded(self, tmp_path: pathlib.Path) -> None:
        from cantrip.agent.state import AgentState

        state = AgentState()
        (tmp_path / "test.charm").write_bytes(b"")
        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value="/bin/qp"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                return_value=_proc(returncode=0, stdout="ok"),
            ),
        ):
            result = await QuickPackTool(state=state).execute(path=str(tmp_path))
        assert result.success is True
        assert state.pack_succeeded is True

    @pytest.mark.asyncio
    async def test_python_success_flips_pack_succeeded(self, tmp_path: pathlib.Path) -> None:
        from cantrip.agent.state import AgentState

        state = AgentState()
        charm = tmp_path / "test.charm"
        charm.write_bytes(b"x" * 100)
        fake_pack = MagicMock()
        fake_pack.quick_pack.return_value = charm
        fake_module = MagicMock(pack=fake_pack)
        import sys

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value=None),
            patch.dict(sys.modules, {"quickpack": fake_module, "quickpack.pack": fake_pack}),
        ):
            result = await QuickPackTool(state=state).execute(path=str(tmp_path))
        assert result.success is True
        assert state.pack_succeeded is True

    @pytest.mark.asyncio
    async def test_rust_failure_leaves_pack_succeeded_unset(self, tmp_path: pathlib.Path) -> None:
        from cantrip.agent.state import AgentState

        state = AgentState()
        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value="/bin/qp"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                return_value=_proc(returncode=1, stderr="bad"),
            ),
        ):
            result = await QuickPackTool(state=state).execute(path=str(tmp_path))
        assert result.success is False
        assert state.pack_succeeded is False


# ---------------------------------------------------------------------------
# CharmValidateTool — coverage-pct branches
# ---------------------------------------------------------------------------


class TestCharmValidateCoverageBranches:
    """``CharmValidateTool`` coverage threshold branches."""

    @pytest.mark.asyncio
    async def test_coverage_above_threshold(self, tmp_path: pathlib.Path) -> None:
        # Provide a tests/unit dir so the unit-test step actually runs.
        (tmp_path / "tests" / "unit").mkdir(parents=True)

        run_mock = MagicMock()
        run_mock.success = True
        run_mock.data = {
            "summary": {"passed": 5, "failed": 0},
            "coverage_pct": 90,
        }

        pack_mock = MagicMock()
        pack_mock.success = True
        pack_mock.data = {"charm_file": "/x/foo.charm"}

        from unittest.mock import AsyncMock

        with (
            patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                new_callable=AsyncMock,
                return_value=run_mock,
            ),
            patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                new_callable=AsyncMock,
                return_value=pack_mock,
            ),
        ):
            result = await CharmValidateTool().execute(path=str(tmp_path))

        assert result.success is True
        assert "PASSED (90%)" in result.output

    @pytest.mark.asyncio
    async def test_coverage_below_threshold(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "tests" / "unit").mkdir(parents=True)

        run_mock = MagicMock()
        run_mock.success = True
        run_mock.data = {
            "summary": {"passed": 5, "failed": 0},
            "coverage_pct": 50,
        }

        pack_mock = MagicMock()
        pack_mock.success = True
        pack_mock.data = {"charm_file": "/x/foo.charm"}

        from unittest.mock import AsyncMock

        with (
            patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                new_callable=AsyncMock,
                return_value=run_mock,
            ),
            patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                new_callable=AsyncMock,
                return_value=pack_mock,
            ),
        ):
            result = await CharmValidateTool().execute(path=str(tmp_path))

        assert "LOW (50%, target 80%)" in result.output


# ---------------------------------------------------------------------------
# QuickPackTool
# ---------------------------------------------------------------------------


class TestQuickPackFindRustBinary:
    """``_find_rust_binary`` PATH lookup and in-tree fallback."""

    def test_returns_path_binary(self) -> None:
        with patch("cantrip.agent.tools.charm.shutil.which", return_value="/bin/quickpack-rs"):
            assert QuickPackTool._find_rust_binary() == "/bin/quickpack-rs"

    def test_returns_in_tree_binary_when_present(self, tmp_path: pathlib.Path) -> None:
        # Force ``shutil.which`` miss; let the in-tree path resolve to a
        # real file we create so ``is_file()`` returns True.
        fake_pkg = tmp_path / "pkg" / "cantrip"
        fake_pkg.mkdir(parents=True)
        (fake_pkg / "__init__.py").write_text("")
        target = tmp_path / "quickpack-rs" / "target" / "release" / "quickpack"
        target.parent.mkdir(parents=True)
        target.write_text("")

        fake_module = MagicMock()
        fake_module.__file__ = str(fake_pkg / "__init__.py")

        with (
            patch("cantrip.agent.tools.charm.shutil.which", return_value=None),
            patch.dict("sys.modules", {"cantrip": fake_module}),
        ):
            assert QuickPackTool._find_rust_binary() == str(target)

    def test_returns_none_when_neither_found(self) -> None:
        with (
            patch("cantrip.agent.tools.charm.shutil.which", return_value=None),
            patch.object(pathlib.Path, "is_file", return_value=False),
        ):
            assert QuickPackTool._find_rust_binary() is None


class TestQuickPackExecuteRust:
    """``_execute_rust`` shell branches."""

    @pytest.mark.asyncio
    async def test_rust_success(self, tmp_path: pathlib.Path) -> None:
        # Create a fake .charm in the output dir so the helper finds it.
        charm = tmp_path / "test.charm"
        charm.write_bytes(b"")

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value="/bin/qp"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                return_value=_proc(returncode=0, stdout="ok"),
            ),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert result.success is True
        assert result.data["backend"] == "rust"

    @pytest.mark.asyncio
    async def test_rust_with_explicit_output_dir(self, tmp_path: pathlib.Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "test.charm").write_bytes(b"")

        captured: list[list[str]] = []

        def _mock_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return _proc(returncode=0)

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value="/bin/qp"),
            patch("cantrip.agent.tools.charm.subprocess.run", side_effect=_mock_run),
        ):
            await QuickPackTool().execute(path=str(tmp_path), output_dir=str(out))
        assert any("--output-dir" in c for c in captured)

    @pytest.mark.asyncio
    async def test_rust_binary_disappears_falls_back_to_python(
        self, tmp_path: pathlib.Path
    ) -> None:
        fallback_result = MagicMock(success=True, output="py", data={"backend": "python"})
        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value="/bin/qp"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                side_effect=FileNotFoundError(),
            ),
            patch.object(
                QuickPackTool,
                "_execute_python",
                return_value=fallback_result,
            ) as fb,
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        fb.assert_called_once()
        assert result is fallback_result

    @pytest.mark.asyncio
    async def test_rust_timeout(self, tmp_path: pathlib.Path) -> None:
        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value="/bin/qp"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="qp", timeout=1),
            ),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "timed out" in (result.error or "")

    @pytest.mark.asyncio
    async def test_rust_non_zero_rc(self, tmp_path: pathlib.Path) -> None:
        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value="/bin/qp"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                return_value=_proc(returncode=2, stderr="boom"),
            ),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "boom" in (result.error or "")


class TestQuickPackExecutePython:
    """``_execute_python`` shell branches via the ``quickpack`` library."""

    @pytest.mark.asyncio
    async def test_python_success(self, tmp_path: pathlib.Path) -> None:
        charm = tmp_path / "test.charm"
        charm.write_bytes(b"x" * 100)

        fake_pack = MagicMock()
        fake_pack.quick_pack.return_value = charm
        fake_module = MagicMock(pack=fake_pack)

        import sys

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value=None),
            patch.dict(sys.modules, {"quickpack": fake_module, "quickpack.pack": fake_pack}),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert result.success is True
        assert result.data["backend"] == "python"

    @pytest.mark.asyncio
    async def test_python_size_oserror_fallback_caption(self, tmp_path: pathlib.Path) -> None:
        charm = tmp_path / "test.charm"

        # Stat raises OSError so the caption falls back to the no-size form.
        class _FakePath:
            def __init__(self, p: pathlib.Path) -> None:
                self._p = p
                self.name = p.name

            def stat(self) -> Any:  # pragma: no cover - exercise the except
                raise OSError("stat failed")

        fake_pack = MagicMock()
        fake_pack.quick_pack.return_value = _FakePath(charm)
        fake_module = MagicMock(pack=fake_pack)

        import sys

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value=None),
            patch.dict(sys.modules, {"quickpack": fake_module, "quickpack.pack": fake_pack}),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert result.success is True
        # Caption falls back to the form without size.
        assert "Packed" in (result.caption or "")
        assert "MB" not in (result.caption or "")

    @pytest.mark.asyncio
    async def test_python_filenotfound(self, tmp_path: pathlib.Path) -> None:
        fake_pack = MagicMock()
        fake_pack.quick_pack.side_effect = FileNotFoundError("no charm")
        fake_module = MagicMock(pack=fake_pack)

        import sys

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value=None),
            patch.dict(sys.modules, {"quickpack": fake_module, "quickpack.pack": fake_pack}),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "no charm" in (result.error or "")

    @pytest.mark.asyncio
    async def test_python_runtime_error(self, tmp_path: pathlib.Path) -> None:
        fake_pack = MagicMock()
        fake_pack.quick_pack.side_effect = RuntimeError("invalid metadata")
        fake_module = MagicMock(pack=fake_pack)

        import sys

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value=None),
            patch.dict(sys.modules, {"quickpack": fake_module, "quickpack.pack": fake_pack}),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "invalid metadata" in (result.error or "")

    @pytest.mark.asyncio
    async def test_python_called_process_error(self, tmp_path: pathlib.Path) -> None:
        exc = subprocess.CalledProcessError(
            returncode=1,
            cmd=["uv"],
            output="",
            stderr="boom",
        )
        fake_pack = MagicMock()
        fake_pack.quick_pack.side_effect = exc
        fake_module = MagicMock(pack=fake_pack)

        import sys

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value=None),
            patch.dict(sys.modules, {"quickpack": fake_module, "quickpack.pack": fake_pack}),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "boom" in (result.error or "")


# ---------------------------------------------------------------------------
# CharmcraftFetchLibsTool
# ---------------------------------------------------------------------------


class TestCharmcraftFetchLibs:
    """``CharmcraftFetchLibsTool`` end-to-end."""

    @pytest.mark.asyncio
    async def test_success_counts_fetched_libs(self, tmp_path: pathlib.Path) -> None:
        stdout = "Fetched library a.b\nFetched library c.d\n"
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=0, stdout=stdout),
        ):
            result = await CharmcraftFetchLibsTool().execute(path=str(tmp_path))
        assert result.success is True
        assert result.data["fetched_count"] == 2

    @pytest.mark.asyncio
    async def test_no_libs_caption_falls_back(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=0, stdout=""),
        ):
            result = await CharmcraftFetchLibsTool().execute(path=str(tmp_path))
        assert result.success is True
        assert result.caption == "Fetched libraries"

    @pytest.mark.asyncio
    async def test_non_zero_rc(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=_proc(returncode=1, stderr="auth required"),
        ):
            result = await CharmcraftFetchLibsTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "auth required" in (result.error or "")

    @pytest.mark.asyncio
    async def test_charmcraft_missing(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            result = await CharmcraftFetchLibsTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "charmcraft not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="charmcraft", timeout=1),
        ):
            result = await CharmcraftFetchLibsTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "timed out" in (result.error or "")

    @pytest.mark.asyncio
    async def test_oserror(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=OSError("eperm"),
        ):
            result = await CharmcraftFetchLibsTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "eperm" in (result.error or "")


# ---------------------------------------------------------------------------
# AnalyseFrameworkTool — substrate suggestions and exception path
# ---------------------------------------------------------------------------


class TestAnalyseFrameworkBranches:
    """``AnalyseFrameworkTool`` substrate-suggestion / exception branches."""

    @pytest.mark.asyncio
    async def test_no_recognised_framework_with_no_signals(self, tmp_path: pathlib.Path) -> None:
        # A bare directory with no manifests, entry points, or anything
        # else — output falls through to the "Could not detect" line.
        result = await AnalyseFrameworkTool().execute(path=str(tmp_path))
        assert result.success is True
        assert result.data["framework"] is None

    @pytest.mark.asyncio
    async def test_machine_substrate_suggested_for_systemd(self, tmp_path: pathlib.Path) -> None:
        # A systemd unit drives the ``"machine"`` substrate suggestion.
        unit_dir = tmp_path / "debian"
        unit_dir.mkdir()
        (tmp_path / "myapp.service").write_text(
            "[Unit]\nDescription=app\n[Service]\nExecStart=/bin/true\n"
        )
        result = await AnalyseFrameworkTool().execute(path=str(tmp_path))
        assert result.success is True
        assert result.data["workload_hints"]["has_systemd"] is True
        assert result.data["workload_hints"]["suggested_substrate"] == "machine"

    @pytest.mark.asyncio
    async def test_k8s_substrate_suggested_for_dockerfile(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        result = await AnalyseFrameworkTool().execute(path=str(tmp_path))
        assert result.success is True
        assert result.data["workload_hints"]["has_dockerfile"] is True
        assert result.data["workload_hints"]["suggested_substrate"] == "k8s"

    @pytest.mark.asyncio
    async def test_path_not_found(self, tmp_path: pathlib.Path) -> None:
        result = await AnalyseFrameworkTool().execute(path=str(tmp_path / "nope"))
        assert result.success is False
        assert "Path not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_broad_exception_returns_failure(self, tmp_path: pathlib.Path) -> None:
        with patch(
            "cantrip.agent.tools.charm.scan",
            side_effect=ValueError("scan died"),
        ):
            result = await AnalyseFrameworkTool().execute(path=str(tmp_path))
        assert result.success is False
        assert "scan died" in (result.error or "")


# ---------------------------------------------------------------------------
# GenerateTerraformTool — yaml-error path
# ---------------------------------------------------------------------------


class TestGenerateTerraformBranches:
    """Failure paths in ``GenerateTerraformTool``."""

    @pytest.mark.asyncio
    async def test_yaml_error_during_generate(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text("name: t\n")
        with patch(
            "cantrip.agent.tools.charm.terraform.generate_terraform_module",
            side_effect=KeyError("no requires"),
        ):
            result = await GenerateTerraformTool().execute(charm_path=str(tmp_path))
        assert result.success is False
        assert "Failed to parse charmcraft.yaml" in (result.error or "")


# ---------------------------------------------------------------------------
# ValidateTerraformTool — full execute matrix
# ---------------------------------------------------------------------------


class TestValidateTerraformBranches:
    """``ValidateTerraformTool`` executes ``fmt`` / ``init`` / ``validate``."""

    @pytest.mark.asyncio
    async def test_directory_not_found(self) -> None:
        with patch("cantrip.agent.tools.charm.shutil.which", return_value="/bin/terraform"):
            result = await ValidateTerraformTool().execute(terraform_path="/nope/exists")
        assert result.success is False
        assert "Directory not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_init_failure_short_circuits(self, tmp_path: pathlib.Path) -> None:
        sequence = [
            _proc(returncode=0),  # fmt
            _proc(returncode=1, stderr="provider missing"),  # init
        ]
        with (
            patch("cantrip.agent.tools.charm.shutil.which", return_value="/bin/terraform"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                side_effect=sequence,
            ),
        ):
            result = await ValidateTerraformTool().execute(terraform_path=str(tmp_path))
        assert result.success is False
        assert "provider missing" in (result.error or "")

    @pytest.mark.asyncio
    async def test_all_steps_pass(self, tmp_path: pathlib.Path) -> None:
        sequence = [
            _proc(returncode=0),  # fmt
            _proc(returncode=0),  # init
            _proc(returncode=0),  # validate
        ]
        with (
            patch("cantrip.agent.tools.charm.shutil.which", return_value="/bin/terraform"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                side_effect=sequence,
            ),
        ):
            result = await ValidateTerraformTool().execute(terraform_path=str(tmp_path))
        assert result.success is True
        assert "fmt: PASSED" in result.output
        assert "validate: PASSED" in result.output
        assert result.caption == "fmt + validate: PASSED"

    @pytest.mark.asyncio
    async def test_fmt_fail_validate_pass(self, tmp_path: pathlib.Path) -> None:
        sequence = [
            _proc(returncode=1, stdout="--- changed.tf"),  # fmt
            _proc(returncode=0),  # init
            _proc(returncode=0),  # validate
        ]
        with (
            patch("cantrip.agent.tools.charm.shutil.which", return_value="/bin/terraform"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                side_effect=sequence,
            ),
        ):
            result = await ValidateTerraformTool().execute(terraform_path=str(tmp_path))
        assert result.success is False
        assert "fmt: FAILED" in result.output
        assert "validate: PASSED" in result.output
        assert result.caption == "fmt FAILED, validate PASSED"

    @pytest.mark.asyncio
    async def test_fmt_pass_validate_fail(self, tmp_path: pathlib.Path) -> None:
        sequence = [
            _proc(returncode=0),  # fmt
            _proc(returncode=0),  # init
            _proc(returncode=1, stderr="invalid resource"),  # validate
        ]
        with (
            patch("cantrip.agent.tools.charm.shutil.which", return_value="/bin/terraform"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                side_effect=sequence,
            ),
        ):
            result = await ValidateTerraformTool().execute(terraform_path=str(tmp_path))
        assert result.success is False
        assert "validate: FAILED" in result.output
        assert "invalid resource" in result.output
        assert result.caption == "fmt PASSED, validate FAILED"

    @pytest.mark.asyncio
    async def test_fmt_and_validate_both_fail(self, tmp_path: pathlib.Path) -> None:
        sequence = [
            _proc(returncode=1, stdout="--- a.tf\n+++ b.tf"),  # fmt
            _proc(returncode=0),  # init
            _proc(returncode=1, stderr="bad"),  # validate
        ]
        with (
            patch("cantrip.agent.tools.charm.shutil.which", return_value="/bin/terraform"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                side_effect=sequence,
            ),
        ):
            result = await ValidateTerraformTool().execute(terraform_path=str(tmp_path))
        assert result.success is False
        assert result.caption == "fmt + validate: FAILED"


# ---------------------------------------------------------------------------
# Module-level helpers exercised by the existing suite are skipped here;
# this file only fills the runtime / shell branches that the per-tool
# files leave behind.
# ---------------------------------------------------------------------------


def test_module_imports_cleanly() -> None:
    """Sanity check — the module's public symbols are importable.

    Acts as a smoke test for the new branches above; ``charm_module``
    is referenced once so the tooling does not flag the import as
    unused.
    """
    assert hasattr(charm_module, "CharmcraftInitTool")


# ---------------------------------------------------------------------------
# Helper-level branches still missing
# ---------------------------------------------------------------------------


class TestCharmUsesPaasExtensionBranches:
    """``_charm_uses_paas_extension`` failure branches."""

    def test_yaml_error_returns_false(self, tmp_path: pathlib.Path) -> None:
        # Malformed YAML — yaml.safe_load raises YAMLError; the helper
        # treats this as "no PaaS extension" rather than crashing the run.
        (tmp_path / "charmcraft.yaml").write_text("name: t\nbroken: [unclosed\n")
        assert charm_module._charm_uses_paas_extension(tmp_path) is False

    def test_extensions_must_be_a_list(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text("name: t\nextensions: not-a-list\n")
        assert charm_module._charm_uses_paas_extension(tmp_path) is False


class TestInjectOpsTracingFallback:
    """``_inject_ops_tracing`` reports a skip when patterns do not match."""

    def test_unmatched_charm_py_records_skip(self, tmp_path: pathlib.Path) -> None:
        # ``src/charm.py`` lacks the ``import ops`` anchor so the
        # ``_inject_ops_tracing_into_charm_py`` helper returns ``None``
        # and the wrapping function records a skip rather than writing
        # back unchanged content.
        src = tmp_path / "src"
        src.mkdir()
        (src / "charm.py").write_text("import sys\n")
        # charmcraft.yaml is needed so the parent function reaches the
        # charm.py inspection branch.
        (tmp_path / "charmcraft.yaml").write_text("name: t\n")
        actions = charm_module._inject_ops_tracing(tmp_path, "kubernetes")
        assert any("did not match expected patterns" in a for a in actions)


class TestInjectPreCommitFailure:
    """``_inject_pre_commit`` swallows install errors."""

    def test_install_failure_recorded(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "tox.ini").write_text("[tox]\n")
        with (
            patch(
                "cantrip.agent.tools.charm.shutil.which",
                return_value="/usr/bin/pre-commit",
            ),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                side_effect=OSError("install failed"),
            ),
        ):
            actions = charm_module._inject_pre_commit(tmp_path)
        assert any("install failed" in a for a in actions)


class TestCharmcraftInitExperimentalEnv:
    """Experimental profiles add the env var to the subprocess call."""

    @pytest.mark.asyncio
    async def test_experimental_profile_sets_env_var(self, tmp_path: pathlib.Path) -> None:
        captured: dict[str, Any] = {}

        def _mock_run(*_args: Any, **kwargs: Any) -> MagicMock:
            captured["env"] = kwargs.get("env", {})
            return _proc(returncode=0)

        with patch("cantrip.agent.tools.charm.subprocess.run", side_effect=_mock_run):
            await CharmcraftInitTool().execute(
                name="t",
                path=str(tmp_path),
                profile="go-framework",
            )
        assert captured["env"].get("CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS") == "true"


class TestQuickPackNoCharmLocated:
    """Both backends fall back to a captionless 'Packed charm' result."""

    @pytest.mark.asyncio
    async def test_rust_no_charm_file_caption_fallback(self, tmp_path: pathlib.Path) -> None:
        # ``_execute_rust`` runs but produces no .charm in the output dir.
        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value="/bin/qp"),
            patch(
                "cantrip.agent.tools.charm.subprocess.run",
                return_value=_proc(returncode=0, stdout="ok"),
            ),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path))
        assert "no .charm located" in (result.caption or "")

    @pytest.mark.asyncio
    async def test_python_with_explicit_output_dir(self, tmp_path: pathlib.Path) -> None:
        # The ``output_dir`` kwarg flows through to ``quickpack.pack.quick_pack``.
        out = tmp_path / "out"
        out.mkdir()
        result_path = out / "test.charm"
        result_path.write_bytes(b"x")

        fake_pack = MagicMock()
        fake_pack.quick_pack.return_value = result_path
        fake_module = MagicMock(pack=fake_pack)

        import sys

        with (
            patch.object(QuickPackTool, "_find_rust_binary", return_value=None),
            patch.dict(sys.modules, {"quickpack": fake_module, "quickpack.pack": fake_pack}),
        ):
            result = await QuickPackTool().execute(path=str(tmp_path), output_dir=str(out))
        assert result.success is True
        # The kwargs the helper passed to ``quick_pack``.
        kwargs = fake_pack.quick_pack.call_args.kwargs
        assert kwargs == {"output_dir": str(out)}
