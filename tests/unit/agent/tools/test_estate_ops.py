"""Tests for the estate-operations (Ubuntu Pro / Landscape) detector.

Covers the substrate gating rule (k8s without estate hints stays
silent), the evidence wiring on each opportunity, the level escalation
when storage / peers / sensitive relations are declared, the already-
mentioned promotion when README/docs reference the product, the K8s
host-coverage carve-out, and the report-rendering helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from cantrip.agent.tools.estate_ops import (
    EstateOpportunity,
    _detect_substrate,
    _scan_text_for_tokens,
    assess_estate_opportunities,
    render_estate_section,
)

if TYPE_CHECKING:
    import pathlib


def _facets(opps: list[EstateOpportunity], product: str) -> set[str]:
    return {o.facet for o in opps if o.product == product}


def _by_facet(opps: list[EstateOpportunity], facet: str) -> EstateOpportunity:
    matches = [o for o in opps if o.facet == facet]
    assert len(matches) == 1, f"expected exactly one {facet}, got {matches}"
    return matches[0]


class TestDetectSubstrate:
    def test_containers_block_is_k8s(self) -> None:
        assert _detect_substrate({"containers": {"workload": {}}}) == "k8s"

    def test_bases_block_is_machine(self) -> None:
        assert _detect_substrate({"bases": [{"name": "ubuntu", "channel": "22.04"}]}) == "machine"

    def test_platforms_block_is_machine(self) -> None:
        assert _detect_substrate({"platforms": {"ubuntu@22.04:amd64": None}}) == "machine"

    def test_empty_containers_falls_through(self) -> None:
        assert _detect_substrate({"containers": {}}) == "unknown"

    def test_empty_metadata_is_unknown(self) -> None:
        assert _detect_substrate({}) == "unknown"


class TestScanTextForTokens:
    def test_multi_word_token_matches_substring(self) -> None:
        assert "ubuntu pro" in _scan_text_for_tokens("Try Ubuntu Pro today.", ("ubuntu pro",))

    def test_hyphenated_token_matches_substring(self) -> None:
        assert "esm-apps" in _scan_text_for_tokens("install esm-apps", ("esm-apps",))

    def test_single_word_uses_word_boundary(self) -> None:
        assert _scan_text_for_tokens("flips out", ("fips",)) == []

    def test_single_word_matches_on_boundary(self) -> None:
        assert _scan_text_for_tokens("requires FIPS modules", ("fips",)) == ["fips"]

    def test_empty_text_returns_empty(self) -> None:
        assert _scan_text_for_tokens("", ("fips",)) == []


class TestMachineCharmRecommendations:
    """Machine substrate is the bread-and-butter Pro/Landscape case."""

    def _meta(self, **extra: Any) -> dict[str, Any]:
        base = {"bases": [{"name": "ubuntu", "channel": "22.04"}]}
        base.update(extra)
        return base

    def test_bare_machine_charm_emits_esm_and_livepatch_and_landscape(
        self, tmp_path: pathlib.Path
    ) -> None:
        opps = assess_estate_opportunities(tmp_path, self._meta())
        pro = _facets(opps, "Ubuntu Pro")
        landscape = _facets(opps, "Landscape")
        assert "esm-security-maintenance" in pro
        assert "livepatch" in pro
        assert "fleet-patching" in landscape
        # No sensitive relations, no peers — FIPS/USG should stay quiet.
        assert "fips-compliance" not in pro
        assert "usg-hardening" not in pro

    def test_stateful_charm_promotes_esm_to_recommended(self, tmp_path: pathlib.Path) -> None:
        meta = self._meta(storage={"data": {"type": "filesystem"}})
        opp = _by_facet(
            assess_estate_opportunities(tmp_path, meta),
            "esm-security-maintenance",
        )
        assert opp.level == "recommended"
        assert "stateful (storage declared)" in opp.evidence

    def test_clustered_charm_promotes_livepatch_and_fleet_patching(
        self, tmp_path: pathlib.Path
    ) -> None:
        meta = self._meta(peers={"cluster": {"interface": "myapp-peers"}})
        opps = assess_estate_opportunities(tmp_path, meta)
        livepatch = _by_facet(opps, "livepatch")
        fleet = _by_facet(opps, "fleet-patching")
        access = _by_facet(opps, "access-management")
        assert livepatch.level == "recommended"
        assert fleet.level == "recommended"
        assert access.level == "consider"
        for opp in (livepatch, fleet, access):
            assert "clustered (peer relation declared)" in opp.evidence

    def test_tls_relation_adds_fips_and_usg_consider(self, tmp_path: pathlib.Path) -> None:
        meta = self._meta(
            requires={"certs": {"interface": "tls-certificates"}},
        )
        opps = assess_estate_opportunities(tmp_path, meta)
        fips = _by_facet(opps, "fips-compliance")
        usg = _by_facet(opps, "usg-hardening")
        compliance = _by_facet(opps, "compliance-reporting")
        assert fips.level == "consider"
        assert usg.level == "consider"
        assert compliance.level == "consider"
        # Evidence cites the sensitive-relation trigger.
        assert any("TLS or identity" in e for e in fips.evidence)

    def test_identity_platform_relation_counts_as_sensitive(self, tmp_path: pathlib.Path) -> None:
        meta = self._meta(requires={"oidc": {"interface": "oauth"}})
        opps = assess_estate_opportunities(tmp_path, meta)
        assert "fips-compliance" in _facets(opps, "Ubuntu Pro")


class TestK8sCharmGating:
    """K8s charms stay silent unless the repo already discusses estate ops."""

    def test_pure_k8s_with_no_mentions_returns_empty(self, tmp_path: pathlib.Path) -> None:
        meta: dict[str, Any] = {"containers": {"workload": {"resource": "oci"}}}
        assert assess_estate_opportunities(tmp_path, meta) == []

    def test_k8s_with_pro_mention_emits_host_coverage_reinforcement(
        self, tmp_path: pathlib.Path
    ) -> None:
        (tmp_path / "README.md").write_text(
            "## Operating\n\nWe recommend Ubuntu Pro on the cluster hosts."
        )
        meta: dict[str, Any] = {"containers": {"workload": {"resource": "oci"}}}
        opps = assess_estate_opportunities(tmp_path, meta)
        assert len(opps) == 1
        opp = opps[0]
        assert opp.product == "Ubuntu Pro"
        assert opp.facet == "host-coverage"
        assert opp.level == "already-mentioned"
        assert any(e == "mention:ubuntu pro" for e in opp.evidence)

    def test_k8s_with_landscape_mention_emits_host_coverage_reinforcement(
        self, tmp_path: pathlib.Path
    ) -> None:
        (tmp_path / "README.md").write_text("We patch hosts via Landscape.")
        meta: dict[str, Any] = {"containers": {"workload": {"resource": "oci"}}}
        opps = assess_estate_opportunities(tmp_path, meta)
        landscape = [o for o in opps if o.product == "Landscape"]
        assert len(landscape) == 1
        assert landscape[0].facet == "host-coverage"
        assert landscape[0].level == "already-mentioned"


class TestAlreadyMentionedPromotion:
    """When README/docs reference Pro/Landscape, level flips to already-mentioned."""

    def test_pro_mention_in_readme_promotes_all_pro_entries(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "README.md").write_text(
            "Configure ESM-Apps and Livepatch on production hosts."
        )
        meta = {"bases": [{"name": "ubuntu", "channel": "22.04"}]}
        opps = assess_estate_opportunities(tmp_path, meta)
        for opp in opps:
            if opp.product == "Ubuntu Pro":
                assert opp.level == "already-mentioned", opp

    def test_landscape_mention_in_docs_dir_promotes_landscape_entries(
        self, tmp_path: pathlib.Path
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "operating.md").write_text("Estate-wide patching is handled by Landscape.")
        meta = {"bases": [{"name": "ubuntu", "channel": "22.04"}]}
        opps = assess_estate_opportunities(tmp_path, meta)
        for opp in opps:
            if opp.product == "Landscape":
                assert opp.level == "already-mentioned", opp

    def test_pro_mention_in_metadata_summary_is_detected(self, tmp_path: pathlib.Path) -> None:
        meta = {
            "bases": [{"name": "ubuntu", "channel": "22.04"}],
            "summary": "A FIPS-aware charm for regulated estates.",
        }
        opps = assess_estate_opportunities(tmp_path, meta)
        assert all(opp.level == "already-mentioned" for opp in opps if opp.product == "Ubuntu Pro")


class TestRenderEstateSection:
    def test_empty_opportunities_returns_empty_lines(self) -> None:
        assert render_estate_section([]) == []

    def test_renders_grouped_by_product(self) -> None:
        opps = [
            EstateOpportunity(
                product="Ubuntu Pro",
                facet="esm-security-maintenance",
                level="recommended",
                rationale="Long-running workload.",
                evidence=("substrate=machine",),
            ),
            EstateOpportunity(
                product="Landscape",
                facet="fleet-patching",
                level="consider",
                rationale="Multi-unit deployment.",
                evidence=("substrate=machine",),
            ),
        ]
        body = "\n".join(render_estate_section(opps))
        assert "## Estate Operations" in body
        assert "### Ubuntu Pro" in body
        assert "### Landscape" in body
        assert "[recommended] esm-security-maintenance" in body
        assert "[consider] fleet-patching" in body
        # The required-vs-recommended preamble must be present so the
        # reader never confuses estate advice with a charm requirement.
        assert "not required for the charm to work" in body

    def test_skips_product_with_no_entries(self) -> None:
        opps = [
            EstateOpportunity(
                product="Landscape",
                facet="fleet-patching",
                level="consider",
                rationale="x",
                evidence=(),
            )
        ]
        body = "\n".join(render_estate_section(opps))
        assert "### Ubuntu Pro" not in body
        assert "### Landscape" in body


class TestOpportunityToDict:
    def test_round_trips_to_json_shape(self) -> None:
        opp = EstateOpportunity(
            product="Ubuntu Pro",
            facet="livepatch",
            level="recommended",
            rationale="Kernel CVEs without reboot.",
            evidence=("substrate=machine", "clustered"),
        )
        data = opp.to_dict()
        assert data == {
            "product": "Ubuntu Pro",
            "facet": "livepatch",
            "level": "recommended",
            "rationale": "Kernel CVEs without reboot.",
            "evidence": ["substrate=machine", "clustered"],
        }


class TestUnknownSubstrate:
    """An incomplete charmcraft.yaml (no containers / bases / platforms)
    should not silently swallow recommendations — the operator might
    add bases later and the agent should still see the advice."""

    def test_unknown_substrate_still_emits_advisories(self, tmp_path: pathlib.Path) -> None:
        opps = assess_estate_opportunities(tmp_path, {"name": "test"})
        assert any(o.product == "Ubuntu Pro" for o in opps)
        assert any(o.product == "Landscape" for o in opps)


@pytest.mark.parametrize(
    "level",
    ["recommended", "consider", "already-mentioned"],
)
def test_level_values_are_stable(level: str) -> None:
    """The three level values are public contract — pin them.

    Downstream consumers (the agent's improvement summary, future
    audit-output templates, structured-output schemas) treat these
    strings as a closed set; introducing a fourth value silently
    would break the existing wording in the skill.
    """
    opp = EstateOpportunity(
        product="Ubuntu Pro",
        facet="x",
        level=level,
        rationale="r",
        evidence=(),
    )
    assert opp.to_dict()["level"] == level
