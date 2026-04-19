"""Planner tests: operability."""

from cantrip.agent.planner import (
    OPERABILITY_PREFIX,
    PlanningContext,
    plan_operability_assessment,
    plan_operability_fixes,
)
from cantrip.agent.queue import ModelHint, TaskCategory

# ===================================================================
# TestPlanOperabilityAssessment
# ===================================================================


class TestPlanOperabilityAssessment:
    """Tests for plan_operability_assessment."""

    def _ctx(self) -> PlanningContext:
        return PlanningContext(
            intent="Assess operational readiness",
            charm_name="my-charm",
            existing_charm_path="/charms/my-charm",
        )

    def test_creates_assessment_and_confirm_tasks(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert len(tasks) == 2
        assert tasks[0].category == TaskCategory.RESEARCH
        assert tasks[1].category == TaskCategory.CONFIRM

    def test_assessment_title_has_prefix(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert tasks[0].title.startswith(OPERABILITY_PREFIX)

    def test_confirm_depends_on_assessment(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert tasks[1].dependencies == [tasks[0].id]

    def test_depends_on_parameter(self) -> None:
        tasks = plan_operability_assessment(self._ctx(), depends_on="acceptance-1")
        assert tasks[0].dependencies == ["acceptance-1"]

    def test_no_depends_on(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert tasks[0].dependencies == []

    def test_description_mentions_tool(self) -> None:
        tasks = plan_operability_assessment(self._ctx())
        assert "operational_readiness" in tasks[0].description


# ===================================================================
# TestPlanOperabilityFixes
# ===================================================================


class TestPlanOperabilityFixes:
    """Tests for plan_operability_fixes."""

    def _ctx(self) -> PlanningContext:
        return PlanningContext(
            intent="Fix operability gaps",
            charm_name="my-charm",
            existing_charm_path="/charms/my-charm",
        )

    def test_generates_status_task(self) -> None:
        findings = {
            "must_fix": ["[Best Practices] Sets status for missing config"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        titles = [t.title for t in tasks]
        assert any("status" in t.lower() for t in titles)

    def test_generates_action_task(self) -> None:
        findings = {
            "must_fix": ["[Reliability] Health validation mechanism exists"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        titles = [t.title for t in tasks]
        assert any("action" in t.lower() for t in titles)

    def test_generates_backup_task(self) -> None:
        findings = {"must_fix": [], "should_fix": ["[Reliability] Backup action exists"]}
        tasks = plan_operability_fixes(self._ctx(), findings)
        titles = [t.title for t in tasks]
        assert any("backup" in t.lower() for t in titles)

    def test_generates_security_task(self) -> None:
        findings = {
            "must_fix": ["[Security] Data encryption in transit (TLS)"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        titles = [t.title for t in tasks]
        assert any("security" in t.lower() for t in titles)

    def test_generates_reassessment_task(self) -> None:
        findings = {
            "must_fix": ["[Best Practices] Sets status for missing config"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        assert any("re-assess" in t.title.lower() for t in tasks)

    def test_reassessment_depends_on_all_fixes(self) -> None:
        findings = {
            "must_fix": [
                "[Best Practices] Sets status for missing config",
                "[Reliability] Health validation mechanism exists",
            ],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        reassess = [t for t in tasks if "re-assess" in t.title.lower()]
        assert len(reassess) == 1
        # Should depend on all fix task IDs.
        fix_ids = [t.id for t in tasks if t.id != reassess[0].id]
        assert set(reassess[0].dependencies) == set(fix_ids)

    def test_no_tasks_for_empty_findings(self) -> None:
        findings = {"must_fix": [], "should_fix": []}
        tasks = plan_operability_fixes(self._ctx(), findings)
        assert tasks == []

    def test_fix_tasks_depend_on_confirm(self) -> None:
        confirm_id = "confirm-operability-abc12345"
        findings = {
            "must_fix": ["[Best Practices] Sets status for missing config"],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(
            self._ctx(),
            findings,
            confirm_task_id=confirm_id,
        )
        fix_tasks = [t for t in tasks if "re-assess" not in t.title.lower()]
        for t in fix_tasks:
            assert confirm_id in t.dependencies

    def test_all_fix_tasks_use_primary_model(self) -> None:
        findings = {
            "must_fix": [
                "[Best Practices] Sets status for missing config",
                "[Reliability] Backup action exists",
            ],
            "should_fix": [],
        }
        tasks = plan_operability_fixes(self._ctx(), findings)
        for t in tasks:
            assert t.model_hint == ModelHint.PRIMARY
