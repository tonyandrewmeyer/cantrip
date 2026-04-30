"""Tests for framework_detection helpers ported from canonical/skills.

Covers the new structured-output surface (candidates, signals,
web-app fit) added on top of AnalyseFrameworkTool by Phase 91.1.
The legacy public-contract tests live in
``tests/unit/charm_tools/test_analyse_framework.py``.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from cantrip.agent.tools.charm import AnalyseFrameworkTool
from cantrip.agent.tools.framework_detection import detect_frameworks


@pytest.fixture
def temp_repo():
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


class TestDetectFrameworksHelper:
    """Pure-helper tests — no Tool wrapping."""

    def test_django_dependency_with_manage_py(self, temp_repo):
        (temp_repo / "requirements.txt").write_text("Django>=4.2\npsycopg2\n")
        (temp_repo / "manage.py").write_text("# entry\n")
        result = detect_frameworks(temp_repo)
        assert result.detected == "django"
        # Both signals (dep + manage.py) should be in the django entry.
        django = next(c for c in result.candidates if c["framework"] == "django")
        signals = " ".join(django["signals"])
        assert "django" in signals.lower()
        assert "manage.py" in signals

    def test_recursive_requirements_include(self, temp_repo):
        (temp_repo / "requirements.txt").write_text("-r requirements/base.txt\n")
        (temp_repo / "requirements").mkdir()
        (temp_repo / "requirements" / "base.txt").write_text("flask\n")
        result = detect_frameworks(temp_repo)
        assert result.detected == "flask"

    def test_pyproject_pep621_dependencies(self, temp_repo):
        (temp_repo / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.1"\n'
            'dependencies = ["fastapi>=0.100", "uvicorn[standard]"]\n'
        )
        result = detect_frameworks(temp_repo)
        assert result.detected == "fastapi"

    def test_pyproject_poetry_dependencies(self, temp_repo):
        (temp_repo / "pyproject.toml").write_text(
            '[tool.poetry]\nname = "x"\nversion = "0.1"\n'
            '[tool.poetry.dependencies]\npython = "^3.12"\nflask = "^3.0"\n'
        )
        result = detect_frameworks(temp_repo)
        assert result.detected == "flask"

    def test_express_via_app_package_json_outranks_root(self, temp_repo):
        (temp_repo / "app").mkdir()
        (temp_repo / "app" / "package.json").write_text(
            json.dumps(
                {
                    "name": "myapp",
                    "scripts": {"start": "node ."},
                    "dependencies": {"express": "^4.18.0"},
                }
            )
        )
        result = detect_frameworks(temp_repo)
        # Mapping to Cantrip's ``express`` happens at the tool layer.
        assert result.detected == "expressjs"
        candidates = {c["framework"]: c["score"] for c in result.candidates}
        assert candidates["expressjs"] >= 7  # 3 + 1 + 2 + 2

    def test_go_module(self, temp_repo):
        (temp_repo / "go.mod").write_text("module example.com/x\n\ngo 1.22\n")
        result = detect_frameworks(temp_repo)
        assert result.detected == "go"

    def test_spring_boot_kotlin_dsl(self, temp_repo):
        (temp_repo / "build.gradle.kts").write_text(
            'plugins { id("org.springframework.boot") version "3.2.0" }\n'
        )
        result = detect_frameworks(temp_repo)
        assert result.detected == "spring-boot"

    def test_no_framework_detected(self, temp_repo):
        (temp_repo / "main.rs").write_text("fn main() {}\n")
        result = detect_frameworks(temp_repo)
        assert result.detected is None
        assert "No supported framework" in result.notes[0]

    def test_bare_package_json_is_not_express(self, temp_repo):
        # A Next.js / Vite app has package.json but no express dep —
        # the upstream's bare ``+2`` score must not trip the threshold.
        (temp_repo / "package.json").write_text(json.dumps({"dependencies": {"next": "^14.0.0"}}))
        result = detect_frameworks(temp_repo)
        assert result.detected is None

    def test_web_app_signal_for_flask(self, temp_repo):
        (temp_repo / "requirements.txt").write_text("flask\n")
        (temp_repo / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
        result = detect_frameworks(temp_repo)
        assert result.detected == "flask"
        assert result.web_app_guess is True
        assert any(
            "Flask entrypoint" in s or "route or controller" in s or "listen-port" in s
            for s in result.web_app_signals_positive
        )

    def test_console_script_negative_signal(self, temp_repo):
        # FastAPI in deps but pyproject also exposes a console script —
        # the negative signal should land in the structured output even
        # when the framework still scores high enough to detect.
        (temp_repo / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.1"\n'
            'dependencies = ["fastapi"]\n'
            '[project.scripts]\nx = "x:main"\n'
        )
        result = detect_frameworks(temp_repo)
        assert result.detected == "fastapi"
        assert any("console-style" in s for s in result.web_app_signals_negative)

    def test_low_web_confidence_note_when_no_signals(self, temp_repo):
        (temp_repo / "go.mod").write_text("module example.com/x\n\ngo 1.22\n")
        # No source files defining HTTP handlers — only the go.mod
        # itself.  The framework still detects, but web confidence
        # should call this out.
        result = detect_frameworks(temp_repo)
        assert result.detected == "go"
        assert result.web_app_guess is False
        assert any("web-service confidence" in n for n in result.notes)


class TestAnalyseFrameworkToolStructuredOutput:
    """The tool should expose the new structured fields downstream."""

    @pytest.fixture
    def tool(self):
        return AnalyseFrameworkTool()

    @pytest.mark.asyncio
    async def test_candidates_remapped_to_cantrip_names(self, tool, temp_repo):
        (temp_repo / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^4.18.0"}})
        )
        result = await tool.execute(path=str(temp_repo))
        assert result.success
        # Upstream "expressjs" must be translated to Cantrip's "express"
        # in both the top-level framework field and the candidate list.
        assert result.data["framework"] == "express"
        candidate_names = {c["framework"] for c in result.data["candidates"]}
        assert "express" in candidate_names
        assert "expressjs" not in candidate_names

    @pytest.mark.asyncio
    async def test_web_app_guess_surfaced(self, tool, temp_repo):
        (temp_repo / "requirements.txt").write_text("flask\n")
        (temp_repo / "app.py").write_text(
            "from flask import Flask\napp = Flask(__name__)\n@app.route('/')\ndef i(): return ''\n"
        )
        result = await tool.execute(path=str(temp_repo))
        assert result.data["web_app_guess"] is True
        assert isinstance(result.data["web_app_signals"], dict)
        assert "positive" in result.data["web_app_signals"]
        assert "negative" in result.data["web_app_signals"]

    @pytest.mark.asyncio
    async def test_detection_notes_present_for_unknown(self, tool, temp_repo):
        (temp_repo / "main.rs").write_text("fn main() {}\n")
        result = await tool.execute(path=str(temp_repo))
        assert result.data["framework"] is None
        assert any("No supported framework" in note for note in result.data["detection_notes"])

    @pytest.mark.asyncio
    async def test_django_outranks_flask_when_both_deps_present(self, tool, temp_repo):
        # Defensive: an unrelated dep mentioning "flask" plus real
        # Django wiring should still pick Django.  manage.py + django
        # dep tot 7; flask dep alone scores 4.
        (temp_repo / "requirements.txt").write_text("Django>=4.2\nflask-cors\n")
        (temp_repo / "manage.py").write_text("# entry\n")
        result = await tool.execute(path=str(temp_repo))
        assert result.data["framework"] == "django"
