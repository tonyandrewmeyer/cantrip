"""Helpers shared by more than one publishing surface.

Keeps the cross-module bits — charm-metadata reading and the Mermaid
architecture-diagram renderer — in one place so the diagram, docs-scaffold,
and design-decision surfaces can import them without reaching into each
other.
"""

import pathlib
import re
from typing import Any

import yaml


def _read_charm_metadata(charm_dir: pathlib.Path) -> dict[str, Any]:
    """Read and return charmcraft.yaml metadata, or empty dict on failure."""
    charmcraft_yaml = charm_dir / "charmcraft.yaml"
    if not charmcraft_yaml.exists():
        return {}
    try:
        data = yaml.safe_load(charmcraft_yaml.read_text(errors="replace"))
        return data if isinstance(data, dict) else {}
    except (yaml.YAMLError, RecursionError):
        return {}


def _mermaid_id(name: str) -> str:
    """Convert a name to a valid Mermaid node ID."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def generate_architecture_diagram(
    charm_name: str,
    metadata: dict[str, Any],
) -> str:
    """Generate a Mermaid architecture diagram from charm metadata.

    Shows the charm as a central node with its requires, provides, and
    peer relations as connected entities.  Containers (for K8s charms)
    appear as internal components.
    """
    lines: list[str] = ["graph LR"]

    # Central charm node.
    charm_id = _mermaid_id(charm_name)
    display = metadata.get("display-name", charm_name)
    lines.append(f"    {charm_id}[{display}]")

    # Containers (K8s charms).
    containers = metadata.get("containers", {})
    if containers:
        lines.append(f"    subgraph {charm_id}_containers[Containers]")
        for ctr_name in containers:
            ctr_id = _mermaid_id(f"ctr_{ctr_name}")
            lines.append(f"        {ctr_id}[/{ctr_name}/]")
        lines.append("    end")
        lines.append(f"    {charm_id} --- {charm_id}_containers")

    # Requires relations.
    requires = metadata.get("requires", {})
    for rel_name, rel_data in requires.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        provider_id = _mermaid_id(f"req_{rel_name}")
        label = f"{rel_name}\\n({iface})" if iface else rel_name
        lines.append(f"    {provider_id}({rel_name} provider) -- {label} --> {charm_id}")

    # Provides relations.
    provides = metadata.get("provides", {})
    for rel_name, rel_data in provides.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        requirer_id = _mermaid_id(f"prov_{rel_name}")
        label = f"{rel_name}\\n({iface})" if iface else rel_name
        lines.append(f"    {charm_id} -- {label} --> {requirer_id}({rel_name} requirer)")

    # Peers relations.
    peers = metadata.get("peers", {})
    for rel_name, rel_data in peers.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        peer_id = _mermaid_id(f"peer_{rel_name}")
        label = f"{rel_name}\\n({iface})" if iface else rel_name
        lines.append(f"    {charm_id} <-- {label} --> {peer_id}({rel_name} peer)")

    return "\n".join(lines) + "\n"
