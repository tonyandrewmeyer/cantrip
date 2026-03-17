"""Tests for the hook benchmark tool."""

from cantrip.agent.tools.benchmark import (
    _format_benchmark_report,
    _parse_hook_timings,
)


class TestParseHookTimings:
    """Tests for _parse_hook_timings."""

    def test_parses_ran_hook_format(self) -> None:
        log = 'unit-myapp-0: 12:00:00 DEBUG juju.worker.uniter.operation ran "install" hook (150ms)'
        timings = _parse_hook_timings(log)
        assert len(timings) == 1
        assert timings[0]["hook"] == "install"
        assert timings[0]["duration_ms"] == 150.0
        assert timings[0]["unit"] == "myapp-0"

    def test_parses_multiple_hooks(self) -> None:
        log = (
            'unit-myapp-0: 12:00:00 DEBUG juju ran "install" hook (100ms)\n'
            'unit-myapp-0: 12:00:01 DEBUG juju ran "config-changed" hook (200ms)\n'
            'unit-myapp-0: 12:00:02 DEBUG juju ran "start" hook (50ms)\n'
        )
        timings = _parse_hook_timings(log)
        assert len(timings) == 3

    def test_empty_log(self) -> None:
        assert _parse_hook_timings("") == []

    def test_no_hook_lines(self) -> None:
        log = "unit-myapp-0: 12:00:00 INFO some other log line\n"
        assert _parse_hook_timings(log) == []

    def test_deduplicates_identical_lines(self) -> None:
        line = 'unit-myapp-0: 12:00:00 DEBUG juju ran "install" hook (100ms)'
        log = f"{line}\n{line}\n"
        timings = _parse_hook_timings(log)
        assert len(timings) == 1


class TestFormatBenchmarkReport:
    """Tests for _format_benchmark_report."""

    def test_empty_timings(self) -> None:
        report = _format_benchmark_report([], 5000)
        assert "No hook execution timings" in report

    def test_report_contains_summary_table(self) -> None:
        timings = [
            {"unit": "myapp-0", "hook": "install", "duration_ms": 100.0},
            {"unit": "myapp-0", "hook": "install", "duration_ms": 200.0},
        ]
        report = _format_benchmark_report(timings, 5000)
        assert "| install |" in report
        assert "| 2 |" in report

    def test_flags_slow_hooks(self) -> None:
        timings = [
            {"unit": "myapp-0", "hook": "install", "duration_ms": 10000.0},
        ]
        report = _format_benchmark_report(timings, 5000)
        assert "Slow Hooks" in report
        assert "install" in report

    def test_no_slow_hooks_message(self) -> None:
        timings = [
            {"unit": "myapp-0", "hook": "install", "duration_ms": 100.0},
        ]
        report = _format_benchmark_report(timings, 5000)
        assert "All hooks executed within" in report
