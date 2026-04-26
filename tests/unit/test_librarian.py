"""Tests for the Phase 70.1 Librarian subsystem.

Covers:
- ``LIBRARIAN`` task category wiring (whitelist + guidance + light-routing).
- Quality-flag derivation in ``charmhub_search``.
- ``charmhub_fetch`` — cache hit, source-URL resolution, missing-link error.
- ``launchpad_search`` and ``launchpad_fetch`` — search shape, VCS gating.
- The shared ``charm_library`` cache helpers (TTL, freshness, sidecar).
- ``/search-charms`` slash command dispatch and combined-render output.

No live HTTP — every Charmhub / Launchpad / git interaction is stubbed.
"""

from __future__ import annotations

import datetime
import json
import pathlib
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cantrip.agent import slash_commands
from cantrip.agent.queue import TaskCategory
from cantrip.agent.subagent import _CATEGORY_GUIDANCE, _CATEGORY_TOOLS, _LIGHT_CATEGORIES
from cantrip.agent.tools import charm_library
from cantrip.agent.tools.charmhub import (
    CharmhubFetchTool,
    CharmhubSearchTool,
    _quality_flags,
)
from cantrip.agent.tools.launchpad import LaunchpadFetchTool, LaunchpadSearchTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _http_response(*, status_code: int = 200, json_body: dict | None = None) -> httpx.Response:
    """Build a minimal httpx.Response usable in tests."""
    body = json.dumps(json_body or {}).encode()
    return httpx.Response(
        status_code=status_code,
        content=body,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://example/"),
    )


def _http_client(response: httpx.Response | None = None, side_effect: Exception | None = None):
    """Return a mock httpx.AsyncClient context manager."""
    mock = AsyncMock()
    if side_effect is not None:
        mock.get = AsyncMock(side_effect=side_effect)
    else:
        mock.get = AsyncMock(return_value=response)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    return mock


@pytest.fixture
def cache_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[pathlib.Path]:
    """Redirect the charm-library cache to a tmpdir."""
    monkeypatch.setenv("CANTRIP_CHARM_LIBRARY_DIR", str(tmp_path / "charm-library"))
    yield tmp_path / "charm-library"


# ---------------------------------------------------------------------------
# LIBRARIAN category wiring
# ---------------------------------------------------------------------------


class TestLibrarianCategory:
    """The new TaskCategory must come with whitelist + guidance + light routing."""

    def test_category_value(self) -> None:
        assert TaskCategory.LIBRARIAN.value == "librarian"

    def test_whitelist_is_read_only_and_includes_new_tools(self) -> None:
        whitelist = _CATEGORY_TOOLS[TaskCategory.LIBRARIAN]
        # Required tools per spec.
        for required in (
            "charmhub_search",
            "charmhub_info",
            "charmhub_fetch",
            "launchpad_search",
            "launchpad_fetch",
            "web_fetch",
        ):
            assert required in whitelist, f"missing {required}"
        # Read-only fs only — no write/edit/run.
        for forbidden in (
            "write_file",
            "edit_file",
            "multi_edit",
            "run_command",
            "git_commit",
            "git_push",
        ):
            assert forbidden not in whitelist, f"unexpected mutating tool: {forbidden}"

    def test_guidance_loaded(self) -> None:
        guidance = _CATEGORY_GUIDANCE[TaskCategory.LIBRARIAN]
        assert "Librarian" in guidance
        assert "quality" in guidance.lower()
        assert "source_url" in guidance  # Output contract is documented.

    def test_routes_to_light_provider(self) -> None:
        assert TaskCategory.LIBRARIAN in _LIGHT_CATEGORIES


# ---------------------------------------------------------------------------
# Quality-flag derivation
# ---------------------------------------------------------------------------


class TestQualityFlags:
    """Search quality flags should reflect age, channel risk, and validation."""

    def test_recently_maintained_flag(self) -> None:
        now = datetime.datetime(2026, 4, 26, tzinfo=datetime.UTC)
        flags = _quality_flags(
            released_at=now - datetime.timedelta(days=30),
            risk="stable",
            publisher_validation="canonical",
            now=now,
        )
        assert "recently-maintained" in flags
        assert "channel-stable" in flags
        assert "publisher-canonical" in flags

    def test_stale_flag(self) -> None:
        now = datetime.datetime(2026, 4, 26, tzinfo=datetime.UTC)
        flags = _quality_flags(
            released_at=now - datetime.timedelta(days=400),
            risk=None,
            publisher_validation=None,
            now=now,
        )
        assert "stale" in flags
        assert not any(f.startswith("channel-") for f in flags)
        assert not any(f.startswith("publisher-") for f in flags)

    def test_empty_when_no_signal_present(self) -> None:
        now = datetime.datetime(2026, 4, 26, tzinfo=datetime.UTC)
        flags = _quality_flags(released_at=None, risk=None, publisher_validation=None, now=now)
        assert flags == []


class TestCharmhubSearchSignals:
    """Search results must surface the new quality fields end-to-end."""

    @pytest.mark.asyncio
    async def test_search_includes_quality_flags(self) -> None:
        body = {
            "results": [
                {
                    "name": "postgresql-k8s",
                    "result": {
                        "summary": "PostgreSQL on Kubernetes",
                        "publisher": {"display-name": "Canonical", "validation": "canonical"},
                        "categories": [{"name": "databases"}],
                        "links": {"source": ["https://github.com/canonical/postgresql-k8s"]},
                    },
                    "default-release": {
                        "channel": {
                            "released-at": "2026-04-01T12:00:00+00:00",
                            "risk": "stable",
                            "name": "latest/stable",
                        },
                    },
                },
            ]
        }
        client = _http_client(_http_response(json_body=body))
        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=client):
            result = await CharmhubSearchTool().execute(query="postgresql")
        assert result.success
        first = result.data["results"][0]
        assert first["source_url"] == "https://github.com/canonical/postgresql-k8s"
        assert first["channel"] == "latest/stable"
        assert first["risk"] == "stable"
        assert first["publisher_validation"] == "canonical"
        # Quality flags include the publisher and channel signals.  The
        # recency flag depends on wall-clock vs. the released-at date,
        # so just check that *something* came back.
        assert "channel-stable" in first["quality_flags"]
        assert "publisher-canonical" in first["quality_flags"]


# ---------------------------------------------------------------------------
# charm_library cache helpers
# ---------------------------------------------------------------------------


class TestCharmLibraryCache:
    """Freshness/TTL + sidecar round-trip + name-safety."""

    def test_cache_root_honours_env(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANTRIP_CHARM_LIBRARY_DIR", str(tmp_path / "lib"))
        assert charm_library.cache_root() == tmp_path / "lib"

    def test_entry_path_rejects_empty_name(self, cache_root: pathlib.Path) -> None:
        with pytest.raises(ValueError):
            charm_library.entry_path(charm_library.SOURCE_CHARMHUB, "")

    def test_entry_path_flattens_separators(self, cache_root: pathlib.Path) -> None:
        entry = charm_library.entry_path(charm_library.SOURCE_CHARMHUB, "foo/bar")
        # Single segment under cache root — no path traversal allowed.
        assert entry.name == "foo-bar"
        assert entry.parent.name == charm_library.SOURCE_CHARMHUB

    def test_record_and_read_meta_round_trip(self, cache_root: pathlib.Path) -> None:
        entry = charm_library.entry_path(charm_library.SOURCE_CHARMHUB, "myapp")
        charm_library.record_fetch(
            entry,
            source=charm_library.SOURCE_CHARMHUB,
            name="myapp",
            upstream_url="https://example.com/myapp.git",
            revision="42",
        )
        meta = charm_library.read_meta(entry)
        assert meta is not None
        assert meta["source"] == charm_library.SOURCE_CHARMHUB
        assert meta["name"] == "myapp"
        assert meta["upstream_url"] == "https://example.com/myapp.git"
        assert meta["revision"] == "42"
        assert "fetched_at" in meta

    def test_is_fresh_within_ttl(self, cache_root: pathlib.Path) -> None:
        entry = charm_library.entry_path(charm_library.SOURCE_CHARMHUB, "myapp")
        charm_library.record_fetch(
            entry,
            source=charm_library.SOURCE_CHARMHUB,
            name="myapp",
            upstream_url="https://example.com/myapp.git",
        )
        assert charm_library.is_fresh(entry, ttl_days=7)

    def test_is_fresh_expired(self, cache_root: pathlib.Path) -> None:
        entry = charm_library.entry_path(charm_library.SOURCE_CHARMHUB, "myapp")
        old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)
        entry.mkdir(parents=True, exist_ok=True)
        charm_library.meta_path(entry).write_text(
            json.dumps(
                {
                    "source": charm_library.SOURCE_CHARMHUB,
                    "name": "myapp",
                    "upstream_url": "https://example.com/myapp.git",
                    "fetched_at": old.isoformat(),
                }
            )
        )
        assert not charm_library.is_fresh(entry, ttl_days=7)

    def test_is_fresh_missing_sidecar(self, cache_root: pathlib.Path) -> None:
        entry = charm_library.entry_path(charm_library.SOURCE_CHARMHUB, "myapp")
        assert not charm_library.is_fresh(entry)

    def test_is_fresh_corrupt_sidecar(self, cache_root: pathlib.Path) -> None:
        entry = charm_library.entry_path(charm_library.SOURCE_CHARMHUB, "myapp")
        entry.mkdir(parents=True, exist_ok=True)
        charm_library.meta_path(entry).write_text("{not json")
        assert charm_library.read_meta(entry) is None
        assert not charm_library.is_fresh(entry)


# ---------------------------------------------------------------------------
# charmhub_fetch
# ---------------------------------------------------------------------------


class TestCharmhubFetch:
    """The fetch tool must respect the cache, surface link gaps, and clone."""

    @pytest.mark.asyncio
    async def test_cache_hit_short_circuits(self, cache_root: pathlib.Path) -> None:
        entry = charm_library.entry_path(charm_library.SOURCE_CHARMHUB, "redis")
        charm_library.record_fetch(
            entry,
            source=charm_library.SOURCE_CHARMHUB,
            name="redis",
            upstream_url="https://github.com/canonical/redis-k8s-operator",
            revision="123",
        )
        # Drop a stub file so the listing renders something useful.
        (entry / "metadata.yaml").write_text("name: redis\n")
        result = await CharmhubFetchTool().execute(name="redis")
        assert result.success
        assert result.data["cached"] is True
        assert "redis (cached)" in result.caption
        assert "metadata.yaml" in result.output

    @pytest.mark.asyncio
    async def test_missing_source_link_surfaces_clear_error(
        self, cache_root: pathlib.Path
    ) -> None:
        body = {
            "result": {"summary": "no links here", "links": {}},
            "default-release": {"revision": {"revision": 7}},
        }
        client = _http_client(_http_response(json_body=body))
        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=client):
            result = await CharmhubFetchTool().execute(name="ghost-charm")
        assert not result.success
        assert "no source / issues / website link" in result.error
        assert result.data["links_missing"] is True

    @pytest.mark.asyncio
    async def test_404_not_found(self, cache_root: pathlib.Path) -> None:
        request = httpx.Request("GET", "https://api.charmhub.io/v2/charms/info/missing")
        response = httpx.Response(status_code=404, request=request)
        exc = httpx.HTTPStatusError("not found", request=request, response=response)
        client = _http_client(side_effect=exc)
        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=client):
            result = await CharmhubFetchTool().execute(name="missing")
        assert not result.success
        assert "not found" in result.error.lower()
        assert result.data["status_code"] == 404

    @pytest.mark.asyncio
    async def test_happy_path_clones_and_records_meta(self, cache_root: pathlib.Path) -> None:
        body = {
            "result": {
                "summary": "test charm",
                "links": {"source": ["https://github.com/example/foo"]},
            },
            "default-release": {"revision": {"revision": 99}},
        }
        client = _http_client(_http_response(json_body=body))

        async def _fake_communicate(_self):
            return b"", b""

        # Stand in for the asyncio subprocess: it must materialise a
        # tree on disk so the listing renders, then return exit 0.
        async def _fake_exec(*args, **_kwargs):
            # The clone target is the last positional arg.
            target = pathlib.Path(args[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "src").mkdir()
            (target / "src" / "charm.py").write_text("# charm\n")
            (target / "metadata.yaml").write_text("name: foo\n")
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with (
            patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=client),
            patch("cantrip.agent.tools.charmhub.shutil.which", return_value="/usr/bin/git"),
            patch("cantrip.agent.tools.charmhub.asyncio.create_subprocess_exec", _fake_exec),
        ):
            result = await CharmhubFetchTool().execute(name="foo", force=True)

        assert result.success, result.error
        assert result.data["cached"] is False
        assert result.data["upstream_url"] == "https://github.com/example/foo"
        assert "src/" in result.output
        assert "metadata.yaml" in result.output
        # Sidecar got written.
        meta = charm_library.read_meta(pathlib.Path(result.data["path"]))
        assert meta is not None
        assert meta["upstream_url"] == "https://github.com/example/foo"
        assert meta["revision"] == "99"

    @pytest.mark.asyncio
    async def test_git_missing_clean_error(self, cache_root: pathlib.Path) -> None:
        body = {
            "result": {
                "summary": "test charm",
                "links": {"source": ["https://github.com/example/foo"]},
            },
            "default-release": {"revision": {"revision": 1}},
        }
        client = _http_client(_http_response(json_body=body))
        with (
            patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=client),
            patch("cantrip.agent.tools.charmhub.shutil.which", return_value=None),
        ):
            result = await CharmhubFetchTool().execute(name="foo", force=True)
        assert not result.success
        assert "git is not installed" in result.error


# ---------------------------------------------------------------------------
# launchpad_search
# ---------------------------------------------------------------------------


class TestLaunchpadSearch:
    """Launchpad project search shape + quality-flag derivation."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        body = {
            "entries": [
                {
                    "name": "kafka-operator",
                    "summary": "Charmed Kafka operator",
                    "vcs": "Git",
                    "web_link": "https://launchpad.net/kafka-operator",
                    "date_last_modified": "2026-04-01T12:00:00+00:00",
                },
                {
                    "name": "ldap-charm",
                    "summary": "Older LDAP work",
                    "vcs": "Bazaar",
                    "web_link": "https://launchpad.net/ldap-charm",
                    "date_last_modified": "2022-01-01T00:00:00+00:00",
                },
            ]
        }
        client = _http_client(_http_response(json_body=body))
        with patch("cantrip.agent.tools.launchpad.httpx.AsyncClient", return_value=client):
            result = await LaunchpadSearchTool().execute(query="kafka")
        assert result.success
        assert result.data["total"] == 2
        first = result.data["results"][0]
        assert first["name"] == "kafka-operator"
        assert first["vcs"] == "Git"
        assert "vcs-git" in first["quality_flags"]
        assert "recently-maintained" in first["quality_flags"]
        second = result.data["results"][1]
        assert "vcs-bazaar" in second["quality_flags"]
        assert "stale" in second["quality_flags"]

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        client = _http_client(_http_response(json_body={"entries": []}))
        with patch("cantrip.agent.tools.launchpad.httpx.AsyncClient", return_value=client):
            result = await LaunchpadSearchTool().execute(query="nonexistent")
        assert result.success
        assert "No Launchpad projects found" in result.output
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_http_error_surfaces(self) -> None:
        request = httpx.Request("GET", "https://api.launchpad.net/devel/projects")
        response = httpx.Response(status_code=503, request=request)
        exc = httpx.HTTPStatusError("svc down", request=request, response=response)
        client = _http_client(side_effect=exc)
        with patch("cantrip.agent.tools.launchpad.httpx.AsyncClient", return_value=client):
            result = await LaunchpadSearchTool().execute(query="anything")
        assert not result.success
        assert "503" in result.error


# ---------------------------------------------------------------------------
# launchpad_fetch
# ---------------------------------------------------------------------------


class TestLaunchpadFetch:
    """Git-only fetch path; Bazaar projects must surface a clear refusal."""

    @pytest.mark.asyncio
    async def test_bazaar_project_refused(self, cache_root: pathlib.Path) -> None:
        body = {
            "vcs": "Bazaar",
            "web_link": "https://launchpad.net/old-charm",
        }
        client = _http_client(_http_response(json_body=body))
        with patch("cantrip.agent.tools.launchpad.httpx.AsyncClient", return_value=client):
            result = await LaunchpadFetchTool().execute(name="old-charm", force=True)
        assert not result.success
        assert "Bazaar" in result.error
        assert result.data["vcs"] == "Bazaar"

    @pytest.mark.asyncio
    async def test_no_vcs_clean_error(self, cache_root: pathlib.Path) -> None:
        body = {"vcs": None, "web_link": "https://launchpad.net/empty"}
        client = _http_client(_http_response(json_body=body))
        with patch("cantrip.agent.tools.launchpad.httpx.AsyncClient", return_value=client):
            result = await LaunchpadFetchTool().execute(name="empty", force=True)
        assert not result.success
        assert "no registered VCS" in result.error

    @pytest.mark.asyncio
    async def test_git_clone_happy_path(self, cache_root: pathlib.Path) -> None:
        body = {
            "vcs": "Git",
            "web_link": "https://launchpad.net/foo",
        }
        client = _http_client(_http_response(json_body=body))

        async def _fake_exec(*args, **_kwargs):
            target = pathlib.Path(args[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "README.md").write_text("hi\n")
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with (
            patch("cantrip.agent.tools.launchpad.httpx.AsyncClient", return_value=client),
            patch("cantrip.agent.tools.launchpad.shutil.which", return_value="/usr/bin/git"),
            patch("cantrip.agent.tools.launchpad.asyncio.create_subprocess_exec", _fake_exec),
        ):
            result = await LaunchpadFetchTool().execute(name="foo", force=True)
        assert result.success, result.error
        assert result.data["upstream_url"] == "https://git.launchpad.net/foo"
        assert "README.md" in result.output
        meta = charm_library.read_meta(pathlib.Path(result.data["path"]))
        assert meta is not None
        assert meta["source"] == charm_library.SOURCE_LAUNCHPAD


# ---------------------------------------------------------------------------
# /search-charms slash command
# ---------------------------------------------------------------------------


class TestSearchCharmsSlash:
    """The /search-charms verb wires both backends and renders the combined view."""

    def test_empty_args_returns_usage(self) -> None:
        result = slash_commands._handle_search_charms("")
        assert result.followup is None
        assert "Usage" in result.text

    def test_with_query_returns_followup(self) -> None:
        result = slash_commands._handle_search_charms("kafka operator")
        assert result.followup is not None
        assert "Searching" in result.text
        assert result.markdown is True
        # Avoid leaking the followup coroutine.
        result.followup.close()

    @pytest.mark.asyncio
    async def test_followup_renders_combined_output(self) -> None:
        charm_body = {
            "results": [
                {
                    "name": "redis-k8s",
                    "result": {
                        "summary": "Redis K8s",
                        "publisher": {
                            "display-name": "Canonical",
                            "validation": "canonical",
                        },
                        "categories": [{"name": "databases"}],
                        "links": {},
                    },
                    "default-release": {
                        "channel": {
                            "released-at": "2026-04-01T12:00:00+00:00",
                            "risk": "stable",
                            "name": "latest/stable",
                        },
                    },
                }
            ]
        }
        launchpad_body = {
            "entries": [
                {
                    "name": "redis-mirror",
                    "summary": "Mirror project",
                    "vcs": "Git",
                    "web_link": "https://launchpad.net/redis-mirror",
                    "date_last_modified": "2026-03-01T00:00:00+00:00",
                }
            ]
        }
        # ``charmhub`` and ``launchpad`` both import the same ``httpx``
        # module, so a single patch on ``httpx.AsyncClient`` is the
        # only way to dispatch correctly across both tools.  Route on
        # the ``base_url`` / first ``client.get(URL, …)`` argument.
        charm_client = _http_client(_http_response(json_body=charm_body))
        lp_client = _http_client(_http_response(json_body=launchpad_body))

        def _factory(*_args, **_kwargs):
            # Pick by a short-lived per-task counter — both tools call
            # ``httpx.AsyncClient(...)`` exactly once.
            calls.append(None)
            return charm_client if len(calls) == 1 else lp_client

        calls: list[None] = []
        with patch("httpx.AsyncClient", side_effect=_factory):
            text = await slash_commands._run_search_charms("redis")

        assert "## Charmhub" in text
        assert "redis-k8s" in text
        assert "## Launchpad" in text
        assert "redis-mirror" in text
        assert text.startswith("# Charm-library search:")

    @pytest.mark.asyncio
    async def test_followup_falls_back_when_one_backend_fails(self) -> None:
        charm_body = {"results": []}
        request = httpx.Request("GET", "https://api.launchpad.net/devel/projects")
        response = httpx.Response(status_code=500, request=request)
        exc = httpx.HTTPStatusError("server error", request=request, response=response)
        charm_client = _http_client(_http_response(json_body=charm_body))
        lp_client = _http_client(side_effect=exc)

        calls: list[None] = []

        def _factory(*_args, **_kwargs):
            calls.append(None)
            return charm_client if len(calls) == 1 else lp_client

        with patch("httpx.AsyncClient", side_effect=_factory):
            text = await slash_commands._run_search_charms("anything")

        assert "Launchpad search failed" in text
        assert "## Charmhub" in text
        # The Charmhub side still rendered (empty result message).
        assert "No charms found" in text

    def test_catalogue_entry_present(self) -> None:
        verbs = {cmd.verb for cmd in slash_commands.COMMAND_CATALOGUE}
        assert "/search-charms" in verbs
        assert "/search-charms" in slash_commands.SHARED_VERBS
