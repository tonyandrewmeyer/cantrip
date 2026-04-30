"""Tests for the design proposal module."""

from cantrip.agent.design import (
    CompanionCharm,
    DesignProposal,
    DesignQuestion,
    parse_design_from_result,
)

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
            questions_for_user=[
                DesignQuestion(
                    key="Mode",
                    text="Sentinel or cluster mode?",
                    suggestions=["Sentinel", "Cluster"],
                ),
            ],
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
- **Mode**: Should we target Redis Cluster or Sentinel mode?
  - Redis Cluster (recommended for horizontal scaling)
  - Sentinel (simpler, primary/replica only)
- **Authentication**: What authentication method is preferred?
  - Password (ACL-based)
  - TLS client certificates

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
        assert any("Sentinel" in q.text for q in proposal.questions_for_user)

    def test_parses_question_keys(self) -> None:
        """Bold key prefixes are extracted into DesignQuestion.key."""
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        keys = [q.key for q in proposal.questions_for_user]
        assert "Mode" in keys
        assert "Authentication" in keys

    def test_parses_question_suggestions(self) -> None:
        """Indented sub-bullets are extracted as suggestions."""
        proposal = parse_design_from_result(_SAMPLE_DESIGN)
        mode_q = next(q for q in proposal.questions_for_user if q.key == "Mode")
        assert len(mode_q.suggestions) == 2
        assert any("Cluster" in s for s in mode_q.suggestions)
        assert any("Sentinel" in s for s in mode_q.suggestions)

        auth_q = next(q for q in proposal.questions_for_user if q.key == "Authentication")
        assert len(auth_q.suggestions) == 2
        assert any("Password" in s for s in auth_q.suggestions)

    def test_parses_questions_without_suggestions(self) -> None:
        """Questions without sub-bullets still parse correctly."""
        md = "# Test\n\n## Questions\n- **DB**: Which database?\n- **Port**: What port?\n"
        proposal = parse_design_from_result(md)
        assert len(proposal.questions_for_user) == 2
        assert proposal.questions_for_user[0].suggestions == []
        assert proposal.questions_for_user[1].suggestions == []

    def test_parses_questions_without_bold_key(self) -> None:
        """Questions without **key**: prefix get a slug key."""
        md = "# Test\n\n## Questions\n- Should we use K8s?\n"
        proposal = parse_design_from_result(md)
        assert len(proposal.questions_for_user) == 1
        q = proposal.questions_for_user[0]
        assert q.text == "Should we use K8s?"
        assert q.key  # Should have some auto-generated key.

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

    def test_security_surface_parsed_from_design(self) -> None:
        """A '## Security Surface' section with bullets populates security_surface."""
        md = (
            "# Design: Keycloak\n\n"
            "## Security Surface\n"
            "- authentication\n"
            "- credential management\n"
            "- network access control\n"
        )
        proposal = parse_design_from_result(md)
        assert proposal.security_surface == [
            "authentication",
            "credential management",
            "network access control",
        ]

    def test_security_event_types_parsed(self) -> None:
        """A '## Security Event Types' section populates security_event_types."""
        md = (
            "# Design: Vault\n\n"
            "## Security Event Types\n"
            "- authn_login_success\n"
            "- authz_fail\n"
            "- secret_access\n"
        )
        proposal = parse_design_from_result(md)
        assert proposal.security_event_types == [
            "authn_login_success",
            "authz_fail",
            "secret_access",
        ]

    def test_security_surface_in_format_for_chat(self) -> None:
        """format_for_chat includes a security surface section when populated."""
        proposal = DesignProposal(
            workload_name="Keycloak",
            security_surface=["authentication", "credential management"],
        )
        chat = proposal.format_for_chat()
        assert "**Security surface:**" in chat
        assert "- authentication" in chat
        assert "- credential management" in chat

    def test_security_surface_empty_when_absent(self) -> None:
        """security_surface defaults to an empty list when no section is present."""
        md = "# Design: Minimal\n\n## Substrate\nK8s\n"
        proposal = parse_design_from_result(md)
        assert proposal.security_surface == []
        assert proposal.security_event_types == []
        # Empty lists should not appear in formatted output.
        chat = proposal.format_for_chat()
        assert "Security surface" not in chat

    def test_preserves_raw_even_if_parsing_fails(self) -> None:
        """Non-Markdown text should still preserve the raw content."""
        text = "This is just plain text with no headings."
        proposal = parse_design_from_result(text)
        assert proposal.raw_design_md == text
        assert proposal.workload_name == ""


# ===================================================================
# TestCompanionCharms
# ===================================================================


class TestCompanionCharms:
    """Tests for companion charm parsing and display."""

    _DESIGN_WITH_COMPANIONS = (
        "# Design: MyApp\n\n"
        "## Substrate\nKubernetes\n\n"
        "## Companion charms\n"
        "- postgresql-k8s via db (postgresql_client)\n"
        "- redis-k8s via cache (redis)\n"
    )

    def test_parses_companion_charms(self) -> None:
        """Companion charms section produces structured CompanionCharm objects."""
        proposal = parse_design_from_result(self._DESIGN_WITH_COMPANIONS)
        assert len(proposal.companions) == 2
        assert proposal.companions[0] == CompanionCharm(
            charm_name="postgresql-k8s",
            endpoint="db",
            interface="postgresql_client",
        )
        assert proposal.companions[1] == CompanionCharm(
            charm_name="redis-k8s",
            endpoint="cache",
            interface="redis",
        )

    def test_no_companion_section_returns_empty_list(self) -> None:
        """Missing companion section produces an empty list."""
        md = "# Design: Simple\n\n## Substrate\nK8s\n"
        proposal = parse_design_from_result(md)
        assert proposal.companions == []

    def test_malformed_lines_skipped(self) -> None:
        """Lines that do not match the expected format are silently skipped."""
        md = (
            "# Design: Test\n\n"
            "## Companion charms\n"
            "- postgresql-k8s via db (postgresql_client)\n"
            "- this line is malformed\n"
            "- also bad\n"
            "- redis-k8s via cache (redis)\n"
        )
        proposal = parse_design_from_result(md)
        assert len(proposal.companions) == 2
        assert proposal.companions[0].charm_name == "postgresql-k8s"
        assert proposal.companions[1].charm_name == "redis-k8s"

    def test_format_for_chat_includes_companions(self) -> None:
        """format_for_chat shows companion charms when present."""
        proposal = DesignProposal(
            workload_name="MyApp",
            companions=[
                CompanionCharm("postgresql-k8s", "db", "postgresql_client"),
                CompanionCharm("redis-k8s", "cache", "redis"),
            ],
        )
        chat = proposal.format_for_chat()
        assert "**Companion charms:**" in chat
        assert "postgresql-k8s via `db` (postgresql_client)" in chat
        assert "redis-k8s via `cache` (redis)" in chat

    def test_format_for_chat_omits_companions_when_empty(self) -> None:
        """format_for_chat does not show companion section when list is empty."""
        proposal = DesignProposal(workload_name="Simple")
        chat = proposal.format_for_chat()
        assert "Companion" not in chat
