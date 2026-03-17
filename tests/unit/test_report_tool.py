"""Tests for the test report aggregation tool."""

from cantrip.agent.tools.report import _format_test_report


class TestFormatTestReport:
    """Tests for _format_test_report."""

    def test_all_passing(self) -> None:
        unit = {"success": True, "summary": {"passed": 5}, "output": ""}
        integration = {"success": True, "summary": {"passed": 3}, "output": ""}
        report = _format_test_report(unit, integration, "my-charm")
        assert "PASS" in report
        assert "8 tests passed" in report

    def test_failures(self) -> None:
        unit = {
            "success": False,
            "summary": {"passed": 3, "failed": 2},
            "output": "FAILED test_foo",
        }
        integration = {"success": None, "summary": {}, "output": ""}
        report = _format_test_report(unit, integration, "my-charm")
        assert "FAIL" in report
        assert "2 failures" in report

    def test_no_tests_available(self) -> None:
        unit = {"success": None, "summary": {}, "output": ""}
        integration = {"success": None, "summary": {}, "output": ""}
        report = _format_test_report(unit, integration, "my-charm")
        assert "No test suites" in report

    def test_contains_charm_name(self) -> None:
        unit = {"success": True, "summary": {"passed": 1}, "output": ""}
        integration = {"success": None, "summary": {}, "output": ""}
        report = _format_test_report(unit, integration, "redis-k8s")
        assert "redis-k8s" in report

    def test_failure_output_included(self) -> None:
        unit = {
            "success": False,
            "summary": {"failed": 1},
            "output": "AssertionError: expected active",
        }
        integration = {"success": None, "summary": {}, "output": ""}
        report = _format_test_report(unit, integration, "test")
        assert "AssertionError" in report
