"""Tests for the rock-contract validator ported from canonical/skills.

Exercises both the pure :func:`check_rock_contract` helper and the
:class:`RockContractCheckTool` wrapper for every supported framework.
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
import tempfile

import pytest

from cantrip.agent.tools.rock_contract import (
    SUPPORTED_BASES,
    SUPPORTED_FRAMEWORKS,
    UnknownFrameworkError,
    check_rock_contract,
)
from cantrip.agent.tools.rockcraft import RockContractCheckTool


@pytest.fixture
def temp_repo():
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


def _write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestCheckRockContractFlask:
    def test_fit_with_flask_app(self, temp_repo):
        _write(temp_repo / "requirements.txt", "flask\n")
        _write(temp_repo / "app.py", "from flask import Flask\napp = Flask(__name__)\n")
        report = check_rock_contract(temp_repo, "flask")
        assert report.fit is True
        assert report.issues == []

    def test_fit_with_create_app_factory(self, temp_repo):
        _write(temp_repo / "requirements.txt", "Flask>=3.0\n")
        _write(
            temp_repo / "app" / "__init__.py",
            "def create_app():\n    from flask import Flask\n    return Flask(__name__)\n",
        )
        report = check_rock_contract(temp_repo, "flask")
        assert report.fit is True

    def test_no_fit_when_dep_missing(self, temp_repo):
        _write(temp_repo / "app.py", "app = object()\n")
        report = check_rock_contract(temp_repo, "flask")
        assert report.fit is False
        assert any("Flask dependency" in issue for issue in report.issues)

    def test_no_fit_when_entrypoint_missing(self, temp_repo):
        _write(temp_repo / "requirements.txt", "flask\n")
        report = check_rock_contract(temp_repo, "flask")
        assert report.fit is False
        assert any("Flask WSGI entrypoint" in issue for issue in report.issues)

    def test_charm_dir_with_pyproject_warns(self, temp_repo):
        _write(temp_repo / "requirements.txt", "flask\n")
        _write(temp_repo / "app.py", "from flask import Flask\napp = Flask(__name__)\n")
        _write(temp_repo / "pyproject.toml", '[project]\nname = "x"\nversion = "0.1"\n')
        (temp_repo / "charm").mkdir()
        report = check_rock_contract(temp_repo, "flask")
        assert report.fit is True  # warnings, not blockers
        assert any("metadata discovery" in warning for warning in report.warnings)


class TestCheckRockContractDjango:
    def _scaffold(self, repo: pathlib.Path, with_wsgi: bool = True) -> None:
        _write(repo / "requirements.txt", "Django>=4.2\n")
        if with_wsgi:
            project = repo.name.replace("-", "_").lower()
            _write(
                repo / project / project / "wsgi.py",
                "application = object()\n",
            )

    def test_fit_with_standard_layout(self, tmp_path):
        repo = tmp_path / "myproject"
        repo.mkdir()
        self._scaffold(repo)
        report = check_rock_contract(repo, "django")
        assert report.fit is True

    def test_fit_with_mysite_layout(self, tmp_path):
        repo = tmp_path / "myproject"
        repo.mkdir()
        _write(repo / "requirements.txt", "Django\n")
        _write(repo / "myproject" / "mysite" / "wsgi.py", "application = object()\n")
        report = check_rock_contract(repo, "django")
        assert report.fit is True

    def test_no_fit_without_requirements(self, tmp_path):
        repo = tmp_path / "myproject"
        repo.mkdir()
        report = check_rock_contract(repo, "django")
        assert report.fit is False
        assert any("requirements.txt" in issue for issue in report.issues)

    def test_no_fit_without_wsgi(self, tmp_path):
        repo = tmp_path / "myproject"
        repo.mkdir()
        _write(repo / "requirements.txt", "Django\n")
        report = check_rock_contract(repo, "django")
        assert report.fit is False
        assert any("wsgi.py" in issue for issue in report.issues)


class TestCheckRockContractFastAPI:
    def test_fit_with_fastapi_dep_and_app(self, temp_repo):
        _write(temp_repo / "requirements.txt", "fastapi\nuvicorn\n")
        _write(
            temp_repo / "app.py",
            "from fastapi import FastAPI\napp = FastAPI()\n",
        )
        report = check_rock_contract(temp_repo, "fastapi")
        assert report.fit is True

    def test_starlette_dep_also_satisfies(self, temp_repo):
        _write(temp_repo / "requirements.txt", "starlette\n")
        _write(temp_repo / "main.py", "app = object()\n")
        report = check_rock_contract(temp_repo, "fastapi")
        assert report.fit is True

    def test_no_fit_with_unrelated_python_deps(self, temp_repo):
        _write(temp_repo / "requirements.txt", "requests\n")
        _write(temp_repo / "app.py", "app = object()\n")
        report = check_rock_contract(temp_repo, "fastapi")
        assert report.fit is False
        assert any("fastapi or starlette" in issue for issue in report.issues)

    def test_no_fit_without_app_object(self, temp_repo):
        _write(temp_repo / "requirements.txt", "fastapi\n")
        report = check_rock_contract(temp_repo, "fastapi")
        assert report.fit is False
        assert any("ASGI `app` object" in issue for issue in report.issues)


class TestCheckRockContractExpress:
    def test_fit_with_app_package_json(self, temp_repo):
        _write(
            temp_repo / "app" / "package.json",
            json.dumps({"name": "x", "scripts": {"start": "node ."}}),
        )
        report = check_rock_contract(temp_repo, "express")
        assert report.fit is True

    def test_no_fit_without_app_package_json(self, temp_repo):
        report = check_rock_contract(temp_repo, "express")
        assert report.fit is False
        assert any("app/package.json" in issue for issue in report.issues)

    def test_no_fit_with_invalid_json(self, temp_repo):
        _write(temp_repo / "app" / "package.json", "not json")
        report = check_rock_contract(temp_repo, "express")
        assert report.fit is False
        assert any("not valid JSON" in issue for issue in report.issues)

    def test_no_fit_missing_name(self, temp_repo):
        _write(
            temp_repo / "app" / "package.json",
            json.dumps({"scripts": {"start": "node ."}}),
        )
        report = check_rock_contract(temp_repo, "express")
        assert report.fit is False
        assert any("`name`" in issue for issue in report.issues)

    def test_no_fit_missing_start_script(self, temp_repo):
        _write(temp_repo / "app" / "package.json", json.dumps({"name": "x"}))
        report = check_rock_contract(temp_repo, "express")
        assert report.fit is False
        assert any("scripts.start" in issue for issue in report.issues)


class TestCheckRockContractGo:
    def test_fit_with_go_mod(self, temp_repo):
        _write(temp_repo / "go.mod", "module example.com/x\n\ngo 1.22\n")
        report = check_rock_contract(temp_repo, "go")
        assert report.fit is True
        assert any("module path" in warning for warning in report.warnings)

    def test_no_fit_without_go_mod(self, temp_repo):
        report = check_rock_contract(temp_repo, "go")
        assert report.fit is False
        assert any("go.mod" in issue for issue in report.issues)

    def test_warns_when_cmd_dir_does_not_match_rock_name(self, tmp_path):
        repo = tmp_path / "myrock"
        repo.mkdir()
        _write(repo / "go.mod", "module example.com/myrock\n\ngo 1.22\n")
        _write(repo / "cmd" / "server" / "main.go", "package main\nfunc main() {}\n")
        report = check_rock_contract(repo, "go")
        assert report.fit is True
        assert any(
            "cmd/* directory matches the rock name" in warning for warning in report.warnings
        )

    def test_matching_cmd_dir_takes_alternate_branch(self, tmp_path):
        repo = tmp_path / "myrock"
        repo.mkdir()
        _write(repo / "go.mod", "module example.com/myrock\n\ngo 1.22\n")
        _write(repo / "cmd" / "myrock" / "main.go", "package main\nfunc main() {}\n")
        report = check_rock_contract(repo, "go")
        # Both branches surface the organize warning, just with
        # different wording — assert one of the two fires.
        assert any("organize" in warning for warning in report.warnings)


class TestCheckRockContractSpringBoot:
    def test_fit_with_pom_only(self, temp_repo):
        _write(temp_repo / "pom.xml", "<project/>\n")
        report = check_rock_contract(temp_repo, "spring-boot")
        assert report.fit is True

    def test_fit_with_gradle_only(self, temp_repo):
        _write(temp_repo / "build.gradle", "// build\n")
        report = check_rock_contract(temp_repo, "spring-boot")
        assert report.fit is True

    def test_fit_with_kotlin_dsl_only(self, temp_repo):
        _write(temp_repo / "build.gradle.kts", "// build\n")
        report = check_rock_contract(temp_repo, "spring-boot")
        assert report.fit is True

    def test_no_fit_with_both_pom_and_gradle(self, temp_repo):
        _write(temp_repo / "pom.xml", "<project/>\n")
        _write(temp_repo / "build.gradle", "// build\n")
        report = check_rock_contract(temp_repo, "spring-boot")
        assert report.fit is False
        assert any("both" in issue and "pom.xml" in issue for issue in report.issues)

    def test_no_fit_with_both_wrappers(self, temp_repo):
        _write(temp_repo / "pom.xml", "<project/>\n")
        _write(temp_repo / "mvnw", "#!/bin/sh\n")
        _write(temp_repo / "gradlew", "#!/bin/sh\n")
        os.chmod(temp_repo / "mvnw", 0o755)
        os.chmod(temp_repo / "gradlew", 0o755)
        report = check_rock_contract(temp_repo, "spring-boot")
        assert report.fit is False
        assert any("mvnw and gradlew" in issue for issue in report.issues)

    def test_non_executable_wrapper_is_an_issue(self, temp_repo):
        _write(temp_repo / "pom.xml", "<project/>\n")
        _write(temp_repo / "mvnw", "#!/bin/sh\n")
        # Strip the execute bit explicitly — write_text leaves files
        # readable but not executable by default, so just confirm.
        os.chmod(temp_repo / "mvnw", stat.S_IRUSR | stat.S_IWUSR)
        report = check_rock_contract(temp_repo, "spring-boot")
        assert report.fit is False
        assert any("not executable" in issue for issue in report.issues)

    def test_no_fit_when_neither_present(self, temp_repo):
        report = check_rock_contract(temp_repo, "spring-boot")
        assert report.fit is False
        assert any("requires pom.xml" in issue for issue in report.issues)


class TestSupportedBasesAndFrameworkSet:
    def test_every_framework_has_supported_bases(self):
        assert set(SUPPORTED_BASES) == set(SUPPORTED_FRAMEWORKS)

    def test_python_frameworks_accept_22_04(self):
        # Flask and Django are stable extensions — Ubuntu 22.04 + 24.04.
        for fw in ("flask", "django"):
            bases = SUPPORTED_BASES[fw]
            assert "ubuntu@22.04" in bases
            assert "ubuntu@24.04" in bases

    def test_experimental_frameworks_only_24_04(self):
        # FastAPI, Express, Go, Spring Boot are experimental — 24.04 only.
        for fw in ("fastapi", "express", "go", "spring-boot"):
            bases = SUPPORTED_BASES[fw]
            assert "ubuntu@24.04" in bases
            assert "ubuntu@22.04" not in bases

    def test_unknown_framework_raises(self, temp_repo):
        with pytest.raises(UnknownFrameworkError):
            check_rock_contract(temp_repo, "rails")


class TestRockContractCheckTool:
    @pytest.fixture
    def tool(self):
        return RockContractCheckTool()

    @pytest.mark.asyncio
    async def test_returns_fit_payload(self, tool, temp_repo):
        _write(temp_repo / "go.mod", "module example.com/x\n\ngo 1.22\n")
        result = await tool.execute(path=str(temp_repo), framework="go")
        assert result.success is True
        assert result.data["fit"] is True
        assert result.data["framework"] == "go"
        assert "ubuntu@24.04" in result.data["supported_bases"]
        assert result.caption == "check_rock_contract(go) → fit"

    @pytest.mark.asyncio
    async def test_returns_no_fit_payload(self, tool, temp_repo):
        result = await tool.execute(path=str(temp_repo), framework="go")
        assert result.success is True  # Tool ran cleanly; rock just doesn't fit.
        assert result.data["fit"] is False
        assert len(result.data["issues"]) >= 1
        assert "1 issues" in result.caption

    @pytest.mark.asyncio
    async def test_uses_cantrip_express_name(self, tool, temp_repo):
        _write(
            temp_repo / "app" / "package.json",
            json.dumps({"name": "x", "scripts": {"start": "node ."}}),
        )
        result = await tool.execute(path=str(temp_repo), framework="express")
        assert result.data["fit"] is True
        assert result.data["framework"] == "express"

    @pytest.mark.asyncio
    async def test_unknown_framework_surfaces_as_error(self, tool, temp_repo):
        result = await tool.execute(path=str(temp_repo), framework="rails")
        assert result.success is False
        assert "Unknown framework" in (result.error or "")

    @pytest.mark.asyncio
    async def test_missing_path_returns_error(self, tool):
        result = await tool.execute(path="/nonexistent/path", framework="flask")
        assert result.success is False
        assert "Path not found" in (result.error or "")

    def test_schema_lists_cantrip_framework_names(self, tool):
        enum = tool.parameters["properties"]["framework"]["enum"]
        assert "express" in enum
        assert "expressjs" not in enum  # Upstream name must not leak.
        assert set(enum) == set(SUPPORTED_FRAMEWORKS)
