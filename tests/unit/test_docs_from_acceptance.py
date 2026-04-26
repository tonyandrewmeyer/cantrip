"""Tests for Phase 74.2 — populating tutorial / how-to from Phase-13 +
Phase-17 acceptance artefacts (``demo/`` tree + ``ACCEPTANCE.md``).
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from cantrip.agent.tools.publishing import (
    AcceptanceArtefacts,
    GenerateDocsTool,
    generate_docs_scaffold,
    load_acceptance_artefacts,
    sanitise_capture,
)

# ===========================================================================
# Sanitiser
# ===========================================================================


class TestSanitiseCapture:
    def test_replaces_ipv4(self) -> None:
        result = sanitise_capture("Unit address: 10.1.34.193 ready")
        assert "10.1.34.193" not in result
        assert "<unit-ip>" in result

    def test_replaces_uuid(self) -> None:
        result = sanitise_capture("Model: 9bb6c7a4-12f2-4f3c-9c2e-7d3e1f3b6c8a")
        assert "9bb6c7a4" not in result
        assert "<model-uuid>" in result

    def test_replaces_k8s_fqdn(self) -> None:
        result = sanitise_capture("hello-0.hello-endpoints.test.svc.cluster.local")
        assert "svc.cluster.local" not in result
        assert "<svc-fqdn>" in result

    def test_replaces_sha256_digest(self) -> None:
        digest = "a" * 64
        result = sanitise_capture(f"Image: image@sha256:{digest}")
        assert digest not in result
        assert "<image-sha256>" in result

    def test_invalid_octets_left_alone(self) -> None:
        # 999.999.999.999 isn't a valid IPv4, so the regex shouldn't match.
        result = sanitise_capture("not-an-ip: 999.999.999.999")
        assert "999.999.999.999" in result

    def test_full_juju_status_excerpt(self) -> None:
        text = (
            "App   Version  Status   Address      Notes\n"
            "hello 1.2.3    active   192.168.1.5  ok\n"
            "Unit            Workload  Address       Ports\n"
            "hello/0*        active    10.0.0.42     8080/tcp\n"
            "Model UUID: 12345678-1234-1234-1234-123456789abc\n"
        )
        result = sanitise_capture(text)
        assert "192.168.1.5" not in result
        assert "10.0.0.42" not in result
        assert "12345678-1234-1234-1234-123456789abc" not in result
        # Version strings *with* invalid octets are left alone — but here
        # 1.2.3 is just three numbers, not IPv4-shaped, so no replacement.
        assert "1.2.3" in result
        assert result.count("<unit-ip>") == 2
        assert result.count("<model-uuid>") == 1


# ===========================================================================
# load_acceptance_artefacts
# ===========================================================================


class TestLoadAcceptanceArtefacts:
    @pytest.fixture
    def temp_charm(self):
        with tempfile.TemporaryDirectory() as td:
            yield pathlib.Path(td)

    def test_empty_charm_returns_empty(self, temp_charm) -> None:
        artefacts = load_acceptance_artefacts(temp_charm)
        assert not artefacts.is_populated
        assert artefacts.juju_status is None
        assert artefacts.action_outputs == {}
        assert not artefacts.has_acceptance_md

    def test_reads_juju_status(self, temp_charm) -> None:
        (temp_charm / "demo").mkdir()
        (temp_charm / "demo" / "juju-status.txt").write_text(
            "App  Status   Address\nhello  active  10.1.1.1  ok\n"
        )
        artefacts = load_acceptance_artefacts(temp_charm)
        assert artefacts.is_populated
        assert artefacts.juju_status is not None
        assert "10.1.1.1" not in artefacts.juju_status  # sanitised on read
        assert "<unit-ip>" in artefacts.juju_status

    def test_reads_action_outputs(self, temp_charm) -> None:
        actions_dir = temp_charm / "demo" / "actions"
        actions_dir.mkdir(parents=True)
        (actions_dir / "backup.json").write_text(
            json.dumps({"result": "ok", "snapshot": "snap-1"})
        )
        (actions_dir / "restore.json").write_text(
            json.dumps({"result": "ok", "restored-from": "snap-1"})
        )
        artefacts = load_acceptance_artefacts(temp_charm)
        assert set(artefacts.action_outputs) == {"backup", "restore"}
        assert "snap-1" in artefacts.action_outputs["backup"]

    def test_action_outputs_pretty_printed(self, temp_charm) -> None:
        actions_dir = temp_charm / "demo" / "actions"
        actions_dir.mkdir(parents=True)
        # Single-line JSON should come back pretty-printed.
        (actions_dir / "backup.json").write_text('{"result":"ok"}')
        artefacts = load_acceptance_artefacts(temp_charm)
        rendered = artefacts.action_outputs["backup"]
        assert '"result": "ok"' in rendered
        assert "\n" in rendered

    def test_invalid_json_falls_back_to_raw(self, temp_charm) -> None:
        actions_dir = temp_charm / "demo" / "actions"
        actions_dir.mkdir(parents=True)
        (actions_dir / "weird.json").write_text("not json {{{ broken")
        artefacts = load_acceptance_artefacts(temp_charm)
        assert "not json" in artefacts.action_outputs["weird"]

    def test_acceptance_md_signal(self, temp_charm) -> None:
        (temp_charm / "ACCEPTANCE.md").write_text("# Report\n")
        artefacts = load_acceptance_artefacts(temp_charm)
        assert artefacts.has_acceptance_md
        assert artefacts.is_populated

    def test_action_output_sanitised(self, temp_charm) -> None:
        actions_dir = temp_charm / "demo" / "actions"
        actions_dir.mkdir(parents=True)
        (actions_dir / "ping.json").write_text(
            json.dumps({"target": "10.0.0.1", "uuid": "12345678-1234-1234-1234-123456789abc"})
        )
        artefacts = load_acceptance_artefacts(temp_charm)
        rendered = artefacts.action_outputs["ping"]
        assert "10.0.0.1" not in rendered
        assert "12345678" not in rendered
        assert "<unit-ip>" in rendered
        assert "<model-uuid>" in rendered


# ===========================================================================
# Scaffold integration
# ===========================================================================


_SAMPLE_METADATA = {
    "name": "hello",
    "display-name": "Hello",
    "summary": "A greeting service.",
    "config": {"options": {"port": {"type": "int", "default": 8080}}},
    "actions": {
        "backup": {"description": "Snapshot data."},
        "restore": {"description": "Restore from a snapshot."},
    },
    "requires": {"db": {"interface": "pgsql"}},
}


def _populated_artefacts() -> AcceptanceArtefacts:
    return AcceptanceArtefacts(
        juju_status=("App    Status   Address      Notes\nhello  active   <unit-ip>    ok\n"),
        action_outputs={
            "backup": '{\n  "result": "ok",\n  "snapshot": "snap-1"\n}',
        },
        has_acceptance_md=True,
    )


class TestScaffoldArtefactPopulation:
    def test_no_artefacts_uses_stub_marker(self) -> None:
        files = generate_docs_scaffold("hello", _SAMPLE_METADATA)
        tutorial = files["docs/tutorial/getting-started.md"]
        # The stub fallback notice gets prepended when acceptance hasn't run.
        assert "templated" in tutorial.lower()
        assert "acceptance_report" in tutorial

    def test_artefacts_replace_tutorial(self) -> None:
        files = generate_docs_scaffold(
            "hello", _SAMPLE_METADATA, acceptance=_populated_artefacts()
        )
        tutorial = files["docs/tutorial/getting-started.md"]
        # The artefact-driven tutorial reads as a real walkthrough — no stub
        # marker, no `juju wait-for application` boilerplate from the stub.
        assert "templated" not in tutorial.lower()
        assert "juju wait-for application" not in tutorial
        assert "$ juju add-model hello" in tutorial
        assert "$ juju deploy hello" in tutorial
        assert "$ juju status" in tutorial
        # Real captured status excerpt is embedded.
        assert "App    Status" in tutorial

    def test_artefacts_add_deploy_and_verify(self) -> None:
        files = generate_docs_scaffold(
            "hello", _SAMPLE_METADATA, acceptance=_populated_artefacts()
        )
        assert "docs/how-to/deploy-and-verify.md" in files
        page = files["docs/how-to/deploy-and-verify.md"]
        assert page.startswith("# Deploy and verify Hello\n")
        assert "$ juju add-model hello" in page
        assert "$ juju deploy hello" in page
        assert "$ juju integrate hello:db" in page

    def test_artefacts_replace_actions_with_captured_output(self) -> None:
        files = generate_docs_scaffold(
            "hello", _SAMPLE_METADATA, acceptance=_populated_artefacts()
        )
        actions_page = files["docs/how-to/actions.md"]
        assert "## `backup`" in actions_page
        assert "## `restore`" in actions_page
        # Captured backup output is embedded; restore has no captured output
        # but its section is still present.
        assert "snap-1" in actions_page
        # No stub marker on the populated page.
        assert "templated" not in actions_page.lower()

    def test_howto_index_includes_deploy_and_verify_when_populated(self) -> None:
        files = generate_docs_scaffold(
            "hello", _SAMPLE_METADATA, acceptance=_populated_artefacts()
        )
        index = files["docs/how-to/index.md"]
        assert "deploy-and-verify" in index

    def test_howto_index_omits_deploy_and_verify_without_artefacts(self) -> None:
        files = generate_docs_scaffold("hello", _SAMPLE_METADATA)
        index = files["docs/how-to/index.md"]
        assert "deploy-and-verify" not in index

    def test_bridged_root_files_win_over_artefacts(self) -> None:
        # If TUTORIAL.md was bridged in 74.1, the bridged content takes
        # precedence over the artefact-derived tutorial.
        files = generate_docs_scaffold(
            "hello",
            _SAMPLE_METADATA,
            root_files={"TUTORIAL.md": "# Walk\n\nAuthored by the agent.\n"},
            acceptance=_populated_artefacts(),
        )
        tutorial = files["docs/tutorial/getting-started.md"]
        assert "Authored by the agent." in tutorial
        # The artefact-derived tutorial would have included `$ juju add-model`
        # — the bridged content doesn't.
        assert "$ juju add-model" not in tutorial

    def test_no_tutorial_status_block_when_status_missing(self) -> None:
        # An artefact bundle with only ACCEPTANCE.md as a signal — no
        # captured juju status — shouldn't pretend to have a status excerpt.
        artefacts = AcceptanceArtefacts(has_acceptance_md=True)
        files = generate_docs_scaffold("hello", _SAMPLE_METADATA, acceptance=artefacts)
        tutorial = files["docs/tutorial/getting-started.md"]
        assert "## Verify the deployment" not in tutorial
        assert "$ juju add-model hello" in tutorial


# ===========================================================================
# GenerateDocsTool end-to-end
# ===========================================================================


class TestGenerateDocsToolWithArtefacts:
    @pytest.fixture
    def tool(self) -> GenerateDocsTool:
        return GenerateDocsTool()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            yield pathlib.Path(td)

    @pytest.mark.asyncio
    async def test_no_artefacts_keeps_stub_with_marker(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: hello\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["acceptance_populated"] is False
        tutorial = (temp_dir / "docs" / "tutorial" / "getting-started.md").read_text()
        assert "templated" in tutorial.lower()

    @pytest.mark.asyncio
    async def test_demo_artefacts_drive_tutorial(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text(
            "name: hello\nactions:\n  backup:\n    description: Snapshot.\n"
        )
        demo = temp_dir / "demo"
        (demo / "actions").mkdir(parents=True)
        (demo / "juju-status.txt").write_text(
            "App    Status   Address    Notes\nhello  active   10.0.0.5   ok\n"
        )
        (demo / "actions" / "backup.json").write_text(
            json.dumps({"result": "ok", "snapshot": "snap-42"})
        )

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["acceptance_populated"] is True
        tutorial = (temp_dir / "docs" / "tutorial" / "getting-started.md").read_text()
        assert "$ juju deploy hello" in tutorial
        assert "$ juju status" in tutorial
        # Real status with IP sanitised.
        assert "10.0.0.5" not in tutorial
        assert "<unit-ip>" in tutorial
        actions_page = (temp_dir / "docs" / "how-to" / "actions.md").read_text()
        assert "snap-42" in actions_page

    @pytest.mark.asyncio
    async def test_acceptance_md_alone_signals_populated(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: hello\n")
        (temp_dir / "ACCEPTANCE.md").write_text("# Acceptance\n\nAll passed.\n")

        result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["acceptance_populated"] is True
        tutorial = (temp_dir / "docs" / "tutorial" / "getting-started.md").read_text()
        # No demo/juju-status.txt → no status excerpt section.
        assert "## Verify the deployment" not in tutorial
        # But still no stub marker.
        assert "templated" not in tutorial.lower()

    @pytest.mark.asyncio
    async def test_bridged_tutorial_wins_over_artefacts(self, tool, temp_dir) -> None:
        (temp_dir / "charmcraft.yaml").write_text("name: hello\n")
        (temp_dir / "TUTORIAL.md").write_text("# Tutorial\n\nAuthored.\n")
        (temp_dir / "demo").mkdir()
        (temp_dir / "demo" / "juju-status.txt").write_text("status text\n")

        await tool.execute(path=str(temp_dir))

        tutorial = (temp_dir / "docs" / "tutorial" / "getting-started.md").read_text()
        assert "Authored." in tutorial
        assert "$ juju status" not in tutorial
