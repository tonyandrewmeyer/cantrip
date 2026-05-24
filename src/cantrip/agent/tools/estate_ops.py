"""Estate-operations opportunity detection — Ubuntu Pro and Landscape.

Phase 98 surfaces Canonical's two estate-shaped products (Ubuntu Pro
for security maintenance / compliance posture / supply-chain hardening,
and Landscape for fleet management / patch orchestration / access
management) as **day-2 advice** that flows alongside the existing
must-fix / should-fix findings from
:mod:`cantrip.agent.tools.operational_readiness`.

The contract is deliberately conservative:

* Recommendations are **evidence-driven** — every opportunity carries
  the observed signals that justified it.  No blanket upsell.
* Recommendations are **estate-level**, never required for the charm
  to work.  Wording calls that out explicitly so a reader can't
  mistake them for a charm bug.
* The detector is **read-only** — it inspects already-loaded metadata,
  README/docs text, and Python source.  No shell-outs, no network.

The detector returns an empty list when the charm is a pure-Kubernetes
workload with no signals that estate operations would help, so the
``Estate Operations`` section disappears entirely from the readiness
report rather than nagging the reader.
"""

from __future__ import annotations

import contextlib
import dataclasses
import pathlib
import re
from typing import Any

# Tokens that indicate the repo already documents Ubuntu Pro adoption.
# Matched case-insensitively against README + docs + charm metadata.
PRO_MENTION_TOKENS: tuple[str, ...] = (
    "ubuntu pro",
    "ubuntu advantage",
    "pro attach",
    "ua attach",
    "ua-client",
    "esm-apps",
    "esm-infra",
    "esm apps",
    "esm infra",
    "livepatch",
    "fips",
    "usg",
    "cis benchmark",
)

# Tokens that indicate the repo already documents Landscape adoption.
LANDSCAPE_MENTION_TOKENS: tuple[str, ...] = (
    "landscape-client",
    "landscape-server",
    "landscape-broker",
    "landscape-common",
    "landscape",
)


@dataclasses.dataclass(frozen=True)
class EstateOpportunity:
    """A single Pro / Landscape recommendation for the operator.

    ``product`` is the human-readable name of the Canonical product
    being recommended.  ``facet`` is a stable identifier (used in
    structured output and in tests) for the *type* of recommendation
    — e.g. ``esm-security-maintenance``, ``fleet-patching``.

    ``level`` is one of:

    * ``recommended`` — strong evidence the workload benefits.
    * ``consider`` — weaker but still relevant; the operator should
      weigh it against their estate posture.
    * ``already-mentioned`` — the repo already references this facet;
      surface the existing reference so the agent can reinforce or
      validate it rather than recommending it from scratch.

    ``rationale`` is a one-sentence explanation written for the
    operator.  ``evidence`` lists the observed signals so the reader
    can audit the recommendation.
    """

    product: str
    facet: str
    level: str
    rationale: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "facet": self.facet,
            "level": self.level,
            "rationale": self.rationale,
            "evidence": list(self.evidence),
        }


def _detect_substrate(metadata: dict[str, Any]) -> str:
    """Return ``"k8s"``, ``"machine"``, or ``"unknown"``.

    A ``containers:`` section unambiguously means k8s.  Otherwise we
    treat the presence of ``bases:`` / ``platforms:`` as a machine
    substrate, since charmcraft requires one or the other.  When
    neither is present the charm metadata is incomplete and we
    return ``unknown`` rather than guess.
    """
    if isinstance(metadata.get("containers"), dict) and metadata["containers"]:
        return "k8s"
    if metadata.get("bases") or metadata.get("platforms"):
        return "machine"
    return "unknown"


def _has_storage(metadata: dict[str, Any]) -> bool:
    """Stateful-charm signal — declared storage means persistent data."""
    storage = metadata.get("storage")
    return isinstance(storage, dict) and bool(storage)


def _has_peers(metadata: dict[str, Any]) -> bool:
    """Multi-unit signal — peer relations imply HA / clustering."""
    peers = metadata.get("peers")
    return isinstance(peers, dict) and bool(peers)


def _has_tls_or_identity(metadata: dict[str, Any]) -> bool:
    """Security-sensitive signal — TLS or identity-platform relations."""
    relations: dict[str, Any] = {}
    for section in ("requires", "provides"):
        section_data = metadata.get(section)
        if isinstance(section_data, dict):
            relations.update(section_data)

    sensitive_interfaces = {
        "tls-certificates",
        "certificates",
        "oauth",
        "oauth-cli",
        "hydra-token-introspect",
        "oidc-info",
        "vault-kv",
    }
    return any(
        isinstance(rel, dict) and rel.get("interface") in sensitive_interfaces
        for rel in relations.values()
    )


def _scan_text_for_tokens(haystack: str, tokens: tuple[str, ...]) -> list[str]:
    """Return matched tokens (lowercased) found in *haystack*.

    Token matching uses word-ish boundaries so ``fips`` doesn't
    spuriously fire on ``flips``; multi-word tokens are matched
    literally because spaces already act as boundaries.
    """
    if not haystack:
        return []
    text = haystack.lower()
    matched: list[str] = []
    for token in tokens:
        token_lower = token.lower()
        if " " in token_lower or "-" in token_lower:
            # Multi-word / hyphenated — spaces and hyphens act as
            # boundaries already, so a substring match is fine.
            if token_lower in text:
                matched.append(token_lower)
            continue
        # Single-word tokens use a word boundary check.
        if re.search(rf"\b{re.escape(token_lower)}\b", text):
            matched.append(token_lower)
    return matched


def _collect_docs_text(charm_dir: pathlib.Path) -> str:
    """Concatenate README + docs/*.md text for token scanning."""
    chunks: list[str] = []
    readme = charm_dir / "README.md"
    if readme.is_file():
        with contextlib.suppress(OSError):
            chunks.append(readme.read_text(errors="replace"))
    docs_dir = charm_dir / "docs"
    if docs_dir.is_dir():
        for path in docs_dir.rglob("*.md"):
            with contextlib.suppress(OSError):
                chunks.append(path.read_text(errors="replace"))
    return "\n".join(chunks)


def _collect_metadata_text(metadata: dict[str, Any]) -> str:
    """Pull free-text metadata fields (summary, description) for scanning."""
    parts: list[str] = []
    for key in ("summary", "description", "title"):
        value = metadata.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def assess_estate_opportunities(
    charm_dir: pathlib.Path,
    metadata: dict[str, Any],
) -> list[EstateOpportunity]:
    """Return Ubuntu Pro / Landscape opportunities for this charm.

    The function inspects only material already on disk — charmcraft
    metadata, README, ``docs/`` markdown.  It emits opportunities only
    when the signals justify it; a pure k8s workload with no security-
    sensitive relations and no estate hints returns an empty list.

    Detection logic, in plain English:

    * **Substrate** decides whether *any* Pro/Landscape recommendation
      makes sense.  Pro/Landscape both operate on Ubuntu hosts, so
      machine charms qualify by default and k8s charms only qualify
      when the operator has already brought them up.
    * **Stateful** (declared storage) or **clustered** (peer relations)
      machine charms warrant ESM and Livepatch — kernel CVEs and
      package CVEs are the failure modes that bite long-running
      services hardest.
    * **Security-sensitive** charms (TLS, OAuth/OIDC, vault-kv) warrant
      FIPS and CIS-hardening *consider* notes — compliance regimes
      tend to require both.
    * **Multi-unit** (peer relations or multiple deploy targets) machine
      charms warrant Landscape fleet patching — orchestrating apt
      updates across N machines is exactly what Landscape exists to do.
    * **Already-mentioned** tokens in README/docs/metadata flip the
      level from ``recommended`` / ``consider`` to ``already-mentioned``
      so the agent reinforces existing documentation rather than
      proposing a duplicate.
    """
    substrate = _detect_substrate(metadata)
    docs_text = _collect_docs_text(charm_dir)
    metadata_text = _collect_metadata_text(metadata)
    combined = f"{docs_text}\n{metadata_text}"

    pro_mentions = _scan_text_for_tokens(combined, PRO_MENTION_TOKENS)
    landscape_mentions = _scan_text_for_tokens(combined, LANDSCAPE_MENTION_TOKENS)

    opportunities: list[EstateOpportunity] = []

    # K8s-only charm with no estate-shaped signals: stay silent.
    is_machine = substrate == "machine"
    is_unknown_substrate = substrate == "unknown"
    if substrate == "k8s" and not (pro_mentions or landscape_mentions):
        return []

    stateful = _has_storage(metadata)
    clustered = _has_peers(metadata)
    sensitive = _has_tls_or_identity(metadata)

    # -----------------------------------------------------------------
    # Ubuntu Pro opportunities
    # -----------------------------------------------------------------

    if is_machine or is_unknown_substrate:
        evidence: list[str] = [f"substrate={substrate}"]
        if stateful:
            evidence.append("stateful (storage declared)")
        if clustered:
            evidence.append("clustered (peer relation declared)")

        opportunities.append(
            EstateOpportunity(
                product="Ubuntu Pro",
                facet="esm-security-maintenance",
                level=_promote_to_already_mentioned(
                    "recommended" if (stateful or clustered) else "consider",
                    pro_mentions,
                ),
                rationale=(
                    "ESM-Apps and ESM-Infra extend security maintenance "
                    "for the workload's Ubuntu base beyond the standard "
                    "five-year LTS window, which matters most for long-"
                    "running stateful services."
                ),
                evidence=tuple(evidence),
            )
        )

        opportunities.append(
            EstateOpportunity(
                product="Ubuntu Pro",
                facet="livepatch",
                level=_promote_to_already_mentioned(
                    "recommended" if clustered else "consider",
                    pro_mentions,
                ),
                rationale=(
                    "Livepatch applies kernel CVE fixes without a "
                    "reboot, preserving uptime for clustered or "
                    "availability-sensitive workloads."
                ),
                evidence=tuple(evidence),
            )
        )

    if (is_machine or is_unknown_substrate) and sensitive:
        opportunities.append(
            EstateOpportunity(
                product="Ubuntu Pro",
                facet="fips-compliance",
                level=_promote_to_already_mentioned("consider", pro_mentions),
                rationale=(
                    "FIPS-validated crypto modules are a hard "
                    "requirement in several regulated environments "
                    "(US federal, healthcare, finance).  The charm "
                    "handles TLS or identity data, so the operator "
                    "may need a FIPS-compliant Ubuntu base."
                ),
                evidence=(f"substrate={substrate}", "TLS or identity relation declared"),
            )
        )
        opportunities.append(
            EstateOpportunity(
                product="Ubuntu Pro",
                facet="usg-hardening",
                level=_promote_to_already_mentioned("consider", pro_mentions),
                rationale=(
                    "USG (Ubuntu Security Guide) automates CIS / DISA-STIG "
                    "hardening on the host.  Worth flagging for operators "
                    "whose estate carries a compliance obligation."
                ),
                evidence=(f"substrate={substrate}", "TLS or identity relation declared"),
            )
        )

    # -----------------------------------------------------------------
    # Landscape opportunities
    # -----------------------------------------------------------------

    if is_machine or is_unknown_substrate:
        landscape_evidence = [f"substrate={substrate}"]
        if clustered:
            landscape_evidence.append("clustered (peer relation declared)")

        opportunities.append(
            EstateOpportunity(
                product="Landscape",
                facet="fleet-patching",
                level=_promote_to_already_mentioned(
                    "recommended" if clustered else "consider",
                    landscape_mentions,
                ),
                rationale=(
                    "Landscape orchestrates package and kernel updates "
                    "across an Ubuntu estate, which scales better than "
                    "ad-hoc juju run / cron loops once more than a "
                    "handful of units are in play."
                ),
                evidence=tuple(landscape_evidence),
            )
        )

        if sensitive or stateful:
            opportunities.append(
                EstateOpportunity(
                    product="Landscape",
                    facet="compliance-reporting",
                    level=_promote_to_already_mentioned("consider", landscape_mentions),
                    rationale=(
                        "Landscape produces per-machine compliance "
                        "reports (kernel, package CVEs, USG findings) "
                        "that operators carrying a regulated workload "
                        "are typically asked to file."
                    ),
                    evidence=tuple(landscape_evidence),
                )
            )

        if clustered:
            opportunities.append(
                EstateOpportunity(
                    product="Landscape",
                    facet="access-management",
                    level=_promote_to_already_mentioned("consider", landscape_mentions),
                    rationale=(
                        "Centralised SSH access and operator authn "
                        "across a multi-unit estate is easier to "
                        "audit through Landscape than through per-"
                        "machine sshd configuration."
                    ),
                    evidence=tuple(landscape_evidence),
                )
            )

    # K8s charm that already mentions Pro/Landscape: emit reinforcement-only
    # entries so the agent can validate the existing docs.
    if substrate == "k8s" and (pro_mentions or landscape_mentions):
        if pro_mentions:
            opportunities.append(
                EstateOpportunity(
                    product="Ubuntu Pro",
                    facet="host-coverage",
                    level="already-mentioned",
                    rationale=(
                        "The repo already references Ubuntu Pro.  For "
                        "a Kubernetes charm the recommendation typically "
                        "applies to the cluster's Ubuntu *host* nodes "
                        "rather than the charm itself — confirm the "
                        "existing wording is aimed at the right layer."
                    ),
                    evidence=tuple(f"mention:{tok}" for tok in pro_mentions),
                )
            )
        if landscape_mentions:
            opportunities.append(
                EstateOpportunity(
                    product="Landscape",
                    facet="host-coverage",
                    level="already-mentioned",
                    rationale=(
                        "The repo already references Landscape.  For a "
                        "Kubernetes charm the recommendation typically "
                        "applies to the cluster's Ubuntu *host* nodes "
                        "rather than the charm itself — confirm the "
                        "existing wording is aimed at the right layer."
                    ),
                    evidence=tuple(f"mention:{tok}" for tok in landscape_mentions),
                )
            )

    return opportunities


def _promote_to_already_mentioned(base_level: str, mentions: list[str]) -> str:
    """If any mention tokens were found, flip the level to ``already-mentioned``.

    Surfacing the existing reference is more useful than re-pitching
    the product: it lets the agent reinforce or audit the wording the
    operator already wrote rather than duplicate it.
    """
    if mentions:
        return "already-mentioned"
    return base_level


def render_estate_section(opportunities: list[EstateOpportunity]) -> list[str]:
    """Format estate opportunities for OPERATIONAL_READINESS.md.

    Returns a list of markdown lines (no trailing newline).  Callers
    splice the lines into the report body.  Returns an empty list
    when there are no opportunities, so the section disappears
    rather than nagging the reader.
    """
    if not opportunities:
        return []

    lines: list[str] = ["## Estate Operations", ""]
    lines.append(
        "These are operator/estate-level recommendations for running the "
        "charm on a supported Ubuntu production estate.  They are "
        "**not required for the charm to work** — they apply when the "
        "operator wants Canonical-supported security maintenance, "
        "compliance posture, or fleet management."
    )
    lines.append("")

    # Group by product so the section reads as two coherent blocks.
    by_product: dict[str, list[EstateOpportunity]] = {}
    for opp in opportunities:
        by_product.setdefault(opp.product, []).append(opp)

    for product in ("Ubuntu Pro", "Landscape"):
        items = by_product.get(product)
        if not items:
            continue
        lines.append(f"### {product}")
        lines.append("")
        for opp in items:
            lines.append(f"- **[{opp.level}] {opp.facet}**")
            lines.append(f"  - Rationale: {opp.rationale}")
            if opp.evidence:
                lines.append(f"  - Evidence: {', '.join(opp.evidence)}")
        lines.append("")

    return lines
