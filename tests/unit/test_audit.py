"""Tests for the Phase 80.4 JSONL audit trail."""

from __future__ import annotations

import json
import pathlib

from cantrip.agent.audit import (
    AUDIT_FILENAME,
    AuditAction,
    AuditEntry,
    AuditWriter,
    filter_entries,
    make_entry,
    read_entries,
    scrub_arguments,
)


class TestAuditEntry:
    """Round-trip and field coverage for the dataclass."""

    def test_to_json_and_from_dict_round_trip(self) -> None:
        entry = AuditEntry(
            timestamp="2026-01-01T00:00:00+00:00",
            task_id="task-42",
            tool="juju_status",
            action=AuditAction.ALLOWED,
            policy_name="org-wide+category:build",
            reason="",
            arguments={"model": "dev"},
        )
        line = entry.to_json()
        restored = AuditEntry.from_dict(json.loads(line))
        assert restored == entry

    def test_to_json_emits_single_line(self) -> None:
        entry = AuditEntry(
            timestamp="t",
            task_id=None,
            tool="read_file",
            action=AuditAction.DENIED,
            policy_name="p",
            reason="blocked",
        )
        line = entry.to_json()
        assert "\n" not in line

    def test_action_values_are_human_readable(self) -> None:
        """The string values match the Phase 80 spec so ``grep`` works."""
        assert AuditAction.ALLOWED.value == "allowed"
        assert AuditAction.DENIED.value == "denied"
        assert AuditAction.REVIEW_REQUESTED.value == "review-requested"
        assert AuditAction.RATE_LIMITED.value == "rate-limited"


class TestScrubArguments:
    """Phase 50.2 sanitiser reuse — secrets never reach the audit file."""

    def test_github_token_scrubbed(self) -> None:
        scrubbed = scrub_arguments({"url": "https://api.github.com/?token=ghp_" + "x" * 40})
        assert "ghp_" not in scrubbed["url"]
        assert "[REDACTED]" in scrubbed["url"]

    def test_password_scrubbed(self) -> None:
        scrubbed = scrub_arguments({"config": "password=s3cret-value"})
        assert "s3cret-value" not in scrubbed["config"]
        assert "[REDACTED]" in scrubbed["config"]

    def test_non_string_values_pass_through(self) -> None:
        scrubbed = scrub_arguments({"count": 42, "flag": True, "items": ["a", "b"]})
        assert scrubbed == {"count": 42, "flag": True, "items": ["a", "b"]}

    def test_charm_path_scrubbed(self, tmp_path: pathlib.Path) -> None:
        scrubbed = scrub_arguments(
            {"path": str(tmp_path / "src/charm.py")},
            charm_path=tmp_path,
        )
        assert str(tmp_path) not in scrubbed["path"]

    def test_nested_dict_secret_scrubbed(self) -> None:
        """``juju_config(values={...})`` and similar shapes must redact recursively."""
        scrubbed = scrub_arguments(
            {"app_name": "foo", "values": {"db-password": "password=supersecret"}}
        )
        assert "supersecret" not in scrubbed["values"]["db-password"]
        assert "[REDACTED]" in scrubbed["values"]["db-password"]

    def test_list_of_strings_scrubbed(self) -> None:
        """An argv carrying a token (``run_command(command=[...])``) must redact."""
        token = "ghp_" + "x" * 40
        scrubbed = scrub_arguments(
            {"cmd": ["gh", "auth", "login", "--with-token", token]},
        )
        assert token not in " ".join(scrubbed["cmd"])
        assert any("[REDACTED]" in arg for arg in scrubbed["cmd"])

    def test_recursion_preserves_non_secret_strings(self) -> None:
        """Recursion must not corrupt benign nested data."""
        scrubbed = scrub_arguments(
            {"items": ["a", "b"], "nested": {"k": "v"}, "n": 42, "flag": True},
        )
        assert scrubbed == {
            "items": ["a", "b"],
            "nested": {"k": "v"},
            "n": 42,
            "flag": True,
        }


class TestMakeEntry:
    """``make_entry`` scrubs and stamps in one call."""

    def test_scrubs_arguments(self) -> None:
        entry = make_entry(
            tool="run_command",
            action=AuditAction.ALLOWED,
            policy_name="org-wide",
            reason="",
            arguments={"command": "echo password=topsecret"},
        )
        assert "topsecret" not in entry.arguments["command"]
        assert "[REDACTED]" in entry.arguments["command"]

    def test_timestamp_is_iso_utc(self) -> None:
        entry = make_entry(
            tool="read_file",
            action=AuditAction.ALLOWED,
            policy_name="org-wide",
            reason="",
        )
        assert "T" in entry.timestamp  # ISO-8601 marker.
        # datetime.isoformat for a UTC-aware datetime ends in "+00:00".
        assert entry.timestamp.endswith("+00:00")


class TestAuditWriter:
    """``AuditWriter`` appends one line per call and tolerates concurrent writes."""

    def test_write_appends_a_line_per_entry(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / AUDIT_FILENAME
        writer = AuditWriter(path)
        writer.write(
            make_entry(
                tool="juju_status",
                action=AuditAction.ALLOWED,
                policy_name="p",
                reason="",
                arguments={},
            )
        )
        writer.write(
            make_entry(
                tool="juju_destroy_model",
                action=AuditAction.DENIED,
                policy_name="p",
                reason="blocked",
                arguments={"model": "dev"},
            )
        )

        lines = path.read_text().splitlines()
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert "timestamp" in parsed
            assert "tool" in parsed

    def test_concurrent_writers_do_not_interleave(self, tmp_path: pathlib.Path) -> None:
        """Two threads writing long entries still produce valid JSON lines.

        This is the whole reason ``AuditWriter`` holds a lock — without
        it, the two ``handle.write`` halves of one call could
        interleave with another and corrupt the file.
        """
        import threading

        path = tmp_path / AUDIT_FILENAME
        writer = AuditWriter(path)

        def _burst(tool: str) -> None:
            for _ in range(50):
                writer.write(
                    make_entry(
                        tool=tool,
                        action=AuditAction.ALLOWED,
                        policy_name="p",
                        reason="x" * 200,
                        arguments={"blob": "y" * 200},
                    )
                )

        t1 = threading.Thread(target=_burst, args=("juju_status",))
        t2 = threading.Thread(target=_burst, args=("read_file",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        lines = path.read_text().splitlines()
        assert len(lines) == 100
        # Every line parses independently.
        for line in lines:
            json.loads(line)


class TestReadEntries:
    """Read-side helper for the CLI subcommand."""

    def test_reads_back_written_entries(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / AUDIT_FILENAME
        writer = AuditWriter(path)
        for tool in ("a", "b", "c"):
            writer.write(
                make_entry(
                    tool=tool,
                    action=AuditAction.ALLOWED,
                    policy_name="p",
                    reason="",
                )
            )
        entries = list(read_entries(path))
        assert [e.tool for e in entries] == ["a", "b", "c"]

    def test_missing_file_returns_empty_iterator(self, tmp_path: pathlib.Path) -> None:
        entries = list(read_entries(tmp_path / "no-such-file.jsonl"))
        assert entries == []

    def test_malformed_line_is_skipped(self, tmp_path: pathlib.Path, caplog) -> None:
        """A corrupt line logs a warning and the good lines still come through."""
        import logging

        path = tmp_path / AUDIT_FILENAME
        writer = AuditWriter(path)
        writer.write(make_entry(tool="a", action=AuditAction.ALLOWED, policy_name="p", reason=""))
        # Hand-append a broken line.
        with path.open("a") as handle:
            handle.write("{this is not json}\n")
        writer.write(make_entry(tool="b", action=AuditAction.ALLOWED, policy_name="p", reason=""))

        with caplog.at_level(logging.WARNING, logger="cantrip.agent.audit"):
            entries = list(read_entries(path))

        assert [e.tool for e in entries] == ["a", "b"]
        assert any("malformed" in rec.getMessage().lower() for rec in caplog.records)

    def test_blank_lines_ignored(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / AUDIT_FILENAME
        writer = AuditWriter(path)
        writer.write(
            make_entry(tool="only", action=AuditAction.ALLOWED, policy_name="p", reason="")
        )
        with path.open("a") as handle:
            handle.write("\n\n   \n")
        entries = list(read_entries(path))
        assert [e.tool for e in entries] == ["only"]


class TestFilterEntries:
    """CLI filter chain: task, action, tool."""

    def _make(self, *, tool: str, action: AuditAction, task_id: str | None = None) -> AuditEntry:
        return AuditEntry(
            timestamp="t",
            task_id=task_id,
            tool=tool,
            action=action,
            policy_name="p",
            reason="",
        )

    def test_filter_by_action_string(self) -> None:
        entries = [
            self._make(tool="a", action=AuditAction.ALLOWED),
            self._make(tool="b", action=AuditAction.DENIED),
        ]
        filtered = list(filter_entries(entries, action="denied"))
        assert [e.tool for e in filtered] == ["b"]

    def test_filter_by_action_enum(self) -> None:
        entries = [
            self._make(tool="a", action=AuditAction.ALLOWED),
            self._make(tool="b", action=AuditAction.DENIED),
        ]
        filtered = list(filter_entries(entries, action=AuditAction.ALLOWED))
        assert [e.tool for e in filtered] == ["a"]

    def test_filter_by_task_id(self) -> None:
        entries = [
            self._make(tool="a", action=AuditAction.ALLOWED, task_id="t1"),
            self._make(tool="b", action=AuditAction.ALLOWED, task_id="t2"),
        ]
        filtered = list(filter_entries(entries, task_id="t1"))
        assert [e.tool for e in filtered] == ["a"]

    def test_filter_by_tool(self) -> None:
        entries = [
            self._make(tool="juju_status", action=AuditAction.ALLOWED),
            self._make(tool="read_file", action=AuditAction.ALLOWED),
        ]
        filtered = list(filter_entries(entries, tool="read_file"))
        assert [e.tool for e in filtered] == ["read_file"]

    def test_filters_combine(self) -> None:
        entries = [
            self._make(tool="a", action=AuditAction.ALLOWED, task_id="t1"),
            self._make(tool="a", action=AuditAction.DENIED, task_id="t1"),
            self._make(tool="a", action=AuditAction.ALLOWED, task_id="t2"),
        ]
        filtered = list(
            filter_entries(entries, task_id="t1", action=AuditAction.ALLOWED, tool="a")
        )
        assert len(filtered) == 1
