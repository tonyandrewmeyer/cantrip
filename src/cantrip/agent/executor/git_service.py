"""Default ``GitService`` implementation backed by ``git`` subprocess calls."""

import contextlib
import logging
import pathlib
import subprocess

from cantrip.agent.queue import AgentTask

log = logging.getLogger(__name__)


class _DefaultGitService:
    """Git operations using subprocess calls."""

    def fingerprint(self, charm_path: str | pathlib.Path | None) -> str:
        if not charm_path:
            return ""
        charm_dir = str(charm_path)
        parts: list[str] = []
        for cmd in (["git", "rev-parse", "HEAD"], ["git", "status", "--porcelain"]):
            try:
                result = subprocess.run(
                    cmd,
                    cwd=charm_dir,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    parts.append(result.stdout.strip())
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        return "\n".join(parts)

    def snapshot_head(self, charm_path: str | pathlib.Path | None) -> str | None:
        if not charm_path:
            return None
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(charm_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def revert_to_clean(
        self,
        charm_path: str | pathlib.Path,
        task: AgentTask,
        snapshot: str,
    ) -> None:
        charm_dir = str(charm_path)

        # Capture the diff so the failure can be diagnosed.
        diff_text = ""
        try:
            diff_result = subprocess.run(
                ["git", "diff"],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if diff_result.returncode == 0 and diff_result.stdout.strip():
                diff_text = diff_result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        if diff_text:
            existing = task.result or ""
            task.result = f"[reverted diff]\n{diff_text}\n\n{existing}"

        # Restore tracked files to their committed state.
        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, OSError):
            subprocess.run(
                ["git", "checkout", "."],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

        # Remove untracked files left behind by failing subagents.
        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, OSError):
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

        log.warning(
            "Reverted working tree in %s after failed task '%s' (snapshot %s)",
            charm_dir,
            task.title,
            snapshot[:12],
        )

    def has_uncommitted_changes(self, charm_path: str | pathlib.Path) -> bool:
        charm_dir = str(charm_path)
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=charm_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())
