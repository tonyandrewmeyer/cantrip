"""Unit coverage for the pure-function helpers in ``tests/e2e/harness.py``.

The live e2e tests that depend on the harness only run when
``GEMINI_API_KEY`` and a Juju controller are available — which means the
prompt-building, nudge-selection and workspace-seeding logic would
otherwise be completely uncovered in CI.  These tests fill that gap
without needing an API key or juju.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.e2e import harness, seeds

# ---------------------------------------------------------------------------
# Workspace seeding
# ---------------------------------------------------------------------------


class TestSeedWorkspace:
    def test_writes_all_files_with_nested_dirs(self, tmp_path: pathlib.Path) -> None:
        workspace = tmp_path / "work"
        harness.seed_workspace(workspace, seeds.DJANGO)

        assert (workspace / "manage.py").is_file()
        assert (workspace / "djangodemo" / "settings.py").is_file()
        assert (workspace / "djangodemo" / "__init__.py").is_file()

    def test_idempotent_when_workspace_exists(self, tmp_path: pathlib.Path) -> None:
        workspace = tmp_path / "work"
        workspace.mkdir()
        (workspace / "preexisting.txt").write_text("keep me")

        harness.seed_workspace(workspace, {"new.txt": "hello"})

        assert (workspace / "preexisting.txt").read_text() == "keep me"
        assert (workspace / "new.txt").read_text() == "hello"


# ---------------------------------------------------------------------------
# Prompt routing
# ---------------------------------------------------------------------------


class TestInitialPrompt:
    def test_paas_prompt_mentions_full_rockcraft_pipeline(self) -> None:
        spec = harness.CharmSpec(
            name="flask-demo",
            profile="flask-framework",
            substrate="k8s",
            seed_files=seeds.FLASK,
        )
        prompt = harness.initial_prompt(spec, "ctrl:m1")

        assert "rockcraft_pack" in prompt
        assert "skopeo_registry_push" in prompt
        assert "charmcraft_pack" in prompt
        assert "ctrl:m1" in prompt

    def test_prebuilt_image_prompt_skips_rockcraft(self) -> None:
        spec = harness.CharmSpec(
            name="go-demo",
            profile="go-framework",
            substrate="k8s",
            seed_files=seeds.GO,
            prebuilt_oci_image="ghcr.io/example/x:latest",
        )
        prompt = harness.initial_prompt(spec, "ctrl:m1")

        assert "ghcr.io/example/x:latest" in prompt
        assert "Do NOT" in prompt
        assert "rockcraft_pack" not in prompt.split("Do NOT")[0].replace("\n", " "), (
            "prebuilt-image prompt should not ask the agent to run rockcraft_pack"
        )

    def test_machine_prompt_avoids_oci_language(self) -> None:
        spec = harness.CharmSpec(
            name="hm",
            profile="machine",
            substrate="machine",
            seed_files=seeds.MACHINE,
        )
        prompt = harness.initial_prompt(spec, "lxd:m1")

        assert "machine charm" in prompt.lower()
        assert "rockcraft" not in prompt.lower()
        # OCI is mentioned only to tell the agent NOT to build one.
        assert "do not build an oci image" in prompt.lower()
        assert "lxd:m1" in prompt

    def test_model_clause_omitted_when_no_model(self) -> None:
        spec = harness.CharmSpec(
            name="x",
            profile="flask-framework",
            substrate="k8s",
            seed_files={},
        )
        prompt = harness.initial_prompt(spec, None)
        assert "Do NOT create a new model" not in prompt


# ---------------------------------------------------------------------------
# Nudge routing
# ---------------------------------------------------------------------------


_EMPTY = harness.BuildProgress(
    has_charm=False,
    has_rock=False,
    has_pushed=False,
    has_deploy_call=False,
    app_in_model=False,
)
_ROCK_BUILT = harness.BuildProgress(
    has_charm=False,
    has_rock=True,
    has_pushed=False,
    has_deploy_call=False,
    app_in_model=False,
)
_CHARM_PACKED = harness.BuildProgress(
    has_charm=True,
    has_rock=True,
    has_pushed=True,
    has_deploy_call=False,
    app_in_model=False,
)
_DEPLOYED_NO_PUSH = harness.BuildProgress(
    has_charm=True,
    has_rock=False,
    has_pushed=False,
    has_deploy_call=True,
    app_in_model=False,
)


class TestPaasNudge:
    def test_empty_progress_mentions_full_pipeline(self) -> None:
        nudge = harness.paas_nudge(_EMPTY, "m")
        assert "rockcraft_pack" in nudge
        assert "skopeo_registry_push" in nudge

    def test_rock_only_tells_agent_to_push(self) -> None:
        nudge = harness.paas_nudge(_ROCK_BUILT, "m")
        assert "skopeo_registry_push" in nudge
        assert "rock is built" in nudge.lower()

    def test_charm_packed_tells_agent_to_deploy(self) -> None:
        nudge = harness.paas_nudge(_CHARM_PACKED, "m")
        assert "deploy" in nudge.lower()
        assert "oci-image" in nudge.lower()

    def test_deploy_without_push_redirects_to_push(self) -> None:
        nudge = harness.paas_nudge(_DEPLOYED_NO_PUSH, "ctrl:x")
        assert "skopeo_registry_push" in nudge
        assert "ctrl:x" in nudge


class TestPrebuiltImageNudge:
    def test_pre_pack_tells_agent_to_pack_then_deploy(self) -> None:
        spec = harness.CharmSpec(
            name="go-demo",
            profile="go-framework",
            substrate="k8s",
            seed_files={},
            prebuilt_oci_image="img:tag",
        )
        nudge = harness.follow_up_prompt(spec, _EMPTY, "ctrl:m1")

        assert "charmcraft_pack" in nudge
        assert "img:tag" in nudge
        assert "Skip rockcraft_pack" in nudge

    def test_charm_packed_tells_agent_to_deploy_with_image(self) -> None:
        spec = harness.CharmSpec(
            name="go-demo",
            profile="go-framework",
            substrate="k8s",
            seed_files={},
            prebuilt_oci_image="img:tag",
        )
        nudge = harness.follow_up_prompt(spec, _CHARM_PACKED, "ctrl:m1")

        assert "img:tag" in nudge
        assert "do not build a rock" in nudge.lower()


class TestMachineNudge:
    def test_pre_pack_tells_agent_to_pack(self) -> None:
        spec = harness.CharmSpec(
            name="hm",
            profile="machine",
            substrate="machine",
            seed_files={},
        )
        nudge = harness.follow_up_prompt(spec, _EMPTY, "lxd:m1")

        assert "charmcraft_pack" in nudge
        assert "Do NOT build a rock" in nudge

    def test_charm_packed_tells_agent_to_deploy_without_resources(self) -> None:
        spec = harness.CharmSpec(
            name="hm",
            profile="machine",
            substrate="machine",
            seed_files={},
        )
        nudge = harness.follow_up_prompt(spec, _CHARM_PACKED, "lxd:m1")

        assert "machine model" in nudge.lower()
        assert "no resources" in nudge.lower()


# ---------------------------------------------------------------------------
# find_deployed_app
# ---------------------------------------------------------------------------


class TestFindDeployedApp:
    def test_prefers_call_with_explicit_model(self) -> None:
        calls = [
            {"charm": "./x_amd64.charm"},
            {"charm": "./y_amd64.charm", "model": "m1", "app_name": "y-app"},
        ]
        name, model = harness.find_deployed_app(calls)
        assert name == "y-app"
        assert model == "m1"

    def test_falls_back_to_last_when_no_model_given(self) -> None:
        calls = [
            {"charm": "./a_amd64.charm"},
            {"charm": "./b_amd64.charm"},
        ]
        name, model = harness.find_deployed_app(calls)
        assert name == "b"
        assert model is None

    def test_handles_empty_list(self) -> None:
        name, model = harness.find_deployed_app([])
        assert name == "unknown"
        assert model is None

    def test_derives_name_from_charm_path(self) -> None:
        assert harness.derive_app_name({"charm": "./my-app_amd64.charm"}) == "my-app"
        assert harness.derive_app_name({"charm": "my-app", "app_name": "explicit"}) == "explicit"


# ---------------------------------------------------------------------------
# Provider factory skipping behaviour
# ---------------------------------------------------------------------------


class TestMakeProvider:
    def test_missing_key_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("CANTRIP_E2E_PROVIDER", raising=False)
        with pytest.raises(pytest.skip.Exception):
            harness.make_provider("gemini")

    def test_env_override_selects_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``CANTRIP_E2E_PROVIDER=claude`` makes gemini-wired tests use Claude."""
        monkeypatch.setenv("CANTRIP_E2E_PROVIDER", "claude")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Keep GEMINI set so we can tell the env var is what's being honoured.
        monkeypatch.setenv("GEMINI_API_KEY", "unused")
        with pytest.raises(pytest.skip.Exception) as exc_info:
            harness.make_provider("gemini")
        assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    def test_unknown_provider_skips_with_clear_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANTRIP_E2E_PROVIDER", "not-a-real-provider")
        with pytest.raises(pytest.skip.Exception) as exc_info:
            harness.make_provider("gemini")
        assert "not-a-real-provider" in str(exc_info.value)
