"""Tests for the stacked tool-access policy primitives (Phase 80.1)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from cantrip.agent.policy import (
    BUILTIN_POLICIES,
    ORG_WIDE_POLICY,
    SPRINT_POLICY,
    GovernancePolicy,
    PolicyAction,
    PolicyParseError,
    category_policy,
    compose_policies,
    discover_policies,
    load_policy_file,
    policy_from_dict,
    policy_to_dict,
)


class TestGovernancePolicy:
    """Direct behaviour of a single policy layer."""

    def test_default_policy_is_permissive(self) -> None:
        """Zero-arg construction produces a policy that allows everything."""
        policy = GovernancePolicy()
        assert policy.check_tool("anything") == PolicyAction.ALLOW
        assert policy.check_tool("juju_destroy_model") == PolicyAction.ALLOW

    def test_blocked_tool_denied(self) -> None:
        policy = GovernancePolicy(blocked_tools=frozenset({"juju_destroy_model"}))
        assert policy.check_tool("juju_destroy_model") == PolicyAction.DENY
        assert policy.check_tool("juju_status") == PolicyAction.ALLOW

    def test_allowlist_denies_unknown_tool(self) -> None:
        """A non-empty allow-list means 'only these tools'."""
        policy = GovernancePolicy(allowed_tools=frozenset({"juju_status", "read_file"}))
        assert policy.check_tool("juju_status") == PolicyAction.ALLOW
        assert policy.check_tool("read_file") == PolicyAction.ALLOW
        assert policy.check_tool("juju_destroy_model") == PolicyAction.DENY

    def test_empty_allowlist_means_no_constraint(self) -> None:
        """An empty allow-list imposes no allow constraint, unlike an empty block-list.

        This is the load-bearing semantic that makes composition clean —
        stacking a "no allow opinion" layer with a "only these" layer
        must preserve the "only these" rule.
        """
        policy = GovernancePolicy(allowed_tools=frozenset())
        assert policy.check_tool("anything") == PolicyAction.ALLOW

    def test_review_beats_allow(self) -> None:
        policy = GovernancePolicy(require_human_approval=frozenset({"juju_destroy_model"}))
        assert policy.check_tool("juju_destroy_model") == PolicyAction.REVIEW

    def test_block_beats_review(self) -> None:
        """A tool in both block and review lists denies — block is strictest."""
        policy = GovernancePolicy(
            blocked_tools=frozenset({"juju_destroy_model"}),
            require_human_approval=frozenset({"juju_destroy_model"}),
        )
        assert policy.check_tool("juju_destroy_model") == PolicyAction.DENY

    def test_policy_is_frozen(self) -> None:
        """GovernancePolicy is immutable so composition can't accidentally mutate layers."""
        policy = GovernancePolicy(allowed_tools=frozenset({"a"}))
        with pytest.raises(dataclasses.FrozenInstanceError):
            policy.allowed_tools = frozenset({"b"})  # type: ignore[misc]

    def test_policy_is_hashable(self) -> None:
        """Immutability implies hashability — useful for set-of-policies caches."""
        p1 = GovernancePolicy(allowed_tools=frozenset({"a"}), name="x")
        p2 = GovernancePolicy(allowed_tools=frozenset({"a"}), name="x")
        assert hash(p1) == hash(p2)


class TestComposePolicies:
    """Most-restrictive-wins semantics across stacked layers."""

    def test_empty_stack_is_permissive(self) -> None:
        composed = compose_policies()
        assert composed.check_tool("anything") == PolicyAction.ALLOW

    def test_allow_lists_intersect(self) -> None:
        """Composition of two allow-lists keeps only tools present in both."""
        a = GovernancePolicy(allowed_tools=frozenset({"a", "b", "c"}), name="a")
        b = GovernancePolicy(allowed_tools=frozenset({"b", "c", "d"}), name="b")
        composed = compose_policies(a, b)
        assert composed.allowed_tools == frozenset({"b", "c"})

    def test_block_lists_union(self) -> None:
        a = GovernancePolicy(blocked_tools=frozenset({"x"}), name="a")
        b = GovernancePolicy(blocked_tools=frozenset({"y"}), name="b")
        composed = compose_policies(a, b)
        assert composed.blocked_tools == frozenset({"x", "y"})

    def test_approval_lists_union(self) -> None:
        a = GovernancePolicy(require_human_approval=frozenset({"p"}), name="a")
        b = GovernancePolicy(require_human_approval=frozenset({"q"}), name="b")
        composed = compose_policies(a, b)
        assert composed.require_human_approval == frozenset({"p", "q"})

    def test_rate_limit_picks_strictest(self) -> None:
        a = GovernancePolicy(max_calls_per_request=50, name="a")
        b = GovernancePolicy(max_calls_per_request=200, name="b")
        composed = compose_policies(a, b)
        assert composed.max_calls_per_request == 50

    def test_rate_limit_ignores_none(self) -> None:
        """A None rate-limit layer doesn't erase a set limit from another layer."""
        a = GovernancePolicy(max_calls_per_request=None, name="a")
        b = GovernancePolicy(max_calls_per_request=50, name="b")
        composed = compose_policies(a, b)
        assert composed.max_calls_per_request == 50

    def test_rate_limit_all_none_stays_none(self) -> None:
        composed = compose_policies(
            GovernancePolicy(name="a"),
            GovernancePolicy(name="b"),
        )
        assert composed.max_calls_per_request is None

    def test_empty_allow_layer_keeps_other_allow(self) -> None:
        """Composing an empty allow with a non-empty allow keeps the non-empty.

        This is the load-bearing case from the roadmap spec: an "only
        these" allow-list in one layer must survive composition with a
        "no allow opinion" layer in another.  Without this, the
        built-in org-wide policy (no allow-list) would accidentally
        reset the per-category allow-list.
        """
        unopinionated = GovernancePolicy(name="no-allow")
        tight = GovernancePolicy(allowed_tools=frozenset({"a", "b"}), name="tight")
        composed = compose_policies(unopinionated, tight)
        assert composed.allowed_tools == frozenset({"a", "b"})
        assert composed.check_tool("a") == PolicyAction.ALLOW
        assert composed.check_tool("c") == PolicyAction.DENY

    def test_compose_is_commutative_for_union_fields(self) -> None:
        """Union fields (block, approval) don't depend on order."""
        a = GovernancePolicy(
            blocked_tools=frozenset({"x"}),
            require_human_approval=frozenset({"p"}),
            name="a",
        )
        b = GovernancePolicy(
            blocked_tools=frozenset({"y"}),
            require_human_approval=frozenset({"q"}),
            name="b",
        )
        left = compose_policies(a, b)
        right = compose_policies(b, a)
        assert left.blocked_tools == right.blocked_tools
        assert left.require_human_approval == right.require_human_approval
        # Allow-lists also commute when both are empty.
        assert left.allowed_tools == right.allowed_tools

    def test_compose_is_commutative_for_allow_intersection(self) -> None:
        """Allow intersection commutes (it's a mathematical intersection)."""
        a = GovernancePolicy(allowed_tools=frozenset({"a", "b", "c"}), name="a")
        b = GovernancePolicy(allowed_tools=frozenset({"b", "c", "d"}), name="b")
        assert compose_policies(a, b).allowed_tools == compose_policies(b, a).allowed_tools

    def test_compose_is_associative(self) -> None:
        """Grouping of composition doesn't change the result."""
        a = GovernancePolicy(
            allowed_tools=frozenset({"a", "b", "c", "d"}),
            blocked_tools=frozenset({"x"}),
            name="a",
        )
        b = GovernancePolicy(
            allowed_tools=frozenset({"b", "c", "d"}),
            require_human_approval=frozenset({"p"}),
            max_calls_per_request=100,
            name="b",
        )
        c = GovernancePolicy(
            allowed_tools=frozenset({"c", "d"}),
            blocked_tools=frozenset({"y"}),
            max_calls_per_request=50,
            name="c",
        )

        left = compose_policies(compose_policies(a, b), c)
        right = compose_policies(a, compose_policies(b, c))

        assert left.allowed_tools == right.allowed_tools
        assert left.blocked_tools == right.blocked_tools
        assert left.require_human_approval == right.require_human_approval
        assert left.max_calls_per_request == right.max_calls_per_request

    def test_composed_name_reflects_stack(self) -> None:
        a = GovernancePolicy(name="org-wide")
        b = GovernancePolicy(name="category:build")
        composed = compose_policies(a, b)
        assert composed.name == "org-wide+category:build"


class TestPolicyFromDict:
    """Strict parsing of YAML-shaped dicts."""

    def test_roundtrip(self) -> None:
        original = GovernancePolicy(
            allowed_tools=frozenset({"a", "b"}),
            blocked_tools=frozenset({"x"}),
            require_human_approval=frozenset({"p"}),
            max_calls_per_request=42,
            name="round-trip",
        )
        restored = policy_from_dict(policy_to_dict(original))
        assert restored == original

    def test_missing_keys_produce_empty_sets(self) -> None:
        policy = policy_from_dict({"name": "bare"})
        assert policy.allowed_tools == frozenset()
        assert policy.blocked_tools == frozenset()
        assert policy.require_human_approval == frozenset()
        assert policy.max_calls_per_request is None

    def test_unknown_key_raises(self) -> None:
        with pytest.raises(PolicyParseError, match="unknown policy fields"):
            policy_from_dict({"allowd_tools": ["a"]})  # typo

    def test_rate_limit_must_be_int(self) -> None:
        with pytest.raises(PolicyParseError, match="must be an integer"):
            policy_from_dict({"max_calls_per_request": "fifty"})

    def test_rate_limit_rejects_bool(self) -> None:
        """``True`` is int-subclass — reject explicitly to catch YAML typos."""
        with pytest.raises(PolicyParseError, match="must be an integer"):
            policy_from_dict({"max_calls_per_request": True})

    def test_rate_limit_must_be_non_negative(self) -> None:
        with pytest.raises(PolicyParseError, match=">= 0"):
            policy_from_dict({"max_calls_per_request": -1})

    def test_tool_list_entries_must_be_strings(self) -> None:
        with pytest.raises(PolicyParseError, match="entries must be strings"):
            policy_from_dict({"allowed_tools": ["a", 42]})

    def test_tool_list_must_be_list(self) -> None:
        with pytest.raises(PolicyParseError, match="must be a list"):
            policy_from_dict({"blocked_tools": "juju_destroy_model"})

    def test_non_mapping_raises(self) -> None:
        with pytest.raises(PolicyParseError, match="must be a mapping"):
            policy_from_dict([])  # type: ignore[arg-type]


class TestLoadPolicyFile:
    """End-to-end YAML loading."""

    def test_loads_valid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "sprint.yaml"
        path.write_text(
            "name: sprint\n"
            "blocked_tools:\n"
            "  - juju_destroy_controller\n"
            "max_calls_per_request: 200\n"
        )
        policy = load_policy_file(path)
        assert policy.name == "sprint"
        assert "juju_destroy_controller" in policy.blocked_tools
        assert policy.max_calls_per_request == 200

    def test_empty_file_produces_zero_policy(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("")
        policy = load_policy_file(path)
        # Name defaults to the file stem when the file doesn't set one.
        assert policy.name == "empty"
        assert policy.allowed_tools == frozenset()

    def test_invalid_yaml_raises_policy_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text(": : : not valid")
        with pytest.raises(PolicyParseError):
            load_policy_file(path)

    def test_filename_stem_becomes_default_name(self, tmp_path: Path) -> None:
        path = tmp_path / "custom.yaml"
        path.write_text("blocked_tools: [x]\n")
        policy = load_policy_file(path)
        assert policy.name == "custom"


class TestDiscoverPolicies:
    """Filesystem scan used by the dispatcher (Phase 80.2)."""

    def test_discovers_user_dir_in_sorted_order(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        (config_dir / "b.yaml").write_text("name: b\n")
        (config_dir / "a.yaml").write_text("name: a\n")
        (config_dir / "c.yml").write_text("name: c\n")
        policies = discover_policies(user_config_dir=config_dir)
        # Sorted alphabetically so composition order is deterministic.
        assert [p.name for p in policies] == ["a", "b", "c"]

    def test_ignores_non_yaml_files(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        (config_dir / "a.yaml").write_text("name: a\n")
        (config_dir / "README.md").write_text("# notes\n")
        (config_dir / "backup.yaml.bak").write_text("ignored\n")
        policies = discover_policies(user_config_dir=config_dir)
        assert [p.name for p in policies] == ["a"]

    def test_missing_user_dir_returns_empty(self, tmp_path: Path) -> None:
        policies = discover_policies(user_config_dir=tmp_path / "does-not-exist")
        assert policies == []

    def test_per_charm_overlay_comes_last(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        (config_dir / "org-wide.yaml").write_text("name: org-wide\n")
        charm_dir = tmp_path / "charm"
        charm_dir.mkdir()
        (charm_dir / "cantrip.policies.yaml").write_text("name: per-charm\n")
        policies = discover_policies(user_config_dir=config_dir, charm_path=charm_dir)
        assert [p.name for p in policies] == ["org-wide", "per-charm"]

    def test_missing_charm_overlay_is_fine(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        (config_dir / "org-wide.yaml").write_text("name: org-wide\n")
        charm_dir = tmp_path / "charm-without-policy"
        charm_dir.mkdir()
        policies = discover_policies(user_config_dir=config_dir, charm_path=charm_dir)
        assert [p.name for p in policies] == ["org-wide"]

    def test_malformed_file_is_skipped_with_warning(self, tmp_path: Path, caplog) -> None:
        """One broken file shouldn't lock the operator out of the stack."""
        import logging

        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        (config_dir / "good.yaml").write_text("name: good\n")
        (config_dir / "bad.yaml").write_text("max_calls_per_request: -1\n")
        with caplog.at_level(logging.WARNING, logger="cantrip.agent.policy"):
            policies = discover_policies(user_config_dir=config_dir)
        assert [p.name for p in policies] == ["good"]
        assert any("bad.yaml" in rec.getMessage() for rec in caplog.records)


class TestBuiltinPolicies:
    """Sanity-check the shipped defaults."""

    def test_org_wide_requires_approval_for_destructive_tools(self) -> None:
        assert ORG_WIDE_POLICY.check_tool("juju_destroy_model") == PolicyAction.REVIEW
        assert ORG_WIDE_POLICY.check_tool("git_push") == PolicyAction.REVIEW
        assert ORG_WIDE_POLICY.check_tool("run_command") == PolicyAction.REVIEW
        # Normal tools pass unchanged.
        assert ORG_WIDE_POLICY.check_tool("read_file") == PolicyAction.ALLOW

    def test_sprint_policy_carries_rate_limit(self) -> None:
        assert SPRINT_POLICY.max_calls_per_request == 200

    def test_builtins_in_registry(self) -> None:
        assert BUILTIN_POLICIES["org-wide"] is ORG_WIDE_POLICY
        assert BUILTIN_POLICIES["sprint"] is SPRINT_POLICY

    def test_category_policy_factory_produces_expected_shape(self) -> None:
        policy = category_policy("build", frozenset({"write_file", "charmcraft_pack"}))
        assert policy.name == "category:build"
        assert policy.allowed_tools == frozenset({"write_file", "charmcraft_pack"})
        # A category policy alone doesn't block or require review — it's an
        # allow-list layer; blocks and reviews come from other layers.
        assert policy.blocked_tools == frozenset()

    def test_full_stack_composes_as_defence_in_depth(self) -> None:
        """Stacking org-wide + category + per-charm gives the right verdicts.

        The motivation from design/TOOLS.md §55.4 — this test pins the
        expected composed behaviour so a future refactor doesn't
        silently weaken the built-ins.
        """
        build_category = category_policy(
            "build",
            frozenset({"write_file", "charmcraft_pack", "git_push"}),
        )
        per_charm = GovernancePolicy(
            name="production",
            blocked_tools=frozenset({"git_push"}),
        )
        composed = compose_policies(ORG_WIDE_POLICY, build_category, per_charm)

        # Allow-list: only tools the category allows survive.
        assert composed.check_tool("read_file") == PolicyAction.DENY  # not in category allow
        assert composed.check_tool("write_file") == PolicyAction.ALLOW
        # Block trumps everything.
        assert composed.check_tool("git_push") == PolicyAction.DENY
        # Org-wide review propagates through composition.
        assert composed.check_tool("charmcraft_pack") == PolicyAction.ALLOW
        assert composed.check_tool("juju_destroy_model") == PolicyAction.REVIEW
