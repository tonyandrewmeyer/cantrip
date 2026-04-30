"""Tests for the env-key inspector ported from canonical/skills.

Covers per-language regexes, ``.env`` files, the IGNORED_DIRS walk
filter, and the framework-contract lookup at both helper and tool
layers.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from cantrip.agent.tools.env_keys import (
    SUPPORTED_CONTRACT_FRAMEWORKS,
    InspectEnvKeysTool,
    inspect_env_keys,
)


@pytest.fixture
def temp_repo():
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


def _write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestInspectEnvKeysHelper:
    def test_python_os_getenv(self, temp_repo):
        _write(
            temp_repo / "app.py",
            'import os\nx = os.getenv("DATABASE_URL")\ny = os.environ.get("PORT")\n'
            'z = os.environ["SECRET_KEY"]\n',
        )
        report = inspect_env_keys(temp_repo)
        assert set(report.detected_env_keys) == {"DATABASE_URL", "PORT", "SECRET_KEY"}

    def test_javascript_process_env(self, temp_repo):
        _write(
            temp_repo / "server.js",
            'const p = process.env.PORT;\nconst e = process.env["NODE_ENV"];\n',
        )
        report = inspect_env_keys(temp_repo)
        assert set(report.detected_env_keys) == {"PORT", "NODE_ENV"}

    def test_typescript_inherits_javascript_patterns(self, temp_repo):
        _write(temp_repo / "main.ts", "const port = process.env.APP_PORT;\n")
        report = inspect_env_keys(temp_repo)
        assert "APP_PORT" in report.detected_env_keys

    def test_go_os_getenv(self, temp_repo):
        _write(
            temp_repo / "main.go",
            'package main\nimport "os"\nfunc x() string { return os.Getenv("APP_PORT") }\n'
            'func y() (string, bool) { return os.LookupEnv("APP_HOST") }\n',
        )
        report = inspect_env_keys(temp_repo)
        assert set(report.detected_env_keys) == {"APP_PORT", "APP_HOST"}

    def test_java_system_getenv(self, temp_repo):
        _write(
            temp_repo / "Main.java",
            'public class Main { String x = System.getenv("DATABASE_URL"); }\n',
        )
        report = inspect_env_keys(temp_repo)
        assert "DATABASE_URL" in report.detected_env_keys

    def test_spring_property_placeholders(self, temp_repo):
        # Inherits an upstream limitation: the bare ``${...}`` pattern
        # only matches when there's no ``:default`` suffix.  Defaults
        # are stripped *only* inside ``@Value("${k:d}")``.  We assert
        # both the catch and the gap so a future widening (e.g. to
        # ``${KEY:default}`` in a properties file) is a deliberate
        # change with a test diff, not a silent shift.
        _write(
            temp_repo / "application.properties",
            "spring.datasource.url=${SPRING_DATASOURCE_URL}\nserver.port=${SERVER_PORT:8080}\n",
        )
        report = inspect_env_keys(temp_repo)
        assert "SPRING_DATASOURCE_URL" in report.detected_env_keys
        assert "SERVER_PORT" not in report.detected_env_keys

    def test_spring_value_annotation_strips_default(self, temp_repo):
        _write(
            temp_repo / "Config.java",
            '@Value("${app.secret-key:fallback}")\nString secretKey;\n',
        )
        report = inspect_env_keys(temp_repo)
        # Default after the colon must be dropped from the captured key.
        assert "app.secret-key" in report.detected_env_keys

    def test_dotenv_file(self, temp_repo):
        _write(
            temp_repo / ".env",
            "# comment\nDATABASE_URL=postgres://localhost\nPORT=8000\n",
        )
        report = inspect_env_keys(temp_repo)
        assert {"DATABASE_URL", "PORT"} <= set(report.detected_env_keys)

    def test_dotenv_sample_files_included(self, temp_repo):
        _write(temp_repo / ".env.sample", "API_KEY=changeme\n")
        report = inspect_env_keys(temp_repo)
        assert "API_KEY" in report.detected_env_keys

    def test_ignored_dirs_are_skipped(self, temp_repo):
        # Files under .venv / node_modules / __pycache__ are common
        # noise sources — env keys that live only there should not
        # leak into the report.
        _write(
            temp_repo / ".venv" / "lib" / "noise.py",
            'os.getenv("VENV_LEAK")\n',
        )
        _write(
            temp_repo / "node_modules" / "pkg" / "index.js",
            "process.env.NODE_LEAK\n",
        )
        _write(
            temp_repo / "__pycache__" / "cached.py",
            'os.getenv("CACHE_LEAK")\n',
        )
        _write(
            temp_repo / ".ruff_cache" / "0.0.0" / "x.py",
            'os.getenv("RUFF_LEAK")\n',
        )
        # And one real reference at the root that must be picked up.
        _write(temp_repo / "app.py", 'os.getenv("REAL_KEY")\n')
        report = inspect_env_keys(temp_repo)
        assert report.detected_env_keys == ["REAL_KEY"]

    def test_per_file_map(self, temp_repo):
        _write(temp_repo / "a.py", 'os.getenv("A_KEY")\n')
        _write(temp_repo / "b.py", 'os.getenv("B_KEY")\n')
        report = inspect_env_keys(temp_repo)
        assert report.per_file == {"a.py": ["A_KEY"], "b.py": ["B_KEY"]}

    def test_framework_contract_returned_when_requested(self, temp_repo):
        _write(temp_repo / "app.py", 'os.getenv("FLASK_DEBUG")\n')
        report = inspect_env_keys(temp_repo, framework="flask")
        assert report.framework == "flask"
        assert report.framework_contract is not None
        assert report.framework_contract["user_config_prefix"] == "FLASK_"
        assert "FLASK_DEBUG" in report.framework_contract["built_in_env_examples"]

    def test_no_framework_yields_no_contract(self, temp_repo):
        _write(temp_repo / "app.py", 'os.getenv("X")\n')
        report = inspect_env_keys(temp_repo)
        assert report.framework is None
        assert report.framework_contract is None

    def test_unknown_framework_yields_none_contract_without_raising(self, temp_repo):
        _write(temp_repo / "app.py", 'os.getenv("X")\n')
        report = inspect_env_keys(temp_repo, framework="rails")
        assert report.framework == "rails"
        assert report.framework_contract is None

    def test_express_contract_uses_cantrip_name(self):
        # Smoke-test that the upstream "expressjs" key was renamed to
        # "express" in the contract dict.
        assert "express" in SUPPORTED_CONTRACT_FRAMEWORKS
        assert "expressjs" not in SUPPORTED_CONTRACT_FRAMEWORKS

    def test_spring_boot_relation_families_carry_oauth(self):
        # Spring Boot's contract has spring.security.oauth2.* in place
        # of OTEL_* — preserve that detail through the port.
        from cantrip.agent.tools.env_keys import _FRAMEWORK_CONTRACTS

        spring = _FRAMEWORK_CONTRACTS["spring-boot"]
        assert "spring.security.oauth2.*" in spring["relation_env_families"]
        assert "OTEL_*" not in spring["relation_env_families"]


class TestInspectEnvKeysTool:
    @pytest.fixture
    def tool(self):
        return InspectEnvKeysTool()

    @pytest.mark.asyncio
    async def test_returns_sorted_keys(self, tool, temp_repo):
        _write(
            temp_repo / "app.py",
            'os.getenv("Z_KEY"); os.getenv("A_KEY"); os.getenv("M_KEY")\n',
        )
        result = await tool.execute(path=str(temp_repo))
        assert result.success is True
        assert result.data["detected_env_keys"] == ["A_KEY", "M_KEY", "Z_KEY"]
        assert "3 keys" in result.caption

    @pytest.mark.asyncio
    async def test_caption_zero_keys(self, tool, temp_repo):
        result = await tool.execute(path=str(temp_repo))
        assert result.success is True
        assert result.data["detected_env_keys"] == []
        assert "0 keys" in result.caption

    @pytest.mark.asyncio
    async def test_framework_contract_in_payload(self, tool, temp_repo):
        _write(temp_repo / "app.py", 'os.getenv("FLASK_DEBUG")\n')
        result = await tool.execute(path=str(temp_repo), framework="flask")
        assert result.data["framework_contract"] is not None
        assert result.data["framework_contract"]["user_config_prefix"] == "FLASK_"
        assert "Framework contract" in result.output

    @pytest.mark.asyncio
    async def test_missing_path_returns_error(self, tool):
        result = await tool.execute(path="/nonexistent/path")
        assert result.success is False
        assert "Path not found" in (result.error or "")

    def test_schema_lists_cantrip_framework_names(self, tool):
        enum = tool.parameters["properties"]["framework"]["enum"]
        assert "express" in enum
        assert "expressjs" not in enum
        assert set(enum) == set(SUPPORTED_CONTRACT_FRAMEWORKS)
