"""Tests for the auto-deploy loop follow-up logic."""

from cantrip.agent.autodeploy import (
    _ACCEPTANCE_FIX_PREFIX,
    _DEMO_TITLE_PREFIX,
    _OPENSTACK_ACCEPTANCE_TITLE,
    _RETRY_PREFIX,
    _VERIFY_PREFIX,
    _WATCHER_PREFIX,
    _extract_acceptance_failures,
    _extract_test_counts,
    followup_tasks,
    openstack_acceptance_task,
    task_for_watcher_event,
    tasks_after_acceptance,
    tasks_after_acceptance_failure,
    tasks_after_build,
    tasks_after_build_failure,
    tasks_after_deploy,
    tasks_after_test,
    tasks_after_verify,
)
from cantrip.agent.planner import OPERABILITY_PREFIX, SPRINT_BUILD_PREFIX
from cantrip.agent.queue import AgentTask, ModelHint, TaskCategory, TaskStatus
from cantrip.agent.state import AgentState
from cantrip.agent.subagent import _ACCEPTANCE_PREFIX
from cantrip.agent.watcher.watcher import WatcherEvent, format_event_for_agent

# ===================================================================
# TestTasksAfterBuild
# ===================================================================


class TestTasksAfterBuild:
    """Tests for tasks_after_build — auto-deploy after code changes."""

    def test_creates_deploy_for_successful_build(self) -> None:
        task = AgentTask(id="b1", title="Scaffold charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        result = tasks_after_build(task)

        assert len(result) == 1
        assert result[0].category == TaskCategory.DEPLOY
        assert "Scaffold charm" in result[0].title

    def test_no_deploy_for_failed_build(self) -> None:
        task = AgentTask(id="b1", title="Scaffold charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED

        assert tasks_after_build(task) == []

    def test_no_deploy_for_non_build(self) -> None:
        task = AgentTask(id="r1", title="Research Redis", category=TaskCategory.RESEARCH)
        task.status = TaskStatus.DONE

        assert tasks_after_build(task) == []

    def test_no_deploy_for_sprint_build(self) -> None:
        """Sprint builds already have an explicit deploy task — no follow-up needed."""
        task = AgentTask(
            id="sb1",
            title=f"{SPRINT_BUILD_PREFIX} my-app",
            category=TaskCategory.BUILD,
        )
        task.status = TaskStatus.DONE

        assert tasks_after_build(task) == []

    def test_deploy_depends_on_build(self) -> None:
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        result = tasks_after_build(task)

        assert result[0].dependencies == ["b1"]

    def test_no_deploy_for_pending_build(self) -> None:
        task = AgentTask(id="b1", title="Build", category=TaskCategory.BUILD)
        task.status = TaskStatus.PENDING

        assert tasks_after_build(task) == []


# ===================================================================
# TestTasksAfterDeploy
# ===================================================================


class TestTasksAfterDeploy:
    """Tests for tasks_after_deploy — verification task creation."""

    def test_creates_verify_for_successful_deploy(self) -> None:
        task = AgentTask(id="d1", title="Deploy myapp", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.DONE

        result = tasks_after_deploy(task)

        assert len(result) == 1
        assert result[0].title.startswith(_VERIFY_PREFIX)
        assert "Deploy myapp" in result[0].title

    def test_no_verify_for_failed_deploy(self) -> None:
        task = AgentTask(id="d1", title="Deploy myapp", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.FAILED

        assert tasks_after_deploy(task) == []

    def test_no_verify_for_non_deploy(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        assert tasks_after_deploy(task) == []

    def test_verify_depends_on_deploy(self) -> None:
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.DONE

        result = tasks_after_deploy(task)

        assert result[0].dependencies == ["d1"]

    def test_verify_has_deploy_category(self) -> None:
        task = AgentTask(id="d1", title="Deploy", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.DONE

        result = tasks_after_deploy(task)

        assert result[0].category == TaskCategory.DEPLOY


# ===================================================================
# TestTasksAfterVerify
# ===================================================================


class TestTasksAfterVerify:
    """Tests for tasks_after_verify — diagnostic task creation."""

    def test_debug_task_for_failed_verification(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy myapp",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED
        task.result = "Unit myapp/0 is in error state"

        result = tasks_after_verify(task)

        assert len(result) == 1
        assert "Diagnose" in result[0].title

    def test_no_debug_for_successful_verify(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy myapp",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.DONE

        assert tasks_after_verify(task) == []

    def test_no_debug_for_non_verify_task(self) -> None:
        task = AgentTask(id="d1", title="Deploy myapp", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.FAILED

        assert tasks_after_verify(task) == []

    def test_debug_includes_failure_result(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy myapp",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED
        task.result = "hook failed: install"

        result = tasks_after_verify(task)

        assert "hook failed: install" in result[0].description

    def test_debug_has_debug_category(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED

        result = tasks_after_verify(task)

        assert result[0].category == TaskCategory.DEBUG

    def test_debug_depends_on_verify(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED

        result = tasks_after_verify(task)

        assert result[0].dependencies == ["v1"]


# ===================================================================
# TestExtractTestCounts
# ===================================================================


class TestExtractTestCounts:
    """Tests for _extract_test_counts — pytest summary extraction."""

    def test_basic_pass_fail(self) -> None:
        text = "=== 3 passed, 2 failed in 1.5s ==="
        assert _extract_test_counts(text) == {"passed": 3, "failed": 2}

    def test_with_error_and_skipped(self) -> None:
        text = "stuff\n=== 1 passed, 2 failed, 1 error, 3 skipped ==="
        assert _extract_test_counts(text) == {
            "passed": 1,
            "failed": 2,
            "error": 1,
            "skipped": 3,
        }

    def test_no_matches(self) -> None:
        assert _extract_test_counts("no test output here") == {}

    def test_scattered_in_text(self) -> None:
        text = "Some output\n5 passed\nmore stuff\n2 failed\n"
        counts = _extract_test_counts(text)
        assert counts["passed"] == 5
        assert counts["failed"] == 2


# ===================================================================
# TestTasksAfterBuildFailure
# ===================================================================


class TestTasksAfterBuildFailure:
    """Tests for tasks_after_build_failure — red/green retry on partial progress."""

    def test_creates_retry_for_partial_test_progress(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "=== 3 passed, 4 failed in 5.2s ==="

        result = tasks_after_build_failure(task)

        assert len(result) == 1
        assert result[0].category == TaskCategory.BUILD
        assert result[0].title.startswith(_RETRY_PREFIX)
        assert "4 failing" in result[0].title

    def test_retry_uses_primary_model(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "=== 3 passed, 2 failed ==="

        result = tasks_after_build_failure(task)

        assert result[0].model_hint == ModelHint.PRIMARY

    def test_retry_depends_on_failed_task(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "=== 1 passed, 1 failed ==="

        result = tasks_after_build_failure(task)

        assert result[0].dependencies == ["b1"]

    def test_no_retry_when_all_tests_fail(self) -> None:
        """No partial progress — not worth a targeted retry."""
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "=== 5 failed ==="

        assert tasks_after_build_failure(task) == []

    def test_no_retry_for_successful_build(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE
        task.result = "=== 7 passed ==="

        assert tasks_after_build_failure(task) == []

    def test_no_retry_for_non_build(self) -> None:
        task = AgentTask(id="t1", title="Test charm", category=TaskCategory.TEST)
        task.status = TaskStatus.FAILED
        task.result = "=== 3 passed, 2 failed ==="

        assert tasks_after_build_failure(task) == []

    def test_no_retry_without_test_output(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "charmcraft pack failed with exit code 1"

        assert tasks_after_build_failure(task) == []

    def test_no_retry_for_existing_retry(self) -> None:
        """Prevents infinite retry chains."""
        task = AgentTask(
            id="b2",
            title=f"{_RETRY_PREFIX} fix 3 failing integration test(s)",
            category=TaskCategory.BUILD,
        )
        task.status = TaskStatus.FAILED
        task.result = "=== 5 passed, 1 failed ==="

        assert tasks_after_build_failure(task) == []

    def test_no_retry_with_no_result(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = None

        assert tasks_after_build_failure(task) == []

    def test_retry_description_includes_previous_result(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "FAILED test_deploy.py::test_ingress\n=== 2 passed, 1 failed ==="

        result = tasks_after_build_failure(task)

        assert "test_deploy" in result[0].description

    def test_retry_description_says_do_not_modify_tests(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "=== 1 passed, 1 failed ==="

        result = tasks_after_build_failure(task)

        assert "do NOT modify the integration tests" in result[0].description

    def test_error_counts_toward_failures(self) -> None:
        """Errors (not just 'failed') are counted as failures."""
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "=== 2 passed, 1 error ==="

        result = tasks_after_build_failure(task)

        assert len(result) == 1
        assert "1 failing" in result[0].title


# ===================================================================
# TestTasksAfterTest
# ===================================================================


class TestTasksAfterTest:
    """Tests for tasks_after_test — demo generation after successful tests."""

    def test_creates_acceptance_for_successful_test(self) -> None:
        task = AgentTask(id="t1", title="Validate charm", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE

        result = tasks_after_test(task)

        assert len(result) == 1
        assert result[0].category == TaskCategory.TEST
        assert result[0].title.startswith(_ACCEPTANCE_PREFIX)

    def test_demo_uses_primary_model(self) -> None:
        task = AgentTask(id="t1", title="Validate", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE

        result = tasks_after_test(task)

        assert result[0].model_hint == ModelHint.PRIMARY

    def test_demo_depends_on_test(self) -> None:
        task = AgentTask(id="t1", title="Validate", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE

        result = tasks_after_test(task)

        assert result[0].dependencies == ["t1"]

    def test_no_demo_for_failed_test(self) -> None:
        task = AgentTask(id="t1", title="Validate", category=TaskCategory.TEST)
        task.status = TaskStatus.FAILED

        assert tasks_after_test(task) == []

    def test_no_demo_for_non_test(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        assert tasks_after_test(task) == []

    def test_no_demo_for_demo_validation(self) -> None:
        """Prevent loops: a test task for demo artefacts should not spawn another demo."""
        task = AgentTask(
            id="t2",
            title=f"Validate {_DEMO_TITLE_PREFIX} artefacts",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE

        assert tasks_after_test(task) == []

    def test_acceptance_description_mentions_tools(self) -> None:
        task = AgentTask(id="t1", title="Validate", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE

        result = tasks_after_test(task)

        assert "action_exerciser" in result[0].description
        assert "relation_smoke_test" in result[0].description
        assert "acceptance_report" in result[0].description


# ===================================================================
# Phase 97.3 — OpenStack acceptance task
# ===================================================================


class TestOpenStackAcceptanceTask:
    """The OpenStack acceptance task fires alongside the base one when relevant."""

    def _done_test(self) -> AgentTask:
        task = AgentTask(id="t1", title="Validate charm", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE
        return task

    def test_creates_openstack_task_when_active_cloud_is_openstack(self) -> None:
        result = openstack_acceptance_task(self._done_test(), active_cloud="openstack")
        assert len(result) == 1
        assert result[0].title == _OPENSTACK_ACCEPTANCE_TITLE
        assert result[0].category == TaskCategory.TEST
        assert result[0].model_hint == ModelHint.PRIMARY
        assert result[0].dependencies == ["t1"]

    def test_sunbeam_cloud_also_triggers_the_task(self) -> None:
        result = openstack_acceptance_task(self._done_test(), active_cloud="sunbeam")
        assert len(result) == 1

    def test_cloud_match_is_case_insensitive(self) -> None:
        result = openstack_acceptance_task(self._done_test(), active_cloud="OpenStack")
        assert len(result) == 1

    def test_no_task_when_cloud_is_other(self) -> None:
        assert openstack_acceptance_task(self._done_test(), active_cloud="localhost") == []
        assert openstack_acceptance_task(self._done_test(), active_cloud="microk8s") == []

    def test_no_task_when_cloud_is_unknown(self) -> None:
        assert openstack_acceptance_task(self._done_test(), active_cloud="") == []

    def test_no_task_for_failed_test(self) -> None:
        task = self._done_test()
        task.status = TaskStatus.FAILED
        assert openstack_acceptance_task(task, active_cloud="openstack") == []

    def test_no_task_for_non_test_category(self) -> None:
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE
        assert openstack_acceptance_task(task, active_cloud="openstack") == []

    def test_no_chain_off_acceptance_task(self) -> None:
        """Prevent runaway — an already-acceptance task doesn't spawn another."""
        task = AgentTask(
            id="a1",
            title=f"{_ACCEPTANCE_PREFIX} put the charm through its paces",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE
        assert openstack_acceptance_task(task, active_cloud="openstack") == []

    def test_no_chain_off_demo_task(self) -> None:
        task = AgentTask(
            id="d1",
            title=f"Validate {_DEMO_TITLE_PREFIX} artefacts",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE
        assert openstack_acceptance_task(task, active_cloud="openstack") == []

    def test_description_names_az_loss_and_volume_detach(self) -> None:
        result = openstack_acceptance_task(self._done_test(), active_cloud="openstack")
        assert "AZ loss" in result[0].description
        assert "Volume detach" in result[0].description or "volume detach" in result[0].description


# ===================================================================
# TestTasksAfterAcceptance
# ===================================================================


class TestTasksAfterAcceptance:
    """Tests for tasks_after_acceptance — demo + operability after acceptance."""

    def _make_acceptance_task(self) -> AgentTask:
        task = AgentTask(
            id="a1",
            title=f"{_ACCEPTANCE_PREFIX} put the charm through its paces",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE
        return task

    def test_creates_demo_and_operability_tasks(self) -> None:
        task = self._make_acceptance_task()
        result = tasks_after_acceptance(task)

        assert len(result) == 2
        titles = [t.title for t in result]
        assert any(_DEMO_TITLE_PREFIX in t for t in titles)
        assert any(OPERABILITY_PREFIX in t for t in titles)

    def test_both_depend_on_acceptance(self) -> None:
        task = self._make_acceptance_task()
        result = tasks_after_acceptance(task)

        for t in result:
            assert t.dependencies == ["a1"]

    def test_operability_is_research(self) -> None:
        task = self._make_acceptance_task()
        result = tasks_after_acceptance(task)

        operability = [t for t in result if OPERABILITY_PREFIX in t.title]
        assert operability[0].category == TaskCategory.RESEARCH

    def test_no_tasks_for_failed_acceptance(self) -> None:
        task = self._make_acceptance_task()
        task.status = TaskStatus.FAILED
        assert tasks_after_acceptance(task) == []

    def test_no_tasks_for_non_acceptance_test(self) -> None:
        task = AgentTask(id="t1", title="Validate charm", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE
        assert tasks_after_acceptance(task) == []


# ===================================================================
# TestFollowupTasks
# ===================================================================


class TestFollowupTasks:
    """Tests for followup_tasks — unified dispatch."""

    def test_dispatches_to_deploy_handler(self) -> None:
        task = AgentTask(id="d1", title="Deploy app", category=TaskCategory.DEPLOY)
        task.status = TaskStatus.DONE

        result = followup_tasks(task)

        assert len(result) == 1
        assert result[0].title.startswith(_VERIFY_PREFIX)

    def test_dispatches_to_verify_handler(self) -> None:
        task = AgentTask(
            id="v1",
            title=f"{_VERIFY_PREFIX} Deploy app",
            category=TaskCategory.DEPLOY,
        )
        task.status = TaskStatus.FAILED

        result = followup_tasks(task)

        assert len(result) == 1
        assert "Diagnose" in result[0].title

    def test_dispatches_to_build_handler(self) -> None:
        task = AgentTask(id="b1", title="Scaffold charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.DONE

        result = followup_tasks(task)

        assert len(result) == 1
        assert result[0].category == TaskCategory.DEPLOY

    def test_empty_for_non_deploy(self) -> None:
        task = AgentTask(id="r1", title="Research Redis", category=TaskCategory.RESEARCH)
        task.status = TaskStatus.DONE

        assert followup_tasks(task) == []

    def test_empty_for_debug_task(self) -> None:
        """DEBUG tasks produce no further follow-ups — chain is bounded."""
        task = AgentTask(id="dbg1", title="Diagnose failure", category=TaskCategory.DEBUG)
        task.status = TaskStatus.DONE

        assert followup_tasks(task) == []

    def test_dispatches_to_build_failure_handler(self) -> None:
        """Failed BUILD with partial test progress gets a retry, not DEBUG."""
        task = AgentTask(id="b1", title="Build charm", category=TaskCategory.BUILD)
        task.status = TaskStatus.FAILED
        task.result = "=== 3 passed, 2 failed ==="

        result = followup_tasks(task)

        assert len(result) == 1
        assert result[0].category == TaskCategory.BUILD
        assert result[0].title.startswith(_RETRY_PREFIX)

    def test_dispatches_to_test_handler(self) -> None:
        """Successful TEST gets an acceptance test follow-up."""
        task = AgentTask(id="t1", title="Validate charm", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE

        result = followup_tasks(task)

        assert any(t.title.startswith(_ACCEPTANCE_PREFIX) for t in result)

    def test_dispatches_to_acceptance_failure_handler(self) -> None:
        """Acceptance with failures gets a fix task."""
        task = AgentTask(
            id="a1",
            title=f"{_ACCEPTANCE_PREFIX} put the charm through its paces",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE
        task.result = "Actions: PASS (3/3)\nRelations: FAIL — mysql endpoint broken"

        result = followup_tasks(task)

        assert any(t.title.startswith(_ACCEPTANCE_FIX_PREFIX) for t in result)


# ===================================================================
# TestExtractAcceptanceFailures
# ===================================================================


class TestExtractAcceptanceFailures:
    """Tests for _extract_acceptance_failures — acceptance verdict extraction."""

    def test_fail_with_area(self) -> None:
        text = "Actions: FAIL (1/3) — backup action returned error"
        result = _extract_acceptance_failures(text)
        assert "actions" in result

    def test_multiple_failures(self) -> None:
        text = (
            "Actions: PASS (3/3)\n"
            "Relations: FAIL (1/2) — mysql endpoint timed out\n"
            "Endpoints: PASS (1/1)\n"
            "Config: FAIL (2/5) — log-level and port had no effect\n"
            "Scaling: PASS"
        )
        result = _extract_acceptance_failures(text)
        assert "relations" in result
        assert "config options" in result
        assert "actions" not in result
        assert "endpoints" not in result
        assert "scaling" not in result

    def test_no_failures(self) -> None:
        text = "Actions: PASS\nRelations: PASS\nEndpoints: PASS"
        assert _extract_acceptance_failures(text) == []

    def test_prose_failure_mentions(self) -> None:
        text = "The relation smoke test failed for the mysql endpoint."
        result = _extract_acceptance_failures(text)
        assert "relations" in result

    def test_verdict_fail_pattern(self) -> None:
        text = "verdict: fail for action exerciser, 2 actions broken"
        result = _extract_acceptance_failures(text)
        assert "actions" in result

    def test_deduplicates_areas(self) -> None:
        text = "Actions: FAIL — broken\nThe action exerciser also failed on backup action"
        result = _extract_acceptance_failures(text)
        assert result.count("actions") == 1

    def test_empty_text(self) -> None:
        assert _extract_acceptance_failures("") == []

    def test_endpoint_failure(self) -> None:
        text = "Endpoint checks failed: HTTP 503 on port 8080"
        result = _extract_acceptance_failures(text)
        assert "endpoints" in result

    def test_scaling_failure(self) -> None:
        text = "Scaling test: FAIL — peer relation broken after scale-up"
        result = _extract_acceptance_failures(text)
        assert "scaling" in result

    def test_lifecycle_failure(self) -> None:
        text = "Lifecycle: FAIL — charm did not recover after restart"
        result = _extract_acceptance_failures(text)
        assert "lifecycle" in result

    def test_word_boundary_rejects_actionable(self) -> None:
        """``actionable`` must not be mistaken for ``action``.

        Regression guard for the previous ``\\S*`` suffix that would
        greedily glue the keyword onto any longer word.
        """
        text = "The workflow is actionable and failed to complete"
        assert _extract_acceptance_failures(text) == []

    def test_word_boundary_rejects_relationship(self) -> None:
        """``relationship`` is not a ``relation`` keyword match."""
        text = "The relationship between the components failed."
        assert _extract_acceptance_failures(text) == []

    def test_prose_error_alone_is_no_longer_enough(self) -> None:
        """Bare ``error`` near a keyword no longer counts as a failure.

        Previously ``error`` was part of the prose alternation, which
        flagged harmless text like ``action executed without error``.
        """
        text = "Actions: PASS (1/1) — action executed without error"
        assert _extract_acceptance_failures(text) == []

    def test_negation_in_prose_is_rejected(self) -> None:
        """``no failures observed`` near ``actions`` does not flag actions."""
        text = "Actions completed normally: no failures observed."
        assert _extract_acceptance_failures(text) == []

    def test_negation_with_contraction(self) -> None:
        """``didn't fail`` near a keyword also disqualifies the match."""
        text = "The relation smoke test didn't fail after the fix."
        assert _extract_acceptance_failures(text) == []

    def test_never_failed_is_rejected(self) -> None:
        """``never failed`` is a negated prose phrase; no area flagged."""
        text = "Scaling never failed in any of the trials."
        assert _extract_acceptance_failures(text) == []

    def test_partial_negation_then_real_failure_on_separate_lines(self) -> None:
        """Negation on one line does not mask a failure on another."""
        text = "Endpoints: no failures observed.\nActions: FAIL — backup broken"
        result = _extract_acceptance_failures(text)
        assert "actions" in result
        assert "endpoints" not in result

    def test_plural_area_keyword(self) -> None:
        """Plural ``actions`` / ``relations`` match the verdict pattern."""
        text = "actions: FAIL — one action returned non-zero"
        result = _extract_acceptance_failures(text)
        assert "actions" in result


# ===================================================================
# TestTasksAfterAcceptanceFailure
# ===================================================================


class TestTasksAfterAcceptanceFailure:
    """Tests for tasks_after_acceptance_failure — fix tasks for acceptance issues."""

    def _make_acceptance_task(
        self, result: str | None = None, status: TaskStatus = TaskStatus.DONE
    ) -> AgentTask:
        task = AgentTask(
            id="a1",
            title=f"{_ACCEPTANCE_PREFIX} put the charm through its paces",
            category=TaskCategory.TEST,
        )
        task.status = status
        task.result = result
        return task

    def test_creates_fix_for_acceptance_failures(self) -> None:
        task = self._make_acceptance_task("Actions: FAIL — backup broken\nRelations: PASS")

        result = tasks_after_acceptance_failure(task)

        assert len(result) == 1
        assert result[0].category == TaskCategory.BUILD
        assert result[0].title.startswith(_ACCEPTANCE_FIX_PREFIX)
        assert "1 acceptance failure" in result[0].title

    def test_fix_uses_primary_model(self) -> None:
        task = self._make_acceptance_task("Config: FAIL — port ignored")

        result = tasks_after_acceptance_failure(task)

        assert result[0].model_hint == ModelHint.PRIMARY

    def test_fix_depends_on_acceptance_task(self) -> None:
        task = self._make_acceptance_task("Config: FAIL — port ignored")

        result = tasks_after_acceptance_failure(task)

        assert result[0].dependencies == ["a1"]

    def test_fix_description_includes_failure_areas(self) -> None:
        task = self._make_acceptance_task(
            "Relations: FAIL — mysql broken\nEndpoints: FAIL — HTTP 503"
        )

        result = tasks_after_acceptance_failure(task)

        assert "relations" in result[0].description
        assert "endpoints" in result[0].description

    def test_fix_description_includes_acceptance_result(self) -> None:
        task = self._make_acceptance_task("Actions: FAIL — backup action returned error")

        result = tasks_after_acceptance_failure(task)

        assert "backup action" in result[0].description

    def test_no_fix_when_all_pass(self) -> None:
        task = self._make_acceptance_task(
            "Actions: PASS (3/3)\nRelations: PASS (2/2)\nEndpoints: PASS"
        )

        assert tasks_after_acceptance_failure(task) == []

    def test_no_fix_for_failed_acceptance_task(self) -> None:
        """If the acceptance task itself failed (crashed), don't create a fix."""
        task = self._make_acceptance_task("Actions: FAIL — broken", status=TaskStatus.FAILED)

        assert tasks_after_acceptance_failure(task) == []

    def test_no_fix_for_non_acceptance_test(self) -> None:
        task = AgentTask(id="t1", title="Validate charm", category=TaskCategory.TEST)
        task.status = TaskStatus.DONE
        task.result = "Actions: FAIL — broken"

        assert tasks_after_acceptance_failure(task) == []

    def test_no_fix_for_non_test_category(self) -> None:
        task = AgentTask(
            id="b1",
            title=f"{_ACCEPTANCE_PREFIX} something",
            category=TaskCategory.BUILD,
        )
        task.status = TaskStatus.DONE
        task.result = "Actions: FAIL — broken"

        assert tasks_after_acceptance_failure(task) == []

    def test_no_fix_without_result(self) -> None:
        task = self._make_acceptance_task(result=None)

        assert tasks_after_acceptance_failure(task) == []

    def test_no_fix_for_existing_fix(self) -> None:
        """Prevents infinite fix chains."""
        task = AgentTask(
            id="a2",
            title=(f"{_ACCEPTANCE_PREFIX} {_ACCEPTANCE_FIX_PREFIX} re-run acceptance"),
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE
        task.result = "Actions: FAIL — still broken"

        assert tasks_after_acceptance_failure(task) == []

    def test_multiple_failure_areas_in_title(self) -> None:
        task = self._make_acceptance_task(
            "Actions: FAIL — broken\nRelations: FAIL — timeout\nConfig: FAIL — ignored"
        )

        result = tasks_after_acceptance_failure(task)

        assert "3 acceptance failure" in result[0].title


# ===================================================================
# TestTaskForWatcherEvent
# ===================================================================


class TestTaskForWatcherEvent:
    """Tests for task_for_watcher_event — watcher event conversion."""

    def _make_state(self, dev_model: str | None = "dev") -> AgentState:
        return AgentState(dev_model=dev_model)

    def test_hook_failure_creates_debug_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.DEBUG

    def test_status_change_creates_debug_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="status_change",
            summary="myapp/0: active -> blocked",
            detail="Unit changed status",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.DEBUG

    def test_log_error_creates_debug_task(self) -> None:
        event = WatcherEvent(
            source="loki",
            category="log_error",
            summary="Log error in myapp",
            detail="Traceback...",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.DEBUG

    def test_new_app_creates_infra_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="new_app",
            summary="New application: redis",
            detail="Application appeared",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.INFRA

    def test_new_relation_creates_infra_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="new_relation",
            summary="New relation: myapp:db-postgres",
            detail="Relation added",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.INFRA

    def test_removed_app_creates_infra_task(self) -> None:
        event = WatcherEvent(
            source="status",
            category="removed_app",
            summary="Application removed: old-app",
            detail="Application gone",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.category == TaskCategory.INFRA

    def test_none_without_dev_model(self) -> None:
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure",
            detail="boom",
        )
        result = task_for_watcher_event(event, self._make_state(dev_model=None))

        assert result is None

    def test_none_for_unknown_category(self) -> None:
        event = WatcherEvent(
            source="status",
            category="unknown_thing",
            summary="Something",
            detail="Details",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is None

    def test_title_prefixed_with_watcher(self) -> None:
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        assert result.title.startswith(_WATCHER_PREFIX)

    def test_description_uses_format_event(self) -> None:
        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="Hook failure on myapp/0",
            detail="hook failed: install",
            app="myapp",
            unit="myapp/0",
        )
        result = task_for_watcher_event(event, self._make_state())

        assert result is not None
        expected = format_event_for_agent(event)
        assert result.description == expected
