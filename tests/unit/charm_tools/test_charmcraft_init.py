"""Tests for CharmcraftInitTool — gitignore, ops-tracing, paas, pre-commit."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from cantrip.agent.tools.charm import (
    CharmcraftInitTool,
    _inject_ops_tracing_into_charm_py,
    _inject_pre_commit,
)


class TestCharmcraftInitGitignore:
    """Tests for CharmcraftInitTool .gitignore handling."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self):
        return CharmcraftInitTool()

    def _mock_charmcraft(self):
        """Return a mock that simulates a successful charmcraft init."""
        return mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="Initialised.", stderr=""),
        )

    @pytest.mark.asyncio
    async def test_gitignore_created_with_cantrip_and_source(self, tool, temp_dir):
        """A new .gitignore should contain both .cantrip and .source/ entries."""
        with self._mock_charmcraft():
            await tool.execute(name="test-charm", path=str(temp_dir))

        gitignore = temp_dir / "test-charm" / ".gitignore"
        content = gitignore.read_text()
        assert ".cantrip" in content
        assert ".source/" in content

    @pytest.mark.asyncio
    async def test_gitignore_appends_missing_entries(self, tool, temp_dir):
        """Existing .gitignore gets missing entries appended."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        gitignore = charm_dir / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n")

        with self._mock_charmcraft():
            await tool.execute(name="test-charm", path=str(temp_dir))

        content = gitignore.read_text()
        assert ".cantrip" in content
        assert ".source/" in content
        assert "*.pyc" in content

    @pytest.mark.asyncio
    async def test_gitignore_does_not_duplicate(self, tool, temp_dir):
        """Entries already present are not repeated."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        gitignore = charm_dir / ".gitignore"
        gitignore.write_text(".cantrip\n.source/\n")

        with self._mock_charmcraft():
            await tool.execute(name="test-charm", path=str(temp_dir))

        content = gitignore.read_text()
        assert content.count(".cantrip") == 1
        assert content.count(".source/") == 1

    @pytest.mark.asyncio
    async def test_force_passed_when_target_has_unrelated_files(self, tool, temp_dir):
        """--force is passed when the target dir has files but no charmcraft.yaml.

        Cantrip's own state (the workspace DB, ``.source/``, scratch notes)
        often lives alongside where the agent wants to scaffold a charm.
        ``charmcraft init`` aborts on a non-empty dir unless ``--force`` is
        given, so we add it whenever there is no existing ``charmcraft.yaml``.
        """
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        (charm_dir / "cantrip.db").write_text("")  # simulate Cantrip state.

        with mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="Initialised.", stderr=""),
        ) as mock_run:
            result = await tool.execute(name="test-charm", path=str(charm_dir))

        assert result.success
        cmd = mock_run.call_args.args[0]
        assert "--force" in cmd

    @pytest.mark.asyncio
    async def test_force_not_passed_when_target_is_empty(self, tool, temp_dir):
        """--force is not added when the target directory is empty.

        Keeps the command minimal in the common case so its behaviour matches
        ``charmcraft init`` invoked by hand.
        """
        with mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="Initialised.", stderr=""),
        ) as mock_run:
            result = await tool.execute(name="test-charm", path=str(temp_dir))

        assert result.success
        cmd = mock_run.call_args.args[0]
        assert "--force" not in cmd

    @pytest.mark.asyncio
    async def test_refuses_when_charmcraft_yaml_already_exists(self, tool, temp_dir):
        """Refuses to re-initialise a directory that already contains a charm.

        ``--force`` would otherwise overwrite the user's hand-edited charm
        files; the existing ``charmcraft.yaml`` is the canonical signal that
        a real charm lives here.
        """
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        (charm_dir / "charmcraft.yaml").write_text("name: test-charm\n")

        with mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
        ) as mock_run:
            result = await tool.execute(name="test-charm", path=str(charm_dir))

        assert not result.success
        assert "already exists" in result.error
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_path_already_named_after_charm_is_not_nested(self, tool, temp_dir):
        """When path already ends with name, scaffold in-place — no name/name nesting.

        Regression: sprint mode pre-sets state.charm_path to ``workspace/charm_name``,
        so the agent calls ``charmcraft_init(path=charm_path, name=charm_name)`` and
        we should not create another ``charm_name`` subdirectory below it.
        """
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)

        with self._mock_charmcraft():
            result = await tool.execute(name="test-charm", path=str(charm_dir))

        assert result.success
        assert result.data["path"] == str(charm_dir)
        assert not (charm_dir / "test-charm").exists()
        assert (charm_dir / ".gitignore").exists()


class TestCharmcraftInitOpsTracing:
    """Tests for ops-tracing injection in CharmcraftInitTool."""

    _CHARMCRAFT_YAML = """\
name: test-charm
type: charm
bases:
  - build-on:
      - name: ubuntu
        channel: "22.04"
    run-on:
      - name: ubuntu
        channel: "22.04"
"""

    _CHARM_PY = """\
#!/usr/bin/env python3
import ops


class TestCharmCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, event: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":
    ops.main(TestCharmCharm)
"""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self):
        return CharmcraftInitTool()

    def _mock_charmcraft(self, setup=None):
        """Mock subprocess.run as a successful charmcraft init.

        ``setup`` is invoked when the tool calls subprocess.run, i.e. *after*
        the existing-charm guard has been checked — exactly like real
        ``charmcraft init`` only writes its files when it actually runs.
        """

        def side_effect(*_args, **_kwargs):
            if setup is not None:
                setup()
            return mock.Mock(returncode=0, stdout="Initialised.", stderr="")

        return mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=side_effect,
        )

    def _scaffold_standard(self, charm_dir: Path) -> None:
        """Write files that charmcraft init would generate for a standard profile."""
        charm_dir.mkdir(parents=True, exist_ok=True)
        (charm_dir / "charmcraft.yaml").write_text(self._CHARMCRAFT_YAML)
        (charm_dir / "requirements.txt").write_text("ops >= 2.0\n")
        src = charm_dir / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "charm.py").write_text(self._CHARM_PY)

    @pytest.mark.asyncio
    async def test_tracing_injected_standard_charm(self, tool, temp_dir):
        """Standard profile gets full ops-tracing injection."""
        charm_dir = temp_dir / "test-charm"

        with self._mock_charmcraft(setup=lambda: self._scaffold_standard(charm_dir)):
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="kubernetes"
            )

        assert result.success
        assert result.data["tracing_injected"] is True

        # requirements.txt should contain ops-tracing.
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "ops-tracing" in reqs

        # charmcraft.yaml should have the tracing relation.
        charmcraft = (charm_dir / "charmcraft.yaml").read_text()
        assert "tracing" in charmcraft
        assert "interface: tracing" in charmcraft

        # src/charm.py should have the import and setup call.
        charm_py = (charm_dir / "src" / "charm.py").read_text()
        assert "import ops_tracing" in charm_py
        assert "ops_tracing.setup(self)" in charm_py

    @pytest.mark.asyncio
    async def test_tracing_charmcraft_yaml_only_for_paas(self, tool, temp_dir):
        """PaaS profile only modifies charmcraft.yaml, not requirements.txt or src/charm.py."""
        charm_dir = temp_dir / "test-charm"

        def setup() -> None:
            charm_dir.mkdir(parents=True, exist_ok=True)
            (charm_dir / "charmcraft.yaml").write_text(self._CHARMCRAFT_YAML)
            (charm_dir / "requirements.txt").write_text("ops >= 2.0\n")

        with self._mock_charmcraft(setup=setup):
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success

        # charmcraft.yaml should have tracing.
        charmcraft = (charm_dir / "charmcraft.yaml").read_text()
        assert "interface: tracing" in charmcraft

        # requirements.txt should be untouched.
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "ops-tracing" not in reqs

    @pytest.mark.asyncio
    async def test_tracing_no_duplicate(self, tool, temp_dir):
        """Files that already contain tracing are not modified again."""
        charm_dir = temp_dir / "test-charm"

        def setup() -> None:
            charm_dir.mkdir(parents=True, exist_ok=True)
            charmcraft_with_tracing = self._CHARMCRAFT_YAML + (
                "\nrequires:\n  tracing:\n    interface: tracing\n    limit: 1\n"
            )
            (charm_dir / "charmcraft.yaml").write_text(charmcraft_with_tracing)
            (charm_dir / "requirements.txt").write_text("ops >= 2.0\nops-tracing\n")
            src = charm_dir / "src"
            src.mkdir(parents=True, exist_ok=True)
            charm_py_with_tracing = self._CHARM_PY.replace(
                "import ops\n", "import ops\nimport ops_tracing\n"
            ).replace(
                "super().__init__(framework)",
                "super().__init__(framework)\n        ops_tracing.setup(self)",
            )
            (src / "charm.py").write_text(charm_py_with_tracing)

        with self._mock_charmcraft(setup=setup):
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="kubernetes"
            )

        assert result.success

        # No duplicates in any file.
        reqs = (charm_dir / "requirements.txt").read_text()
        assert reqs.count("ops-tracing") == 1

        charmcraft = (charm_dir / "charmcraft.yaml").read_text()
        assert charmcraft.count("interface: tracing") == 1

        charm_py = (charm_dir / "src" / "charm.py").read_text()
        assert charm_py.count("import ops_tracing") == 1
        assert charm_py.count("ops_tracing.setup") == 1

    @pytest.mark.asyncio
    async def test_tracing_missing_files_still_succeeds(self, tool, temp_dir):
        """Tool succeeds even when expected files are absent."""
        charm_dir = temp_dir / "test-charm"
        charm_dir.mkdir(parents=True)
        # No files pre-created — simulates charmcraft init producing nothing.

        with self._mock_charmcraft():
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="kubernetes"
            )

        assert result.success
        assert "skipped" in result.output.lower() or "not found" in result.output.lower()


class TestCharmcraftInitPaasRequirements:
    """Tests for the PaaS requirements.txt re-assertion.

    The agent has been observed overwriting a freshly-scaffolded charm's
    requirements.txt with the app's (e.g. ``cp app.py requirements.txt
    flask-demo/``).  That wipes ``paas-charm`` and the deployed charm
    then dies at install with ``ModuleNotFoundError: No module named
    'paas_charm'``.  ``_ensure_paas_requirements`` guarantees the lines
    are there again.
    """

    _PAAS_CHARMCRAFT_YAML = """\
name: test-charm
type: charm
base: ubuntu@24.04
platforms:
  amd64:
extensions:
  - flask-framework
"""

    _NON_PAAS_CHARMCRAFT_YAML = """\
name: test-charm
type: charm
base: ubuntu@24.04
platforms:
  amd64:
"""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def tool(self):
        return CharmcraftInitTool()

    def _mock_charmcraft(self, setup=None):
        """Mock subprocess.run; ``setup`` runs as a side_effect of the call."""

        def side_effect(*_args, **_kwargs):
            if setup is not None:
                setup()
            return mock.Mock(returncode=0, stdout="Initialised.", stderr="")

        return mock.patch(
            "cantrip.agent.tools.charm.subprocess.run",
            side_effect=side_effect,
        )

    @pytest.mark.asyncio
    async def test_app_requirements_overwrite_is_repaired(self, tool, temp_dir):
        """Simulate the observed bug: requirements.txt has only the app's deps."""
        charm_dir = temp_dir / "test-charm"

        def setup() -> None:
            charm_dir.mkdir(parents=True, exist_ok=True)
            (charm_dir / "charmcraft.yaml").write_text(self._PAAS_CHARMCRAFT_YAML)
            (charm_dir / "requirements.txt").write_text("flask>=3.0\n")

        with self._mock_charmcraft(setup=setup):
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "paas-charm" in reqs, f"paas-charm missing from reqs: {reqs!r}"
        assert "ops" in reqs, f"ops missing from reqs: {reqs!r}"
        # The application's dep must survive the repair.
        assert "flask>=3.0" in reqs

    @pytest.mark.asyncio
    async def test_already_present_paas_deps_are_not_duplicated(self, tool, temp_dir):
        """A well-formed PaaS requirements.txt is left alone."""
        charm_dir = temp_dir / "test-charm"

        def setup() -> None:
            charm_dir.mkdir(parents=True, exist_ok=True)
            (charm_dir / "charmcraft.yaml").write_text(self._PAAS_CHARMCRAFT_YAML)
            (charm_dir / "requirements.txt").write_text(
                "ops ~= 2.17\npaas-charm>=1.0,<2\nflask>=3.0\n"
            )

        with self._mock_charmcraft(setup=setup):
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        assert reqs.count("paas-charm") == 1
        # One ``ops`` line (excluding ``ops-tracing`` which PaaS skips anyway).
        ops_lines = [ln for ln in reqs.splitlines() if ln.strip().startswith("ops")]
        assert len(ops_lines) == 1

    @pytest.mark.asyncio
    async def test_missing_requirements_file_is_created(self, tool, temp_dir):
        """When the agent deletes requirements.txt entirely the file is rebuilt."""
        charm_dir = temp_dir / "test-charm"

        def setup() -> None:
            charm_dir.mkdir(parents=True, exist_ok=True)
            (charm_dir / "charmcraft.yaml").write_text(self._PAAS_CHARMCRAFT_YAML)
            # Deliberately no requirements.txt.

        with self._mock_charmcraft(setup=setup):
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success
        reqs_path = charm_dir / "requirements.txt"
        assert reqs_path.exists()
        reqs = reqs_path.read_text()
        assert "paas-charm" in reqs
        assert "ops" in reqs

    @pytest.mark.asyncio
    async def test_non_paas_charm_untouched(self, tool, temp_dir):
        """A non-PaaS charm's requirements.txt must NOT gain paas-charm."""
        charm_dir = temp_dir / "test-charm"

        def setup() -> None:
            charm_dir.mkdir(parents=True, exist_ok=True)
            (charm_dir / "charmcraft.yaml").write_text(self._NON_PAAS_CHARMCRAFT_YAML)
            (charm_dir / "requirements.txt").write_text("ops >= 2.0\n")

        with self._mock_charmcraft(setup=setup):
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="kubernetes"
            )

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        assert "paas-charm" not in reqs

    @pytest.mark.asyncio
    async def test_ops_tracing_is_not_treated_as_ops(self, tool, temp_dir):
        """``ops-tracing`` alone must not satisfy the ``ops`` requirement.

        Because the regex that looks for ``ops`` had to avoid false
        positives on ``ops-tracing``, a requirements.txt containing only
        ``ops-tracing`` should still get ``ops`` added.  Otherwise the
        charm's ``import ops`` fails even though the deps look complete.
        """
        charm_dir = temp_dir / "test-charm"

        def setup() -> None:
            charm_dir.mkdir(parents=True, exist_ok=True)
            (charm_dir / "charmcraft.yaml").write_text(self._PAAS_CHARMCRAFT_YAML)
            (charm_dir / "requirements.txt").write_text("ops-tracing\npaas-charm>=1.0,<2\n")

        with self._mock_charmcraft(setup=setup):
            result = await tool.execute(
                name="test-charm", path=str(temp_dir), profile="flask-framework"
            )

        assert result.success
        reqs = (charm_dir / "requirements.txt").read_text()
        # One standalone ops line, plus the original ops-tracing line.
        bare_ops_lines = [
            ln
            for ln in reqs.splitlines()
            if ln.strip().startswith("ops")
            and not ln.strip().startswith("ops-")
            and not ln.strip().startswith("ops_")
        ]
        assert len(bare_ops_lines) == 1
        assert "ops-tracing" in reqs


class TestCharmcraftInitPreCommit:
    """Tests for pre-commit injection in CharmcraftInitTool."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    def test_pre_commit_config_written(self, temp_dir):
        """Writes .pre-commit-config.yaml with format, lint, and unit hooks."""
        (temp_dir / "tox.ini").write_text("[testenv:format]\n")

        actions = _inject_pre_commit(temp_dir)

        config = temp_dir / ".pre-commit-config.yaml"
        assert config.exists()
        content = config.read_text()
        assert "id: format" in content
        assert "id: lint" in content
        assert "id: unit" in content
        assert "tox -e format" in content
        assert "tox -e lint" in content
        assert "tox -e unit" in content
        assert any("Created" in a for a in actions)

    def test_pre_commit_skipped_when_exists(self, temp_dir):
        """Skips writing when .pre-commit-config.yaml already exists."""
        (temp_dir / "tox.ini").write_text("[testenv:format]\n")
        existing = temp_dir / ".pre-commit-config.yaml"
        existing.write_text("repos: []\n")

        actions = _inject_pre_commit(temp_dir)

        # File should be unchanged.
        assert existing.read_text() == "repos: []\n"
        assert any("already exists" in a for a in actions)

    def test_pre_commit_skipped_without_tox_ini(self, temp_dir):
        """Skips pre-commit setup when tox.ini is absent."""
        actions = _inject_pre_commit(temp_dir)

        assert not (temp_dir / ".pre-commit-config.yaml").exists()
        assert any("tox.ini not found" in a for a in actions)

    def test_pre_commit_install_runs(self, temp_dir):
        """Runs pre-commit install when the binary is on PATH."""
        (temp_dir / "tox.ini").write_text("[testenv:format]\n")

        with (
            mock.patch(
                "cantrip.agent.tools.charm.shutil.which", return_value="/usr/bin/pre-commit"
            ),
            mock.patch("cantrip.agent.tools.charm.subprocess.run") as mock_run,
        ):
            actions = _inject_pre_commit(temp_dir)

        mock_run.assert_called_once_with(
            ["pre-commit", "install"],
            cwd=temp_dir,
            capture_output=True,
            timeout=30,
        )
        assert any("Ran pre-commit install" in a for a in actions)

    def test_pre_commit_install_skipped(self, temp_dir):
        """Gracefully skips when pre-commit is not on PATH."""
        (temp_dir / "tox.ini").write_text("[testenv:format]\n")

        with mock.patch("cantrip.agent.tools.charm.shutil.which", return_value=None):
            actions = _inject_pre_commit(temp_dir)

        assert (temp_dir / ".pre-commit-config.yaml").exists()
        assert any("pre-commit not found" in a for a in actions)


class TestInjectOpsTracingIntoCharmPy:
    """Tests for the regex-anchored ``_inject_ops_tracing_into_charm_py`` helper.

    The previous ``str.replace`` implementation silently produced broken
    output when the charm file diverged from the scaffold (for example,
    when ``__init__`` used a different argument name), or partially
    patched the file (import without setup).  These tests pin the
    regex-based helper against those failure modes.
    """

    _SIMPLE_CHARM = """\
#!/usr/bin/env python3
import ops


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
"""

    def test_standard_scaffold(self):
        """Scaffold matching the usual ``framework`` argument gets both lines."""
        patched = _inject_ops_tracing_into_charm_py(self._SIMPLE_CHARM)
        assert patched is not None
        assert "import ops\nimport ops_tracing\n" in patched
        assert "super().__init__(framework)\n        ops_tracing.setup(self)\n" in patched

    def test_alternate_init_argument(self):
        """Charms using ``*args`` or a different arg name still get patched."""
        source = self._SIMPLE_CHARM.replace(
            "super().__init__(framework)",
            "super().__init__(*args, **kwargs)",
        )
        patched = _inject_ops_tracing_into_charm_py(source)
        assert patched is not None
        # Setup line uses the same 8-space indent as the matched init line.
        assert "super().__init__(*args, **kwargs)\n        ops_tracing.setup(self)" in patched

    def test_empty_super_init(self):
        """``super().__init__()`` (no args) is still a valid anchor."""
        source = self._SIMPLE_CHARM.replace(
            "super().__init__(framework)",
            "super().__init__()",
        )
        patched = _inject_ops_tracing_into_charm_py(source)
        assert patched is not None
        assert "super().__init__()\n        ops_tracing.setup(self)" in patched

    def test_import_ops_charm_alone_is_not_enough(self):
        """``import ops.charm`` alone — without a bare ``import ops`` — fails safely."""
        source = self._SIMPLE_CHARM.replace("import ops", "import ops.charm")
        assert _inject_ops_tracing_into_charm_py(source) is None

    def test_no_super_init_fails_safely(self):
        """Without a ``super().__init__`` anchor, the helper refuses to patch.

        Previously the helper would silently insert the import line and
        leave the setup call missing — a NameError at charm start.  The
        regex-anchored version returns ``None`` so the caller reports a
        skip instead.
        """
        source = (
            "#!/usr/bin/env python3\nimport ops\n\n\nclass NakedCharm(ops.CharmBase):\n    pass\n"
        )
        assert _inject_ops_tracing_into_charm_py(source) is None
        assert "import ops_tracing" not in source

    def test_custom_indent_is_preserved(self):
        """A ``super().__init__`` indented with four spaces keeps four spaces."""
        source = (
            "import ops\n"
            "\n"
            "class Tiny(ops.CharmBase):\n"
            "  def __init__(self, framework):\n"
            "    super().__init__(framework)\n"
        )
        patched = _inject_ops_tracing_into_charm_py(source)
        assert patched is not None
        assert "    super().__init__(framework)\n    ops_tracing.setup(self)\n" in patched

    def test_crlf_line_endings(self):
        """CRLF-line-ending files still match the anchors."""
        source = self._SIMPLE_CHARM.replace("\n", "\r\n")
        patched = _inject_ops_tracing_into_charm_py(source)
        assert patched is not None
        # The injection output uses LF for the new lines it inserts — that
        # is consistent with how Python writes files on Linux runners.
        assert "import ops_tracing" in patched
        assert "ops_tracing.setup(self)" in patched

    def test_only_first_occurrence_patched(self):
        """Multiple ``super().__init__`` calls: only the first is patched."""
        source = (
            "import ops\n"
            "\n"
            "class A(ops.CharmBase):\n"
            "    def __init__(self, framework):\n"
            "        super().__init__(framework)\n"
            "\n"
            "class B(ops.CharmBase):\n"
            "    def __init__(self, framework):\n"
            "        super().__init__(framework)\n"
        )
        patched = _inject_ops_tracing_into_charm_py(source)
        assert patched is not None
        assert patched.count("ops_tracing.setup(self)") == 1
        assert patched.count("import ops_tracing") == 1
