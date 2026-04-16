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


def generate_manifest(
    project: dict[str, Any],
    arch: str | None = None,
) -> dict[str, Any]:
    """Build the ``manifest.yaml`` content."""
    distro, series = resolve_base(project)
    if arch is None:
        arch = local_arch()

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
        "analysis": {"attributes": []},
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
