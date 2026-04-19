"""Tests for _inject_coverage_threshold and the GitHub workflow injector."""

import tempfile
from pathlib import Path

from cantrip.agent.tools.charm import (
    _inject_coverage_threshold,
)

# ===================================================================
# TestInjectCoverageThreshold
# ===================================================================


class TestInjectCoverageThreshold:
    """Tests for _inject_coverage_threshold — pyproject.toml injection."""

    def test_adds_fail_under_to_existing_report_section(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            pyproject = target / "pyproject.toml"
            pyproject.write_text(
                "[tool.coverage.run]\nbranch = true\n\n"
                "[tool.coverage.report]\nshow_missing = true\n"
            )
            actions = _inject_coverage_threshold(target)
            content = pyproject.read_text()
            assert "fail_under = 80" in content
            assert len(actions) == 1
            assert "80%" in actions[0]

    def test_skips_when_fail_under_already_set(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            pyproject = target / "pyproject.toml"
            pyproject.write_text("[tool.coverage.report]\nfail_under = 90\nshow_missing = true\n")
            actions = _inject_coverage_threshold(target)
            content = pyproject.read_text()
            assert "fail_under = 90" in content
            assert content.count("fail_under") == 1
            assert "already configured" in actions[0]

    def test_creates_report_section_when_only_run_exists(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            pyproject = target / "pyproject.toml"
            pyproject.write_text("[tool.coverage.run]\nbranch = true\n")
            _inject_coverage_threshold(target)
            content = pyproject.read_text()
            assert "[tool.coverage.report]" in content
            assert "fail_under = 80" in content

    def test_creates_both_sections_when_no_coverage_config(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            pyproject = target / "pyproject.toml"
            pyproject.write_text("[project]\nname = 'my-charm'\n")
            _inject_coverage_threshold(target)
            content = pyproject.read_text()
            assert "[tool.coverage.run]" in content
            assert "[tool.coverage.report]" in content
            assert "fail_under = 80" in content

    def test_no_pyproject_returns_skip_message(self):
        with tempfile.TemporaryDirectory() as td:
            actions = _inject_coverage_threshold(Path(td))
            assert "skipped" in actions[0]


class TestInjectGithubWorkflows:
    """Tests for workflow/Dependabot/SECURITY.md scaffolding."""

    def test_creates_all_expected_files(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            actions = inject_github_workflows(target, "my-charm")

            assert (target / ".github" / "workflows" / "ci.yaml").exists()
            assert (target / ".github" / "workflows" / "security.yaml").exists()
            assert (target / ".github" / "workflows" / "release.yaml").exists()
            assert (target / ".github" / "dependabot.yml").exists()
            assert (target / "SECURITY.md").exists()
            assert len(actions) == 5
            assert all("Created" in a for a in actions)

    def test_preserves_existing_files(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            workflows = target / ".github" / "workflows"
            workflows.mkdir(parents=True)
            existing_ci = workflows / "ci.yaml"
            existing_ci.write_text("name: custom CI\n")

            actions = inject_github_workflows(target, "my-charm")

            assert existing_ci.read_text() == "name: custom CI\n"
            assert any("already exists" in a and "ci.yaml" in a for a in actions)
            assert (workflows / "security.yaml").exists()

    def test_actions_pinned_to_full_shas(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            ci = (target / ".github" / "workflows" / "ci.yaml").read_text()
            security = (target / ".github" / "workflows" / "security.yaml").read_text()
            release = (target / ".github" / "workflows" / "release.yaml").read_text()

            # No floating tag pins like ``@v4`` without a SHA.
            import re

            combined = ci + security + release
            for match in re.finditer(r"uses:\s*\S+", combined):
                line = match.group(0)
                # Every ``uses:`` line must have an @<40-hex-sha>.
                assert re.search(r"@[0-9a-f]{40}", line), f"unpinned action: {line}"

    def test_checkout_sets_persist_credentials_false(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            for name in ("ci.yaml", "security.yaml", "release.yaml"):
                content = (target / ".github" / "workflows" / name).read_text()
                # Every checkout step should be followed by persist-credentials: false.
                assert content.count("actions/checkout@") == content.count(
                    "persist-credentials: false"
                ), f"{name} has a checkout without persist-credentials: false"

    def test_workflows_have_empty_workflow_level_permissions(self):
        import yaml

        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            for name in ("ci.yaml", "security.yaml", "release.yaml"):
                content = (target / ".github" / "workflows" / name).read_text()
                parsed = yaml.safe_load(content)
                # Workflow-level permissions should be an empty mapping so
                # each job must opt in to what it needs.
                assert parsed.get("permissions") == {}, (
                    f"{name} should declare empty workflow-level permissions"
                )

    def test_release_uses_environment_and_avoids_pull_request_target(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            release = (target / ".github" / "workflows" / "release.yaml").read_text()
            assert "environment: charmhub" in release
            assert "workflow_dispatch" in release
            # Tag creation happens via gh api, not via git push.
            assert "git push origin" not in release
            # Never use pull_request_target.
            for name in ("ci.yaml", "security.yaml", "release.yaml"):
                content = (target / ".github" / "workflows" / name).read_text()
                assert "pull_request_target" not in content

    def test_dependabot_includes_cooldowns(self):
        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            config = (target / ".github" / "dependabot.yml").read_text()
            assert "cooldown:" in config
            assert "default-days: 14" in config
            assert "github-actions" in config
            assert "pip" in config

    def test_generated_yaml_parses(self):
        """Every generated YAML file must parse cleanly."""
        import yaml

        from cantrip.agent.tools.workflows import inject_github_workflows

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            inject_github_workflows(target, "my-charm")
            for path in (
                target / ".github" / "workflows" / "ci.yaml",
                target / ".github" / "workflows" / "security.yaml",
                target / ".github" / "workflows" / "release.yaml",
                target / ".github" / "dependabot.yml",
            ):
                yaml.safe_load(path.read_text())
