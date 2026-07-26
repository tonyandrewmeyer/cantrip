"""Planner tests: improvement."""

from cantrip.agent.planner import (
    PlanningContext,
    plan_improvement_fixes,
)
from cantrip.agent.queue import ModelHint, TaskCategory

# ===================================================================
# TestPlanImprovementFixes
# ===================================================================


class TestPlanImprovementFixes:
    """Tests for plan_improvement_fixes — conditional fix task generation."""

    def _ctx(self) -> PlanningContext:
        return PlanningContext(
            intent="improve",
            existing_charm_path="/tmp/charm",
            charm_name="my-charm",
        )

    def test_no_gaps_produces_no_tasks(self) -> None:
        gaps: dict[str, bool] = {}
        tasks = plan_improvement_fixes(self._ctx(), gaps)
        assert tasks == []

    def test_cos_gaps_produce_observability_task(self) -> None:
        gaps = {"cos_tracing": True, "cos_metrics": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        obs_tasks = [t for t in tasks if t.id.startswith("fill-observability-")]
        assert len(obs_tasks) == 1
        assert obs_tasks[0].category == TaskCategory.BUILD

    def test_test_gaps_produce_test_task(self) -> None:
        gaps = {"unit_tests": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        test_tasks = [t for t in tasks if t.id.startswith("fill-tests-")]
        assert len(test_tasks) == 1

    def test_deprecated_apis_produce_modernise_task(self) -> None:
        gaps = {"deprecated_apis": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        mod_tasks = [t for t in tasks if t.id.startswith("modernise-code-")]
        assert len(mod_tasks) == 1

    def test_listing_gaps_produce_listing_task(self) -> None:
        gaps = {"readme": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        listing_tasks = [t for t in tasks if t.id.startswith("listing-readiness-")]
        assert len(listing_tasks) == 1

    def test_icon_gap_produces_listing_task(self) -> None:
        gaps = {"icon": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        listing_tasks = [t for t in tasks if t.id.startswith("listing-readiness-")]
        assert len(listing_tasks) == 1
        assert "generate_icon" in listing_tasks[0].description

    def test_validation_task_depends_on_all_fixes(self) -> None:
        gaps = {"cos_tracing": True, "unit_tests": True, "deprecated_apis": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        validate = [t for t in tasks if t.id.startswith("validate-improvements-")]
        assert len(validate) == 1
        assert any(d.startswith("fill-observability-") for d in validate[0].dependencies)
        assert any(d.startswith("fill-tests-") for d in validate[0].dependencies)
        assert any(d.startswith("modernise-code-") for d in validate[0].dependencies)

    def test_fix_tasks_depend_on_confirm(self) -> None:
        confirm_id = "confirm-improvements-abc12345"
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps, confirm_task_id=confirm_id)

        obs = next(t for t in tasks if t.id.startswith("fill-observability-"))
        assert confirm_id in obs.dependencies

    def test_all_fix_tasks_use_primary_model(self) -> None:
        gaps = {
            "cos_tracing": True,
            "unit_tests": True,
            "deprecated_apis": True,
            "readme": True,
        }
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        build_tasks = [t for t in tasks if t.category == TaskCategory.BUILD]
        assert all(t.model_hint == ModelHint.PRIMARY for t in build_tasks)

    def test_deploy_verify_task_after_validation(self) -> None:
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        deploy = [t for t in tasks if t.id.startswith("deploy-verify-improvements-")]
        assert len(deploy) == 1
        assert deploy[0].category == TaskCategory.DEPLOY
        validate = [t for t in tasks if t.id.startswith("validate-improvements-")]
        assert validate[0].id in deploy[0].dependencies

    def test_diff_review_task_at_end(self) -> None:
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        review = [t for t in tasks if t.id.startswith("diff-review-")]
        assert len(review) == 1
        assert review[0].category == TaskCategory.RESEARCH
        deploy = [t for t in tasks if t.id.startswith("deploy-verify-improvements-")]
        assert deploy[0].id in review[0].dependencies

    def test_no_deploy_or_review_without_fixes(self) -> None:
        gaps: dict[str, bool] = {}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        assert not any(t.id.startswith("deploy-verify-improvements-") for t in tasks)
        assert not any(t.id.startswith("diff-review-") for t in tasks)

    def test_observability_description_mentions_dashboards(self) -> None:
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        obs = next(t for t in tasks if t.id.startswith("fill-observability-"))
        assert "Grafana dashboard" in obs.description
        assert "alert rules" in obs.description

    def test_test_fill_description_mentions_jubilant(self) -> None:
        gaps = {"integration_tests": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        test_task = next(t for t in tasks if t.id.startswith("fill-tests-"))
        assert "Jubilant" in test_task.description
        assert "run_charm_tests" in test_task.description

    def test_operability_assessment_after_deploy(self) -> None:
        gaps = {"cos_tracing": True}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        assess = [t for t in tasks if t.id.startswith("assess-operational-readiness-")]
        assert len(assess) == 1
        assert assess[0].category == TaskCategory.RESEARCH
        deploy = [t for t in tasks if t.id.startswith("deploy-verify-improvements-")]
        assert deploy[0].id in assess[0].dependencies

    def test_no_operability_without_fixes(self) -> None:
        gaps: dict[str, bool] = {}
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        assert not any(t.id.startswith("assess-operational-readiness-") for t in tasks)

    def test_full_pipeline_task_count(self) -> None:
        """With all gaps: 4 fixes + validate + deploy + review + assess = 8."""
        gaps = {
            "cos_tracing": True,
            "unit_tests": True,
            "deprecated_apis": True,
            "readme": True,
        }
        tasks = plan_improvement_fixes(self._ctx(), gaps)

        assert len(tasks) == 8
        ids = [t.id for t in tasks]
        assert any(i.startswith("fill-observability-") for i in ids)
        assert any(i.startswith("fill-tests-") for i in ids)
        assert any(i.startswith("modernise-code-") for i in ids)
        assert any(i.startswith("listing-readiness-") for i in ids)
        assert any(i.startswith("validate-improvements-") for i in ids)
        assert any(i.startswith("deploy-verify-improvements-") for i in ids)
        assert any(i.startswith("assess-operational-readiness-") for i in ids)
        assert any(i.startswith("diff-review-") for i in ids)
