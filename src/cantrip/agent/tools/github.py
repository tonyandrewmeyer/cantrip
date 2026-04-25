"""GitHub CLI tools."""

import json
import pathlib
import re
import shutil
import subprocess
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult

# Timeout for all gh operations (seconds).
_GH_TIMEOUT = 30

_GH_NOT_AUTHENTICATED = (
    "The GitHub CLI is not authenticated. "
    "Please run `gh auth login` and follow the prompts, then try again."
)


def _check_gh_auth() -> str | None:
    """Return an error message if gh is not authenticated, or None if all is well."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return "Timed out checking gh authentication status."

    if result.returncode != 0:
        return _GH_NOT_AUTHENTICATED
    return None


class GhRepoCreateTool(Tool):
    """Tool to create a GitHub repository."""

    @property
    def name(self) -> str:
        return "gh_repo_create"

    @property
    def description(self) -> str:
        return "Create a new GitHub repository using the gh CLI. Defaults to a private repository."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Repository name",
                },
                "description": {
                    "type": "string",
                    "description": "Repository description",
                },
                "private": {
                    "type": "boolean",
                    "description": "Whether the repository is private",
                    "default": True,
                },
                "push": {
                    "type": "boolean",
                    "description": "Push local repository to the new remote after creation",
                    "default": False,
                },
            },
            "required": ["name"],
        }

    async def execute(
        self,
        name: str,
        description: str | None = None,
        private: bool = True,
        push: bool = False,
    ) -> ToolResult:
        """Run gh repo create."""
        if not shutil.which("gh"):
            return ToolResult(
                success=False,
                output="",
                error="gh CLI not found. Is it installed?",
            )

        auth_err = _check_gh_auth()
        if auth_err:
            return ToolResult(success=False, output="", error=auth_err)

        cmd = ["gh", "repo", "create", name]
        cmd.append("--private" if private else "--public")
        if description:
            cmd.extend(["--description", description])
        if push:
            cmd.append("--push")
            cmd.append("--source=.")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "gh repo create failed",
                )

            return ToolResult(
                success=True,
                output=result.stdout.strip(),
                data={"name": name, "private": private},
                caption=f"Created {name}{' (private)' if private else ''}",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="gh repo create timed out",
            )


class GhPrCreateTool(Tool):
    """Tool to create a GitHub pull request."""

    @property
    def name(self) -> str:
        return "gh_pr_create"

    @property
    def description(self) -> str:
        return "Create a pull request on GitHub using the gh CLI."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Pull request title",
                },
                "body": {
                    "type": "string",
                    "description": "Pull request body/description",
                },
                "base": {
                    "type": "string",
                    "description": "Base branch for the pull request (e.g. main)",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
                "draft": {
                    "type": "boolean",
                    "description": "Create as a draft pull request",
                    "default": False,
                },
            },
            "required": ["title", "body"],
        }

    async def execute(
        self,
        title: str,
        body: str,
        base: str | None = None,
        path: str = ".",
        draft: bool = False,
    ) -> ToolResult:
        """Run gh pr create."""
        if not shutil.which("gh"):
            return ToolResult(
                success=False,
                output="",
                error="gh CLI not found. Is it installed?",
            )

        auth_err = _check_gh_auth()
        if auth_err:
            return ToolResult(success=False, output="", error=auth_err)

        cmd = ["gh", "pr", "create", "--title", title, "--body", body]
        if base:
            cmd.extend(["--base", base])
        if draft:
            cmd.append("--draft")

        try:
            result = subprocess.run(
                cmd,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "gh pr create failed",
                )

            # Extract the PR number from the URL gh prints on success
            # ("https://github.com/owner/repo/pull/42") so the caption
            # carries the actionable identifier instead of the title.
            stdout = result.stdout.strip()
            pr_match = re.search(r"/pull/(\d+)", stdout)
            caption = f"Created PR #{pr_match.group(1)}" if pr_match else f"Created PR: {title}"
            return ToolResult(
                success=True,
                output=stdout,
                data={"title": title},
                caption=caption,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="gh pr create timed out",
            )


class GhIssueListTool(Tool):
    """Tool to list GitHub issues."""

    @property
    def name(self) -> str:
        return "gh_issue_list"

    @property
    def description(self) -> str:
        return "List issues on a GitHub repository using the gh CLI."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": (
                        "Repository in OWNER/REPO format. Defaults to the current repository."
                    ),
                },
                "state": {
                    "type": "string",
                    "description": "Filter by issue state",
                    "enum": ["open", "closed", "all"],
                    "default": "open",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of issues to list",
                    "default": 10,
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository (used when repo is not specified)",
                    "default": ".",
                },
            },
        }

    async def execute(
        self,
        repo: str | None = None,
        state: str = "open",
        limit: int = 10,
        path: str = ".",
    ) -> ToolResult:
        """Run gh issue list."""
        if not shutil.which("gh"):
            return ToolResult(
                success=False,
                output="",
                error="gh CLI not found. Is it installed?",
            )

        auth_err = _check_gh_auth()
        if auth_err:
            return ToolResult(success=False, output="", error=auth_err)

        cmd = ["gh", "issue", "list", "--state", state, "--limit", str(limit)]
        if repo:
            cmd.extend(["--repo", repo])

        try:
            result = subprocess.run(
                cmd,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "gh issue list failed",
                )

            output = result.stdout.strip()
            if not output:
                output = "No issues found."
                caption = f"no {state} issues"
            else:
                count = sum(1 for line in output.splitlines() if line.strip())
                caption = f"{count} {state} issue{'s' if count != 1 else ''}"

            return ToolResult(
                success=True,
                output=output,
                caption=caption,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="gh issue list timed out",
            )


class GhPrListTool(Tool):
    """Tool to list pull requests on a GitHub repository."""

    @property
    def name(self) -> str:
        return "gh_pr_list"

    @property
    def description(self) -> str:
        return "List pull requests on a GitHub repository using the gh CLI."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in OWNER/REPO format. Defaults to the current repository.",
                },
                "state": {
                    "type": "string",
                    "description": "Filter by PR state",
                    "enum": ["open", "closed", "merged", "all"],
                    "default": "open",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of PRs to list",
                    "default": 10,
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository (used when repo is not specified)",
                    "default": ".",
                },
            },
        }

    async def execute(
        self,
        repo: str | None = None,
        state: str = "open",
        limit: int = 10,
        path: str = ".",
    ) -> ToolResult:
        """Run gh pr list."""
        if not shutil.which("gh"):
            return ToolResult(success=False, output="", error="gh CLI not found. Is it installed?")

        auth_err = _check_gh_auth()
        if auth_err:
            return ToolResult(success=False, output="", error=auth_err)

        cmd = ["gh", "pr", "list", "--state", state, "--limit", str(limit)]
        if repo:
            cmd.extend(["--repo", repo])

        try:
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=_GH_TIMEOUT
            )
            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "gh pr list failed",
                )
            output = result.stdout.strip()
            if not output:
                caption = f"no {state} PRs"
            else:
                count = sum(1 for line in output.splitlines() if line.strip())
                caption = f"{count} {state} PR{'s' if count != 1 else ''}"
            return ToolResult(
                success=True,
                output=output or "No pull requests found.",
                caption=caption,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="gh pr list timed out")


class GhPrViewTool(Tool):
    """Tool to view details of a pull request."""

    @property
    def name(self) -> str:
        return "gh_pr_view"

    @property
    def description(self) -> str:
        return "View details of a GitHub pull request including status, reviews, and checks."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pr_number": {
                    "type": "integer",
                    "description": "Pull request number",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository in OWNER/REPO format. Defaults to the current repository.",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the git repository (used when repo is not specified)",
                    "default": ".",
                },
            },
            "required": ["pr_number"],
        }

    async def execute(
        self,
        pr_number: int,
        repo: str | None = None,
        path: str = ".",
    ) -> ToolResult:
        """Run gh pr view."""
        if not shutil.which("gh"):
            return ToolResult(success=False, output="", error="gh CLI not found. Is it installed?")

        auth_err = _check_gh_auth()
        if auth_err:
            return ToolResult(success=False, output="", error=auth_err)

        cmd = [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,title,state,body,author,reviewDecision,url,headRefName,baseRefName",
        ]
        if repo:
            cmd.extend(["--repo", repo])

        try:
            result = subprocess.run(
                cmd, cwd=path, capture_output=True, text=True, timeout=_GH_TIMEOUT
            )
            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "gh pr view failed",
                )

            import json

            try:
                data = json.loads(result.stdout)
                lines = [
                    f"**PR #{data.get('number')}** — {data.get('title', '')}",
                    f"State: {data.get('state', 'unknown')}",
                    f"Author: {data.get('author', {}).get('login', 'unknown')}",
                    f"Branch: {data.get('headRefName', '')} → {data.get('baseRefName', '')}",
                    f"Review: {data.get('reviewDecision', 'none')}",
                    f"URL: {data.get('url', '')}",
                ]
                body = data.get("body", "")
                if body:
                    preview = body[:500]
                    if len(body) > 500:
                        preview += "\n…(truncated)"
                    lines.append(f"\n{preview}")
                title = data.get("title", "") or ""
                if len(title) > 50:
                    title = title[:49] + "…"
                caption = (
                    f"PR #{data.get('number')}: {title}" if title else f"PR #{data.get('number')}"
                )
                return ToolResult(
                    success=True,
                    output="\n".join(lines),
                    data=data,
                    caption=caption,
                )
            except json.JSONDecodeError:
                return ToolResult(
                    success=True,
                    output=result.stdout.strip(),
                    caption=f"PR #{pr_number}",
                )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="gh pr view timed out")


_BUG_REPORT_TEMPLATE = """\
---
name: Bug report
about: Report a problem with this charm
title: ''
labels: bug
---

## What happened?

<!-- Describe the behaviour you saw. -->

## What did you expect to happen?

<!-- Describe the behaviour you expected. -->

## Steps to reproduce

1.
2.
3.

## Environment

- Juju version:
- Charm revision:
- Cloud / substrate:

## Logs

<!-- Paste relevant output from `juju debug-log` or `juju status` here. -->
"""

_FEATURE_REQUEST_TEMPLATE = """\
---
name: Feature request
about: Suggest an idea for this charm
title: ''
labels: enhancement
---

## Problem

<!-- What problem are you trying to solve? -->

## Proposed solution

<!-- What would you like to see? -->

## Alternatives considered

<!-- What else did you think about? -->
"""

# CI workflow stub aligned with the upstream "set up CI for a charm" how-to:
# top-level least-privilege, pinned action SHAs/majors, persist-credentials off
# on checkout, and tox/tox-uv driving the actual lint + unit jobs.
_CI_WORKFLOW_TEMPLATE = """\
name: CI
on:
  push:
    branches: [main]
  pull_request:
  workflow_call:
  workflow_dispatch:

permissions: {}

jobs:
  lint:
    name: Linting
    runs-on: ubuntu-24.04
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up uv
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8.0.0
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Lint the code
        run: tox -e lint

  unit:
    name: Unit tests
    runs-on: ubuntu-24.04
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up uv
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8.0.0
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Run unit tests
        run: tox -e unit
"""

# Conservative defaults for a fresh charm repo: require one PR review, forbid
# force-pushes and deletions, no required status checks until CI has had a
# chance to land green.
_BRANCH_PROTECTION_PAYLOAD: dict[str, Any] = {
    "required_status_checks": None,
    "enforce_admins": False,
    "required_pull_request_reviews": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews": False,
        "require_code_owner_reviews": False,
    },
    "restrictions": None,
    "allow_force_pushes": False,
    "allow_deletions": False,
}


def _detect_repo_slug(path: str) -> tuple[str | None, str | None]:
    """Return ``(slug, error)`` where ``slug`` is ``OWNER/REPO`` or ``None``."""
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, "gh repo view timed out"
    if result.returncode != 0:
        return None, result.stderr.strip() or "gh repo view failed"
    slug = result.stdout.strip()
    if not slug:
        return None, "gh repo view returned an empty repository slug"
    return slug, None


class GhRepoBootstrapTool(Tool):
    """Apply default repository settings after ``gh repo create``.

    Writes issue templates and a CI workflow stub into the local
    ``.github/`` tree (the caller commits and pushes them) and enables
    conservative branch protection on the default branch via ``gh api``.
    Each step is independently opt-out so the agent can apply a subset
    when appropriate.
    """

    @property
    def name(self) -> str:
        return "gh_repo_bootstrap"

    @property
    def description(self) -> str:
        return (
            "Configure a freshly-created GitHub repository with default branch "
            "protection, issue templates, and a CI workflow stub. Local files "
            "are written under .github/ and still need to be committed; branch "
            "protection is applied immediately via the GitHub API."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                    "default": ".",
                },
                "repo": {
                    "type": "string",
                    "description": (
                        "Repository in OWNER/REPO format. If omitted, the slug "
                        "is detected via `gh repo view` from the given path."
                    ),
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to protect",
                    "default": "main",
                },
                "branch_protection": {
                    "type": "boolean",
                    "description": "Enable default branch protection",
                    "default": True,
                },
                "issue_templates": {
                    "type": "boolean",
                    "description": (
                        "Write .github/ISSUE_TEMPLATE/bug_report.md and "
                        "feature_request.md if they don't already exist"
                    ),
                    "default": True,
                },
                "ci_workflow": {
                    "type": "boolean",
                    "description": ("Write .github/workflows/ci.yaml if it doesn't already exist"),
                    "default": True,
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        repo: str | None = None,
        branch: str = "main",
        branch_protection: bool = True,
        issue_templates: bool = True,
        ci_workflow: bool = True,
    ) -> ToolResult:
        """Run the bootstrap steps selected by the caller."""
        if not shutil.which("gh"):
            return ToolResult(
                success=False,
                output="",
                error="gh CLI not found. Is it installed?",
            )

        auth_err = _check_gh_auth()
        if auth_err:
            return ToolResult(success=False, output="", error=auth_err)

        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        written: list[str] = []
        skipped: list[str] = []
        warnings: list[str] = []

        if issue_templates:
            templates_dir = charm_dir / ".github" / "ISSUE_TEMPLATE"
            templates_dir.mkdir(parents=True, exist_ok=True)
            for filename, content in (
                ("bug_report.md", _BUG_REPORT_TEMPLATE),
                ("feature_request.md", _FEATURE_REQUEST_TEMPLATE),
            ):
                target = templates_dir / filename
                if target.exists():
                    skipped.append(str(target.relative_to(charm_dir)))
                    continue
                target.write_text(content)
                written.append(str(target.relative_to(charm_dir)))

        if ci_workflow:
            workflows_dir = charm_dir / ".github" / "workflows"
            workflows_dir.mkdir(parents=True, exist_ok=True)
            ci_path = workflows_dir / "ci.yaml"
            if ci_path.exists():
                skipped.append(str(ci_path.relative_to(charm_dir)))
            else:
                ci_path.write_text(_CI_WORKFLOW_TEMPLATE)
                written.append(str(ci_path.relative_to(charm_dir)))

        protection_applied = False
        if branch_protection:
            slug = repo
            if not slug:
                slug, detect_err = _detect_repo_slug(str(charm_dir))
                if not slug:
                    warnings.append(
                        f"Could not detect repository slug: {detect_err}. "
                        "Branch protection skipped."
                    )
            if slug:
                cmd = [
                    "gh",
                    "api",
                    "-X",
                    "PUT",
                    f"repos/{slug}/branches/{branch}/protection",
                    "--input",
                    "-",
                ]
                try:
                    result = subprocess.run(
                        cmd,
                        input=json.dumps(_BRANCH_PROTECTION_PAYLOAD),
                        capture_output=True,
                        text=True,
                        timeout=_GH_TIMEOUT,
                    )
                except subprocess.TimeoutExpired:
                    warnings.append("Branch protection API call timed out.")
                else:
                    if result.returncode == 0:
                        protection_applied = True
                    else:
                        stderr = result.stderr.strip() or "gh api failed"
                        warnings.append(f"Branch protection API call failed: {stderr}")

        summary_lines: list[str] = []
        if written:
            summary_lines.append("Wrote: " + ", ".join(written))
        if skipped:
            summary_lines.append("Skipped (already present): " + ", ".join(skipped))
        if protection_applied:
            summary_lines.append(f"Applied branch protection to {branch}.")
        for warning in warnings:
            summary_lines.append(f"Warning: {warning}")
        if not summary_lines:
            summary_lines.append("Nothing to do (all steps disabled).")

        caption_parts: list[str] = []
        if written:
            caption_parts.append(f"wrote {len(written)}")
        if skipped:
            caption_parts.append(f"skipped {len(skipped)}")
        if protection_applied:
            caption_parts.append("protection applied")
        if warnings:
            caption_parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
        caption = ", ".join(caption_parts) if caption_parts else "no changes"

        return ToolResult(
            success=not warnings,
            output="\n".join(summary_lines),
            error="\n".join(warnings) if warnings else None,
            caption=caption,
            data={
                "written": written,
                "skipped": skipped,
                "branch_protection_applied": protection_applied,
                "warnings": warnings,
            },
        )
