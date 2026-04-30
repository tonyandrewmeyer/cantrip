"""Tests for Phase 82.2 — bespoke ``intro_caption`` overrides on real tools.

The pre-call caption replaces the formulaic ``Running tool(arg=value)…``
fallback for the high-traffic tools listed in ROADMAP §82.2.  These
tests assert the present-continuous shape that the chat will render in
the pending block before the tool returns — they're independent of
the post-call ``ToolResult.caption`` covered by ``test_tool_captions``.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from cantrip.agent.tools.audit import CharmAuditTool
from cantrip.agent.tools.charm import (
    CharmcraftPackTool,
    CharmValidateTool,
    QuickPackTool,
)
from cantrip.agent.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from cantrip.agent.tools.git import GitCloneTool, GitCommitTool, GitPushTool
from cantrip.agent.tools.juju import (
    JujuDeployTool,
    JujuRefreshTool,
    JujuStatusTool,
    JujuWaitTool,
)
from cantrip.agent.tools.multi_edit import MultiEditTool
from cantrip.agent.tools.observability import LokiQueryTool, TempoQueryTool
from cantrip.agent.tools.oci_registry import (
    RegistryImageInfoTool,
    RegistrySearchTool,
)
from cantrip.agent.tools.testing import RunCharmTestsTool
from cantrip.agent.tools.web import WebFetchTool


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield pathlib.Path(td)


class TestFileSystemIntros:
    def test_read_file(self, temp_dir):
        assert (
            ReadFileTool(base_path=temp_dir).intro_caption({"path": "src/charm.py"})
            == "Reading src/charm.py…"
        )

    def test_read_file_no_path_falls_through(self, temp_dir):
        # No path → return None so the synthesised fallback applies.
        assert ReadFileTool(base_path=temp_dir).intro_caption({}) is None

    def test_write_file(self, temp_dir):
        assert (
            WriteFileTool(base_path=temp_dir).intro_caption({"path": "tests/t.py"})
            == "Writing tests/t.py…"
        )

    def test_edit_file(self, temp_dir):
        assert (
            EditFileTool(base_path=temp_dir).intro_caption({"path": "src/charm.py"})
            == "Editing src/charm.py…"
        )

    def test_multi_edit_single_file(self, temp_dir):
        edits = [
            {"file": "src/charm.py", "old": "a", "new": "b"},
            {"file": "src/charm.py", "old": "c", "new": "d"},
        ]
        assert (
            MultiEditTool(base_path=temp_dir).intro_caption({"edits": edits})
            == "Applying 2 edits to src/charm.py…"
        )

    def test_multi_edit_multiple_files(self, temp_dir):
        edits = [
            {"file": "a.py", "old": "x", "new": "y"},
            {"file": "b.py", "old": "x", "new": "y"},
        ]
        assert (
            MultiEditTool(base_path=temp_dir).intro_caption({"edits": edits})
            == "Applying 2 edits across 2 files…"
        )

    def test_multi_edit_empty_falls_through(self, temp_dir):
        assert MultiEditTool(base_path=temp_dir).intro_caption({"edits": []}) is None


class TestGitIntros:
    def test_clone_https(self):
        assert (
            GitCloneTool().intro_caption({"url": "https://github.com/foo/bar.git"})
            == "Cloning github.com/foo/bar…"
        )

    def test_clone_ssh(self):
        assert (
            GitCloneTool().intro_caption({"url": "git@github.com:foo/bar.git"})
            == "Cloning github.com:foo/bar…"
        )

    def test_clone_no_url_falls_through(self):
        assert GitCloneTool().intro_caption({}) is None

    def test_commit_constant(self):
        assert GitCommitTool().intro_caption({"message": "Fix"}) == "Committing…"

    def test_push_with_remote_and_branch(self):
        assert (
            GitPushTool().intro_caption({"remote": "upstream", "branch": "main"})
            == "Pushing → upstream/main…"
        )

    def test_push_default_remote(self):
        # Default origin used when no remote arg given.
        assert GitPushTool().intro_caption({}) == "Pushing → origin…"


class TestCharmIntros:
    def test_pack_constant(self):
        assert CharmcraftPackTool().intro_caption({"path": "."}) == "Packing the charm…"

    def test_quick_pack_constant(self):
        assert QuickPackTool().intro_caption({"path": "."}) == "Quick-packing the charm…"

    def test_validate_constant(self):
        assert CharmValidateTool().intro_caption({"path": "."}) == "Validating the charm…"

    def test_audit_constant(self):
        assert CharmAuditTool().intro_caption({"path": "."}) == "Auditing the charm…"


class TestJujuIntros:
    def test_status_no_model(self):
        assert JujuStatusTool().intro_caption({}) == "Reading juju status…"

    def test_status_with_model(self):
        assert JujuStatusTool().intro_caption({"model": "dev"}) == "Reading juju status (dev)…"

    def test_deploy_with_app_name(self):
        assert JujuDeployTool().intro_caption({"app_name": "redis"}) == "Deploying redis…"

    def test_deploy_with_charm_path(self):
        # Path-shaped charm input gets shortened to the basename.
        assert (
            JujuDeployTool().intro_caption({"charm": "./redis.charm"}) == "Deploying redis.charm…"
        )

    def test_deploy_no_target(self):
        assert JujuDeployTool().intro_caption({}) == "Deploying…"

    def test_refresh_with_app(self):
        assert JujuRefreshTool().intro_caption({"app_name": "redis"}) == "Refreshing redis…"

    def test_refresh_no_app(self):
        assert JujuRefreshTool().intro_caption({}) == "Refreshing…"

    def test_wait_with_app_only(self):
        assert (
            JujuWaitTool().intro_caption({"app_name": "redis"}) == "Waiting for redis to settle…"
        )

    def test_wait_with_app_and_model(self):
        assert (
            JujuWaitTool().intro_caption({"app_name": "redis", "model": "dev"})
            == "Waiting for redis (dev) to settle…"
        )

    def test_wait_no_target(self):
        assert JujuWaitTool().intro_caption({}) == "Waiting for the model to settle…"


class TestTestingIntros:
    def test_default_test_type(self):
        assert RunCharmTestsTool().intro_caption({}) == "Running unit tests…"

    def test_integration(self):
        assert (
            RunCharmTestsTool().intro_caption({"test_type": "integration"})
            == "Running integration tests…"
        )

    def test_with_pattern(self):
        assert (
            RunCharmTestsTool().intro_caption({"test_type": "unit", "pattern": "test_db"})
            == "Running unit tests (test_db)…"
        )


class TestObservabilityIntros:
    def test_tempo_with_trace_id(self):
        assert (
            TempoQueryTool().intro_caption({"trace_id": "abc123"})
            == "Fetching Tempo trace abc123…"
        )

    def test_tempo_with_service_name(self):
        assert (
            TempoQueryTool().intro_caption({"service_name": "redis"})
            == "Querying Tempo for redis…"
        )

    def test_tempo_no_args(self):
        assert TempoQueryTool().intro_caption({}) == "Querying Tempo…"

    def test_loki_constant(self):
        assert LokiQueryTool().intro_caption({"query": "{}"}) == "Querying Loki…"


class TestWebAndRegistryIntros:
    def test_web_fetch_extracts_host(self):
        assert (
            WebFetchTool().intro_caption({"url": "https://github.com/foo/bar"})
            == "Fetching github.com…"
        )

    def test_web_fetch_no_url_falls_through(self):
        assert WebFetchTool().intro_caption({}) is None

    def test_registry_search_with_query(self):
        assert (
            RegistrySearchTool().intro_caption({"query": "redis"})
            == "Searching Docker Hub for 'redis'…"
        )

    def test_registry_search_no_query(self):
        assert RegistrySearchTool().intro_caption({}) == "Searching Docker Hub…"

    def test_registry_image_info_with_tag(self):
        assert (
            RegistryImageInfoTool().intro_caption({"image": "redis", "tag": "7-alpine"})
            == "Inspecting redis:7-alpine…"
        )

    def test_registry_image_info_image_only(self):
        assert RegistryImageInfoTool().intro_caption({"image": "redis"}) == "Inspecting redis…"

    def test_registry_image_info_no_args(self):
        assert RegistryImageInfoTool().intro_caption({}) == "Inspecting Docker Hub image…"
