"""Juju status parsing and display."""

from dataclasses import dataclass, field


@dataclass
class UnitStatus:
    """Status of a single unit."""

    name: str
    workload_status: str
    workload_message: str
    agent_status: str
    address: str | None = None
    ports: list[str] = field(default_factory=list)


@dataclass
class AppStatus:
    """Status of an application."""

    name: str
    charm: str
    status: str
    message: str
    units: list[UnitStatus] = field(default_factory=list)
    relations: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ModelStatus:
    """Status of a Juju model."""

    name: str
    cloud: str
    region: str | None
    controller: str
    apps: list[AppStatus] = field(default_factory=list)


def parse_status_json(data: dict) -> ModelStatus:
    """Parse juju status --format=json output."""
    apps = []
    for app_name, app_data in data.get("applications", {}).items():
        units = []
        for unit_name, unit_data in app_data.get("units", {}).items():
            units.append(
                UnitStatus(
                    name=unit_name,
                    workload_status=unit_data.get("workload-status", {}).get("current", "unknown"),
                    workload_message=unit_data.get("workload-status", {}).get("message", ""),
                    agent_status=unit_data.get("juju-status", {}).get("current", "unknown"),
                    address=unit_data.get("address"),
                    ports=unit_data.get("open-ports", []),
                )
            )

        relations = {}
        for rel_name, rel_data in app_data.get("relations", {}).items():
            relations[rel_name] = rel_data if isinstance(rel_data, list) else [rel_data]

        apps.append(
            AppStatus(
                name=app_name,
                charm=app_data.get("charm", ""),
                status=app_data.get("application-status", {}).get("current", "unknown"),
                message=app_data.get("application-status", {}).get("message", ""),
                units=units,
                relations=relations,
            )
        )

    model_data = data.get("model", {})
    return ModelStatus(
        name=model_data.get("name", "unknown"),
        cloud=model_data.get("cloud", "unknown"),
        region=model_data.get("region"),
        controller=model_data.get("controller", "unknown"),
        apps=apps,
    )
