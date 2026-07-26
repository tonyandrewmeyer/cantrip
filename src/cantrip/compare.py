"""Charm comparison mode (Phase 31.7).

Diffs two charm implementations along four dimensions — directory
structure, ``config.options``, relation endpoints, and test-file
counts — then renders a human-readable report.  Intended for
evaluating a Cantrip-generated charm against a hand-crafted or
upstream one, so it deliberately summarises rather than producing a
line-by-line diff (use ``diff -r`` for that).

Pure functions throughout; the CLI entry point in ``cantrip.main``
just calls :func:`compare_charms` and prints :func:`format_report`.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    import pathlib

# Top-level files and directories we flag in the structure section.
# Presence / absence matters; content is compared elsewhere for the
# specific cases (``charmcraft.yaml``) where we have a schema.
_STRUCTURE_LANDMARKS: tuple[str, ...] = (
    "charmcraft.yaml",
    "metadata.yaml",
    "config.yaml",
    "actions.yaml",
    "pyproject.toml",
    "requirements.txt",
    "tox.ini",
    "src",
    "lib",
    "tests",
    "tests/unit",
    "tests/integration",
    "docs",
    "terraform",
    ".github/workflows",
    "README.md",
    "CONTRIBUTING.md",
    "icon.svg",
)


@dataclasses.dataclass(frozen=True)
class CharmSnapshot:
    """Everything we extract from a charm directory for comparison."""

    path: pathlib.Path
    present_landmarks: frozenset[str]
    # Parsed from charmcraft.yaml; empty dicts when the file is absent
    # or unparseable so the caller never has to reach for Optional.
    config_options: dict[str, dict[str, Any]]
    provides: dict[str, str]  # endpoint -> interface
    requires: dict[str, str]
    peers: dict[str, str]
    actions: frozenset[str]
    containers: frozenset[str]
    extensions: frozenset[str]
    base: str
    charm_name: str
    unit_test_count: int
    integration_test_count: int


@dataclasses.dataclass(frozen=True)
class DictDiff:
    """Three-way set diff over two dicts."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    # Keys present in both snapshots but with different values.
    changed: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ComparisonReport:
    """Structured diff between two charm snapshots."""

    left: CharmSnapshot
    right: CharmSnapshot
    structure: DictDiff
    config: DictDiff
    provides: DictDiff
    requires: DictDiff
    peers: DictDiff
    actions: DictDiff
    containers: DictDiff
    extensions: DictDiff


# ── Snapshot extraction ────────────────────────────────────────────────


def snapshot_charm(path: pathlib.Path) -> CharmSnapshot:
    """Read *path* and return a :class:`CharmSnapshot`.

    A missing ``charmcraft.yaml`` is not an error — the snapshot just
    carries empty collections for the fields that would have come from
    it, and the structure diff still shows the landmark as absent.
    This matches how humans would read the two charms: "this one has
    no charmcraft.yaml at all" is itself a useful finding.
    """
    charmcraft = _load_yaml(path / "charmcraft.yaml")
    metadata = _load_yaml(path / "metadata.yaml")  # legacy split
    config_yaml = _load_yaml(path / "config.yaml")  # legacy split
    actions_yaml = _load_yaml(path / "actions.yaml")  # legacy split

    # charmcraft.yaml wins; metadata.yaml / config.yaml / actions.yaml
    # only fill in what charmcraft.yaml omits, matching how modern
    # charmcraft itself merges the two formats.
    merged: dict[str, Any] = dict(metadata)
    merged.update(config_yaml)
    merged.update(actions_yaml)
    merged.update(charmcraft)

    config_opts = _extract_config_options(merged, config_yaml)
    actions = _extract_actions(merged, actions_yaml)
    provides, requires, peers = _extract_relations(merged)
    containers = _extract_containers(merged)
    extensions = _extract_extensions(merged)
    base = _extract_base(merged)
    charm_name = str(merged.get("name") or path.name)

    return CharmSnapshot(
        path=path,
        present_landmarks=_present_landmarks(path),
        config_options=config_opts,
        provides=provides,
        requires=requires,
        peers=peers,
        actions=actions,
        containers=containers,
        extensions=extensions,
        base=base,
        charm_name=charm_name,
        unit_test_count=_count_tests(path / "tests" / "unit"),
        integration_test_count=_count_tests(path / "tests" / "integration"),
    )


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    """Parse *path* as YAML, returning an empty dict on any failure.

    The diff is best-effort by design: a charm with a malformed (or
    non-UTF-8) YAML file should still surface in the report as "missing
    structure" rather than crashing the whole compare invocation.
    ``errors="replace"`` lets a stray legacy-encoded byte (latin-1
    ``é`` etc.) become U+FFFD instead of raising — the YAML parser
    will usually still understand the rest of the file, and if it
    cannot, ``yaml.YAMLError`` falls through to the empty-dict path.
    """
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError, RecursionError):
        # ``RecursionError`` here means a maliciously- or accidentally-
        # deeply-nested document blew through Python's stack while
        # PyYAML was tokenising it.  The diff is best-effort, so treat
        # an unparseable file as if it were missing.
        return {}
    return data if isinstance(data, dict) else {}


def _present_landmarks(path: pathlib.Path) -> frozenset[str]:
    """Return the subset of :data:`_STRUCTURE_LANDMARKS` that exist under *path*."""
    found: set[str] = set()
    for rel in _STRUCTURE_LANDMARKS:
        target = path / rel
        if target.exists():
            found.add(rel)
    return frozenset(found)


def _extract_config_options(
    merged: dict[str, Any], config_yaml: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Return the ``config.options`` mapping — name → {type, default, ...}.

    Charmcraft 4.x puts options under ``config.options`` in
    ``charmcraft.yaml``; the legacy standalone ``config.yaml`` uses the
    same ``options`` key at the top level.
    """
    config = merged.get("config")
    opts: Any = config.get("options") if isinstance(config, dict) else config_yaml.get("options")
    if not isinstance(opts, dict):
        return {}
    normalised: dict[str, dict[str, Any]] = {}
    for name, spec in opts.items():
        if isinstance(spec, dict):
            normalised[str(name)] = {k: spec.get(k) for k in ("type", "default", "description")}
    return normalised


def _extract_actions(merged: dict[str, Any], actions_yaml: dict[str, Any]) -> frozenset[str]:
    """Return the set of action names declared by the charm."""
    actions = merged.get("actions")
    if not isinstance(actions, dict):
        actions = actions_yaml if isinstance(actions_yaml, dict) else {}
    return frozenset(str(name) for name in actions if isinstance(name, str))


def _extract_relations(
    merged: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return (provides, requires, peers) as endpoint → interface dicts."""

    def _pull(kind: str) -> dict[str, str]:
        block = merged.get(kind)
        if not isinstance(block, dict):
            return {}
        result: dict[str, str] = {}
        for endpoint, spec in block.items():
            if not isinstance(spec, dict):
                continue
            interface = spec.get("interface")
            if isinstance(interface, str):
                result[str(endpoint)] = interface
        return result

    return _pull("provides"), _pull("requires"), _pull("peers")


def _extract_containers(merged: dict[str, Any]) -> frozenset[str]:
    """Return K8s container names declared in ``containers:``."""
    containers = merged.get("containers")
    if not isinstance(containers, dict):
        return frozenset()
    return frozenset(str(name) for name in containers)


def _extract_extensions(merged: dict[str, Any]) -> frozenset[str]:
    """Return the charmcraft ``extensions:`` list as a set."""
    exts = merged.get("extensions")
    if not isinstance(exts, list):
        return frozenset()
    return frozenset(str(e) for e in exts if isinstance(e, str))


def _extract_base(merged: dict[str, Any]) -> str:
    """Return the charm's base (``base:`` field) or an empty string if absent."""
    base = merged.get("base")
    if isinstance(base, str):
        return base
    # Legacy ``bases:`` list form — take the first entry's ``name@channel``.
    bases = merged.get("bases")
    if isinstance(bases, list) and bases:
        first = bases[0]
        if isinstance(first, dict):
            # ``build-on`` may be missing, ``[]``, or a list of dicts; the
            # ``or [{}]`` lets us index unconditionally only after we've
            # confirmed there is at least one entry to look at.
            build_on = first.get("build-on") or [{}]
            inner = build_on[0] if isinstance(build_on, list) else {}
            if not isinstance(inner, dict):
                inner = {}
            name = first.get("name") or inner.get("name", "")
            channel = first.get("channel") or inner.get("channel", "")
            if name and channel:
                return f"{name}@{channel}"
    return ""


def _count_tests(path: pathlib.Path) -> int:
    """Count ``test_*.py`` files under *path* (recursive)."""
    if not path.is_dir():
        return 0
    return sum(1 for p in path.rglob("test_*.py"))


# ── Comparison ─────────────────────────────────────────────────────────


def compare_charms(left: pathlib.Path, right: pathlib.Path) -> ComparisonReport:
    """Return a :class:`ComparisonReport` for two charm directories.

    The caller is expected to have resolved *left* and *right* to real
    paths — the function tolerates non-existent paths (treats them as
    empty charms) but does not attempt any path expansion itself.
    """
    left_snap = snapshot_charm(left)
    right_snap = snapshot_charm(right)

    return ComparisonReport(
        left=left_snap,
        right=right_snap,
        structure=_diff_sets(left_snap.present_landmarks, right_snap.present_landmarks),
        config=_diff_dicts(left_snap.config_options, right_snap.config_options),
        provides=_diff_dicts(left_snap.provides, right_snap.provides),
        requires=_diff_dicts(left_snap.requires, right_snap.requires),
        peers=_diff_dicts(left_snap.peers, right_snap.peers),
        actions=_diff_sets(left_snap.actions, right_snap.actions),
        containers=_diff_sets(left_snap.containers, right_snap.containers),
        extensions=_diff_sets(left_snap.extensions, right_snap.extensions),
    )


def _diff_sets(left: frozenset[str], right: frozenset[str]) -> DictDiff:
    """Set-difference a→b; ``changed`` is empty since sets carry no value."""
    return DictDiff(
        added=tuple(sorted(right - left)),
        removed=tuple(sorted(left - right)),
        changed=(),
    )


def _diff_dicts(left: dict[str, Any], right: dict[str, Any]) -> DictDiff:
    """Return dict diff — added (in right only), removed (in left only), changed (value differs)."""
    left_keys = set(left)
    right_keys = set(right)
    return DictDiff(
        added=tuple(sorted(right_keys - left_keys)),
        removed=tuple(sorted(left_keys - right_keys)),
        changed=tuple(sorted(k for k in left_keys & right_keys if left[k] != right[k])),
    )


# ── Rendering ──────────────────────────────────────────────────────────


def format_report(report: ComparisonReport) -> str:
    """Render *report* as a plain-text summary fit for a terminal."""
    left, right = report.left, report.right
    lines: list[str] = []
    lines.append(f"Comparing {_label(left)}  ↔  {_label(right)}")
    lines.append("")

    # Header — names and bases side by side so the reader sees
    # immediately if the two charms are for different workloads or
    # different Ubuntu bases.
    lines.append(f"  name:  {left.charm_name}  vs  {right.charm_name}")
    if left.base or right.base:
        lines.append(f"  base:  {left.base or '(missing)'}  vs  {right.base or '(missing)'}")
    if left.extensions or right.extensions:
        lines.append(
            "  extensions: "
            f"{sorted(left.extensions) or '(none)'}  vs  "
            f"{sorted(right.extensions) or '(none)'}"
        )
    lines.append("")

    _render_set_section(lines, "Structure", report.structure, singular="file/directory")
    _render_dict_section(
        lines,
        "Config options",
        report.config,
        left.config_options,
        right.config_options,
        singular="option",
    )
    _render_dict_section(
        lines, "provides", report.provides, left.provides, right.provides, singular="endpoint"
    )
    _render_dict_section(
        lines, "requires", report.requires, left.requires, right.requires, singular="endpoint"
    )
    _render_dict_section(
        lines, "peers", report.peers, left.peers, right.peers, singular="endpoint"
    )
    _render_set_section(lines, "Actions", report.actions, singular="action")
    _render_set_section(lines, "Containers", report.containers, singular="container")

    # Test counts — emit even when identical because "both zero" is
    # itself a finding worth flagging.
    lines.append("Tests")
    lines.append(
        f"  unit:        {left.unit_test_count:>4} (left)  vs  {right.unit_test_count:>4} (right)"
    )
    lines.append(
        f"  integration: {left.integration_test_count:>4} (left)  vs  "
        f"{right.integration_test_count:>4} (right)"
    )
    lines.append("")

    return "\n".join(lines)


def _label(snap: CharmSnapshot) -> str:
    """Short display label for a snapshot — name + path so the reader can orient."""
    return f"{snap.charm_name} ({snap.path})"


def _render_set_section(lines: list[str], title: str, diff: DictDiff, *, singular: str) -> None:
    """Append a title + added/removed/changed block for a set-based diff."""
    lines.append(title)
    if not diff.added and not diff.removed:
        lines.append(f"  (identical — same {singular} set)")
        lines.append("")
        return
    if diff.removed:
        lines.append(f"  only in left:  {', '.join(diff.removed)}")
    if diff.added:
        lines.append(f"  only in right: {', '.join(diff.added)}")
    lines.append("")


def _render_dict_section(
    lines: list[str],
    title: str,
    diff: DictDiff,
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    singular: str,
) -> None:
    """Append a title + added/removed/changed block for a dict-based diff.

    For ``changed`` keys, includes the differing values so the reader
    can see the nature of the drift (e.g. one charm uses
    ``interface: http`` and the other uses ``interface: ingress``).
    """
    lines.append(title)
    if not diff.added and not diff.removed and not diff.changed:
        lines.append(f"  (identical — same {singular}s, same values)")
        lines.append("")
        return
    if diff.removed:
        lines.append(f"  only in left:  {', '.join(diff.removed)}")
    if diff.added:
        lines.append(f"  only in right: {', '.join(diff.added)}")
    for key in diff.changed:
        lines.append(f"  changed: {key}")
        lines.append(f"    left:  {left[key]!r}")
        lines.append(f"    right: {right[key]!r}")
    lines.append("")
