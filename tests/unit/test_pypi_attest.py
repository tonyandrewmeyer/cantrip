"""Unit tests for the shared ``pypi_attest`` module."""

import io
import json
import urllib.error
from collections.abc import Iterator
from unittest import mock

import pytest

import pypi_attest


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    """Ensure each test starts with an empty provenance cache."""
    pypi_attest.clear_cache()
    yield
    pypi_attest.clear_cache()


class TestNormaliseName:
    def test_lowercases(self) -> None:
        assert pypi_attest.normalise_name("Ops") == "ops"

    def test_collapses_separators(self) -> None:
        # PEP 503 treats -, _ and . as equivalent separators and collapses runs.
        assert pypi_attest.normalise_name("Ops_Scenario") == "ops-scenario"
        assert pypi_attest.normalise_name("ops.scenario") == "ops-scenario"
        assert pypi_attest.normalise_name("charmlibs_pathops") == "charmlibs-pathops"

    def test_collapses_repeated_separators(self) -> None:
        assert pypi_attest.normalise_name("ops--scenario") == "ops-scenario"
        assert pypi_attest.normalise_name("ops_._scenario") == "ops-scenario"


class TestIsMustHave:
    @pytest.mark.parametrize(
        "name",
        [
            "ops",
            "Ops",
            "ops-scenario",
            "ops_scenario",
            "ops.scenario",
            "ops-tracing",
            "jubilant",
            "charmlibs-pathops",
            "charmlibs_anything",
            "charmlibs-very-specific-library",
        ],
    )
    def test_matches_must_have_packages(self, name: str) -> None:
        assert pypi_attest.is_must_have(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "requests",
            "pydantic",
            "opsify",  # starts with "ops" but not an exact match.
            "ops-extra",  # no such sibling package; pattern list is exact.
            "charmlib-pathops",  # note: singular — not a charmlibs-* match.
            "charmlibs",  # no trailing path segment.
        ],
    )
    def test_does_not_match_unrelated_packages(self, name: str) -> None:
        assert pypi_attest.is_must_have(name) is False


def _mock_urlopen(body: dict | None, *, status: int | None = None) -> mock.MagicMock:
    """Return a patched ``urlopen`` that yields *body* or an HTTPError."""
    if status is not None:
        error = urllib.error.HTTPError(
            "https://pypi.org/simple/x/", status, "nope", {}, io.BytesIO(b"")
        )
        return mock.MagicMock(side_effect=error)

    payload = json.dumps(body).encode() if body is not None else b"not json"
    response = mock.MagicMock()
    response.read.return_value = payload
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    return mock.MagicMock(return_value=response)


class TestCheckProvenance:
    def test_attested_when_file_has_provenance_url(self) -> None:
        body = {
            "files": [
                {
                    "filename": "ops-3.7.0-py3-none-any.whl",
                    "provenance": "https://pypi.org/integrity/ops/3.7.0/.../provenance",
                },
            ],
        }
        with mock.patch("pypi_attest.urllib.request.urlopen", _mock_urlopen(body)):
            result = pypi_attest.check_provenance("ops", "3.7.0")
        assert result.status is pypi_attest.ProvenanceStatus.ATTESTED
        assert result.provenance_url is not None
        assert result.name == "ops"

    def test_unattested_when_no_files_have_provenance(self) -> None:
        body = {
            "files": [
                {"filename": "foo-1.0.tar.gz", "provenance": None},
                {"filename": "foo-1.0-py3-none-any.whl"},
            ],
        }
        with mock.patch("pypi_attest.urllib.request.urlopen", _mock_urlopen(body)):
            result = pypi_attest.check_provenance("foo", "1.0")
        assert result.status is pypi_attest.ProvenanceStatus.UNATTESTED

    def test_unknown_on_http_error(self) -> None:
        with mock.patch(
            "pypi_attest.urllib.request.urlopen",
            _mock_urlopen(None, status=404),
        ):
            result = pypi_attest.check_provenance("nonexistent", "1.0")
        assert result.status is pypi_attest.ProvenanceStatus.UNKNOWN
        assert "404" in (result.detail or "")

    def test_unknown_on_network_error(self) -> None:
        err = urllib.error.URLError("connection refused")
        with mock.patch(
            "pypi_attest.urllib.request.urlopen",
            mock.MagicMock(side_effect=err),
        ):
            result = pypi_attest.check_provenance("foo", "1.0")
        assert result.status is pypi_attest.ProvenanceStatus.UNKNOWN
        assert "network error" in (result.detail or "")

    def test_unknown_on_invalid_json(self) -> None:
        with mock.patch(
            "pypi_attest.urllib.request.urlopen",
            _mock_urlopen(None),
        ):
            result = pypi_attest.check_provenance("foo", "1.0")
        assert result.status is pypi_attest.ProvenanceStatus.UNKNOWN

    def test_version_filter_narrows_files(self) -> None:
        body = {
            "files": [
                {
                    "filename": "ops-3.6.0-py3-none-any.whl",
                    "provenance": "https://pypi.org/integrity/ops/3.6.0/.../provenance",
                },
                {
                    "filename": "ops-3.7.0-py3-none-any.whl",
                    # No provenance for 3.7.0.
                },
            ],
        }
        with mock.patch("pypi_attest.urllib.request.urlopen", _mock_urlopen(body)):
            # Requesting 3.7.0 should look at only the 3.7.0 file and thus
            # report UNATTESTED even though 3.6.0 is attested.
            result = pypi_attest.check_provenance("ops", "3.7.0")
        assert result.status is pypi_attest.ProvenanceStatus.UNATTESTED

    def test_cache_avoids_repeat_network_calls(self) -> None:
        body = {
            "files": [
                {
                    "filename": "ops-3.7.0-py3-none-any.whl",
                    "provenance": "https://pypi.org/integrity/ops/3.7.0/.../provenance",
                },
            ],
        }
        with mock.patch("pypi_attest.urllib.request.urlopen", _mock_urlopen(body)) as patched:
            pypi_attest.check_provenance("ops", "3.7.0")
            pypi_attest.check_provenance("ops", "3.7.0")
            pypi_attest.check_provenance("Ops", "3.7.0")  # Normalised → same key.
        assert patched.call_count == 1

    def test_version_none_accepts_any_file(self) -> None:
        body = {
            "files": [
                {"filename": "foo-1.0.tar.gz"},
                {
                    "filename": "foo-2.0-py3-none-any.whl",
                    "provenance": "https://example/prov",
                },
            ],
        }
        with mock.patch("pypi_attest.urllib.request.urlopen", _mock_urlopen(body)):
            result = pypi_attest.check_provenance("foo")
        assert result.status is pypi_attest.ProvenanceStatus.ATTESTED
