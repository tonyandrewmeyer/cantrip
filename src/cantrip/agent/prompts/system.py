"""System prompt for the Cantrip agent."""

from pathlib import Path

import jinja2

_TEMPLATE_DIR = Path(__file__).parent
_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)
_SYSTEM_TEMPLATE = _ENV.get_template("system.md.j2")

# Pre-rendered default prompt (no context injected).
SYSTEM_PROMPT = _SYSTEM_TEMPLATE.render(
    charm_name=None,
    charm_path=None,
    charm_type=None,
    framework=None,
    dev_model=None,
    cos_model=None,
    recent_decisions=None,
    skills_index=None,
    environment_ready=None,
)


def build_system_prompt(
    charm_name: str | None = None,
    charm_path: str | None = None,
    charm_type: str | None = None,
    framework: str | None = None,
    dev_model: str | None = None,
    cos_model: str | None = None,
    recent_decisions: list[dict] | None = None,
    skills_index: str | None = None,
    environment_ready: bool | None = None,
) -> str:
    """Build the full system prompt with current context.

    Args:
        charm_name: Name of the current charm project.
        charm_path: Path to the charm directory.
        charm_type: Type of charm (machine or k8s).
        framework: Detected framework (flask, django, etc.).
        dev_model: Name of the development Juju model.
        cos_model: Name of the COS Juju model.
        recent_decisions: List of recent decisions made.
        skills_index: Pre-rendered XML listing available skills.
        environment_ready: Whether the dev environment is fully provisioned.

    Returns:
        Complete system prompt with context.
    """
    return _SYSTEM_TEMPLATE.render(
        charm_name=charm_name,
        charm_path=charm_path,
        charm_type=charm_type,
        framework=framework,
        dev_model=dev_model,
        cos_model=cos_model,
        recent_decisions=recent_decisions,
        skills_index=skills_index,
        environment_ready=environment_ready,
    )
