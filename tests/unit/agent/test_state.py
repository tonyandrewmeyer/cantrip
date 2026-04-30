"""Tests for agent state data structures."""

from cantrip.agent.state import TestResults


class TestTestResultsFormatSummary:
    """Tests for TestResults.format_summary()."""

    def test_all_passed(self):
        """All tests passed shows tick icon."""
        tr = TestResults(test_type="unit", passed=5)
        assert tr.format_summary() == "✓ 5 passed"

    def test_all_failed(self):
        """All tests failed shows cross icon."""
        tr = TestResults(test_type="unit", failed=3)
        assert tr.format_summary() == "✗ 3 failed"

    def test_mixed_pass_fail(self):
        """Mixed results show failures first with cross icon."""
        tr = TestResults(test_type="unit", passed=3, failed=2)
        assert tr.format_summary() == "✗ 2 failed, 3 passed"

    def test_with_errors(self):
        """Errors show cross icon and appear after failures."""
        tr = TestResults(test_type="unit", passed=1, error=2)
        assert tr.format_summary() == "✗ 2 error, 1 passed"

    def test_with_skipped(self):
        """Skipped tests appear last."""
        tr = TestResults(test_type="unit", passed=5, skipped=2)
        assert tr.format_summary() == "✓ 5 passed, 2 skipped"

    def test_all_categories(self):
        """All categories present: failed, error, passed, skipped."""
        tr = TestResults(test_type="unit", passed=3, failed=1, error=1, skipped=2)
        assert tr.format_summary() == "✗ 1 failed, 1 error, 3 passed, 2 skipped"

    def test_empty_summary(self):
        """No counts produces an empty string."""
        tr = TestResults(test_type="unit")
        assert tr.format_summary() == ""

    def test_only_skipped(self):
        """Only skipped tests show tick icon."""
        tr = TestResults(test_type="unit", skipped=3)
        assert tr.format_summary() == "✓ 3 skipped"
