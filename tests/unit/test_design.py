"""Tests for the design proposal module."""

from cantrip.agent.design import DesignProposal, parse_design_from_result

# ===================================================================
# TestDesignProposal
# ===================================================================


class TestDesignProposal:
    """Tests for DesignProposal dataclass methods."""

    def test_format_for_chat_full(self) -> None:
        """Format a fully populated proposal."""
        proposal = DesignProposal(
            workload_name="Redis",
            substrate="K8s",
            substrate_reasoning="Has Dockerfile",
            charm_path="infrastructure",
            charm_path_reasoning="Database workload",
            charmhub_recommendation="Build new",
            charmhub_details="Existing redis-k8s lacks clustering",
            integrations=["COS", "TLS"],
            config_options=["port", "maxmemory"],
            actions=["backup", "restore"],
            scaling_strategy="Horizontal with sentinel",
            operational_patterns="Primary/replica with automatic failover",
            questions_for_user=["Sentinel or cluster mode?"],
            sources=["https://redis.io/docs"],
            raw_design_md="# Full design content",
        )
        chat = proposal.format_for_chat()

        assert "# Redis" in chat
        assert "**Substrate:** K8s" in chat
        assert "Has Dockerfile" in chat
        assert "**Charm path:** infrastructure" in chat
        assert "Database workload" in chat
        assert "**Charmhub:** Build new" in chat
        assert "Existing redis-k8s" in chat
        assert "- COS" in chat
        assert "- TLS" in chat
        assert "- port" in chat
        assert "- backup" in chat
        assert "Horizontal with sentinel" in chat
        assert "Primary/replica" in chat
        assert "Sentinel or cluster mode?" in chat
        assert "https://redis.io/docs" in chat

    def test_format_for_chat_minimal(self) -> None:
        """Format a proposal with only required fields."""
        proposal = DesignProposal(raw_design_md="raw")
        chat = proposal.format_for_chat()

        # Should still have a heading.
        assert "# Design Proposal" in chat
        # Should not have empty sections.
        assert "Integrations" not in chat
        assert "Config" not in chat
        assert "Actions" not in chat

    def test_format_for_chat_empty_lists(self) -> None:
        """Empty lists should not produce section headings."""
        proposal = DesignProposal(
            workload_name="Test",
            integrations=[],
            config_options=[],
            actions=[],
            questions_for_user=[],
            sources=[],
        )
        chat = proposal.format_for_chat()
        assert "Integrations" not in chat
        assert "Questions" not in chat

    def test_to_design_md(self) -> None:
        """to_design_md returns the raw content."""
        raw = "# Design: Redis\n\n## Substrate\nK8s"
        proposal = DesignProposal(raw_design_md=raw)
        assert proposal.to_design_md() == raw

    def test_to_design_md_empty(self) -> None:
        """to_design_md returns empty string when no raw content."""
        proposal = DesignProposal()
        assert proposal.to_design_md() == ""


# ===================================================================
# TestParseDesignFromResult
# ===================================================================

_SAMPLE_DESIGN = """\
# Design: Redis

## Substrate
K8s

## Substrate Reasoning
Has Dockerfile, cloud-native workload

## Charm Path
Infrastructure (Path C)

## Charm Path Reasoning
Database/cache workload

## Charmhub
Build new — existing redis-k8s lacks clustering support

## Integrations
- COS (Grafana, Prometheus, Loki, Tempo)
- TLS certificates
- Database relation (redis protocol)

## Config Options
- port
- maxmemory
- cluster-enabled

## Actions
- backup
- restore
- failover

## Scaling
Horizontal scaling with Redis Cluster or Sentinel

## Operational Patterns
Primary/replica with automatic failover. Supports RDB and AOF persistence.

## Questions
- Should we target Redis Cluster or Sentinel mode?
- What authentication method is preferred?

## Sources
- https://redis.io/docs
- https://hub.docker.com/_/redis
"""


class TestParseDesignFromResult:
    """Tests for parse_design_from_result — heading-based parsing."""

    def test_parses_workload_name(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert proposal.workload_name == "Design: Redis"

    def test_parses_substrate(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert proposal.substrate == "K8s"

    def test_parses_substrate_reasoning(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert "Dockerfile" in proposal.substrate_reasoning

    def test_parses_charm_path(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert "Infrastructure" in proposal.charm_path

    def test_parses_integrations(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert len(proposal.integrations) == 3
        assert any("COS" in i for i in proposal.integrations)
        assert any("TLS" in i for i in proposal.integrations)

    def test_parses_config_options(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert "port" in proposal.config_options
        assert "maxmemory" in proposal.config_options

    def test_parses_actions(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert "backup" in proposal.actions
        assert "restore" in proposal.actions

    def test_parses_questions(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert len(proposal.questions_for_user) == 2
        assert any("Sentinel" in q for q in proposal.questions_for_user)

    def test_parses_sources(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert len(proposal.sources) == 2
        assert any("redis.io" in s for s in proposal.sources)

    def test_preserves_raw_text(self) -> None:
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        assert proposal.raw_design_md == _SAMPLE_DESIGN

    def test_handles_missing_sections(self) -> None:
        """Missing sections should produce empty strings/lists."""
        minimal = "# Design: Minimal\n\n## Substrate\nK8s\n"
        proposal = parse_design_from_result(minimal)

        assert proposal.workload_name == "Design: Minimal"
        assert proposal.substrate == "K8s"
        assert proposal.integrations == []
        assert proposal.questions_for_user == []
        assert proposal.charm_path == ""

    def test_handles_empty_text(self) -> None:
        """Empty input produces a valid but empty proposal."""
        proposal = parse_design_from_result("")
        assert proposal.workload_name == ""
        assert proposal.substrate == ""
        assert proposal.raw_design_md == ""

    def test_preserves_raw_even_if_parsing_fails(self) -> None:
        """Non-Markdown text should still preserve the raw content."""
        text = "This is just plain text with no headings."
        proposal = parse_design_from_result(text)
        assert proposal.raw_design_md == text
        assert proposal.workload_name == ""
