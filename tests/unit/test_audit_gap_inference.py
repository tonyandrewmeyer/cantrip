"""Tests for _infer_gaps_from_audit and plan_improvement_fixes."""

from cantrip.agent.core import _infer_gaps_from_audit
from cantrip.agent.planner import PlanningContext, plan_improvement_fixes
from cantrip.agent.queue import TaskCategory


class TestInferGapsFromAudit:
    """Tests for the heuristic gap inference from audit text."""

    def test_no_gaps_in_clean_report(self):
        """A clean audit report triggers no gaps."""
        text = "All checks passed. The charm is well structured."
        gaps = _infer_gaps_from_audit(text)
        assert not any(gaps.values())

    def test_missing_tracing_detected(self):
        """Keywords 'tracing' + 'missing' trigger cos_tracing."""
        text = "COS integration: tracing is missing from the charm."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_tracing"] is True

    def test_no_tracing_phrasing(self):
        """'no tracing' phrasing also triggers the gap."""
        text = "There is no tracing support configured."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_tracing"] is True

    def test_missing_metrics(self):
        text = "Metrics endpoint is missing — no Prometheus scraping configured."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_metrics"] is True

    def test_missing_logging(self):
        text = "No logging integration with Loki. Logging is missing."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_logging"] is True

    def test_missing_dashboards(self):
        text = "Grafana dashboard is missing from the charm."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_dashboards"] is True

    def test_ops_tracing_not_installed(self):
        text = "ops-tracing library is not installed."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["ops_tracing"] is True

    def test_missing_unit_tests(self):
        text = "No unit tests found. Unit test coverage is missing."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["unit_tests"] is True

    def test_missing_integration_tests(self):
        text = "No integration test suite. Integration test coverage is missing."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["integration_tests"] is True

    def test_deprecated_storedstate(self):
        text = "The charm uses StoredState which is deprecated."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["deprecated_apis"] is True

    def test_deprecated_harness(self):
        text = "Tests still use Harness instead of Scenario."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["deprecated_apis"] is True

    def test_deprecated_fetch_libs(self):
        text = "Still using fetch-libs for libraries."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["deprecated_apis"] is True

    def test_missing_readme(self):
        text = "README is missing from the project."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["readme"] is True

    def test_missing_licence(self):
        text = "No licence file found. Licence is missing."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["licence"] is True

    def test_missing_license_american_spelling(self):
        """American spelling 'license' also triggers the gap."""
        text = "License file is missing."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["licence"] is True

    def test_missing_listing_metadata(self):
        text = "Charmhub listing metadata is incomplete."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["listing_metadata"] is True

    def test_missing_type_annotations(self):
        text = "Type annotations are missing throughout the codebase."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["type_annotations"] is True

    def test_case_insensitive(self):
        """Gap detection is case-insensitive."""
        text = "TRACING is MISSING from the CHARM."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_tracing"] is True

    def test_multiple_gaps_detected(self):
        """Multiple gaps in a single report are all detected."""
        text = (
            "Audit results:\n"
            "- Tracing is missing\n"
            "- No unit tests found\n"
            "- Still using Harness\n"
            "- README is missing\n"
        )
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_tracing"] is True
        assert gaps["unit_tests"] is True
        assert gaps["deprecated_apis"] is True
        assert gaps["readme"] is True

    def test_no_false_positive_from_unrelated_sections(self):
        """Keywords in different sections must not trigger false positives.

        'Good tracing setup' in one section and 'missing' in an unrelated
        section should NOT set cos_tracing=True.
        """
        text = (
            "## Observability\n"
            "Good tracing setup with ops-tracing configured.\n"
            "Metrics endpoint is present and working.\n"
            "\n"
            "## Testing\n"
            "Unit tests are missing.\n"
        )
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_tracing"] is False
        assert gaps["cos_metrics"] is False
        assert gaps["unit_tests"] is True

    def test_no_false_positive_good_tracing_no_logging(self):
        """'Good tracing, no logging' should only flag logging, not tracing."""
        text = "Tracing is properly configured. Logging is missing."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_tracing"] is False
        assert gaps["cos_logging"] is True

    def test_absent_keyword(self):
        """The 'absent' negative keyword triggers gaps."""
        text = "Metrics endpoint is absent from the charm."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_metrics"] is True

    def test_not_configured_keyword(self):
        """The 'not configured' negative keyword triggers gaps."""
        text = "Tracing is not configured."
        gaps = _infer_gaps_from_audit(text)
        assert gaps["cos_tracing"] is True


class TestPlanImprovementFixes:
    """Tests for plan_improvement_fixes task generation."""

    def _context(self) -> PlanningContext:
        return PlanningContext(
            intent="Improve the charm",
            charm_name="test-k8s",
            existing_charm_path="/tmp/test-charm",
        )

    def test_no_gaps_produces_no_tasks(self):
        """When all gaps are False, no fix tasks are generated."""
        gap_names = (
            "cos_tracing",
            "cos_metrics",
            "cos_logging",
            "cos_dashboards",
            "ops_tracing",
            "unit_tests",
            "integration_tests",
            "deprecated_apis",
            "readme",
            "licence",
            "listing_metadata",
            "type_annotations",
            "modern_patterns",
        )
        gaps = dict.fromkeys(gap_names, False)
        tasks = plan_improvement_fixes(self._context(), gaps)
        assert len(tasks) == 0

    def test_observability_gaps_create_fill_task(self):
        """Any COS gap creates a fill-observability task."""
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._context(), gaps)
        ids = [t.id for t in tasks]
        assert any(i.startswith("fill-observability-") for i in ids)

    def test_test_gaps_create_fill_task(self):
        """Test gaps create a fill-tests task."""
        gaps = {"unit_tests": True}
        tasks = plan_improvement_fixes(self._context(), gaps)
        ids = [t.id for t in tasks]
        assert any(i.startswith("fill-tests-") for i in ids)

    def test_deprecated_apis_create_modernise_task(self):
        """Deprecated APIs trigger a modernisation task."""
        gaps = {"deprecated_apis": True}
        tasks = plan_improvement_fixes(self._context(), gaps)
        ids = [t.id for t in tasks]
        assert any(i.startswith("modernise-code-") for i in ids)

    def test_fix_tasks_are_build_category(self):
        """The actual fix tasks are in the BUILD category."""
        gaps = {"cos_tracing": True, "unit_tests": True, "deprecated_apis": True}
        tasks = plan_improvement_fixes(self._context(), gaps)
        fix_prefixes = {
            "fill-observability-",
            "fill-tests-",
            "modernise-code-",
            "listing-readiness-",
        }
        fix_tasks = [t for t in tasks if any(t.id.startswith(p) for p in fix_prefixes)]
        assert len(fix_tasks) > 0
        for task in fix_tasks:
            assert task.category == TaskCategory.BUILD

    def test_validation_task_depends_on_fix_tasks(self):
        """A validation task is generated that depends on the fix tasks."""
        gaps = {"cos_tracing": True, "unit_tests": True}
        tasks = plan_improvement_fixes(self._context(), gaps)
        validation = next(
            (t for t in tasks if t.id.startswith("validate-improvements-")),
            None,
        )
        assert validation is not None
        assert any(d.startswith("fill-observability-") for d in validation.dependencies)
        assert any(d.startswith("fill-tests-") for d in validation.dependencies)

    def test_multiple_cos_gaps_collapsed_into_one_task(self):
        """Multiple COS gaps produce a single fill-observability task."""
        gaps = {
            "cos_tracing": True,
            "cos_metrics": True,
            "cos_logging": True,
            "cos_dashboards": True,
            "ops_tracing": True,
        }
        tasks = plan_improvement_fixes(self._context(), gaps)
        obs_tasks = [t for t in tasks if t.id.startswith("fill-observability-")]
        assert len(obs_tasks) == 1
        # The description should mention all gaps.
        assert "cos_tracing" in obs_tasks[0].description
