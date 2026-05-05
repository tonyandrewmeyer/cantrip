"""Generate metadata files for a charm from ``charmcraft.yaml``."""

import datetime
import pathlib
import platform
import shutil
from typing import Any

import yaml

import quickpack

# Maps ``platform.machine()`` values to Juju architecture labels.
_MACHINE_TO_ARCH: dict[str, str] = {
    "x86_64": "amd64",
    "arm64": "arm64",
    "aarch64": "arm64",
    "armv7l": "armhf",
    "ppc64le": "ppc64el",
    "s390x": "s390x",
    "riscv64": "riscv64",
}


def local_arch() -> str:
    """Return the Juju architecture label for the current machine."""
    machine = platform.machine()
    try:
        return _MACHINE_TO_ARCH[machine]
    except KeyError:
        raise RuntimeError(f"Unsupported architecture: {machine}") from None


def parse_charmcraft_yaml(charm_dir: pathlib.Path) -> dict[str, Any]:
    """Load and return the parsed ``charmcraft.yaml``.

    If the ``name`` field is missing, it is inferred from the directory
    name (matching charmcraft's behaviour).
    """
    path = charm_dir / "charmcraft.yaml"
    if not path.exists():
        raise FileNotFoundError(f"charmcraft.yaml not found in {charm_dir}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("charmcraft.yaml must be a YAML mapping")
    if "name" not in data:
        data["name"] = charm_dir.name
    return data


def resolve_base(project: dict[str, Any]) -> tuple[str, str]:
    """Determine the (distro, series) base from the project config.

    Returns e.g. ``("ubuntu", "24.04")``.
    """
    # Modern ``base:`` field (e.g. ``base: "ubuntu@24.04"``).
    if (base_str := project.get("base")) and "@" in base_str:
        distro, series = base_str.split("@", 1)
        return distro, series

    # ``platforms:`` keys (e.g. ``ubuntu@24.04:amd64``).
    if platforms := project.get("platforms"):
        for key in platforms:
            if "@" in str(key):
                label = str(key).split(":")[0]  # Strip arch suffix.
                distro, series = label.split("@", 1)
                return distro, series

    # Legacy ``bases:`` format.
    if bases := project.get("bases"):
        for base_entry in bases:
            for run_on in base_entry.get("run-on", []):
                name = run_on.get("name", "ubuntu")
                channel = str(run_on.get("channel", "24.04"))
                return name, channel

    return "ubuntu", "24.04"


def resolve_entrypoint(project: dict[str, Any]) -> str:
    """Determine the charm entrypoint from the parts config."""
    for part in (project.get("parts") or {}).values():
        if ep := part.get("charm-entrypoint"):
            return ep
    return "src/charm.py"


def _validate_entrypoint(entrypoint: str, charm_dir: pathlib.Path) -> None:
    """Reject entrypoints the dispatch script could not safely launch.

    The entrypoint is interpolated into a generated POSIX shell script
    and is also the path the charm's process actually executes — so it
    must be a relative file that lives inside the charm tree, with no
    parent traversal and no shell-hostile characters.  Catching these
    cases at pack time turns a delayed deploy-time hook failure into a
    crisp build error.
    """
    if not isinstance(entrypoint, str):
        raise ValueError(f"charm-entrypoint must be a string, got {type(entrypoint).__name__}")
    if not entrypoint:
        raise ValueError("charm-entrypoint must not be empty")

    # Reject characters that would break the dispatch script's exec
    # line or smuggle additional commands.  Newlines, NULs, and quotes
    # are all immediate hazards; backslashes get rejected because we
    # do not want to reason about shell quoting at runtime.
    forbidden = set("\n\r\0\"'`\\$")
    bad = sorted(forbidden.intersection(entrypoint))
    if bad:
        raise ValueError(f"charm-entrypoint contains forbidden characters: {bad}")

    candidate = pathlib.PurePosixPath(entrypoint)
    if candidate.is_absolute():
        raise ValueError(f"charm-entrypoint must be relative, got {entrypoint!r}")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"charm-entrypoint must stay inside the charm tree, got {entrypoint!r}")

    full = (charm_dir / entrypoint).resolve()
    try:
        full.relative_to(charm_dir.resolve())
    except ValueError as exc:
        raise ValueError(
            f"charm-entrypoint resolves outside the charm directory: {entrypoint!r}"
        ) from exc

    if not full.is_file():
        raise FileNotFoundError(f"charm-entrypoint points to a missing file: {entrypoint!r}")


def validate_project(project: dict[str, Any], charm_dir: pathlib.Path) -> None:
    """Validate the charmcraft.yaml fields the pack path depends on.

    Run before any heavy work so malformed metadata fails fast with a
    targeted message instead of triggering a confusing failure deep in
    parts processing or zip assembly.
    """
    name = project.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("charmcraft.yaml: 'name' must be a non-empty string")

    parts = project.get("parts")
    if parts is not None and not isinstance(parts, dict):
        raise ValueError("charmcraft.yaml: 'parts' must be a mapping when set")

    _validate_entrypoint(resolve_entrypoint(project), charm_dir)


# Maps the Ubuntu series to the system-supplied CPython on that LTS.
# Used to pick the build venv's Python version so the resulting
# ``venv/lib/pythonX.Y`` directory matches what the unit's ``python3``
# will read at runtime.  Out-of-range or unknown series fall back to
# whatever Python the build host's ``python3`` resolves to — which is
# the historical behaviour, so existing quickpack runs that happened
# to match the host Python don't change.
_UBUNTU_PYTHON: dict[str, str] = {
    "20.04": "3.8",
    "22.04": "3.10",
    "24.04": "3.12",
    "24.10": "3.12",
    "25.04": "3.13",
    "26.04": "3.14",
}


def resolve_target_python(project: dict[str, Any]) -> str | None:
    """Return the CPython version label the unit will run, or ``None``.

    Reads the (optional) ``build-base`` field first, since that's the
    series the charm code is actually compiled and packed against; the
    runtime ``base`` falls through when ``build-base`` is omitted.
    Returns a string like ``"3.12"`` suitable for ``uv venv --python``,
    or ``None`` when the series is unknown so callers can fall back to
    the host's default.
    """
    build_base = str(project.get("build-base") or "").strip()
    if "@" in build_base:
        _, _, series = build_base.partition("@")
        if series in _UBUNTU_PYTHON:
            return _UBUNTU_PYTHON[series]

    distro, series = resolve_base(project)
    if distro != "ubuntu":
        return None
    return _UBUNTU_PYTHON.get(series)


def generate_metadata(project: dict[str, Any]) -> dict[str, Any]:
    """Build the ``metadata.yaml`` content from a parsed ``charmcraft.yaml``.

    Performs the same field renaming and link flattening that charmcraft does.
    """
    metadata: dict[str, Any] = {}

    # Direct-copy fields.
    for key in (
        "name",
        "summary",
        "description",
        "assumes",
        "containers",
        "devices",
        "extra-bindings",
        "peers",
        "provides",
        "requires",
        "resources",
        "storage",
        "subordinate",
        "terms",
    ):
        if key in project:
            metadata[key] = project[key]

    # Rename ``title`` → ``display-name``.
    if "title" in project:
        metadata["display-name"] = project["title"]

    # Flatten ``links`` into top-level metadata fields.
    if links := project.get("links"):
        if "documentation" in links:
            metadata["docs"] = links["documentation"]
        if "contact" in links:
            contact = links["contact"]
            if isinstance(contact, str):
                contact = [contact]
            metadata["maintainers"] = contact
        if "issues" in links:
            metadata["issues"] = links["issues"]
        if "website" in links:
            metadata["website"] = links["website"]
        if "source" in links:
            metadata["source"] = links["source"]

    return metadata


def _detect_language(project: dict[str, Any]) -> str:
    """Detect the charm's primary language from parts config.

    Returns ``"python"`` when a ``uv`` or ``charm`` plugin is used,
    ``"unknown"`` otherwise.
    """
    for part in (project.get("parts") or {}).values():
        if isinstance(part, dict) and part.get("plugin") in ("uv", "charm"):
            return "python"
    return "unknown"


def generate_manifest(
    project: dict[str, Any],
    arch: str | None = None,
) -> dict[str, Any]:
    """Build the ``manifest.yaml`` content."""
    distro, series = resolve_base(project)
    if arch is None:
        arch = local_arch()

    language = _detect_language(project)

    return {
        "charmcraft-version": f"quickpack-{quickpack.__version__}",
        "charmcraft-started-at": datetime.datetime.now(datetime.UTC).isoformat(),
        "bases": [
            {
                "name": distro,
                "channel": series,
                "architectures": [arch],
            },
        ],
        "analysis": {
            "attributes": [
                {"name": "language", "result": language},
                {"name": "framework", "result": "unknown"},
            ],
        },
    }


def _resolve_platform_label(project: dict[str, Any], arch: str) -> str:
    """Determine the platform label for the charm filename.

    Charmcraft uses the platform key directly:
    - ``platforms: {amd64: null}`` → label is ``amd64``
    - ``platforms: {ubuntu@24.04:amd64: null}`` → label is ``ubuntu@24.04-amd64``
      (colon replaced with hyphen)

    When no platform key matches, falls back to ``{base}-{arch}``.
    """
    if platforms := project.get("platforms"):
        for key in platforms:
            key_str = str(key)
            # Platform key that is just the arch name.
            if key_str == arch:
                return arch
            # Platform key that includes the base and arch.
            if key_str.endswith(f":{arch}") or key_str.endswith(f"-{arch}"):
                return key_str.replace(":", "-")
        # Use the first platform key if none matched explicitly.
        first = str(next(iter(platforms)))
        return first.replace(":", "-")

    distro, series = resolve_base(project)
    return f"{distro}@{series}-{arch}"


def charm_filename(project: dict[str, Any], arch: str | None = None) -> str:
    """Return the standard charm filename, e.g. ``myapp_amd64.charm``."""
    name = project["name"]
    if arch is None:
        arch = local_arch()
    label = _resolve_platform_label(project, arch)
    return f"{name}_{label}.charm"


def write_optional_yaml(
    project: dict[str, Any],
    field: str,
    filename: str,
    charm_dir: pathlib.Path,
    prime_dir: pathlib.Path,
) -> None:
    """Write ``actions.yaml`` or ``config.yaml`` into *prime_dir*.

    Prefers copying the source file from *charm_dir* if it exists on disk,
    otherwise generates it from the project dict.
    """
    source = charm_dir / filename
    dest = prime_dir / filename
    if source.is_file():
        shutil.copy2(str(source), str(dest))
    elif field in project and project[field]:
        with dest.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(project[field], fh, default_flow_style=False)
