"""Tests for the chisel-eligibility rubric.

Covers the pure :func:`check_chisel_eligibility` helper and the
:class:`ChiselEligibilityCheckTool` wrapper for every supported framework.
Fixtures prove that chiselled output keeps expected runtime files /
entrypoints / libraries by checking that eligible repos leave no shell-
at-runtime or apt-at-runtime blockers.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from cantrip.agent.tools.chisel_eligibility import (
    CHISEL_ELIGIBLE_FRAMEWORKS,
    ChiselEligibilityReport,
    check_chisel_eligibility,
)
from cantrip.agent.tools.rockcraft import ChiselEligibilityCheckTool


@pytest.fixture
def temp_repo():
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


def _write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Framework gate
# ---------------------------------------------------------------------------


class TestFrameworkGate:
    def test_unknown_framework_is_not_eligible(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "rails")
        assert report.eligible is False
        assert any("not in the supported" in b for b in report.blockers)

    def test_all_supported_frameworks_pass_gate_on_clean_repo(self, temp_repo):
        for fw in CHISEL_ELIGIBLE_FRAMEWORKS:
            report = check_chisel_eligibility(temp_repo, fw)
            # A clean empty repo should have no shell / apt blockers.
            assert not any("Shell-at-runtime" in b for b in report.blockers), fw
            assert not any("apt/dpkg" in b for b in report.blockers), fw

    def test_spring_boot_advisory_present(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "spring-boot")
        assert any("JRE slice set" in a for a in report.advisories)


# ---------------------------------------------------------------------------
# Shell-at-runtime detection
# ---------------------------------------------------------------------------


class TestShellAtRuntime:
    def test_os_system_call_blocks(self, temp_repo):
        _write(temp_repo / "app.py", "import os\nos.system('ls')\n")
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is False
        assert any("Shell-at-runtime" in b for b in report.blockers)

    def test_subprocess_shell_true_blocks(self, temp_repo):
        _write(
            temp_repo / "app.py",
            "import subprocess\nsubprocess.run('ls', shell=True)\n",
        )
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is False
        assert any("Shell-at-runtime" in b for b in report.blockers)

    def test_subprocess_invoking_sh_blocks(self, temp_repo):
        _write(
            temp_repo / "app.py",
            'import subprocess\nsubprocess.run(["/bin/sh", "-c", "echo hi"])\n',
        )
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is False

    def test_subprocess_invoking_bash_blocks(self, temp_repo):
        _write(
            temp_repo / "app.py",
            'import subprocess\nsubprocess.Popen(["bash", "-c", "echo hi"])\n',
        )
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is False

    def test_go_exec_command_sh_blocks(self, temp_repo):
        _write(
            temp_repo / "main.go",
            'package main\nfunc main() { exec.Command("sh", "-c", "ls") }\n',
        )
        report = check_chisel_eligibility(temp_repo, "go")
        assert report.eligible is False

    def test_java_runtime_exec_sh_blocks(self, temp_repo):
        _write(
            temp_repo / "App.java",
            'public class App { Runtime.getRuntime().exec(new String[]{"bash", "-c", "ls"}); }\n',
        )
        report = check_chisel_eligibility(temp_repo, "spring-boot")
        assert report.eligible is False

    def test_non_shell_subprocess_does_not_block(self, temp_repo):
        # Calling a known binary (not sh/bash) should not trigger the blocker.
        _write(
            temp_repo / "app.py",
            'import subprocess\nsubprocess.run(["python", "-m", "pytest"])\n',
        )
        report = check_chisel_eligibility(temp_repo, "flask")
        assert not any("Shell-at-runtime" in b for b in report.blockers)

    def test_shell_in_vendor_is_ignored(self, temp_repo):
        # Patterns inside vendor/ should be skipped.
        _write(
            temp_repo / "vendor" / "lib" / "util.py",
            "import os\nos.system('ls')\n",
        )
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is True

    def test_shell_in_node_modules_is_ignored(self, temp_repo):
        _write(
            temp_repo / "node_modules" / "some-pkg" / "index.js",
            "const {exec} = require('child_process'); exec('sh -c ls');\n",
        )
        report = check_chisel_eligibility(temp_repo, "express")
        assert report.eligible is True


# ---------------------------------------------------------------------------
# apt-at-runtime detection
# ---------------------------------------------------------------------------


class TestAptAtRuntime:
    def test_apt_get_install_in_python_blocks(self, temp_repo):
        _write(temp_repo / "setup.py", "import os\nos.system('apt-get install -y curl')\n")
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is False
        assert any("apt/dpkg" in b for b in report.blockers)

    def test_apt_install_in_shell_script_blocks(self, temp_repo):
        _write(temp_repo / "bootstrap.sh", "#!/bin/sh\napt install -y git\n")
        report = check_chisel_eligibility(temp_repo, "django")
        assert report.eligible is False

    def test_dpkg_install_blocks(self, temp_repo):
        # dpkg -i in a shell script is the common form the regex targets.
        _write(temp_repo / "install.sh", "#!/bin/sh\ndpkg -i pkg.deb\n")
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is False
        assert any("apt/dpkg" in b for b in report.blockers)

    def test_apt_get_in_comment_does_not_block(self, temp_repo):
        # Comments referencing apt-get should not trigger the blocker.
        _write(
            temp_repo / "README.md",
            "# Install: apt-get install python3\n",
        )
        # .md is not in _SCANNABLE_SUFFIXES, so no match.
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is True


# ---------------------------------------------------------------------------
# Opaque vendor install scripts
# ---------------------------------------------------------------------------


class TestVendorInstallScripts:
    def test_curl_pipe_bash_in_npm_script_blocks(self, temp_repo):
        pkg = {
            "name": "myapp",
            "scripts": {
                "start": "node server.js",
                "postinstall": "curl https://example.com/setup.sh | bash",
            },
        }
        _write(temp_repo / "app" / "package.json", json.dumps(pkg))
        report = check_chisel_eligibility(temp_repo, "express")
        assert report.eligible is False
        assert any("Opaque vendor install script" in b for b in report.blockers)

    def test_wget_pipe_sh_in_npm_script_blocks(self, temp_repo):
        pkg = {
            "name": "myapp",
            "scripts": {"preinstall": "wget -O - https://example.com | sh"},
        }
        _write(temp_repo / "package.json", json.dumps(pkg))
        report = check_chisel_eligibility(temp_repo, "express")
        assert report.eligible is False

    def test_normal_npm_script_does_not_block(self, temp_repo):
        pkg = {
            "name": "myapp",
            "scripts": {"start": "node server.js", "test": "jest"},
        }
        _write(temp_repo / "app" / "package.json", json.dumps(pkg))
        report = check_chisel_eligibility(temp_repo, "express")
        assert not any("Opaque vendor" in b for b in report.blockers)


# ---------------------------------------------------------------------------
# Entrypoint script advisories
# ---------------------------------------------------------------------------


class TestEntrypointScriptAdvisories:
    def test_migrate_sh_with_shell_builtins_triggers_advisory(self, temp_repo):
        _write(
            temp_repo / "migrate.sh", "#!/bin/bash\nset -euxo pipefail\npython manage.py migrate\n"
        )
        report = check_chisel_eligibility(temp_repo, "django")
        assert any("migrate.sh" in a for a in report.advisories)

    def test_entrypoint_sh_with_source_triggers_advisory(self, temp_repo):
        _write(temp_repo / "entrypoint.sh", "#!/bin/sh\nsource /etc/profile\nexec python app.py\n")
        report = check_chisel_eligibility(temp_repo, "flask")
        assert any("entrypoint.sh" in a for a in report.advisories)

    def test_plain_sh_without_builtins_does_not_trigger(self, temp_repo):
        _write(temp_repo / "migrate.sh", "#!/bin/sh\npython manage.py migrate\n")
        report = check_chisel_eligibility(temp_repo, "django")
        assert not any("migrate.sh" in a for a in report.advisories)

    def test_no_entrypoint_script_means_no_advisory(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "flask")
        assert not any("migrate.sh" in a or "entrypoint.sh" in a for a in report.advisories)


# ---------------------------------------------------------------------------
# Rationale field
# ---------------------------------------------------------------------------


class TestRationaleField:
    def test_eligible_rationale_mentions_base_bare(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "flask")
        assert "base: bare" in report.rationale

    def test_eligible_rationale_mentions_escape_hatch(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "flask")
        assert "ubuntu@24.04" in report.rationale

    def test_ineligible_rationale_mentions_ubuntu_base(self, temp_repo):
        _write(temp_repo / "app.py", "import os\nos.system('ls')\n")
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is False
        assert "ubuntu@24.04" in report.rationale

    def test_framework_specific_intro_flask(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "flask")
        assert "Gunicorn" in report.rationale

    def test_framework_specific_intro_go(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "go")
        assert "Go" in report.rationale

    def test_framework_specific_intro_spring_boot(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "spring-boot")
        assert "JRE" in report.rationale


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


class TestChiselEligibilityReport:
    def test_frozen_dataclass(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "flask")
        with pytest.raises((AttributeError, TypeError)):
            report.eligible = False  # type: ignore[misc]

    def test_eligible_true_on_clean_repo(self, temp_repo):
        report = check_chisel_eligibility(temp_repo, "flask")
        assert isinstance(report, ChiselEligibilityReport)
        assert report.eligible is True
        assert report.blockers == []

    def test_eligible_false_when_blocked(self, temp_repo):
        _write(temp_repo / "app.py", "import os\nos.system('ls')\n")
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is False
        assert len(report.blockers) >= 1


# ---------------------------------------------------------------------------
# ChiselEligibilityCheckTool (async wrapper)
# ---------------------------------------------------------------------------


class TestChiselEligibilityCheckTool:
    @pytest.fixture
    def tool(self):
        return ChiselEligibilityCheckTool()

    @pytest.mark.asyncio
    async def test_eligible_result(self, tool, temp_repo):
        result = await tool.execute(path=str(temp_repo), framework="flask")
        assert result.success is True
        assert result.data["eligible"] is True
        assert result.data["framework"] == "flask"
        assert "eligible" in result.caption

    @pytest.mark.asyncio
    async def test_ineligible_result(self, tool, temp_repo):
        _write(temp_repo / "app.py", "import os\nos.system('ls')\n")
        result = await tool.execute(path=str(temp_repo), framework="flask")
        assert result.success is True
        assert result.data["eligible"] is False
        assert len(result.data["blockers"]) >= 1
        assert "blockers" in result.caption

    @pytest.mark.asyncio
    async def test_missing_path_returns_error(self, tool):
        result = await tool.execute(path="/nonexistent/path", framework="flask")
        assert result.success is False
        assert "Path not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_rationale_in_data(self, tool, temp_repo):
        result = await tool.execute(path=str(temp_repo), framework="go")
        assert result.data["rationale"]
        assert "base: bare" in result.data["rationale"]

    def test_schema_lists_eligible_frameworks(self, tool):
        enum = tool.parameters["properties"]["framework"]["enum"]
        assert set(enum) == set(CHISEL_ELIGIBLE_FRAMEWORKS)
        assert "flask" in enum
        assert "go" in enum
        assert "spring-boot" in enum

    def test_name(self, tool):
        assert tool.name == "check_chisel_eligibility"


# ---------------------------------------------------------------------------
# Fixture-style integration: typical 12-factor app repos pass the rubric
# ---------------------------------------------------------------------------


class TestTypicalWorkloadsAreEligible:
    """Representative minimal repos that should be eligible for a chiselled base.

    These fixtures prove that expected runtime files / entrypoints / libraries
    do not accidentally trigger blockers.
    """

    def test_flask_app_with_gunicorn(self, temp_repo):
        _write(temp_repo / "requirements.txt", "flask\ngunicorn\n")
        _write(
            temp_repo / "app.py",
            "from flask import Flask\napp = Flask(__name__)\n\n@app.route('/')\ndef index(): return 'ok'\n",
        )
        report = check_chisel_eligibility(temp_repo, "flask")
        assert report.eligible is True

    def test_fastapi_app_with_uvicorn(self, temp_repo):
        _write(temp_repo / "requirements.txt", "fastapi\nuvicorn[standard]\n")
        _write(
            temp_repo / "app.py",
            "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/')\nasync def root(): return {'ok': True}\n",
        )
        report = check_chisel_eligibility(temp_repo, "fastapi")
        assert report.eligible is True

    def test_go_http_server(self, temp_repo):
        _write(temp_repo / "go.mod", "module example.com/svc\n\ngo 1.22\n")
        _write(
            temp_repo / "main.go",
            "package main\nimport \"net/http\"\nfunc main() { http.ListenAndServe(':8080', nil) }\n",
        )
        report = check_chisel_eligibility(temp_repo, "go")
        assert report.eligible is True

    def test_express_app_without_lifecycle_hooks(self, temp_repo):
        pkg = {
            "name": "myapp",
            "version": "1.0.0",
            "scripts": {"start": "node server.js"},
            "dependencies": {"express": "^4.18.2"},
        }
        _write(temp_repo / "app" / "package.json", json.dumps(pkg))
        _write(
            temp_repo / "app" / "server.js",
            "const express = require('express');\nconst app = express();\napp.listen(8080);\n",
        )
        report = check_chisel_eligibility(temp_repo, "express")
        assert report.eligible is True

    def test_django_app_no_shell_calls(self, temp_repo):
        project = temp_repo.name.replace("-", "_").lower()
        _write(temp_repo / "requirements.txt", "Django>=4.2\n")
        _write(
            temp_repo / project / project / "wsgi.py",
            "from django.core.wsgi import get_wsgi_application\napplication = get_wsgi_application()\n",
        )
        report = check_chisel_eligibility(temp_repo, "django")
        assert report.eligible is True

    def test_spring_boot_eligible_with_advisory(self, temp_repo):
        _write(temp_repo / "pom.xml", "<project/>\n")
        report = check_chisel_eligibility(temp_repo, "spring-boot")
        assert report.eligible is True
        # Advisory about JRE slices must be present.
        assert any("JRE slice set" in a for a in report.advisories)
