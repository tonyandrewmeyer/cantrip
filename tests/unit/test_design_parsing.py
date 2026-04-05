"""Tests for design proposal parsing and DesignProposal formatting."""

from cantrip.agent.design import (
    DesignProposal,
    DesignQuestion,
    parse_design_from_result,
)

FULL_DESIGN_MD = """\
# PostgreSQL

## Substrate

Kubernetes — best for containerised deployment.

## Substrate reasoning

K8s provides Pebble workload management.

## Charm path

Custom — complex operational patterns.

## Charm path reasoning

Needs custom replication handling.

## Charmhub

Build new — no maintained charm.

## Integrations

- db (provides)
- cos-agent (requires)
- certificates (requires)

## Config

- port: Listen port (default 5432)
- max-connections: Max client connections

## Actions

- backup: Create a backup
- restore: Restore from backup

## Scaling

Horizontal scaling via streaming replication.

## Operational patterns

WAL shipping for disaster recovery. Health via pg_isready.

## Security surface

- TLS termination
- Client authentication

## Companion charms

- postgresql-pgbouncer via pgbouncer (pgsql)
- s3-integrator via s3-credentials (s3)

## Questions

- **HA mode**: What high-availability mode should be used?
  - Synchronous replication
  - Asynchronous replication
  - Patroni-based failover
- **Backup schedule**: How often should backups run?
  - Daily
  - Hourly

## Sources

- https://postgresql.org/docs/
- https://hub.docker.com/_/postgres
"""


class TestParseDesignFromResult:
    """Tests for the heading-based design parser."""

    def test_workload_name(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert proposal.workload_name == "PostgreSQL"

    def test_substrate(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert "Kubernetes" in proposal.substrate

    def test_substrate_reasoning(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert "Pebble" in proposal.substrate_reasoning

    def test_charm_path(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert "Custom" in proposal.charm_path

    def test_charmhub(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert "Build new" in proposal.charmhub_recommendation

    def test_integrations(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert len(proposal.integrations) == 3
        assert "db (provides)" in proposal.integrations

    def test_config_options(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert len(proposal.config_options) == 2
        assert any("port" in c for c in proposal.config_options)

    def test_actions(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert len(proposal.actions) == 2
        assert any("backup" in a for a in proposal.actions)

    def test_scaling(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert "replication" in proposal.scaling_strategy.lower()

    def test_operational_patterns(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert "WAL" in proposal.operational_patterns

    def test_security_surface(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert len(proposal.security_surface) == 2
        assert "TLS termination" in proposal.security_surface

    def test_companions(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert len(proposal.companions) == 2
        assert proposal.companions[0].charm_name == "postgresql-pgbouncer"
        assert proposal.companions[0].endpoint == "pgbouncer"
        assert proposal.companions[0].interface == "pgsql"

    def test_questions(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert len(proposal.questions_for_user) == 2
        ha_q = proposal.questions_for_user[0]
        assert ha_q.key == "HA mode"
        assert len(ha_q.suggestions) == 3
        assert "Synchronous replication" in ha_q.suggestions

    def test_sources(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert len(proposal.sources) == 2
        assert "https://postgresql.org/docs/" in proposal.sources

    def test_raw_design_md_preserved(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert proposal.raw_design_md == FULL_DESIGN_MD


class TestParseEdgeCases:
    """Edge cases for design parsing."""

    def test_empty_text(self):
        proposal = parse_design_from_result("")
        assert proposal.workload_name == ""
        assert proposal.integrations == []
        assert proposal.raw_design_md == ""

    def test_only_heading(self):
        proposal = parse_design_from_result("# MyApp")
        assert proposal.workload_name == "MyApp"

    def test_missing_sections(self):
        text = "# MyApp\n\n## Substrate\n\nMachine\n"
        proposal = parse_design_from_result(text)
        assert proposal.workload_name == "MyApp"
        assert "Machine" in proposal.substrate
        assert proposal.integrations == []
        assert proposal.actions == []

    def test_no_h1_heading(self):
        text = "## Substrate\n\nK8s\n"
        proposal = parse_design_from_result(text)
        assert proposal.workload_name == ""
        assert "K8s" in proposal.substrate

    def test_companion_without_backticks(self):
        text = "# App\n\n## Companion charms\n\n- mycharm via endpoint (iface)\n"
        proposal = parse_design_from_result(text)
        assert len(proposal.companions) == 1
        assert proposal.companions[0].charm_name == "mycharm"

    def test_companion_with_backticks(self):
        text = "# App\n\n## Companion charms\n\n- mycharm via `endpoint` (iface)\n"
        proposal = parse_design_from_result(text)
        assert len(proposal.companions) == 1
        assert proposal.companions[0].endpoint == "endpoint"

    def test_malformed_companion_line_skipped(self):
        text = "# App\n\n## Companion charms\n\n- just some text\n"
        proposal = parse_design_from_result(text)
        assert proposal.companions == []


class TestDesignProposalFormatForChat:
    """Tests for format_for_chat output."""

    def test_includes_workload_heading(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        chat = proposal.format_for_chat()
        assert "# PostgreSQL" in chat

    def test_includes_substrate(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        chat = proposal.format_for_chat()
        assert "**Substrate:**" in chat

    def test_includes_integrations(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        chat = proposal.format_for_chat()
        assert "**Integrations:**" in chat
        assert "- db (provides)" in chat

    def test_includes_companions(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        chat = proposal.format_for_chat()
        assert "**Companion charms:**" in chat

    def test_empty_proposal_shows_default_heading(self):
        proposal = DesignProposal()
        chat = proposal.format_for_chat()
        assert "# Design Proposal" in chat

    def test_to_design_md_returns_raw(self):
        proposal = parse_design_from_result(FULL_DESIGN_MD)
        assert proposal.to_design_md() == FULL_DESIGN_MD


class TestDesignQuestion:
    """Tests for DesignQuestion dataclass."""

    def test_question_defaults(self):
        q = DesignQuestion(key="test", text="A question?")
        assert q.suggestions == []
        assert q.answer is None

    def test_question_with_suggestions(self):
        q = DesignQuestion(key="mode", text="Which mode?", suggestions=["A", "B"])
        assert len(q.suggestions) == 2


class TestWatcherEvent:
    """Tests for WatcherEvent dedup key generation."""

    def test_dedup_key_auto_generated(self):
        from cantrip.agent.watcher import WatcherEvent

        event = WatcherEvent(
            source="status",
            category="hook_failure",
            summary="install failed",
            detail="error details",
            app="redis",
            unit="redis/0",
        )
        assert event.dedup_key  # Non-empty.
        assert len(event.dedup_key) == 32  # MD5 hex digest.

    def test_dedup_key_deterministic(self):
        from cantrip.agent.watcher import WatcherEvent

        kwargs = {
            "source": "status",
            "category": "hook_failure",
            "summary": "install failed",
            "detail": "error",
            "app": "redis",
        }
        e1 = WatcherEvent(**kwargs)
        e2 = WatcherEvent(**kwargs)
        assert e1.dedup_key == e2.dedup_key

    def test_different_events_different_keys(self):
        from cantrip.agent.watcher import WatcherEvent

        e1 = WatcherEvent(source="status", category="hook_failure", summary="a", detail="")
        e2 = WatcherEvent(source="status", category="status_change", summary="b", detail="")
        assert e1.dedup_key != e2.dedup_key

    def test_explicit_dedup_key_preserved(self):
        from cantrip.agent.watcher import WatcherEvent

        event = WatcherEvent(
            source="status",
            category="test",
            summary="test",
            detail="",
            dedup_key="custom-key",
        )
        assert event.dedup_key == "custom-key"


class TestWatcherConfig:
    """Tests for WatcherConfig defaults."""

    def test_default_values(self):
        from cantrip.agent.watcher import WatcherConfig

        config = WatcherConfig()
        assert config.status_interval == 10.0
        assert config.loki_interval == 15.0
        assert config.dedup_window == 300.0
        assert config.max_queue == 50
        assert config.snapshot_databags is False

    def test_custom_values(self):
        from cantrip.agent.watcher import WatcherConfig

        config = WatcherConfig(status_interval=5.0, max_queue=100)
        assert config.status_interval == 5.0
        assert config.max_queue == 100
